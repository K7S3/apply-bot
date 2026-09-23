#!/usr/bin/env python3
"""Generate a CHANGELOG.md entry from git log between two refs.

Usage:
    python scripts/changelog.py <from> <to> [--output CHANGELOG.md]

Example:
    python scripts/changelog.py v0.2.0 HEAD

Commit messages are grouped into sections by conventional-commit prefix
or, for free-form messages, by leading keyword heuristics:

    Features      feat, feature, add, support, new, rename
    Bug Fixes     fix, bug, repair
    Documentation docs, doc
    Performance   perf
    Refactor      refactor
    Tests         test, tests
    Maintenance   chore, build, ci, style

Anything else lands under "Other changes". The grouping is intentionally
forgiving: it is a release-notes draft, not a spec.

With --output, the entry is prepended to the given file (after the first
"# " heading, creating the file if needed).
"""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date

GROUPS = [
    ("Features", ("feat", "feature", "add", "support", "new", "rename")),
    ("Bug Fixes", ("fix", "bug", "repair")),
    ("Documentation", ("docs", "doc")),
    ("Performance", ("perf",)),
    ("Refactor", ("refactor",)),
    ("Tests", ("test", "tests")),
    ("Maintenance", ("chore", "build", "ci", "style")),
]

CONVENTIONAL_RE = re.compile(r"^(\w+)(\(.+\))?\s*:\s*(.*)$", re.IGNORECASE)


def _git(args: list[str], repo: str | None = None) -> str:
    cmd = ["git"]
    if repo:
        cmd += ["-C", repo]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def collect_commits(from_ref: str, to_ref: str, repo: str | None = None) -> list[dict]:
    """Return [{'sha', 'subject', 'body'}] for commits in from_ref..to_ref."""
    raw = _git(
        ["log", f"{from_ref}..{to_ref}", "--pretty=format:%H%x1f%s%x1f%b%x1e", "--reverse"],
        repo,
    )
    commits = []
    for record in raw.strip().split("\x1e"):
        if not record.strip():
            continue
        parts = record.strip("\n").split("\x1f")
        sha = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""
        commits.append({"sha": sha, "subject": subject.strip(), "body": body.strip()})
    return commits


def classify(subject: str) -> tuple[str, str]:
    """Map a commit subject to (group, summary)."""
    match = CONVENTIONAL_RE.match(subject)
    prefix = match.group(1).lower() if match else subject.split()[0].lower().rstrip(":") if subject else ""
    summary = match.group(3).strip() if match else subject.strip()

    for group, keywords in GROUPS:
        if prefix in keywords:
            return group, summary
    return "Other changes", summary


def group_commits(commits: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {name: [] for name, _ in GROUPS}
    grouped["Other changes"] = []
    for commit in commits:
        group, summary = classify(commit["subject"])
        grouped[group].append({**commit, "summary": summary})
    return grouped


def render_entry(version: str, grouped: dict[str, list[dict]], release_date: str | None = None) -> str:
    release_date = release_date or date.today().isoformat()
    lines = [f"## {version} - {release_date}", ""]
    for name, _ in GROUPS:
        entries = grouped.get(name, [])
        if not entries:
            continue
        lines.append(f"### {name}")
        for e in entries:
            short = e["sha"][:7]
            summary = e["summary"] or e["subject"]
            lines.append(f"- {summary} ({short})")
        lines.append("")
    other = grouped.get("Other changes", [])
    if other:
        lines.append("### Other changes")
        for e in other:
            short = e["sha"][:7]
            summary = e["summary"] or e["subject"]
            lines.append(f"- {summary} ({short})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def prepend_to_changelog(path: str, entry: str) -> None:
    """Prepend entry under the file's first '# ' heading (or create the file)."""
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""
    if existing.startswith("#"):
        first, _, rest = existing.partition("\n")
        new = first + "\n\n" + entry + ("\n" + rest if rest.strip() else "")
    elif existing:
        new = entry + "\n" + existing
    else:
        new = "# Changelog\n\n" + entry
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a CHANGELOG.md entry from git log.")
    parser.add_argument("from_ref", help="start ref (exclusive), e.g. v0.2.0")
    parser.add_argument("to_ref", help="end ref (inclusive), e.g. HEAD")
    parser.add_argument("--output", metavar="PATH", help="prepend the entry to this changelog file")
    parser.add_argument("--repo", metavar="DIR", help="git repo to read (default: cwd)")
    args = parser.parse_args()

    commits = collect_commits(args.from_ref, args.to_ref, args.repo)
    if args.to_ref.lstrip("v") in ("HEAD", "main", "master") or args.to_ref in ("HEAD", "main", "master"):
        version = "Unreleased"
    else:
        version = args.to_ref.lstrip("v")
    entry = render_entry(version, group_commits(commits))
    if args.output:
        prepend_to_changelog(args.output, entry)
        print(f"Wrote entry ({len(commits)} commits) to {args.output}")
    else:
        print(entry, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
