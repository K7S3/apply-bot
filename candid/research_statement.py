"""Research statement generator for candid.

Builds a grounded research-statement draft from the user's stored profile:
past research is distilled ONLY from profile publications / projects /
experience, the current direction is a synthesis of the profile's summary,
skills, and most recent role, and future directions are a clearly-marked
SCAFFOLD of prompts the user must fill in themselves ("TODO: personalize").
Nothing is ever invented.
"""

from __future__ import annotations

import argparse

SCAFFOLD_MARKER = "TODO: personalize"

# Generic future-direction prompts. These are questions for the user, never
# pre-filled plans; they contain no profile facts so nothing can leak in.
SCAFFOLD_PROMPTS: list[str] = [
    "What open problem in the field do you want to tackle in the next 2-3 years, and why is now the right time?",
    "Which of your past methods or results would you build on first, and what would you do differently?",
    "What collaboration or resources in the target lab/group would accelerate this work, and what do you bring to them?",
    "What does success look like for you in this role (publications, systems, real-world impact)?",
    "What is your 5-year vision: the research program you would lead and the questions it would answer?",
]


def _profile_text(profile: dict) -> list[str]:
    """Collect every profile text the statement may draw from."""
    texts: list[str] = []
    for key in ("summary", "headline"):
        if profile.get(key):
            texts.append(str(profile[key]))
    for exp in profile.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        for key in ("title", "company", "dates"):
            if exp.get(key):
                texts.append(str(exp[key]))
        for b in exp.get("bullets") or []:
            if b:
                texts.append(str(b))
    for key in ("publications", "projects"):
        for item in profile.get(key) or []:
            if isinstance(item, dict):
                texts.append(" ".join(str(v) for v in item.values() if v))
            elif item:
                texts.append(str(item))
    return texts


def _past_research_items(profile: dict) -> list[dict]:
    """Distill past-research bullets ONLY from profile data.

    Each bullet is verbatim profile content (an experience bullet, a
    publication citation, or a project description) tagged with its source,
    so nothing can be invented.
    """
    items: list[dict] = []

    def _cite(title: str, venue: str, year: str) -> str:
        bits = [b for b in (title.strip(), venue.strip(), year.strip()) if b]
        return " — ".join(bits)

    for pub in profile.get("publications") or []:
        if isinstance(pub, dict):
            text = _cite(str(pub.get("title", "")), str(pub.get("venue", "") or pub.get("journal", "") or pub.get("conference", "")), str(pub.get("year", "")))
        else:
            text = str(pub)
        text = text.strip()
        if text:
            items.append({"text": text, "source": "publication (from your profile)"})

    for proj in profile.get("projects") or []:
        if isinstance(proj, dict):
            text = " — ".join(str(v).strip() for v in proj.values() if str(v).strip())
        else:
            text = str(proj).strip()
        if text:
            items.append({"text": text, "source": "project (from your profile)"})

    for exp in profile.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        where = " — ".join(p for p in (str(exp.get("title", "")), str(exp.get("company", ""))) if p.strip())
        for b in exp.get("bullets") or []:
            b = str(b).strip()
            if b:
                items.append({"text": b, "source": f"experience: {where}" if where else "experience (from your profile)"})
    return items


def _current_direction(profile: dict) -> str:
    """Synthesize the current research direction from profile data only.

    No future plans are stated here; it summarizes what the profile shows
    the user is working on now.
    """
    bits: list[str] = []
    exps = [e for e in (profile.get("experience") or []) if isinstance(e, dict)]
    if exps:
        cur = exps[0]
        role = " — ".join(p for p in (str(cur.get("title", "")), str(cur.get("company", ""))) if p.strip())
        if role:
            bits.append(f"Most recent role: {role}.")
    if profile.get("summary"):
        bits.append(str(profile["summary"]).strip())
    skills = [str(s) for s in (profile.get("skills") or [])][:8]
    if skills:
        bits.append("Core methods and tools: " + ", ".join(skills) + ".")
    domains = [str(d) for d in (profile.get("domains") or [])]
    if domains:
        bits.append("Research areas: " + ", ".join(domains) + ".")
    if not bits:
        return "No current-direction signal found in your profile yet — add a summary or experience bullets."
    return " ".join(bits)


def build_statement(profile: dict, *, lab: str = "", pi: str = "") -> dict:
    """Build a grounded research-statement draft dict.

    ``lab`` / ``pi`` optionally tailor the framing paragraph. The returned
    dict has keys: name, framing, past_research (list of {text, source}),
    current_direction (str), scaffold (list of {prompt, marker}).
    """
    profile = profile or {}
    lab = (lab or "").strip()
    pi = (pi or "").strip()

    if lab and pi:
        framing = (
            f"This statement summarizes my research background and interests "
            f"as they relate to {lab}, led by {pi}. Everything below the "
            f"scaffold is drawn from my profile; the scaffold lists the "
            f"future-direction prompts I will personalize for this lab."
        )
    elif lab:
        framing = (
            f"This statement summarizes my research background and interests "
            f"as they relate to {lab}. Everything below the scaffold is "
            f"drawn from my profile; the scaffold lists the future-direction "
            f"prompts I will personalize for this lab."
        )
    else:
        framing = (
            "This statement summarizes my research background and current "
            "direction, drawn entirely from my profile. The scaffold at the "
            "end lists future-direction prompts to personalize for each "
            "application — it is intentionally left blank."
        )

    scaffold = [{"prompt": p, "marker": SCAFFOLD_MARKER} for p in SCAFFOLD_PROMPTS]

    return {
        "name": profile.get("name", ""),
        "framing": framing,
        "lab": lab,
        "pi": pi,
        "past_research": _past_research_items(profile),
        "current_direction": _current_direction(profile),
        "scaffold": scaffold,
    }


def render_markdown(statement: dict) -> str:
    """Render the statement dict as Markdown."""
    lines: list[str] = []
    title = "Research Statement"
    if statement.get("name"):
        title += f" — {statement['name']}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(statement.get("framing", ""))
    lines.append("")
    lines.append("## Past Research (from my profile)")
    lines.append("")
    past = statement.get("past_research", [])
    if past:
        for item in past:
            lines.append(f"- {item['text']}")
            lines.append(f"  - *Source: {item['source']}*")
    else:
        lines.append("_No publications, projects, or experience bullets in the profile yet._")
    lines.append("")
    lines.append("## Current Direction (from my profile)")
    lines.append("")
    lines.append(statement.get("current_direction", ""))
    lines.append("")
    lines.append("## Future Directions — SCAFFOLD")
    lines.append("")
    lines.append(
        "> The prompts below are intentionally blank. Fill each one in "
        "yourself before sending; nothing here should be invented for you."
    )
    lines.append("")
    for item in statement.get("scaffold", []):
        lines.append(f"- **{item['marker']}** — {item['prompt']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_research_statement(a: argparse.Namespace) -> None:
    """CLI handler for `candid research-statement`."""
    from candid import profile as P
    prof = P.load_profile()
    statement = build_statement(prof, lab=a.lab or "", pi=a.pi or "")
    md = render_markdown(statement)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Saved to {a.out}")
    else:
        print(md)


def add_parsers(subparsers) -> None:
    """Register the `research-statement` subcommand on an argparse subparsers object."""
    s = subparsers.add_parser(
        "research-statement",
        help="Draft a grounded research statement from your profile.",
        description=(
            "Generate a research-statement draft distilled only from your "
            "profile (publications, projects, experience). Future directions "
            "are a scaffold of TODO prompts you fill in yourself — nothing "
            "is invented."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "examples:",
            "  python -m candid research-statement",
            "  python -m candid research-statement --lab \"Vision Lab\" --pi \"Dr. Rao\"",
            "  python -m candid research-statement --lab \"Vision Lab\" --out statement.md",
        ]),
    )
    s.add_argument("--lab", default="", help="Target lab/group name (tailors the framing paragraph)")
    s.add_argument("--pi", default="", help="Target PI name (tailors the framing paragraph)")
    s.add_argument("--out", default="", help="Write Markdown to this file instead of stdout")
    s.set_defaults(func=cmd_research_statement)
