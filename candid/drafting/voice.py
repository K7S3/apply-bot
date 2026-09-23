"""Voice profile: learn the user's writing style from approved samples.

``learn_style`` computes small, deterministic stats over a list of
``{"subject": ..., "body": ...}`` samples the user approved (e.g. drafts they
actually sent). ``apply_style`` nudges a new draft's greeting and signoff
toward the learned preference. Everything is rule-based -- no LLM, no
network -- so results are reproducible.
"""

from __future__ import annotations

import re
from collections import Counter

# Common English contractions (apostrophe forms).
_CONTRACTION_RE = re.compile(
    r"\b\w+'(?:re|ve|ll|d|s|m|t|clock)\b", re.IGNORECASE
)
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]+")


def _nonempty_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def learn_style(samples: list[dict]) -> dict:
    """Learn a deterministic style profile from approved {subject, body} samples.

    Returns stats:
      - avg_sentence_len: mean words per sentence across all bodies
      - greeting: most common first non-empty body line ("" if none)
      - signoff: most common last non-empty body line ("" if none)
      - contraction_rate: contractions / total body words
      - avg_body_words: mean body word count
      - sample_count: number of samples consumed

    Empty sample list -> neutral defaults (no crash).
    """
    bodies = [str(s.get("body", "")) for s in samples or []]
    greetings = Counter()
    signoffs = Counter()
    sentence_lens: list[int] = []
    body_words: list[int] = []
    contractions = 0
    total_words = 0

    for body in bodies:
        lines = _nonempty_lines(body)
        if lines:
            greetings[lines[0]] += 1
            signoffs[lines[-1]] += 1
        for s in _sentences(body):
            sentence_lens.append(len(_words(s)))
        words = _words(body)
        body_words.append(len(words))
        contractions += len(_CONTRACTION_RE.findall(body))
        total_words += len(words)

    def _top(counter: Counter) -> str:
        if not counter:
            return ""
        # most_common is insertion-ordered on ties -> deterministic
        return counter.most_common(1)[0][0]

    return {
        "avg_sentence_len": round(sum(sentence_lens) / len(sentence_lens), 2)
        if sentence_lens
        else 0.0,
        "greeting": _top(greetings),
        "signoff": _top(signoffs),
        "contraction_rate": round(contractions / total_words, 3)
        if total_words
        else 0.0,
        "avg_body_words": round(sum(body_words) / len(body_words), 2)
        if body_words
        else 0.0,
        "sample_count": len(bodies),
    }


def _replace_edge(lines: list[str], edge: int, new: str) -> list[str]:
    """Replace first (edge=0) or last (edge=-1) line, preserving body shape."""
    out = list(lines)
    out[edge] = new
    return out


def apply_style(draft: dict, profile: dict) -> dict:
    """Adjust a draft's greeting/signoff to the learned profile preference.

    Returns ``{"subject", "body", "changed"}``; ``changed`` lists the parts
    that were rewritten ("greeting", "signoff"). No-op when the draft already
    matches or the profile has no preference.
    """
    subject = str(draft.get("subject", ""))
    body = str(draft.get("body", ""))
    changed: list[str] = []

    greeting = (profile or {}).get("greeting") or ""
    signoff = (profile or {}).get("signoff") or ""
    lines = body.splitlines()

    first_idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if greeting and first_idx is not None and lines[first_idx].strip() != greeting:
        lines = _replace_edge(lines, first_idx, greeting)
        changed.append("greeting")

    last_idx = next(
        (i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None
    )
    if (
        signoff
        and last_idx is not None
        and last_idx != first_idx
        and lines[last_idx].strip() != signoff
    ):
        lines = _replace_edge(lines, last_idx, signoff)
        changed.append("signoff")

    return {"subject": subject, "body": "\n".join(lines), "changed": changed}
