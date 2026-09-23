"""Completeness checks: missing fields, missing optional data, profile gaps,
orphaned prep-pack references and stray generated files."""

from __future__ import annotations

import os
from pathlib import Path

from candid.quality import Issue

REQUIRED_FIELDS = ("company", "role", "status", "date_added")

PROFILE_KEYS = ("name", "email", "location", "summary", "skills", "experience")

#: dirs scanned for files that are not referenced by any tracker record
_UNREF_DIRS = ("prep_packs", "tailored")

_MAX_UNREFERENCED_LISTED = 5


def _is_empty(value) -> bool:
    """True when a field counts as missing: absent, None, or blank string."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _data_dir(ctx) -> Path:
    return Path(ctx.get("data_dir") or ".")


def run(apps, ctx) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(_missing_fields(apps))
    issues.extend(_missing_optional_fields(apps))
    issues.extend(_profile_completeness(ctx))
    issues.extend(_orphaned_references(apps, ctx))
    return issues


def _missing_fields(apps) -> list[Issue]:
    """One error per required tracker field that is missing or blank."""
    issues: list[Issue] = []
    for app in apps or []:
        record_id = app.get("id")
        for field in REQUIRED_FIELDS:
            if _is_empty(app.get(field)):
                issues.append(Issue(
                    check="missing_fields",
                    severity="error",
                    record_id=record_id,
                    message=f"Record {record_id}: required field '{field}' is missing.",
                    suggestion=f"Fill in '{field}' with `candid track update {record_id}`.",
                ))
    return issues


def _missing_optional_fields(apps) -> list[Issue]:
    """Info nudges for useful-but-optional fields."""
    issues: list[Issue] = []
    for app in apps or []:
        record_id = app.get("id")
        if _is_empty(app.get("jd_link")):
            issues.append(Issue(
                check="missing_optional_fields",
                severity="info",
                record_id=record_id,
                message=f"Record {record_id}: no job-posting link saved.",
                suggestion="Save the posting URL with `candid track update <id>` so "
                           "tailored resumes can reference it.",
            ))
        if _is_empty(app.get("source")):
            issues.append(Issue(
                check="missing_optional_fields",
                severity="info",
                record_id=record_id,
                message=f"Record {record_id}: no source recorded.",
                suggestion="Record where you found this job (e.g. a board, "
                           "referral, outreach) with `candid track update <id>`.",
            ))
    return issues


def _profile_completeness(ctx) -> list[Issue]:
    """One warning per missing/empty profile key (global, record_id=None)."""
    profile = ctx.get("profile") or {}
    issues: list[Issue] = []
    for key in PROFILE_KEYS:
        value = profile.get(key)
        if key in ("skills", "experience"):
            # skills/experience are list-like: non-empty required
            missing = not (isinstance(value, (list, tuple)) and len(value) > 0)
        else:
            missing = _is_empty(value)
        if missing:
            issues.append(Issue(
                check="profile_completeness",
                severity="warning",
                record_id=None,
                message=f"Profile is missing '{key}'.",
                suggestion=f"Add '{key}' via `candid onboard` or `candid profile`.",
            ))
    return issues


def _orphaned_references(apps, ctx) -> list[Issue]:
    """Warnings for prep-pack paths that don't exist; info for files on disk
    that no record references."""
    data_dir = _data_dir(ctx)
    issues: list[Issue] = []
    referenced: set[str] = set()

    for app in apps or []:
        record_id = app.get("id")
        ref = app.get("prep_pack")
        if _is_empty(ref):
            continue
        ref_path = Path(str(ref))
        if not ref_path.is_absolute():
            ref_path = data_dir / ref_path
        referenced.add(ref_path.name)
        if not ref_path.exists():
            issues.append(Issue(
                check="orphaned_references",
                severity="warning",
                record_id=record_id,
                message=f"Record {record_id}: prep pack '{ref}' does not exist.",
                suggestion="Regenerate it with `candid prep` or clear the stale "
                           f"reference with `candid track update {record_id}`.",
            ))

    for dirname in _UNREF_DIRS:
        d = data_dir / dirname
        if not os.path.isdir(d):
            continue
        stray = sorted(
            p.name for p in d.iterdir()
            if p.is_file() and p.name not in referenced
        )
        if stray:
            shown = ", ".join(stray[:_MAX_UNREFERENCED_LISTED])
            extra = len(stray) - _MAX_UNREFERENCED_LISTED
            if extra > 0:
                shown += f" (+{extra} more)"
            issues.append(Issue(
                check="orphaned_references",
                severity="info",
                record_id=None,
                message=f"{len(stray)} file(s) in '{dirname}/' are not referenced "
                        f"by any record: {shown}.",
                suggestion="Remove them or re-link them to a tracker record.",
            ))
    return issues

