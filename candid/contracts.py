"""Contract-rate math: normalize contract offers and compare against FTE offers.

When to use it: screening a 1099/C2C contract offer against one or more FTE
(full-time, W-2) offers - e.g. "a $120/hr contract vs a $180k FTE offer" - so
both sides are expressed as rough annualized numbers before you dig deeper.

Limits (plain language):
- No tax-bracket modeling and no state or city taxes. Numbers are pre-tax.
- ``benefits_value`` is user-supplied (401k match, health premiums, etc.)
  from ``candid.offer``'s ``benefits_value`` field or your own estimate.
- Assumes a full work year (2080 hours / 260 days by default). Contract
  gigs often have unpaid gaps, no PTO, and no overtime - adjust the inputs
  if the role differs.
- ``fte_equivalent`` is an approximation, not advice. Talk to a tax pro
  before deciding.
"""

from __future__ import annotations

import re

# Map of user-facing unit words -> canonical period. Longest-first matching
# is handled by trying the full token before falling back to pieces.
_PERIOD_ALIASES = {
    "hour": "hour", "hours": "hour", "hourly": "hour",
    "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day", "daily": "day",
    "month": "month", "months": "month", "monthly": "month",
    "mo": "month", "mos": "month",
    "year": "year", "years": "year", "yearly": "year",
    "yr": "year", "yrs": "year", "y": "year",
    "annual": "year", "annum": "year",
}

_NUM_RE = re.compile(
    r"""^\$?\s*
        (?P<low>[\d,]+(?:\.\d+)?)\s*(?P<lowk>[kK])?
        (?:\s*[-–—]\s*\$?
           (?P<high>[\d,]+(?:\.\d+)?)\s*(?P<highk>[kK])?)?
        \s*(?P<rest>.*)$""",
    re.VERBOSE,
)


def _num(raw: str, k_suffix: str | None) -> float:
    value = float(raw.replace(",", ""))
    if k_suffix:
        value *= 1000
    return value


def _unit(rest: str) -> str | None:
    """Extract a canonical period from the text after the number."""
    rest = rest.strip().lower()
    if not rest:
        # Bare figure like "$150K" is quoted as an annualized rate.
        return "year"
    if rest.startswith("/"):
        rest = rest[1:].strip()
    if rest.startswith("per"):
        rest = rest[3:].strip()
    elif rest.startswith("an "):
        rest = rest[3:].strip()
    elif rest.startswith("a "):
        rest = rest[2:].strip()
    return _PERIOD_ALIASES.get(rest)


def parse_rate(text) -> dict | None:
    """Parse a contract rate string into ``{"amount": float, "period": str}``.

    Supported formats (case-insensitive, "$" optional, commas allowed):
    - Hourly: ``"$120/hr"``, ``"$120 per hour"``, ``"$120/hour"``, ``"120/hr"``
    - Daily: ``"$900/day"``, ``"$900 per day"``, ``"$900 daily"``
    - Monthly: ``"$12k/month"``, ``"$12k per month"``, ``"$12000 monthly"``
    - Yearly: ``"$150k/yr"``, ``"$200,000/year"``, ``"$150K"`` (bare = yearly)
    - Ranges: ``"$110-130/hr"`` takes the midpoint (``$120/hr``).

    Returns ``None`` when the text does not look like a rate.
    """
    if not isinstance(text, str):
        return None
    m = _NUM_RE.match(text.strip())
    if not m:
        return None
    low = _num(m.group("low"), m.group("lowk"))
    high_raw = m.group("high")
    if high_raw is not None:
        high = _num(high_raw, m.group("highk"))
        amount = (low + high) / 2
    else:
        amount = low
    if amount <= 0:
        return None
    period = _unit(m.group("rest"))
    if period is None:
        return None
    return {"amount": round(amount, 2), "period": period}


def annualize(parsed: dict | None,
              hours_per_year: int = 2080,
              days_per_year: int = 260) -> float:
    """Annualize a parsed rate: hour * 2080, day * 260, month * 12, year * 1.

    Raises ``ValueError`` when ``parsed`` is ``None`` (unparseable input).
    """
    if parsed is None:
        raise ValueError("Cannot annualize: rate did not parse (got None).")
    period = parsed.get("period")
    amount = parsed.get("amount")
    factors = {"hour": hours_per_year, "day": days_per_year,
               "month": 12, "year": 1}
    if period not in factors:
        raise ValueError(f"Unknown rate period: {period!r}.")
    return round(float(amount) * factors[period], 2)


def fte_equivalent(contract_annual: float,
                   benefits_value: float = 0.0,
                   se_tax_extra: float = 0.0765) -> float:
    """Estimate the FTE base salary whose total value matches a contract.

    Math: ``contract_annual * (1 - se_tax_extra) - benefits_value``.

    Assumptions (this is an approximation, not tax advice):
    - A 1099 contractor pays both halves of Social Security/Medicare, so
      they owe roughly 7.65% more payroll tax than a W-2 employee on the
      same income. Subtracting that gives a net-ish cash figure.
    - An FTE offer's total value is salary + ``benefits_value`` (401k match,
      health premiums, PTO value - supplied by the user, not estimated).
    - Income-tax brackets are ignored entirely (they shift both sides in
      complicated, personal ways); only the payroll-tax gap is modeled.
    - No unpaid contract gaps, no overtime, and no FTE perks that lack a
      dollar value (stability, equity upside, visa sponsorship, etc.).
    """
    contract_annual = float(contract_annual)
    benefits_value = float(benefits_value or 0)
    return round(contract_annual * (1 - se_tax_extra) - benefits_value, 2)


def _fmt_money(x: float) -> str:
    return f"${float(x):,.0f}"


def compare_contract_vs_fte(rate_text: str,
                            fte_total_comp: float,
                            fte_benefits: float = 0.0,
                            hours_per_year: int = 2080,
                            days_per_year: int = 260,
                            se_tax_extra: float = 0.0765) -> dict:
    """Compare one contract rate against an FTE total-comp figure.

    Returns a dict with:
    - ``contract_rate``: the parsed rate (``{"amount", "period"}``)
    - ``contract_annual``: annualized contract revenue (pre-tax, gross)
    - ``contract_net_approx``: contract cash after the SE-tax gap (approx)
    - ``fte_total_comp``: the FTE figure passed in
    - ``fte_equiv_salary``: FTE base salary matching the contract's value
    - ``delta``: ``contract_annual - fte_total_comp``
    - ``verdict``: one-line human summary
    - ``assumptions``: list of the documented caveats

    ``fte_benefits`` is the user-supplied dollar value of FTE benefits and
    feeds ``fte_equivalent``. Raises ``ValueError`` on an unparseable rate.
    """
    parsed = parse_rate(rate_text)
    if parsed is None:
        raise ValueError(f"Could not parse a contract rate from {rate_text!r}.")
    contract_annual = annualize(parsed, hours_per_year, days_per_year)
    contract_net = round(contract_annual * (1 - se_tax_extra), 2)
    equiv = fte_equivalent(contract_annual, benefits_value=fte_benefits,
                           se_tax_extra=se_tax_extra)
    delta = round(contract_annual - float(fte_total_comp), 2)

    gap = abs(delta)
    if delta > 0:
        verdict = (f"Contract pays ~{_fmt_money(gap)}/yr more than the FTE "
                   f"offer, before benefits gaps.")
    elif delta < 0:
        verdict = (f"FTE offer pays ~{_fmt_money(gap)}/yr more than the "
                   f"contract, before benefits gaps.")
    else:
        verdict = "Contract and FTE offer pay about the same, before benefits gaps."

    assumptions = [
        "Contract annualized at full-year workload "
        f"({hours_per_year} hrs / {days_per_year} days); unpaid gaps, no PTO, "
        "and no overtime are not modeled.",
        "Contractor owes ~7.65% extra payroll tax vs W-2 (both halves of "
        "Social Security/Medicare); this is an approximation, not tax advice.",
        "Income-tax brackets and state/city taxes are not modeled.",
        "FTE benefits are user-supplied via fte_benefits; non-cash perks "
        "(stability, equity upside, PTO quality) are not valued.",
    ]

    return {
        "contract_rate": parsed,
        "contract_annual": contract_annual,
        "contract_net_approx": contract_net,
        "fte_total_comp": float(fte_total_comp),
        "fte_equiv_salary": equiv,
        "delta": delta,
        "verdict": verdict,
        "assumptions": assumptions,
    }
