"""Equity deep-dives: RSUs, stock options, ISO/NSO, vesting math, and the
questions to ask about equity in an offer.

Everything here is EDUCATIONAL ONLY - not tax advice, not legal advice, not
financial advice. Equity taxation is genuinely complicated and the rules
change; talk to a qualified tax professional before making decisions about
exercise, sale, or an offer.

Subcommands:
    types      RSU vs stock options vs ISO vs NSO explainer cards
    lifecycle  grant -> vest -> exercise -> sell walkthroughs (rsu | options)
    iso-nso    ISO vs NSO tax-basics comparison (educational)
    glossary   equity term glossary (optionally: --term <word>)
    vest       vesting schedule math: timeline of vest events with $ values
    cliff      cliff explainer + calculator
    scenarios  what is this grant worth at different share prices?
    exercise   options exercise cost calculator (strike + estimated tax)
    refresh    refresh grants: what they are + stacking math
    dilution   dilution explainer + ownership % calculator
    checklist  questions to ask about equity in an offer
    quiz       equity literacy self-check (multiple choice)
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date


class EquityError(Exception):
    """Raised for invalid equity inputs."""


DISCLAIMER = (
    "_Educational only: this is not tax, legal, or financial advice. Equity "
    "taxation depends on your situation, your state, and current law. Talk to "
    "a qualified tax professional before exercising options, selling shares, "
    "or deciding on an offer._"
)


def _money(x) -> str:
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _num(x, what="value") -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise EquityError(f"Expected a number for {what}, got '{x}'.")
    return v


# ---------------------------------------------------------------------------
# 1. types: RSU vs options vs ISO vs NSO explainer cards
# ---------------------------------------------------------------------------

EQUITY_TYPES = {
    "rsu": {
        "name": "RSUs (Restricted Stock Units)",
        "what": ("A promise that the company will give you actual shares (or "
                 "their cash value) once they vest. You pay nothing to receive "
                 "them - no strike price, no exercise."),
        "when_value": ("Worth the share price at vest. If the stock is at $50 "
                       "when 100 RSUs vest, you get $5,000 of value (before tax)."),
        "tax_shape": ("Taxed as ordinary income when they vest, on the share "
                      "price that day. Your employer usually withholds shares "
                      "to cover taxes (sell-to-cover)."),
        "typical_at": "Public companies and late-stage startups.",
        "watch_outs": [
            "Double-trigger RSUs at private startups: they vest on a schedule "
            "AND require a liquidity event (IPO/acquisition) before you own anything.",
            "RSUs can expire - some have a 7-year expiration from grant.",
            "A big vest in one year can push you into a higher tax bracket that year.",
        ],
    },
    "options": {
        "name": "Stock options (general)",
        "what": ("The right to BUY shares later at a fixed price (the strike "
                 "price), set when the options are granted. You must pay the "
                 "strike price to turn options into shares - this is called "
                 "exercising."),
        "when_value": ("Worth max($0, share price - strike price) per option. "
                       "If the strike is $10 and shares are worth $50, each "
                       "option is worth $40. If shares are worth $8, the "
                       "options are worth $0 ('underwater')."),
        "tax_shape": ("Depends on the kind: ISOs and NSOs are taxed "
                      "differently. See `equity iso-nso`."),
        "typical_at": "Early and mid-stage startups; some public companies.",
        "watch_outs": [
            "Options expire - usually 10 years from grant, and often 90 days "
            "after you leave the company (the post-termination exercise window).",
            "Exercising can cost real money: strike price x shares, plus "
            "possible taxes (see `equity exercise`).",
            "An option grant quoted in dollars is really a share count: "
            "$100k of options at a $10 strike = 10,000 options.",
        ],
    },
    "iso": {
        "name": "ISOs (Incentive Stock Options)",
        "what": ("A tax-advantaged kind of stock option, only for employees "
                 "(not contractors or advisors). Same mechanics as options: "
                 "strike price, vesting, exercise."),
        "when_value": ("Same as options: max($0, share price - strike) per "
                       "option. The advantage is in how they are taxed, not in "
                       "their value."),
        "tax_shape": ("No regular income tax at exercise IF you meet the "
                      "holding rules (see `equity iso-nso`). The spread at "
                      "exercise can trigger AMT (alternative minimum tax)."),
        "typical_at": "US startups granting options to employees.",
        "watch_outs": [
            "$100k limit: only $100k of underlying stock (by grant-date value) "
            "can become exercisable as ISOs per calendar year; the rest convert "
            "to NSOs.",
            "The 90-day post-termination window is the classic ISO trap: leave, "
            "and you may have 90 days to come up with exercise cash.",
            "Exercising ISOs and holding can create an AMT bill even though you "
            "received no cash.",
        ],
    },
    "nso": {
        "name": "NSOs (Non-Qualified Stock Options)",
        "what": ("Stock options without the ISO tax advantages. Can be granted "
                 "to anyone: employees, contractors, advisors, board members."),
        "when_value": ("Same as options: max($0, share price - strike) per "
                       "option."),
        "tax_shape": ("The spread (share price minus strike) at exercise is "
                      "taxed as ordinary income that year - like a cash bonus. "
                      "Any further gain after exercise is capital gain/loss."),
        "typical_at": "Startups (for non-employees), public companies with option programs.",
        "watch_outs": [
            "The tax bill arrives at exercise whether or not you sell the shares.",
            "If you exercise and the stock later falls, you already paid tax on "
            "the higher spread.",
            "NSOs are simpler than ISOs (no AMT, no holding-period puzzle) but "
            "the ordinary-income hit at exercise is usually larger.",
        ],
    },
}


def get_type(kind: str) -> dict:
    """Return the explainer card for one equity type."""
    k = (kind or "").strip().lower()
    if k not in EQUITY_TYPES:
        raise EquityError(
            f"Unknown equity type '{kind}'. Choose from: "
            + ", ".join(sorted(EQUITY_TYPES)))
    return EQUITY_TYPES[k]


def render_types(kind: str = "") -> str:
    """Render one or all equity-type explainer cards."""
    cards = [EQUITY_TYPES[k] for k in sorted(EQUITY_TYPES)] if not kind \
        else [get_type(kind)]
    lines = ["# Equity types: RSUs vs options vs ISOs vs NSOs", ""]
    for c in cards:
        lines += [
            f"## {c['name']}", "",
            f"**What it is:** {c['what']}", "",
            f"**When it has value:** {c['when_value']}", "",
            f"**Tax shape:** {c['tax_shape']}", "",
            f"**Typical at:** {c['typical_at']}", "",
            "**Watch out for:**",
        ]
        lines += [f"- {w}" for w in c["watch_outs"]]
        lines += [""]
    lines += [
        "**The one-line version:** RSUs are shares you get for free at vest; "
        "options are the right to buy shares at a fixed price; ISOs and NSOs "
        "are the two tax flavors of options.",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. lifecycle: grant -> vest -> exercise -> sell walkthroughs
# ---------------------------------------------------------------------------

LIFECYCLES = {
    "rsu": """# RSU lifecycle: grant -> vest -> (sell)

**1. Grant.** The company grants you N RSUs. Nothing is taxed yet and you own
nothing yet - it is a promise of future shares.

**2. Vest.** On the vesting schedule (often 4 years, sometimes with a 1-year
cliff), chunks of RSUs convert into actual shares. THIS is the taxable event:
the market value of the vested shares counts as ordinary income, like salary.
Most employers do "sell to cover" - they sell some of your vested shares
automatically to pay withholding tax, and you keep the rest.

**3. Hold or sell.** After vest, the shares are yours. If you hold and the
price rises, the extra gain is capital gain (short- or long-term depending on
how long you hold after vest). If the price falls, that is a capital loss.

**Example.** 1,000 RSUs, vesting 250/year for 4 years, stock at $60 at each
vest: each year you get $15,000 of ordinary income and (after sell-to-cover)
roughly $15,000 minus withholding in shares or cash.

**Key questions for your grant:** vesting schedule? cliff? double-trigger
(private company)? expiration? See `equity checklist`.""",
    "options": """# Stock option lifecycle: grant -> vest -> exercise -> sell

**1. Grant.** The company grants you options on N shares at a strike price
(usually the current 409A fair market value). Nothing is taxed at grant.

**2. Vest.** Options vest over time (often 4 years with a 1-year cliff).
Vesting gives you the *right* to buy - you still own nothing and owe nothing.

**3. Exercise.** You pay strike price x shares to convert vested options into
actual shares. This costs real cash up front. Tax depends on kind:
NSOs: the spread (market price minus strike) is ordinary income this year.
ISOs: no regular income tax now IF you hold long enough, but the spread can
trigger AMT. See `equity iso-nso` and `equity exercise`.

**4. Sell.** Sell the shares: any gain after exercise is capital gain (or
loss). For ISOs, selling before the holding periods ends = "disqualifying
disposition" and the tax advantage mostly evaporates.

**Example.** 10,000 options, $5 strike, vested, stock now worth $25. Exercise
costs $50,000 cash. Spread is $200,000 - that is the amount with tax
consequences at exercise (ordinary income for NSOs, AMT base for ISOs).

**Key questions for your grant:** ISO or NSO? strike and current 409A value?
vesting + cliff? post-termination exercise window? See `equity checklist`.""",
}


def get_lifecycle(kind: str) -> str:
    """Return the lifecycle walkthrough for 'rsu' or 'options'."""
    k = (kind or "").strip().lower()
    if k not in LIFECYCLES:
        raise EquityError(
            f"Unknown lifecycle '{kind}'. Choose from: rsu, options.")
    return LIFECYCLES[k] + "\n\n" + DISCLAIMER


# ---------------------------------------------------------------------------
# 3. iso-nso: ISO vs NSO tax-basics (educational)
# ---------------------------------------------------------------------------

ISO_NSO_GUIDE = """# ISOs vs NSOs: tax basics (educational, not advice)

Both are stock options. The difference is entirely about tax treatment.

## At exercise

- **NSO:** the spread (market value minus strike, times shares) is taxed as
  ordinary income in the year you exercise - just like a cash bonus. Your
  employer withholds on it.
- **ISO:** no regular income tax at exercise. BUT the spread counts as income
  for AMT (alternative minimum tax) purposes, which can produce a real tax
  bill in the exercise year even though you received no cash.

## The ISO holding-period puzzle

To get the favorable ISO treatment (gains taxed as capital gains, not
ordinary income), you must meet BOTH holding periods - a **qualifying
disposition**:

1. Hold the shares more than **2 years after the grant date**, AND
2. Hold the shares more than **1 year after the exercise date**.

Sell before both are met and it is a **disqualifying disposition**: the
spread at exercise is taxed as ordinary income (like an NSO), and only gain
beyond that is capital gain. The AMT you paid may come back as a credit in
later years - this is where a tax pro earns their fee.

## After exercise (both kinds)

Any change in share price after exercise is capital gain or loss when you
sell: short-term if you held the shares one year or less, long-term if more
than one year.

## Quick comparison

| | NSO | ISO (qualifying) |
|---|---|---|
| Tax at exercise | Ordinary income on spread | No regular tax; AMT possible |
| Tax at sale | Capital gain/loss on post-exercise change | Long-term capital gain on most of it |
| Who can get them | Anyone | Employees only |
| $100k/year limit | No | Yes (excess becomes NSO) |

## The classic traps

1. **The 90-day window:** leave the company and you often have 90 days to
   exercise vested options or lose them - for ISOs and NSOs alike.
2. **AMT surprise:** exercising ISOs in a high-valuation year can create a
   five- or six-figure AMT bill with no cash from a sale to pay it.
3. **Disqualifying by accident:** selling ISO shares a month too early can
   convert capital-gain treatment into ordinary income.

Run the numbers with `equity exercise --count N --strike S --fmv F
--kind iso|nso` before you exercise anything.
"""


def render_iso_nso() -> str:
    return ISO_NSO_GUIDE + "\n" + DISCLAIMER


# ---------------------------------------------------------------------------
# 4. glossary
# ---------------------------------------------------------------------------

GLOSSARY = {
    "vesting": "Earning your equity over time. Unvested equity can be taken back; vested equity is yours (subject to exercise for options).",
    "cliff": "An initial period (often 12 months) during which nothing vests; at the cliff date, the accrued chunk vests all at once.",
    "strike price": "The fixed price at which an option lets you buy a share. Also called the exercise price. Usually set to the 409A fair market value at grant.",
    "exercise": "Paying the strike price to convert vested options into actual shares.",
    "spread": "Market value minus strike price, per share. The amount with tax consequences when NSOs are exercised (and the AMT base for ISOs).",
    "fmv": "Fair market value: what a share is worth now. For private companies this comes from a 409A valuation.",
    "409a": "An independent valuation of a private company's common stock, refreshed roughly yearly. Sets the strike price for new option grants.",
    "underwater": "Options whose strike price is above the current share value - worth $0 unless the price recovers.",
    "double-trigger": "RSUs (common at private startups) that vest on a time schedule AND require a liquidity event (IPO/acquisition) before you actually receive shares.",
    "amt": "Alternative minimum tax: a parallel US tax computation. The ISO spread at exercise counts as AMT income and can create a bill even with no sale.",
    "qualifying disposition": "Selling ISO shares after BOTH holding periods (2 years from grant, 1 year from exercise) to get capital-gains treatment.",
    "disqualifying disposition": "Selling ISO shares before the holding periods are met; the spread is then taxed as ordinary income.",
    "post-termination exercise window": "How long after leaving you can exercise vested options - often 90 days, sometimes extended to years at some startups.",
    "refresh grant": "Additional equity granted in later years (often annually) to top up your unvested balance and keep total comp competitive.",
    "dilution": "Your ownership percentage shrinking as the company issues more shares (new hires, investors, option pool increases).",
    "fully diluted": "Share count including all options, RSUs, warrants, and convertibles - the honest denominator for ownership math.",
    "liquidation preference": "Investors getting paid first in a sale. In a bad outcome, common shareholders (you) can get little or nothing.",
    "sell to cover": "At RSU vest, the employer sells some of your shares automatically to pay withholding tax; you keep the rest.",
}


def glossary(term: str = "") -> dict | str:
    """Return the glossary dict, or the definition of one term."""
    t = (term or "").strip().lower()
    if not t:
        return dict(GLOSSARY)
    for key, definition in GLOSSARY.items():
        if key == t or t in key:
            return {key: definition}
    raise EquityError(
        f"No glossary entry for '{term}'. Try `equity glossary` to list all terms.")


def render_glossary(term: str = "") -> str:
    entries = glossary(term)
    lines = ["# Equity glossary", ""]
    for key in sorted(entries):
        lines.append(f"**{key}**: {entries[key]}")
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. vest: vesting schedule math
# ---------------------------------------------------------------------------

def parse_schedule(schedule: str) -> list[float]:
    """Parse '25/25/25/25' or '40/30/20/10' into fractions summing to 1."""
    s = (schedule or "").strip()
    if not s:
        raise EquityError("Provide a vesting schedule like '25/25/25/25'.")
    try:
        parts = [float(p) for p in s.replace("%", "").split("/")]
    except ValueError:
        raise EquityError(f"Could not parse schedule '{schedule}'. Use e.g. '25/25/25/25'.")
    if any(p < 0 for p in parts):
        raise EquityError("Schedule parts must be non-negative.")
    total = sum(parts)
    if abs(total - 100) > 0.5:
        raise EquityError(f"Schedule '{schedule}' sums to {total}, expected 100.")
    return [p / 100 for p in parts]


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def vesting_timeline(total_value: float = 0, share_price: float = 0,
                     schedule: str = "25/25/25/25",
                     start: str = "", frequency: str = "annual",
                     cliff_months: int = 0) -> list[dict]:
    """Build a vesting timeline.

    total_value: grant value in $ (RSUs) at share_price. share_price: price at
    grant (also used to value each vest). schedule: '25/25/25/25' style.
    start: ISO grant date 'YYYY-MM-DD' (default today). frequency: annual,
    quarterly, or monthly. cliff_months: months before anything vests.
    Returns a list of {date, shares, value, cumulative_shares, cumulative_value}.
    """
    total_value = _num(total_value, "total_value")
    share_price = _num(share_price, "share_price")
    if total_value <= 0:
        raise EquityError("total_value must be positive.")
    if share_price <= 0:
        raise EquityError("share_price must be positive.")
    freq = (frequency or "").strip().lower()
    if freq not in ("annual", "quarterly", "monthly"):
        raise EquityError(f"Unknown frequency '{frequency}'. Use annual, quarterly, or monthly.")
    cliff_months = int(cliff_months or 0)
    if cliff_months < 0:
        raise EquityError("cliff_months must be >= 0.")
    if start:
        try:
            start_d = date.fromisoformat(start)
        except ValueError:
            raise EquityError(f"Could not parse start date '{start}'. Use YYYY-MM-DD.")
    else:
        start_d = date.today()

    fracs = parse_schedule(schedule)
    years = len(fracs)
    total_shares = total_value / share_price
    months_total = years * 12

    # monthly vest fractions from the annual schedule
    monthly = [0.0] * months_total
    for yi, f in enumerate(fracs):
        for m in range(12):
            monthly[yi * 12 + m] += f / 12

    # apply cliff: accrue, release at the cliff boundary
    accrued = 0.0
    releasable = [0.0] * months_total
    for i, frac in enumerate(monthly):
        month_no = i + 1
        if month_no < cliff_months:
            accrued += frac
        elif month_no == cliff_months:
            releasable[i] = frac + accrued
            accrued = 0.0
        else:
            releasable[i] = frac
    if cliff_months > months_total:
        # cliff beyond the whole schedule: everything vests at the end
        releasable = [0.0] * months_total
        releasable[-1] = 1.0

    step = {"annual": 12, "quarterly": 3, "monthly": 1}[freq]
    events = []
    cum_frac = 0.0
    for i in range(0, months_total, step):
        chunk = sum(releasable[i:i + step])
        if chunk <= 0:
            continue
        cum_frac += chunk
        vest_date = _add_months(start_d, i + step)
        shares = total_shares * chunk
        value = shares * share_price
        events.append({
            "date": vest_date.isoformat(),
            "shares": round(shares, 2),
            "value": round(value, 2),
            "cumulative_shares": round(total_shares * cum_frac, 2),
            "cumulative_value": round(total_shares * cum_frac * share_price, 2),
        })
    return events


def render_vest(total_value: float, share_price: float, schedule: str,
                start: str, frequency: str, cliff_months: int) -> str:
    events = vesting_timeline(total_value, share_price, schedule, start,
                              frequency, cliff_months)
    total_shares = _num(total_value, "t") / _num(share_price, "p")
    lines = [
        "# Vesting timeline",
        "",
        f"Grant: {_money(total_value)} at {_money(share_price)}/share = "
        f"{total_shares:,.0f} shares; schedule {schedule}; {frequency}; "
        + (f"{cliff_months}-month cliff." if cliff_months else "no cliff."),
        "",
        f"{'Vest date':<12}{'Shares':>10}{'Value':>12}{'Cumulative':>14}",
        "-" * 50,
    ]
    for e in events:
        lines.append(f"{e['date']:<12}{e['shares']:>10,.0f}"
                     f"{_money(e['value']):>12}{_money(e['cumulative_value']):>14}")
    lines += [
        "",
        "Values assume the share price stays flat at the grant price - in "
        "reality each vest is valued at the price that day.",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. cliff: explainer + calculator
# ---------------------------------------------------------------------------

CLIFF_GUIDE = """# The cliff, explained

A cliff is an initial waiting period - usually the first 12 months of a
4-year vesting schedule - during which *nothing* vests. On the cliff date,
everything that accrued during the wait vests all at once, and vesting then
continues on its normal cadence (monthly or quarterly).

**The classic shape:** 4-year vest, 1-year cliff, monthly after.
Leave at month 11: you walk away with $0 of equity. Stay to month 12: 25% of
your grant vests in one day. Months 13-48 vest 1/48th of the grant each.

**Why cliffs exist:** they protect the company from granting equity to
someone who leaves in the first months, and they give you a clean decision
point at one year.

**What to check in your grant:** cliff length (12 months is standard, some
have none), what happens to the accrued chunk if you leave the day before,
and whether vesting after the cliff is monthly or quarterly.
"""


def cliff_table(total_shares: float, months: int = 48,
                cliff_months: int = 12) -> list[dict]:
    """Month-by-month vesting with a cliff. Returns vest events."""
    total_shares = _num(total_shares, "total_shares")
    months = int(months)
    cliff_months = int(cliff_months)
    if total_shares <= 0 or months <= 0:
        raise EquityError("total_shares and months must be positive.")
    if not 0 <= cliff_months <= months:
        raise EquityError("cliff_months must be between 0 and months.")
    per_month = total_shares / months
    events = []
    if cliff_months:
        events.append({"month": cliff_months,
                       "shares": round(per_month * cliff_months, 2),
                       "note": f"cliff: {cliff_months} months accrue at once"})
    # round each event but let the final one absorb the rounding remainder
    raw = [per_month] * (months - cliff_months)
    rounded = [round(x, 2) for x in raw]
    if rounded:
        rounded[-1] = round(total_shares - sum(e["shares"] for e in events)
                            - sum(rounded[:-1]), 2)
    for m, sh in zip(range(cliff_months + 1, months + 1), rounded):
        events.append({"month": m, "shares": sh, "note": ""})
    return events


def render_cliff(total_shares: float, months: int, cliff_months: int) -> str:
    events = cliff_table(total_shares, months, cliff_months)
    per_month = _num(total_shares, "t") / int(months)
    lines = [CLIFF_GUIDE, "",
             f"## Calculator: {total_shares:,.0f} shares over {months} months, "
             f"{cliff_months}-month cliff", "",
             f"{'Month':<8}{'Vests':>12}{'Note':>34}", "-" * 56]
    for e in events:
        lines.append(f"{e['month']:<8}{e['shares']:>12,.0f}{e['note']:>34}")
    lines += ["",
              f"After the cliff, {per_month:,.0f} shares vest each month.",
              "", DISCLAIMER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. scenarios: what is this grant worth at different share prices?
# ---------------------------------------------------------------------------

def parse_prices(raw: str) -> list[float]:
    """Parse '40,60,80' or '40 60 80' into a sorted price list."""
    s = (raw or "").strip()
    if not s:
        raise EquityError("Provide share prices, e.g. --prices 40,60,80.")
    try:
        prices = sorted({float(p) for p in s.replace(",", " ").split()})
    except ValueError:
        raise EquityError(f"Could not parse prices '{raw}'.")
    if any(p < 0 for p in prices):
        raise EquityError("Prices must be non-negative.")
    return prices


def scenario_table(kind: str = "rsu", shares: float = 0, count: float = 0,
                   strike: float = 0, prices: list[float] | None = None) -> list[dict]:
    """Value a grant across share-price scenarios.

    kind 'rsu': value = shares * price.
    kind 'options': intrinsic value per option = max(0, price - strike).
    Returns rows of {price, per_share, total}.
    """
    k = (kind or "").strip().lower()
    if k not in ("rsu", "options"):
        raise EquityError(f"Unknown kind '{kind}'. Use rsu or options.")
    if not prices:
        raise EquityError("Provide share prices, e.g. --prices 40,60,80.")
    rows = []
    if k == "rsu":
        shares = _num(shares, "shares")
        if shares <= 0:
            raise EquityError("--shares must be positive for RSU scenarios.")
        for p in prices:
            rows.append({"price": p, "per_share": p, "total": round(shares * p, 2)})
    else:
        count = _num(count, "count")
        strike = _num(strike, "strike")
        if count <= 0:
            raise EquityError("--count must be positive for option scenarios.")
        if strike < 0:
            raise EquityError("--strike must be non-negative.")
        for p in prices:
            intrinsic = max(0.0, p - strike)
            rows.append({"price": p, "per_share": round(intrinsic, 2),
                         "total": round(intrinsic * count, 2)})
    return rows


def render_scenarios(kind: str, shares: float, count: float, strike: float,
                     prices: list[float]) -> str:
    rows = scenario_table(kind, shares, count, strike, prices)
    k = kind.strip().lower()
    if k == "rsu":
        title = f"# RSU scenarios: {shares:,.0f} shares"
        note = ("RSUs are worth the share price, whatever it is - there is no "
                "strike price and no scenario where they are worth $0 while "
                "the company has value.")
    else:
        title = (f"# Option scenarios: {count:,.0f} options at "
                 f"{_money(strike)} strike")
        note = ("Each option is worth max($0, price - strike). Below the "
                f"strike ({_money(strike)}) the options are underwater and "
                "worth $0. Break-even on exercise (before tax) is any price "
                "above the strike.")
    lines = [title, "",
             f"{'Share price':<14}{'Per share':>12}{'Total value':>16}",
             "-" * 44]
    for r in rows:
        lines.append(f"{_money(r['price']):<14}{_money(r['per_share']):>12}"
                     f"{_money(r['total']):>16}")
    lines += ["", note, "",
              "Pre-tax values. RSUs are taxed as ordinary income at vest; "
              "options have tax consequences at exercise (see `equity "
              "exercise`).", "", DISCLAIMER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. exercise: options exercise cost calculator
# ---------------------------------------------------------------------------

def exercise_cost(count: float, strike: float, fmv: float,
                  kind: str = "nso", marginal_rate: float = 0.32) -> dict:
    """Cost to exercise options, with estimated tax at exercise.

    count: options exercised. strike: strike price. fmv: current fair market
    value per share. kind: 'nso' or 'iso'. marginal_rate: your estimated
    marginal ordinary-income rate (a placeholder - your real rate depends on
    income, state, and current brackets).
    Returns dict with cash cost, spread, estimated tax, and total outlay.
    """
    count = _num(count, "count")
    strike = _num(strike, "strike")
    fmv = _num(fmv, "fmv")
    rate = _num(marginal_rate, "marginal_rate")
    k = (kind or "").strip().lower()
    if k not in ("nso", "iso"):
        raise EquityError(f"Unknown kind '{kind}'. Use nso or iso.")
    if count <= 0:
        raise EquityError("count must be positive.")
    if strike < 0 or fmv < 0:
        raise EquityError("strike and fmv must be non-negative.")
    if not 0 <= rate <= 1:
        raise EquityError("marginal_rate must be between 0 and 1.")

    cash_cost = count * strike
    spread = max(0.0, fmv - strike) * count
    if k == "nso":
        est_tax = spread * rate
        tax_note = (f"NSO: spread taxed as ordinary income at exercise. "
                    f"Estimated tax at {rate:.0%} marginal rate.")
    else:
        est_tax = 0.0
        tax_note = ("ISO: no regular income tax at exercise (holding periods "
                    "permitting), but the spread counts as AMT income and can "
                    "create an AMT bill. See `equity iso-nso`.")
    return {
        "kind": k.upper(),
        "count": count,
        "strike": strike,
        "fmv": fmv,
        "cash_cost": round(cash_cost, 2),
        "spread": round(spread, 2),
        "est_tax_at_exercise": round(est_tax, 2),
        "total_outlay": round(cash_cost + est_tax, 2),
        "tax_note": tax_note,
    }


def render_exercise(result: dict) -> str:
    r = result
    lines = [
        f"# Exercise cost: {r['count']:,.0f} {r['kind']} options",
        "",
        f"Strike {_money(r['strike'])} x {r['count']:,.0f} shares = "
        f"**{_money(r['cash_cost'])} cash** to exercise.",
        f"Spread at {_money(r['fmv'])} FMV: {_money(r['spread'])}.",
        "",
        r["tax_note"],
        "",
        f"Estimated tax at exercise: {_money(r['est_tax_at_exercise'])}",
        f"**Total out-of-pocket: {_money(r['total_outlay'])}**",
        "",
        "The marginal rate is a placeholder you supply - your actual rate "
        "depends on total income, state, and current brackets. This is an "
        "estimate for planning, not a tax calculation.",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. refresh: refresh grants concept + stacking math
# ---------------------------------------------------------------------------

REFRESH_GUIDE = """# Refresh grants

Your initial grant vests over ~4 years, which means your unvested balance
(and your effective annual comp) declines every year if nothing else is
granted. Refresh grants fix that: companies typically grant additional equity
each year (often around review time) to top you back up.

**How it usually works:** each annual refresh has its own 4-year vesting
schedule, so the grants stack. In year 5 you might be vesting pieces of your
year-1, year-2, year-3, and year-4 grants simultaneously.

**What to ask:** does the company do annual refreshers? Are they automatic or
performance-based? What is the typical refresh size relative to the initial
grant (a common pattern is 25-50% of the initial grant per year at high
performers, less elsewhere)?

**The stacking math** below shows how overlapping 4-year grants add up: with
steady $100k refreshers on top of a $400k initial grant, annual vesting stays
roughly flat instead of falling off a cliff in year 5.
"""


@dataclass
class Grant:
    start_year: int
    total: float
    years: int = 4

    def vests_in(self, year: int) -> float:
        """Dollars vesting in a calendar year (straight-line)."""
        if self.years < 1:
            raise EquityError("Grant years must be >= 1.")
        if self.start_year <= year < self.start_year + self.years:
            return self.total / self.years
        return 0.0


def parse_grants(raw: str) -> list[Grant]:
    """Parse '400000:2026:4,100000:2027:4' into Grants."""
    s = (raw or "").strip()
    if not s:
        raise EquityError("Provide grants like '400000:2026:4,100000:2027:4'.")
    grants = []
    for chunk in s.split(","):
        parts = chunk.strip().split(":")
        if len(parts) not in (2, 3):
            raise EquityError(f"Could not parse grant '{chunk}'. "
                              "Use total:start_year[:years].")
        try:
            total = float(parts[0])
            year = int(parts[1])
            years = int(parts[2]) if len(parts) == 3 else 4
        except ValueError:
            raise EquityError(f"Could not parse grant '{chunk}'.")
        if total <= 0 or years < 1:
            raise EquityError(f"Grant '{chunk}' needs total > 0 and years >= 1.")
        grants.append(Grant(year, total, years))
    return grants


def refresh_stack(grants: list[Grant]) -> list[dict]:
    """Year-by-year vesting totals across overlapping grants."""
    if not grants:
        raise EquityError("Provide at least one grant.")
    first = min(g.start_year for g in grants)
    last = max(g.start_year + g.years for g in grants)
    rows = []
    for y in range(first, last):
        parts = [(g, g.vests_in(y)) for g in grants]
        rows.append({
            "year": y,
            "total": round(sum(v for _, v in parts), 2),
            "by_grant": [(g.start_year, round(v, 2)) for g, v in parts if v > 0],
        })
    return rows


def render_refresh(grants: list[Grant]) -> str:
    rows = refresh_stack(grants)
    lines = [REFRESH_GUIDE, "",
             "## Stacking math", "",
             f"{'Year':<8}{'Vesting':>12}{'From grants (start year)':>28}",
             "-" * 50]
    for r in rows:
        detail = ", ".join(f"{_money(v)} ({sy})" for sy, v in r["by_grant"])
        lines.append(f"{r['year']:<8}{_money(r['total']):>12}{detail:>28}")
    lines += ["",
              "Straight-line vesting assumed; real grants may use custom "
              "schedules. Values at grant-date prices - actual vest value "
              "depends on the share price that day.", "", DISCLAIMER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. dilution: explainer + ownership calculator
# ---------------------------------------------------------------------------

DILUTION_GUIDE = """# Dilution, explained

Your ownership percentage is your shares divided by the company's total
shares. When the company issues new shares - to investors, to new hires, or
to grow the option pool - the denominator grows and your percentage shrinks.
That is dilution.

**It is normal.** Every funding round dilutes existing holders; the bet is
that the company becomes worth enough that your smaller slice is worth more
in dollars.

**Fully diluted matters.** Always do ownership math on the fully-diluted
share count (all options, RSUs, convertibles included), not just shares
outstanding - otherwise your percentage looks bigger than it is.

**Watch the option pool shuffle.** If the company increases the option pool
(say 10% to 15%) right before a funding round, existing holders absorb that
dilution. It is standard, but worth knowing it happened.
"""


def ownership(your_shares: float, fully_diluted: float,
              new_pool_pct: float = 0) -> dict:
    """Ownership % now, and after an option-pool increase.

    your_shares: shares (or options) you hold. fully_diluted: total
    fully-diluted shares. new_pool_pct: e.g. 0.15 if the pool grows to 15%
    of fully diluted (0 = no change modeled).
    """
    your_shares = _num(your_shares, "your_shares")
    fully_diluted = _num(fully_diluted, "fully_diluted")
    new_pool_pct = _num(new_pool_pct, "new_pool_pct")
    if your_shares < 0 or fully_diluted <= 0:
        raise EquityError("your_shares must be >= 0 and fully_diluted > 0.")
    if your_shares > fully_diluted:
        raise EquityError("your_shares cannot exceed fully_diluted.")
    if not 0 <= new_pool_pct < 1:
        raise EquityError("new_pool_pct must be between 0 and 1.")
    now = your_shares / fully_diluted
    out = {"ownership_pct": round(now * 100, 4),
           "fully_diluted": fully_diluted}
    if new_pool_pct:
        # new shares issued so the pool becomes new_pool_pct of the new total
        new_total = fully_diluted / (1 - new_pool_pct)
        after = your_shares / new_total
        out.update({
            "new_total_shares": round(new_total, 0),
            "new_shares_issued": round(new_total - fully_diluted, 0),
            "ownership_after_pct": round(after * 100, 4),
            "dilution_pts": round((now - after) * 100, 4),
        })
    return out


def render_dilution(result: dict, your_shares: float,
                    new_pool_pct: float) -> str:
    lines = [DILUTION_GUIDE, "",
             "## Calculator",
             f"Your shares/options: {your_shares:,.0f}; fully-diluted total: "
             f"{result['fully_diluted']:,.0f}",
             f"**Your ownership: {result['ownership_pct']:.3f}%**"]
    if new_pool_pct:
        lines += ["",
                  f"After growing the option pool to {new_pool_pct:.0%}:",
                  f"- New fully-diluted total: {result['new_shares_issued']:,.0f} "
                  f"new shares ({result['new_total_shares']:,.0f} total)",
                  f"- **Your ownership: {result['ownership_after_pct']:.3f}%** "
                  f"(-{result['dilution_pts']:.3f} pts)"]
    lines += ["",
              "Ownership % is only half the story - multiply by your estimate "
              "of company value for the dollar picture.", "", DISCLAIMER]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 11. checklist: questions to ask about equity in an offer
# ---------------------------------------------------------------------------

CHECKLIST = [
    ("What kind of equity is it?", "RSUs, ISOs, NSOs, or a mix? The kind drives everything about tax and risk."),
    ("How many shares (not just dollars)?", "A $200k grant at a $50 share price is 4,000 shares; at $25 it is 8,000. Get the share count."),
    ("What is the vesting schedule?", "4 years with a 1-year cliff is standard; get the exact shape (25/25/25/25? monthly? quarterly?)."),
    ("Is there a cliff?", "How long, and what happens to the accrued chunk if you leave just before it?"),
    ("For options: what is the strike price?", "And the current 409A fair market value - the gap between them is your built-in spread."),
    ("When was the last 409A valuation?", "A stale 409A can mean the strike understates (or overstates) current value."),
    ("What is the post-termination exercise window?", "90 days is standard; some startups extend to 2-10 years. This decides how much pressure a departure puts on you."),
    ("Do options expire?", "Usually 10 years from grant. RSUs can also expire (some at 7 years)."),
    ("Are there refresh grants?", "Annual? Automatic or performance-based? Typical size relative to the initial grant?"),
    ("Double-trigger RSUs?", "At a private company: do RSUs need a liquidity event (IPO/acquisition) before you actually receive shares?"),
    ("What is the fully-diluted share count?", "Lets you compute your real ownership % (see `equity dilution`)."),
    ("Any liquidation preference overhang?", "In a mediocre exit, investors paid first can leave little for common holders."),
]


def get_checklist() -> list[dict]:
    return [{"question": q, "why": w} for q, w in CHECKLIST]


def render_checklist(as_json: bool = False) -> str:
    if as_json:
        return json.dumps(get_checklist(), indent=2)
    lines = ["# Equity questions to ask about an offer", "",
             "Ask the recruiter or hiring manager these before you sign. The "
             "answers change the real value of the equity by a lot.", ""]
    for i, (q, w) in enumerate(CHECKLIST, 1):
        lines.append(f"**{i}. {q}**")
        lines.append(f"   {w}")
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12. quiz: equity literacy self-check
# ---------------------------------------------------------------------------

QUIZ = [
    {
        "q": "You are granted 1,000 RSUs vesting over 4 years. At the first vest (250 shares), the stock is at $40. What happens tax-wise?",
        "options": [
            "Nothing - RSUs are never taxed",
            "$10,000 of ordinary income in that year",
            "Only capital gains tax when you eventually sell",
            "You owe the strike price times 250 shares",
        ],
        "answer": 1,
        "why": "RSUs are taxed as ordinary income at vest on the market value that day: 250 x $40 = $10,000.",
    },
    {
        "q": "You hold NSOs with a $10 strike. The stock is at $30 when you exercise 1,000 options. What is taxed as ordinary income?",
        "options": [
            "$10,000 (the strike times shares)",
            "Nothing until you sell",
            "$20,000 (the spread times shares)",
            "$30,000 (the full market value)",
        ],
        "answer": 2,
        "why": "NSO spread at exercise is ordinary income: ($30 - $10) x 1,000 = $20,000.",
    },
    {
        "q": "For ISOs to get qualifying-disposition treatment, you must hold the shares:",
        "options": [
            "1 year from grant",
            "2 years from grant AND 1 year from exercise",
            "Until the company IPOs",
            "90 days from exercise",
        ],
        "answer": 1,
        "why": "Both clocks must run: more than 2 years after grant and more than 1 year after exercise.",
    },
    {
        "q": "Your options have a $25 strike and the stock falls to $20. The options are:",
        "options": [
            "Worth $5 per share (strike minus price)",
            "Underwater and worth $0 unless the price recovers",
            "Automatically repriced to $20",
            "Converted to RSUs",
        ],
        "answer": 1,
        "why": "Options are worth max($0, price - strike). Underwater options have no intrinsic value.",
    },
    {
        "q": "A 1-year cliff on a 4-year vesting schedule means:",
        "options": [
            "You get 25% of the grant on day one",
            "Nothing vests for 12 months, then 25% vests at once",
            "Vesting stops after 1 year",
            "You must stay 5 years total",
        ],
        "answer": 1,
        "why": "The first 12 months accrue; at the cliff date the accrued 25% vests in one chunk.",
    },
    {
        "q": "The company grows its option pool from 10% to 15% of fully-diluted shares. Your ownership percentage:",
        "options": [
            "Stays the same - pools do not affect holders",
            "Increases, because there are more options",
            "Decreases - new shares were issued, growing the denominator",
            "Converts to a fixed dollar amount",
        ],
        "answer": 2,
        "why": "Dilution: your shares divided by a bigger total = a smaller percentage.",
    },
]


def quiz_score(answers: list[int]) -> dict:
    """Score quiz answers (0-based indices). Returns score + per-question results."""
    results = []
    correct = 0
    for i, item in enumerate(QUIZ):
        given = answers[i] if i < len(answers) else None
        ok = given == item["answer"]
        correct += ok
        results.append({
            "n": i + 1,
            "question": item["q"],
            "your_answer": given,
            "correct_answer": item["answer"],
            "correct": ok,
            "why": item["why"],
        })
    return {"score": correct, "total": len(QUIZ), "results": results}


def render_quiz(answers: list[int] | None = None) -> str:
    letters = "abcd"
    lines = ["# Equity literacy self-check", ""]
    if answers is None:
        lines.append("Answer a-f conceptually, then check yourself with "
                     "`equity quiz --answers 1,2,1,1,1,2` (0-based indices).")
        lines.append("")
        for i, item in enumerate(QUIZ, 1):
            lines.append(f"**{i}. {item['q']}**")
            for j, opt in enumerate(item["options"]):
                lines.append(f"   {letters[j]}) {opt}")
            lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)
    res = quiz_score(answers)
    lines.append(f"**Score: {res['score']}/{res['total']}**")
    lines.append("")
    for r in res["results"]:
        mark = "correct" if r["correct"] else "missed"
        lines.append(f"{r['n']}. [{mark}] {r['question']}")
        if not r["correct"]:
            item = QUIZ[r["n"] - 1]
            lines.append(f"   Correct: {letters[item['answer']]}) "
                         f"{item['options'][item['answer']]}")
        lines.append(f"   Why: {r['why']}")
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def parse_answers(raw: str) -> list[int]:
    """Parse '1,2,1,1,1,2' into answer indices."""
    s = (raw or "").strip()
    if not s:
        raise EquityError("Provide answers like --answers 1,2,1,1,1,2.")
    try:
        ans = [int(p) for p in s.replace(",", " ").split()]
    except ValueError:
        raise EquityError(f"Could not parse answers '{raw}'.")
    if any(a < 0 or a > 3 for a in ans):
        raise EquityError("Answers must be 0-3 (one per option a-d).")
    if len(ans) != len(QUIZ):
        raise EquityError(f"Expected {len(QUIZ)} answers, got {len(ans)}.")
    return ans
