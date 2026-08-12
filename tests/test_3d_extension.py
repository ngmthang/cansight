"""
    Run with: python tests/test_3d_extension.py
"""

import sys
import os
import random

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from geometry.height_inference import estimate_floor_and_ceiling
from building_model.schema import BuildingModel


def test_recovers_clean_floor_ceiling():
    random.seed(1)
    samples = [0.0 + random.uniform(-0.005, 0.005) for _ in range(50)]
    samples += [2.4 + random.uniform(-0.005, 0.005) for _ in range(50)]
    est = estimate_floor_and_ceiling(samples)
    assert abs(est.floor_elevation - 0.0) < 0.01
    assert abs(est.ceiling_elevation - 2.4) < 0.01
    assert abs(est.height - 2.4) < 0.02


def test_rejects_outliers_naive_minmax_would_fail_on():
    random.seed(3)
    samples = [0.0 + random.uniform(-0.005, 0.005) for _ in range(80)]
    samples += [2.4 + random.uniform(-0.005, 0.005) for _ in range(80)]
    samples += [
        random.uniform(0.1, 2.3) for _ in range(15)
    ]  # in-between clutter, not outliers
    samples += [-0.3, 2.9]  # genuine outliers

    naive_height = max(samples) - min(samples)
    est = estimate_floor_and_ceiling(samples)

    # the whole point of the algorithm: it should beat naive min/max
    # by a lot
    assert abs(est.height - 2.4) < 0.05
    assert (
        abs(naive_height - 2.4) > 0.5
    )  # sanity check the naive approach really is bad here
    assert est.outliers_rejected == 2


def test_in_between_clutter_not_counted_as_outliers():
    random.seed(3)
    samples = [0.0 + random.uniform(-0.005, 0.005) for _ in range(80)]
    samples += [2.4 + random.uniform(-0.005, 0.005) for _ in range(80)]
    samples += [random.uniform(0.1, 2.3) for _ in range(15)]
    est = estimate_floor_and_ceiling(samples)
    assert (
        est.outliers_rejected == 0
    )  # no points outside [floor,ceiling] here


def test_sparse_data_falls_back_to_percentile():
    # too few points per bin to ever hit density_threshold=3
    samples = [0.01, 0.02, 1.2, 2.38, 2.39]
    est = estimate_floor_and_ceiling(samples, density_threshold=3)
    assert est.floor_elevation <= est.ceiling_elevation


def test_raises_on_insufficient_samples():
    try:
        estimate_floor_and_ceiling([1.0])
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_floor_and_ceiling_objects():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    boundary = [(0, 0), (5, 0), (5, 4), (0, 4)]
    floor = bm.add_floor("L1", boundary, elevation=0.0)
    ceiling = bm.add_ceiling("L1", boundary, elevation=2.4)
    assert abs(floor.area() - 20.0) < 1e-9
    assert abs(ceiling.area() - 20.0) < 1e-9
    assert floor.id in bm.levels["L1"].floors
    assert ceiling.id in bm.levels["L1"].ceilings
    assert bm.validate() == []


def test_room_volume():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    room = bm.add_room(
        "L1",
        [(0, 0), (5, 0), (5, 4), (0, 4)],
        bounded_by=[],
        floor_elevation=0.0,
        ceiling_elevation=2.4,
    )
    assert abs(room.area() - 20.0) < 1e-9
    assert abs(room.height() - 2.4) < 1e-9
    assert abs(room.volume() - 48.0) < 1e-9


def test_room_rejects_inverted_elevations():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    room = bm.add_room(
        "L1",
        [(0, 0), (5, 0), (5, 4), (0, 4)],
        bounded_by=[],
        floor_elevation=2.0,
        ceiling_elevation=1.5,
    )
    errors = bm.validate()
    assert any("ceiling_elevation" in e for e in errors)


def test_opening_rejects_sill_plus_height_exceeding_wall():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    w = bm.add_wall("L1", [(0, 0), (5, 0)], height=2.4)
    # 1.5 + 1.5 = 3.0m, taller than the 2.4m wall it's hosted on
    bm.add_window("L1", w.id, sill_height=1.5, height=1.5)
    errors = bm.validate()
    assert any("exceeds host wall height" in e for e in errors)


def test_opening_fits_within_wall_passes():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    w = bm.add_wall("L1", [(0, 0), (5, 0)], height=2.4)
    bm.add_window("L1", w.id, sill_height=0.9, height=1.2)
    assert bm.validate() == []


def test_opening_rejects_negative_sill_height():
    bm = BuildingModel(building_id="t")
    bm.add_level("L1")
    w = bm.add_wall("L1", [(0, 0), (5, 0)], height=2.4)
    bm.add_window("L1", w.id, sill_height=-0.5, height=1.0)
    errors = bm.validate()
    assert any("cannot be negative" in e for e in errors)


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