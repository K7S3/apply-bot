"""Privacy dashboard: archive (export) and permanently delete (purge) data categories.

Exposes ``add_parsers(sub)`` so ``candid privacy`` can register the
``export`` and ``purge`` subcommands.
"""

from __future__ import annotations

import sys
import time
import zipfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import privacy as P

TEXT_SUFFIXES = {".json", ".txt", ".md"}


def _export_archive_path(category: str, out: str | None) -> Path:
    if out:
        return Path(out).expanduser()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return P.PRIVACY_EXPORT_DIR / f"{category}-{stamp}.zip"


def _export_category(category: str, out: str | None = None, redact: bool = False) -> Path:
    """Archive a category's files into a zip. Returns the archive path."""
    P.require_category(category)
    files = P.category_files(category)
    if not files:
        print(f"Nothing to export: category {category!r} has no files.", file=sys.stderr)
        raise SystemExit(2)

    archive = _export_archive_path(category, out)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = str(f.relative_to(config.DATA_DIR))
            if redact and f.suffix.lower() in TEXT_SUFFIXES:
                try:
                    text = f.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    zf.write(f, arcname)
                else:
                    zf.writestr(arcname, P.redact_text(text))
            else:
                zf.write(f, arcname)

    print(str(archive))
    P.audit("export", f"category={category} files={len(files)} archive={archive.name} redact={redact}")
    return archive


def cmd_export(args: Namespace) -> int:
    _export_category(args.category, out=args.out, redact=args.redact)
    return 0


def _remove_empty_dirs(category: str) -> None:
    """Remove directories that became empty, up from each category path to DATA_DIR."""
    seen: set[Path] = set()
    for path in P.category_paths(category):
        d = path if path.is_dir() else path.parent
        while d != config.DATA_DIR and d not in seen and config.DATA_DIR in d.parents:
            seen.add(d)
            try:
                d.rmdir()  # succeeds only when empty
            except OSError:
                break
            d = d.parent


def cmd_purge(args: Namespace) -> int:
    P.require_category(args.category)
    category = args.category
    files = P.category_files(category)
    if not files:
        print(f"Nothing to purge: category {category!r} has no files.", file=sys.stderr)
        raise SystemExit(2)

    if args.export_first:
        _export_category(category)

    keep_days = args.keep_days
    if keep_days is not None:
        cutoff = time.time() - keep_days * 86400
        kept = [f for f in files if f.stat().st_mtime >= cutoff]
        files = [f for f in files if f.stat().st_mtime < cutoff]
        if not files:
            print(
                f"Nothing to purge: all files in {category!r} are newer than {keep_days} days.",
                file=sys.stderr,
            )
            raise SystemExit(2)
    else:
        kept = []

    nbytes = sum(f.stat().st_size for f in files if f.exists())
    n = len(files)

    if not args.yes:
        prompt = (
            f"Permanently delete {n} file(s) ({P.human_size(nbytes)}) "
            f"from category {category!r}? This cannot be undone."
        )
        if not P.confirm(prompt):
            print("Purge cancelled; nothing was deleted.")
            return 0

    for f in files:
        try:
            f.unlink()
        except OSError as e:
            print(f"Warning: could not delete {f}: {e}", file=sys.stderr)

    _remove_empty_dirs(category)

    P.audit(
        "purge",
        f"category={category} files={n} freed_bytes={nbytes} "
        f"kept={len(kept)} export_first={bool(args.export_first)}",
    )
    print(f"Purged {n} file(s), freed {P.human_size(nbytes)} from {category!r}.")
    return 0


def add_parsers(sub) -> None:
    p = sub.add_parser("export", help="Archive a data category before deleting it.")
    p.add_argument("category")
    p.add_argument("--out")
    p.add_argument("--redact", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("purge", help="Permanently delete all files in a data category.")
    p.add_argument("category")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--export-first", action="store_true")
    p.add_argument("--keep-days", type=int, default=None)
    p.set_defaults(func=cmd_purge)
