"""
Run with: python3 -m pytest tests/ -v
(or: python3 tests/test_all.py  for a plain run without pytest)
"""
import sys
import os
import math
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from building_model.schema import BuildingModel
from geometry.wall_fitting import fit_walls, cluster_wall_observations
from geometry.room_extraction import extract_rooms, room_area, _split_at_t_junctions
from geometry.opening_detection import GapObservation, merge_gaps, classify_openings
from review.queue import ReviewQueue


def test_schema_area_and_validation():
    bm = BuildingModel(building_id="t1")
    bm.add_level("L1")
    w1 = bm.add_wall("L1", [(0, 0), (5, 0)])
    w2 = bm.add_wall("L1", [(5, 0), (5, 4)])
    w3 = bm.add_wall("L1", [(5, 4), (0, 4)])
    w4 = bm.add_wall("L1", [(0, 4), (0, 0)])
    room = bm.add_room("L1", [(0, 0), (5, 0), (5, 4), (0, 4)],
                        bounded_by=[w1.id, w2.id, w3.id, w4.id])
    assert abs(room.area() - 20.0) < 1e-9
    assert bm.validate() == []


def test_schema_catches_bad_reference():
    bm = BuildingModel(building_id="t2")
    bm.add_level("L1")
    w1 = bm.add_wall("L1", [(0, 0), (5, 0)])
    bm.add_door("L1", host_wall_id="wall_does_not_exist")
    errors = bm.validate()
    assert any("not found" in e for e in errors)


def test_wall_clustering_groups_noisy_observations():
    random.seed(42)
    segs = []
    for _ in range(8):
        j = lambda: random.uniform(-0.02, 0.02)
        segs.append(((0 + j(), 0 + j()), (5 + j(), 0 + j())))
    segs.append(((0, 0), (0, 3)))  # unrelated wall
    groups = cluster_wall_observations(segs)
    assert len(groups) == 2
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 8]


def test_wall_fitting_recovers_true_line():
    random.seed(7)
    segs = []
    for _ in range(10):
        j = lambda: random.uniform(-0.03, 0.03)
        segs.append(((0 + j(), 0 + j()), (6 + j(), 0 + j())))
    fitted = fit_walls(segs)
    assert len(fitted) == 1
    (x0, y0), (x1, y1) = fitted[0].centerline
    length = math.hypot(x1 - x0, y1 - y0)
    assert abs(length - 6.0) < 0.1
    assert abs(y0) < 0.05 and abs(y1) < 0.05


def test_room_extraction_single_room():
    walls = [((0, 0), (5, 0)), ((5, 0), (5, 4)), ((5, 4), (0, 4)), ((0, 4), (0, 0))]
    rooms = extract_rooms(walls)
    assert len(rooms) == 1
    assert abs(room_area(rooms[0]) - 20.0) < 1e-6


def test_room_extraction_t_junction():
    walls = [
        ((0, 0), (8, 0)), ((8, 0), (8, 4)), ((8, 4), (0, 4)), ((0, 4), (0, 0)),
        ((4, 0), (4, 4)),
    ]
    rooms = extract_rooms(walls)
    assert len(rooms) == 2
    areas = sorted(round(room_area(r), 2) for r in rooms)
    assert areas == [16.0, 16.0]


def test_opening_merge_and_classify():
    gaps = [
        GapObservation(1.0, 1.85, 0.8),
        GapObservation(1.05, 1.9, 0.7),
        GapObservation(4.5, 4.55, 0.3),
    ]
    merged = merge_gaps(gaps)
    assert len(merged) == 2
    classified = classify_openings(merged)
    types = sorted(c.likely_type for c in classified)
    assert types == ["door", "noise"]


def test_review_queue_ordering_and_resolution():
    q = ReviewQueue()
    q.add_or_update("a", 0.9)
    q.add_or_update("b", 0.5)
    q.add_or_update("c", 0.7)
    # lowest confidence surfaces first, and stays surfaced until resolved
    assert q.next_for_review() == "b"
    assert q.next_for_review() == "b"
    q.resolve("b")
    assert q.next_for_review() == "c"

    q.add_or_update("d", 0.1)
    assert q.peek_batch(2) == ["d", "c"]  # c (0.7) still unresolved, lower than a (0.9)
    q.resolve("d")
    q.resolve("c")
    assert q.next_for_review() == "a"
    assert q.remaining_count() == 1
    q.resolve("a")
    assert q.remaining_count() == 0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")