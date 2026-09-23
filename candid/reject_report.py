"""Rejection resilience report and "what changed" improvement log.

The report aggregates rejection data (by reason category and by stage),
tracks scheduled re-approaches and pending feedback, and logs the
improvements you made after each rejection so progress is visible even when
offers are not.

This module is a pure layer over passed-in data plus a small JSON log file
for changes. It never imports the sibling reject_log module; it accepts
plain rejection dicts.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from candid import config as C
from candid import reject_coach

__all__ = [
    "CHANGES_PATH",
    "RejectReportError",
    "log_change",
    "changes_since",
    "build_report",
    "render",
]

CHANGES_PATH = C.DATA_DIR / "reject_changes.json"


class RejectReportError(Exception):
    """Raised when a change log entry is invalid."""


def _read_changes(path) -> list[dict]:
    path = path or CHANGES_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_changes(entries: list[dict], path) -> None:
    path = path or CHANGES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def log_change(app_id: int, text: str, path=None) -> dict:
    """Log one improvement you made after a rejection.

    Returns the entry ``{"app_id", "text", "date"}``. Raises
    ``RejectReportError`` on empty text.
    """
    text = (text or "").strip()
    if not text:
        raise RejectReportError("Change text must not be empty.")
    entry = {"app_id": app_id, "text": text, "date": date.today().isoformat()}
    entries = _read_changes(path)
    entries.append(entry)
    _write_changes(entries, path)
    return entry


def changes_since(app_id: int, path=None) -> list[dict]:
    """Return all logged changes for one application, in logged order."""
    return [e for e in _read_changes(path) if e.get("app_id") == app_id]


def build_report(
    *,
    rejections: list[dict] | None = None,
    reapproaches_due: list[dict] | None = None,
    pending_feedback: list[dict] | None = None,
    apps: list[dict] | None = None,
) -> dict:
    """Build a resilience report. Pure function over passed-in data.

    ``by_category`` uses ``reject_coach.categorize`` on each rejection's
    ``reason_notes``. ``changes_logged`` counts entries in the changes log.
    """
    rejections = rejections or []
    reapproaches_due = reapproaches_due or []
    pending_feedback = pending_feedback or []
    apps = apps or []

    by_category = Counter(
        reject_coach.categorize(r.get("reason_notes") or "") for r in rejections
    )
    by_stage = Counter(r.get("stage") or reject_coach.UNSTATED for r in rejections)

    return {
        "total_rejected": len(rejections),
        "by_category": dict(by_category),
        "by_stage": dict(by_stage),
        "reapproaches_due_count": len(reapproaches_due),
        "pending_feedback_count": len(pending_feedback),
        "changes_logged": len(_read_changes(None)),
        "morale": reject_coach.morale_summary(apps, rejections),
    }


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "  (none)"
    return f"{title}\n{body}"


def render(report: dict) -> str:
    """Render the resilience report as plain text with clear sections."""
    parts = [
        _section("Rejections", [f"Total rejected: {report['total_rejected']}"]),
        _section(
            "By category",
            [f"  {cat}: {count}" for cat, count in sorted(report["by_category"].items())],
        ),
        _section(
            "By stage",
            [f"  {stage}: {count}" for stage, count in sorted(report["by_stage"].items())],
        ),
        _section(
            "Re-approaches due",
            [f"  {report['reapproaches_due_count']} companies ready for a re-approach."],
        ),
        _section(
            "Feedback pending",
            [f"  {report['pending_feedback_count']} rejections awaiting feedback."],
        ),
        _section(
            "Improvements logged",
            [f"  {report['changes_logged']} changes logged since the first rejection."],
        ),
        _section("Morale", [reject_coach.render_morale(report["morale"])]),
    ]
    return "\n\n".join(parts)
