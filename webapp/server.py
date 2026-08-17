"""
Local review/correction web app -- a real interface on top of the
existing, already-tested backend (building_model/, geometry/,
review/). This file adds no new domain logic; it's a thin HTTP
layer that calls the same functions the test suite already
exercises (build_review_queue, correct_wall_dimension,
add_manual_wall, etc.).

Single-user, local-only, in-memory state -- this is a development
tool for reviewing one capture at a time, not a multi-tenant
server. The V1 spec's actual server architecture (Section 14) is a
separate, later concern (see docs/BACKLOG.md).

Run with: python3 webapp/server.py
Then open: http://127.0.0.1:5000
"""

from __future__ import annotations
import sys
import os
import zipfile
import uuid

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from flask import Flask, jsonify, request, render_template

from building_model.schema import (
    BuildingModel,
    Wall,
    Door,
    Window,
    Room,
)
from review.queue import ReviewQueue
from review.correction_session import (
    build_review_queue,
    build_review_queue_with_resolved,
    next_review_item,
    approve,
    correct_wall_dimension,
    correct_opening_dimension,
    reclassify_room,
    add_manual_wall,
)
from review.formatting import format_object
from geometry.capture_ingestion import (
    ingest_capture,
    build_building_model_from_capture,
)
from geometry.room_extraction import extract_rooms
import webapp.storage as storage
from export.ifc_export import export_to_ifc
from export.dxf_export import export_to_dxf

app = Flask(__name__)

_DB_PATH = os.environ.get(
    "WEBAPP_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webapp_data.db",
    ),
)
storage.init_db(_DB_PATH)

# --- In-memory session state (single user, local tool) ---
# Persisted to SQLite after every mutation via _persist_current_state()
# so the active project survives a server restart -- see
# webapp/storage.py and docs/PROJECT_STATUS.md Section 6.
_state = {
    "model": None,  # BuildingModel | None
    "queue": None,  # ReviewQueue | None
    "project_id": None,  # str | None
}


def _persist_current_state() -> None:
    if _state["model"] is not None and _state["project_id"] is not None:
        storage.save_project(
            _DB_PATH,
            _state["project_id"],
            _state["model"],
            _state["queue"].resolved_ids(),
        )


def _require_model() -> BuildingModel:
    if _state["model"] is None:
        raise RuntimeError("No model loaded yet")
    return _state["model"]


def _wall_endpoint_position(wall: Wall, position_on_wall: float):
    (x0, y0), (x1, y1) = wall.centerline
    return (
        x0 + position_on_wall * (x1 - x0),
        y0 + position_on_wall * (y1 - y0),
    )


def _serialize_model(model: BuildingModel) -> dict:
    """Turns the internal BuildingModel into a JSON-friendly shape
    the frontend can render directly -- walls as line segments,
    rooms as boundary polygons, doors/windows as points along their
    host wall, everything tagged with confidence and a display
    string via review/formatting.py so the UI never needs its own
    copy of unit-conversion or formatting logic."""
    walls, rooms, doors, windows = [], [], [], []

    for obj in model.objects.values():
        entry = {
            "id": obj.id,
            "confidence": obj.confidence,
            "detection_method": obj.provenance.detection_method,
            "label": format_object(obj, unit_system="us"),
        }
        if isinstance(obj, Wall):
            entry["centerline"] = obj.centerline
            walls.append(entry)
        elif isinstance(obj, Room):
            entry["boundary"] = obj.boundary
            entry["classification"] = obj.classification
            rooms.append(entry)
        elif isinstance(obj, Door):
            wall = model.objects.get(obj.host_wall_id)
            if wall is not None:
                entry["position"] = _wall_endpoint_position(
                    wall, obj.position_on_wall
                )
                entry["host_wall_id"] = obj.host_wall_id
                doors.append(entry)
        elif isinstance(obj, Window):
            wall = model.objects.get(obj.host_wall_id)
            if wall is not None:
                entry["position"] = _wall_endpoint_position(
                    wall, obj.position_on_wall
                )
                entry["host_wall_id"] = obj.host_wall_id
                windows.append(entry)

    return {
        "building_id": model.building_id,
        "walls": walls,
        "rooms": rooms,
        "doors": doors,
        "windows": windows,
        "validation_errors": model.validate(),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/model", methods=["GET"])
def get_model():
    if _state["model"] is None:
        return jsonify({"loaded": False})
    payload = _serialize_model(_state["model"])
    payload["loaded"] = True
    payload["project_id"] = _state["project_id"]
    payload["remaining_review_count"] = _state[
        "queue"
    ].remaining_count()
    return jsonify(payload)


@app.route("/api/load_bundle", methods=["POST"])
def load_bundle_route():
    data = request.get_json(force=True)
    bundle_dir = data.get("bundle_dir")
    if not bundle_dir or not os.path.isdir(bundle_dir):
        return (
            jsonify({"error": f"bundle_dir not found: {bundle_dir!r}"}),
            400,
        )

    try:
        result = ingest_capture(bundle_dir)
        model = build_building_model_from_capture(
            result, building_id=os.path.basename(bundle_dir)
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    _state["model"] = model
    _state["queue"] = build_review_queue(model)
    _state["project_id"] = uuid.uuid4().hex
    _persist_current_state()
    payload = _serialize_model(model)
    payload["loaded"] = True
    payload["capture_method"] = result.capture_method
    payload["project_id"] = _state["project_id"]
    return jsonify(payload)


_UPLOAD_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "webapp_uploads",
)


def _safe_extract_zip(zip_path: str, extract_dir: str) -> None:
    """Extracts a zip, rejecting any member whose path would escape
    extract_dir (a "zip slip" attack -- a malicious zip entry named
    e.g. "../../etc/passwd" that writes outside the intended
    directory). Necessary any time zip contents come from an
    untrusted upload, which this endpoint's input is."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        normalized_root = os.path.normpath(extract_dir)
        for member in zf.namelist():
            member_path = os.path.normpath(
                os.path.join(extract_dir, member)
            )
            is_inside_root = member_path == normalized_root or (
                member_path.startswith(normalized_root + os.sep)
            )
            if not is_inside_root:
                raise ValueError(f"unsafe path in zip: {member!r}")
        zf.extractall(extract_dir)


def _find_bundle_dir(root_dir: str) -> str | None:
    """The uploaded zip might contain manifest.json directly at its
    root, or nested one level inside a folder (the common case when
    someone zips a folder via Finder/Explorer/Files app, which often
    wraps it in a folder matching the zip's name). Walk the extracted
    tree and use whichever directory actually contains manifest.json."""
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        if "manifest.json" in filenames:
            return dirpath
    return None


@app.route("/api/upload_bundle", methods=["POST"])
def upload_bundle_route():
    """Accepts a zipped capture bundle via multipart upload -- the
    fix for load_bundle_route's real limitation: it requires the
    Flask process to already have local filesystem access to the
    bundle, which breaks the moment the web UI isn't running on the
    same machine the bundle was transferred to (see
    docs/PROJECT_STATUS.md Section 5)."""
    if "bundle_zip" not in request.files:
        return (
            jsonify(
                {
                    "error": (
                        "no file uploaded "
                        "(expected field 'bundle_zip')"
                    )
                }
            ),
            400,
        )
    file = request.files["bundle_zip"]
    if file.filename == "":
        return jsonify({"error": "empty filename"}), 400

    upload_id = uuid.uuid4().hex
    extract_dir = os.path.join(_UPLOAD_ROOT, upload_id)
    os.makedirs(extract_dir, exist_ok=True)
    zip_path = os.path.join(extract_dir, "upload.zip")
    file.save(zip_path)

    try:
        _safe_extract_zip(zip_path, extract_dir)
    except zipfile.BadZipFile:
        return (
            jsonify({"error": "uploaded file is not a valid zip"}),
            400,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    bundle_dir = _find_bundle_dir(extract_dir)
    if bundle_dir is None:
        return (
            jsonify(
                {"error": "no manifest.json found in uploaded zip"}
            ),
            400,
        )

    try:
        result = ingest_capture(bundle_dir)
        model = build_building_model_from_capture(
            result, building_id=upload_id[:8]
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    _state["model"] = model
    _state["queue"] = build_review_queue(model)
    _state["project_id"] = upload_id
    _persist_current_state()
    payload = _serialize_model(model)
    payload["loaded"] = True
    payload["capture_method"] = result.capture_method
    payload["project_id"] = _state["project_id"]
    return jsonify(payload)


@app.route("/api/projects", methods=["GET"])
def list_projects_route():
    projects = storage.list_projects(_DB_PATH)
    return jsonify(
        {
            "projects": [
                {
                    "project_id": p.project_id,
                    "building_id": p.building_id,
                    "updated_at": p.updated_at,
                    "active": p.project_id == _state["project_id"],
                }
                for p in projects
            ]
        }
    )


@app.route("/api/projects/<project_id>/activate", methods=["POST"])
def activate_project_route(project_id):
    """Resumes a previously saved project -- the actual 'survive a
    restart' path. Loading a new bundle (load_bundle_route /
    upload_bundle_route) always starts a fresh project instead;
    this endpoint is for coming back to earlier work."""
    result = storage.load_project(_DB_PATH, project_id)
    if result is None:
        return (
            jsonify({"error": f"project not found: {project_id!r}"}),
            404,
        )

    model, resolved_ids = result
    _state["model"] = model
    _state["queue"] = build_review_queue_with_resolved(
        model, resolved_ids
    )
    _state["project_id"] = project_id

    payload = _serialize_model(model)
    payload["loaded"] = True
    payload["project_id"] = project_id
    return jsonify(payload)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project_route(project_id):
    storage.delete_project(_DB_PATH, project_id)
    if _state["project_id"] == project_id:
        _state["model"] = None
        _state["queue"] = None
        _state["project_id"] = None
    return jsonify({"ok": True})


@app.route("/api/review/next", methods=["GET"])
def review_next():
    try:
        model, queue = _require_model(), _state["queue"]
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    item = next_review_item(model, queue, unit_system="us")
    if item is None:
        return jsonify({"item": None})
    obj = model.objects[item.object_id]
    return jsonify(
        {
            "item": {
                "object_id": item.object_id,
                "display_text": item.display_text,
                "remaining_count": item.remaining_count,
                "type": obj.type.value,
            }
        }
    )


@app.route("/api/review/approve", methods=["POST"])
def review_approve():
    model, queue = _require_model(), _state["queue"]
    object_id = request.get_json(force=True)["object_id"]
    if object_id not in model.objects:
        return (
            jsonify({"error": f"unknown object_id {object_id!r}"}),
            404,
        )
    approve(model, queue, object_id)
    _persist_current_state()
    return jsonify({"ok": True})


@app.route("/api/review/correct_wall", methods=["POST"])
def review_correct_wall():
    model, queue = _require_model(), _state["queue"]
    data = request.get_json(force=True)
    try:
        correct_wall_dimension(
            model,
            queue,
            data["object_id"],
            data["field"],
            data["value_text"],
            unit_system=data.get("unit_system", "us"),
        )
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    _persist_current_state()
    return jsonify({"ok": True})


@app.route("/api/review/correct_opening", methods=["POST"])
def review_correct_opening():
    model, queue = _require_model(), _state["queue"]
    data = request.get_json(force=True)
    try:
        correct_opening_dimension(
            model,
            queue,
            data["object_id"],
            data["field"],
            data["value_text"],
            unit_system=data.get("unit_system", "us"),
        )
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    _persist_current_state()
    return jsonify({"ok": True})


@app.route("/api/review/reclassify_room", methods=["POST"])
def review_reclassify_room():
    model, queue = _require_model(), _state["queue"]
    data = request.get_json(force=True)
    try:
        reclassify_room(
            model, queue, data["object_id"], data["classification"]
        )
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    _persist_current_state()
    return jsonify({"ok": True})


@app.route("/api/review/add_wall", methods=["POST"])
def review_add_wall():
    """The feature this whole UI exists to make usable: click two
    points on the floor plan to draw in a wall the pipeline missed
    (e.g. one occluded by furniture -- see docs/BACKLOG.md)."""
    model, queue = _require_model(), _state["queue"]
    data = request.get_json(force=True)
    try:
        level = next(iter(model.levels.keys()))
        centerline = (tuple(data["start"]), tuple(data["end"]))
        new_id = add_manual_wall(model, queue, level, centerline)
    except (ValueError, KeyError, StopIteration) as e:
        return jsonify({"error": str(e)}), 400
    _persist_current_state()
    return jsonify({"ok": True, "wall_id": new_id})


@app.route("/api/reextract_rooms", methods=["POST"])
def reextract_rooms():
    """After adding/editing walls, room boundaries may have changed
    (e.g. a manually-added wall just closed a gap). Recomputes rooms
    from the current wall set and replaces the model's room objects."""
    model = _require_model()
    level = next(iter(model.levels.keys()))

    wall_ids = model.levels[level].walls
    segments = [model.objects[wid].centerline for wid in wall_ids]
    new_boundaries = extract_rooms(segments)

    old_room_ids = list(model.levels[level].rooms)
    for rid in old_room_ids:
        del model.objects[rid]
    model.levels[level].rooms = []
    model.relationships = [
        r for r in model.relationships if r.from_id not in old_room_ids
    ]

    for boundary in new_boundaries:
        model.add_room(
            level,
            boundary,
            bounded_by=wall_ids,
            classification="unclassified",
            confidence=0.7,
        )

    payload = _serialize_model(model)
    payload["loaded"] = True
    _persist_current_state()
    return jsonify(payload)


@app.route("/api/export_ifc", methods=["POST"])
def export_ifc_route():
    model = _require_model()
    errors = model.validate()
    if errors:
        return (
            jsonify(
                {
                    "error": "Model has validation errors",
                    "details": errors,
                }
            ),
            400,
        )

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webapp_exports",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{model.building_id}.ifc")
    warnings = export_to_ifc(model, out_path)
    return jsonify({"ok": True, "path": out_path, "warnings": warnings})


@app.route("/api/export_dxf", methods=["POST"])
def export_dxf_route():
    """DXF export: AutoCAD's native format, and importable directly
    into SketchUp too (built-in DXF import) -- see
    export/dxf_export.py's module docstring for why one exporter
    covers both targets."""
    model = _require_model()
    errors = model.validate()
    if errors:
        return (
            jsonify(
                {
                    "error": "Model has validation errors",
                    "details": errors,
                }
            ),
            400,
        )

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webapp_exports",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{model.building_id}.dxf")
    warnings = export_to_dxf(model, out_path)
    return jsonify({"ok": True, "path": out_path, "warnings": warnings})


if __name__ == "__main__":
    app.run(debug=True, port=5000)