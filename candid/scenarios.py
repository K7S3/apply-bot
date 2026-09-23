"""Offer scenario modeler: what-if projections for competing offers.

Builds on the offer records stored by ``candid.offer`` (same fields, same
``candid_data/offers.json``). All math is deterministic and local; the only
inputs are the offer terms the user entered plus explicit what-if
assumptions (stock growth, raises, bonus payout, discount rate).

Features:
    1. Stock-growth presets (bear / flat / base / bull) plus custom rates.
    2. Year-by-year total-comp projections over N years (default 4).
    3. Vesting-schedule modeling, including cliff-style schedules.
    4. Sign-on amortization variants (1 / 2 / 4 years).
    5. Bonus payout scenarios (e.g. 80% / 100% / 120% of target).
    6. After-tax take-home estimates (illustrative brackets, not advice).
    7. NPV: discount future comp to present value for apples-to-apples.
    8. Break-even analysis: the year (or growth rate) at which one offer
       overtakes another.
    9. Sensitivity analysis: which assumption moves the 4-year total most.
    10. Scenario comparison matrix: offers x growth assumptions, rendered as
        a table and exportable to markdown with the assumptions spelled out.

Equity math: an RSU grant of ``equity_total`` dollars vesting ``pct`` of the
grant in year ``t`` is valued at ``equity_total * pct * (1 + growth) ** t``,
i.e. the grant-value slice compounded at the assumed annual stock growth to
the end of the vest year. This is identical to shares * grant_price *
(1+g)^t without needing a share price. Option grants are modeled the same
way on grant fair value and flagged as approximate, since real option value
depends on the strike price.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import offer as O


class ScenarioError(Exception):
    """Raised for invalid scenario inputs."""


#: Named annual stock-growth assumptions (fraction, e.g. 0.08 = 8%/yr).
GROWTH_PRESETS = {
    "bear": -0.10,
    "flat": 0.0,
    "base": 0.08,
    "bull": 0.20,
}

#: Illustrative 2026 federal brackets, single filer, rounded. Rough estimate
#: only - not tax advice. (upper bound, marginal rate)
TAX_BRACKETS = [
    (11_925, 0.10),
    (48_475, 0.12),
    (119_925, 0.22),
    (246_600, 0.24),
    (626_350, 0.32),
    (751_600, 0.35),
    (float("inf"), 0.37),
]

TAX_NOTE_SHORT = (
    "After-tax figures use illustrative 2026 federal single-filer brackets "
    "(rounded) and ignore state/city tax. Rough estimate, not tax advice."
)


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def parse_growth(spec: str | float | None) -> float:
    """Parse a growth assumption: preset name, '10%', '0.1', or a float."""
    if spec is None:
        return GROWTH_PRESETS["base"]
    if isinstance(spec, (int, float)):
        return float(spec)
    s = str(spec).strip().lower()
    if not s:
        return GROWTH_PRESETS["base"]
    if s in GROWTH_PRESETS:
        return GROWTH_PRESETS[s]
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1]
    try:
        v = float(s)
    except ValueError:
        raise ScenarioError(
            f"Unknown growth assumption '{spec}'. Use a preset "
            f"({', '.join(sorted(GROWTH_PRESETS))}), a decimal like 0.1, "
            f"or a percent like 10%.")
    return v / 100 if is_pct else v


def parse_growth_list(spec: str) -> list[tuple[str, float]]:
    """Parse 'bear,flat,base,bull' or '0,0.1,0.2' into (label, rate) pairs."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        label = part.lower() if part.lower() in GROWTH_PRESETS else part
        out.append((label, parse_growth(part)))
    if not out:
        raise ScenarioError("No growth scenarios given.")
    return out


def vesting_pcts(offer: dict, years: int) -> list[float]:
    """Per-year vest fractions for ``years`` years.

    Parses the offer's ``vest_schedule`` ("40/30/20/10"); a leading 0 encodes
    a cliff year (e.g. "0/34/33/33"). Falls back to straight-line vesting
    over ``vest_years`` when no schedule is set.
    """
    if years < 1:
        raise ScenarioError("years must be >= 1.")
    schedule = str(offer.get("vest_schedule") or "").strip()
    if schedule:
        parts = [float(p) for p in schedule.replace("%", "").split("/")]
        if abs(sum(parts) - 100) > 0.5:
            raise ScenarioError(
                f"vest_schedule '{schedule}' should sum to 100.")
        fracs = [p / 100 for p in parts]
    else:
        vest_years = int(offer.get("vest_years") or 4)
        if vest_years < 1:
            raise ScenarioError("vest_years must be >= 1.")
        fracs = [1 / vest_years] * vest_years
    fracs = (fracs + [0.0] * years)[:years]
    return [round(f, 6) for f in fracs]


def amortize_signon(offer: dict, over_years: int = 2) -> float:
    """Sign-on bonus spread evenly over ``over_years`` (default 2).

    Variants: 1 = cash in year 1, 2 = the comparison convention used by
    ``candid.offer.normalize``, 4 = spread across the grant window.
    """
    if over_years < 1:
        raise ScenarioError("over_years must be >= 1.")
    return _money(offer.get("sign_on")) / over_years


def bonus_for_year(offer: dict, year: int, payout: float = 1.0) -> float:
    """Year ``t`` bonus: guaranteed first-year bonus if set, else target * payout."""
    base = _money(offer.get("base"))
    target = base * _money(offer.get("bonus_target_pct")) / 100
    guaranteed = _money(offer.get("bonus_first_year_guaranteed"))
    if year == 1 and guaranteed:
        return guaranteed
    return target * payout


# ---------------------------------------------------------------------------
# core math
# ---------------------------------------------------------------------------

def after_tax(amount: float) -> float:
    """Illustrative after-tax take-home. Rough estimate, not tax advice."""
    remaining, tax = float(amount or 0), 0.0
    prev = 0.0
    for cap, rate in TAX_BRACKETS:
        if remaining <= 0:
            break
        taxable = min(remaining, cap - prev)
        tax += taxable * rate
        remaining -= taxable
        prev = cap
    return round(float(amount or 0) - tax, 2)


def npv(cashflows: list[float], rate: float) -> float:
    """Present value of year-end cashflows discounted at ``rate``."""
    if rate <= -1:
        raise ScenarioError("discount rate must be > -1.")
    return round(sum(cf / (1 + rate) ** t
                     for t, cf in enumerate(cashflows, start=1)), 2)


def project_comp(offer: dict, years: int = 4, growth: float = 0.08,
                 raise_pct: float = 0.03, bonus_payout: float = 1.0,
                 discount: float = 0.05) -> dict:
    """Year-by-year total-comp projection under explicit assumptions.

    Returns a JSON-serializable dict with per-year rows and totals. Equity
    slices are valued at the end-of-vest-year price, i.e. compounded at
    ``growth`` to the vest year.
    """
    if years < 1:
        raise ScenarioError("years must be >= 1.")
    base0 = _money(offer.get("base"))
    equity_total = _money(offer.get("equity_total"))
    benefits = _money(offer.get("benefits_value"))
    sign_on = _money(offer.get("sign_on"))
    vests = vesting_pcts(offer, years)

    rows = []
    for t in range(1, years + 1):
        base = base0 * (1 + raise_pct) ** (t - 1)
        bonus = bonus_for_year(offer, t, payout=bonus_payout)
        equity_vest = equity_total * vests[t - 1] * (1 + growth) ** t
        pre = base + bonus + (sign_on if t == 1 else 0.0) + equity_vest + benefits
        rows.append({
            "year": t,
            "base": round(base, 2),
            "bonus": round(bonus, 2),
            "sign_on": round(sign_on if t == 1 else 0.0, 2),
            "equity_vest": round(equity_vest, 2),
            "benefits": round(benefits, 2),
            "pre_tax": round(pre, 2),
            "after_tax": after_tax(pre),
        })
    pre_flows = [r["pre_tax"] for r in rows]
    totals = {
        "total_pre_tax": round(sum(pre_flows), 2),
        "total_after_tax": round(sum(r["after_tax"] for r in rows), 2),
        "total_equity_vest": round(sum(r["equity_vest"] for r in rows), 2),
        "npv": npv(pre_flows, discount),
    }
    assumptions = {
        "years": years,
        "growth": growth,
        "raise_pct": raise_pct,
        "bonus_payout": bonus_payout,
        "discount": discount,
    }
    note = None
    if str(offer.get("equity_type") or "").lower() == "options":
        note = ("Equity modeled on grant fair value; option upside depends on "
                "the strike price, so treat equity figures as approximate.")
    return {
        "company": offer.get("company", ""),
        "role": offer.get("role", ""),
        "level": offer.get("level", ""),
        "assumptions": assumptions,
        "years": rows,
        "totals": totals,
        "note": note,
    }


# ---------------------------------------------------------------------------
# comparisons
# ---------------------------------------------------------------------------

def breakeven_year(proj_a: dict, proj_b: dict) -> int | None:
    """First year in which A's cumulative pre-tax comp reaches B's.

    Returns None when A never catches B within the projected window.
    """
    cum_a = cum_b = 0.0
    for ra, rb in zip(proj_a["years"], proj_b["years"]):
        cum_a += ra["pre_tax"]
        cum_b += rb["pre_tax"]
        if cum_a >= cum_b:
            return ra["year"]
    return None


def breakeven_growth(offer_a: dict, offer_b: dict, years: int = 4,
                    raise_pct: float = 0.03, bonus_payout: float = 1.0,
                    lo: float = -0.5, hi: float = 1.0) -> float | None:
    """Stock-growth rate at which A's ``years``-year total ties B's.

    Bisection search; None when the gap never changes sign on [lo, hi]
    (one offer wins at every plausible growth rate).
    """
    def gap(g: float) -> float:
        ta = project_comp(offer_a, years=years, growth=g, raise_pct=raise_pct,
                          bonus_payout=bonus_payout)["totals"]["total_pre_tax"]
        tb = project_comp(offer_b, years=years, growth=g, raise_pct=raise_pct,
                          bonus_payout=bonus_payout)["totals"]["total_pre_tax"]
        return ta - tb

    glo, ghi = gap(lo), gap(hi)
    if glo == 0:
        return round(lo, 4)
    if ghi == 0:
        return round(hi, 4)
    if (glo > 0) == (ghi > 0):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if (gap(lo) > 0) == (gap(mid) > 0):
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def sensitivity(offer: dict, years: int = 4, growth: float = 0.08,
                raise_pct: float = 0.03, bonus_payout: float = 1.0,
                discount: float = 0.05) -> list[dict]:
    """One-at-a-time sensitivity: which assumption moves 4-yr NPV most?

    Each assumption is nudged down and up by a fixed delta; the swing in NPV
    is reported and the assumptions are ranked by |swing|.
    """
    base = {"years": years, "growth": growth, "raise_pct": raise_pct,
            "bonus_payout": bonus_payout, "discount": discount}

    def npv_with(**kw) -> float:
        kw2 = {**base, **kw}
        proj = project_comp(offer, **kw2)
        return proj["totals"]["npv"]

    perturbations = [
        ("growth", 0.05),
        ("raise_pct", 0.02),
        ("bonus_payout", 0.20),
        ("discount", 0.02),
    ]
    out = []
    for name, delta in perturbations:
        lo_v = npv_with(**{name: base[name] - delta})
        hi_v = npv_with(**{name: base[name] + delta})
        out.append({
            "assumption": name,
            "delta": delta,
            "npv_low": lo_v,
            "npv_high": hi_v,
            "swing": round(hi_v - lo_v, 2),
        })
    out.sort(key=lambda r: abs(r["swing"]), reverse=True)
    return out


def compare_matrix(offers: list[dict], growth_specs: str = "bear,flat,base,bull",
                   years: int = 4, raise_pct: float = 0.03,
                   bonus_payout: float = 1.0, discount: float = 0.05) -> dict:
    """Offers x growth-scenarios matrix of 4-year totals and NPVs."""
    cols = parse_growth_list(growth_specs)
    rows = []
    for offer in offers:
        cells = []
        for label, g in cols:
            proj = project_comp(offer, years=years, growth=g,
                                raise_pct=raise_pct, bonus_payout=bonus_payout,
                                discount=discount)
            cells.append({
                "growth_label": label,
                "growth": g,
                "total_pre_tax": proj["totals"]["total_pre_tax"],
                "total_after_tax": proj["totals"]["total_after_tax"],
                "npv": proj["totals"]["npv"],
            })
        best = max(cells, key=lambda c: c["npv"])
        rows.append({
            "company": offer.get("company", ""),
            "role": offer.get("role", ""),
            "level": offer.get("level", ""),
            "cells": cells,
            "best_scenario": best["growth_label"],
        })
    rows.sort(key=lambda r: max(c["npv"] for c in r["cells"]), reverse=True)
    return {
        "assumptions": {"years": years, "raise_pct": raise_pct,
                        "bonus_payout": bonus_payout, "discount": discount},
        "scenarios": [{"label": label, "growth": g} for label, g in cols],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _fmt(x) -> str:
    try:
        return f"${float(x or 0):,.0f}"
    except (TypeError, ValueError):
        return "-"


def render_projection(proj: dict) -> str:
    """Text table of the year-by-year projection."""
    a = proj["assumptions"]
    title = proj["company"]
    if proj.get("role"):
        title += f" - {proj['role']}"
    lines = [
        f"Offer scenario: {title}",
        (f"Assumptions: {a['years']}y horizon, stock growth "
         f"{a['growth'] * 100:.1f}%/yr, base raises {a['raise_pct'] * 100:.1f}%/yr, "
         f"bonus payout {a['bonus_payout'] * 100:.0f}% of target, "
         f"discount {a['discount'] * 100:.1f}%"),
        "",
        f"{'Year':<6}{'Base':>10}{'Bonus':>10}{'Sign-on':>10}"
        f"{'Equity vest':>13}{'Benefits':>10}{'Pre-tax':>11}{'After-tax':>11}",
        "-" * 81,
    ]
    for r in proj["years"]:
        lines.append(
            f"{r['year']:<6}{_fmt(r['base']):>10}{_fmt(r['bonus']):>10}"
            f"{_fmt(r['sign_on']):>10}{_fmt(r['equity_vest']):>13}"
            f"{_fmt(r['benefits']):>10}{_fmt(r['pre_tax']):>11}"
            f"{_fmt(r['after_tax']):>11}")
    t = proj["totals"]
    lines += [
        "-" * 81,
        f"{'TOTAL':<6}{'':>10}{'':>10}{'':>10}{_fmt(t['total_equity_vest']):>13}"
        f"{'':>10}{_fmt(t['total_pre_tax']):>11}{_fmt(t['total_after_tax']):>11}",
        "",
        f"NPV @ {a['discount'] * 100:.1f}%: {_fmt(t['npv'])}",
    ]
    if proj.get("note"):
        lines += ["", f"Note: {proj['note']}"]
    lines += ["", TAX_NOTE_SHORT]
    return "\n".join(lines)


def render_matrix(matrix: dict) -> str:
    """Text table: rows = offers, columns = growth scenarios (NPV cells)."""
    if not matrix["rows"]:
        return "No offers recorded yet. Add one with: python -m candid offer add ..."
    a = matrix["assumptions"]
    scen_labels = [s["label"] for s in matrix["scenarios"]]
    cell_strs = [[f"{_fmt(c['npv'])} / {_fmt(c['total_pre_tax'])}"
                  for c in row["cells"]] for row in matrix["rows"]]
    col_w = max([len(s) for cells in cell_strs for s in cells]
                + [len(lb) for lb in scen_labels]) + 3
    lines = [
        (f"Scenario comparison ({a['years']}y horizon, raises "
         f"{a['raise_pct'] * 100:.1f}%/yr, bonus "
         f"{a['bonus_payout'] * 100:.0f}% of target, discount "
         f"{a['discount'] * 100:.1f}%) - cells show NPV, then 4y pre-tax total:"),
        "",
        f"{'Offer':<24}" + "".join(f"{lb:>{col_w}}" for lb in scen_labels),
        "-" * (24 + col_w * len(scen_labels)),
    ]
    for row, cells in zip(matrix["rows"], cell_strs):
        name = f"{row['company']} {row.get('level', '')}".strip()[:22]
        lines.append(f"{name:<24}" + "".join(f"{s:>{col_w}}" for s in cells))
    lines += ["", TAX_NOTE_SHORT]
    return "\n".join(lines)


def export_matrix_md(matrix: dict, path: str | Path | None = None) -> Path:
    """Write the scenario matrix as markdown with assumptions spelled out."""
    if path is None:
        d = C.DATA_DIR / "offer_comparisons"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{date.today().isoformat()}_offer_scenarios.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    a = matrix["assumptions"]
    lines = ["# Offer Scenario Comparison", "",
             f"*Generated {date.today().isoformat()}*",
             "", "## Assumptions",
             "",
             f"- Horizon: {a['years']} years",
             "- Stock growth scenarios: " + ", ".join(
                 f"{s['label']} ({s['growth'] * 100:.1f}%/yr)"
                 for s in matrix["scenarios"]),
             f"- Annual base raises: {a['raise_pct'] * 100:.1f}%",
             f"- Bonus payout: {a['bonus_payout'] * 100:.0f}% of target "
             "(year-1 guaranteed bonus used when set)",
             f"- Discount rate for NPV: {a['discount'] * 100:.1f}%",
             "- Equity slices valued at the end-of-vest-year price "
             "(grant value compounded at the growth rate to the vest year).",
             "",
             "## 4-year totals by scenario (NPV / pre-tax total)", ""]
    header = ["Offer"] + [s["label"] for s in matrix["scenarios"]]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in matrix["rows"]:
        name = f"{row['company']} {row.get('level', '')}".strip()
        cells = [f"{_fmt(c['npv'])} / {_fmt(c['total_pre_tax'])}"
                 for c in row["cells"]]
        lines.append("| " + " | ".join([name] + cells) + " |")
    lines += ["", TAX_NOTE_SHORT, ""]
    md = "\n".join(lines)
    path.write_text(md, encoding="utf-8")
    return path


def export_projection_md(proj: dict, path: str | Path | None = None) -> Path:
    """Write a single-offer projection as markdown."""
    if path is None:
        d = C.DATA_DIR / "offer_comparisons"
        d.mkdir(parents=True, exist_ok=True)
        slug = "".join(ch.lower() if ch.isalnum() else "-"
                       for ch in proj.get("company", "offer"))[:40].strip("-")
        path = d / f"{date.today().isoformat()}_scenario_{slug or 'offer'}.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    a = proj["assumptions"]
    title = proj["company"] + (f" - {proj['role']}" if proj.get("role") else "")
    lines = [f"# Offer Scenario: {title}", "",
             f"*Generated {date.today().isoformat()}*",
             "", "## Assumptions", "",
             f"- Horizon: {a['years']} years",
             f"- Stock growth: {a['growth'] * 100:.1f}%/yr",
             f"- Annual base raises: {a['raise_pct'] * 100:.1f}%",
             f"- Bonus payout: {a['bonus_payout'] * 100:.0f}% of target",
             f"- Discount rate: {a['discount'] * 100:.1f}%",
             "", "## Year-by-year projection", "",
             "| Year | Base | Bonus | Sign-on | Equity vest | Benefits | "
             "Pre-tax | After-tax |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in proj["years"]:
        lines.append("| " + " | ".join([
            str(r["year"]), _fmt(r["base"]), _fmt(r["bonus"]),
            _fmt(r["sign_on"]), _fmt(r["equity_vest"]), _fmt(r["benefits"]),
            _fmt(r["pre_tax"]), _fmt(r["after_tax"])]) + " |")
    t = proj["totals"]
    lines += ["",
              f"**4-year pre-tax total: {_fmt(t['total_pre_tax'])}** · "
              f"**after-tax: {_fmt(t['total_after_tax'])}** · "
              f"**NPV @ {a['discount'] * 100:.1f}%: {_fmt(t['npv'])}**",
              ""]
    if proj.get("note"):
        lines += [f"Note: {proj['note']}", ""]
    lines += [TAX_NOTE_SHORT, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _money(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        raise O.OfferError(f"Expected a dollar amount, got '{x}'.")


def get_offer(name: str) -> dict:
    """Find a recorded offer by company name (case-insensitive substring)."""
    offers = O.list_offers()
    matches = [o for o in offers
               if name.lower() in str(o.get("company", "")).lower()]
    if not matches:
        raise O.OfferError(
            f"No offer found for '{name}'. Add one with: "
            "python -m candid offer add --company NAME --role ROLE --base 180000")
    return matches[0]


def top_offer() -> dict:
    """Highest normalized-annual offer (used when --company is omitted)."""
    offers = O.list_offers()
    if not offers:
        raise O.OfferError("No offers recorded yet. Add one with: "
                           "python -m candid offer add ...")
    return offers[0]


def as_jsonable(obj):
    """Round-trip through JSON to guarantee JSON-serializable CLI output."""
    return json.loads(json.dumps(obj, default=str))
