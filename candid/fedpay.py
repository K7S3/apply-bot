"""General Schedule (GS) pay table lookup.

Bundles the OPM 2026 GS base pay table (grades 1-15, steps 1-10) and the
2026 locality-pay percentages for major locality pay areas, so candid can
quote federal salaries offline.

Sources (all verified via web search, September 2026):
  - Base rates: OPM Salary Table 2026-GS ("Incorporating the 1% General
    Schedule Increase, Effective January 2026"), cross-checked against the
    federalpay.org rendering of the same table. OPM publishes hourly basic
    rates; the annual figures here equal hourly x 2087, rounded, matching the
    published annual locality tables (e.g. LA 2026: base GS-5 step 1
    $34,799 x 1.3647 = $47,490, which is exactly OPM's published number).
  - Locality percentages: each area's official OPM 2026 salary table
    ("Incorporating the 1% General Schedule Increase and a Locality Payment
    of N% ... Effective January 2026").

CAVEAT: locality tables change every January. These figures are labeled with
their source year (2026). For the current year, check OPM's salary tables:
https://www.opm.gov/policy-data-oversight/pay-leave/salaries-wages/salary-tables/
"""

from __future__ import annotations


PAY_YEAR = 2026
PAY_SOURCE = (
    "OPM Salary Table 2026-GS (1% General Schedule Increase, "
    "effective January 2026)"
)
PAY_CAVEAT = (
    "Figures are 2026 OPM rates. Locality pay tables change every January; "
    "confirm current-year numbers on OPM's salary-table pages before using "
    "them in a negotiation or application."
)

# Base annual rates, grade -> [step 1 .. step 10].
_BASE_TABLE: dict[int, list[int]] = {
    1:  [22584, 23341, 24092, 24840, 25589, 26028, 26771, 27519, 27550, 28248],
    2:  [25393, 25997, 26839, 27550, 27858, 28677, 29496, 30315, 31134, 31953],
    3:  [27708, 28632, 29556, 30480, 31404, 32328, 33252, 34176, 35100, 36024],
    4:  [31103, 32140, 33177, 34214, 35251, 36288, 37325, 38362, 39399, 40436],
    5:  [34799, 35959, 37119, 38279, 39439, 40599, 41759, 42919, 44079, 45239],
    6:  [38791, 40084, 41377, 42670, 43963, 45256, 46549, 47842, 49135, 50428],
    7:  [43106, 44543, 45980, 47417, 48854, 50291, 51728, 53165, 54602, 56039],
    8:  [47738, 49329, 50920, 52511, 54102, 55693, 57284, 58875, 60466, 62057],
    9:  [52727, 54485, 56243, 58001, 59759, 61517, 63275, 65033, 66791, 68549],
    10: [58064, 59999, 61934, 63869, 65804, 67739, 69674, 71609, 73544, 75479],
    11: [63795, 65922, 68049, 70176, 72303, 74430, 76557, 78684, 80811, 82938],
    12: [76463, 79012, 81561, 84110, 86659, 89208, 91757, 94306, 96855, 99404],
    13: [90925, 93956, 96987, 100018, 103049, 106080, 109111, 112142, 115173, 118204],
    14: [107446, 111028, 114610, 118192, 121774, 125356, 128938, 132520, 136102, 139684],
    15: [126384, 130597, 134810, 139023, 143236, 147449, 151662, 155875, 160088, 164301],
}

# Official 2026 locality payment percentages by locality pay area.
# Keys are normalized (lowercase) in _norm; the dict holds display names.
_LOCALITY: dict[str, float] = {
    "Washington-Baltimore-Arlington, DC-MD-VA-WV-PA": 33.94,
    "New York-Newark, NY-NJ-CT-PA": 37.95,
    "San Jose-San Francisco-Oakland, CA": 46.34,
    "Los Angeles-Long Beach, CA": 36.47,
    "Boston-Worcester-Providence, MA-RI-NH-CT-ME-VT": 32.58,
    "Dallas-Fort Worth, TX-OK": 27.26,
    "Rest of U.S.": 17.06,
}

# 2026 pay cap: Level IV of the Executive Schedule (5 U.S.C. 5304(g)(1)).
# OPM's 2026 locality tables mark rates above this with "*", limited to
# this amount.
_PAY_CAP_2026 = 197200


def _norm(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def locality_areas() -> list[tuple[str, float]]:
    """Known locality pay areas: [(area display name, 2026 pct), ...]."""
    return sorted(_LOCALITY.items())


def locality_adjustment(area: str) -> float | None:
    """Return the 2026 locality payment percentage for an area, or None.

    Matching is fuzzy: any known area whose normalized name shares a
    substantial token overlap with the input is returned, so "San
    Francisco" matches "San Jose-San Francisco-Oakland, CA". Returns None
    when nothing matches.

    The percentage is expressed as a percent (e.g. 33.94), not a fraction.
    """
    q = _norm(area)
    if not q:
        return None
    best: tuple[str, float] | None = None
    best_score = 0.0
    qtokens = set(q.split())
    for name, pct in _LOCALITY.items():
        ntokens = set(_norm(name).split())
        if _norm(name) == q or qtokens <= ntokens:
            # exact match, or the query names a strict subset of the area's
            # tokens ("Washington, DC", "San Francisco", "New York-Newark")
            return pct
        overlap = len(qtokens & ntokens) / max(1, len(qtokens | ntokens))
        # require at least one shared meaningful token
        shared = qtokens & ntokens
        meaningful = any(len(t) > 2 for t in shared)
        if meaningful and overlap > best_score:
            best, best_score = (name, pct), overlap
    if best and best_score >= 0.3:
        return best[1]
    return None


def gs_pay(grade: int, step: int = 1, locality: str | None = None) -> dict:
    """Annual GS salary for a grade/step, optionally locality-adjusted.

    Returns {"annual": int, "base": int, "locality": str|None,
             "locality_pct": float|None, "capped": bool, "year": 2026}.
    Locality-adjusted pay is capped at the 2026 Level IV Executive Schedule
    rate ($197,200), matching OPM's published tables ("*" entries).
    """
    if grade not in _BASE_TABLE:
        raise ValueError(f"Grade must be 1-15, got {grade!r}.")
    if not 1 <= step <= 10:
        raise ValueError(f"Step must be 1-10, got {step!r}.")
    base = _BASE_TABLE[grade][step - 1]
    out = {"annual": base, "base": base, "locality": None,
           "locality_pct": None, "capped": False, "year": PAY_YEAR}
    if locality:
        pct = locality_adjustment(locality)
        if pct is None:
            raise ValueError(
                f"Unknown locality pay area: {locality!r}. "
                f"Known areas: {', '.join(sorted(_LOCALITY))}."
            )
        annual = round(base * (1 + pct / 100))
        capped = annual > _PAY_CAP_2026
        out.update({
            "annual": min(annual, _PAY_CAP_2026),
            "locality": locality,
            "locality_pct": pct,
            "capped": capped,
            "year": PAY_YEAR,
        })
    return out


def grade_salary_range(grade: int, locality: str | None = None) -> dict:
    """{"step1", "step10"} annual salaries for a grade (base or locality).

    Always carries the source-year label and caveat.
    """
    lo = gs_pay(grade, 1, locality)
    hi = gs_pay(grade, 10, locality)
    return {
        "grade": grade,
        "step1": lo["annual"],
        "step10": hi["annual"],
        "locality": lo["locality"],
        "locality_pct": lo["locality_pct"],
        "year": PAY_YEAR,
        "source": PAY_SOURCE,
        "caveat": PAY_CAVEAT,
    }


def table_info() -> dict:
    """Provenance metadata for the bundled figures."""
    return {"year": PAY_YEAR, "source": PAY_SOURCE, "caveat": PAY_CAVEAT,
            "locality_areas": sorted(_LOCALITY)}
