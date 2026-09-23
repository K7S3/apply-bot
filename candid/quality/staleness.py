"""Staleness checks: expired-looking saved postings, untouched saved records,
and source-coverage gaps."""

from __future__ import annotations

from datetime import date, timedelta

from candid.quality import Issue

STALE_JD_DAYS = 90
STALE_SAVED_DAYS = 60


def run(apps, ctx) -> list[Issue]:
    today = ctx.get("today") or date.today()
    issues: list[Issue] = []
    issues.extend(_stale_jd(apps, today))
    issues.extend(_stale_saved(apps, today))
    issues.extend(_source_coverage(apps))
    return issues


def _parse_date(value):
    """Best-effort parse of an ISO date string; returns None if unusable."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _stale_jd(apps, today: date) -> list[Issue]:
    """Saved postings with a JD link added > 90 days ago are likely expired."""
    issues: list[Issue] = []
    cutoff = today - timedelta(days=STALE_JD_DAYS)
    for app in apps or []:
        if app.get("status") != "saved":
            continue
        if not app.get("jd_link") or not str(app.get("jd_link")).strip():
            continue
        added = _parse_date(app.get("date_added"))
        if added is None or added >= cutoff:
            continue
        record_id = app.get("id")
        issues.append(Issue(
            check="stale_jd",
            severity="warning",
            record_id=record_id,
            message=f"Record {record_id}: saved {STALE_JD_DAYS}+ days ago, "
                    "posting may have expired.",
            suggestion="Re-verify the posting link is still live, or archive "
                       f"the record with `candid track update {record_id}`.",
        ))
    return issues


def _stale_saved(apps, today: date) -> list[Issue]:
    """Saved records untouched for 60+ days with no JD link get a nudge."""
    issues: list[Issue] = []
    cutoff = today - timedelta(days=STALE_SAVED_DAYS)
    for app in apps or []:
        if app.get("status") != "saved":
            continue
        if app.get("jd_link") and str(app.get("jd_link")).strip():
            continue
        updated = _parse_date(app.get("date_updated"))
        if updated is None or updated >= cutoff:
            continue
        record_id = app.get("id")
        issues.append(Issue(
            check="stale_saved",
            severity="info",
            record_id=record_id,
            message=f"Record {record_id}: untouched for {STALE_SAVED_DAYS}+ days "
                    "and has no job-posting link.",
            suggestion="Add the JD link with `candid track update <id>`, or drop "
                       "the record if you are no longer interested.",
        ))
    return issues


def _source_coverage(apps) -> list[Issue]:
    """Report what fraction of records carry a non-empty source field."""
    records = apps or []
    if not records:
        return []
    with_source = sum(
        1 for app in records
        if app.get("source") and str(app.get("source")).strip()
    )
    coverage = with_source / len(records)
    if coverage >= 1.0:
        return []
    return [Issue(
        check="source_coverage",
        severity="info",
        record_id=None,
        message=f"Only {coverage:.0%} of {len(records)} records have a source recorded.",
        suggestion="Backfill 'source' (e.g. job board, referral, outreach) on "
                   "your records with `candid track update <id>` so you know "
                   "which channels work best.",
    )]
