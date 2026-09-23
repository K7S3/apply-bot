"""Consistency checks for the candid tracker.

Checks:
  unknown_status          (error)   - status not in config.STATUSES
  impossible_dates        (error/warning) - bad or impossible date_added/date_updated
  duplicate_ids           (error)   - two records sharing the same id
  status_without_evidence (warning) - interview status with no date in notes
  messy_values            (warning) - leading/trailing whitespace in text fields
  missing_date_updated    (info)    - empty date_updated with a valid date_added
"""

from __future__ import annotations

import re
from datetime import date

try:  # primary contract
    from candid.quality import Issue
except ImportError:  # pragma: no cover - local fallback, identical fields
    from dataclasses import dataclass, field

    @dataclass
    class Issue:
        check: str
        severity: str
        record_id: "int | None"
        message: str
        suggestion: str = ""
        auto_fix: "str | None" = None
        fix_args: dict = field(default_factory=dict)

try:
    from candid import config as _config
    _STATUSES: tuple[str, ...] = tuple(_config.STATUSES)
except ImportError:  # pragma: no cover - local fallback
    _STATUSES = ("saved", "applied", "selected_for_interview",
                 "rejected", "offer", "withdrawn")

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse_date(value) -> "date | None":
    """Return a date for ISO-ish input, else None. Accepts date objects too."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _unknown_status(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    lowered = {s.lower(): s for s in _STATUSES}
    for app in apps:
        status = app.get("status")
        if status in _STATUSES:
            continue
        match = lowered.get(str(status or "").lower())
        if match:
            issues.append(Issue(
                check="unknown_status",
                severity="error",
                record_id=app.get("id"),
                message=(
                    f"Application id={app.get('id')} has status "
                    f"'{status}', which only differs in case from the valid "
                    f"status '{match}'."
                ),
                suggestion=f"Normalize the status to '{match}'.",
                auto_fix="normalize_status",
                fix_args={"app_id": app.get("id"), "status": match},
            ))
        else:
            issues.append(Issue(
                check="unknown_status",
                severity="error",
                record_id=app.get("id"),
                message=(
                    f"Application id={app.get('id')} has unknown status "
                    f"'{status}'."
                ),
                suggestion=(
                    "Pick a valid status: " + ", ".join(_STATUSES) + "."
                ),
            ))
    return issues


def _impossible_dates(apps: list[dict], today: date) -> list[Issue]:
    issues: list[Issue] = []
    for app in apps:
        rid = app.get("id")
        added = _parse_date(app.get("date_added"))
        if added is None:
            issues.append(Issue(
                check="impossible_dates",
                severity="error",
                record_id=rid,
                message=(
                    f"Application id={rid} has an unparseable date_added "
                    f"({app.get('date_added')!r})."
                ),
                suggestion="Set date_added to a valid YYYY-MM-DD date.",
            ))
        elif added > today:
            issues.append(Issue(
                check="impossible_dates",
                severity="error",
                record_id=rid,
                message=(
                    f"Application id={rid} has date_added {added.isoformat()} "
                    f"in the future (today is {today.isoformat()})."
                ),
                suggestion="Correct date_added to the actual date the "
                           "application was added.",
            ))
        updated_raw = app.get("date_updated")
        if updated_raw not in (None, ""):
            updated = _parse_date(updated_raw)
            if updated is None:
                issues.append(Issue(
                    check="impossible_dates",
                    severity="warning",
                    record_id=rid,
                    message=(
                        f"Application id={rid} has an unparseable date_updated "
                        f"({updated_raw!r})."
                    ),
                    suggestion="Set date_updated to a valid YYYY-MM-DD date.",
                ))
            elif added is not None and updated < added:
                issues.append(Issue(
                    check="impossible_dates",
                    severity="error",
                    record_id=rid,
                    message=(
                        f"Application id={rid} has date_updated "
                        f"{updated.isoformat()} earlier than date_added "
                        f"{added.isoformat()}."
                    ),
                    suggestion="Correct the dates so date_updated is on or "
                               "after date_added.",
                ))
    return issues


def _duplicate_ids(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    seen: set = set()
    for app in apps:
        rid = app.get("id")
        if rid in seen:
            issues.append(Issue(
                check="duplicate_ids",
                severity="error",
                record_id=rid,
                message=(
                    f"Two records share id={rid}; ids must be unique."
                ),
                suggestion=(
                    "Reassign a fresh id to one of the records (e.g. the "
                    "higher-date one) so every record has a unique id."
                ),
            ))
        else:
            seen.add(rid)
    return issues


def _status_without_evidence(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    for app in apps:
        if app.get("status") != "selected_for_interview":
            continue
        notes = str(app.get("notes") or "")
        if _DATE_RE.search(notes):
            continue
        issues.append(Issue(
            check="status_without_evidence",
            severity="warning",
            record_id=app.get("id"),
            message=(
                f"Application id={app.get('id')} is marked "
                f"selected_for_interview but the notes contain no date "
                f"(expected YYYY-MM-DD)."
            ),
            suggestion="Log the interview date in the notes, e.g. "
                       "'Interview on 2026-10-05'.",
        ))
    return issues


_WHITESPACE_FIELDS = ("company", "role", "notes", "jd_link")


def _messy_values(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    for app in apps:
        messy = [f for f in _WHITESPACE_FIELDS
                 if isinstance(app.get(f), str) and app[f] != app[f].strip()]
        if not messy:
            continue
        issues.append(Issue(
            check="messy_values",
            severity="warning",
            record_id=app.get("id"),
            message=(
                f"Application id={app.get('id')} has leading/trailing "
                f"whitespace in: {', '.join(messy)}."
            ),
            suggestion="Trim the whitespace with `candid quality --fix`.",
            auto_fix="strip_whitespace",
            fix_args={"app_id": app.get("id")},
        ))
    return issues


def _missing_date_updated(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    for app in apps:
        if app.get("date_updated") not in (None, ""):
            continue
        if _parse_date(app.get("date_added")) is None:
            continue
        issues.append(Issue(
            check="missing_date_updated",
            severity="info",
            record_id=app.get("id"),
            message=(
                f"Application id={app.get('id')} has no date_updated; "
                f"it can safely default to date_added."
            ),
            suggestion="Fill date_updated with `candid quality --fix`.",
            auto_fix="fill_date_updated",
            fix_args={"app_id": app.get("id")},
        ))
    return issues


def run(apps: list[dict], ctx: dict) -> list[Issue]:
    """Run all consistency checks. ctx must carry 'today' (datetime.date)."""
    today = ctx.get("today") if isinstance(ctx, dict) else None
    if not isinstance(today, date):
        today = date.today()
    return (
        _unknown_status(apps)
        + _impossible_dates(apps, today)
        + _duplicate_ids(apps)
        + _status_without_evidence(apps)
        + _messy_values(apps)
        + _missing_date_updated(apps)
    )
