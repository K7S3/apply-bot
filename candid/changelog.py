"""candid changelog: generate changelogs from git history.

Reads a repo's commit history via ``git log``, classifies each commit
(conventional-commit prefixes with a keyword fallback, breaking-change
detection), and renders Keep-a-Changelog style Markdown, plain text,
GitHub release bodies, or JSON.

Everything is stdlib-only: parsing is done with an unambiguous
unit-separator ``git log`` format, no external dependencies.

Typical flow::

    commits = get_commits()              # since most recent tag
    groups = group_commits(commits)
    md = render_markdown(groups, stats(commits), version="0.3.0")
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path

__all__ = [
    "ChangelogError",
    "get_commits",
    "categorize",
    "group_commits",
    "suggest_bump",
    "stats",
    "render_markdown",
    "render_plain",
    "render_github",
    "render_json",
    "check_against_file",
]


class ChangelogError(RuntimeError):
    """Raised when the changelog cannot be built (not a git repo, bad revision)."""


# Category order used by group_commits and all renderers.
CATEGORIES = (
    "breaking",
    "feat",
    "fix",
    "perf",
    "docs",
    "refactor",
    "test",
    "chore",
    "other",
)

SECTION_TITLES = {
    "breaking": "Breaking Changes",
    "feat": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance",
    "docs": "Documentation",
    "refactor": "Refactoring",
    "test": "Tests",
    "chore": "Chores",
    "other": "Other",
}

# type(scope)!: subject  - the "!" marks a breaking change
_CONVENTIONAL_RE = re.compile(
    r"^([A-Za-z][\w-]*)(?:\([^)]*\))?(!)?:(.*)$"
)

# Keyword fallback when a commit has no conventional-commit prefix.
# Checked in this order so the first match wins.
_KEYWORD_CATEGORIES = (
    ("feat", r"\b(add|added|adds|new|support|feature|features)\b"),
    ("fix", r"\b(fix|fixed|fixes|bug|bugs|correct|corrects|corrected)\b"),
    ("docs", r"\b(doc|docs|documentation|readme|guide)\b"),
    ("perf", r"\b(performance|faster|speed|speedup|optimiz\w*)\b"),
    ("test", r"\b(test|tests|tested|testing)\b"),
    ("refactor", r"\b(refactor|refactored|refactoring|cleanup|clean up)\b"),
    ("chore", r"\b(chore|bump|bumped|dep|deps|dependency|dependencies|ci|release)\b"),
)

_BREAKING_BODY_RE = re.compile(r"breaking[- ]change", re.IGNORECASE)

# git log fields separated by \x1f (unit separator), records by \x1e.
_LOG_FORMAT = "%H%x1f%h%x1f%s%x1f%b%x1f%an%x1f%ae%x1f%aI%x1e"


def _run_git(args: list[str], repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def get_commits(since: str | None = None, repo: str | Path | None = None) -> list[dict]:
    """Return commits newest-first as dicts.

    Each dict has keys: sha, short, subject, body, author, email, date
    (ISO 8601 string), raw (the raw ``git log`` record).

    ``since`` is a tag/SHA; the range is ``since..HEAD``. When ``since``
    is None, the most recent tag (``git describe --tags --abbrev=0``) is
    used; if the repo has no tags, all commits are returned.

    ``repo`` may be a Path or str; defaults to the current directory.

    Raises ChangelogError if ``repo`` is not a git repository or ``since``
    is not a valid revision.
    """
    repo = Path(repo) if repo is not None else Path.cwd()
    probe = _run_git(["rev-parse", "--git-dir"], repo)
    if probe.returncode != 0:
        raise ChangelogError(f"not a git repository: {repo}")

    rev_range: list[str] = []
    if since is not None:
        rev_range = [f"{since}..HEAD"]
    else:
        tag = _run_git(["describe", "--tags", "--abbrev=0"], repo)
        if tag.returncode == 0 and tag.stdout.strip():
            rev_range = [f"{tag.stdout.strip()}..HEAD"]
        # no tags: fall through to all commits

    result = _run_git(
        ["log", *rev_range, "--no-color", f"--format={_LOG_FORMAT}"], repo
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "does not have any commits yet" in stderr:
            return []
        if since is not None and "unknown revision" in stderr.lower():
            raise ChangelogError(f"bad revision for since={since!r}: {stderr}")
        raise ChangelogError(f"git log failed: {stderr}")

    commits: list[dict] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) != 7:
            continue  # defensive: skip malformed records
        sha, short, subject, body, author, email, iso_date = fields
        commits.append(
            {
                "sha": sha,
                "short": short,
                "subject": subject,
                "body": body.strip(),
                "author": author,
                "email": email,
                "date": iso_date,
                "raw": record,
            }
        )
    return commits


def categorize(subject: str, body: str = "") -> tuple[str, bool]:
    """Classify a commit into (category, breaking).

    Parses a conventional-commit prefix ``type(scope)!: subject``; known
    types map to categories, unknown types to ``other``. A ``!`` after the
    type, a ``BREAKING CHANGE``/``BREAKING-CHANGE`` trailer in the body
    (case-insensitive), or a subject starting with ``BREAKING`` marks the
    commit as breaking.

    Without a prefix, keyword matching on the subject/body decides.
    """
    subject = (subject or "").strip()
    body = body or ""
    text = f"{subject}\n{body}".lower()

    breaking = (
        subject.upper().startswith("BREAKING")
        or bool(_BREAKING_BODY_RE.search(body))
    )

    match = _CONVENTIONAL_RE.match(subject)
    if match:
        ctype, bang, _rest = match.groups()
        if bang:
            breaking = True
        category = ctype.lower()
        if category not in CATEGORIES or category == "breaking":
            category = "other"
        return category, breaking

    for category, pattern in _KEYWORD_CATEGORIES:
        if re.search(pattern, text):
            return category, breaking
    return "other", breaking


def group_commits(commits: list[dict]) -> dict[str, list[dict]]:
    """Group commits into an ordered dict of small entry dicts.

    Keys are ``breaking, feat, fix, perf, docs, refactor, test, chore,
    other``. Each entry is ``{"short", "subject", "author"}``. Breaking
    commits appear ONLY under ``breaking``.
    """
    groups: dict[str, list[dict]] = {cat: [] for cat in CATEGORIES}
    for commit in commits:
        category, breaking = categorize(commit.get("subject", ""),
                                        commit.get("body", ""))
        key = "breaking" if breaking else category
        groups[key].append(
            {
                "short": commit.get("short", ""),
                "subject": commit.get("subject", ""),
                "author": commit.get("author", ""),
            }
        )
    return groups


def suggest_bump(commits: list[dict]) -> str:
    """Suggest a semver bump: 'major' | 'minor' | 'patch' | 'none'.

    Breaking change -> major; any feat -> minor; any fix/perf/docs/
    refactor/test -> patch; empty or only chore/other -> none.
    """
    if not commits:
        return "none"
    categories: set[str] = set()
    breaking = False
    for commit in commits:
        category, is_breaking = categorize(commit.get("subject", ""),
                                           commit.get("body", ""))
        if is_breaking:
            breaking = True
        categories.add(category)
    if breaking:
        return "major"
    if "feat" in categories:
        return "minor"
    if categories - {"chore", "other"}:
        return "patch"
    return "none"


def stats(commits: list[dict]) -> dict:
    """Aggregate commit stats.

    Returns ``{"total", "by_category", "authors", "first_date",
    "last_date"}``. ``by_category`` counts routing categories (breaking
    commits count under ``breaking``); dates are ISO strings from the
    commits, ``None`` when there are no commits.
    """
    by_category: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    authors: dict[str, int] = {}
    dates: list[str] = []
    for commit in commits:
        category, breaking = categorize(commit.get("subject", ""),
                                        commit.get("body", ""))
        by_category["breaking" if breaking else category] += 1
        name = commit.get("author", "") or "unknown"
        authors[name] = authors.get(name, 0) + 1
        if commit.get("date"):
            dates.append(commit["date"])
    return {
        "total": len(commits),
        "by_category": by_category,
        "authors": dict(sorted(authors.items(), key=lambda kv: (-kv[1], kv[0]))),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
    }


def _entry_line_md(entry: dict) -> str:
    return f"- {entry['subject']} (`{entry['short']}`) - {entry['author']}"


def render_markdown(
    groups: dict[str, list[dict]],
    stats: dict | None = None,
    version: str | None = None,
    since: str | None = None,
    include_stats: bool = True,
) -> str:
    """Render a Keep-a-Changelog style Markdown changelog. Empty sections are skipped."""
    lines: list[str] = []
    if version:
        lines.append(f"## [{version}] - {date.today().isoformat()}")
    else:
        lines.append("## Unreleased")
    if since:
        lines.append("")
        lines.append(f"Changes since `{since}`.")
    for key in CATEGORIES:
        entries = groups.get(key, [])
        if not entries:
            continue
        lines.append("")
        lines.append(f"### {SECTION_TITLES[key]}")
        lines.append("")
        lines.extend(_entry_line_md(e) for e in entries)
    if include_stats and stats:
        lines.append("")
        lines.append("### Stats")
        lines.append("")
        lines.append(f"- {stats['total']} commits")
        cats = ", ".join(
            f"{k}: {v}" for k, v in stats["by_category"].items() if v
        )
        if cats:
            lines.append(f"- By category: {cats}")
        authors = ", ".join(
            f"{name} ({count})" for name, count in stats["authors"].items()
        )
        if authors:
            lines.append(f"- Authors: {authors}")
        if stats.get("first_date") and stats.get("last_date"):
            lines.append(f"- Range: {stats['first_date']} to {stats['last_date']}")
    return "\n".join(lines) + "\n"


def render_plain(
    groups: dict[str, list[dict]],
    stats: dict | None = None,
    version: str | None = None,
    since: str | None = None,
    include_stats: bool = True,
) -> str:
    """Plain-text variant of render_markdown (no Markdown syntax)."""
    title = f"Changelog - {version}" if version else "Changelog - Unreleased"
    lines: list[str] = [title, "=" * len(title)]
    if since:
        lines.append("")
        lines.append(f"Changes since {since}.")
    for key in CATEGORIES:
        entries = groups.get(key, [])
        if not entries:
            continue
        heading = SECTION_TITLES[key].upper()
        lines.append("")
        lines.append(heading)
        lines.append("-" * len(heading))
        for e in entries:
            lines.append(f"* {e['subject']} ({e['short']}) - {e['author']}")
    if include_stats and stats:
        lines.append("")
        lines.append("STATS")
        lines.append("-----")
        lines.append(f"Total commits: {stats['total']}")
        cats = ", ".join(
            f"{k}: {v}" for k, v in stats["by_category"].items() if v
        )
        if cats:
            lines.append(f"By category: {cats}")
        authors = ", ".join(
            f"{name} ({count})" for name, count in stats["authors"].items()
        )
        if authors:
            lines.append(f"Authors: {authors}")
    return "\n".join(lines) + "\n"


def render_github(
    groups: dict[str, list[dict]],
    stats: dict | None,
    version: str | None,
    since: str | None,
    repo_url: str | None = None,
) -> str:
    """Render a GitHub release body: "## What's Changed" plus sections."""
    lines: list[str] = ["## What's Changed", ""]
    if version:
        lines.append(f"Release {version}")
        lines.append("")
    for key in CATEGORIES:
        entries = groups.get(key, [])
        if not entries:
            continue
        lines.append(f"### {SECTION_TITLES[key]}")
        lines.append("")
        for e in entries:
            lines.append(f"- {e['subject']} ({e['short']}) - {e['author']}")
        lines.append("")
    if repo_url and version and since:
        lines.append(
            f"**Full Changelog**: {repo_url.rstrip('/')}/compare/{since}...{version}"
        )
        lines.append("")
    if stats:
        lines.append(f"_{stats['total']} commits in this range._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(
    groups: dict[str, list[dict]],
    stats: dict | None,
    version: str | None,
    since: str | None,
) -> str:
    """Render the changelog as a JSON string with structured entries."""
    payload = {
        "version": version,
        "since": since,
        "groups": {key: list(groups.get(key, [])) for key in CATEGORIES},
        "stats": stats,
    }
    return json.dumps(payload, indent=2) + "\n"


def check_against_file(
    path: str | Path, generated: dict[str, list[dict]] | list[dict]
) -> tuple[bool, list[str]]:
    """Check generated entries against an existing CHANGELOG.md.

    Takes the first ``## `` section body of the file and verifies each
    generated entry's subject appears in it. Returns ``(ok, missing)``
    where ``missing`` lists the subjects not found.

    ``generated`` may be a groups dict (as from group_commits) or a plain
    list of entry dicts.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    start: int | None = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if start is None:
                start = i + 1
            else:
                end = i
                break
    body = "\n".join(lines[start:end]) if start is not None else text

    if isinstance(generated, dict):
        entries = [e for items in generated.values() for e in items]
    elif isinstance(generated, list):
        entries = generated
    else:
        raise ChangelogError(
            "generated must be a groups dict or a list of entry dicts"
        )
    missing = [
        e.get("subject", "")
        for e in entries
        if e.get("subject", "") not in body
    ]
    return (not missing, missing)
