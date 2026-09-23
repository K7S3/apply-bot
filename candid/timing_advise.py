"""Apply-now vs wait guidance and repost analysis (batch-25 advise).

Data-grounded: every claim cites the user's own tracker numbers or is
explicitly labeled a general heuristic. No market statistics are invented.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

from candid import timing as T

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _today() -> date:
    return date.today()


def _parse_iso(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        sys.exit(f"{label} must be a valid ISO date (YYYY-MM-DD); got {value!r}.")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def _n(n: int) -> str:
    return f"{n} application{'s' if n != 1 else ''}"


def _age_at_apply(app: dict) -> int | None:
    """How old the posting was (days) when the user applied. None if unknown."""
    posted = T.get_posted_date(app)
    applied = T.get_applied_date(app)
    if posted is None or applied is None:
        return None
    return (applied - posted).days


def _bucket_stats(apps: list[dict]) -> dict[str, dict]:
    """Per-bucket app lists + response rates, keyed by bucket name."""
    stats: dict[str, dict] = {b: {"apps": [], "rate": None} for b in T.BUCKETS}
    for app in apps:
        age = _age_at_apply(app)
        if age is None:
            continue
        bucket = T.bucket_posting_age(age)
        stats[bucket]["apps"].append(app)
    for bucket in T.BUCKETS:
        stats[bucket]["rate"] = T.response_rate(stats[bucket]["apps"])
    return stats


def _best_bucket(stats: dict[str, dict]) -> tuple[str, dict] | tuple[None, None]:
    """Bucket with the highest response rate among buckets with enough data."""
    candidates = [
        (b, s) for b, s in stats.items()
        if T.enough_data(s["apps"]) and s["rate"] is not None
    ]
    if not candidates:
        return None, None
    # Highest rate wins; ties go to the fresher bucket.
    order = {b: i for i, b in enumerate(T.BUCKETS)}
    candidates.sort(key=lambda item: (-item[1]["rate"], order[item[0]]))
    return candidates[0]


# ---------------------------------------------------------------------------
# repost detection (shared by advise + reposts)
# ---------------------------------------------------------------------------


def detect_reposts(apps: list[dict]) -> list[dict]:
    """Group applications into repost series.

    A series is a normalized (company, role) group with more than one
    record, or a single record whose notes mention "repost". Each series
    carries company, role, applications (oldest first), count, and a
    ``flagged_by_notes`` marker.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for app in apps:
        key = (_norm(app.get("company")), _norm(app.get("role")))
        groups.setdefault(key, []).append(app)

    series = []
    for (company, role), recs in groups.items():
        flagged = any("repost" in (r.get("notes") or "").lower() for r in recs)
        if len(recs) > 1 or flagged:
            ordered = sorted(
                recs,
                key=lambda r: (T.get_applied_date(r) or date.min),
            )
            series.append({
                "company": ordered[0].get("company", "").strip(),
                "role": ordered[0].get("role", "").strip(),
                "count": len(ordered),
                "flagged_by_notes": flagged and len(ordered) == 1,
                "applications": ordered,
            })
    series.sort(key=lambda s: (s["company"].lower(), s["role"].lower()))
    return series


def repost_report(apps: list[dict]) -> dict:
    """Machine-readable repost analysis: series + fresh-vs-repost aggregates."""
    series = detect_reposts(apps)
    firsts = [s["applications"][0] for s in series]
    reposts = [r for s in series for r in s["applications"][1:]]
    first_rate = T.response_rate(firsts)
    repost_rate = T.response_rate(reposts)

    if series:
        guidance = (
            f"Reposts convert at {_pct(repost_rate)} vs {_pct(first_rate)} for first "
            f"postings across {len(series)} repost series "
            f"({_n(len(reposts))} on reposts, {_n(len(firsts))} on first postings). "
            + ("When a role you want gets reposted, treat it as a fresh posting "
               "and apply quickly."
               if (repost_rate or 0) >= (first_rate or 0)
               else "First postings have converted better for you, so prioritize "
                    "fresh postings over re-applying to reposts.")
        )
    else:
        guidance = ("No reposts detected in your tracker, so there is no "
                    "fresh-vs-repost signal yet. It will appear once you apply "
                    "to the same role more than once.")

    def _entry(s: dict) -> dict:
        applied = [
            (T.get_applied_date(r) or date.min).isoformat()
            if T.get_applied_date(r) else "unknown"
            for r in s["applications"]
        ]
        return {
            "company": s["company"],
            "role": s["role"],
            "applications": s["count"],
            "dates_applied": applied,
            "statuses": [r.get("status") for r in s["applications"]],
            "flagged_by_notes": s["flagged_by_notes"],
        }

    return {
        "series": [_entry(s) for s in series],
        "aggregate": {
            "series_count": len(series),
            "first_postings": {
                "applications": len(firsts),
                "response_rate": first_rate,
            },
            "repost_applications": {
                "applications": len(reposts),
                "response_rate": repost_rate,
            },
        },
        "guidance": guidance,
    }


# ---------------------------------------------------------------------------
# advise: per-job apply-now vs wait guidance
# ---------------------------------------------------------------------------


def advise_for_job(company: str, role: str, posted: date,
                   deadline: date | None, apps: list[dict],
                   today: date | None = None) -> dict:
    """Pure analysis: verdict + reasons for one job. No printing."""
    today = today or _today()
    age = (today - posted).days
    bucket = T.bucket_posting_age(age)

    stats = _bucket_stats(apps)
    bucket_apps = stats[bucket]["apps"]
    bucket_rate = stats[bucket]["rate"]
    best_name, best = _best_bucket(stats)
    overall_rate = T.response_rate(apps)

    usable = sum(len(s["apps"]) for s in stats.values())
    skipped = len(apps) - usable

    repost_series = detect_reposts(apps)
    repost_signal = bool(repost_series)
    same_role_reposted = any(
        _norm(s["company"]) == _norm(company) and _norm(s["role"]) == _norm(role)
        for s in repost_series
    )

    reasons: list[str] = []
    changes: list[str] = []
    note = T.honesty_note(bucket_apps)

    # --- deadline first: it can end the conversation ----------------------
    days_left = (deadline - today).days if deadline else None
    if days_left is not None and days_left < 0:
        verdict = "NEUTRAL"
        reasons.append(
            f"Deadline passed on {deadline.isoformat()} "
            f"({-days_left} day{'s' if days_left != -1 else ''} ago)."
        )
        changes.append("Only apply if the posting is actually still live.")
    elif age <= 7:
        verdict = "APPLY NOW"
        reasons.append(
            f"Posting is {age} day{'s' if age != 1 else ''} old "
            f"(bucket '{bucket}')  -  fresh postings get priority review. "
            "(General heuristic, not from your data.)"
        )
        if T.enough_data(bucket_apps) and bucket_rate is not None:
            pos = sum(1 for a in bucket_apps if T.is_positive(a))
            reasons.append(
                f"Your tracker backs this up: {pos}/{len(bucket_apps)} positive "
                f"({_pct(bucket_rate)}) when you applied within '{bucket}'."
            )
        changes.append("Apply now; nothing about the timing argues for waiting.")
    elif best_name == bucket:
        verdict = "APPLY NOW"
        pos = sum(1 for a in bucket_apps if T.is_positive(a))
        reasons.append(
            f"'{bucket}' is your best posting-age bucket: {pos}/{len(bucket_apps)} "
            f"positive ({_pct(bucket_rate)})  -  and this posting is in it."
        )
        changes.append("Apply now; nothing about the timing argues for waiting.")
    elif age >= 31 and repost_signal:
        verdict = "CONSIDER WAITING"
        reasons.append(
            f"Posting is {age} days old ('{bucket}')  -  stale for most pipelines."
        )
        rep = repost_report(apps)["aggregate"]
        reasons.append(
            f"You have {rep['series_count']} repost series in your tracker; "
            f"reposts convert at {_pct(rep['repost_applications']['response_rate'])} "
            f"vs {_pct(rep['first_postings']['response_rate'])} for first postings."
        )
        if same_role_reposted:
            reasons.append(
                f"This exact role ({role} @ {company}) has been reposted before  -  "
                "a fresh repost is likely."
            )
        changes.append(
            "If the role is reposted, apply within 3 days of the new posting. "
            "Apply now only if the role is a strong fit you don't want to risk losing."
        )
    elif T.enough_data(bucket_apps) and (bucket_rate or 0) <= 0.05:
        verdict = "LOW PRIORITY"
        pos = sum(1 for a in bucket_apps if T.is_positive(a))
        reasons.append(
            f"Your tracker shows ~0 response in the '{bucket}' bucket: "
            f"{pos}/{len(bucket_apps)} positive ({_pct(bucket_rate)}) with a "
            f"decent sample of {len(bucket_apps)}."
        )
        changes.append(
            "Deprioritize this one; spend the effort on postings under 14 days old instead."
        )
    else:
        verdict = "NEUTRAL"
        if note:
            reasons.append(note)
        else:
            pos = sum(1 for a in bucket_apps if T.is_positive(a))
            reasons.append(
                f"Your '{bucket}' bucket: {pos}/{len(bucket_apps)} positive "
                f"({_pct(bucket_rate)})  -  not clearly good or bad."
            )
        if overall_rate is not None and T.enough_data(apps):
            reasons.append(
                f"Your overall positive rate is {_pct(overall_rate)} across "
                f"{_n(len(apps))}  -  this posting sits near your average."
            )
        changes.append(
            "A repost, a referral, or a deadline would change this verdict."
        )

    if skipped:
        reasons.append(
            f"({_n(skipped)} in your tracker lacked posting/applied dates "
            "and were excluded from bucket stats.)"
        )

    if days_left is not None and days_left >= 0:
        if days_left == 0:
            urgency = "Deadline is today  -  apply now or not at all."
        elif days_left <= 3:
            urgency = f"Only {days_left} day{'s' if days_left != 1 else ''} left  -  urgent."
        elif days_left <= 7:
            urgency = f"{days_left} days left  -  apply this week."
        else:
            urgency = f"{days_left} days left before the deadline."
    else:
        urgency = None

    return {
        "verdict": verdict,
        "company": company,
        "role": role,
        "posted_date": posted.isoformat(),
        "posting_age_days": age,
        "age_bucket": bucket,
        "deadline": deadline.isoformat() if deadline else None,
        "days_until_deadline": days_left,
        "deadline_urgency": urgency,
        "reasons": reasons[:4],
        "what_would_change_verdict": changes,
        "honesty_note": note,
        "bucket_stats": {
            b: {
                "applications": len(s["apps"]),
                "response_rate": s["rate"],
                "enough_data": T.enough_data(s["apps"]),
            }
            for b, s in stats.items()
        },
        "overall_response_rate": overall_rate,
        "repost_series_count": len(repost_series),
    }


def _render_advise(result: dict) -> str:
    lines = [
        f"{result['role']} @ {result['company']}",
        f"Verdict: {result['verdict']}",
        f"Posted {result['posted_date']}  -  {result['posting_age_days']} days old "
        f"(bucket '{result['age_bucket']}').",
    ]
    if result["deadline_urgency"]:
        lines.append(f"Deadline {result['deadline']}: {result['deadline_urgency']}")
    lines.append("")
    lines.append("Why:")
    for r in result["reasons"]:
        lines.append(f"  - {r}")
    lines.append("")
    lines.append("What would change the verdict:")
    for c in result["what_would_change_verdict"]:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def cmd_advise(a) -> None:
    """CLI entry: per-job apply-now vs wait guidance."""
    posted_raw = getattr(a, "posted_date", None)
    if not posted_raw:
        sys.exit("--posted-date is required (YYYY-MM-DD).")
    posted = _parse_iso(posted_raw, "--posted-date")
    deadline_raw = getattr(a, "deadline", None)
    deadline = _parse_iso(deadline_raw, "--deadline") if deadline_raw else None
    apps = T.load_applications()
    result = advise_for_job(
        getattr(a, "company", "") or "",
        getattr(a, "role", "") or "",
        posted, deadline, apps,
    )
    if getattr(a, "json", False):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(_render_advise(result))


# ---------------------------------------------------------------------------
# reposts: repost detection + fresh-vs-repost analysis
# ---------------------------------------------------------------------------


def _render_reposts(report: dict) -> str:
    if not report["series"]:
        return ("No reposts detected in your tracker yet.\n"
                "Apply to the same company+role more than once (or note "
                "\"repost\" on a record) and the series will show up here.")
    lines = [f"{len(report['series'])} repost series detected:\n"]
    for s in report["series"]:
        flag = " [flagged via notes]" if s["flagged_by_notes"] else ""
        lines.append(f"{s['role']} @ {s['company']}  -  {s['applications']} applications{flag}")
        for d, st in zip(s["dates_applied"], s["statuses"]):
            lines.append(f"    {d}: {st}")
        lines.append("")
    agg = report["aggregate"]
    lines.append(
        f"First postings: {_pct(agg['first_postings']['response_rate'])} "
        f"({_n(agg['first_postings']['applications'])}) | "
        f"Reposts: {_pct(agg['repost_applications']['response_rate'])} "
        f"({_n(agg['repost_applications']['applications'])})"
    )
    lines.append("")
    lines.append(report["guidance"])
    return "\n".join(lines)


def cmd_reposts(a) -> None:
    """CLI entry: repost detection + fresh-vs-repost analysis."""
    report = repost_report(T.load_applications())
    if getattr(a, "json", False):
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_render_reposts(report))
