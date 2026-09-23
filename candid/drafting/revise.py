"""Deterministic draft revision.

``revise(draft, instruction)`` parses a plain-text instruction with keyword
matching (no LLM, no network) and applies a small set of composable rules to
an email draft ``{"subject": ..., "body": ...}``.

Recognised rules:
  - ``shorten``   -- drop lowest-information sentences past a target length
  - ``formalize`` -- expand contractions, upgrade greetings/signoffs
  - ``soften``    -- swap blunt phrasing for hedged alternatives
  - ``add_cta``   -- append a closing call-to-action question

Returns ``{"subject", "body", "applied"}`` where ``applied`` lists the rule
names that fired. Instructions that match no rule leave the draft unchanged.
"""

import re

# ---------------------------------------------------------------------------
# Instruction parsing
# ---------------------------------------------------------------------------

_RULE_KEYWORDS = {
    "shorten": ("shorter", "shorten", "concise", "brief", "trim",
                "cut it down", "tighter"),
    "formalize": ("formal", "professional", "polished"),
    "soften": ("softer", "soften", "gentle", "polite", "hedge",
               "less pushy", "less blunt"),
    "add_cta": ("call to action", "cta", "closing question",
                "ask for a call", "ask for a meeting", "clear next step"),
}


def _parse_rules(instruction):
    """Return the ordered list of rule names matched by *instruction*."""
    text = (instruction or "").lower()
    return [rule for rule, keywords in _RULE_KEYWORDS.items()
            if any(k in text for k in keywords)]


# ---------------------------------------------------------------------------
# Shared text helpers
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_STOPWORDS = frozenset("""
a an the and or but if then else when at by for with about into through
during before after above below to from up down in out on off over under
again further once here there all any both each few more most other some
such no nor not only own same so than too very can will just don do does
did is are was were be been being have has had having do does did
i you he she it we they me him her us them my your his its our their
this that these those am of as
""".split())

_FILLER_PATTERNS = (
    "hope you are doing well",
    "hope you're doing well",
    "just checking in",
    "just touching base",
    "touching base",
    "circling back",
    "bumping this",
)


def _split_sentences(paragraph):
    return [s for s in _SENTENCE_RE.split(paragraph.strip()) if s.strip()]


def _word_count(text):
    return len(text.split())


def _info_score(sentence):
    """Higher = more informative. Low scores mark filler droppable sentences."""
    words = re.findall(r"[a-zA-Z']+", sentence.lower())
    score = sum(1 for w in words if w not in _STOPWORDS)
    lowered = sentence.lower()
    if any(p in lowered for p in _FILLER_PATTERNS):
        score -= 3
    return score


# ---------------------------------------------------------------------------
# Rule: shorten
# ---------------------------------------------------------------------------

SHORTEN_TARGET_WORDS = 80


def _shorten(body, target=SHORTEN_TARGET_WORDS):
    """Drop lowest-information sentences until *body* fits *target* words.

    The first and last sentences are never dropped (they usually hold the
    greeting and the signoff/closing).
    """
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    if not paragraphs:
        return body

    # Work on a flat sentence list; remember which paragraph each came from.
    indexed = []
    for pidx, para in enumerate(paragraphs):
        for s in _split_sentences(para):
            indexed.append((pidx, s))

    total = sum(_word_count(s) for _, s in indexed)
    if total <= target or len(indexed) <= 2:
        return body

    drop_order = sorted(
        range(1, len(indexed) - 1),            # never first or last sentence
        key=lambda i: (_info_score(indexed[i][1]), i),
    )
    keep = set(range(len(indexed)))
    for i in drop_order:
        if total <= target:
            break
        total -= _word_count(indexed[i][1])
        keep.discard(i)

    kept_by_para = {}
    for i in sorted(keep):
        pidx, s = indexed[i]
        kept_by_para.setdefault(pidx, []).append(s)
    return "\n\n".join(" ".join(kept_by_para[p]) for p in sorted(kept_by_para))


# ---------------------------------------------------------------------------
# Rule: formalize
# ---------------------------------------------------------------------------

_CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "can't": "cannot", "won't": "will not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "wouldn't": "would not", "couldn't": "could not",
    "shouldn't": "should not", "mightn't": "might not",
    "i'm": "I am", "you're": "you are", "it's": "it is",
    "that's": "that is", "there's": "there is", "we're": "we are",
    "they're": "they are", "i'll": "I will", "we'll": "we will",
    "you'll": "you will", "i've": "I have", "we've": "we have",
    "you've": "you have", "let's": "let us",
}

_GREETING_UPGRADES = (
    (r"^Hey\b", "Hello"),
    (r"^Hi\b", "Dear"),
    (r"^Hiya\b", "Hello"),
)

_SIGNOFF_UPGRADES = (
    (r"(?m)^Cheers,$", "Best regards,"),
    (r"(?m)^Thanks,$", "Thank you,"),
    (r"(?m)^Thanks!$", "Thank you."),
)


def _formalize(body):
    def expand(match):
        word = match.group(0)
        expanded = _CONTRACTIONS[word.lower()]
        if word[0].isupper():
            expanded = expanded[0].upper() + expanded[1:]
        return expanded

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(c) for c in _CONTRACTIONS) + r")\b",
        re.IGNORECASE,
    )
    body = pattern.sub(expand, body)
    for pat, repl in _GREETING_UPGRADES:
        body = re.sub(pat, repl, body)
    for pat, repl in _SIGNOFF_UPGRADES:
        body = re.sub(pat, repl, body)
    return body


# ---------------------------------------------------------------------------
# Rule: soften
# ---------------------------------------------------------------------------

_SOFTENINGS = (
    (r"\bI want to\b", "I would like to"),
    (r"\bI want\b", "I would like"),
    (r"\bI need\b", "I would appreciate"),
    (r"\bWe need\b", "We would appreciate"),
    (r"\byou need to\b", "it would be helpful if you could"),
    (r"\bASAP\b", "at your earliest convenience"),
    (r"\burgent\b", "time-sensitive"),
)


def _soften(body):
    for pat, repl in _SOFTENINGS:
        body = re.sub(pat, repl, body)
    return body


# ---------------------------------------------------------------------------
# Rule: add_cta
# ---------------------------------------------------------------------------

_CTA = ("Would you be available for a brief call next week "
        "to discuss further?")

_SIGNOFF_RE = re.compile(
    r"^(best|regards|thank you|thanks|sincerely|cheers|"
    r"warm regards|kind regards)[,\s]",
    re.IGNORECASE,
)


def _add_cta(body):
    stripped = body.rstrip()
    if "?" in stripped:
        return body  # a question (call to action) already exists
    lines = stripped.split("\n")
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if _SIGNOFF_RE.match(line.strip()):
            insert_at = i
            break
    lines.insert(insert_at, _CTA)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_RULE_FUNCS = {
    "shorten": _shorten,
    "formalize": _formalize,
    "soften": _soften,
    "add_cta": _add_cta,
}


def revise(draft, instruction):
    """Revise a draft per a plain-text instruction.

    Args:
        draft: dict with ``subject`` and ``body`` strings.
        instruction: plain-text revision instruction, e.g.
            "make it shorter and more formal".

    Returns:
        dict with ``subject``, ``body``, and ``applied`` (list of rule
        names). The subject is never modified. An instruction matching no
        rule returns the draft unchanged with an empty ``applied`` list.
    """
    rules = _parse_rules(instruction)
    subject = draft.get("subject", "")
    body = draft.get("body", "")
    applied = []
    for rule in rules:
        body = _RULE_FUNCS[rule](body)
        applied.append(rule)
    return {"subject": subject, "body": body, "applied": applied}
