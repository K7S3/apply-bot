"""PM-flavored execution narratives (PIERL) built from your own resume bullets.

Each narrative has five sections - Problem, Insight, Execution, Result,
Lesson (PIERL) - and is tagged with PM competencies. The key rule: never
invent experience. Scaffolds contain ONLY the user's own bullet text plus
writing prompts; the user fills in the rest with `story update`.

PM competency tagger (keyword-based):
    roadmap, prioritization, stakeholder_mgmt, launch, data_driven,
    user_empathy, experimentation, cross_functional

Narratives are stored in DATA_DIR/pm_stories.json.
Profile bullets are read with candid.profile.load_profile (never duplicated
from stories.py - this module stands alone and does not modify it).

This module is wired into the CLI by the coordinator via register_pm();
it never touches candid.__main__ itself.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from candid.profile import load_profile  # reused; monkeypatchable in tests

__all__ = [
    "PmStoryError",
    "PIERL_SECTIONS",
    "COMPETENCY_KEYWORDS",
    "tag_competencies",
    "build_narrative",
    "build_from_profile",
    "load_stories",
    "save_stories",
    "get_story",
    "update_story",
    "render_story",
    "register_pm",
]


class PmStoryError(Exception):
    """Raised for PM-story usage errors."""


#: The five narrative sections, in order.
PIERL_SECTIONS: list[str] = ["problem", "insight", "execution", "result", "lesson"]

#: competency -> keyword stems (matched case-insensitively as substrings).
COMPETENCY_KEYWORDS: dict[str, list[str]] = {
    "roadmap": ["roadmap", "strategy", "strategic", "vision", "okr", "quarterly plan"],
    "prioritization": ["prioritiz", "tradeoff", "trade-off", "backlog",
                       "stack rank", "triage", "scope cut"],
    "stakeholder_mgmt": ["stakeholder", "leadership", "executive", "buy-in",
                         "buy in", "alignment", "sponsor", "steering"],
    "launch": ["launch", "shipped", "ship ", "release", "rollout", "go-live",
               "general availability", "ga launch"],
    "data_driven": ["metric", "dashboard", "conversion", "retention", "funnel",
                    "sql", "analytics", "data-driven", "kpi"],
    "user_empathy": ["user", "customer", "interview", "usability", "persona",
                     "journey", "feedback", "nps", "survey"],
    "experimentation": ["experiment", "a/b", "hypothesis", "pilot", "iteration",
                        "iterate", "test group", "control group"],
    "cross_functional": ["engineering", "design", "data science", "legal",
                         "marketing", "sales", "partner", "cross-functional"],
}


def _data_dir() -> Path:
    """User data dir, overridable via CANDID_DATA_DIR (used by tests)."""
    override = os.environ.get("CANDID_DATA_DIR")
    return Path(override).expanduser() if override else Path.cwd() / "candid_data"


def _stories_path() -> Path:
    return _data_dir() / "pm_stories.json"


def tag_competencies(text: str) -> list[str]:
    """Keyword-based PM competency tags for a block of text.

    Returns tags in the canonical COMPETENCY_KEYWORDS order.
    """
    lowered = text.lower()
    tags = [comp for comp, keywords in COMPETENCY_KEYWORDS.items()
            if any(k in lowered for k in keywords)]
    return tags


def _scaffold(section: str, bullet: str) -> str:
    """A writing prompt for one PIERL section; contains only the user's bullet."""
    prompts = {
        "problem": (
            f'Your bullet says: "{bullet}"\n'
            "Write 2-3 sentences: what was broken or missing, who felt the pain, "
            "and why did it matter to the business?"
        ),
        "insight": (
            f'Your bullet says: "{bullet}"\n'
            "What did you learn (from data, users, or stakeholders) that changed "
            "the approach? What was the non-obvious read?"
        ),
        "execution": (
            f'Your bullet says: "{bullet}"\n'
            "What did YOU personally do - the 2-3 concrete steps, the people you "
            "aligned, the decisions you made? Name your own actions, not the team's."
        ),
        "result": (
            f'Your bullet says: "{bullet}"\n'
            "State the outcome as a metric (the number in your bullet, if it has "
            "one). What moved, by how much, and what guardrails held?"
        ),
        "lesson": (
            f'Your bullet says: "{bullet}"\n'
            "What would you do differently next time? What principle about "
            "product execution did this teach you?"
        ),
    }
    return prompts[section]


def build_narrative(title: str, company: str, bullet: str) -> dict:
    """Build one PIERL scaffold from a single resume bullet.

    Every section contains only the user's own bullet text plus a writing
    prompt - nothing is invented.
    """
    bullet = bullet.strip()
    if not bullet:
        raise PmStoryError("Cannot build a narrative from an empty bullet.")
    return {
        "title": title or "",
        "company": company or "",
        "bullet": bullet,
        "competencies": tag_competencies(f"{title} {company} {bullet}"),
        "sections": {s: _scaffold(s, bullet) for s in PIERL_SECTIONS},
        "filled": {s: False for s in PIERL_SECTIONS},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _profile_bullets(profile: dict, limit: int = 8) -> list[tuple[str, str, str]]:
    """(title, company, bullet) triples from the profile's experience section."""
    triples: list[tuple[str, str, str]] = []
    for entry in profile.get("experience", []) or []:
        title = str(entry.get("title", "") or "")
        company = str(entry.get("company", "") or "")
        for bullet in entry.get("bullets", []) or []:
            text = str(bullet).strip()
            if text:
                triples.append((title, company, text))
        if len(triples) >= limit:
            break
    return triples[:limit]


def build_from_profile(profile: dict, limit: int = 8) -> list[dict]:
    """Build PIERL scaffolds from the profile's resume bullets.

    Accepts a plain profile dict (as returned by load_profile); tests can
    pass a fake dict directly without touching the real profile file.
    """
    return [build_narrative(title, company, bullet)
            for title, company, bullet in _profile_bullets(profile, limit)]


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def load_stories() -> list[dict]:
    """All saved PM narratives (oldest first)."""
    path = _stories_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PmStoryError(f"Story file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PmStoryError(f"Story file {path} is corrupted (expected a list).")
    return data


def save_stories(stories: list[dict]) -> Path:
    """Write the narrative list to DATA_DIR/pm_stories.json."""
    path = _stories_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stories, indent=2), encoding="utf-8")
    return path


def get_story(index: int, stories: list[dict] | None = None) -> dict:
    """Fetch one narrative by index; raises PmStoryError if out of range."""
    stories = load_stories() if stories is None else stories
    if not 0 <= index < len(stories):
        raise PmStoryError(
            f"Story #{index} does not exist ({len(stories)} saved). "
            "Run `story build` first.")
    return stories[index]


def update_story(index: int, section: str, text: str) -> dict:
    """Let the user write their own text into one PIERL section.

    Marks the section filled and persists the change.
    """
    section = section.lower()
    if section not in PIERL_SECTIONS:
        raise PmStoryError(
            f"Unknown section '{section}'. Choose from: {', '.join(PIERL_SECTIONS)}.")
    if not text.strip():
        raise PmStoryError("Refusing to save an empty section - write something first.")
    stories = load_stories()
    story = get_story(index, stories)
    story["sections"][section] = text.strip()
    story["filled"][section] = True
    story["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_stories(stories)
    return story


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_story(story: dict, index: int | None = None) -> str:
    """Human-readable rendering of one narrative."""
    header = f"### Story #{index}" if index is not None else "### Story"
    at = f" ({story.get('title')} @ {story.get('company')})" \
        if story.get("title") or story.get("company") else ""
    comps = story.get("competencies") or []
    lines = [
        f"{header}{at}",
        f"Competencies: {', '.join(comps) if comps else '(untagged)'}",
        f"Bullet: \"{story.get('bullet', '')}\"",
        "",
    ]
    for section in PIERL_SECTIONS:
        mark = "x" if (story.get("filled") or {}).get(section) else " "
        lines.append(f"[{mark}] {section.upper()}")
        lines.append(story.get("sections", {}).get(section, ""))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_story_list(stories: list[dict]) -> str:
    """One-line-per-story index."""
    if not stories:
        return "No PM stories yet. Run `story build` to scaffold some from your resume."
    lines = []
    for i, s in enumerate(stories):
        done = sum(1 for v in (s.get("filled") or {}).values() if v)
        comps = ", ".join(s.get("competencies") or []) or "untagged"
        lines.append(f"#{i}  [{done}/5 filled]  {comps}  —  {s.get('bullet', '')[:70]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (register_pm is called by the coordinator; see module docstring)
# ---------------------------------------------------------------------------

def register_pm(subparsers) -> None:
    """Register the 'story' PM-stories subcommand on an argparse subparsers object.

    Actions: build (scaffold from resume bullets), list, show, update
    (write your own section text). Flags: --index, --section, --text,
    --limit, --json.
    """
    p = subparsers.add_parser(
        "story", help="PM execution narratives (PIERL) from your resume bullets.",
        epilog="examples:\n"
               "  python -m candid pm story build\n"
               "  python -m candid pm story list\n")
    p.add_argument("action", choices=["build", "list", "show", "update"],
                   help="What to do.")
    p.add_argument("--index", type=int, default=0,
                   help="Story index for show/update (default 0).")
    p.add_argument("--section", default="",
                   help="PIERL section for update: " + ", ".join(PIERL_SECTIONS) + ".")
    p.add_argument("--text", default="",
                   help="Your own text for the section (update action).")
    p.add_argument("--limit", type=int, default=8,
                   help="Max narratives to build (default 8).")
    p.add_argument("--json", action="store_true",
                   help="Print machine-readable JSON instead of text.")
    p.set_defaults(func=cmd_pm_story)


def cmd_pm_story(args: argparse.Namespace) -> None:
    """Dispatch for the registered 'story' subcommand."""
    if args.action == "build":
        profile = load_profile()
        stories = build_from_profile(profile, limit=args.limit)
        if not stories:
            raise PmStoryError(
                "No resume bullets found in your profile - nothing to build from.\n"
                "Run `python -m candid onboard --resume your_resume.pdf` first.")
        save_stories(stories)
        if args.json:
            print(json.dumps({"built": len(stories)}, indent=2))
        else:
            print(f"Built {len(stories)} PIERL scaffolds from your resume bullets.")
            print("Fill each section with `story update --index N --section S --text ...`.")
    elif args.action == "list":
        stories = load_stories()
        if args.json:
            print(json.dumps([{"index": i, "bullet": s.get("bullet"),
                               "competencies": s.get("competencies"),
                               "filled": s.get("filled")}
                              for i, s in enumerate(stories)], indent=2))
        else:
            print(render_story_list(stories))
    elif args.action == "show":
        story = get_story(args.index)
        if args.json:
            print(json.dumps(story, indent=2))
        else:
            print(render_story(story, index=args.index))
    elif args.action == "update":
        if not args.section:
            raise PmStoryError(
                f"update needs --section: {', '.join(PIERL_SECTIONS)}.")
        story = update_story(args.index, args.section, args.text)
        if args.json:
            print(json.dumps({"index": args.index, "section": args.section.lower(),
                              "filled": story["filled"]}, indent=2))
        else:
            print(f"Story #{args.index} [{args.section.lower()}] updated.")
    return None
