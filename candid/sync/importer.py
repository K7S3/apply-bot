"""Import sync bundles: dry-run preview, replace import, merge, verification.

Owned by batch-74 worker B. New file only; the stable modules this imports
(machine, categories, manifest, errors, base) are not modified.

Public entry points, intended to be wired to the CLI by the coordinator::

    candid sync verify FILE                  -> verify_bundle_file
    candid sync import FILE [--dry-run] [--mode replace|merge]
                                              -> preview_import / import_bundle
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from candid import config
from candid.sync import manifest
from candid.sync.base import snapshot_current, update_last
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id
from candid.sync.manifest import sha256_file

BACKUP_DIRNAME = "backups"


def _check_peer(m: dict) -> None:
    """Refuse a bundle that is addressed to a different machine."""
    peer_id = m.get("peer_id")
    if peer_id and peer_id != get_machine_id():
        raise SyncError(
            f"bundle is addressed to another machine ({peer_id!r}); "
            "refusing to import"
        )


def preview_import(bundle_path: str | Path) -> dict:
    """Dry-run import: verify the bundle, compare each file to the local copy.

    Performs no writes whatsoever. Returns::

        {
            "machine_id": ...,
            "created_at": ...,
            "categories": [...],
            "files": [{"path": ..., "status": "new|changed|unchanged"}],
        }
    """
    m = manifest.verify_bundle(Path(bundle_path))
    data = Path(config.DATA_DIR)
    files: list[dict] = []
    for rel in sorted(m["files"]):
        local = data / rel
        if not local.exists():
            status = "new"
        elif local.is_file() and sha256_file(local) == m["files"][rel].get("sha256"):
            status = "unchanged"
        else:
            status = "changed"
        files.append({"path": rel, "status": status})
    return {
        "machine_id": m.get("machine_id"),
        "created_at": m.get("created_at"),
        "categories": m.get("categories", []),
        "files": files,
    }


def verify_bundle_file(bundle_path: str | Path) -> dict:
    """Verify a bundle file: read the manifest, checksum every file in it.

    Returns ``{"ok": True, "files": n, "machine_id": ...}`` or raises
    SyncError on any structural problem, checksum mismatch, or extra file.
    """
    m = manifest.verify_bundle(Path(bundle_path))
    return {"ok": True, "files": len(m["files"]), "machine_id": m.get("machine_id")}


def _backup_overwritten(data: Path, rels: list[str]) -> list[str]:
    """Copy local files that the import will overwrite into a backup dir.

    Returns the list of backed-up relative paths.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = data / "sync" / BACKUP_DIRNAME / stamp
    backed_up: list[str] = []
    for rel in rels:
        local = data / rel
        if local.is_file():
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, dest)
            backed_up.append(rel)
    return backed_up


def _import_replace(bundle: Path, m: dict) -> dict:
    """Apply a bundle by overwriting local files (backing them up first)."""
    with tempfile.TemporaryDirectory(prefix="candid-sync-import-") as tmp:
        tmpdir = Path(tmp)
        extracted = manifest.safe_extract(bundle, tmpdir, m)
        data = Path(config.DATA_DIR)
        backed_up = _backup_overwritten(data, extracted)
        applied: list[str] = []
        for rel in extracted:
            dst = data / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmpdir / rel), str(dst))
            applied.append(rel)
    update_last(snapshot_current())
    return {
        "applied": sorted(applied),
        "backed_up": sorted(backed_up),
        "mode": "replace",
    }


def _import_merge(bundle: Path) -> dict:
    """Apply a bundle through the three-way merge engine (worker C)."""
    try:
        from candid.sync import merge  # lazy: only needed for merge mode
    except ImportError:
        raise SyncError("merge engine not available in this build") from None
    result = merge.merge_bundle(bundle)
    update_last(snapshot_current())
    return result


def import_bundle(bundle_path: str | Path, mode: str = "replace") -> dict:
    """Import a verified sync bundle into DATA_DIR.

    mode="replace": overwrite local files with the bundle contents,
    backing up anything overwritten into
    DATA_DIR/sync/backups/<timestamp>/. mode="merge": delegate to the
    merge engine. Returns {"applied", "backed_up", "mode"} for replace,
    or the merge engine's result dict for merge.
    """
    if mode not in ("replace", "merge"):
        raise SyncError(
            f"unknown import mode {mode!r}; want 'replace' or 'merge'"
        )
    bundle = Path(bundle_path)
    m = manifest.verify_bundle(bundle)
    _check_peer(m)
    if mode == "merge":
        return _import_merge(bundle)
    return _import_replace(bundle, m)
