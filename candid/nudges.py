"""Pending nudges: follow-ups due, stale saved jobs, quiet applications,
upcoming interviews.

Pure logic over tracker records — shared by the CLI and the dashboard.
Nothing here sends anything; nudges are suggestions the user acts on.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from candid import config as C

# After this many days of silence post-interview/offer, suggest a check-in.
FOLLOW_UP_AFTER_DAYS = 5
# A "saved" job untouched this long is probably stale.
STALE_SAVED_DAYS = 7
# An application with no response this long deserves a check-in.
QUIET_APPLIED_DAYS = 14


def _days_since(iso: str, today: date) -> int | None:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None
    return (today - d).days


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# defensive date extractors — every match is validated with date()
_DATE_RES = [
    # 2026-09-24 / 2026/09/24
    re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b"),
    # Sep 24 / September 24 / Sep 24th / Sep 24, 2026
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
               r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
               r"(?:\s*,?\s*(\d{4}))?", re.I),
]


def _extract_dates(text: str) -> list[date]:
    """Pull calendar dates out of free text. Never raises."""
    found: list[date] = []
    for rx in _DATE_RES:
        try:
            for m in rx.finditer(text or ""):
                groups = m.groups()
                if len(groups) == 3 and groups[0] and groups[0][0].isdigit() \
                        and len(groups[0]) == 4:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                else:
                    mo = _MONTHS.get(groups[0][:3].lower(), 0)
                    d = int(groups[1])
                    y = int(groups[2]) if len(groups) > 2 and groups[2] else None
                    if y is None:
                        continue  # year-less dates are too ambiguous
                    if y < 2000 or y > 2100:
                        continue
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    found.append(date(y, mo, d))
        except (ValueError, IndexError, TypeError, AttributeError):
            continue
    return found


def _scan_text_for_interview_dates(a: dict) -> list[date]:
    """Dates from notes (+ prep pack file if it exists). Never raises."""
    texts = [a.get("notes", "") or ""]
    pack = (a.get("prep_pack") or "").strip()
    if pack:
        try:
            p = Path(pack)
            if not p.is_absolute():
                p = C.PREP_PACKS_DIR / pack
            if p.exists() and p.stat().st_size < 200_000:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    out: list[date] = []
    for t in texts:
        out.extend(_extract_dates(t))
    return out


def pending_nudges(apps: list[dict] | None = None,
                   today: date | None = None) -> list[dict]:
    """Return pending nudges, most urgent first.

    Each nudge: {kind, app_id, company, role, message, action}.
    """
    from candid import tracker as T
    apps = T.list_apps() if apps is None else apps
    today = today or date.today()
    nudges: list[dict] = []

    for a in apps:
        status = a.get("status", "saved")
        quiet = _days_since(a.get("date_updated", ""), today)
        if quiet is None:
            continue
        company, role = a.get("company", ""), a.get("role", "")

        if status in ("selected_for_interview", "offer") and quiet >= FOLLOW_UP_AFTER_DAYS:
            nudges.append({
                "kind": "follow_up_due",
                "app_id": a["id"],
                "company": company,
                "role": role,
                "message": (
                    f"No update in {quiet}d on your {status.replace('_', ' ')} "
                    f"for {role} @ {company}."
                ),
                "action": "Draft a thank-you / check-in email",
                "command": f"python -m candid followup check-in --person <recruiter> --role \"{role}\" --company \"{company}\"",
            })
        elif status == "saved" and quiet >= STALE_SAVED_DAYS:
            nudges.append({
                "kind": "stale_saved",
                "app_id": a["id"],
                "company": company,
                "role": role,
                "message": f"Saved {quiet}d ago, never applied: {role} @ {company}.",
                "action": "Apply, or withdraw it from the pipeline",
                "command": f"python -m candid track update {a['id']} --status applied",
            })
        elif status == "applied" and quiet >= QUIET_APPLIED_DAYS:
            nudges.append({
                "kind": "quiet_applied",
                "app_id": a["id"],
                "company": company,
                "role": role,
                "message": f"Applied {quiet}d ago, no response: {role} @ {company}.",
                "action": "Send a polite check-in",
                "command": f"python -m candid followup check-in --person <recruiter> --role \"{role}\" --company \"{company}\"",
            })

        # interview within 3 days, mentioned in notes or the prep pack
        if status in ("applied", "selected_for_interview"):
            try:
                for d in _scan_text_for_interview_dates(a):
                    delta = (d - today).days
                    if 0 <= delta <= 3:
                        when = "today" if delta == 0 else (
                            "tomorrow" if delta == 1 else f"in {delta} days")
                        nudges.append({
                            "kind": "interview_soon",
                            "app_id": a["id"],
                            "company": company,
                            "role": role,
                            "message": (
                                f"Interview {when} ({d.isoformat()}) for "
                                f"{role} @ {company}."
                            ),
                            "action": "Review your prep pack and logistics",
                            "command": f"python -m candid prep --app-id {a['id']}",
                        })
                        break
            except Exception:
                pass  # date parsing must never break the nudge list

        # postdoc application deadline approaching (worker-2, academic track)
        try:
            if T.kind_of(a) == "postdoc" and status in ("saved", "applied"):
                d = T.parse_deadline(a.get("deadline", ""))
                if d is not None:
                    delta = (d - today).days
                    if 0 <= delta <= 14:
                        when = "today" if delta == 0 else (
                            "tomorrow" if delta == 1 else f"in {delta} days")
                        nudges.append({
                            "kind": "postdoc_deadline",
                            "app_id": a["id"],
                            "company": company,
                            "role": role,
                            "message": (
                                f"Postdoc application deadline {when} "
                                f"({d.isoformat()}) for {role} @ {company}."
                            ),
                            "action": "Draft research statement + email the PI",
                            "command": f"python -m candid track update {a['id']} --status applied",
                        })
        except Exception:
            pass  # deadline parsing must never break the nudge list

    # upcoming fellowship deadlines (worker-2 hook; pure data, offline-safe)
    try:
        from candid import fellowships as _F
        for n in _F.fellowship_deadlines(days=30, today=today):
            nudges.append(n)
    except Exception:
        pass

    order = {"interview_soon": 0, "postdoc_deadline": 1, "follow_up_due": 2,
             "fellowship_deadline": 3, "quiet_applied": 4, "stale_saved": 5}
    nudges.sort(key=lambda n: order.get(n["kind"], 9))
    return nudges


def render(nudges: list[dict]) -> str:
    if not nudges:
        return "No pending nudges. Your pipeline is quiet. 🎉"
    lines = [f"📌 {len(nudges)} pending nudge(s):", ""]
    for n in nudges:
        lines.append(f"• [{n['kind']}] {n['message']}")
        lines.append(f"  → {n['action']}: {n['command']}")
    return "\n".join(lines)
