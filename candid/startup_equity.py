"""Startup equity evaluation: due-diligence notes and a cash-vs-equity modeler.

Two pieces:

1. ``equity_notes(offer_id)`` - startup-specific evaluation notes for an
   existing offer: a checklist of questions to ask the company (strike price,
   409A valuation date, fully-diluted shares, cliff/vesting, ISO vs NSO,
   post-termination exercise window, dilution history), with an educational
   explainer for each term. The notes reference ONLY values already stored on
   the offer record. Anything missing becomes an "ask the company" prompt.
   Numbers are never invented.

2. ``compare_startup(offer_a_id, offer_b_id, growth=...)`` - an illustrative
   cash-vs-equity tradeoff model over 4 years under user-set growth
   assumptions. Growth presets are documented assumptions (low 0%/yr,
   base 15%/yr, high 40%/yr) and can be overridden with a custom rate.
   Output is year-by-year, plus totals per scenario and a break-even growth
   rate. Everything is clearly labeled as an illustrative model, not tax or
   financial advice.

Storage reuses offer.py's store (candid_data/offers.json) without changing it:
offers are read through ``offer.list_offers()`` and never rewritten here.
"""

from __future__ import annotations

import json
from datetime import date

from candid import offer as O


class StartupEquityError(Exception):
    """Raised for invalid startup-equity input or operations."""


DISCLAIMER = (
    "Illustrative model only. This is educational, not tax, legal, or "
    "financial advice. Startup equity is risky and can end up worth nothing. "
    "Talk to a tax professional before making decisions about exercise or sale."
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _num(value, field: str) -> float:
    """Coerce a stored value to float; None stays None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise StartupEquityError(
            f"Offer field '{field}' should be a number, got '{value}'.")


def _get(offer: dict, *names: str):
    """First present-and-not-None value among the field name aliases."""
    for name in names:
        if name in offer and offer[name] is not None:
            return offer[name]
    return None


def _offer_by_id(offer_id: int, path=None) -> dict:
    for offer in O.list_offers(path=path):
        if offer.get("id") == offer_id:
            return offer
    raise StartupEquityError(
        f"No offer with id {offer_id}. Run `python -m candid offer list` to see ids.")


def _fmt(x) -> str:
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "not provided"


def _fmt_shares(x) -> str:
    try:
        return f"{float(x):,.0f} shares"
    except (TypeError, ValueError):
        return "not provided"


# ---------------------------------------------------------------------------
# 1. equity notes
# ---------------------------------------------------------------------------

#: Checklist entries: (field aliases, question, explainer).
_EQUITY_TERMS = [
    (
        ("strike_price",),
        "What is the strike price per share?",
        "The strike price is what you pay per share to exercise each option. "
        "Your per-share gain at a future exit is roughly the future share "
        "price minus the strike (before taxes). A lower strike relative to the "
        "current 409A value means the options already have paper value.",
    ),
    (
        ("share_price_409a", "current_share_price"),
        "What is the current 409A per-share valuation, and when was it set?",
        "The 409A is an independent fair-market valuation of the company's "
        "common stock. It is what your strike price is usually based on, so a "
        "fresh 409A means the strike reflects a recent valuation. An old 409A "
        "(or one set right before a fundraise) can make the numbers stale.",
    ),
    (
        ("valuation_409a_date", "409a_date"),
        "When was the last 409A valuation done?",
        "409A valuations are typically refreshed yearly or after major events. "
        "If the valuation is old, the strike price and paper value may not "
        "reflect what the company is worth today.",
    ),
    (
        ("option_shares", "equity_shares", "shares"),
        "How many option shares are you being granted?",
        "The share count, not the dollar figure, is what you own. Combined "
        "with the fully-diluted share count it tells you your ownership "
        "percentage, and combined with the strike and 409A it tells you the "
        "current paper value.",
    ),
    (
        ("total_fully_diluted_shares", "fully_diluted_shares"),
        "What is the total fully-diluted share count (including all options and convertibles)?",
        "Your ownership percentage is your option shares divided by the total "
        "fully-diluted shares. Without this number a share grant is "
        "meaningless: 10,000 shares could be 1% or 0.001% of the company.",
    ),
    (
        ("cliff",),
        "Is there a vesting cliff, and what happens to unvested shares if you leave?",
        "Many startups use a 1-year cliff: you get nothing if you leave before "
        "a year, then a chunk vests at once. Unvested shares are forfeited when "
        "you leave, so the cliff matters a lot if the role might not last.",
    ),
    (
        ("equity_type",),
        "Are these ISOs or NSOs?",
        "Incentive stock options (ISOs) are for employees and can get favorable "
        "tax treatment if you meet holding periods; non-qualified stock options "
        "(NSOs) are taxed as ordinary income at exercise. The type changes the "
        "tax math, so confirm which one you are getting.",
    ),
    (
        ("post_termination_window", "exercise_window"),
        "How long after leaving do I have to exercise vested options?",
        "The standard window is 90 days: leave the company and you must buy "
        "your vested shares (paying the strike, possibly a large cash outlay) "
        "or lose them. Some companies extend this to years, which removes a "
        "lot of pressure.",
    ),
    (
        ("funding_round", "dilution_history", "last_valuation"),
        "What is the funding and dilution history, and are more rounds planned?",
        "Every fundraise issues new shares and dilutes existing holders, "
        "including you. Past dilution plus planned future rounds tell you how "
        "much smaller your ownership percentage is likely to get before any "
        "exit.",
    ),
]

_CASH_FIELDS = (
    ("base", "annual base salary"),
    ("bonus_target_pct", "target bonus %"),
    ("sign_on", "sign-on bonus"),
    ("benefits_value", "benefits value"),
)


def _known_values_block(offer: dict) -> list[str]:
    """Lines describing stored values, referencing only what the user entered."""
    lines = []
    strike = _get(offer, "strike_price")
    shares = _get(offer, "option_shares", "equity_shares", "shares")
    price409 = _get(offer, "share_price_409a", "current_share_price")
    fd = _get(offer, "total_fully_diluted_shares", "fully_diluted_shares")
    eq_type = _get(offer, "equity_type")
    cliff = _get(offer, "cliff")
    window = _get(offer, "post_termination_window", "exercise_window")
    vest = _get(offer, "vest_schedule")
    vest_years = _get(offer, "vest_years")
    date409 = _get(offer, "valuation_409a_date", "409a_date")

    if shares is not None:
        lines.append(f"- Option shares granted: {_fmt_shares(shares)}")
    if strike is not None:
        lines.append(f"- Strike price: {_fmt(strike)} per share")
    if price409 is not None:
        when = f" (409A dated {date409})" if date409 is not None else ""
        lines.append(f"- Current 409A per-share value: {_fmt(price409)}{when}")
    if fd is not None:
        lines.append(f"- Fully-diluted shares outstanding: {_fmt_shares(fd)}")
    if eq_type is not None:
        lines.append(f"- Equity type on record: {eq_type}")
    if vest is not None:
        lines.append(f"- Vesting schedule on record: {vest}")
    elif vest_years is not None:
        lines.append(f"- Vesting period on record: {vest_years} years (schedule not specified)")
    if cliff is not None:
        lines.append(f"- Cliff on record: {cliff}")
    if window is not None:
        lines.append(f"- Post-termination exercise window on record: {window}")

    for field, label in _CASH_FIELDS:
        val = _get(offer, field)
        if val is not None:
            if field == "bonus_target_pct":
                lines.append(f"- {label}: {val}%")
            else:
                lines.append(f"- {label}: {_fmt(val)}")

    # Derived figures, only when every input is present.
    s = _num(shares, "option_shares") if shares is not None else None
    f = _num(fd, "total_fully_diluted_shares") if fd is not None else None
    k = _num(strike, "strike_price") if strike is not None else None
    p = _num(price409, "share_price_409a") if price409 is not None else None
    if s is not None and f is not None and f > 0:
        lines.append(f"- Implied ownership: {s / f * 100:.3f}% of fully-diluted shares")
    if s is not None and k is not None and p is not None:
        paper = s * (p - k)
        if paper > 0:
            lines.append(
                f"- Current paper value at the stored 409A: {_fmt(paper)} "
                f"(shares x (409A - strike), before taxes)")
        else:
            lines.append(
                "- Current paper value at the stored 409A: $0 (strike is at or "
                "above the 409A, so the options have no paper value yet)")
    return lines


def equity_notes(offer_id: int, path=None) -> str:
    """Build the startup equity due-diligence notes for one stored offer.

    Only values already on the offer record are referenced; every missing
    checklist item becomes an explicit "ask the company" prompt.
    """
    offer = _offer_by_id(offer_id, path=path)
    company = offer.get("company", "")
    role = offer.get("role", "")
    lines = [
        f"Startup equity notes: {company} - {role} (offer #{offer_id})",
        f"Generated {date.today().isoformat()}",
        "",
        "## What the offer record already says",
        "",
    ]
    known = _known_values_block(offer)
    if known:
        lines.extend(known)
    else:
        lines.append("- Nothing equity-specific stored yet: no strike price, share "
                     "counts, 409A, or vesting details on this record.")
    lines += ["", "## Checklist: ask the company", ""]
    for fields, question, explainer in _EQUITY_TERMS:
        if _get(offer, *fields) is not None:
            status = "on record (see above)"
        else:
            status = "ASK THE COMPANY"
        lines += [
            f"### {question} [{status}]",
            "",
            explainer,
            "",
        ]
    lines += [
        "## How to use this",
        "",
        "- Fill in the missing items above with the recruiter or offer letter, "
        "then re-run this command to see the implied ownership and paper value.",
        "- Compare the answers across offers with "
        "`python -m candid offer compare-startup --offer-a ID --offer-b ID`.",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. cash-vs-equity modeler
# ---------------------------------------------------------------------------

HORIZON_YEARS = 4

#: Documented, user-editable growth assumptions (annual equity appreciation).
GROWTH_PRESETS: dict[str, float] = {
    "low": 0.00,   # equity stays flat
    "base": 0.15,  # 15%/yr
    "high": 0.40,  # 40%/yr
}

ASSUMPTION_NOTES = [
    "Growth rates are assumptions you set, not predictions. Presets: low 0%/yr, "
    "base 15%/yr, high 40%/yr; override any of them with --growth-rate (a "
    "decimal, e.g. 0.25 for 25%/yr).",
    "Cash comp (base, bonus, benefits) is held flat across the horizon; the "
    "sign-on is counted once in year 1.",
    "Equity vesting in year y is valued at its grant value times (1 + r)^y, "
    "where r is the annual growth assumption. For options this assumes the "
    "stored equity value is the current paper value (shares x (409A - strike)) "
    "or the grant value the company quoted.",
    "Vesting follows the stored vest schedule when present, otherwise "
    "straight-line over the vesting years. Years beyond the vesting period "
    "vest nothing; only the first 4 years are modeled.",
    "No taxes, no dilution from future fundraises, and no probability of the "
    "company failing are modeled. Real startup equity is far riskier than "
    "these numbers suggest.",
]


def _vest_per_year(offer: dict) -> list[float]:
    """Equity grant value vesting in each modeled year (len == HORIZON_YEARS)."""
    equity_total = _num(offer.get("equity_total"), "equity_total") or 0.0
    vest_years = int(offer.get("vest_years") or 4)
    if vest_years < 1:
        raise StartupEquityError("vest_years must be >= 1.")
    schedule = str(offer.get("vest_schedule") or "").strip()
    if schedule:
        parts = [float(p) for p in schedule.replace("%", "").split("/")]
        if abs(sum(parts) - 100) > 0.5:
            raise StartupEquityError(
                f"vest_schedule '{schedule}' should sum to 100.")
        if len(parts) != vest_years:
            raise StartupEquityError(
                f"vest_schedule has {len(parts)} parts but vest_years is "
                f"{vest_years}; make them match.")
        pcts = [p / 100 for p in parts]
    else:
        pcts = [1 / vest_years] * vest_years
    vested = [equity_total * p for p in pcts]
    vested += [0.0] * (HORIZON_YEARS - len(vested))
    return vested[:HORIZON_YEARS]


def _cash_per_year(offer: dict) -> list[float]:
    """Cash comp per modeled year: sign-on lands fully in year 1."""
    base = _num(offer.get("base"), "base") or 0.0
    bonus_pct = _num(offer.get("bonus_target_pct"), "bonus_target_pct") or 0.0
    bonus_first = _num(offer.get("bonus_first_year_guaranteed"),
                       "bonus_first_year_guaranteed")
    sign_on = _num(offer.get("sign_on"), "sign_on") or 0.0
    benefits = _num(offer.get("benefits_value"), "benefits_value") or 0.0
    target_bonus = base * bonus_pct / 100
    first_year_bonus = bonus_first if bonus_first else target_bonus
    year1 = base + first_year_bonus + sign_on + benefits
    later = base + target_bonus + benefits
    return [year1] + [later] * (HORIZON_YEARS - 1)


def model_offer(offer: dict, rate: float) -> dict:
    """Year-by-year comp for one offer at annual equity growth ``rate``.

    Returns {"years": [...], "cash_total": x, "equity_total": y, "grand_total": z}.
    Year y (1-based): cash_y + vested_y * (1 + rate)^y.
    """
    cash = _cash_per_year(offer)
    vest = _vest_per_year(offer)
    years = []
    for y in range(1, HORIZON_YEARS + 1):
        eq = vest[y - 1] * (1 + rate) ** y
        years.append({
            "year": y,
            "cash": round(cash[y - 1], 2),
            "equity": round(eq, 2),
            "total": round(cash[y - 1] + eq, 2),
        })
    cash_total = round(sum(cash), 2)
    equity_total = round(sum(w["equity"] for w in years), 2)
    return {
        "years": years,
        "cash_total": cash_total,
        "equity_total": equity_total,
        "grand_total": round(cash_total + equity_total, 2),
    }


def find_breakeven(offer_a: dict, offer_b: dict,
                   lo: float = -0.99, hi: float = 5.0) -> float | None:
    """Annual growth rate r where the two 4-year totals are equal.

    Bisection on f(r) = total_a(r) - total_b(r), which is continuous in r.
    Returns None when no sign change exists in [lo, hi] (one offer wins at
    every modeled growth rate).
    """
    def diff(r: float) -> float:
        return (model_offer(offer_a, r)["grand_total"]
                - model_offer(offer_b, r)["grand_total"])

    fa, fb = diff(lo), diff(hi)
    if abs(fa) < 1e-9:
        return lo
    if fa * fb > 0:
        return None
    for _ in range(120):
        mid = (lo + hi) / 2
        fm = diff(mid)
        if abs(fm) < 1e-9:
            return mid
        if fa * fm <= 0:
            hi, fb = mid, fm
        else:
            lo, fa = mid, fm
    return (lo + hi) / 2


def compare_startup(offer_a_id: int, offer_b_id: int,
                    growth: str = "base", growth_rate: float | None = None,
                    path=None) -> dict:
    """Model two offers' 4-year comp under growth assumptions.

    ``growth`` picks a documented preset; ``growth_rate`` (decimal, e.g. 0.25)
    overrides it with a custom assumption.
    """
    if offer_a_id == offer_b_id:
        raise StartupEquityError("offer-a and offer-b must be different offers.")
    offer_a = _offer_by_id(offer_a_id, path=path)
    offer_b = _offer_by_id(offer_b_id, path=path)

    if growth_rate is not None:
        if growth_rate < -0.99:
            raise StartupEquityError(
                "growth_rate must be >= -0.99 (worse than -99%/yr is not modeled).")
        rate = growth_rate
        growth_label = f"custom {growth_rate * 100:.0f}%/yr (overrides preset)"
    else:
        if growth not in GROWTH_PRESETS:
            raise StartupEquityError(
                f"Unknown growth preset '{growth}'. Choose from: "
                f"{', '.join(sorted(GROWTH_PRESETS))}.")
        rate = GROWTH_PRESETS[growth]
        growth_label = f"{growth} ({rate * 100:.0f}%/yr)"

    modeled_a = model_offer(offer_a, rate)
    modeled_b = model_offer(offer_b, rate)

    scenarios = {}
    for name, r in GROWTH_PRESETS.items():
        ta = model_offer(offer_a, r)["grand_total"]
        tb = model_offer(offer_b, r)["grand_total"]
        scenarios[name] = {
            "rate": r,
            "a_total": ta,
            "b_total": tb,
            "leader": (_short(offer_a) if ta > tb else
                       _short(offer_b) if tb > ta else "tie"),
        }

    be = find_breakeven(offer_a, offer_b)
    # rate is kept unrounded in the payload (rate_pct is the display form) so
    # model_offer(rate) reproduces equal totals within cent-rounding.
    breakeven = ({"exists": True, "rate": be,
                  "rate_pct": f"{be * 100:.1f}%/yr"}
                 if be is not None else
                 {"exists": False,
                  "reason": "No break-even growth rate between -99%/yr and "
                            "+500%/yr: one offer leads at every modeled rate."})

    return {
        "offer_a": _short(offer_a),
        "offer_b": _short(offer_b),
        "generated": date.today().isoformat(),
        "assumptions": {
            "horizon_years": HORIZON_YEARS,
            "growth_presets": {k: v for k, v in GROWTH_PRESETS.items()},
            "selected": growth_label,
            "selected_rate": rate,
            "notes": ASSUMPTION_NOTES,
        },
        "years": [
            {
                "year": ya["year"],
                "a_cash": ya["cash"], "a_equity": ya["equity"], "a_total": ya["total"],
                "b_cash": yb["cash"], "b_equity": yb["equity"], "b_total": yb["total"],
            }
            for ya, yb in zip(modeled_a["years"], modeled_b["years"])
        ],
        "selected_totals": {
            "a_cash_total": modeled_a["cash_total"],
            "a_equity_total": modeled_a["equity_total"],
            "a_grand_total": modeled_a["grand_total"],
            "b_cash_total": modeled_b["cash_total"],
            "b_equity_total": modeled_b["equity_total"],
            "b_grand_total": modeled_b["grand_total"],
        },
        "scenarios": scenarios,
        "breakeven": breakeven,
        "disclaimer": DISCLAIMER,
    }


def _short(offer: dict) -> str:
    return f"{offer.get('company', '')} (offer #{offer.get('id')})"


def render_compare(result: dict) -> str:
    """Human-readable rendering of a compare_startup result."""
    a, b = result["offer_a"], result["offer_b"]
    asm = result["assumptions"]
    lines = [
        f"Startup cash-vs-equity model: {a} vs {b}",
        f"Generated {result['generated']}",
        "",
        f"Growth assumption (selected): {asm['selected']}",
        "",
        "## Year-by-year (selected assumption)",
        "",
        f"{'Year':<6}{'A cash':>12}{'A equity':>12}{'A total':>12}"
        f"{'B cash':>12}{'B equity':>12}{'B total':>12}",
        "-" * 78,
    ]
    for y in result["years"]:
        lines.append(
            f"{y['year']:<6}{_fmt(y['a_cash']):>12}{_fmt(y['a_equity']):>12}"
            f"{_fmt(y['a_total']):>12}{_fmt(y['b_cash']):>12}"
            f"{_fmt(y['b_equity']):>12}{_fmt(y['b_total']):>12}")
    lines.append("-" * 78)
    t = result["selected_totals"]
    lines.append(
        f"{'4-yr':<6}{_fmt(t['a_cash_total']):>12}{_fmt(t['a_equity_total']):>12}"
        f"{_fmt(t['a_grand_total']):>12}{_fmt(t['b_cash_total']):>12}"
        f"{_fmt(t['b_equity_total']):>12}{_fmt(t['b_grand_total']):>12}")
    lines += ["", "## 4-year totals per growth scenario", ""]
    lines.append(f"{'Scenario':<10}{'Rate':>10}{'A total':>14}{'B total':>14}{'Leader':>28}")
    lines.append("-" * 76)
    for name in ("low", "base", "high"):
        s = result["scenarios"][name]
        lines.append(
            f"{name:<10}{s['rate'] * 100:>9.0f}%{_fmt(s['a_total']):>14}"
            f"{_fmt(s['b_total']):>14}{s['leader']:>28}")
    lines += ["", "## Break-even growth rate", ""]
    be = result["breakeven"]
    if be["exists"]:
        lines.append(
            f"Both offers total the same over 4 years at about {be['rate_pct']} "
            f"annual equity growth. Below that rate the cash-heavier offer wins; "
            f"above it the equity-heavier offer wins.")
    else:
        lines.append(be["reason"])
    lines += ["", "## Assumptions (all editable, none are predictions)", ""]
    for note in asm["notes"]:
        lines.append(f"- {note}")
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI handlers (argparse wiring lives in __main__.py; see worker report)
# ---------------------------------------------------------------------------

def cmd_offer_equity_notes(a) -> None:
    """Handler for `offer equity-notes --offer-id ID`."""
    print(equity_notes(a.offer_id))


def cmd_offer_compare_startup(a) -> None:
    """Handler for `offer compare-startup --offer-a ID --offer-b ID ...`."""
    result = compare_startup(a.offer_a, a.offer_b,
                             growth=getattr(a, "growth", "base"),
                             growth_rate=getattr(a, "growth_rate", None))
    if getattr(a, "json", False):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_compare(result))
