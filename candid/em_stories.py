"""Engineering-Manager story bank + team-health narratives.

Two halves, both strictly grounded in the user's profile (the profile.json
format produced by candid/profile.py):

1. EM STAR story prompts (`build_em_stories` / `list_em_stories`) —
   competency-tagged story prompts built from the user's resume bullets,
   using EM-specific competencies: hiring bar, growing engineers, managing
   up, incident leadership, cross-team influence, and org design. Mirrors
   the pattern of candid/stories.py but tags for what EM interviews probe.

2. Team-health storytelling (`em_narrative`) — turns management experience
   in the profile into narrative scaffolds for prompts like "tell me about
   a struggling team you inherited". The narrative is built ONLY from
   profile text; when the profile lacks management evidence, it says so
   plainly and lists what is missing instead of inventing a story.

Stories are stored in DATA_DIR / "em_stories.json".

Usage:
    from candid import profile as P, em_stories as E
    prof = P.load_profile()
    E.build_em_stories(prof)                       # writes DATA_DIR/em_stories.json
    E.list_em_stories(competency="growing_engineers")
    E.list_em_stories(query="hired")
    result = E.em_narrative(prof, "struggling-team")
    print(result["narrative"])
    print(result["gaps"])
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import config as C


class EmStoriesError(Exception):
    """Raised when EM stories cannot be built, found, or narrated."""


# --- EM competency tagger ----------------------------------------------------
# competency -> keyword substrings, matched case-insensitively against the
# resume bullet. Keep keywords behavioral ("hired", "promoted", "paged")
# rather than skill names so tags reflect what the bullet *demonstrates*
# for an EM loop. Extend freely: add a competency and its signals here.
EM_COMPETENCY_KEYWORDS: dict[str, list[str]] = {
    "hiring_bar": [
        "hired", "hiring", "interview", "interviewed", "onboarded",
        "hiring bar", "recruit", "recruiting", "candidate",
    ],
    "growing_engineers": [
        "mentored", "coached", "coaching", "grew", "promoted", "promotion",
        "career growth", "1:1", "1-1", "one-on-one", "feedback",
        "developed engineers", "leveling",
    ],
    "managing_up": [
        "stakeholder", "executive", "exec", "leadership team", "director",
        "vp", "cto", "reported to", "alignment", "buy-in", "roadmap",
    ],
    "incident_leadership": [
        "incident", "outage", "on-call", "oncall", "postmortem", "paged",
        "sev", "war room", "rollback", "mitigated", "downtime", "slo",
    ],
    "cross_team_influence": [
        "cross-functional", "cross-team", "partnered", "collaborat",
        "aligned", "influenced", "org-wide", "multiple teams",
        "drove adoption",
    ],
    "org_design": [
        "team of", "direct reports", "org", "restructured", "reorg",
        "team structure", "staffed", "team lead", "managed", "managed a",
        "engineering manager", "headcount",
    ],
}

#: Evidence that the profile reflects real people-management (not just IC lead).
MANAGEMENT_EVIDENCE_KEYWORDS = [
    "managed", "direct reports", "reports to me", "team of",
    "engineering manager", "hired", "fired", "performance review",
    "perf review", "pip", "performance improvement", "promoted",
    "1:1", "1-1", "one-on-one",
]

#: Common team-health / EM interview prompts, keyed for `em_narrative`.
TEAM_HEALTH_PROMPTS: dict[str, dict] = {
    "struggling-team": {
        "question": "Tell me about a struggling team you inherited.",
        "competencies": ["growing_engineers", "org_design"],
        "hint": "Walk through: how you diagnosed the problems, what you "
                "changed in the first 90 days, and how you measured recovery.",
    },
    "raised-the-bar": {
        "question": "Tell me about a time you raised the bar for your team.",
        "competencies": ["hiring_bar", "growing_engineers"],
        "hint": "Concrete bar-raising moves: hiring standards, code review "
                "culture, on-call expectations, or review calibration.",
    },
    "managing-up": {
        "question": "Tell me about a time you had to manage up.",
        "competencies": ["managing_up", "cross_team_influence"],
        "hint": "Who the stakeholder was, what they wanted, how you aligned "
                "them, and what the outcome was.",
    },
    "incident": {
        "question": "Tell me about the toughest incident you led.",
        "competencies": ["incident_leadership", "managing_up"],
        "hint": "Your role during the incident, the decisions you made under "
                "pressure, and what the team changed afterwards.",
    },
    "underperformer": {
        "question": "How have you handled an underperforming engineer?",
        "competencies": ["growing_engineers", "hiring_bar"],
        "hint": "How you diagnosed the gap, the support plan you put in "
                "place, and how you decided between coaching and exit.",
    },
    "cross-team": {
        "question": "Tell me about a time you influenced a decision you "
                    "didn't own.",
        "competencies": ["cross_team_influence", "managing_up"],
        "hint": "Why you got involved, how you built alignment without "
                "authority, and what changed.",
    },
}


def tag_em_bullet(bullet: str) -> list[str]:
    """Tag one resume bullet with EM competencies (may be multiple)."""
    text = (bullet or "").lower()
    return sorted(
        comp for comp, keywords in EM_COMPETENCY_KEYWORDS.items()
        if any(kw in text for kw in keywords)
    )


def _em_stories_path() -> Path:
    """Resolve the storage path at call time (tests override DATA_DIR)."""
    return C.DATA_DIR / "em_stories.json"


def _iter_bullets(profile: dict):
    """Yield (title, company, dates, bullet) for every experience bullet."""
    if not isinstance(profile, dict):
        raise EmStoriesError("profile must be a dict (profile.json format).")
    for entry in profile.get("experience", []) or []:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title", "") or ""
        company = entry.get("company", "") or ""
        dates = entry.get("dates", "") or ""
        for bullet in entry.get("bullets", []) or []:
            if bullet and bullet.strip():
                yield title, company, dates, bullet.strip()


def _title_for(bullet: str) -> str:
    """Short story title: first ~8 words of the bullet."""
    words = bullet.split()
    title = " ".join(words[:8])
    if len(words) > 8:
        title += "..."
    return title


def _save_em_stories(stories: list[dict]) -> None:
    C.ensure_data_dirs()
    _em_stories_path().write_text(
        json.dumps(stories, indent=2), encoding="utf-8")


def build_em_stories(profile: dict) -> list[dict]:
    """Build EM STAR story prompts from a profile's experience bullets.

    Only bullets with at least one EM competency tag become stories, so the
    bank reflects management-relevant evidence, not every IC bullet.
    Returns the stories and stores them in DATA_DIR / "em_stories.json".
    Each story: {id, title, bullet_source, situation_prompt, task_prompt,
    action_prompt, result_prompt, competencies, user_text}.
    Raises EmStoriesError if the profile has no bullets with EM signal.
    """
    stories: list[dict] = []
    for title, company, dates, bullet in _iter_bullets(profile):
        tags = tag_em_bullet(bullet)
        if not tags:
            continue
        stories.append({
            "id": f"e{len(stories) + 1}",
            "title": _title_for(bullet),
            "bullet_source": {
                "title": title, "company": company,
                "dates": dates, "bullet": bullet,
            },
            "situation_prompt": (
                "Set the management context: the team (size, tenure, health), "
                "the org around it, and what was at stake for the business."
            ),
            "task_prompt": (
                "What were you accountable for as the manager? Separate "
                "your decisions (staffing, priorities, process, standards) "
                "from IC work the team did."
            ),
            "action_prompt": (
                f'Your resume says: "{bullet}"\n'
                "What management actions did you take? Cover diagnosis, "
                "the conversations you had (team, skip-levels, stakeholders), "
                "and the structural changes you made."
            ),
            "result_prompt": (
                "What changed for the team (retention, velocity, quality, "
                "morale) and the business? Numbers where you have them. "
                "What would you do differently?"
            ),
            "competencies": tags,
            "user_text": "",
        })
    if not stories:
        raise EmStoriesError(
            "No experience bullets in the profile carry EM signal "
            "(hiring, mentoring, incidents, stakeholders, team size, ...). "
            "EM story prompts need management-relevant resume bullets — "
            "add bullets about teams you managed, engineers you hired or "
            "grew, or incidents you led, then rebuild."
        )
    _save_em_stories(stories)
    return stories


def _load_em_stories() -> list[dict]:
    path = _em_stories_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmStoriesError(
            f"EM stories file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise EmStoriesError(f"EM stories file {path} must contain a JSON list.")
    return data


def _searchable(story: dict) -> str:
    """Text searched by the query filter: title + prompts + user text."""
    parts = [story.get("title", ""), story.get("user_text", "")]
    for key in ("situation_prompt", "task_prompt", "action_prompt",
                "result_prompt"):
        parts.append(story.get(key, ""))
    return "\n".join(parts).lower()


def list_em_stories(competency: str | None = None,
                    query: str | None = None) -> list[dict]:
    """List EM stories, optionally filtered by competency and/or query.

    The query is a case-insensitive substring match over the title,
    the STAR prompts, and the user's written text.
    """
    stories = _load_em_stories()
    if competency:
        want = competency.strip().lower()
        stories = [s for s in stories
                   if want in [c.lower() for c in s.get("competencies", [])]]
    if query:
        want = query.strip().lower()
        stories = [s for s in stories if want in _searchable(s)]
    return stories


def get_em_story(story_id: str) -> dict:
    """Return one EM story by id; raise EmStoriesError if missing."""
    for story in _load_em_stories():
        if story.get("id") == story_id:
            return story
    raise EmStoriesError(f"No EM story with id '{story_id}'.")


def update_em_story(story_id: str, user_text: str) -> dict:
    """Save the user's written version of an EM story."""
    if not isinstance(user_text, str):
        raise EmStoriesError("user_text must be a string.")
    stories = _load_em_stories()
    for story in stories:
        if story.get("id") == story_id:
            story["user_text"] = user_text
            _save_em_stories(stories)
            return story
    raise EmStoriesError(f"No EM story with id '{story_id}'.")


def format_em_story(story: dict) -> str:
    """Render an EM story as a Markdown STAR scaffold."""
    src = story.get("bullet_source", {}) or {}
    source_line = f"{src.get('title', '')} - {src.get('company', '')}"
    if src.get("dates"):
        source_line += f" ({src.get('dates')})"
    competencies = ", ".join(story.get("competencies", [])) or "untagged"
    lines = [
        f"# {story.get('title', 'Untitled story')}",
        "",
        f"**Source:** {source_line}",
        f"**Competencies:** {competencies}",
        "",
        "## Situation",
        story.get("situation_prompt", ""),
        "",
        "## Task",
        story.get("task_prompt", ""),
        "",
        "## Action",
        story.get("action_prompt", ""),
        "",
        "## Result",
        story.get("result_prompt", ""),
        "",
    ]
    user_text = story.get("user_text", "") or ""
    if user_text.strip():
        lines += ["## My version", user_text, ""]
    else:
        lines += ["## My version", "*(write your version here)*", ""]
    return "\n".join(lines)


# --- team-health storytelling ------------------------------------------------

def _profile_text(profile: dict) -> str:
    """All experience + summary text, lowercased, for evidence detection."""
    parts = [profile.get("summary", "") or ""]
    for entry in profile.get("experience", []) or []:
        if not isinstance(entry, dict):
            continue
        parts.append(entry.get("title", "") or "")
        parts.append(entry.get("company", "") or "")
        for bullet in entry.get("bullets", []) or []:
            parts.append(bullet or "")
    return "\n".join(parts).lower()


def has_management_evidence(profile: dict) -> bool:
    """True if the profile shows real people-management experience."""
    text = _profile_text(profile)
    return any(kw in text for kw in MANAGEMENT_EVIDENCE_KEYWORDS)


def _evidence_bullets(profile: dict, competencies: list[str]) -> list[dict]:
    """Bullets tagged with any of the given EM competencies."""
    out = []
    for title, company, dates, bullet in _iter_bullets(profile):
        tags = tag_em_bullet(bullet)
        if any(c in tags for c in competencies):
            out.append({
                "title": title, "company": company, "dates": dates,
                "bullet": bullet, "competencies": tags,
            })
    return out


def em_narrative(profile: dict, prompt_key: str) -> dict:
    """Build a team-health narrative scaffold for a prompt key.

    Returns {"question", "evidence", "narrative", "gaps"}.
    The narrative is assembled ONLY from the user's profile bullets — it
    quotes the evidence and leaves explicit [fill in] gaps rather than
    inventing details. When the profile lacks relevant management
    evidence, the narrative says so and "gaps" lists what's missing.
    """
    key = (prompt_key or "").strip().lower()
    if key not in TEAM_HEALTH_PROMPTS:
        known = ", ".join(sorted(TEAM_HEALTH_PROMPTS))
        raise EmStoriesError(
            f"Unknown prompt key '{prompt_key}'. Choose from: {known}."
        )
    spec = TEAM_HEALTH_PROMPTS[key]
    evidence = _evidence_bullets(profile, spec["competencies"])

    gaps: list[str] = []
    lines = [f"# {spec['question']}", ""]
    if not evidence:
        if not has_management_evidence(profile):
            gaps.append(
                "Your profile shows no people-management experience "
                "(managing, hiring, 1:1s, performance reviews). Interviewers "
                "expect a real team-management story here; add management "
                "bullets to your profile before using this prompt."
            )
        else:
            gaps.append(
                f"Your profile has management experience but no bullets tagged "
                f"with {', '.join(spec['competencies'])} — add a bullet about "
                f"that area (or pick another prompt) instead of improvising."
            )
        lines += [
            "No grounded evidence for this prompt in your profile.",
            "",
            "Do not invent a story: interviewers probe these answers, and a "
            "made-up story will collapse under follow-ups.",
            "",
        ]
    else:
        lines += [
            "Built strictly from your profile. Anything in [brackets] is a "
            "gap — fill it with your real experience before using this answer.",
            "",
            "## Evidence from your profile",
            "",
        ]
        for i, ev in enumerate(evidence, start=1):
            src = f"{ev['title']} - {ev['company']}".strip(" -")
            lines.append(f"{i}. \"{ev['bullet']}\" ({src})")
        ref = "evidence 1" if len(evidence) == 1 else f"evidence 1-{len(evidence)}"
        lines += [
            "",
            "## Narrative scaffold",
            "",
            "**Situation.** [Describe the team you walked into: size, "
            f"tenure, what was going wrong. Ground it in {ref} above.]",
            "",
            "**Task.** [What you were accountable for as the manager.]",
            "",
            "**Action.** [Diagnosis, conversations, structural changes — "
            "pick the specific actions behind the bullets above.]",
            "",
            "**Result.** [Team outcome: retention, velocity, quality, "
            "morale. Use your real numbers; don't just quote the bullets.]",
            "",
        ]
        gaps.append(
            "Fill the [bracketed] sections with your own details before "
            "interviewing — this scaffold is prompts plus your own words, "
            "not a finished answer."
        )
    lines += [
        "## Interviewer hint",
        spec["hint"],
        "",
    ]
    if gaps:
        lines += ["## Gaps", ""]
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")
    return {
        "question": spec["question"],
        "evidence": evidence,
        "narrative": "\n".join(lines),
        "gaps": gaps,
    }
