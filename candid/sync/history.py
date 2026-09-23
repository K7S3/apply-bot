"""Sync history: append-only log of sync activity plus a status summary.

The log is one JSON line per sync at
``DATA_DIR / "sync" / "history.jsonl"``. Status is derived from the log
plus the base snapshots, pending conflicts, and the peer registry.

Only stdlib is used.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from candid import config
from candid.sync import base, categories
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id

DIRECTIONS = ("export", "import")


def _sync_dir() -> Path:
    d = Path(config.DATA_DIR) / categories.SYNC_STATE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _history_path() -> Path:
    return _sync_dir() / "history.jsonl"


def _summarize_result(result: dict) -> dict:
    """Reduce an arbitrary result dict to a small JSON-safe summary."""
    summary: dict = {}
    for key in ("applied", "deleted", "changed", "conflicts", "skipped"):
        if key not in result:
            continue
        value = result[key]
        summary[key] = len(value) if isinstance(value, (list, tuple)) else value
    for key, value in result.items():
        if key not in summary and isinstance(value, (str, int, float, bool)):
            summary[key] = value
    return summary


def log_sync(
    direction: str, peer_id: str | None, bundle_name: str, result: dict
) -> dict:
    """Append one sync record to history.jsonl and return the entry.

    ``direction`` is "export" or "import". ``result`` is reduced to a small
    summary (applied/deleted/conflict counts).
    """
    if direction not in DIRECTIONS:
        raise SyncError(
            f"invalid sync direction {direction!r}; "
            f"choose from: {', '.join(DIRECTIONS)}"
        )
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "machine_id": get_machine_id(),
        "direction": direction,
        "peer_id": peer_id,
        "bundle_name": bundle_name,
        "result": _summarize_result(result or {}),
    }
    with open(_history_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def get_log(limit: int = 20) -> list[dict]:
    """Return the most recent log entries first (up to ``limit``)."""
    path = _history_path()
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # skip a corrupt line rather than losing the whole log
        if isinstance(entry, dict):
            entries.append(entry)
    entries.reverse()
    return entries[: max(limit, 0)]


def _read_json_file(name: str):
    path = _sync_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _count_conflicts() -> int:
    """Count pending conflicts from sync/conflicts.json if present.

    The conflicts file is owned by worker C's conflict engine; accept either
    a bare list of conflicts or a dict carrying them under "conflicts".
    """
    data = _read_json_file("conflicts.json")
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        conflicts = data.get("conflicts", data)
        return len(conflicts) if isinstance(conflicts, (list, dict)) else 0
    return 0


def _read_peers():
    """Return the peer registry (sync/peers.json) verbatim, else {}.

    The file is owned by the pairing module; its content is passed through
    unchanged so the status summary never loses the registry's shape.
    """
    data = _read_json_file("peers.json")
    if isinstance(data, (dict, list)):
        return data
    return {}


def get_status() -> dict:
    """Summarize sync state: machine, last export/import, conflicts, bases, peers."""
    last_export = None
    last_import = None
    for entry in get_log(limit=1000):
        if entry.get("direction") == "export" and last_export is None:
            last_export = entry
        elif entry.get("direction") == "import" and last_import is None:
            last_import = entry
        if last_export is not None and last_import is not None:
            break
    return {
        "machine_id": get_machine_id(),
        "last_export": last_export,
        "last_import": last_import,
        "pending_conflicts": _count_conflicts(),
        "bases": base.list_bases(),
        "peers": _read_peers(),
    }
