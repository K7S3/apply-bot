"""Follow-up scheduler: scan the tracker and suggest timed follow-ups.

Output only: this module NEVER sends email, NEVER mutates the tracker,
and makes no network calls. It reads tracker records, computes how stale
each one is, and returns per-app suggestions (rung + suggested subject)
the user can review.

Conventions (aligned with candid/nudges.py):
    - "last contact" is read from the record's date_updated field
      (the last time the record changed, i.e. last contact with the
      company), falling back to date_added.
    - output dicts use the same field names as nudges.py
      (app_id, company, role) plus scheduler-specific fields.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from candid.drafting import ladder as L

# Statuses that represent an open, follow-up-able thread with a company.
# Saved (never applied), rejected, and withdrawn records are skipped.
ELIGIBLE_STATUSES = frozenset({"applied", "selected_for_interview", "offer"})

# Minimum days of silence before rung 1 becomes eligible.
FRESH_DAYS = 3

DEFAULT_CONFIG = {
    "eligible_statuses": ELIGIBLE_STATUSES,
    "fresh_days": FRESH_DAYS,
}


def _days_since(iso: str, today: date) -> int | None:
    """Days between an ISO date string and today. None if unparseable."""
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None
    return (today - d).days


def _load_apps(tracker) -> list[dict]:
    """Accept a list of app dicts, a tracker.json path, or None (default tracker)."""
    if tracker is None:
        from candid import tracker as T
        return T.list_apps()
    if isinstance(tracker, (str, Path)):
        import json
        data = json.loads(Path(tracker).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    return list(tracker)


def suggest_followups(tracker=None, config=None, today=None) -> list[dict]:
    """Suggest follow-ups for stale applications.

    tracker: None (use the default tracker), a list of app dicts, or a
        path to a tracker.json file. Never mutated, never written.
    config: optional dict overriding {"eligible_statuses", "fresh_days"}.
    today: optional datetime.date, defaulting to date.today() (test seam).

    Returns a list of, most stale first:
        {app_id, company, role, days_stale, ladder (ladder_for dict),
         suggested_subject}
    """
    today = today or date.today()
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    eligible = set(cfg["eligible_statuses"])
    fresh_days = int(cfg["fresh_days"])

    out: list[dict] = []
    for a in _load_apps(tracker):
        status = (a.get("status") or "").strip()
        if status not in eligible:
            continue
        quiet = _days_since(a.get("date_updated") or "", today)
        if quiet is None:
            quiet = _days_since(a.get("date_added") or "", today)
        if quiet is None or quiet < fresh_days:
            continue  # fresh apps need no follow-up
        rungs = L.ladder_for(quiet, status)
        draft = L.render_ladder_draft(
            rungs,
            {
                "company": a.get("company", ""),
                "role": a.get("role", ""),
                "last_contact_date": (a.get("date_updated") or "")[:10],
            },
        )
        out.append({
            "app_id": a.get("id"),
            "company": a.get("company", ""),
            "role": a.get("role", ""),
            "days_stale": quiet,
            "ladder": rungs,
            "suggested_subject": draft["subject"],
        })

    out.sort(key=lambda s: (-s["days_stale"], s["app_id"] if s["app_id"] is not None else 0))
    return out
