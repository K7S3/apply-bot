"""iCal export: interviews + follow-up reminders as one .ics file.

RFC 5545 written with stdlib only. Nothing is submitted anywhere — the
output is a local .ics file you can import into any calendar app.

Events come from two places:
  * tracker applications in interview-ish states (selected_for_interview,
    or applied with an interview date mentioned in the notes) — the date is
    extracted from the notes text (see nudges._scan_text_for_interview_dates);
    entries with NO detectable date are SKIPPED and listed in the report
    (a fabricated time would be worse than a missing event).
  * pending follow-up reminders (nudges.py) — these are dated "today"
    because they are pending now; the description says so explicitly.

All-day events use VALUE=DATE; every line is folded at 75 octets.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path


class IcalError(Exception):
    """Raised when the iCal export can't be produced."""


PRODID = "-//candid//job-search copilot//EN"
CALNAME = "candid — interviews & follow-ups"

# statuses whose applications count as interview events
_INTERVIEW_STATUSES = {"selected_for_interview", "offer"}


# ---------------------------------------------------------------------------
# RFC 5545 text escaping + line folding
# ---------------------------------------------------------------------------

def escape_text(value: str) -> str:
    """Escape TEXT per RFC 5545 §3.3.11: backslash, ;, comma, newlines."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold a content line so every physical line is <= 75 octets.

    First line has no continuation prefix; each continuation starts with
    one space (which is not part of the value). Never splits a UTF-8
    character across the fold boundary.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    chunk: list[str] = []
    limit, prefix = 75, ""
    for ch in line:
        if chunk and len(("".join(chunk) + ch).encode("utf-8")) > limit:
            parts.append(prefix + "".join(chunk))
            chunk, limit, prefix = [], 74, " "
        chunk.append(ch)
    parts.append(prefix + "".join(chunk))
    return "\r\n".join(parts)


# ---------------------------------------------------------------------------
# event collection
# ---------------------------------------------------------------------------

def _uid() -> str:
    return f"{uuid.uuid4().hex}@candid.local"


def collect_events(apps: list[dict] | None = None, *,
                   today: date | None = None) -> tuple[list[dict], list[str]]:
    """Collect VEVENT dicts + a list of human-readable "skipped" notes.

    Each event dict: {uid, dtstart(date), summary, description}.
    """
    from candid import nudges as N
    from candid import tracker as T

    apps = T.list_apps() if apps is None else apps
    today = today or date.today()
    events: list[dict] = []
    skipped: list[str] = []
    seen: set[tuple[int, str, str]] = set()  # dedupe (app_id, date, kind)

    def add(app_id: int, kind: str, dt: date, summary: str, desc: str) -> None:
        key = (app_id, dt.isoformat(), kind)
        if key in seen:
            return
        seen.add(key)
        events.append({
            "uid": _uid(), "dtstart": dt, "kind": kind,
            "summary": summary, "description": desc,
        })

    for a in apps:
        app_id = a.get("id", 0)
        company, role = a.get("company", ""), a.get("role", "")
        status = a.get("status", "")
        label = f"{role} @ {company}"

        # interviews: only with a real detected date, never fabricated
        if status in _INTERVIEW_STATUSES or status == "applied":
            try:
                dates = sorted(set(N._scan_text_for_interview_dates(a)))
            except Exception:
                dates = []
            upcoming = [d for d in dates if d >= today]
            if status in _INTERVIEW_STATUSES and not dates:
                skipped.append(
                    f"Interview for {label}: no interview date found in "
                    f"notes — skipped (run `python -m candid track update "
                    f"{app_id} --notes \"...\"` with a date like 'Oct 5, 2026' "
                    f"and re-export)."
                )
                continue
            for d in (upcoming or dates[:1]):
                when = "today" if d == today else (
                    "tomorrow" if d == date.fromordinal(today.toordinal() + 1)
                    else d.isoformat())
                add(app_id, "interview", d,
                    f"Interview: {label}",
                    f"Interview {when} for {label}. "
                    f"Details in `python -m candid track list` / prep pack. "
                    f"Status: {status.replace('_', ' ')}.")
                break

    # follow-up reminders: pending now, so they are dated today
    try:
        nudges = N.pending_nudges(apps=apps, today=today)
    except Exception:
        nudges = []
    for n in nudges:
        kind = n.get("kind", "")
        if kind == "interview_soon":
            continue  # already covered by the interview event above
        add(n.get("app_id", 0), f"nudge:{kind}", today,
            f"Reminder: {n.get('message', '').split('.')[0]}",
            f"{n.get('message', '')}\nSuggested action: {n.get('action', '')}\n"
            f"Command: {n.get('command', '')}\n"
            f"(Pending nudge — dated {today.isoformat()} because it is due now.)")

    events.sort(key=lambda e: (e["dtstart"].isoformat(), e["kind"]))
    return events, skipped


# ---------------------------------------------------------------------------
# .ics writing
# ---------------------------------------------------------------------------

def render_ics(events: list[dict]) -> str:
    """Render events as an RFC 5545 calendar."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        f"X-WR-CALNAME:{escape_text(CALNAME)}",
    ]
    for e in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{e['uid']}",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{e['dtstart'].strftime('%Y%m%d')}",
            f"SUMMARY:{escape_text(e['summary'])}",
            f"DESCRIPTION:{escape_text(e['description'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    folded = "\r\n".join(fold_line(l) for l in lines)
    return folded + "\r\n"


def export_ics(out: str | Path, apps: list[dict] | None = None, *,
               today: date | None = None) -> tuple[Path, list[dict], list[str]]:
    """Write the tracker + nudges as one .ics file.

    Returns (path, events, skipped_notes).
    """
    p = Path(out)
    events, skipped = collect_events(apps, today=today)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_ics(events), encoding="utf-8", newline="")
    return p, events, skipped


def render_report(path: Path, events: list[dict], skipped: list[str]) -> str:
    lines = [f"Exported {len(events)} event(s) to {path}"]
    for e in events:
        lines.append(f"  • {e['dtstart'].isoformat()}  [{e['kind']}]  {e['summary']}")
    if skipped:
        lines.append("")
        lines.append("Skipped (no date detected — nothing fabricated):")
        for s in skipped:
            lines.append(f"  • {s}")
    return "\n".join(lines)
