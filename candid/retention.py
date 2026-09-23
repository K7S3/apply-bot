"""Data retention: archive old terminal applications from the tracker.

Applications in a terminal status (rejected, withdrawn, offer) whose
``date_updated`` is older than a cutoff are moved from ``tracker.json``
to ``archive.json`` (each record gains an ``archived_on`` date), keeping
the active tracker focused. Malformed dates are skipped, never crash.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C


class RetentionError(Exception):
    """Raised for retention problems (unreadable tracker, bad input, ...)."""


TERMINAL_STATUSES = {"rejected", "withdrawn", "offer"}

ARCHIVE_NAME = "archive.json"


def _resolve_data_dir(data_dir: Path | None) -> Path:
    return Path(data_dir) if data_dir is not None else C.DATA_DIR


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise RetentionError(f"Could not read {path.name}: {e}") from None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _parse_date(value) -> date | None:
    """Parse a date from a record; None for anything malformed/missing."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.date()


def _load_tracker(root: Path) -> list:
    apps = _read_json(root / "tracker.json", [])
    if not isinstance(apps, list):
        raise RetentionError(
            "tracker.json is not a list - it may be corrupted."
        )
    return apps


def archive_old(
    days: int = 180, *, data_dir: Path | None = None, dry_run: bool = False
) -> dict:
    """Archive terminal applications not updated in ``days`` days.

    Returns ``{archived: [ids], skipped: count, dry_run}``. With
    ``dry_run=True`` nothing is written: it reports what would happen.
    """
    if days < 0:
        raise RetentionError("days must be >= 0.")
    C.ensure_data_dirs()
    root = _resolve_data_dir(data_dir)
    apps = _load_tracker(root)
    cutoff = date.today() - timedelta(days=days)

    archived: list = []
    skipped = 0
    kept: list = []
    for app in apps:
        if not isinstance(app, dict) or app.get("status") not in TERMINAL_STATUSES:
            kept.append(app)
            continue
        updated = _parse_date(app.get("date_updated"))
        if updated is None or updated >= cutoff:
            skipped += 1
            kept.append(app)
            continue
        rec = dict(app)
        rec["archived_on"] = date.today().isoformat()
        archived.append(rec)

    if not dry_run and archived:
        archive = _read_json(root / ARCHIVE_NAME, [])
        if not isinstance(archive, list):
            archive = []
        archive.extend(archived)
        _write_json(root / ARCHIVE_NAME, archive)
        _write_json(root / "tracker.json", kept)

    return {
        "archived": [r.get("id") for r in archived],
        "skipped": skipped,
        "dry_run": dry_run,
    }


def archive_stats(*, data_dir: Path | None = None) -> dict:
    """Summary of the archive: {archived_count, oldest, newest}.

    oldest/newest are ``archived_on`` dates (ISO strings), or None when the
    archive is empty.
    """
    root = _resolve_data_dir(data_dir)
    archive = _read_json(root / ARCHIVE_NAME, [])
    if not isinstance(archive, list):
        archive = []
    dates = [
        r.get("archived_on")
        for r in archive
        if isinstance(r, dict) and r.get("archived_on")
    ]
    dates.sort()
    return {
        "archived_count": len(archive),
        "oldest": dates[0] if dates else None,
        "newest": dates[-1] if dates else None,
    }


def render_archive_summary(result: dict) -> str:
    """Human-readable one-paragraph summary of an archive run."""
    n = len(result["archived"])
    if result["dry_run"]:
        line = f"Would archive {n} application(s)"
    else:
        line = f"Archived {n} application(s)"
    if result["archived"]:
        line += f": {', '.join(str(i) for i in result['archived'])}"
    if result["skipped"]:
        line += f" ({result['skipped']} kept: recent, active, or missing a usable date)"
    if result["dry_run"]:
        line += ". Next: run `python -m candid retention run` to apply"
    return line
