"""
    Run with: python tests/test_capture_ingestion.py
"""

import sys, os, random, tempfile, json

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.plane_detection import (
     ransac_plane_segmentation,
     extract_wall_candidates,
)

from geometry.wall_fitting import fit_walls
from geometry.room_extraction import extract_rooms, room_area
from geometry.capture_ingestion import (
    load_bundle,
    ingest_capture,
    write_bundle,
)


def _sample_wall_plane(
    x0, y0, x1, y1, z_range=(0, 2.4), n=150, noise=0.01
):
    pts = []
    for _ in range(n):
        t = random.uniform(0, 1)
        x = x0 + t * (x1 - x0)
        y = y0 + t * (y1 - y0)
        z = random.uniform(*z_range)
        pts.append(
            (
                x + random.uniform(-noise, noise),
                y + random.uniform(-noise, noise),
                z,
            )
        )
    return pts


def _sample_horizontal_plane(x_range, y_range, z, n=150, noise=0.01):
    return [(
            random.uniform(*x_range),
            random.uniform(*y_range),
            z + random.uniform(-noise, noise),
        ) for _ in range(n)]


def _synthetic_room_points(seed=5):
    random.seed(seed)
    points = []
    points += _sample_wall_plane(0, 0, 5, 0)
    points += _sample_wall_plane(5, 0, 5, 4)
    points += _sample_wall_plane(5, 4, 0, 4)
    points += _sample_wall_plane(0, 4, 0, 0)
    points += _sample_horizontal_plane((0, 5), (0, 4), 0.0)
    points += _sample_horizontal_plane((0, 5), (0, 4), 2.4)
    random.shuffle(points)
    return points


def test_ransac_finds_all_planes():
    points = _synthetic_room_points()
    planes = ransac_plane_segmentation(points, seed=1)
    # 4 walls + floor + ceiling = 6 planes
    assert len(planes) == 6


def test_wall_candidates_excludes_floor_and_ceiling():
    points = _synthetic_room_points()
    candidates = extract_wall_candidates(points)
    assert len(candidates) == 4


def test_wall_candidates_position_are_accurate():
    points = _synthetic_room_points()
    candidates = extract_wall_candidates(points)
    # every candidate's z_samples should span close to the full
    # 0-2.4m wall height
    for c in candidates:
        assert min(c.z_samples) < 0.15
        assert max(c.z_samples) > 2.25


def test_wall_candidates_feed_existing_pipeline():
    """The real integration test: raw points -> plane_detection ->
    wall_fitting -> room_extraction, using every geometry module."""
    points = _synthetic_room_points()
    candidates = extract_wall_candidates(points)
    segments = [c.segment for c in candidates]
    fitted =  fit_walls(segments)
    rooms = extract_rooms([w.centerline for w in fitted])
    assert len(rooms) == 1
    assert abs(room_area(rooms[0]) - 20.0) < 1.0 # within 1 sq m of truth


def test_ransac_ignore_sparse_outlier_noise():
    random.seed(2)
    points = _synthetic_room_points(seed=2)
    # sprinkle in random noise points that shouldn't form a plane
    noise_points = [(
        random.uniform(-1, 6),
        random.uniform(-1, 5),
        random.uniform(-1, 3),
    ) for _ in range(20)]
    planes = ransac_plane_segmentation(points + noise_points, seed=1)
    # should still find the 6 real surfaces; scattered noise shouldn't
    # form a 20-point-min plane of its own
    assert len(planes) == 6


def test_bundle_round_trip_axis_conversion():
    random.seed(3)
    # ARKit frame: (x, y_up, z)
    points_arkit = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = os.path.join(tmpdir, "b")
        write_bundle(
            bundle_dir,
            "s1",
            "iPhone",
            "2026-01-01T00:00:00Z",
            points_arkit,
        )
        manifest, model_points = load_bundle(bundle_dir)

    assert manifest.session_id == "s1"
    assert manifest.point_count == 2
    # model_x = arkit_x, model_y = -arkit_z, model_z = arkit_y
    assert model_points[0] == (1.0, -3.0, 2.0)
    assert model_points[1] == (4.0, -6.0, 5.0)


def test_bundle_rejects_wrong_coordinate_frame():
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "bad")
        os.makedirs(bd)
        with open(os.path.join(bd, "manifest.json"), "w") as f:
            json.dump({
                "session_id": "x",
                "device_model": "y",
                "capture_timestamp": "z",
                "coordinate_frame": "some_other_frame",
                "point_count": 1,
            }, f)
        with open(os.path.join(bd, "points.json"), "w") as f:
            json.dump([[0, 0, 0]], f)
        try:
            load_bundle(bd)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


def test_bundle_rejects_mismatched_point_count():
    with tempfile.TemporaryDirectory() as tmpdir:
        bd = os.path.join(tmpdir, "bad")
        os.makedirs(bd)
        with open(os.path.join(bd, "manifest.json"), "w") as f:
            json.dump({
                "session_id": "x",
                "device_model": "y",
                "capture_timestamp": "z",
                "coordinate_frame": "arkit_world_y_up_meters",
                "point_count": 100,
            }, f)
        with open(os.path.join(bd, "points.json"), "w") as f:
            json.dump([[0, 0, 0]], f)
        try:
            load_bundle(bd)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


def test_ingest_capture_full_pipeline():
    random.seed(9)
    points_arkit = []
    for a, b in [
        ((0, 0), (5, 0)),
        ((5, 0), (5, 4)),
        ((5, 4), (0, 4)),
        ((0, 4), (0, 0)),
    ]:
        points_arkit += [(
            a[0] + t * (b[0] - a[0]) + random.uniform(-0.01, 0.01),
            random.uniform(0, 2.4),
            a[1] + t * (b[1] - a[1]) + random.uniform(-0.01, 0.01),
        ) for t in [random.uniform(0, 1) for _ in range(150)]
        ]

    points_arkit += [
        (random.uniform(0, 5), 0.0, random.uniform(0, 4))
        for _ in range(150)
    ]
    points_arkit += [
        (random.uniform(0, 5), 2.4, random.uniform(0, 4))
        for _ in range(150)
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = os.path.join(tmpdir, "room")
        write_bundle(
            bundle_dir,
            "sess",
            "iPhone 15 Pro",
            "2026-01-01T00:00:00Z",
            points_arkit,
        )
        result = ingest_capture(bundle_dir)

    assert len(result.fitted_walls) == 4
    assert abs(result.height_estimate.height - 2.4) < 0.3


def test_ingest_capture_raises_on_insufficient_points():
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_dir = os.path.join(tmpdir, "tiny")
        write_bundle(
            bundle_dir,
            "s",
            "d",
            "t",
            [(0, 0, 0), (1, 0, 0)]
        )
        try:
            ingest_capture(bundle_dir)
            assert False, "should have raised ValueError"
        except ValueError:
            pass


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")