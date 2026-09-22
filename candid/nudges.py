"""Pending nudges: follow-ups due, stale saved jobs, quiet applications.

Pure logic over tracker records — shared by the CLI and the dashboard.
Nothing here sends anything; nudges are suggestions the user acts on.
"""

from __future__ import annotations

from datetime import date, timedelta

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

    order = {"follow_up_due": 0, "quiet_applied": 1, "stale_saved": 2}
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
