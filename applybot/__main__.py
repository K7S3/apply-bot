"""CLI entry point: python -m applybot --excel applications.xlsx [--dry-run | --live | --check-only]

Modes:
  --dry-run    (default) Fill every form and screenshot it, but NEVER submit.
  --live       Actually submit applications. Use only after a dry-run looks right.
  --check-only Only run the AI resume review step (no browser at all).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from applybot import config as C


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m applybot",
        description=(
            "End-to-end job application bot: reviews each tailored resume with "
            f"Gemini ({C.MODEL}), applies to each job link, updates the Excel "
            "status column, and emails a summary."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m applybot --excel applications.xlsx --dry-run\n"
            "  python -m applybot --excel applications.xlsx --check-only\n"
            "  python -m applybot --excel applications.xlsx --live   # actually submits!\n"
            "\n"
            "Always run --dry-run first and inspect output/ before going --live."
        ),
    )
    p.add_argument(
        "--excel",
        default="applications.xlsx",
        help="Path to the applications workbook (default: applications.xlsx)",
    )
    p.add_argument(
        "--profile",
        default="profile.yaml",
        help="Path to profile.yaml with your details (default: profile.yaml)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Fill forms and screenshot, but never submit (default).",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Actually submit applications. Implies --dry-run is off.",
    )
    mode.add_argument(
        "--check-only",
        action="store_true",
        help="Only do the AI resume review step; skip the browser entirely.",
    )
    p.add_argument(
        "--make-sample",
        action="store_true",
        help="Write a sample applications.xlsx (2 example rows) and exit.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.make_sample:
        from applybot import excel_io

        path = excel_io.create_sample_excel(Path(args.excel))
        print(f"Sample workbook written to {path}")
        print("Fill in your real rows, then run: python -m applybot --excel applications.xlsx --dry-run")
        return 0

    live = bool(args.live)
    check_only = bool(args.check_only)
    dry_run = not live  # --check-only also skips submission

    if live:
        print("*** LIVE MODE: applications will actually be submitted. ***")
        answer = input("Type YES to continue: ").strip()
        if answer != "YES":
            print("Aborted. (Use --dry-run to preview without submitting.)")
            return 1

    from applybot import runner  # lazy: keeps --help working without deps

    runner.run(args.excel, args.profile, dry_run=dry_run, check_only=check_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
