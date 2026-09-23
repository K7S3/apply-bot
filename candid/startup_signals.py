"""Hiring signals from candid's own curated job runs.

Computes per-company signals purely from local curation history
(``candid_data/jobs.json`` - the record of what ``jobs curate`` / ``refresh``
found), with no network and no scraping:

- posting velocity: curated postings per 30 days (last 30-day window)
- trend: growing / flat / shrinking vs the prior 30-day window
- new-vs-repeat: distinct role titles vs reposts of the same title

A missing or empty ``jobs.json`` means "no curation runs yet":
``compute_signals`` returns ``[]`` and the CLI says so plainly.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from candid import config as C


class StartupSignalError(Exception):
    """Raised for hiring-signal failures (e.g. bad CLI values)."""


#: Window length in days for velocity and trend comparisons.
WINDOW_DAYS = 30


def _jobs_path() -> Path:
    return C.DATA_DIR / "jobs.json"


def _load_seen() -> dict:
    """The jobs.json ``seen`` map (source_id -> tracker app id), defensively."""
    try:
        p = _jobs_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                seen = raw.get("seen")
                if isinstance(seen, dict):
                    return seen
    except (OSError, ValueError):
        pass
    return {}


def _parse_day(value: object) -> date | None:
    """Parse a tracker date_added value ("YYYY-MM-DD"). None when unusable."""
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def _norm_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _curated_postings() -> list[dict]:
    """All curated postings from jobs.json, enriched from the tracker.

    jobs.json stores only ``seen`` (source_id -> tracker app id); company,
    title, and curation date come from the matching tracker record, which is
    exactly the record ``jobs curate`` wrote when the posting was curated.
    Tracker entries that were never curated (no jobs.json entry) are excluded.
    """
    from candid import tracker as T
    apps = {str(a.get("id")): a for a in T.list_apps()}
    postings = []
    for source_id, app_id in _load_seen().items():
        rec = apps.get(str(app_id))
        if not isinstance(rec, dict):
            continue
        company = str(rec.get("company") or "").strip() or "(unknown company)"
        postings.append({
            "source_id": str(source_id),
            "company": company,
            "title": str(rec.get("role") or "").strip(),
            "day": _parse_day(rec.get("date_added")),
        })
    return postings


def _trend(recent: int, prior: int) -> str:
    if recent > prior:
        return "growing"
    if recent < prior:
        return "shrinking"
    return "flat"


def compute_signals(min_postings: int = 2,
                    now: date | None = None) -> list[dict]:
    """Compute per-company hiring signals from curated runs.

    Returns a list of dicts sorted by velocity (desc), then total postings
    (desc), then company name. Each dict has: company, postings_total,
    postings_per_30d (velocity), trend (growing/flat/shrinking),
    trend_detail, new, repeat, new_vs_repeat_ratio (None when no repeats),
    recent_titles.

    Companies with fewer than ``min_postings`` curated postings are skipped.
    Missing/empty jobs.json yields [].
    """
    if min_postings < 1:
        raise StartupSignalError("--min-postings must be at least 1.")
    now = now or date.today()
    recent_cutoff = now - timedelta(days=WINDOW_DAYS)
    prior_cutoff = now - timedelta(days=2 * WINDOW_DAYS)

    by_company: dict[str, list[dict]] = {}
    for post in _curated_postings():
        by_company.setdefault(post["company"], []).append(post)

    signals = []
    for company, posts in by_company.items():
        if len(posts) < min_postings:
            continue
        dated = [p for p in posts if p["day"] is not None]
        recent = [p for p in dated if p["day"] > recent_cutoff]
        prior = [p for p in dated if prior_cutoff < p["day"] <= recent_cutoff]
        trend = _trend(len(recent), len(prior))

        titles = {_norm_title(p["title"]) for p in posts if _norm_title(p["title"])}
        if titles:
            new = len(titles)
            repeat = len(posts) - new
        else:  # titles missing entirely: each posting counts as its own role
            new, repeat = len(posts), 0

        signals.append({
            "company": company,
            "postings_total": len(posts),
            "postings_per_30d": float(len(recent)),
            "trend": trend,
            "trend_detail": (f"{len(recent)} posting(s) in the last {WINDOW_DAYS}d "
                             f"vs {len(prior)} in the prior {WINDOW_DAYS}d"),
            "new": new,
            "repeat": repeat,
            "new_vs_repeat_ratio": (round(new / repeat, 2) if repeat else None),
            "recent_titles": sorted({p["title"] for p in recent if p["title"]}),
        })

    signals.sort(key=lambda s: (-s["postings_per_30d"], -s["postings_total"],
                                s["company"].lower()))
    return signals


def signals_by_company(min_postings: int = 1,
                       now: date | None = None) -> dict[str, dict]:
    """compute_signals keyed by lowercased company name (for ranking lookups)."""
    return {s["company"].lower(): s
            for s in compute_signals(min_postings=min_postings, now=now)}


def render_signals(signals: list[dict]) -> str:
    """Human-readable table of hiring signals."""
    if not signals:
        return ("No hiring signals yet: candid_data/jobs.json has no curated "
                "postings.\nNext: run `python -m candid jobs curate --role "
                "\"Your Role\"` to build some history.")
    lines = [f"{'Company':<28}{'Total':>6}{'30d':>5}  Trend     New/Repeat",
             "-" * 72]
    for s in signals:
        ratio = (f"{s['new_vs_repeat_ratio']:.2f}"
                 if s["new_vs_repeat_ratio"] is not None else "all new")
        lines.append(f"{s['company'][:28]:<28}{s['postings_total']:>6}"
                     f"{int(s['postings_per_30d']):>5}  {s['trend']:<9}"
                     f"{s['new']} new / {s['repeat']} repeat ({ratio})")
    return "\n".join(lines)
