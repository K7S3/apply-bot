"""Privacy dashboard: per-category data retention policies.

Exposes ``add_parsers(sub)`` so ``candid privacy`` can register the
``retention`` command with its own sub-subcommands:

    python -m candid privacy retention set <category> <days>
    python -m candid privacy retention show [--json]
    python -m candid privacy retention run [--dry-run] [--yes]

Policies are stored in ``privacy_retention.json`` ({"<category>": <days>}).
days=0 disables automatic deletion for the category; unset means no policy.

Handlers return int exit codes and never call sys.exit themselves; the only
exception is P.require_category, which raises SystemExit(2) on unknown
categories (and we raise SystemExit(2) for invalid day counts).
"""

from __future__ import annotations

import json
import sys
import time
from argparse import Namespace
from pathlib import Path

from . import privacy as P

SECONDS_PER_DAY = 86400


# --- policy storage -----------------------------------------------------------

def _load_policies() -> dict[str, int]:
    path = P.RETENTION_POLICY_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    policies: dict[str, int] = {}
    for key, value in data.items():
        if key in P.CATEGORIES and isinstance(value, int):
            policies[key] = value
    return policies


def _save_policies(policies: dict[str, int]) -> None:
    path = P.RETENTION_POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(policies, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _policy_meaning(days: int | None) -> str:
    if days is None:
        return "no policy - files are kept indefinitely"
    if days == 0:
        return "auto-deletion disabled - files are kept indefinitely"
    return f"files older than {days} days are deleted by `retention run`"


# --- set ----------------------------------------------------------------------

def cmd_set(args: Namespace) -> int:
    P.require_category(args.category)
    days = args.days
    if days < 0:
        print(
            f"Invalid retention days {days!r}: must be a non-negative integer (0 disables).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    policies = _load_policies()
    policies[args.category] = days
    _save_policies(policies)
    if days == 0:
        print(f"Retention for {args.category!r} disabled (0 days = never auto-deleted).")
    else:
        print(
            f"Retention for {args.category!r} set: files older than {days} day(s) "
            "will be deleted by `candid privacy retention run`."
        )
    P.audit("retention.set", f"category={args.category} days={days}")
    return 0


# --- show ---------------------------------------------------------------------

def _show_rows() -> list[dict]:
    policies = _load_policies()
    rows = []
    for name in sorted(P.CATEGORIES):
        days = policies.get(name)
        rows.append(
            {
                "name": name,
                "label": P.CATEGORIES[name]["label"],
                "days": days,
                "meaning": _policy_meaning(days),
            }
        )
    return rows


def cmd_show(args: Namespace) -> int:
    rows = _show_rows()
    if args.json:
        print(json.dumps({"policies": rows}, indent=2))
        return 0
    name_w = max(len(r["name"]) for r in rows)
    print(f"{'CATEGORY':<{name_w}}  {'RETENTION':<12} MEANING")
    print("-" * (name_w + 70))
    for r in rows:
        if r["days"] is None:
            retention = "not set"
        elif r["days"] == 0:
            retention = "0 (disabled)"
        else:
            retention = f"{r['days']} days"
        print(f"{r['name']:<{name_w}}  {retention:<12} {r['meaning']}")
    print(
        "\nWhat this means:\n"
        "  <N> days   - files older than N days are deleted by `candid privacy retention run`\n"
        "  0 (disabled) - auto-deletion is disabled for the category\n"
        "  not set    - no policy; files are kept indefinitely"
    )
    return 0


# --- run ----------------------------------------------------------------------

def _old_files(category: str, days: int) -> list[Path]:
    """Files in the category older than ``days`` days (by mtime)."""
    cutoff = time.time() - days * SECONDS_PER_DAY
    old: list[Path] = []
    for f in P.category_files(category):
        try:
            if f.stat().st_mtime < cutoff:
                old.append(f)
        except OSError:
            continue
    return old


def _prune_empty_dirs(category: str) -> None:
    """Remove directories that became empty, up from each category path."""
    from . import config

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


def _print_plan(plan: dict[str, list[Path]], dry: bool) -> None:
    total = sum(len(files) for files in plan.values())
    if total == 0:
        print("[dry-run] " if dry else "", end="")
        print("No files are older than their retention policy; nothing to delete.")
        return
    prefix = "[dry-run] " if dry else ""
    verb = "would be deleted" if dry else "will be deleted"
    for category, files in plan.items():
        days = _load_policies().get(category, 0)
        print(f"{prefix}{category}: {len(files)} file(s) older than {days} days {verb}:")
        from . import config

        for f in files:
            try:
                rel = f.relative_to(config.DATA_DIR)
            except ValueError:
                rel = f
            print(f"    {rel}")


def cmd_run(args: Namespace) -> int:
    policies = _load_policies()
    active = {c: d for c, d in policies.items() if c in P.CATEGORIES and d and d > 0}
    if not active:
        print(
            "No retention policies configured. "
            "Use `candid privacy retention set <category> <days>` to add one."
        )
        return 0

    plan = {category: _old_files(category, days) for category, days in active.items()}
    total_files = sum(len(files) for files in plan.values())
    total_bytes = 0
    for files in plan.values():
        for f in files:
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass

    if args.dry_run:
        _print_plan(plan, dry=True)
        P.audit(
            "retention.run",
            f"dry_run=true categories={len(active)} would_delete={total_files}",
        )
        return 0

    if total_files == 0:
        print("Nothing to delete: no files are older than their retention policy.")
        P.audit(
            "retention.run",
            f"dry_run=false categories={len(active)} deleted=0 freed_bytes=0",
        )
        return 0

    if not args.yes:
        _print_plan(plan, dry=False)
        prompt = (
            f"Permanently delete {total_files} file(s) "
            f"({P.human_size(total_bytes)}) covered by retention policies? "
            "This cannot be undone."
        )
        if not P.confirm(prompt):
            print("Retention run cancelled; nothing was deleted.")
            return 0

    deleted = 0
    freed = 0
    per_category: dict[str, int] = {}
    for category, files in plan.items():
        n = 0
        for f in files:
            try:
                size = f.stat().st_size
                f.unlink()
            except OSError as e:
                print(f"Warning: could not delete {f}: {e}", file=sys.stderr)
                continue
            deleted += 1
            freed += size
            n += 1
        per_category[category] = n
        _prune_empty_dirs(category)

    detail = (
        f"dry_run=false categories={len(active)} deleted={deleted} "
        f"freed_bytes={freed} per_category={per_category}"
    )
    P.audit("retention.run", detail)
    print(f"Deleted {deleted} file(s), freed {P.human_size(freed)}.")
    return 0


# --- parser wiring ------------------------------------------------------------

def add_parsers(sub) -> None:
    p = sub.add_parser("retention", help="Manage per-category data retention policies.")
    nested = p.add_subparsers(
        dest="retention_cmd", required=True,
        title="subcommands", metavar="<subcommand>",
    )

    s = nested.add_parser("set", help="Set the retention policy for a category.")
    s.add_argument("category", help="Data category (see `candid privacy inventory`).")
    s.add_argument(
        "days",
        type=int,
        help="Delete files older than this many days. 0 disables auto-deletion.",
    )
    s.set_defaults(func=cmd_set)

    s = nested.add_parser("show", help="Show the current retention policies.")
    s.add_argument(
        "--json",
        action="store_true",
        help="Emit the policies as JSON (for scripting).",
    )
    s.set_defaults(func=cmd_show)

    s = nested.add_parser(
        "run",
        help="Delete files older than their retention policy.",
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list what would be deleted; delete nothing.",
    )
    s.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    s.set_defaults(func=cmd_run)
