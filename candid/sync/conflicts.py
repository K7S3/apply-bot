"""Pending sync conflicts: listing, inspection, and resolution.

Conflicts are recorded by the merge engine (candid.sync.merge) and live in
``DATA_DIR/sync/conflicts.json`` as a JSON list. Each entry looks like::

    {
        "id": "c-1a2b3c4d",
        "kind": "file" | "record",
        "path": "tracker.json",        # relative to DATA_DIR
        "record_id": "abc123" | None,  # set for kind == "record"
        "local": ...,                  # parsed JSON, hash summary, or None
        "remote": ...,                 # parsed JSON, hash summary, or None
        "base": ...,                   # base hash (file) or None (record)
        "bundle": "bundle.zip",
        "bundle_created_at": "2026-09-22T20:30:00",
        "remote_stash": "remote/c-1a2b3c4d/tracker.json" | None,
        "created_at": "2026-09-22T20:31:00",
    }

``local``/``remote`` stay JSON-serializable: parsed JSON when the file is
JSON, otherwise a ``{"sha256": ..., "size": ..., "path": ...}`` summary.
Binary remote bytes are stashed under ``DATA_DIR/sync/remote/<id>/`` so a
"remote" resolution can copy the whole file back.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from candid import config
from candid.sync import categories
from candid.sync.errors import SyncError

VALID_CHOICES = ("local", "remote", "newer", "older")


def sync_state_dir() -> Path:
    d = Path(config.DATA_DIR) / categories.SYNC_STATE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def conflicts_path() -> Path:
    return sync_state_dir() / "conflicts.json"


def _load() -> list[dict]:
    p = conflicts_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SyncError("sync conflicts file is corrupt") from exc
    if not isinstance(data, list):
        raise SyncError("sync conflicts file is corrupt")
    return data


def _save(items: list[dict]) -> None:
    conflicts_path().write_text(
        json.dumps(items, indent=2, sort_keys=True), encoding="utf-8"
    )


def append_conflicts(new: list[dict]) -> list[dict]:
    """Append freshly created conflicts to the pending list."""
    items = _load()
    for c in new:
        c.setdefault("id", f"c-{uuid.uuid4().hex[:8]}")
        c.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        items.append(c)
    _save(items)
    return new


def stash_remote(conflict_id: str, rel: str, data: bytes) -> str:
    """Stash remote file bytes for a file conflict.

    Returns the stash path relative to the sync state dir.
    """
    dest = sync_state_dir() / "remote" / conflict_id / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return Path("remote", conflict_id, rel).as_posix()


def parse_records(raw: bytes) -> tuple[str | None, list[dict]] | None:
    """Parse tracker-style JSON into (wrapper, records).

    Accepts a bare JSON list of ``{"id": ...}`` dicts, or
    ``{"applications": [...]}``. Returns None when the payload is not a
    record list.
    """
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(doc, dict) and isinstance(doc.get("applications"), list):
        records, wrapper = doc["applications"], "applications"
    elif isinstance(doc, list):
        records, wrapper = doc, None
    else:
        return None
    if not all(isinstance(r, dict) and "id" in r for r in records):
        return None
    return wrapper, records


def write_records(path: Path, wrapper: str | None, records: list[dict]) -> None:
    """Write records back to a tracker-style JSON file, keeping the wrapper."""
    doc = {"applications": records} if wrapper == "applications" else records
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def list_conflicts() -> list[dict]:
    """Return all pending conflicts, oldest first."""
    return _load()


def _index_of(items: list[dict], ref) -> int:
    if isinstance(ref, bool):
        raise SyncError(f"no conflict matching {ref!r}")
    if isinstance(ref, int):
        if 0 <= ref < len(items):
            return ref
        raise SyncError(f"no conflict #{ref} ({len(items)} pending)")
    if isinstance(ref, str):
        if ref.isdigit():
            return _index_of(items, int(ref))
        for i, c in enumerate(items):
            if c.get("id") == ref or c.get("record_id") == ref:
                return i
    raise SyncError(f"no conflict matching {ref!r}")


def get_conflict(ref) -> dict:
    """Fetch one pending conflict by list index, conflict id, or record_id."""
    items = _load()
    return items[_index_of(items, ref)]


def resolve_conflict(ref, choice) -> dict:
    """Resolve one pending conflict and apply the winner to the data file.

    choice is one of "local", "remote", "newer", "older". "newer"/"older"
    compare "updated_at"/"created_at" fields when both sides carry them,
    otherwise fall back to the bundle's created_at versus the local file's
    mtime. For record conflicts the winning record is patched into the
    tracker-style JSON file; for file conflicts the winning bytes are
    written back (remote wins copy from the stash). The conflict is then
    removed from the pending list.
    """
    if choice not in VALID_CHOICES:
        raise SyncError(
            f"unknown choice {choice!r}; pick one of: {', '.join(VALID_CHOICES)}"
        )
    items = _load()
    idx = _index_of(items, ref)
    conflict = items[idx]
    winner = choice if choice in ("local", "remote") else _pick_by_time(conflict, choice)
    _apply_winner(conflict, winner)
    _drop_stash(conflict)
    del items[idx]
    _save(items)
    return {
        "id": conflict.get("id"),
        "kind": conflict.get("kind"),
        "path": conflict.get("path"),
        "record_id": conflict.get("record_id"),
        "choice": choice,
        "winner": winner,
    }


def _content_timestamp(value) -> str | None:
    if isinstance(value, dict):
        ts = value.get("updated_at") or value.get("created_at")
        return ts if isinstance(ts, str) else None
    return None


def _local_file_mtime(rel: str) -> str | None:
    p = Path(config.DATA_DIR) / rel
    if p.is_file():
        return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    return None


def _pick_by_time(conflict: dict, choice: str) -> str:
    local_ts = _content_timestamp(conflict.get("local"))
    remote_ts = _content_timestamp(conflict.get("remote"))
    if local_ts is None:
        local_ts = _local_file_mtime(conflict["path"])
    if remote_ts is None:
        remote_ts = conflict.get("bundle_created_at")
    if not local_ts or not remote_ts:
        raise SyncError(
            "cannot decide newer/older for this conflict: "
            "no usable timestamps on either side"
        )
    if choice == "newer":
        return "remote" if remote_ts >= local_ts else "local"
    return "remote" if remote_ts <= local_ts else "local"


def _apply_winner(conflict: dict, winner: str) -> None:
    data_dir = Path(config.DATA_DIR)
    if conflict.get("kind") == "record":
        _apply_record_winner(data_dir, conflict, winner)
    else:
        _apply_file_winner(data_dir, conflict, winner)


def _apply_record_winner(data_dir: Path, conflict: dict, winner: str) -> None:
    path = data_dir / conflict["path"]
    parsed = parse_records(path.read_bytes()) if path.is_file() else None
    wrapper, records = parsed if parsed is not None else (None, [])
    rid = conflict.get("record_id")
    winning = conflict.get("remote") if winner == "remote" else conflict.get("local")
    out: list[dict] = []
    replaced = False
    for r in records:
        if r.get("id") == rid:
            replaced = True
            if winning is not None:
                out.append(winning)
        else:
            out.append(r)
    if not replaced and winning is not None:
        out.append(winning)
    write_records(path, wrapper, out)


def _apply_file_winner(data_dir: Path, conflict: dict, winner: str) -> None:
    if winner == "local":
        return  # local content is already in place
    stash_rel = conflict.get("remote_stash")
    src = sync_state_dir() / stash_rel if stash_rel else None
    if not src or not src.is_file():
        raise SyncError("remote content for this conflict is no longer available")
    dest = data_dir / conflict["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def _drop_stash(conflict: dict) -> None:
    cid = conflict.get("id")
    if cid:
        d = sync_state_dir() / "remote" / cid
        if d.is_dir():
            shutil.rmtree(d)
