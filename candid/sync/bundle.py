"""Export sync bundles: zipped snapshots of selected sync categories.

A bundle is a zip file containing every file from the selected categories
(relative paths under ``config.DATA_DIR``) plus a
``candid-sync-manifest.json`` with per-file sha256 checksums, the source
machine id, and the intended peer. Missing category paths are skipped
silently; unknown category names raise :class:`SyncError`.

After a successful export, the exported snapshot is stored as the ``last``
base so later merges and deltas have a reference point.

Only stdlib is used.
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from candid import config
from candid.sync import base, categories, manifest
from candid.sync.errors import SyncError
from candid.sync.machine import get_machine_id


def resolve_selection(
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> list[str]:
    """Resolve include/exclude lists into a sorted list of category names.

    Each name is validated with :func:`categories.resolve`; unknown names
    raise :class:`SyncError`. ``include=None`` (or empty) means all
    categories; excludes always win over includes.
    """
    if include:
        selected = list(include)
        # Validate every name up front so a typo fails fast.
        for name in selected:
            categories.resolve(name)
    else:
        selected = categories.all_categories()
    excluded: set[str] = set()
    if exclude:
        for name in exclude:
            categories.resolve(name)
            excluded.add(name)
    return sorted(c for c in set(selected) if c not in excluded)


def _iter_category_files(selected: list[str]) -> list[tuple[str, Path]]:
    """Collect ``(relative_posix_path, absolute_path)`` for selected files.

    Missing paths are skipped silently. Directories are walked recursively.
    """
    data = Path(config.DATA_DIR)
    found: list[tuple[str, Path]] = []
    for cat in selected:
        for rel in categories.resolve(cat):
            p = data / rel
            if p.is_file():
                found.append((rel, p))
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        found.append((f.relative_to(data).as_posix(), f))
            # Anything else (missing path, odd type) is skipped silently.
    # De-dup by relative path; later categories win on overlap.
    deduped: dict[str, Path] = {}
    for rel, p in found:
        deduped[rel] = p
    return sorted(deduped.items())


def summarize_selection(
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> dict:
    """Dry-run style preview of an export selection.

    Returns ``{"categories", "file_count", "total_bytes"}``. Unknown
    category names raise :class:`SyncError`.
    """
    selected = resolve_selection(include, exclude)
    files = _iter_category_files(selected)
    total_bytes = sum(p.stat().st_size for _, p in files)
    return {
        "categories": selected,
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def _bundle_name() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"candid-sync-{get_machine_id()}-{stamp}.zip"


def export_bundle(
    out,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    peer_id: str | None = None,
    categories_selected: Iterable[str] | None = None,
) -> Path:
    """Export a sync bundle zip and return its path.

    ``out`` may be a file path or an existing directory; for a directory the
    bundle is named ``candid-sync-<machine_id>-<yyyymmdd-HHMMSS>.zip``.

    ``categories_selected`` is an already-resolved category list that
    bypasses include/exclude handling (the CLI passes include/exclude;
    other workers may pass an explicit selection).
    """
    if categories_selected is not None:
        selected = sorted(set(categories_selected))
        for name in selected:
            categories.resolve(name)  # validate, raises SyncError if unknown
    else:
        selected = resolve_selection(include, exclude)

    files = _iter_category_files(selected)
    entries = {
        rel: {"sha256": manifest.sha256_file(p), "size": p.stat().st_size}
        for rel, p in files
    }
    man = manifest.build_manifest(
        machine_id=get_machine_id(),
        files=entries,
        categories=selected,
        peer_id=peer_id,
    )

    out_path = Path(out)
    if out_path.is_dir():
        out_path = out_path / _bundle_name()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            out_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            zf.writestr(manifest.MANIFEST_NAME, manifest.write_manifest(man))
            for rel, p in files:
                zf.write(p, arcname=rel)
    except OSError as exc:
        raise SyncError(f"could not write bundle to {out_path}: {exc}") from exc

    # Record this export as the "last" base for future merges/deltas.
    base.update_last({rel: entries[rel]["sha256"] for rel, _ in files})
    return out_path
