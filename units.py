"""
    Unit Conversion / Display Layer.

    Design decision: the Building Model (building_model/schema.py) and every
    geometry algorithm (geometry/*.py) stay in METERS internally, always.
    That's non-negotiable -- it's what IFC export expects (export/ifc_export.py
    assigns METERS as the project unit), and every distance tolerance in the
    geometry algorithms (e.g. wall_fitting.py's offset_tol=0.08,
    room_extraction.py's T-junction tol=0.02) is calibrated in meters.

    This module is the ONLY place feet/inches should appear in the codebase.
    A correction-UI input field showing "8' 6"" to a U.S. user should call
    parse_feet_inches() to get meters before it ever touches a BuildingModel
    object; a display showing a wall's length back to that user should call
    format_feet_inches() on the stored (metric) value. Nothing in
    building_model/ or geometry/ should import this module -- the dependency
    only goes one direction, from UI/display code down to this, never from
    the core model out to unit-formatting code.

    @author: Minh Thang Nguyen
    @version: August 11, 2026
"""


from __future__ import annotations
import math
import re

FEET_TO_METERS = 0.3048
INCH_TO_METERS = FEET_TO_METERS / 12.0 # 0.0254
SQFT_TO_SQM = FEET_TO_METERS ** 2 # 0.09290304

# Length: feet/inches <-> meters

def feet_inches_to_meters(feet: float, inches: float = 0.0) -> float:
    """Straightforward conversion, feet+inches -> meters."""
    return feet * FEET_TO_METERS + inches * INCH_TO_METERS


def meters_to_feet_inches(meters: float) -> tuple[int, float]:
    """
    Returns (whole_feet, remaining_inches_as_decimal). Doesn't do
    fraction rounding -- that's format_feet_inches()'s job, since a raw
    numeric value (e.g. for further math) shouldn't be lossy-rounded,
    only a human-facing display string should be.
    """
    total_inches = meters / INCH_TO_METERS
    whole_feet = int(total_inches // 12)
    remaining_inches_as_decimal = total_inches - whole_feet * 12
    return whole_feet, remaining_inches_as_decimal


def _reduce_fraction(numerator: int, denominator: int) -> tuple[int, int]:
    """Reduce a fraction to lowest term via CGD (e.g. 8/16 -> 1/2)."""
    if numerator == 0:
        return 0, 1
    g = math.gcd(numerator, denominator)
    return numerator // g, denominator // g


def format_feet_inches(meters: float, precision_denominator: int = 16) -> str:
    """
    Format a metric length as an architectural feet/inches string, e.g.
    2.591 m -> "8' 6 1/2"".

    precision_denominator controls rounding granularity : 16 -> nearest
    1/16", the standard architectural tape-measure precision. Use 8 for
    coarser (nearest 1/8") display if that reads cleaner for a given UI.
    """
    if precision_denominator < 1:
        raise ValueError("precision_denominator must be >= 1")

    negative = meters < 0
    whole_feet, remaining_inches = meters_to_feet_inches(abs(meters))

    # round the fractional inches to the nearest 1/precision_denominator
    whole_inches = int(remaining_inches)
    frac_inches = remaining_inches - whole_inches
    numerator = round(frac_inches * precision_denominator)

    if numerator == precision_denominator:
        # round up to a full inch (e.g. 5.99/16 rounds to 16/16 == 1")
        numerator = 0
        whole_inches += 1
        if whole_inches == 12:
            whole_inches = 0
            whole_feet += 1

    parts = []
    if whole_feet > 0:
        parts.append(f"{whole_feet}'")

    if whole_inches > 0 or numerator > 0 or not parts:
        inch_str = str(whole_inches)
        if numerator > 0:
            num, den = _reduce_fraction(numerator, precision_denominator)
            inch_str += f" {num}/{den}"
        parts.append(f'{inch_str}"')

    results = " ".join(parts)
    return f"-{results}" if negative else results


_FEET_INCHES_RE = re.compile(
    r"""
    ^\s*
    (?:(?P<feet>-?\d+(?:\.\d+)?)\s*(?:'|ft)\s*)? # optional feet, e.g. 8' or 8ft
    -?\s*
    (?:(?P<inches>\d+(?:\.\d+)?) # optional inches, e.g. 6 or 6.5
        (?:\s+(?P<inch_frac_num>\d+)/(?P<inch_frac_den>\d+))?  # optional fraction, e.g. 1/2
        \s*(?:"|in|inch(?:es)?)?\s*)?
       $
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_feet_inches(text: str) -> float:
    """
    Parse a feet/inches string into meters. Accepts:
        8'6"  8' 6"  8ft 6in  8'-6"  8' 6 1/2"  10'  6"  10.5'
    Raises ValueError on unparsable input -- never silently guesses,
    same principle as opening_detection.classify_openings not guessing
    at ambiguous widths. A malformed  measurement should be rejected
    loudly in a correction-UI form, not quietly misinterpreted.
    """
    match = _FEET_INCHES_RE.match(text.strip())
    if not match or (not match.group("feet") and not match.group("inches")):
        raise ValueError(f"Could not parse feet/inches value: {text!r}")

    feet = float(match.group("feet") or 0)
    inches = float(match.group("inches") or 0)

    if match.group("inch_frac_num"):
        num = int(match.group("inch_frac_num"))
        den = int(match.group("inch_frac_den"))
        if den == 0:
            raise ValueError(f"Invalid fraction denominator in: {text!r}")
        inches += num / den

    return feet_inches_to_meters(feet, inches)


# Area: square meters <-> square feet

def sqm_to_sqft(square_meters: float) -> float:
    return square_meters / SQFT_TO_SQM


def sqft_to_sqm(square_feet: float) -> float:
    return square_feet * SQFT_TO_SQM


def format_area_sqft(square_meters: float, decimals: int = 1) -> str:
    """e.g. 16.0 sq m -> '172.2 sq ft'"""
    sqft = sqm_to_sqft(square_meters)
    return f"{sqft:.{decimals}f} sq ft"


# Generic dispatcher, for display code that doesn't want to branch on
# unit system itself

def format_length(meters: float, unit_system: str = "us") -> str:
    if unit_system == "us":
        return format_feet_inches(meters)
    if unit_system == "metric":
        return f"{meters:.3f} m"
    raise ValueError(f"Unknown unit_system: {unit_system!r}")


def format_area(square_meters: float, unit_system: str = "us") -> str:
    if unit_system == "us":
        return format_area_sqft(square_meters)
    if unit_system == "metric":
        return f"{square_meters:.2f} sq m"
    raise ValueError(f"Unknown unit_system: {unit_system!r}")