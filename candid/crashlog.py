"""Local structured crash log for candid.

Every uncaught exception is recorded as one JSONL line in CRASH_LOG_PATH so
the user (and, with their explicit opt-in consent, a bug report) can see what
broke, when, and how often. Recording is best-effort: ``log_crash`` never
raises, even when the disk is unavailable.

Frame filenames are stored basename-only so no user paths leak into the log.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Callable

from candid import __version__ as CANDID_VERSION
from candid.config import (
    CRASH_LAST_PATH,
    CRASH_LOG_KEEP,
    CRASH_LOG_MAX_AGE_DAYS,
    CRASH_LOG_MAX_BYTES,
    CRASH_LOG_PATH,
)

# Signature of sys.excepthook: (exc_type, exc_value, traceback) -> None
Excepthook = Callable[[type[BaseException], BaseException, "TracebackType | None"], None]

__all__ = [
    "log_crash",
    "read_crashes",
    "group_crashes",
    "rotate_if_needed",
    "prune_old",
    "install_crash_hook",
    "uninstall_crash_hook",
    "check_last_crash",
    "clear_last_crash",
    "build_record",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_iso(dt: datetime | None = None) -> str:
    """ISO timestamp in the user's local timezone."""
    dt = dt or _utcnow()
    return dt.astimezone().isoformat()


def build_record(exc: BaseException, command: str | None = None, argv: list[str] | None = None) -> dict:
    """Build the crash record dict without touching the filesystem."""
    raw_argv = list(argv) if argv is not None else list(sys.argv)
    if command is None:
        command = Path(raw_argv[0]).name if raw_argv else ""
    frames: list[dict] = []
    if exc.__traceback__ is not None:
        for frame in traceback.extract_tb(exc.__traceback__):
            basename = os.path.basename(frame.filename or "")
            frames.append(
                {
                    "file": basename,
                    "module": os.path.splitext(basename)[0],
                    "func": frame.name or "",
                    "line": frame.lineno or 0,
                }
            )
    normalized = "\n".join(
        f"{f['file']}|{f['module']}|{f['func']}|{f['line']}" for f in frames
    )
    tb_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return {
        "id": uuid.uuid4().hex[:12],
        "ts": _local_iso(),
        "candid_version": CANDID_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "command": command,
        "argv": raw_argv,
        "exc_type": type(exc).__name__,
        "exc_msg": str(exc),
        "traceback_hash": tb_hash,
        "frames": frames,
    }


def _append_line(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_crash(
    exc: BaseException, command: str | None = None, argv: list[str] | None = None
) -> dict:
    """Record a crash to the local JSONL crash log. Never raises.

    Appends the record, rotates the log if it grew too big, prunes records
    older than CRASH_LOG_MAX_AGE_DAYS, and writes the last-crash marker.
    """
    record = build_record(exc, command=command, argv=argv)
    try:
        _append_line(CRASH_LOG_PATH, record)
        rotate_if_needed()
        prune_old()
        try:
            CRASH_LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
            CRASH_LAST_PATH.write_text(record["id"], encoding="utf-8")
        except OSError:
            pass
    except Exception:
        # Crash logging must never break the program it is instrumenting.
        pass
    return record


def read_crashes(limit: int | None = None) -> list[dict]:
    """Read crash records, newest first. Corrupt lines are skipped."""
    records: list[dict] = []
    try:
        with CRASH_LOG_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, FileNotFoundError):
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("id") and rec.get("ts"):
            records.append(rec)
    records.sort(key=lambda r: str(r.get("ts", "")), reverse=True)
    if limit is not None:
        records = records[: max(0, limit)]
    return records


def group_crashes() -> list[dict]:
    """Group crashes by traceback_hash, newest group first."""
    groups: dict[str, dict] = {}
    for rec in read_crashes():
        key = rec.get("traceback_hash", "")
        g = groups.get(key)
        if g is None:
            groups[key] = {
                "hash": key,
                "exc_type": rec.get("exc_type", ""),
                "count": 1,
                "first_ts": rec.get("ts", ""),
                "last_ts": rec.get("ts", ""),
                "sample_id": rec.get("id", ""),
            }
        else:
            g["count"] += 1
            ts = str(rec.get("ts", ""))
            if ts < str(g["first_ts"]):
                g["first_ts"] = ts
            if ts > str(g["last_ts"]):
                g["last_ts"] = ts
    return sorted(groups.values(), key=lambda g: str(g["last_ts"]), reverse=True)


def rotate_if_needed() -> None:
    """Rotate crash.log when it exceeds CRASH_LOG_MAX_BYTES, keeping
    CRASH_LOG_KEEP numbered backups (crash.log.1 .. crash.log.N)."""
    try:
        if not CRASH_LOG_PATH.is_file():
            return
        if CRASH_LOG_PATH.stat().st_size <= CRASH_LOG_MAX_BYTES:
            return
        oldest = CRASH_LOG_PATH.with_name(CRASH_LOG_PATH.name + f".{CRASH_LOG_KEEP}")
        try:
            oldest.unlink()
        except FileNotFoundError:
            pass
        for i in range(CRASH_LOG_KEEP - 1, 0, -1):
            src = CRASH_LOG_PATH.with_name(CRASH_LOG_PATH.name + f".{i}")
            dst = CRASH_LOG_PATH.with_name(CRASH_LOG_PATH.name + f".{i + 1}")
            if src.exists():
                os.replace(src, dst)
        os.replace(CRASH_LOG_PATH, CRASH_LOG_PATH.with_name(CRASH_LOG_PATH.name + ".1"))
    except OSError:
        pass


def prune_old() -> None:
    """Drop records older than CRASH_LOG_MAX_AGE_DAYS from the crash log."""
    try:
        cutoff = _utcnow() - timedelta(days=CRASH_LOG_MAX_AGE_DAYS)
        kept: list[str] = []
        try:
            with CRASH_LOG_PATH.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            return
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
                ts = datetime.fromisoformat(str(rec["ts"]))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue  # corrupt or unparsable: drop on prune
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc).astimezone().astimezone(timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            if ts >= cutoff:
                kept.append(line if line.endswith("\n") else line + "\n")
        tmp = CRASH_LOG_PATH.with_name(CRASH_LOG_PATH.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.writelines(kept)
        os.replace(tmp, CRASH_LOG_PATH)
    except OSError:
        pass


def install_crash_hook(restore: Excepthook | None = None) -> Excepthook | None:
    """Install a sys.excepthook that logs the crash then delegates.

    If ``restore`` is given, the previous hook is restored instead and
    ``None`` is returned. Otherwise the previous hook is returned so it
    can be restored later (also see ``uninstall_crash_hook``).
    """
    if restore is not None:
        sys.excepthook = restore
        return None

    previous = sys.excepthook

    def _candid_crash_hook(
        exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
    ) -> None:
        try:
            log_crash(exc_value)
        except Exception:
            pass
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = _candid_crash_hook
    return previous


def uninstall_crash_hook(previous: Excepthook | None = None) -> None:
    """Restore the excepthook that was in place before install_crash_hook."""
    sys.excepthook = previous if previous is not None else sys.__excepthook__


def check_last_crash() -> dict | None:
    """Return the record for the last crash, or None if there is none."""
    try:
        crash_id = CRASH_LAST_PATH.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return None
    if not crash_id:
        return None
    for rec in read_crashes():
        if rec.get("id") == crash_id:
            return rec
    return None


def clear_last_crash() -> None:
    """Clear the last-crash marker."""
    try:
        CRASH_LAST_PATH.unlink()
    except (OSError, FileNotFoundError):
        pass
