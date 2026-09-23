"""Best-time-to-apply analysis: seasonal response rates and follow-up timing.

Two CLI entry points (dispatched from ``candid/__main__.py``):

* ``cmd_seasons(a)``  - response rate by applied month / quarter.
* ``cmd_followups(a)`` - best weekday to send follow-ups, derived from when
  responses arrive in the tracker (plus Gmail proposal mail as a labeled
  supplemental signal).
* ``timing_nudge_lines(apps=None)`` - 0-3 short nudge strings for reuse by
  the nudges pipeline. Pure function, defensive: never raises.

Timing primitives come from ``candid.timing`` (batch W-core). A minimal
compat shim below fills in the same API when that module has not landed
yet, so this module and its tests keep working either way. The shim is
clearly marked and becomes inert the moment ``candid.timing`` exists.

Honesty rules: seasonality is only claimed when a pattern is actually
visible (a quarter clearly above/below with n >= MIN_SAMPLE per period).
On thin data we print the honesty note plus the raw table, without grand
claims, and only then add a clearly-labeled general hiring-seasonality
heuristic (marked "not from your data").

Standard library only.
"""

from __future__ import annotations

import json
from datetime import date
from email.utils import parsedate_to_datetime

# ---------------------------------------------------------------------------
# timing API (candid.timing, batch W-core) + compat shim
# ---------------------------------------------------------------------------

try:
    from candid.timing import (  # noqa: F401
        POSITIVE_STATUSES,
        MIN_SAMPLE,
        load_applications,
        get_posted_date,
        get_applied_date,
        get_first_response_date,
        is_positive,
        posting_age_days,
        response_rate,
        enough_data,
        honesty_note,
    )
    _TIMING_SHIM = False
except ImportError:  # pragma: no cover - temporary compat shim
    from candid import config as _C

    POSITIVE_STATUSES = set(_C.RESPONSE_STATUSES)
    MIN_SAMPLE = 5
    _TIMING_SHIM = True

    def load_applications():
        from candid import tracker as _T
        return _T.list_apps()

    def _field_date(app, *keys):
        if not isinstance(app, dict):
            return None
        for k in keys:
            v = app.get(k)
            if not v:
                continue
            try:
                return date.fromisoformat(str(v)[:10])
            except (ValueError, TypeError):
                continue
        return None

    def get_posted_date(app):
        return _field_date(app, "posted_date", "date_posted")

    def get_applied_date(app):
        return _field_date(app, "applied_date", "date_applied", "date_added")

    def get_first_response_date(app):
        return _field_date(app, "first_response_date", "response_date",
                           "date_first_response")

    def is_positive(app):
        return isinstance(app, dict) and app.get("status") in POSITIVE_STATUSES

    def posting_age_days(app):
        posted = get_posted_date(app)
        if posted is None:
            return None
        return (date.today() - posted).days

    def response_rate(apps):
        apps = list(apps)
        if not apps:
            return None
        return sum(1 for a in apps if is_positive(a)) / len(apps)

    def enough_data(apps, n=MIN_SAMPLE):
        return len(list(apps)) >= n

    def honesty_note(apps):
        return ("Your tracker has too few data points for reliable timing "
                "conclusions - treat these numbers as rough hints, not rules.")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]
SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

#: Minimum gap (in response-rate points) between the best and worst qualified
#: period before we call it a visible seasonal pattern.
PATTERN_GAP = 0.20

#: General hiring seasonality. Printed ONLY when the user's own data is too
#: thin to say anything, and always labeled as not-from-your-data.
HEURISTIC_LINE = (
    "General heuristic, not from your data: hiring activity typically peaks "
    "Jan-Mar and Sep-Nov, and slows in December and mid-summer. "
    "Treat this as a rule of thumb, not your record."
)


def _as_date(value):
    """date from whatever the timing getters return (date or ISO string)."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except (ValueError, TypeError):
            return None
    return None


def _pct(rate):
    return "n/a" if rate is None else f"{round(rate * 100)}%"


# ---------------------------------------------------------------------------
# seasonal analysis
# ---------------------------------------------------------------------------

def _month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def _quarter_key(d):
    return f"{d.year:04d}-Q{(d.month - 1) // 3 + 1}"


def season_summary(apps):
    """Aggregate applications by applied month and quarter.

    Returns a dict with sorted period rows
    [{period, n, positives, response_rate}], best/worst picks (among periods
    with n >= MIN_SAMPLE, else None), a pattern verdict, and honesty flags.
    """
    apps = [a for a in (apps or []) if isinstance(a, dict)]
    dated = []
    for a in apps:
        d = _as_date(get_applied_date(a))
        if d is not None:
            dated.append((d, bool(is_positive(a))))

    def bucket(key_fn):
        table = {}
        for d, pos in dated:
            row = table.setdefault(key_fn(d), {"n": 0, "positives": 0})
            row["n"] += 1
            row["positives"] += pos
        rows = [{"period": k, "n": v["n"], "positives": v["positives"],
                 "response_rate": (v["positives"] / v["n"]) if v["n"] else None}
                for k, v in table.items()]
        rows.sort(key=lambda r: r["period"])
        return rows

    months = bucket(_month_key)
    quarters = bucket(_quarter_key)

    def best_worst(rows):
        qualified = [r for r in rows if r["n"] >= MIN_SAMPLE]
        if not qualified:
            return None, None
        ordered = sorted(qualified, key=lambda r: (r["response_rate"], r["n"]))
        return ordered[-1], ordered[0]

    best_month, worst_month = best_worst(months)
    best_quarter, worst_quarter = best_worst(quarters)

    pattern = {"detected": False, "detail": None}
    qualified_q = [r for r in quarters if r["n"] >= MIN_SAMPLE]
    if len(qualified_q) >= 2:
        hi = max(qualified_q, key=lambda r: r["response_rate"])
        lo = min(qualified_q, key=lambda r: r["response_rate"])
        gap = hi["response_rate"] - lo["response_rate"]
        if gap >= PATTERN_GAP:
            pattern = {
                "detected": True,
                "detail": (f"{hi['period']} ({_pct(hi['response_rate'])}, n={hi['n']}) "
                           f"clearly above {lo['period']} "
                           f"({_pct(lo['response_rate'])}, n={lo['n']})"),
            }

    thin = not enough_data(dated, n=MIN_SAMPLE)
    any_qualified = bool(best_quarter or best_month)
    return {
        "n_dated": len(dated),
        "months": months,
        "quarters": quarters,
        "best_month": best_month,
        "worst_month": worst_month,
        "best_quarter": best_quarter,
        "worst_quarter": worst_quarter,
        "pattern": pattern,
        "thin": thin,
        "any_qualified": any_qualified,
        "honesty_note": honesty_note(dated) if thin or not any_qualified else None,
        "heuristic": HEURISTIC_LINE if not any_qualified else None,
    }


def _period_table(title, rows, width=12):
    lines = [title]
    if not rows:
        lines.append("  (no data)")
        return lines
    lines.append(f"  {'Period':<{width}}{'n':>4}  {'responses':>9}  {'rate':>5}")
    for r in rows:
        lines.append(f"  {r['period']:<{width}}{r['n']:>4}  "
                     f"{r['positives']:>9}  {_pct(r['response_rate']):>5}")
    return lines


def render_seasons(summary):
    """Human-readable text for a season_summary dict."""
    lines = ["Seasonal response rates (by applied date)", "=" * 44]
    lines.append(f"n = {summary['n_dated']} applications with applied dates")
    lines.append("")
    lines.extend(_period_table("Applied month:", summary["months"]))
    lines.append("")
    lines.extend(_period_table("Applied quarter:", summary["quarters"]))
    lines.append("")

    if summary["n_dated"] == 0:
        lines.append("No applications with applied dates in your tracker yet.")
        if summary["honesty_note"]:
            lines.append(summary["honesty_note"])
        lines.append(summary["heuristic"])
        return "\n".join(lines)

    def pick_line(label, pick):
        if pick:
            return (f"{label}: {pick['period']} - "
                    f"{_pct(pick['response_rate'])} (n={pick['n']})")
        return None

    for label, pick in (("Best quarter (n>=%d)" % MIN_SAMPLE, summary["best_quarter"]),
                        ("Worst quarter (n>=%d)" % MIN_SAMPLE, summary["worst_quarter"]),
                        ("Best month (n>=%d)" % MIN_SAMPLE, summary["best_month"]),
                        ("Worst month (n>=%d)" % MIN_SAMPLE, summary["worst_month"])):
        line = pick_line(label, pick)
        if line:
            lines.append(line)

    pat = summary["pattern"]
    if pat["detected"]:
        lines.append(f"Seasonality signal: {pat['detail']}.")
    elif summary["any_qualified"]:
        lines.append("No clear seasonal pattern yet - qualified periods are "
                     "within 20 points of each other.")

    if summary["honesty_note"]:
        lines.append("")
        lines.append(summary["honesty_note"])
    if summary["heuristic"]:
        lines.append("")
        lines.append(summary["heuristic"])
    return "\n".join(lines)


def cmd_seasons(a):
    """CLI: seasonal response-rate analysis. Namespace needs .json (bool)."""
    apps = list(load_applications())
    summary = season_summary(apps)
    if getattr(a, "json", False):
        print(json.dumps(summary, indent=2))
    else:
        print(render_seasons(summary))


# ---------------------------------------------------------------------------
# follow-up timing
# ---------------------------------------------------------------------------

def _gmail_proposals():
    """Recruiter inbound proposals stored by gmail import (may be empty)."""
    try:
        from candid import gmail as G
        return G.list_proposals() or []
    except Exception:
        return []


def _proposal_weekdays(proposals):
    """Weekday counts of recruiter inbound mail (parsed Date headers)."""
    counts = [0] * 7
    for p in proposals or []:
        if not isinstance(p, dict):
            continue
        raw = p.get("date") or ""
        try:
            dt = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError, OverflowError):
            continue
        if dt is not None:
            counts[dt.weekday()] += 1
    return counts


def followup_timing(apps):
    """Weekday distribution of when responses ARRIVE (tracker), ranked.

    Also reports the Gmail reality check: stored Gmail data is recruiter
    inbound mail only, so outbound send-time analysis is not possible.
    """
    apps = [a for a in (apps or []) if isinstance(a, dict)]
    counts = [0] * 7
    for a in apps:
        d = _as_date(get_first_response_date(a))
        if d is not None:
            counts[d.weekday()] += 1
    total = sum(counts)
    ranking = [{"weekday": WEEKDAYS[i], "arrivals": counts[i],
                "share": round(counts[i] / total, 3) if total else 0.0}
               for i in range(7)]
    ranking.sort(key=lambda r: (-r["arrivals"], r["weekday"]))

    proposals = _gmail_proposals()
    inbound = _proposal_weekdays(proposals)
    supplemental = None
    if sum(inbound) > 0:
        rows = [{"weekday": WEEKDAYS[i], "messages": inbound[i]}
                for i in range(7)]
        rows.sort(key=lambda r: (-r["messages"], r["weekday"]))
        supplemental = {"n": sum(inbound), "by_weekday": rows,
                        "label": ("Recruiter inbound mail by weekday, from your "
                                  "Gmail proposals (supplemental, not responses)")}

    windows = []
    if total >= MIN_SAMPLE:
        top = [r for r in ranking[:2] if r["arrivals"] > 0]
        for r in top:
            peak_idx = WEEKDAYS.index(r["weekday"])
            send_idx = (peak_idx - 1) % 7  # land just before the peak day
            windows.append(
                f"Send {WEEKDAYS[send_idx]} morning so your note is near the "
                f"top when {r['weekday']} activity hits "
                f"({r['arrivals']} of {total} responses arrived "
                f"{r['weekday']}s).")
    windows.append("Hour of day is a general heuristic, not from your data: "
                   "weekday mornings (local time) beat late nights.")

    return {
        "n_responses": total,
        "weekday_ranking": ranking,
        "suggested_send_windows": windows,
        "data_source": "tracker first_response_date "
                       "(weekday responses ARRIVED; approximate guidance)",
        "gmail_note": ("Your Gmail import stores recruiter inbound mail "
                       "(proposals) only - it does not record your outbound "
                       "follow-ups or their send times, so outbound send-time "
                       "analysis is not possible from stored data."),
        "supplemental_gmail_inbound": supplemental,
        "honesty_note": honesty_note(apps) if total < MIN_SAMPLE else None,
    }


def render_followups(t):
    lines = ["Best time to send follow-ups", "=" * 44]
    lines.append("")
    if t["n_responses"] == 0:
        lines.append("No first-response dates in your tracker yet.")
    else:
        lines.append("Responses arrived on (your tracker):")
        lines.append(f"  {'Weekday':<10}{'responses':>10}  {'share':>6}")
        for r in t["weekday_ranking"]:
            if r["arrivals"]:
                lines.append(f"  {r['weekday']:<10}{r['arrivals']:>10}  "
                             f"{round(r['share'] * 100):>5}%")
    lines.append("")
    lines.append("Suggested send windows (approximate):")
    for w in t["suggested_send_windows"]:
        lines.append(f"  - {w}")
    lines.append("")
    lines.append(f"Data source: {t['data_source']}.")
    lines.append(t["gmail_note"])
    sup = t["supplemental_gmail_inbound"]
    if sup:
        top = ", ".join(f"{r['weekday']} ({r['messages']})"
                        for r in sup["by_weekday"][:3] if r["messages"])
        lines.append(f"Supplemental - {sup['label']}: {sup['n']} messages; "
                     f"busiest: {top}.")
    if t["honesty_note"]:
        lines.append("")
        lines.append(t["honesty_note"])
    return "\n".join(lines)


def cmd_followups(a):
    """CLI: best time to send follow-ups. Namespace needs .json (bool)."""
    apps = list(load_applications())
    t = followup_timing(apps)
    if getattr(a, "json", False):
        print(json.dumps(t, indent=2))
    else:
        print(render_followups(t))


# ---------------------------------------------------------------------------
# timing nudge lines (for the nudges pipeline)
# ---------------------------------------------------------------------------

def _days_since_posted(a: dict, today: date) -> int | None:
    """Days since the job was posted. None when the posting date is unknown."""
    posted = _as_date(get_posted_date(a))
    if posted is None:
        return None
    return (today - posted).days


def timing_nudge_lines(apps=None):
    """0-3 short timing-based nudge strings. Pure function, never raises.

    Example: "3 saved jobs are 5+ days old - your data shows applying within
    3 days converts 2x better". Returns [] when there is nothing worth saying.
    """
    try:
        apps = [a for a in (load_applications() if apps is None else apps)
                if isinstance(a, dict)]
    except Exception:
        return []
    lines = []
    try:
        today = date.today()

        # 1. Stale saved jobs + early-apply conversion uplift from own data.
        # Staleness for a saved (not yet applied) job is measured from the
        # posting date: a posting that has sat 5+ days is going stale.
        saved = [a for a in apps if a.get("status") == "saved"]
        stale = [a for a in saved
                 if (_days_since_posted(a, today) or 0) >= 5]
        early, late = [], []
        for a in apps:
            applied = _as_date(get_applied_date(a))
            posted = _as_date(get_posted_date(a))
            if applied is None or posted is None:
                continue
            age = (applied - posted).days
            if 0 <= age <= 3:
                early.append(a)
            elif age >= 7:
                late.append(a)
        uplift = None
        if len(early) >= 3 and len(late) >= 3:
            r_early = response_rate(early) or 0.0
            r_late = response_rate(late) or 0.0
            if r_late > 0 and r_early >= 2 * r_late:
                uplift = r_early / r_late
        if stale:
            msg = (f"{len(stale)} saved job{'s' if len(stale) != 1 else ''} "
                   f"{'are' if len(stale) != 1 else 'is'} 5+ days old - apply soon")
            if uplift is not None:
                msg += (f"; your data shows applying within 3 days converts "
                        f"{uplift:.0f}x better than waiting a week+")
            lines.append(msg + ".")

        # 2. Peak response weekday -> time follow-ups ahead of it.
        counts = [0] * 7
        for a in apps:
            d = _as_date(get_first_response_date(a))
            if d is not None:
                counts[d.weekday()] += 1
        if sum(counts) >= MIN_SAMPLE:
            peak = max(range(7), key=lambda i: (counts[i], -i))
            if counts[peak] > 0:
                send_day = WEEKDAYS[(peak - 1) % 7]
                lines.append(
                    f"Responses in your tracker peak on {WEEKDAYS[peak]}s - "
                    f"time follow-ups to land {send_day} morning.")

        # 3. Seasonal heads-up if the current quarter is the weakest qualified.
        summary = season_summary(apps)
        if summary["pattern"]["detected"] and summary["worst_quarter"]:
            now_q = _quarter_key(today)
            wq = summary["worst_quarter"]
            if wq["period"] == now_q:
                lines.append(
                    f"It's {now_q} and that's your weakest qualified quarter "
                    f"({_pct(wq['response_rate'])}, n={wq['n']}) - push volume "
                    f"now or save energy for next quarter.")
    except Exception:
        pass
    return lines[:3]
