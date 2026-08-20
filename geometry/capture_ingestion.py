"""
Capture bundle ingestion.

This module defines the CONTRACT between whatever captures raw
sensor data (the iOS app, per docs/ROOMPLAN_SPIKE.md's recommendation
to use raw ARKit capture, not RoomPlan) and this project's geometry
pipeline. Anything that produces a bundle in this format -- a real
iOS app, a test fixture, a different capture device entirely -- can
feed the same pipeline without changes downstream.

Bundle format on disk:

    <bundle_dir>/
        manifest.json       -- metadata (see BundleManifest below)
        points.json          -- the fused point cloud: a JSON array
                                 of [x, y, z] triples, ARKit world
                                 coordinates (Y-up, meters)

This is intentionally a plain, inspectable format for V1 -- not a
compressed binary point-cloud format (e.g. PCD, LAS). Optimizing
bundle size/format is a fast-follow once real capture volume makes
it matter; V1 prioritizes something a human can open and read.

Coordinate conversion: ARKit's world frame is Y-up. This project's
Building Model is Z-up (V1 spec Section 4). This module is the
ONE place that axis conversion happens -- nothing downstream
(plane_detection.py, wall_fitting.py, etc.) needs to know ARKit
coordinates exist at all.
"""

from __future__ import annotations
from dataclasses import dataclass
import json
import os
import math

from geometry.plane_detection import extract_wall_candidates
from geometry.wall_fitting import (
    fit_walls,
    fit_line_total_least_squares,
    FittedWall,
)
from geometry.height_inference import (
    estimate_floor_and_ceiling,
    HeightEstimate,
)
from geometry.room_extraction import extract_rooms
from geometry.opening_detection import (
    GapObservation,
    merge_gaps,
    classify_openings,
)
from building_model.schema import BuildingModel, Provenance

# Confidence formulas per capture method. NON_LIDAR values are
# deliberately capped low -- placeholders pending real-device
# calibration (see docs/ROOMPLAN_SPIKE.md Section 5) -- so that
# non-LiDAR captures always surface near the top of
# review/queue.py's confidence-sorted queue rather than being
# silently treated as equal-quality to LiDAR data.
LIDAR_METHOD = "lidar_ransac_mesh"
NON_LIDAR_METHOD = "arkit_plane_detection_non_lidar"


@dataclass
class BundleManifest:
    session_id: str
    device_model: str
    capture_timestamp: str
    coordinate_frame: str  # expected: "arkit_world_y_up_meters"
    capture_method: str = "lidar_mesh"  # or "arkit_plane_detection"
    point_count: int = 0
    plane_count: int = 0


@dataclass
class IngestedCapture:
    manifest: BundleManifest
    fitted_walls: list[FittedWall]
    height_estimate: HeightEstimate
    capture_method: str


def _arkit_y_up_to_model_z_up(
    points: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """
    ARKit: (x, y, z) with Y up, -Z forward.
    Model frame: (x, y, z) with Z up (V1 spec Section 4).

    The conversion is a simple axis relabel: model_x = arkit_x,
    model_y = -arkit_z, model_z = arkit_y. (Sign on the old Z axis
    keeps the result right-handed.) This does NOT do the
    Manhattan-alignment rotation described in the spec (rotating to
    align with the dominant wall direction) -- that's a separate,
    not-yet-implemented step, deliberately left for when real
    capture data can validate the alignment approach against actual
    building geometry rather than synthetic axis-aligned test data.
    """
    return [(x, -z, y) for (x, y, z) in points]


def load_bundle(bundle_dir: str) -> tuple[BundleManifest, list]:
    """Reads manifest.json + points.json from a bundle directory.
    Returns (manifest, points_in_model_frame)."""
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    points_path = os.path.join(bundle_dir, "points.json")

    with open(manifest_path) as f:
        raw_manifest = json.load(f)

    if (
        raw_manifest.get("coordinate_frame")
        != "arkit_world_y_up_meters"
    ):
        raise ValueError(
            f"Unsupported coordinate_frame in manifest: "
            f"{raw_manifest.get('coordinate_frame')!r}. "
            f"Expected 'arkit_world_y_up_meters'."
        )

    manifest = BundleManifest(
        session_id=raw_manifest["session_id"],
        device_model=raw_manifest["device_model"],
        capture_timestamp=raw_manifest["capture_timestamp"],
        coordinate_frame=raw_manifest["coordinate_frame"],
        capture_method=raw_manifest.get("capture_method", "lidar_mesh"),
        point_count=raw_manifest.get("point_count", 0),
        plane_count=raw_manifest.get("plane_count", 0),
    )

    with open(points_path) as f:
        raw_points = json.load(f)

    points = [(p[0], p[1], p[2]) for p in raw_points]

    if len(points) != manifest.point_count:
        raise ValueError(
            f"manifest.point_count ({manifest.point_count}) doesn't "
            f"match actual points.json length ({len(points)})"
        )

    model_points = _arkit_y_up_to_model_z_up(points)
    return manifest, model_points


def ingest_capture(
    bundle_dir: str,
    ransac_distance_threshold: float = 0.03,
    ransac_min_inliers: int = 20,
    ransac_seed: int | None = None,
) -> IngestedCapture:
    """
    Dispatches on manifest.capture_method:
      "lidar_mesh"           -> RANSAC plane segmentation over a
                                 dense point cloud (plane_detection.py)
      "arkit_plane_detection" -> ARKit's own on-device plane detector
                                 already found the walls; just fit
                                 lines through their sparse boundary
                                 vertices (non-LiDAR fallback devices)

    ransac_seed is None (non-deterministic) by default -- fine for
    real captures. Tests that assert exact wall counts/positions
    should pass a fixed seed, or RANSAC's inherent randomness makes
    the assertion flaky (this was a real bug found during
    development: see tests/test_capture_ingestion.py history).
    """
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    with open(manifest_path) as f:
        raw_manifest = json.load(f)
    capture_method = raw_manifest.get("capture_method", "lidar_mesh")

    if capture_method == "lidar_mesh":
        return _ingest_lidar_mesh_bundle(
            bundle_dir,
            ransac_distance_threshold,
            ransac_min_inliers,
            ransac_seed,
        )
    elif capture_method == "arkit_plane_detection":
        return _ingest_plane_detection_bundle(bundle_dir)
    else:
        raise ValueError(f"Unknown capture_method: {capture_method!r}")


def _ingest_lidar_mesh_bundle(
    bundle_dir: str,
    ransac_distance_threshold: float,
    ransac_min_inliers: int,
    ransac_seed: int | None = None,
) -> IngestedCapture:
    """
    Full ingestion: load a capture bundle from disk, run it through
    plane_detection -> wall_fitting -> height_inference, and return
    the results ready to hand to BuildingModel construction (the same
    role examples/synthetic_house.py's make_noisy_observations() and
    make_noisy_z_samples() play for synthetic data).
    """
    manifest, points = load_bundle(bundle_dir)

    if len(points) < 3:
        raise ValueError(
            f"bundle {manifest.session_id!r} has too few points "
            f"({len(points)}) to run plane detection"
        )

    wall_candidates = extract_wall_candidates(
        points,
        distance_threshold=ransac_distance_threshold,
        min_inliers=ransac_min_inliers,
        seed=ransac_seed,
    )
    if not wall_candidates:
        raise ValueError(
            f"bundle {manifest.session_id!r}: no wall-candidate "
            f"planes detected -- check point cloud density and "
            f"ransac_min_inliers"
        )

    segments = [c.segment for c in wall_candidates]
    fitted_walls = fit_walls(segments)

    all_z_samples = [z for c in wall_candidates for z in c.z_samples]
    height_estimate = estimate_floor_and_ceiling(all_z_samples)

    return IngestedCapture(
        manifest=manifest,
        fitted_walls=fitted_walls,
        height_estimate=height_estimate,
        capture_method=LIDAR_METHOD,
    )


def load_plane_bundle(
    bundle_dir: str,
) -> tuple[BundleManifest, list[dict]]:
    """
    Reads manifest.json + planes.json (the non-LiDAR bundle format)
    from a bundle directory. Returns (manifest, planes_in_model_frame),
    where each plane is {"alignment": "vertical"|"horizontal",
    "boundary_vertices": [(x,y,z), ...]} with vertices already
    converted to the model's Z-up frame.
    """
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    planes_path = os.path.join(bundle_dir, "planes.json")

    with open(manifest_path) as f:
        raw_manifest = json.load(f)

    if (
        raw_manifest.get("coordinate_frame")
        != "arkit_world_y_up_meters"
    ):
        raise ValueError(
            f"Unsupported coordinate_frame in manifest: "
            f"{raw_manifest.get('coordinate_frame')!r}. "
            f"Expected 'arkit_world_y_up_meters'."
        )

    manifest = BundleManifest(
        session_id=raw_manifest["session_id"],
        device_model=raw_manifest["device_model"],
        capture_timestamp=raw_manifest["capture_timestamp"],
        coordinate_frame=raw_manifest["coordinate_frame"],
        capture_method=raw_manifest.get(
            "capture_method", "arkit_plane_detection"
        ),
        point_count=raw_manifest.get("point_count", 0),
        plane_count=raw_manifest.get("plane_count", 0),
    )

    with open(planes_path) as f:
        raw_planes = json.load(f)

    if len(raw_planes) != manifest.plane_count:
        raise ValueError(
            f"manifest.plane_count ({manifest.plane_count}) doesn't "
            f"match actual planes.json length ({len(raw_planes)})"
        )

    planes: list[dict] = []
    for p in raw_planes:
        verts_arkit = [
            (v[0], v[1], v[2]) for v in p["boundary_vertices"]
        ]
        verts_model = _arkit_y_up_to_model_z_up(verts_arkit)
        planes.append(
            {
                "alignment": p["alignment"],
                "boundary_vertices": verts_model,
            }
        )

    return manifest, planes


def _wall_segment_from_vertical_plane(
    boundary_vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Fit a 2D wall segment through a sparse set of boundary vertices --
    only ~4-8 points from ARKit's own plane polygon, not a dense
    point cloud. Reuses wall_fitting.py's total-least-squares line
    fit -- same math used there to average many noisy observations,
    just applied here to the few points a non-LiDAR device's plane
    detector gives us. A vertical plane's corners naturally project
    to just two distinct (x,y) positions (top/bottom pairs share XY),
    which is exactly the degenerate-but-valid case this fit handles
    cleanly.
    """
    xy_points = [(v[0], v[1]) for v in boundary_vertices]
    centroid, direction = fit_line_total_least_squares(xy_points)
    dx, dy = direction
    projections = [
        (p[0] - centroid[0]) * dx + (p[1] - centroid[1]) * dy
        for p in xy_points
    ]
    t_min, t_max = min(projections), max(projections)
    p_start = (centroid[0] + t_min * dx, centroid[1] + t_min * dy)
    p_end = (centroid[0] + t_max * dx, centroid[1] + t_max * dy)
    return (p_start, p_end)


def _ingest_plane_detection_bundle(bundle_dir: str) -> IngestedCapture:
    """
    Non-LiDAR path: ARKit's own vision-based plane detector already
    found the walls (as ARPlaneAnchor polygons) on-device -- there's
    nothing to RANSAC over. Just fit a clean line through each
    vertical plane's sparse boundary, cluster/dedupe via the same
    wall_fitting.fit_walls() the LiDAR path uses, and pool every
    plane's z-extent into height_inference's estimator (with a
    looser density_threshold, since a handful of boundary points
    will rarely clear the LiDAR path's default of 3-per-bin).
    """
    manifest, planes = load_plane_bundle(bundle_dir)

    vertical_planes = [
        p for p in planes if p["alignment"] == "vertical"
    ]
    if not vertical_planes:
        raise ValueError(
            f"bundle {manifest.session_id!r}: no vertical planes "
            f"(walls) detected -- nothing to build a model from"
        )

    # ARKit's ARPlaneAnchor detection is purely geometric -- it has
    # no semantic understanding of what a surface actually is, so
    # any sufficiently flat, sufficiently large vertical object
    # (a monitor screen, a picture frame, a whiteboard) gets
    # reported exactly like a real wall would (confirmed by a real
    # capture session: a monitor screen was detected and visualized
    # as if it were a wall segment). The discriminating signal that
    # actually works: a real wall, however narrow horizontally,
    # spans close to full room height, while a monitor/picture
    # frame/similar object is short regardless of its width.
    # Threshold derived from tests/fixtures/real_ipad_capture_1's
    # real data: every genuine wall segment there spans >= 0.7m
    # vertically; one clear false positive (a likely monitor) spans
    # only 0.267m despite being 0.95m wide.
    MIN_WALL_VERTICAL_EXTENT = 0.5  # meters

    segments = []
    all_z: list[float] = []
    for p in vertical_planes:
        verts = p["boundary_vertices"]
        z_values = [v[2] for v in verts]
        vertical_extent = max(z_values) - min(z_values)
        if vertical_extent < MIN_WALL_VERTICAL_EXTENT:
            continue  # too short to plausibly be a wall segment
        segments.append(_wall_segment_from_vertical_plane(verts))
        all_z.extend(z_values)

    if not segments:
        raise ValueError(
            f"bundle {manifest.session_id!r}: no vertical planes "
            f"tall enough to plausibly be walls (all under "
            f"{MIN_WALL_VERTICAL_EXTENT}m) -- nothing to build a "
            f"model from"
        )

    for p in planes:
        if p["alignment"] == "horizontal":
            all_z.extend(v[2] for v in p["boundary_vertices"])

    fitted_walls = fit_walls(
        segments,
        # Looser than the LiDAR path's defaults (6deg/0.08m):
        # a line fit through only ~4-17 sparse ARKit plane-boundary
        # points has genuinely higher angular noise than a fit
        # through hundreds of dense LiDAR points, so the tighter
        # LiDAR-tuned tolerance leaves near-duplicate detections of
        # the same physical wall unmerged. Calibrated against a real
        # iPad (non-LiDAR) capture -- see docs/ROOMPLAN_SPIKE.md
        # Section 5 for the "needs real-device validation" note this
        # confirms and resolves.
        angle_tol_deg=25.0,
        offset_tol=0.25,
    )
    height_estimate = estimate_floor_and_ceiling(
        all_z, density_threshold=2
    )

    return IngestedCapture(
        manifest=manifest,
        fitted_walls=fitted_walls,
        height_estimate=height_estimate,
        capture_method=NON_LIDAR_METHOD,
    )


def _find_wall_openings(wall: FittedWall) -> list:
    """
    Bridges FittedWall.covered_intervals (per-observation coverage
    along the wall) to opening_detection.py's interval-merge
    algorithm: finds positions along this wall where NO observation
    ever saw material, and classifies each by width into door/
    window/noise/reconstruction_gap/ambiguous. opening_detection.py
    has existed and been tested since early in this project, but
    was never actually wired into the real capture pipeline until
    now -- see docs/PROJECT_STATUS.md.
    """
    (x0, y0), (x1, y1) = wall.centerline
    wall_length = math.hypot(x1 - x0, y1 - y0)
    if wall_length < 1e-6 or not wall.covered_intervals:
        return []

    ordered = sorted(wall.covered_intervals)
    combined = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = combined[-1]
        if start <= last_end:
            combined[-1] = (last_start, max(last_end, end))
        else:
            combined.append((start, end))

    gaps: list[GapObservation] = []
    if combined[0][0] > 0:
        gaps.append(GapObservation(0.0, combined[0][0]))
    for i in range(len(combined) - 1):
        gaps.append(GapObservation(combined[i][1], combined[i + 1][0]))
    if combined[-1][1] < wall_length:
        gaps.append(GapObservation(combined[-1][1], wall_length))

    return classify_openings(merge_gaps(gaps))


def build_building_model_from_capture(
    ingested: IngestedCapture,
    building_id: str,
    level_id: str = "L1",
) -> BuildingModel:
    """
    Assembles a BuildingModel from an IngestedCapture, applying the
    confidence formula appropriate to the capture method. This is
    the ONE place that formula lives -- centralizing it here (rather
    than duplicating it per call site, the way the earlier synthetic
    demo did inline) means the LiDAR-vs-non-LiDAR confidence gap
    can't silently drift out of sync between different callers.
    """
    bm = BuildingModel(building_id=building_id)
    bm.add_level(
        level_id, elevation=ingested.height_estimate.floor_elevation
    )

    is_lidar = ingested.capture_method == LIDAR_METHOD

    wall_ids = []
    for w in ingested.fitted_walls:
        if is_lidar:
            confidence = min(1.0, 0.5 + 0.08 * w.support_count)
        else:
            # capped well below the LiDAR path's ceiling, per the
            # V1 spec's Conceptual-vs-Architectural accuracy tiers
            # (Section 13) -- non-LiDAR captures should never look
            # as trustworthy as LiDAR ones to the review queue
            confidence = min(0.6, 0.3 + 0.05 * w.support_count)

        wall = bm.add_wall(
            level_id,
            w.centerline,
            thickness=0.12,
            height=ingested.height_estimate.height,
            confidence=confidence,
            provenance=Provenance(
                detection_method=ingested.capture_method
            ),
        )
        wall_ids.append(wall.id)

        for candidate in _find_wall_openings(w):
            if candidate.likely_type not in ("door", "window"):
                # "noise", "reconstruction_gap", "ambiguous" --
                # per opening_detection.py's own "don't guess"
                # design, these are deliberately NOT added as
                # Opening objects. A too-wide or ambiguous gap is
                # more likely leftover furniture occlusion within
                # the wall than a real opening; asserting a wrong
                # door/window would be worse than omitting it.
                continue

            wall_length = wall.length()
            position_on_wall = (
                (candidate.start + candidate.end) / 2 / wall_length
                if wall_length > 0
                else 0.5
            )
            opening_confidence = min(
                confidence, 0.7 if is_lidar else 0.5
            )
            opening_provenance = Provenance(
                detection_method=(
                    ingested.capture_method + "_opening_gap"
                )
            )

            if candidate.likely_type == "door":
                door_height = min(2.1, wall.height * 0.9)
                if door_height <= 0:
                    continue
                bm.add_door(
                    level_id,
                    wall.id,
                    width=candidate.width,
                    height=door_height,
                    sill_height=0.0,
                    position_on_wall=position_on_wall,
                    confidence=opening_confidence,
                    provenance=opening_provenance,
                )
            else:  # "window"
                window_sill = min(0.9, wall.height * 0.35)
                window_height = min(
                    1.2, wall.height * 0.9 - window_sill
                )
                if window_height <= 0:
                    continue
                bm.add_window(
                    level_id,
                    wall.id,
                    width=candidate.width,
                    height=window_height,
                    sill_height=window_sill,
                    position_on_wall=position_on_wall,
                    confidence=opening_confidence,
                    provenance=opening_provenance,
                )

    rooms = extract_rooms([w.centerline for w in ingested.fitted_walls])
    room_confidence = 0.85 if is_lidar else 0.5

    for r in rooms:
        bm.add_room(
            level_id,
            r,
            bounded_by=wall_ids,
            classification="unclassified",
            floor_elevation=ingested.height_estimate.floor_elevation,
            ceiling_elevation=ingested.height_estimate.ceiling_elevation,
            confidence=room_confidence,
            provenance=Provenance(
                detection_method=ingested.capture_method
            ),
        )

    return bm


def write_bundle(
    bundle_dir: str,
    session_id: str,
    device_model: str,
    capture_timestamp: str,
    points_arkit_frame: list[tuple[float, float, float]],
) -> None:
    """
    Writes a LiDAR-mode bundle to disk in the format load_bundle()
    expects. Used by test fixtures and by anything simulating a
    capture -- a real iOS app would write this format directly
    rather than calling this Python function.
    """
    os.makedirs(bundle_dir, exist_ok=True)

    manifest = {
        "session_id": session_id,
        "device_model": device_model,
        "capture_timestamp": capture_timestamp,
        "coordinate_frame": "arkit_world_y_up_meters",
        "capture_method": "lidar_mesh",
        "point_count": len(points_arkit_frame),
        "plane_count": 0,
    }
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(bundle_dir, "points.json"), "w") as f:
        json.dump([list(p) for p in points_arkit_frame], f)


def write_plane_bundle(
    bundle_dir: str,
    session_id: str,
    device_model: str,
    capture_timestamp: str,
    planes_arkit_frame: list[dict],
) -> None:
    """
    Writes a non-LiDAR-mode bundle to disk in the format
    load_plane_bundle() expects. Each entry in planes_arkit_frame is
    {"alignment": "vertical"|"horizontal",
     "boundary_vertices": [(x,y,z), ...]}, in ARKit's raw Y-up frame.
    """
    os.makedirs(bundle_dir, exist_ok=True)

    manifest = {
        "session_id": session_id,
        "device_model": device_model,
        "capture_timestamp": capture_timestamp,
        "coordinate_frame": "arkit_world_y_up_meters",
        "capture_method": "arkit_plane_detection",
        "point_count": 0,
        "plane_count": len(planes_arkit_frame),
    }
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    serializable = [
        {
            "alignment": p["alignment"],
            "boundary_vertices": [
                list(v) for v in p["boundary_vertices"]
            ],
        }
        for p in planes_arkit_frame
    ]
    with open(os.path.join(bundle_dir, "planes.json"), "w") as f:
        json.dump(serializable, f)