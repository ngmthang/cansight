"""
Run with: python3 tests/test_non_lidar_capture.py
"""

import sys
import os
import json
import random
import tempfile

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.capture_ingestion import (
    write_bundle,
    write_plane_bundle,
    load_plane_bundle,
    ingest_capture,
    build_building_model_from_capture,
    LIDAR_METHOD,
    NON_LIDAR_METHOD,
)


def _wall_corners(x0, z0, x1, z1, y_range=(0.0, 2.4)):
    """4 boundary corners of a vertical wall plane, ARKit frame
    (x, y_up, z) -- the kind of sparse polygon
    ARPlaneGeometry.boundaryVertices gives on a non-LiDAR device."""
    y_lo, y_hi = y_range
    return [
        (x0, y_lo, z0),
        (x1, y_lo, z1),
        (x1, y_hi, z1),
        (x0, y_hi, z0),
    ]


def _synthetic_room_planes():
    return [
        {
            "alignment": "vertical",
            "boundary_vertices": _wall_corners(0, 0, 5, 0),
        },
        {
            "alignment": "vertical",
            "boundary_vertices": _wall_corners(5, 0, 5, 4),
        },
        {
            "alignment": "vertical",
            "boundary_vertices": _wall_corners(5, 4, 0, 4),
        },
        {
            "alignment": "vertical",
            "boundary_vertices": _wall_corners(0, 4, 0, 0),
        },
        {
            "alignment": "horizontal",
            "boundary_vertices": [
                (0, 0, 0),
                (5, 0, 0),
                (5, 0, 4),
                (0, 0, 4),
            ],
        },
    ]


def test_plane_bundle_round_trip():
    planes = _synthetic_room_planes()
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "b")
        write_plane_bundle(
            bd, "s1", "iPhone 8", "2026-01-01T00:00:00Z", planes
        )
        manifest, loaded_planes = load_plane_bundle(bd)

    assert manifest.session_id == "s1"
    assert manifest.capture_method == "arkit_plane_detection"
    assert manifest.plane_count == 5
    assert len(loaded_planes) == 5


def test_plane_bundle_axis_conversion():
    planes = [
        {
            "alignment": "vertical",
            "boundary_vertices": [(1.0, 2.0, 3.0)],
        }
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "b")
        write_plane_bundle(bd, "s", "d", "t", planes)
        _, loaded = load_plane_bundle(bd)

    # model_x = arkit_x, model_y = -arkit_z, model_z = arkit_y
    assert loaded[0]["boundary_vertices"][0] == (1.0, -3.0, 2.0)


def test_ingest_dispatches_to_plane_detection():
    planes = _synthetic_room_planes()
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "room")
        write_plane_bundle(bd, "s", "iPhone 8", "t", planes)
        result = ingest_capture(bd)

    assert result.capture_method == NON_LIDAR_METHOD
    assert len(result.fitted_walls) == 4


def test_ingest_dispatches_to_lidar_by_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "room")
        write_bundle(
            bd,
            "s",
            "iPhone 15 Pro",
            "t",
            [(i * 0.1, 0, 0) for i in range(30)],
        )
        # not enough points to find a plane, but this confirms
        # dispatch routing goes to the LiDAR path (raises for a
        # LiDAR-specific reason, not "unknown capture_method")
        try:
            ingest_capture(bd)
        except ValueError as e:
            assert "capture_method" not in str(e)


def test_non_lidar_confidence_capped_below_lidar():
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

    with tempfile.TemporaryDirectory() as tmpdir:
        lidar_bd = os.path.join(tmpdir, "lidar")
        write_bundle(lidar_bd, "s", "iPhone 15 Pro", "t", points_arkit)
        lidar_result = ingest_capture(lidar_bd, ransac_seed=1)

        plane_bd = os.path.join(tmpdir, "plane")
        write_plane_bundle(
            plane_bd, "s", "iPhone 8", "t", _synthetic_room_planes()
        )
        plane_result = ingest_capture(plane_bd)

    lidar_bm = build_building_model_from_capture(lidar_result, "b1")
    plane_bm = build_building_model_from_capture(plane_result, "b2")

    lidar_conf = [
        o.confidence
        for o in lidar_bm.objects.values()
        if o.type.value == "wall"
    ]
    plane_conf = [
        o.confidence
        for o in plane_bm.objects.values()
        if o.type.value == "wall"
    ]

    assert max(plane_conf) < min(lidar_conf)
    assert (
        max(plane_conf) <= 0.6
    )  # hard cap from the confidence formula


def test_building_model_from_non_lidar_validates():
    planes = _synthetic_room_planes()
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "room")
        write_plane_bundle(bd, "s", "iPhone 8", "t", planes)
        result = ingest_capture(bd)

    bm = build_building_model_from_capture(result, "test_building")
    assert bm.validate() == []
    for obj in bm.objects.values():
        assert obj.provenance.detection_method == NON_LIDAR_METHOD


def test_ingest_raises_when_no_vertical_planes():
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "no_walls")
        write_plane_bundle(
            bd,
            "s",
            "d",
            "t",
            [
                {
                    "alignment": "horizontal",
                    "boundary_vertices": [
                        (0, 0, 0),
                        (1, 0, 0),
                        (1, 0, 1),
                    ],
                }
            ],
        )
        try:
            ingest_capture(bd)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


def test_unknown_capture_method_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "bad")
        os.makedirs(bd)
        with open(os.path.join(bd, "manifest.json"), "w") as f:
            json.dump(
                {
                    "session_id": "x",
                    "device_model": "y",
                    "capture_timestamp": "z",
                    "coordinate_frame": "arkit_world_y_up_meters",
                    "capture_method": "made_up_method",
                },
                f,
            )
        try:
            ingest_capture(bd)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


def test_old_style_bundle_defaults_to_lidar_mesh():
    """Bundles written before capture_method existed should still
    load correctly -- backward compatibility."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "legacy")
        os.makedirs(bd)
        with open(os.path.join(bd, "manifest.json"), "w") as f:
            json.dump(
                {
                    "session_id": "legacy",
                    "device_model": "d",
                    "capture_timestamp": "t",
                    "coordinate_frame": "arkit_world_y_up_meters",
                    "point_count": 2,
                },
                f,
            )
        with open(os.path.join(bd, "points.json"), "w") as f:
            json.dump([[0, 0, 0], [1, 1, 1]], f)

        from geometry.capture_ingestion import load_bundle

        manifest, _ = load_bundle(bd)

    assert manifest.capture_method == "lidar_mesh"


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
    print(f"\n{passed}/{len(tests)} passed")