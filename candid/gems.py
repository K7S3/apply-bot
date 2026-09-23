"""Hidden-gem detector: find postings with high fit and low competition.

A "hidden gem" is a posting where a strong candidate likely faces a small
applicant pool: fresh, rarely reposted, from a low-volume or obscure
employer, on a niche board, without salary transparency drawing crowds, and
not remote (remote postings pull national applicant pools).

Scoring model — every signal below is an honest heuristic, documented with
its assumption. No signal is a measured applicant count.

  competition_score (0-100, higher = LESS competition):
    - freshness (25%): posted_at parsed with the same tolerant logic as
      jobs._parse_posted_at (copied here, not imported, since it is
      private). Score decays linearly to 0 over 21 days. Unparseable dates
      score neutral (50); future-dated scores 100. Assumption: older
      postings are closer to filled, or buried under newer ones.
    - repost rarity (20%): (company, title) duplicates inside the batch are
      treated as reposts/relistings; fewer copies = less competition.
      Assumption: the same title+company on several boards is usually the
      same role being pushed hard.
    - company volume (20%): employers flooding the batch are treated as
      high-competition (megacorp-style hiring funnels). Assumption: posting
      volume proxies applicant volume.
    - source niche (15%): niche boards (hn_hiring, greenhouse, lever)
      outrank mass boards (arbeitnow, remoteok). Assumption: board audience
      size proxies applicant volume.
    - salary opacity (10%): a disclosed salary draws more applicants, so a
      posting *without* salary_text scores higher. Small effect.
    - remote pool (10%): remote=True draws a national pool; on-site/hybrid
      draws a local one. Small effect.

  gem_score:
    - with a profile: 0.65 * fit + 0.35 * competition, where fit comes from
      jobs.score_job(profile, job)["score"] (0-100).
    - without a profile: competition only, fit_score=None.

GEM_THRESHOLD (60.0) is the cutoff top_gems() uses: a posting counts as a
"gem" at or above it.

No network calls, no keys, no scraping. Deterministic for fixed inputs
(posted_at is compared against the clock, so scores age naturally).
"""

from __future__ import annotations

import re
from datetime import datetime

GEM_THRESHOLD = 60.0

# ---------------------------------------------------------------------------
# posted_at parsing (copy of jobs._parse_posted_at logic — private there,
# so duplicated here rather than imported)
# ---------------------------------------------------------------------------

def _parse_posted_at(raw: str) -> datetime | None:
    """Parse a posted_at value defensively. None when unparseable.

    Accepts ISO strings ('2026-09-20', '2026-09-20T10:00:00Z'),
    epoch seconds/millis, and a few common date formats.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10}(\.\d+)?", s):
        try:
            return datetime.fromtimestamp(float(s))
        except (ValueError, OSError, OverflowError):
            return None
    if re.fullmatch(r"\d{13}", s):
        try:
            return datetime.fromtimestamp(int(s) / 1000)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y",
                "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


def _age_days(job: dict, now: datetime | None = None) -> float | None:
    """Age of the posting in days, or None when posted_at is unparseable."""
    now = now or datetime.now()
    posted = _parse_posted_at(job.get("posted_at", ""))
    if posted is None:
        return None
    if posted > now:
        return 0.0
    return (now - posted).total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------

def _norm_company(company: str) -> str:
    """Normalized company key for grouping (lowercased, punctuation-free)."""
    return re.sub(r"[^a-z0-9]+", " ", (company or "").lower()).strip()


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


# ---------------------------------------------------------------------------
# competition signals — each returns 0-100, higher = less competition
# ---------------------------------------------------------------------------

FRESHNESS_WINDOW_DAYS = 21.0

_SOURCE_NICHE: dict[str, float] = {
    # niche boards first (smaller, more targeted audiences)
    "hn_hiring": 100.0,
    "greenhouse": 90.0,
    "lever": 85.0,
    "ashby": 85.0,
    "workable": 75.0,
    "wellfound": 70.0,
    "angellist": 70.0,
    # mass boards (huge audiences)
    "remoteok": 55.0,
    "arbeitnow": 50.0,
    "adzuna": 50.0,
    "reed": 50.0,
}


def _sig_freshness(job: dict) -> tuple[float, str]:
    """Freshness signal: decays linearly to 0 over ~21 days."""
    age = _age_days(job)
    if age is None:
        return 50.0, "posted date unknown"
    if age <= 0:
        return 100.0, "posted today"
    score = max(0.0, 100.0 * (1.0 - age / FRESHNESS_WINDOW_DAYS))
    return round(score, 1), f"posted {age:.0f}d ago"


def _repost_counts(all_jobs: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for j in all_jobs:
        key = (_norm_title(j.get("title", "")), _norm_company(j.get("company", "")))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sig_reposts(job: dict, all_jobs: list[dict] | None) -> tuple[float, str]:
    """Repost rarity: fewer (company, title) copies in the batch = better."""
    if not all_jobs:
        # no batch to compare against — stay neutral, say so
        return 70.0, "repost count unknown (no batch)"
    counts = _repost_counts(all_jobs)
    copies = counts.get((_norm_title(job.get("title", "")),
                         _norm_company(job.get("company", ""))), 1)
    score = 100.0 / (1.0 + (copies - 1))
    note = "single listing" if copies == 1 else f"listed {copies}x across sources"
    return round(score, 1), note


def _company_counts(all_jobs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for j in all_jobs:
        key = _norm_company(j.get("company", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sig_company_volume(job: dict, all_jobs: list[dict] | None) -> tuple[float, str]:
    """Company volume: employers with few batch postings score better."""
    if not all_jobs:
        return 70.0, "employer volume unknown (no batch)"
    counts = _company_counts(all_jobs)
    n = counts.get(_norm_company(job.get("company", "")), 1)
    score = 100.0 / (1.0 + (n - 1) / 4.0)
    note = "sole posting from this employer" if n == 1 else f"{n} postings from this employer"
    return round(score, 1), note


def _sig_source(job: dict) -> tuple[float, str]:
    """Source niche: niche boards outrank mass boards."""
    source = (job.get("source") or "").lower().strip()
    if source in _SOURCE_NICHE:
        score = _SOURCE_NICHE[source]
        note = f"{'niche' if score >= 75 else 'mass-market'} source ({source})"
    else:
        score = 55.0
        note = f"unknown source ({source or 'none'})"
    return score, note


def _sig_salary_opacity(job: dict) -> tuple[float, str]:
    """Salary opacity: no disclosed salary = fewer salary-shoppers."""
    if (job.get("salary_text") or "").strip():
        return 70.0, "salary disclosed (draws more applicants)"
    return 100.0, "salary not disclosed"


def _sig_remote_pool(job: dict) -> tuple[float, str]:
    """Remote pool: remote postings compete nationally."""
    if job.get("remote"):
        return 80.0, "remote (national applicant pool)"
    return 100.0, "on-site/hybrid (local applicant pool)"


_SIGNAL_WEIGHTS: dict[str, float] = {
    "freshness": 0.25,
    "repost_rarity": 0.20,
    "company_volume": 0.20,
    "source_niche": 0.15,
    "salary_opacity": 0.10,
    "remote_pool": 0.10,
}


def _competition_score(job: dict, all_jobs: list[dict] | None) -> tuple[float, dict]:
    """Weighted competition score (0-100, higher = less competition)."""
    signals = {
        "freshness": _sig_freshness(job)[0],
        "repost_rarity": _sig_reposts(job, all_jobs)[0],
        "company_volume": _sig_company_volume(job, all_jobs)[0],
        "source_niche": _sig_source(job)[0],
        "salary_opacity": _sig_salary_opacity(job)[0],
        "remote_pool": _sig_remote_pool(job)[0],
    }
    total = sum(signals[k] * _SIGNAL_WEIGHTS[k] for k in signals)
    return round(total, 1), signals


def _build_reasons(job: dict, fit: float | None, signals: dict,
                   all_jobs: list[dict] | None) -> list[str]:
    """Short human-readable notes for the strongest signals."""
    reasons: list[str] = []
    if fit is not None:
        reasons.append(f"profile fit {fit:.0f}/100")
    age = _age_days(job)
    if age is not None and age <= 3:
        reasons.append("fresh posting (<= 3 days old)")
    elif age is not None and age > FRESHNESS_WINDOW_DAYS:
        reasons.append(f"stale posting ({age:.0f}d old)")
    if all_jobs:
        counts = _repost_counts(all_jobs)
        copies = counts.get((_norm_title(job.get("title", "")),
                             _norm_company(job.get("company", ""))), 1)
        if copies == 1:
            reasons.append("not reposted across sources")
        elif copies >= 3:
            reasons.append(f"reposted {copies}x (crowded)")
        vol = _company_counts(all_jobs).get(_norm_company(job.get("company", "")), 1)
        if vol == 1:
            reasons.append("sole posting from this employer")
        elif vol >= 10:
            reasons.append("high-volume employer")
    if signals["source_niche"] >= 75:
        reasons.append(f"niche source ({job.get('source')})")
    elif signals["source_niche"] <= 55:
        reasons.append(f"mass-market source ({job.get('source')})")
    if not (job.get("salary_text") or "").strip():
        reasons.append("no salary disclosed")
    if not job.get("remote"):
        reasons.append("on-site/hybrid role")
    return reasons[:6]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def gem_score(job: dict, profile: dict | None = None,
              all_jobs: list[dict] | None = None) -> dict:
    """Score one job as a hidden gem.

    Returns {"gem_score": 0-100, "fit_score": float|None, "signals": dict,
    "reasons": [str], "sleeper": bool, "megacorp": bool}.

    With a profile, gem = 0.65 * fit + 0.35 * competition; without one, gem
    is the pure competition score and fit_score is None.
    """
    from candid import jobs as J

    fit: float | None = None
    if profile is not None:
        try:
            fit = float(J.score_job(profile, job)["score"])
        except Exception:
            fit = None
    competition, signals = _competition_score(job, all_jobs)
    if fit is not None:
        gem = round(0.65 * fit + 0.35 * competition, 1)
    else:
        gem = competition
    batch = all_jobs if all_jobs else [job]
    sleeper = sleeper_posting(job)
    if all_jobs:
        copies = _repost_counts(all_jobs).get(
            (_norm_title(job.get("title", "")), _norm_company(job.get("company", ""))), 1)
        sleeper = sleeper and copies <= 2
    return {
        "gem_score": gem,
        "fit_score": fit,
        "signals": signals,
        "reasons": _build_reasons(job, fit, signals, all_jobs),
        "sleeper": sleeper,
        "megacorp": is_megacorp(job.get("company", ""), batch),
    }


def top_gems(jobs: list[dict], profile: dict | None = None, limit: int = 15,
             exclude_megacorps: bool = False, min_fit: float = 0.0) -> list[dict]:
    """Top hidden gems: score, filter, and rank.

    Keeps postings at/above GEM_THRESHOLD, drops megacorps when
    ``exclude_megacorps`` is set, drops postings whose fit_score is below
    ``min_fit`` (postings with no fit score only survive min_fit <= 0), then
    returns the top ``limit`` sorted by gem_score (ties broken
    deterministically). Each returned job is a copy with a "_gem" key holding
    its gem_score() result; the input dicts are never mutated.
    """
    scored: list[tuple[float, dict, dict]] = []
    for job in jobs:
        if exclude_megacorps and is_megacorp(job.get("company", ""), jobs):
            continue
        g = gem_score(job, profile, all_jobs=jobs)
        fit = g["fit_score"]
        if fit is None:
            if min_fit > 0:
                continue
        elif fit < min_fit:
            continue
        if g["gem_score"] < GEM_THRESHOLD:
            continue
        scored.append((g["gem_score"], job, g))
    scored.sort(key=lambda t: (-t[0], _norm_company(t[1].get("company", "")),
                               _norm_title(t[1].get("title", "")),
                               str(t[1].get("source_id", ""))))
    out = []
    for _gem_val, job, g in scored[:max(0, limit)]:
        copy = dict(job)
        copy["_gem"] = g
        out.append(copy)
    return out


# ---------------------------------------------------------------------------
# employer-level analysis
# ---------------------------------------------------------------------------

# Brand names whose sheer recognition draws crowds regardless of batch
# volume. Heuristic, deliberately short — volume ranking does the real work.
_KNOWN_MEGACORPS = {
    "google", "alphabet", "meta", "facebook", "instagram", "whatsapp",
    "amazon", "aws", "microsoft", "apple", "netflix", "nvidia", "tesla",
    "oracle", "ibm", "salesforce", "adobe", "uber", "lyft", "airbnb",
    "linkedin", "tiktok", "bytedance", "samsung", "intel",
}


def is_megacorp(company: str, jobs: list[dict], top_n: int = 10) -> bool:
    """True when the company looks like a high-competition employer.

    Two independent heuristics: the normalized name contains a known giant's
    brand token, or the company ranks in the top_n employers by posting
    volume within the batch.
    """
    norm = _norm_company(company)
    if not norm:
        return False
    tokens = set(norm.split())
    if tokens & _KNOWN_MEGACORPS:
        return True
    if not jobs or top_n <= 0:
        return False
    counts = _company_counts(jobs)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return norm in {name for name, _ in ranked[:top_n]}


SLEEPER_DAYS = 45


def sleeper_posting(job: dict) -> bool:
    """True for old-but-still-listed postings (posted > 45 days ago).

    "Still listed" is taken as given: the job arrived in a live source
    batch, so it was listed at fetch time. Unparseable dates -> False.
    The stricter gem_score() "sleeper" flag additionally requires a low
    repost count when a batch is available.
    """
    age = _age_days(job)
    return age is not None and age > SLEEPER_DAYS


# Generic corporate filler words: company names built mostly from these are
# harder to search for and remember, which adds to obscurity.
_GENERIC_NAME_TOKENS = {
    "labs", "lab", "solutions", "systems", "technologies", "technology",
    "tech", "group", "partners", "global", "digital", "data", "ventures",
    "capital", "studio", "studios", "works", "media", "services", "inc",
    "llc", "corp", "corporation", "co", "ltd", "holdings", "consulting",
    "software", "analytics", "ai", "io",
}


def _name_genericness(company: str) -> float:
    """Fraction of company-name tokens that are generic filler (0-1)."""
    toks = [t for t in _norm_company(company).split() if t]
    if not toks:
        return 0.0
    generic = sum(1 for t in toks if t in _GENERIC_NAME_TOKENS)
    return generic / len(toks)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _employer_median_salary(company_jobs: list[dict]) -> float | None:
    """Median of per-posting salary midpoints (USD/yr), None when unknown."""
    from candid import salary as S
    mids: list[float] = []
    for j in company_jobs:
        parsed = S.parse_posted_range(
            (j.get("description") or "") + " " + (j.get("salary_text") or ""))
        if parsed:
            mids.append((parsed["low"] + parsed["high"]) / 2.0)
    med = _median(mids)
    return round(med, 2) if med is not None else None


def employer_ranking(jobs: list[dict]) -> list[dict]:
    """Rank employers in the batch by hidden-gem potential.

    Each entry: {"company", "postings", "obscurity" (0-100, higher = more
    obscure), "median_salary_usd" | None, "velocity" (postings/day heuristic),
    "gem_employer_score" (0-100)}.

    obscurity = 0.7 * (share-based rarity) + 0.3 * (generic-name factor):
    rare-in-batch employers score high, and employers with generic,
    hard-to-search names get a bump. gem_employer_score = 0.55 * obscurity
    + 0.25 * (low-volume bonus) + 0.20 * (salary-data bonus: 100 when a
    median salary is known, else 40).
    """
    total = len(jobs)
    if not total:
        return []
    by_company: dict[str, list[dict]] = {}
    display: dict[str, str] = {}
    for j in jobs:
        key = _norm_company(j.get("company", ""))
        by_company.setdefault(key, []).append(j)
        name = (j.get("company") or "").strip() or "(unknown)"
        # most common original spelling wins as the display name
        display[key] = name

    ranked = []
    for key, cjobs in by_company.items():
        n = len(cjobs)
        volume_part = 100.0 * (1.0 - n / total)
        generic_part = 100.0 * _name_genericness(display[key])
        obscurity = round(0.7 * volume_part + 0.3 * generic_part, 1)
        median_salary = _employer_median_salary(cjobs)
        dates = sorted(d for d in
                       (_parse_posted_at(j.get("posted_at", "")) for j in cjobs)
                       if d is not None)
        span = (dates[-1] - dates[0]).days + 1 if len(dates) >= 2 else 1
        velocity = round(n / span, 3)
        low_volume_bonus = 100.0 / (1.0 + (n - 1) / 4.0)
        salary_bonus = 100.0 if median_salary is not None else 40.0
        gem_employer_score = round(
            0.55 * obscurity + 0.25 * low_volume_bonus + 0.20 * salary_bonus, 1)
        ranked.append({
            "company": display[key],
            "postings": n,
            "obscurity": obscurity,
            "median_salary_usd": median_salary,
            "velocity": velocity,
            "gem_employer_score": gem_employer_score,
        })
    ranked.sort(key=lambda e: (-e["gem_employer_score"], -e["obscurity"],
                               e["company"].lower()))
    return ranked
