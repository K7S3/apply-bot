"""Read-only remote verification checks for a release.

Never writes anything: no tags, no pushes, no ref updates. Remote reads use
`git ls-remote` and degrade to skipped (ok=None) on network/auth failure,
which is the expected behavior on machines without git auth.
"""
from __future__ import annotations

import subprocess

from candid.release_tag import tree_is_clean


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


def _ls_remote(repo_root, ref):
    """Return ls-remote output for ref, or None when the remote cannot be
    reached (network/auth failure). Empty string means reachable but ref
    absent."""
    r = _git(repo_root, "ls-remote", "origin", ref)
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip()


def _check_working_tree_clean(repo_root):
    clean = tree_is_clean(repo_root)
    return {
        "name": "working tree clean",
        "ok": clean,
        "detail": (
            "git status --short is empty"
            if clean
            else "uncommitted changes present (git status --short non-empty)"
        ),
    }


def _check_main_matches_origin(repo_root):
    name = "local main matches origin/main"
    remote = _ls_remote(repo_root, "refs/heads/main")
    if remote is None:
        return {
            "name": name,
            "ok": None,
            "detail": "skipped: could not reach origin (no network or no git auth)",
        }
    r = _git(repo_root, "rev-parse", "main")
    if r is None or r.returncode != 0:
        return {
            "name": name,
            "ok": None,
            "detail": "skipped: no local main branch to compare",
        }
    local_sha = r.stdout.strip()
    remote_sha = remote.split()[0] if remote else ""
    if not remote_sha:
        return {
            "name": name,
            "ok": False,
            "detail": "origin has no refs/heads/main",
        }
    if local_sha == remote_sha:
        return {
            "name": name,
            "ok": True,
            "detail": f"local main {local_sha} matches origin/main",
        }
    return {
        "name": name,
        "ok": False,
        "detail": f"local main {local_sha} differs from origin/main {remote_sha}",
    }


def _check_tags_on_remote(repo_root):
    name = "tags present on remote"
    r = _git(repo_root, "tag", "-l", "v*")
    if r is None or r.returncode != 0:
        return {
            "name": name,
            "ok": None,
            "detail": "skipped: could not list local tags",
        }
    local_tags = [t for t in r.stdout.split() if t]
    if not local_tags:
        return {"name": name, "ok": True, "detail": "no local v* tags to check"}

    missing = []
    for tag in local_tags:
        out = _ls_remote(repo_root, f"refs/tags/{tag}")
        if out is None:
            return {
                "name": name,
                "ok": None,
                "detail": "skipped: could not reach origin (no network or no git auth)",
            }
        if not out:
            missing.append(tag)

    if missing:
        return {
            "name": name,
            "ok": False,
            "detail": "missing on origin: " + ", ".join(missing),
        }
    return {
        "name": name,
        "ok": True,
        "detail": f"{len(local_tags)} v* tag(s) present on origin",
    }


def run_checks(repo_root) -> list[dict]:
    """Remote verification, read-only. Each check is a dict with name, ok
    (True/False, or None for skipped), and detail."""
    return [
        _check_working_tree_clean(repo_root),
        _check_main_matches_origin(repo_root),
        _check_tags_on_remote(repo_root),
    ]
