"""Privacy dashboard: wipe ALL candid user data in one shot.

Exposes ``add_parsers(sub)`` so ``candid privacy`` can register the
``nuke`` subcommand.
"""

from __future__ import annotations

import sys
import zipfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import privacy as P


def _backup_archive_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return P.PRIVACY_EXPORT_DIR / f"full-backup-{stamp}.zip"


def _export_full_backup() -> Path:
    """Archive every category's files into privacy_exports/full-backup-<ts>.zip."""
    files: list[Path] = []
    seen: set[Path] = set()
    for name in P.CATEGORIES:
        for f in P.category_files(name):
            if f not in seen:
                seen.add(f)
                files.append(f)
    archive = _backup_archive_path()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            try:
                arcname = str(f.relative_to(config.DATA_DIR))
            except ValueError:
                continue
            try:
                zf.write(f, arcname)
            except OSError:
                pass
    print(f"Backed up {len(files)} file(s) to {archive}.")
    return archive


def _deletable_files() -> list[Path]:
    """Every file under DATA_DIR except the protected privacy_exports tree."""
    base = config.DATA_DIR
    if not base.exists():
        return []
    out: list[Path] = []
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        if f == P.PRIVACY_EXPORT_DIR or P.PRIVACY_EXPORT_DIR in f.parents:
            continue
        out.append(f)
    return out


def _remove_empty_dirs() -> None:
    """Remove directories emptied by the nuke, up to (not incl.) DATA_DIR."""
    base = config.DATA_DIR
    dirs = sorted(
        (d for d in base.rglob("*") if d.is_dir()),
        key=lambda d: -len(d.parts),
    )
    for d in dirs:
        if d == P.PRIVACY_EXPORT_DIR or P.PRIVACY_EXPORT_DIR in d.parents:
            continue
        try:
            d.rmdir()  # succeeds only when empty
        except OSError:
            pass


def cmd_nuke(args: Namespace) -> int:
    export_first = bool(getattr(args, "export_first", False))

    backup_name = ""
    if export_first:
        backup_name = _export_full_backup().name

    files = _deletable_files()
    if not files:
        print("Nothing to nuke: no candid user data found.")
        return 0

    nbytes = 0
    for f in files:
        try:
            nbytes += f.stat().st_size
        except OSError:
            pass

    if args.yes:
        print("!!! WARNING: --yes given, skipping confirmation. "
              "WIPING ALL CANDID USER DATA NOW. THIS CANNOT BE UNDONE. !!!")
    else:
        print(
            f"This will PERMANENTLY DELETE {len(files)} file(s) "
            f"({P.human_size(nbytes)}) of candid user data. "
            "This cannot be undone. Protected: privacy_exports."
        )
        try:
            ans = input("Type DELETE to confirm (anything else cancels): ").strip()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "DELETE":
            print("Nuke cancelled; nothing was deleted.")
            return 0

    detail = (
        f"files={len(files)} freed_bytes={nbytes} "
        f"export_first={export_first} backup={backup_name or 'none'}"
    )
    # The audit log itself lives in DATA_DIR, so it is deleted below along
    # with everything else: write the entry first, then re-append it after
    # the wipe so the nuke stays on the record.
    P.audit("nuke", detail)

    failed = 0
    for f in files:
        try:
            f.unlink()
        except OSError as e:
            failed += 1
            print(f"Warning: could not delete {f}: {e}", file=sys.stderr)
    _remove_empty_dirs()

    P.audit("nuke", detail)

    removed = len(files) - failed
    print(
        f"Nuked {removed} file(s), freed {P.human_size(nbytes)}. "
        "privacy_exports preserved."
    )
    return 0


def add_parsers(sub) -> None:
    p = sub.add_parser(
        "nuke",
        help="Permanently delete ALL candid user data (privacy exports survive).",
    )
    p.add_argument("--yes", action="store_true",
                   help="Skip all prompts (a loud warning is still printed).")
    p.add_argument("--export-first", action="store_true",
                   help="Archive everything to privacy_exports/full-backup-<timestamp>.zip before wiping.")
    p.set_defaults(func=cmd_nuke)
