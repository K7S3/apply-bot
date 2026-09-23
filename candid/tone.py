"""Tone tuner: nudge a draft toward the user's voice.

This module performs a light stylistic pass, NOT a rewrite. It only
touches:

  - the greeting line ("Hi Priya," becomes "Dear Priya,")
  - the sign-off line ("Best," becomes "Warm regards,")
  - a small curated map of hedgy or wordy phrases per tone
    ("I was wondering if" becomes "Could you" for direct)
  - sentence splitting/joining for the concise tone and for match_voice

It never invents new content and never alters names, dates, numbers, or
other facts: the phrase maps only match their listed templates, so fact
strings pass through untouched. Anything fancier (rewording for clarity,
restructuring an argument, changing what the draft asks for) is out of
scope; edit the draft yourself for that.

Deterministic: same input gives same output, every time. No network,
no API keys, stdlib only.

Limitations: the rules are plain string matching, so they can misfire on
quoted text or on phrasing that already matches the target tone, and
splitting/joining sentences is a heuristic, not grammar-aware. As a side
effect, em/en dashes in the input are normalized to hyphens, per the
project-wide style rule (no em dashes in user-facing text).
"""

from __future__ import annotations

import re

TONES = ["warm", "formal", "concise", "enthusiastic", "direct"]

_GREETING_BY_TONE = {
    "warm": "Hi",
    "formal": "Dear",
    "concise": "Hi",
    "enthusiastic": "Hi",
    "direct": "Hello",
}

_CLOSER_BY_TONE = {
    "warm": "Warm regards,",
    "formal": "Sincerely,",
    "concise": "Best,",
    "enthusiastic": "Best,",
    "direct": "Best,",
}

_GREETING_WORDS = (
    "Good morning", "Good afternoon", "Greetings",
    "Hi", "Hey", "Hello", "Dear",
)
_GREETING_RE = re.compile(
    r"^(" + "|".join(_GREETING_WORDS) + r")\b(.*)$", re.IGNORECASE
)

_SIGNOFF_WORDS = (
    "Warm regards", "Yours truly", "Thank you", "Talk soon",
    "Take care", "Warmly", "Sincerely", "Respectfully",
    "Thanks", "Regards", "Cheers", "Best",
)
_SIGNOFF_RE = re.compile(
    r"^(" + "|".join(_SIGNOFF_WORDS) + r")\b[,.]?\s*$", re.IGNORECASE
)

# Curated per-tone phrase swaps: (regex, replacement). Kept deliberately
# small and conservative; replacements are capitalized to fit their slot.
_SWAPS: dict[str, list[tuple[str, str]]] = {
    "warm": [
        (r"\bthank you\b", "thanks so much"),
        (r"\bI would appreciate\b", "I'd really appreciate"),
        (r"\bplease let me know\b", "I'd love to hear"),
    ],
    "formal": [
        (r"\bthanks so much\b", "thank you very much"),
        (r"\bthanks a lot\b", "thank you very much"),
        (r"\bcan't wait\b", "look forward"),
        (r"\breally excited\b", "very enthusiastic"),
        (r"\bhope you're doing well\b", "I hope this message finds you well"),
        (r"\bjust checking in\b", "following up"),
    ],
    "concise": [
        (r"\bin order to\b", "to"),
        (r"\bdue to the fact that\b", "because"),
        (r"\bat this point in time\b", "now"),
        (r"\ba little while\b", "a while"),
        (r"\bjust wanted to\b", "wanted to"),
        (r"\bplease do not hesitate to\b", "please"),
        (r"\bI hope you(?:'re| are) doing well[.!]?\s*", ""),
    ],
    "enthusiastic": [
        (r"\blooking forward to\b", "so excited for"),
        (r"\bthank you for your time\b", "thanks so much for your time"),
        (r"\bI look forward to hearing\b", "can't wait to hear"),
        (r"\bvery interested\b", "so excited"),
    ],
    "direct": [
        (r"\bI was wondering if\b", "could you"),
        (r"\bwould it be possible for you to\b", "please"),
        (r"\bI wanted to (?:just )?check in\b", "following up"),
        (r"\bI just wanted to\b", "I am"),
        (r"\bsorry to bother you,?\s*", ""),
        (r"\bplease let me know if (?:that|this) works\b", "please confirm"),
    ],
}

# Markers used by detect_tone. Each hit adds one point to that tone.
_MARKERS: dict[str, list[str]] = {
    "warm": [
        r"\bwarm regards\b", r"\bthanks so much\b", r"\breally appreciate\b",
        r"\bso grateful\b", r"\bhope you're doing well\b", r"\bglad\b",
        r"\blovely\b", r"\bso kind\b",
    ],
    "formal": [
        r"\bdear\b", r"\bsincerely\b", r"\brespectfully\b",
        r"\byours truly\b", r"\bdo not hesitate\b", r"\bplease advise\b",
        r"\bI look forward to\b",
    ],
    "concise": [],
    "enthusiastic": [
        r"!", r"\bexcited\b", r"\bcan't wait\b", r"\bthrilled\b",
        r"\bloves?\b", r"\bloved\b", r"\bfired up\b", r"\bamazing\b",
        r"\bawesome\b",
    ],
    "direct": [
        r"\bcould you\b", r"\bplease send\b", r"\bplease share\b",
        r"\bplease confirm\b", r"\bplease review\b", r"\bplease forward\b",
        r"\blet me know by\b", r"\bkindly\b", r"\bno later than\b",
        r"\basap\b", r"\beod\b",
    ],
}

# Hedgy phrasing subtracts from the direct score.
_HEDGES = [
    r"\bi was wondering if\b", r"\bjust wanted to\b",
    r"\bsorry to bother\b", r"\bperhaps\b", r"\bmaybe\b",
    r"\bwould it be possible\b",
]

# Contraction pairs for match_voice, applied in one direction only.
_CONTRACT = [
    (r"\bdo not\b", "don't"), (r"\bdoes not\b", "doesn't"),
    (r"\bdid not\b", "didn't"), (r"\bcannot\b", "can't"),
    (r"\bwill not\b", "won't"), (r"\bwould not\b", "wouldn't"),
    (r"\bshould not\b", "shouldn't"), (r"\bcould not\b", "couldn't"),
    (r"\bis not\b", "isn't"), (r"\bare not\b", "aren't"),
    (r"\bwas not\b", "wasn't"), (r"\bwere not\b", "weren't"),
    (r"\bhave not\b", "haven't"), (r"\bhas not\b", "hasn't"),
    (r"\bI am\b", "I'm"), (r"\byou are\b", "you're"),
    (r"\bwe are\b", "we're"), (r"\bit is\b", "it's"),
    (r"\bI will\b", "I'll"), (r"\bwe will\b", "we'll"),
]
_EXPAND = [(new, old) for old, new in _CONTRACT]

_CONTRACTION_RE = re.compile(r"\b\w+n't\b|\b\w+'(ll|re|ve|d|m)\b", re.IGNORECASE)
_SENT_END_RE = re.compile(r"(?<=[.!?])\s+")


def list_tones() -> list[str]:
    """Return the supported tone names."""
    return list(TONES)


def _require_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value


def _normalize_dashes(text: str) -> str:
    return text.replace("\u2014", "-").replace("\u2013", "-")


def _words(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", sentence)


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_END_RE.split(text) if s.strip()]


def _avg_sentence_len(text: str) -> float:
    sents = _sentences(text)
    if not sents:
        return 0.0
    return sum(len(_words(s)) for s in sents) / len(sents)


def _swap(text: str, pattern: str, replacement: str) -> str:
    """Case-insensitive regex swap that re-capitalizes to fit its slot."""
    def fix(match: re.Match[str]) -> str:
        original = match.group(0)
        rep = replacement
        if not rep:
            return rep
        if original[0].isupper() and not rep[0].isupper():
            return rep[0].upper() + rep[1:]
        if not original[0].isupper() and rep[0].isupper():
            before = text[:match.start()].rstrip(" \t")
            prev = before[-1] if before else ""
            if prev and prev not in ".!?\n":
                return rep[0].lower() + rep[1:]
        return rep
    return re.sub(pattern, fix, text, flags=re.IGNORECASE)


def _apply_swaps(text: str, pairs: list[tuple[str, str]]) -> str:
    for pattern, replacement in pairs:
        text = _swap(text, pattern, replacement)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _retune_greeting(text: str, new_word: str, bang: bool = False) -> str:
    lines = text.split("\n")
    checked = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        checked += 1
        if checked > 6:
            break
        match = _GREETING_RE.match(line.strip())
        if match:
            rest = match.group(2)
            if bang and rest.rstrip().endswith(","):
                rest = rest.rstrip()[:-1] + "!"
            lines[i] = line.replace(match.group(0), new_word + rest, 1)
            break
    return "\n".join(lines)


def _retune_signoff(text: str, new_closer: str) -> str:
    lines = text.split("\n")
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    for i in reversed(nonempty[-5:]):
        if _SIGNOFF_RE.match(lines[i].strip()):
            lines[i] = new_closer
            break
    return "\n".join(lines)


def _looks_like_header(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if stripped.lower().startswith("subject:"):
        return True
    if _GREETING_RE.match(stripped):
        return True
    if _SIGNOFF_RE.match(stripped):
        return True
    return False


def _split_long_sentences(text: str, target: float) -> str:
    """Split sentences much longer than target at a middle comma or 'and'."""
    out_paragraphs = []
    for para in text.split("\n\n"):
        if "\n" in para or _looks_like_header(para):
            out_paragraphs.append(para)
            continue
        new_sentences: list[str] = []
        for sent in _sentences(para):
            words = _words(sent)
            if len(words) <= max(12, target * 1.6):
                new_sentences.append(sent)
                continue
            split_at = _middle_split_point(sent, len(words))
            if split_at is None:
                new_sentences.append(sent)
                continue
            first = sent[:split_at].rstrip(" ,").rstrip()
            second = sent[split_at:].lstrip(" ,").lstrip()
            if not first.endswith((".", "!", "?")):
                first += "."
            if second:
                second = second[0].upper() + second[1:]
            new_sentences.extend([first, second] if second else [first])
        out_paragraphs.append(" ".join(new_sentences))
    return "\n\n".join(out_paragraphs)


def _middle_split_point(sentence: str, n_words: int) -> int | None:
    best: int | None = None
    best_dist = float("inf")
    for match in re.finditer(r",| and | but | or ", sentence):
        word_offset = len(_words(sentence[:match.start()]))
        if word_offset < 3 or word_offset > n_words - 3:
            continue
        dist = abs(word_offset - n_words / 2)
        if dist < best_dist:
            best_dist = dist
            best = match.start() if match.group(0) == "," else match.start() + 1
    return best


def _join_short_sentences(text: str, max_each: int) -> str:
    """Join adjacent short sentences with a semicolon (one pass)."""
    out_paragraphs = []
    for para in text.split("\n\n"):
        stripped = para.strip()
        if "\n" in para or _looks_like_header(para):
            out_paragraphs.append(para)
            continue
        sents = _sentences(stripped)
        merged: list[str] = []
        i = 0
        while i < len(sents):
            current = sents[i]
            nxt = sents[i + 1] if i + 1 < len(sents) else None
            if (
                nxt is not None
                and len(_words(current)) <= max_each
                and len(_words(nxt)) <= max_each
                and not current.rstrip().endswith("?")
                and not nxt.lstrip().startswith("I ")
            ):
                first = current.rstrip().rstrip(".!?")
                second = nxt.lstrip()
                second = second[0].lower() + second[1:] if second else second
                merged.append(first + "; " + second)
                i += 2
            else:
                merged.append(current)
                i += 1
        out_paragraphs.append(" ".join(merged))
    return "\n\n".join(out_paragraphs)


def tune(draft: str, tone: str) -> str:
    """Apply a light stylistic pass to a draft for the given tone.

    Only the greeting, the sign-off, and the tone's curated phrase map
    are changed; for "concise", short adjacent sentences are also joined
    and pleasantry openers dropped. Names, dates, numbers, and everything
    else pass through untouched.
    """
    _require_text(draft, "draft")
    if tone not in TONES:
        raise ValueError(f"Unknown tone '{tone}'. Choose from {TONES}.")
    text = _normalize_dashes(draft)
    text = _retune_greeting(
        text, _GREETING_BY_TONE[tone], bang=(tone == "enthusiastic")
    )
    text = _retune_signoff(text, _CLOSER_BY_TONE[tone])
    text = _apply_swaps(text, _SWAPS[tone])
    if tone == "concise":
        text = _join_short_sentences(text, max_each=8)
    return text


def _voice_stats(sample: str) -> dict:
    greeting = ""
    for line in sample.split("\n"):
        if not line.strip():
            continue
        match = _GREETING_RE.match(line.strip())
        if match:
            greeting = match.group(1)
            break
    signoff = ""
    nonempty = [line for line in sample.split("\n") if line.strip()]
    for line in reversed(nonempty[-5:]):
        if _SIGNOFF_RE.match(line.strip()):
            signoff = line.strip()
            break
    words = _words(sample)
    contractions = len(_CONTRACTION_RE.findall(sample))
    return {
        "greeting": greeting,
        "signoff": signoff,
        "avg_len": _avg_sentence_len(sample),
        "contraction_rate": contractions / len(words) if words else 0.0,
    }


def _match_contractions(text: str, sample_rate: float) -> str:
    words = _words(text)
    if not words:
        return text
    draft_rate = len(_CONTRACTION_RE.findall(text)) / len(words)
    if sample_rate > 0.03 and draft_rate < sample_rate:
        return _apply_swaps(text, _CONTRACT)
    if sample_rate == 0.0 and draft_rate > 0.0:
        return _apply_swaps(text, _EXPAND)
    return text


def _match_sentence_length(text: str, sample_avg: float) -> str:
    if sample_avg <= 0:
        return text
    draft_avg = _avg_sentence_len(text)
    if sample_avg < draft_avg - 4:
        return _split_long_sentences(text, sample_avg)
    if sample_avg > draft_avg + 4:
        return _join_short_sentences(text, max_each=max(6, int(sample_avg * 0.5)))
    return text


def match_voice(draft: str, sample: str) -> str:
    """Nudge a draft toward the voice of a sample text.

    Adopts the sample's greeting word and sign-off, moves contraction use
    toward the sample's (contracts if the sample uses them, expands if it
    avoids them), and splits or joins sentences toward the sample's
    average sentence length. Deterministic.

    Limitations: only simple stats are measured (greeting, sign-off,
    average sentence length, contraction rate), so vocabulary, rhythm, and
    subtler style are not captured. Sentence splitting/joining is a
    single heuristic pass and may not fully reach the sample's average.
    """
    _require_text(draft, "draft")
    _require_text(sample, "sample")
    stats = _voice_stats(_normalize_dashes(sample))
    text = _normalize_dashes(draft)
    if stats["greeting"]:
        text = _retune_greeting(text, stats["greeting"])
    if stats["signoff"]:
        text = _retune_signoff(text, stats["signoff"])
    text = _match_contractions(text, stats["contraction_rate"])
    text = _match_sentence_length(text, stats["avg_len"])
    return text


def detect_tone(text: str) -> str:
    """Best-guess classification of text into one of list_tones().

    Scores curated marker phrases per tone, penalizes hedgy phrasing for
    "direct", and gives "concise" a structural bonus for short average
    sentence length. Ties break in list_tones() order. This is a rough
    heuristic for display purposes, not a confident classifier.
    """
    _require_text(text, "text")
    lowered = text.lower()
    scores = {tone: 0 for tone in TONES}
    for tone, markers in _MARKERS.items():
        for marker in markers:
            scores[tone] += len(re.findall(marker, lowered))
    for hedge in _HEDGES:
        scores["direct"] -= len(re.findall(hedge, lowered))
    words = _words(text)
    avg = len(words) / len(_sentences(text)) if _sentences(text) else 0
    # Structural fallback: only when no tone markers matched at all does
    # short text read as concise. Otherwise marker evidence wins, so a
    # short formal or direct note is not mislabeled concise.
    if sum(scores.values()) == 0:
        if words and avg <= 12 and len(words) <= 80:
            scores["concise"] += 3
    elif avg >= 20:
        scores["concise"] -= 2
    return max(TONES, key=lambda tone: scores[tone])
