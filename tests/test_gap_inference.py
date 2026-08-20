"""
Run with: python3 tests/test_gap_inference.py
"""

import sys
import os

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.gap_inference import suggest_gap_completions
from geometry.capture_ingestion import ingest_capture


def test_furniture_occluded_wall_suggests_correct_bridge():
    """The core scenario this module exists for: one wall split
    into two collinear fragments by an obstruction (furniture) in
    an otherwise-closed room."""
    walls = [
        ((0, 0), (2, 0)),  # fragment 1 of the bottom wall
        ((3, 0), (5, 0)),  # fragment 2 (gap 2->3)
        ((5, 0), (5, 4)),
        ((5, 4), (0, 4)),
        ((0, 4), (0, 0)),
    ]
    suggestions = suggest_gap_completions(walls)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.collinearity_deg < 1.0
    assert abs(s.gap_distance - 1.0) < 1e-6
    endpoints = {s.wall_a_endpoint, s.wall_b_endpoint}
    assert endpoints == {(2, 0), (3, 0)}


def test_real_corner_not_suggested():
    """Two perpendicular walls near a corner should never be
    suggested -- collinearity check must correctly reject this."""
    walls = [
        ((0, 0), (3, 0)),
        ((3.1, 0.1), (3.1, 3)),
    ]
    assert suggest_gap_completions(walls) == []


def test_distant_parallel_walls_not_suggested():
    """Two parallel walls on opposite sides of a room (5m apart)
    share an orientation but are far too distant to be a plausible
    furniture-occlusion gap -- max_gap should exclude this."""
    walls = [
        ((0, 0), (2, 0)),
        ((0, 5), (2, 5)),
    ]
    assert suggest_gap_completions(walls) == []


def test_fully_closed_room_has_no_suggestions():
    """Nothing is dangling in a fully closed room -- no
    suggestions should ever be produced."""
    walls = [
        ((0, 0), (5, 0)),
        ((5, 0), (5, 4)),
        ((5, 4), (0, 4)),
        ((0, 4), (0, 0)),
    ]
    assert suggest_gap_completions(walls) == []


def test_dedup_prevents_double_use_of_same_endpoint():
    """If three dangling endpoints are all mutually collinear
    (e.g. three fragments of one long wall), each endpoint should
    appear in at most one suggestion -- not multiple overlapping
    ones competing for the same gap."""
    walls = [
        ((0, 0), (1, 0)),
        ((2, 0), (3, 0)),
        ((4, 0), (5, 0)),
    ]
    suggestions = suggest_gap_completions(walls)
    used_endpoints = []
    for s in suggestions:
        used_endpoints.append((s.wall_a_index, s.wall_a_endpoint))
        used_endpoints.append((s.wall_b_index, s.wall_b_endpoint))
    assert len(used_endpoints) == len(set(used_endpoints))


def test_real_capture_1_no_confident_suggestions():
    """Honest negative result: fixture 1's real dangling endpoints
    aren't collinear enough to suggest anything confidently. A
    correct 'no suggestion' is a better outcome than a wrong
    guess -- this locks in that the function stays appropriately
    conservative on this real data rather than forcing a bad
    suggestion."""
    result = ingest_capture("tests/fixtures/real_ipad_capture_1")
    wall_segments = [w.centerline for w in result.fitted_walls]
    suggestions = suggest_gap_completions(wall_segments)
    assert suggestions == []


def test_real_capture_2_produces_suggestions():
    """Fixture 2's real data DOES produce gap suggestions -- locks
    in current behavior. Honest note (see docs/PROJECT_STATUS.md):
    these two suggestions connect two already-merged wall clusters
    (each wall_fitting support_count=2) that are themselves roughly
    parallel to each other. This is geometrically identical to a
    real furniture-occlusion gap from this function's point of
    view -- it could equally mean wall_fitting's clustering didn't
    fully merge two detections of the same physical wall. Only a
    human looking at the real room can tell the difference; this
    is why suggestions are never auto-applied."""
    result = ingest_capture("tests/fixtures/real_ipad_capture_2")
    wall_segments = [w.centerline for w in result.fitted_walls]
    suggestions = suggest_gap_completions(wall_segments)
    assert len(suggestions) == 2
    for s in suggestions:
        assert s.collinearity_deg < 20.0
        assert 0.15 <= s.gap_distance <= 2.5


def test_suggestions_sorted_by_collinearity():
    result = ingest_capture("tests/fixtures/real_ipad_capture_2")
    wall_segments = [w.centerline for w in result.fitted_walls]
    suggestions = suggest_gap_completions(wall_segments)
    degrees = [s.collinearity_deg for s in suggestions]
    assert degrees == sorted(degrees)


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