"""Portable export / import of candid cold archives.

An exported archive is a byte-identical copy of the archive zip, renamed
with a ``.candid-cold`` extension so it is recognizable as a portable
candid cold archive.  Import validates the file with the same verifier
used for installed archives (on a temp copy, so the source is never
touched) and then installs it into the cold archive directory.

``candid.coldstore`` / ``candid.cold_verify`` are imported lazily inside
functions; ``DATA_DIR`` is resolved at call time via ``candid.config``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

EXPORT_SUFFIX = ".candid-cold"


def _coldstore():
    from candid import coldstore

    return coldstore


def _cold_verify():
    from candid import cold_verify

    return cold_verify


def export_archive(archive_id: str, dest: str | Path) -> Path:
    """Copy archive ``archive_id`` to ``dest`` as a ``.candid-cold`` file.

    ``dest`` may be a directory (the file is placed inside it as
    ``<archive_id>.candid-cold``) or a file path (the ``.candid-cold``
    extension is enforced).  The original archive stays in place.
    Returns the destination path.
    """
    cs = _coldstore()
    src = cs.archive_root() / f"{archive_id}.zip"
    if not src.is_file():
        raise cs.ColdArchiveError(f"archive not found: {archive_id}")

    dest = Path(dest)
    if dest.is_dir():
        dest = dest / f"{archive_id}{EXPORT_SUFFIX}"
    elif dest.suffix == ".zip":
        dest = dest.with_suffix(EXPORT_SUFFIX)
    elif dest.suffix != EXPORT_SUFFIX:
        dest = dest.with_name(dest.name + EXPORT_SUFFIX)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _rewrite_manifest_id(src_zip: Path, new_id: str, tmp_dir: Path) -> Path:
    """Copy ``src_zip`` while replacing manifest.json's archive_id."""
    cs = _coldstore()
    out = tmp_dir / f"{new_id}.zip"
    with zipfile.ZipFile(src_zip) as zin:
        with zipfile.ZipFile(
            out, "w", compression=zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == cs.MANIFEST_NAME:
                    manifest = json.loads(data.decode("utf-8"))
                    manifest["archive_id"] = new_id
                    data = json.dumps(
                        manifest, indent=2, sort_keys=True
                    ).encode("utf-8")
                zout.writestr(item, data)
    return out


def import_archive(path: str | Path) -> dict:
    """Validate and install a portable ``.candid-cold`` (or zip) file.

    The file is verified on a temp copy with the standard archive
    verifier; non-zip or corrupt files are rejected with
    ``ColdArchiveError``.  On an archive-id collision the installed copy
    is renamed (``<id>-2``, ``<id>-3``, ...) and its manifest is updated
    to match.  Returns the installed manifest record.
    """
    cs = _coldstore()
    cv = _cold_verify()
    src = Path(path)

    if not src.is_file():
        raise cs.ColdArchiveError(f"file not found: {src}")
    if not zipfile.is_zipfile(src):
        raise cs.ColdArchiveError(f"not a zip archive: {src}")

    with tempfile.TemporaryDirectory(prefix="candid-import-") as td:
        tmp_dir = Path(td)
        tmp_zip = tmp_dir / (src.stem + ".zip")
        shutil.copy2(src, tmp_zip)

        result = cv.verify_file(tmp_zip)
        if not result["ok"]:
            detail = "; ".join(result["errors"]) or "unknown reason"
            raise cs.ColdArchiveError(f"invalid cold archive {src}: {detail}")

        with zipfile.ZipFile(tmp_zip) as zf:
            manifest = json.loads(zf.read(cs.MANIFEST_NAME).decode("utf-8"))
        archive_id = manifest.get("archive_id") or src.stem

        root = cs.archive_root()
        target_id = archive_id
        counter = 1
        while (root / f"{target_id}.zip").exists():
            counter += 1
            target_id = f"{archive_id}-{counter}"

        install_src = tmp_zip
        if target_id != archive_id:
            manifest = dict(manifest)
            manifest["archive_id"] = target_id
            install_src = _rewrite_manifest_id(tmp_zip, target_id, tmp_dir)

        shutil.copy2(install_src, root / f"{target_id}.zip")

    return manifest
