"""Job match scoring: score a job description against the user profile.

Score breakdown (0-100):
  - skills match (50 pts): fraction of JD-required skills present in the profile,
    weighted so must-have skills count double.
  - seniority match (25 pts): JD seniority level vs profile seniority/years.
  - domain/keyword match (15 pts): overlap of role-domain keywords.
  - title alignment (10 pts): role family similarity.

Also surfaces: matched skills, missing skills, gaps, a go / conditional /
no-go recommendation, and — when salary data exists — the market range for
the role (see candid.salary).
"""

from __future__ import annotations

import re
import urllib.request

from candid import config as C

_MUST_HAVE_RE = re.compile(
    r"(must have|required|requirements?|you have|you'll bring|qualifications)", re.I
)


class MatchError(Exception):
    """Raised when a JD cannot be obtained or scored."""


def fetch_jd(source: str, timeout: int = 25) -> str:
    """Get JD text from a URL, a file path, or raw pasted text."""
    from pathlib import Path
    s = (source or "").strip()
    if not s:
        raise MatchError("Empty job description input.")
    if s.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(s, headers={"User-Agent": "candid/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 200:
                raise MatchError("Fetched page had almost no readable text.")
            return text[:20000]
        except MatchError:
            raise
        except Exception as exc:
            raise MatchError(f"Could not fetch JD from URL: {exc}") from exc
    p = Path(s)
    if p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 50:
            raise MatchError(f"JD file {p} looks empty.")
        return text[:20000]
    # treat as pasted text
    if len(s) < 50:
        raise MatchError(
            "That doesn't look like a job description (too short). "
            "Paste the full JD text, or pass a URL / file path."
        )
    return s[:20000]


def _jd_skills(jd: str) -> tuple[set[str], set[str]]:
    """Return (must_have_skills, nice_to_have_skills) canonical names."""
    low = jd.lower()
    must: set[str] = set()
    nice: set[str] = set()
    # crude section split: text near "must have/required" counts double
    must_zone = _MUST_HAVE_RE.search(low)
    for canonical, aliases in C.SKILL_LEXICON.items():
        hit = any(C.skill_regex(a).search(low) for a in aliases)
        if not hit:
            continue
        # if the skill appears after a "requirements" header, treat as must-have
        is_must = True
        if must_zone:
            first_hit = min(
                (m.start() for a in aliases for m in C.skill_regex(a).finditer(low)),
                default=len(low),
            )
            is_must = first_hit > must_zone.start() - 2000
        (must if is_must else nice).add(canonical)
    return must, nice


def _jd_seniority(jd: str, title: str = "") -> int | None:
    text = f"{title} {jd[:1500]}".lower()
    best: int | None = None
    for kw, rank in C.SENIORITY_KEYWORDS.items():
        if kw in text:
            best = rank if best is None else max(best, rank)
    return best


# role-family keyword sets for title alignment
_ROLE_FAMILIES: dict[str, set[str]] = {
    "data_scientist": {"data scientist", "data science", "scientist"},
    "ml_engineer": {"machine learning engineer", "ml engineer", "applied scientist"},
    "data_analyst": {"data analyst", "analytics", "business intelligence"},
    "data_engineer": {"data engineer", "data engineering", "etl"},
    "quant": {"quant", "quantitative", "researcher", "trader"},
    "software_engineer": {"software engineer", "developer", "swe"},
    "product_manager": {"product manager"},
}


def _profile_role_family(profile: dict) -> str:
    titles = " ".join(e.get("title", "") for e in profile.get("experience", [])).lower()
    skills = set(profile.get("skills", []))
    for fam, kws in _ROLE_FAMILIES.items():
        if any(k in titles for k in kws):
            return fam
    if "deep learning" in skills or "llm" in skills:
        return "ml_engineer"
    if "machine learning" in skills:
        return "data_scientist"
    return "data_analyst"


def score_match(profile: dict, jd: str, title: str = "", company: str = "",
                location: str = "") -> dict:
    """Score the JD against the profile. Returns a full breakdown dict."""
    must, nice = _jd_skills(jd)
    pskills = set(profile.get("skills", []))

    must_hit = must & pskills
    nice_hit = nice & pskills
    denom = 2 * len(must) + len(nice)
    skills_score = round(50 * (2 * len(must_hit) + len(nice_hit)) / denom, 1) if denom else 25.0

    jd_level = _jd_seniority(jd, title)
    prof_years = float(profile.get("years_experience") or 0)
    prof_level = {"entry": 0, "junior": 1, "mid": 2, "senior": 3,
                  "lead": 4, "staff": 5, "principal": 6}.get(profile.get("seniority", "mid"), 2)
    if jd_level is None:
        seniority_score = 15.0
        seniority_note = "JD seniority unclear — scored neutrally."
    else:
        gap = abs(prof_level - jd_level)
        seniority_score = [25.0, 20.0, 12.0, 5.0][min(gap, 3)]
        want = C.SENIORITY_LABELS.get(jd_level, "?")
        have = profile.get("seniority", "?")
        seniority_note = f"JD looks '{want}', you read as '{have}'."
        if jd_level > prof_level + 1:
            seniority_note += " This role may be a stretch level-wise."

    # domain keywords: overlap of non-skill substantive words is too noisy;
    # use lexicon-adjacent domain terms instead.
    domain_terms = ["finance", "healthcare", "retail", "marketing", "fraud",
                    "recommendation", "ads", "risk", "supply chain", "genai"]
    jd_low, prof_text = jd.lower(), json_text(profile).lower()
    jd_domains = {t for t in domain_terms if t in jd_low}
    prof_domains = {t for t in domain_terms if t in prof_text}
    overlap = jd_domains & prof_domains
    domain_score = round(15 * len(overlap) / max(1, len(jd_domains)), 1) if jd_domains else 8.0

    # title alignment via role family
    fam = _profile_role_family(profile)
    fam_kws = _ROLE_FAMILIES[fam]
    title_score = 10.0 if any(k in (title + " " + jd[:300]).lower() for k in fam_kws) else 4.0

    total = round(skills_score + seniority_score + domain_score + title_score, 1)
    if total >= C.SCORE_STRONG_GO:
        verdict, reason = "GO", "Strong fit — worth a tailored application."
    elif total >= C.SCORE_CONDITIONAL_GO:
        verdict, reason = "CONDITIONAL", "Decent fit — apply if the team/mission excites you, and close the gaps below."
    else:
        verdict, reason = "NO-GO", "Weak fit — your time is probably better spent elsewhere."

    gaps: list[str] = []
    for s in sorted(must - pskills):
        gaps.append(f"Missing must-have skill: {s}")
    if jd_level is not None and jd_level > prof_level + 1:
        gaps.append(f"Seniority gap: role wants ~{C.SENIORITY_LABELS[jd_level]} level")
    if not overlap and jd_domains:
        gaps.append(f"No overlap on JD domain keywords: {sorted(jd_domains)[:4]}")

    market = _market_snapshot(company, title, location)

    return {
        "score": total,
        "verdict": verdict,
        "verdict_reason": reason,
        "breakdown": {
            "skills": skills_score,
            "seniority": seniority_score,
            "domain": domain_score,
            "title_alignment": title_score,
        },
        "skills_required": sorted(must | nice),
        "skills_matched": sorted(must_hit | nice_hit),
        "skills_missing": sorted((must | nice) - pskills),
        "seniority_note": seniority_note,
        "domain_overlap": sorted(overlap),
        "gaps": gaps,
        "market": market,
    }


def json_text(profile: dict) -> str:
    import json as _json
    return _json.dumps(profile)


def _market_snapshot(company: str, title: str, location: str) -> dict | None:
    """Best-effort market pay range for the role (None when unknown)."""
    try:
        from candid import salary
        if not company and not title:
            return None
        return salary.lookup(company=company, title=title, location=location)
    except Exception:
        return None


def render_report(result: dict, company: str = "", title: str = "") -> str:
    """Human-readable match report."""
    b = result["breakdown"]
    lines = [
        f"Match score: {result['score']}/100 — {result['verdict']}",
        result["verdict_reason"],
        "",
        f"  Skills      {b['skills']:>5}/50   matched {len(result['skills_matched'])}/{len(result['skills_required'])}",
        f"  Seniority   {b['seniority']:>5}/25   {result['seniority_note']}",
        f"  Domain      {b['domain']:>5}/15   overlap: {', '.join(result['domain_overlap']) or '—'}",
        f"  Title fit   {b['title_alignment']:>5}/10",
        "",
    ]
    if result["skills_matched"]:
        lines.append("Matched skills: " + ", ".join(result["skills_matched"]))
    if result["skills_missing"]:
        lines.append("Missing skills: " + ", ".join(result["skills_missing"]))
    if result["gaps"]:
        lines += ["", "Gaps to close:"] + [f"  • {g}" for g in result["gaps"]]
    m = result.get("market")
    if m and (m.get("p25") or m.get("low")):
        lines += ["", "Market pay (from salary intelligence): " + _fmt_market(m)]
    elif company or title:
        lines += ["", "Market pay: no data yet — import DOL LCA data or parse JDs to build it up."]
    return "\n".join(lines)


def _fmt_market(m: dict) -> str:
    parts = []
    if m.get("p25") and m.get("p75"):
        parts.append(f"${m['p25']:,.0f}–${m['p75']:,.0f}/yr (p25–p75, n={m.get('n', '?')})")
    elif m.get("low") and m.get("high"):
        parts.append(f"${m['low']:,.0f}–${m['high']:,.0f}/yr (posted range)")
    if m.get("source"):
        parts.append(f"[{m['source']}]")
    return " ".join(parts)
