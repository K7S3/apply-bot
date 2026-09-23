"""Debrief reminders: which interviews are missing a debrief, and markdown export.

Core idea: an interview is a memory that fades fast. Any application whose
tracker status (or notes) says an interview *happened* in the last N days,
but which has no debrief recorded in the debrief store
(``candid.debrief``, built by worker C), shows up in ``debrief due`` and in
the nudge flow.

Everything here degrades gracefully when the debrief store is absent:
``has_debrief`` is treated as False and nothing raises.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from candid import config as C

# Statuses that imply an interview already happened (tracker.py only ships a
# handful of statuses today, so we also keep forward-compatible aliases for
# statuses other workers may add, e.g. "interviewed" or "onsite").
INTERVIEW_HAPPENED_STATUSES = {
    "offer",           # an offer means interviews happened
    "interview",
    "interviewed",
    "onsite",
}

# "selected_for_interview" is ambiguous (upcoming vs past), so it is only
# counted when a past interview date is found in the notes / prep pack.
UPCOMING_INTERVIEW_STATUS = "selected_for_interview"


class DebriefDueError(Exception):
    """Raised when a debrief cannot be found or exported."""


def _days_since(iso: str, today: date) -> int | None:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None
    return (today - d).days


def _has_debrief(app_id: int, store=None) -> bool:
    """True if a debrief is recorded for the app. Never raises.

    ``store`` is an optional override callable (app_id) -> bool, used by
    tests. Without it we import ``candid.debrief`` defensively: a missing
    store means "no debriefs recorded".
    """
    if store is not None:
        try:
            return bool(store(app_id))
        except Exception:
            return False
    try:
        from candid import debrief as D
    except ImportError:
        return False
    try:
        return bool(D.has_debrief(app_id))
    except Exception:
        return False


def _past_interview_date(app: dict, today: date) -> date | None:
    """Most recent interview date mentioned in notes/prep pack that is past."""
    try:
        from candid import nudges as N
    except ImportError:
        return None
    try:
        past = [d for d in N._scan_text_for_interview_dates(app) if d <= today]
    except Exception:
        return None
    return max(past) if past else None


def interview_event(app: dict, today: date) -> date | None:
    """Date the interview happened for this app, or None if it didn't.

    - status in INTERVIEW_HAPPENED_STATUSES -> the status-change date
      (date_updated is the best proxy we store).
    - status == "selected_for_interview" -> the latest past interview date
      found in notes / prep pack.
    - anything else -> None.
    """
    status = app.get("status", "")
    if status in INTERVIEW_HAPPENED_STATUSES:
        upd = _days_since(app.get("date_updated", ""), today)
        if upd is None or upd < 0:
            return None
        return today - timedelta(days=upd)
    if status == UPCOMING_INTERVIEW_STATUS:
        return _past_interview_date(app, today)
    return None


def interviews_due(apps: list[dict] | None = None,
                   today: date | None = None,
                   days: int = 7,
                   has_debrief=None) -> list[dict]:
    """Applications with a recent interview but no debrief recorded.

    Each item: {app, interview_date (iso), days_since}.
    Most recent first. Never raises.
    """
    from candid import tracker as T
    try:
        apps = T.list_apps() if apps is None else apps
    except Exception:
        return []
    today = today or date.today()
    due: list[dict] = []
    for a in apps:
        try:
            event = interview_event(a, today)
            if event is None:
                continue
            since = (today - event).days
            if since < 0 or since > days:
                continue
            if _has_debrief(a.get("id"), store=has_debrief):
                continue
            due.append({
                "app": a,
                "interview_date": event.isoformat(),
                "days_since": since,
            })
        except Exception:
            continue  # one bad record must not break the whole list
    due.sort(key=lambda d: d["days_since"])
    return due


def render_due(due: list[dict], days: int = 7) -> str:
    if not due:
        return (f"No interviews from the last {days} day(s) are missing a "
                "debrief. 🎉")
    lines = [f"📝 {len(due)} interview(s) still need a debrief:", ""]
    for d in due:
        a = d["app"]
        when = ("today" if d["days_since"] == 0
                else f"{d['days_since']} day(s) ago ({d['interview_date']})")
        lines.append(
            f"• #{a.get('id')}: {a.get('role', '')} @ {a.get('company', '')} "
            f"— interview {when}")
    lines += ["", "Record one while it's fresh; it feeds your prep packs.",
              "See docs/debrief_voice.md for the guided voice/text flow."]
    return "\n".join(lines)


def debrief_nudges(apps: list[dict] | None = None,
                   today: date | None = None,
                   days: int = 7,
                   has_debrief=None) -> list[dict]:
    """Nudge dicts (kind='debrief_due') for the existing reminder flow.

    Shape matches nudges.pending_nudges(): {kind, app_id, company, role,
    message, action, command}. ``has_debrief`` is an optional
    (app_id) -> bool override (tests). Never raises.
    """
    out: list[dict] = []
    try:
        for d in interviews_due(apps=apps, today=today, days=days,
                                has_debrief=has_debrief):
            a = d["app"]
            company, role = a.get("company", ""), a.get("role", "")
            when = ("today" if d["days_since"] == 0
                    else f"{d['days_since']} day(s) ago")
            out.append({
                "kind": "debrief_due",
                "app_id": a.get("id"),
                "company": company,
                "role": role,
                "message": (f"Debrief your {role} @ {company} interview "
                            f"({when}) while it's fresh."),
                "action": "Capture what happened and your weak spots",
                "command": "python -m candid debrief due",
            })
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# markdown export
# ---------------------------------------------------------------------------

def _exports_dir() -> Path:
    """Debrief markdown exports live under the (possibly rebound) data dir."""
    d = C.DATA_DIR / "debrief_exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


_MAX_TRANSCRIPT_CHARS = 8000


def _load_debrief(debrief_id: int) -> dict:
    """Fetch a debrief by debrief id, falling back to newest for an app id."""
    try:
        from candid import debrief as D
    except ImportError:
        raise DebriefDueError(
            "The debrief store (candid/debrief.py) is not available — "
            "nothing to export.") from None
    try:
        return D.get(debrief_id)
    except Exception:
        pass
    # maybe the user meant a tracker app id: export its newest debrief
    try:
        recs = D.list_debriefs(app_id=debrief_id)
    except Exception:
        recs = []
    if recs:
        return recs[0]
    raise DebriefDueError(
        f"No debrief with id {debrief_id} (also not a tracker id with a "
        "debrief).")


def _transcript_text(debrief: dict) -> str:
    """Transcript content as markdown, truncated. Never raises."""
    tpath = (debrief.get("transcript_path") or "").strip()
    if not tpath:
        return "_No transcript recorded._"
    try:
        p = Path(tpath)
        if not p.exists():
            return f"_Transcript file not found: {tpath}_"
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return f"_Could not read transcript: {tpath}_"
    # mock sessions store a JSON list of {prompt, answer} turns
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            lines = []
            for i, turn in enumerate(data, 1):
                if not isinstance(turn, dict):
                    continue
                prompt = str(turn.get("prompt", "")).strip()
                answer = str(turn.get("answer", "")).strip()
                if prompt:
                    lines.append(f"**Q{i}.** {prompt}")
                if answer:
                    lines.append(f"> {answer}")
                lines.append("")
            text = "\n".join(lines).strip()
            if text:
                return text
    except (json.JSONDecodeError, ValueError):
        pass
    if len(raw) > _MAX_TRANSCRIPT_CHARS:
        raw = raw[:_MAX_TRANSCRIPT_CHARS] + "\n\n…(truncated)"
    return "```\n" + raw.strip() + "\n```"


def export_debrief_markdown(debrief_id: int, out: str | Path | None = None,
                            fmt: str = "md") -> Path:
    """Export transcript + summary + weak spots as Markdown under the data dir.

    Returns the written path. Raises DebriefDueError when the store is
    absent or the id is unknown.
    """
    if fmt != "md":
        raise DebriefDueError(f"Unsupported export format {fmt!r} (only 'md').")
    d = _load_debrief(debrief_id)
    s = d.get("summary") or {}
    company = d.get("company", "")
    role = d.get("role", "")
    lines = [
        f"# Interview Debrief — {role} @ {company}",
        (f"*Debrief #{d.get('id')} · recorded {d.get('recorded_at', '')}"
         + (f" · tracker app #{d.get('app_id')}" if d.get("app_id") else "")
         + "*"),
        "",
        "## Summary",
        "",
        s.get("one_paragraph_summary") or "_No summary recorded._",
        "",
        "## Key questions & answers",
        "",
    ]
    questions = s.get("key_questions") or []
    answers = s.get("key_answers") or []
    if questions:
        for i, q in enumerate(questions, 1):
            lines.append(f"**Q{i}.** {q}")
            if i - 1 < len(answers) and answers[i - 1]:
                lines.append(f"> {answers[i - 1]}")
            lines.append("")
    else:
        lines.append("_No questions recorded._\n")
    lines += ["## Weak spots", ""]
    spots = s.get("weak_spots") or []
    lines += [f"- {w}" for w in spots] if spots else ["_None identified._"]
    lines += ["", "## Action items", ""]
    actions = s.get("action_items") or []
    lines += [f"- {a}" for a in actions] if actions else ["_None recorded._"]
    lines += ["", "## Transcript", "", _transcript_text(d), ""]
    markdown = "\n".join(lines)

    _exports_dir()
    if out is None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in f"{company}-{role}")[:40]
        out = _exports_dir() / f"debrief_{d.get('id')}_{safe}.md"
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown, encoding="utf-8")
    return p
