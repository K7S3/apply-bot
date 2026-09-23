"""Session lock/unlock for candid's passphrase encryption.

Threat model (stated honestly):

- The session file (CONFIG_DIR/session.json, mode 0o600) caches the user's
  *passphrase* so each CLI invocation can re-derive per-file encryption keys
  without prompting again. While a session is unlocked, anyone who can read
  the user's account can read the session file and decrypt data.
- What this protects against:
  * a stolen or lost disk *while locked* (keys are passphrase-derived; nothing
    on disk helps an attacker without the passphrase), and
  * an unattended unlocked terminal *after the timeout lapses* (sessions are
    age-based: created_at + timeout_minutes, so a forgotten terminal re-locks
    itself).
- Out of scope: a live compromise of the user account while unlocked
  (keyloggers, memory readers, process inspection). No local agent can defend
  against that; `candid lock` is your manual tripwire.

Sessions are age-based, not idle-based: there is no per-command idle timer.
Idle tracking would need hooks in every command (a missed hook silently
extends the window), so the session simply expires `timeout_minutes` after it
was created.

No passphrases are ever logged or printed. No network calls are made.
"""

from __future__ import annotations

import getpass
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from candid.crypto import CryptoError, keystore_exists, verify_passphrase

SESSION_FILENAME = "session.json"


# --- exceptions -------------------------------------------------------------


class LockError(LookupError):
    """Raised when a locked operation is attempted while candid is locked.

    A LookupError subclass ("LookupError-ish") so callers that treat a locked
    session like a missing value get sensible semantics.
    """


# --- config-dir access (lazy, respects CANDID_CONFIG_DIR) --------------------


def _config_dir() -> Path:
    from candid import config as _config

    return Path(_config.CONFIG_DIR)


def _session_path() -> Path:
    return _config_dir() / SESSION_FILENAME


def _default_timeout_minutes() -> int:
    from candid import config as _config

    return int(_config.CONFIG_DEFAULTS.get("lock_timeout_minutes", 30))


# --- session file I/O ---------------------------------------------------------


def _write_session(passphrase: str, timeout_minutes: int) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passphrase": passphrase,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timeout_minutes": timeout_minutes,
    }
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_session() -> dict | None:
    """Return the session payload, or None when missing/invalid.

    A corrupt or unreadable session is treated as no session (i.e. locked):
    fail closed.
    """
    path = _session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("passphrase"), str)
        or not data.get("passphrase")
        or not isinstance(data.get("created_at"), str)
        or not isinstance(data.get("timeout_minutes"), (int, float))
    ):
        return None
    try:
        datetime.fromisoformat(data["created_at"])
    except ValueError:
        return None
    return data


def _session_expired(session: dict) -> bool:
    created = datetime.fromisoformat(session["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    expiry = created + timedelta(minutes=float(session["timeout_minutes"]))
    return datetime.now(timezone.utc) > expiry


# --- public API ---------------------------------------------------------------


def unlock_session(passphrase: str, timeout_minutes: int | None = None) -> None:
    """Unlock the session by verifying the passphrase against the keystore.

    Writes CONFIG_DIR/session.json (mode 0o600) with the passphrase, creation
    time, and timeout. Raises CryptoError when no keystore exists
    ("run `candid crypto init` first") or the passphrase is wrong.
    """
    if not keystore_exists():
        raise CryptoError("no keystore exists; run `candid crypto init` first")
    if not passphrase or not verify_passphrase(passphrase):
        raise CryptoError("incorrect passphrase")
    timeout = _default_timeout_minutes() if timeout_minutes is None else timeout_minutes
    if timeout <= 0:
        raise CryptoError("timeout_minutes must be positive")
    _write_session(passphrase, int(timeout))


def lock_now() -> None:
    """Lock the session now: forget the cached passphrase.

    Secure-ish teardown: the session file is overwritten with zeros before
    unlinking, so the passphrase does not linger in unallocated-but-readable
    blocks. No-op when there is no session file.
    """
    path = _session_path()
    if not path.exists():
        return
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            fh.write(b"\x00" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def is_locked() -> bool:
    """True when candid is locked.

    False when no keystore exists (backward compatible: encryption not set
    up means everything works as before). True when a keystore exists and
    there is no session file, or the session has expired.
    """
    if not keystore_exists():
        return False
    session = _read_session()
    if session is None:
        return True
    return _session_expired(session)


def require_unlocked() -> None:
    """Raise LockError when locked; no-op otherwise (including no keystore)."""
    if is_locked():
        raise LockError("candid is locked - run `candid unlock`")


def get_session_passphrase() -> str | None:
    """Return the cached passphrase when the session is valid, else None.

    Never logs or prints the value; callers must treat it as secret.
    """
    if not keystore_exists():
        return None
    session = _read_session()
    if session is None or _session_expired(session):
        return None
    return session["passphrase"]


def touch_session() -> None:
    """No-op.

    Sessions are age-based (created_at + timeout_minutes), not idle-based, so
    there is nothing to refresh. Per-command idle tracking would need hooks
    in every command; a hook missed anywhere would silently extend the unlock
    window, which is worse than an honest fixed window.
    """


def session_info() -> dict:
    """Public session metadata: locked, created_at, timeout_minutes,
    expires_in_seconds. Contains no secrets."""
    locked = is_locked()
    session = _read_session() if keystore_exists() else None
    if session is None or _session_expired(session):
        return {
            "locked": locked,
            "created_at": None,
            "timeout_minutes": None,
            "expires_in_seconds": None,
        }
    created = datetime.fromisoformat(session["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    expires_in = (created + timedelta(minutes=float(session["timeout_minutes"]))
                  - datetime.now(timezone.utc)).total_seconds()
    return {
        "locked": locked,
        "created_at": session["created_at"],
        "timeout_minutes": session["timeout_minutes"],
        "expires_in_seconds": max(0.0, expires_in),
    }


# --- CLI --------------------------------------------------------------------
# Thin wrappers over the functions above. Prompt-based variants take getpass
# input; every command also accepts the secret directly via a private kwarg so
# tests never need a tty.


def cmd_lock(args) -> None:
    """`candid lock`: lock the session now."""
    lock_now()
    print("Session locked.")


def cmd_unlock(args, _passphrase: str | None = None) -> None:
    """`candid unlock [--timeout MINUTES]`: verify passphrase, start a session."""
    timeout = getattr(args, "timeout", None)
    passphrase = _passphrase if _passphrase is not None else getpass.getpass("Passphrase: ")
    unlock_session(passphrase, timeout_minutes=timeout)
    info = session_info()
    print(f"Unlocked for {info['timeout_minutes']} minutes.")


def register_lock_commands(subparsers) -> None:
    """Register the top-level `lock` and `unlock` commands.

    `subparsers` is the TOP-LEVEL command subparsers object; a later worker
    wires this into __main__.py.
    """
    p_lock = subparsers.add_parser(
        "lock",
        help="Lock the session now (forget the cached passphrase).",
        description="Delete the cached session passphrase immediately.",
        epilog="examples:\n  python -m candid lock",
    )
    p_lock.set_defaults(func=cmd_lock)

    p_unlock = subparsers.add_parser(
        "unlock",
        help="Unlock the session (verify passphrase, start a timed session).",
        description="Verify the passphrase against the keystore and cache it "
        "for a timed session (default 30 minutes, see lock_timeout_minutes).",
        epilog="examples:\n  python -m candid unlock\n"
        "  python -m candid unlock --timeout 10",
    )
    p_unlock.add_argument(
        "--timeout",
        type=int,
        metavar="MINUTES",
        default=None,
        help="Session length in minutes (overrides the configured default).",
    )
    p_unlock.set_defaults(func=cmd_unlock)
