"""Benefits comparator: normalize every perk into dollars.

Each offer's "benefits" line is usually hand-waved as a single number.
This module breaks it into ~10 concrete, auditable pieces so two offers
can be compared on equal footing:

    1. health        annual cost of one health plan at a given spend level
    2. healthcare    scenario-weighted expected healthcare cost (low/mid/high)
    3. match         401(k) employer match math (tiered formulas, IRS cap)
    4. vesting      value of the match you actually keep (cliff/graded)
    5. pto           PTO / sick / holiday days converted to dollars
    6. espp          Employee Stock Purchase Plan gain (discount, lookback)
    7. hsa           HSA value: employer seed + tax savings
    8. fsa           FSA value: tax savings on the election
    9. commute       commuter/parking benefit (pre-tax or subsidy)
    10. leave        parental/family leave converted to dollars
    11. stipends     wellness / learning / phone / home-office stipends
    12. normalize    roll a whole package into one annual $ number
    13. compare      side-by-side table of two packages, ranked

Everything is computed from numbers the user enters. Nothing is fetched
from the network and no tax filing position is taken here.

Estimates, not tax advice: tax figures use a user-supplied marginal rate
and ignore state/local nuance. Confirm with a tax pro before deciding.
"""

from __future__ import annotations

import json
from pathlib import Path

# 2026 IRS annual compensation limit used for 401(k) match math.
# Overridable per call; kept as a constant so the default is explicit.
IRS_COMP_LIMIT_2026 = 360_000.0

# Standard working days per year for PTO valuation (52 weeks x 5).
WORK_DAYS_PER_YEAR = 260


class BenefitsError(Exception):
    """Raised for invalid benefit inputs."""


def _num(value, name: str, minimum: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise BenefitsError(f"{name} must be a number, got {value!r}") from exc
    if v < minimum:
        raise BenefitsError(f"{name} must be >= {minimum}, got {v}")
    return v


def _pct(value, name: str) -> float:
    v = _num(value, name)
    if v > 1:
        raise BenefitsError(f"{name} must be a fraction 0-1 (e.g. 0.2 for 20%), got {v}")
    return v


def _fmt(value: float) -> str:
    return f"${value:,.0f}"


# ---------------------------------------------------------------------------
# 1. Health plan annual cost
# ---------------------------------------------------------------------------

def health_plan_cost(monthly_premium: float, deductible: float,
                     coinsurance: float, oop_max: float,
                     annual_spend: float) -> dict:
    """Annual cost of one health plan at a given level of medical spend.

    OOP math: you pay the full spend up to the deductible, then
    coinsurance on the rest, capped at the out-of-pocket max.
    """
    premium = _num(monthly_premium, "monthly_premium")
    ded = _num(deductible, "deductible")
    coins = _pct(coinsurance, "coinsurance")
    oop = _num(oop_max, "oop_max")
    spend = _num(annual_spend, "annual_spend")
    if oop < ded:
        raise BenefitsError("oop_max must be >= deductible")
    if spend <= ded:
        oop_cost = spend
    else:
        oop_cost = min(ded + coins * (spend - ded), oop)
    annual_premium = premium * 12
    return {
        "annual_premium": annual_premium,
        "oop_cost": oop_cost,
        "total_cost": annual_premium + oop_cost,
    }


# ---------------------------------------------------------------------------
# 2. Scenario-weighted expected healthcare cost
# ---------------------------------------------------------------------------

def healthcare_expected_cost(monthly_premium: float, deductible: float,
                             coinsurance: float, oop_max: float,
                             scenarios: list[tuple[float, float]] | None = None) -> dict:
    """Expected annual healthcare cost across low/mid/high spend scenarios.

    scenarios: list of (probability, annual_spend). Probabilities must sum
    to ~1. Defaults to a typical young-professional mix.
    """
    if scenarios is None:
        scenarios = [(0.5, 1_500.0), (0.35, 6_000.0), (0.15, 25_000.0)]
    total_p = sum(p for p, _ in scenarios)
    if not 0.99 <= total_p <= 1.01:
        raise BenefitsError(f"scenario probabilities must sum to 1, got {total_p}")
    rows = []
    expected = 0.0
    for prob, spend in scenarios:
        cost = health_plan_cost(monthly_premium, deductible, coinsurance,
                                oop_max, spend)["total_cost"]
        rows.append({"probability": prob, "spend": spend, "cost": cost})
        expected += prob * cost
    return {"scenarios": rows, "expected_cost": expected}


# ---------------------------------------------------------------------------
# 3. 401(k) match math
# ---------------------------------------------------------------------------

def parse_match_formula(formula: str) -> list[tuple[float, float]]:
    """Parse a tiered match formula like ``"100:3,50:2"``.

    Each tier is ``match_pct:of_pay_pct``: the employer matches match_pct%
    of the first of_pay_pct% of your pay. Tiers apply in order.
    """
    tiers: list[tuple[float, float]] = []
    for part in formula.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            m, p = part.split(":")
            tiers.append((float(m) / 100.0, float(p) / 100.0))
        except ValueError as exc:
            raise BenefitsError(
                f"bad match formula {formula!r}: use e.g. '100:3,50:2'") from exc
    if not tiers:
        raise BenefitsError(f"bad match formula {formula!r}: no tiers parsed")
    return tiers


def match_401k(salary: float, employee_contrib_pct: float,
               formula: str = "100:3,50:2",
               irs_comp_limit: float = IRS_COMP_LIMIT_2026) -> dict:
    """Annual employer 401(k) match in dollars.

    Tiers apply to eligible pay (salary capped at the IRS compensation
    limit). Example: formula "100:3,50:2" with 10% employee contribution
    on $150k -> 100% of first 3% ($4,500) + 50% of next 2% ($1,500) = $6,000.
    """
    sal = _num(salary, "salary")
    contrib = _pct(employee_contrib_pct, "employee_contrib_pct")
    eligible = min(sal, _num(irs_comp_limit, "irs_comp_limit"))
    tiers = parse_match_formula(formula)
    remaining = contrib
    total = 0.0
    breakdown = []
    for match_pct, tier_pct in tiers:
        take = min(remaining, tier_pct)
        amount = match_pct * take * eligible
        breakdown.append({"tier": f"{match_pct:.0%} of {tier_pct:.0%} of pay",
                          "amount": amount})
        total += amount
        remaining -= take
        if remaining <= 0:
            break
    return {"eligible_pay": eligible, "tiers": breakdown,
            "annual_match": total}


# ---------------------------------------------------------------------------
# 4. Vesting schedule value
# ---------------------------------------------------------------------------

def vesting_value(unvested_balance: float, years_of_service: float,
                  schedule: str = "graded:6") -> dict:
    """Vested fraction (and keepable dollars) of an employer-match balance.

    schedule: "cliff:N" (0% until N years, then 100%) or "graded:N"
    (20% per year of service after year 1, capped at 100%, for the common
    6-year graded schedule; N scales the yearly step as 1/(N-1)).
    """
    balance = _num(unvested_balance, "unvested_balance")
    yos = _num(years_of_service, "years_of_service")
    try:
        kind, n = schedule.split(":")
        n_years = int(n)
    except ValueError as exc:
        raise BenefitsError(
            f"bad schedule {schedule!r}: use 'cliff:3' or 'graded:6'") from exc
    if kind == "cliff":
        vested_pct = 1.0 if yos >= n_years else 0.0
    elif kind == "graded":
        if n_years < 2:
            raise BenefitsError("graded schedule needs at least 2 years")
        step = 1.0 / (n_years - 1)
        vested_pct = min(1.0, max(0.0, (yos - 1.0)) * step) if yos >= 1 else 0.0
    else:
        raise BenefitsError(f"bad schedule {schedule!r}: kind must be cliff or graded")
    return {"vested_pct": vested_pct, "vested_value": balance * vested_pct,
            "unvested_value": balance * (1 - vested_pct)}


# ---------------------------------------------------------------------------
# 5. PTO valuation
# ---------------------------------------------------------------------------

def pto_value(salary: float, pto_days: float = 0, sick_days: float = 0,
              holidays: float = 0,
              work_days_per_year: float = WORK_DAYS_PER_YEAR) -> dict:
    """Convert paid time off into dollars at the daily salary rate."""
    sal = _num(salary, "salary")
    days = _num(pto_days, "pto_days") + _num(sick_days, "sick_days") + _num(holidays, "holidays")
    work_days = _num(work_days_per_year, "work_days_per_year", minimum=1)
    daily = sal / work_days
    return {"paid_days_off": days, "daily_rate": daily,
            "value": daily * days}


# ---------------------------------------------------------------------------
# 6. ESPP valuation
# ---------------------------------------------------------------------------

def espp_value(salary: float, contribution_pct: float, discount_pct: float,
               lookback: bool = False,
               periods_per_year: int = 2) -> dict:
    """Estimated annual ESPP gain.

    contribution_pct of salary goes in; the discount_pct is the immediate
    gain on purchase. A lookback roughly doubles the expected gain on
    average (stock appreciation over the offering period), modeled here
    as a 1.5x multiplier on the discount gain, labeled as an estimate.
    """
    sal = _num(salary, "salary")
    contrib = _pct(contribution_pct, "contribution_pct")
    discount = _pct(discount_pct, "discount_pct")
    annual_contrib = sal * contrib
    base_gain = annual_contrib * discount
    multiplier = 1.5 if lookback else 1.0
    gain = base_gain * multiplier
    return {"annual_contribution": annual_contrib,
            "discount_gain": base_gain,
            "lookback": lookback,
            "estimated_annual_gain": gain}


# ---------------------------------------------------------------------------
# 7/8. HSA and FSA value
# ---------------------------------------------------------------------------

def hsa_value(employer_seed: float = 0, employee_contribution: float = 0,
              marginal_tax_rate: float = 0.24) -> dict:
    """HSA annual value: employer seed (free money) + tax savings on your
    pre-tax contribution. HSA dollars are triple-tax-advantaged."""
    seed = _num(employer_seed, "employer_seed")
    contrib = _num(employee_contribution, "employee_contribution")
    rate = _pct(marginal_tax_rate, "marginal_tax_rate")
    tax_savings = contrib * rate
    return {"employer_seed": seed, "tax_savings": tax_savings,
            "total_value": seed + tax_savings}


def fsa_value(election: float, marginal_tax_rate: float = 0.24) -> dict:
    """FSA annual value: tax savings on the elected amount.

    Note the use-it-or-lose-it rule: only elect what you will spend.
    """
    amount = _num(election, "election")
    rate = _pct(marginal_tax_rate, "marginal_tax_rate")
    return {"election": amount, "tax_savings": amount * rate,
            "note": "use-it-or-lose-it: only elect what you will spend"}


# ---------------------------------------------------------------------------
# 9. Commuter / parking benefit
# ---------------------------------------------------------------------------

def commute_value(monthly_pretax: float = 0, monthly_subsidy: float = 0,
                  marginal_tax_rate: float = 0.24) -> dict:
    """Annual commuter benefit value: tax savings on pre-tax payroll
    deductions plus any direct employer subsidy (free transit pass,
    parking paid by the company, ...)."""
    pretax = _num(monthly_pretax, "monthly_pretax")
    subsidy = _num(monthly_subsidy, "monthly_subsidy")
    rate = _pct(marginal_tax_rate, "marginal_tax_rate")
    tax_savings = pretax * 12 * rate
    subsidy_value = subsidy * 12
    return {"tax_savings": tax_savings, "subsidy_value": subsidy_value,
            "total_value": tax_savings + subsidy_value}


# ---------------------------------------------------------------------------
# 10. Parental / family leave valuation
# ---------------------------------------------------------------------------

def leave_value(salary: float, weeks_full_pay: float = 0,
                weeks_partial_pay: float = 0, partial_pct: float = 0.6) -> dict:
    """Dollar value of paid parental/family leave.

    Values the leave at the salary you keep receiving while out, which is
    the apples-to-apples way to compare a 12-week-full-pay policy against
    an 8-week-60%-pay one.
    """
    sal = _num(salary, "salary")
    full = _num(weeks_full_pay, "weeks_full_pay")
    partial = _num(weeks_partial_pay, "weeks_partial_pay")
    pct = _pct(partial_pct, "partial_pct")
    weekly = sal / 52.0
    value = weekly * full + weekly * pct * partial
    return {"weekly_pay": weekly, "weeks_full_pay": full,
            "weeks_partial_pay": partial, "value": value}


# ---------------------------------------------------------------------------
# 11. Stipends
# ---------------------------------------------------------------------------

def stipends_value(stipends: dict[str, float]) -> dict:
    """Sum named stipends (wellness, learning, phone, home office, ...)."""
    items = []
    total = 0.0
    for name, amount in stipends.items():
        v = _num(amount, f"stipend[{name}]")
        items.append({"name": name, "amount": v})
        total += v
    return {"stipends": items, "total_value": total}


# ---------------------------------------------------------------------------
# 12. Normalize a whole package into one annual $ number
# ---------------------------------------------------------------------------

def normalize_package(pkg: dict) -> dict:
    """Roll a benefits package dict into one annual dollar value.

    Expected keys (all optional except salary when PTO/leave are used):
        salary, bonus,
        health: {monthly_premium, deductible, coinsurance, oop_max,
                 annual_spend}            -> counted as (negative) cost
        healthcare_expected: same keys but scenario-weighted
        match: {formula, employee_contrib_pct}
        pto: {pto_days, sick_days, holidays}
        espp: {contribution_pct, discount_pct, lookback}
        hsa: {employer_seed, employee_contribution, marginal_tax_rate}
        fsa: {election, marginal_tax_rate}
        commute: {monthly_pretax, monthly_subsidy, marginal_tax_rate}
        leave: {weeks_full_pay, weeks_partial_pay, partial_pct}
        stipends: {name: amount, ...}
        other_cash: extra annual cash perks not modeled above

    Health cost is subtracted (it is money you pay); everything else adds.
    Returns the total plus a per-line breakdown.
    """
    salary = _num(pkg.get("salary", 0), "salary")
    bonus = _num(pkg.get("bonus", 0), "bonus")
    rate = _pct(pkg.get("marginal_tax_rate", 0.24), "marginal_tax_rate")
    lines: list[tuple[str, float]] = [("Base salary", salary), ("Bonus", bonus)]

    health = pkg.get("health") or pkg.get("healthcare_expected")
    if health:
        if "scenarios" in health or pkg.get("healthcare_expected"):
            h = healthcare_expected_cost(
                health["monthly_premium"], health["deductible"],
                health["coinsurance"], health["oop_max"],
                scenarios=health.get("scenarios"))
            cost = h["expected_cost"]
            label = "Health cost (expected)"
        else:
            cost = health_plan_cost(
                health["monthly_premium"], health["deductible"],
                health["coinsurance"], health["oop_max"],
                health.get("annual_spend", 0))["total_cost"]
            label = "Health cost"
        lines.append((label, -cost))

    m = pkg.get("match")
    if m:
        lines.append(("401(k) match",
                      match_401k(salary, m.get("employee_contrib_pct", 0.06),
                                 m.get("formula", "100:3,50:2"))["annual_match"]))

    p = pkg.get("pto")
    if p:
        lines.append(("PTO value", pto_value(
            salary, p.get("pto_days", 0), p.get("sick_days", 0),
            p.get("holidays", 0))["value"]))

    e = pkg.get("espp")
    if e:
        lines.append(("ESPP gain", espp_value(
            salary, e.get("contribution_pct", 0.1),
            e.get("discount_pct", 0.15),
            e.get("lookback", False))["estimated_annual_gain"]))

    hsa = pkg.get("hsa")
    if hsa:
        lines.append(("HSA value", hsa_value(
            hsa.get("employer_seed", 0), hsa.get("employee_contribution", 0),
            hsa.get("marginal_tax_rate", rate))["total_value"]))

    fsa = pkg.get("fsa")
    if fsa:
        lines.append(("FSA value", fsa_value(
            fsa.get("election", 0),
            fsa.get("marginal_tax_rate", rate))["tax_savings"]))

    c = pkg.get("commute")
    if c:
        lines.append(("Commuter value", commute_value(
            c.get("monthly_pretax", 0), c.get("monthly_subsidy", 0),
            c.get("marginal_tax_rate", rate))["total_value"]))

    lv = pkg.get("leave")
    if lv:
        lines.append(("Parental leave value", leave_value(
            salary, lv.get("weeks_full_pay", 0),
            lv.get("weeks_partial_pay", 0),
            lv.get("partial_pct", 0.6))["value"]))

    st = pkg.get("stipends")
    if st:
        lines.append(("Stipends", stipends_value(st)["total_value"]))

    other = _num(pkg.get("other_cash", 0), "other_cash")
    if other:
        lines.append(("Other cash perks", other))

    total = sum(v for _, v in lines)
    return {"name": pkg.get("name", "package"), "lines": lines,
            "total_annual_value": total}


# ---------------------------------------------------------------------------
# 13. Compare two packages
# ---------------------------------------------------------------------------

def compare_packages(pkg_a: dict, pkg_b: dict) -> dict:
    """Normalize two packages and rank them with per-line deltas."""
    a = normalize_package(pkg_a)
    b = normalize_package(pkg_b)
    lines_a = dict(a["lines"])
    lines_b = dict(b["lines"])
    labels = list(dict.fromkeys(list(lines_a) + list(lines_b)))
    rows = [{"line": label,
             a["name"]: lines_a.get(label, 0.0),
             b["name"]: lines_b.get(label, 0.0),
             "delta": lines_a.get(label, 0.0) - lines_b.get(label, 0.0)}
            for label in labels]
    delta_total = a["total_annual_value"] - b["total_annual_value"]
    winner = a["name"] if delta_total >= 0 else b["name"]
    return {"a": a, "b": b, "rows": rows,
            "delta_total": delta_total, "winner": winner}


def load_package(path: str | Path) -> dict:
    """Load a benefits package from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise BenefitsError(f"package file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenefitsError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BenefitsError(f"{p} must contain a JSON object")
    return data


def render_normalized(result: dict) -> str:
    out = [f"Benefits package: {result['name']}", ""]
    for label, value in result["lines"]:
        out.append(f"  {label:<28} {_fmt(value):>12}")
    out.append(f"  {'-' * 42}")
    out.append(f"  {'TOTAL annual value':<28} {_fmt(result['total_annual_value']):>12}")
    return "\n".join(out)


def render_comparison(comp: dict) -> str:
    a_name, b_name = comp["a"]["name"], comp["b"]["name"]
    out = [f"Benefits comparison: {a_name} vs {b_name}", ""]
    out.append(f"  {'line':<28} {a_name[:14]:>14} {b_name[:14]:>14} {'delta (A-B)':>14}")
    for row in comp["rows"]:
        out.append(f"  {row['line']:<28} {_fmt(row[a_name]):>14} "
                   f"{_fmt(row[b_name]):>14} {_fmt(row['delta']):>14}")
    out.append(f"  {'-' * 74}")
    out.append(f"  {'TOTAL':<28} {_fmt(comp['a']['total_annual_value']):>14} "
               f"{_fmt(comp['b']['total_annual_value']):>14} "
               f"{_fmt(comp['delta_total']):>14}")
    out.append("")
    out.append(f"Winner on benefits value: {comp['winner']} "
               f"({_fmt(abs(comp['delta_total']))}/yr ahead)")
    return "\n".join(out)
