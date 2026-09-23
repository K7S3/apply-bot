"""Research paper library + deep-dive drills.

Feature 1 (paper library): a local JSON library of papers the user adds by
hand. Each record holds only user-supplied metadata - title, authors, venue,
year, url, abstract, free-text notes, and a status in
(unread, reading, read, summarized).

Feature 2 (paper drills): template-based deep questions generated from a
paper's own metadata and notes (never from a paper the user does not have).
Drill mode asks one question at a time, the user self-scores confidence 1-5
per answer, and drill history is stored per paper for stats.

Anti-fabrication rule: nothing in this module invents papers, venues,
baselines, citations, or results. Anything the user has not entered is
explicitly labeled "[fill in]".

Stored as JSON under the candid data dir (git-ignored):
    research_papers.json  - the paper library
    research_drills.json  - drill sessions per paper
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C

# Defined here (not in config.py) per module ownership.
PAPERS_PATH = C.DATA_DIR / "research_papers.json"
DRILLS_PATH = C.DATA_DIR / "research_drills.json"

PAPER_STATUSES = ["unread", "reading", "read", "summarized"]

MIN_CONFIDENCE = 1
MAX_CONFIDENCE = 5


class ResearchError(Exception):
    """Raised for invalid paper-library or drill operations."""


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------

def _load_papers(path: str | Path | None = None) -> dict[str, dict]:
    p = Path(path) if path else PAPERS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResearchError(f"Paper file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResearchError(f"Paper file {p} should contain a JSON object keyed by id.")
    return data


def _save_papers(papers: dict[str, dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else PAPERS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(papers, indent=2, sort_keys=True), encoding="utf-8")
    return p


def _load_drills(path: str | Path | None = None) -> dict[str, list[dict]]:
    p = Path(path) if path else DRILLS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResearchError(f"Drill file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResearchError(f"Drill file {p} should contain a JSON object keyed by paper id.")
    return data


def _save_drills(drills: dict[str, list[dict]], path: str | Path | None = None) -> Path:
    p = Path(path) if path else DRILLS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(drills, indent=2, sort_keys=True), encoding="utf-8")
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Feature 1: paper library
# ---------------------------------------------------------------------------

def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "paper"


def _unique_id(base: str, papers: dict[str, dict]) -> str:
    if base not in papers:
        return base
    n = 2
    while f"{base}-{n}" in papers:
        n += 1
    return f"{base}-{n}"


def _parse_authors(authors) -> list[str]:
    if isinstance(authors, str):
        parts = [a.strip() for a in re.split(r"[;,]|\band\b", authors) if a.strip()]
        return parts
    if isinstance(authors, (list, tuple)):
        out = [str(a).strip() for a in authors if str(a).strip()]
        return out
    raise ResearchError("Authors must be a list of names or a comma/semicolon-separated string.")


def _validate_year(year) -> int | None:
    if year is None or (isinstance(year, str) and not year.strip()):
        return None
    if isinstance(year, bool):
        raise ResearchError("Year must be an integer, e.g. 2024.")
    if isinstance(year, float):
        if not year.is_integer():
            raise ResearchError("Year must be an integer, e.g. 2024.")
        year = int(year)
    if isinstance(year, str):
        if not re.fullmatch(r"\d{1,4}", year.strip()):
            raise ResearchError("Year must be an integer, e.g. 2024.")
        year = int(year.strip())
    if not isinstance(year, int):
        raise ResearchError("Year must be an integer, e.g. 2024.")
    if year < 1900 or year > 2100:
        raise ResearchError(f"Year {year} looks wrong; expected between 1900 and 2100.")
    return year


def add_paper(title: str, authors: list[str] | str | None = None, *,
              venue: str = "", year: int | str | None = None,
              url: str = "", abstract: str = "", notes: str = "",
              status: str = "unread",
              path: str | Path | None = None) -> dict:
    """Add a paper to the library. Returns the new record.

    The id is a slug of the title, suffixed (-2, -3, ...) on collision.
    """
    title = (title or "").strip()
    if not title:
        raise ResearchError("A paper needs a non-empty title.")
    if status not in PAPER_STATUSES:
        raise ResearchError(
            f"Unknown status '{status}'. Choose from: {', '.join(PAPER_STATUSES)}")
    papers = _load_papers(path)
    rec = {
        "id": _unique_id(_slugify(title), papers),
        "title": title,
        "authors": _parse_authors(authors) if authors is not None else [],
        "venue": (venue or "").strip(),
        "year": _validate_year(year),
        "url": (url or "").strip(),
        "abstract": (abstract or "").strip(),
        "notes": (notes or "").strip(),
        "status": status,
        "date_added": _now_iso(),
        "date_updated": _now_iso(),
    }
    papers[rec["id"]] = rec
    _save_papers(papers, path)
    return rec


def get_paper(paper_id: str, path: str | Path | None = None) -> dict:
    """Return one paper record, or raise ResearchError."""
    papers = _load_papers(path)
    rec = papers.get(paper_id)
    if rec is None:
        raise ResearchError(
            f"No paper with id '{paper_id}'. Use list_papers() to see ids.")
    return rec


def list_papers(*, status: str | None = None,
                path: str | Path | None = None) -> list[dict]:
    """List papers, optionally filtered by status."""
    if status is not None and status not in PAPER_STATUSES:
        raise ResearchError(
            f"Unknown status '{status}'. Choose from: {', '.join(PAPER_STATUSES)}")
    papers = _load_papers(path).values()
    if status is not None:
        papers = [p for p in papers if p.get("status") == status]
    return sorted(papers, key=lambda p: (p.get("year") or 0, p["id"]), reverse=True)


def search_papers(query: str, path: str | Path | None = None) -> list[dict]:
    """Case-insensitive search over title, authors, venue, abstract, and notes."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for p in _load_papers(path).values():
        hay = " ".join([
            p.get("title", ""),
            " ".join(p.get("authors", [])),
            p.get("venue", ""),
            p.get("abstract", ""),
            p.get("notes", ""),
        ]).lower()
        if q in hay:
            out.append(p)
    return sorted(out, key=lambda p: p["id"])


def update_status(paper_id: str, status: str,
                  path: str | Path | None = None) -> dict:
    """Move a paper to a new status. Returns the updated record."""
    if status not in PAPER_STATUSES:
        raise ResearchError(
            f"Unknown status '{status}'. Choose from: {', '.join(PAPER_STATUSES)}")
    papers = _load_papers(path)
    rec = papers.get(paper_id)
    if rec is None:
        raise ResearchError(f"No paper with id '{paper_id}'.")
    rec["status"] = status
    rec["date_updated"] = _now_iso()
    _save_papers(papers, path)
    return rec


def append_notes(paper_id: str, text: str,
                 path: str | Path | None = None) -> dict:
    """Append free text to a paper's notes, timestamped. Returns the record."""
    text = (text or "").strip()
    if not text:
        raise ResearchError("Notes text must not be empty.")
    papers = _load_papers(path)
    rec = papers.get(paper_id)
    if rec is None:
        raise ResearchError(f"No paper with id '{paper_id}'.")
    entry = f"[{_now_iso()}] {text}"
    rec["notes"] = f"{rec['notes']}\n{entry}".strip() if rec["notes"] else entry
    rec["date_updated"] = _now_iso()
    _save_papers(papers, path)
    return rec


# ---------------------------------------------------------------------------
# Feature 2: deep-dive drills
# ---------------------------------------------------------------------------

#: (category, question template). Placeholders are filled from the paper's own
#: metadata only. Anything the template needs but the user never entered must
#: be answered by the user - templates never invent baselines, results, or
#: related work.
DRILL_TEMPLATES: list[tuple[str, str]] = [
    ("main_contribution",
     "In one or two sentences, what is the main contribution of "
     "'{title}'{cite}?"),
    ("key_method",
     "What is the key method or core idea in '{title}'? Walk through it "
     "step by step as if explaining it to a colleague."),
    ("baselines",
     "Which baselines should '{title}' beat, and why are those the right "
     "comparisons? Name them from the paper's experiments section "
     "(check your notes)."),
    ("missing_ablations",
     "What ablations are missing from '{title}'? Which single experiment "
     "would you run to test its core claim?"),
    ("limitations",
     "What are the limitations of '{title}'? When would it fail, or when "
     "would you not use it?"),
    ("extension",
     "How would you extend '{title}' in your own work? Describe one "
     "concrete next experiment or application."),
    ("one_sentence_pitch",
     "Give a one-sentence pitch for '{title}' that a colleague would "
     "remember."),
    ("hardest_reviewer_question",
     "What is the hardest question a reviewer would ask about "
     "'{title}'{cite}? Answer it the way you would in a rebuttal."),
]


def _citation(paper: dict) -> str:
    bits = []
    if paper.get("venue"):
        bits.append(paper["venue"])
    if paper.get("year"):
        bits.append(str(paper["year"]))
    return f" ({', '.join(bits)})" if bits else ""


def build_drill_questions(paper: dict) -> list[dict]:
    """Build one drill question per template, filled from the paper's metadata.

    Each question dict has: category, question, fill_in_hint.
    The hint tells the user where to look when the answer is not in their
    notes yet - labeled so nothing looks machine-authored.
    """
    cite = _citation(paper)
    title = paper.get("title", "")
    questions = []
    for category, template in DRILL_TEMPLATES:
        question = template.format(title=title, cite=cite)
        if paper.get("notes"):
            hint = "Answer from your notes on this paper."
        else:
            hint = "[fill in] No notes on this paper yet - answer from the paper itself."
        questions.append({
            "category": category,
            "question": question,
            "fill_in_hint": hint,
        })
    return questions


def _validate_confidences(confidences: list[int], n_questions: int) -> list[int]:
    if len(confidences) != n_questions:
        raise ResearchError(
            f"Expected {n_questions} confidence scores (one per question), "
            f"got {len(confidences)}.")
    out = []
    for c in confidences:
        if isinstance(c, bool) or not isinstance(c, int):
            raise ResearchError(f"Confidence scores must be integers 1-5, got {c!r}.")
        if not (MIN_CONFIDENCE <= c <= MAX_CONFIDENCE):
            raise ResearchError(
                f"Confidence scores must be {MIN_CONFIDENCE}-{MAX_CONFIDENCE}, got {c}.")
        out.append(c)
    return out


def record_drill(paper_id: str, confidences: list[int], *,
                 answers: list[str] | None = None,
                 path: str | Path | None = None,
                 drills_path: str | Path | None = None) -> dict:
    """Store one drill session: per-question confidence 1-5, timestamps, average.

    Raises ResearchError if the paper does not exist or scores are invalid.
    """
    paper = get_paper(paper_id, path)  # validates existence
    questions = build_drill_questions(paper)
    scores = _validate_confidences(list(confidences), len(questions))
    if answers is not None and len(answers) != len(questions):
        raise ResearchError(
            f"Expected {len(questions)} answers (one per question), "
            f"got {len(answers)}.")
    started = _now_iso()
    session = {
        "paper_id": paper_id,
        "started_at": started,
        "finished_at": _now_iso(),
        "avg_confidence": round(sum(scores) / len(scores), 2),
        "items": [
            {
                "category": q["category"],
                "question": q["question"],
                "confidence": s,
                "answer": (answers[i] if answers else "").strip() if answers else "",
            }
            for i, (q, s) in enumerate(zip(questions, scores))
        ],
    }
    drills = _load_drills(drills_path)
    drills.setdefault(paper_id, []).append(session)
    _save_drills(drills, drills_path)
    return session


def drill_history(paper_id: str, *,
                  path: str | Path | None = None,
                  drills_path: str | Path | None = None) -> list[dict]:
    """All recorded drill sessions for a paper, oldest first."""
    get_paper(paper_id, path)  # validates existence
    return _load_drills(drills_path).get(paper_id, [])


def drill_stats(paper_id: str, *,
                path: str | Path | None = None,
                drills_path: str | Path | None = None) -> dict:
    """Stats over a paper's drill history.

    Returns sessions count, overall avg confidence, per-category averages,
    and weakest_categories (lowest avg first, only categories with data).
    """
    sessions = drill_history(paper_id, path=path, drills_path=drills_path)
    cat_scores: dict[str, list[int]] = {}
    all_scores: list[int] = []
    for s in sessions:
        for item in s["items"]:
            cat_scores.setdefault(item["category"], []).append(item["confidence"])
            all_scores.append(item["confidence"])
    per_category = {
        cat: {"avg_confidence": round(sum(v) / len(v), 2), "samples": len(v)}
        for cat, v in cat_scores.items()
    }
    weakest = sorted(per_category, key=lambda c: (per_category[c]["avg_confidence"],
                                                 -per_category[c]["samples"]))
    return {
        "paper_id": paper_id,
        "sessions": len(sessions),
        "avg_confidence": round(sum(all_scores) / len(all_scores), 2) if all_scores else None,
        "per_category": per_category,
        "weakest_categories": weakest,
    }


def drill_interactive(paper_id: str, *,
                      path: str | Path | None = None,
                      drills_path: str | Path | None = None,
                      input_fn=input, print_fn=print) -> dict:
    """Interactive drill: one question at a time, self-score confidence 1-5.

    Type your answer (may be blank), then a confidence score 1-5. Returns the
    recorded session.
    """
    paper = get_paper(paper_id, path)
    questions = build_drill_questions(paper)
    print_fn(f"Drilling '{paper['title']}' ({len(questions)} questions).")
    print_fn("Answer each, then self-score your confidence 1-5 (1 = shaky, 5 = solid).")
    answers: list[str] = []
    confidences: list[int] = []
    for i, q in enumerate(questions, start=1):
        print_fn(f"\n[{i}/{len(questions)}] {q['category'].replace('_', ' ').upper()}")
        print_fn(q["question"])
        print_fn(q["fill_in_hint"])
        answer = input_fn("Your answer (enter to skip): ").strip()
        answers.append(answer)
        while True:
            raw = input_fn("Confidence 1-5: ").strip()
            try:
                score = int(raw)
            except ValueError:
                score = 0
            if MIN_CONFIDENCE <= score <= MAX_CONFIDENCE:
                confidences.append(score)
                break
            print_fn(f"Please enter a whole number {MIN_CONFIDENCE}-{MAX_CONFIDENCE}.")
    session = record_drill(paper_id, confidences, answers=answers,
                           path=path, drills_path=drills_path)
    print_fn(f"\nDrill recorded. Average confidence: {session['avg_confidence']}/5.")
    return session


# ---------------------------------------------------------------------------
# rendering (for CLI use)
# ---------------------------------------------------------------------------

def render_list(papers: list[dict]) -> str:
    if not papers:
        return ("No papers yet. Add one with: "
                "python -m candid research papers add --title \"...\" --authors \"A, B\"")
    lines = [f"{'ID':<38}{'Status':<12}{'Year':<6}Title"]
    for p in papers:
        year = str(p.get("year") or "-")
        title = p["title"]
        if p.get("venue"):
            title += f"  [{p['venue']}]"
        lines.append(f"{p['id']:<38}{p['status']:<12}{year:<6}{title[:60]}")
    return "\n".join(lines)


def render_paper(p: dict) -> str:
    lines = [
        f"{p['title']}",
        f"  id:      {p['id']}",
        f"  authors: {', '.join(p.get('authors', [])) or '-'}",
        f"  venue:   {p.get('venue') or '-'}",
        f"  year:    {p.get('year') or '-'}",
        f"  url:     {p.get('url') or '-'}",
        f"  status:  {p['status']}",
    ]
    if p.get("abstract"):
        lines += ["", "Abstract:", f"  {p['abstract']}"]
    if p.get("notes"):
        lines += ["", "Notes:", f"  {p['notes']}"]
    return "\n".join(lines)


def render_drill_stats(s: dict, paper_title: str = "") -> str:
    title = f" for '{paper_title}'" if paper_title else ""
    lines = [f"Drill stats{title}:", f"  sessions: {s['sessions']}"]
    avg = s["avg_confidence"]
    lines.append(f"  avg confidence: {avg if avg is not None else '- (no sessions yet)'}/5")
    if s["per_category"]:
        lines.append("")
        lines.append("  per category:")
        for cat in sorted(s["per_category"]):
            info = s["per_category"][cat]
            lines.append(f"    {cat:<24} {info['avg_confidence']}/5  (n={info['samples']})")
        lines += ["", f"  weakest: {', '.join(s['weakest_categories']) or '-'}"]
    return "\n".join(lines)
