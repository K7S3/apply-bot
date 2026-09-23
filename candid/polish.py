"""Interview answer polisher: deterministic, rule-based STAR rewriting.

Pipeline (all local, no network, no APIs):
  1. scrub_fillers()  -- strip filler phrases and hedges, keep every
                         number, metric, and proper noun.
  2. to_star()         -- split the draft into Situation / Task / Action /
                         Result using marker heuristics. Never invents
                         content: sections it cannot find stay empty and are
                         listed under "missing".
  3. tighten           -- cut lowest-information sentences first to fit the
                         spoken target (~150 words per minute), but always
                         keep sentences that carry numbers/metrics.

Usage:
    python -m candid polish run --file draft.txt [--target-seconds 90] [--json]
    python -m candid polish star --file draft.txt [--json]
    python -m candid polish scrub --file draft.txt [--json]

polish_answer() returns everything the caller needs:
    {"original", "polished", "star", "stats", "suggestions"}
suggestions only flag gaps ("no quantified result") and never add claims.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

#: Spoken pace used to size the tightened answer (words per minute).
WORDS_PER_MINUTE = 150

#: Content-word stopwords for the voice-overlap computation.
_STOPWORDS = frozenset(
    "a an and are as at be been because before between both but by can could "
    "did do does done during each few for from further had has have having he "
    "her hers herself him himself his how i if in into is it its itself just "
    "me more most my no not now of off on once only or other our ours really "
    "same she should so some such than that the their theirs them then there "
    "these they this those through to too under up very was we were what when "
    "where which while who whom with would you your yours also again about "
    "after all any both each few further once over own quite rather than too "
    "up will may might must shall s t ve ll re d m".split()
)


class PolishError(Exception):
    """Expected failure: missing draft file, empty input, bad arguments."""


# ---------------------------------------------------------------------------
# 1. input
# ---------------------------------------------------------------------------

def read_draft(source: str) -> str:
    """Read a draft from a file path, "-" (stdin), or "text:<raw text>".

    Raises PolishError on a missing file or on empty input.
    """
    if source == "-":
        text = sys.stdin.read()
    elif source.startswith("text:"):
        text = source[len("text:"):]
    else:
        path = Path(source)
        if not path.is_file():
            raise PolishError(f"Draft file not found: {source}")
        text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise PolishError("Draft is empty: nothing to polish.")
    return text.strip()


# ---------------------------------------------------------------------------
# 2. filler scrubbing
# ---------------------------------------------------------------------------

#: (regex, replacement, canonical label). Applied in order; labels feed `removed_list`.
_FILLER_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # sentence-leading hedges ("Actually, ...", "Well, ..."): keep the
    # sentence boundary/prefix in group 1, drop the hedge itself.
    (r"(^|[.!?]\s+)actually,\s*", r"\1", "actually"),
    (r"(^|[.!?]\s+)well,\s*", r"\1", "well"),
    (r"(^|[.!?]\s+)so,\s*", r"\1", "so"),
    (r"(^|[.!?]\s+)(?:um|uh|er|ah),\s*", r"\1", "um"),
    # freestanding filler words
    (r"\byou know\b[,\s]*", "", "you know"),
    (r"\bbasically\b[,\s]*", "", "basically"),
    (r"\bsort of\b\s*", "", "sort of"),
    (r"\bkind of\b\s*", "", "kind of"),
    (r"\bi think maybe\b\s*", "", "i think maybe"),
    (r"\bi guess\b\s*", "", "i guess"),
    (r",?\s*\blike\s*,", "", "like"),
    (r"\b(?:um|uh|er|ah)\b[,\s]*", "", "um"),
)

_NUM_RE = re.compile(r"\d")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def scrub_fillers(text: str) -> tuple[str, list[str]]:
    """Remove filler phrases and hedges.

    Returns (cleaned_text, removed_list) where removed_list holds one
    canonical label per removal, in order of occurrence. Numbers, metrics,
    and proper nouns are never deleted.
    """
    removed: list[str] = []
    cleaned = text
    # snapshot protected tokens so the regex pass can never eat them
    protected = set(_NUM_RE.findall(cleaned)) | set(
        m.group(0) for m in _PROPER_NOUN_RE.finditer(cleaned)
    )
    for pattern, replacement, label in _FILLER_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE)
        while True:
            m = regex.search(cleaned)
            if not m:
                break
            span = m.group(0)
            # safety: never remove something that is (or contains) a number
            # or a proper noun
            if _NUM_RE.search(span) or span.strip() in protected:
                # blank this one occurrence only and stop matching it
                cleaned = cleaned[: m.start()] + " " + cleaned[m.end():]
                continue
            removed.append(label)
            cleaned = (cleaned[: m.start()]
                       + m.expand(replacement)
                       + cleaned[m.end():])
    cleaned = _tidy(cleaned)
    # a leading stray comma from an eaten sentence starter
    cleaned = re.sub(r"(^|[.!?])\s*,\s*", r"\1 ", cleaned)
    return _tidy(cleaned), removed


# ---------------------------------------------------------------------------
# 3. STAR split
# ---------------------------------------------------------------------------

_TASK_RE = re.compile(
    r"\b(needed to|asked to|had to|tasked with|assigned to|responsible for|"
    r"my goal was|my job was|supposed to)\b",
    re.IGNORECASE,
)
_RESULT_RE = re.compile(
    r"\b(resulted in|led to|as a result|the outcome|outcome was|achieved|"
    r"improved by|reduced by|increased by|decreased by|cut by|delivered|"
    r"shipped|saved\b)",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"\bi\s+(built|led|created|designed|implemented|wrote|drove|launched|"
    r"fixed|ran|worked|partnered|coordinated|proposed|refactored|migrated|"
    r"automated|mentored|presented|pitched|debugged|shipped|owned|"
    r"kick(?:ed)?\s+off|set\s+up|took\s+over)\b",
    re.IGNORECASE,
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text.strip()) if s.strip()]


def _has_metric(sentence: str) -> bool:
    """A number, percentage, or money figure: never cut these sentences."""
    return bool(_NUM_RE.search(sentence))


def to_star(text: str) -> dict:
    """Split a rambling draft into a STAR dict.

    {"situation", "task", "action", "result", "missing": [...]}
    Each sentence lands in exactly one section by precedence
    task > result > action > situation. Unclassified sentences become the
    situation (context). Sections that cannot be found stay "" and are named
    in "missing". Nothing is invented.
    """
    sections = {"situation": [], "task": [], "action": [], "result": []}
    for sent in _sentences(text):
        if _TASK_RE.search(sent):
            sections["task"].append(sent)
        elif _RESULT_RE.search(sent) or _has_metric(sent):
            sections["result"].append(sent)
        elif _ACTION_RE.search(sent):
            sections["action"].append(sent)
        else:
            sections["situation"].append(sent)
    star = {k: " ".join(v) for k, v in sections.items()}
    star["missing"] = [k for k in ("situation", "task", "action", "result")
                       if not star[k].strip()]
    return star


# ---------------------------------------------------------------------------
# 4. tightening + voice preservation
# ---------------------------------------------------------------------------

def _info_score(sentence: str) -> float:
    score = len(sentence.split()) / 100.0  # longer sentences carry more info
    if _RESULT_RE.search(sentence):
        score += 2.0
    if _ACTION_RE.search(sentence):
        score += 1.0
    if _TASK_RE.search(sentence):
        score += 0.5
    return score


def _tighten(sentences: list[str], target_words: int) -> tuple[list[str], list[str]]:
    """Drop lowest-information sentences until under budget.

    Sentences with numbers/metrics are always kept, even if that means the
    result exceeds the target.
    """
    word_count = sum(len(s.split()) for s in sentences)
    if word_count <= target_words:
        return list(sentences), []
    protected = [s for s in sentences if _has_metric(s)]
    rest = [s for s in sentences if not _has_metric(s)]
    budget = target_words - sum(len(s.split()) for s in protected)
    kept: list[str] = list(protected)
    dropped: list[str] = []
    for s in sorted(rest, key=_info_score, reverse=True):
        w = len(s.split())
        if w <= budget:
            kept.append(s)
            budget -= w
        else:
            dropped.append(s)
    kept.sort(key=sentences.index)
    return kept, dropped


def _content_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in _STOPWORDS and len(w) > 1
    }


def voice_overlap(original: str, polished: str) -> float:
    """Word-overlap % between original and polished content words."""
    orig = _content_words(original)
    if not orig:
        return 0.0
    return round(len(orig & _content_words(polished)) / len(orig) * 100, 1)


def render_diff(original: str, polished: str) -> str:
    """Human-readable unified diff (plain text, terminal friendly)."""
    diff = difflib.unified_diff(
        original.splitlines(), polished.splitlines(),
        fromfile="original", tofile="polished", lineterm="",
    )
    return "\n".join(diff)


def polish_answer(text: str, target_seconds: int = 90) -> dict:
    """Full pipeline: scrub -> STAR split -> tighten.

    Returns {"original", "polished", "star", "stats", "suggestions"}.
    suggestions flag gaps and drift; they never add claims.
    """
    if target_seconds <= 0:
        raise PolishError("target-seconds must be positive.")
    original = text.strip()
    cleaned, removed = scrub_fillers(original)
    star = to_star(cleaned)

    target_words = max(1, int(target_seconds / 60 * WORDS_PER_MINUTE))
    sentences = _sentences(cleaned)
    kept, dropped = _tighten(sentences, target_words)
    polished = " ".join(kept)

    overlap = voice_overlap(original, polished)
    words_before = len(original.split())
    words_after = len(polished.split())

    suggestions: list[str] = []
    for section in ("situation", "task", "action", "result"):
        if not star[section]:
            suggestions.append(
                f"{section} section missing: add a sentence covering it; "
                "nothing was invented for you."
            )
    if not _has_metric(star["result"]):
        suggestions.append(
            "no quantified result: add a number, %, or outcome metric "
            "to the result section."
        )
    if dropped:
        suggestions.append(
            f"cut {len(dropped)} low-information sentence(s) to fit "
            f"~{target_seconds}s; metric sentences were kept."
        )
    if words_after > target_words:
        suggestions.append(
            f"still {words_after - target_words} words over the "
            f"~{target_seconds}s target because metric sentences were kept."
        )
    if overlap < 60:
        suggestions.append(
            f"rewrite drifted from your voice ({overlap:.0f}% word overlap, "
            "below the 60% floor): consider restoring your phrasing."
        )

    return {
        "original": original,
        "polished": polished,
        "star": star,
        "stats": {
            "words_before": words_before,
            "words_after": words_after,
            "fillers_removed": len(removed),
            "voice_overlap_pct": overlap,
        },
        "suggestions": suggestions,
    }
