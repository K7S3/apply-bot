"""Academic digest: one briefing for the academic job search.

Combines three sources into a single Markdown briefing:

  1. Upcoming fellowship deadlines   (candid.fellowships, sibling module)
  2. Watched-lab hits in the latest curated jobs
     (candid.labs + DATA_DIR/jobs.json)
  3. This month's hiring-season milestones (candid.academic_calendar)

Each section degrades to a "not configured / no data" line when its source
module or data is absent. Sibling modules are imported lazily (never at
module top level), so a missing or half-built sibling can never break this
module: ImportError always degrades to the "not configured" line.

Usage:
    python -m candid academic-digest
    python -m candid academic-digest --json
"""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import date, datetime
from pathlib import Path

from candid import config as C

NOT_CONFIGURED = "not configured"
NO_DATA = "no data"


# ---------------------------------------------------------------------------
# section 1: fellowship deadlines (sibling module: candid.fellowships)
# ---------------------------------------------------------------------------

#: Function names we will try, in order, on the fellowships module.
_FELLOWSHIP_FNS = (
    "upcoming",
    "upcoming_deadlines",
    "deadlines",
    "list_fellowships",
    "get_deadlines",
    "get_fellowships",
)

#: Module-level data attributes we will try if no function works.
_FELLOWSHIP_ATTRS = ("FELLOWSHIPS", "DEADLINES", "fellowships", "deadlines")

#: Keys inside DATA_DIR/fellowships.json that might hold the list.
_FELLOWSHIP_FILE_KEYS = ("fellowships", "deadlines", "upcoming", "items")


def _scalar(v):
    """Return v if it is a plain scalar, else '' (never str() a dict)."""
    if isinstance(v, bool):
        return ""
    return v if isinstance(v, (str, int, float)) else ""


def _name_of(it: dict) -> str:
    for key in ("name", "title", "fellowship", "program"):
        v = it.get(key)
        if isinstance(v, dict):  # e.g. {"fellowship": {...record...}}
            v = v.get("name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _deadline_of(it: dict) -> str:
    for key in ("deadline", "due", "due_date", "closes", "date"):
        v = it.get(key)
        if v is None or isinstance(v, (dict, list)):
            continue
        if hasattr(v, "isoformat"):
            return v.isoformat()
        s = str(v).strip()
        if s:
            return s
    return ""


def _adapt_fellowship_item(it: dict) -> dict | None:
    """Adapt the real sibling shape: {fellowship: {...}, deadline: date|None,
    days_until, approx, rolling} -> {name, deadline, url, notes}."""
    if not isinstance(it, dict):
        return None
    rec = it.get("fellowship")
    if not isinstance(rec, dict):
        return None
    name = str(rec.get("name") or "").strip()
    if not name:
        return None
    org = str(rec.get("org") or "").strip()
    deadline = it.get("deadline")
    deadline_s = (deadline.isoformat() if hasattr(deadline, "isoformat")
                  else str(deadline or "").strip())
    notes = str(rec.get("deadline_note") or "")
    extra = []
    if it.get("rolling"):
        extra.append("rolling applications")
    if it.get("approx"):
        du = it.get("days_until")
        extra.append(f"~{du}d away, approximate cycle date"
                     if du is not None else "approximate cycle date")
    if extra:
        notes = (notes + " (" + "; ".join(extra) + ")").strip()
    return {
        "name": f"{name} ({org})" if org else name,
        "deadline": deadline_s,
        "url": str(rec.get("url") or ""),
        "notes": notes,
    }


def _normalize_deadlines(items) -> list[dict]:
    """Normalize generic fellowship-ish data to [{name, deadline, url, notes}]."""
    if isinstance(items, dict):
        # maybe {"fellowships": [...]} or {name: deadline, ...}
        for key in _FELLOWSHIP_FILE_KEYS:
            if isinstance(items.get(key), list):
                items = items[key]
                break
        else:
            items = [{"name": k, "deadline": v} for k, v in items.items()]
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("fellowship"), dict):
            adapted = _adapt_fellowship_item(it)
            if adapted:
                out.append(adapted)
            continue
        name = _name_of(it)
        if not name:
            continue
        out.append({
            "name": name,
            "deadline": _deadline_of(it),
            "url": str(_scalar(it.get("url")) or _scalar(it.get("link"))),
            "notes": str(_scalar(it.get("notes")) or _scalar(it.get("description")) or ""),
        })
    out.sort(key=lambda d: (not d["deadline"], d["deadline"]))
    return out


def _probe_fellowship_module(mod, today=None) -> tuple[list[dict], list[dict] | None] | None:
    """Try the module's likely APIs.

    Returns (normalized_items, raw_items_or_None), or None when the module
    exposes nothing readable. The known sibling API is
    ``upcoming(today=...)`` -> [{fellowship, deadline, days_until, approx,
    rolling}]; its raw items are returned too so the digest can reuse the
    sibling's own renderer.
    """
    for fname in _FELLOWSHIP_FNS:
        fn = getattr(mod, fname, None)
        if not callable(fn):
            continue
        raw = None
        try:
            # known sibling signature: upcoming(days=60, today=None, ...)
            raw = fn(today=today) if today is not None else fn()
        except TypeError:
            try:
                raw = fn()
            except Exception:
                continue
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        norm = _normalize_deadlines(raw)
        raw_out = raw if any(isinstance(it, dict)
                             and isinstance(it.get("fellowship"), dict)
                             for it in raw) else None
        return norm, raw_out
    for attr in _FELLOWSHIP_ATTRS:
        val = getattr(mod, attr, None)
        if isinstance(val, (list, dict)):
            norm = _normalize_deadlines(val)
            if norm:
                return norm, None
    return None


def _fellowship_file_items() -> list[dict]:
    p = C.DATA_DIR / "fellowships.json"
    if not p.exists():
        return []
    try:
        return _normalize_deadlines(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return []


def _fellowships_section(today: date | None = None) -> dict:
    try:
        mod = importlib.import_module("candid.fellowships")
    except ImportError:
        return {"status": "unavailable", "items": [],
                "note": f"{NOT_CONFIGURED}: the fellowships tracker is not set up yet."}
    except Exception as e:  # sibling mid-edit: never break the digest
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: fellowships module unreadable ({e})."}
    probed = _probe_fellowship_module(mod, today)
    items: list[dict] | None = None
    raw_items: list[dict] | None = None
    if probed is not None:
        items, raw_items = probed
    if items is None:
        file_items = _fellowship_file_items()
        items = file_items if file_items else None
    if items is None:
        return {"status": "unavailable", "items": [],
                "note": f"{NOT_CONFIGURED}: the fellowships module has no readable "
                        "deadline list."}
    if not items:
        return {"status": "ok", "items": [],
                "note": f"{NO_DATA}: no fellowship deadlines in the upcoming window."}
    section: dict = {"status": "ok", "items": items, "note": ""}
    if raw_items:
        # kept so the digest can reuse the sibling's own renderer; date
        # objects inside are stringified by the --json path's default=str.
        section["raw_items"] = raw_items
    return section


# ---------------------------------------------------------------------------
# section 2: watched-lab hits (candid.labs + DATA_DIR/jobs.json)
# ---------------------------------------------------------------------------

def _labs_section() -> dict:
    try:
        mod = importlib.import_module("candid.labs")
    except ImportError:
        return {"status": "unavailable", "items": [],
                "note": f"{NOT_CONFIGURED}: the labs watchlist module is not available."}
    except Exception as e:  # sibling mid-edit: never break the digest
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: labs module unreadable ({e})."}
    try:
        watchlist = mod.list_labs()
        jobs = mod.load_curated_jobs()
    except Exception as e:  # half-written data files, etc.
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: labs data unreadable ({e})."}
    if not watchlist and not jobs:
        return {"status": "ok", "items": [],
                "note": f"{NO_DATA}: no labs on the watchlist and no curated jobs yet. "
                        "Add labs with `python -m candid labs add \"Name\"` and curate "
                        "jobs with `python -m candid jobs curate --role ...`."}
    if not watchlist:
        return {"status": "ok", "items": [],
                "note": f"{NO_DATA}: no labs on the watchlist. "
                        "Add some with `python -m candid labs add \"Name\"`."}
    if not jobs:
        return {"status": "ok", "items": [],
                "note": f"{NO_DATA}: no curated jobs to scan yet. "
                        "Run `python -m candid jobs curate --role ...` first."}
    try:
        hits = mod.check_labs(jobs)
    except Exception as e:
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: lab scan failed ({e})."}
    if not hits:
        return {"status": "ok", "items": [],
                "note": f"{NO_DATA}: no watchlist hits in the {len(jobs)} curated job(s) "
                        f"({len(watchlist)} lab(s) watched)."}
    return {"status": "ok", "items": hits[:25],
            "note": f"{len(hits)} hit(s) across {len(jobs)} curated job(s).",
            "watchlist_size": len(watchlist), "jobs_scanned": len(jobs)}


# ---------------------------------------------------------------------------
# section 3: hiring-season milestones (candid.academic_calendar)
# ---------------------------------------------------------------------------

def _calendar_section(now: date | None = None) -> dict:
    try:
        mod = importlib.import_module("candid.academic_calendar")
    except ImportError:
        return {"status": "unavailable", "items": [],
                "note": f"{NOT_CONFIGURED}: the academic calendar module is not available."}
    except Exception as e:  # sibling mid-edit: never break the digest
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: calendar module unreadable ({e})."}
    try:
        status = mod.season_status(now)
        reminders = mod.season_reminders(now)
        month_detail = mod.month_view(status["month"]) if hasattr(mod, "month_view") else {}
    except Exception as e:
        return {"status": "unavailable", "items": [],
                "note": f"{NO_DATA}: calendar data unreadable ({e})."}
    item = {
        "month_name": status.get("month_name", ""),
        "headline": status.get("headline", ""),
        "phases": list(status.get("phases", [])),
        "month_detail": dict(month_detail) if isinstance(month_detail, dict) else {},
        "reminders": [str(r) for r in reminders or []],
        "disclaimer": status.get("disclaimer", ""),
    }
    return {"status": "ok", "items": [item], "note": ""}


# ---------------------------------------------------------------------------
# digest assembly + rendering
# ---------------------------------------------------------------------------

def build_digest(now: date | None = None) -> dict:
    """Build the digest dict. Each section degrades independently.

    Returns {"generated_at", "as_of", "sections": {fellowships, labs,
    milestones}}. ``now`` (a date) pins the calendar section and the
    fellowship window for tests.
    """
    today = now or date.today()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "sections": {
            "fellowships": _fellowships_section(today),
            "labs": _labs_section(),
            "milestones": _calendar_section(today),
        },
    }


def _section_block(title: str, section: dict, render_items) -> list[str]:
    lines = [f"## {title}"]
    if section["status"] != "ok" or not section["items"]:
        lines.append(f"_{section['note']}_")
    else:
        lines.extend(render_items(section["items"]))
        if section.get("note"):
            lines.append(f"_{section['note']}_")
    lines.append("")
    return lines


def _render_fellowship_items(items: list[dict]) -> list[str]:
    lines = []
    for it in items[:15]:
        bits = [f"- **{it['name']}**"]
        if it["deadline"]:
            bits.append(f"deadline: {it['deadline']}")
        if it["url"]:
            bits.append(it["url"])
        lines.append(" - ".join(bits))
        if it["notes"]:
            lines.append(f"  {it['notes'][:160]}")
    if len(items) > 15:
        lines.append(f"  ... and {len(items) - 15} more")
    return lines


def _render_fellowships_block(section: dict) -> list[str]:
    """Fellowship section: prefer the sibling's own renderer when available."""
    lines = ["## 1. Upcoming fellowship deadlines"]
    if section.get("status") != "ok" or not section.get("items"):
        lines.append(f"_{section.get('note', '')}_")
        lines.append("")
        return lines
    text = None
    try:
        mod = importlib.import_module("candid.fellowships")
        renderer = getattr(mod, "render_upcoming", None)
        raw = section.get("raw_items")
        if callable(renderer) and raw:
            text = renderer(raw)
    except ImportError:
        text = None
    except Exception:
        text = None
    if text:
        lines.extend(text.splitlines())
    else:
        lines.extend(_render_fellowship_items(section["items"]))
    lines.append("")
    return lines


def _render_lab_items(items: list[dict]) -> list[str]:
    lines = []
    for h in items[:15]:
        aff = f" ({h.get('affiliation')})" if h.get("affiliation") else ""
        title = h.get("job_title") or "(untitled posting)"
        comp = f" @ {h.get('company')}" if h.get("company") else ""
        lines.append(f"- **{h.get('lab')}{aff}**: {title}{comp}")
        if h.get("url"):
            lines.append(f"  {h['url']}")
    if len(items) > 15:
        lines.append(f"  ... and {len(items) - 15} more")
    return lines


def _render_milestone_items(items: list[dict]) -> list[str]:
    it = items[0]
    lines = [it["headline"], ""]
    detail = it.get("month_detail") or {}
    for key in ("faculty", "postdoc", "fellowship"):
        if detail.get(key):
            lines.append(f"- {key.capitalize()}: {detail[key]}")
    if it.get("reminders"):
        lines.append("")
        for r in it["reminders"][:6]:
            lines.append(f"- {r}")
    if it.get("disclaimer"):
        lines.append("")
        lines.append(f"_Note: {it['disclaimer']}_")
    return lines


def render_digest(digest: dict) -> str:
    """Render a digest dict as a Markdown briefing."""
    try:
        as_of = date.fromisoformat(digest.get("as_of", ""))
        dateline = as_of.strftime("%B %d, %Y")
    except ValueError:
        dateline = digest.get("as_of", "")
    sections = digest.get("sections", {})
    month_name = ""
    ms = sections.get("milestones", {})
    if ms.get("items"):
        month_name = ms["items"][0].get("month_name", "")

    lines = [f"# Academic digest - {dateline}", ""]
    lines += _render_fellowships_block(sections.get("fellowships", {}))
    lines += _section_block("2. Watched-lab hits in latest curated jobs",
                            sections.get("labs", {}),
                            _render_lab_items)
    milestone_title = "3. This month's hiring-season milestones"
    if month_name:
        milestone_title += f" ({month_name})"
    lines += _section_block(milestone_title,
                            sections.get("milestones", {}),
                            _render_milestone_items)
    lines.append(f"_Generated {digest.get('generated_at', '')}. "
                 "Fellowship deadlines come from your tracker; milestones are "
                 "typical-cycle approximations, not exact dates._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_academic_digest(a) -> None:
    """CLI entry point for `candid academic-digest`."""
    digest = build_digest()
    if getattr(a, "json", False):
        print(json.dumps(digest, indent=2, default=str))
    else:
        print(render_digest(digest))


def add_parsers(subparsers) -> None:
    """Wire the ``academic-digest`` command. Called by the coordinator.

    ``subparsers`` is the top-level _SubParsersAction from build_parser()
    (the one holding onboard/profile/match/...). Adds a single
    ``academic-digest`` command with an optional --json flag.
    """
    p = subparsers.add_parser(
        "academic-digest",
        help="Briefing: fellowship deadlines, watched-lab hits, hiring-season milestones.")
    p.add_argument("--json", action="store_true",
                   help="Print the raw digest dict as JSON (for scripting).")
    p.set_defaults(func=cmd_academic_digest)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    parser = argparse.ArgumentParser(prog="academic-digest")
    add_parsers(parser.add_subparsers(dest="cmd", required=True))
    args = parser.parse_args(["academic-digest"])
    args.func(args)
