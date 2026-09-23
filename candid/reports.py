"""Trend reports and a custom report builder over the application tracker.

- trend_report(): per-week or per-month activity buckets ending this week/month,
  with counts for added applications, responses, interviews, and offers.
- build_report(): filtered CSV/Markdown report over tracker applications.

Response attribution prefers each record's ``status_history`` (a sibling
feature: a list of status-change entries) when present; otherwise responses
are estimated from ``date_updated`` of records currently sitting in a response
status, and the affected bucket rows are marked ``"estimated": True``. All
optional tracker fields (``source``, ``status_history``) are read defensively
so the module works with or without them.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C
from candid import tracker as T


class ReportsError(Exception):
    """Raised for invalid report operations."""


log = C.get_logger("reports")

REPORT_FIELDS = ["id", "company", "role", "status", "source", "notes",
                 "date_added", "date_updated"]


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------

def _parse_date(value: object) -> date | None:
    """Parse a date from str/date/datetime; None when unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _history_events(app: dict) -> list[tuple[str, date | None]]:
    """Extract (status, date) pairs from a record's status_history, defensively.

    Accepts entries as dicts (keys like {"status","date"}, {"to","changed_at"},
    {"status","at"}) or as 2-element [status, date]/[date, status] lists.
    Entries with no recognizable status are skipped; missing dates come back
    as None.
    """
    events: list[tuple[str, date | None]] = []
    hist = app.get("status_history") or []
    if not isinstance(hist, list):
        return events
    for entry in hist:
        status: str | None = None
        when: date | None = None
        if isinstance(entry, dict):
            status = entry.get("status") or entry.get("to")
            for key in ("date", "changed_at", "at", "timestamp"):
                if entry.get(key):
                    when = _parse_date(entry[key])
                    break
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            a, b = entry
            known = {s.lower() for s in C.STATUSES}
            if isinstance(a, str) and a.lower() in known:
                status, when = a, _parse_date(b)
            elif isinstance(b, str) and b.lower() in known:
                status, when = b, _parse_date(a)
        if status:
            events.append((str(status).lower(), when))
    return events


# ---------------------------------------------------------------------------
# trend buckets
# ---------------------------------------------------------------------------

def _weekly_buckets(n: int, today: date) -> list[tuple[str, date, date]]:
    """n week buckets (Mon-Sun), oldest first, ending this week."""
    monday = today - timedelta(days=today.weekday())
    buckets = []
    for i in range(n - 1, -1, -1):
        start = monday - timedelta(weeks=i)
        end = start + timedelta(days=6)
        iso = start.isocalendar()
        buckets.append((f"{iso.year}-W{iso.week:02d}", start, end))
    return buckets


def _monthly_buckets(n: int, today: date) -> list[tuple[str, date, date]]:
    """n month buckets, oldest first, ending this month."""
    months: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    buckets = []
    for y, m in reversed(months):
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
        buckets.append((f"{y}-{m:02d}", start, end))
    return buckets


def _bucket_index(buckets: list[tuple[str, date, date]], day: date) -> int | None:
    for i, (_, start, end) in enumerate(buckets):
        if start <= day <= end:
            return i
    return None


def trend_report(period: str = "weekly", n: int = 8,
                 *, path: str | Path | None = None) -> list[dict]:
    """Per-period activity buckets ending this week/month.

    Each row: {"period", "added", "responses", "interviews", "offers",
    "estimated"}. Responses/interviews/offers come from status_history dates
    when present; otherwise they are estimated from date_updated of records
    currently in a response status, and that row is marked estimated=True.
    """
    if period not in ("weekly", "monthly"):
        raise ReportsError(
            f"Unknown period {period!r}. Use 'weekly' or 'monthly'. "
            "Next: run `python -m candid reports --help`")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ReportsError(
            f"Invalid -n value {n!r}. It must be a positive integer. "
            "Next: run `python -m candid reports --help`")
    today = date.today()
    buckets = _weekly_buckets(n, today) if period == "weekly" else _monthly_buckets(n, today)
    rows = [{"period": label, "added": 0, "responses": 0,
             "interviews": 0, "offers": 0, "estimated": False}
            for label, _, _ in buckets]

    for app in T._load(path):
        # applications added
        idx = _bucket_index(buckets, _parse_date(app.get("date_added"))) if app.get("date_added") else None
        if idx is not None:
            rows[idx]["added"] += 1
        # responses / interviews / offers
        events = _history_events(app)
        if events:
            for status, when in events:
                if when is None:
                    continue
                idx = _bucket_index(buckets, when)
                if idx is None:
                    continue
                if status in C.RESPONSE_STATUSES:
                    rows[idx]["responses"] += 1
                if status in ("selected_for_interview", "offer"):
                    rows[idx]["interviews"] += 1
                if status == "offer":
                    rows[idx]["offers"] += 1
        elif app.get("status") in C.RESPONSE_STATUSES:
            # estimated: no history, fall back to the current status + date_updated
            when = _parse_date(app.get("date_updated"))
            if when is None:
                continue
            idx = _bucket_index(buckets, when)
            if idx is None:
                continue
            rows[idx]["responses"] += 1
            rows[idx]["estimated"] = True
            if app["status"] in ("selected_for_interview", "offer"):
                rows[idx]["interviews"] += 1
            if app["status"] == "offer":
                rows[idx]["offers"] += 1
    return rows


def render_trend(rows: list[dict], format: str = "text") -> str:
    """Render trend_report rows as a text table or a Markdown table."""
    if format not in ("text", "md"):
        raise ReportsError(
            f"Unknown format {format!r}. Use 'text' or 'md'. "
            "Next: run `python -m candid reports --help`")
    if format == "md":
        lines = ["| Period | Added | Responses | Interviews | Offers |",
                 "|---|---|---|---|---|"]
        for r in rows:
            star = " *" if r.get("estimated") else ""
            lines.append(
                f"| {r['period']}{star} | {r['added']} | {r['responses']} | "
                f"{r['interviews']} | {r['offers']} |")
        if any(r.get("estimated") for r in rows):
            lines.append("")
            lines.append("* Estimated from current statuses (no status_history).")
        return "\n".join(lines)

    periods = [r["period"] + ("*" if r.get("estimated") else "") for r in rows]
    w = max([len("Period")] + [len(p) for p in periods]) if periods else len("Period")
    lines = [f"{'Period':<{w}}  Added  Resp  Intv  Offers"]
    for r, p in zip(rows, periods):
        lines.append(f"{p:<{w}}  {r['added']:>5}  {r['responses']:>4}  "
                     f"{r['interviews']:>4}  {r['offers']:>6}")
    if any(r.get("estimated") for r in rows):
        lines.append("")
        lines.append("* Estimated from current statuses (no status_history).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# custom report builder
# ---------------------------------------------------------------------------

def _validate_ymd(value: str, flag: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ReportsError(
            f"Invalid {flag} date {value!r}. Use YYYY-MM-DD format. "
            "Next: run `python -m candid report build --help`") from None
    return value


def build_report(*, status: str | None = None, source: str = "",
                 company: str = "", since: str = "", until: str = "",
                 format: str = "csv", out: str | Path | None = None,
                 path: str | Path | None = None) -> Path:
    """Build a filtered tracker report (CSV or Markdown). All filters are ANDed.

    since/until compare date_added (YYYY-MM-DD). Returns the output path.
    """
    if status is not None and status not in C.STATUSES:
        raise ReportsError(
            f"Unknown status {status!r}. Choose from: {', '.join(C.STATUSES)}. "
            "Next: run `python -m candid report build --help`")
    if format not in ("csv", "md"):
        raise ReportsError(
            f"Unknown format {format!r}. Use 'csv' or 'md'. "
            "Next: run `python -m candid report build --help`")
    since = _validate_ymd(since, "--since") if since else ""
    until = _validate_ymd(until, "--until") if until else ""

    apps = T._load(path)

    def keep(a: dict) -> bool:
        if status is not None and a.get("status") != status:
            return False
        if source and a.get("source", "").lower() != source.lower():
            return False
        if company and company.lower() not in a.get("company", "").lower():
            return False
        added = a.get("date_added", "")
        if since and added < since:
            return False
        if until and added > until:
            return False
        return True

    shown = sorted((a for a in apps if keep(a)),
                   key=lambda a: (a.get("date_added", ""), a.get("id", 0)))

    ext = "csv" if format == "csv" else "md"
    if out is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        p = C.DATA_DIR / f"report-{ts}.{ext}"
    else:
        p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, extrasaction="ignore")
            w.writeheader()
            for a in shown:
                w.writerow({k: a.get(k, "") for k in REPORT_FIELDS})
    else:
        lines = ["| " + " | ".join(REPORT_FIELDS) + " |",
                 "|" + "|".join(["---"] * len(REPORT_FIELDS)) + "|"]
        for a in shown:
            cells = [str(a.get(k, "")).replace("|", "/") for k in REPORT_FIELDS]
            lines.append("| " + " | ".join(cells) + " |")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("report built: %s (%d rows)", p, len(shown))
    return p
