"""Atomic file writes and cross-platform advisory file locking.

All saves go through a temp file in the same directory followed by
os.replace(), so a crash mid-write never leaves a half-written JSON file
(the rename is atomic on both POSIX and Windows).

Locks are advisory and best-effort: on POSIX we use fcntl.flock, on
Windows msvcrt.locking. If neither is available (or locking fails), the
context manager still yields so the save proceeds unlocked rather than
erroring out.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write", "file_lock"]


def atomic_write(path: str | Path, data: str | bytes, encoding: str = "utf-8") -> Path:
    """Write ``data`` (str or bytes) to ``path`` atomically.

    The payload is written to a temp file in the same directory, fsync'ed,
    then swapped into place with ``os.replace``. No temp file is left
    behind on success or failure.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode(encoding) if isinstance(data, str) else bytes(data)
    fd, tmp = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


@contextlib.contextmanager
def file_lock(path: str | Path):
    """Advisory exclusive lock on ``path + ".lock"`` (context manager).

    Uses ``msvcrt.locking`` on Windows and ``fcntl.flock`` on POSIX.
    Best-effort: if locking primitives are missing or fail, the lock
    file is still opened and we yield anyway, so the guarded save
    proceeds unlocked instead of crashing.
    """
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = lock_path.open("a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass  # locking unavailable - proceed unlocked
        yield f
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()
