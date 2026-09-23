"""Startup watchlist alerts.

Track a personal watchlist of startup names and get alerted when the
curated job feed (``candid_data/jobs.json``) contains a posting from one
of them:

    python -m candid startups watch add --name "Acme AI"
    python -m candid startups watch remove --name "Acme AI"
    python -m candid startups watch list
    python -m candid startups watch check [--json]

Matching is fuzzy: exact, substring, or close-enough names match, so
"Acme" finds "Acme AI Inc.". New alerts are appended to
``candid_data/startup_alerts.jsonl``; already-alerted matches are never
re-alerted. Expected failures raise ``StartupWatchError`` (clean errors,
no tracebacks). No network calls - the watch works purely off local data.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C


class StartupWatchError(Exception):
    """Raised for watchlist failures (expected, user-facing)."""


# --- storage -----------------------------------------------------------------

def _watch_path() -> Path:
    return C.DATA_DIR / "startup_watch.json"


def _alerts_path() -> Path:
    return C.DATA_DIR / "startup_alerts.jsonl"


def _jobs_state_path() -> Path:
    return C.DATA_DIR / "jobs.json"


def _load_watchlist() -> list[dict]:
    p = _watch_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StartupWatchError(f"Watchlist file {p} is not valid JSON: {exc}") from exc
    items = data.get("watching", []) if isinstance(data, dict) else []
    return [i for i in items if isinstance(i, dict) and i.get("name")]


def _save_watchlist(items: list[dict]) -> None:
    C.ensure_data_dirs()
    _watch_path().write_text(
        json.dumps({"watching": items}, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- watchlist CRUD ----------------------------------------------------------

def add(name: str) -> dict:
    """Add a startup name to the watchlist. Returns the entry."""
    name = (name or "").strip()
    if not name:
        raise StartupWatchError("Give a name to watch, e.g. --name \"Acme AI\".")
    items = _load_watchlist()
    for i in items:
        if _norm(i["name"]) == _norm(name):
            return {**i, "duplicate": True}
    entry = {"name": name, "added_at": _now_iso()}
    items.append(entry)
    _save_watchlist(items)
    return entry


def remove(name: str) -> dict:
    """Remove a startup name from the watchlist. Returns the removed entry."""
    name = (name or "").strip()
    if not name:
        raise StartupWatchError("Give a name to remove, e.g. --name \"Acme AI\".")
    items = _load_watchlist()
    for i in items:
        if _norm(i["name"]) == _norm(name):
            items.remove(i)
            _save_watchlist(items)
            return i
    raise StartupWatchError(
        f"{name!r} is not on the watchlist. Run `python -m candid startups watch list` to see it.")


def list_watched() -> list[dict]:
    """Return the watchlist entries in add order."""
    return _load_watchlist()


def render_list(items: list[dict]) -> str:
    if not items:
        return "Watchlist is empty. Add one with `python -m candid startups watch add --name \"Acme AI\"`."
    lines = [f"{len(items)} startup(s) watched:"]
    for i in items:
        lines.append(f"  - {i['name']}  (added {i.get('added_at', '?')})")
    return "\n".join(lines)


# --- fuzzy name matching -----------------------------------------------------

_STRIP_WORDS = {"inc", "incorporated", "llc", "ltd", "corp", "co", "labs", "ai"}


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()
    return re.sub(r"\s+", " ", s)


def _tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if t and t not in _STRIP_WORDS}


def matches(watched: str, company: str) -> bool:
    """Fuzzy match a watchlist name against a job's company name."""
    wn, cn = _norm(watched), _norm(company)
    if not wn or not cn:
        return False
    if wn == cn or wn in cn or cn in wn:
        return True
    wt, ct = _tokens(watched), _tokens(company)
    if wt and ct and (wt <= ct or ct <= wt):
        return True
    return difflib.SequenceMatcher(None, wn, cn).ratio() >= 0.85


# --- curated jobs (local jobs.json, read defensively) ------------------------

def _curated_jobs() -> list[dict]:
    """Gather curated jobs from candid_data/jobs.json.

    Combines low-score stash entries (full company/title/url) with
    tracker-backed entries resolved through the ``seen`` map. Missing or
    corrupt files degrade to an empty list, never an exception.
    """
    jobs: list[dict] = []
    state: dict = {}
    p = _jobs_state_path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state = raw
        except json.JSONDecodeError:
            state = {}

    for e in state.get("skipped_low_score", []):
        if isinstance(e, dict) and e.get("company"):
            jobs.append({
                "source_id": str(e.get("source_id") or ""),
                "company": str(e.get("company") or ""),
                "title": str(e.get("title") or ""),
                "url": str(e.get("url") or ""),
            })

    seen = state.get("seen", {})
    if seen:
        try:
            from candid import tracker as T
            apps = {a.get("id"): a for a in T.list_apps()}
            from candid import jobs as J
            for source_id, app_id in seen.items():
                rec = apps.get(app_id)
                if not rec:
                    continue
                try:
                    meta = J.get_job_meta(app_id)
                except Exception:
                    meta = {}
                jobs.append({
                    "source_id": str(source_id),
                    "company": str(rec.get("company") or ""),
                    "title": str(rec.get("role") or ""),
                    "url": str(meta.get("source_url") or rec.get("jd_link") or ""),
                })
        except Exception:
            pass
    return jobs


# --- alerts ------------------------------------------------------------------

def _alerted_keys() -> set[tuple[str, str]]:
    """(watched_name_norm, source_id) pairs already alerted."""
    keys: set[tuple[str, str]] = set()
    p = _alerts_path()
    if not p.exists():
        return keys
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                continue
            keys.add((_norm(a.get("name", "")), str(a.get("source_id", ""))))
    except OSError:
        pass
    return keys


def _append_alert(alert: dict) -> None:
    C.ensure_data_dirs()
    with _alerts_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(alert) + "\n")


def check() -> dict:
    """Match the watchlist against curated jobs and alert on new hits.

    Returns {"checked": n_jobs, "new_alerts": [alert dicts]}.
    """
    watched = _load_watchlist()
    if not watched:
        raise StartupWatchError(
            "Watchlist is empty. Add one first: "
            "`python -m candid startups watch add --name \"Acme AI\"`.")
    jobs = _curated_jobs()
    seen_keys = _alerted_keys()
    new_alerts: list[dict] = []
    for job in jobs:
        if not job["company"] or not job["source_id"]:
            continue
        for w in watched:
            key = (_norm(w["name"]), job["source_id"])
            if key in seen_keys:
                continue
            if matches(w["name"], job["company"]):
                alert = {
                    "name": w["name"],
                    "company": job["company"],
                    "title": job["title"],
                    "source_id": job["source_id"],
                    "url": job["url"],
                    "alerted_at": _now_iso(),
                }
                _append_alert(alert)
                seen_keys.add(key)
                new_alerts.append(alert)
    return {"checked": len(jobs), "new_alerts": new_alerts}


def render_check(result: dict) -> str:
    alerts = result.get("new_alerts", [])
    if not alerts:
        return f"Checked {result.get('checked', 0)} curated job(s). No new watchlist hits."
    lines = [f"{len(alerts)} new watchlist hit(s):"]
    for a in alerts:
        lines.append(f"  - {a['name']} -> {a['title']} @ {a['company']}"
                     + (f"  {a['url']}" if a.get("url") else ""))
    return "\n".join(lines)
