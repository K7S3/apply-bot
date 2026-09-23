"""Full-text search across candid's job-search data.

Searches tracker applications (company, role, notes, jd_link, jd_text),
interview prep pack markdown files, tailored resume/cover-letter files,
and a ``debriefs`` data dir if one exists (skipped silently if missing).

Multi-term queries use AND semantics (all terms must match) and are
case-insensitive. Quoted phrases (e.g. ``"machine learning"``) count as
a single term.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config as C

KINDS = ("application", "prep_pack", "tailored", "debrief")
_SNIPPET_LEN = 160


class SearchError(Exception):
    """Raised when the search data cannot be read."""


def _parse_terms(query: str) -> list[str]:
    """Split a query into terms; quoted phrases stay together.

    >>> _parse_terms('python "machine learning"')
    ['python', 'machine learning']
    """
    terms: list[str] = []
    for m in re.finditer(r'"([^"]+)"|(\S+)', query):
        term = m.group(1) if m.group(1) is not None else m.group(2)
        term = term.strip().lower()
        if term:
            terms.append(term)
    return terms


def _count(haystack: str, term: str) -> int:
    return haystack.lower().count(term)


def _snippet(body: str, terms: list[str]) -> str:
    """~160-char context around the first term hit, with ... ellision."""
    lowered = body.lower()
    positions = [(lowered.find(t), t) for t in terms]
    positions = [(p, t) for p, t in positions if p >= 0]
    if not positions:
        text = body.strip()
        return (text[:_SNIPPET_LEN] + "...") if len(text) > _SNIPPET_LEN else text
    pos, _ = min(positions)
    half = _SNIPPET_LEN // 2
    start = max(0, pos - half)
    end = min(len(body), start + _SNIPPET_LEN)
    if end == len(body):
        start = max(0, end - _SNIPPET_LEN)
    chunk = body[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(body) else ""
    return f"{prefix}{chunk}{suffix}"


def _doc(kind: str, ref: str, title: str, body: str,
         terms: list[str]) -> dict | None:
    """Build a result dict if all terms match; None otherwise."""
    title_l = title.lower()
    body_l = body.lower()
    title_freq = sum(_count(title_l, t) for t in terms)
    body_freq = sum(_count(body_l, t) for t in terms)
    if not all(_count(title_l, t) + _count(body_l, t) > 0 for t in terms):
        return None  # AND semantics: every term must match somewhere
    score = (1000.0 if title_freq > 0 else 0.0) + title_freq * 10 + body_freq
    return {
        "kind": kind,
        "ref": ref,
        "title": title,
        "snippet": _snippet(body if body.strip() else title, terms),
        "score": float(score),
    }


def _read_text(path: Path) -> str | None:
    """Read a file as text; None if it can't be read or decoded."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _md_title(path: Path, text: str) -> str:
    """First markdown heading as a human title; else the filename stem."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem


def _search_applications(terms: list[str], path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SearchError(
            f"Tracker file {path} is not valid JSON: {exc}. "
            "Fix or delete it, then run `python -m candid search <query>` again."
        ) from exc
    if not isinstance(data, list):
        raise SearchError(
            f"Tracker file {path} should contain a JSON list. "
            "Fix it, then run `python -m candid search <query>` again."
        )
    results: list[dict] = []
    for app in data:
        if not isinstance(app, dict):
            continue
        company = str(app.get("company", "") or "")
        role = str(app.get("role", "") or "")
        title = f"{role} @ {company}".strip(" @")
        body_parts = [
            str(app.get("notes", "") or ""),
            str(app.get("jd_link", "") or ""),
            str(app.get("jd_text", "") or ""),
            str(app.get("status", "") or ""),
        ]
        hit = _doc("application", str(app.get("id", "")), title,
                   "\n".join(body_parts), terms)
        if hit:
            results.append(hit)
    return results


def _search_dir(terms: list[str], directory: Path, kind: str) -> list[dict]:
    if not directory.exists() or not directory.is_dir():
        return []
    results: list[dict] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        text = _read_text(path)
        if text is None:
            continue
        title = _md_title(path, text) if path.suffix.lower() in (".md", ".txt") else path.stem
        hit = _doc(kind, path.name, title, text, terms)
        if hit:
            results.append(hit)
    return results


def _debriefs_dir(debriefs_dir: Path | str | None) -> Path:
    if debriefs_dir is not None:
        return Path(debriefs_dir)
    # Defensive: a sibling batch may add a debriefs dir later; skip if missing.
    return getattr(C, "DEBRIEFS_DIR", C.DATA_DIR / "debriefs")


def search_all(query: str, *, path: str | Path | None = None,
               prep_dir: str | Path | None = None,
               tailor_dir: str | Path | None = None,
               debriefs_dir: str | Path | None = None) -> list[dict]:
    """Search tracker, prep packs, tailored files, and debriefs.

    All query terms must match (AND), case-insensitively; quoted phrases
    count as one term. Results are ranked title-matches first, then by
    term frequency. Empty query or missing data dirs yield no results.
    """
    terms = _parse_terms(query or "")
    if not terms:
        return []
    results: list[dict] = []
    results += _search_applications(terms, Path(path) if path else C.TRACKER_PATH)
    results += _search_dir(terms, Path(prep_dir) if prep_dir else C.PREP_PACKS_DIR,
                           "prep_pack")
    results += _search_dir(terms, Path(tailor_dir) if tailor_dir else C.TAILOR_DIR,
                           "tailored")
    results += _search_dir(terms, _debriefs_dir(debriefs_dir), "debrief")
    results.sort(key=lambda r: (-r["score"], r["kind"], r["ref"]))
    return results


def render_results(results: list[dict], limit: int = 20) -> str:
    """Plain-text rendering: one header line per hit plus a snippet line."""
    if not results:
        return "No matches found."
    lines = [f"{len(results)} match(es):"]
    for r in results[:limit]:
        lines.append(f"[{r['kind']}] {r['title']} (ref: {r['ref']}, "
                     f"score: {r['score']:.1f})")
        lines.append(f"  {r['snippet']}")
    if len(results) > limit:
        lines.append(f"... and {len(results) - limit} more "
                     f"(use --limit N to see more)")
    return "\n".join(lines)
