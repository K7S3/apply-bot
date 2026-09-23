"""Polish export and drill: cheatsheets, printer-friendly sheets, flashcards.

This module turns *approved* entries from ``DATA_DIR/polish_library.json``
into study artifacts. It is deliberately standalone: it reads the JSON file
directly and does not import any other feature module, so nothing here can
change the library contents - export is read-only and only polished answers
with ``status == "approved"`` are exported (the approval-gate rule).

Export never invents content: every sentence in the cheatsheet, sheet, and
flashcards comes verbatim from the entry's ``polished`` text. The
competency tags are a small local keyword map computed inline, and the
STAR recap is a deterministic reshaping of the entry's own sentences.

No network, no models, no randomness except seeded shuffles for drills.
"""

from __future__ import annotations

import json
import random
import re
import textwrap
from pathlib import Path

from candid.config import DATA_DIR


class ExportError(Exception):
    """Raised for expected polish-export failures (missing library, bad id)."""


# --- library loading ---------------------------------------------------------

LIBRARY_FILENAME = "polish_library.json"
DEFAULT_CHEATSHEET = "polish_cheatsheet.md"
APPROVED_STATUS = "approved"


def _library_path() -> Path:
    return DATA_DIR / LIBRARY_FILENAME


def load_library() -> list[dict]:
    """Load the polish library from DATA_DIR/polish_library.json.

    Accepts either ``{"entries": [...]}`` or a bare JSON list.
    Returns [] when the file does not exist (nothing to export yet).
    """
    path = _library_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ExportError(f"Could not read polish library at {path}: {e}")
    if isinstance(raw, dict):
        entries = raw.get("entries", [])
    else:
        entries = raw
    if not isinstance(entries, list):
        raise ExportError(f"Polish library at {path} has no entry list.")
    return [e for e in entries if isinstance(e, dict)]


def approved_entries(entries: list[dict] | None = None) -> list[dict]:
    """Entries whose status is 'approved' (the approval gate)."""
    if entries is None:
        entries = load_library()
    return [e for e in entries if str(e.get("status", "")).lower() == APPROVED_STATUS]


def get_entry(entry_id: str, entries: list[dict] | None = None) -> dict:
    """Fetch one library entry by id, or raise ExportError."""
    if entries is None:
        entries = load_library()
    for e in entries:
        if str(e.get("id")) == str(entry_id):
            return e
    raise ExportError(f"No polish entry with id '{entry_id}' in {_library_path()}.")


# --- competency tags (local keyword map, independent of other modules) --------

#: keyword -> tag. Keywords are matched case-insensitively as substrings
#: against question + polished text.
COMPETENCY_KEYWORDS: dict[str, str] = {
    "led": "leadership",
    "lead ": "leadership",
    "managed": "leadership",
    "mentor": "mentorship",
    "coach": "mentorship",
    "onboard": "mentorship",
    "conflict": "conflict-resolution",
    "disagre": "conflict-resolution",
    "difficult stakeholder": "stakeholder-management",
    "stakeholder": "stakeholder-management",
    "fail": "ownership",
    "mistake": "ownership",
    "own up": "ownership",
    "deadline": "execution",
    "shipped": "execution",
    "launched": "execution",
    "deliver": "execution",
    "under pressure": "execution",
    "design": "technical-design",
    "architect": "technical-design",
    "data": "data-driven",
    "metric": "data-driven",
    "a/b": "data-driven",
    "customer": "customer-focus",
    "user ": "customer-focus",
    "cross-functional": "collaboration",
    "cross functional": "collaboration",
    "team": "collaboration",
    "debug": "debugging",
    "incident": "reliability",
    "outage": "reliability",
    "on-call": "reliability",
    "oncall": "reliability",
    "persuad": "influence",
    "convinced": "influence",
    "negotiat": "influence",
    "automat": "process-improvement",
    "refactor": "code-quality",
    "review": "code-quality",
    "grow": "growth",
    "learned": "growth",
    "scale": "scale",
    "performance": "performance",
    "latency": "performance",
}


def competency_tags(entry: dict) -> list[str]:
    """Compute competency tags for an entry from question + polished text."""
    haystack = f"{entry.get('question', '')} {entry.get('polished', '')}".lower()
    tags: list[str] = []
    for keyword, tag in COMPETENCY_KEYWORDS.items():
        if keyword in haystack and tag not in tags:
            tags.append(tag)
    return tags


# --- STAR recap ----------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


def star_recap(polished: str) -> dict[str, str]:
    """Deterministic STAR recap reshaping the entry's own sentences.

    Situation = first sentence, Task = second, Action = everything between,
    Result = last sentence. Single-sentence answers fill Situation and Result
    from the same sentence rather than inventing filler.
    """
    sents = _sentences(polished or "")
    if not sents:
        return {"situation": "", "task": "", "action": "", "result": ""}
    if len(sents) == 1:
        return {"situation": sents[0], "task": "", "action": "",
                "result": sents[0]}
    recap = {
        "situation": sents[0],
        "task": sents[1] if len(sents) > 2 else "",
        "action": " ".join(sents[2:-1]) if len(sents) > 3 else "",
        "result": sents[-1],
    }
    return recap


def _title_of(entry: dict) -> str:
    return entry.get("name") or entry.get("question") or f"entry {entry.get('id', '?')}"


# --- export_markdown -------------------------------------------------------------

def _entry_markdown(entry: dict) -> str:
    q = entry.get("question", "").strip() or "(no question recorded)"
    polished = entry.get("polished", "").strip()
    tags = competency_tags(entry)
    recap = star_recap(polished)
    lines = [
        f"## {q}",
        "",
        f"**Entry:** {_title_of(entry)}",
    ]
    if entry.get("story_id"):
        lines.append(f"**Story:** {entry['story_id']}")
    lines += [
        "",
        polished,
        "",
        f"**Competencies:** {', '.join(tags) if tags else 'general'}",
        "",
        "### STAR recap",
        "",
    ]
    for label, key in (("Situation", "situation"), ("Task", "task"),
                       ("Action", "action"), ("Result", "result")):
        val = recap[key]
        lines.append(f"- **{label}:** {val if val else 'see answer above'}")
    lines.append("")
    return "\n".join(lines)


def export_markdown(entry_id: str | None = None,
                    path: str | Path | None = None) -> str:
    """Write one entry (by id) or all approved entries as a Markdown cheatsheet.

    Default output: ``DATA_DIR/polish_cheatsheet.md``. Returns the path written.
    """
    entries = approved_entries()
    if entry_id is not None:
        entry = get_entry(entry_id)  # searches the whole library
        if str(entry.get("status", "")).lower() != APPROVED_STATUS:
            raise ExportError(
                f"Entry '{entry_id}' is not approved (status="
                f"'{entry.get('status', '')}'); only approved entries can be exported."
            )
        entries = [entry]
    if not entries:
        raise ExportError(
            "No approved polish entries to export. Approve an entry first."
        )
    out = Path(path).expanduser() if path else DATA_DIR / DEFAULT_CHEATSHEET
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if out.parent != DATA_DIR:
        out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Interview answer cheatsheet\n\n"
        "_Polished answers, approved only. Review the night before and the "
        "morning of the interview._\n\n"
    )
    body = "\n".join(_entry_markdown(e) for e in entries)
    out.write_text(header + body, encoding="utf-8")
    return str(out)


# --- print_sheet -----------------------------------------------------------------

_WIDTH = 80


def _wrap_lines(text: str, width: int = _WIDTH) -> list[str]:
    wrapped: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            wrapped.append("")
        else:
            wrapped.extend(
                textwrap.wrap(para, width=width,
                              break_long_words=False, break_on_hyphens=False)
                or [""])
    return wrapped


def _entry_sheet(entry: dict) -> list[str]:
    q = entry.get("question", "").strip() or "(no question recorded)"
    polished = entry.get("polished", "").strip()
    tags = competency_tags(entry)
    recap = star_recap(polished)
    lines = [
        "=" * _WIDTH,
    ]
    lines.extend(_wrap_lines(f"QUESTION: {q}"))
    lines.append("-" * _WIDTH)
    lines.extend(_wrap_lines(f"Entry: {_title_of(entry)}"))
    if entry.get("story_id"):
        lines.append(f"Story: {entry['story_id']}")
    lines.append("")
    lines.extend(_wrap_lines(polished))
    lines.append("")
    lines.extend(_wrap_lines(f"Competencies: {', '.join(tags) if tags else 'general'}"))
    lines.append("")
    lines.append("STAR recap:")
    for label, key in (("S", "situation"), ("T", "task"),
                       ("A", "action"), ("R", "result")):
        val = recap[key] or "see answer above"
        lines.extend(_wrap_lines(f"[{label}] {val}"))
    lines.append("")
    return lines


def print_sheet(entry_id: str | None = None) -> str:
    """Plain-text, printer-friendly (80-col, no markdown) sheet. Returned as str."""
    entries = approved_entries()
    if entry_id is not None:
        entry = get_entry(entry_id)
        if str(entry.get("status", "")).lower() != APPROVED_STATUS:
            raise ExportError(
                f"Entry '{entry_id}' is not approved; only approved entries "
                "can be printed."
            )
        entries = [entry]
    if not entries:
        raise ExportError(
            "No approved polish entries to print. Approve an entry first."
        )
    lines = ["INTERVIEW ANSWER CHEAT SHEET", ""]
    for entry in entries:
        lines.extend(_entry_sheet(entry))
    return "\n".join(lines).rstrip("\n") + "\n"


# --- flashcards ------------------------------------------------------------------

def flashcards() -> list[dict[str, str]]:
    """Flashcards from approved entries: {front: question or name, back: polished}."""
    return [
        {
            "front": e.get("question", "").strip() or _title_of(e),
            "back": e.get("polished", "").strip(),
        }
        for e in approved_entries()
    ]


def format_cards(cards: list[dict[str, str]]) -> str:
    """Numbered, self-quizzing-friendly text for a list of flashcard dicts."""
    if not cards:
        return "No flashcards yet. Approve a polished answer first."
    lines = []
    for i, card in enumerate(cards, 1):
        lines.append(f"Card {i}/{len(cards)}")
        lines.append(f"Q: {card.get('front', '')}")
        lines.append("")
        lines.append("(say your answer out loud, then check)")
        lines.append("")
        lines.append(f"A: {card.get('back', '')}")
        if i < len(cards):
            lines.append("")
            lines.append("-" * 40)
            lines.append("")
    return "\n".join(lines) + "\n"


# --- drill order -----------------------------------------------------------------

def drill_order(cards: list[dict], seed: int = 0) -> list[dict]:
    """Deterministic shuffle of cards for a practice session.

    Same (cards, seed) always yields the same order. The input list is not
    mutated; a new list is returned.
    """
    order = list(cards)
    random.Random(seed).shuffle(order)
    return order
