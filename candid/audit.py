"""Append-only, tamper-evident audit log for candid.

Every state-changing command (tracker updates, offer edits, goal changes,
undo/redo, ...) records one JSON object per line in a JSONL file at
``config.AUDIT_PATH`` (inside the git-ignored ``candid_data/`` directory).

Tamper evidence comes from a SHA-256 hash chain: each entry stores the
hash of the previous entry, so editing, deleting, or reordering lines
breaks the chain and is reported by :func:`verify`.

Schema per entry::

    {seq, id, ts, actor, command, entity, entity_id, action,
     before, after, changes, note, prev_hash, hash}

Nothing is redacted here: audit data is the user's own tracker data,
so before/after values are kept as-is (which also makes entries
undo-friendly).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from candid import config

#: Sentinel marking the start of the hash chain (first entry ever).
GENESIS_HASH = "GENESIS"

_ACTORS = ("cli", "dashboard", "api")

_MISSING = object()  # sentinel for "key absent" in _diff


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _meta_path() -> Path:
    """Sidecar file remembering where a pruned chain starts."""
    return config.AUDIT_PATH.parent / "audit.meta.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _canonical(payload: dict) -> bytes:
    """Canonical JSON bytes for hashing (stable key order, no whitespace)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _entry_hash(prev_hash: str, fields: dict) -> str:
    """SHA-256 over canonical JSON of (prev_hash + entry fields minus hash)."""
    return hashlib.sha256(_canonical({"prev_hash": prev_hash, **fields})).hexdigest()


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested dicts to dotted-path keys, e.g. {'a': {'b': 1}} -> {'a.b': 1}."""
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _diff(before: Optional[dict], after: Optional[dict]) -> list[dict]:
    """Field-level diff: [{field, old, new}] for every changed/added/removed field."""
    flat_before = _flatten(before or {})
    flat_after = _flatten(after or {})
    changes = []
    for field in sorted(set(flat_before) | set(flat_after)):
        old = flat_before.get(field, _MISSING)
        new = flat_after.get(field, _MISSING)
        if old is _MISSING or new is _MISSING or old != new:
            changes.append({
                "field": field,
                "old": None if old is _MISSING else old,
                "new": None if new is _MISSING else new,
            })
    return changes


def _append_line(entry: dict) -> None:
    """Append one entry as a single JSONL line (atomic enough for CLI use)."""
    path = config.AUDIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _iter_lines():
    """Yield (lineno, raw_line) for the audit file; empty if missing."""
    path = config.AUDIT_PATH
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            yield lineno, raw


def _tail_state() -> tuple[int, str]:
    """(max seq, hash of last valid entry) for chaining the next record."""
    last_seq = 0
    last_hash = GENESIS_HASH
    for _, raw in _iter_lines():
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # corrupt lines are skipped; verify() reports them
        if not isinstance(entry, dict):
            continue
        seq = entry.get("seq")
        h = entry.get("hash")
        if isinstance(seq, int) and isinstance(h, str):
            last_seq = max(last_seq, seq)
            last_hash = h  # last valid line wins (file is append-ordered)
    return last_seq, last_hash


def _read_meta() -> dict:
    try:
        return json.loads(_meta_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_meta(meta: dict) -> None:
    mp = _meta_path()
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _as_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def _record(actor: str, command: str, entity: str, entity_id: Any,
           action: str, before: Optional[dict] = None,
           after: Optional[dict] = None, note: str = "",
           ts: Optional[str] = None) -> dict:
    """Build, seal, and append one audit entry. ``ts`` is internal (tests)."""
    if actor not in _ACTORS:
        raise ValueError(f"actor must be one of {_ACTORS}, got {actor!r}")
    before = dict(before) if before else None
    after = dict(after) if after else None
    last_seq, last_hash = _tail_state()
    fields = {
        "seq": last_seq + 1,
        "id": secrets.token_hex(4),  # 8 hex chars, e.g. "a1b2c3d4"
        "ts": ts or _now_iso(),
        "actor": actor,
        "command": command,
        "entity": entity,
        "entity_id": str(entity_id),
        "action": action,
        "before": before,
        "after": after,
        "changes": _diff(before, after),
        "note": note or "",
        "prev_hash": last_hash,
    }
    fields["hash"] = _entry_hash(last_hash, fields)
    _append_line(fields)
    return dict(fields)


def record(actor: str, command: str, entity: str, entity_id: Any,
           action: str, before: Optional[dict] = None,
           after: Optional[dict] = None, note: str = "") -> dict:
    """Append one audit entry and return it.

    ``before``/``after`` are the entity snapshots around the change;
    they make entries undo-friendly. ``changes`` is derived automatically.
    """
    return _record(actor, command, entity, entity_id, action,
                   before=before, after=after, note=note)


def read(limit: Optional[int] = None, since: Any = None, until: Any = None,
         entity: Optional[str] = None, action: Optional[str] = None,
         entity_id: Any = None) -> list[dict]:
    """Read entries newest-first, with optional filters.

    Corrupt lines are skipped here (count them via :func:`verify`).
    ``since``/``until`` accept ISO-8601 strings or datetimes.
    """
    entries: list[dict] = []
    for _, raw in _iter_lines():
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entries.append(entry)

    since_s, until_s = _as_iso(since), _as_iso(until)
    if entity_id is not None:
        entity_id = str(entity_id)
    out = []
    for e in entries:
        if entity is not None and e.get("entity") != entity:
            continue
        if action is not None and e.get("action") != action:
            continue
        if entity_id is not None and str(e.get("entity_id")) != entity_id:
            continue
        ts = str(e.get("ts", ""))
        if since_s is not None and ts < since_s:
            continue
        if until_s is not None and ts > until_s:
            continue
        out.append(e)
    out.reverse()  # newest first
    if limit is not None:
        out = out[:limit]
    return out


def get(entry_id: str) -> Optional[dict]:
    """Fetch one entry by its short id, or None."""
    for e in read():
        if e.get("id") == entry_id:
            return e
    return None


def search(query: str) -> list[dict]:
    """Case-insensitive substring search across the stringified entry."""
    q = query.lower()
    return [e for e in read()
            if q in json.dumps(e, ensure_ascii=False, default=str).lower()]


def stats() -> dict:
    """Aggregate counts: {total, by_day, by_action, by_entity}."""
    by_day: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_entity: dict[str, int] = {}
    total = 0
    for e in read():
        total += 1
        day = str(e.get("ts", ""))[:10]
        by_day[day] = by_day.get(day, 0) + 1
        act = str(e.get("action", "?"))
        by_action[act] = by_action.get(act, 0) + 1
        ent = str(e.get("entity", "?"))
        by_entity[ent] = by_entity.get(ent, 0) + 1
    return {"total": total, "by_day": by_day,
            "by_action": by_action, "by_entity": by_entity}


def export_csv(path: Any) -> Path:
    """Export the full log (oldest first) to CSV. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = reversed(read())  # chronological
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "seq", "id", "ts", "actor", "command", "entity",
            "entity_id", "action", "changes", "before", "after", "note",
        ])
        w.writeheader()
        for e in rows:
            w.writerow({
                "seq": e.get("seq"), "id": e.get("id"), "ts": e.get("ts"),
                "actor": e.get("actor"), "command": e.get("command"),
                "entity": e.get("entity"), "entity_id": e.get("entity_id"),
                "action": e.get("action"),
                "changes": json.dumps(e.get("changes", []), ensure_ascii=False),
                "before": json.dumps(e.get("before"), ensure_ascii=False),
                "after": json.dumps(e.get("after"), ensure_ascii=False),
                "note": e.get("note", ""),
            })
    return path


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def export_markdown(path: Any) -> Path:
    """Export the full log (oldest first) to a Markdown table. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = list(reversed(read()))
    lines = [
        "# Audit log",
        "",
        f"Exported {_now_iso()} - {len(entries)} entries, oldest first.",
        "",
        "| seq | ts | actor | command | entity | entity_id | action | changes | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        changes = "; ".join(
            f"{c['field']}: {c['old']} -> {c['new']}"
            for c in (e.get("changes") or []))
        lines.append("| " + " | ".join(_md_cell(v) for v in [
            e.get("seq"), e.get("ts"), e.get("actor"), e.get("command"),
            e.get("entity"), e.get("entity_id"), e.get("action"),
            changes, e.get("note", ""),
        ]) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def prune(older_than_days: int, dry_run: bool = True) -> dict:
    """Drop entries older than ``older_than_days``.

    Returns {"total", "kept", "pruned", "dry_run"}. With dry_run=False the
    file is rewritten and a sidecar records the last pruned hash/seq so
    :func:`verify` still passes on the surviving chain.
    """
    cutoff = (_now() - timedelta(days=older_than_days)).isoformat()
    entries = read()  # newest first
    kept = [e for e in entries if str(e.get("ts", "")) >= cutoff]
    pruned = [e for e in entries if str(e.get("ts", "")) < cutoff]
    result = {"total": len(entries), "kept": len(kept),
              "pruned": len(pruned), "dry_run": dry_run}
    if dry_run or not pruned:
        return result
    path = config.AUDIT_PATH
    tmp = path.with_suffix(".log.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in reversed(kept):  # oldest first
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    newest_pruned = pruned[0]  # read() is newest-first
    meta = _read_meta()
    _write_meta({
        "pruned_entries": meta.get("pruned_entries", 0) + len(pruned),
        "last_pruned_seq": newest_pruned["seq"],
        "last_pruned_hash": newest_pruned["hash"],
        "pruned_at": _now_iso(),
    })
    return result


def verify() -> list[str]:
    """Check the hash chain. Returns a list of problems; empty means OK.

    Detects: corrupt (non-JSON) lines, gaps or out-of-order ``seq``,
    ``prev_hash`` link mismatches, and bad entry hashes (tampering).
    """
    problems: list[str] = []
    path = config.AUDIT_PATH
    if not path.exists():
        return []
    meta = _read_meta()
    pruned_seq = meta.get("last_pruned_seq")
    pruned_hash = meta.get("last_pruned_hash")

    prev_seq: Optional[int] = None
    prev_hash: Optional[str] = None
    first = True
    for lineno, raw in _iter_lines():
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {lineno}: corrupt line (not valid JSON)")
            continue
        if not isinstance(entry, dict):
            problems.append(f"line {lineno}: corrupt line (not a JSON object)")
            continue

        seq = entry.get("seq")
        stored_hash = entry.get("hash")
        entry_prev = entry.get("prev_hash")

        if first:
            first = False
            if pruned_seq is not None:
                if seq != pruned_seq + 1:
                    problems.append(
                        f"line {lineno}: seq {seq} does not continue pruned "
                        f"chain (expected {pruned_seq + 1})")
                if entry_prev != pruned_hash:
                    problems.append(
                        f"line {lineno}: prev_hash does not match last pruned entry")
            else:
                if seq != 1:
                    problems.append(
                        f"line {lineno}: first seq is {seq}, expected 1")
                if entry_prev != GENESIS_HASH:
                    problems.append(
                        f"line {lineno}: first entry prev_hash is not GENESIS")
        else:
            if not isinstance(seq, int) or not isinstance(prev_seq, int) \
                    or seq != prev_seq + 1:
                problems.append(
                    f"line {lineno}: seq {seq} out of order "
                    f"(previous was {prev_seq})")
            if entry_prev != prev_hash:
                problems.append(
                    f"line {lineno}: prev_hash does not match previous entry hash")

        fields = {k: v for k, v in entry.items()
                  if k not in ("hash", "prev_hash")}
        if not isinstance(entry_prev, str) or stored_hash != _entry_hash(entry_prev, fields):
            problems.append(f"line {lineno}: bad hash (entry tampered or corrupted)")

        prev_seq = seq if isinstance(seq, int) else prev_seq
        prev_hash = stored_hash if isinstance(stored_hash, str) else prev_hash
    return problems
