"""Timing patterns: weekday / time-of-day and deadline-proximity response analysis.

Built on top of candid.timing's baseline API (W-core, batch 25):

- cmd_weekday(a):  response rate per day-of-week you applied, plus an
  optional morning/afternoon/evening split when records carry time info.
- cmd_deadline(a): response rate by how early before the deadline you applied.

Both take an argparse Namespace with a ``json`` bool (a.json).
No em dashes anywhere, per project style.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from candid.timing import (
    MIN_SAMPLE,
    enough_data,
    get_applied_date,
    get_deadline,
    honesty_note,
    is_positive,
    load_applications,
    response_rate,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

# (bucket label, predicate over days-before-deadline)
DEADLINE_BUCKETS = [
    ("7+ days early", lambda d: d >= 7),
    ("3-6 days early", lambda d: 3 <= d <= 6),
    ("1-2 days early", lambda d: 1 <= d <= 2),
    ("last day / late", lambda d: d <= 0),
]

TIME_OF_DAY_BUCKETS = [
    ("morning", lambda h: 5 <= h < 12),
    ("afternoon", lambda h: 12 <= h < 17),
    ("evening", lambda h: 17 <= h < 22),
    ("night", lambda h: h >= 22 or h < 5),
]


def bucket_deadline(days_before: int) -> str:
    """Bucket days_before_deadline into a display label.

    Exactly 7 days early counts as "7+ days early"; 0 or negative
    (deadline day or past it) counts as "last day / late".
    """
    for label, pred in DEADLINE_BUCKETS:
        if pred(days_before):
            return label
    raise AssertionError(f"no bucket for days_before={days_before!r}")


def bucket_time_of_day(hour: int) -> str:
    for label, pred in TIME_OF_DAY_BUCKETS:
        if pred(hour):
            return label
    raise AssertionError(f"no bucket for hour={hour!r}")


def _applied_parts(app: dict) -> tuple[date | None, int | None]:
    """Return (applied date, applied hour or None).

    The date comes from timing.get_applied_date (applied_date, falling
    back to date_added), which normalizes to a date. The hour is read
    from the raw applied_date / date_added string when it carries a
    non-midnight time component (e.g. "2026-09-22T09:30"). A midnight
    time (00:00) or a date-only value means "no time info".
    """
    d = _as_date(get_applied_date(app))
    if d is None:
        return None, None
    hour = None
    raw = app.get("applied_date") or app.get("date_added")
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.strip())
        except ValueError:
            dt = None
        if dt is not None and (dt.hour, dt.minute, dt.second) != (0, 0, 0):
            hour = dt.hour
    return d, hour


def _as_date(value) -> date | None:
    """Coerce a date/datetime/ISO string to date, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            return None
    return None


def _weekday_rows(dated: list[tuple[date, dict]]) -> list[dict]:
    """Aggregate response stats per weekday. Rows sorted Mon-Sun."""
    groups: dict[int, list[dict]] = {i: [] for i in range(7)}
    for d, app in dated:
        groups[d.weekday()].append(app)
    rows = []
    for i in range(7):
        apps = groups[i]
        rows.append({
            "weekday": WEEKDAYS[i],
            "n": len(apps),
            "responses": sum(1 for a in apps if is_positive(a)),
            "response_rate": response_rate(apps),
        })
    return rows


def _ranked(rows: list[dict]) -> list[dict]:
    """Sort rows by response rate desc, then n desc (zeros last)."""
    return sorted(
        rows,
        key=lambda r: (r["response_rate"] is None, -(r["response_rate"] or 0.0), -r["n"]),
    )


def _weekday_payload() -> dict:
    """Pure data payload for cmd_weekday; also used by --json."""
    apps = load_applications()
    dated = [(d, app) for app in apps
             for d, _h in [_applied_parts(app)] if d is not None]
    with_time = [(d, app, h) for app in apps
                 for d, h in [_applied_parts(app)] if d is not None and h is not None]

    rows = _weekday_rows(dated)
    ranked = _ranked([r for r in rows if r["n"] > 0])

    best = None
    if ranked:
        top = ranked[0]
        best = {"weekday": top["weekday"],
                "response_rate": top["response_rate"], "n": top["n"]}

    tod_rows = []
    tod_best = None
    if with_time:
        groups: dict[str, list[dict]] = {}
        for _d, app, h in with_time:
            groups.setdefault(bucket_time_of_day(h), []).append(app)
        for label, _pred in TIME_OF_DAY_BUCKETS:
            apps_b = groups.get(label, [])
            tod_rows.append({
                "period": label, "n": len(apps_b),
                "responses": sum(1 for a in apps_b if is_positive(a)),
                "response_rate": response_rate(apps_b),
            })
        ranked_tod = _ranked([r for r in tod_rows if r["n"] > 0])
        if ranked_tod:
            t = ranked_tod[0]
            tod_best = {"period": t["period"],
                        "response_rate": t["response_rate"], "n": t["n"]}

    payload = {
        "total_applications": len(apps),
        "with_applied_date": len(dated),
        "weekdays": rows,
        "best": best,
        "time_of_day": tod_rows if with_time else [],
        "time_of_day_captured": bool(with_time),
        "time_of_day_best": tod_best,
        "caveat": None if enough_data(apps, n=MIN_SAMPLE) else honesty_note(apps),
    }
    return payload


def _render_weekday(p: dict) -> str:
    lines = []
    lines.append(f"Best time to apply (n={p['total_applications']} applications, "
                 f"{p['with_applied_date']} with an applied date)")
    lines.append("")
    lines.append(f"{'weekday':<10}{'n':>4}  response rate")
    for r in _ranked([x for x in p["weekdays"] if x["n"] > 0]):
        rate = r["response_rate"]
        rate_s = f"{rate * 100:5.1f}%" if rate is not None else "  n/a "
        lines.append(f"{r['weekday']:<10}{r['n']:>4}  {rate_s}")
    lines.append("")
    if p["best"]:
        b = p["best"]
        lines.append(f"Your best apply day is {b['weekday']} at "
                     f"{b['response_rate'] * 100:.1f}% (n={b['n']}).")
    else:
        lines.append("No applications have an applied date yet - "
                     "add some and re-run.")
    if p["time_of_day_captured"]:
        lines.append("")
        lines.append("Time of day (only from records with a time stamp):")
        for r in _ranked([x for x in p["time_of_day"] if x["n"] > 0]):
            rate = r["response_rate"]
            rate_s = f"{rate * 100:5.1f}%" if rate is not None else "  n/a "
            lines.append(f"  {r['period']:<10}{r['n']:>4}  {rate_s}")
        t = p["time_of_day_best"]
        if t:
            lines.append(f"  Best time of day: {t['period']} at "
                         f"{t['response_rate'] * 100:.1f}% (n={t['n']}).")
    else:
        lines.append("")
        lines.append("Time-of-day data isn't captured yet - include a time "
                     "in your applied date (e.g. 2026-09-22T09:30) "
                     "for a morning/afternoon/evening split.")
    lines.append("")
    if p["caveat"]:
        lines.append(p["caveat"])
    else:
        thin = [r for r in p["weekdays"] if 0 < r["n"] < MIN_SAMPLE]
        if thin:
            lines.append("Note: samples per weekday are thin "
                         f"(fewer than {MIN_SAMPLE} each) - treat these as "
                         "hints, not rules.")
    return "\n".join(lines)


def cmd_weekday(a) -> None:
    """Day-of-week / time-of-day response analysis (dispatch entry)."""
    payload = _weekday_payload()
    if getattr(a, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(_render_weekday(payload))


# ---------------------------------------------------------------------------
# Deadline-proximity analysis
# ---------------------------------------------------------------------------

def _deadline_payload() -> dict:
    apps = load_applications()
    bucketed: list[tuple[str, dict]] = []
    no_deadline = 0
    no_applied_date = 0
    for app in apps:
        applied = _as_date(get_applied_date(app))
        deadline = _as_date(get_deadline(app))
        if applied is None:
            no_applied_date += 1
            continue
        if deadline is None:
            no_deadline += 1
            continue
        days_before = (deadline - applied).days
        bucketed.append((bucket_deadline(days_before), app))

    buckets = []
    for label, _pred in DEADLINE_BUCKETS:
        apps_b = [app for b, app in bucketed if b == label]
        buckets.append({
            "bucket": label, "n": len(apps_b),
            "responses": sum(1 for a in apps_b if is_positive(a)),
            "response_rate": response_rate(apps_b),
        })

    early = [app for b, app in bucketed
             if b in ("7+ days early", "3-6 days early")]
    late = [app for b, app in bucketed if b == "last day / late"]
    early_rate = response_rate(early)
    late_rate = response_rate(late)
    if early_rate is not None and late_rate is not None:
        guidance = (
            f"Applying 3+ days before the deadline converts at "
            f"{early_rate * 100:.1f}% (n={len(early)}) vs "
            f"{late_rate * 100:.1f}% (n={len(late)}) last-minute."
        )
    elif early_rate is not None:
        guidance = (f"Early applications (3+ days before deadline) convert "
                    f"at {early_rate * 100:.1f}% (n={len(early)}); "
                    "not enough last-minute data to compare.")
    elif late_rate is not None:
        guidance = (f"Last-minute applications convert at "
                    f"{late_rate * 100:.1f}% (n={len(late)}); "
                    "not enough early data to compare.")
    else:
        guidance = ("Not enough applications with deadlines yet to compare "
                    "early vs last-minute.")

    payload = {
        "total_applications": len(apps),
        "with_deadline_and_applied_date": len(bucketed),
        "no_deadline": no_deadline,
        "no_applied_date": no_applied_date,
        "buckets": buckets,
        "guidance": guidance,
        "caveat": (None if enough_data(apps, n=MIN_SAMPLE)
                   else honesty_note(apps)),
    }
    return payload


def _render_deadline(p: dict) -> str:
    lines = []
    lines.append(f"Deadline proximity (n={p['with_deadline_and_applied_date']} "
                 "applications with both an applied date and a deadline)")
    lines.append("")
    lines.append(f"{'when you applied':<16}{'n':>4}  response rate")
    for b in p["buckets"]:
        rate = b["response_rate"]
        rate_s = f"{rate * 100:5.1f}%" if rate is not None else "  n/a "
        lines.append(f"{b['bucket']:<16}{b['n']:>4}  {rate_s}")
    lines.append("")
    lines.append(p["guidance"])
    lines.append("")
    if p["no_deadline"]:
        lines.append(f"{p['no_deadline']} applications have no deadline recorded "
                     "- add --deadline to track add for sharper insights.")
    if p["caveat"]:
        lines.append(p["caveat"])
    return "\n".join(lines)


def cmd_deadline(a) -> None:
    """Deadline-proximity response analysis (dispatch entry)."""
    payload = _deadline_payload()
    if getattr(a, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(_render_deadline(payload))
