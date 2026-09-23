"""Vesting schedule visualizer: timelines, cliffs, charts, refreshers.

Everything is driven by grant data the user enters (or by offers already
recorded with ``python -m candid offer add``) — nothing is estimated from
the network. A grant is described by:

    kind         "shares" (RSUs/options) or "dollars" (cash-settled value)
    total        total shares, or total dollar value at grant
    grant_price  $/share at grant (shares only; used for value math)
    start        vesting commencement date (YYYY-MM-DD)
    years        vesting duration in years
    freq         "monthly" | "quarterly" | "annual"
    cliff_months months before anything vests (0 = no cliff)
    schedule     yearly vest percentages: "straight" (even), "amazon"
                 (5/15/40/40 back-loaded), "front" (40/30/20/10
                 front-loaded), or "custom:25/25/25/25"

Features:

    1. build_schedule()      per-grant vesting timeline (dated events)
    2. cliff markers         events flagged is_cliff + cliff_summary()
    3. cumulative charts     ASCII cumulative vested-value chart
    4. refresher modeling    stack annual refresher grants on the base grant
    5. vesting event table   date / vested / cumulative / value
    6. offer comparison      vesting-basis compare across recorded offers
    7. departure analysis    vested vs forfeited if you leave at month N
    8. price scenarios       bear / base / bull $/share paths
    9. golden handcuffs      unvested-remaining curve (retention incentive)
    10. taxable events       RSU vest = ordinary-income event markers
    11. markdown export      full vesting report to a .md file

Conventions: amounts are rounded to whole shares (or cents for dollar
grants) with largest-remainder so the timeline always sums exactly to the
grant total. Prices compound monthly from an annual growth rate.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, datetime
from pathlib import Path

from candid import config as C

try:
    from candid import offer as _offer_mod
except Exception:  # pragma: no cover - offer module always ships with candid
    _offer_mod = None


class VestingError(Exception):
    """Raised for invalid grant data or operations."""


# Clearly labeled rough estimate - tax law changes and this is not advice.
VEST_TAX_NOTE = (
    "_Rough tax note (estimate, not advice): in the US, RSUs are taxed as "
    "ordinary income when they vest, on the share price at vest — each vest "
    "below is a taxable event even though no cash changes hands (your employer "
    "usually withholds shares to cover it). ISOs/NSOs have different rules. "
    "Confirm the current IRS tables and talk to a tax pro before deciding._"
)

#: vest events per year for each frequency
PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "annual": 1}

#: named yearly-percentage presets (fractions of the grant per year)
PRESETS = {
    "straight": None,  # computed from years: 1/years each year
    "amazon": (0.05, 0.15, 0.40, 0.40),   # back-loaded, 4 years only
    "front": (0.40, 0.30, 0.20, 0.10),    # front-loaded, 4 years only
}

#: chart glyphs, one per overlaid series
SERIES_GLYPHS = ["#", "+", "x", "o", "*"]


# ---------------------------------------------------------------------------
# grant parsing / validation
# ---------------------------------------------------------------------------

def parse_schedule(spec: str, years: int) -> list[float]:
    """Yearly vest fractions from a schedule spec. Sums to 1.0."""
    spec = (spec or "straight").strip().lower()
    if spec == "straight":
        return [1.0 / years] * years
    if spec in PRESETS:
        pcts = PRESETS[spec]
        if len(pcts) != years:
            raise VestingError(
                f"Schedule preset '{spec}' is defined for {len(pcts)} years, "
                f"but the grant vests over {years} years. Use 'straight' or "
                f"'custom:a/b/c/...' instead.")
        return list(pcts)
    if spec.startswith("custom:"):
        parts = spec[len("custom:"):].replace("%", "").split("/")
        try:
            pcts = [float(p) / 100 for p in parts]
        except ValueError:
            raise VestingError(
                f"Custom schedule '{spec}' should look like "
                f"'custom:25/25/25/25'.")
        if len(pcts) != years:
            raise VestingError(
                f"Custom schedule has {len(pcts)} yearly parts but the grant "
                f"vests over {years} years.")
        if abs(sum(pcts) - 1.0) > 0.005:
            raise VestingError(
                f"Custom schedule '{spec}' should sum to 100.")
        if any(p < 0 for p in pcts):
            raise VestingError("Custom schedule parts must be >= 0.")
        return pcts
    raise VestingError(
        f"Unknown schedule '{spec}'. Use straight, amazon, front, or "
        f"custom:a/b/c/...")


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise VestingError(
            f"Could not parse date '{s}'. Use YYYY-MM-DD.")


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def normalize_grant(spec: dict) -> dict:
    """Validate a grant spec dict and fill defaults. Returns a new dict."""
    g = dict(spec)
    kind = str(g.get("kind", "dollars")).lower()
    if kind not in ("dollars", "shares"):
        raise VestingError("Grant kind must be 'dollars' or 'shares'.")
    g["kind"] = kind

    try:
        total = float(g.get("total", 0))
    except (TypeError, ValueError):
        raise VestingError(f"Grant total must be a number, got '{g.get('total')}'.")
    if total <= 0:
        raise VestingError("Grant total must be > 0.")
    g["total"] = total

    if kind == "shares":
        try:
            gp = float(g.get("grant_price", 0))
        except (TypeError, ValueError):
            raise VestingError("grant_price must be a number.")
        if gp <= 0:
            raise VestingError("Share grants need grant_price > 0 for value math.")
        g["grant_price"] = gp
        if abs(total - round(total)) > 1e-9:
            raise VestingError("Share grants need a whole number of shares.")

    start = g.get("start")
    g["start"] = _parse_date(start) if isinstance(start, str) else (
        start if isinstance(start, date) else date.today())

    years = int(g.get("years", 4))
    if years < 1:
        raise VestingError("Grant years must be >= 1.")
    g["years"] = years

    freq = str(g.get("freq", "monthly")).lower()
    if freq not in PERIODS_PER_YEAR:
        raise VestingError(f"freq must be one of {sorted(PERIODS_PER_YEAR)}.")
    g["freq"] = freq

    cliff = int(g.get("cliff_months", 12))
    if cliff < 0:
        raise VestingError("cliff_months must be >= 0.")
    if cliff > years * 12:
        raise VestingError(
            f"cliff_months ({cliff}) is beyond the {years * 12}-month vesting "
            f"period — nothing would ever vest.")
    g["cliff_months"] = cliff

    g["yearly"] = parse_schedule(str(g.get("schedule", "straight")), years)
    g["label"] = str(g.get("label") or "Grant")
    return g


def grant_from_offer(offer: dict) -> dict:
    """Build a dollar-grant spec from a recorded offer (candid.offer)."""
    schedule = str(offer.get("vest_schedule") or "").strip()
    years = int(offer.get("vest_years") or 4)
    spec = {
        "kind": "dollars",
        "total": float(offer.get("equity_total") or 0),
        "start": offer.get("start_date") or date.today().isoformat(),
        "years": years,
        "freq": "monthly",
        "cliff_months": 12,
        "schedule": f"custom:{schedule}" if schedule else "straight",
        "label": f"{offer.get('company', 'Offer')} equity",
    }
    return normalize_grant(spec)


# ---------------------------------------------------------------------------
# 1. vesting timeline
# ---------------------------------------------------------------------------

def _round_units(exact: list[float], quantum: float) -> list[float]:
    """Largest-remainder rounding so amounts sum exactly to the grant total.

    quantum is 1.0 for share grants, 0.01 for dollar grants.
    """
    total = sum(exact)
    floored = [math.floor(x / quantum + 1e-9) * quantum for x in exact]
    # guard against float dust pushing a value a hair below an integer
    floored = [round(f, 10) for f in floored]
    leftover = int(round((total - sum(floored)) / quantum))
    order = sorted(range(len(exact)),
                   key=lambda i: (exact[i] - floored[i], -i), reverse=True)
    for i in order[:max(leftover, 0)]:
        floored[i] = round(floored[i] + quantum, 10)
    # final dust fix on the last event so the total is exact
    if floored:
        floored[-1] = round(floored[-1] + (total - sum(floored)), 10)
    return floored


def build_schedule(spec: dict) -> list[dict]:
    """Build the vesting timeline for one grant.

    Returns a list of events, each a dict with:
        date, month (months since start), units (shares or $),
        cumulative (units), is_cliff, grant (label).
    Events before the cliff accrue into the cliff event.
    """
    g = normalize_grant(spec)
    ppy = PERIODS_PER_YEAR[g["freq"]]
    step = 12 // ppy
    total_months = g["years"] * 12

    # exact (float) units per vest date, ignoring the cliff first
    dates: list[date] = []
    exact: list[float] = []
    for year in range(1, g["years"] + 1):
        year_amount = g["total"] * g["yearly"][year - 1]
        for k in range(1, ppy + 1):
            month = (year - 1) * 12 + k * step
            dates.append(_add_months(g["start"], month))
            exact.append(year_amount / ppy)

    # apply the cliff: everything before it accrues into the cliff event
    cliff_idx = next((i for i, m in
                      enumerate(range(step, total_months + 1, step))
                      if m >= g["cliff_months"]), None)
    if cliff_idx is None:  # pragma: no cover - guarded by normalize_grant
        raise VestingError("Cliff falls beyond the vesting period.")
    if cliff_idx > 0:
        acc = sum(exact[:cliff_idx])
        exact = [exact[cliff_idx] + acc] + exact[cliff_idx + 1:]
        dates = dates[cliff_idx:]
        is_cliff = [True] + [False] * (len(dates) - 1)
    else:
        is_cliff = [False] * len(dates)

    quantum = 1.0 if g["kind"] == "shares" else 0.01
    units = _round_units(exact, quantum)

    events = []
    cum = 0.0
    for i, (d, u) in enumerate(zip(dates, units)):
        if u <= 0 and not is_cliff[i]:
            continue
        cum = round(cum + u, 10)
        month = (d.year - g["start"].year) * 12 + (d.month - g["start"].month)
        events.append({
            "date": d,
            "month": month,
            "units": u,
            "cumulative": cum,
            "is_cliff": is_cliff[i],
            "grant": g["label"],
            "kind": g["kind"],
        })
    return events


# ---------------------------------------------------------------------------
# 2. cliff markers
# ---------------------------------------------------------------------------

def cliff_summary(events: list[dict]) -> dict | None:
    """Describe the cliff event, or None when the grant has no cliff."""
    for e in events:
        if e.get("is_cliff"):
            total = events[-1]["cumulative"] if events else 0
            return {
                "date": e["date"],
                "month": e["month"],
                "units": e["units"],
                "pct_of_grant": (e["units"] / total * 100) if total else 0,
            }
    return None


# ---------------------------------------------------------------------------
# value math + 8. price scenarios
# ---------------------------------------------------------------------------

def price_path(start_price: float, months: int,
               annual_growth_pct: float) -> list[float]:
    """Monthly $/share prices compounding from an annual growth rate."""
    if start_price <= 0:
        raise VestingError("start_price must be > 0.")
    monthly = (1 + annual_growth_pct / 100) ** (1 / 12) - 1
    return [start_price * (1 + monthly) ** m for m in range(months + 1)]


def event_value(event: dict, price: float | None = None) -> float:
    """Dollar value of one vest event at a given $/share price.

    Dollar grants are already dollars (price ignored); share grants need
    a price (defaults to the grant price when omitted).
    """
    if event.get("kind") == "dollars":
        return float(event["units"])
    return float(event["units"]) * float(
        event.get("grant_price", 0) if price is None else price)


def _price_at(events: list[dict], prices: list[float] | None,
              fallback: float) -> dict[date, float]:
    """Map each event date to its $/share price (for share grants)."""
    if not events or events[0].get("kind") == "dollars":
        return {}
    return {e["date"]: prices[e["month"]] if prices and e["month"] < len(prices)
            else fallback for e in events}


def cumulative_value_series(events: list[dict], months: int,
                            prices: list[float] | None = None,
                            grant_price: float | None = None) -> list[float]:
    """Cumulative vested $ at each month-end 0..months."""
    if not events:
        return [0.0] * (months + 1)
    kind = events[0].get("kind")
    pmap = _price_at(events, prices, grant_price or 0)
    by_month: dict[int, float] = {}
    for e in events:
        price = pmap.get(e["date"], grant_price or 0) if kind == "shares" else None
        by_month[e["month"]] = by_month.get(e["month"], 0.0) + event_value(
            {**e, "grant_price": grant_price}, price)
    out, cum = [], 0.0
    for m in range(months + 1):
        cum += by_month.get(m, 0.0)
        out.append(round(cum, 2))
    return out


def scenario_series(events: list[dict], months: int,
                    price_start: float,
                    scenarios: dict[str, float] | None = None,
                    grant_price: float | None = None) -> dict[str, list[float]]:
    """Cumulative vested $ per month under bear/base/bull price scenarios.

    scenarios maps a name to an annual growth %. For dollar grants every
    scenario is the same flat series (price risk does not apply).
    """
    scenarios = scenarios or {"bear": -10.0, "base": 5.0, "bull": 20.0}
    if not events:
        return {name: [0.0] * (months + 1) for name in scenarios}
    if events[0].get("kind") == "dollars":
        flat = cumulative_value_series(events, months)
        return {name: list(flat) for name in scenarios}
    gp = grant_price or price_start
    out = {}
    for name, growth in scenarios.items():
        prices = price_path(price_start, months, growth)
        out[name] = cumulative_value_series(events, months, prices,
                                            grant_price=gp)
    return out


# ---------------------------------------------------------------------------
# 3. cumulative value chart (ASCII)
# ---------------------------------------------------------------------------

def render_chart(series: dict[str, list[float]], months: int,
                 title: str = "Cumulative vested value",
                 width: int = 60, height: int = 12) -> str:
    """ASCII line chart of one or more (month -> $) series."""
    names = list(series)
    if not names:
        return "No data to chart."
    top = max((max(v) for v in series.values() if v), default=0)
    if top <= 0:
        return "No vested value to chart yet."
    glyphs = {n: SERIES_GLYPHS[i % len(SERIES_GLYPHS)]
              for i, n in enumerate(names)}
    grid = [[" "] * width for _ in range(height)]
    for name in names:
        vals = series[name]
        for m in range(months + 1):
            v = vals[m] if m < len(vals) else vals[-1]
            x = round(m / months * (width - 1)) if months else 0
            y = height - 1 - round(v / top * (height - 1))
            if grid[y][x] == " ":
                grid[y][x] = glyphs[name]
    lines = [title,
             "  ".join(f"{glyphs[n]} {n}" for n in names),
             f"${top:,.0f} " + "+" + "-" * width]
    for r in grid:
        lines.append(" " * 9 + "|" + "".join(r))
    lines.append(" " * 9 + "+" + "-" * width)
    lines.append(f"{'mo 0':>9} {'mo ' + str(months):>{width - 4}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. vesting event table
# ---------------------------------------------------------------------------

def _fmt_money(x) -> str:
    return f"${float(x):,.0f}"


def _fmt_units(e: dict) -> str:
    if e.get("kind") == "shares":
        return f"{e['units']:,.0f} sh"
    return _fmt_money(e["units"])


def render_table(events: list[dict], prices: list[float] | None = None,
                 grant_price: float | None = None,
                 title: str = "Vesting timeline") -> str:
    """Per-event table: date, vested, cumulative, value, cliff flags."""
    if not events:
        return "No vesting events."
    pmap = _price_at(events, prices, grant_price or 0)
    lines = [title,
             f"{'Date':<12}{'Vested':>12}{'Cumulative':>14}{'Value':>12}  "]
    for e in events:
        price = pmap.get(e["date"]) if e.get("kind") == "shares" else None
        val = event_value({**e, "grant_price": grant_price}, price)
        flag = "  <-- CLIFF" if e.get("is_cliff") else ""
        lines.append(
            f"{e['date'].isoformat():<12}{_fmt_units(e):>12}"
            f"{_fmt_units({**e, 'units': e['cumulative']}):>14}"
            f"{_fmt_money(val):>12}{flag}")
    lines.append(f"{'TOTAL':<12}{_fmt_units(events[-1]):>12}"
                 f"{_fmt_units({**events[-1], 'units': events[-1]['cumulative']}):>14}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. refresher modeling
# ---------------------------------------------------------------------------

def parse_refresher(spec: str, base_start: date) -> dict:
    """Parse 'VALUE:YEARS:START' where START is months offset or YYYY-MM-DD.

    Refreshers vest straight-line monthly with no cliff (the common Big Tech
    pattern); the assumption is stated wherever it is rendered.
    """
    parts = spec.split(":")
    if len(parts) != 3:
        raise VestingError(
            f"Refresher '{spec}' should look like 'VALUE:YEARS:START', e.g. "
            f"'40000:2:12' (starts month 12) or '40000:2:2027-06-01'.")
    try:
        value, years = float(parts[0]), int(parts[1])
    except ValueError:
        raise VestingError(f"Could not parse refresher '{spec}'.")
    start_raw = parts[2]
    if start_raw.lstrip("-").isdigit():
        start = _add_months(base_start, int(start_raw))
    else:
        start = _parse_date(start_raw)
    if value <= 0 or years < 1:
        raise VestingError(f"Refresher '{spec}' needs VALUE > 0 and YEARS >= 1.")
    return {
        "kind": "dollars",
        "total": value,
        "start": start,
        "years": years,
        "freq": "monthly",
        "cliff_months": 0,
        "schedule": "straight",
        "label": f"Refresher {start.isoformat()}",
    }


def add_refreshers(base_spec: dict, refresher_specs: list[str]) -> list[dict]:
    """Stack refresher grants onto the base grant; one merged timeline.

    Events keep their ``grant`` label so the combined table/chart can show
    what came from the base grant vs each refresher. Refreshers vest
    straight-line monthly with no cliff.
    """
    base = normalize_grant(base_spec)
    all_events = build_schedule(base)
    for rspec in refresher_specs:
        rspec_parsed = parse_refresher(rspec, base["start"])
        all_events.extend(build_schedule(rspec_parsed))
    all_events.sort(key=lambda e: (e["date"], e["grant"]))
    # recompute the merged cumulative column
    cum = 0.0
    for e in all_events:
        cum = round(cum + e["units"], 10)
        e["cumulative"] = cum
    return all_events


def render_refresher_summary(base_spec: dict, refresher_specs: list[str],
                             events: list[dict]) -> str:
    """Explain what the refresher stack adds on top of the base grant."""
    base = normalize_grant(base_spec)
    lines = ["Refresher modeling",
             f"Base: {base['label']} — {_fmt_money(base['total'])} over "
             f"{base['years']}y ({base['freq']}, {base['cliff_months']}mo cliff)",
             "Refreshers vest straight-line monthly with no cliff.",
             ""]
    total_refresh = 0.0
    for rspec in refresher_specs:
        r = parse_refresher(rspec, base["start"])
        total_refresh += r["total"]
        lines.append(f"  + {_fmt_money(r['total'])} over {r['years']}y "
                     f"starting {r['start'].isoformat()}")
    lines += ["",
              f"Combined grant value: {_fmt_money(base['total'] + total_refresh)}",
              f"Combined vest events: {len(events)}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. offer comparison on a vesting basis
# ---------------------------------------------------------------------------

def compare_offers(offers: list[dict],
                   at_months: tuple[int, ...] = (12, 24, 36, 48)) -> list[dict]:
    """Vested equity value per offer at 12/24/36/48 months (grant-date $).

    Uses each offer's equity_total / vest_years / vest_schedule; monthly
    vesting with a 12-month cliff is assumed and stated in the rendering.
    """
    rows = []
    for o in offers:
        try:
            spec = grant_from_offer(o)
        except VestingError:
            continue
        events = build_schedule(spec)
        if not events:
            continue
        total = events[-1]["cumulative"]
        row = {"company": o.get("company", "?"),
               "role": f"{o.get('role', '')} {o.get('level', '')}".strip(),
               "equity_total": total}
        for m in at_months:
            vested = sum(e["units"] for e in events if e["month"] <= m)
            row[f"m{m}"] = round(vested, 2)
        rows.append(row)
    return sorted(rows, key=lambda r: r.get("m48", r.get("m36", 0)),
                  reverse=True)


def render_offer_vesting_comparison(rows: list[dict],
                                    at_months: tuple[int, ...] = (12, 24, 36, 48)
                                    ) -> str:
    """Side-by-side vested-value table across offers."""
    if not rows:
        return ("No offers with equity to compare. Add one with: "
                "python -m candid offer add ...")
    header = f"{'Company':<18}{'Grant value':>13}" + "".join(
        f"{f'Vested mo {m}':>15}" for m in at_months)
    lines = ["Offer vesting comparison (grant-date $, monthly vest, 12mo cliff)",
             header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['company'][:18]:<18}{_fmt_money(r['equity_total']):>13}" +
            "".join(f"{_fmt_money(r[f'm{m}']):>15}" for m in at_months))
    lines += ["",
              "Assumes monthly vesting with a 12-month cliff at grant-date "
              "value (no price change). Use `vesting chart --offer-id N` "
              "with price scenarios to stress-test the $/share path.",
              "",
              VEST_TAX_NOTE]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. departure analysis ("what if I leave at month N")
# ---------------------------------------------------------------------------

def departure_analysis(events: list[dict], at_month: int) -> dict:
    """Vested vs forfeited value if employment ends at_month months in."""
    if at_month < 0:
        raise VestingError("at_month must be >= 0.")
    if not events:
        raise VestingError("No vesting events to analyze.")
    total = events[-1]["cumulative"]
    vested = sum(e["units"] for e in events if e["month"] <= at_month)
    upcoming = sum(e["units"] for e in events
                   if at_month < e["month"] <= at_month + 12)
    forfeited = round(total - vested, 10)
    return {
        "at_month": at_month,
        "vested": round(vested, 2),
        "forfeited": round(forfeited, 2),
        "upcoming_12mo": round(upcoming, 2),
        "pct_vested": round(vested / total * 100, 1) if total else 0.0,
        "kind": events[0].get("kind"),
    }


def render_departure(a: dict, label: str = "Grant") -> str:
    """Human-readable departure report."""
    unit = "sh" if a["kind"] == "shares" else "$"
    fmt = (lambda x: f"{x:,.0f} sh") if a["kind"] == "shares" else _fmt_money
    return "\n".join([
        f"Departure analysis — {label}, leaving at month {a['at_month']}",
        f"  Vested:                {fmt(a['vested'])} ({a['pct_vested']}%)",
        f"  Forfeited (walk away): {fmt(a['forfeited'])}",
        f"  Vesting in next 12mo:  {fmt(a['upcoming_12mo'])}",
        "",
        "The forfeited amount is what unvested equity is worth to your "
        "employer as a retention tool — it is also your walk-away cost.",
    ])


# ---------------------------------------------------------------------------
# 9. golden handcuffs (unvested-remaining curve)
# ---------------------------------------------------------------------------

def handcuffs(events: list[dict], months: int,
              prices: list[float] | None = None,
              grant_price: float | None = None) -> list[float]:
    """Unvested remaining $ at each month-end 0..months (retention curve)."""
    cum = cumulative_value_series(events, months, prices, grant_price)
    total = cum[-1] if cum else 0.0
    return [round(total - c, 2) for c in cum]


def render_handcuffs(events: list[dict], months: int,
                     prices: list[float] | None = None,
                     grant_price: float | None = None,
                     label: str = "Grant") -> str:
    """Golden-handcuffs report: unvested value left on the table over time."""
    curve = handcuffs(events, months, prices, grant_price)
    chart = render_chart({"unvested $": curve}, months,
                         title=f"Golden handcuffs — {label} (unvested $ remaining)")
    marks = [0, 12, 24, 36, 48]
    rows = [f"  mo {m:<3} {_fmt_money(curve[m])} unvested"
            for m in marks if m <= months]
    return "\n".join([chart, "",
                      "Unvested value remaining:"] + rows +
                     ["",
                      "This is the retention incentive your employer holds: "
                      "leaving forfeits the unvested remainder."])


# ---------------------------------------------------------------------------
# 10. taxable events (RSU vest = ordinary income)
# ---------------------------------------------------------------------------

def tax_events(events: list[dict], prices: list[float] | None = None,
               grant_price: float | None = None) -> list[dict]:
    """Each vest as an estimated taxable-income event (RSUs)."""
    if not events:
        return []
    pmap = _price_at(events, prices, grant_price or 0)
    out = []
    cum = 0.0
    for e in events:
        price = pmap.get(e["date"]) if e.get("kind") == "shares" else None
        taxable = event_value({**e, "grant_price": grant_price}, price)
        cum = round(cum + taxable, 2)
        out.append({"date": e["date"], "month": e["month"],
                    "taxable": round(taxable, 2), "cumulative_taxable": cum,
                    "kind": e.get("kind")})
    return out


def render_tax_events(tevents: list[dict], label: str = "Grant") -> str:
    """Table of estimated taxable-income events."""
    if not tevents:
        return "No vesting events."
    lines = [f"Taxable events (estimate) — {label}",
             f"{'Date':<12}{'Taxable income':>16}{'Cumulative':>14}"]
    for t in tevents:
        lines.append(f"{t['date'].isoformat():<12}"
                     f"{_fmt_money(t['taxable']):>16}"
                     f"{_fmt_money(t['cumulative_taxable']):>14}")
    lines += ["", VEST_TAX_NOTE]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 11. markdown export
# ---------------------------------------------------------------------------

def export_report(spec: dict, path: str | Path | None = None,
                  refresher_specs: list[str] | None = None,
                  price_start: float | None = None,
                  annual_growth_pct: float = 0.0) -> Path:
    """Write a full vesting report (table, chart, cliff, departure, tax)."""
    g = normalize_grant(spec)
    events = (add_refreshers(g, refresher_specs or []) if refresher_specs
              else build_schedule(g))
    months = g["years"] * 12
    prices = (price_path(price_start, months, annual_growth_pct)
              if price_start and g["kind"] == "shares" else None)
    gp = g.get("grant_price") or price_start

    cliff = cliff_summary([e for e in events if e["grant"] == g["label"]])
    cum = cumulative_value_series(events, months, prices, gp)
    chart = render_chart({"cumulative vested $": cum}, months,
                         title="Cumulative vested value")
    dep = departure_analysis(events, months // 2)

    if path is None:
        d = C.DATA_DIR / "vesting_reports"
        d.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-" for c in g["label"].lower())
        path = d / f"{date.today().isoformat()}_vesting_{slug or 'grant'}.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    unit_word = "shares" if g["kind"] == "shares" else "dollars"
    lines = [
        f"# Vesting report — {g['label']}",
        "",
        f"*Generated {date.today().isoformat()}*",
        "",
        "## Grant",
        "",
        f"- Type: {g['kind']} ({unit_word}), total "
        f"{_fmt_units({'kind': g['kind'], 'units': g['total']})}",
        f"- Start: {g['start'].isoformat()}, {g['years']} years, {g['freq']}",
        f"- Cliff: {g['cliff_months']} months",
        f"- Schedule: {g.get('schedule', 'straight')}",
    ]
    if refresher_specs:
        lines += ["", "## Refreshers",
                  "",
                  render_refresher_summary(g, refresher_specs, events)]
    if cliff:
        lines += ["", "## Cliff",
                  "",
                  f"First vest on {cliff['date'].isoformat()} (month "
                  f"{cliff['month']}): {_fmt_money(cliff['units'])} "
                  f"({cliff['pct_of_grant']:.1f}% of grant)."]
    lines += ["", "## Cumulative vested value",
              "",
              "```",
              chart,
              "```",
              "",
              "## Vesting events",
              "",
              "```",
              render_table(events, prices, gp),
              "```",
              "",
              "## Departure snapshot",
              "",
              "```",
              render_departure(dep, g["label"]),
              "```",
              "",
              "## Taxable events",
              "",
              "```",
              render_tax_events(tax_events(events, prices, gp), g["label"]),
              "```",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# offer-backed helpers for the CLI
# ---------------------------------------------------------------------------

def list_offer_grants() -> list[dict]:
    """Recorded offers that carry equity, as grant specs."""
    if _offer_mod is None:
        return []
    return [grant_from_offer(o) for o in _offer_mod.list_offers()
            if float(o.get("equity_total") or 0) > 0]


def grant_by_offer_id(offer_id: int) -> dict:
    """Grant spec for one recorded offer id."""
    if _offer_mod is None:
        raise VestingError("Offer module is unavailable.")
    for o in _offer_mod.list_offers():
        if int(o.get("id", -1)) == int(offer_id):
            if not float(o.get("equity_total") or 0) > 0:
                raise VestingError(f"Offer #{offer_id} has no equity recorded.")
            return grant_from_offer(o)
    raise VestingError(f"No offer #{offer_id} found. "
                       "See: python -m candid offer list")
