"""Transparent encryption at rest for sensitive candid data files.

This module sits between the feature modules (profile, tracker, ...) and the
filesystem. When no keystore exists, every function behaves exactly like a
plain file read/write (backward compatible). When a keystore exists, files
are transparently encrypted with the session passphrase on write and
decrypted on read — callers never handle ciphertext themselves.

The `candid.lock` session module is imported lazily (inside the functions
that need it) so this module stays importable on its own; it is coded
against the lock contract:

    lock.LockError
    lock.require_unlocked()          # no-op when no keystore; raises LockError when locked
    lock.get_session_passphrase()    # str when unlocked, None when no keystore or locked
    lock.is_locked()
    lock.lock_now()
    lock.unlock_session(passphrase, timeout_minutes=None)

Never prints or logs passphrases. No network calls.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from candid import config as C
from candid import crypto

# Number of overwrite passes secure_wipe performs.
WIPE_PASSES = 3


def _lock():
    """Import candid.lock lazily; raise CryptoError if it is unavailable."""
    import importlib

    try:
        return importlib.import_module("candid.lock")
    except ImportError as exc:
        raise crypto.CryptoError(
            "encryption at rest needs the candid.lock session module"
        ) from exc


def _write_bytes_private(path: Path, data: bytes) -> None:
    """Write bytes with mode 0o600 (owner read/write only), atomic-ish.

    Uses os.open with an explicit mode so the file is never briefly
    world-readable, then chmods 0o600 in case the file already existed with
    looser permissions. fsyncs before closing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_protected(path: str | Path, data: bytes, passphrase: str | None = None) -> None:
    """Write bytes to path, encrypting when a keystore exists.

    With a keystore: resolve the passphrase (explicit arg, else the session
    passphrase), require an unlocked session, and write the AES-256-GCM
    envelope with mode 0o600. Without a keystore: plain write, byte-identical
    to ``Path.write_bytes``.
    """
    p = Path(path)
    data = bytes(data)
    if not crypto.keystore_exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return
    lock = _lock()
    resolved = passphrase if passphrase else lock.get_session_passphrase()
    lock.require_unlocked()
    if not resolved:
        raise lock.LockError("no session passphrase available")
    _write_bytes_private(p, crypto.encrypt_bytes(data, resolved))


def read_protected(path: str | Path, passphrase: str | None = None) -> bytes:
    """Read bytes from path, decrypting when the content is an encrypted blob.

    Plaintext files pass through untouched. Missing files raise
    FileNotFoundError as usual. Tampered blobs / wrong passphrases raise
    crypto.CryptoError; a locked session raises lock.LockError.
    """
    p = Path(path)
    raw = p.read_bytes()  # FileNotFoundError when missing
    if not crypto.is_encrypted_blob(raw):
        return raw
    lock = _lock()
    lock.require_unlocked()
    resolved = passphrase if passphrase else lock.get_session_passphrase()
    if not resolved:
        raise lock.LockError("no session passphrase available")
    return crypto.decrypt_bytes(raw, resolved)


def is_encrypted(path: str | Path) -> bool:
    """True iff path exists and its content is a candid encrypted blob."""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        return crypto.is_encrypted_blob(p.read_bytes())
    except OSError:
        return False


def sensitive_files() -> list[Path]:
    """Data files considered sensitive for encryption-at-rest migration.

    The four top-level JSON stores plus every file under the prep_packs and
    tailored directories (when those directories exist). Only existing files
    are returned, sorted for deterministic reports.
    """
    files: list[Path] = []
    for candidate in (
        C.PROFILE_PATH,
        C.TRACKER_PATH,
        C.OFFERS_PATH,
        C.GMAIL_PROPOSALS_PATH,
    ):
        if candidate.is_file():
            files.append(candidate)
    for directory in (C.PREP_PACKS_DIR, C.TAILOR_DIR):
        if directory.is_dir():
            files.extend(f for f in sorted(directory.rglob("*")) if f.is_file())
    # de-duplicate while preserving order (a dir file could equal a top file)
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def secure_wipe(path: str | Path) -> None:
    """Overwrite a file with random bytes (3 passes), fsync, then unlink it.

    Best-effort by design: on SSDs (wear leveling), journaling filesystems,
    and copy-on-write filesystems the old bytes may survive in blocks the OS
    never rewrites. It still defeats casual recovery from the live file.
    Raises FileNotFoundError when the file does not exist.
    """
    p = Path(path)
    size = p.stat().st_size  # FileNotFoundError when missing
    if size > 0:
        with open(p, "r+b") as fh:
            for _ in range(WIPE_PASSES):
                fh.seek(0)
                remaining = size
                while remaining:
                    chunk = secrets.token_bytes(min(remaining, 1024 * 1024))
                    fh.write(chunk)
                    remaining -= len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
    p.unlink()


# --- migration ---------------------------------------------------------------


def _display_name(path: Path) -> str:
    try:
        return str(path.relative_to(C.DATA_DIR))
    except ValueError:
        return str(path)


def migrate_atrest(*, decrypt: bool = False) -> list[tuple[str, str]]:
    """Encrypt (or with decrypt=True, decrypt) every sensitive file.

    Returns a per-file report: [(display_name, status), ...] where status is
    one of "encrypted", "decrypted", "skipped (already encrypted)",
    "skipped (plaintext)".

    Requires a keystore (else crypto.CryptoError telling the user to run
    `candid crypto init` first) and an unlocked session (else LockError).

    Each file is converted via a temp sibling: the converted copy is
    verified (decrypts back to the exact original bytes, or matches the
    decrypted plaintext) BEFORE the original is secure-wiped and the temp
    file is moved into place — a crash mid-file never loses data.
    """
    if not crypto.keystore_exists():
        raise crypto.CryptoError(
            "encryption at rest needs a keystore: run `candid crypto init` first"
        )
    lock = _lock()
    lock.require_unlocked()
    passphrase = lock.get_session_passphrase()
    if not passphrase:
        raise lock.LockError("no session passphrase available")

    report: list[tuple[str, str]] = []
    for path in sensitive_files():
        name = _display_name(path)
        encrypted = is_encrypted(path)
        if decrypt and not encrypted:
            report.append((name, "skipped (plaintext)"))
            continue
        if not decrypt and encrypted:
            report.append((name, "skipped (already encrypted)"))
            continue
        original = path.read_bytes()
        if decrypt:
            plaintext = crypto.decrypt_bytes(original, passphrase)
            tmp = path.with_name(path.name + ".atrest.tmp")
            tmp.write_bytes(plaintext)
            if tmp.read_bytes() != plaintext:
                tmp.unlink(missing_ok=True)
                raise crypto.CryptoError(f"verification failed for {name}")
            secure_wipe(path)
            os.replace(tmp, path)
            report.append((name, "decrypted"))
        else:
            blob = crypto.encrypt_bytes(original, passphrase)
            tmp = path.with_name(path.name + ".atrest.tmp")
            _write_bytes_private(tmp, blob)
            if crypto.decrypt_bytes(tmp.read_bytes(), passphrase) != original:
                tmp.unlink(missing_ok=True)
                raise crypto.CryptoError(f"verification failed for {name}")
            secure_wipe(path)
            os.replace(tmp, path)
            report.append((name, "encrypted"))
    return report


# --- CLI ---------------------------------------------------------------------


def cmd_crypto_migrate(args) -> list[tuple[str, str]]:
    """`candid crypto migrate [--decrypt]`: encrypt/decrypt sensitive files.

    Refuses to run without a keystore. Prints a per-file report.
    """
    if not crypto.keystore_exists():
        msg = "no keystore exists: run `candid crypto init` first"
        print(msg)
        raise crypto.CryptoError(msg)
    lock = _lock()
    lock.require_unlocked()
    decrypt = bool(getattr(args, "decrypt", False))
    report = migrate_atrest(decrypt=decrypt)
    if not report:
        print("No sensitive files found; nothing to migrate.")
        return report
    action = "decrypt" if decrypt else "encrypt"
    for name, status in report:
        print(f"  {status:28} {name}")
    done = sum(1 for _, s in report if s in ("encrypted", "decrypted"))
    skipped = len(report) - done
    print(f"{action.title()}ed {done} file(s), skipped {skipped}.")
    return report


def register_atrest_commands(subparsers) -> None:
    """Register the `migrate` subcommand on the `crypto` command group.

    `subparsers` is the argparse subparsers object for the `crypto` command;
    a later worker wires it into __main__.py.
    """
    p = subparsers.add_parser(
        "migrate",
        help="Encrypt (or --decrypt) sensitive data files at rest.",
        description=(
            "Encrypt every plaintext file reported by sensitive_files() "
            "(profile.json, tracker.json, offers.json, gmail_proposals.json, "
            "prep packs, tailored outputs), verifying each converted copy "
            "before secure-wiping the original. --decrypt reverses the "
            "process. Requires an initialized keystore and an unlocked "
            "session."
        ),
        epilog="examples:\n  python -m candid crypto migrate\n"
        "  python -m candid crypto migrate --decrypt",
    )
    p.add_argument(
        "--decrypt",
        action="store_true",
        help="Decrypt encrypted files back to plaintext (wipes the encrypted copies).",
    )
    p.set_defaults(func=cmd_crypto_migrate)
