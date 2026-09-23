"""Panel interview prep: multi-interviewer loops, who's-who briefs, per-interviewer expectations.

A "panel" is one interview loop: the ordered rounds and the interviewer
behind each one. This module helps you prepare per interviewer instead of
preparing generically:

  1. ``panel create`` — define the loop: interviewer name, interviewer
     archetype (hiring manager, peer engineer, bar raiser, ...), duration.
  2. ``panel brief`` — who's-who brief sheet: what each interviewer
     evaluates, how they ask, likely questions, red flags they watch for,
     and questions you should ask them.
  3. ``panel questions`` — role-based question expectations per interviewer:
     which question categories each round draws from, with sample questions.
  4. ``panel ask`` — smart questions to ask each interviewer, tailored to
     their role.
  5. ``panel plan`` — the day's timeline: round order, durations, breaks,
     and prep blocks.
  6. ``panel mock`` — deterministic per-interviewer mock round: a likely
     question, talking points grounded in *your* profile, and a self-score
     rubric. Sessions are saved so readiness can see them.
  7. ``panel log`` + ``panel consistency`` — story-consistency tracker: log
     what you told each interviewer (metrics, claims), then scan for
     contradictions across rounds.
  8. ``panel research`` — interviewer-research checklist plus a place to
     record what you found.
  9. ``panel debrief`` — consolidate per-round notes after the loop into a
     panel debrief with signals, follow-ups, and thank-you draft hooks.
 10. ``panel readiness`` — readiness score: how much of the prep is done
     per round.
 11. ``panel brief --export`` — the full brief sheet as Markdown, saved next
     to the prep packs.

Everything is deterministic and offline. Interviewer backgrounds come from
*your* notes (recruiter emails, LinkedIn exports) — nothing is scraped, and
nothing about a real person is fabricated. Question expectations come from
the interviewer *archetype*, labeled as such, plus the general question
banks in ``prep_questions`` — never presented as leaked company questions.

Usage:
    python -m candid panel create --company "Acme" --role "Data Scientist" \\
        --rounds "Priya Nair:hiring_manager:45, Sam Rao:engineer:60, Jo:bar_raiser:45"
    python -m candid panel brief --panel P1
    python -m candid panel questions --panel P1 --round 2
    python -m candid panel mock --panel P1 --round 2
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from candid import config as C


class PanelError(Exception):
    """Raised for invalid panel operations."""


# ---------------------------------------------------------------------------
# Interviewer archetypes: role-based question expectations.
#
# Each archetype describes what that interviewer evaluates, how they ask,
# which question categories they draw from (categories are the ones used by
# candid/prep_questions.py GENERIC_BANKS), sample questions they typically
# ask, red flags they watch for, questions YOU should ask them, and prep
# tips. These are generic archetype expectations, not company leaks.
# To add an archetype, copy a block and keep the same keys
# (see docs/panel_prep.md).
# ---------------------------------------------------------------------------

ARCHETYPES: dict[str, dict] = {
    "recruiter": {
        "label": "Recruiter screen",
        "description": "First human filter. Checks motivation, logistics, comp band, and basic fit.",
        "evaluates": [
            "Genuine interest in this company and role (not spray-and-pray)",
            "Logistics: location, work authorization, timeline, comp expectations",
            "Communication clarity and basic role fit",
        ],
        "styles": ["Short screen, 20-30 min", "Conversational, checklist-driven"],
        "categories": ["behavioral"],
        "sample_questions": [
            "Walk me through your background in two minutes.",
            "Why this company, and why this role specifically?",
            "What are you looking for in your next role?",
            "What are your compensation expectations?",
            "Where are you in your search? Any competing timelines?",
        ],
        "watch_for": [
            "Can't articulate why *this* company",
            "Comp expectations far outside the band",
            "Vague answers about what they want next",
        ],
        "ask_them": [
            "What does the interview loop look like after this, and who will I meet?",
            "What is the team prioritizing in the first 6 months of this hire?",
            "What is the leveling and comp band for this role?",
        ],
        "prep_tips": [
            "Have a crisp 2-minute pitch ready — recruiters decide in the first 5 minutes.",
            "Know your walk-away comp number before the call, not during it.",
        ],
    },
    "hiring_manager": {
        "label": "Hiring manager",
        "description": "Your would-be boss. Tests ownership, team fit, and whether you can do the job on their team.",
        "evaluates": [
            "Ownership and scope: did you drive outcomes or just contribute?",
            "Team fit: how you work with engineers, PMs, stakeholders",
            "Career narrative: does this role make sense as your next step?",
            "What you'd do in the first 90 days",
        ],
        "styles": ["45-60 min", "Deep dives on 2-3 resume stories", "Situational 'what would you do' questions"],
        "categories": ["behavioral", "product"],
        "sample_questions": [
            "Tell me about the most impactful project you owned end to end.",
            "What would your first 90 days on my team look like?",
            "Tell me about a time you disagreed with a stakeholder. How did you resolve it?",
            "What kind of manager brings out your best work?",
            "What is something on your resume you'd do differently now?",
        ],
        "watch_for": [
            "No clear personal ownership ('we' with no 'I')",
            "Can't connect past work to this team's problems",
            "Badmouthing previous managers or teams",
        ],
        "ask_them": [
            "What does success look like for this role in the first 6 months?",
            "What is the biggest challenge facing the team right now?",
            "How do you like to work with your reports — how hands-on are you?",
            "What happened to the last person in this role?",
        ],
        "prep_tips": [
            "Map 3 resume stories to this team's actual problems before the call.",
            "Prepare a 90-day plan sketch — managers love candidates who think like owners.",
        ],
    },
    "engineer": {
        "label": "Peer engineer (coding/technical)",
        "description": "A future teammate. Tests whether they want to work with you on hard problems.",
        "evaluates": [
            "Coding fluency: clean, correct code under mild pressure",
            "Debugging and problem decomposition",
            "Technical communication: can you narrate your thinking?",
            "Code quality instincts: edge cases, complexity, testing",
        ],
        "styles": ["45-60 min", "1-2 coding problems or a deep technical dive", "Think-aloud expected"],
        "categories": ["python", "process", "ml"],
        "sample_questions": [
            "Solve a medium-difficulty coding problem while narrating your approach.",
            "A production service's p99 latency just spiked. Walk me through your debugging, step by step.",
            "How would you test the code you just wrote?",
            "Tell me about the hardest bug you ever fixed. What was the root cause?",
            "Design the data model for a feature you've built before.",
        ],
        "watch_for": [
            "Silent coding with no narration",
            "Skipping edge cases and complexity analysis",
            "Can't explain *why* a solution works, only that it does",
        ],
        "ask_them": [
            "What does the team's code review culture look like?",
            "What is the most interesting technical problem the team is working on?",
            "How does the team handle on-call and incident review?",
        ],
        "prep_tips": [
            "Practice narrating while you code — silence reads as stuck.",
            "Always state complexity and one edge case before you finish.",
        ],
    },
    "bar_raiser": {
        "label": "Bar raiser",
        "description": "An outsider to the hiring team whose job is to protect the hiring bar. Digs deep on principles and past behavior.",
        "evaluates": [
            "Whether you *raise* the team's bar, not just clear it",
            "Depth and honesty of behavioral stories (follow-up drilling)",
            "Customer obsession and ownership under ambiguity",
            "Consistency: does the story hold up under 3 levels of 'why?'",
        ],
        "styles": ["45-60 min", "2-3 stories max, drilled 3-4 levels deep", "STAR with relentless follow-ups"],
        "categories": ["behavioral"],
        "sample_questions": [
            "Tell me about a time you disagreed with your manager and what happened.",
            "Describe your most challenging project. What was *your* specific contribution?",
            "Tell me about a time you failed. What did you change afterward?",
            "Give me an example of going beyond what was asked for a customer or user.",
            "Tell me about a time you had to make a decision with incomplete data.",
        ],
        "watch_for": [
            "Stories that collapse under follow-up questions",
            "Taking credit for team outcomes without a clear personal role",
            "No genuine failure story (or a humblebrag failure)",
        ],
        "ask_them": [
            "What separates the people who thrive here from those who don't?",
            "What is something about the culture that surprised you when you joined?",
        ],
        "prep_tips": [
            "Prepare 5-6 stories you can defend 4 levels deep — bar raisers drill.",
            "For each story, know the metric, your exact role, and what you'd do differently.",
        ],
    },
    "system_design": {
        "label": "System design interviewer",
        "description": "Tests large-scale thinking: requirements, tradeoffs, and depth where it matters.",
        "evaluates": [
            "Requirements gathering before jumping to solutions",
            "Breadth: can cover API, data model, scaling, reliability",
            "Depth: goes deep on the 1-2 components that actually matter",
            "Tradeoff reasoning: every choice has a cost, name it",
        ],
        "styles": ["45-60 min", "One open-ended design problem", "Collaborative whiteboard, not a quiz"],
        "categories": ["system_design"],
        "sample_questions": [
            "Design a URL shortener that handles 100M URLs a day.",
            "Design a rate limiter for a public API.",
            "Design an ML feature-serving system end to end.",
            "How would you design a notification system for a billion users?",
            "Walk me through how you'd scale a system you built from 10x to 100x traffic.",
        ],
        "watch_for": [
            "Jumping to technology choices before clarifying requirements",
            "Hand-waving the hard parts (consistency, failure modes)",
            "No discussion of tradeoffs or alternatives",
        ],
        "ask_them": [
            "What are the hardest scaling challenges the team faces today?",
            "How much of the work is greenfield vs. evolving existing systems?",
        ],
        "prep_tips": [
            "Start every design with: scope, users, scale numbers, then API.",
            "Practice saying 'the tradeoff here is...' out loud — it scores.",
        ],
    },
    "data_scientist": {
        "label": "Data science technical",
        "description": "A technical peer in data/ML. Tests statistical depth and real-world modeling judgment.",
        "evaluates": [
            "Statistical fundamentals: experiments, inference, uncertainty",
            "ML judgment: when simple beats fancy, leakage, evaluation",
            "SQL fluency for real analysis",
            "Business translation: metrics that connect to decisions",
        ],
        "styles": ["45-60 min", "Mix of stats theory, ML debugging, and SQL", "Case-style business questions"],
        "categories": ["ml", "stats", "sql"],
        "sample_questions": [
            "Design an A/B test for a new feature. How do you pick the sample size?",
            "Your model's offline metrics improved but the online metric didn't move. Debug it.",
            "How do you detect and handle data leakage?",
            "Write SQL with window functions to compute a 7-day rolling average.",
            "How would you explain a confidence interval to a non-technical stakeholder?",
        ],
        "watch_for": [
            "Buzzword ML with no grasp of evaluation or leakage",
            "Can't reason about uncertainty or sample size",
            "No connection between metrics and business decisions",
        ],
        "ask_them": [
            "How does the team decide what to model vs. what to solve with heuristics?",
            "What does the experimentation platform look like — who can launch tests?",
            "How close is the DS team to product decisions?",
        ],
        "prep_tips": [
            "Re-derive A/B test sample-size logic once — it comes up constantly.",
            "Have one leakage story and one 'offline vs online' story ready.",
        ],
    },
    "product": {
        "label": "Product sense interviewer",
        "description": "Usually a PM. Tests product thinking: users, metrics, tradeoffs, prioritization.",
        "evaluates": [
            "User empathy: who is it for, what job are they hiring the product to do",
            "Metrics: north-star and guardrail thinking",
            "Prioritization under constraints",
            "Tradeoff reasoning and structured communication",
        ],
        "styles": ["45 min", "Case-style: 'design X' or 'metrics for Y'", "Structured frameworks expected"],
        "categories": ["product", "case"],
        "sample_questions": [
            "Design a metric tree for a subscription product. What is the north-star metric?",
            "Revenue dropped 10% week-over-week. How do you find the root cause?",
            "How would you improve our onboarding flow?",
            "You have 3 features and one sprint. How do you prioritize?",
            "What product do you love, and what would you change about it?",
        ],
        "watch_for": [
            "Jumping to solutions before understanding the user",
            "Vanity metrics with no link to decisions",
            "No framework — rambling instead of structured thinking",
        ],
        "ask_them": [
            "How are product decisions made here — who has the final call?",
            "What is the most controversial product decision the team made recently?",
        ],
        "prep_tips": [
            "Use a structure out loud: users → pain → options → metrics → recommendation.",
            "Always name a guardrail metric, not just the north star.",
        ],
    },
    "behavioral": {
        "label": "Behavioral / culture",
        "description": "Tests collaboration, conflict, and growth through past behavior.",
        "evaluates": [
            "Self-awareness: honest about strengths and growth areas",
            "Collaboration and conflict resolution",
            "Adaptability and learning speed",
            "Alignment with team values",
        ],
        "styles": ["30-45 min", "STAR stories", "Conversational, values-probing"],
        "categories": ["behavioral"],
        "sample_questions": [
            "Tell me about a time you had a conflict with a teammate. How did you handle it?",
            "Describe a time you had to learn something completely new under a deadline.",
            "What feedback have you received that was hard to hear?",
            "Tell me about a time you helped someone else succeed.",
            "Why do you want to leave your current role?",
        ],
        "watch_for": [
            "Blaming others in every story",
            "No growth narrative — same person as 3 years ago",
            "Negativity about the current employer",
        ],
        "ask_them": [
            "How would you describe the team culture in three words?",
            "How does the team handle disagreement?",
        ],
        "prep_tips": [
            "One honest growth story beats three perfect ones.",
            "Never badmouth a current/past employer — frame moves as 'toward', not 'away'.",
        ],
    },
    "skip_level": {
        "label": "Skip-level / director",
        "description": "A senior leader two levels up. Tests scope of thinking and leadership trajectory.",
        "evaluates": [
            "Scope: do you think in team/org terms, not just tasks?",
            "Vision: where is your craft going, and where do you fit?",
            "Leadership signals: influence without authority, mentorship",
            "Why this company at this stage",
        ],
        "styles": ["30-45 min", "High-level, career-arc conversation", "Few questions, deep answers"],
        "categories": ["behavioral", "product"],
        "sample_questions": [
            "Where do you see your craft going in the next 3 years?",
            "Tell me about a time you influenced a decision without authority.",
            "What would you change about how your current org works?",
            "Why us, and why now?",
            "What kind of problems do you want to own in 2 years?",
        ],
        "watch_for": [
            "Thinks only in tickets and tasks, never in outcomes",
            "No opinion about the industry or craft direction",
            "Mercenary signals: only comp and title matter",
        ],
        "ask_them": [
            "What are the org's biggest bets this year?",
            "What does the career path from this role look like here?",
            "What keeps you up at night about the business?",
        ],
        "prep_tips": [
            "Zoom out: talk in outcomes and org impact, not JIRA tickets.",
            "Have one genuine opinion about where the industry is going.",
        ],
    },
    "cross_functional": {
        "label": "Cross-functional partner",
        "description": "Someone you'd work with but not for (PM, designer, data, ops). Tests collaboration.",
        "evaluates": [
            "Stakeholder management: can you work with non-engineers?",
            "Communication: translating technical work for other functions",
            "Empathy for other functions' constraints",
            "Conflict resolution without escalation",
        ],
        "styles": ["30-45 min", "Situational collaboration stories", "Case: 'how would you work with me on X'"],
        "categories": ["behavioral", "case"],
        "sample_questions": [
            "Tell me about a time you worked with a difficult stakeholder.",
            "How do you explain technical tradeoffs to non-technical partners?",
            "Describe a project where priorities shifted mid-flight. How did you handle it?",
            "Tell me about a time a launch went wrong. What was your role in the response?",
        ],
        "watch_for": [
            "Us-vs-them framing about other functions",
            "Can't simplify technical concepts",
            "Escalates instead of resolving",
        ],
        "ask_them": [
            "How do engineers and your function typically collaborate here?",
            "What does a great partnership with this role look like to you?",
        ],
        "prep_tips": [
            "Prepare one story where a non-engineer made your work better.",
            "Show curiosity about their function — ask how *they* measure success.",
        ],
    },
}

#: Archetype names in a sensible default loop order.
DEFAULT_LOOP_ORDER = [
    "recruiter", "engineer", "data_scientist", "system_design",
    "product", "hiring_manager", "bar_raiser", "behavioral",
    "cross_functional", "skip_level",
]

# Mock self-score rubric (1-5 per criterion).
MOCK_RUBRIC = [
    ("Structure", "Clear beginning, middle, end — not rambling"),
    ("Specificity", "Concrete details, numbers, and your personal role"),
    ("Depth", "Survives follow-up 'why?' questions"),
    ("Relevance", "Connects to this interviewer's actual concerns"),
]

# Interviewer-research checklist. Export-only: LinkedIn exports, recruiter
# emails, company blog — never scraped (see candid's ingestion model).
RESEARCH_CHECKLIST = [
    "Read the interviewer's LinkedIn profile (from your LinkedIn data export) — current role, tenure, past companies",
    "Note 1-2 shared touchpoints (same school, past employer, tech stack) for rapport",
    "Skim their team's engineering blog posts or talks for a reference point",
    "Check the recruiter's email for what this round is *actually* testing",
    "Draft 2 role-specific questions to ask them (see `panel ask`)",
    "Review your story-consistency log so this round matches earlier rounds",
]

_SIGNAL_LABELS = {"strong": "Strong", "mixed": "Mixed", "weak": "Weak"}


# ---------------------------------------------------------------------------
# Storage: panels.json under DATA_DIR (honors CANDID_DATA_DIR at call time,
# so tests never touch real user data).
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _panels_path() -> Path:
    return _data_dir() / "panels.json"


def _load_panels() -> list[dict]:
    p = _panels_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PanelError(f"Panel store {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PanelError(f"Panel store {p} should contain a JSON list.")
    return data


def _save_panels(panels: list[dict]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _panels_path().write_text(json.dumps(panels, indent=2), encoding="utf-8")


def _next_id(panels: list[dict]) -> str:
    used = {p.get("id", "") for p in panels}
    n = 1
    while f"P{n}" in used:
        n += 1
    return f"P{n}"


def _require_archetype(archetype: str) -> dict:
    key = (archetype or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in ARCHETYPES:
        raise PanelError(
            f"Unknown interviewer archetype '{archetype}'. "
            f"Valid: {', '.join(sorted(ARCHETYPES))}. "
            "See `python -m candid panel archetypes`."
        )
    return ARCHETYPES[key]


def parse_rounds(spec: str) -> list[dict]:
    """Parse ``--rounds "Name:archetype[:mins], ..."`` into round dicts.

    Minutes default to 45. Names may not contain commas or colons.
    """
    rounds: list[dict] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) < 2 or len(parts) > 3:
            raise PanelError(
                f"Bad round spec '{chunk}'. Use Name:archetype[:minutes], e.g. "
                "'Priya Nair:hiring_manager:45'."
            )
        name, archetype = parts[0], parts[1]
        if not name:
            raise PanelError(f"Bad round spec '{chunk}': interviewer name is empty.")
        _require_archetype(archetype)
        minutes = 45
        if len(parts) == 3:
            try:
                minutes = int(parts[2])
            except ValueError:
                raise PanelError(
                    f"Bad round spec '{chunk}': minutes must be a number."
                ) from None
            if minutes <= 0 or minutes > 480:
                raise PanelError(
                    f"Bad round spec '{chunk}': minutes must be 1-480."
                )
        rounds.append({
            "name": name,
            "title": "",
            "archetype": archetype.strip().lower().replace(" ", "_").replace("-", "_"),
            "duration_min": minutes,
            "order": len(rounds) + 1,
            "background": "",
            "log": [],
        })
    if not rounds:
        raise PanelError(
            "No rounds parsed. Use --rounds \"Name:archetype[:minutes], ...\"."
        )
    return rounds


def create_panel(company: str, role: str, rounds_spec: str,
                 app_id: int | None = None) -> dict:
    """Create a panel (interview loop). Returns the panel dict."""
    if not (company or "").strip():
        raise PanelError("--company is required.")
    if not (role or "").strip():
        raise PanelError("--role is required.")
    panels = _load_panels()
    panel = {
        "id": _next_id(panels),
        "company": company.strip(),
        "role": role.strip(),
        "app_id": app_id,
        "created": date.today().isoformat(),
        "rounds": parse_rounds(rounds_spec),
        "mocks": [],
        "activity": {
            "briefed": False,
            "mocked_rounds": [],
            "researched_rounds": [],
        },
    }
    panels.append(panel)
    _save_panels(panels)
    return panel


def list_panels() -> list[dict]:
    return _load_panels()


def get_panel(panel_id: str) -> dict:
    pid = (panel_id or "").strip().upper()
    for p in _load_panels():
        if p.get("id", "").upper() == pid:
            return p
    raise PanelError(
        f"No panel '{panel_id}'. See `python -m candid panel list`."
    )


def _get_round(panel: dict, round_no: int) -> dict:
    rounds = panel.get("rounds", [])
    if not isinstance(round_no, int) or isinstance(round_no, bool) \
            or not 1 <= round_no <= len(rounds):
        raise PanelError(
            f"Panel {panel['id']} has {len(rounds)} round(s); "
            f"--round must be 1-{len(rounds)}."
        )
    return rounds[round_no - 1]


def _update_panel(panel: dict) -> None:
    panels = _load_panels()
    for i, p in enumerate(panels):
        if p.get("id") == panel["id"]:
            panels[i] = panel
            break
    else:
        raise PanelError(f"No panel '{panel['id']}'.")
    _save_panels(panels)


def remove_panel(panel_id: str) -> None:
    panels = _load_panels()
    pid = (panel_id or "").strip().upper()
    kept = [p for p in panels if p.get("id", "").upper() != pid]
    if len(kept) == len(panels):
        raise PanelError(f"No panel '{panel_id}'.")
    _save_panels(kept)


def add_round(panel_id: str, name: str, archetype: str,
              minutes: int = 45, title: str = "") -> dict:
    """Append a round to an existing panel. Returns the updated panel."""
    panel = get_panel(panel_id)
    _require_archetype(archetype)  # validates; raises PanelError if unknown
    if not (name or "").strip():
        raise PanelError("Interviewer name is required.")
    if minutes <= 0 or minutes > 480:
        raise PanelError("Minutes must be 1-480.")
    panel["rounds"].append({
        "name": name.strip(),
        "title": title.strip(),
        "archetype": archetype.strip().lower().replace(" ", "_").replace("-", "_"),
        "duration_min": minutes,
        "order": len(panel["rounds"]) + 1,
        "background": "",
        "log": [],
    })
    _update_panel(panel)
    return panel


def render_panels(panels: list[dict]) -> str:
    if not panels:
        return ("No panels yet. Create one:\n"
                "  python -m candid panel create --company \"Acme\" --role \"Data Scientist\" \\\n"
                "      --rounds \"Priya Nair:hiring_manager:45, Sam Rao:engineer:60\"")
    lines = [f"{'ID':<5}{'Company':<22}{'Role':<28}Rounds"]
    for p in panels:
        n = len(p.get("rounds", []))
        lines.append(f"{p['id']:<5}{p.get('company','')[:21]:<22}"
                     f"{p.get('role','')[:27]:<28}{n}")
    return "\n".join(lines)


def render_panel_detail(panel: dict) -> str:
    lines = [
        f"Panel {panel['id']}: {panel['role']} @ {panel['company']}",
        f"Created {panel.get('created', '')}"
        + (f" · linked to tracker #{panel['app_id']}" if panel.get("app_id") else ""),
        "",
        f"{'#':<3}{'Interviewer':<24}{'Archetype':<18}Min",
    ]
    for i, r in enumerate(panel.get("rounds", []), 1):
        arch = ARCHETYPES.get(r["archetype"], {})
        lines.append(f"{i:<3}{r['name'][:23]:<24}"
                     f"{arch.get('label', r['archetype'])[:17]:<18}"
                     f"{r['duration_min']}")
        if r.get("title"):
            lines[-1] += f"  ({r['title']})"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Who's-who brief sheet (feature 2)
# ---------------------------------------------------------------------------

def brief_round(panel: dict, rnd: dict, round_no: int) -> str:
    """Markdown brief card for one interviewer."""
    arch = ARCHETYPES[rnd["archetype"]]
    title = f" ({rnd['title']})" if rnd.get("title") else ""
    lines = [
        f"## Round {round_no} — {rnd['name']}{title}",
        f"*{arch['label']} · {rnd['duration_min']} min*",
        "",
        f"{arch['description']}",
        "",
        "**What they're evaluating:**",
        "",
    ]
    lines += [f"- {e}" for e in arch["evaluates"]]
    lines += ["", "**How they ask:**", ""]
    lines += [f"- {s}" for s in arch["styles"]]
    if rnd.get("background"):
        lines += ["", "**Your research notes on them:**", "", f"> {rnd['background']}", ""]
    else:
        lines += ["",
                  "_No background recorded yet — add what the recruiter told you:_",
                  f"`python -m candid panel research --panel {panel['id']} "
                  f"--round {round_no} --background \"...\"`",
                  ""]
    lines += ["**Red flags they watch for:**", ""]
    lines += [f"- {w}" for w in arch["watch_for"]]
    lines += ["", "**Prep tips:**", ""]
    lines += [f"- {t}" for t in arch["prep_tips"]]
    lines.append("")
    return "\n".join(lines)


def brief_panel(panel: dict, mark_briefed: bool = True) -> str:
    """Full who's-who brief sheet markdown for the panel."""
    lines = [
        f"# Panel Brief — {panel['role']} @ {panel['company']}",
        f"*Panel {panel['id']} · generated {date.today().isoformat()} · "
        f"{len(panel.get('rounds', []))} rounds*",
        "",
        "_Expectations below come from the interviewer archetype (their role "
        "in the loop), not from leaked company questions. Treat them as "
        "how this kind of interviewer tends to evaluate, then sharpen with "
        "your own research._",
        "",
    ]
    for i, rnd in enumerate(panel.get("rounds", []), 1):
        lines.append(brief_round(panel, rnd, i))
    lines += [
        "---",
        "_Tip: run `panel questions` for per-interviewer question expectations, "
        "`panel ask` for questions to ask each interviewer, and `panel plan` "
        "for the day's timeline._",
    ]
    if mark_briefed:
        panel["activity"]["briefed"] = True
        _update_panel(panel)
    return "\n".join(lines)


def export_brief(panel: dict) -> Path:
    """Write the brief sheet to the prep-packs dir. Returns the path."""
    md = brief_panel(panel)
    packs = _data_dir() / "prep_packs"
    packs.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_"
                   for c in f"{panel['company']}-{panel['role']}")[:60]
    out = packs / f"{date.today().isoformat()}_panel-{panel['id']}_{safe}.md"
    out.write_text(md, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Role-based question expectations per interviewer (feature 3)
# ---------------------------------------------------------------------------

def _bank_questions(categories: list[str], per_category: int = 2) -> list[dict]:
    """General-bank questions for categories, labeled as general prep."""
    from candid.prep_questions import GENERIC_BANKS
    out: list[dict] = []
    for cat in categories:
        for bank in GENERIC_BANKS.values():
            for q in bank:
                if q.get("category") == cat and len(
                        [x for x in out if x["category"] == cat]) < per_category:
                    out.append({"question": q["q"], "category": cat,
                                "source": "general bank"})
    return out


def questions_for_round(rnd: dict) -> list[dict]:
    """Likely questions for one round: archetype samples + mapped bank questions.

    Archetype samples are labeled ``archetype expectation``; bank questions
    are labeled ``general prep``. Nothing is presented as company-verified.
    """
    arch = ARCHETYPES[rnd["archetype"]]
    out = [{"question": q, "category": None, "source": "archetype expectation"}
           for q in arch["sample_questions"]]
    for bq in _bank_questions(arch["categories"]):
        if bq["question"] not in {o["question"] for o in out}:
            out.append(bq)
    return out


def render_questions(panel: dict, round_no: int | None = None) -> str:
    rounds = panel.get("rounds", [])
    idxs = [round_no - 1] if round_no else range(len(rounds))
    if round_no:
        _get_round(panel, round_no)
    lines = [f"# Question expectations — {panel['role']} @ {panel['company']}",
             ""]
    for i in idxs:
        rnd = rounds[i]
        arch = ARCHETYPES[rnd["archetype"]]
        title = f" ({rnd['title']})" if rnd.get("title") else ""
        lines += [f"## Round {i + 1} — {rnd['name']}{title} · {arch['label']}", ""]
        for q in questions_for_round(rnd):
            tag = "archetype" if q["source"] == "archetype expectation" else "general"
            cat = f" [{q['category']}]" if q.get("category") else ""
            lines.append(f"- {q['question']}{cat} _({tag})_")
        lines.append("")
    lines.append("_Archetype questions describe how this interviewer role tends to "
                 "ask; general-bank questions are labeled as general prep. Neither "
                 "is a leaked company list._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Questions to ask each interviewer (feature 4)
# ---------------------------------------------------------------------------

def ask_them_for_round(rnd: dict) -> list[str]:
    return list(ARCHETYPES[rnd["archetype"]]["ask_them"])


def render_ask(panel: dict, round_no: int | None = None) -> str:
    rounds = panel.get("rounds", [])
    if round_no:
        _get_round(panel, round_no)
        idxs = [round_no - 1]
    else:
        idxs = range(len(rounds))
    lines = [f"# Questions to ask your interviewers — {panel['role']} @ {panel['company']}",
             "",
             "_Pick 2 per round. Asking role-specific questions signals you "
             "understand what each interviewer cares about._",
             ""]
    for i in idxs:
        rnd = rounds[i]
        arch = ARCHETYPES[rnd["archetype"]]
        title = f" ({rnd['title']})" if rnd.get("title") else ""
        lines += [f"## Round {i + 1} — {rnd['name']}{title} · {arch['label']}", ""]
        lines += [f"- {q}" for q in arch["ask_them"]]
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Day timeline planner (feature 5)
# ---------------------------------------------------------------------------

def plan_panel(panel: dict, start: str = "10:00", break_min: int = 15) -> list[dict]:
    """Build the day's timeline. Returns schedule rows.

    start: "HH:MM" 24h. Between rounds, insert a break of break_min minutes
    (0 to disable). Each row: kind (round/break/prep), label, start, end.
    """
    try:
        h, m = (int(x) for x in start.split(":"))
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
    except ValueError:
        raise PanelError(f"Bad --start '{start}'. Use HH:MM, e.g. 10:00.") from None
    if break_min < 0 or break_min > 120:
        raise PanelError("--break-min must be 0-120.")

    cur = h * 60 + m
    rows: list[dict] = []

    def fmt(total_min: int) -> str:
        return f"{(total_min // 60) % 24:02d}:{total_min % 60:02d}"

    # 20-minute prep block before the first round.
    rows.append({"kind": "prep", "label": "Prep block: review brief sheet + questions",
                 "start": fmt(cur), "end": fmt(cur + 20)})
    cur += 20
    rounds = panel.get("rounds", [])
    for i, rnd in enumerate(rounds):
        arch = ARCHETYPES[rnd["archetype"]]
        rows.append({"kind": "round",
                     "label": f"Round {i + 1}: {rnd['name']} ({arch['label']})",
                     "start": fmt(cur), "end": fmt(cur + rnd["duration_min"])})
        cur += rnd["duration_min"]
        if break_min and i < len(rounds) - 1:
            rows.append({"kind": "break", "label": "Break: water, notes, reset",
                         "start": fmt(cur), "end": fmt(cur + break_min)})
            cur += break_min
    return rows


def render_plan(panel: dict, start: str = "10:00", break_min: int = 15) -> str:
    rows = plan_panel(panel, start=start, break_min=break_min)
    total = sum(r.get("duration_min", 0) for r in panel.get("rounds", []))
    lines = [f"# Interview day plan — {panel['role']} @ {panel['company']}",
             f"*Panel {panel['id']} · starts {start}*", ""]
    for r in rows:
        marker = {"round": "▶", "break": "☕", "prep": "📝"}.get(r["kind"], "·")
        lines.append(f"{marker} {r['start']}–{r['end']}  {r['label']}")
    lines += ["",
              f"Total interview time: {total} min across {len(panel.get('rounds', []))} rounds.",
              "_Tip: keep a one-line note per round right after it ends — "
              "your debrief will thank you._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-interviewer mock round (feature 6): deterministic, profile-grounded.
# ---------------------------------------------------------------------------

def _profile_bullets(profile: dict | None, limit: int = 3) -> list[str]:
    if not profile:
        return []
    bullets: list[str] = []
    for e in profile.get("experience", [])[:2]:
        for b in e.get("bullets", [])[:2]:
            text = str(b).strip()
            if text:
                bullets.append(f"{e.get('title', '')} @ {e.get('company', '')}: {text}")
    return bullets[:limit]


def mock_round(panel: dict, round_no: int,
               profile: dict | None = None) -> dict:
    """Run a deterministic practice round in the interviewer's persona.

    The question is picked deterministically (rotates with each attempt so
    repeated mocks cover more ground). Talking points are grounded in the
    user's real profile bullets — never fabricated. The session is saved on
    the panel so ``panel readiness`` can see it.
    """
    rnd = _get_round(panel, round_no)
    arch = ARCHETYPES[rnd["archetype"]]
    pool = questions_for_round(rnd)
    attempt = sum(1 for m in panel.get("mocks", [])
                  if m.get("round") == round_no)
    q = pool[attempt % len(pool)]
    bullets = _profile_bullets(profile)
    if bullets:
        talking = ("Ground your answer in: " +
                   " / ".join(f"\"{b[:80]}…\"" if len(b) > 80 else f"\"{b}\""
                               for b in bullets))
    else:
        talking = ("No profile loaded — run `python -m candid onboard` first, "
                   "then re-run this mock for talking points from your resume.")
    session = {
        "round": round_no,
        "interviewer": rnd["name"],
        "archetype": rnd["archetype"],
        "question": q["question"],
        "question_source": q["source"],
        "talking_points": talking,
        "rubric": [{"criterion": c, "hint": h} for c, h in MOCK_RUBRIC],
        "score": None,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    panel.setdefault("mocks", []).append(session)
    if round_no not in panel["activity"]["mocked_rounds"]:
        panel["activity"]["mocked_rounds"].append(round_no)
    _update_panel(panel)
    return session


def score_mock(panel: dict, round_no: int, scores: list[int]) -> dict:
    """Record self-scores (1-5 per rubric criterion) for the latest mock."""
    if len(scores) != len(MOCK_RUBRIC):
        raise PanelError(
            f"Need {len(MOCK_RUBRIC)} scores (1-5), one per rubric criterion.")
    if any(not 1 <= s <= 5 for s in scores):
        raise PanelError("Scores must be 1-5.")
    sessions = [m for m in panel.get("mocks", []) if m.get("round") == round_no]
    if not sessions:
        raise PanelError(
            f"No mock session for round {round_no} yet. Run `panel mock` first.")
    latest = sessions[-1]
    latest["score"] = [
        {"criterion": c, "score": s}
        for (c, _), s in zip(MOCK_RUBRIC, scores)
    ]
    latest["total"] = sum(scores)
    _update_panel(panel)
    return latest


def render_mock(session: dict, rnd: dict) -> str:
    arch = ARCHETYPES[session["archetype"]]
    lines = [
        f"# Mock round — {session['interviewer']} ({arch['label']})",
        "",
        f"**Question** _({session['question_source']})_:",
        f"> {session['question']}",
        "",
        "**Talking points:**",
        f"{session['talking_points']}",
        "",
        "**Answer out loud (2-3 min), then self-score 1-5:**",
        "",
    ]
    for i, r in enumerate(session["rubric"], 1):
        lines.append(f"{i}. **{r['criterion']}** — {r['hint']}")
    lines += [
        "",
        "Record scores:",
        f"`python -m candid panel mock --panel <id> --round {session['round']} "
        "--score 4 3 5 4`",
    ]
    if session.get("score"):
        lines += ["", "**Your scores:**"]
        lines += [f"- {s['criterion']}: {s['score']}/5" for s in session["score"]]
        lines.append(f"- **Total: {session['total']}/{5 * len(MOCK_RUBRIC)}**")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interviewer research (feature 8): export-only, recorded findings.
# ---------------------------------------------------------------------------

def research_checklist_for_round(rnd: dict) -> list[str]:
    return list(RESEARCH_CHECKLIST)


def set_background(panel: dict, round_no: int, background: str) -> dict:
    rnd = _get_round(panel, round_no)
    if not (background or "").strip():
        raise PanelError("--background text is required.")
    rnd["background"] = background.strip()
    if round_no not in panel["activity"]["researched_rounds"]:
        panel["activity"]["researched_rounds"].append(round_no)
    _update_panel(panel)
    return panel


def render_research(panel: dict, round_no: int | None = None) -> str:
    rounds = panel.get("rounds", [])
    if round_no:
        _get_round(panel, round_no)
        idxs = [round_no - 1]
    else:
        idxs = range(len(rounds))
    lines = ["# Interviewer research — export-only checklist",
             "",
             "_Use your own sources: the recruiter's emails, your LinkedIn data "
             "export (`python -m candid linkedin guide`), the company blog. "
             "candid never scrapes profiles and never fabricates backgrounds._",
             ""]
    for i in idxs:
        rnd = rounds[i]
        arch = ARCHETYPES[rnd["archetype"]]
        title = f" ({rnd['title']})" if rnd.get("title") else ""
        lines += [f"## Round {i + 1} — {rnd['name']}{title} · {arch['label']}", ""]
        if rnd.get("background"):
            lines += [f"> {rnd['background']}", ""]
        for j, item in enumerate(RESEARCH_CHECKLIST, 1):
            done = "[x]" if rnd.get("background") and j <= 2 else "[ ]"
            lines.append(f"- {done} {item}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Story-consistency tracker (feature 7): log what you told each interviewer,
# then scan for contradictions.
# ---------------------------------------------------------------------------

def log_note(panel: dict, round_no: int, note: str,
             signal: str | None = None) -> dict:
    """Append a note to a round's log. Signal: strong|mixed|weak (debrief use)."""
    rnd = _get_round(panel, round_no)
    if not (note or "").strip():
        raise PanelError("--note text is required.")
    if signal is not None and signal not in _SIGNAL_LABELS:
        raise PanelError(f"Bad --signal '{signal}'. Use strong, mixed, or weak.")
    entry = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note.strip(),
    }
    if signal:
        entry["signal"] = signal
    rnd.setdefault("log", []).append(entry)
    _update_panel(panel)
    return entry


_NUMBER_RE = re.compile(
    r"\$?\b\d+(?:\.\d+)?\s*"
    r"(%|percent\b|[xkm]\b|millions?\b|billions?\b|ms\b|s\b"
    r"| engineers?\b| users?\b| customers?\b| reports?\b"
    r"| years?\b| months?\b| weeks?\b)",
    re.IGNORECASE,
)

_STOPWORDS = {"a", "an", "the", "of", "by", "to", "in", "on", "for", "with",
              "and", "or", "at", "from", "up", "about", "over", "under",
              "said", "say", "says", "told", "tell", "mentioned", "mention",
              "noted", "claimed", "shared", "told"}


def _claim_keyword(note: str, match: re.Match) -> str:
    """Keyword for a number: up to 2 content words before it, else the unit."""
    before = note[:match.start()].lower()
    words = re.findall(r"[a-z]+", before)
    content = [w for w in words if w not in _STOPWORDS and len(w) > 1]
    if content:
        return " ".join(content[-2:])
    unit = re.sub(r"[\d\s\.\$,]", "", match.group(0)).strip().lower()
    return unit or "number"


def _extract_claims(note: str) -> list[tuple[str, str]]:
    claims = []
    for m in _NUMBER_RE.finditer(note):
        value = m.group(0).strip().replace(" ", "")
        claims.append((_claim_keyword(note, m), value))
    return claims


def consistency_check(panel: dict) -> list[dict]:
    """Flag numbers/claims that differ across rounds for the same keyword.

    Deterministic and conservative: it reports *possible* inconsistencies
    for you to verify, never asserting you contradicted yourself.
    """
    seen: dict[str, dict[str, list[int]]] = {}  # keyword -> value -> [rounds]
    for i, rnd in enumerate(panel.get("rounds", []), 1):
        for entry in rnd.get("log", []):
            for keyword, value in _extract_claims(entry.get("note", "")):
                seen.setdefault(keyword, {}).setdefault(value, []).append(i)
    flags = []
    for keyword, by_value in sorted(seen.items()):
        if len(by_value) > 1:
            detail = "; ".join(
                f"'{v}' in round(s) {sorted(set(rs))}"
                for v, rs in sorted(by_value.items()))
            flags.append({"keyword": keyword, "detail": detail})
    return flags


def render_consistency(panel: dict) -> str:
    flags = consistency_check(panel)
    lines = [f"# Story consistency — panel {panel['id']}",
             f"*{panel['role']} @ {panel['company']}*", ""]
    if not flags:
        lines += ["✅ No conflicting numbers or claims found across rounds.",
                  "",
                  "_Keep logging what you tell each interviewer — small metric "
                  "drift between rounds is the classic panel trap._"]
    else:
        lines += ["⚠️  Possible inconsistencies to verify (same topic, different numbers):",
                  ""]
        for f in flags:
            lines.append(f"- **{f['keyword']}**: {f['detail']}")
        lines += ["",
                  "_These are keyword-adjacent numbers, not proof of contradiction. "
                  "Check the context in each round's log before worrying._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Post-panel debrief consolidation (feature 9)
# ---------------------------------------------------------------------------

def debrief_panel(panel: dict, profile: dict | None = None,
                  drafts: bool = False) -> str:
    """Consolidate per-round log notes into a panel debrief.

    drafts: also generate per-interviewer thank-you draft outlines via the
    followup module (needs a profile name; falls back to a prompt).
    """
    lines = [f"# Panel debrief — {panel['role']} @ {panel['company']}",
             f"*Panel {panel['id']} · {date.today().isoformat()}*", ""]
    signals: list[str] = []
    for i, rnd in enumerate(panel.get("rounds", []), 1):
        arch = ARCHETYPES[rnd["archetype"]]
        title = f" ({rnd['title']})" if rnd.get("title") else ""
        sig_entries = [e for e in rnd.get("log", []) if e.get("signal")]
        sig = sig_entries[-1]["signal"] if sig_entries else None
        if sig:
            signals.append(sig)
        sig_line = f" — signal: **{_SIGNAL_LABELS[sig]}**" if sig else ""
        lines += [f"## Round {i} — {rnd['name']}{title} · {arch['label']}{sig_line}", ""]
        notes = rnd.get("log", [])
        if notes:
            for e in notes:
                tag = f" [{_SIGNAL_LABELS[e['signal']]}]" if e.get("signal") else ""
                lines.append(f"- {e['note']}{tag}")
        else:
            lines.append("_No notes logged for this round._")
        lines.append("")
    lines += ["## Overall read", ""]
    if signals:
        counts = {s: signals.count(s) for s in _SIGNAL_LABELS}
        parts = [f"{counts[s]} {_SIGNAL_LABELS[s].lower()}" for s in _SIGNAL_LABELS
                 if counts[s]]
        lines.append(f"Round signals: {', '.join(parts)}.")
        if counts.get("weak"):
            lines.append("_Follow up on weak rounds: what would you do differently? "
                         "Note it while it's fresh._")
        elif counts.get("strong") == len(signals):
            lines.append("_Clean sweep. Send thank-yous within 24h referencing "
                         "something specific from each round._")
    else:
        lines.append("_No signals recorded. Log each round with "
                     "`panel log --panel <id> --round N --signal strong|mixed|weak "
                     "--note \"...\"`, then re-run the debrief._")
    lines += ["", "## Follow-ups", "",
              "- [ ] Thank-you note to each interviewer within 24h "
              "(reference one specific topic per round)",
              "- [ ] Recruiter check-in with timeline and enthusiasm level",
              "- [ ] Update the tracker: `python -m candid track update --help`",
              ""]
    if drafts:
        lines += ["## Thank-you draft outlines", ""]
        name = (profile or {}).get("name", "")
        if name:
            from candid import followup as F
            for i, rnd in enumerate(panel.get("rounds", []), 1):
                topic_notes = [e["note"] for e in rnd.get("log", [])][:2]
                topic = "; ".join(topic_notes) if topic_notes else "our conversation"
                try:
                    draft = F.thank_you(name, rnd["name"], panel["role"],
                                        panel["company"], topics=topic)
                except TypeError:
                    draft = (f"Thank {rnd['name']} for round {i}; mention: {topic}. "
                             "See `python -m candid followup thank-you --help` for a full draft.")
                lines += [f"### To {rnd['name']} (round {i})", "", draft, ""]
        else:
            lines.append("_No profile name found — run `python -m candid onboard` "
                         "first, or draft with `python -m candid followup thank-you --help`._")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Readiness score (feature 10)
# ---------------------------------------------------------------------------

def readiness(panel: dict) -> dict:
    """Readiness breakdown per round + overall score 0-100.

    Checks per round: briefed (panel-wide), mock done, research recorded,
    notes logged. Score = completed / total.
    """
    rounds = panel.get("rounds", [])
    activity = panel.get("activity", {})
    briefed = bool(activity.get("briefed"))
    mocked = set(activity.get("mocked_rounds", []))
    researched = set(activity.get("researched_rounds", []))
    per_round = []
    done = 1 if briefed else 0
    total = 1 + 3 * len(rounds)
    for i, rnd in enumerate(rounds, 1):
        checks = {
            "mock_done": i in mocked,
            "researched": i in researched or bool(rnd.get("background")),
            "notes_logged": bool(rnd.get("log")),
        }
        done += sum(checks.values())
        per_round.append({"round": i, "interviewer": rnd["name"],
                          "archetype": rnd["archetype"], "checks": checks})
    score = round(100 * done / total) if total else 0
    return {"score": score, "done": done, "total": total,
            "briefed": briefed, "per_round": per_round}


def render_readiness(panel: dict) -> str:
    r = readiness(panel)
    lines = [f"# Panel readiness — {panel['id']}: {panel['role']} @ {panel['company']}",
             "", f"**Readiness: {r['score']}/100** ({r['done']}/{r['total']} checks)", ""]
    mark = "✅" if r["briefed"] else "⬜"
    lines.append(f"- {mark} brief sheet generated (panel-wide)")
    lines.append("")
    check_names = {"mock_done": "mock round completed",
                   "researched": "interviewer research recorded",
                   "notes_logged": "round notes logged"}
    for pr in r["per_round"]:
        arch = ARCHETYPES[pr["archetype"]]
        lines.append(f"## Round {pr['round']} — {pr['interviewer']} · {arch['label']}")
        for key, label in check_names.items():
            mark = "✅" if pr["checks"][key] else "⬜"
            lines.append(f"- {mark} {label}")
        lines.append("")
    hints = {
        "mock_done": "`python -m candid panel mock --panel <id> --round N`",
        "researched": "`python -m candid panel research --panel <id> --round N --background \"...\"`",
        "notes_logged": "`python -m candid panel log --panel <id> --round N --note \"...\"`",
    }
    next_cmds: list[str] = []
    if not r["briefed"]:
        next_cmds.append(f"`python -m candid panel brief --panel {panel['id']}`")
    for pr in r["per_round"]:
        for k, v in pr["checks"].items():
            if not v and hints[k] not in next_cmds:
                next_cmds.append(hints[k])
    if next_cmds:
        lines += ["**Next up:**", ""]
        lines += [f"- {c}" for c in next_cmds]
    else:
        lines.append("🎉 Fully prepped. Go get the offer. *Keta da!*")
    return "\n".join(lines)
