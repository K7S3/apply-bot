"""Integrity verification for candid cold archives.

Recomputes the sha256 of every member inside an archive zip and compares it
against the checksums recorded in ``manifest.json``, runs the zip's own
CRC integrity check, and validates the manifest's required fields.

``candid.coldstore`` is imported lazily inside functions so this module can
be imported even while the archive engine is still being assembled, and
``DATA_DIR`` is always resolved at call time via ``candid.config``.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

REQUIRED_MANIFEST_FIELDS = ("archive_id", "kind", "label", "created_utc", "files")


def _coldstore():
    from candid import coldstore

    return coldstore


def verify_file(path: str | Path) -> dict:
    """Verify a cold-archive zip at an explicit filesystem path.

    Returns ``{"ok": bool, "errors": [str], "checked": n}`` where ``n`` is
    the number of member checksums compared against the manifest.
    """
    cs = _coldstore()
    errors: list[str] = []
    checked = 0
    path = Path(path)

    if not path.is_file():
        return {"ok": False, "errors": [f"archive file not found: {path}"], "checked": 0}

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        return {"ok": False, "errors": [f"not a valid zip file: {exc}"], "checked": 0}

    with zf:
        try:
            bad_member = zf.testzip()
        except Exception as exc:  # truncated / unreadable zip data
            errors.append(f"zip integrity check failed: {exc}")
            bad_member = None
        if bad_member:
            errors.append(f"corrupt member in zip (CRC failure): {bad_member}")

        names = set(zf.namelist())
        manifest: dict | None = None

        if cs.MANIFEST_NAME not in names:
            errors.append("missing manifest.json")
        else:
            try:
                raw = zf.read(cs.MANIFEST_NAME).decode("utf-8")
            except Exception as exc:
                errors.append(f"could not read manifest.json: {exc}")
            else:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    errors.append(f"manifest.json is not valid JSON: {exc}")
                else:
                    manifest = parsed if isinstance(parsed, dict) else None
                    if manifest is None:
                        errors.append("manifest.json is not a JSON object")

        if manifest is not None:
            for field in REQUIRED_MANIFEST_FIELDS:
                if field not in manifest:
                    errors.append(f"manifest missing required field: {field!r}")
            files = manifest.get("files")
            if not isinstance(files, dict):
                errors.append("manifest 'files' must be a mapping of member -> sha256")
                files = {}

            for name, expected in files.items():
                checked += 1
                if name not in names:
                    errors.append(f"manifest member missing from zip: {name}")
                    continue
                try:
                    data = zf.read(name)
                except Exception as exc:
                    errors.append(f"could not read member {name!r}: {exc}")
                    continue
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected:
                    errors.append(f"checksum mismatch for member {name!r}")

            for name in names:
                if name == cs.MANIFEST_NAME:
                    continue
                if name not in files:
                    errors.append(f"zip contains member not listed in manifest: {name!r}")

    return {"ok": not errors, "errors": errors, "checked": checked}


def verify_archive(archive_id: str) -> dict:
    """Verify the installed archive ``archive_id``.

    Returns ``{"ok": bool, "errors": [str], "checked": n}``.
    A missing archive id is reported as a failed verification, not raised.
    """
    cs = _coldstore()
    path = cs.archive_root() / f"{archive_id}.zip"
    return verify_file(path)


def verify_all(kind: str | None = None) -> dict:
    """Verify every installed archive, optionally filtered by ``kind``.

    Returns ``{"total": int, "ok": int, "failed": [archive_id, ...]}``.
    Archives whose manifest cannot be read are counted as failed (they are
    exactly the ones ``list_archives`` would silently skip).
    """
    cs = _coldstore()
    root = cs.archive_root()
    total = 0
    ok = 0
    failed: list[str] = []

    for path in sorted(root.glob("*.zip"), key=lambda p: p.name):
        if kind is not None:
            try:
                with zipfile.ZipFile(path) as zf:
                    manifest = json.loads(zf.read(cs.MANIFEST_NAME).decode("utf-8"))
                if manifest.get("kind") != kind:
                    continue
            except Exception:
                pass  # unreadable manifest: falls through to a failed verify
        total += 1
        result = verify_file(path)
        if result["ok"]:
            ok += 1
        else:
            failed.append(path.stem)

    return {"total": total, "ok": ok, "failed": failed}
