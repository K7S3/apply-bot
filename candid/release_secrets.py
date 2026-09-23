"""Pre-release secret and PII scan.

Checks that forbidden artifacts are not staged/committed and that no
obvious secrets or personal data are sitting in the source tree. Secret
VALUES are never printed; findings report file:line plus a pattern name.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

#: Artifacts that must never be committed to the repo.
FORBIDDEN = ("profile.yaml", "output", "run_ollama_shim.py")

_GIT_TIMEOUT = 60
_MAX_FILE_BYTES = 1_000_000
_SKIP_DIRS = {".git", "__pycache__", "tests", "samples"}

_SECRET_PATTERNS = (
    ("assigned secret value", re.compile(
        r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{4,}"
    )),
    ("aws access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("github token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SAFE_DOMAINS = ("example.com", "example.org", "example.net", "test.com")


def git_status_short(repo_root) -> str:
    """Return `git status --short` output, or "" on any failure."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def _status_paths(status_output) -> list[str]:
    """Extract file paths from `git status --short` output."""
    paths = []
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:  # rename/copy: check both sides
            parts = rest.split(" -> ")
        else:
            parts = [rest]
        for part in parts:
            part = part.strip().strip('"')
            if part:
                paths.append(part)
    return paths


def _path_is_forbidden(rel_path: str) -> bool:
    """True when any path component is a forbidden artifact name.

    Covers both basenames (profile.yaml, run_ollama_shim.py anywhere in the
    tree) and directory prefixes (anything under output/).
    """
    parts = Path(rel_path).parts
    return any(forbidden in parts for forbidden in FORBIDDEN)


def _iter_repo_files(root: Path):
    """Yield relative file paths under root, skipping VCS/cache dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            full = Path(dirpath) / filename
            try:
                yield full.relative_to(root).as_posix(), full
            except ValueError:
                continue


def _check_forbidden_files(root: Path, status_output: str) -> dict:
    offenders = []
    seen = set()

    def add(path_str):
        if path_str not in seen:
            seen.add(path_str)
            offenders.append(path_str)

    for path_str in _status_paths(status_output):
        if _path_is_forbidden(path_str):
            add(path_str)
    for rel, _full in _iter_repo_files(root):
        if _path_is_forbidden(rel):
            add(rel)
    detail = f"forbidden paths present: {', '.join(sorted(offenders))}" if offenders else "no forbidden artifacts found"
    return {
        "name": "forbidden files clean",
        "ok": not offenders,
        "detail": detail,
    }


def _read_text_limited(full: Path):
    try:
        if full.stat().st_size >= _MAX_FILE_BYTES:
            return None
        return full.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _check_secret_patterns(root: Path) -> dict:
    findings = []
    candid_dir = root / "candid"
    for rel, full in _iter_repo_files(root):
        if rel.startswith("candid/"):
            in_scope = True
        else:
            # repo-root dotfiles only (e.g. .env.example); not nested dirs
            in_scope = "/" not in rel and rel.startswith(".")
        if not in_scope:
            continue
        text = _read_text_limited(full)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno} [{name}]")
                    break  # one finding per line keeps output tight
    detail = (
        f"{len(findings)} secret pattern hit(s): {'; '.join(findings)}"
        if findings
        else "no secret patterns found"
    )
    return {"name": "no secret patterns", "ok": not findings, "detail": detail}


def _check_pii(root: Path) -> dict:
    findings = []
    candid_dir = root / "candid"
    if candid_dir.is_dir():
        for full in sorted(candid_dir.glob("*.py")):
            rel = full.relative_to(root).as_posix()
            text = _read_text_limited(full)
            if text is None:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for match in _EMAIL_RE.finditer(line):
                    domain = match.group(0).rsplit("@", 1)[1].lower()
                    if domain.endswith(_SAFE_DOMAINS):
                        continue
                    findings.append(f"{rel}:{lineno} [email address]")
                for _match in _PHONE_RE.finditer(line):
                    findings.append(f"{rel}:{lineno} [phone number]")
    detail = (
        f"{len(findings)} PII hit(s): {'; '.join(findings)}"
        if findings
        else "no obvious PII in source"
    )
    return {"name": "no obvious PII in source", "ok": not findings, "detail": detail}


def run_checks(repo_root) -> list[dict]:
    """Run all pre-release secret/PII checks. Findings never include values."""
    root = Path(repo_root)
    status_output = git_status_short(root)
    return [
        _check_forbidden_files(root, status_output),
        _check_secret_patterns(root),
        _check_pii(root),
    ]
