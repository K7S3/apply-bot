"""Base snapshots for three-way sync merges.

A *base* is a ``{relative_path: sha256}`` map of the sync categories at the
moment of the last successful sync. The merge engine (worker C) and the
delta exporter (worker D) both diff against a base to tell local changes
apart from remote changes.

Bases live under ``DATA_DIR / "sync" / "bases" / <base_id>.json``.
The special base id ``"last"`` always points at the most recent snapshot.
"""

from __future__ import annotations

import json
import time

from candid import config
from candid.sync import categories
from candid.sync.errors import SyncError
from candid.sync.manifest import sha256_file


def bases_dir() -> "Path":
    from pathlib import Path

    d = Path(config.DATA_DIR) / categories.SYNC_STATE_DIRNAME / "bases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_current(selected: list[str] | None = None) -> dict[str, str]:
    """Hash every file in the selected categories (default: all).

    Returns ``{relative_posix_path: sha256}``.
    """
    from pathlib import Path

    data = Path(config.DATA_DIR)
    snap: dict[str, str] = {}
    for cat in selected or categories.all_categories():
        for rel in categories.resolve(cat):
            p = data / rel
            if p.is_file():
                snap[rel] = sha256_file(p)
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        snap[f.relative_to(data).as_posix()] = sha256_file(f)
    return snap


def _path(base_id: str) -> "Path":
    from pathlib import Path

    safe = "".join(c for c in base_id if c.isalnum() or c in "-_")
    if not safe or safe != base_id:
        raise SyncError(f"invalid base id {base_id!r}")
    return bases_dir() / f"{safe}.json"


def save_base(base_id: str, snapshot: dict[str, str]) -> str:
    _path(base_id).write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    return base_id


def load_base(base_id: str) -> dict[str, str]:
    p = _path(base_id)
    if not p.exists():
        raise SyncError(
            f"no base snapshot {base_id!r}; run a sync first to establish one"
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SyncError(f"base snapshot {base_id!r} is corrupt") from exc
    if not isinstance(data, dict):
        raise SyncError(f"base snapshot {base_id!r} is corrupt")
    return data


def list_bases() -> list[str]:
    return sorted(p.stem for p in bases_dir().glob("*.json"))


def new_base_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def update_last(snapshot: dict[str, str]) -> str:
    """Save snapshot as the new ``last`` base; returns its timestamp id."""
    base_id = new_base_id()
    save_base(base_id, snapshot)
    save_base("last", snapshot)
    return base_id
