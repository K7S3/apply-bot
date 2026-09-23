"""Privacy dashboard: see everything candid holds about you, and control it.

Subcommand modules (privacy_inventory, privacy_purge, privacy_retention,
privacy_scan, privacy_audit) each expose ``add_parsers(sub)`` and register
themselves here via ``register_privacy_parsers``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config

# --- shared paths -----------------------------------------------------------
PRIVACY_EXPORT_DIR = config.DATA_DIR / "privacy_exports"
RETENTION_POLICY_PATH = config.DATA_DIR / "privacy_retention.json"
AUDIT_LOG_PATH = config.DATA_DIR / "privacy_audit.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def confirm(prompt: str) -> bool:
    """Interactive yes/no confirmation. Defaults to no."""
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def audit(action: str, detail: str = "") -> None:
    """Append an entry to the privacy audit log. Never raises."""
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": utc_now(), "action": action, "detail": detail}
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read_audit_log(limit: int = 100) -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    entries: list[dict] = []
    try:
        for line in AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return entries
    return entries[-limit:]


# --- data categories ---------------------------------------------------------
# Each category: name -> dict(label, paths relative to DATA_DIR, kind).
# "paths" may include files or directories; missing ones are simply skipped.
CATEGORIES: dict[str, dict] = {
    "profile": {
        "label": "Your profile (resume/LinkedIn ingestion)",
        "paths": ["profile.json"],
        "kind": "json",
    },
    "tracker": {
        "label": "Application tracker",
        "paths": ["tracker.json"],
        "kind": "json",
    },
    "tailored": {
        "label": "Tailored resumes and cover letters",
        "paths": ["tailored", "tailored_versions"],
        "kind": "dir",
    },
    "prep": {
        "label": "Interview prep packs",
        "paths": ["prep_packs"],
        "kind": "dir",
    },
    "debriefs": {
        "label": "Interview debriefs",
        "paths": ["debriefs.json"],
        "kind": "json",
    },
    "stories": {
        "label": "STAR story bank",
        "paths": ["stories.json"],
        "kind": "json",
    },
    "salary": {
        "label": "Salary intelligence (LCA database)",
        "paths": ["salary.db"],
        "kind": "db",
    },
    "gmail": {
        "label": "Gmail Takeout import proposals",
        "paths": ["gmail_proposals.json"],
        "kind": "json",
    },
    "offers": {
        "label": "Offers and comparisons",
        "paths": ["offers.json", "offer_comparisons"],
        "kind": "mixed",
    },
    "jobs": {
        "label": "Curated jobs and dismissed jobs",
        "paths": ["jobs.json", "job_meta.json", "dismissed_jobs.json"],
        "kind": "json",
    },
    "study": {
        "label": "Skill-gap study plans",
        "paths": ["study_plans"],
        "kind": "dir",
    },
    "mock": {
        "label": "Mock interview sessions",
        "paths": ["mock_sessions"],
        "kind": "dir",
    },
    "milestones": {
        "label": "Milestones",
        "paths": ["milestones.json"],
        "kind": "json",
    },
    "watchlist": {
        "label": "Target-company watchlist",
        "paths": ["watchlist.json"],
        "kind": "json",
    },
    "archive": {
        "label": "Archived applications",
        "paths": ["archive"],
        "kind": "dir",
    },
    "privacy-exports": {
        "label": "Privacy exports (made by candid privacy)",
        "paths": ["privacy_exports"],
        "kind": "dir",
    },
}

#: Categories never touched by `privacy nuke` (they hold candid's own config,
#: not the user's job-search data). Everything else is wiped.
NUKE_PROTECTED = {"privacy-exports"}


def category_paths(name: str) -> list[Path]:
    info = CATEGORIES[name]
    return [config.DATA_DIR / p for p in info["paths"]]


def category_files(name: str) -> list[Path]:
    """All existing files belonging to a category (expanding directories)."""
    files: list[Path] = []
    for path in category_paths(name):
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.is_file())
    return files


def category_bytes(name: str) -> int:
    total = 0
    for f in category_files(name):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def category_records(name: str) -> int | None:
    """Best-effort record count, or None when not countable."""
    info = CATEGORIES[name]
    try:
        if info["kind"] == "json":
            path = config.DATA_DIR / info["paths"][0]
            if not path.exists():
                return 0
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                for key in ("applications", "items", "entries", "records"):
                    if isinstance(data.get(key), list):
                        return len(data[key])
                return len(data)
            return None
        if info["kind"] in ("dir", "mixed"):
            return len(category_files(name))
    except (OSError, json.JSONDecodeError):
        return None
    return None


def iter_inventory() -> list[dict]:
    """One dict per category: name, label, exists, bytes, records."""
    rows = []
    for name, info in CATEGORIES.items():
        nbytes = category_bytes(name)
        exists = bool(category_files(name))
        rows.append(
            {
                "name": name,
                "label": info["label"],
                "exists": exists,
                "bytes": nbytes,
                "size": human_size(nbytes),
                "records": category_records(name),
            }
        )
    return rows


# --- PII redaction ------------------------------------------------------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
APIKEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+]{8,})['\"]?"
)


def redact_text(text: str) -> str:
    """Replace likely PII in text with [REDACTED] markers."""
    text = EMAIL_RE.sub("[REDACTED-EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED-PHONE]", text)
    text = SSN_RE.sub("[REDACTED-SSN]", text)
    text = APIKEY_RE.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "[REDACTED]", text)
    return text


def find_pii(text: str) -> list[dict]:
    """Return list of {type, match, line} for likely PII in text."""
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in EMAIL_RE.finditer(line):
            findings.append({"type": "email", "match": m.group(0), "line": i})
        for m in PHONE_RE.finditer(line):
            findings.append({"type": "phone", "match": m.group(0), "line": i})
        for m in SSN_RE.finditer(line):
            findings.append({"type": "ssn", "match": m.group(0), "line": i})
        for m in APIKEY_RE.finditer(line):
            findings.append({"type": "possible-secret", "match": m.group(0)[:40], "line": i})
    return findings


def require_category(name: str) -> None:
    if name not in CATEGORIES:
        valid = ", ".join(sorted(CATEGORIES))
        print(f"Unknown category {name!r}. Valid: {valid}", file=sys.stderr)
        raise SystemExit(2)


def register_privacy_parsers(sub) -> None:
    """Wire all privacy subcommand modules into `candid privacy`."""
    from . import (
        privacy_audit,
        privacy_inventory,
        privacy_nuke,
        privacy_purge,
        privacy_retention,
        privacy_scan,
    )

    for mod in (
        privacy_inventory,
        privacy_purge,
        privacy_retention,
        privacy_scan,
        privacy_audit,
        privacy_nuke,
    ):
        mod.add_parsers(sub)
