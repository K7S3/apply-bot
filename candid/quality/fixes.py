"""Safe auto-fixes for data-quality issues.

Only field-level normalizations are supported: strip stray whitespace,
repair case-mangled statuses, and fill a missing ``date_updated`` from
``date_added``. Fixes never delete records, never merge records, and
never invent data - ``apply_fixes`` only applies a fix to a record whose
id still exists, and anything not on the known-fix list is logged and
skipped.
"""

from __future__ import annotations

import copy

from candid import config as C
from candid.quality import Issue

STRIP_FIELDS = ("company", "role", "notes", "jd_link")


def _rid(rec: dict) -> str:
    return f"#{rec.get('id', '?')}"


def fix_strip_whitespace(rec: dict, args: dict) -> str | None:
    """Strip leading/trailing whitespace on free-text fields. Returns a log line."""
    changed = [f for f in STRIP_FIELDS
               if isinstance(rec.get(f), str)
               and rec[f] != rec[f].strip()]
    if not changed:
        return None
    for f in changed:
        rec[f] = rec[f].strip()
    return f"{_rid(rec)} strip_whitespace: trimmed {', '.join(changed)}"


def fix_normalize_status(rec: dict, args: dict) -> str | None:
    """Case-insensitive match of status into config.STATUSES. Returns a log line."""
    raw = str(rec.get("status", "") or "")
    cleaned = raw.strip()
    target = next((s for s in C.STATUSES if s.lower() == cleaned.lower()), None)
    if target is None or target == rec.get("status"):
        return None
    old = rec.get("status")
    rec["status"] = target
    return f"{_rid(rec)} normalize_status: {old!r} -> {target!r}"


def fix_fill_date_updated(rec: dict, args: dict) -> str | None:
    """Copy date_added into date_updated when date_updated is missing/empty."""
    if rec.get("date_updated"):
        return None
    added = rec.get("date_added")
    if not added:
        return None
    rec["date_updated"] = added
    return f"{_rid(rec)} fill_date_updated: set to date_added ({added})"


#: Known safe fixes; anything else is logged and skipped.
FIXERS = {
    "strip_whitespace": fix_strip_whitespace,
    "normalize_status": fix_normalize_status,
    "fill_date_updated": fix_fill_date_updated,
}


def apply_fixes(apps: list[dict], issues: list[Issue],
                dry_run: bool = True) -> tuple[list[dict], list[str]]:
    """Apply safe auto-fixes for issues that carry an ``auto_fix`` key.

    Returns ``(new_apps, log_lines)``. Input ``apps`` is never mutated -
    fixes are applied to copies. When ``dry_run`` is True nothing is
    persisted (the caller also skips the tracker save); log lines are
    prefixed accordingly.
    """
    new_apps = copy.deepcopy(apps)
    by_id = {a.get("id"): a for a in new_apps}
    log: list[str] = []
    mode = "(dry run) " if dry_run else ""
    n = 0
    for issue in issues:
        key = issue.auto_fix
        if not key:
            continue
        fixer = FIXERS.get(key)
        if fixer is None:
            log.append(f"{mode}skipped {key}: unknown auto-fix "
                       f"(record #{issue.record_id})")
            continue
        rec = by_id.get(issue.record_id)
        if rec is None:
            log.append(f"{mode}skipped {key}: no record #{issue.record_id} found")
            continue
        line = fixer(rec, issue.fix_args or {})
        if line is None:
            log.append(f"{mode}skipped {key}: nothing to change "
                       f"(#{issue.record_id})")
        else:
            n += 1
            log.append(f"{mode}{line}")
    log.append(f"{mode}{n} fix(es) applied.")
    return new_apps, log
