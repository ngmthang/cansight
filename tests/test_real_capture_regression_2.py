"""
Second real-capture regression fixture -- see
tests/test_real_capture_regression.py's module docstring for why
this pattern exists. This fixture (tests/fixtures/real_ipad_capture_2)
is a genuinely different scan: a different room/area (includes a
desk with a monitor), captured specifically to validate the
false-positive vertical-extent filter (capture_ingestion.py's
MIN_WALL_VERTICAL_EXTENT) against a real desk/monitor scene -- the
exact scenario that originally motivated that filter.

Complementary to fixture 1: fixture 1's data DOES trigger the
filter (one plane gets correctly excluded). This fixture's data
does NOT trigger it -- every vertical plane here happens to clear
the 0.5m threshold -- which is an equally important case to lock
in: confirming the filter doesn't over-trigger and incorrectly
exclude legitimate walls on a real, different capture.

Run with: python3 tests/test_real_capture_regression_2.py
"""

import sys
import os

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.capture_ingestion import (
    ingest_capture,
    build_building_model_from_capture,
    NON_LIDAR_METHOD,
)

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "real_ipad_capture_2",
)


def test_real_capture_2_ingests_without_error():
    result = ingest_capture(FIXTURE_DIR)
    assert result.capture_method == NON_LIDAR_METHOD


def test_real_capture_2_wall_count():
    """9 walls -- unlike fixture 1, none of this capture's vertical
    planes are short enough to trigger the false-positive filter
    (closest is 0.514m, just above the 0.5m threshold), confirming
    the filter doesn't over-trigger on a real, legitimate capture."""
    result = ingest_capture(FIXTURE_DIR)
    assert len(result.fitted_walls) == 9


def test_real_capture_2_no_plane_incorrectly_filtered():
    """Direct check that every vertical plane in this fixture clears
    the false-positive filter's threshold -- if a future change to
    MIN_WALL_VERTICAL_EXTENT accidentally makes it too aggressive,
    this test catches walls disappearing that shouldn't."""
    from geometry.capture_ingestion import load_plane_bundle

    manifest, planes = load_plane_bundle(FIXTURE_DIR)
    vertical = [p for p in planes if p["alignment"] == "vertical"]
    assert len(vertical) == 12

    for p in vertical:
        z_values = [v[2] for v in p["boundary_vertices"]]
        extent = max(z_values) - min(z_values)
        assert extent >= 0.5, (
            f"expected all planes in this fixture to clear the "
            f"filter threshold, found one at {extent:.3f}m"
        )


def test_real_capture_2_height_estimate_is_plausible():
    result = ingest_capture(FIXTURE_DIR)
    assert 2.2 < result.height_estimate.height < 3.0


def test_real_capture_2_produces_valid_building_model():
    result = ingest_capture(FIXTURE_DIR)
    bm = build_building_model_from_capture(result, "real_capture_2")
    assert bm.validate() == []


def test_real_capture_2_wall_confidences_stay_non_lidar_capped():
    result = ingest_capture(FIXTURE_DIR)
    bm = build_building_model_from_capture(result, "real_capture_2")
    wall_confidences = [
        o.confidence
        for o in bm.objects.values()
        if o.type.value == "wall"
    ]
    assert len(wall_confidences) == 9
    assert all(c <= 0.6 for c in wall_confidences)


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