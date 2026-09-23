"""Local web dashboard for candid.

``python -m candid dashboard`` starts a server on 127.0.0.1 and opens it in
your browser. Everything is served from your machine; the server binds
localhost only, needs no accounts, no keys, no network.

The UI itself lives in ``candid/data/dashboard.html`` (single file, no CDN,
works fully offline). This module exposes the JSON API it talks to — the
data functions are importable and unit-tested independently of HTTP.
"""

from __future__ import annotations

import http.server
import importlib
import json
import re
import sys
import tempfile
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from candid import config as C


log = C.get_logger("dashboard")


class DashboardError(Exception):
    """Raised for dashboard operation problems."""


# ---------------------------------------------------------------------------
# data functions (pure logic — testable without HTTP)
# ---------------------------------------------------------------------------

def overview() -> dict:
    """Funnel stats, counts, nudges, integration status — one payload."""
    from candid import tracker as T, nudges as N, gmail
    from candid import profile as P
    stats = T.stats()
    try:
        prof = P.load_profile()
        profile_info = {"has_profile": True, "name": prof.get("name", ""),
                        "headline": prof.get("headline", "")}
    except Exception:
        profile_info = {"has_profile": False, "name": "", "headline": ""}
    return {
        "funnel": stats["counts"],
        "total": stats["total"],
        "response_rate": stats["response_rate"],
        "interview_rate": stats["interview_rate"],
        "offer_rate": stats["offer_rate"],
        "nudges": N.pending_nudges(),
        "nudge_count": len(N.pending_nudges()),
        # import model: candid never connects to accounts — the user exports
        # their own data and feeds it in. Only proposal counts are surfaced.
        "gmail": {"pending_proposals": len(gmail.list_proposals(status="pending"))},
        "gmail_pending_proposals": len(gmail.list_proposals(status="pending")),
        "profile": profile_info,
        "curated_count": len(curated_jobs()),
    }


IMPORT_PATTERN = """\
How to add a new source (the generic pattern):

1. The user exports their own data from the source (Takeout, data-export
   archive, CSV download, …) — candid never connects to accounts.
2. Add a module under candid/ that parses the export into plain dicts.
3. Wire it into `candid import` (candid/__main__.py), the dashboard's
   "Import your data" section (candid/dashboard.py + data/dashboard.html),
   and add fixture-based tests under tests/.
"""


def import_guides() -> dict:
    """Step-by-step export instructions per source, for the dashboard."""
    from candid import gmail, linkedin
    return {
        "gmail": {"title": "Gmail — Google Takeout mbox",
                  "steps": gmail.TAKEOUT_GUIDE.strip().splitlines(),
                  "accept": ".mbox",
                  "command": "python -m candid gmail import /path/to/your.mbox"},
        "linkedin": {"title": "LinkedIn — official data-export archive",
                     "steps": linkedin.EXPORT_GUIDE.strip().splitlines(),
                     "accept": ".zip",
                     "command": "python -m candid linkedin import --zip /path/to/LinkedIn-export.zip"},
        "pattern": {"title": "Any other source",
                    "steps": IMPORT_PATTERN.strip().splitlines()},
    }


def run_import(source: str, path: str | Path) -> dict:
    """Run an import from a user-supplied export file. Returns a summary."""
    source = (source or "").lower()
    if source == "gmail":
        from candid import gmail
        res = gmail.import_mbox(path)
        return {"source": "gmail",
                "files": res["files"],
                "messages": res["messages"],
                "new_proposals": len(res["new_proposals"]),
                "proposals": res["new_proposals"],
                "summary": gmail.render_import_summary(res)}
    if source == "linkedin":
        from candid import linkedin
        res = linkedin.import_zip(str(path))
        prof = res["profile"]
        return {"source": "linkedin",
                "mode": res["mode"],
                "positions": res["positions"],
                "skills": res["skills"],
                "education": res["education"],
                "summary": (f"LinkedIn import ({res['mode']}): {res['positions']} positions, "
                            f"{res['skills']} skills, {res['education']} education entries. "
                            f"Profile: {prof.get('name', '')} — {prof.get('headline', '')}.")}
    raise DashboardError(f"Unknown import source: {source!r} "
                         "(expected 'gmail' or 'linkedin').")


def detect_source(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".mbox"):
        return "gmail"
    if name.endswith(".zip"):
        return "linkedin"
    return None


def list_apps_filtered(status: str | None = None, query: str = "") -> list[dict]:
    from candid import config as C
    from candid import tracker as T
    if status and status not in C.STATUSES:
        return []  # unknown filter value → empty, not a 500
    apps = T.list_apps(status=status or None)
    if query:
        ql = query.lower()
        apps = [a for a in apps
                if ql in a.get("company", "").lower()
                or ql in a.get("role", "").lower()
                or ql in a.get("notes", "").lower()]
    return apps


def curated_jobs() -> list[dict]:
    """Saved jobs with match scores and apply links — structured.

    Jobs dismissed via POST /api/jobs/dismiss are filtered out here.
    """
    from candid import tracker as T, jobs as J
    dismissed = dismissed_ids()
    out = []
    for a in T.list_apps(status="saved"):
        if a["id"] in dismissed["app_ids"]:
            continue
        meta = J.get_job_meta(a["id"])
        sid = _source_id_for_app(a["id"]) or meta.get("source_id") or ""
        if sid and sid in dismissed["source_ids"]:
            continue
        out.append({
            "app_id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "score": meta.get("match_score"),
            "source": meta.get("source"),
            "source_id": sid,
            "url": meta.get("source_url") or a.get("jd_link") or "",
            "date_added": a.get("date_added", ""),
            "has_jd": bool(meta.get("jd_text")),
        })
    return out


def run_curate(role: str, location: str = "", remote: bool = False,
               level: str | None = None, limit: int = 15,
               sources: list | None = None) -> dict:
    """Run a job-curation pass from the dashboard.

    Returns the human-readable summary plus the structured result.
    """
    from candid import jobs as J, profile as Prof
    if not (role or "").strip():
        raise DashboardError("role is required (e.g. 'Data Scientist').")
    profile = Prof.load_profile()
    try:
        result = J.curate(profile, role=role, location=location or "",
                          remote=bool(remote), level=level or None,
                          limit=int(limit or 15), sources=sources or None)
    except J.JobsError as e:
        raise DashboardError(str(e)) from e
    return {
        "summary": J.render_curated(result),
        "fetched": result["fetched"],
        "candidates": result["candidates"],
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
    }


# ---------------------------------------------------------------------------
# dismissed curated jobs (sidecar state — jobs.py itself is untouched)
# ---------------------------------------------------------------------------

def _dismissed_path() -> Path:
    return C.DATA_DIR / "dismissed_jobs.json"


def _jobs_seen() -> dict:
    """Read jobs.py's own {source_id: app_id} map (read-only).

    This is how a curated tracker record is traced back to the job-board
    posting that produced it.
    """
    p = C.DATA_DIR / "jobs.json"
    if p.exists():
        try:
            seen = json.loads(p.read_text(encoding="utf-8")).get("seen", {})
            return seen if isinstance(seen, dict) else {}
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    return {}


def _source_id_for_app(app_id: int) -> str:
    for sid, aid in _jobs_seen().items():
        if aid == app_id:
            return str(sid)
    return ""


def dismissed_ids() -> dict:
    """{'source_ids': set[str], 'app_ids': set[int]} of dismissed jobs."""
    p = _dismissed_path()
    data: dict = {"source_ids": [], "app_ids": []}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data["source_ids"] = raw.get("source_ids", [])
                data["app_ids"] = raw.get("app_ids", [])
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    return {"source_ids": {str(s) for s in data["source_ids"]},
            "app_ids": {int(i) for i in data["app_ids"] if str(i).isdigit()}}


def _save_dismissed(d: dict) -> None:
    C.ensure_data_dirs()
    _dismissed_path().write_text(json.dumps({
        "source_ids": sorted(d["source_ids"]),
        "app_ids": sorted(d["app_ids"]),
    }, indent=2), encoding="utf-8")


def dismiss_job(source_id: str | None = None,
                app_id: int | None = None) -> dict:
    """Hide a curated job without tracking it.

    Accepts a curation ``source_id`` and/or a tracker ``app_id`` (resolved
    to its source_id via jobs.py's ``seen`` map). Dismissed jobs disappear
    from ``curated_jobs()`` and the dashboard's curated-jobs section.
    """
    if app_id is not None:
        try:
            app_id = int(app_id)
        except (TypeError, ValueError):
            raise DashboardError(f"Bad app_id: {app_id!r}")
        if not source_id:
            source_id = _source_id_for_app(app_id)
    if not source_id and app_id is None:
        raise DashboardError("Provide a source_id or an app_id to dismiss.")
    d = dismissed_ids()
    if source_id:
        d["source_ids"].add(str(source_id))
    if app_id is not None:
        d["app_ids"].add(app_id)
    _save_dismissed(d)
    log.debug("dismissed job source_id=%r app_id=%r", source_id, app_id)
    return {"dismissed": True, "source_id": str(source_id or ""),
            "app_id": app_id}


def run_tailor_diff(kind: str, company: str, role: str, jd: str,
                    tone: str = "confident", length: str = "one-page") -> dict:
    """Tailored text + keyword coverage vs the JD.

    Returns {text, coverage: {covered: [...], missing: [...]}, changes: []}.
    Coverage is computed from the same skill lexicon ``match`` uses, so the
    chips agree with the match breakdown.
    """
    from candid import tailor as T, profile as Prof, match as M
    if kind not in ("resume", "cover-letter"):
        raise DashboardError("kind must be 'resume' or 'cover-letter'.")
    if not (jd or "").strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    if kind == "resume":
        text = T.build_resume(profile, jd, company=company, role=role,
                              tone=tone, length=length)
    else:
        text = T.build_cover_letter(profile, jd, company=company, role=role,
                                    tone=tone, hook="")
    must, nice = M._jd_skills(jd)
    pskills = set(profile.get("skills", []))
    wanted = must | nice
    return {
        "text": text,
        "coverage": {
            "covered": sorted(wanted & pskills),
            "missing": sorted(wanted - pskills),
        },
        "changes": [],
    }


def prep_status() -> list[dict]:
    """Per-application interview-prep state (interview-stage apps only)."""
    from candid import tracker as T
    out = []
    for a in T.list_apps():
        if a.get("status") not in ("selected_for_interview", "offer"):
            continue
        pack = a.get("prep_pack", "")
        has_pack = bool(pack) and Path(pack).exists()
        out.append({
            "app_id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "status": a["status"],
            "has_pack": has_pack,
            "pack_path": pack if has_pack else "",
        })
    return out


def run_prep(company: str, role: str, app_id: int | None = None,
             jd: str = "", location: str = "") -> dict:
    from candid import prep as P, profile as Prof, tracker as T
    if not company or not role:
        raise DashboardError("company and role are required.")
    profile = Prof.load_profile()
    markdown, path = P.build_pack(profile, company, role, jd=jd,
                                  app_id=app_id, location=location)
    if app_id:
        T.update(app_id, prep_pack=str(path))
    return {"path": str(path), "chars": len(markdown)}


def run_match(jd: str, company: str = "", role: str = "",
              location: str = "") -> dict:
    from candid import match as M, profile as Prof
    if not jd.strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    result = M.score_match(profile, jd, title=role, company=company, location=location)
    result["report"] = M.render_report(result, company=company, title=role)
    return result


def update_status(app_id: int, status: str) -> dict:
    """Change an application's status from the dashboard."""
    from candid import config as C
    from candid import tracker as T
    if status not in C.STATUSES:
        raise DashboardError(f"Unknown status: {status!r}")
    try:
        return T.update(app_id, status=status)
    except T.TrackerError as e:
        raise DashboardError(str(e)) from e


def proposal_list(status: str = "pending") -> list[dict]:
    """Pending Gmail proposals awaiting confirmation."""
    from candid import gmail
    return gmail.list_proposals(status=status)


def confirm_proposal(proposal_id: int) -> dict:
    """Confirm a Gmail proposal → writes to the tracker."""
    from candid import gmail
    try:
        return gmail.confirm_proposal(proposal_id)
    except gmail.GmailError as e:
        raise DashboardError(str(e)) from e


def reject_proposal(proposal_id: int) -> None:
    """Dismiss a Gmail proposal."""
    from candid import gmail
    try:
        gmail.reject_proposal(proposal_id)
    except gmail.GmailError as e:
        raise DashboardError(str(e)) from e


def run_tailor(kind: str, company: str, role: str, jd: str,
               tone: str = "confident", length: str = "one-page") -> dict:
    from candid import tailor as T, profile as Prof
    if kind not in ("resume", "cover-letter"):
        raise DashboardError("kind must be 'resume' or 'cover-letter'.")
    if not jd.strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    if kind == "resume":
        text = T.build_resume(profile, jd, company=company, role=role,
                              tone=tone, length=length)
    else:
        text = T.build_cover_letter(profile, jd, company=company, role=role,
                                    tone=tone, hook="")
    C.ensure_data_dirs()
    safe = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}-{kind}".lower()).strip("-")
    out = C.TAILOR_DIR / f"{safe}.md"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "text": text}


def salary_lookup(company: str, title: str, location: str = "") -> dict:
    from candid import salary as S
    return S.lookup(company=company, title=title, location=location)


# ---------------------------------------------------------------------------
# watchlist (company career-page monitors) — defensive integration
#
# candid/monitors.py and candid/alerts.py are owned elsewhere. The dashboard
# must never crash because of them: every read goes through _watch_module(),
# which returns None when the module is absent (or known-absent via
# sys.modules), and all state access is wrapped in try/except. Field
# normalization uses .get() with multiple aliases so slightly different
# shapes still render.
#
# Native API preferred (list_companies/health/get_history on monitors;
# get_pending_alerts/mark_read/load_alerts/get_threshold on alerts); generic
# aliases below are probed as fallbacks.
# ---------------------------------------------------------------------------

_WATCH_MONITORS_ALIASES = ["list_companies", "list_monitors", "get_monitors",
                           "companies", "all_monitors", "monitors"]
_WATCH_ALERTS_ALIASES = ["get_pending_alerts", "unread", "unread_alerts",
                         "list_unread", "pending", "pending_alerts"]
_WATCH_MARK_READ_ALIASES = ["mark_read", "ack", "ack_alert", "dismiss_alert",
                            "mark_alert_read"]
_WATCH_TIMELINE_ALIASES = ["get_history", "timeline", "company_timeline",
                           "postings", "company_postings", "get_postings"]


def _watch_module(name: str):
    """Import candid.<name> (monitors/alerts) or return None if absent.

    A defensive import: the dashboard works fine without these modules —
    the watch panels just render a "not configured" state.
    """
    fullname = f"candid.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]  # may be None = known absent
    try:
        return importlib.import_module(fullname)
    except Exception:  # ImportError or anything raised at import time
        log.debug("watch module %s unavailable", fullname)
        return None


def _first_fn(mod, aliases: list[str]):
    for a in aliases:
        fn = getattr(mod, a, None)
        if callable(fn):
            return fn
    return None


def watch_available() -> bool:
    """True when at least the monitors module is importable."""
    return _watch_module("monitors") is not None


def _native_watch_cards(mod) -> list[dict]:
    """Build company cards from the native monitors API.

    Combines the registry (list_companies), per-source feed health
    (health), and last-run counts (alerts.load_runs) — all defensively,
    since any of those reads may fail.
    """
    companies = mod.list_companies() or []
    try:
        health_map = mod.health() or {}
    except Exception:  # noqa: BLE001
        health_map = {}
    try:
        alerts_mod = _watch_module("alerts")
        runs = (alerts_mod.load_runs() or {}) if alerts_mod else {}
    except Exception:  # noqa: BLE001
        runs = {}
    runs_companies = runs.get("companies", {}) or {}

    def _runs_for(name: str) -> dict:
        if name in runs_companies:
            return runs_companies[name]
        low = name.lower()
        for k, v in runs_companies.items():
            if str(k).lower() == low:
                return v
        return {}

    cards = []
    for comp in companies:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name", "")
        sources = comp.get("sources") or []
        types = sorted({str(s.get("type", "")) for s in sources if s.get("type")})
        entries = [h for h in (health_map.values() if isinstance(health_map, dict) else [])
                   if isinstance(h, dict) and h.get("company") == name]
        statuses = {str(e.get("status", "")).lower() for e in entries}
        if not sources:
            feed_health = "not configured"
        elif statuses & {"skipped", "failing"}:
            feed_health = "error"
        elif statuses == {"ok"} or not statuses:
            feed_health = "ok"
        else:
            feed_health = "unknown"
        last_error = next((str(e.get("last_error") or "") for e in entries
                           if e.get("last_error")), "")
        run = _runs_for(name)
        open_count = run.get("open")
        if open_count is None:
            # fall back to counting open postings in the history
            try:
                hist = mod.get_history(name) or {}
                open_count = sum(1 for r in hist.values()
                                 if isinstance(r, dict)
                                 and r.get("status") == "open")
            except Exception:  # noqa: BLE001
                open_count = 0
        cards.append({
            "company": name,
            "source_type": ", ".join(types),
            "source_key": str(sources[0].get("label", "")) if sources else "",
            "enabled": True,
            "last_run": run.get("last_run", ""),
            "open_count": int(open_count or 0),
            "new_since_last": int(run.get("new", 0) or 0),
            "feed_health": feed_health,
            "last_error": last_error,
        })
    return cards


def _norm_company_card(c: dict) -> dict:
    c = dict(c or {})
    open_count = c.get("open_count", c.get("open_postings", None))
    if open_count is None:
        postings = c.get("postings") or []
        open_count = len(postings)
    health = c.get("feed_health", c.get("health", c.get("status", "unknown")))
    return {
        "company": c.get("company", c.get("name", "")),
        "source_type": c.get("source_type", c.get("source", "")),
        "source_key": str(c.get("source_key", c.get("key", c.get("token", "")))),
        "enabled": bool(c.get("enabled", True)),
        "last_run": c.get("last_run", c.get("last_checked", "")),
        "open_count": int(open_count or 0),
        "new_since_last": int(c.get("new_since_last",
                                   c.get("new_count", c.get("new", 0))) or 0),
        "feed_health": str(health or "unknown"),
        "last_error": c.get("last_error", c.get("error", "")) or "",
    }


def watch_status() -> dict:
    """Per-company monitor cards: status, counts, feed health.

    Returns {"enabled": bool, "companies": [...]}. Never raises for a
    missing/broken monitors module — degrades to enabled=False.
    """
    mod = _watch_module("monitors")
    if mod is None:
        return {"enabled": False, "companies": []}
    try:
        if callable(getattr(mod, "list_companies", None)):
            return {"enabled": True,
                    "companies": _native_watch_cards(mod)}
        fn = _first_fn(mod, _WATCH_MONITORS_ALIASES)
        companies = [_norm_company_card(c) for c in (fn() if fn else [])]
        return {"enabled": True, "companies": companies}
    except Exception as e:  # noqa: BLE001 — dashboard must not crash
        log.warning("watch_status failed: %s: %s", type(e).__name__, e)
        return {"enabled": True, "companies": [],
                "error": f"{type(e).__name__}: {e}"}


def _norm_alert(a: dict) -> dict:
    a = dict(a or {})
    return {
        "id": a.get("id"),
        "kind": a.get("kind", "new"),
        "company": a.get("company", ""),
        "title": a.get("title", a.get("role", "")),
        "url": a.get("url", a.get("link", a.get("apply_url", ""))),
        "location": a.get("location", ""),
        "source_type": a.get("source_type", a.get("source", "")),
        "posted_at": a.get("posted_at", ""),
        "first_seen": a.get("first_seen", ""),
        "created_at": a.get("created_at", ""),
        "score": a.get("score"),
        "verdict": a.get("verdict", ""),
        "message": a.get("message", ""),
        "read": bool(a.get("read", False)),
    }


def watch_alerts(unread_only: bool = True) -> dict:
    """Unread new-posting alerts with posting URLs.

    Returns {"enabled": bool, "alerts": [...], "threshold": ...}. Degrades
    to enabled=False when the alerts module is absent.
    """
    mod = _watch_module("alerts")
    if mod is None:
        return {"enabled": False, "alerts": []}
    try:
        threshold = None
        if callable(getattr(mod, "get_threshold", None)):
            try:
                threshold = mod.get_threshold()
            except Exception:  # noqa: BLE001
                pass
        fn = _first_fn(mod, _WATCH_ALERTS_ALIASES)
        raw = fn() if fn else []
        alerts = [_norm_alert(a) for a in (raw or [])]
        if unread_only:
            alerts = [a for a in alerts if not a["read"]]
        return {"enabled": True, "alerts": alerts, "threshold": threshold}
    except Exception as e:  # noqa: BLE001
        log.warning("watch_alerts failed: %s: %s", type(e).__name__, e)
        return {"enabled": True, "alerts": [],
                "error": f"{type(e).__name__}: {e}"}


def watch_mark_read(alert_id) -> dict:
    """Mark one alert as read. Raises DashboardError when unavailable."""
    mod = _watch_module("alerts")
    if mod is None:
        raise DashboardError("Alerts are not available — candid/alerts.py "
                             "is not installed.")
    fn = _first_fn(mod, _WATCH_MARK_READ_ALIASES)
    if fn is None:
        raise DashboardError("The alerts module has no mark-read function.")
    try:
        fn(alert_id)
    except Exception as e:  # noqa: BLE001
        raise DashboardError(f"Could not mark alert {alert_id!r} read: {e}") from e
    log.debug("marked alert %r read", alert_id)
    return {"ok": True, "id": alert_id}


def _norm_posting(p: dict) -> dict:
    p = dict(p or {})
    reposted = p.get("reposted", p.get("is_repost", p.get("repost", False)))
    return {
        "id": p.get("id", ""),
        "title": p.get("title", p.get("role", "")),
        "url": p.get("url", p.get("link", p.get("apply_url", ""))),
        "location": p.get("location", ""),
        "first_seen": p.get("first_seen", ""),
        "last_seen": p.get("last_seen", ""),
        "closed_at": p.get("closed_at", ""),
        "reposted": bool(reposted),
    }


def _timeline_from_history(name: str, hist: dict) -> dict:
    """Split a {posting_id: record} history into open / recently closed."""
    recs = [r for r in (hist or {}).values() if isinstance(r, dict)]
    open_ = [r for r in recs if r.get("status") == "open"]
    closed = sorted(
        (r for r in recs if r.get("status") == "closed"),
        key=lambda r: str(r.get("closed_at", "")), reverse=True)[:25]
    open_.sort(key=lambda r: str(r.get("first_seen", "")), reverse=True)
    return {"company": name,
            "open": [_norm_posting(p) for p in open_],
            "recently_closed": [_norm_posting(p) for p in closed]}


def company_timeline(name: str) -> dict:
    """Open postings (with first_seen), recently closed, repost flags.

    Raises DashboardError when unavailable or the company is unknown.
    """
    if not (name or "").strip():
        raise DashboardError("Provide a company name (?name=...).")
    mod = _watch_module("monitors")
    if mod is None:
        raise DashboardError("Watch is not available — candid/monitors.py "
                             "is not installed.")
    get_history = getattr(mod, "get_history", None)
    if callable(get_history):
        try:
            return _timeline_from_history(name, get_history(name))
        except Exception as e:  # noqa: BLE001
            raise DashboardError(str(e)) from e
    fn = _first_fn(mod, [a for a in _WATCH_TIMELINE_ALIASES
                         if a != "get_history"])
    if fn is None:
        raise DashboardError("The monitors module has no timeline function.")
    try:
        res = fn(name)
    except TypeError:  # maybe keyword-style signature
        res = fn(company=name)
    except Exception as e:  # noqa: BLE001
        raise DashboardError(f"Could not load timeline for {name!r}: {e}") from e
    if isinstance(res, list):  # plain list of postings → all open
        return {"company": name,
                "open": [_norm_posting(p) for p in res],
                "recently_closed": []}
    if isinstance(res, dict) and ("open" in res or "recently_closed" in res
                                  or "closed" in res):
        res = dict(res)
        return {"company": res.get("company", name),
                "open": [_norm_posting(p) for p in (res.get("open") or [])],
                "recently_closed": [_norm_posting(p)
                                    for p in (res.get("recently_closed")
                                              or res.get("closed") or [])]}
    if isinstance(res, dict):  # {posting_id: record} history shape
        return _timeline_from_history(name, res)
    return {"company": name, "open": [], "recently_closed": []}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

HTML_PATH = C.PACKAGE_ROOT / "data" / "dashboard.html"


def _send_json(handler: http.server.BaseHTTPRequestHandler, obj,
               status: int = 200) -> None:
    body = json.dumps(obj).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict, dict]:
    """Minimal multipart/form-data parser (stdlib only).

    Returns (fields, files) where files maps field name ->
    (filename, bytes). Good enough for a local dashboard file picker.
    """
    m = re.search(r"boundary=([^;]+)", content_type or "")
    if not m:
        raise DashboardError("multipart upload without a boundary.")
    boundary = ("--" + m.group(1).strip().strip('"')).encode()
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in body.split(boundary)[1:-1]:
        head, _, data = part.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = head.decode("latin-1", errors="replace")
        nm = re.search(r'name="([^"]+)"', headers)
        if not nm:
            continue
        fn = re.search(r'filename="([^"]*)"', headers)
        if fn and fn.group(1):
            files[nm.group(1)] = (fn.group(1), data)
        else:
            fields[nm.group(1)] = data.decode("utf-8", errors="replace")
    return fields, files


def _read_upload(handler: http.server.BaseHTTPRequestHandler) -> tuple[str, bytes]:
    """Read a multipart file upload. Returns (filename, bytes)."""
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if not length:
        raise DashboardError("Empty upload.")
    if length > 500 * 1024 * 1024:
        raise DashboardError("File too large (500 MB limit).")
    body = handler.rfile.read(length)
    _, files = _parse_multipart(body, handler.headers.get("Content-Type", ""))
    if "file" not in files:
        raise DashboardError("No file field in upload.")
    return files["file"]


def _read_json(handler: http.server.BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    server_version = "candid-dashboard/1.0"

    def log_message(self, *args):  # keep the CLI quiet
        pass

    # -- routing ---------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        log.debug("GET %s", self.path)
        try:
            if path == "/":
                self._serve_html()
            elif path == "/api/overview":
                _send_json(self, overview())
            elif path == "/api/apps":
                _send_json(self, list_apps_filtered(
                    status=qs.get("status", [None])[0],
                    query=qs.get("q", [""])[0]))
            elif path == "/api/jobs":
                _send_json(self, curated_jobs())
            elif path == "/api/prep-status":
                _send_json(self, prep_status())
            elif path == "/api/nudges":
                from candid import nudges as N
                _send_json(self, N.pending_nudges())
            elif path == "/api/salary":
                _send_json(self, salary_lookup(
                    qs.get("company", [""])[0], qs.get("title", [""])[0],
                    qs.get("location", [""])[0]))
            elif path == "/api/proposals":
                _send_json(self, proposal_list(
                    status=qs.get("status", [None])[0]))
            elif path == "/api/import-guides":
                _send_json(self, import_guides())
            elif path == "/api/watch":
                _send_json(self, watch_status())
            elif path == "/api/watch/alerts":
                _send_json(self, watch_alerts())
            elif path == "/api/watch/company":
                try:
                    _send_json(self, company_timeline(
                        qs.get("name", [""])[0]))
                except DashboardError as e:
                    code = 404 if "Unknown company" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                return
            else:
                _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            log.debug("GET %s -> 400: %s", self.path, e)
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 — never leak tracebacks to UI
            log.warning("GET %s -> 500: %s: %s", self.path,
                        type(e).__name__, e)
            _send_json(self, {"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ctype = self.headers.get("Content-Type", "")
        log.debug("POST %s", self.path)
        # file uploads bypass the JSON reader (it would consume rfile)
        if path == "/api/import" and "multipart/form-data" in ctype:
            try:
                filename, data = _read_upload(self)
                source = detect_source(filename)
                if not source:
                    _send_json(self, {"error":
                        f"Can't detect source for {filename!r} — "
                        "use a .mbox (Gmail Takeout) or .zip (LinkedIn export)."}, 400)
                    return
                tmp = Path(tempfile.gettempdir()) / f"candid-import-{filename}"
                tmp.write_bytes(data)
                try:
                    _send_json(self, {**run_import(source, tmp),
                                      "filename": filename})
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            except DashboardError as e:
                log.debug("POST %s (upload) -> 400: %s", self.path, e)
                _send_json(self, {"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name in ("GmailError", "LinkedInError", "ValueError"):
                    log.debug("POST %s (upload) -> 400: %s: %s",
                              self.path, name, e)
                    _send_json(self, {"error": str(e)}, 400)
                else:
                    log.warning("POST %s (upload) -> 500: %s: %s",
                                self.path, name, e)
                    _send_json(self, {"error": f"{name}: {e}"}, 500)
            return
        body = _read_json(self)
        try:
            m = re.fullmatch(r"/api/apps/(\d+)", path)
            if m:
                try:
                    rec = update_status(int(m.group(1)),
                                        body.get("status", ""))
                except DashboardError as e:
                    code = 404 if "No application" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                    return
                _send_json(self, rec)
                return
            if path == "/api/prep":
                _send_json(self, run_prep(
                    body.get("company", ""), body.get("role", ""),
                    app_id=body.get("app_id"), jd=body.get("jd", ""),
                    location=body.get("location", "")))
                return
            if path == "/api/match":
                _send_json(self, run_match(
                    body.get("jd", ""), company=body.get("company", ""),
                    role=body.get("role", ""),
                    location=body.get("location", "")))
                return
            if path == "/api/tailor":
                _send_json(self, run_tailor(
                    body.get("kind", "resume"), body.get("company", ""),
                    body.get("role", ""), body.get("jd", ""),
                    tone=body.get("tone", "confident"),
                    length=body.get("length", "one-page")))
                return
            m = re.fullmatch(r"/api/proposals/(\d+)/(confirm|reject)", path)
            if m:
                pid, action = int(m.group(1)), m.group(2)
                try:
                    if action == "confirm":
                        _send_json(self, confirm_proposal(pid))
                    else:
                        reject_proposal(pid)
                        _send_json(self, {"ok": True, "id": pid})
                except DashboardError as e:
                    code = 404 if "No proposal" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                return
            if path == "/api/import":
                src_name = (body.get("source") or "").lower()
                src_path = body.get("path", "")
                if not src_name or not src_path:
                    _send_json(self, {"error":
                        "Provide {\"source\": \"gmail\"|\"linkedin\", "
                        "\"path\": \"/path/to/export\"}."}, 400)
                    return
                _send_json(self, run_import(src_name, src_path))
                return
            if path == "/api/curate":
                _send_json(self, run_curate(
                    role=body.get("role", ""),
                    location=body.get("location", ""),
                    remote=bool(body.get("remote", False)),
                    level=body.get("level") or None,
                    limit=body.get("limit", 15),
                    sources=body.get("sources") or None))
                return
            if path == "/api/jobs/dismiss":
                _send_json(self, dismiss_job(
                    source_id=body.get("source_id"),
                    app_id=body.get("app_id")))
                return
            if path == "/api/tailor-diff":
                _send_json(self, run_tailor_diff(
                    body.get("kind", "resume"), body.get("company", ""),
                    body.get("role", ""), body.get("jd", ""),
                    tone=body.get("tone", "confident"),
                    length=body.get("length", "one-page")))
                return
            m = re.fullmatch(r"/api/watch/alerts/([^/]+)/read", path)
            if m:
                alert_id = urllib.parse.unquote(m.group(1))
                try:
                    alert_id = int(alert_id)
                except (TypeError, ValueError):
                    pass  # string ids are passed through unchanged
                try:
                    _send_json(self, watch_mark_read(alert_id))
                except DashboardError as e:
                    code = 404 if "No alert" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                return
            _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            log.debug("POST %s -> 400: %s", self.path, e)
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            # map known domain errors to 400
            name = type(e).__name__
            if name in ("TrackerError", "PrepError", "GmailError", "OnboardError",
                        "MatchError", "JobsError", "ValueError"):
                log.debug("POST %s -> 400: %s: %s", self.path, name, e)
                _send_json(self, {"error": str(e)}, 400)
            else:
                log.warning("POST %s -> 500: %s: %s", self.path, name, e)
                _send_json(self, {"error": f"{name}: {e}"}, 500)

    def _serve_html(self):
        try:
            body = HTML_PATH.read_bytes()
        except OSError:
            _send_json(self, {"error": "dashboard.html missing"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8765, open_browser: bool = True,
          handler_class=DashboardHandler):
    """Start the dashboard server (blocking). Binds 127.0.0.1 only."""
    server = None
    last_err = None
    for p in range(port, port + 10):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", p),
                                                     handler_class)
            port = p
            break
        except OSError as e:
            last_err = e
    if server is None:
        raise DashboardError(f"Could not bind a port near {port}: {last_err}")
    url = f"http://127.0.0.1:{port}/"
    print(f"📊 candid dashboard: {url}")
    print("   Local only — nothing leaves your machine. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
