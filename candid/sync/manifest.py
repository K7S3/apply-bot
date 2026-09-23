"""Sync bundle manifest: schema, checksum helpers, zip-slip-safe extraction.

Manifest schema (JSON, stored as ``candid-sync-manifest.json`` at the zip root)::

    {
        "format": "candid-sync/1",
        "created_at": "2026-09-22T20:30:00",   # ISO-8601, local time
        "machine_id": "m-...",
        "peer_id": "m-..." | null,            # intended recipient, if paired
        "categories": ["tracker", "prep"],
        "incremental": false,
        "base_id": null,                       # snapshot id this delta applies to
        "files": {
            "tracker.json": {"sha256": "...", "size": 1234},
            ...
        },
    }

Only stdlib is used. Bundles are integrity-checked (sha256) but not
encrypted: the user moves the file over a channel they trust.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

from candid.sync.errors import SyncError

FORMAT = "candid-sync/1"
MANIFEST_NAME = "candid-sync-manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    *,
    machine_id: str,
    files: dict[str, dict],
    categories: list[str],
    peer_id: str | None = None,
    incremental: bool = False,
    base_id: str | None = None,
) -> dict:
    return {
        "format": FORMAT,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "machine_id": machine_id,
        "peer_id": peer_id,
        "categories": sorted(categories),
        "incremental": incremental,
        "base_id": base_id,
        "files": files,
    }


def write_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True)


def read_manifest(bundle_path: Path) -> dict:
    """Read and structurally validate the manifest inside a bundle."""
    try:
        with zipfile.ZipFile(bundle_path) as zf:
            try:
                raw = zf.read(MANIFEST_NAME)
            except KeyError:
                raise SyncError(
                    f"{bundle_path.name} is not a candid sync bundle "
                    f"(missing {MANIFEST_NAME})"
                ) from None
    except zipfile.BadZipFile as exc:
        raise SyncError(f"{bundle_path.name} is not a valid zip file") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SyncError(f"{bundle_path.name} has a corrupt manifest") from exc
    if manifest.get("format") != FORMAT:
        raise SyncError(
            f"unsupported bundle format {manifest.get('format')!r}; "
            f"this candid understands {FORMAT!r}"
        )
    if not isinstance(manifest.get("files"), dict):
        raise SyncError(f"{bundle_path.name} manifest is missing its file list")
    return manifest


def verify_bundle(bundle_path: Path, manifest: dict | None = None) -> dict:
    """Check every file's sha256 against the manifest. Returns the manifest.

    Raises SyncError on any mismatch, missing file, or extra file.
    """
    manifest = manifest or read_manifest(bundle_path)
    expected = manifest["files"]
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise SyncError("bundle is missing its manifest")
        for rel, meta in expected.items():
            if rel not in names:
                raise SyncError(f"bundle is missing file {rel!r}")
            h = hashlib.sha256()
            with zf.open(rel) as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != meta.get("sha256"):
                raise SyncError(f"checksum mismatch for {rel!r}: bundle is corrupt")
        extras = names - set(expected) - {MANIFEST_NAME}
        if extras:
            raise SyncError(
                f"bundle contains unexpected files: {sorted(extras)[:5]}"
            )
    return manifest


def safe_extract(bundle_path: Path, dest: Path, manifest: dict | None = None) -> list[str]:
    """Extract bundle files (not the manifest) into dest, zip-slip guarded.

    Returns the list of extracted relative paths.
    """
    manifest = manifest or read_manifest(bundle_path)
    dest = dest.resolve()
    extracted: list[str] = []
    with zipfile.ZipFile(bundle_path) as zf:
        for rel in manifest["files"]:
            target = (dest / rel).resolve()
            if dest not in target.parents and target != dest:
                raise SyncError(f"unsafe path in bundle: {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(rel) as src, open(target, "wb") as fh:
                for chunk in iter(lambda: src.read(65536), b""):
                    fh.write(chunk)
            extracted.append(rel)
    return extracted
