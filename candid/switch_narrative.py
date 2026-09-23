"""Narrative reframing for career switchers targeting adjacent roles.

Gives a career switcher language to re-angle what they have already done
through the lens of a target role. Two entry points:

  reframe_bullets(bullets, target_role)
      Rewrites each resume bullet so the *same facts* read as evidence for
      the target role. Every bullet keeps its original text verbatim and
      gains a lens prefix naming the transferable competency it evidences.

  career_story_arc(roles, target_role)
      Builds a "tell me about yourself" narrative arc: where the person
      started, what each role added, the common thread across roles, and why
      the target role is the natural next step. Uses only supplied facts.

GROUNDED RULE (critical): neither function invents metrics, tools,
employers, achievements, or anything else not present in the input. Reframing
changes the angle, never the facts. Prefixes and connective prose are
generated from fixed templates with no numbers, tool names, or dates.

Everything is deterministic and local - no network, no paid APIs, no LLM.
"""

from __future__ import annotations

import re


class SwitchNarrativeError(Exception):
    """Raised for invalid input to the narrative reframing helpers."""


# Competency buckets: (label, [regex cues]). First matching bucket wins.
_COMPETENCIES: list[tuple[str, list[str]]] = [
    ("Data & analysis",
     [r"\banalyz", r"\bdata\b", r"\bmetric", r"\bdashboard", r"\bsql\b",
      r"\bmodel", r"a/b", r"\bexperiment", r"\bforecast", r"\binsight"]),
    ("Leadership & ownership",
     [r"\bled\b", r"\bmanaged\b", r"\bmentored\b", r"\bowned\b", r"\bdrove\b",
      r"\bteam\b", r"\bhired\b"]),
    ("Stakeholder communication",
     [r"\bpresented\b", r"\bstakeholder", r"\bcross-?functional\b",
      r"\bcommunicat", r"\bclient\b", r"\bpartnered\b", r"\bdoc\b"]),
    ("Technical delivery",
     [r"\bbuilt\b", r"\bshipped\b", r"\blaunched\b", r"\bdeployed\b",
      r"\bengineered\b", r"\bpython\b", r"\bapi\b", r"\bsystem\b",
      r"\bpipeline\b"]),
    ("Process & operations",
     [r"\bprocess\b", r"\bworkflow\b", r"\bautomat", r"\befficien",
      r"\bstreamlin", r"\breduced\b", r"\bcost\b"]),
    ("Customer & domain expertise",
     [r"\bcustomer\b", r"\buser\b", r"\bux\b", r"\bresearch\b", r"\bsupport\b",
      r"\bfeedback\b"]),
]

_FALLBACK_COMPETENCY = "Cross-functional strength"


def competency_of(bullet: str) -> str:
    """Return the competency label a bullet best evidences (first regex hit)."""
    low = bullet.lower()
    for label, cues in _COMPETENCIES:
        if any(re.search(c, low) for c in cues):
            return label
    return _FALLBACK_COMPETENCY


# Target-role lenses: keyword match -> {competency label -> framing prefix}.
# Prefixes name the transferable aspect; they add no new facts.
_LENSES: list[dict] = [
    {
        "keywords": ["product manager", "product management", "pm "],
        "frames": {
            "Data & analysis": "Data-informed decision making",
            "Leadership & ownership": "Owning outcomes",
            "Stakeholder communication": "Stakeholder alignment",
            "Technical delivery": "Shipping with engineering",
            "Process & operations": "Operational leverage",
            "Customer & domain expertise": "Customer empathy",
        },
        "generic": "Transferable product strength",
    },
    {
        "keywords": ["data scientist", "data science", "ml ", "machine learning"],
        "frames": {
            "Data & analysis": "Quantitative rigor",
            "Leadership & ownership": "Technical ownership",
            "Stakeholder communication": "Translating analysis for stakeholders",
            "Technical delivery": "Building analytical systems",
            "Process & operations": "Measurement discipline",
            "Customer & domain expertise": "Domain-grounded modeling",
        },
        "generic": "Transferable analytical strength",
    },
    {
        "keywords": ["software engineer", "software developer", "backend", "frontend",
                     "full stack", "full-stack", "devops", "sre"],
        "frames": {
            "Data & analysis": "Evidence-driven engineering",
            "Leadership & ownership": "Technical leadership",
            "Stakeholder communication": "Cross-team collaboration",
            "Technical delivery": "Shipping production systems",
            "Process & operations": "Engineering efficiency",
            "Customer & domain expertise": "User-centered building",
        },
        "generic": "Transferable engineering strength",
    },
    {
        "keywords": ["designer", "ux ", "product design"],
        "frames": {
            "Data & analysis": "Research-backed decisions",
            "Leadership & ownership": "Design ownership",
            "Stakeholder communication": "Communicating design rationale",
            "Technical delivery": "Prototyping and iteration",
            "Process & operations": "Design process discipline",
            "Customer & domain expertise": "User advocacy",
        },
        "generic": "Transferable design strength",
    },
    {
        "keywords": ["engineering manager", "team lead", "tech lead"],
        "frames": {
            "Data & analysis": "Metrics-led management",
            "Leadership & ownership": "People leadership",
            "Stakeholder communication": "Org-level communication",
            "Technical delivery": "Delivery through teams",
            "Process & operations": "Scaling process",
            "Customer & domain expertise": "Customer-obsessed teams",
        },
        "generic": "Transferable management strength",
    },
]

_GENERIC_LENS = {
    "frames": {},
    "generic": "Transferable strength",
}


def _lens_for(target_role: str) -> dict:
    low = target_role.lower()
    for lens in _LENSES:
        if any(k in low for k in lens["keywords"]):
            return lens
    return _GENERIC_LENS


def _clean(bullet: str) -> str:
    return re.sub(r"\s+", " ", bullet).strip().rstrip(".")


def reframe_bullets(bullets: list[str], target_role: str) -> list[str]:
    """Rewrite bullets through the target role's lens, facts unchanged.

    Each output bullet is ``"<framing prefix>: <original bullet>"`` where the
    prefix names the transferable competency the bullet evidences. The original
    bullet text (with its metrics, tools, and achievements) is preserved
    verbatim; only the angle changes.
    """
    if not isinstance(bullets, list):
        raise SwitchNarrativeError("bullets must be a list of strings.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise SwitchNarrativeError("target_role must be a non-empty string.")
    lens = _lens_for(target_role)
    out = []
    for b in bullets:
        if not isinstance(b, str) or not b.strip():
            raise SwitchNarrativeError("Each bullet must be a non-empty string.")
        comp = competency_of(b)
        prefix = lens["frames"].get(comp, lens["generic"])
        out.append(f"{prefix}: {_clean(b)}.")
    return out


def career_story_arc(roles: list[dict], target_role: str) -> str:
    """Build a "tell me about yourself" arc using only supplied facts.

    ``roles`` is a list of dicts with keys ``title`` and ``company`` plus
    optional ``dates`` and ``highlights`` (list of fact strings). Roles should
    be ordered oldest-first. Returns a short multi-paragraph script.
    """
    if not isinstance(roles, list) or not roles:
        raise SwitchNarrativeError("roles must be a non-empty list of dicts.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise SwitchNarrativeError("target_role must be a non-empty string.")
    target_role = target_role.strip()
    for r in roles:
        if not isinstance(r, dict) or not r.get("title") or not r.get("company"):
            raise SwitchNarrativeError(
                "Each role needs at least 'title' and 'company'.")

    parts: list[str] = []
    first = roles[0]
    first_facts = [h for h in (first.get("highlights") or []) if isinstance(h, str)]
    dates = f" ({first['dates']})" if first.get("dates") else ""
    opener = f"I started out as a {first['title']} at {first['company']}{dates}"
    if first_facts:
        opener += f", where I {_lead_lower(_clean(first_facts[0]))}"
    opener += "."
    parts.append(opener)

    for r in roles[1:]:
        facts = [h for h in (r.get("highlights") or []) if isinstance(h, str)]
        d = f" ({r['dates']})" if r.get("dates") else ""
        sentence = f"From there I moved to {r['company']} as a {r['title']}{d}"
        if facts:
            sentence += f", where I {_lead_lower(_clean(facts[0]))}"
        sentence += "."
        parts.append(sentence)

    # Common thread: competencies evidenced across the supplied facts.
    all_facts = [h for r in roles for h in (r.get("highlights") or [])
                 if isinstance(h, str)]
    threads = []
    seen = set()
    for f in all_facts:
        c = competency_of(f)
        if c not in seen and c != _FALLBACK_COMPETENCY:
            seen.add(c)
            threads.append(c.lower())
    if threads:
        thread_line = "The common thread across those roles has been " + \
            _oxford(threads) + "."
        parts.append(thread_line)

    last = roles[-1]
    last_fact = all_facts[-1] if all_facts else ""
    pivot = (f"That's what draws me to {target_role} now: the {competency_of(last_fact).lower()} "
             f"I've built as a {last['title']} is exactly what I want to keep doing - "
             f"just pointed at {target_role.lower()} problems.")
    parts.append(pivot)
    parts.append(f"So I'm looking to bring everything I've learned into a {target_role} role.")
    return "\n\n".join(parts)


def _lead_lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _oxford(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
