"""Lab/PI watchlist for the academic job hunt.

A user-managed watchlist of labs, PIs, and fellowships. ``labs check`` scans
the latest curated jobs (``candid_data/jobs.json``, read defensively since the
sibling academic-feeds worker is still building it) plus any text files passed
via ``--text``, and reports hits with context snippets.

Matching is case-insensitive and *word-aware*: a watched name "Lab" will NOT
match "collaborate" (no false positives on substrings buried inside larger
words). Multi-word names tolerate any whitespace between their words.

Everything is stored locally in ``candid_data/watched_labs.json``.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from candid import config as C


class LabsError(Exception):
    """Raised for watchlist failures."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _watchlist_path() -> Path:
    return C.DATA_DIR / "watched_labs.json"


def _load_watchlist() -> list[dict]:
    p = _watchlist_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_watchlist(entries: list[dict]) -> None:
    C.ensure_data_dirs()
    _watchlist_path().write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _norm(name: str) -> str:
    return " ".join(name.strip().split())


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def add_lab(name: str, affiliation: str = "") -> dict:
    """Add a watched lab/PI. Returns the stored entry."""
    name = _norm(name)
    if not name:
        raise LabsError("Lab/PI name cannot be empty.")
    entries = _load_watchlist()
    for e in entries:
        if e.get("name", "").lower() == name.lower():
            raise LabsError(f'"{name}" is already on your watchlist.')
    entry = {
        "name": name,
        "affiliation": _norm(affiliation),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries.append(entry)
    _save_watchlist(entries)
    return entry


def list_labs() -> list[dict]:
    """Return all watched labs/PIs."""
    return _load_watchlist()


def remove_lab(name: str) -> dict:
    """Remove a watched lab/PI (case-insensitive). Returns the removed entry."""
    name = _norm(name)
    entries = _load_watchlist()
    for e in entries:
        if e.get("name", "").lower() == name.lower():
            entries.remove(e)
            _save_watchlist(entries)
            return e
    raise LabsError(f'"{name}" is not on your watchlist.')


# ---------------------------------------------------------------------------
# word-aware matching
# ---------------------------------------------------------------------------

def _word_aware_pattern(name: str) -> re.Pattern:
    """Case-insensitive regex for ``name`` that never matches inside a word.

    "Lab" matches "the AI Lab" but not "collaborate". Multi-word names allow
    any whitespace between words (so line-wrapped text still matches).
    """
    parts = [re.escape(w) for w in name.lower().split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


#: Fields scanned on a job dict, in priority order.
_SCAN_FIELDS = (
    "title", "company", "description",
    "lab", "lab_name", "fellowship", "fellowship_name", "sponsor",
)


def _snippet(text: str, match: re.Match, radius: int = 60) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    frag = re.sub(r"\s+", " ", text[start:end]).strip()
    if start > 0:
        frag = "..." + frag
    if end < len(text):
        frag = frag + "..."
    return frag


def check_labs(jobs: list[dict]) -> list[dict]:
    """Scan job dicts against the watchlist; return hits with context.

    Each job is scanned over title, company, description, plus any
    lab/fellowship-flavored fields. A hit is
    {lab, affiliation, matched_field, snippet, job_title, company, location, url}.
    """
    watchlist = _load_watchlist()
    if not watchlist:
        return []
    patterns = [(e, _word_aware_pattern(e["name"])) for e in watchlist]
    hits = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        for entry, pat in patterns:
            for field in _SCAN_FIELDS:
                text = str(job.get(field) or "")
                if not text:
                    continue
                m = pat.search(text)
                if m:
                    hits.append({
                        "lab": entry["name"],
                        "affiliation": entry.get("affiliation", ""),
                        "matched_field": field,
                        "snippet": _snippet(text, m),
                        "job_title": str(job.get("title") or ""),
                        "company": str(job.get("company") or ""),
                        "location": str(job.get("location") or ""),
                        "url": str(job.get("url") or job.get("jd_link") or ""),
                    })
                    break  # one hit per (job, watched name)
    return hits


# ---------------------------------------------------------------------------
# curated-jobs loading (defensive: the sibling feeds worker is still building)
# ---------------------------------------------------------------------------

#: Keys that might hold a list of full job dicts inside jobs.json.
_JOB_LIST_KEYS = (
    "jobs", "curated", "results", "listings", "items",
    "postings", "candidates", "added", "academic_jobs",
)


def load_curated_jobs() -> list[dict]:
    """Load the latest curated jobs from DATA_DIR/jobs.json defensively.

    Handles: file missing, invalid JSON, top-level list, or a dict with job
    lists under any of several plausible keys. Returns [] when nothing usable
    is found — callers must treat "no jobs" as "nothing to scan", not an error.
    """
    p = C.DATA_DIR / "jobs.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [j for j in data if isinstance(j, dict)]
    if isinstance(data, dict):
        for key in _JOB_LIST_KEYS:
            val = data.get(key)
            if isinstance(val, list) and val and all(isinstance(j, dict) for j in val):
                return val
    return []


def check_text_files(paths: list[str]) -> list[dict]:
    """Scan plain-text files (CFP emails, forwarded ads) against the watchlist."""
    docs = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.is_file():
            raise LabsError(f"Text file not found: {raw}")
        docs.append({
            "title": p.name,
            "company": "",
            "description": p.read_text(encoding="utf-8", errors="replace"),
            "url": str(p),
        })
    return check_labs(docs)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_watchlist(entries: list[dict]) -> str:
    if not entries:
        return ("Your lab/PI watchlist is empty.\n"
                'Next: python -m candid labs add "Geoffrey Hinton" --affiliation "U Toronto"')
    lines = [f"Watched labs/PIs ({len(entries)}):"]
    for e in entries:
        aff = f" — {e['affiliation']}" if e.get("affiliation") else ""
        lines.append(f"  - {e['name']}{aff}")
    return "\n".join(lines)


def render_hits(hits: list[dict]) -> str:
    if not hits:
        return "No watchlist hits in the scanned jobs."
    lines = [f"{len(hits)} watchlist hit(s):"]
    for h in hits:
        aff = f" ({h['affiliation']})" if h["affiliation"] else ""
        title = h["job_title"] or "(untitled)"
        comp = f" @ {h['company']}" if h["company"] else ""
        lines.append(f"\n  [{h['lab']}{aff}] {title}{comp}")
        lines.append(f"  matched in {h['matched_field']}: {h['snippet']}")
        if h["url"]:
            lines.append(f"  {h['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_parsers(subparsers) -> None:
    """Wire the ``labs`` command tree. Called by the coordinator."""
    p = subparsers.add_parser(
        "labs", help="Watchlist of labs/PIs/fellowships; scan curated jobs for them.")
    sub = p.add_subparsers(dest="what", required=True, metavar="<subcommand>")

    pa = sub.add_parser("add", help="Add a lab/PI to the watchlist.")
    pa.add_argument("name", help='Lab/PI/fellowship name, e.g. "Geoffrey Hinton"')
    pa.add_argument("--affiliation", default="", help="e.g. \"U Toronto\"")
    pa.set_defaults(_labs_cmd="add")

    sub.add_parser("list", help="Show the watchlist.").set_defaults(_labs_cmd="list")

    pr = sub.add_parser("remove", help="Remove a lab/PI from the watchlist.")
    pr.add_argument("name", help="Name to remove (case-insensitive).")
    pr.set_defaults(_labs_cmd="remove")

    pc = sub.add_parser("check", help="Scan curated jobs for watched labs/PIs.")
    pc.add_argument("--text", nargs="*", default=[],
                    help="Extra text files to scan (forwarded ads, CFP emails).")
    pc.set_defaults(_labs_cmd="check")
    p.set_defaults(func=cmd_labs)


def cmd_labs(a) -> None:
    """CLI dispatch for the ``labs`` command tree."""
    what = getattr(a, "_labs_cmd", None)
    if what == "add":
        entry = add_lab(a.name, getattr(a, "affiliation", ""))
        print(f'Watching "{entry["name"]}"'
              + (f" ({entry['affiliation']})" if entry["affiliation"] else "")
              + ".")
    elif what == "list":
        print(render_watchlist(list_labs()))
    elif what == "remove":
        entry = remove_lab(a.name)
        print(f'Removed "{entry["name"]}" from the watchlist.')
    elif what == "check":
        watchlist = list_labs()
        if not watchlist:
            print(render_watchlist([]))
            return
        jobs = load_curated_jobs()
        hits = check_labs(jobs)
        extra = getattr(a, "text", None) or []
        if extra:
            hits = hits + check_text_files(extra)
        notes = []
        if not (C.DATA_DIR / "jobs.json").exists():
            notes.append("(no curated jobs yet: jobs.json missing — "
                         "run `jobs curate` first)")
        print(render_hits(hits))
        if notes:
            print("\n" + "\n".join(notes))
    else:
        raise LabsError(f"Unknown labs subcommand: {what}")
