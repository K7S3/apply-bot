"""Word-level approval flow and per-role pitch tailoring for career narratives.

Pitch drafts live under the "pitches" key of narrative.json (written by the
narrative builder). This module owns the "approvals" key only: it breaks a
pitch into numbered sentences for human review, records approve/edit/reject
decisions per sentence, and builds per-role tailored drafts that are NEVER
auto-approved. A pitch becomes canonical only when EVERY sentence is approved
(edited sentences count as approved after the edit). Rejected sentences are
dropped from the canonical text and block full approval.

All logic here is deterministic: no network, no keys, no LLMs at runtime.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config as C
from candid import profile as P


class NarrativeError(Exception):
    """Raised for invalid narrative review operations."""


# --- sentence splitting -------------------------------------------------------

# Placeholder swapped into abbreviations so "Dr." / "e.g." never split a sentence.
_DOT = "\ue000"

_ABBREVIATIONS = (
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "St.",
    "Inc.", "Ltd.", "Co.", "etc.", "vs.", "e.g.", "i.e.",
    "Ph.D.", "M.S.", "B.S.", "B.A.", "M.A.",
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=(?:[\"'\(\[]?\s*)[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, deterministically.

    Abbreviations such as "Dr." or "e.g." are protected before splitting so
    they never end a sentence. Raises NarrativeError on empty input.
    """
    if not text or not text.strip():
        raise NarrativeError("Cannot split an empty pitch into sentences.")
    protected = text
    for abbr in _ABBREVIATIONS:
        protected = protected.replace(abbr, abbr.replace(".", _DOT))
    parts = _SENT_SPLIT_RE.split(protected)
    return [p.replace(_DOT, ".").strip() for p in parts if p.replace(_DOT, ".").strip()]


# --- storage ------------------------------------------------------------------

def _narrative_path() -> Path:
    """narrative.json path, computed lazily so tests can rebind C.DATA_DIR."""
    return C.DATA_DIR / "narrative.json"


def _load_doc() -> dict:
    p = _narrative_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NarrativeError(f"Narrative file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NarrativeError(f"Narrative file {p} should contain a JSON object.")
    return data


def _save_doc(doc: dict) -> Path:
    p = _narrative_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def _approvals(doc: dict) -> dict:
    approvals = doc.get("approvals")
    if approvals is None:
        approvals = {}
        doc["approvals"] = approvals
    if not isinstance(approvals, dict):
        raise NarrativeError('The "approvals" key in narrative.json must be a JSON object.')
    return approvals


# --- pitch reading (worker A's "pitches" key, read defensively) ----------------

def _align_citations(citations, n: int) -> list[list[str]]:
    """Normalize citation data to one list of citation strings per sentence."""
    if isinstance(citations, dict):
        out = []
        for i in range(n):
            val = citations.get(str(i), citations.get(i, []))
            out.append(list(val) if isinstance(val, (list, tuple)) else [])
        return out
    if (
        isinstance(citations, list)
        and len(citations) == n
        and all(isinstance(c, (list, tuple)) for c in citations)
    ):
        return [list(c) for c in citations]
    return [[] for _ in range(n)]


def _pitch_sentences(length: str) -> tuple[str, list[dict]]:
    """Return (source text, sentence records) for a pitch draft.

    Accepts a pitch stored as a plain string or as a dict with "text" and
    optional "citations" (list-of-lists aligned with sentences, or a dict of
    sentence index -> citation list).
    """
    if not length:
        raise NarrativeError("A pitch length is required (e.g. '2min').")
    doc = _load_doc()
    pitches = doc.get("pitches") or {}
    pitch = pitches.get(length)
    if pitch is None:
        raise NarrativeError(
            f"No pitch draft found for length '{length}'. "
            "Build a pitch first (the narrative builder writes it under the "
            '"pitches" key of narrative.json).'
        )
    if isinstance(pitch, str):
        text, citations = pitch, None
    elif isinstance(pitch, dict):
        text, citations = pitch.get("text") or "", pitch.get("citations")
    else:
        raise NarrativeError(
            f'Pitch for length \'{length}\' must be a string or an object with "text".'
        )
    sentences = split_sentences(text)
    aligned = _align_citations(citations, len(sentences))
    records = [
        {"index": i, "text": s, "citations": aligned[i],
         "decision": "pending", "replacement": None}
        for i, s in enumerate(sentences)
    ]
    return text, records


def _blank_record(kind: str, key: str, text: str, sentences: list[dict],
                  extra: dict | None = None) -> dict:
    record = {
        "kind": kind,
        "key": key,
        "source_text": text,
        "sentences": sentences,
        "approved_text": "",
        "fully_approved": False,
    }
    if extra:
        record.update(extra)
    return record


# --- approval flow ------------------------------------------------------------

def review_pitch(length: str) -> list[dict]:
    """Break the pitch draft for `length` into numbered review sentences.

    Each returned sentence has {"index", "text", "citations", "decision",
    "replacement"}. The first call initializes a review record under
    approvals[length]; later calls return the existing record (with decisions
    intact) as long as the draft text has not changed.
    """
    text, sentences = _pitch_sentences(length)
    doc = _load_doc()
    approvals = _approvals(doc)
    existing = approvals.get(length)
    if (
        existing
        and existing.get("kind") == "pitch"
        and existing.get("source_text") == text
    ):
        return existing["sentences"]
    record = _blank_record("pitch", length, text, sentences, {"length": length})
    approvals[length] = record
    _save_doc(doc)
    return record["sentences"]


def _parse_decision(raw: object, idx: int) -> tuple[str, str | None]:
    if not isinstance(raw, str):
        raise NarrativeError(
            f"Sentence {idx}: decision must be a string, got {type(raw).__name__}."
        )
    if raw == "approve":
        return "approve", None
    if raw == "reject":
        return "reject", None
    if raw.startswith("edit:"):
        new_text = raw[len("edit:"):].strip()
        if not new_text:
            raise NarrativeError(f"Sentence {idx}: 'edit:' needs replacement text.")
        return "edit", new_text
    raise NarrativeError(
        f"Sentence {idx}: bad decision {raw!r}. "
        "Use 'approve', 'edit:<new text>', or 'reject'."
    )


def submit_review(key: str, decisions: dict) -> dict:
    """Record per-sentence decisions for a review.

    `key` is the approvals key: a plain pitch length ("2min") or a tailored
    draft key ("Acme::ML Engineer::2min"). `decisions` maps sentence index to
    "approve", "edit:<new text>", or "reject". Edited sentences count as
    approved; rejected sentences are dropped from the canonical text and
    block full approval. Returns the updated record.
    """
    if not isinstance(decisions, dict) or not decisions:
        raise NarrativeError("decisions must be a non-empty mapping of sentence index to decision.")
    doc = _load_doc()
    approvals = _approvals(doc)
    record = approvals.get(key)
    if record is None:
        raise NarrativeError(
            f"No review found for '{key}'. Start one with review_pitch() first."
        )
    sentences = record["sentences"]
    parsed: dict[int, tuple[str, str | None]] = {}
    for raw_idx, raw_decision in decisions.items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            raise NarrativeError(f"Bad sentence index {raw_idx!r}: must be an integer.") from None
        if idx < 0 or idx >= len(sentences):
            raise NarrativeError(
                f"Sentence index {idx} is out of range (0-{len(sentences) - 1})."
            )
        parsed[idx] = _parse_decision(raw_decision, idx)
    for idx, (decision, replacement) in parsed.items():
        sentences[idx]["decision"] = decision
        sentences[idx]["replacement"] = replacement
    record["approved_text"] = _canonical_text(sentences)
    record["fully_approved"] = all(
        s["decision"] in ("approve", "edit") for s in sentences
    )
    _save_doc(doc)
    return record


def _canonical_text(sentences: list[dict]) -> str:
    parts = []
    for s in sentences:
        if s["decision"] == "edit":
            parts.append(s["replacement"])
        elif s["decision"] == "approve":
            parts.append(s["text"])
    return " ".join(p for p in parts if p).strip()


def approval_status(key: str) -> dict:
    """Report whether EVERY word of a review is approved.

    Returns {"key", "total", "approved", "edited", "rejected", "pending",
    "fully_approved", "approved_text"}. A review counts as fully approved
    only when all sentences carry "approve" or "edit" (no pending, no reject).
    """
    doc = _load_doc()
    approvals = _approvals(doc)
    record = approvals.get(key)
    if record is None:
        raise NarrativeError(
            f"No review found for '{key}'. Start one with review_pitch() first."
        )
    sentences = record["sentences"]
    counts = {"approved": 0, "edited": 0, "rejected": 0, "pending": 0}
    for s in sentences:
        d = s.get("decision", "pending")
        if d == "approve":
            counts["approved"] += 1
        elif d == "edit":
            counts["edited"] += 1
        elif d == "reject":
            counts["rejected"] += 1
        else:
            counts["pending"] += 1
    return {
        "key": key,
        "total": len(sentences),
        "approved": counts["approved"],
        "edited": counts["edited"],
        "rejected": counts["rejected"],
        "pending": counts["pending"],
        "fully_approved": bool(record.get("fully_approved")),
        "approved_text": record.get("approved_text", ""),
    }


# --- per-role pitch tailoring -------------------------------------------------

def _jd_keywords(jd_text: str, profile: dict) -> list[str]:
    """Canonical lexicon skills present in BOTH the JD and the profile."""
    jd_low = (jd_text or "").lower()
    profile_skills = {
        s.lower() for s in (profile.get("skills") or []) if isinstance(s, str)
    }
    matched = []
    for canonical, aliases in C.SKILL_LEXICON.items():
        if canonical.lower() not in profile_skills:
            continue
        terms = set(aliases) | {canonical}
        if any(C.skill_regex(a).search(jd_low) for a in terms):
            matched.append(canonical)
    return matched


def _sentence_keyword_hits(sentence: str, jd_keywords: list[str]) -> list[str]:
    """JD keywords (from the lexicon) mentioned in a sentence, deterministic."""
    low = sentence.lower()
    hits = []
    for canonical in jd_keywords:
        aliases = C.SKILL_LEXICON.get(canonical, [])
        terms = set(aliases) | {canonical}
        if any(C.skill_regex(a).search(low) for a in terms):
            hits.append(canonical)
    return hits


def tailor_pitch(jd_text: str, company: str, role: str, length: str = "2min") -> dict:
    """Reorder a pitch's sentences to emphasize JD keyword matches.

    Deterministic keyword-overlap scoring: sentences are reordered (stable) so
    the ones mentioning the most JD keywords come first. Sentences are copied
    VERBATIM, no new factual claims are ever added, and the draft is stored
    clearly marked as needing approval (never auto-approved) under
    approvals["{company}::{role}::{length}"].

    JD keywords are canonical lexicon skills present in BOTH the JD text and
    the user's profile. Raises NarrativeError if the pitch draft or the
    profile is missing.
    """
    if not company or not role:
        raise NarrativeError("Both company and role are required to tailor a pitch.")
    key = f"{company}::{role}::{length}"
    sentences = review_pitch(length)
    profile_path = C.DATA_DIR / "profile.json"
    try:
        profile = P.load_profile(profile_path)
    except P.OnboardError as exc:
        raise NarrativeError(
            "Tailoring needs your profile for keyword grounding, but no profile "
            f"was found at {profile_path}. Onboard first:\n"
            "    python -m candid onboard --resume your_resume.pdf"
        ) from exc
    keywords = _jd_keywords(jd_text, profile)
    scored = []
    for s in sentences:
        hits = _sentence_keyword_hits(s["text"], keywords)
        scored.append((s, hits))
    order = sorted(range(len(scored)), key=lambda i: (-len(scored[i][1]), i))
    tailored_sentences = []
    for new_idx, old_idx in enumerate(order):
        s, hits = scored[old_idx]
        tailored_sentences.append({
            "index": new_idx,
            "original_index": old_idx,
            "text": s["text"],
            "citations": list(s["citations"]),
            "decision": "pending",
            "replacement": None,
            "matched_keywords": hits,
        })
    doc = _load_doc()
    approvals = _approvals(doc)
    record = _blank_record(
        "tailored", key, " ||| ".join(s["text"] for s in tailored_sentences),
        tailored_sentences,
        {
            "company": company,
            "role": role,
            "length": length,
            "jd_keywords": keywords,
            "needs_approval": True,
            "note": (
                "Tailored draft. NOT approved: review every sentence "
                "(review_pitch semantics apply via submit_review) before use."
            ),
        },
    )
    approvals[key] = record
    _save_doc(doc)
    return record
