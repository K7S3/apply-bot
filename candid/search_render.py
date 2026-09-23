"""Presentation helpers for the `search` CLI command (batch 69).

The search engine lives in :mod:`candid.search` (``search_advanced``,
``explain_query``, ``render_results``) and the query language in
:mod:`candid.query`. This module holds the extra output formats the CLI
needs: CSV / Markdown export and facet count breakdowns.

Facet rule (per the batch-69 spec): ``kind`` comes straight from the
result dicts and works for every doc. ``status`` / ``source`` /
``company`` are looked up from the tracker JSON by the application
result's ``ref`` (the application id); file docs (prep packs, tailored
files, debriefs) are counted under ``kind`` only, so they are skipped
for the other fields.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import candid.config as C

#: Columns used by the CSV and Markdown exports, in order.
EXPORT_COLUMNS = ("kind", "ref", "title", "score", "snippet")


def render_csv(results: list[dict]) -> str:
    """Render results as CSV with header kind,ref,title,score,snippet."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for r in results:
        writer.writerow([
            r.get("kind", ""),
            r.get("ref", ""),
            r.get("title", ""),
            f"{r.get('score', 0):.1f}",
            r.get("snippet", ""),
        ])
    return buf.getvalue().rstrip("\n")


def _md_cell(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text


def render_md(results: list[dict]) -> str:
    """Render results as a Markdown table."""
    header = "| " + " | ".join(EXPORT_COLUMNS) + " |"
    sep = "|" + "|".join(["---"] * len(EXPORT_COLUMNS)) + "|"
    lines = [header, sep]
    for r in results:
        lines.append("| " + " | ".join(
            _md_cell(r.get(col, "")) if col != "score"
            else f"{r.get('score', 0):.1f}"
            for col in EXPORT_COLUMNS
        ) + " |")
    return "\n".join(lines)


def _tracker_index(path: Path | None = None) -> dict[str, dict]:
    """Map tracker application id (as string) -> record."""
    p = Path(path) if path else C.TRACKER_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    return {str(rec.get("id", "")): rec for rec in data
            if isinstance(rec, dict)}


def facet_counts(results: list[dict], field: str,
                 tracker_path: Path | None = None) -> list[tuple[str, int]]:
    """Count results per facet value, sorted by count desc then value.

    *field* is one of ``status``, ``kind``, ``source``, ``company``.
    File docs only contribute to the ``kind`` facet; for the other
    fields only application docs are counted (values looked up from the
    tracker by result ``ref``). Application docs whose id is missing
    from the tracker, or that lack the field, count under ``"(unknown)"``.
    """
    index = _tracker_index(tracker_path) if field != "kind" else {}
    counts: dict[str, int] = {}
    for r in results:
        if field == "kind":
            value = r.get("kind") or "(unknown)"
        elif r.get("kind") == "application":
            rec = index.get(str(r.get("ref", "")))
            value = (rec or {}).get(field) or "(unknown)"
        else:
            continue  # file docs count under kind only
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def render_facet(field: str, counts: list[tuple[str, int]]) -> str:
    """Render a facet breakdown, e.g. ``By status:`` followed by counts."""
    lines = [f"By {field}:"]
    if not counts:
        lines.append("  (no results)")
    for value, n in counts:
        lines.append(f"  {value}: {n}")
    return "\n".join(lines)
