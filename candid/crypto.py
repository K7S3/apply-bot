"""Passphrase-based encryption at rest for the candid package.

This module is the cryptographic core used to protect user data with a
passphrase. It uses AES-256-GCM for encryption and PBKDF2-HMAC-SHA256
(600,000 iterations by default, per OWASP guidance) for key derivation.

The `cryptography` package is OPTIONAL: every crypto operation degrades
gracefully. `crypto_available()` reports whether it is installed, and the
encrypt/decrypt/KDF/keystore entry points raise `CryptoUnavailableError`
(with a clear install hint) when it is missing instead of ImportError.

No passphrases, keys, salts, or nonces are ever logged or printed.
No network calls are made; everything is local.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

# --- constants --------------------------------------------------------------

MAGIC = b"CANDID1"  # envelope magic, also bound as GCM associated data
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32
DEFAULT_ITERATIONS = 600_000
KEYSTORE_FILENAME = "keystore.json"
# Domain separation for the keystore verifier derivation: the verifier is a
# derived value, never the passphrase and never a data-encryption key.
_VERIFIER_DOMAIN = "candid-keystore-verifier\x00"

# --- exceptions -------------------------------------------------------------


class CryptoError(Exception):
    """Base error for all candid crypto failures."""


class CryptoUnavailableError(CryptoError):
    """Raised when an operation needs the `cryptography` package but it is missing."""


# --- availability -----------------------------------------------------------


def _import_crypto():
    """Import the pieces of `cryptography` we need, or raise CryptoUnavailableError.

    The import is deferred (not module-level) so the rest of this module —
    strength meter, CLI wiring — works even when `cryptography` is absent.
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as exc:
        raise CryptoUnavailableError(
            "Passphrase encryption needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        ) from exc
    return hashes, PBKDF2HMAC, AESGCM


def crypto_available() -> bool:
    """True iff the `cryptography` package is importable."""
    try:
        _import_crypto()
    except CryptoUnavailableError:
        return False
    return True


# --- key derivation ---------------------------------------------------------


def derive_key(passphrase: str, salt: bytes, iterations: int = DEFAULT_ITERATIONS) -> bytes:
    """Derive a 32-byte key from a passphrase via PBKDF2-HMAC-SHA256.

    Deterministic for a given (passphrase, salt, iterations) triple.
    Raises CryptoUnavailableError when `cryptography` is not installed.
    """
    if not isinstance(salt, (bytes, bytearray)) or not salt:
        raise CryptoError("salt must be non-empty bytes")
    if iterations <= 0:
        raise CryptoError("iterations must be positive")
    _hashes, PBKDF2HMAC, _AESGCM = _import_crypto()
    kdf = PBKDF2HMAC(
        algorithm=_hashes.SHA256(),
        length=KEY_LEN,
        salt=bytes(salt),
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


# --- symmetric encryption ---------------------------------------------------


def encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt bytes with AES-256-GCM under a passphrase-derived key.

    Envelope: MAGIC (7 bytes) + salt (16) + nonce (12) + ciphertext+tag.
    Raises CryptoUnavailableError when `cryptography` is not installed.
    """
    if not passphrase:
        raise CryptoError("passphrase must not be empty")
    _hashes, _PBKDF2HMAC, AESGCM = _import_crypto()
    salt = secrets.token_bytes(SALT_LEN)
    nonce = secrets.token_bytes(NONCE_LEN)
    key = derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(nonce, bytes(plaintext), MAGIC)
    return MAGIC + salt + nonce + ct


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a blob produced by encrypt_bytes.

    Raises CryptoError("wrong passphrase or corrupt data") when the GCM tag
    does not verify (wrong passphrase or tampered blob). Raises CryptoError
    for malformed blobs.
    """
    if not passphrase:
        raise CryptoError("passphrase must not be empty")
    blob = bytes(blob)
    header_len = len(MAGIC) + SALT_LEN + NONCE_LEN
    if len(blob) < header_len + 1 or not hmac.compare_digest(blob[: len(MAGIC)], MAGIC):
        raise CryptoError("not a candid encrypted blob")
    salt = blob[len(MAGIC) : len(MAGIC) + SALT_LEN]
    nonce = blob[len(MAGIC) + SALT_LEN : header_len]
    ct = blob[header_len:]
    _hashes, _PBKDF2HMAC, AESGCM = _import_crypto()
    key = derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, MAGIC)
    except Exception as exc:
        # cryptography raises InvalidTag; normalize so callers do not have
        # to depend on its exception types, and so a wrong passphrase is
        # indistinguishable from corrupted data.
        raise CryptoError("wrong passphrase or corrupt data") from exc


def is_encrypted_blob(data: bytes) -> bool:
    """True iff data starts with the candid encryption magic."""
    try:
        data = bytes(data)
    except (TypeError, ValueError):
        return False
    return len(data) >= len(MAGIC) and hmac.compare_digest(data[: len(MAGIC)], MAGIC)


# --- passphrase strength ----------------------------------------------------

_COMMON_PATTERNS = (
    "password",
    "passw0rd",
    "123456",
    "12345678",
    "qwerty",
    "letmein",
    "welcome",
    "monkey",
    "dragon",
    "football",
    "abc123",
    "admin",
    "111111",
    "000000",
    "candid",
    "jobsearch",
)

_STRENGTH_LABELS = {0: "very weak", 1: "weak", 2: "okay", 3: "strong", 4: "very strong"}


def passphrase_strength(passphrase: str) -> tuple[int, list[str]]:
    """Score a passphrase 0-4 and return human-readable feedback.

    Scoring: +1 for length >= 12, +1 for length >= 16, +1 for using at least
    three of the four character classes (lower/upper/digit/symbol), +1 for
    containing no common pattern, repeated run, or long sequence.
    """
    passphrase = passphrase or ""
    feedback: list[str] = []
    score = 0

    if len(passphrase) >= 12:
        score += 1
    else:
        feedback.append("use at least 12 characters")

    if len(passphrase) >= 16:
        score += 1
    elif len(passphrase) >= 12:
        feedback.append("16+ characters is even better")

    classes = sum(
        (
            any(c.islower() for c in passphrase),
            any(c.isupper() for c in passphrase),
            any(c.isdigit() for c in passphrase),
            any(c in string.punctuation for c in passphrase),
        )
    )
    if classes >= 3:
        score += 1
    else:
        feedback.append("mix uppercase, lowercase, digits, and symbols")

    lowered = passphrase.lower()
    has_common = any(p in lowered for p in _COMMON_PATTERNS)
    has_run = bool(re.search(r"(.)\1\1", passphrase))  # aaa, 111, ...
    has_sequence = any(
        seq in lowered or seq in lowered[::-1]
        for seq in ("abcd", "bcde", "cdef", "defg", "efgh", "fghi", "ghij",
                    "hijk", "ijkl", "jklm", "klmn", "lmno", "mnop", "nopq",
                    "opqr", "pqrs", "qrst", "rstu", "stuv", "tuvw", "uvwx",
                    "vwxy", "wxyz", "1234", "2345", "3456", "4567", "5678",
                    "6789", "7890")
    )
    if passphrase and not (has_common or has_run or has_sequence):
        score += 1
    elif passphrase:
        if has_common:
            feedback.append("avoid common words and patterns")
        if has_run or has_sequence:
            feedback.append("avoid repeated characters and sequences")

    if not feedback:
        feedback.append("looks good")
    return min(score, 4), feedback


def strength_label(score: int) -> str:
    """Human label for a strength score."""
    return _STRENGTH_LABELS.get(max(0, min(4, score)), "unknown")


# --- keystore ---------------------------------------------------------------

# The keystore lives in CONFIG_DIR (overridable via CANDID_CONFIG_DIR) so the
# passphrase verifier is per-user, separate from the (possibly shared/exported)
# data directory. We read CONFIG_DIR lazily so tests can re-point it.


def _config_dir() -> Path:
    from candid import config as _config

    return Path(_config.CONFIG_DIR)


def _keystore_path() -> Path:
    return _config_dir() / KEYSTORE_FILENAME


def _load_keystore() -> dict | None:
    path = _keystore_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CryptoError(f"keystore is unreadable: {exc}") from exc
    if not isinstance(data, dict) or "verifier" not in data or "salt" not in data:
        raise CryptoError("keystore is corrupt")
    return data


def _write_keystore(data: dict) -> None:
    path = _keystore_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    # 0o600: the verifier only helps offline guessing attacks a little, but
    # defense in depth costs nothing here.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
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


def _verifier_for(passphrase: str, salt: bytes, iterations: int) -> bytes:
    """Derived verifier value stored in the keystore.

    This is a KDF output over a domain-separated passphrase — never the
    passphrase itself and never a key used to encrypt data.
    """
    return derive_key(_VERIFIER_DOMAIN + passphrase, salt, iterations)


def keystore_exists() -> bool:
    """True iff a keystore has been initialized."""
    return _keystore_path().exists()


def init_keystore(passphrase: str, *, iterations: int = DEFAULT_ITERATIONS,
                  force: bool = False) -> dict:
    """Create the keystore with a salt + verifier for the passphrase.

    Raises CryptoError if a keystore already exists (unless force=True) or
    the passphrase is empty/weak (score < 2 requires force=True).
    Returns the public key info dict (same shape as get_key_info()).
    Raises CryptoUnavailableError when `cryptography` is not installed.
    """
    if not passphrase:
        raise CryptoError("passphrase must not be empty")
    score, _fb = passphrase_strength(passphrase)
    if score < 2 and not force:
        raise CryptoError(
            f"passphrase is too weak (score {score}/4, need >= 2); "
            "use --force to proceed anyway"
        )
    if keystore_exists() and not force:
        raise CryptoError("keystore already exists; use change_passphrase to change it")
    salt = secrets.token_bytes(SALT_LEN)
    verifier = _verifier_for(passphrase, salt, iterations)
    _write_keystore(
        {
            "version": 1,
            "kdf": "pbkdf2-hmac-sha256",
            "iterations": iterations,
            "salt": base64.b64encode(salt).decode("ascii"),
            "verifier": base64.b64encode(verifier).decode("ascii"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return get_key_info()


def verify_passphrase(passphrase: str) -> bool:
    """Constant-time check of a passphrase against the keystore.

    Returns False when no keystore exists (never raises for a wrong guess).
    Raises CryptoUnavailableError when `cryptography` is not installed.
    """
    data = _load_keystore()
    if data is None:
        return False
    if not passphrase:
        return False
    try:
        salt = base64.b64decode(data["salt"])
        expected = base64.b64decode(data["verifier"])
    except (ValueError, KeyError) as exc:
        raise CryptoError("keystore is corrupt") from exc
    candidate = _verifier_for(passphrase, salt, int(data.get("iterations", DEFAULT_ITERATIONS)))
    # sha256 of both sides first so the compare is fixed-length; compare_digest
    # itself is constant-time for equal-length inputs.
    return hmac.compare_digest(
        hashlib.sha256(candidate).digest(), hashlib.sha256(expected).digest()
    )


def change_passphrase(old: str, new: str, *, force: bool = False) -> dict:
    """Change the keystore passphrase after verifying the old one.

    Raises CryptoError when the old passphrase does not match or the new one
    is empty/weak (score < 2 requires force=True). The old verifier is
    replaced atomically; a failed change leaves the old one intact.
    Raises CryptoUnavailableError when `cryptography` is not installed.
    """
    if not keystore_exists():
        raise CryptoError("no keystore exists; run `candid crypto init` first")
    if not verify_passphrase(old):
        raise CryptoError("incorrect passphrase")
    if not new:
        raise CryptoError("new passphrase must not be empty")
    score, _fb = passphrase_strength(new)
    if score < 2 and not force:
        raise CryptoError(
            f"new passphrase is too weak (score {score}/4, need >= 2); "
            "use --force to proceed anyway"
        )
    data = _load_keystore()
    assert data is not None
    iterations = int(data.get("iterations", DEFAULT_ITERATIONS))
    salt = secrets.token_bytes(SALT_LEN)
    verifier = _verifier_for(new, salt, iterations)
    data.update(
        {
            "salt": base64.b64encode(salt).decode("ascii"),
            "verifier": base64.b64encode(verifier).decode("ascii"),
            "changed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_keystore(data)
    return get_key_info()


def get_key_info() -> dict:
    """Public keystore metadata: iterations, created_at, has_verifier.

    Never includes secrets (no salt, verifier, passphrase, or key).
    Values are None/False when no keystore exists.
    """
    data = _load_keystore()
    if data is None:
        return {"iterations": None, "created_at": None, "has_verifier": False}
    return {
        "iterations": data.get("iterations"),
        "created_at": data.get("created_at"),
        "has_verifier": bool(data.get("verifier")),
    }


# --- CLI --------------------------------------------------------------------
# Thin wrappers around the core functions above. The prompt-based variants
# take getpass input; every command also accepts the secret directly via a
# private kwarg so tests never need a tty.


def _print_strength(passphrase: str) -> int:
    score, feedback = passphrase_strength(passphrase)
    label = strength_label(score)
    bars = "#" * score + "-" * (4 - score)
    print(f"Passphrase strength: [{bars}] {score}/4 ({label})")
    for tip in feedback:
        print(f"  - {tip}")
    return score


def crypto_init(passphrase: str, *, force: bool = False,
                iterations: int = DEFAULT_ITERATIONS) -> dict:
    """Testable core of `crypto init` (no prompting, no printing)."""
    return init_keystore(passphrase, iterations=iterations, force=force)


def cmd_crypto_init(args, _passphrase: str | None = None,
                    _confirm: str | None = None) -> dict:
    """`candid crypto init [--force]`: set the passphrase for the first time."""
    if not crypto_available():
        raise CryptoUnavailableError(
            "Passphrase encryption needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        )
    force = bool(getattr(args, "force", False))
    passphrase = _passphrase if _passphrase is not None else getpass.getpass("New passphrase: ")
    score = _print_strength(passphrase)
    if score < 2 and not force:
        raise CryptoError("passphrase too weak; re-run with --force to use it anyway")
    confirm = _confirm if _confirm is not None else getpass.getpass("Confirm passphrase: ")
    if not hmac.compare_digest(passphrase.encode("utf-8"), confirm.encode("utf-8")):
        raise CryptoError("passphrases do not match")
    info = crypto_init(passphrase, force=force)
    print(f"Keystore initialized ({info['created_at']}).")
    print("Keep your passphrase safe: it cannot be recovered if lost.")
    return info


def crypto_verify(passphrase: str) -> bool:
    """Testable core of `crypto verify` (no prompting, no printing)."""
    return verify_passphrase(passphrase)


def cmd_crypto_verify(args, _passphrase: str | None = None) -> bool:
    """`candid crypto verify`: check a passphrase against the keystore."""
    if not crypto_available():
        raise CryptoUnavailableError(
            "Passphrase verification needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        )
    passphrase = _passphrase if _passphrase is not None else getpass.getpass("Passphrase: ")
    ok = crypto_verify(passphrase)
    print("ok" if ok else "fail")
    return ok


def crypto_change(old: str, new: str, *, force: bool = False) -> dict:
    """Testable core of `crypto change` (no prompting, no printing)."""
    return change_passphrase(old, new, force=force)


def cmd_crypto_change(args, _old: str | None = None, _new: str | None = None,
                      _confirm: str | None = None) -> dict:
    """`candid crypto change`: replace the keystore passphrase."""
    if not crypto_available():
        raise CryptoUnavailableError(
            "Passphrase encryption needs the optional 'cryptography' package. "
            "Install it with: pip install cryptography"
        )
    old = _old if _old is not None else getpass.getpass("Current passphrase: ")
    new = _new if _new is not None else getpass.getpass("New passphrase: ")
    score = _print_strength(new)
    force = bool(getattr(args, "force", False))
    if score < 2 and not force:
        raise CryptoError("new passphrase too weak; re-run with --force to use it anyway")
    confirm = _confirm if _confirm is not None else getpass.getpass("Confirm new passphrase: ")
    if not hmac.compare_digest(new.encode("utf-8"), confirm.encode("utf-8")):
        raise CryptoError("passphrases do not match")
    info = crypto_change(old, new, force=force)
    print("Passphrase changed.")
    return info


def register_crypto_commands(subparsers) -> None:
    """Register the `crypto` command group: init [--force], change, verify.

    `subparsers` is the argparse subparsers object for the `crypto` command;
    a later worker wires it into __main__.py.
    """
    p_init = subparsers.add_parser(
        "init",
        help="Set the encryption passphrase for the first time.",
        description="Initialize the keystore with a new passphrase. "
        "Shows a strength meter; weak passphrases (score < 2) need --force.",
        epilog="examples:\n  python -m candid crypto init",
    )
    p_init.add_argument("--force", action="store_true",
                        help="Proceed even if the passphrase is weak or a keystore exists.")
    p_init.set_defaults(func=cmd_crypto_init)

    p_change = subparsers.add_parser(
        "change",
        help="Change the encryption passphrase.",
        description="Verify the current passphrase, then set a new one.",
        epilog="examples:\n  python -m candid crypto change",
    )
    p_change.add_argument("--force", action="store_true",
                         help="Accept a weak new passphrase.")
    p_change.set_defaults(func=cmd_crypto_change)

    p_verify = subparsers.add_parser(
        "verify",
        help="Check a passphrase against the keystore.",
        description="Prompt for a passphrase and print ok/fail.",
        epilog="examples:\n  python -m candid crypto verify",
    )
    p_verify.set_defaults(func=cmd_crypto_verify)
