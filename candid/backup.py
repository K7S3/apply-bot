"""Full JSON backups of the candid user data directory, plus restore.

Everything is stored under ``config.DATA_DIR`` (default: ``candid_data/``,
git-ignored). A backup is a zip file with every user data file plus a
``manifest.json`` describing the contents. Restoring a backup first takes
an automatic pre-restore snapshot so no data is ever lost.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from candid import __version__, config as C


class BackupError(Exception):
    """Raised for backup/restore problems (missing backup, bad name, ...)."""


BACKUP_DIR_NAME = "backups"
MANIFEST_NAME = "manifest.json"
ARCHIVE_NAME = "archive.json"

# Data files and dirs copied into every backup (when present).
_DATA_FILES = (
    "profile.json",
    "tracker.json",
    "offers.json",
    "gmail_proposals.json",
    "salary.db",
)
_DATA_DIRS = ("prep_packs", "tailored")


def _resolve_data_dir(data_dir: Path | None) -> Path:
    return Path(data_dir) if data_dir is not None else C.DATA_DIR


def _backup_dir(data_dir: Path) -> Path:
    d = data_dir / BACKUP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_name(name: str) -> str:
    """Keep backup names safe for use as a file name."""
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    if not clean:
        raise BackupError(
            "Backup name cannot be blank or made only of special characters."
        )
    return clean


def _manifest(files: list[str]) -> dict:
    return {
        "candid_version": __version__,
        "created": datetime.now().isoformat(timespec="seconds"),
        "files": files,
    }


def create_backup(name: str | None = None, *, data_dir: Path | None = None) -> Path:
    """Create a zip backup of the whole data directory.

    Returns the path of the created zip. Files that don't exist yet are
    skipped silently (a fresh user may have no profile or tracker yet).
    """
    C.ensure_data_dirs()
    root = _resolve_data_dir(data_dir)
    bdir = _backup_dir(root)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_name = _sanitize_name(name) if name else f"candid-backup-{ts}"
    zip_path = bdir / f"{zip_name}.zip"

    members: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in _DATA_FILES:
            src = root / fname
            if src.is_file():
                zf.write(src, fname)
                members.append(fname)
        for dname in _DATA_DIRS:
            src = root / dname
            if src.is_dir():
                for child in sorted(src.rglob("*")):
                    if child.is_file():
                        arc = f"{dname}/{child.relative_to(src).as_posix()}"
                        zf.write(child, arc)
                        members.append(arc)
        zf.writestr(MANIFEST_NAME, json.dumps(_manifest(members), indent=2))
    return zip_path


def _read_manifest(zip_path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(MANIFEST_NAME) as fh:
                return json.load(fh)
    except (KeyError, zipfile.BadZipFile, ValueError, OSError):
        return None


def list_backups(*, data_dir: Path | None = None) -> list[dict]:
    """List backups newest-first: {name, path, created, size_bytes}."""
    root = _resolve_data_dir(data_dir)
    bdir = root / BACKUP_DIR_NAME
    if not bdir.is_dir():
        return []
    found: list[dict] = []
    for zip_path in sorted(bdir.glob("*.zip")):
        manifest = _read_manifest(zip_path)
        created = (manifest or {}).get("created")
        if not created:
            created = datetime.fromtimestamp(
                zip_path.stat().st_mtime
            ).isoformat(timespec="seconds")
        found.append(
            {
                "name": zip_path.stem,
                "path": str(zip_path),
                "created": created,
                "size_bytes": zip_path.stat().st_size,
                "_sort": (created, zip_path.stat().st_mtime_ns),
            }
        )
    found.sort(key=lambda b: b["_sort"], reverse=True)
    for b in found:
        del b["_sort"]
    return found


def _find_backup(name: str, data_dir: Path) -> Path:
    clean = _sanitize_name(name)
    zip_path = _backup_dir(data_dir) / f"{clean}.zip"
    if not zip_path.is_file():
        known = [b["name"] for b in list_backups(data_dir=data_dir)]
        hint = f" Known backups: {', '.join(known)}." if known else " No backups exist yet."
        raise BackupError(
            f"Unknown backup '{name}'.{hint}"
        )
    return zip_path


def _safe_target(member: str, root: Path) -> Path:
    """Resolve a zip member inside root; blocks zip-slip entries."""
    target = (root / member).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise BackupError(
            f"Backup contains an entry outside the data directory: {member}"
        )
    return target


def restore_backup(
    name: str, *, data_dir: Path | None = None, force: bool = False
) -> dict:
    """Restore a backup over the data directory.

    First takes an automatic ``pre-restore-<ts>`` snapshot of the current
    state via :func:`create_backup`, so nothing is lost. Returns
    ``{restored, snapshot}``.
    """
    C.ensure_data_dirs()
    root = _resolve_data_dir(data_dir)
    zip_path = _find_backup(name, root)

    manifest = _read_manifest(zip_path)
    if manifest and manifest.get("candid_version") != __version__ and not force:
        raise BackupError(
            f"Backup '{name}' was made by candid {manifest.get('candid_version', '?')}, "
            f"but this is candid {__version__}. Restore with --force to proceed anyway."
        )

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot = create_backup(f"pre-restore-{ts}", data_dir=root)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.filename == MANIFEST_NAME:
                    continue
                target = _safe_target(info.filename, root)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    dst.write(src.read())
    except BackupError:
        raise
    except zipfile.BadZipFile:
        raise BackupError(
            f"Backup '{name}' is corrupted and could not be read."
        ) from None
    return {"restored": zip_path.stem, "snapshot": str(snapshot)}


def render_backups(backups: list[dict]) -> str:
    """One-line-per-backup human-readable listing."""
    if not backups:
        return "No backups yet. Next: run `python -m candid backup create`"
    lines = []
    for b in backups:
        kb = b["size_bytes"] / 1024
        lines.append(f"{b['name']}  ({b['created']}, {kb:.1f} KB)")
    return "\n".join(lines)
