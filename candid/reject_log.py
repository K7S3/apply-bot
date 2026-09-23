"""Structured rejection intake: log how far an application got and why.

Keeps a small JSON list of rejection records (one per application) at
``C.DATA_DIR / "reject_log.json"``. Logging a rejection also flips the
tracked application's status to ``"rejected"`` in the tracker, so the
funnel views stay consistent.

Re-logging the same app updates its record in place rather than
creating a duplicate.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import tracker as T


class RejectLogError(Exception):
    """Raised for invalid rejection-log operations."""


# How far the candidate got before the rejection.
STAGES = ("applied", "recruiter_screen", "phone_screen", "technical", "onsite", "final", "offer")

REJECT_LOG_PATH = C.DATA_DIR / "reject_log.json"


def _resolve(path: str | Path | None) -> Path:
    return Path(path) if path else REJECT_LOG_PATH


def _load(log_path: str | Path | None = None) -> list[dict]:
    p = _resolve(log_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RejectLogError(f"Reject log {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RejectLogError(f"Reject log {p} should contain a JSON list.")
    return data


def _save(records: list[dict], log_path: str | Path | None = None) -> Path:
    p = _resolve(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return p


def log_rejection(
    app_id: int,
    *,
    stage: str,
    reason_notes: str = "",
    feedback: str = "",
    log_path: str | Path | None = None,
    tracker_path: str | Path | None = None,
) -> dict:
    """Log a rejection for an application. Returns the record.

    Validates ``stage`` against STAGES, looks up the application in the
    tracker, flips its tracker status to ``"rejected"``, then upserts the
    rejection record keyed by ``app_id`` (re-logging updates in place).
    """
    if stage not in STAGES:
        raise RejectLogError(f"Unknown stage '{stage}'. Choose from: {', '.join(STAGES)}")
    apps = T.list_apps(path=tracker_path)
    app = next((a for a in apps if a.get("id") == app_id), None)
    if app is None:
        raise RejectLogError(f"No application with id {app_id}. Use `track list` to see ids.")

    T.update(app_id, status="rejected", path=tracker_path)

    records = _load(log_path)
    record = {
        "app_id": app_id,
        "company": app.get("company", ""),
        "role": app.get("role", ""),
        "stage": stage,
        "reason_notes": reason_notes.strip(),
        "feedback": feedback.strip(),
        "date_logged": date.today().isoformat(),
    }
    existing = next((r for r in records if r.get("app_id") == app_id), None)
    if existing is not None:
        existing.update(record)
    else:
        records.append(record)
    _save(records, log_path)
    return {**record}


def list_rejections(log_path: str | Path | None = None) -> list[dict]:
    """List all rejection records, ordered by app id."""
    return sorted(_load(log_path), key=lambda r: r.get("app_id", 0))


def get_rejection(app_id: int, log_path: str | Path | None = None) -> dict | None:
    """Return the rejection record for an app, or None if not logged."""
    return next((r for r in _load(log_path) if r.get("app_id") == app_id), None)


def _snippet(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def render_log(rejections: list[dict]) -> str:
    """Render one line per rejection, e.g. ``#3 Acme Corp - MLE | stage: onsite | logged 2026-09-22``."""
    if not rejections:
        return "No rejections logged yet."
    lines = []
    for r in rejections:
        line = (
            f"#{r.get('app_id')} {r.get('company', '')} - {r.get('role', '')} "
            f"| stage: {r.get('stage', '')} | logged {r.get('date_logged', '')}"
        )
        reason = _snippet(r.get("reason_notes", "") or "")
        if reason:
            line += f" | {reason}"
        lines.append(line)
    return "\n".join(lines)
