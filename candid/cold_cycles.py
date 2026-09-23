"""Archive old application cycles (closed job applications) into cold storage.

Finds tracker applications whose status is closed AND whose last activity
date is older than a cutoff, removes them from the tracker, and stores them
in a coldstore archive of kind ``"cycles"``. Restoring re-inserts an archived
application back into the tracker.

Path handling is patch-friendly: this module reads ``C.DATA_DIR`` (from
``from candid import config as C``) *inside* functions, so tests can
``monkeypatch`` ``candid.config.DATA_DIR`` to an isolated directory.

The coldstore module (``candid.coldstore``) is imported lazily inside
functions. Its contract is:

- ``create_archive(kind, label=..., members=..., payload=...) -> dict``
  where ``members`` is a dict of ``name -> bytes`` and the returned
  manifest carries the id under ``"archive_id"``.
- ``list_archives(kind=None) -> list[dict]`` — manifests with
  ``"archive_id"`` and ``"kind"``.
- ``read_archive(archive_id) -> dict`` — manifest plus ``"members"``,
  a list of member names (``"payload.json"`` excluded).
- ``extract_member(archive_id, member_name) -> bytes``
- ``delete_archive(archive_id) -> bool``

For forwards/backwards tolerance, archive-id lookups accept either
``"archive_id"`` or ``"id"`` on the manifest/entry dicts.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from candid import config as C

# Closed = terminal application-cycle statuses, taken from the statuses
# tracker.py actually uses (candid/config.py STATUSES). "offer" is treated as
# closed: an offer (accepted or declined elsewhere) ends that cycle's
# follow-ups; override with the `statuses` parameter of archive_old_cycles
# if a workflow needs otherwise.
CLOSED_STATUSES = {"rejected", "withdrawn", "offer"}

ARCHIVE_KIND = "cycles"
MEMBER_PREFIX = "apps/"
MEMBER_SUFFIX = ".json"


class ColdCyclesError(Exception):
    """Raised for invalid cold-cycle archive operations."""


def _tracker_path():
    from pathlib import Path

    return Path(C.DATA_DIR) / "tracker.json"


def _load_apps() -> list[dict]:
    p = _tracker_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _save_apps(apps: list[dict]) -> None:
    p = _tracker_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(apps, indent=2), encoding="utf-8")


def _coldstore():
    """Import candid.coldstore lazily (it may not exist yet at import time).

    Prefers ``sys.modules`` over the package attribute so test doubles
    injected into ``sys.modules`` are honored even when another module has
    already imported the real coldstore (``from P import M`` resolves the
    package attribute first).
    """
    import sys

    mod = sys.modules.get("candid.coldstore")
    if mod is not None:
        return mod
    from candid import coldstore

    return coldstore


def _aid(entry: dict):
    """Archive id from a manifest/entry dict, tolerant of key naming."""
    return entry.get("archive_id") or entry.get("id")


def _parse_date(value) -> date | None:
    """Defensively parse an ISO date/datetime string. None if unusable."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _last_activity(app: dict) -> date | None:
    """Most recent activity date of an app, or None if unknown/unparseable."""
    return _parse_date(app.get("date_updated")) or _parse_date(app.get("date_added"))


def _is_old_enough(app: dict, cutoff: date) -> bool:
    last = _last_activity(app)
    # Unparseable/missing dates are never "old enough" — never archive those.
    return last is not None and last < cutoff


def archive_old_cycles(
    days: int = 90,
    dry_run: bool = False,
    statuses: set | None = None,
) -> dict:
    """Archive closed applications whose last activity is older than `days`.

    Returns ``{"archived": n, "archive_id": ..., "app_ids": [...],
    "dry_run": ...}``. With ``dry_run=True`` nothing is changed: ``archived``
    is the count that *would* be archived, ``archive_id`` is None, and
    ``app_ids`` lists the would-be archived ids.
    """
    cold = _coldstore()
    closed = set(statuses) if statuses is not None else set(CLOSED_STATUSES)
    cutoff = date.today() - timedelta(days=days)

    apps = _load_apps()
    old = [
        a
        for a in apps
        if str(a.get("status")) in closed and _is_old_enough(a, cutoff)
    ]
    app_ids = [a.get("id") for a in old]
    result = {
        "archived": len(old),
        "archive_id": None,
        "app_ids": app_ids,
        "dry_run": dry_run,
    }
    if dry_run or not old:
        return result

    members = {
        f"{MEMBER_PREFIX}{a.get('id')}{MEMBER_SUFFIX}": json.dumps(
            a, indent=2, sort_keys=True
        ).encode("utf-8")
        for a in old
    }
    payload = {
        "count": len(old),
        "archived_utc": datetime.now(timezone.utc).isoformat(),
        "statuses": sorted({str(a.get("status")) for a in old}),
        "app_ids": app_ids,
        "days": days,
    }
    label = f"closed-apps-{date.today().isoformat()}"
    archive = cold.create_archive(
        ARCHIVE_KIND, label=label, members=members, payload=payload
    )
    archive_id = _aid(archive) if isinstance(archive, dict) else None

    # Archive first, then remove from tracker so nothing is lost on failure.
    archived_ids = {a.get("id") for a in old}
    _save_apps([a for a in apps if a.get("id") not in archived_ids])

    result["archived"] = len(old)
    result["archive_id"] = archive_id
    return result


def _iter_cycles_archives(cold) -> list[dict]:
    return [a for a in cold.list_archives(kind=ARCHIVE_KIND)
            if a.get("kind", ARCHIVE_KIND) == ARCHIVE_KIND]


def _member_names(detail: dict) -> list[str]:
    members = detail.get("members") or []
    if isinstance(members, dict):
        return list(members.keys())
    return list(members)


def _decode_member(raw) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def restore_application(app_id) -> dict:
    """Restore an archived application back into the tracker.

    Returns the restored app dict. If an app with the same id is already in
    the tracker it is not duplicated (the existing record is returned).
    Raises ColdCyclesError if the app is not found in any cycles archive.
    """
    cold = _coldstore()
    target = f"{MEMBER_PREFIX}{app_id}{MEMBER_SUFFIX}"
    for arc in _iter_cycles_archives(cold):
        aid = _aid(arc)
        names = _member_names(cold.read_archive(aid))
        if target not in names:
            continue
        app = _decode_member(cold.extract_member(aid, target))
        apps = _load_apps()
        existing = next(
            (a for a in apps if str(a.get("id")) == str(app.get("id"))), None
        )
        if existing is None:
            apps.append(app)
            _save_apps(apps)
            return dict(app)
        return dict(existing)
    raise ColdCyclesError(
        f"No archived application with id {app_id!r} in any cycles archive."
    )


def list_archived_cycles() -> list[dict]:
    """Flattened list of archived applications, each with its archive_id."""
    cold = _coldstore()
    out: list[dict] = []
    for arc in _iter_cycles_archives(cold):
        aid = _aid(arc)
        for name in _member_names(cold.read_archive(aid)):
            if not (
                name.startswith(MEMBER_PREFIX) and name.endswith(MEMBER_SUFFIX)
            ):
                continue
            try:
                app = _decode_member(cold.extract_member(aid, name))
            except Exception:
                continue
            out.append(
                {
                    "archive_id": aid,
                    "app_id": app.get("id"),
                    "company": app.get("company"),
                    "role": app.get("role"),
                    "status": app.get("status"),
                    "date_updated": app.get("date_updated"),
                    "app": app,
                }
            )
    return out


def prune_cycles_archive(archive_id: str) -> bool:
    """Delete a cycles archive (for retention-policy use). Returns True if
    deleted, False if it did not exist. Refuses non-cycles archives."""
    cold = _coldstore()
    # Look the archive up across ALL archives (unfiltered) so the guard
    # works even if the store ignores the kind filter.
    by_id = {str(_aid(a)): a for a in cold.list_archives()}
    entry = by_id.get(str(archive_id))
    if entry is not None and entry.get("kind", ARCHIVE_KIND) != ARCHIVE_KIND:
        raise ColdCyclesError(
            f"Archive {archive_id!r} is not a {ARCHIVE_KIND} archive."
        )
    deleter = getattr(cold, "delete_archive", None) or getattr(
        cold, "remove_archive", None
    )
    if deleter is None:
        raise ColdCyclesError(
            "coldstore exposes neither delete_archive nor remove_archive."
        )
    return bool(deleter(archive_id))
