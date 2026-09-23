"""Incremental (delta) sync bundles: only what changed since a base snapshot.

A delta bundle carries just the files that changed (or are new) since the
given base snapshot, plus a manifest that records deleted files under the
top-level ``"deleted"`` key. Deltas keep the file the user moves between
machines small; a full bundle (worker A's ``bundle`` module) is the
fallback when the two machines no longer share a base.

Manifest delta extras on top of ``candid.sync.manifest.build_manifest``::

    {
        ...,
        "incremental": true,
        "base_id": "last",        # the base this delta was diffed against
        "deleted": ["prep_packs/old.md"],   # relpaths removed since the base
        "files": { ... changed/new files only ... },
    }

Only stdlib is used. Deltas are integrity-checked (sha256) but not
encrypted: the user moves the file over a channel they trust.
"""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from candid import config
from candid.sync import base, categories
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id
from candid.sync.manifest import (
    MANIFEST_NAME,
    build_manifest,
    safe_extract,
    verify_bundle,
    write_manifest,
)


def _selected_categories(
    include: list[str] | None, exclude: list[str] | None
) -> list[str]:
    """Validate and normalize the include/exclude category selection."""
    selected = list(include) if include else categories.all_categories()
    for cat in selected:
        categories.resolve(cat)  # raises SyncError on unknown category
    excluded = set(exclude or ())
    for cat in excluded:
        categories.resolve(cat)
    return [cat for cat in selected if cat not in excluded]


def _rel_belongs(rel: str, selected: list[str]) -> bool:
    """Check whether a base relpath belongs to one of the selected categories."""
    for cat in selected:
        for prefix in categories.resolve(cat):
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
    return False


def _bundle_path(out: str | Path, machine_id: str) -> Path:
    """Resolve the bundle target path.

    When ``out`` is a directory (or has no ``.zip`` suffix), the bundle is
    named ``candid-sync-delta-<machine>-<timestamp>.zip`` inside it.
    """
    out_p = Path(out)
    if out_p.suffix.lower() == ".zip":
        out_p.parent.mkdir(parents=True, exist_ok=True)
        return out_p
    out_p.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return out_p / f"candid-sync-delta-{machine_id}-{stamp}.zip"


def export_delta(
    out: str | Path,
    base_id: str = "last",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    peer_id: str | None = None,
) -> Path:
    """Export an incremental bundle of changes since ``base_id``.

    Diffs the current snapshot against the stored base by sha256 and bundles
    only changed/new files. Files present in the base but missing now are
    recorded in the manifest under ``"deleted"`` (not bundled).

    Always produces a valid bundle, even when nothing changed (zero files).
    Does not touch the stored base: the base advances only when a sync
    actually lands (see :func:`apply_delta`).

    Returns the bundle path.
    """
    selected = _selected_categories(include, exclude)
    base_snapshot = base.load_base(base_id)
    current = base.snapshot_current(selected)

    changed = {
        rel: digest
        for rel, digest in current.items()
        if base_snapshot.get(rel) != digest
    }
    deleted = sorted(
        rel
        for rel in base_snapshot
        if rel not in current and _rel_belongs(rel, selected)
    )

    data = Path(config.DATA_DIR)
    files: dict[str, dict] = {}
    for rel in sorted(changed):
        p = data / rel
        files[rel] = {"sha256": changed[rel], "size": p.stat().st_size}

    manifest = build_manifest(
        machine_id=get_machine_id(),
        files=files,
        categories=selected,
        peer_id=peer_id,
        incremental=True,
        base_id=base_id,
    )
    manifest["deleted"] = deleted

    machine_id = get_machine_id()
    target = _bundle_path(out, machine_id)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, write_manifest(manifest))
        for rel in files:
            zf.write(data / rel, arcname=rel)
    return target


def _backup_deleted(relpaths: list[str]) -> Path:
    """Copy currently-present doomed files into sync/backups/<timestamp>/."""
    data = Path(config.DATA_DIR)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = data / categories.SYNC_STATE_DIRNAME / "backups" / stamp
    for rel in relpaths:
        src = data / rel
        if src.is_file():
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return backup_dir


def apply_delta(bundle_path: str | Path, base_id: str = "last") -> dict:
    """Apply a delta bundle onto this machine's data directory.

    Verifies integrity (sha256), requires the manifest to be incremental and
    to name this machine's ``base_id`` (else raises SyncError and suggests a
    full bundle), writes changed files, backs up then deletes files listed
    under ``"deleted"``, and records the post-apply state as the new base.

    Returns ``{"applied": [...], "deleted": [...]}`` with relative paths.
    """
    bundle_path = Path(bundle_path)
    manifest = verify_bundle(bundle_path)

    if manifest.get("incremental") is not True:
        raise SyncError(
            f"{bundle_path.name} is a full bundle, not a delta; "
            "use the regular bundle importer for full bundles"
        )
    bundle_base = manifest.get("base_id")
    if bundle_base != base_id:
        raise SyncError(
            f"delta bundle was built against base {bundle_base!r}, "
            f"but this machine is at base {base_id!r}; "
            "the bases no longer match, so apply a full bundle instead "
            "(or re-export a delta from the current base)"
        )

    data = Path(config.DATA_DIR)
    applied = safe_extract(bundle_path, data, manifest)

    deleted: list[str] = []
    doomed = manifest.get("deleted") or []
    if doomed:
        _backup_deleted(doomed)
        for rel in doomed:
            target = data / rel
            if target.is_file():
                target.unlink()
                deleted.append(rel)

    base.update_last(base.snapshot_current())
    return {"applied": sorted(applied), "deleted": sorted(deleted)}
