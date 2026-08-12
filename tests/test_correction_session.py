"""
    Run with: python tests/test_correction_session.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from building_model.schema import BuildingModel
from review.correction_session import(
    build_review_queue, next_review_item, approve,
    correct_wall_dimension, correct_opening_dimension, reclassify_room,
)
from review.formatting import format_wall, format_room


def _make_model():
    bm = BuildingModel(building_id="test")
    bm.add_level("L1")
    w1 = bm.add_wall("L1", [(0, 0), (5, 0)], thickness=0.10, height=2.4, confidence=0.65)
    w2 = bm.add_wall("L1", [(5, 0), (5, 4)], thickness=0.10, height=2.4, confidence=0.95)
    d1 = bm.add_door("L1", w1.id, width=0.85, height=2.0, confidence=0.55)
    room = bm.add_room("L1", [(0, 0), (5, 0), (5, 4), (0, 4)],
                       bounded_by=[w1.id, w2.id], classification="unclassified",
                       confidence=0.80)
    return bm, w1, w2, d1, room


def test_queue_orders_by_confidence():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    item = next_review_item(bm, queue)
    assert item.object_id == d1.id # lowest confidence (0.55) first


def test_correct_opening_dimension_parses_us_units():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    correct_opening_dimension(bm, queue, d1.id, "width", "3'-0\"", unit_system="us")
    assert abs(bm.objects.get(d1.id).width - 0.9144) < 1e-6
    assert bm.objects.get(d1.id).confidence == 1.0


def test_correction_removes_item_from_queue():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    assert queue.next_for_review() == d1.id
    correct_opening_dimension(bm, queue, d1.id, "width", "3'-0\"", unit_system="us")
    assert queue.next_for_review() == w1.id # door resolved, wall (0.65) now lowest


def test_correct_wall_dimension_metric_mode():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    correct_wall_dimension(bm, queue, w1.id, "thickness", "0.15", unit_system="metric")
    assert abs(bm.objects.get(w1.id).thickness - 0.15) < 1e-9


def test_approve_sets_full_confidence():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    approve(bm, queue, w2.id)
    assert bm.objects.get(w2.id).confidence == 1.0


def test_reclassify_room():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    reclassify_room(bm, queue, room.id, "kitchen")
    assert bm.objects.get(room.id).classification == "kitchen"
    assert bm.objects.get(room.id).confidence == 1.0


def test_correct_wrong_type_raises():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    try:
        correct_wall_dimension(bm, queue, room.id, "thickness", "6\"", unit_system="us")
        assert False, "should have raised (room.id is not a Wall)"
    except ValueError:
        pass


def test_correct_bad_field_raises():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    try:
        correct_wall_dimension(bm, queue, w1.id, "material", "brick", unit_system="us")
        assert False, "should have raised (material isn't a correctable numeric field)"
    except ValueError:
        pass


def test_format_wall_us():
    bm, w1, w2, d1, room = _make_model()
    text = format_wall(w1, unit_system="us")
    assert w1.id in text
    assert "%" in text # confidence shown


def test_format_room_area():
    bm, w1, w2, d1, room = _make_model()
    text = format_room(room, unit_system="us")
    assert "sq ft" in text


def test_full_review_workflow_empties_queue():
    bm, w1, w2, d1, room = _make_model()
    queue = build_review_queue(bm)
    for obj_id in [d1.id, w1.id, room.id, w2.id]:
        approve(bm, queue, obj_id)
    assert queue.remaining_count() == 0
    assert next_review_item(bm, queue) is None
    assert bm.validate() == []


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