"""Ghosting detector: flag tracked applications that went quiet.

An application is "ghosted" when it has seen no status movement in N days
(default 21), measured against the tracker's ``date_updated`` timestamps.
Terminal states (offer, rejected, withdrawn, archived) are never flagged.

For each flagged application the detector suggests a next action:
draft a ``followup check-in`` email or archive it with
``track update --status archived``.
"""

from __future__ import annotations

from datetime import date, datetime

from candid import tracker as T

#: Default quiet window, in days. Overridable via ``track ghosts --days N``.
DEFAULT_GHOST_DAYS = 21

#: Statuses that end a pipeline — applications in these are never ghosted.
TERMINAL_STATUSES = {"offer", "rejected", "withdrawn", "archived"}


class GhostError(Exception):
    """Raised for invalid ghosting-detector operations."""


def _stale_days(updated: str | None, today: date) -> int | None:
    """Days since ``updated`` (a YYYY-MM-DD string). None if unparseable."""
    try:
        d = datetime.strptime(updated or "", "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - d).days


def find_ghosts(days: int = DEFAULT_GHOST_DAYS, *, today: date | None = None,
                path=None) -> list[dict]:
    """Return applications quiet for ``days`` or more, stalest first.

    Each record gets a ``stale_days`` key. Terminal-state applications and
    records with unparseable timestamps are skipped, not flagged.
    """
    if days is None or days < 1:
        raise GhostError(f"--days must be a positive number of days, got {days!r}.")
    today = today or date.today()
    ghosts = []
    for a in T.list_apps(path=path):
        if a.get("status") in TERMINAL_STATUSES:
            continue
        stale = _stale_days(a.get("date_updated"), today)
        if stale is None:
            continue
        if stale >= days:
            ghosts.append({**a, "stale_days": stale})
    return sorted(ghosts, key=lambda a: -a["stale_days"])


def next_actions(app: dict) -> list[str]:
    """Suggested next steps for one ghosted application."""
    check_in = (
        f"python -m candid followup check-in --person \"Recruiter\" "
        f"--role \"{app['role']}\" --company \"{app['company']}\""
    )
    archive = f"python -m candid track update {app['id']} --status archived"
    return [
        f"Draft a check-in email: {check_in}",
        f"Or archive it: {archive}",
    ]


def render_ghosts(ghosts: list[dict], days: int) -> str:
    """Human-readable ghost report, one suggested action block per app."""
    if not ghosts:
        return (f"No ghosted applications — nothing has been quiet for {days}+ days.\n"
                "Keep applying: python -m candid jobs curate")
    lines = [f"{len(ghosts)} ghosted application(s) — quiet for {days}+ days:",
             ""]
    for a in ghosts:
        lines.append(
            f"#{a['id']}  {a['role']} @ {a['company']} [{a['status']}] "
            f"— quiet {a['stale_days']} days (last update {a.get('date_updated', 'unknown')})"
        )
        for act in next_actions(a):
            lines.append(f"      → {act}")
        lines.append("")
    return "\n".join(lines).rstrip()
