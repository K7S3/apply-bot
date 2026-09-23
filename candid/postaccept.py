"""Post-accept milestone tracker: what happens after you sign the offer.

Once an offer is accepted, the job search is over but the money calendar is
just starting. This module tracks:

    1.  record_acceptance()  accepted-offer record (start date, comp, grant)
    2.  cliff_date()         1-year (or custom) cliff date from the start date
    3.  vesting_events()     full vesting calendar for the initial grant
    4.  add_refresher()      annual refresher grants, each with its own vesting
    5.  first_year_milestones()  30/60/90-day, 6-month and 1-year checklist
    6.  mark_milestone_done()/add_milestone()  check off or add milestones
    7.  promotion_checkins() 6/9/12-month promotion-prep check-ins
    8.  upcoming_reminders() one sorted nudge list: vests, milestones, cliff,
                             promo check-ins due soon or overdue
    9.  tenure()             days/weeks/months since the start date
    10. comp_realization()   vested vs unvested value at a share price
    11. render_dashboard()   one-screen text summary of all of the above

Everything is driven by data the user enters - nothing is estimated from the
network. Stored at candid_data/postaccept.json (git-ignored).

Date math is pure and deterministic so tests never depend on "today".
"""

from __future__ import annotations

import calendar
import json
import os
from datetime import date, timedelta
from pathlib import Path

from candid import config as C


class PostAcceptError(Exception):
    """Raised for invalid post-accept data or operations."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _data_path() -> Path:
    """Resolve the store path at call time so CANDID_DATA_DIR overrides work."""
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    return base / "postaccept.json"


def _blank_state() -> dict:
    return {"record": None, "refreshers": [], "milestones": []}


def _load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _data_path()
    if not p.exists():
        return _blank_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PostAcceptError(f"Post-accept file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        return _blank_state()
    state = _blank_state()
    state.update({k: v for k, v in data.items() if k in state})
    return state


def _save(state: dict, path: str | Path | None = None) -> None:
    p = Path(path) if path else _data_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        raise PostAcceptError(
            f"Invalid {field} '{value}': expected YYYY-MM-DD.") from None


def _today(value: date | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return _parse_date(value, "today")


def add_months(d: date, months: int) -> date:
    """Add months, clamping to the last day of the target month."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def cliff_date(start: date | str, cliff_months: int = 12) -> date:
    """The vesting cliff date: start_date + cliff_months (default 12)."""
    d = _parse_date(start, "start_date") if not isinstance(start, date) else start
    if cliff_months < 0:
        raise PostAcceptError("cliff_months cannot be negative.")
    return add_months(d, cliff_months)


# ---------------------------------------------------------------------------
# 1. acceptance record
# ---------------------------------------------------------------------------

REQUIRED_RECORD_FIELDS = ["company", "role", "start_date"]


def _money(value, field: str) -> float:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        raise PostAcceptError(f"Expected a dollar amount for {field}, got '{value}'.") from None
    if num < 0:
        raise PostAcceptError(f"{field} cannot be negative.")
    return num


def _shares(value, field: str) -> float:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        raise PostAcceptError(f"Expected a share count for {field}, got '{value}'.") from None
    if num < 0:
        raise PostAcceptError(f"{field} cannot be negative.")
    return num


def _parse_schedule(value: str | None) -> list[float]:
    """'25/25/25/25' -> [25.0, 25.0, 25.0, 25.0]; must sum to ~100."""
    raw = (value or "25/25/25/25").strip()
    try:
        parts = [float(p) for p in raw.split("/")]
    except ValueError:
        raise PostAcceptError(
            f"Invalid vest schedule '{value}': expected like '25/25/25/25'.") from None
    if not parts or any(p < 0 for p in parts):
        raise PostAcceptError(f"Invalid vest schedule '{value}'.")
    if abs(sum(parts) - 100.0) > 0.01:
        raise PostAcceptError(
            f"Vest schedule '{value}' sums to {sum(parts)}, expected 100.")
    return parts


def record_acceptance(company: str, role: str, start_date: str | date, *,
                      level: str = "", base: float = 0,
                      bonus_target_pct: float = 0, sign_on: float = 0,
                      shares: float = 0, grant_value: float = 0,
                      grant_date: str | date | None = None,
                      vest_years: int = 4, schedule: str = "25/25/25/25",
                      cliff_months: int = 12,
                      path: str | Path | None = None) -> dict:
    """Record the accepted offer. Regenerates the first-year milestones."""
    if not (company or "").strip():
        raise PostAcceptError("company is required.")
    if not (role or "").strip():
        raise PostAcceptError("role is required.")
    start = _parse_date(start_date, "start_date") if not isinstance(start_date, date) else start_date
    gdate = grant_date
    if gdate is None:
        gdate = start
    elif not isinstance(gdate, date):
        gdate = _parse_date(gdate, "grant_date")
    vest_years = int(vest_years)
    if vest_years < 1:
        raise PostAcceptError("vest_years must be at least 1.")
    pcts = _parse_schedule(schedule)
    if len(pcts) != vest_years:
        raise PostAcceptError(
            f"Schedule has {len(pcts)} parts but vest_years={vest_years}.")
    cliff_months = int(cliff_months)
    if cliff_months < 0:
        raise PostAcceptError("cliff_months cannot be negative.")

    record = {
        "company": company.strip(),
        "role": role.strip(),
        "level": (level or "").strip(),
        "start_date": start.isoformat(),
        "base": _money(base, "base"),
        "bonus_target_pct": _money(bonus_target_pct, "bonus_target_pct"),
        "sign_on": _money(sign_on, "sign_on"),
        "shares": _shares(shares, "shares"),
        "grant_value": _money(grant_value, "grant_value"),
        "grant_date": gdate.isoformat(),
        "vest_years": vest_years,
        "schedule": "/".join(str(int(p) if p == int(p) else p) for p in pcts),
        "cliff_months": cliff_months,
        "recorded_on": date.today().isoformat(),
    }
    state = _load(path)
    state["record"] = record
    state["milestones"] = [m for m in state["milestones"] if m.get("kind") == "custom"]
    state["milestones"] = first_year_milestones(start) + state["milestones"]
    _save(state, path)
    return record


def load_record(path: str | Path | None = None) -> dict:
    """Return the acceptance record, or raise if none is recorded."""
    record = _load(path)["record"]
    if not record:
        raise PostAcceptError(
            "No accepted offer recorded yet. Run `postaccept record` first.")
    return record


# ---------------------------------------------------------------------------
# 3. vesting calendar
# ---------------------------------------------------------------------------

def _split_yearly(total: float, parts: list[float]) -> list[float]:
    """Split total into per-year amounts that sum exactly to total."""
    amounts = [round(total * p / 100.0, 4) for p in parts]
    amounts[-1] = round(amounts[-1] + (total - sum(amounts)), 4)
    return amounts


def vesting_events(record: dict | None = None,
                   refreshers: list[dict] | None = None,
                   path: str | Path | None = None) -> list[dict]:
    """Full vesting calendar, sorted by date.

    Months up to the cliff accrue and vest as one lump on the cliff date
    (nothing vests before it); later months vest on their month
    anniversary. Refresher grants vest monthly with no cliff.
    Each event: {date, shares, source, kind}.
    """
    if record is None:
        state = _load(path)
        record = state["record"]
        refreshers = state["refreshers"] if refreshers is None else refreshers
    if not record:
        raise PostAcceptError(
            "No accepted offer recorded yet. Run `postaccept record` first.")
    refreshers = refreshers or []

    events: list[dict] = []

    def add_grant(label: str, grant_date: date, shares: float,
                  vest_years: int, pcts: list[float], cliff_months: int) -> None:
        # Model vesting as monthly accruals: month 1..12*vest_years. With a
        # cliff, months 1..cliff_months accrue and pay out as one lump on the
        # cliff date; later months vest on their month anniversary. This
        # matches real RSU mechanics: the cliff pays the accrued first year,
        # then vesting continues monthly (no double-vest on the cliff date).
        yearly = _split_yearly(shares, pcts)
        accruals: list[tuple[int, float]] = []  # (1-based month index, shares)
        for year, year_shares in enumerate(yearly, start=1):
            if year_shares <= 0:
                continue
            monthly = [round(year_shares / 12.0, 4)] * 12
            monthly[-1] = round(monthly[-1] + (year_shares - sum(monthly)), 4)
            base = (year - 1) * 12
            for m in range(12):
                if monthly[m] > 0:
                    accruals.append((base + m + 1, monthly[m]))
        if cliff_months > 0:
            cliff_shares = sum(s for mi, s in accruals if mi <= cliff_months)
            if cliff_shares > 0:
                events.append({
                    "date": add_months(grant_date, cliff_months).isoformat(),
                    "shares": round(cliff_shares, 4),
                    "source": label,
                    "kind": "cliff",
                })
            for mi, s in accruals:
                if mi > cliff_months:
                    events.append({
                        "date": add_months(grant_date, mi).isoformat(),
                        "shares": s,
                        "source": label,
                        "kind": "vest",
                    })
        else:
            for mi, s in accruals:
                events.append({
                    "date": add_months(grant_date, mi - 1).isoformat(),
                    "shares": s,
                    "source": label,
                    "kind": "vest",
                })

    grant_date = _parse_date(record["grant_date"], "grant_date")
    add_grant("initial grant", grant_date, float(record.get("shares") or 0),
              int(record.get("vest_years") or 4),
              _parse_schedule(record.get("schedule")),
              int(record.get("cliff_months") or 0))
    for r in refreshers:
        rdate = _parse_date(r["grant_date"], "grant_date")
        add_grant(f"refresher: {r['label']}", rdate, float(r["shares"]),
                  int(r.get("vest_years") or 4),
                  _parse_schedule(r.get("schedule")), 0)

    events.sort(key=lambda e: (e["date"], e["source"]))
    return events


# ---------------------------------------------------------------------------
# 4. refresher grants
# ---------------------------------------------------------------------------

def add_refresher(label: str, grant_date: str | date, shares: float,
                  vest_years: int = 4, schedule: str = "25/25/25/25",
                  path: str | Path | None = None) -> dict:
    """Track an annual refresher grant with its own vesting timeline."""
    label = (label or "").strip()
    if not label:
        raise PostAcceptError("Refresher label is required (e.g. '2027 refresher').")
    gdate = _parse_date(grant_date, "grant_date") if not isinstance(grant_date, date) else grant_date
    shares = _shares(shares, "shares")
    if shares <= 0:
        raise PostAcceptError("Refresher shares must be positive.")
    vest_years = int(vest_years)
    if vest_years < 1:
        raise PostAcceptError("vest_years must be at least 1.")
    pcts = _parse_schedule(schedule)
    if len(pcts) != vest_years:
        raise PostAcceptError(
            f"Schedule has {len(pcts)} parts but vest_years={vest_years}.")

    state = _load(path)
    if any(r["label"].lower() == label.lower() for r in state["refreshers"]):
        raise PostAcceptError(f"A refresher labeled '{label}' already exists.")
    refresher = {
        "label": label,
        "grant_date": gdate.isoformat(),
        "shares": shares,
        "vest_years": vest_years,
        "schedule": "/".join(str(int(p) if p == int(p) else p) for p in pcts),
    }
    state["refreshers"].append(refresher)
    _save(state, path)
    return refresher


def list_refreshers(path: str | Path | None = None) -> list[dict]:
    return _load(path)["refreshers"]


# ---------------------------------------------------------------------------
# 5-6. first-year milestones
# ---------------------------------------------------------------------------

_MILESTONE_TEMPLATE = [
    ("day-30", "First 30 days: learn the ropes",
     "Know your team's systems, meet your stakeholders, read the runbooks. "
     "Write down every question; the dumb ones expire fast.",
     30, None),
    ("day-60", "First 60 days: ship something small",
     "Land a first scoped win - a bugfix, a dashboard, a doc. "
     "Momentum beats perfection in month two.",
     60, None),
    ("day-90", "90-day check-in: align with your manager",
     "Ask explicitly: 'what does good look like by month 6?' Write the "
     "answer down and revisit it monthly.",
     90, None),
    ("month-6", "6-month mark: review prep starts",
     "Collect your wins in one doc now, while they're fresh. Ask peers for "
     "feedback before the formal cycle.",
     None, 6),
    ("year-1", "1-year anniversary: cliff crossed, promo case ready",
     "Your cliff vests today. Update your brag doc, refresh your market "
     "value, and decide if the promotion case is ready.",
     None, 12),
]


def first_year_milestones(start: date | str) -> list[dict]:
    """The standard first-year checklist, with due dates from the start date."""
    d = _parse_date(start, "start_date") if not isinstance(start, date) else start
    out = []
    for mid, title, detail, days, months in _MILESTONE_TEMPLATE:
        due = d + timedelta(days=days) if days is not None else add_months(d, months)
        out.append({"id": mid, "title": title, "detail": detail,
                    "due": due.isoformat(), "done": False, "done_on": None,
                    "kind": "first-year"})
    return out


def list_milestones(path: str | Path | None = None) -> list[dict]:
    state = _load(path)
    if state["record"] and not any(m.get("kind") == "first-year"
                                   for m in state["milestones"]):
        state["milestones"] = (first_year_milestones(state["record"]["start_date"])
                               + state["milestones"])
        _save(state, path)
    return sorted(state["milestones"], key=lambda m: (m["due"], m["id"]))


def mark_milestone_done(milestone_id: str, done: bool = True,
                        path: str | Path | None = None) -> dict:
    state = _load(path)
    for m in state["milestones"]:
        if m["id"] == milestone_id:
            m["done"] = bool(done)
            m["done_on"] = date.today().isoformat() if done else None
            _save(state, path)
            return m
    raise PostAcceptError(f"No milestone with id '{milestone_id}'.")


def add_milestone(title: str, due: str | date, detail: str = "",
                  path: str | Path | None = None) -> dict:
    """Add a custom milestone (e.g. 'finish onboarding bootcamp')."""
    title = (title or "").strip()
    if not title:
        raise PostAcceptError("Milestone title is required.")
    due_d = _parse_date(due, "due") if not isinstance(due, date) else due
    state = _load(path)
    base = "".join(c if c.isalnum() else "-" for c in title.lower())[:24].strip("-")
    mid = f"custom-{base}" or "custom"
    n = 2
    existing = {m["id"] for m in state["milestones"]}
    while mid in existing:
        mid = f"custom-{base}-{n}"
        n += 1
    m = {"id": mid, "title": title, "detail": detail or "",
         "due": due_d.isoformat(), "done": False, "done_on": None,
         "kind": "custom"}
    state["milestones"].append(m)
    _save(state, path)
    return m


# ---------------------------------------------------------------------------
# 7. promotion check-ins
# ---------------------------------------------------------------------------

_PROMO_TEMPLATE = [
    ("promo-6mo", 6, "Promotion groundwork: 6-month self-review",
     "Write your self-review early: 3 wins, 1 growth area, and the level "
     "rubric one above you. Ask your manager which gaps matter most."),
    ("promo-9mo", 9, "Manager alignment: 9-month promo conversation",
     "Ask directly: 'what would it take to make a promotion case next "
     "cycle?' Get the answer in writing (email recap counts)."),
    ("promo-12mo", 12, "Promotion packet: 12-month case",
     "Assemble the packet: impact bullets with numbers, peer quotes, and a "
     "manager sponsor. If the case isn't ready, name the gap and the plan."),
]


def promotion_checkins(start: date | str) -> list[dict]:
    """6/9/12-month promotion-prep check-ins with due dates and prompts."""
    d = _parse_date(start, "start_date") if not isinstance(start, date) else start
    return [{"id": pid, "title": title, "prompt": prompt,
             "due": add_months(d, months).isoformat()}
            for pid, months, title, prompt in _PROMO_TEMPLATE]


# ---------------------------------------------------------------------------
# 8. reminders
# ---------------------------------------------------------------------------

def upcoming_reminders(today: date | str | None = None, days: int = 30,
                       path: str | Path | None = None) -> list[dict]:
    """One sorted nudge list: vests, milestones, cliff, promo check-ins.

    Includes anything due within `days` from today plus anything overdue
    (not done). Pure read - nothing is sent anywhere.
    """
    now = _today(today)
    horizon = now + timedelta(days=days)
    state = _load(path)
    record = state["record"]
    if not record:
        raise PostAcceptError(
            "No accepted offer recorded yet. Run `postaccept record` first.")
    start = _parse_date(record["start_date"], "start_date")
    reminders: list[dict] = []

    def add(due_iso: str, kind: str, title: str, detail: str = "") -> None:
        due = _parse_date(due_iso, "due")
        if due <= horizon:
            reminders.append({
                "date": due_iso,
                "kind": kind,
                "title": title,
                "detail": detail,
                "overdue": due < now,
                "days_out": (due - now).days,
            })

    for ev in vesting_events(record, state["refreshers"]):
        ev_date = _parse_date(ev["date"], "date")
        if now <= ev_date <= horizon:
            label = "cliff vest" if ev["kind"] == "cliff" else "vest"
            add(ev["date"], label,
                f"{ev['shares']:g} shares vest ({ev['source']})")

    for m in list_milestones(path):
        if not m["done"]:
            add(m["due"], "milestone",
                f"Milestone: {m['title']}", m.get("detail", ""))

    for c in promotion_checkins(start):
        add(c["due"], "promo-checkin", f"Promo: {c['title']}", c["prompt"])

    cliff = cliff_date(start, int(record.get("cliff_months") or 0))
    if now <= cliff <= now + timedelta(days=60):
        reminders.append({
            "date": cliff.isoformat(), "kind": "cliff",
            "title": f"Vesting cliff in {(cliff - now).days} days",
            "detail": "First-year equity vests. Confirm tax withholding with payroll.",
            "overdue": False, "days_out": (cliff - now).days,
        })

    reminders.sort(key=lambda r: (r["date"], r["kind"]))
    return reminders


# ---------------------------------------------------------------------------
# 9. tenure
# ---------------------------------------------------------------------------

def tenure(start: date | str, today: date | str | None = None) -> dict:
    """Days/weeks/months since the start date (negative if not started)."""
    d = _parse_date(start, "start_date") if not isinstance(start, date) else start
    now = _today(today)
    days = (now - d).days
    return {"days": days,
            "weeks": round(days / 7.0, 1),
            "months": round(days / 30.44, 1),
            "started": days >= 0}


# ---------------------------------------------------------------------------
# 10. comp realization
# ---------------------------------------------------------------------------

def comp_realization(price_per_share: float,
                     as_of: date | str | None = None,
                     path: str | Path | None = None) -> dict:
    """Vested vs unvested equity value at a given share price, as of a date."""
    try:
        price = float(price_per_share)
    except (TypeError, ValueError):
        raise PostAcceptError(
            f"Expected a share price, got '{price_per_share}'.") from None
    if price < 0:
        raise PostAcceptError("Share price cannot be negative.")
    now = _today(as_of)
    state = _load(path)
    record = state["record"]
    if not record:
        raise PostAcceptError(
            "No accepted offer recorded yet. Run `postaccept record` first.")

    vested = unvested = 0.0
    by_year: dict[str, dict] = {}
    for ev in vesting_events(record, state["refreshers"]):
        ev_date = _parse_date(ev["date"], "date")
        bucket = by_year.setdefault(str(ev_date.year),
                                    {"vested_shares": 0.0, "upcoming_shares": 0.0})
        if ev_date <= now:
            vested += ev["shares"]
            bucket["vested_shares"] += ev["shares"]
        else:
            unvested += ev["shares"]
            bucket["upcoming_shares"] += ev["shares"]

    def val(shares: float) -> float:
        return round(shares * price, 2)

    return {
        "as_of": now.isoformat(),
        "price_per_share": price,
        "vested_shares": round(vested, 4),
        "vested_value": val(vested),
        "unvested_shares": round(unvested, 4),
        "unvested_value": val(unvested),
        "total_shares": round(vested + unvested, 4),
        "total_value": val(vested + unvested),
        "by_year": {y: {"vested_shares": round(b["vested_shares"], 4),
                        "vested_value": val(b["vested_shares"]),
                        "upcoming_shares": round(b["upcoming_shares"], 4),
                        "upcoming_value": val(b["upcoming_shares"])}
                    for y, b in sorted(by_year.items())},
    }


# ---------------------------------------------------------------------------
# 11. dashboard
# ---------------------------------------------------------------------------

def _fmt_money(n: float) -> str:
    return f"${n:,.0f}"


def render_dashboard(today: date | str | None = None,
                     path: str | Path | None = None) -> str:
    """One-screen text summary: record, cliff, tenure, milestones, reminders."""
    now = _today(today)
    record = load_record(path)
    start = _parse_date(record["start_date"], "start_date")
    cliff = cliff_date(start, int(record.get("cliff_months") or 0))
    ten = tenure(start, now)
    milestones = list_milestones(path)
    done = sum(1 for m in milestones if m["done"])
    reminders = upcoming_reminders(now, days=30, path=path)

    lines = [
        f"# Post-accept: {record['company']} - {record['role']}",
        "",
        f"Start date: {start.isoformat()}  |  Tenure: {ten['days']} days "
        f"({ten['months']} months)",
        f"Cliff: {cliff.isoformat()} ({(cliff - now).days} days out)",
        f"Grant: {record['shares']:g} shares over {record['vest_years']}y "
        f"({record['schedule']})",
        f"Cash: {_fmt_money(record['base'])}/yr base + "
        f"{record['bonus_target_pct']:g}% bonus target + "
        f"{_fmt_money(record['sign_on'])} sign-on",
        "",
        f"## Milestones ({done}/{len(milestones)} done)",
    ]
    for m in milestones:
        box = "x" if m["done"] else " "
        flag = "" if m["done"] or _parse_date(m["due"], "due") >= now else " OVERDUE"
        lines.append(f"- [{box}] {m['due']} {m['title']}{flag}")
    lines += ["", "## Upcoming (30 days)"]
    if reminders:
        for r in reminders:
            tag = "OVERDUE" if r["overdue"] else f"in {r['days_out']}d"
            lines.append(f"- {r['date']} [{r['kind']}] {r['title']} ({tag})")
    else:
        lines.append("- nothing due in the next 30 days")
    return "\n".join(lines)
