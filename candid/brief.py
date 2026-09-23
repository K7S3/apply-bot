"""Interview brief builder: one Markdown doc per company loop.

Pulls together the interviewer roster (``candid.interviewers``), role angle
profiles and question ranking (Worker B: ``candid.interviewer_roles`` and
``candid.brief_rank``), panel planning (``candid.panel``), and reverse
questions (``candid.reverse_questions``) into a single prep document.

All interviewer background data is user-supplied; candid never scrapes it.
"""

from __future__ import annotations

import re
from pathlib import Path

from candid import config as C
from candid import brief_rank
from candid import panel as panel_mod
from candid import reverse_questions as rq_mod
from candid import tracker
from candid.interviewer_roles import get_role_profile
from candid import interviewers as roster


SECTION_HEADERS = [
    "## Interviewers",
    "## Likely angles",
    "## Top questions to prepare",
    "## Deep dives",
    "## Panel strategy",
    "## Questions to ask them",
    "## Research checklist",
    "## Debrief history",
]


def _role_label(role: str) -> str:
    profile = get_role_profile(role) or {}
    label = profile.get("label")
    if label:
        return str(label)
    return (role or "interviewer").replace("_", " ").title()


def _background_lines(bg: dict) -> list[str]:
    """Render the user-supplied background dict as highlight bullets."""
    lines: list[str] = []
    bg = bg or {}
    for field in ("title", "team", "tenure"):
        if bg.get(field):
            lines.append(f"- {field.title()}: {bg[field]}")
    for area in bg.get("focus_areas") or []:
        lines.append(f"- Focus area: {area}")
    for talk in bg.get("talks") or []:
        if isinstance(talk, dict):
            topics = ", ".join(talk.get("topics") or [])
            lines.append(f"- Talk: {talk.get('title', '')}" + (f" ({topics})" if topics else ""))
        elif talk:
            lines.append(f"- Talk: {talk}")
    for link in bg.get("public_links") or []:
        if isinstance(link, dict):
            lines.append(f"- Link: {link.get('label', 'link')}: {link.get('url', '')}")
        elif link:
            lines.append(f"- Link: {link}")
    if bg.get("notes"):
        lines.append(f"- Notes: {bg['notes']}")
    return lines


def _normalize_question(entry) -> dict | None:
    """Coerce a questions_db entry to Worker B's question-dict shape.

    Accepts the ``{"q", "category", ...}`` dicts from
    ``candid.prep_questions.QUESTIONS_DB``, plain strings, and dicts with a
    ``"question"`` key.
    """
    if isinstance(entry, dict):
        if entry.get("q"):
            return dict(entry)
        if entry.get("question"):
            return {"q": str(entry["question"]), "category": str(entry.get("category", ""))}
        return None
    if isinstance(entry, str) and entry.strip():
        return {"q": entry.strip(), "category": ""}
    return None


def _ranked_questions(questions_db: list, role: str, jd_text: str, n: int = 5) -> list[dict]:
    """Rank questions via Worker B and normalize to question/rationale dicts."""
    normed = []
    for entry in questions_db or []:
        q = _normalize_question(entry)
        if q:
            normed.append(q)
    if not normed:
        return []
    ranked = brief_rank.rank_questions(normed, role=role, jd_text=jd_text or "")
    out: list[dict] = []
    for entry in ranked or []:
        if isinstance(entry, (tuple, list)) and len(entry) >= 3:
            qdict, _score, rationale = entry[0], entry[1], entry[2]
            text = qdict.get("q", "") if isinstance(qdict, dict) else str(qdict)
        elif isinstance(entry, dict):
            text = entry.get("q", entry.get("question", ""))
            rationale = entry.get("rationale", "")
        else:
            text, rationale = str(entry), ""
        if text:
            out.append({"question": str(text), "rationale": str(rationale)})
        if len(out) >= n:
            break
    return out


def _deep_dives(topics: list[str], role: str, n: int = 2) -> list[dict]:
    """Normalize Worker B's topic_deep_dives output to topic/angle dicts."""
    if not topics:
        return []
    dives = brief_rank.topic_deep_dives(list(topics), role=role, n=n)
    out: list[dict] = []
    for entry in dives or []:
        if isinstance(entry, dict):
            t = entry.get("topic", "")
            a = entry.get("angle", entry.get("prep_angle", ""))
            q = entry.get("question", "")
        else:
            t, a, q = str(entry), "", ""
        if t:
            out.append({"topic": str(t), "angle": str(a), "question": str(q)})
    return out


def _interviewer_topics(iv: dict) -> list[str]:
    """Collect prep topics from an interviewer's background."""
    bg = iv.get("background") or {}
    topics: list[str] = []
    for area in bg.get("focus_areas") or []:
        if area and area not in topics:
            topics.append(str(area))
    for talk in bg.get("talks") or []:
        if isinstance(talk, dict):
            for t in talk.get("topics") or []:
                if t and t not in topics:
                    topics.append(str(t))
    return topics


def build_brief(
    interviewers: list[dict],
    *,
    company: str = "",
    role_title: str = "",
    jd_text: str = "",
    profile_bullets: list[str] | None = None,
    questions_db: list | None = None,
) -> str:
    """Build the full interview brief as Markdown.

    Args:
        interviewers: roster dicts (see ``candid.interviewers``).
        company: company name, used in the title.
        role_title: the role being interviewed for.
        jd_text: job description text, used for question ranking.
        profile_bullets: your story bullets, distributed by ``plan_panel``.
        questions_db: candidate questions to rank per interviewer.
    """
    company = (company or "").strip()
    title = f"# Interview brief: {company}" if company else "# Interview brief"
    lines = [title, ""]
    if role_title:
        lines += [f"Role: {role_title}", ""]

    plan = panel_mod.plan_panel(interviewers, profile_bullets=profile_bullets)
    assignments = {a["interviewer"]: a for a in plan["assignments"]}

    # --- Interviewer cards -------------------------------------------------
    lines += ["## Interviewers", ""]
    if not interviewers:
        lines += ["_No interviewers on the roster yet._", ""]
    for iv in interviewers:
        name = iv.get("name", "")
        role = (iv.get("role") or "").strip().lower()
        label = _role_label(role)
        round_label = iv.get("round_label") or ""
        header = f"### {name} - {label}"
        if round_label:
            header += f" ({round_label})"
        lines += [header, ""]
        for bl in _background_lines(iv.get("background") or {}):
            lines.append(bl)
        if not (iv.get("background") or {}):
            lines.append("_No background notes yet._")
        lines.append("")

    # --- Likely angles -----------------------------------------------------
    lines += ["## Likely angles", ""]
    for iv in interviewers:
        name = iv.get("name", "")
        role = (iv.get("role") or "").strip().lower()
        profile = get_role_profile(role) or {}
        angles = [str(a) for a in (profile.get("angle_categories") or []) if a]
        assignment = assignments.get(name, {})
        focus = assignment.get("focus_categories") or angles[:3]
        lines.append(f"**{name}** ({_role_label(role)}): " + (", ".join(focus) if focus else "general fit"))
    if not interviewers:
        lines.append("_No interviewers on the roster yet._")
    lines.append("")

    # --- Top questions to prepare ------------------------------------------
    lines += ["## Top questions to prepare", ""]
    for iv in interviewers:
        name = iv.get("name", "")
        role = (iv.get("role") or "").strip().lower()
        lines += [f"### For {name}", ""]
        ranked = _ranked_questions(questions_db or [], role, jd_text, n=5)
        if not ranked:
            lines.append("_Add questions to your prep question bank to get ranked picks._")
        for item in ranked:
            line = f"- {item['question']}"
            if item["rationale"]:
                line += f" _(why: {item['rationale']})_"
            lines.append(line)
        lines.append("")

    # --- Deep dives ----------------------------------------------------------
    lines += ["## Deep dives", ""]
    any_dives = False
    for iv in interviewers:
        name = iv.get("name", "")
        role = (iv.get("role") or "").strip().lower()
        dives = _deep_dives(_interviewer_topics(iv), role)
        if not dives:
            continue
        any_dives = True
        lines += [f"### From {name}'s background", ""]
        for d in dives:
            line = f"- {d['topic']}"
            if d["angle"]:
                line += f" ({d['angle']})"
            if d["question"]:
                line += f": {d['question']}"
            lines.append(line)
        lines.append("")
    if not any_dives:
        lines += ["_Add focus areas or talks to interviewer backgrounds to get deep dives._", ""]

    # --- Panel strategy ------------------------------------------------------
    lines += ["## Panel strategy", ""]
    for a in plan["assignments"]:
        focus = ", ".join(a["focus_categories"]) if a["focus_categories"] else "general fit"
        lines.append(f"- **{a['interviewer']}** ({a['role_label']}): lead with {focus}.")
        for tp in a["talking_points"]:
            lines.append(f"  - Tell them: {tp}")
        for av in a["avoid"]:
            lines.append(f"  - Avoid: {av}.")
    for note in plan["strategy_notes"]:
        lines.append(f"- {note}")
    lines.append("")

    # --- Questions to ask them -----------------------------------------------
    lines += ["## Questions to ask them", ""]
    panel_qs = rq_mod.questions_for_panel([(iv.get("role") or "") for iv in interviewers])
    for iv in interviewers:
        name = iv.get("name", "")
        key = ((iv.get("role") or "").strip().lower()) or "generic"
        qs = panel_qs.get(key, [])
        lines += [f"### Ask {name}", ""]
        for q in qs:
            lines.append(f"- {q}")
        lines.append("")

    # --- Research checklist ----------------------------------------------------
    lines += [
        "## Research checklist",
        "",
        "- [ ] Read their latest blog post or launch announcement and note one discussion point.",
        "- [ ] Skim each interviewer's public talks or posts; write one question tied to their focus area.",
        "- [ ] Re-read the job description and map each requirement to one of your stories.",
        "- [ ] Prepare your 2-minute career narrative ending with why this team, why now.",
        "- [ ] List three recent company news items (funding, launch, leadership) you can reference naturally.",
        "",
    ]

    # --- Debrief history -------------------------------------------------------
    lines += ["## Debrief history", ""]
    any_debrief = False
    for iv in interviewers:
        debrief = iv.get("debrief") or {}
        if not debrief:
            continue
        any_debrief = True
        lines += [f"### {iv.get('name', '')}", ""]
        for asked in debrief.get("asked") or []:
            lines.append(f"- Asked: {asked}")
        for signal in debrief.get("signals") or []:
            lines.append(f"- Signal: {signal}")
        if debrief.get("follow_up"):
            lines.append(f"- Follow-up: {debrief['follow_up']}")
        lines.append("")
    if not any_debrief:
        lines += ["_No debriefs recorded yet. Add one after each round with add_debrief._", ""]

    return "\n".join(lines).rstrip() + "\n"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "brief"


def save_brief(markdown: str, company: str) -> Path:
    """Write the brief to ``candid_data/briefs/<company-slug>.md``.

    Returns the path written.
    """
    briefs_dir = C.DATA_DIR / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / f"{_slugify(company)}.md"
    path.write_text(markdown or "", encoding="utf-8")
    return path


def brief_section_for_prep(company: str) -> str:
    """Compact interviewer section for prep packs.

    Looks up tracker apps for the company, then the interviewer roster for
    those apps. Returns "" when there are no interviewers.
    """
    apps = tracker.list_apps(company=company)
    interviewers: list[dict] = []
    for app in apps:
        interviewers.extend(roster.list_interviewers(app_id=app.get("id")))
    if not interviewers:
        return ""

    lines = ["## Interview brief", ""]
    for iv in interviewers:
        name = iv.get("name", "")
        role = (iv.get("role") or "").strip().lower()
        profile = get_role_profile(role) or {}
        angles = [str(a) for a in (profile.get("angle_categories") or []) if a]
        primary = angles[0] if angles else "general fit"
        lines.append(f"- **{name}** ({_role_label(role)}): expect {primary}.")
    lines.append("")
    lines.append("Ask each interviewer one role-specific question from your brief.")
    lines.append("")
    return "\n".join(lines)
