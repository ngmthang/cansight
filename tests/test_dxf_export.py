"""
Run with: python3 tests/test_dxf_export.py
"""

import sys
import os
import tempfile

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import ezdxf

from building_model.schema import BuildingModel
from export.dxf_export import export_to_dxf


def _make_test_model():
    bm = BuildingModel(building_id="dxf_test")
    bm.add_level("L1")
    w1 = bm.add_wall("L1", [(0, 0), (5, 0)], thickness=0.12, height=2.4)
    w2 = bm.add_wall("L1", [(5, 0), (5, 4)], thickness=0.12, height=2.4)
    w3 = bm.add_wall("L1", [(5, 4), (0, 4)], thickness=0.12, height=2.4)
    w4 = bm.add_wall("L1", [(0, 4), (0, 0)], thickness=0.12, height=2.4)
    d1 = bm.add_door(
        "L1", w1.id, position_on_wall=0.5, width=0.9, height=2.1
    )
    win1 = bm.add_window(
        "L1",
        w3.id,
        position_on_wall=0.3,
        width=1.2,
        height=1.0,
        sill_height=0.9,
    )
    room = bm.add_room(
        "L1",
        [(0, 0), (5, 0), (5, 4), (0, 4)],
        bounded_by=[w1.id, w2.id, w3.id, w4.id],
        classification="living_room",
    )
    return bm, w1, w2, w3, w4, d1, win1, room


def test_export_produces_valid_dxf():
    bm, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        warnings = export_to_dxf(bm, path)
        assert warnings == []
        # readfile() itself raises if the DXF is malformed -- this
        # is a real structural validity check, not just "a file
        # exists"
        doc = ezdxf.readfile(path)
        assert doc is not None


def test_export_creates_expected_layers():
    bm, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        layer_names = {layer.dxf.name for layer in doc.layers}
        assert {"WALLS", "ROOMS", "DOORS", "WINDOWS", "TEXT"}.issubset(
            layer_names
        )


def test_export_units_are_meters():
    bm, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        assert doc.units == ezdxf.units.M


def test_wall_polygon_offset_matches_thickness():
    bm, w1, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        walls = [e for e in msp if e.dxf.layer == "WALLS"]
        assert len(walls) == 4

        # wall 1: (0,0)->(5,0), thickness 0.12 -> offset 0.06 on
        # each side, so all points should have |y| == 0.06
        first_wall_points = list(walls[0].get_points("xy"))
        ys = sorted(
            set(round(float(p[1]), 3) for p in first_wall_points)
        )
        assert ys == [-0.06, 0.06]


def test_room_polygon_and_label():
    bm, *_, room = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        room_polys = [e for e in msp if e.dxf.layer == "ROOMS"]
        assert len(room_polys) == 1
        points = [
            (round(float(x), 2), round(float(y), 2))
            for x, y in room_polys[0].get_points("xy")
        ]
        assert points == [
            (0.0, 0.0),
            (5.0, 0.0),
            (5.0, 4.0),
            (0.0, 4.0),
        ]

        texts = [e for e in msp if e.dxf.layer == "TEXT"]
        assert len(texts) == 1
        assert "living_room" in texts[0].dxf.text
        assert "20.0" in texts[0].dxf.text  # area


def test_door_opening_position_and_size():
    bm, w1, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        doors = [e for e in msp if e.dxf.layer == "DOORS"]
        assert len(doors) == 1
        xs = [float(p[0]) for p in doors[0].get_points("xy")]
        # door: position_on_wall=0.5 on wall (0,0)->(5,0), width=0.9
        # -> centered at x=2.5, spanning 2.05 to 2.95
        assert min(xs) == pytest_approx(2.05)
        assert max(xs) == pytest_approx(2.95)


def pytest_approx(value, tol=0.01):
    """Tiny local approx helper -- avoids adding a pytest dependency
    just for one tolerance check."""

    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol

    return _Approx()


def test_window_opening_position_and_size():
    bm, w1, w2, w3, *_ = _make_test_model()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        export_to_dxf(bm, path)
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        windows = [e for e in msp if e.dxf.layer == "WINDOWS"]
        assert len(windows) == 1
        xs = [float(p[0]) for p in windows[0].get_points("xy")]
        # window: position_on_wall=0.3 on wall (5,4)->(0,4), width=1.2
        # -> centered at x=3.5, spanning 2.9 to 4.1
        assert min(xs) == pytest_approx(2.9)
        assert max(xs) == pytest_approx(4.1)


def test_export_refuses_invalid_model():
    bm = BuildingModel(building_id="bad")
    bm.add_level("L1")
    bm.add_door("L1", host_wall_id="nonexistent_wall")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.dxf")
        try:
            export_to_dxf(bm, path)
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "validation" in str(e)


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