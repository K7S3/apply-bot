"""Designer-track interview preparation: portfolio review packs, portfolio gap
analysis, design-concept deep-dives, and self-critique checklists.

Everything here is deterministic and offline - no network, no paid APIs.
Usage:
    from candid import design as D

    md, path = D.build_design_prep("Acme", "Product Designer", profile)
    gaps = D.analyze_portfolio_gaps(profile, jd_text)
    print(D.render_gap_report(gaps))
    print(D.get_concept("wcag_accessibility"))
    print(D.self_critique_checklist("My onboarding redesign case study"))

Grounding rule: the question banks are general design interview prep. There
is no company-verified question bank for design roles, and this module never
claims otherwise (see `_NO_VERIFIED_QUESTIONS`). Portfolio analysis only
uses what is actually in the caller's profile - it never invents experience.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from candid import config as C

DESIGN_PACKS_DIR = C.DATA_DIR / "design_packs"


class DesignError(Exception):
    """Raised when a design prep artifact cannot be built."""


# ---------------------------------------------------------------------------
# 1. Portfolio review prep packs
# ---------------------------------------------------------------------------

_NO_VERIFIED_QUESTIONS = (
    "> **No company-verified design questions.** candid has no bank of "
    "interview questions reported specifically for this company's design "
    "roles, and we will not invent any. Every question below is *general* "
    "product/UX-design interview preparation - clearly labeled as such. "
    "If you find questions candidates publicly reported for this company, "
    "share them so a future version can include them with source attribution."
)

# category -> list of general-prep questions
_DESIGN_QUESTION_BANK: dict[str, list[str]] = {
    "portfolio_walkthrough": [
        "Walk me through your portfolio and pick the project you are proudest of.",
        "Choose one case study and go deep: what was the problem, your process, and the outcome?",
        "Which project in your portfolio failed or underperformed, and what did you change afterward?",
        "How do you decide which projects to show for this role?",
        "Walk me through a project from first discovery to final handoff.",
    ],
    "design_process": [
        "Walk me through your end-to-end design process.",
        "How do you approach an ambiguous problem with no clear user request?",
        "Tell me about a time you had to change direction mid-project. What made you pivot?",
        "How do you balance speed with rigor when timelines are tight?",
        "Describe how you scope a design problem before touching a tool.",
    ],
    "handling_critique": [
        "Tell me about a time you received harsh design critique. How did you respond?",
        "How do you defend a design decision when stakeholders disagree?",
        "Describe a time your design was wrong. What happened and what did you learn?",
        "How do you give critique to another designer's work?",
        "Tell me about feedback that fundamentally changed a design of yours.",
    ],
    "collaboration": [
        "How do you work with engineers during implementation?",
        "Tell me about a conflict with a product manager and how you resolved it.",
        "How do you partner with researchers or data scientists?",
        "How do you hand off designs so engineers build the right thing?",
        "Describe a time you aligned multiple stakeholders behind one direction.",
    ],
    "design_systems": [
        "How would you approach building or contributing to a design system?",
        "Tell me about a time you reused or extended a design system component.",
        "How do you balance consistency (the system) with the needs of a new feature?",
        "How do design tokens work, and why do teams use them?",
    ],
    "accessibility": [
        "How do you design for accessibility from the start, not as an afterthought?",
        "What WCAG level do you target and what does that mean in practice?",
        "Walk me through an accessibility audit you did on a product.",
        "How do you handle a design that looks great but fails contrast requirements?",
    ],
}

_CATEGORY_TITLES = {
    "portfolio_walkthrough": "Portfolio walkthrough",
    "design_process": "Design process",
    "handling_critique": "Handling critique",
    "collaboration": "Collaboration with engineering and PM",
    "design_systems": "Design systems",
    "accessibility": "Accessibility",
}


def _design_tips() -> list[str]:
    return [
        "Structure every case study as Problem → Process → Decisions → Outcome → Reflection.",
        "For each portfolio piece, prepare one 2-minute and one 5-minute version.",
        "Name tradeoffs explicitly: what you gave up and why. Interviewers probe this.",
        "Bring metrics when you have them (task success, conversion, CSAT); say plainly when you do not.",
        "End each case study with what you would do differently - it shows growth.",
        "Never invent users, research, or results you did not actually do or see.",
    ]


def build_design_prep(company: str, role: str, profile: dict,
                      out_dir: str | Path | None = None) -> tuple[str, Path]:
    """Build a Markdown portfolio-review prep pack.

    All questions are general design prep - the pack states this explicitly
    and never claims company-specific questions. Returns (markdown, path).
    """
    if not role or not str(role).strip():
        raise DesignError("role is required to build a design prep pack")
    role = str(role).strip()
    company = str(company or "").strip() or "the company"
    name = (profile or {}).get("name") or "you"

    lines = [
        f"# Design Interview Prep - {role} @ {company}",
        f"*Generated {date.today().isoformat()} · for {name}*",
        "",
        _NO_VERIFIED_QUESTIONS,
        "",
        "## Question bank (general prep)",
        "",
        "_Every question below is general product/UX-design interview prep. "
        "None of them is verified as asked at this company._",
        "",
    ]
    for cat, questions in _DESIGN_QUESTION_BANK.items():
        lines.append(f"### {_CATEGORY_TITLES[cat]}")
        lines.append("")
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")
        lines.append("")

    lines += [
        "## Concept deep-dives",
        "",
        "Pair each category with its explainer below "
        "(`get_concept(<slug>)` prints one; slugs: "
        + ", ".join(f"`{s}`" for s in DESIGN_CONCEPTS)
        + ").",
        "",
        "## Answering tips",
        "",
    ]
    lines += [f"- {t}" for t in _design_tips()]
    lines += [
        "",
        "## Portfolio checklist",
        "",
        "- [ ] 3-4 case studies, each with problem / process / decisions / outcome",
        "- [ ] At least one project showing research with real users",
        "- [ ] At least one project showing systems thinking (components, tokens, patterns)",
        "- [ ] Before/after or iteration examples that show you respond to feedback",
        "- [ ] Remove anything you cannot speak to in depth",
        "",
        "---",
        "_Question bank lives in `candid/design.py`. "
        "No company-specific design questions are fabricated._",
    ]
    markdown = "\n".join(lines)

    target = Path(out_dir) if out_dir else DESIGN_PACKS_DIR
    target.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{company}-{role}")[:60]
    out = target / f"{date.today().isoformat()}_{safe}.md"
    out.write_text(markdown, encoding="utf-8")
    return markdown, out


# ---------------------------------------------------------------------------
# 2. Portfolio gap analyzer
# ---------------------------------------------------------------------------

# canonical design skill -> aliases matched in JD text (case-insensitive)
DESIGN_SKILL_LEXICON: dict[str, list[str]] = {
    "user research": ["user research", "user interviews", "usability testing",
                      "contextual inquiry", "ethnographic", "diary study", "card sort",
                      "tree testing", "survey research"],
    "interaction design": ["interaction design", "ixd", "micro-interaction",
                           "microinteraction", "gesture", "animation"],
    "motion design": ["motion design", "animation", "lottie", "after effects",
                      "principle", "protoPie", "protopie"],
    "prototyping": ["prototyping", "prototype", "prototypes", "prototyped",
                    "figma", "framer", "invision", "wireframe",
                    "mockup", "low-fi", "high-fi", "lofi", "hifi"],
    "visual design": ["visual design", "typography", "color theory", "layout",
                      "iconography", "illustration", "brand"],
    "design systems": ["design system", "component library", "pattern library",
                       "design tokens", "style guide"],
    "accessibility": ["accessibility", "a11y", "wcag", "screen reader",
                      "inclusive design", "contrast ratio"],
    "information architecture": ["information architecture", "ia",
                                 "sitemap", "navigation model", "taxonomy"],
    "data visualization": ["data visualization", "dashboard", "charts",
                            "analytics ui"],
    "mobile design": ["mobile design", "ios", "android", "responsive",
                      "adaptive", "material design", "human interface"],
    "web design": ["html", "css", "front-end", "frontend", "web design"],
    "experimentation": ["a/b test", "ab test", "experimentation", "metrics",
                        "kpi", "funnel", "conversion"],
    "service design": ["service design", "journey map", "blueprint",
                       "omnichannel"],
    "content design": ["content design", "ux writing", "microcopy", "copy"],
    "design ops": ["design ops", "designops", "design critique", "design review"],
    "stakeholder management": ["stakeholder", "cross-functional", "xfn",
                               "influence", "alignment"],
}

# canonical skill -> concrete suggestion when missing from the portfolio
_GAP_SUGGESTIONS: dict[str, str] = {
    "user research": "Add one case study showing real user sessions (method, 2-3 findings, design change). Never invent participants or quotes.",
    "interaction design": "Show a flow with states and transitions annotated; explain why each state exists.",
    "motion design": "Build a small prototype (Figma smart animate or Lottie) showing one meaningful transition.",
    "prototyping": "Include low-fi and high-fi versions of one screen to show iteration, not just polish.",
    "visual design": "Add a visual-exploration spread: type scale, color ramps, spacing rationale.",
    "design systems": "Document one component you built or extended: anatomy, variants, usage rules.",
    "accessibility": "Run a contrast + keyboard pass on one project and document the fixes.",
    "information architecture": "Show a sitemap or nav restructure with the reasoning and any card-sort evidence.",
    "data visualization": "Add one dashboard or chart case study: what decision the data supports, why that chart type.",
    "mobile design": "Show a mobile flow end to end, including one platform-specific decision (iOS vs Android).",
    "web design": "Ship or mock a small responsive page; note the breakpoints and type scale.",
    "experimentation": "Write up one A/B test: hypothesis, metric, result, and what you shipped after.",
    "service design": "Map one end-to-end journey across touchpoints with pain points and opportunities.",
    "content design": "Show before/after microcopy with the rationale and any comprehension testing.",
    "design ops": "Describe a critique format or handoff process you improved, with the before/after.",
    "stakeholder management": "Pick a case study where you aligned disagreeing stakeholders and name the technique used.",
}


def _portfolio_text(profile: dict) -> str:
    """All portfolio-relevant text from the profile: projects + experience + skills."""
    parts: list[str] = []
    for p in (profile or {}).get("projects", []) or []:
        if isinstance(p, dict):
            parts.append(str(p.get("title", "")))
            parts.append(str(p.get("description", "")))
        else:
            parts.append(str(p))
    for e in (profile or {}).get("experience", []) or []:
        parts.append(str(e.get("title", "")))
        for b in e.get("bullets", []) or []:
            parts.append(str(b))
    parts.append(" ".join(str(s) for s in (profile or {}).get("skills", []) or []))
    parts.append(str((profile or {}).get("summary", "")))
    return "\n".join(parts)


def _skill_mentioned(text: str, alias: str) -> bool:
    esc = re.escape(alias)
    if alias[:1].isalnum():
        esc = r"\b" + esc
    if alias[-1:].isalnum():
        esc = esc + r"\b"
    return re.search(esc, text, re.IGNORECASE) is not None


def analyze_portfolio_gaps(profile: dict, jd_text: str) -> dict:
    """Compare the JD's design skills against the profile's portfolio.

    Returns a dict with:
      jd_skills  - design skills mentioned in the JD (canonical names)
      covered    - skills the portfolio text already evidences
      missing    - skills in the JD with no portfolio evidence
      suggestions - concrete, non-fabricating suggestions per missing skill

    Only skills actually matched in the JD are reported; nothing is
    invented about the user's experience.
    """
    jd = str(jd_text or "")
    portfolio = _portfolio_text(profile or {})
    jd_skills: list[str] = []
    for skill, aliases in DESIGN_SKILL_LEXICON.items():
        if any(_skill_mentioned(jd, a) for a in aliases):
            jd_skills.append(skill)
    covered = [s for s in jd_skills
               if any(_skill_mentioned(portfolio, a) for a in DESIGN_SKILL_LEXICON[s])]
    missing = [s for s in jd_skills if s not in covered]
    return {
        "jd_skills": jd_skills,
        "covered": covered,
        "missing": missing,
        "suggestions": {s: _GAP_SUGGESTIONS.get(s, "Add a portfolio piece evidencing this skill.") for s in missing},
    }


def render_gap_report(result: dict) -> str:
    """Render an analyze_portfolio_gaps result as Markdown."""
    lines = ["# Portfolio Gap Report", ""]
    jd_skills = result.get("jd_skills", [])
    if not jd_skills:
        return "\n".join(lines + [
            "_No design skills from our lexicon were found in this job description. "
            "Paste the full JD text (not just the title) for a useful analysis._",
            "",
        ])
    covered = result.get("covered", [])
    missing = result.get("missing", [])
    suggestions = result.get("suggestions", {})
    lines += ["## Design skills in this JD", ""]
    for s in jd_skills:
        mark = "covered" if s in covered else "missing"
        lines.append(f"- **{s}** - {mark}")
    lines.append("")
    if covered:
        lines += ["## Covered by your portfolio", ""]
        lines += [f"- {s}" for s in covered]
        lines.append("")
    if missing:
        lines += ["## Gaps (in the JD, not evidenced in your portfolio)", ""]
        for s in missing:
            lines.append(f"- **{s}**: {suggestions.get(s, '')}")
        lines.append("")
        lines.append(
            "_Suggestions are starting points. Only add work you actually did - "
            "never fabricate projects, users, or results to fill a gap._"
        )
        lines.append("")
    else:
        lines += ["_Your portfolio evidences every design skill mentioned in this JD._", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Design methods deep-dives
# ---------------------------------------------------------------------------

DESIGN_CONCEPTS: dict[str, str] = {
    "usability_heuristics": """### Usability Heuristics (Nielsen)

**The idea in 60 seconds.** Ten rules of thumb for spotting usability problems
without users in the room: visibility of system status, match with the real
world, user control and freedom, consistency and standards, error prevention,
recognition over recall, flexibility and efficiency, aesthetic and minimalist
design, help users recover from errors, and help/documentation.

**When to use.** Heuristic evaluations of an existing product, quick design
critiques, and the "review this screen" whiteboard exercise.

**Interview angle.** "Evaluate this checkout flow." Pick 3-4 heuristics, name
the violation, its severity, and a concrete fix. Severity rating (0-4) shows
you can prioritize, not just list problems.""",
    "user_research_methods": """### User Research Methods

**The idea in 60 seconds.** Generative methods (user interviews, contextual
inquiry, diary studies) discover *what problems exist*; evaluative methods
(usability testing, card sorting, tree testing, surveys) test *whether your
solution works*. Match the method to the question and the fidelity of what
you have.

**When to use.** Discovery before building; usability testing on prototypes
before engineering; card sorts when IA is the question; surveys only when
you need breadth, not depth.

**Interview angle.** "How would you research X?" Answer: the question first,
then the method, then sample size and why (5 users find most usability
issues), then what decision the findings would change.""",
    "wcag_accessibility": """### WCAG Accessibility Basics

**The idea in 60 seconds.** WCAG 2.x has four principles - Perceivable,
Operable, Understandable, Robust (POUR) - and three conformance levels: A,
AA (the usual legal/product target), AAA. Practical checks: 4.5:1 contrast
for body text, visible focus states, keyboard-only operation, meaningful alt
text, and no information conveyed by color alone.

**When to use.** Every design review, from wireframes (heading order, focus
order) to visual QA (contrast, touch targets >= 44px).

**Interview angle.** "How do you design accessibly?" Name POUR, the AA bar,
and one concrete fix you have made (e.g., "we bumped secondary text from
3.2:1 to 4.6:1 and added focus rings"). Accessibility baked in beats a
remediation story.""",
    "design_systems_tokens": """### Design Systems & Tokens

**The idea in 60 seconds.** A design system is a shared language: components,
patterns, and guidance. Design tokens are the atomic decisions (color,
spacing, type, radius) stored as data so every platform renders the same
values. Tokens decouple *intent* ("surface-primary") from *value* ("#FFFFFF"),
which is what makes theming and dark mode tractable.

**When to use.** Contributing components, auditing inconsistency, or
explaining how you would scale design across teams.

**Interview angle.** "How would you build a design system?" Start with an
audit of the existing UI, tokenize the smallest decisions first, build
components from tokens, document usage (do/don't), and define governance:
who can add or change a component.""",
    "prototyping_fidelity": """### Prototyping Fidelity

**The idea in 60 seconds.** Fidelity should match the question. Low-fi
(paper, wireframes) answers structure and flow questions cheaply; mid-fi
(clickable) tests navigation and task completion; high-fi (pixel-perfect,
motion) tests desirability and handoff details. Prototyping the wrong
fidelity wastes the most expensive resource: stakeholder attention.

**When to use.** Low-fi for early concept tests and alignment; high-fi only
when the question is visual, emotional, or about implementation detail.

**Interview angle.** "Show me how you'd prototype X." State the riskiest
assumption, pick the cheapest fidelity that tests it, and name what you
would *not* build. Interviewers reward restraint.""",
    "information_architecture": """### Information Architecture

**The idea in 60 seconds.** IA is how content is organized, labeled, and
connected: organization schemes (by topic, task, audience), labeling
systems, navigation, and search. Good IA is invisible - users find things
without thinking about the structure.

**When to use.** Restructuring navigation, merging products, or any screen
where users ask "where do I find...?".

**Interview angle.** "Redesign this app's navigation." Talk about mental
models first, card-sort or tree-test evidence second, and the tradeoff
between breadth (many top-level items) and depth (many taps).""",
    "interaction_design_principles": """### Interaction Design Principles

**The idea in 60 seconds.** Interactions should be discoverable (affordances,
signifiers), give feedback (every action gets a response), be forgiving
(undo, confirmations for destructive actions), and respect timing (perceived
performance, skeleton states, optimistic UI). State design - empty, loading,
error, partial, ideal - is where most products fail.

**When to use.** Designing flows, reviewing edge cases, and critiquing
micro-interactions.

**Interview angle.** "Design a [flow]." Walk the happy path, then immediately
cover the states: empty, loading, error, offline, and success. Naming the
states unprompted is the signal of seniority.""",
    "visual_hierarchy": """### Visual Hierarchy

**The idea in 60 seconds.** Hierarchy tells the eye what matters and in what
order: size, weight, color/contrast, spacing, and position. One primary
action per screen, grouped related items (proximity), and generous
whitespace. If everything is emphasized, nothing is.

**When to use.** Critiquing screens, presenting visual design, and
explaining why a redesign "feels cleaner."

**Interview angle.** "What would you change about this screen?" Rank by
impact: first the hierarchy (what should the eye hit first?), then
consistency, then polish. Tie each change to a user goal, not taste.""",
}

# order used when listing concepts in packs
CONCEPT_ORDER = list(DESIGN_CONCEPTS)


def get_concept(slug: str) -> str:
    """Return the Markdown deep-dive for a design concept slug.

    Raises DesignError for unknown slugs (with the valid list).
    """
    key = str(slug or "").strip().lower().replace("-", "_")
    if key not in DESIGN_CONCEPTS:
        raise DesignError(
            f"unknown design concept: {slug!r}. "
            f"Valid slugs: {', '.join(CONCEPT_ORDER)}"
        )
    return DESIGN_CONCEPTS[key]


# ---------------------------------------------------------------------------
# 4. Self-critique checklist
# ---------------------------------------------------------------------------

# item -> guidance text shown under each checklist row
_CRITIQUE_ITEMS: list[tuple[str, str]] = [
    ("Clarity of user goal",
     "Can a first-time user state in one sentence what this screen helps them "
     "do? If the goal needs explaining, the hierarchy or copy is wrong."),
    ("Visual hierarchy",
     "Does the eye land on the most important element first? Check size, "
     "weight, contrast, and spacing - one primary action per screen."),
    ("Consistency",
     "Do components, labels, and patterns match the rest of the product (or "
     "the design system)? Flag every one-off as intentional or a fix."),
    ("Accessibility",
     "Contrast >= 4.5:1 for body text, visible focus order, keyboard-only "
     "path, alt text, no color-only meaning. Note the WCAG level you target."),
    ("Error handling",
     "List every error state: what went wrong, in plain language, plus the "
     "recovery action. No dead ends, no raw error codes shown to users."),
    ("Mobile / responsive",
     "Touch targets >= 44px, readable type without zoom, no horizontal "
     "scroll, safe-area respected. Check the smallest breakpoint you support."),
    ("Empty states",
     "First-run and no-data states explain what belongs here and offer a "
     "next step - never a blank screen or a lonely illustration."),
    ("Feedback & states",
     "Every action gets feedback (loading, success, error). List the states "
     "you designed: empty, loading, partial, error, ideal."),
]


def self_critique_checklist(project_desc: str) -> str:
    """Build a scored, fill-in Markdown self-critique checklist.

    Each heuristic has guidance plus a 1-5 score slot and a notes slot.
    Scoring: 1 = fails, 3 = acceptable, 5 = exemplary. Tally at the end.
    """
    desc = str(project_desc or "").strip() or "your project"
    lines = [
        f"# Self-Critique Checklist - {desc}",
        "",
        "_Work through each heuristic against your actual screens. Score 1-5 "
        "(1 = fails, 3 = acceptable, 5 = exemplary), note the evidence, then "
        "tally. Anything scoring 1-2 goes on your fix list before the "
        "interview._",
        "",
        "| # | Heuristic | Guidance | Score (1-5) | Notes / evidence |",
        "|---|-----------|----------|-------------|------------------|",
    ]
    for i, (item, guidance) in enumerate(_CRITIQUE_ITEMS, 1):
        lines.append(f"| {i} | **{item}** | {guidance} | _ / 5 |  |")
    lines += [
        "",
        "## Tally",
        "",
        f"- Total: ___ / {5 * len(_CRITIQUE_ITEMS)}",
        "- Items scoring 1-2 (fix before presenting):",
        "  - ",
        "- Items scoring 5 (lead with these in the walkthrough):",
        "  - ",
        "",
        "## Fix list",
        "",
        "- [ ] ",
        "- [ ] ",
        "- [ ] ",
        "",
        "_Re-score after fixes. Bring the before/after to the interview - "
        "showing your critique process is often more impressive than a "
        "flawless screen._",
    ]
    return "\n".join(lines)
