"""Persistence for saved searches, search history, and watch/alert state.

JSON files live under ``candid.config.DATA_DIR``:

- ``saved_searches.json`` -> ``{"name": "query", ...}``
- ``search_history.jsonl`` -> one ``{"query": str, "ts": iso}`` per line,
  newest appended (capped at 500 entries, oldest pruned)
- ``search_watch.json`` -> ``{"name": {"query", "seen", "last_run"}, ...}``

Test seam: each function takes no path arguments. Instead it reads the
module-level path constants ``SAVED_PATH``, ``HISTORY_PATH``, and
``WATCH_PATH``, which are computed from ``candid.config.DATA_DIR`` at
import time. Tests can monkeypatch e.g. ``candid.searchstore.SAVED_PATH``
to point at files under ``tmp_path`` so the real data dir is never touched.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import candid.config as C

SAVED_PATH = C.DATA_DIR / "saved_searches.json"
HISTORY_PATH = C.DATA_DIR / "search_history.jsonl"
WATCH_PATH = C.DATA_DIR / "search_watch.json"

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HISTORY_CAP = 500


class SearchStoreError(Exception):
    """Raised for any saved-search/history/watch store problem."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: str) -> None:
    _ensure_dir(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SearchStoreError(f"cannot read {path.name}: {exc}") from exc
    try:
        value = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        raise SearchStoreError(
            f"{path.name} is corrupt ({exc}); delete {path} to start fresh"
        ) from exc
    if not isinstance(value, dict):
        raise SearchStoreError(
            f"{path.name} is corrupt (expected a JSON object); "
            f"delete {path} to start fresh"
        )
    return value


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise SearchStoreError("saved-search name must be a non-blank string")
    if not _NAME_RE.match(name):
        raise SearchStoreError(
            "saved-search name must match ^[A-Za-z0-9_-]{1,64}$; got "
            f"{name!r}"
        )


def _validate_query(query: str) -> None:
    if not isinstance(query, str) or not query.strip():
        raise SearchStoreError("query must be a non-blank string")


# --- saved searches ----------------------------------------------------------


def save_search(name: str, query: str) -> None:
    """Save or overwrite a named search query."""
    _validate_name(name)
    _validate_query(query)
    saved = _read_json(SAVED_PATH)
    saved[name] = query
    _atomic_write(SAVED_PATH, json.dumps(saved, indent=2))


def list_saved() -> dict:
    """Return ``{name: query}`` for all saved searches."""
    return _read_json(SAVED_PATH)


def get_saved(name: str) -> str:
    """Return the query saved under *name*; missing -> SearchStoreError."""
    saved = _read_json(SAVED_PATH)
    if name not in saved:
        raise SearchStoreError(f"no saved search named {name!r}")
    return saved[name]


def delete_search(name: str) -> None:
    """Delete a saved search; missing -> SearchStoreError."""
    saved = _read_json(SAVED_PATH)
    if name not in saved:
        raise SearchStoreError(f"no saved search named {name!r}")
    del saved[name]
    _atomic_write(SAVED_PATH, json.dumps(saved, indent=2))


# --- search history ----------------------------------------------------------


def log_query(query: str) -> None:
    """Append *query* to history (skip blank; no-op if same as most recent)."""
    if not isinstance(query, str) or not query.strip():
        return
    _ensure_dir(HISTORY_PATH)
    entries: list[dict] = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SearchStoreError(
                    f"{HISTORY_PATH.name} is corrupt ({exc}); delete "
                    f"{HISTORY_PATH} to start fresh"
                ) from exc
            if isinstance(entry, dict) and "query" in entry:
                entries.append(entry)
    if entries and entries[-1].get("query") == query:
        return  # dedupe: already the most recent entry
    entries.append({"query": query, "ts": _now_iso()})
    entries = entries[-_HISTORY_CAP:]
    _atomic_write(HISTORY_PATH, "\n".join(json.dumps(e) for e in entries) + "\n")


def get_history(limit: int = 20) -> list[dict]:
    """Return newest-first ``{"query", "ts"}`` entries, up to *limit*."""
    if limit <= 0:
        return []
    entries: list[dict] = []
    if HISTORY_PATH.exists():
        try:
            text = HISTORY_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise SearchStoreError(
                f"cannot read {HISTORY_PATH.name}: {exc}"
            ) from exc
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SearchStoreError(
                    f"{HISTORY_PATH.name} is corrupt ({exc}); delete "
                    f"{HISTORY_PATH} to start fresh"
                ) from exc
            if isinstance(entry, dict) and "query" in entry:
                entries.append(entry)
    return list(reversed(entries))[:limit]


def clear_history() -> None:
    """Remove all search history."""
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()


# --- watches / alerts --------------------------------------------------------


def record_watch(name: str, query: str, refs: list[str]) -> None:
    """Upsert a watch entry: stored seen set is ``sorted(set(refs))``."""
    _validate_name(name)
    _validate_query(query)
    watches = _read_json(WATCH_PATH)
    watches[name] = {
        "query": query,
        "seen": sorted(set(refs)),
        "last_run": _now_iso(),
    }
    _atomic_write(WATCH_PATH, json.dumps(watches, indent=2))


def watch_new(name: str, query: str, current_refs: list[str]) -> list[str]:
    """Return refs in *current_refs* not yet seen by this watch.

    If there is no stored entry, ALL refs count as new, but the entry is
    still recorded. The stored ``seen`` set and ``last_run`` are updated,
    so a second call with the same refs yields ``[]``.
    """
    _validate_name(name)
    _validate_query(query)
    watches = _read_json(WATCH_PATH)
    entry = watches.get(name)
    if entry is None:
        new = list(current_refs)
    else:
        seen = set(entry.get("seen", []))
        new = [r for r in current_refs if r not in seen]
    merged = set(entry.get("seen", [])) if entry else set()
    merged.update(current_refs)
    watches[name] = {
        "query": query,
        "seen": sorted(merged),
        "last_run": _now_iso(),
    }
    _atomic_write(WATCH_PATH, json.dumps(watches, indent=2))
    return new


def get_watch(name: str) -> dict | None:
    """Return the watch entry for *name*, or None if never watched."""
    watches = _read_json(WATCH_PATH)
    entry = watches.get(name)
    return dict(entry) if entry is not None else None


def list_watches() -> dict:
    """Return ``{name: {"query", "last_run", "seen_count"}}``."""
    watches = _read_json(WATCH_PATH)
    return {
        name: {
            "query": entry.get("query", ""),
            "last_run": entry.get("last_run"),
            "seen_count": len(entry.get("seen", [])),
        }
        for name, entry in watches.items()
    }
