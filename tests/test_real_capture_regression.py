"""
Regression test using a REAL capture bundle (iPad A16, non-LiDAR
plane-detection mode), not synthetic data -- see
tests/fixtures/real_ipad_capture_1/.

Why this exists: every other test in this project uses carefully
constructed synthetic data, which is good for testing algorithm
*logic* but can't catch calibration drift against real sensor
noise -- exactly the kind of gap that let the wall_fitting.py
clustering-tolerance issue go unnoticed until a real device test
found it (see docs/PROJECT_STATUS.md Section 4). This test locks
in the current, verified-correct behavior on one real capture, so
future changes to plane_detection.py/wall_fitting.py/
room_extraction.py/height_inference.py get checked against real
noise automatically, not just synthetic noise.

If a future, deliberate improvement legitimately changes this
capture's results (e.g. better gap-closing heuristics finally
making the room extract cleanly), that's expected -- update the
asserted values here to match the new, better behavior, with a
comment explaining what improved and why. The point of this test
is to catch *accidental* regressions, not to freeze behavior
forever.

Run with: python3 tests/test_real_capture_regression.py
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
    "real_ipad_capture_1",
)


def test_real_capture_ingests_without_error():
    result = ingest_capture(FIXTURE_DIR)
    assert result.capture_method == NON_LIDAR_METHOD


def test_real_capture_wall_count():
    """Locks in the current, verified-correct wall count after the
    angle_tol_deg=25/offset_tol=0.25 clustering fix (see
    docs/PROJECT_STATUS.md Section 4, item 1). Before that fix, this
    same fixture produced 17 unclustered fragments instead of 8
    properly-merged walls."""
    result = ingest_capture(FIXTURE_DIR)
    assert len(result.fitted_walls) == 8


def test_real_capture_height_estimate_is_plausible():
    """A real room's ceiling height should land in a sane range --
    this fixture's true height is unknown exactly (no ground-truth
    survey), but 2.2-2.6m covers ordinary residential ceiling
    heights, and the estimate (2.435m as of this writing) should
    stay stable run-to-run since ransac_seed isn't involved in the
    non-LiDAR path (no RANSAC -- see capture_ingestion.py's
    _ingest_plane_detection_bundle)."""
    result = ingest_capture(FIXTURE_DIR)
    assert 2.2 < result.height_estimate.height < 2.6


def test_real_capture_produces_valid_building_model():
    result = ingest_capture(FIXTURE_DIR)
    bm = build_building_model_from_capture(result, "real_capture_1")
    assert bm.validate() == []


def test_real_capture_wall_confidences_stay_non_lidar_capped():
    """Every wall from this non-LiDAR capture should have confidence
    <= 0.6, per the formula in build_building_model_from_capture()
    -- confirms the confidence-tier separation (V1 spec Section 13)
    holds on real data, not just synthetic."""
    result = ingest_capture(FIXTURE_DIR)
    bm = build_building_model_from_capture(result, "real_capture_1")
    wall_confidences = [
        o.confidence
        for o in bm.objects.values()
        if o.type.value == "wall"
    ]
    assert len(wall_confidences) == 8
    assert all(c <= 0.6 for c in wall_confidences)


def test_real_capture_no_room_closes_yet():
    """Documents current, known behavior: this real capture has
    genuine furniture-occlusion gaps (see the project's real-device
    debugging session), so no room polygon closes. This is NOT a
    bug -- it's exactly the scenario add_manual_wall()
    (review/correction_session.py) exists to handle. If a future
    gap-inference improvement (docs/BACKLOG.md's "furniture-aware
    wall detection") changes this, update this assertion
    deliberately, with a comment explaining the improvement."""
    result = ingest_capture(FIXTURE_DIR)
    bm = build_building_model_from_capture(result, "real_capture_1")
    room_count = len(
        [o for o in bm.objects.values() if o.type.value == "room"]
    )
    assert room_count == 0


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