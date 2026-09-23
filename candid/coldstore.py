"""Cold archival core engine for candid.

Every archive is a single self-contained .zip stored under
``DATA_DIR / "cold_archive"``.  A zip named
``<utc-timestamp>-<kind>-<slug>.zip`` holds a ``manifest.json`` plus the
archived member files (and an optional ``payload.json``).

All paths are resolved dynamically at call time from
``candid.config.DATA_DIR`` so tests can monkeypatch it.  An optional
``CANDID_COLD_DIR`` env var overrides the archive root entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import candid
from candid import config as C

MANIFEST_NAME = "manifest.json"
PAYLOAD_NAME = "payload.json"

# member names that are reserved for archive internals
_RESERVED_NAMES = {MANIFEST_NAME}


class ColdArchiveError(Exception):
    """Raised for any cold-archive operation failure."""


def archive_root() -> Path:
    """Return (creating if needed) the cold-archive root directory."""
    override = os.environ.get("CANDID_COLD_DIR")
    if override:
        root = Path(override).expanduser()
    else:
        root = Path(C.DATA_DIR) / "cold_archive"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clamp_compression(level: int) -> int:
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 6
    return max(0, min(9, level))


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return (slug or "archive")[:48]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_path(archive_id: str) -> Path:
    path = archive_root() / f"{archive_id}.zip"
    if not path.is_file():
        raise ColdArchiveError(f"archive not found: {archive_id}")
    return path


def _validate_member_name(name: str) -> str:
    """Zip-slip guard: reject absolute paths and any ``..`` traversal."""
    if not isinstance(name, str) or not name:
        raise ColdArchiveError(f"invalid member name: {name!r}")
    if os.path.isabs(name) or name.startswith("\\\\"):
        raise ColdArchiveError(f"refusing absolute member name: {name!r}")
    parts = name.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise ColdArchiveError(f"refusing member name with '..': {name!r}")
    if name in _RESERVED_NAMES:
        raise ColdArchiveError(f"member name is reserved: {name!r}")
    return name


def create_archive(
    kind: str,
    label: str,
    members: dict[str, bytes] | None = None,
    payload: dict | None = None,
    compression: int = 6,
) -> dict:
    """Create a new cold archive zip and return its manifest dict.

    ``archive_id`` is the zip stem.  ``payload`` (when given) is stored as
    ``payload.json``.  Member names are zip-slip validated.
    """
    level = _clamp_compression(compression)
    members = dict(members or {})

    files: dict[str, bytes] = {}
    for name, data in members.items():
        safe = _validate_member_name(name)
        if not isinstance(data, (bytes, bytearray)):
            raise ColdArchiveError(f"member {name!r} must be bytes")
        files[safe] = bytes(data)

    if payload is not None:
        files[PAYLOAD_NAME] = json.dumps(
            payload, indent=2, sort_keys=True
        ).encode("utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%f")
    stem = f"{timestamp}-{kind}-{_slugify(label)}"
    root = archive_root()
    archive_id = stem
    counter = 1
    while (root / f"{archive_id}.zip").exists():
        counter += 1
        archive_id = f"{stem}-{counter}"

    manifest = {
        "archive_id": archive_id,
        "kind": kind,
        "label": label,
        "created_utc": _utc_now_iso(),
        "candid_version": candid.__version__,
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
        "compression": level,
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    zip_path = root / f"{archive_id}.zip"
    try:
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level
        ) as zf:
            zf.writestr(MANIFEST_NAME, manifest_bytes)
            for name, data in files.items():
                zf.writestr(name, data)
    except Exception as exc:
        if zip_path.exists():
            zip_path.unlink()
        raise ColdArchiveError(f"failed to create archive: {exc}") from exc

    return manifest


def _read_manifest_from_zip(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError as exc:
        raise ColdArchiveError("missing manifest.json") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ColdArchiveError("manifest.json is not valid JSON") from exc


def list_archives(kind: str | None = None) -> list[dict]:
    """List archive manifests, newest first. Corrupt zips are skipped."""
    root = archive_root()
    zips = sorted(root.glob("*.zip"), key=lambda p: p.name, reverse=True)
    out: list[dict] = []
    for path in zips:
        try:
            with zipfile.ZipFile(path) as zf:
                manifest = _read_manifest_from_zip(zf)
        except Exception as exc:  # corrupt / unreadable: skip gracefully
            print(f"coldstore: skipping corrupt archive {path.name}: {exc}",
                  file=sys.stderr)
            continue
        if kind is not None and manifest.get("kind") != kind:
            continue
        out.append(manifest)
    return out


def read_archive(archive_id: str) -> dict:
    """Return manifest fields plus parsed payload and member name list."""
    path = _zip_path(archive_id)
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = _read_manifest_from_zip(zf)
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise ColdArchiveError(f"archive {archive_id} is corrupt: {exc}") from exc

    payload = None
    if PAYLOAD_NAME in names:
        with zipfile.ZipFile(path) as zf:
            payload = json.loads(zf.read(PAYLOAD_NAME).decode("utf-8"))

    members = [n for n in names if n not in (MANIFEST_NAME, PAYLOAD_NAME)]
    return {
        **manifest,
        "payload": payload,
        "members": members,
        "path": str(path),
    }


def extract_member(archive_id: str, member_name: str) -> bytes:
    """Return the raw bytes of a member. Zip-slip safe."""
    safe = _validate_member_name(member_name)
    path = _zip_path(archive_id)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if safe not in names:
                raise ColdArchiveError(
                    f"member {member_name!r} not in archive {archive_id}"
                )
            return zf.read(safe)
    except zipfile.BadZipFile as exc:
        raise ColdArchiveError(f"archive {archive_id} is corrupt: {exc}") from exc


def archive_size(archive_id: str) -> int:
    """Size in bytes of the archive zip file."""
    return _zip_path(archive_id).stat().st_size


def delete_archive(archive_id: str) -> bool:
    """Delete the archive zip. Returns True if it existed."""
    path = archive_root() / f"{archive_id}.zip"
    if not path.is_file():
        return False
    path.unlink()
    return True
