"""
    Run with: python tests/test_units.py
"""
import sys, os, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from units import(
    feet_inches_to_meters, format_feet_inches, parse_feet_inches,
    sqm_to_sqft, sqft_to_sqm, format_area_sqft,
)


def test_basic_conversion():
    assert abs(feet_inches_to_meters(8) - 2.4384) < 1e-9
    assert abs(feet_inches_to_meters(0, 1) - 0.0254) < 1e-9


def test_format_whole_feet():
    assert format_feet_inches(2.4384) == "8'"


def test_format_feet_and_inches():
    assert format_feet_inches(2.5908) == "8' 6\""


def test_format_inches_only():
    assert format_feet_inches(0.1524) == '6"'


def test_format_zero():
    assert format_feet_inches(0.0) == '0"'


def test_format_negative():
    result = format_feet_inches(-1.0)
    assert result.startswith("-")


def test_format_fraction_reduces_to_lowest_terms():
    # 8mm past 8' 6" should round to a clean 1/2" fraction, not 8/16
    m = feet_inches_to_meters(8, 6.5)
    result = format_feet_inches(m)
    assert "1/2" in result
    assert "8/16" not in result


def test_parse_various_formats_agree():
    reference = parse_feet_inches("8'6\"")
    variants = ["8' 6\"", "8ft 6in", "8'-6\"", "8 ft 6 in"]
    for v in variants:
        assert abs(parse_feet_inches(v) - reference) < 1e-6, f"{v!r} disagreed"


def test_parse_feet_only():
    assert abs(parse_feet_inches("10'") - 3.048) < 1e-9


def test_parse_inches_only():
    assert abs(parse_feet_inches('6"') - 0.1524) < 1e-9


def test_parse_fractional_inches():
    m = parse_feet_inches("8' 6 1/2\"")
    expected = feet_inches_to_meters(8, 6.5)
    assert abs(m - expected) < 1e-9


def test_parse_rejects_garbage():
    try:
        parse_feet_inches("not a measurement")
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_round_trip_fuzz():
    random.seed(0)
    max_err = 0.0
    for _ in range(500):
        m = random.uniform(0.01, 30.0)
        back = parse_feet_inches(format_feet_inches(m))
        max_err = max(abs(back - m), max_err)
    # nearest-1/16" rounding implies worst case error is half of 1/16"
    assert max_err < (0.0254 / 16) / 2 + 1e-9


def test_area_conversion_round_trip():
    sqm = 16.0
    sqft = sqm_to_sqft(sqm)
    back = sqft_to_sqm(sqft)
    assert abs(back - sqm) < 1e-6


def test_format_area_sqft():
    assert format_area_sqft(16.0) == "172.2 sq ft"


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