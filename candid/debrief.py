"""Interview debrief store: record and retrieve post-interview debriefs.

Debriefs are the integration point other workers and the future ``prep``
command will use: after a mock session or a real interview, the extractor
(``candid.debrief_extract``) condenses the transcript into a summary dict and
this module persists it against the application tracker id.

Schema (stored as a JSON list at ``candid_data/debriefs.json``, indent=2)::

    {
        "id": 1,                          # debrief id, assigned on record()
        "app_id": 7,                      # tracker application id (or null)
        "company": "Acme",
        "role": "Senior Data Scientist",
        "transcript_path": "candid_data/mock_sessions/20260922_101500_coding_two-sum.json",
        "summary": {                      # produced by candid.debrief_extract
            "key_questions": ["..."],
            "key_answers": ["..."],
            "weak_spots": ["..."],
            "action_items": ["..."],
            "one_paragraph_summary": "...",
            "enhanced": false             # true if the local-LLM layer ran
        },
        "recorded_at": "2026-09-22T20:15:00"   # ISO, local time
    }
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from candid import config as C


class DebriefError(Exception):
    """Raised for invalid debrief operations."""


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.DEBRIEFS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DebriefError(f"Debrief file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise DebriefError(f"Debrief file {p} should contain a JSON list.")
    return data


def _save(debriefs: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.DEBRIEFS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(debriefs, indent=2), encoding="utf-8")
    return p


def _next_id(debriefs: list[dict]) -> int:
    return max((d.get("id", 0) for d in debriefs), default=0) + 1


def record_debrief(app_id: int | None, company: str, role: str,
                   transcript_path: str | Path, summary: dict,
                   path: str | Path | None = None) -> dict:
    """Record a debrief for an interview. Assigns a debrief id.

    ``summary`` is the dict returned by ``candid.debrief_extract.extract``
    (or ``extract_enhanced``). Returns the stored record.
    """
    if not isinstance(summary, dict):
        raise DebriefError("summary must be the dict returned by debrief_extract.")
    debriefs = _load(path)
    rec = {
        "id": _next_id(debriefs),
        "app_id": app_id,
        "company": (company or "").strip(),
        "role": (role or "").strip(),
        "transcript_path": str(transcript_path or ""),
        "summary": summary,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    debriefs.append(rec)
    _save(debriefs, path)
    return rec


def get(debrief_id: int, path: str | Path | None = None) -> dict:
    """Return one debrief record. Raises DebriefError if missing."""
    for d in _load(path):
        if d.get("id") == debrief_id:
            return d
    raise DebriefError(f"No debrief with id {debrief_id}.")


def list_debriefs(app_id: int | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """List debriefs, newest first. Filter by application id when given."""
    debriefs = _load(path)
    if app_id is not None:
        debriefs = [d for d in debriefs if d.get("app_id") == app_id]
    return sorted(debriefs, key=lambda d: (d.get("recorded_at", ""), d.get("id", 0)),
                  reverse=True)


def weak_spots(app_id: int | None = None,
               path: str | Path | None = None) -> list[str]:
    """Aggregate weak spots across debriefs, newest first, deduped.

    Filter by ``app_id`` when given; pass None for all applications.
    """
    seen: set[str] = set()
    out: list[str] = []
    for d in list_debriefs(app_id=app_id, path=path):
        spots = (d.get("summary") or {}).get("weak_spots") or []
        for s in spots:
            key = str(s).strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                out.append(str(s))
    return out


def has_debrief(app_id: int, path: str | Path | None = None) -> bool:
    """True if at least one debrief exists for the application id."""
    return any(d.get("app_id") == app_id for d in _load(path))


def render_summary(debrief: dict) -> str:
    """Render a debrief record as a one-page plain-text debrief."""
    s = debrief.get("summary") or {}
    questions = s.get("key_questions") or []
    answers = s.get("key_answers") or []
    spots = s.get("weak_spots") or []
    actions = s.get("action_items") or []
    company = debrief.get("company", "")
    role = debrief.get("role", "")

    lines = [
        "=" * 64,
        f"INTERVIEW DEBRIEF - {company} - {role}",
        f"Debrief #{debrief.get('id')}  |  recorded {debrief.get('recorded_at', '')}",
        "=" * 64,
        "",
        "SUMMARY",
        "-------",
        s.get("one_paragraph_summary", "No summary recorded."),
        "",
        "KEY QUESTIONS & ANSWERS",
        "-----------------------",
    ]
    if questions:
        for i, q in enumerate(questions, 1):
            lines.append(f"Q{i}. {q}")
            ans = answers[i - 1] if i - 1 < len(answers) else ""
            if ans:
                lines.append(f"    A: {ans}")
            lines.append("")
    else:
        lines.append("No questions recorded.\n")

    lines += ["WEAK SPOTS", "----------"]
    if spots:
        lines += [f"- {w}" for w in spots]
    else:
        lines.append("None identified.")
    lines += ["", "ACTION ITEMS", "------------"]
    if actions:
        lines += [f"- {a}" for a in actions]
    else:
        lines.append("None recorded.")

    tpath = debrief.get("transcript_path") or ""
    if tpath:
        lines += ["", f"Transcript: {tpath}"]
    return "\n".join(lines).rstrip()
