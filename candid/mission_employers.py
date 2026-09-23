"""Mission-driven employers: a curated list of well-known nonprofits,
foundations, B Corps, and social enterprises, plus matching and boost
helpers so the watchlist coordinator can recognize and score them.

Pure local data and string logic - no network, no models. Org URLs are
the organizations' real domains (verified); `is_mission_employer`
normalizes company names (lowercase, strip corporate suffixes) and
resolves common aliases like "MSF" before matching.

`boost_for_watchlist` returns a 0-15 score bump the coordinator can add
into watchlist alert scoring; `mission_digest` / `render_digest` build
a compact weekly Markdown digest of mission-sector jobs and watchlist
hits at these employers.
"""

from __future__ import annotations

import re
from collections import Counter

# Cause keys intentionally mirror the mission_fit.py taxonomy so the
# coordinator can join them without translation.
VALID_CAUSES = frozenset(
    {
        "education",
        "health",
        "climate_environment",
        "human_rights",
        "poverty_hunger",
        "disaster_relief",
        "animals",
        "arts_culture",
        "economic_development",
        "peace_conflict",
        "gender_equality",
        "tech_for_good",
    }
)

VALID_TYPES = ("nonprofit", "bcorp", "social_enterprise", "foundation")

# ---------------------------------------------------------------------------
# MISSION_EMPLOYERS - every entry is a real, verifiably real organization.
# Each: {"name", "type", "cause", "url"}.
# ---------------------------------------------------------------------------
MISSION_EMPLOYERS: list[dict[str, str]] = [
    # --- nonprofits: education -------------------------------------------
    {"name": "Khan Academy", "type": "nonprofit", "cause": "education",
     "url": "https://www.khanacademy.org"},
    {"name": "Teach for America", "type": "nonprofit", "cause": "education",
     "url": "https://www.teachforamerica.org"},
    {"name": "Teach For All", "type": "nonprofit", "cause": "education",
     "url": "https://teachforall.org"},
    {"name": "Room to Read", "type": "nonprofit", "cause": "education",
     "url": "https://www.roomtoread.org"},
    {"name": "Code.org", "type": "nonprofit", "cause": "education",
     "url": "https://code.org"},
    # --- nonprofits: health / humanitarian --------------------------------
    {"name": "Doctors Without Borders", "type": "nonprofit", "cause": "health",
     "url": "https://www.doctorswithoutborders.org"},
    {"name": "American Red Cross", "type": "nonprofit", "cause": "disaster_relief",
     "url": "https://www.redcross.org"},
    {"name": "Crisis Text Line", "type": "nonprofit", "cause": "health",
     "url": "https://www.crisistextline.org"},
    {"name": "Save the Children", "type": "nonprofit", "cause": "poverty_hunger",
     "url": "https://www.savethechildren.org"},
    {"name": "Mercy Corps", "type": "nonprofit", "cause": "disaster_relief",
     "url": "https://www.mercycorps.org"},
    # --- nonprofits: environment ------------------------------------------
    {"name": "The Nature Conservancy", "type": "nonprofit",
     "cause": "climate_environment", "url": "https://www.nature.org"},
    {"name": "World Wildlife Fund", "type": "nonprofit",
     "cause": "climate_environment", "url": "https://www.worldwildlife.org"},
    {"name": "Wildlife Conservation Society", "type": "nonprofit",
     "cause": "climate_environment", "url": "https://www.wcs.org"},
    # --- nonprofits: human rights / tech for good --------------------------
    {"name": "Amnesty International", "type": "nonprofit", "cause": "human_rights",
     "url": "https://www.amnesty.org"},
    {"name": "Human Rights Watch", "type": "nonprofit", "cause": "human_rights",
     "url": "https://www.hrw.org"},
    {"name": "Electronic Frontier Foundation", "type": "nonprofit",
     "cause": "tech_for_good", "url": "https://www.eff.org"},
    {"name": "Creative Commons", "type": "nonprofit", "cause": "tech_for_good",
     "url": "https://creativecommons.org"},
    {"name": "Internet Archive", "type": "nonprofit", "cause": "tech_for_good",
     "url": "https://archive.org"},
    {"name": "Wikimedia Foundation", "type": "nonprofit", "cause": "tech_for_good",
     "url": "https://wikimediafoundation.org"},
    {"name": "Mozilla Foundation", "type": "nonprofit", "cause": "tech_for_good",
     "url": "https://foundation.mozilla.org"},
    # --- nonprofits: economic development / poverty ------------------------
    {"name": "Kiva", "type": "nonprofit", "cause": "economic_development",
     "url": "https://www.kiva.org"},
    {"name": "Acumen", "type": "nonprofit", "cause": "economic_development",
     "url": "https://acumen.org"},
    {"name": "BRAC", "type": "nonprofit", "cause": "economic_development",
     "url": "https://www.brac.net"},
    {"name": "Grameen Foundation", "type": "nonprofit", "cause": "economic_development",
     "url": "https://grameenfoundation.org"},
    {"name": "Ashoka", "type": "nonprofit", "cause": "economic_development",
     "url": "https://www.ashoka.org"},
    {"name": "Echoing Green", "type": "nonprofit", "cause": "economic_development",
     "url": "https://echoinggreen.org"},
    {"name": "Oxfam", "type": "nonprofit", "cause": "poverty_hunger",
     "url": "https://www.oxfam.org"},
    {"name": "charity: water", "type": "nonprofit", "cause": "health",
     "url": "https://www.charitywater.org"},
    {"name": "One Acre Fund", "type": "nonprofit", "cause": "poverty_hunger",
     "url": "https://oneacrefund.org"},
    # --- nonprofits: workforce / youth -------------------------------------
    {"name": "Goodwill Industries", "type": "nonprofit",
     "cause": "economic_development", "url": "https://www.goodwill.org"},
    {"name": "Boys & Girls Clubs of America", "type": "nonprofit",
     "cause": "education", "url": "https://www.bgca.org"},
    # --- foundations --------------------------------------------------------
    {"name": "Bill & Melinda Gates Foundation", "type": "foundation",
     "cause": "health", "url": "https://www.gatesfoundation.org"},
    {"name": "Rockefeller Foundation", "type": "foundation",
     "cause": "health", "url": "https://www.rockefellerfoundation.org"},
    {"name": "Ford Foundation", "type": "foundation", "cause": "human_rights",
     "url": "https://www.fordfoundation.org"},
    # --- B Corps ------------------------------------------------------------
    {"name": "Patagonia", "type": "bcorp", "cause": "climate_environment",
     "url": "https://www.patagonia.com"},
    {"name": "Ben & Jerry's", "type": "bcorp", "cause": "human_rights",
     "url": "https://www.benjerry.com"},
    {"name": "Allbirds", "type": "bcorp", "cause": "climate_environment",
     "url": "https://www.allbirds.com"},
    {"name": "Warby Parker", "type": "bcorp", "cause": "health",
     "url": "https://www.warbyparker.com"},
    {"name": "Coursera", "type": "bcorp", "cause": "education",
     "url": "https://www.coursera.org"},
    {"name": "Danone North America", "type": "bcorp", "cause": "health",
     "url": "https://www.danonenorthamerica.com"},
    {"name": "Etsy", "type": "bcorp", "cause": "economic_development",
     "url": "https://www.etsy.com"},
    # --- social enterprises --------------------------------------------------
    {"name": "Chan Zuckerberg Initiative", "type": "social_enterprise",
     "cause": "health", "url": "https://chanzuckerberg.com"},
    {"name": "Kickstarter", "type": "social_enterprise", "cause": "arts_culture",
     "url": "https://www.kickstarter.com"},
    {"name": "TOMS", "type": "social_enterprise", "cause": "poverty_hunger",
     "url": "https://www.toms.com"},
    {"name": "Newman's Own", "type": "social_enterprise", "cause": "poverty_hunger",
     "url": "https://www.newmansown.com"},
]

# Common short names / acronyms -> canonical employer name (pre-normalization).
ALIASES: dict[str, str] = {
    "msf": "Doctors Without Borders",
    "medecins sans frontieres": "Doctors Without Borders",
    "wwf": "World Wildlife Fund",
    "tfa": "Teach for America",
    "eff": "Electronic Frontier Foundation",
    "czi": "Chan Zuckerberg Initiative",
    "chan zuckerberg": "Chan Zuckerberg Initiative",
    "gates foundation": "Bill & Melinda Gates Foundation",
    "bill and melinda gates foundation": "Bill & Melinda Gates Foundation",
    "red cross": "American Red Cross",
    "wikimedia": "Wikimedia Foundation",
    "mozilla": "Mozilla Foundation",
    "goodwill": "Goodwill Industries",
}

# Corporate-sounding tokens stripped during normalization (also applied to
# stored names so both sides match; harmless because they're only suffixes).
_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "company", "co",
    "llc", "ltd", "limited", "plc", "foundation", "org", "the",
}

_name_index: dict[str, dict[str, str]] = {}


def _normalize(name: str) -> str:
    """Lowercase, drop punctuation/ampersands, strip corporate suffix tokens."""
    text = name.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t not in _SUFFIXES]
    return " ".join(tokens)


def _index() -> dict[str, dict[str, str]]:
    global _name_index
    if not _name_index:
        for rec in MISSION_EMPLOYERS:
            _name_index[_normalize(rec["name"])] = rec
    return _name_index


def is_mission_employer(company: str) -> dict | None:
    """Return the MISSION_EMPLOYERS record for *company*, or None.

    Matching is case-insensitive: the name is lowercased, corporate
    suffixes (Inc, LLC, Foundation, ...) are stripped, and common
    aliases ("MSF", "WWF", "CZI", ...) are resolved first.
    """
    if not company or not isinstance(company, str):
        return None
    # Alias lookup first, on the raw lowercased name (punctuation kept
    # minimal so "Ben & Jerry's" style names still work by normalization).
    raw = company.strip().lower()
    if raw.startswith("the "):
        raw = raw[4:]
    if raw in ALIASES:
        return _index().get(_normalize(ALIASES[raw]))
    key = _normalize(company)
    if key in ALIASES:
        return _index().get(_normalize(ALIASES[key]))
    return _index().get(key)


# Score bump added to watchlist alert scoring for a mission employer.
# Foundations signal the deepest mission commitment, then nonprofits;
# B Corps and social enterprises get a solid but smaller bump.
_TYPE_BOOST = {
    "foundation": 12,
    "nonprofit": 10,
    "bcorp": 8,
    "social_enterprise": 8,
}


def boost_for_watchlist(company: str) -> int:
    """Return a 0-15 score bump for *company*, 0 if not a mission employer.

    Designed to be added into watchlist alert scoring by the coordinator.
    """
    rec = is_mission_employer(company)
    if rec is None:
        return 0
    return _TYPE_BOOST.get(rec["type"], 5)


def mission_digest(
    profile: dict,
    new_jobs: list[dict],
    watchlist_hits: list[dict],
) -> dict:
    """Build a weekly digest of mission-sector activity.

    *profile*: candid profile dict (uses ``cause_interests`` when present).
    *new_jobs*: normalized job dicts (jobs.py schema); only postings at
    known mission employers are kept, each tagged with its employer record.
    *watchlist_hits*: coordinator hit dicts with at least ``company``; each
    is tagged with its employer record when the company is a mission
    employer. Pure function - no I/O.
    """
    interests = list((profile or {}).get("cause_interests") or [])

    mission_jobs = []
    for job in new_jobs or []:
        rec = is_mission_employer((job or {}).get("company", ""))
        if rec is None:
            continue
        mission_jobs.append({**job, "mission_employer": rec, "cause": rec["cause"]})

    mission_hits = []
    for hit in watchlist_hits or []:
        rec = is_mission_employer((hit or {}).get("company", ""))
        if rec is None:
            continue
        mission_hits.append({**hit, "mission_employer": rec, "cause": rec["cause"]})

    cause_counts = Counter(j["cause"] for j in mission_jobs)
    cause_counts.update(h["cause"] for h in mission_hits)

    if cause_counts:
        top = cause_counts.most_common(3)
        summary = (
            f"{len(mission_jobs)} new mission-sector posting(s) and "
            f"{len(mission_hits)} watchlist hit(s) across {len(cause_counts)} "
            "cause area(s): "
            + ", ".join(f"{cause} ({n})" for cause, n in top)
            + "."
        )
    else:
        summary = "No mission-sector postings or watchlist hits this week."

    return {
        "profile_name": (profile or {}).get("name", ""),
        "cause_interests": interests,
        "mission_jobs": mission_jobs,
        "watchlist_hits": mission_hits,
        "cause_breakdown": dict(cause_counts),
        "summary": summary,
    }


def render_digest(digest: dict) -> str:
    """Render a weekly mission digest as compact Markdown."""
    lines = ["# Mission Digest"]
    name = digest.get("profile_name")
    if name:
        lines.append(f"Prepared for **{name}**.")
    lines.append("")
    lines.append("## Summary")
    lines.append(digest.get("summary", ""))
    lines.append("")
    lines.append("## Mission-sector jobs")
    jobs = digest.get("mission_jobs") or []
    if not jobs:
        lines.append("_No new mission-sector postings this week._")
    for job in jobs:
        rec = job.get("mission_employer") or {}
        employer = rec.get("name", job.get("company", ""))
        title = job.get("title", "(untitled)")
        location = job.get("location", "")
        url = job.get("url", "")
        line = f"- **{employer}** - {title}"
        if location:
            line += f" ({location})"
        if url:
            line += f" - {url}"
        lines.append(line)
    lines.append("")
    lines.append("## Watchlist hits at mission employers")
    hits = digest.get("watchlist_hits") or []
    if not hits:
        lines.append("_No watchlist hits at mission employers this week._")
    for hit in hits:
        rec = hit.get("mission_employer") or {}
        employer = rec.get("name", hit.get("company", ""))
        note = hit.get("note") or hit.get("detail") or ""
        line = f"- **{employer}**"
        if note:
            line += f" - {note}"
        lines.append(line)
    breakdown = digest.get("cause_breakdown") or {}
    if breakdown:
        lines.append("")
        lines.append("## Cause breakdown")
        for cause, n in sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {cause}: {n}")
    return "\n".join(lines) + "\n"
