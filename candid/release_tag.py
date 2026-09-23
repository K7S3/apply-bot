"""Release tag flow for candid: prerequisites, dry-run planning, tag creation.

Never pushes. All writes happen only in the repo you point at (the test
suite uses throwaway repos); the real checkout is only ever read.
"""
from __future__ import annotations

import subprocess


def tag_name(version: str) -> str:
    """Return the tag name for a release version, e.g. v0.2.0."""
    return f"v{version}"


def tag_message(version: str, notes: str = "") -> str:
    """Annotated-tag message template: "candid <version>" plus optional notes."""
    return f"candid {version}\n\n{notes}".rstrip()


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


def tree_is_clean(repo_root) -> bool:
    """True when `git status --short` is empty; False on any git error."""
    r = _git(repo_root, "status", "--short")
    if r is None or r.returncode != 0:
        return False
    return not r.stdout.strip()


def tag_exists(repo_root, tag: str) -> bool:
    """True when refs/tags/<tag> already resolves in repo_root."""
    r = _git(repo_root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}")
    return r is not None and r.returncode == 0


def _short_sha(repo_root) -> str:
    r = _git(repo_root, "rev-parse", "--short", "HEAD")
    if r is None or r.returncode != 0:
        return "unknown"
    return r.stdout.strip() or "unknown"


def _identity_configured(repo_root):
    """Return (ok, detail) for git user.name / user.email presence, which
    annotated tags require."""
    missing = []
    for key in ("user.name", "user.email"):
        r = _git(repo_root, "config", key)
        if r is None or r.returncode != 0 or not r.stdout.strip():
            missing.append(key)
    if missing:
        return False, "missing git config: " + ", ".join(missing)
    return True, "user.name and user.email are configured"


def current_version() -> str:
    """Current package version, used to check for a duplicate release tag."""
    from candid import __version__

    return __version__


def run_checks(repo_root) -> list[dict]:
    """Tag prerequisites: working tree clean, no duplicate tag for the
    current version, and git user.name/email configured (needed for
    annotated tags)."""
    checks = []

    clean = tree_is_clean(repo_root)
    checks.append(
        {
            "name": "working tree clean",
            "ok": clean,
            "detail": (
                "git status --short is empty"
                if clean
                else "uncommitted changes present (git status --short non-empty)"
            ),
        }
    )

    version = current_version()
    tag = tag_name(version)
    dup = tag_exists(repo_root, tag)
    checks.append(
        {
            "name": "no duplicate tag for current version",
            "ok": not dup,
            "detail": (
                f"tag {tag} already exists"
                if dup
                else f"tag {tag} is free (current version {version})"
            ),
        }
    )

    ident_ok, ident_detail = _identity_configured(repo_root)
    checks.append(
        {
            "name": "git identity configured",
            "ok": ident_ok,
            "detail": ident_detail + " (required to create annotated tags)",
        }
    )
    return checks


def create_tag(repo_root, version, notes="", dry_run=True, require_checks_fn=None) -> dict:
    """Create annotated tag v<version>. Never pushes.

    Steps, in order:
      1. if require_checks_fn is given, run it and abort (no tag) when any
         result has ok is False, recording which checks failed;
      2. refuse when the tag already exists;
      3. refuse when the tree is dirty, unless dry_run;
      4. with dry_run True, return the plan without creating anything;
      5. otherwise run `git tag -a <tag> -m <message>`.

    Returns a dict with ok, tag, detail (and dry_run when applicable).
    """
    tag = tag_name(version)

    if require_checks_fn is not None:
        results = require_checks_fn() or []
        failed = [r.get("name", "?") for r in results if r.get("ok") is False]
        if failed:
            return {
                "ok": False,
                "tag": tag,
                "detail": "refusing: prerequisite checks failed: " + ", ".join(failed),
            }

    if tag_exists(repo_root, tag):
        return {
            "ok": False,
            "tag": tag,
            "detail": f"refusing: tag {tag} already exists",
        }

    if not dry_run and not tree_is_clean(repo_root):
        return {
            "ok": False,
            "tag": tag,
            "detail": "refusing: working tree is dirty (commit or stash first)",
        }

    sha = _short_sha(repo_root)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "tag": tag,
            "detail": f"would create annotated tag {tag} on {sha}",
        }

    r = _git(repo_root, "tag", "-a", tag, "-m", tag_message(version, notes))
    if r is None or r.returncode != 0:
        err = r.stderr.strip() if r is not None else "could not run git"
        return {"ok": False, "tag": tag, "detail": f"git tag failed: {err}"}
    return {
        "ok": True,
        "dry_run": False,
        "tag": tag,
        "detail": f"created annotated tag {tag} on {sha}",
    }
