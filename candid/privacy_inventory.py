"""`candid privacy inventory` and `candid privacy show`.

Read-only window into everything candid stores about you:

    python -m candid privacy inventory          # table of every data category
    python -m candid privacy inventory --json   # machine-readable inventory
    python -m candid privacy show tracker       # first tracker record
    python -m candid privacy show tailored --index 1

Handlers return int exit codes and never call sys.exit themselves; the only
exception is P.require_category, which raises SystemExit(2) on unknown
categories.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from . import privacy as P

#: Max characters of a text file shown by `privacy show` before truncation.
SHOW_CHAR_LIMIT = 12_000


def add_parsers(sub):
    p = sub.add_parser(
        "inventory",
        help="List everything candid stores about you.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the inventory as JSON (for scripting).",
    )
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser(
        "show",
        help="Show exactly what is stored for one record.",
    )
    p.add_argument(
        "category",
        help="Data category (see `candid privacy inventory`).",
    )
    p.add_argument(
        "--index",
        type=int,
        default=0,
        help="Which record/file to show (default: 0).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the record as raw JSON instead of human-readable text.",
    )
    p.set_defaults(func=cmd_show)


# --- inventory -------------------------------------------------------------


def _print_inventory_table(rows: list[dict]) -> None:
    name_w = max(len(r["name"]) for r in rows)
    size_w = max(len(r["size"]) for r in rows)
    header = f"{'CATEGORY':<{name_w}}  {'SIZE':>{size_w}}  {'RECORDS':>7}  {'EXISTS':>6}  LABEL"
    print(header)
    print("-" * len(header))
    for r in rows:
        records = str(r["records"]) if r["records"] is not None else "n/a"
        exists = "yes" if r["exists"] else "no"
        print(
            f"{r['name']:<{name_w}}  {r['size']:>{size_w}}  "
            f"{records:>7}  {exists:>6}  {r['label']}"
        )
    total = sum(r["bytes"] for r in rows)
    print(f"\nTotal: {P.human_size(total)} across {len(rows)} categories.")


def cmd_inventory(args: argparse.Namespace) -> int:
    rows = P.iter_inventory()
    P.audit("inventory", f"categories={len(rows)}")
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_inventory_table(rows)
    return 0


# --- show ------------------------------------------------------------------


def _file_size(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_text(path):
    """File contents as text, or None when binary/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _truncate(text: str) -> str:
    if len(text) <= SHOW_CHAR_LIMIT:
        return text
    return (
        text[:SHOW_CHAR_LIMIT]
        + f"\n\n... (truncated: showing {SHOW_CHAR_LIMIT} of {len(text)} chars)"
    )


def _as_record_list(data) -> list:
    """Normalize a JSON payload to a list of records for indexed display."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("applications", "items", "entries", "records"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]  # a single object is one record
    return [data]


def _pretty_record(record) -> str:
    if isinstance(record, dict):
        lines = []
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, indent=2, default=str)
            lines.append(f"{key}: {value}")
        return "\n".join(lines)
    if isinstance(record, str):
        return record
    return json.dumps(record, indent=2, default=str)


def _show_json_record(category: str, info: dict, idx: int, as_json: bool) -> int:
    json_files = [
        p for p in P.category_paths(category) if p.suffix == ".json" and p.is_file()
    ]
    if not json_files:
        print(f"No stored data for category {category!r} yet.", file=sys.stderr)
        return 1
    path = json_files[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {path.name}: {exc}", file=sys.stderr)
        return 1
    records = _as_record_list(data)
    if idx >= len(records):
        print(
            f"Category {category!r} has {len(records)} record(s); "
            f"index {idx} is out of range.",
            file=sys.stderr,
        )
        return 1
    record = records[idx]
    if as_json:
        print(json.dumps(record, indent=2, default=str))
    else:
        print(f"{category} — record {idx} of {len(records)} ({path.name})\n")
        print(_pretty_record(record))
    return 0


def _show_file(category: str, files: list, idx: int, as_json: bool) -> int:
    if not files:
        print(f"No stored files for category {category!r} yet.", file=sys.stderr)
        return 1
    if idx >= len(files):
        print(
            f"Category {category!r} has {len(files)} file(s); "
            f"index {idx} is out of range.",
            file=sys.stderr,
        )
        return 1
    path = files[idx]
    content = _read_text(path)
    if as_json:
        meta = {
            "category": category,
            "path": str(path),
            "name": path.name,
            "size_bytes": _file_size(path),
            "is_text": content is not None,
        }
        if content is not None:
            meta["content"] = content
        print(json.dumps(meta, indent=2))
        return 0
    print(f"{category} — {len(files)} file(s):")
    for i, f in enumerate(files):
        marker = ">" if i == idx else " "
        print(f" {marker} [{i}] {f.name} ({P.human_size(_file_size(f))})")
    print(f"\n--- {path.name} ---")
    if content is None:
        print(f"(binary file, {P.human_size(_file_size(path))} — content not shown)")
    else:
        print(_truncate(content))
    return 0


def _show_db(category: str, info: dict, as_json: bool) -> int:
    paths = P.category_paths(category)
    path = paths[0] if paths else None
    exists = bool(path and path.is_file())
    meta: dict = {
        "category": category,
        "path": str(path) if path else None,
        "exists": exists,
        "size_bytes": _file_size(path) if path else 0,
    }
    if exists:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            tables = [
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            counts = {}
            for table in tables:
                try:
                    counts[table] = con.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = None
            con.close()
            meta["tables"] = counts
        except sqlite3.Error as exc:
            meta["error"] = str(exc)
    if as_json:
        print(json.dumps(meta, indent=2))
    else:
        print(f"{category} — SQLite database")
        print(f"path: {meta['path']}")
        print(f"size: {P.human_size(meta['size_bytes'])}")
        if meta.get("tables"):
            print("tables:")
            for table, count in meta["tables"].items():
                print(f"  {table}: {count} rows" if count is not None else f"  {table}: (unreadable)")
        elif exists:
            print("(no readable tables)")
        else:
            print("(no database file stored yet)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    P.require_category(args.category)  # raises SystemExit(2) on unknown category
    info = P.CATEGORIES[args.category]
    kind = info["kind"]
    idx = args.index
    if idx < 0:
        print(f"Index must be >= 0, got {idx}.", file=sys.stderr)
        return 1
    P.audit("show", f"{args.category} index={idx}")
    if kind == "db":
        return _show_db(args.category, info, args.json)
    if kind in ("json", "mixed"):
        json_files = [
            p
            for p in P.category_paths(args.category)
            if p.suffix == ".json" and p.is_file()
        ]
        if json_files:
            return _show_json_record(args.category, info, idx, args.json)
        # fall through to file view when the JSON file is missing
    files = P.category_files(args.category)
    return _show_file(args.category, files, idx, args.json)
