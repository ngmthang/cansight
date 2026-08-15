"""
Run with: python3 tests/test_webapp.py
"""

import sys
import os
import json
import tempfile
import io
import zipfile

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webapp",
    ),
)

from geometry.capture_ingestion import write_bundle
import random


def _make_client():
    import webapp.server as server_module

    server_module.app.testing = True
    # reset state between tests
    server_module._state["model"] = None
    server_module._state["queue"] = None
    return server_module.app.test_client()


def _make_lidar_bundle_dir(tmpdir):
    random.seed(9)
    points_arkit = []
    for a, b in [
        ((0, 0), (5, 0)),
        ((5, 0), (5, 4)),
        ((5, 4), (0, 4)),
        ((0, 4), (0, 0)),
    ]:
        points_arkit += [
            (
                a[0] + t * (b[0] - a[0]) + random.uniform(-0.01, 0.01),
                random.uniform(0, 2.4),
                a[1] + t * (b[1] - a[1]) + random.uniform(-0.01, 0.01),
            )
            for t in [random.uniform(0, 1) for _ in range(150)]
        ]
    bundle_dir = os.path.join(tmpdir, "bundle")
    write_bundle(bundle_dir, "s", "iPhone 15 Pro", "t", points_arkit)
    return bundle_dir


def test_no_model_loaded_initially():
    client = _make_client()
    resp = client.get("/api/model")
    assert resp.status_code == 200
    assert resp.get_json()["loaded"] is False


def test_load_bundle_and_get_model():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        resp = client.post(
            "/api/load_bundle", json={"bundle_dir": bundle_dir}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["loaded"] is True
        assert len(data["walls"]) > 0
        assert data["validation_errors"] == []


def test_load_bundle_missing_dir_returns_error():
    client = _make_client()
    resp = client.post(
        "/api/load_bundle", json={"bundle_dir": "/nonexistent/path"}
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_review_next_returns_lowest_confidence_item():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        client.post("/api/load_bundle", json={"bundle_dir": bundle_dir})

    resp = client.get("/api/review/next")
    assert resp.status_code == 200
    item = resp.get_json()["item"]
    assert item is not None
    assert "display_text" in item
    assert item["type"] in ("wall", "door", "window", "room")


def test_approve_removes_item_from_queue():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        client.post("/api/load_bundle", json={"bundle_dir": bundle_dir})

    first = client.get("/api/review/next").get_json()["item"]
    client.post(
        "/api/review/approve", json={"object_id": first["object_id"]}
    )
    second = client.get("/api/review/next").get_json()["item"]
    assert second["object_id"] != first["object_id"]


def test_correct_wall_via_api():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        model_data = client.post(
            "/api/load_bundle", json={"bundle_dir": bundle_dir}
        ).get_json()

    wall_id = model_data["walls"][0]["id"]
    resp = client.post(
        "/api/review/correct_wall",
        json={
            "object_id": wall_id,
            "field": "thickness",
            "value_text": "6\"",
            "unit_system": "us",
        },
    )
    assert resp.status_code == 200

    updated = client.get("/api/model").get_json()
    updated_wall = next(
        w for w in updated["walls"] if w["id"] == wall_id
    )
    assert updated_wall["confidence"] == 1.0


def test_add_wall_via_api():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        client.post("/api/load_bundle", json={"bundle_dir": bundle_dir})

    resp = client.post(
        "/api/review/add_wall",
        json={"start": [10.0, 10.0], "end": [15.0, 10.0]},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "wall_id" in data

    updated = client.get("/api/model").get_json()
    ids = [w["id"] for w in updated["walls"]]
    assert data["wall_id"] in ids


def test_add_wall_closes_gap_end_to_end():
    """The real scenario this UI exists for: 3 auto-detected walls,
    1 missing (furniture occlusion), manually add it, re-extract
    rooms, confirm a room now exists."""
    client = _make_client()
    import webapp.server as server_module
    from building_model.schema import BuildingModel
    from review.correction_session import build_review_queue

    bm = BuildingModel(building_id="gap_test")
    bm.add_level("L1")
    bm.add_wall("L1", ((0, 0), (5, 0)), confidence=0.4)
    bm.add_wall("L1", ((5, 0), (5, 4)), confidence=0.4)
    bm.add_wall("L1", ((5, 4), (0, 4)), confidence=0.4)
    server_module._state["model"] = bm
    server_module._state["queue"] = build_review_queue(bm)

    resp = client.post(
        "/api/review/add_wall",
        json={"start": [0, 4], "end": [0, 0]},
    )
    assert resp.status_code == 200

    resp = client.post("/api/reextract_rooms")
    data = resp.get_json()
    assert len(data["rooms"]) == 1
    boundary = data["rooms"][0]["boundary"]
    assert len(boundary) == 4  # the 4-corner room from the walls above


def test_export_ifc_via_api():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        client.post("/api/load_bundle", json={"bundle_dir": bundle_dir})

    resp = client.post("/api/export_ifc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert os.path.exists(data["path"])


def test_operations_before_load_return_error():
    client = _make_client()
    resp = client.get("/api/review/next")
    assert resp.status_code == 400


def _zip_bundle(bundle_dir, nested_folder_name=None):
    """Zips a bundle directory's manifest/points/planes files,
    optionally wrapping them in a nested folder to simulate the
    common real-world case (zipping a folder via Finder/Explorer/
    Files app often adds an extra wrapping directory)."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        for fname in os.listdir(bundle_dir):
            arcname = (
                f"{nested_folder_name}/{fname}"
                if nested_folder_name
                else fname
            )
            zf.write(os.path.join(bundle_dir, fname), arcname)
    zip_buf.seek(0)
    return zip_buf


def test_upload_bundle_flat_zip():
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        zip_buf = _zip_bundle(bundle_dir)

    resp = client.post(
        "/api/upload_bundle",
        data={"bundle_zip": (zip_buf, "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["loaded"] is True
    assert len(data["walls"]) > 0


def test_upload_bundle_nested_folder_zip():
    """The common real-world case: the zip wraps its contents in a
    folder (e.g. zipping a folder via a file manager)."""
    client = _make_client()
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = _make_lidar_bundle_dir(tmpdir)
        zip_buf = _zip_bundle(bundle_dir, nested_folder_name="my_scan")

    resp = client.post(
        "/api/upload_bundle",
        data={"bundle_zip": (zip_buf, "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json()["loaded"] is True


def test_upload_bundle_rejects_zip_slip():
    client = _make_client()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("../../evil.txt", "malicious content")
    zip_buf.seek(0)

    resp = client.post(
        "/api/upload_bundle",
        data={"bundle_zip": (zip_buf, "evil.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "unsafe path" in resp.get_json()["error"]


def test_upload_bundle_rejects_invalid_zip():
    client = _make_client()
    resp = client.post(
        "/api/upload_bundle",
        data={"bundle_zip": (io.BytesIO(b"not a zip"), "fake.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "not a valid zip" in resp.get_json()["error"]


def test_upload_bundle_requires_file():
    client = _make_client()
    resp = client.post(
        "/api/upload_bundle",
        data={},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


if __name__ == "__main__":
    tests = [
        v for k, v in list(globals().items()) if k.startswith("test_")
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")