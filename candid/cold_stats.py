"""Storage statistics for the candid data directory.

Walks ``DATA_DIR`` and reports per-category byte usage for the live
(active) data plus the cold archive (split by archive kind).  Missing
files and directories count as 0.  All sizes come from file stat.

``DATA_DIR`` is resolved at call time via ``candid.config`` so tests can
redirect it; the cold-archive root goes through ``candid.coldstore``
(lazily imported) to honor the ``CANDID_COLD_DIR`` override.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _human(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# Active (live-data) categories, in display order.
ACTIVE_CATEGORIES = (
    "tracker",
    "profile",
    "prep_packs",
    "tailored",
    "gmail_proposals",
    "salary",
    "jobs",
)


def storage_stats() -> dict:
    """Return storage usage for the data dir.

    ``by_category`` holds the active categories plus one
    ``cold_archive:<kind>`` entry per archive kind; the aggregate cold
    usage is in ``cold_bytes``.  ``total_bytes == active_bytes +
    cold_bytes`` and the ``cold_archive:<kind>`` entries sum to
    ``cold_bytes``.
    """
    from candid import config as C
    from candid import coldstore

    data = Path(C.DATA_DIR)
    by_category: dict[str, int] = {}

    by_category["tracker"] = _file_bytes(data / "tracker.json")
    by_category["profile"] = _file_bytes(data / "profile.json")
    by_category["prep_packs"] = _dir_bytes(data / "prep_packs")
    by_category["tailored"] = _dir_bytes(data / "tailored")
    by_category["gmail_proposals"] = _file_bytes(data / "gmail_proposals.json")

    salary_paths = {data / "salary.db"}
    salary_paths.update(p for p in data.glob("salary*") if p.is_file())
    by_category["salary"] = sum(_file_bytes(p) for p in salary_paths)

    by_category["jobs"] = _file_bytes(data / "jobs.json") + _file_bytes(
        data / "job_meta.json"
    )

    active_bytes = sum(by_category.values())

    # Cold archive, split by kind.
    root = coldstore.archive_root()
    cold_bytes = 0
    kind_bytes: dict[str, int] = {}
    archive_count = 0
    oldest_archive_utc: str | None = None

    for zpath in sorted(root.glob("*.zip"), key=lambda p: p.name):
        archive_count += 1
        size = _file_bytes(zpath)
        cold_bytes += size
        kind = "unknown"
        created = None
        try:
            with zipfile.ZipFile(zpath) as zf:
                manifest = json.loads(
                    zf.read(coldstore.MANIFEST_NAME).decode("utf-8")
                )
            kind = str(manifest.get("kind") or "unknown")
            created = manifest.get("created_utc")
        except Exception:
            pass
        kind_bytes[kind] = kind_bytes.get(kind, 0) + size
        if isinstance(created, str) and (
            oldest_archive_utc is None or created < oldest_archive_utc
        ):
            oldest_archive_utc = created

    for kind_name in sorted(kind_bytes):
        by_category[f"cold_archive:{kind_name}"] = kind_bytes[kind_name]

    return {
        "active_bytes": active_bytes,
        "cold_bytes": cold_bytes,
        "total_bytes": active_bytes + cold_bytes,
        "by_category": by_category,
        "archive_count": archive_count,
        "oldest_archive_utc": oldest_archive_utc,
    }


def format_stats(stats: dict) -> str:
    """Render ``storage_stats()`` output as a human-readable summary."""
    by_category = stats.get("by_category", {})
    lines = ["candid storage:"]
    for key in ACTIVE_CATEGORIES:
        lines.append(f"  {key:15} {_human(by_category.get(key, 0))}")
    lines.append(
        f"  {'cold_archive':15} {_human(stats.get('cold_bytes', 0))}"
        f" ({stats.get('archive_count', 0)} archives)"
    )
    for key in sorted(by_category):
        if key.startswith("cold_archive:"):
            kind_name = key.split(":", 1)[1]
            lines.append(f"    - {kind_name:13} {_human(by_category[key])}")
    lines.append(f"  {'active':15} {_human(stats.get('active_bytes', 0))}")
    lines.append(f"  {'total':15} {_human(stats.get('total_bytes', 0))}")
    if stats.get("oldest_archive_utc"):
        lines.append(f"  oldest archive: {stats['oldest_archive_utc']}")
    return "\n".join(lines)
