"""Polish intelligence: competency tagging, question pairing, rubric scoring.

Deterministic, rule-based intelligence layered over the polished-answer
library (``DATA_DIR/polish_library.json``, written by the polish feature).
No network, no models, no APIs — keyword lists, regexes and arithmetic only.

Public surface:

- ``tag_competencies(text)`` — competencies demonstrated by a story/answer.
  Reuses ``candid.stories.COMPETENCY_KEYWORDS`` when that module is
  importable (it lives on another worker's branch); falls back to a built-in
  keyword map otherwise. Matching is case-insensitive; keywords of 3 chars
  or fewer are word-boundary matched so "led" doesn't fire in "profiled".
- ``pair_with_question(question, entries=None)`` — rank approved library
  entries that best answer a new interview question, by keyword overlap.
- ``rubric_score(original, polished)`` — heuristic 1-5 scores for clarity,
  structure, specificity and impact. Scores the polished text; ``original``
  is used only to describe the improvement in the notes. Pass
  ``(text, text)`` to score a single text.
- ``before_after_report()`` — aggregate gains over library entries that
  have both an original and a polished answer. Keys:
  ``n_entries``, ``avg_word_reduction_pct``, ``total_fillers_removed``,
  ``avg_rubric_delta``, ``competency_coverage`` (competency -> entry count),
  ``entries`` (per-entry breakdown).
- ``format_report(report)`` — render the report dict as readable text.

The library file is read directly from disk; this module never imports the
polish library *writer* module. (``candid.debrief`` is intentionally not
imported: none of these functions need debrief files.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config


class IntelError(Exception):
    """Raised for polish-intel problems: bad input, missing entry, unreadable library."""


# ---------------------------------------------------------------------------
# Library access (read-only; never imports the polish writer module)
# ---------------------------------------------------------------------------

POLISH_LIBRARY_FILENAME = "polish_library.json"
APPROVED_STATUS = "approved"


def library_path() -> Path:
    """Path to the polish library JSON under the active DATA_DIR.

    Resolved at call time (not import time) so tests can repoint
    ``candid.config.DATA_DIR`` before calling.
    """
    return config.DATA_DIR / POLISH_LIBRARY_FILENAME


def load_entries(status: str | None = None) -> list[dict]:
    """Read the polish library file directly. A missing file yields []."""
    path = library_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise IntelError(f"Cannot read polish library at {path}: {exc}") from exc
    if isinstance(raw, dict):
        raw = raw.get("entries", [])
    if not isinstance(raw, list):
        raise IntelError(
            f"Unexpected schema in {path}: expected a JSON list of entries.")
    entries = [e for e in raw if isinstance(e, dict)]
    if status is not None:
        entries = [e for e in entries if e.get("status") == status]
    return entries


def get_entry(entry_id: str) -> dict:
    """Fetch one library entry by id; raises IntelError when missing."""
    for entry in load_entries():
        if str(entry.get("id")) == str(entry_id):
            return entry
    raise IntelError(f"No polish library entry with id {entry_id!r}.")


# ---------------------------------------------------------------------------
# Competency tagging
# ---------------------------------------------------------------------------

try:  # stories lives on another worker's branch; prefer it once merged
    from candid.stories import COMPETENCY_KEYWORDS as _STORIES_KEYWORDS
except ImportError:  # pragma: no cover - depends on sibling branch state
    _STORIES_KEYWORDS = None

# Fallback: competency -> keyword substrings, matched case-insensitively.
_FALLBACK_COMPETENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "adaptability": ("adapt", "pivot", "ambiguous", "uncertain",
                     "unfamiliar", "learned quickly", "changed direction"),
    "collaboration": ("collaborat", "cross-functional", "teamed up",
                      "partnered", "coordinat", "align"),
    "communication": ("communicat", "presented", "explained", "stakeholder",
                      "articulate", "pitched", "documented"),
    "conflict_resolution": ("disagree", "conflict", "push back", "escalat",
                            "compromise", "difficult conversation",
                            "resolved the tension"),
    "customer_focus": ("customer", "client", "user feedback", "empathy",
                       "delighted", "support ticket"),
    "leadership": ("led", "lead", "mentor", "manag", "direct", "coach",
                   "drove the team", "grew the team"),
    "ownership": ("took ownership", "initiative", "spearheaded", "proposed",
                  "volunteered", "owned the"),
    "problem_solving": ("root cause", "debugg", "troubleshoot", "investigat",
                        "analyz", "narrowed down", "reproduc"),
    "results": ("increased", "reduced", "improved", "grew revenue",
                "cut costs", "shipped", "delivered", "doubled", "%", "$"),
    "technical_depth": ("designed the", "architecture", "scaled", "optim",
                        "refactored", "performance bottleneck", "trade-off"),
}


def _competency_keywords() -> dict:
    """The real stories map when importable, else the built-in fallback."""
    return _STORIES_KEYWORDS or _FALLBACK_COMPETENCY_KEYWORDS


def _keyword_hit(keyword: str, lowered: str) -> bool:
    """Case-insensitive substring hit, with a guard for tiny keywords.

    Keywords of 3 chars or fewer (e.g. "led") are matched on word
    boundaries so they don't fire inside longer words ("led" in
    "profiled"); longer keywords keep plain substring semantics.
    """
    kw = str(keyword).lower()
    if len(kw) <= 3:
        return re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])",
                         lowered) is not None
    return kw in lowered


def tag_competencies(text: str) -> list[str]:
    """Return the sorted competencies whose keyword substrings appear in text.

    Matching is case-insensitive substring matching, reusing
    ``stories.COMPETENCY_KEYWORDS`` when available.
    """
    if not isinstance(text, str):
        raise IntelError(f"text must be a string, got {type(text).__name__}.")
    lowered = text.lower()
    return sorted(
        competency
        for competency, keywords in _competency_keywords().items()
        if any(_keyword_hit(kw, lowered) for kw in keywords)
    )


# ---------------------------------------------------------------------------
# Question pairing
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset("""
a an the and or but if then else when at by for with about into through during
before after above below to from up down in out on off over under again further
once here there all any both each few more most other some such no nor not only
own same so than too very can will just should now i me my we our you your he
she it they them his her its their this that these those am is are was were be
been being have has had having do does did doing would could ought i'm i've
i'll i'd what's that's there's here's how what which who whom whose where why
of as tell me about your describe time times
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _content_tokens(text: str) -> set[str]:
    """Lowercased word tokens minus stopwords and tiny tokens."""
    return {t for t in _TOKEN_RE.findall(text.lower())
            if t not in _STOPWORDS and len(t) > 2}


def pair_with_question(question: str,
                       entries: list[dict] | None = None) -> list[dict]:
    """Rank library entries that best answer ``question``.

    ``entries`` defaults to the approved library entries. Each candidate is
    scored by distinct content-word overlap between the question and the
    candidate's (question + polished) text; a keyword that also appears in
    the candidate's own question counts double. Returns best-first; ties
    break on entry id for determinism. Each row carries an ``explanation``.
    """
    if not isinstance(question, str) or not question.strip():
        raise IntelError("question must be a non-empty string.")
    if entries is None:
        entries = load_entries(status=APPROVED_STATUS)
    if not isinstance(entries, list):
        raise IntelError("entries must be a list of library entry dicts.")
    q_tokens = _content_tokens(question)
    ranked: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cand_question = str(entry.get("question") or "")
        cand_body = str(entry.get("polished") or entry.get("original") or "")
        body_tokens = _content_tokens(cand_question + "\n" + cand_body)
        matched = sorted(q_tokens & body_tokens)
        if not matched:
            continue
        question_tokens = _content_tokens(cand_question)
        score = sum(2 if kw in question_tokens else 1 for kw in matched)
        name = entry.get("name") or entry.get("id") or "untitled"
        ranked.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "score": score,
            "matched_keywords": matched,
            "explanation": (
                f"Shares {len(matched)} keyword(s) ({', '.join(matched)}) "
                f"with the question; best fit from entry '{name}'."
            ),
        })
    ranked.sort(key=lambda r: (-r["score"],
                               str(r["id"] if r["id"] is not None else "")))
    return ranked


# ---------------------------------------------------------------------------
# Rubric scoring
# ---------------------------------------------------------------------------

# Filler words/phrases counted word-boundary-aware. Note: common words like
# "like" and "actually" are counted even when used legitimately — the same
# rule applies to both texts, so the before/after *diff* stays meaningful.
_FILLERS = (
    "um", "uh", "erm", "ah", "like", "you know", "i mean", "basically",
    "kind of", "sort of", "stuff", "things", "anyway", "honestly",
    "obviously", "literally", "actually", "pretty much",
)

_STAR_MARKERS = {
    "situation": ("situation", "context", "background", "at the time",
                  "when i joined"),
    "task": ("task", "goal", "objective", "challenge", "problem was"),
    "action": ("action", "steps i took", "i decided", "i built", "i led",
               "i proposed", "my approach", "what i did", "i worked with"),
    "result": ("result", "outcome", "impact", "as a result", "led to",
               "we achieved", "in the end"),
}

_OUTCOME_VERBS = (
    "achiev", "deliver", "increas", "reduc", "improv", "grew", "saved",
    "shipp", "launch", "drove", "exceed", "doubl", "halv", "accelerat",
    "unblock", "eliminat",
)

_METRIC_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_NUMBER_RE = re.compile(r"\d")


def count_fillers(text: str) -> int:
    """Count filler word/phrase occurrences (word-boundary aware)."""
    lowered = text.lower()
    return sum(
        len(re.findall(r"\b" + re.escape(filler) + r"\b", lowered))
        for filler in _FILLERS
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?;]+", text) if s.strip()]


def _word_list(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text)


def _clamp1to5(value: float) -> int:
    return max(1, min(5, int(round(value))))


def _score_clarity(text: str) -> tuple[int, str]:
    words = _word_list(text)
    sentences = _sentences(text)
    if not words:
        return 1, "Empty answer: nothing to score."
    avg_len = len(words) / max(len(sentences), 1)
    fillers = count_fillers(text)
    density = fillers / len(words) * 100
    score = 5
    if density > 8:
        score -= 2
    elif density > 3:
        score -= 1
    if avg_len > 32 or avg_len < 8:
        score -= 1
    detail = (f"{len(words)} words in {len(sentences)} sentence(s) "
              f"(avg {avg_len:.1f} words/sentence), {fillers} filler(s) "
              f"({density:.1f} per 100 words).")
    return _clamp1to5(score), detail


def _star_coverage(text: str) -> dict[str, bool]:
    lowered = text.lower()
    return {section: any(m in lowered for m in markers)
            for section, markers in _STAR_MARKERS.items()}


def _score_structure(text: str) -> tuple[int, str]:
    found = [s for s, hit in _star_coverage(text).items() if hit]
    detail = (f"STAR sections detected: {', '.join(found) or 'none'} "
              f"({len(found)}/4).")
    return _clamp1to5(1 + len(found)), detail


def _metric_tokens(text: str) -> list[str]:
    return _METRIC_RE.findall(text)


def _proper_nouns(text: str) -> list[str]:
    nouns = []
    for sent in _sentences(text):
        for word in _word_list(sent)[1:]:  # skip sentence-initial word
            if (len(word) > 1 and word[0].isupper() and word != "I"
                    and word.lower() not in _STOPWORDS):
                nouns.append(word)
    return nouns


def _score_specificity(text: str) -> tuple[int, str]:
    metrics = _metric_tokens(text)
    nouns = _proper_nouns(text)
    detail = (f"{len(metrics)} metric(s) ({', '.join(metrics[:5]) or 'none'}), "
              f"{len(nouns)} proper noun(s) ({', '.join(nouns[:5]) or 'none'}).")
    return _clamp1to5(1 + min(2, len(metrics)) + min(2, len(nouns))), detail


def _outcome_verb_hits(text: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(verb) for verb in _OUTCOME_VERBS)


def _score_impact(text: str) -> tuple[int, str]:
    hits = _outcome_verb_hits(text)
    result_hit = _star_coverage(text)["result"]
    quantified = result_hit and bool(_NUMBER_RE.search(text))
    detail = (f"{hits} outcome verb(s); result section "
              f"{'present' if result_hit else 'missing'}"
              f"{' with numbers' if quantified else ''}.")
    return _clamp1to5(1 + min(3, hits) + (1 if quantified else 0)), detail


def _next_step(dimension: str, polished: str) -> str:
    """One concrete next improvement for a rubric dimension."""
    if dimension == "clarity":
        return ("cut any remaining filler words and split sentences "
                "longer than ~30 words")
    if dimension == "structure":
        missing = [s for s, hit in _star_coverage(polished).items() if not hit]
        if missing:
            return "add an explicit " + "/".join(missing) + " section"
        return "tighten each STAR section to 2-3 sentences"
    if dimension == "specificity":
        return ("add one concrete number (%, $, time saved) and name the "
                "team or system involved")
    if not _star_coverage(polished)["result"]:
        return ("close with a result: what changed because of your actions, "
                "in numbers")
    return "strengthen the outcome with a before/after metric"


def _rubric_notes(original: str, polished: str,
                  pol_scores: dict[str, tuple[int, str]]) -> list[str]:
    orig_scores = {
        "clarity": _score_clarity(original),
        "structure": _score_structure(original),
        "specificity": _score_specificity(original),
        "impact": _score_impact(original),
    }
    notes = []
    for dimension in ("clarity", "structure", "specificity", "impact"):
        new, detail = pol_scores[dimension]
        old = orig_scores[dimension][0]
        delta = (f" (was {old}, {'+' if new - old >= 0 else ''}{new - old})"
                 if old != new else " (unchanged)")
        notes.append(
            f"{dimension.capitalize()} {new}/5{delta}: {detail} "
            f"Next: {_next_step(dimension, polished)}."
        )
    return notes


def rubric_score(original: str, polished: str) -> dict:
    """Score the polished answer 1-5 on four heuristic dimensions.

    - clarity: sentence length and filler density
    - structure: STAR section coverage
    - specificity: numbers/metrics and proper nouns
    - impact: result-section strength and outcome verbs

    Returns ``{"clarity", "structure", "specificity", "impact", "overall",
    "notes"}``; ``overall`` is the mean of the four, and each note explains
    its score (with the delta vs ``original``) plus one concrete next step.
    """
    for label, value in (("original", original), ("polished", polished)):
        if not isinstance(value, str) or not value.strip():
            raise IntelError(f"{label} must be a non-empty string.")
    scores: dict[str, tuple[int, str]] = {
        "clarity": _score_clarity(polished),
        "structure": _score_structure(polished),
        "specificity": _score_specificity(polished),
        "impact": _score_impact(polished),
    }
    overall = round(sum(s for s, _ in scores.values()) / len(scores), 2)
    return {
        "clarity": scores["clarity"][0],
        "structure": scores["structure"][0],
        "specificity": scores["specificity"][0],
        "impact": scores["impact"][0],
        "overall": overall,
        "notes": _rubric_notes(original, polished, scores),
    }


# ---------------------------------------------------------------------------
# Before/after report
# ---------------------------------------------------------------------------

def before_after_report() -> dict:
    """Aggregate polish gains over entries with both original and polished text.

    - ``avg_word_reduction_pct``: mean per-entry word-count change
      (positive = polished is shorter)
    - ``total_fillers_removed``: sum of per-entry filler-count diffs,
      floored at 0 per entry
    - ``avg_rubric_delta``: mean (polished overall - original overall)
    - ``competency_coverage``: competency -> number of polished answers
      tagged with it
    """
    usable = [e for e in load_entries()
              if isinstance(e, dict)
              and str(e.get("original") or "").strip()
              and str(e.get("polished") or "").strip()]
    per_entry = []
    for entry in usable:
        original, polished = entry["original"], entry["polished"]
        orig_words = len(_word_list(original))
        pol_words = len(_word_list(polished))
        reduction = ((orig_words - pol_words) / orig_words * 100
                     if orig_words else 0.0)
        fillers_removed = max(0, count_fillers(original) - count_fillers(polished))
        delta = (rubric_score(original, polished)["overall"]
                 - rubric_score(original, original)["overall"])
        per_entry.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "word_reduction_pct": round(reduction, 1),
            "fillers_removed": fillers_removed,
            "rubric_delta": round(delta, 2),
        })
    coverage: dict[str, int] = {}
    for entry in usable:
        for competency in tag_competencies(str(entry["polished"])):
            coverage[competency] = coverage.get(competency, 0) + 1
    coverage = dict(sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0])))
    n = len(usable)
    return {
        "n_entries": n,
        "avg_word_reduction_pct": (
            round(sum(p["word_reduction_pct"] for p in per_entry) / n, 1)
            if n else 0.0),
        "total_fillers_removed": sum(p["fillers_removed"] for p in per_entry),
        "avg_rubric_delta": (
            round(sum(p["rubric_delta"] for p in per_entry) / n, 2)
            if n else 0.0),
        "competency_coverage": coverage,
        "entries": per_entry,
    }


def format_report(report: dict) -> str:
    """Render a ``before_after_report()`` dict as readable text."""
    lines = [
        "Polish before/after report",
        f"Entries analyzed: {report.get('n_entries', 0)}",
        "",
        "Average word-count reduction: "
        f"{report.get('avg_word_reduction_pct', 0.0):.1f}%",
        "Total fillers removed (diff-based): "
        f"{report.get('total_fillers_removed', 0)}",
        "Average rubric delta (1-5 scale): "
        f"{report.get('avg_rubric_delta', 0.0):+.2f}",
        "",
        "Competency coverage (polished answers):",
    ]
    coverage = report.get("competency_coverage") or {}
    if coverage:
        lines.extend(f"  {comp}: {count}" for comp, count in coverage.items())
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Per entry:")
    entries = report.get("entries") or []
    if entries:
        for pe in entries:
            lines.append(
                f"  {pe.get('id')} {pe.get('name') or ''}: "
                f"words {pe.get('word_reduction_pct', 0.0):+.1f}%, "
                f"fillers -{pe.get('fillers_removed', 0)}, "
                f"rubric {pe.get('rubric_delta', 0.0):+.2f}"
            )
    else:
        lines.append("  (none)")
    return "\n".join(lines)
