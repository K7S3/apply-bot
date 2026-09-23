"""Encrypted backups, crypto status, and the audit log for candid.

This module is the backup/audit layer on top of :mod:`candid.crypto`:

- :func:`create_encrypted_backup` zips ``DATA_DIR`` and encrypts it with the
  session passphrase, storing ``<name>.candidbak`` plus a JSON sidecar
  manifest under ``CONFIG_DIR/backups``.
- :func:`restore_encrypted_backup` decrypts a backup, snapshots the current
  data first, and extracts it back into ``DATA_DIR`` (zip-slip guarded).
- :func:`crypto_status` reports keystore / session / file-encryption state.
- :func:`audit_log` / :func:`read_audit` append to and read the JSON-lines
  audit log at ``CONFIG_DIR/audit.log``.

The passphrase always comes from the caller's ``passphrase`` argument or the
unlocked session (``candid.lock``); it is NEVER accepted via CLI argv, so it
cannot leak into shell history. No passphrase, key, salt, or nonce is ever
printed or logged. No network calls are made; everything is local.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from candid import config
from candid.crypto import (
    CryptoError,
    CryptoUnavailableError,
    crypto_available,
    decrypt_bytes,
    encrypt_bytes,
    get_key_info,
    is_encrypted_blob,
    keystore_exists,
)

# --- constants --------------------------------------------------------------

BACKUP_SUFFIX = ".candidbak"
MANIFEST_SUFFIX = ".candidbak.json"
AUDIT_FILENAME = "audit.log"

# Backup names are used as file names: keep them to a safe alphabet so a
# name can never escape BACKUP_DIR ("../../evil" must be rejected).
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


# --- paths (lazy so CANDID_CONFIG_DIR / CANDID_DATA_DIR stay overridable) ---


def _config_dir() -> Path:
    return Path(config.CONFIG_DIR)


def _data_dir() -> Path:
    return Path(config.DATA_DIR)


def _backup_dir() -> Path:
    return _config_dir() / "backups"


def __getattr__(name: str):
    # BACKUP_DIR is part of the integration-worker API contract. It is
    # resolved lazily (not at import time) so CANDID_CONFIG_DIR overrides
    # keep working even when set after import.
    if name == "BACKUP_DIR":
        return _backup_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- internal helpers -------------------------------------------------------


def _lock():
    """Import candid.lock lazily (Worker B owns that file; it may not exist yet)."""
    try:
        from candid import lock
    except ImportError as exc:
        raise CryptoError(
            "candid.lock is not available; the session-lock feature must be "
            "installed before encrypted backups can run"
        ) from exc
    return lock


def _require_crypto() -> None:
    if not crypto_available():
        raise CryptoUnavailableError(
            "Passphrase encryption needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        )


def _require_keystore() -> None:
    if not keystore_exists():
        raise CryptoError("no keystore exists; run `candid crypto init` first")


def _sanitize_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise CryptoError(
            f"invalid backup name {name!r}: use 1-64 chars of letters, "
            "digits, dash, underscore only"
        )
    return name


def _resolve_passphrase(explicit: str | None) -> str:
    """Session passphrase: explicit arg wins, otherwise the unlocked session."""
    lock = _lock()
    lock.require_unlocked()
    pw = explicit or lock.get_session_passphrase()
    if not pw:
        raise CryptoError(
            "no passphrase available: unlock the session "
            "(`candid lock unlock`) and retry"
        )
    return pw


def _write_private(path: Path, data: bytes) -> None:
    """Write bytes to path with mode 0o600 (best effort)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _zip_data_dir() -> tuple[bytes, int, int]:
    """Zip DATA_DIR into memory. Returns (zip_bytes, n_files, total_bytes)."""
    data_dir = _data_dir()
    buf = io.BytesIO()
    n_files = 0
    total_bytes = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if not data_dir.is_dir():
            print(
                f"warning: data dir {data_dir} does not exist; "
                "creating an empty backup",
                file=sys.stderr,
            )
        else:
            for path in sorted(data_dir.rglob("*")):
                # Skip symlinks: they could point outside DATA_DIR and would
                # not survive a restore faithfully anyway.
                if path.is_file() and not path.is_symlink():
                    arcname = path.relative_to(data_dir).as_posix()
                    zf.writestr(arcname, path.read_bytes())
                    n_files += 1
                    total_bytes += path.stat().st_size
    return buf.getvalue(), n_files, total_bytes


def _safe_extract(payload: bytes, dest: Path) -> int:
    """Extract a zip payload into dest, rejecting zip-slip paths.

    Rejects absolute paths, ``..`` segments, drive letters, and anything
    that normalizes outside dest. Returns the number of files extracted.
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = str(dest.resolve())
    n = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            raw = info.filename.replace("\\", "/")
            if not raw:
                continue
            if raw.endswith("/"):
                (dest / raw.rstrip("/")).mkdir(parents=True, exist_ok=True)
                continue
            if (
                Path(raw).is_absolute()
                or ".." in Path(raw).parts
                or re.match(r"^[A-Za-z]:", raw)
                or raw.startswith("~")
            ):
                raise CryptoError(
                    f"refusing to extract unsafe archive path: {info.filename!r}"
                )
            final = os.path.normpath(os.path.join(dest_resolved, raw))
            if not (final == dest_resolved or final.startswith(dest_resolved + os.sep)):
                raise CryptoError(
                    f"refusing to extract path escaping the data dir: {info.filename!r}"
                )
            target = Path(final)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info.filename))
            n += 1
    return n


def _clear_dir(path: Path) -> None:
    """Remove everything inside path (path itself is kept)."""
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            import shutil

            shutil.rmtree(child)


def _newest_mtime(data_dir: Path) -> float | None:
    newest: float | None = None
    if data_dir.is_dir():
        for path in data_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                mtime = path.stat().st_mtime
                if newest is None or mtime > newest:
                    newest = mtime
    return newest


def _read_manifest(name: str) -> dict | None:
    man_path = _backup_dir() / f"{name}{BACKUP_SUFFIX}.json"
    if not man_path.exists():
        return None
    try:
        data = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _manifest_path(name: str) -> Path:
    return _backup_dir() / f"{name}{BACKUP_SUFFIX}.json"


# --- audit log --------------------------------------------------------------


def audit_log(event: str, detail: str = "") -> None:
    """Append one JSON-lines entry to CONFIG_DIR/audit.log (mode 0o600)."""
    path = _config_dir() / AUDIT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": str(event),
        "detail": str(detail),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)
    except BaseException:
        os.close(fd)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_audit(limit: int = 50) -> list[dict]:
    """Read the audit log, newest entries first (up to `limit`)."""
    path = _config_dir() / AUDIT_FILENAME
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    entries.reverse()
    return entries[: max(0, limit)]


# --- backups ----------------------------------------------------------------


def create_encrypted_backup(name: str, passphrase: str | None = None) -> Path:
    """Zip DATA_DIR, encrypt it, and store it as BACKUP_DIR/<name>.candidbak.

    Requires an initialized keystore and an unlocked session; the passphrase
    comes from the explicit argument or the session (never CLI argv).
    Writes a sidecar manifest <name>.candidbak.json with name, created_at,
    n_files, total_bytes, and key_info (iterations only, never secrets).
    Filenames inside the zip are not considered sensitive. An empty or
    missing DATA_DIR is allowed (with a warning), not an error.
    """
    name = _sanitize_name(name)
    _require_crypto()
    _require_keystore()
    pw = _resolve_passphrase(passphrase)

    zip_bytes, n_files, total_bytes = _zip_data_dir()
    blob = encrypt_bytes(zip_bytes, pw)

    out = _backup_dir() / f"{name}{BACKUP_SUFFIX}"
    _write_private(out, blob)

    key_info = get_key_info()
    manifest = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_files": n_files,
        "total_bytes": total_bytes,
        # Iterations only: never salts, verifiers, keys, or passphrases.
        "key_info": {"iterations": key_info.get("iterations")},
    }
    _write_private(_manifest_path(name), json.dumps(manifest, indent=2).encode("utf-8"))

    audit_log("backup_created", name)
    return out


def restore_encrypted_backup(
    name: str, passphrase: str | None = None, force: bool = False
) -> Path:
    """Restore BACKUP_DIR/<name>.candidbak into DATA_DIR.

    Requires an unlocked session. The current DATA_DIR is first snapshotted
    to BACKUP_DIR/pre-restore-<timestamp>.candidbak (encrypted with the same
    passphrase). Without force=True, refuses when DATA_DIR contains files
    newer than the backup. Extraction is zip-slip guarded.
    """
    name = _sanitize_name(name)
    _require_crypto()
    _require_keystore()
    pw = _resolve_passphrase(passphrase)

    src = _backup_dir() / f"{name}{BACKUP_SUFFIX}"
    if not src.exists():
        raise CryptoError(f"no such backup: {name!r}")
    # Raises CryptoError("wrong passphrase or corrupt data") on tampering or
    # a wrong passphrase; raises CryptoError on malformed blobs.
    payload = decrypt_bytes(src.read_bytes(), pw)
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise CryptoError(f"backup {name!r}: decrypted payload is not a valid archive")

    if not force:
        manifest = _read_manifest(name)
        backup_ts: float | None = None
        if manifest and manifest.get("created_at"):
            try:
                backup_ts = datetime.fromisoformat(manifest["created_at"]).timestamp()
            except ValueError:
                backup_ts = None
        if backup_ts is None:
            backup_ts = src.stat().st_mtime
        newest = _newest_mtime(_data_dir())
        if newest is not None and newest > backup_ts + 1:
            raise CryptoError(
                f"DATA_DIR contains files newer than backup {name!r}; "
                "pass --force to overwrite anyway"
            )

    # Snapshot current state BEFORE overwriting, so a bad restore is undoable.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_name = f"pre-restore-{stamp}"
    counter = 2
    while (_backup_dir() / f"{snap_name}{BACKUP_SUFFIX}").exists():
        snap_name = f"pre-restore-{stamp}-{counter}"
        counter += 1
    create_encrypted_backup(snap_name, pw)
    audit_log("pre_restore_snapshot", snap_name)

    data_dir = _data_dir()
    _clear_dir(data_dir)
    _safe_extract(payload, data_dir)

    audit_log("backup_restored", name)
    return data_dir


def list_backups() -> list[dict]:
    """List encrypted backups from BACKUP_DIR, newest first.

    Each entry: name, path, size_bytes, created_at, n_files, total_bytes,
    manifest_missing. A .candidbak file with no sidecar manifest is still
    listed, flagged manifest_missing=True.
    """
    bdir = _backup_dir()
    if not bdir.is_dir():
        return []
    out: list[dict] = []
    for blob in sorted(bdir.glob(f"*{BACKUP_SUFFIX}")):
        name = blob.name[: -len(BACKUP_SUFFIX)]
        manifest = _read_manifest(name)
        out.append(
            {
                "name": name,
                "path": str(blob),
                "size_bytes": blob.stat().st_size,
                "created_at": (manifest or {}).get("created_at"),
                "n_files": (manifest or {}).get("n_files"),
                "total_bytes": (manifest or {}).get("total_bytes"),
                "manifest_missing": manifest is None,
            }
        )
    out.sort(key=lambda e: (e["created_at"] or "", e["name"]), reverse=True)
    return out


# --- status -----------------------------------------------------------------


def _file_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        data = path.read_bytes()
    except OSError:
        return "unreadable"
    return "encrypted" if is_encrypted_blob(data) else "plaintext"


def crypto_status() -> dict:
    """Snapshot of encryption state: keystore, session, files, backups.

    files maps each sensitive path to "encrypted" | "plaintext" | "missing"
    (never includes file contents or secrets).
    """
    lock = _lock()
    key_info = get_key_info()
    # Sensitive file set from candid.config, resolved against the CURRENT
    # DATA_DIR (the config constants are import-time values, so derive the
    # live paths from their basenames to stay correct under overrides).
    data_dir = _data_dir()
    sensitive = [
        data_dir / Path(config.PROFILE_PATH).name,
        data_dir / Path(config.TRACKER_PATH).name,
        data_dir / Path(config.OFFERS_PATH).name,
        data_dir / Path(config.GMAIL_PROPOSALS_PATH).name,
    ]
    files = {str(p): _file_state(p) for p in sensitive}
    return {
        "keystore": key_info if key_info.get("has_verifier") else None,
        "locked": lock.is_locked(),
        "session": lock.session_info(),
        "crypto_available": crypto_available(),
        "files": files,
        "backups": len(list_backups()),
    }


# --- CLI --------------------------------------------------------------------


def _die_unless_crypto() -> None:
    if not crypto_available():
        raise CryptoUnavailableError(
            "Passphrase encryption needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        )


def cmd_encbackup_backup(args) -> Path:
    """`candid crypto backup <name>`: encrypted backup of DATA_DIR."""
    _die_unless_crypto()
    out = create_encrypted_backup(args.name)
    manifest = _read_manifest(args.name) or {}
    print(
        f"created encrypted backup {args.name!r}: "
        f"{manifest.get('n_files', '?')} files, "
        f"{manifest.get('total_bytes', '?')} bytes -> {out}"
    )
    return out


def cmd_encbackup_restore(args) -> Path:
    """`candid crypto restore <name> [--force]`: restore a backup."""
    _die_unless_crypto()
    dest = restore_encrypted_backup(args.name, force=bool(getattr(args, "force", False)))
    print(f"restored backup {args.name!r} into {dest}")
    return dest


def cmd_encbackup_status(args) -> dict:
    """`candid crypto status [--json]`: show encryption/session/backup state."""
    _die_unless_crypto()
    status = crypto_status()
    if getattr(args, "json", False):
        print(json.dumps(status, indent=2))
        return status
    ki = status["keystore"]
    sess = status["session"] or {}
    print("crypto status")
    print(f"  cryptography package: {'available' if status['crypto_available'] else 'MISSING'}")
    if ki:
        print(
            f"  keystore: initialized "
            f"({ki.get('iterations')} iterations, created {ki.get('created_at')})"
        )
    else:
        print("  keystore: not initialized (run `candid crypto init`)")
    if status["locked"]:
        print("  session: locked")
    else:
        print(f"  session: unlocked (expires in {sess.get('expires_in_seconds')}s)")
    print(f"  backups: {status['backups']}")
    print("  files:")
    for path, state in status["files"].items():
        print(f"    {path}: {state}")
    return status


def cmd_encbackup_audit(args) -> list[dict]:
    """`candid crypto audit [--limit N] [--json]`: show the audit log."""
    _die_unless_crypto()
    entries = read_audit(int(getattr(args, "limit", 50) or 50))
    if getattr(args, "json", False):
        print(json.dumps(entries, indent=2))
        return entries
    if not entries:
        print("audit log is empty")
        return entries
    for e in entries:
        detail = f"  {e['detail']}" if e.get("detail") else ""
        print(f"{e.get('ts')}  {e.get('event')}{detail}")
    return entries


def register_encbackup_commands(subparsers) -> None:
    """Register backup/restore/status/audit under the `crypto` command group.

    `subparsers` is the argparse subparsers object for the `crypto` command;
    the integration worker wires it into __main__.py.

    Security note (also shown in --help): the passphrase is NEVER accepted as
    a CLI argument — it comes from the unlocked session only, so it cannot
    leak into shell history.
    """
    p_backup = subparsers.add_parser(
        "backup",
        help="Create an encrypted backup of your data.",
        description="Zip DATA_DIR, encrypt it, and store it as "
        "<name>.candidbak in the backups dir. The passphrase is taken from "
        "the unlocked session only; it is never accepted as a CLI argument "
        "(that would leak it into shell history).",
        epilog="examples:\n  python -m candid crypto backup nightly",
    )
    p_backup.add_argument(
        "name",
        help="backup name: letters, digits, dash, underscore only",
    )
    p_backup.set_defaults(func=cmd_encbackup_backup)

    p_restore = subparsers.add_parser(
        "restore",
        help="Restore an encrypted backup into your data dir.",
        description="Decrypt a backup and extract it into DATA_DIR. The "
        "current data is snapshotted first (pre-restore-<timestamp>). "
        "Refuses when current files are newer than the backup unless "
        "--force is given.",
        epilog="examples:\n  python -m candid crypto restore nightly\n"
        "  python -m candid crypto restore nightly --force",
    )
    p_restore.add_argument("name", help="name of the backup to restore")
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="overwrite even if current data is newer than the backup",
    )
    p_restore.set_defaults(func=cmd_encbackup_restore)

    p_status = subparsers.add_parser(
        "status",
        help="Show keystore, session, file-encryption, and backup status.",
        epilog="examples:\n  python -m candid crypto status\n"
        "  python -m candid crypto status --json",
    )
    p_status.add_argument("--json", action="store_true", help="machine-readable output")
    p_status.set_defaults(func=cmd_encbackup_status)

    p_audit = subparsers.add_parser(
        "audit",
        help="Show the audit log (newest first).",
        epilog="examples:\n  python -m candid crypto audit\n"
        "  python -m candid crypto audit --limit 10 --json",
    )
    p_audit.add_argument(
        "--limit", type=int, default=50, help="max entries to show (default 50)"
    )
    p_audit.add_argument("--json", action="store_true", help="machine-readable output")
    p_audit.set_defaults(func=cmd_encbackup_audit)
