"""Engineering-manager interview prep: verified question bank + EM prep pack.

The question bank (``candid/data/em_questions.json``) holds REAL EM interview
questions found through public web research (interview guides, candidate
write-ups, hiring guides). Every entry carries its source URL, so packs never
invent questions. The honest-fallback rule from ``candid.prep_questions``
applies here too: if the bank has no verified questions for a topic, we say
so explicitly instead of fabricating any.

``candid prep em-questions [--topic X] [--json]``
    List the verified EM question bank, optionally filtered to one topic.
``candid prep em [--role TEXT] [--json]``
    Build an EM-specific prep pack from the user's profile + target role:
    leadership-principles deep dive, org-design questions, EM-angle system
    design prompts, stakeholder-management scenarios, and STAR prompts drawn
    only from the user's real resume bullets.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C

_BANK_PATH = Path(__file__).resolve().parent / "data" / "em_questions.json"


class EMPrepError(Exception):
    """Raised when the EM question bank cannot be loaded or read."""


_BANK: dict | None = None


def load_bank() -> dict:
    """Load (and cache) the verified EM question bank JSON."""
    global _BANK
    if _BANK is None:
        try:
            _BANK = json.loads(_BANK_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EMPrepError(
                f"Could not load the EM question bank at {_BANK_PATH}: {exc}"
            ) from exc
    return _BANK


def _norm(topic: str) -> str:
    return "".join(c for c in str(topic).lower() if c.isalnum() or c == "_")


def topics() -> list[dict]:
    """Topic metadata: slug, label, blurb, and verified-question count."""
    bank = load_bank()
    counts: dict[str, int] = {}
    for q in bank.get("questions", []):
        counts[q["topic"]] = counts.get(q["topic"], 0) + 1
    out = []
    for slug, meta in bank.get("topics", {}).items():
        out.append({
            "slug": slug,
            "label": meta.get("label", slug),
            "blurb": meta.get("blurb", ""),
            "count": counts.get(slug, 0),
        })
    return out


def questions_by_topic(topic: str) -> list[dict]:
    """Verified questions for one topic slug (case-insensitive).

    Returns an empty list when the bank has no verified questions for the
    topic - callers should surface :func:`no_questions_note` instead of
    inventing questions.
    """
    want = _norm(topic)
    return [q for q in load_bank().get("questions", [])
            if _norm(q.get("topic", "")) == want]


def no_questions_note(topic: str) -> str:
    """Honest fallback when a topic has no verified questions."""
    return (
        f"> **No verified questions for topic {topic!r}.** We have not found "
        "publicly reported EM interview questions for this topic in our bank. "
        "Add real ones (with source URLs) to `candid/data/em_questions.json` "
        "so future packs include them."
    )


def list_questions(topic: str | None = None) -> tuple[list[dict], str | None]:
    """All questions, or one topic's; returns (questions, honest-note-or-None)."""
    if topic is None:
        return list(load_bank().get("questions", [])), None
    qs = questions_by_topic(topic)
    if not qs:
        return [], no_questions_note(topic)
    return qs, None


def render_bank_text(topic: str | None = None) -> str:
    """Human-readable rendering of the bank (optionally one topic)."""
    qs, note = list_questions(topic)
    lines = ["# Verified EM interview questions", ""]
    if topic is not None and qs:
        label = next((t["label"] for t in topics()
                      if _norm(t["slug"]) == _norm(topic)), topic)
        lines.append(f"_Topic: {label} ({len(qs)} verified questions)_\n")
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for q in qs:
        if q["topic"] not in grouped:
            grouped[q["topic"]] = []
            order.append(q["topic"])
    for q in qs:
        grouped[q["topic"]].append(q)
    labels = {t["slug"]: t["label"] for t in topics()}
    for slug in (order if topic else [t["slug"] for t in topics()]):
        items = grouped.get(slug, [])
        if not items:
            continue
        lines.append(f"## {labels.get(slug, slug)}")
        lines.append("")
        for i, q in enumerate(items, 1):
            lines.append(f"{i}. {q['q']}")
            reported = f" (reported {q['reported']})" if q.get("reported") else ""
            lines.append(f"   ↳ *Source: {q['source']}{reported}*")
            lines.append(f"     {q['url']}")
        lines.append("")
    if note:
        lines.append(note)
        lines.append("")
    lines.append("_Every question above was publicly reported with its source. "
                 "Questions are never fabricated._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Leadership-principles deep dive (Amazon's public Leadership Principles,
# the framework most EM interview loops are explicitly mapped to).
# ---------------------------------------------------------------------------

_AMAZON_LPS: list[tuple[str, str]] = [
    ("Customer Obsession", "Frame every EM story from the customer backward: "
     "what user pain did your team solve, and how did you measure it?"),
    ("Ownership", "Show you acted beyond your lane: picked up the incident, "
     "the hiring gap, or the failing project nobody owned."),
    ("Invent and Simplify", "Talk about a process or system you simplified "
     "while raising the bar - managers are judged on leverage, not heroics."),
    ("Are Right, A Lot", "Demonstrate judgment: a decision you made with "
     "incomplete data that proved correct, and what you would redo."),
    ("Learn and Be Curious", "What did you deliberately learn in the last "
     "year - a technology, a management craft skill - and how did it change "
     "your team?"),
    ("Hire and Develop the Best", "Your hiring bar, a hard 'no hire' call "
     "you made, and an engineer you grew into a bigger scope."),
    ("Insist on the Highest Standards", "Where you raised the bar: code "
     "review culture, on-call quality, design docs - and how the team "
     "responded."),
    ("Think Big", "A bet you pushed that was bigger than the quarterly plan: "
     "platform investment, reorg, or technical strategy."),
    ("Bias for Action", "A fast decision under ambiguity; EMs are evaluated "
     "on whether they unblock or wait for perfect information."),
    ("Frugality", "Doing more with less: headcount tradeoffs, infra cost "
     "wins, or scope discipline that saved the quarter."),
    ("Earn Trust", "A time you delivered bad news upward early, or told a "
     "stakeholder something they did not want to hear."),
    ("Dive Deep", "Staying technical as a manager: the incident where you "
     "read the code/logs yourself instead of managing the status thread."),
    ("Have Backbone; Disagree and Commit", "A decision you argued against, "
     "then committed to fully once it was made."),
    ("Deliver Results", "Outcomes with numbers: what shipped, what improved, "
     "what the business got - from work you led, not did."),
    ("Strive to be Earth's Best Employer", "How you made your team a place "
     "people grow: retention, psychological safety, career ladders."),
    ("Success and Scale Bring Broad Responsibility", "How your decisions "
     "considered people beyond your team: customers, partner teams, the "
     "wider org."),
]


def _leadership_principles_section() -> str:
    lines = [
        "## 1. Leadership-principles deep dive",
        "",
        "_Amazon's 16 Leadership Principles are public, and most EM interview "
        "loops are explicitly mapped to them. For each principle, prepare one "
        "STAR story from your own experience - the EM angle is what the "
        "interviewer listens for._",
        "",
    ]
    for name, angle in _AMAZON_LPS:
        lines.append(f"**{name}** - {angle}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EM-angle system design prompts. These are GENERAL practice prompts - clearly
# labeled as not verified at any company. The EM system-design round evaluates
# how you LEAD a design discussion, not just the boxes and arrows.
# ---------------------------------------------------------------------------

_EM_SYSTEM_DESIGN_PROMPTS: list[tuple[str, str]] = [
    ("Design a rate limiter for a public API.",
     "EM angle: narrate trade-offs out loud (token bucket vs. fixed window, "
     "distributed counters) and show how you would coach a mid-level engineer "
     "through the same reasoning."),
    ("Design a notification service (email/SMS/push) at scale.",
     "EM angle: the team proposes Kafka + workers; a staff engineer wants a "
     "managed service. How do you make the build-vs-buy call and get buy-in?"),
    ("Design a URL shortener.",
     "EM angle: run it as a design review - how do you keep two senior "
     "engineers with opposing approaches converging instead of stalling?"),
    ("Design the on-call rotation and incident-response process for a 24/7 "
     "payments service.",
     "EM angle: this tests operational leadership - escalation policy, "
     "blameless postmortems, and how you keep the team healthy on call."),
    ("Design a product analytics pipeline.",
     "EM angle: how do you scope an MVP the team can ship in 6 weeks versus "
     "the 'complete' platform, and how do you sell that scope upward?"),
]


def _system_design_section() -> str:
    lines = [
        "## 3. EM-angle system design prompts",
        "",
        "_General EM system-design practice prompts - not verified as asked at "
        "any specific company. The EM system-design round evaluates how you "
        "lead a design discussion: trade-offs, decision-making, and coaching - "
        "not just the architecture._",
        "",
    ]
    for i, (prompt, angle) in enumerate(_EM_SYSTEM_DESIGN_PROMPTS, 1):
        lines.append(f"{i}. **{prompt}**")
        lines.append(f"   {angle}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Profile-driven sections: STAR prompts from real resume bullets only.
# ---------------------------------------------------------------------------

_EM_STAR_ROTATION = [
    "Tell me about a time you grew an engineer or raised the team's bar.",
    "Tell me about a time you managed an underperformer or a hard people situation.",
    "Tell me about a time you influenced a decision without direct authority.",
    "Tell me about a time you owned an incident or a failing project.",
    "Tell me about a time you had to hire or staff up under pressure.",
]


def _top_bullets(profile: dict, limit: int = 5) -> list[tuple[str, str, str]]:
    """Strongest resume bullets: most recent experience, numbers first."""
    bullets: list[tuple[str, str, str]] = []
    for e in profile.get("experience", [])[:3]:
        for b in e.get("bullets", [])[:3]:
            text = str(b).strip()
            if text:
                bullets.append((e.get("title", ""), e.get("company", ""), text))
    bullets.sort(key=lambda t: (any(ch.isdigit() for ch in t[2]), len(t[2])),
                 reverse=True)
    return bullets[:limit]


def _star_section(profile: dict) -> str:
    lines = [
        "## 5. Your experience, EM-framed",
        "",
        "_Each classic EM behavioral question is paired with one of your real "
        "resume bullets. Draft each answer as Situation → Task → Action → "
        "Result, 150+ words, said out loud - never invent details that are "
        "not in the bullet._",
        "",
    ]
    top = _top_bullets(profile)
    if not top:
        lines += ["_No resume bullets found - write 3 STAR stories from your "
                  "proudest projects (one people, one delivery, one "
                  "technical judgment) before interview day._", ""]
        return "\n".join(lines)
    for i, (title, company, bullet) in enumerate(top):
        q = _EM_STAR_ROTATION[i % len(_EM_STAR_ROTATION)]
        at = f" ({title} @ {company})" if title or company else ""
        lines += [
            f"**{q}**",
            "",
            f"> Your bullet{at}: \"{bullet}\"",
            "",
            "*EM framing:* interviewers listen for scope (team size), the "
            "people decision you made (hire, coach, reassign, let go), the "
            "stakeholders you aligned, and the outcome in numbers.",
            "",
        ]
    return "\n".join(lines)


def _verified_section(topic_slugs: list[str], heading: str, number: int) -> str:
    """Verified bank questions for the given topics, with sources."""
    lines = [f"## {number}. {heading}", ""]
    any_q = False
    labels = {t["slug"]: t["label"] for t in topics()}
    for slug in topic_slugs:
        qs = questions_by_topic(slug)
        if not qs:
            lines.append(no_questions_note(slug))
            lines.append("")
            continue
        any_q = True
        lines.append(f"### {labels.get(slug, slug)}")
        lines.append("")
        for i, q in enumerate(qs, 1):
            lines.append(f"{i}. {q['q']}")
            reported = f" (reported {q['reported']})" if q.get("reported") else ""
            lines.append(f"   ↳ *Source: {q['source']}{reported}*")
            lines.append(f"     {q['url']}")
        lines.append("")
    if not any_q:
        lines.append("_No verified questions yet for these topics._")
        lines.append("")
    lines.append("_These are questions EM candidates publicly reported. Treat "
                 "them as representative of style and topics._")
    lines.append("")
    return "\n".join(lines)


def _mock_section(profile: dict) -> str:
    lines = [
        "## 6. Mock EM interview (tailored to you)",
        "",
        "_Answer out loud, 3-4 minutes each. The follow-ups are where EM "
        "loops are won or lost - prepare a second level of detail for each._",
        "",
    ]
    top = _top_bullets(profile, limit=3)
    if top:
        for i, (title, company, bullet) in enumerate(top, 1):
            at = f" ({title} @ {company})" if title or company else ""
            lines += [
                f"**Q{i}. You list{at}: \"{bullet}\"**",
                "",
                "Walk me through the hardest people or process problem on "
                "that work - not the technical problem, the human one. "
                "Follow-up: what would you do differently as the manager?",
                "",
            ]
    else:
        lines += ["_Onboard your resume first (`python -m candid onboard "
                  "--resume resume.pdf`) to get tailored mock questions._", ""]
    lines += [
        "**Q (hiring).** Your team has headcount for two engineers but the "
        "roadmap needs four. Walk me through your hiring plan and what you "
        "tell leadership.",
        "",
        "**Q (managing up).** Your director asks for a date on work the team "
        "says is un-estimable. What do you say in the meeting, and what do "
        "you say to the team after?",
        "",
        "_These two are general EM practice prompts, not verified as asked "
        "at any company._",
        "",
    ]
    return "\n".join(lines)


def _jd_topic_hints(jd: str) -> list[str]:
    """Order pack topics by what the JD emphasizes (keyword scan)."""
    low = (jd or "").lower()
    hints: list[tuple[str, list[str]]] = [
        ("hiring", ["hiring", "recruit", "grow the team", "talent", "headcount"]),
        ("performance_management", ["performance", "coach", "mentor", "feedback", "growth"]),
        ("org_design", ["org design", "reorg", "reorganization", "team structure", "scale the team"]),
        ("incident_leadership", ["incident", "on-call", "oncall", "outage", "reliability", "sre"]),
        ("managing_up", ["stakeholder", "leadership", "executive", "strategy", "roadmap"]),
        ("cross_functional", ["cross-functional", "cross functional", "partner", "product", "design"]),
    ]
    scored = [(slug, sum(k in low for k in kws)) for slug, kws in hints]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [slug for slug, s in scored if s > 0]


def build_em_pack(profile: dict, role: str = "Engineering Manager",
                  jd: str = "", company: str = "") -> tuple[str, Path, dict]:
    """Build an EM-specific prep pack. Returns (markdown, saved_path, sections).

    Never invents achievements: all experience references come from the
    profile's real bullets, and all bank questions carry their sources.
    """
    role = role or "Engineering Manager"
    company_line = f" at {company}" if company else ""
    hints = _jd_topic_hints(jd)
    hint_line = ""
    if hints:
        labels = {t["slug"]: t["label"] for t in topics()}
        hint_line = ("_JD emphasis detected: " +
                     ", ".join(labels.get(h, h) for h in hints) +
                     " - those sections are ordered first._\n\n")

    org_slugs = ["org_design"]
    stake_slugs = ["managing_up", "cross_functional"]
    if hints:
        stake_slugs = sorted(stake_slugs,
                             key=lambda s: hints.index(s) if s in hints else 99)

    sections = {
        "title": f"EM Interview Prep Pack: {role}{company_line}",
        "leadership_principles": _leadership_principles_section(),
        "org_design_questions": _verified_section(org_slugs, "Org-design questions (verified)", 2),
        "system_design_prompts": _system_design_section(),
        "stakeholder_scenarios": _verified_section(stake_slugs, "Stakeholder-management scenarios (verified)", 4),
        "star_prompts": _star_section(profile),
        "mock_interview": _mock_section(profile),
    }

    lines = [
        f"# {sections['title']}",
        "",
        f"_Generated {date.today().isoformat()}._",
        "",
        hint_line,
        sections["leadership_principles"],
        "",
        sections["org_design_questions"],
        "",
        sections["system_design_prompts"],
        "",
        sections["stakeholder_scenarios"],
        "",
        sections["star_prompts"],
        "",
        sections["mock_interview"],
        "",
        "---",
        "_Verified questions: `candid/data/em_questions.json` - every bank "
        "question carries its source. General prompts are labeled as such. "
        "Experience references come only from your onboarded profile._",
    ]
    markdown = "\n".join(lines)

    C.ensure_data_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_"
                   for c in f"em-{role}")[:60]
    out = C.PREP_PACKS_DIR / f"{date.today().isoformat()}_{safe}.md"
    out.write_text(markdown, encoding="utf-8")
    return markdown, out, sections


def pack_as_json(profile: dict, role: str = "Engineering Manager",
                 jd: str = "", company: str = "") -> dict:
    """JSON-serializable EM prep pack (for --json)."""
    markdown, path, sections = build_em_pack(profile, role=role, jd=jd,
                                             company=company)
    return {
        "role": role or "Engineering Manager",
        "company": company,
        "generated": date.today().isoformat(),
        "path": str(path),
        "markdown": markdown,
        "sections": sections,
    }


def bank_as_json(topic: str | None = None) -> list[dict] | dict:
    """JSON-serializable question bank (for --json)."""
    qs, note = list_questions(topic)
    if note is not None:
        return {"topic": topic, "questions": [], "note": note}
    return {"topic": topic, "count": len(qs), "questions": qs}
