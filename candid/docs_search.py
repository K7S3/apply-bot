"""Full-text search over the offline docs bundle (stdlib only).

Build an inverted index over a {slug: markdown} mapping and rank results
with AND semantics. Importing this module never touches
``candid.docs_bundle``: the bundle is only imported lazily inside
:func:`load_bundle_topics`, so ``import candid.docs_search`` works even when
the bundle module (or its data) is absent.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PHRASE_RE = re.compile(r'"([^"]+)"')
_SNIPPET_WIDTH = 160


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def build_index(topics: dict[str, str]) -> dict:
    """Build an inverted index: token -> {slug: term frequency}.

    ``topics`` maps a slug to its markdown source. The returned index is a
    plain dict (``{"postings": ..., "docs": ...}``) that :func:`search`
    consumes; it also carries the raw doc text so snippets can be built.
    """
    postings: dict[str, dict[str, int]] = {}
    docs: dict[str, str] = {}
    for slug, markdown in topics.items():
        text = markdown or ""
        docs[slug] = text
        for token in _tokenize(text):
            bucket = postings.setdefault(token, {})
            bucket[slug] = bucket.get(slug, 0) + 1
    return {"postings": postings, "docs": docs}


def _parse_query(query: str) -> tuple[list[str], list[str]]:
    """Split a query into plain terms and quoted phrases."""
    query = query or ""
    phrases = [p.strip() for p in _PHRASE_RE.findall(query)]
    rest = _PHRASE_RE.sub(" ", query)
    return _tokenize(rest), [p for p in phrases if p]


def _snippet(text: str, terms: list[str], phrases: list[str],
             width: int = _SNIPPET_WIDTH) -> str:
    """~160-char snippet centered on the first query hit, with ellipsis."""
    lower = text.lower()
    positions = []
    for term in terms:
        i = lower.find(term)
        if i >= 0:
            positions.append(i)
    for phrase in phrases:
        i = lower.find(phrase.lower())
        if i >= 0:
            positions.append(i)
    flat = re.sub(r"\s+", " ", text).strip()
    if not positions:
        return flat[:width] + ("..." if len(flat) > width else "")
    first = min(positions)
    start = max(0, first - width // 2)
    end = min(len(text), start + width)
    chunk = re.sub(r"\s+", " ", text[start:end]).strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{chunk}{suffix}"


def search(query: str, index: dict, titles: dict[str, str] | None
           ) -> list[tuple[str, str, str]]:
    """Search the index; return [(slug, title, snippet)] ranked best first.

    Semantics:
    - AND across all terms and quoted phrases: a doc must contain every
      term and every phrase (phrases are matched literally, case-insensitively).
    - Ranking: docs whose title matches query terms/phrases come first,
      then by total term frequency in the body; ties break on slug for
      deterministic output.
    """
    terms, phrases = _parse_query(query)
    if not terms and not phrases:
        return []
    postings = index.get("postings", {})
    docs = index.get("docs", {})
    titles = titles or {}

    candidates: set[str] | None = None
    for term in terms:
        slugs = set(postings.get(term, {}))
        candidates = slugs if candidates is None else candidates & slugs
        if not candidates:
            return []
    if candidates is None:
        candidates = set(docs)

    lowered = {slug: docs[slug].lower() for slug in candidates if slug in docs}
    candidates &= set(lowered)
    for phrase in phrases:
        needle = phrase.lower()
        candidates = {s for s in candidates if needle in lowered[s]}
        if not candidates:
            return []

    scored = []
    for slug in candidates:
        body_hits = sum(postings.get(t, {}).get(slug, 0) for t in terms)
        body_hits += sum(lowered[slug].count(p.lower()) for p in phrases)
        title = titles.get(slug, slug)
        title_tokens = set(_tokenize(title))
        title_hits = sum(1 for t in terms if t in title_tokens)
        title_hits += sum(1 for p in phrases if p.lower() in title.lower())
        snippet = _snippet(docs[slug], terms, phrases)
        scored.append((slug, title, snippet, title_hits, body_hits))
    scored.sort(key=lambda r: (-r[3], -r[4], r[0]))
    return [(slug, title, snippet) for slug, title, snippet, _, _ in scored]


def load_bundle_topics() -> dict[str, str]:
    """Return the real docs bundle's {slug: markdown} mapping.

    The ``candid.docs_bundle`` import is deferred on purpose so this module
    stays importable (and testable with synthetic topics) when the bundle
    is not installed. Raises RuntimeError if the bundle exposes no topics.
    """
    from candid import docs_bundle  # noqa: PLC0415 - deferred import by design

    lister = getattr(docs_bundle, "list_topics", None)
    if callable(lister):
        getter = getattr(docs_bundle, "get_topic", None)
        if callable(getter):
            return {slug: getter(slug) for slug, _title in lister()}
    getter = getattr(docs_bundle, "get_topics", None)
    if callable(getter):
        return dict(getter())
    topics = getattr(docs_bundle, "TOPICS", None)
    if topics:
        return dict(topics)
    raise RuntimeError("candid.docs_bundle exposes no topics (looked for "
                       "list_topics()/get_topic(), get_topics() and TOPICS)")
