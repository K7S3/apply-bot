"""Design studio: case studies, portfolio site drafts, and talk-through scripts.

Designer-track helpers for turning raw project notes into portfolio-ready
content. Everything is offline and grounded: the functions only use what the
user provides and never invent metrics, outcomes, or praise.

Entry points:
  case_study_wizard(project, answers=None)
      Guided case-study framework: context/problem -> your role -> process
      (research, ideation, iteration) -> outcome/learnings. With ``answers``
      (a dict keyed by section name) it assembles non-interactively;
      without, it prompts interactively. Returns a dict with the structured
      case study plus a ``missing`` list flagging incomplete sections.
  render_case_study_md(cs)
      Render a structured case study to Markdown.
  site_content(profile, projects)
      Generate clearly-labeled DRAFT content for a portfolio site: a homepage
      hero line, an about-page draft, and per-project teaser cards. Saved to
      ``DATA_DIR/design_packs/site_draft.md``. Every line is marked as draft
      for the user to edit.
  walkthrough_script(projects, total_minutes=5)
      Ordered "walk me through your portfolio" narrative across 2-3 projects
      with transitions, timed beats that sum exactly to ``total_minutes``,
      a closing line, and tips for the classic opener and closer.
  export_case_study(cs, fmt="md")
      Write a structured case study to ``DATA_DIR/design_packs/`` as
      Markdown and/or simple single-file HTML (inline CSS, clean typography)
      ready to drop into a portfolio site.

Usage (non-interactive):

    from candid.design_studio import case_study_wizard, export_case_study

    cs = case_study_wizard(project, answers={
        "context_problem": "...", "role": "...", "research": "...",
        "ideation": "...", "iteration": "...", "outcome": "...",
        "learnings": "...",
    })
    print(cs["missing"])          # -> [] when complete
    path = export_case_study(cs, fmt="both")

Style rules (candid-wide): no em dashes in user-facing copy; hyphens and
commas are used instead.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from candid import config as C


def _design_packs_dir() -> Path:
    """Resolved at call time so CANDID_DATA_DIR overrides apply (tests)."""
    return C._data_dir() / "design_packs"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "case-study").lower()).strip("-")
    return s or "case-study"


# --- case-study wizard -------------------------------------------------------

SECTIONS = [
    ("context_problem", "Context / Problem",
     "What was the situation and the core problem you set out to solve?"),
    ("role", "Your Role",
     "What was your role, scope, and what were you responsible for?"),
    ("research", "Process: Research",
     "What research did you do (users, data, competitive, constraints)?"),
    ("ideation", "Process: Ideation",
     "What directions did you explore and how did you decide between them?"),
    ("iteration", "Process: Iteration",
     "What did you test or prototype, what changed, and why?"),
    ("outcome", "Outcome",
     "What actually happened? Use only real results, no invented metrics."),
    ("learnings", "Learnings",
     "What did you take away? What would you do differently?"),
]

_SECTION_TITLE = {key: title for key, title, _ in SECTIONS}


def build_case_study(project: dict, answers: dict) -> dict:
    """Pure: assemble a structured case study from project + section answers.

    ``answers`` maps section keys (see SECTIONS) to free-text. Only the
    provided text is used; nothing is embellished or inferred.
    """
    sections = {}
    for key, _title, _prompt in SECTIONS:
        value = answers.get(key) if answers else None
        sections[key] = (value or "").strip()
    cs = {
        "title": (project.get("title") or project.get("name") or "Untitled project").strip(),
        "project": dict(project),
        "sections": sections,
        "date": date.today().isoformat(),
    }
    cs["missing"] = validate_case_study(cs)
    return cs


def validate_case_study(cs: dict) -> list[str]:
    """Pure: return the section keys whose content is missing or blank."""
    sections = cs.get("sections", {}) or {}
    return [key for key, _t, _p in SECTIONS if not (sections.get(key) or "").strip()]


def _ask(prompt: str) -> str:
    print(f"\n{prompt}")
    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def case_study_wizard(project: dict, answers: dict | None = None) -> dict:
    """Guided case-study framework.

    With ``answers`` given, assemble non-interactively. Otherwise prompt
    interactively per section; blank answers are kept as missing sections.
    Returns the case-study dict with a ``missing`` list of incomplete keys.
    """
    if answers is not None:
        return build_case_study(project, answers)
    title = project.get("title") or project.get("name") or "Untitled project"
    print(f"Case-study wizard: {title}")
    print("Answer each prompt; press Enter to skip a section (it will be flagged).")
    collected: dict = {}
    for key, title, prompt in SECTIONS:
        collected[key] = _ask(f"{title}\n  {prompt}")
    return build_case_study(project, collected)


def render_case_study_md(cs: dict) -> str:
    """Pure: render a structured case study to Markdown.

    Missing sections render as an explicit placeholder so gaps are visible
    rather than silently dropped; no filler content is invented.
    """
    lines = [f"# {cs.get('title', 'Case study')}", ""]
    project = cs.get("project") or {}
    tagline = project.get("tagline") or project.get("summary") or ""
    if tagline:
        lines += [f"*{tagline.strip()}*", ""]
    for key, title, _prompt in SECTIONS:
        body = (cs.get("sections", {}) or {}).get(key, "").strip()
        lines.append(f"## {title}")
        if body:
            lines.append(body)
        else:
            lines.append("_[Not provided yet; fill this in before publishing.]_")
        lines.append("")
    missing = cs.get("missing") or []
    if missing:
        lines.append(f"*Sections still to complete: {', '.join(missing)}*")
    return "\n".join(lines).rstrip() + "\n"


# --- portfolio site content generator ----------------------------------------

def _outcome_bullets(project: dict, n: int = 3) -> list[str]:
    """Pure: pull up to n outcome bullets strictly from the project data."""
    for key in ("outcomes", "results", "bullets", "highlights"):
        items = project.get(key)
        if isinstance(items, list) and items:
            return [str(b).strip() for b in items if str(b).strip()][:n]
    return []


def site_content(profile: dict, projects: list[dict]) -> dict:
    """Generate clearly-labeled DRAFT portfolio site content and save it.

    Returns the content dict and writes ``design_packs/site_draft.md``.
    Everything is marked as draft; outcome bullets come only from the
    project data passed in.
    """
    name = (profile.get("name") or "Your name").strip()
    headline = (profile.get("headline") or profile.get("title") or "").strip()
    summary = (profile.get("summary") or profile.get("bio") or "").strip()
    skills = ", ".join(s for s in (profile.get("skills") or [])[:12] if s)

    hero = f"{name}"
    if headline:
        hero += f" - {headline}"

    about_lines = [
        "> DRAFT: about-page draft. Edit freely before publishing.",
        "",
        f"Hi, I'm {name}.",
    ]
    if headline:
        about_lines.append(f"I'm a {headline}.")
    if summary:
        about_lines.append(summary)
    if skills:
        about_lines.append(f"What I work with: {skills}.")

    cards = []
    for p in projects:
        title = (p.get("title") or p.get("name") or "Untitled project").strip()
        teaser = (p.get("summary") or p.get("tagline") or p.get("description") or "").strip()
        if teaser:
            teaser = teaser.split(".")[0].strip() + "."
        role = (p.get("role") or "").strip()
        cards.append({
            "title": title,
            "teaser": teaser or "[DRAFT: add a one-line summary]",
            "role": role or "[DRAFT: add your role]",
            "outcomes": _outcome_bullets(p),
        })

    content = {"hero": hero, "about": "\n".join(about_lines), "cards": cards}

    md = [
        "# Portfolio site content",
        "",
        "> DRAFT: generated by candid design studio. Everything below is a",
        "> starting point for you to edit; nothing is publication-ready.",
        "",
        "## Homepage hero",
        "",
        f"> DRAFT: {hero}",
        "",
        "## About page",
        "",
        "\n".join(about_lines),
        "",
        "## Project teaser cards",
        "",
    ]
    for c in cards:
        md += [
            f"### {c['title']}  (DRAFT)",
            "",
            f"- Teaser: {c['teaser']}",
            f"- Role: {c['role']}",
        ]
        if c["outcomes"]:
            md += ["- Outcomes:"] + [f"  - {b}" for b in c["outcomes"]]
        else:
            md += ["- Outcomes: [DRAFT: add 3 outcome bullets from real data]"]
        md.append("")
    out = _design_packs_dir() / "site_draft.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    content["path"] = str(out)
    return content


# --- "walk me through your portfolio" script builder -------------------------

OPENER_TIP = (
    "Tip: open with who you are and what kind of work you do, then name "
    "the two or three projects you will cover so the interviewer knows "
    "where this is going."
)
CLOSER_TIP = (
    "Tip: close by restating the thread, say what you are looking for "
    "next, and invite questions on any project, including trade-offs you "
    "would make differently today."
)


def walkthrough_script(projects: list[dict], total_minutes: float = 5) -> dict:
    """Build a timed walkthrough narrative across 2-3 projects.

    Returns a dict with ``beats`` (each with minutes, label, script),
    ``total_minutes``, ``closing`` line, and opener/closer tips. Beat
    minutes are rounded to 2 decimals and the last beat absorbs the
    remainder so the beats always sum exactly to ``total_minutes``.
    """
    chosen = list(projects[:3])
    if not chosen:
        raise ValueError("Need at least one project to build a walkthrough.")

    threads = [ (p.get("theme") or "").strip() for p in chosen ]
    thread_line = "The thread connecting these is growth through iteration: each project sharpened how I scope ambiguity, test with users, and ship."
    if any(threads):
        thread_line = f"The thread connecting these is: {', '.join(t for t in threads if t)}."

    beats = []
    beats.append({
        "label": "Opener",
        "minutes": 0.5,
        "tip": OPENER_TIP,
        "script": (
            "I'm a designer focused on turning ambiguous problems into shipped "
            "products. I'll walk you through "
            f"{'three' if len(chosen) == 3 else 'two'} projects that show how I work: "
            + ", ".join(_title(p) for p in chosen) + "."
        ),
    })
    for i, p in enumerate(chosen):
        summary = (p.get("summary") or p.get("tagline") or p.get("description") or "").strip()
        role = (p.get("role") or "").strip()
        script = f"In {_title(p)}, "
        script += f"I was the {role}" if role else "my role spanned research through delivery"
        script += ". "
        script += summary if summary else "The project tackled a real user problem and shipped to production."
        beats.append({
            "label": f"Project {i + 1}: {_title(p)}",
            "minutes": 0.0,  # filled in below
            "script": script,
        })
        if i < len(chosen) - 1:
            nxt = _title(chosen[i + 1])
            beats.append({
                "label": f"Transition {i + 1}",
                "minutes": 0.25,
                "script": f"{thread_line} That leads into {nxt}, where...",
            })

    n_projects = len(chosen)
    n_transitions = max(n_projects - 1, 0)
    fixed = 0.5 + 0.5 + 0.25 * n_transitions  # opener + closer + transitions
    per_project = max((total_minutes - fixed) / n_projects, 0.5)
    for b in beats:
        if b["label"].startswith("Project"):
            b["minutes"] = round(per_project, 2)

    beats.append({
        "label": "Closer",
        "minutes": 0.0,  # absorbs remainder so the sum is exact
        "tip": CLOSER_TIP,
        "script": (
            f"{thread_line} That's my portfolio in {total_minutes:g} minutes. "
            "I'm happy to go deeper on any project, especially the "
            "trade-offs I'd make differently today."
        ),
    })
    # Normalize: last beat absorbs rounding remainder so the sum is exact.
    running = round(sum(b["minutes"] for b in beats[:-1]), 2)
    beats[-1]["minutes"] = round(total_minutes - running, 2)
    for b in beats:
        b["minutes"] = round(b["minutes"], 2)

    return {
        "total_minutes": total_minutes,
        "beats": beats,
        "thread": thread_line,
        "closing": beats[-1]["script"],
        "tips": {"opener": OPENER_TIP, "closer": CLOSER_TIP},
    }


def _title(p: dict) -> str:
    return (p.get("title") or p.get("name") or "this project").strip()


# --- case-study export -------------------------------------------------------

_EXPORT_CSS = """
body { font-family: -apple-system, 'Segoe UI', Georgia, serif; max-width: 720px;
       margin: 2rem auto; padding: 0 1.25rem; color: #1a1a1a; line-height: 1.65; }
h1 { font-size: 2rem; border-bottom: 2px solid #222; padding-bottom: 0.5rem; }
h2 { font-size: 1.25rem; color: #333; margin-top: 2rem; }
.tagline { font-style: italic; color: #555; }
.placeholder { color: #888; font-style: italic; }
footer { margin-top: 3rem; font-size: 0.8rem; color: #999; }
""".strip()


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def render_case_study_html(cs: dict) -> str:
    """Pure: render a structured case study as single-file HTML with inline CSS."""
    parts = ["<!DOCTYPE html>", "<html lang=\"en\">", "<head>",
             "<meta charset=\"utf-8\">",
             f"<title>{_escape(cs.get('title', 'Case study'))}</title>",
             f"<style>{_EXPORT_CSS}</style>",
             "</head>", "<body>"]
    parts.append(f"<h1>{_escape(cs.get('title', 'Case study'))}</h1>")
    project = cs.get("project") or {}
    tagline = (project.get("tagline") or project.get("summary") or "").strip()
    if tagline:
        parts.append(f"<p class=\"tagline\">{_escape(tagline)}</p>")
    for key, title, _prompt in SECTIONS:
        body = (cs.get("sections", {}) or {}).get(key, "").strip()
        parts.append(f"<h2>{_escape(title)}</h2>")
        if body:
            paragraphs = [f"<p>{_escape(p.strip())}</p>"
                          for p in body.split("\n\n") if p.strip()]
            parts.extend(paragraphs or [f"<p>{_escape(body)}</p>"])
        else:
            parts.append("<p class=\"placeholder\">Not provided yet; "
                         "fill this in before publishing.</p>")
    missing = cs.get("missing") or []
    if missing:
        parts.append(f"<footer>Sections still to complete: "
                     f"{_escape(', '.join(missing))}</footer>")
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


def export_case_study(cs: dict, fmt: str = "md") -> str:
    """Export a structured case study to ``DATA_DIR/design_packs/``.

    ``fmt`` is "md", "html", or "both". Returns the path written (for
    "both", the Markdown path; the HTML path sits alongside it).
    """
    if fmt not in ("md", "html", "both"):
        raise ValueError(f'fmt must be "md", "html", or "both", got {fmt!r}')
    out_dir = _design_packs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _slug(cs.get("title") or "case-study")
    paths = {}
    if fmt in ("md", "both"):
        md_path = out_dir / f"case-study-{stem}.md"
        md_path.write_text(render_case_study_md(cs), encoding="utf-8")
        paths["md"] = md_path
    if fmt in ("html", "both"):
        html_path = out_dir / f"case-study-{stem}.html"
        html_path.write_text(render_case_study_html(cs), encoding="utf-8")
        paths["html"] = html_path
    return str(paths["md"] if "md" in paths else paths["html"])
