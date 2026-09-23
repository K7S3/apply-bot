"""Three-way merge engine for sync bundles.

Takes a verified bundle, a base snapshot (see candid.sync.base), and the
current local state, classifies every bundled file with classify_file,
applies the clean cases, and tries a record-level merge for tracker-style
JSON before recording anything ambiguous as a pending conflict (see
candid.sync.conflicts).

Strategy "auto" means: apply everything that merges without ambiguity and
stash the rest as pending conflicts. After a merge with zero conflicts the
"last" base snapshot is refreshed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from candid import config
from candid.sync import base as base_mod
from candid.sync import manifest as manifest_mod
from candid.sync.conflicts import (
    append_conflicts,
    parse_records,
    stash_remote,
    write_records,
)
from candid.sync.errors import SyncError

UNCHANGED = "unchanged"
LOCAL_ONLY = "local-only"
REMOTE_ONLY = "remote-only"
BOTH_SAME = "both-same"
CONFLICT = "conflict"

CLASSIFICATIONS = (UNCHANGED, LOCAL_ONLY, REMOTE_ONLY, BOTH_SAME, CONFLICT)


def classify_file(rel, base_hash, local_hash, remote_hash) -> str:
    """Classify one file's three-way state.

    rel is the bundle-relative path (kept in the signature so callers can
    classify in a loop without extra bookkeeping). A missing file counts
    as hash None.

    Returns one of "unchanged" (all three equal), "local-only"
    (remote matches base), "remote-only" (local matches base), "both-same"
    (local and remote match each other but not base), or "conflict" (all
    three differ).
    """
    if base_hash == local_hash == remote_hash:
        return UNCHANGED
    if local_hash == remote_hash:
        return BOTH_SAME
    if remote_hash == base_hash:
        return LOCAL_ONLY
    if local_hash == base_hash:
        return REMOTE_ONLY
    return CONFLICT


def merge_bundle(bundle_path, base_id="last", strategy="auto") -> dict:
    """Three-way merge a bundle into the local DATA_DIR.

    Verifies the bundle, extracts it to a temp dir, snapshots local state,
    and loads the base. Each bundled file is classified: remote-only files
    are applied automatically, local-only/unchanged/both-same files are
    left alone, and conflicts go through a record-level merge attempt
    before being stashed as pending conflicts.

    Returns {"applied": [...], "conflicts": [...], "base_id": base_id,
    "new_base_id": ... or None}. Raises SyncError on a bad bundle, an
    unknown base id, or an unknown strategy.
    """
    if strategy != "auto":
        raise SyncError(f"unknown merge strategy {strategy!r}; expected 'auto'")
    bundle_path = Path(bundle_path)
    man = manifest_mod.read_manifest(bundle_path)
    manifest_mod.verify_bundle(bundle_path, man)
    base = base_mod.load_base(base_id)
    local_snap = base_mod.snapshot_current()
    data_dir = Path(config.DATA_DIR)
    bundle_name = bundle_path.name
    bundle_created_at = man.get("created_at")

    applied: list[str] = []
    new_conflicts: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="candid-merge-") as tmp:
        tmpdir = Path(tmp)
        manifest_mod.safe_extract(bundle_path, tmpdir, man)
        for rel, meta in man["files"].items():
            cls = classify_file(
                rel, base.get(rel), local_snap.get(rel), meta.get("sha256")
            )
            if cls == REMOTE_ONLY:
                _apply_remote_file(data_dir, tmpdir, rel)
                applied.append(rel)
            elif cls == CONFLICT:
                clean, file_conflicts = _handle_conflict(
                    data_dir, tmpdir, rel, base.get(rel),
                    bundle_name, bundle_created_at,
                )
                if clean:
                    applied.append(rel)
                new_conflicts.extend(file_conflicts)
            # UNCHANGED, LOCAL_ONLY, BOTH_SAME: nothing to do

    if new_conflicts:
        append_conflicts(new_conflicts)
        new_base_id = None
    else:
        new_base_id = base_mod.update_last(base_mod.snapshot_current())
    return {
        "applied": sorted(applied),
        "conflicts": new_conflicts,
        "base_id": base_id,
        "new_base_id": new_base_id,
    }


def _apply_remote_file(data_dir: Path, tmpdir: Path, rel: str) -> None:
    dest = data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tmpdir / rel, dest)


def _handle_conflict(
    data_dir: Path,
    tmpdir: Path,
    rel: str,
    base_hash: str | None,
    bundle_name: str,
    bundle_created_at: str | None,
) -> tuple[bool, list[dict]]:
    """Try a record-level merge for a file-level conflict.

    Returns (clean, conflicts). clean True means the file merged fully and
    counts as applied; otherwise the returned conflicts were stashed and
    the file keeps the merged non-conflicting records with the local
    version of each conflicting record.
    """
    local_path = data_dir / rel
    local_raw = local_path.read_bytes() if local_path.is_file() else None
    remote_raw = (tmpdir / rel).read_bytes()
    local_parsed = parse_records(local_raw) if local_raw is not None else (None, [])
    remote_parsed = parse_records(remote_raw)
    if local_parsed is not None and remote_parsed is not None:
        (lwrapper, lrecs), (_, rrecs) = local_parsed, remote_parsed
        merged, per_record = _merge_records(lrecs, rrecs)
        write_records(local_path, lwrapper, merged)
        conflicts = _record_conflicts(rel, per_record, bundle_name, bundle_created_at)
        return (not conflicts, conflicts)
    return (
        False,
        [
            _file_conflict(
                rel, base_hash, local_raw, remote_raw,
                bundle_name, bundle_created_at,
            )
        ],
    )


def _merge_records(
    local_recs: list[dict], remote_recs: list[dict]
) -> tuple[list[dict], list[tuple[str, dict | None, dict | None]]]:
    """Union-merge two record lists by id.

    Returns (merged, conflicts). merged keeps the local version of any
    record both sides changed differently; conflicts is a list of
    (record_id, local_record, remote_record) triples. Records present on
    only one side are taken from that side. Order follows the local list,
    then remote-only records in remote order.
    """
    local_by_id = {r["id"]: r for r in local_recs}
    remote_by_id = {r["id"]: r for r in remote_recs}
    merged: list[dict] = []
    conflicts: list[tuple[str, dict | None, dict | None]] = []
    order = [r["id"] for r in local_recs]
    order.extend(r["id"] for r in remote_recs if r["id"] not in local_by_id)
    for rid in order:
        lrec = local_by_id.get(rid)
        rrec = remote_by_id.get(rid)
        if lrec is not None and rrec is not None:
            merged.append(lrec)
            if lrec != rrec:
                conflicts.append((rid, lrec, rrec))
        elif lrec is not None:
            merged.append(lrec)
        else:
            merged.append(rrec)
    return merged, conflicts


def _record_conflicts(
    rel: str,
    per_record: list[tuple[str, dict | None, dict | None]],
    bundle_name: str,
    bundle_created_at: str | None,
) -> list[dict]:
    return [
        {
            "kind": "record",
            "path": rel,
            "record_id": rid,
            "local": lrec,
            "remote": rrec,
            "base": None,  # base snapshots store hashes only
            "bundle": bundle_name,
            "bundle_created_at": bundle_created_at,
        }
        for rid, lrec, rrec in per_record
    ]


def _summarize(raw: bytes | None, rel: str):
    """JSON-safe view of file bytes: parsed JSON, a hash summary, or None."""
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "path": rel,
        }


def _file_conflict(
    rel: str,
    base_hash: str | None,
    local_raw: bytes | None,
    remote_raw: bytes,
    bundle_name: str,
    bundle_created_at: str | None,
) -> dict:
    cid = f"c-{uuid.uuid4().hex[:8]}"
    return {
        "id": cid,
        "kind": "file",
        "path": rel,
        "record_id": None,
        "local": _summarize(local_raw, rel),
        "remote": _summarize(remote_raw, rel),
        "base": base_hash,
        "bundle": bundle_name,
        "bundle_created_at": bundle_created_at,
        "remote_stash": stash_remote(cid, rel, remote_raw),
    }
