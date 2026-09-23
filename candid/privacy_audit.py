"""Privacy dashboard: read-only view of the privacy audit log.

    python -m candid privacy audit [--json] [--limit N]

Shows the append-only audit trail of privacy actions (exports, purges,
retention runs, policy changes, ...). The log is written by the privacy
commands via P.audit(); this command only reads it.

Handlers return int exit codes and never call sys.exit themselves; a
negative --limit raises SystemExit(2) as a usage error.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace

from . import privacy as P

DEFAULT_LIMIT = 20


def cmd_audit(args: Namespace) -> int:
    limit = args.limit
    if limit is not None and limit < 0:
        print(
            f"Invalid --limit {limit!r}: must be a non-negative integer.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    entries = [] if limit == 0 else P.read_audit_log(limit=limit or DEFAULT_LIMIT)

    if args.json:
        print(json.dumps(entries, indent=2))
        return 0

    if not entries:
        print(
            "No privacy actions recorded yet. "
            "Actions like exports, purges, and retention runs will appear here."
        )
        return 0

    ts_w = max(len(str(e.get("ts", ""))) for e in entries)
    act_w = max(len(str(e.get("action", ""))) for e in entries)
    print(f"{'TIMESTAMP':<{ts_w}}  {'ACTION':<{act_w}}  DETAIL")
    print("-" * (ts_w + act_w + 40))
    for e in entries:
        ts = str(e.get("ts", ""))
        action = str(e.get("action", ""))
        detail = str(e.get("detail", ""))
        print(f"{ts:<{ts_w}}  {action:<{act_w}}  {detail}")
    print(f"\n{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} shown (newest last).")
    return 0


def add_parsers(sub) -> None:
    p = sub.add_parser(
        "audit",
        help="Show the append-only privacy audit log.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit entries as JSON (for scripting).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many recent entries to show (default: {DEFAULT_LIMIT}).",
    )
    p.set_defaults(func=cmd_audit)
