"""Application analytics: per-source funnels, time-to-response, source ranking.

Reads tracker records and answers "where do responses come from and how fast".
Records pre-dating the ``source``/``status_history`` fields (added with the
analytics feature) are handled defensively: missing sources bucket to
"unknown", and time-to-response falls back to date_updated for records already
in a response status, flagged as estimates.
"""

from __future__ import annotations

import statistics
from datetime import date
from pathlib import Path

from candid import config as C
from candid import tracker as T


class AnalyticsError(Exception):
    """Raised for invalid analytics requests."""


#: Bucket for records with no source recorded.
UNKNOWN_SOURCE = "unknown"

#: A record counts as "submitted" once it leaves the "saved" stage without
#: being withdrawn — submitted apps form the denominator of funnel rates.
SUBMITTED_STATUSES = {"applied"} | set(C.RESPONSE_STATUSES)


def _parse_day(value: object) -> date | None:
    """Parse an ISO date defensively; None on anything unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _source_of(rec: dict) -> str:
    src = (rec.get("source") or "").strip()
    return src if src else UNKNOWN_SOURCE


def _first_response(rec: dict) -> tuple[date | None, bool]:
    """First date the record entered a response status.

    Returns (response_date, estimated). The estimate fallback uses
    date_updated when the record is already in a response status but has no
    status_history (e.g. records written before history existed).
    """
    added = _parse_day(rec.get("date_added"))
    if added is None:
        return None, False
    history = rec.get("status_history")
    if isinstance(history, list):
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") in C.RESPONSE_STATUSES:
                day = _parse_day(entry.get("date"))
                if day is not None:
                    return day, False
    if rec.get("status") in C.RESPONSE_STATUSES:
        day = _parse_day(rec.get("date_updated"))
        if day is not None:
            return day, True
    return None, False


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _summarize_days(days: list[int]) -> dict:
    if not days:
        return {"count": 0, "avg_days": None, "median_days": None,
                "min_days": None, "max_days": None}
    return {
        "count": len(days),
        "avg_days": round(sum(days) / len(days), 1),
        "median_days": statistics.median(days),
        "min_days": min(days),
        "max_days": max(days),
    }


def funnel_by_source(path: str | Path | None = None) -> dict:
    """Per-source funnel: counts per status plus conversion rates.

    Rates are floats 0..1 (None when the denominator is 0):
    applied->response (any RESPONSE_STATUS), applied->interview
    (selected_for_interview or offer), applied->offer. The denominator is the
    number of submitted applications (status applied/rejected/
    selected_for_interview/offer).
    """
    apps = T._load(path)
    sources: dict[str, dict] = {}
    for a in apps:
        src = _source_of(a)
        bucket = sources.setdefault(src, {"applications": 0,
                                          "counts": {s: 0 for s in C.STATUSES}})
        bucket["applications"] += 1
        st = a.get("status", "saved")
        bucket["counts"][st] = bucket["counts"].get(st, 0) + 1
    for src, bucket in sources.items():
        counts = bucket["counts"]
        submitted = sum(counts.get(s, 0) for s in SUBMITTED_STATUSES)
        responses = sum(counts.get(s, 0) for s in C.RESPONSE_STATUSES)
        interviews = counts.get("selected_for_interview", 0) + counts.get("offer", 0)
        offers = counts.get("offer", 0)
        bucket["submitted"] = submitted
        bucket["response_rate"] = _rate(responses, submitted)
        bucket["interview_rate"] = _rate(interviews, submitted)
        bucket["offer_rate"] = _rate(offers, submitted)
    ordered = dict(sorted(sources.items(),
                          key=lambda kv: kv[1]["applications"], reverse=True))
    return {"total": len(apps), "sources": ordered}


def time_to_response(path: str | Path | None = None) -> dict:
    """Days from date_added to the first response status, overall + per company.

    Estimated dates (response status but no history — the fallback to
    date_updated) are counted under "estimated"; records with no determinable
    response date are counted under "unknown".
    """
    apps = T._load(path)
    overall_days: list[int] = []
    per_company: dict[str, list[int]] = {}
    estimated = 0
    unknown = 0
    for a in apps:
        resp_day, is_estimated = _first_response(a)
        if resp_day is None:
            unknown += 1
            continue
        added = _parse_day(a.get("date_added"))
        days = (resp_day - added).days if added else None
        if days is None:
            unknown += 1
            continue
        if is_estimated:
            estimated += 1
        overall_days.append(days)
        per_company.setdefault(a.get("company", "") or "(unknown)",
                               []).append(days)
    return {
        "overall": _summarize_days(overall_days),
        "by_company": {c: _summarize_days(d)
                       for c, d in sorted(per_company.items())},
        "estimated": estimated,
        "unknown": unknown,
        "total": len(apps),
    }


def sources_summary(path: str | Path | None = None) -> list[dict]:
    """Per-source leaderboard sorted by application count desc.

    Each row: source, applications, responses, interviews, offers,
    response_rate (float 0..1, None when no submitted applications).
    """
    funnel = funnel_by_source(path)
    rows = []
    for src, b in funnel["sources"].items():
        rows.append({
            "source": src,
            "applications": b["applications"],
            "responses": sum(b["counts"].get(s, 0) for s in C.RESPONSE_STATUSES),
            "interviews": b["counts"].get("selected_for_interview", 0)
                          + b["counts"].get("offer", 0),
            "offers": b["counts"].get("offer", 0),
            "response_rate": b["response_rate"],
        })
    return rows


def _pct(rate: float | None) -> str:
    return f"{rate * 100:.1f}%" if rate is not None else "n/a"


def render_funnel(funnel: dict) -> str:
    """Plain-text per-source funnel table."""
    sources = funnel.get("sources", {})
    if not sources:
        return "No applications tracked yet. Add one with: python -m candid track add --company X --role Y"
    lines = [f"{'Source':<16}{'Apps':>5}{'Subm':>6}{'Resp%':>8}{'Int%':>8}{'Offer%':>8}"]
    for src, b in sources.items():
        counts = b.get("counts", {})
        lines.append(
            f"{src[:15]:<16}{b.get('applications', 0):>5}"
            f"{b.get('submitted', 0):>6}"
            f"{_pct(b.get('response_rate')):>8}"
            f"{_pct(b.get('interview_rate')):>8}"
            f"{_pct(b.get('offer_rate')):>8}"
        )
        for st in C.STATUSES:
            n = counts.get(st, 0)
            if n:
                lines.append(f"    {st:<22} {n}")
    lines.append(f"\nTotal applications: {funnel.get('total', 0)}")
    return "\n".join(lines)


def render_response_times(ttr: dict) -> str:
    """Plain-text time-to-response table."""
    ov = ttr.get("overall", {})
    if not ov.get("count"):
        return "No responses recorded yet — time-to-response needs at least one application in a response status."
    lines = [
        "Time to first response (days from application to a reply):",
        "",
        f"{'Scope':<20}{'n':>4}{'avg':>7}{'median':>8}{'min':>6}{'max':>6}",
        f"{'overall':<20}{ov['count']:>4}{ov['avg_days']:>7}"
        f"{ov['median_days']:>8}{ov['min_days']:>6}{ov['max_days']:>6}",
    ]
    for company, s in ttr.get("by_company", {}).items():
        lines.append(f"{company[:19]:<20}{s['count']:>4}{s['avg_days']:>7}"
                     f"{s['median_days']:>8}{s['min_days']:>6}{s['max_days']:>6}")
    if ttr.get("estimated"):
        lines.append(f"\n{ttr['estimated']} response date(s) estimated from date_updated.")
    if ttr.get("unknown"):
        lines.append(f"{ttr['unknown']} application(s) with no determinable response date.")
    return "\n".join(lines)


def render_sources(rows: list[dict]) -> str:
    """Plain-text source leaderboard table."""
    if not rows:
        return "No applications tracked yet. Add one with: python -m candid track add --company X --role Y --source linkedin"
    lines = [f"{'Source':<18}{'Apps':>5}{'Resp':>6}{'Intv':>6}{'Offers':>7}{'Resp%':>8}"]
    for r in rows:
        lines.append(
            f"{r['source'][:17]:<18}{r['applications']:>5}{r['responses']:>6}"
            f"{r['interviews']:>6}{r['offers']:>7}{_pct(r['response_rate']):>8}"
        )
    return "\n".join(lines)
