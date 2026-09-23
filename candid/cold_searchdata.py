"""Compress stale search/curation data and search inside cold archives.

This module works on top of :mod:`candid.coldstore` (the cold-archive core
engine).  ``coldstore`` is imported lazily inside each public function so
module import order never matters.

Expected ``coldstore`` API surface (as of candid 0.2.0):

- ``create_archive(kind, label, members: dict[str, bytes], payload: dict | None,
  compression=6) -> dict`` — manifest dict containing ``archive_id`` and
  ``files`` (member name -> sha256).
- ``list_archives(kind=None) -> list[dict]`` — manifests, newest first.
- ``read_archive(archive_id) -> dict`` — manifest fields plus ``payload``,
  ``members`` (name list) and ``path``.
- ``extract_member(archive_id, member_name) -> bytes`` — zip-slip safe.
- ``archive_size(archive_id) -> int``
- ``ColdArchiveError`` — raised on any archive failure.

Data kinds handled here (all resolved under ``candid.config.DATA_DIR`` at
call time, so tests can monkeypatch it):

- ``jobs`` — ``DATA_DIR/jobs.json`` (curated job-discovery output).
- ``prep_packs`` — ``DATA_DIR/prep_packs/``; staleness is judged per
  top-level directory by the newest file inside it (loose files in the
  directory root are judged individually).
- ``salary_cache`` — ``DATA_DIR/salary_cache.json`` and/or
  ``DATA_DIR/salary_cache/``.  The live ``salary.db`` is never touched.

Files named ``tracker.json``, ``profile.json`` or ``offers.json`` are never
compressed, no matter what.  A file is only eligible when its mtime is older
than ``days``; anything fresher is left alone.  Originals are deleted only
after the archive zip is written *and* verified readable (manifest hashes
re-checked against the original bytes).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C

#: Archive kind used for every archive this module creates.
ARCHIVE_KIND = "searchdata"

#: Live files that must never be compressed under any circumstance.
_PROTECTED_NAMES = frozenset({"tracker.json", "profile.json", "offers.json"})

#: JSON object fields indexed into the archive payload so
#: :func:`search_archives` can find them without opening member payloads.
_INDEX_FIELDS = frozenset(
    {"company", "role", "status", "title", "name", "position", "employer"}
)
_INDEX_CAP = 50  # max indexed values per member

_KNOWN_KINDS = ("jobs", "prep_packs", "salary_cache")


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------

def _is_stale(path: Path, cutoff: float) -> bool:
    """True when ``path`` exists and its mtime is older than ``cutoff``."""
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _newest_mtime(root: Path) -> float | None:
    """Newest mtime of any file under ``root`` (recursive), or None."""
    newest: float | None = None
    try:
        entries = root.rglob("*")
    except OSError:
        return None
    for entry in entries:
        try:
            if entry.is_file():
                mtime = entry.stat().st_mtime
                if newest is None or mtime > newest:
                    newest = mtime
        except OSError:
            continue
    return newest


def _collect_jobs(data_dir: Path, cutoff: float) -> list[tuple[str, Path]]:
    """Stale ``jobs.json`` as ``(member_name, source_path)``."""
    candidate = data_dir / "jobs.json"
    if candidate.is_file() and _is_stale(candidate, cutoff):
        return [("jobs/jobs.json", candidate)]
    return []


def _collect_prep_packs(data_dir: Path, cutoff: float) -> list[tuple[str, Path]]:
    """Stale prep packs: per-directory by newest file inside.

    Loose files directly under ``prep_packs/`` are judged individually.
    """
    packs_dir = data_dir / "prep_packs"
    out: list[tuple[str, Path]] = []
    if not packs_dir.is_dir():
        return out
    try:
        entries = sorted(packs_dir.iterdir())
    except OSError:
        return out
    for entry in entries:
        try:
            if entry.is_dir():
                newest = _newest_mtime(entry)
                if newest is None or newest >= cutoff:
                    continue
                for src in sorted(entry.rglob("*")):
                    try:
                        if src.is_file():
                            rel = src.relative_to(entry).as_posix()
                            out.append((f"prep_packs/{entry.name}/{rel}", src))
                    except OSError:
                        continue
            elif entry.is_file() and _is_stale(entry, cutoff):
                out.append((f"prep_packs/{entry.name}", entry))
        except OSError:
            continue
    return out


def _collect_salary_cache(data_dir: Path, cutoff: float) -> list[tuple[str, Path]]:
    """Stale salary cache file/dir.  The live ``salary.db`` is never touched."""
    out: list[tuple[str, Path]] = []
    cache_file = data_dir / "salary_cache.json"
    if cache_file.is_file() and _is_stale(cache_file, cutoff):
        out.append(("salary_cache/salary_cache.json", cache_file))
    cache_dir = data_dir / "salary_cache"
    if cache_dir.is_dir():
        newest = _newest_mtime(cache_dir)
        if newest is not None and newest < cutoff:
            for src in sorted(cache_dir.rglob("*")):
                try:
                    if src.is_file():
                        rel = src.relative_to(cache_dir).as_posix()
                        out.append((f"salary_cache/{rel}", src))
                except OSError:
                    continue
    return out


_COLLECTORS = {
    "jobs": _collect_jobs,
    "prep_packs": _collect_prep_packs,
    "salary_cache": _collect_salary_cache,
}


def _index_member(member_name: str, data: bytes) -> list[str]:
    """Extract a bounded content index from a JSON member for fast search.

    Collects ``field:value`` hints for known fields (company, role, status,
    ...) so :func:`search_archives` can match payload content from the
    archive's ``payload.json`` without opening the member bytes.
    """
    if not member_name.endswith(".json"):
        return []
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return []
    found: list[str] = []

    def walk(node: object, depth: int = 0) -> None:
        if len(found) >= _INDEX_CAP or depth > 4:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    isinstance(value, str)
                    and key.lower() in _INDEX_FIELDS
                    and value.strip()
                ):
                    found.append(f"{key}:{value.strip()[:120]}")
                else:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(obj)
    return found


def _cleanup_empty_dirs(data_dir: Path, removed: list[Path]) -> None:
    """Remove directories left empty after archiving (never DATA_DIR itself)."""
    data_resolved = data_dir.resolve()
    for path in removed:
        parent = path.parent
        try:
            parent_resolved = parent.resolve()
        except OSError:
            continue
        while parent_resolved != data_resolved and data_resolved in parent_resolved.parents:
            try:
                parent_resolved.rmdir()
            except OSError:
                break
            parent_resolved = parent_resolved.parent


def _verify_archive(coldstore: object, archive_id: str, raw: dict[str, bytes]) -> None:
    """Confirm the zip is written and readable; raise on any mismatch."""
    info = coldstore.read_archive(archive_id)  # type: ignore[attr-defined]
    manifest_files = info.get("files", {}) or {}
    if set(info.get("members", [])) != set(raw):
        raise ValueError(f"archive {archive_id} member list mismatch after write")
    for name, data in raw.items():
        digest = hashlib.sha256(data).hexdigest()
        if manifest_files.get(name) != digest:
            raise ValueError(f"archive {archive_id} member {name!r} failed hash check")


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def compress_stale_data(
    days: int = 30,
    kinds: tuple = ("jobs", "prep_packs", "salary_cache"),
    dry_run: bool = False,
) -> dict:
    """Archive search/curation data older than ``days`` into cold storage.

    For each requested kind, stale members are zipped into one coldstore
    archive of kind ``"searchdata"`` (members like ``jobs/jobs.json`` or
    ``prep_packs/<pack>/...``).  Originals are deleted only after the zip is
    written and verified readable.  ``tracker.json``, ``profile.json`` and
    ``offers.json`` are never compressed.  Files with mtime newer than
    ``days`` are skipped.

    With ``dry_run=True`` nothing is written or deleted; the return value
    describes what *would* be compressed.

    Returns ``{"archives": [ids], "bytes_saved": n, "files": n, "dry_run":
    bool}`` where ``bytes_saved`` is original bytes minus archive bytes
    (original bytes only, for a dry run).
    """
    from candid import coldstore

    unknown = [k for k in kinds if k not in _KNOWN_KINDS]
    if unknown:
        raise ValueError(f"unknown search-data kind(s): {unknown}")
    data_dir = Path(C.DATA_DIR)
    cutoff = time.time() - max(0.0, float(days)) * 86400.0
    today = datetime.now(timezone.utc).date().isoformat()

    result: dict = {"archives": [], "bytes_saved": 0, "files": 0, "dry_run": bool(dry_run)}
    for kind_name in kinds:
        members = [
            (name, src)
            for name, src in _COLLECTORS[kind_name](data_dir, cutoff)
            if Path(name).name.lower() not in _PROTECTED_NAMES
        ]
        if not members:
            continue
        original_bytes = 0
        for _, src in members:
            try:
                original_bytes += src.stat().st_size
            except OSError:
                pass
        if dry_run:
            result["files"] += len(members)
            result["bytes_saved"] += original_bytes
            continue

        raw = {name: src.read_bytes() for name, src in members}
        payload = {
            "searchdata_kind": kind_name,
            "originals": sorted(raw),
            "content_index": {
                name: _index_member(name, data) for name, data in raw.items()
            },
            "archived_utc": datetime.now(timezone.utc).isoformat(),
            "note": "stale search/curation data; restore with cold_searchdata.restore_searchdata",
        }
        manifest = coldstore.create_archive(
            ARCHIVE_KIND, f"stale-{kind_name}-{today}", members=raw, payload=payload
        )
        archive_id = manifest["archive_id"]
        _verify_archive(coldstore, archive_id, raw)

        for _, src in members:
            try:
                src.unlink(missing_ok=True)
            except OSError:
                pass
        _cleanup_empty_dirs(data_dir, [src for _, src in members])

        saved = original_bytes - coldstore.archive_size(archive_id)
        result["archives"].append(archive_id)
        result["files"] += len(members)
        result["bytes_saved"] += saved
    return result


def _deep_member_hits(
    coldstore: object, archive_id: str, member_name: str, kind: str, query: str
) -> list[str]:
    """Search one member's payload bytes for ``query``; return field hints."""
    hints: list[str] = []
    try:
        data = coldstore.extract_member(archive_id, member_name)  # type: ignore[attr-defined]
    except Exception:
        return hints
    if query in member_name.casefold():
        hints.append(f"member:{member_name}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return hints
    try:
        obj = json.loads(text)
    except Exception:
        if query in text.casefold():
            hints.append(f"member:{member_name}")
        return hints

    # JSON members: look at the informative fields.  For archived
    # application cycles these are company / role / status.
    targets = {"company", "role", "status"} if kind == "cycles" else _INDEX_FIELDS
    items = obj if isinstance(obj, list) else [obj]
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if (
                isinstance(value, str)
                and key.lower() in targets
                and query in value.casefold()
            ):
                hints.append(f"member:{key}")
    if not hints and query in text.casefold():
        hints.append(f"member:{member_name}")
    return hints


def search_archives(query: str, kinds: tuple | None = None) -> list[dict]:
    """Case-insensitive substring search over cold archives.

    Searches archive manifests (``archive_id``, ``kind``, ``label``), member
    names, and archive payloads.  Member payload bytes are only opened when
    the manifest/payload already hints at a possible match, except for kind
    ``"cycles"`` archives, whose archived application JSON members are
    always scanned (company / role / status fields) without extracting
    anything to disk.

    ``kinds`` optionally restricts the search to archive kinds, e.g.
    ``("cycles",)`` or ``("searchdata",)``.

    Returns a list of ``{"archive_id", "kind", "label", "matched"}`` dicts
    where ``matched`` holds sorted field hints like ``"label"``,
    ``"payload"``, ``"member_name"`` or ``"member:company"``.
    """
    from candid import coldstore

    q = (query or "").casefold()
    if not q:
        return []
    matches: list[dict] = []
    for manifest in coldstore.list_archives():
        kind = manifest.get("kind", "") or ""
        if kinds is not None and kind not in kinds:
            continue
        archive_id = manifest.get("archive_id", "")
        label = manifest.get("label", "") or ""
        matched: set[str] = set()
        for field, value in (("archive_id", archive_id), ("kind", kind), ("label", label)):
            if q in str(value).casefold():
                matched.add(field)
        try:
            info = coldstore.read_archive(archive_id)
        except Exception:
            continue
        member_names = info.get("members", []) or []
        if any(q in name.casefold() for name in member_names):
            matched.add("member_name")
        payload = info.get("payload")
        if isinstance(payload, dict):
            try:
                payload_text = json.dumps(payload, sort_keys=True).casefold()
            except Exception:
                payload_text = ""
            if q in payload_text:
                matched.add("payload")

        # Fast path respected: only open member payloads when the manifest
        # already hints at a match, or always for application cycles.
        if kind == "cycles" or matched:
            for name in member_names:
                for hint in _deep_member_hits(coldstore, archive_id, name, kind, q):
                    matched.add(hint)
        if matched:
            matches.append(
                {
                    "archive_id": archive_id,
                    "kind": kind,
                    "label": label,
                    "matched": sorted(matched),
                }
            )
    return matches


def restore_searchdata(
    archive_id: str, dest: Path | None = None, overwrite: bool = False
) -> Path:
    """Extract a ``searchdata`` archive back into the data dir.

    Members keep their original layout (``jobs/jobs.json``,
    ``prep_packs/<pack>/...``), so the default destination is
    ``DATA_DIR``.  Pass ``dest`` to extract elsewhere instead.

    Zip-slip safe: member names are validated by coldstore and every target
    path is additionally checked to stay inside the destination.  Existing
    files are never overwritten unless ``overwrite=True`` — conflicts raise
    ``FileExistsError`` before anything is written.

    Returns the destination root :class:`Path`.
    """
    from candid import coldstore

    info = coldstore.read_archive(archive_id)
    if info.get("kind") != ARCHIVE_KIND:
        raise ValueError(
            f"not a {ARCHIVE_KIND!r} archive: {archive_id} "
            f"(kind={info.get('kind')!r})"
        )
    root = Path(dest).expanduser() if dest is not None else Path(C.DATA_DIR)
    root.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()

    targets: list[tuple[str, Path]] = []
    for name in info.get("members", []) or []:
        target = (root_resolved / name).resolve()
        if target != root_resolved and root_resolved not in target.parents:
            raise coldstore.ColdArchiveError(
                f"refusing member {name!r}: escapes destination {root}"
            )
        targets.append((name, target))

    conflicts = [str(target) for _, target in targets if target.exists()]
    if conflicts and not overwrite:
        shown = ", ".join(conflicts[:5])
        raise FileExistsError(
            f"refusing to overwrite {len(conflicts)} existing file(s): {shown}"
        )

    for name, target in targets:
        data = coldstore.extract_member(archive_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root
