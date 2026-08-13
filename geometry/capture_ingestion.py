"""
    Capture bundle ingestion.

    This module defines the CONTRACT between whatever captures raw
    sensor data (the iOS app, per docs/ROOMPLAN_SPIKE.md's recommendation
    to use raw ARKit capture, not RoomPlan) and this project's geometry
    pipeline. Anything that produces a bundle in this format -- a real
    iOS app, a text fixture, a different capture device entirely -- can
    feed the same pipeline without changes downstream.

    Bundle format on disk:

        <bundle_dir>/
            manifest.json -- metadata (see BundleManifest below)
            points.json -- the fused point cloud: a JSON array
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

    :author: Minh Thang Nguyen
    :version: August 12, 2026
"""

from __future__ import annotations
from dataclasses import dataclass
import json, os

from .plane_detection import extract_wall_candidates
from .wall_fitting import fit_walls, FittedWall
from .height_inference import (
    estimate_floor_and_ceiling,
    HeightEstimate,
)


@dataclass
class BundleManifest:
    session_id: str
    device_model: str
    capture_timestamp: str
    coordinate_frame: str # expected: "arkit_world_y_up_meters"
    point_count: int


@dataclass
class IngestedCapture:
    manifest: BundleManifest
    fitted_walls: list[FittedWall]
    height_estimate: HeightEstimate


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

    if(raw_manifest.get("coordinate_frame")
            != "arkit_world_y_up_meters"):
        raise ValueError(
            f"Unsupported coordinate_frame in manifest: "
            f"{raw_manifest.get('coordinate_frame')!r}. "
            f"Expected 'arkit_world_y_up_meters'."
        )

    manifest = BundleManifest(
        session_id=raw_manifest.get("session_id"),
        device_model=raw_manifest.get("device_model"),
        capture_timestamp=raw_manifest.get("capture_timestamp"),
        coordinate_frame=raw_manifest.get("coordinate_frame"),
        point_count=raw_manifest.get("point_count"),
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
    )


def write_bundle(
        bundle_dir: str,
        session_id: str,
        device_model: str,
        capture_timestamp: str,
        points_arkit_frame: list[tuple[float, float, float]],
) -> None:
    """
    Writes a bundle to disk in the format load_bundle() expects.
    Used by test fixtures and by anything simulating a capture
    (e.g. a future synthetic-bundle generator) -- a real iOS app
    would write this format directly rather than calling this
    Python function.
    """
    os.makedirs(bundle_dir, exist_ok=True)

    manifest = {
        "session_id": session_id,
        "device_model": device_model,
        "capture_timestamp": capture_timestamp,
        "coordinate_frame": "arkit_world_y_up_meters",
        "point_count": len(points_arkit_frame),
    }
    with open(os.path.join(bundle_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(bundle_dir, "points.json"), "w") as f:
        json.dump([list(p) for p in points_arkit_frame], f)