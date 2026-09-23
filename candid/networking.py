"""One-page networking brief: who you are, highlights, what you want.

Everything is grounded in the profile. Target roles are used as given;
when none are given, a cautious inference from seniority + domain is
offered and explicitly labeled "(inferred)". The ask is user-supplied or
template prompts with ``[fill in]`` markers — never invented.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from candid import config as C


class NetworkingError(Exception):
    """Raised when a brief cannot be built from the profile."""


# ---------------------------------------------------------------------------
# bullet scoring (local heuristic: numbers, impact verbs, skill matches)
# ---------------------------------------------------------------------------

_IMPACT_VERBS = (
    "built", "led", "launched", "shipped", "designed", "drove", "owned",
    "improved", "reduced", "increased", "scaled", "automated", "architected",
    "mentored", "delivered", "migrated", "optimized", "pioneered",
)

_METRIC_RE = re.compile(
    r"\d+\s*(?:%|percent|x\b|million|billion|k\b|\$)|"
    r"\$[\d,]+|\d+\s*(?:ms|seconds?|minutes?|hours?|days?)",
    re.I,
)


def _bullet_score(bullet: str, skills: set[str]) -> float:
    """Impact score for a resume bullet (higher = more impressive)."""
    low = bullet.lower()
    score = 0.0
    if _METRIC_RE.search(bullet):
        score += 3.0
    elif re.search(r"\d", bullet):
        score += 1.5
    if any(v in low for v in _IMPACT_VERBS):
        score += 1.0
    score += 0.5 * sum(1 for s in skills if s in low)
    score += min(len(bullet) / 200, 0.5)  # slight preference for substance
    return score


def _top_bullets(profile: dict, limit: int = 3) -> list[tuple[str, str, str]]:
    """Strongest bullets across experience as (title, company, bullet)."""
    skills = {s.lower() for s in (profile.get("skills") or [])}
    scored: list[tuple[float, str, str, str]] = []
    for e in (profile.get("experience") or []):
        title = (e.get("title") or "").strip()
        company = (e.get("company") or "").strip()
        for b in (e.get("bullets") or []):
            text = str(b).strip()
            if text:
                scored.append((_bullet_score(text, skills), title, company, text))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(t, c, b) for _, t, c, b in scored[:limit]]


# ---------------------------------------------------------------------------
# inference helpers (always labeled as inferred)
# ---------------------------------------------------------------------------

def _infer_target_roles(profile: dict) -> list[str]:
    """Cautious target-role guess from seniority + domain, labeled inferred."""
    seniority = (profile.get("seniority") or "").strip()
    domains = [d for d in (profile.get("domains") or []) if d]
    titles = [(e.get("title") or "").strip() for e in (profile.get("experience") or [])]
    guesses: list[str] = []
    if titles:
        guesses.append(f"{titles[0]} (inferred)")
    if seniority and domains:
        cap = seniority.replace("-", " ").title()
        guesses.append(f"{cap} role in {domains[0]} (inferred)")
    return guesses[:2]


# conversation starters keyed on domain tags
_DOMAIN_STARTERS: dict[str, list[str]] = {
    "data science": [
        "What's the biggest modeling challenge your team is wrestling with right now?",
        "How does your team decide between a quick heuristic and a full ML solution?",
    ],
    "software engineering": [
        "What's the most interesting architectural decision your team made recently?",
        "How does your team balance shipping speed with reliability?",
    ],
    "ml platform / mlops": [
        "What does your model deployment pipeline look like today?",
        "What's the hardest part of keeping models reliable in production for you?",
    ],
    "ads / monetization": [
        "What's the biggest shift you've seen in ads ranking or monetization lately?",
        "How does your team measure the business impact of ranking changes?",
    ],
    "finance": [
        "How is your team thinking about AI/ML in trading or risk right now?",
        "What's the most interesting quant problem on your desk this year?",
    ],
    "product": [
        "How does your team decide what to build next?",
        "What metric does your team live and die by?",
    ],
    "research": [
        "What open problems is your group most excited about?",
        "How do you pick which ideas are worth the compute?",
    ],
    "data engineering": [
        "What does your data stack look like, and what would you change?",
        "What's your biggest data-quality headache right now?",
    ],
    "consulting": [
        "What kinds of client problems are most common in your practice right now?",
        "What's changed most about the work in the last couple of years?",
    ],
}

_GENERIC_STARTERS = [
    "What does a typical week look like on your team?",
    "What's the most interesting project your team has shipped recently?",
    "If you were starting in this role today, what would you focus on first?",
]


def _starters(profile: dict) -> list[str]:
    out: list[str] = []
    for domain in (profile.get("domains") or [])[:2]:
        out.extend(_DOMAIN_STARTERS.get(domain, []))
    if not out:
        out = list(_GENERIC_STARTERS)
    return out[:3]


# ---------------------------------------------------------------------------
# brief builder
# ---------------------------------------------------------------------------

def build_brief(profile: dict, target_roles: list[str] | None = None,
                ask: str | None = None) -> str:
    """Build a one-page networking brief in markdown.

    ``target_roles``: what you are looking for. If omitted and the profile
    has none, a cautious inference is offered, labeled "(inferred)".
    ``ask``: your specific ask; when omitted, template prompts with
    ``[fill in]`` markers are used instead of inventing one.
    """
    exp = [e for e in (profile.get("experience") or [])
           if e.get("title") or e.get("company")]
    if not exp:
        raise NetworkingError(
            "No experience entries in the profile — a networking brief "
            "needs at least one role to summarize."
        )

    name = (profile.get("name") or "[fill in: your name]").strip()
    headline = (profile.get("headline") or "").strip()
    location = (profile.get("location") or "").strip()
    current = exp[0]
    cur = ((current.get("title") or "").strip()
           + (f" at {(current.get('company') or '').strip()}"
              if (current.get("company") or "").strip() else ""))

    # --- who you are (2 lines) -------------------------------------------
    who_1 = f"{name}"
    if cur.strip():
        who_1 += f" — {cur.strip()}"
    who_1 += "."
    who_2_bits = []
    if headline:
        who_2_bits.append(headline)
    years = profile.get("years_experience")
    if years:
        who_2_bits.append(f"~{years} years of experience")
    if location:
        who_2_bits.append(f"based in {location}")
    who_2 = (" ".join(who_2_bits) + ".") if who_2_bits else \
        "[fill in: a one-line summary of your background]."

    # --- career highlights (top 3 bullets by impact) ---------------------
    highlights = _top_bullets(profile, limit=3)

    # --- what you're looking for -----------------------------------------
    roles = [str(t).strip() for t in (target_roles or []) if str(t).strip()]
    if not roles:
        roles = [str(t).strip()
                 for t in (profile.get("target_roles") or [])
                 if str(t).strip()]
    inferred = False
    if not roles:
        roles = _infer_target_roles(profile)
        inferred = True
    if not roles:
        looking = "- [fill in: the roles you're targeting]"
    else:
        looking = "\n".join(f"- {r}" for r in roles)
        if inferred:
            looking += "\n\n_Inferred from your seniority and domain — confirm or replace._"

    # --- your ask ----------------------------------------------------------
    if (ask or "").strip():
        ask_text = ask.strip()
    else:
        ask_text = (
            "- [fill in: your specific ask — e.g. an intro to the hiring "
            "manager, a 20-minute chat about the team, feedback on your "
            "background]\n"
            "- If they can't help directly: [fill in: who else should you "
            "talk to?]"
        )

    # --- build -------------------------------------------------------------
    lines = [
        f"# Networking Brief — {name}",
        "",
        "## Who I am",
        "",
        who_1,
        who_2,
        "",
        "## Career highlights",
        "",
    ]
    if highlights:
        for title, company, bullet in highlights:
            src = f" ({title}{', ' + company if company else ''})"
            lines.append(f"- {bullet}{src}")
    else:
        lines.append("- [fill in: your 2-3 strongest accomplishments]")
    lines += [
        "",
        "## What I'm looking for",
        "",
        looking,
        "",
        "## My ask",
        "",
        ask_text,
        "",
        "## Conversation starters",
        "",
    ]
    for s in _starters(profile):
        lines.append(f"- {s}")
    lines.append("")
    return "\n".join(lines)


def _data_dir() -> Path:
    """User data dir, honoring CANDID_DATA_DIR at call time."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def save_brief(profile: dict, target_roles: list[str] | None = None,
               ask: str | None = None,
               path: str | Path | None = None) -> Path:
    """Render ``build_brief`` and write it to a markdown file.

    Defaults to ``<DATA_DIR>/networking_brief.md``. Returns the Path written.
    """
    dest = Path(path) if path else _data_dir() / "networking_brief.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(build_brief(profile, target_roles=target_roles, ask=ask),
                    encoding="utf-8")
    return dest
