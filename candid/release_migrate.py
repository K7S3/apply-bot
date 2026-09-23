"""Migration notes for a release range, built from a heuristic scan of
commit subjects.

This is explicitly a heuristic: commits are flagged by case-insensitive
keyword matching on their subjects only, with no semantic analysis. A human
should review the hits before publishing release notes.
"""
from __future__ import annotations

import subprocess

KEYWORDS = (
    "config",
    "schema",
    "migration",
    "breaking",
    "data dir",
    "backward",
    "upgrade",
)


def _git(repo_root, *args):
    """Run git in repo_root; return the CompletedProcess or None if git
    could not be run at all."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _log_commits(repo_root, from_ref, to_ref):
    """Return [{"hash", "subject"}] for commits in from_ref..to_ref, newest
    first; [] on any git error or bad ref."""
    r = _git(repo_root, "log", f"{from_ref}..{to_ref}", "--pretty=format:%H%x09%s")
    if r is None or r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        if "\t" not in line:
            continue
        h, subject = line.split("\t", 1)
        out.append({"hash": h, "subject": subject})
    return out


def commits_between(repo_root, from_ref, to_ref) -> list[str]:
    """Commit subjects between from_ref and to_ref (exclusive of from_ref),
    newest first; [] on error."""
    return [c["subject"] for c in _log_commits(repo_root, from_ref, to_ref)]


def detect_migrations(repo_root, from_ref, to_ref) -> list[dict]:
    """Heuristic scan: flag a commit when its subject contains any of
    KEYWORDS (case-insensitive). One hit dict per (commit, keyword) with
    keys "subject", "hash", "keyword"."""
    hits = []
    for c in _log_commits(repo_root, from_ref, to_ref):
        lowered = c["subject"].lower()
        for kw in KEYWORDS:
            if kw in lowered:
                hits.append(
                    {"subject": c["subject"], "hash": c["hash"], "keyword": kw}
                )
    return hits


def render_migration_notes(migrations, from_ref, to_ref) -> str:
    """Render a markdown migration-notes section, or a fallback sentence
    when the heuristic scan found nothing."""
    header = f"## Migration notes ({from_ref} -> {to_ref})"
    if not migrations:
        return header + "\n\nNo migration-relevant changes detected (heuristic scan)."
    lines = [header, ""]
    for m in migrations:
        lines.append(f"- {m['subject']} (`{m['hash'][:7]}`, keyword: {m['keyword']})")
    lines.append("")
    lines.append(
        "_Heuristic keyword scan of commit subjects; review before publishing._"
    )
    return "\n".join(lines)


def _latest_two_tags(repo_root):
    r = _git(repo_root, "tag", "--list", "v*", "--sort=-v:refname")
    if r is None or r.returncode != 0:
        return []
    return [t for t in r.stdout.split() if t][:2]


def run_checks(repo_root) -> list[dict]:
    """'migration notes generatable': always ok=True (informational, never
    fails); detail reports the heuristic hit count for the latest tag range
    (newest tag vs previous tag, or tag vs HEAD, or none when no v* tags)."""
    tags = _latest_two_tags(repo_root)
    if len(tags) >= 2:
        from_ref, to_ref = tags[1], tags[0]
    elif len(tags) == 1:
        from_ref, to_ref = tags[0], "HEAD"
    else:
        return [
            {
                "name": "migration notes generatable",
                "ok": True,
                "detail": "0 migration-relevant commits (heuristic scan): no v* tags found",
            }
        ]
    hits = detect_migrations(repo_root, from_ref, to_ref)
    return [
        {
            "name": "migration notes generatable",
            "ok": True,
            "detail": (
                f"{len(hits)} migration-relevant commit(s) detected "
                f"by heuristic scan ({from_ref} -> {to_ref})"
            ),
        }
    ]
