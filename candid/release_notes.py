"""Release notes generation from git history.

Builds a human-readable changelog entry from conventional commits between
the last tag and HEAD. Used as a pre-release step before tagging a version.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

_GROUP_ORDER = ("feat", "fix", "docs", "test", "chore", "refactor")

_GIT_TIMEOUT = 60


def _run_git(repo_root, *args):
    """Run a git command, returning the CompletedProcess or None on failure."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_log(repo_root, since_ref=None) -> list[dict]:
    """Return commits as [{"hash", "date", "author", "subject"}].

    When since_ref is given, only commits in <since_ref>..HEAD are returned.
    Returns [] for non-git directories or git failures.
    """
    args = ["log", "--format=%H|%ad|%an|%s", "--date=short"]
    if since_ref:
        args.append(f"{since_ref}..HEAD")
    result = _run_git(repo_root, *args)
    if result is None or result.returncode != 0:
        return []
    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        commit_hash, commit_date, author, subject = parts
        commits.append(
            {
                "hash": commit_hash.strip(),
                "date": commit_date.strip(),
                "author": author.strip(),
                "subject": subject.strip(),
            }
        )
    return commits


def last_tag(repo_root) -> str | None:
    """Return the most recent tag, or None when there is no tag or git fails."""
    result = _run_git(repo_root, "describe", "--tags", "--abbrev=0")
    if result is None or result.returncode != 0:
        return None
    tag = result.stdout.strip()
    return tag or None


def group_commits(commits) -> dict:
    """Bucket commits by conventional-commit prefix before the first colon.

    Known groups: feat, fix, docs, test, chore, refactor. Anything else,
    including subjects with no colon, goes to "other". All groups are
    present as keys, empty lists included.
    """
    groups = {name: [] for name in (*_GROUP_ORDER, "other")}
    for commit in commits:
        subject = str(commit.get("subject", ""))
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*:", subject)
        key = match.group(1).lower() if match else None
        if key not in groups:
            key = "other"
        groups[key].append(commit)
    return groups


def generate_notes(repo_root, since_ref=None) -> str:
    """Generate markdown release notes for commits since since_ref (or last tag).

    Returns "No changes found." when there is nothing to report.
    """
    ref = since_ref if since_ref is not None else last_tag(repo_root)
    commits = git_log(repo_root, since_ref=ref)
    if not commits:
        return "No changes found."
    groups = group_commits(commits)
    dates = sorted(c["date"] for c in commits if c.get("date"))
    authors = {c["author"] for c in commits if c.get("author")}
    date_range = f"{dates[0]} to {dates[-1]}" if dates else "unknown dates"
    lines = []
    lines.append(f"## Changes since {ref}" if ref else "## Changes since the beginning")
    lines.append("")
    lines.append(
        f"{len(commits)} commit(s), {date_range}, {len(authors)} contributor(s)."
    )
    lines.append("")
    for name in (*_GROUP_ORDER, "other"):
        items = groups[name]
        if not items:
            continue
        lines.append(f"### {name}")
        for commit in items:
            short = commit["hash"][:7]
            lines.append(f"- {commit['subject']} ({short})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_changelog_entry(repo_root, version, notes) -> Path:
    """Insert a versioned entry at the top of CHANGELOG.md.

    Creates the file with a "# Changelog" header when missing. The new entry
    goes directly under the top header so the newest release stays first.
    Returns the changelog path.
    """
    path = Path(repo_root) / "CHANGELOG.md"
    entry = f"## [{version}] - {date.today().isoformat()}\n\n{notes.rstrip()}\n\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        lines = existing.splitlines(keepends=True)
        if lines and lines[0].lstrip().startswith("#"):
            head = lines[0]
            if not head.endswith("\n"):
                head += "\n"
            rest = "".join(lines[1:])
            text = head + "\n" + entry + rest
        else:
            text = entry + existing
    else:
        text = "# Changelog\n\n" + entry
    path.write_text(text, encoding="utf-8")
    return path


def run_checks(repo_root) -> dict:
    """Single pre-release check: release notes can be generated.

    ok is True with a detail naming the commit count since the last tag
    (or the total count when there is no tag). Only a git-level failure
    makes this check fail.
    """
    result = _run_git(repo_root, "rev-parse", "--git-dir")
    if result is None or result.returncode != 0:
        return {
            "name": "release notes generatable",
            "ok": False,
            "detail": "git is not usable in this directory",
        }
    ref = last_tag(repo_root)
    commits = git_log(repo_root, since_ref=ref)
    if ref:
        detail = f"{len(commits)} commit(s) since tag {ref}"
    else:
        detail = f"{len(commits)} commit(s) total (no tag found)"
    return {"name": "release notes generatable", "ok": True, "detail": detail}
