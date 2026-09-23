"""Research talk prep and research-notes export.

Feature 1 - talk outlines: turn user-supplied paper/project content into a
timed talk outline (5 / 15 / 30 / 60 minutes) with per-section time budgets,
slide-count suggestions, and speaker-note prompts. The prompts are questions
the speaker should be able to answer - not scripted notes.

Feature 2 - notes export: export the user's paper library, notes, and drill
summaries to Markdown (Obsidian-friendly, with [[wikilink]] cross
references), plus an index file and a consolidated digest.

Everything is local and offline. Outlines and exports use ONLY content the
user supplies - nothing here invents papers, results, or citations.

Usage (proposed CLI):
    candid research talk --minutes 15        # build a timed outline
    candid research export-notes              # export library to Markdown
    candid research export-digest             # write the consolidated digest
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from candid import config as C

log = logging.getLogger("candid.research_talk")

# --- local paths (config.py is read-only for us; define our own constants) ---
RESEARCH_DIR = C.DATA_DIR / "research"
DEFAULT_EXPORTS_DIR = RESEARCH_DIR / "exports"

# Candidate JSON stores for the paper library. The sibling module
# candid/research_papers.py may define its own location; we try these in
# order and export whatever is available - a missing store is never an error.
def _paper_store_candidates(base: Path | None = None) -> list[Path]:
    root = base or RESEARCH_DIR
    return [
        root / "papers.json",
        root / "paper_library.json",
        C.DATA_DIR / "research_papers.json",
    ]


# --------------------------------------------------------------------------
# Feature 1: talk-prep outline builder
# --------------------------------------------------------------------------

SUPPORTED_MINUTES = (5, 15, 30, 60)

REQUIRED_CONTENT_FIELDS = (
    "title",
    "problem",
    "approach",
    "results",
    "takeaways",
    "future_work",
)

# Optional content fields shown in the outline header when provided.
OPTIONAL_CONTENT_FIELDS = ("authors", "venue", "audience")

# (section key, display name, fraction of talk time, prompt questions)
_SECTIONS: list[tuple[str, str, float, list[str]]] = [
    (
        "hook",
        "Hook",
        0.05,
        [
            "What is the one-sentence surprise that makes the audience care?",
            "Why should someone outside your subfield keep listening?",
        ],
    ),
    (
        "problem",
        "Problem",
        0.10,
        [
            "What problem are you solving, in one sentence?",
            "Why is the current state of the art insufficient - what breaks?",
            "Who feels the pain of this problem, and how badly?",
        ],
    ),
    (
        "approach",
        "Approach",
        0.25,
        [
            "What is the key insight or idea behind your approach?",
            "Why is this approach promising where others failed?",
            "What did you deliberately choose NOT to do, and why?",
        ],
    ),
    (
        "results",
        "Results",
        0.35,
        [
            "What is your headline result (one number, one sentence)?",
            "How do you know the result is real - what could a skeptic poke at?",
            "What is the main limitation or threat to validity?",
        ],
    ),
    (
        "takeaways",
        "Takeaways",
        0.15,
        [
            "What should the audience still remember tomorrow?",
            "What can a practitioner do differently because of this work?",
        ],
    ),
    (
        "future",
        "Future work",
        0.10,
        [
            "What is the next concrete step?",
            "What open question would you hand to the audience?",
        ],
    ),
    (
        "backup",
        "Backup slides",
        0.0,
        [
            "Which extra plot would answer the hardest expected question?",
            "What ablations or negative results are worth keeping ready?",
            "What detail would you show only if someone asks for it?",
        ],
    ),
]


def _nearest_supported(minutes: int) -> tuple[int, str | None]:
    """Snap an arbitrary length to the nearest supported one.

    Returns (supported_minutes, note or None). Ties break toward the
    shorter talk.
    """
    nearest = min(SUPPORTED_MINUTES, key=lambda m: (abs(m - minutes), m))
    if nearest == minutes:
        return nearest, None
    return nearest, (
        f"Note: {minutes} minutes is not a supported talk length; "
        f"using the nearest supported length ({nearest} minutes)."
    )


def build_outline(content: dict, minutes: int) -> dict:
    """Build a timed talk outline from user-supplied content.

    content must include title, problem, approach, results, takeaways, and
    future_work (all non-empty strings). Optional: authors, venue, audience.

    minutes should be one of 5, 15, 30, 60; any other positive value snaps
    to the nearest supported length and the outline carries a note saying so.

    Returns an outline dict with sections, each carrying a time budget, a
    slide-count suggestion, and speaker-note prompts.
    """
    if not isinstance(content, dict):
        raise ValueError("content must be a dict of talk content fields.")
    missing = [f for f in REQUIRED_CONTENT_FIELDS
               if not str(content.get(f, "")).strip()]
    if missing:
        raise ValueError(
            "Missing required content fields: " + ", ".join(missing)
            + ". Supply them all - outlines never invent content."
        )
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise ValueError(f"minutes must be a number; got {minutes!r}.")
    if minutes <= 0:
        raise ValueError(f"minutes must be positive; got {minutes}.")

    actual, note = _nearest_supported(minutes)

    sections = []
    for key, name, fraction, prompts in _SECTIONS:
        sec_minutes = round(fraction * actual * 2) / 2  # nearest half minute
        if key == "backup":
            slides = min(6, max(2, round(actual / 10)))
        else:
            # Roughly one slide per 1.5 minutes of speaking time.
            slides = max(1, round(sec_minutes / 1.5)) if sec_minutes else 1
        sections.append({
            "key": key,
            "name": name,
            "minutes": sec_minutes,
            "slides": slides,
            "prompts": list(prompts),
        })

    outline = {
        "title": str(content["title"]).strip(),
        "minutes": actual,
        "requested_minutes": minutes,
        "sections": sections,
        "content": {k: str(content[k]).strip()
                    for k in REQUIRED_CONTENT_FIELDS},
    }
    for k in OPTIONAL_CONTENT_FIELDS:
        if str(content.get(k, "")).strip():
            outline[k] = str(content[k]).strip()
    if note:
        outline["note"] = note
    return outline


# section key -> content field echoed under "Your content" in Markdown.
_SECTION_CONTENT_FIELD = {
    "hook": "title",
    "problem": "problem",
    "approach": "approach",
    "results": "results",
    "takeaways": "takeaways",
    "future": "future_work",
}


def render_outline(outline: dict) -> str:
    """Render an outline as plain text."""
    lines = [f"Talk outline: {outline['title']} ({outline['minutes']}-minute talk)"]
    if outline.get("note"):
        lines.append(outline["note"])
    lines.append("")
    for i, sec in enumerate(outline["sections"], 1):
        time_str = f"{sec['minutes']:g} min" if sec["minutes"] else "not timed"
        lines.append(f"{i}. {sec['name']} - {time_str} ({sec['slides']} slides)")
        for p in sec["prompts"]:
            lines.append(f"   - Can you answer: {p}")
    return "\n".join(lines)


def render_outline_md(outline: dict) -> str:
    """Render an outline as Markdown."""
    lines = [f"# {outline['title']}", ""]
    lines.append(f"**Talk length:** {outline['minutes']} minutes")
    for k in OPTIONAL_CONTENT_FIELDS:
        if outline.get(k):
            lines.append(f"**{k.capitalize()}:** {outline[k]}")
    if outline.get("note"):
        lines += ["", f"> {outline['note']}"]
    lines += ["", "## Time budget", "",
              "| # | Section | Time (min) | Slides |",
              "|---|---------|------------|--------|"]
    for i, sec in enumerate(outline["sections"], 1):
        time_cell = f"{sec['minutes']:g}" if sec["minutes"] else "-"
        lines.append(f"| {i} | {sec['name']} | {time_cell} | {sec['slides']} |")
    lines += ["", "## Speaker notes"]
    content = outline.get("content", {})
    for i, sec in enumerate(outline["sections"], 1):
        time_str = f"{sec['minutes']:g} min" if sec["minutes"] else "backup"
        lines += ["", f"### {i}. {sec['name']} ({time_str}, ~{sec['slides']} slides)"]
        field = _SECTION_CONTENT_FIELD.get(sec["key"])
        if field and content.get(field):
            lines += ["", "> Your content:", ""]
            for para in str(content[field]).splitlines():
                lines.append(f"> {para}" if para.strip() else ">")
            lines.append("")
        lines.append("**Be ready to answer:**")
        for p in sec["prompts"]:
            lines.append(f"- {p}")
    return "\n".join(lines)


def save_outline(outline: dict, path: str | Path) -> Path:
    """Save an outline to disk. ``.md`` paths get Markdown, others get text.

    Creates parent directories as needed. Returns the written Path.
    """
    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = render_outline_md(outline) if dest.suffix.lower() == ".md" \
        else render_outline(outline)
    dest.write_text(text.rstrip() + "\n", encoding="utf-8")
    return dest


# --------------------------------------------------------------------------
# Feature 2: research notes exporter
# --------------------------------------------------------------------------

def _normalize_paper(raw: dict, index: int) -> dict:
    """Coerce a raw paper record into a predictable shape (defensive)."""
    if not isinstance(raw, dict):
        raw = {"notes": str(raw)}
    pid = str(raw.get("id") or raw.get("paper_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not pid:
        pid = _slug(title) or f"paper-{index + 1}"
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    def _as_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            return "\n".join(str(v).strip() for v in value if str(v).strip())
        return str(value).strip()

    return {
        "id": pid,
        "title": title or pid,
        "authors": _as_text(raw.get("authors")),
        "year": str(raw.get("year") or "").strip(),
        "venue": str(raw.get("venue") or "").strip(),
        "tags": [str(t) for t in tags],
        "summary": _as_text(raw.get("summary") or raw.get("abstract")),
        "notes": _as_text(raw.get("notes")),
        "drill_summaries": _as_text(raw.get("drill_summaries") or raw.get("drills")),
        "takeaways": _as_text(raw.get("takeaways")),
        "related": [str(r).strip() for r in (raw.get("related") or [])
                    if str(r).strip()],
    }


def load_paper_library(base: Path | None = None) -> list[dict]:
    """Load the user's paper library defensively.

    Tries known JSON store locations; a missing or unreadable store yields
    an empty list (never raises). All records are normalized but all text
    is the user's own - nothing is generated.
    """
    for store in _paper_store_candidates(base):
        if not store.is_file():
            continue
        try:
            raw = json.loads(store.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Ignoring unreadable paper store %s: %s", store, exc)
            continue
        if isinstance(raw, dict):
            for key in ("papers", "library", "items"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                # Dict-of-records store (e.g. research_papers.py: {id: record}).
                if raw and all(isinstance(v, dict) for v in raw.values()):
                    raw = list(raw.values())
        if not isinstance(raw, list):
            log.warning("Ignoring paper store %s: expected a JSON list.", store)
            continue
        papers = [_normalize_paper(p, i) for i, p in enumerate(raw)]
        # De-duplicate ids while preserving order.
        seen: set[str] = set()
        unique = []
        for p in papers:
            pid, n = p["id"], 2
            while pid in seen:
                pid = f"{p['id']}-{n}"
                n += 1
            p["id"] = pid
            seen.add(pid)
            unique.append(p)
        return unique
    return []


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]


def _paper_filename(paper: dict) -> str:
    return f"{_slug(paper['id']) or 'paper'}.md"


def _frontmatter(paper: dict) -> str:
    lines = ["---", f'title: "{paper["title"]}"', f'id: "{paper["id"]}"']
    if paper["authors"]:
        lines.append(f'authors: "{paper["authors"]}"')
    if paper["year"]:
        lines.append(f"year: {paper['year']}")
    if paper["venue"]:
        lines.append(f'venue: "{paper["venue"]}"')
    if paper["tags"]:
        tags = ", ".join(f'"{t}"' for t in paper["tags"])
        lines.append(f"tags: [{tags}]")
    lines.append("---")
    return "\n".join(lines)


def render_paper_md(paper: dict) -> str:
    """Render one paper's notes as Obsidian-friendly Markdown."""
    lines = [_frontmatter(paper), "", f"# {paper['title']}", ""]
    meta = []
    if paper["authors"]:
        meta.append(f"**Authors:** {paper['authors']}")
    if paper["venue"] or paper["year"]:
        meta.append(f"**Venue:** {paper['venue']} {paper['year']}".rstrip())
    if paper["tags"]:
        meta.append("**Tags:** " + ", ".join(f"#{t}" for t in paper["tags"]))
    if meta:
        lines += meta + [""]
    if paper["summary"]:
        lines += ["## Summary", "", paper["summary"], ""]
    if paper["takeaways"]:
        lines += ["## Key takeaways", "", paper["takeaways"], ""]
    if paper["notes"]:
        lines += ["## Notes", "", paper["notes"], ""]
    if paper["drill_summaries"]:
        lines += ["## Drill summaries", "", paper["drill_summaries"], ""]
    if paper["related"]:
        links = " ".join(f"[[{r}]]" for r in paper["related"])
        lines += ["## Related papers", "", links, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_index_md(papers: list[dict]) -> str:
    """Render the library index with [[wikilink]] cross references."""
    lines = ["# Research library index", "",
             f"**{len(papers)} paper(s)** in the library.", ""]
    if not papers:
        lines += [
            "The paper library is empty (or its store could not be read).",
            "Export ran anyway so you still get this index file - add papers",
            "and re-run to populate it.",
        ]
        return "\n".join(lines) + "\n"
    for p in papers:
        label = p["title"]
        if p["year"]:
            label += f" ({p['year']})"
        lines.append(f"- [[{p['id']}|{label}]]")
    return "\n".join(lines) + "\n"


def export_notes(out_dir: str | Path | None = None,
                 base: Path | None = None) -> list[str]:
    """Export the paper library to one Markdown file per paper plus an index.

    Writes to out_dir (default: <data>/research/exports). Reads the paper
    store via load_paper_library(); a missing store exports just the index,
    never crashes. Returns the list of written file paths (as strings).
    """
    dest = Path(out_dir).expanduser() if out_dir else DEFAULT_EXPORTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    papers = load_paper_library(base)
    written: list[str] = []
    for paper in papers:
        path = dest / _paper_filename(paper)
        path.write_text(render_paper_md(paper), encoding="utf-8")
        written.append(str(path))
    index_path = dest / "index.md"
    index_path.write_text(render_index_md(papers), encoding="utf-8")
    written.append(str(index_path))
    return written


def render_digest_md(papers: list[dict]) -> str:
    """Render a consolidated digest of the whole library."""
    lines = ["# Research digest", "",
             f"Consolidated notes for {len(papers)} paper(s).", ""]
    if not papers:
        lines.append("No papers in the library yet - nothing to digest.")
        return "\n".join(lines) + "\n"
    for p in papers:
        lines += ["---", "", f"## [[{p['id']}|{p['title']}]]"]
        if p["authors"] or p["year"]:
            lines.append(f"*{p['authors']}{', ' if p['authors'] and p['year'] else ''}{p['year']}*")
        if p["takeaways"]:
            lines += ["", "**Key takeaways**", "", p["takeaways"]]
        elif p["summary"]:
            lines += ["", "**Summary**", "", p["summary"]]
        if p["drill_summaries"]:
            lines += ["", "**Drill summaries**", "", p["drill_summaries"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_digest(out_path: str | Path | None = None,
                  base: Path | None = None) -> str:
    """Write the consolidated digest Markdown file. Returns its path."""
    dest = Path(out_path).expanduser() if out_path \
        else DEFAULT_EXPORTS_DIR / "digest.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    papers = load_paper_library(base)
    dest.write_text(render_digest_md(papers), encoding="utf-8")
    return str(dest)
