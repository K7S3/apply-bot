"""Company culture decoder: extract stated values and turn them into interview prep.

Two pieces:

1. Values extractor - ``extract_values()`` parses user-pasted company
   values/handbook text into structured items. It is extractive only: every
   item's ``quote`` is a verbatim substring of the input text, and empty
   input returns an empty list. Nothing is ever invented. ``save_values()``
   and ``load_values()`` persist extracted values under the data dir.

2. Values-to-questions - ``values_to_questions()`` instantiates behavioral
   interview-question templates with each value name. The returned
   questions are clearly labeled as generated in their ``source`` field;
   they are never presented as real asked questions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

# Numbered list item: "1. Foo", "1) Foo", "a. Foo", "(1) Foo".
_NUMBERED_RE = re.compile(r"^\s*(?:\(?[0-9]+\)?|[a-z])[\.\)]\s+(?P<body>.+)$")

# Bulleted list item: "- Foo", "* Foo", "• Foo".
_BULLETED_RE = re.compile(r"^\s*[-*•‣▪]\s+(?P<body>.+)$")

# Inline enumerations on a single line: "Our values: 1. Ownership 2. Trust".
# The body is non-greedy and stops at the next marker or end of line.
_INLINE_NUMBERED_RE = re.compile(
    r"(?:^|(?<=[\s:;(\"\']))\(?\d{1,2}[.)]\s+"
    r"(?P<body>.+?)(?=(?:\s+\(?\d{1,2}[.)]\s)|$)"
)

# Inline sentence declaring values, e.g. "Our values are A, B, and C."
_INLINE_VALUES_RE = re.compile(
    r"(?i)\b(?:our|the|company|core)\s+(?:values?|principles?|tenets?|beliefs?)\s+"
    r"(?:are|include)?\s*:?\s*(?P<rest>[^.?!]+)"
)

# Sentence-level declaration, e.g. "We value transparency."
_SENTENCE_RE = re.compile(
    r"(?i)\bwe\s+(?:value|believe\s+in|prize|champion)\s+(?P<name>[^.?!]+)"
)

# "Value: description" or "Value - description" separators inside list items.
_TITLE_SPLIT_RE = re.compile(r"\s*[:\-–]\s+")

_MAX_VALUE_LEN = 120
_MAX_VALUES = 50


def _slug(company: str) -> str:
    """Lowercase company name with non-alphanumeric runs replaced by underscores."""
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    return slug or "unknown"


def _values_dir() -> Path:
    """Directory that holds saved value files; created on demand."""
    path = config.DATA_DIR / "culture"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean_value_name(name: str) -> str:
    """Normalize a candidate value name: strip quotes, collapse whitespace, trim."""
    name = name.strip().strip("'\"").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > _MAX_VALUE_LEN:
        name = name[:_MAX_VALUE_LEN].rstrip() + "..."
    return name


def _item_to_entry(item: str, origin: str) -> dict | None:
    """Turn a raw list-item string into a value entry, or None if unusable."""
    item = item.strip()
    if not item:
        return None
    # "Customer obsession: we start with the customer..." -> name before colon/dash.
    parts = _TITLE_SPLIT_RE.split(item, maxsplit=1)
    if len(parts) == 2 and parts[0] and len(parts[0]) <= 60:
        name = _clean_value_name(parts[0])
    else:
        name = _clean_value_name(item)
    if not name:
        return None
    return {"value": name, "quote": item, "source": origin}


def _entries_from_items(items: list[str], origin: str) -> list[dict]:
    """Build deduplicated entries from candidate item strings."""
    seen: set[str] = set()
    entries: list[dict] = []
    for item in items:
        entry = _item_to_entry(item, origin)
        if entry is None:
            continue
        key = entry["value"].lower()
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
        if len(entries) >= _MAX_VALUES:
            break
    return entries


def _strip_leading_conjunction(text: str) -> str:
    """Drop a leading 'and' / 'as well as' from an inline value list item."""
    return re.sub(r"(?i)^(?:and|as well as)\s+", "", text).strip()


def _split_inline_names(rest: str) -> list[str]:
    """Split 'A, B, and C' style inline declarations into individual names."""
    names: list[str] = []
    for chunk in re.split(r";\s*|,\s*", rest):
        chunk = _strip_leading_conjunction(chunk)
        if chunk:
            names.append(_clean_value_name(chunk))
    return names


def _inline_numbered_entries(text: str, origin: str) -> list[dict]:
    """Entries from single-line "1. X 2. Y" style enumerations.

    Catches pasted values pages where numbered items share one line.
    Only fires when two or more markers appear on the same line, so a
    stray "1." mid-sentence cannot produce a bogus value. Each quote is
    the verbatim item text, a substring of the input.
    """
    items: list[str] = []
    for line in text.splitlines():
        bodies = [m.group("body").strip().rstrip(".!?")
                  for m in _INLINE_NUMBERED_RE.finditer(line)]
        bodies = [b for b in bodies if b]
        if len(bodies) >= 2:
            items.extend(bodies)
    if not items:
        return []
    return _entries_from_items(items, origin)


def _inline_entries(text: str, origin: str) -> list[dict]:
    """Entries from 'Our values are X, Y, and Z' style sentences."""
    entries: list[dict] = []
    for match in _INLINE_VALUES_RE.finditer(text):
        sentence = match.group(0).strip()
        for name in _split_inline_names(match.group("rest")):
            entries.append({"value": name, "quote": sentence, "source": origin})
    return entries


def _sentence_entries(text: str, origin: str) -> list[dict]:
    """Entries from 'We value X' style sentences."""
    entries: list[dict] = []
    for match in _SENTENCE_RE.finditer(text):
        name = _clean_value_name(match.group("name"))
        if not name:
            continue
        # Quote the full sentence: find the sentence the match belongs to.
        start = text.rfind(".", 0, match.start()) + 1
        end = match.end()
        while end < len(text) and text[end] not in ".?!":
            end += 1
        end = min(end + 1, len(text))
        sentence = text[start:end].strip()
        entries.append({"value": name, "quote": sentence, "source": origin})
    return entries


def _dedupe(entries: list[dict]) -> list[dict]:
    """Remove entries with duplicate value names (case-insensitive), keep first."""
    seen: set[str] = set()
    kept: list[dict] = []
    for entry in entries:
        key = entry["value"].lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
        if len(kept) >= _MAX_VALUES:
            break
    return kept


def extract_values(text: str, company: str, origin: str = "user-provided text") -> list[dict]:
    """Extract company values from pasted values/handbook text.

    Heuristics, in priority order:

    1. Numbered or bulleted list items (each item becomes a value).
    2. Inline declarations like "Our values are X, Y, and Z."
    3. Sentence declarations like "We value transparency."
    4. Single-line enumerations like "Our values: 1. X 2. Y" (fallback).

    Extractive only: every returned ``quote`` is a verbatim substring of
    ``text``. ``origin`` labels where the text came from and is stored in
    each item's ``source`` field. Empty or blank ``text`` returns [].
    ``company`` is accepted for API symmetry with save/load but does not
    affect extraction.
    """
    if not text or not text.strip():
        return []
    _ = company  # accepted for API symmetry; not used in extraction.

    list_items: list[str] = []
    for line in text.splitlines():
        match = _NUMBERED_RE.match(line) or _BULLETED_RE.match(line)
        if match:
            list_items.append(match.group("body").strip())

    if list_items:
        return _entries_from_items(list_items, origin)

    entries = _inline_entries(text, origin) + _sentence_entries(text, origin)
    if not entries:
        entries = _inline_numbered_entries(text, origin)
    return _dedupe(entries)


def values_file(company: str) -> Path:
    """Path of the saved values file for a company (not created as a side effect)."""
    return config.DATA_DIR / "culture" / f"values_{_slug(company)}.json"


def save_values(company: str, values: list[dict]) -> Path:
    """Save extracted values to the data dir; returns the file path written."""
    path = values_file(company)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"company": company, "values": list(values)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def load_values(company: str) -> list[dict]:
    """Load saved values for a company; returns [] if none were saved."""
    path = values_file(company)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("values", [])
    return values if isinstance(values, list) else []


# Behavioral templates instantiated with each value name. Every question is
# labeled as generated; none claim to be real asked questions.
_QUESTION_TEMPLATES = (
    "Tell me about a time you demonstrated {value} at work.",
    "Give an example of a situation where {value} guided a hard decision you made.",
    "How does {value} show up in your day-to-day work?",
    "Describe a challenge you faced that tested your commitment to {value}.",
    "Why does {value} matter to you personally, and how do you practice it?",
)


def values_to_questions(values: list) -> list[dict]:
    """Generate labeled behavioral questions from extracted company values.

    Each input may be a dict with a ``value`` key (as returned by
    ``extract_values()``) or a plain string. Templates rotate across the
    values so questions vary. Every output carries ``targets_value`` and a
    ``source`` field marked as generated, never as a real asked question.
    """
    questions: list[dict] = []
    for index, item in enumerate(values):
        value = item["value"] if isinstance(item, dict) else item
        value = str(value).strip()
        if not value:
            continue
        template = _QUESTION_TEMPLATES[index % len(_QUESTION_TEMPLATES)]
        questions.append({
            "question": template.format(value=value),
            "targets_value": value,
            "source": f"generated from company value '{value}'",
        })
    return questions
