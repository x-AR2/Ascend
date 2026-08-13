"""
grading.py
-----------
The single source of truth for the official grading scale, the
Academic-Council rounding rule, and percentage <-> grade-point conversions.

Every other module (course calculator, SGPA, CGPA) imports from here so
that if the university ever changes the scale, this is the only file
that needs to change.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, Optional

# (min_percent, max_percent, letter, grade_point) — inclusive bounds, whole numbers
GRADE_SCALE = [
    (85, 100, "A", 4.00),
    (80, 84, "A-", 3.66),
    (75, 79, "B+", 3.33),
    (71, 74, "B", 3.00),
    (68, 70, "B-", 2.66),
    (64, 67, "C+", 2.33),
    (61, 63, "C", 2.00),
    (58, 60, "C-", 1.66),
    (54, 57, "D+", 1.30),
    (50, 53, "D", 1.00),
    (0, 49, "F", 0.00),
]


def round_percentage(percentage: float) -> int:
    """
    Official rounding rule (per the Academic Council notification):
    Round to the nearest whole number based STRICTLY on the tenths digit.
    Tenths digit >= 5 -> round up. Tenths digit < 5 -> round down.

    e.g. 70.5% or 70.8% -> 71 (B)   |   70.4% -> 70 (B-)
    """
    d = Decimal(str(percentage)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def percentage_to_grade(percentage: float) -> Tuple[str, float]:
    """Raw percentage -> (letter, grade_point), applying the official rounding first."""
    rounded = round_percentage(percentage)
    rounded = max(0, min(100, rounded))
    for lo, hi, letter, gp in GRADE_SCALE:
        if lo <= rounded <= hi:
            return letter, gp
    return "F", 0.00  # unreachable, safety net


def grade_point_for_letter(letter: str) -> float:
    for lo, hi, l, gp in GRADE_SCALE:
        if l == letter:
            return gp
    raise ValueError(f"Unknown grade letter: {letter!r}")


def min_percentage_for_letter(letter: str) -> int:
    for lo, hi, l, gp in GRADE_SCALE:
        if l == letter:
            return lo
    raise ValueError(f"Unknown grade letter: {letter!r}")


def min_percentage_for_grade_point(target_gp: float) -> int:
    """
    Given a target grade point (e.g. 3.33 for a B+), return the minimum
    whole-number percentage that secures AT LEAST that grade point.
    This is what lets a user say 'I want a 3.5 SGPA' and have the app
    translate that into concrete percentage targets per course.
    """
    bands_asc = sorted(GRADE_SCALE, key=lambda b: b[3])
    for lo, hi, letter, gp in bands_asc:
        if gp >= target_gp - 1e-9:
            return lo
    return 100


def next_band_up(letter: str) -> Optional[Tuple[str, float, int]]:
    """Returns (letter, grade_point, min_percent) of the next grade band above the given one, or None if already at A."""
    bands_desc = sorted(GRADE_SCALE, key=lambda b: -b[3])
    letters_desc = [b[2] for b in bands_desc]
    idx = letters_desc.index(letter)
    if idx == 0:
        return None
    lo, hi, l, gp = bands_desc[idx - 1]
    return l, gp, lo
