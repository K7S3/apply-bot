"""Docs-bundle consistency checks (stdlib only).

Checks, without ever raising on missing files:

1. every command in ``commands`` has a ``commands/<cmd>.md`` page;
2. every markdown ``[text](target)`` relative link target exists;
3. every top-level ``*.md`` topic file is linked from ``index.md``.

Returns a list of human-readable problem strings; empty when clean.
"""

from __future__ import annotations

import re
from pathlib import Path

# [text](target) but not ![alt](src); captures the target, tolerates a
# trailing "title".
_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _is_external(target: str) -> bool:
    """True for absolute URLs, absolute paths, and pure #anchors."""
    return (not target) or target.startswith(("#", "/")) or bool(_SCHEME_RE.match(target))


def _clean_target(raw: str) -> str:
    """Strip fragments, query strings, and surrounding whitespace."""
    return raw.split("#", 1)[0].split("?", 1)[0].strip()


def _iter_markdown(docs_dir: Path) -> list[Path]:
    try:
        return sorted(docs_dir.rglob("*.md"))
    except OSError:
        return []


def _check_command_pages(commands: list[str], docs_dir: Path) -> list[str]:
    problems = []
    for cmd in commands:
        page = docs_dir / "commands" / f"{cmd}.md"
        try:
            if not page.is_file():
                problems.append(f"missing command page: commands/{cmd}.md")
        except OSError:
            problems.append(f"missing command page: commands/{cmd}.md")
    return problems


def _check_links(md_files: list[Path], docs_dir: Path) -> list[str]:
    problems = []
    for md in md_files:
        try:
            rel = md.relative_to(docs_dir)
        except ValueError:
            rel = md
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            problems.append(f"unreadable markdown file: {rel}")
            continue
        for raw_target in _LINK_RE.findall(text):
            target = _clean_target(raw_target)
            if _is_external(target):
                continue
            try:
                if not (md.parent / target).exists():
                    problems.append(f"broken link in {rel}: [{target}]")
            except OSError:
                problems.append(f"broken link in {rel}: [{target}]")
    return problems


def _check_index_listing(docs_dir: Path) -> list[str]:
    index = docs_dir / "index.md"
    try:
        topic_files = sorted(
            p for p in docs_dir.glob("*.md") if p.name != "index.md"
        )
    except OSError:
        return []
    if not index.is_file():
        if topic_files:
            return ["index.md missing: cannot verify topic listing"]
        return []
    try:
        index_text = index.read_text(encoding="utf-8")
    except OSError:
        return ["unreadable file: index.md"]
    listed = set()
    for raw_target in _LINK_RE.findall(index_text):
        target = _clean_target(raw_target)
        if _is_external(target):
            continue
        try:
            listed.add((index.parent / target).name)
        except OSError:
            continue
    return [
        f"topic not listed in index.md: {p.name}"
        for p in topic_files
        if p.name not in listed
    ]


def check_docs(commands: list[str], docs_dir: Path) -> list[str]:
    """Run all consistency checks; never raises on missing files."""
    docs_dir = Path(docs_dir)
    try:
        if not docs_dir.is_dir():
            return [f"docs directory not found: {docs_dir}"]
    except OSError:
        return [f"docs directory not accessible: {docs_dir}"]
    problems: list[str] = []
    problems.extend(_check_command_pages(commands, docs_dir))
    md_files = _iter_markdown(docs_dir)
    problems.extend(_check_links(md_files, docs_dir))
    problems.extend(_check_index_listing(docs_dir))
    return problems
