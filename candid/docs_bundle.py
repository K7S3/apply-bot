"""Offline docs bundle for candid.

All documentation lives in ``candid/data/docs/`` as plain Markdown files that
ship with the package, so it works with zero network access. The content
describes the real CLI commands and flags (see ``candid/__main__.py``).

Stdlib only — no dependencies added here.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Directory holding the bundled Markdown docs plus the VERSION file.
DOCS_DIR = Path(__file__).resolve().parent / "data" / "docs"

#: Files in DOCS_DIR that are not topic pages (excluded from list_topics).
_NON_TOPIC_FILES = {"index.md"}


class DocsError(Exception):
    """Raised when a docs topic is unknown or the docs bundle is broken."""


def _topic_files() -> list[Path]:
    return sorted(
        p
        for p in DOCS_DIR.glob("*.md")
        if p.name not in _NON_TOPIC_FILES
    )


def _title_of(path: Path) -> str:
    """Title from the first ``# `` heading; falls back to the filename."""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def list_topics() -> list[tuple[str, str]]:
    """Return ``(slug, title)`` pairs for every topic page, sorted by slug."""
    return [(p.stem, _title_of(p)) for p in _topic_files()]


def get_topic(slug: str) -> str:
    """Return the Markdown text of one topic page.

    Raises:
        DocsError: if ``slug`` does not name a bundled topic page.
    """
    candidate = (DOCS_DIR / f"{slug}.md").resolve()
    if candidate.parent != DOCS_DIR.resolve() or not candidate.is_file():
        known = ", ".join(s for s, _ in list_topics())
        raise DocsError(f"Unknown docs topic {slug!r}. Known topics: {known}")
    return candidate.read_text(encoding="utf-8")


def docs_version() -> str:
    """Return the docs bundle version from ``data/docs/VERSION``, stripped."""
    path = DOCS_DIR / "VERSION"
    if not path.is_file():
        raise DocsError("docs VERSION file is missing from the bundle")
    return path.read_text(encoding="utf-8").strip()


_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def render_text(md: str) -> str:
    """Minimal Markdown-to-plain-text: strip ``#``, ``*``, backticks.

    Link markup is removed but the link *text* is kept. Table separator
    rows and horizontal rules are dropped.
    """
    out: list[str] = []
    for line in md.splitlines():
        line = re.sub(r"^#{1,6}\s+", "", line)          # headings
        line = _IMAGE_RE.sub(r"\1", line)                # ![alt](url) -> alt
        line = _LINK_RE.sub(r"\1", line)                 # [text](url) -> text
        line = line.replace("`", "")                     # code spans
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)   # bold
        line = re.sub(r"__([^_]+)__", r"\1", line)       # bold alt
        line = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", line)  # italic
        line = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", line)     # italic alt
        line = re.sub(r"^>\s?", "", line)                # blockquote
        line = re.sub(r"^\s{0,3}([-*+]|\d+[.)])\s+", "", line)  # list markers
        out.append(line.rstrip())

    cleaned: list[str] = []
    for line in out:
        s = line.strip()
        # Drop table separator rows (| --- | --- |) and horizontal rules.
        if s and set(s) <= set("-*_|: "):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()
