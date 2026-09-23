"""Research framing + research statement builder.

Two offline, template-only helpers for researchers on the job market:

1. Publication framing helper — turn a user-supplied project description
   (title, what was built, techniques used, observed outcomes) into a
   paper-style framing document: candidate paper titles, an abstract
   skeleton, novelty claims, generic venue-tier guidance, and a
   related-work checklist.

2. Research statement builder — assemble a 1-2 page research statement
   (Past Research / Current Focus / Future Agenda / Fit) from the user's
   own words, with a rough length check (~800 words) and Markdown export.

NEVER-INVENT RULE: every sentence the module emits is a template filled
with the user's own words, or an explicit ``[FILL IN]`` placeholder the
user must complete. This module never invents experience, metrics,
results, or publications.

All file paths follow the config.py convention (data under
``candid_data/``, overridable via ``CANDID_DATA_DIR``).
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import config as C
from candid import profile as P

# --- module-local data-dir paths (config.py is not modified) -----------------
FRAMINGS_DIR = C.DATA_DIR / "research_framings"
STATEMENTS_DIR = C.DATA_DIR / "research_statements"

#: Placeholder marker required in every slot the user must complete.
FILL = "[FILL IN]"

#: Claim provenance label — every novelty claim is grounded in user input.
USER_STATED = "user-stated"

#: Rough word target for a 1-2 page research statement.
TARGET_WORDS = 800
MIN_OK_WORDS = 600
MAX_OK_WORDS = 1000


class FrameError(ValueError):
    """Raised when framing/statement input is missing or malformed."""


DISCLAIMER = (
    "NOTE: This document was assembled from templates and YOUR words only. "
    "Every blank marked [FILL IN] must be completed by you. Verify every "
    "novelty claim against the literature before citing it anywhere."
)


# ===========================================================================
# FEATURE 1 — publication framing helper
# ===========================================================================

REQUIRED_PROJECT_FIELDS = ("title", "description")
OPTIONAL_PROJECT_FIELDS = ("techniques", "outcomes", "context")


def _as_list(value: object) -> list[str]:
    """Normalize a string or list value into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [p.strip(" -•\t") for p in value.replace(";", "\n").splitlines()]
        return [i for i in items if i]
    return [str(i).strip() for i in value if str(i).strip()]


def _normalize_project(project: dict) -> dict:
    """Validate and normalize a raw project dict."""
    if not isinstance(project, dict):
        raise FrameError(
            "frame_project() expects a dict with keys: "
            "title, description, techniques, outcomes (lists or text)."
        )
    missing = [f for f in REQUIRED_PROJECT_FIELDS
               if not str(project.get(f, "")).strip()]
    if missing:
        raise FrameError(
            f"Project is missing required field(s): {', '.join(missing)}. "
            "Provide at least a 'title' and a 'description' of what was built."
        )
    return {
        "title": str(project["title"]).strip(),
        "description": str(project["description"]).strip(),
        "techniques": _as_list(project.get("techniques")),
        "outcomes": _as_list(project.get("outcomes")),
        "context": str(project.get("context", "") or "").strip(),
    }


def _title_candidates(proj: dict) -> list[str]:
    """Three template-based paper-title candidates from the user's words."""
    title = proj["title"]
    techs = proj["techniques"]
    tech_phrase = ", ".join(techs[:2]) if techs else FILL + " technique"
    outcomes = proj["outcomes"]
    outcome_hook = f"Evidence from {FILL + ' setting/dataset'}"
    return [
        f"{title}: A {tech_phrase} Approach",
        f"Towards Better {title.rstrip('.')} with {tech_phrase}",
        f"{title} — {outcome_hook if outcomes else FILL + ' qualifier'}",
    ]


def _abstract_skeleton(proj: dict) -> dict[str, str]:
    """Abstract skeleton: 4 labeled paragraphs with [FILL IN] slots."""
    title = proj["title"]
    techs = ", ".join(proj["techniques"]) if proj["techniques"] else FILL + " technique(s)"
    return {
        "problem": (
            f"{proj['description']} "  # user's own words
            f"Despite prior work, {FILL + ' the specific gap this addresses'} "
            f"remains unsolved in {FILL + ' the application domain'}."
        ),
        "approach": (
            f"We built {title} using {techs}. "
            f"The key idea is {FILL + ' the core technical idea in one sentence'}. "
            f"{FILL + ' What distinguishes this approach from the closest prior work'}."
        ),
        "results": (
            f"{('We observed: ' + '; '.join(proj['outcomes']) + '.') if proj['outcomes'] else ''} "
            f"{FILL + ' Add measured results here (numbers, baselines, significance) — do not invent them'}. "
            f"Evaluation was conducted on {FILL + ' dataset / benchmark / setting'}."
        ),
        "contribution": (
            f"Our contributions are: "
            f"(1) {FILL + ' first concrete contribution'}; "
            f"(2) {FILL + ' second concrete contribution'}; "
            f"(3) {FILL + ' released artifacts, if any (code, data, models)'}."
        ),
    }


def _claims(proj: dict) -> list[dict[str, str]]:
    """Novelty claims derived ONLY from what the user wrote, labeled user-stated."""
    claims = []
    for tech in proj["techniques"]:
        claims.append({
            "text": f"Applies {tech} in the context of {proj['title']}.",
            "basis": USER_STATED,
            "source": "user-supplied techniques list",
        })
    for outcome in proj["outcomes"]:
        claims.append({
            "text": f"Observed outcome: {outcome} (verify with supporting evidence before citing).",
            "basis": USER_STATED,
            "source": "user-supplied outcomes list",
        })
    claims.append({
        "text": f"Presents a working implementation of: {proj['title']}.",
        "basis": USER_STATED,
        "source": "user-supplied project description",
    })
    return claims


VENUE_TIERS = [
    {
        "tier": "Workshop",
        "consider_if": [
            "The work is preliminary or exploratory.",
            "You want early feedback before a full submission.",
            "Results are promising but not yet complete or fully evaluated.",
        ],
        "expect": "Short format (typically 4 pages); faster, lighter review; "
                  "good venue for work-in-progress and discussion.",
    },
    {
        "tier": "Top-tier conference",
        "consider_if": [
            "The story is complete: clear problem, approach, and measured results.",
            "You can state a concrete novelty claim relative to prior work.",
            "You have baselines or comparisons reviewers will expect.",
        ],
        "expect": "Full paper; competitive review; strong emphasis on novelty "
                  "and empirical rigor. No specific venue is suggested here — "
                  "match the paper's topic to the venue's scope yourself.",
    },
    {
        "tier": "Journal",
        "consider_if": [
            "The work is mature and you want space for extended analysis.",
            "You have follow-up experiments, ablations, or theory to include.",
            "You prefer a longer review cycle with room for revision.",
        ],
        "expect": "Longer format; emphasis on completeness, reproducibility, "
                  "and archival value rather than speed.",
    },
]

RELATED_WORK_ALWAYS = [
    f"The closest prior work to this project: {FILL + ' cite and summarize'}",
    f"Baselines reviewers will expect you to compare against: {FILL + ' list them'}",
    f"Datasets or benchmarks used by related work: {FILL + ' list them'}",
    "Limitations of your approach and where it breaks: write honestly — reviewers notice.",
    f"Positioning: one sentence on how this differs from the single most similar paper: {FILL + ' sentence'}",
]


def _related_work_checklist(proj: dict) -> list[str]:
    items = [
        f"Prior work applying {tech} to similar problems: {FILL + ' survey and cite'}"
        for tech in proj["techniques"]
    ]
    return items + list(RELATED_WORK_ALWAYS)


def frame_project(project: dict) -> dict:
    """Build a paper-style framing document from a user-supplied project.

    ``project`` keys: ``title`` (required), ``description`` (required),
    ``techniques`` (list or text, optional), ``outcomes`` (list or text,
    optional), ``context`` (optional free text).

    Returns a dict with: project, candidate_titles, abstract_skeleton,
    claims, venue_tiers, related_work_checklist, disclaimer.
    """
    proj = _normalize_project(project)
    return {
        "project": proj,
        "candidate_titles": _title_candidates(proj),
        "abstract_skeleton": _abstract_skeleton(proj),
        "claims": _claims(proj),
        "venue_tiers": VENUE_TIERS,
        "related_work_checklist": _related_work_checklist(proj),
        "disclaimer": DISCLAIMER,
    }


def render_framing(framing: dict) -> str:
    """Render a framing dict (from frame_project) as Markdown."""
    proj = framing["project"]
    lines = [f"# Publication framing: {proj['title']}", "", DISCLAIMER, ""]
    lines += ["## Candidate paper titles", ""]
    for i, t in enumerate(framing["candidate_titles"], 1):
        lines.append(f"{i}. {t}")
    lines += ["", "## Abstract skeleton", ""]
    for label in ("problem", "approach", "results", "contribution"):
        lines.append(f"**{label.capitalize()}.** {framing['abstract_skeleton'][label]}")
        lines.append("")
    lines += ["## Novelty claims (user-stated only)", ""]
    for c in framing["claims"]:
        lines.append(f"- {c['text']} _(basis: {c['basis']}; source: {c['source']})_")
    lines += ["", "## Venue tiers (generic guidance — no venue recommendations)", ""]
    for v in framing["venue_tiers"]:
        lines.append(f"### {v['tier']}")
        lines.append("Consider if:")
        lines += [f"- {s}" for s in v["consider_if"]]
        lines.append(f"Expect: {v['expect']}")
        lines.append("")
    lines += ["## Related-work checklist", ""]
    lines += [f"- [ ] {item}" for item in framing["related_work_checklist"]]
    if proj.get("context"):
        lines += ["", f"_Project context (your words): {proj['context']}_"]
    return "\n".join(lines).rstrip() + "\n"


def save_framing(framing: dict, path: str | Path | None = None) -> Path:
    """Write the rendered framing Markdown to ``path`` (default data dir)."""
    dest = Path(path) if path else (
        FRAMINGS_DIR / f"framing-{_slug(framing['project']['title'])}.md"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_framing(framing), encoding="utf-8")
    return dest


def _slug(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "project"


# ---------------------------------------------------------------------------
# project intake: pasted text and/or candid profile
# ---------------------------------------------------------------------------

INTAKE_LABELS = {
    "title": ("title", "project", "name"),
    "description": ("description", "what was built", "what i built", "built", "summary"),
    "techniques": ("techniques", "methods", "tech stack", "tools", "approach"),
    "outcomes": ("outcomes", "results", "observations", "findings"),
    "context": ("context", "background"),
}


def intake_project(text: str | None = None,
                   profile_path: str | Path | None = None,
                   project_index: int = 0) -> dict:
    """Build a project dict for frame_project() from pasted text and/or profile.

    - Pasted text: labeled lines like ``Title: ...``, ``Techniques: ...``,
      ``Outcomes: ...`` are parsed; unlabeled text becomes the description,
      with the first non-empty line used as the title.
    - Profile: if ``profile_path`` is given (or the default candid profile
      exists and has a ``projects`` list), the entry at ``project_index``
      is merged under the pasted text (pasted text wins on conflicts).

    Works fully standalone: ``intake_project(text="...")`` needs no profile.
    """
    merged: dict = {}
    profile_projects: list[dict] = []

    if profile_path is not None or C.PROFILE_PATH.exists():
        try:
            profile = P.load_profile(profile_path)
        except Exception:
            profile = {}
        raw = profile.get("projects") if isinstance(profile, dict) else None
        if isinstance(raw, list):
            profile_projects = [p for p in raw if isinstance(p, dict)]

    if profile_projects:
        try:
            base = profile_projects[project_index]
        except IndexError:
            raise FrameError(
                f"Profile has {len(profile_projects)} project(s); "
                f"project_index={project_index} is out of range."
            ) from None
        for key in ("title", "description", "techniques", "outcomes", "context"):
            if base.get(key):
                merged[key] = base[key]
    elif profile_path is not None:
        raise FrameError(
            "No 'projects' entries found in the candid profile. "
            "Paste the project as text instead: intake_project(text=...)."
        )

    if text:
        merged.update(_parse_intake_text(text))

    if not merged:
        raise FrameError(
            "Nothing to frame: pass pasted text via text=..., or store "
            "projects in your candid profile first."
        )
    return merged


def _parse_intake_text(text: str) -> dict:
    """Parse labeled/unlabeled pasted text into project fields."""
    fields: dict[str, list[str]] = {}
    unlabeled: list[str] = []
    current: str | None = None

    def label_for(line: str) -> str | None:
        if ":" not in line:
            return None
        head = line.split(":", 1)[0].strip().lower()
        for field, aliases in INTAKE_LABELS.items():
            if head in aliases:
                return field
        return None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = label_for(line)
        if label:
            current = label
            rest = line.split(":", 1)[1].strip()
            fields.setdefault(label, [])
            if rest:
                fields[label].append(rest)
        elif current:
            fields[current].append(line)
        else:
            unlabeled.append(line)

    project: dict = {}
    for field, lines in fields.items():
        project[field] = "\n".join(lines).strip()
    if unlabeled:
        if "title" not in project:
            project["title"] = unlabeled[0]
            rest = unlabeled[1:]
        else:
            rest = unlabeled
        if rest and "description" not in project:
            project["description"] = "\n".join(rest).strip()
    return project


# ===========================================================================
# FEATURE 2 — research statement builder
# ===========================================================================

REQUIRED_STATEMENT_FIELDS = ("past_projects", "current_focus", "future_agenda")

STATEMENT_TEMPLATES = {
    "past_intro": (
        "My research to date has focused on {focus_hint}. "
        "The projects below trace how my questions and methods developed."
    ),
    "project_para": (
        "**{title}.** {description}"
        "{outcomes_sentence} "
        f"{FILL + ' status: published / in submission / class project / industry work'}"
    ),
    "current_focus": (
        "My current work centers on {current_focus}. "
        f"{FILL + ' Why this matters: 1-2 sentences in your words'}. "
        f"{FILL + ' The open question driving this work'}."
    ),
    "agenda_intro": (
        "Looking ahead, my research agenda pursues the following directions. "
        f"Each is a question I intend to answer, not a result I claim to have: "
        f"{FILL + ' adjust or reorder as needed'}."
    ),
    "agenda_item": (
        "{n}. **{item}** "
        f"{FILL + ' planned approach and expected contribution'}"
    ),
    "fit": (
        "I am particularly drawn to {target} because "
        f"{FILL + ' 2-3 sentences connecting your agenda to this group/lab/role, in your words'}. "
        "My background in {skills_hint} maps directly onto the problems this group tackles."
    ),
}


def _word_count(text: str) -> int:
    return len(text.split())


def _length_note(words: int) -> str:
    if words < MIN_OK_WORDS:
        return (
            f"{words} words — well under the ~{TARGET_WORDS}-word target for a "
            "1-2 page statement. Expand with your own detail (methods, "
            "results, open questions) rather than filler."
        )
    if words > MAX_OK_WORDS:
        return (
            f"{words} words — well over the ~{TARGET_WORDS}-word target. "
            "Trim to your strongest threads; move detail to an appendix or CV."
        )
    return (
        f"{words} words — within the target band for a 1-2 page statement "
        f"(~{TARGET_WORDS} words)."
    )


def _validate_statement_data(data: dict) -> None:
    if not isinstance(data, dict):
        raise FrameError(
            "build_statement() expects a dict with keys: past_projects "
            "(list), current_focus (text), future_agenda (list), "
            "target (optional text)."
        )
    missing = []
    for field in REQUIRED_STATEMENT_FIELDS:
        val = data.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            missing.append(field)
    if missing:
        raise FrameError(
            f"Research statement is missing required field(s): {', '.join(missing)}. "
            "Provide past_projects (list of {title, description, outcomes}), "
            "current_focus (text), and future_agenda (list of items)."
        )
    for i, proj in enumerate(data["past_projects"]):
        if not isinstance(proj, dict) or not str(proj.get("title", "")).strip():
            raise FrameError(
                f"past_projects[{i}] must be a dict with at least a 'title'."
            )


def build_statement(data: dict) -> dict:
    """Assemble a research statement from the user's own words.

    ``data`` keys: ``past_projects`` (list of dicts with title,
    description, outcomes), ``current_focus`` (text), ``future_agenda``
    (list of text items), ``target`` (optional text: role/lab type),
    ``name`` (optional, used in rendering).

    Returns a dict with sections, word_count, and a length_note warning
    when far over/under ~800 words.
    """
    _validate_statement_data(data)

    sections: dict[str, str] = {}

    past_paras = [STATEMENT_TEMPLATES["past_intro"].format(focus_hint=FILL + " theme")]
    for proj in data["past_projects"]:
        outcomes = _as_list(proj.get("outcomes"))
        outcomes_sentence = (
            f" Observed outcomes: {'; '.join(outcomes)}." if outcomes else ""
        )
        past_paras.append(
            STATEMENT_TEMPLATES["project_para"].format(
                title=str(proj["title"]).strip(),
                description=str(proj.get("description", "")).strip(),
                outcomes_sentence=outcomes_sentence,
            )
        )
    sections["past_research"] = "\n\n".join(past_paras)

    sections["current_focus"] = STATEMENT_TEMPLATES["current_focus"].format(
        current_focus=str(data["current_focus"]).strip()
    )

    agenda_paras = [STATEMENT_TEMPLATES["agenda_intro"]]
    for n, item in enumerate(data["future_agenda"], 1):
        agenda_paras.append(
            STATEMENT_TEMPLATES["agenda_item"].format(
                n=n, item=str(item).strip()
            )
        )
    sections["future_agenda"] = "\n\n".join(agenda_paras)

    target = str(data.get("target", "") or "").strip()
    if target:
        skills_hint = FILL + " 2-3 core skills"
        sections["fit"] = STATEMENT_TEMPLATES["fit"].format(
            target=target, skills_hint=skills_hint
        )

    words = sum(_word_count(s) for s in sections.values())
    return {
        "name": str(data.get("name", "") or "").strip(),
        "target": target,
        "sections": sections,
        "word_count": words,
        "target_words": TARGET_WORDS,
        "length_note": _length_note(words),
    }


def render_statement(stmt: dict) -> str:
    """Render a built statement (from build_statement) as Markdown."""
    name = stmt.get("name") or FILL + " your name"
    target = stmt.get("target", "")
    title_line = f"# Research Statement — {name}"
    lines = [title_line, "", DISCLAIMER, "",
             f"_Length check: {stmt['length_note']}_", ""]
    headings = [
        ("past_research", "Past Research"),
        ("current_focus", "Current Focus"),
        ("future_agenda", "Future Agenda"),
    ]
    if target:
        headings.append(("fit", f"Fit — {target}"))
    for key, heading in headings:
        lines += [f"## {heading}", "", stmt["sections"][key], ""]
    return "\n".join(lines).rstrip() + "\n"


def save_statement(stmt: dict, path: str | Path | None = None) -> Path:
    """Write the rendered statement Markdown to ``path`` (default data dir)."""
    name = stmt.get("name") or "statement"
    dest = Path(path) if path else (
        STATEMENTS_DIR / f"research-statement-{_slug(name)}.md"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_statement(stmt), encoding="utf-8")
    return dest


def load_statement_data(path: str | Path) -> dict:
    """Load statement input data from a JSON file (for CLI use)."""
    p = Path(path)
    if not p.exists():
        raise FrameError(f"Statement data file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrameError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FrameError(f"{p} must contain a JSON object, not {type(data).__name__}.")
    return data
