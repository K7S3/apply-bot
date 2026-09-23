"""Signing bonus vs base trade-off calculator.

Answers the classic negotiation question: "They won't move on base — how
much sign-on (or equity) do I need to say yes?" Everything is driven by
numbers the user enters; nothing is scraped or estimated from the network.

Features
--------
1. bonus_raise_equivalence / base_raise_equivalence
   How much sign-on equals a given annual base raise over N years, and
   vice versa (simple straight-line, or discounted with a rate).
2. amortize_sign_on
   The annualized value of a sign-on spread over N years (simple or
   present-value discounted).
3. multi_year_projection
   Year-by-year cash + equity vesting cash flow for an offer, with an
   assumed annual raise and a bonus-attainment factor.
4. cumulative_value
   Running totals of a projection (for "what do I pocket by year 3?").
5. present_value
   NPV of any cash-flow schedule at a chosen discount rate.
6. breakeven_years
   Given two offers that differ in base vs sign-on, after how many years
   does the higher-base offer overtake the higher-sign-on offer?
7. bonus_vs_sign_on
   Guaranteed sign-on vs a probabilistic target bonus: expected-value
   comparison with a simple risk framing.
8. tax_timing_notes
   Notes on how the *timing* of income (a lump sign-on in year 1 vs
   spread-out base raises) interacts with marginal tax brackets. Rough
   estimate, not advice.
9. counter_bridge_amount
   "Base is $X/yr below my target — what sign-on ask bridges the gap
   over Y years?" Concrete counter-ask number.
10. compare_tradeoffs
    Multi-year side-by-side comparison of two offers with per-year table,
    cumulative totals, NPV, breakeven, and plain-language verdicts.
11. render_report / export_report
    Text and markdown versions of a full trade-off report.

All money is USD; functions take and return floats and dicts. Raises
``TradeoffError`` on invalid input.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from candid import config as C

DISCLAIMER = (
    "_This is arithmetic on numbers you entered, not tax or financial "
    "advice. Tax treatment depends on jurisdiction, filing status, and the "
    "current IRS tables — talk to a tax pro before deciding._"
)


class TradeoffError(Exception):
    """Raised for invalid trade-off inputs."""


def _num(x, name: str) -> float:
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        raise TradeoffError(f"Expected a dollar amount for {name}, got '{x}'.")
    return v


def _positive(x, name: str) -> int:
    try:
        v = int(x)
    except (TypeError, ValueError):
        raise TradeoffError(f"Expected an integer for {name}, got '{x}'.")
    if v < 1:
        raise TradeoffError(f"{name} must be >= 1.")
    return v


def _rate(x) -> float:
    v = _num(x, "discount rate")
    if v < 0 or v >= 1:
        raise TradeoffError("Discount rate must be between 0 and 1 (e.g. 0.05).")
    return v


def annuity_factor(years: int, discount_rate: float) -> float:
    """Present-value factor of a $1/year annuity: (1 - (1+d)^-N) / d.

    Falls back to straight-line N when the rate is 0.
    """
    years = _positive(years, "years")
    d = _rate(discount_rate)
    if d == 0:
        return float(years)
    return (1 - (1 + d) ** -years) / d


def bonus_raise_equivalence(annual_raise: float, years: int,
                            discount_rate: float = 0.0) -> dict:
    """1. What sign-on equals an extra ``annual_raise`` of base every year?

    Simple math: raise x years. With a discount rate: present value of the
    raise annuity — money today is worth more than money later.
    """
    r = _num(annual_raise, "annual raise")
    if r < 0:
        raise TradeoffError("annual raise must be >= 0.")
    factor = annuity_factor(years, discount_rate)
    return {
        "annual_raise": r,
        "years": _positive(years, "years"),
        "discount_rate": _rate(discount_rate),
        "equivalent_sign_on": round(r * factor, 2),
        "simple_sign_on": round(r * _positive(years, "years"), 2),
        "explanation": (
            f"A ${r:,.0f}/yr raise for {years} years equals a "
            f"${r * factor:,.0f} sign-on at a {discount_rate:.1%} discount rate "
            f"(${r * years:,.0f} undiscounted)."
        ),
    }


def base_raise_equivalence(sign_on: float, years: int,
                           discount_rate: float = 0.0) -> dict:
    """Inverse of bonus_raise_equivalence: what annual raise is a sign-on worth?"""
    s = _num(sign_on, "sign-on")
    if s < 0:
        raise TradeoffError("sign-on must be >= 0.")
    years = _positive(years, "years")
    d = _rate(discount_rate)
    factor = annuity_factor(years, d)
    return {
        "sign_on": s,
        "years": years,
        "discount_rate": d,
        "equivalent_annual_raise": round(s / factor, 2),
        "simple_annual_raise": round(s / years, 2),
        "explanation": (
            f"A ${s:,.0f} sign-on is worth ${s / factor:,.0f}/yr over {years} "
            f"years at a {d:.1%} discount rate (${s / years:,.0f}/yr "
            "undiscounted)."
        ),
    }


def amortize_sign_on(sign_on: float, years: int,
                     discount_rate: float = 0.0) -> dict:
    """2. Annualized value of a sign-on spread over N years."""
    s = _num(sign_on, "sign-on")
    if s < 0:
        raise TradeoffError("sign-on must be >= 0.")
    years = _positive(years, "years")
    d = _rate(discount_rate)
    factor = annuity_factor(years, d)
    return {
        "sign_on": s,
        "years": years,
        "discount_rate": d,
        "annualized_value": round(s / factor, 2),
        "total_value": round(s, 2),
        "note": (
            f"${s:,.0f} up front is equivalent to ${s / factor:,.0f}/yr for "
            f"{years} years at {d:.1%} (undiscounted: ${s / years:,.0f}/yr)."
        ),
    }


def multi_year_projection(base: float, bonus_target_pct: float, sign_on: float,
                          annual_equity: float, benefits: float, years: int,
                          raise_pct: float = 3.0,
                          bonus_attainment: float = 1.0,
                          equity_growth_pct: float = 0.0) -> list[dict]:
    """3. Year-by-year cash + vesting projection for one offer.

    - base grows at ``raise_pct`` %/yr (compounding)
    - bonus = base x target% x attainment each year
    - sign-on lands entirely in year 1
    - equity vests ``annual_equity``/yr, growing at ``equity_growth_pct`` %/yr
    """
    base = _num(base, "base")
    bonus_pct = _num(bonus_target_pct, "bonus target pct")
    if bonus_pct < 0:
        raise TradeoffError("bonus target pct must be >= 0.")
    sign_on = _num(sign_on, "sign-on")
    equity = _num(annual_equity, "annual equity")
    benefits = _num(benefits, "benefits")
    years = _positive(years, "years")
    raise_r = _num(raise_pct, "raise pct") / 100
    if raise_r < -1:
        raise TradeoffError("raise pct cannot be below -100.")
    attainment = _num(bonus_attainment, "bonus attainment")
    if attainment < 0 or attainment > 1.5:
        raise TradeoffError("bonus attainment should be between 0 and 1.5.")
    eq_growth = _num(equity_growth_pct, "equity growth pct") / 100

    rows = []
    for y in range(1, years + 1):
        base_y = base * (1 + raise_r) ** (y - 1)
        bonus_y = base_y * bonus_pct / 100 * attainment
        equity_y = equity * (1 + eq_growth) ** (y - 1)
        sign_on_y = sign_on if y == 1 else 0.0
        total = base_y + bonus_y + equity_y + benefits + sign_on_y
        rows.append({
            "year": y,
            "base": round(base_y, 2),
            "bonus": round(bonus_y, 2),
            "equity_vest": round(equity_y, 2),
            "benefits": round(benefits, 2),
            "sign_on": round(sign_on_y, 2),
            "total": round(total, 2),
        })
    return rows


def cumulative_value(projection: list[dict]) -> list[dict]:
    """4. Running cumulative totals alongside a projection."""
    cum = 0.0
    out = []
    for row in projection:
        cum += row.get("total", 0) or 0
        out.append({"year": row.get("year"), "total": row.get("total"),
                    "cumulative": round(cum, 2)})
    return out


def present_value(cashflows: list[float], discount_rate: float = 0.05) -> float:
    """5. NPV of a cash-flow schedule: sum cf[t] / (1+d)^t.

    ``cashflows`` is a list of year-1..N amounts (or a projection list,
    whose 'total' column is used).
    """
    d = _rate(discount_rate)
    total = 0.0
    for t, cf in enumerate(cashflows, start=1):
        amount = cf["total"] if isinstance(cf, dict) else cf
        total += _num(amount, "cash flow") / (1 + d) ** t
    return round(total, 2)


def breakeven_years(base_a: float, sign_on_a: float,
                    base_b: float, sign_on_b: float) -> dict:
    """6. When does the higher-base offer overtake the higher-sign-on offer?

    Solves cumulative cash (base x n + sign-on). Returns the fractional
    breakeven year, or None if the curves never cross (e.g. equal bases).
    """
    ba, sa = _num(base_a, "base_a"), _num(sign_on_a, "sign_on_a")
    bb, sb = _num(base_b, "base_b"), _num(sign_on_b, "sign_on_b")
    if ba == bb:
        if sa == sb:
            return {"breakeven_year": 0.0, "crosses": True,
                    "note": "Identical cash profiles — no trade-off to model."}
        leader = "A" if sa > sb else "B"
        return {"breakeven_year": None, "crosses": False,
                "note": f"Equal bases: offer {leader}'s larger sign-on wins "
                        "every year; the curves never cross."}
    # Identify higher-base offer (h) and higher-sign-on offer (l).
    if ba > bb:
        h, l, base_h, base_l = "A", "B", ba, bb
        sign_h, sign_l = sa, sb
    else:
        h, l, base_h, base_l = "B", "A", bb, ba
        sign_h, sign_l = sb, sa
    if sign_l <= sign_h:
        return {"breakeven_year": 0.0, "crosses": True,
                "note": f"Offer {h} has both the higher base and the "
                        f"higher-or-equal sign-on — it wins from day one."}
    year = (sign_l - sign_h) / (base_h - base_l)
    return {
        "breakeven_year": round(year, 2),
        "crosses": True,
        "higher_base_offer": h,
        "higher_sign_on_offer": l,
        "note": (
            f"Offer {h}'s base advantage of ${base_h - base_l:,.0f}/yr makes "
            f"up offer {l}'s ${sign_l - sign_h:,.0f} sign-on lead after about "
            f"{year:.1f} years. Stay less than that and {l} pays more; stay "
            f"longer and {h} pulls ahead."
        ),
    }


def bonus_vs_sign_on(sign_on: float, bonus_target: float,
                     attainment: float = 0.8) -> dict:
    """7. Guaranteed sign-on vs a probabilistic target bonus.

    ``attainment`` is your expected payout as a fraction of target
    (e.g. 0.8 if bonuses usually pay ~80%). Sign-on is certain money;
    the bonus depends on company performance, your rating, and staying
    through payout.
    """
    s = _num(sign_on, "sign-on")
    b = _num(bonus_target, "bonus target")
    if s < 0 or b < 0:
        raise TradeoffError("amounts must be >= 0.")
    a = _num(attainment, "attainment")
    if a < 0 or a > 1.5:
        raise TradeoffError("attainment should be between 0 and 1.5.")
    expected = b * a
    winner = "sign-on" if s >= expected else "target bonus"
    return {
        "sign_on_guaranteed": round(s, 2),
        "bonus_target": round(b, 2),
        "attainment": a,
        "bonus_expected_value": round(expected, 2),
        "difference": round(s - expected, 2),
        "better_expected_value": winner,
        "risk_note": (
            f"The sign-on is certain; the bonus has an expected value of "
            f"${expected:,.0f} at {a:.0%} attainment. A guaranteed "
            f"${s:,.0f} beats a bonus target of ${b:,.0f} whenever attainment "
            f"would fall below {s / b:.0%}." if b else
            "No bonus target to compare against."
        ),
    }


def tax_timing_notes(yearly_income: list[float]) -> list[str]:
    """8. Timing notes for a yearly income schedule.

    Flags the core trade-off: a lump sign-on concentrates income in year 1
    (possibly spiking your marginal bracket), while base raises spread it.
    Rough estimate, not advice.
    """
    if not yearly_income:
        raise TradeoffError("yearly_income must be non-empty.")
    incomes = [_num(x, "yearly income") for x in yearly_income]
    notes = []
    avg = sum(incomes) / len(incomes)
    first, peak = incomes[0], max(incomes)
    if len(incomes) > 1 and first > avg * 1.25:
        notes.append(
            f"Year 1 income (${first:,.0f}) is well above your {len(incomes)}-yr "
            f"average (${avg:,.0f}) — the lump sign-on concentrates tax in year "
            "1 and can push that year's income into a higher marginal bracket."
        )
    if peak > incomes[-1] * 1.25:
        notes.append(
            f"Income peaks mid-schedule (${peak:,.0f}) then falls — a large "
            "year-1 vest or sign-on can make your first year your "
            "highest-taxed year even if later years pay more base."
        )
    notes.append(
        "Rough timing principle (estimate, not advice): in the US, base "
        "salary, cash bonuses, and sign-ons are taxed as ordinary income when "
        "paid, and RSUs when they vest. Spreading income across years can "
        "keep more of it in lower brackets; a big lump sum does the opposite."
    )
    notes.append(
        "If the sign-on is paid in January of your start year vs December, "
        "it lands in different tax years — the payment date, not the offer "
        "date, controls which year's return it hits."
    )
    return notes


def counter_bridge_amount(base_gap_annual: float, years: int,
                          discount_rate: float = 0.05) -> dict:
    """9. Base is $X/yr below target — what sign-on bridges the gap?

    Ask = present value of the base shortfall over the years you expect to
    stay. Gives you a concrete, defensible counter number.
    """
    gap = _num(base_gap_annual, "base gap")
    if gap < 0:
        raise TradeoffError("base gap must be >= 0 (target base - offered base).")
    years = _positive(years, "years")
    d = _rate(discount_rate)
    pv_ask = gap * annuity_factor(years, d)
    simple_ask = gap * years
    return {
        "base_gap_annual": gap,
        "years": years,
        "discount_rate": d,
        "suggested_sign_on_ask": round(pv_ask, 2),
        "undiscounted_gap_total": round(simple_ask, 2),
        "script": (
            f"\"Base is ${gap:,.0f}/yr below my target. If base is capped by "
            f"band, a ${pv_ask:,.0f} sign-on closes that gap over {years} "
            f"years at {d:.0%} — the undiscounted total is "
            f"${simple_ask:,.0f}.\""
        ),
        "negotiation_note": (
            "Frame the sign-on as the bridge, not a bonus: it costs them "
            "once, while a base increase compounds every year. That asymmetry "
            "is why companies often prefer to move on sign-on."
        ),
    }


def compare_tradeoffs(offer_a: dict, offer_b: dict, years: int = 4,
                      discount_rate: float = 0.05, raise_pct: float = 3.0,
                      attainment: float = 1.0) -> dict:
    """10. Multi-year side-by-side of two offers with trade-off verdicts.

    Each offer dict may carry: company, base, bonus_target_pct, sign_on,
    annual_equity (or equity_total/vest_years), benefits_value.
    """
    for name, o in (("A", offer_a), ("B", offer_b)):
        if not o.get("company"):
            raise TradeoffError(f"Offer {name} needs a company name.")
    years = _positive(years, "years")
    d = _rate(discount_rate)

    def _proj(o: dict) -> list[dict]:
        equity = _num(o.get("annual_equity"), "annual equity")
        if not equity and o.get("equity_total"):
            vy = int(o.get("vest_years") or 4)
            equity = _num(o.get("equity_total"), "equity total") / max(vy, 1)
        return multi_year_projection(
            _num(o.get("base"), "base"),
            _num(o.get("bonus_target_pct"), "bonus target pct"),
            _num(o.get("sign_on"), "sign-on"),
            equity,
            _num(o.get("benefits_value"), "benefits"),
            years, raise_pct=raise_pct, bonus_attainment=attainment,
        )

    pa, pb = _proj(offer_a), _proj(offer_b)
    cum_a, cum_b = cumulative_value(pa), cumulative_value(pb)
    npv_a = present_value(pa, d)
    npv_b = present_value(pb, d)
    total_a = cum_a[-1]["cumulative"]
    total_b = cum_b[-1]["cumulative"]
    be = breakeven_years(
        _num(offer_a.get("base"), "base"), _num(offer_a.get("sign_on"), "sign-on"),
        _num(offer_b.get("base"), "base"), _num(offer_b.get("sign_on"), "sign-on"),
    )
    ca, cb = offer_a["company"], offer_b["company"]
    winner_total = ca if total_a >= total_b else cb
    winner_npv = ca if npv_a >= npv_b else cb
    verdicts = [
        f"Over {years} years, {winner_total} pays ${abs(total_a - total_b):,.0f} "
        f"more in total (${max(total_a, total_b):,.0f} vs ${min(total_a, total_b):,.0f}).",
        f"On present value at {d:.0%}, {winner_npv} leads by "
        f"${abs(npv_a - npv_b):,.0f}.",
        be["note"],
    ]
    if winner_total != winner_npv:
        verdicts.append(
            "Total and present-value disagree: the higher total is back-loaded "
            "(more base/equity later), the NPV winner pays more up front. "
            "Pick based on how long you plan to stay."
        )
    return {
        "offer_a": ca, "offer_b": cb, "years": years,
        "discount_rate": d, "raise_pct": _num(raise_pct, "raise pct"),
        "attainment": _num(attainment, "attainment"),
        "projection_a": pa, "projection_b": pb,
        "cumulative_a": cum_a, "cumulative_b": cum_b,
        "total_a": round(total_a, 2), "total_b": round(total_b, 2),
        "npv_a": npv_a, "npv_b": npv_b,
        "breakeven": be,
        "verdicts": verdicts,
    }


def _fmt(x) -> str:
    try:
        return f"${float(x or 0):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_report(comp: dict) -> str:
    """Text report for a compare_tradeoffs result."""
    ca, cb = comp["offer_a"], comp["offer_b"]
    years = comp["years"]
    w = 22
    lines = [
        f"Sign-on vs base trade-off: {ca} vs {cb} ({years} years)",
        "=" * 60,
        "",
        "Year-by-year total comp (cash + vesting + benefits):",
        f"{'Year':<8}{ca[:w - 2]:<{w}}{cb[:w - 2]:<{w}}",
        "-" * (8 + 2 * w),
    ]
    for ra, rb in zip(comp["projection_a"], comp["projection_b"]):
        lines.append(f"{ra['year']:<8}{_fmt(ra['total']):<{w}}{_fmt(rb['total']):<{w}}")
    lines += [
        "-" * (8 + 2 * w),
        f"{'Cumulative':<8}{_fmt(comp['total_a']):<{w}}{_fmt(comp['total_b']):<{w}}",
        f"{'Present value':<8}{_fmt(comp['npv_a']):<{w}}{_fmt(comp['npv_b']):<{w}}",
        "",
        "Year 1 detail:",
    ]
    for key, label in (("base", "Base"), ("sign_on", "Sign-on"),
                       ("bonus", "Bonus"), ("equity_vest", "Equity vest"),
                       ("benefits", "Benefits")):
        ra, rb = comp["projection_a"][0], comp["projection_b"][0]
        lines.append(f"  {label:<12}{_fmt(ra[key]):<{w}}{_fmt(rb[key]):<{w}}")
    lines += ["", "Verdicts:"]
    lines += [f"  - {v}" for v in comp["verdicts"]]
    lines += ["", "Tax timing notes:"]
    incomes = [r["total"] for r in comp["projection_a"]]
    lines += [f"  - {n}" for n in tax_timing_notes(incomes)]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def export_report(comp: dict, path: str | Path | None = None) -> Path:
    """11. Write the trade-off comparison as markdown. Returns saved path."""
    if path is None:
        d = C.DATA_DIR / "tradeoff_reports"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{date.today().isoformat()}_tradeoff.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    ca, cb, years = comp["offer_a"], comp["offer_b"], comp["years"]
    lines = [
        f"# Sign-on vs base trade-off: {ca} vs {cb}",
        "",
        f"*Generated {date.today().isoformat()} · {years}-year horizon · "
        f"discount rate {comp['discount_rate']:.0%} · raise "
        f"{comp['raise_pct']:.1f}%/yr · bonus attainment "
        f"{comp['attainment']:.0%}*",
        "",
        f"| Year | {ca} total | {cb} total |",
        "| --- | --- | --- |",
    ]
    for ra, rb in zip(comp["projection_a"], comp["projection_b"]):
        lines.append(f"| {ra['year']} | {_fmt(ra['total'])} | {_fmt(rb['total'])} |")
    lines += [
        f"| **Cumulative** | **{_fmt(comp['total_a'])}** | **{_fmt(comp['total_b'])}** |",
        f"| **Present value** | **{_fmt(comp['npv_a'])}** | **{_fmt(comp['npv_b'])}** |",
        "",
        "## Verdicts",
        "",
    ]
    lines += [f"- {v}" for v in comp["verdicts"]]
    lines += ["", "## Tax timing notes", ""]
    incomes = [r["total"] for r in comp["projection_a"]]
    lines += [f"- {n}" for n in tax_timing_notes(incomes)]
    lines += ["", DISCLAIMER, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
