"""Feature 6 - follow-up reminders.

One view of everything networking-related that needs attention:
sequence steps that are due (overdue / today / upcoming) plus
re-engagement nudges for valuable contacts whose warmth is slipping.
"""

from __future__ import annotations

from datetime import date, timedelta

from candid.network import sequences as SQ
from candid.network import touchpoints as TP
from candid.network import warmth as W
from candid.network import contacts as CT

# Contacts this valuable (or more) get nudged when they go quiet.
REENGAGE_VALUE_MIN = 3
# Days of silence before a warm/active contact is flagged.
REENGAGE_QUIET_DAYS = 45


def _bucket(due_iso: str, today: date) -> str:
    due = date.fromisoformat(due_iso)
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    return "upcoming"


def due_followups(today: date | None = None,
                  upcoming_days: int = 7) -> dict:
    """Sequence steps needing attention, bucketed by urgency."""
    today = today or date.today()
    horizon = today + timedelta(days=upcoming_days)
    buckets: dict[str, list[dict]] = {"overdue": [], "today": [], "upcoming": []}
    for seq, step in SQ.due_steps(horizon):
        bucket = _bucket(step["due"], today)
        if bucket == "upcoming" and date.fromisoformat(step["due"]) > horizon:
            continue
        try:
            contact = CT.get_contact(seq["contact_id"])
            name = contact["name"]
        except ValueError:
            name = f"contact #{seq['contact_id']}"
        buckets[bucket].append({
            "seq_id": seq["id"],
            "step_idx": seq["steps"].index(step),
            "contact": name,
            "template": seq["template"],
            "title": step["title"],
            "kind": step["kind"],
            "due": step["due"],
            "guidance": step["guidance"],
        })
    return buckets


def reengagement_nudges(today: date | None = None) -> list[dict]:
    """Valuable contacts going quiet - nudges before they go cold."""
    today = today or date.today()
    nudges = []
    for summary in W.all_warmth(today):
        if summary["value"] < REENGAGE_VALUE_MIN:
            continue
        last = summary["days_since_last_touch"]
        if last is None:
            nudges.append({**summary, "reason": "never logged a touchpoint",
                           "suggestion": "Log your first interaction or send an intro note."})
        elif last >= REENGAGE_QUIET_DAYS and summary["tier"] in ("cooling", "cold", "active"):
            nudges.append({**summary,
                           "reason": f"{last} days since last touch",
                           "suggestion": "Send a value-add touch - try "
                                         "`candid network value-add "
                                         f"{summary['contact_id']}`."})
    nudges.sort(key=lambda n: (n["days_since_last_touch"] is not None,
                               n["days_since_last_touch"] or 0), reverse=True)
    return nudges


def render_due(today: date | None = None, upcoming_days: int = 7) -> str:
    buckets = due_followups(today, upcoming_days)
    nudges = reengagement_nudges(today)
    lines = ["Networking follow-ups due:"]
    total_steps = sum(len(v) for v in buckets.values())
    if total_steps == 0:
        lines.append("  Nothing due - your sequences are all clear.")
    for bucket in ("overdue", "today", "upcoming"):
        items = buckets[bucket]
        if not items:
            continue
        lines.append(f"  {bucket.upper()} ({len(items)}):")
        for it in items:
            lines.append(f"    - {it['contact']}: {it['title']} "
                         f"(due {it['due']}) [seq {it['seq_id']} step {it['step_idx']}]")
    if nudges:
        lines.append(f"\nRe-engagement nudges ({len(nudges)}):")
        for n in nudges:
            lines.append(f"  - {n['name']} ({n['tier']}, {n['score']}/100): "
                         f"{n['reason']}. {n['suggestion']}")
    else:
        lines.append("\nNo re-engagement nudges - nobody valuable is going quiet.")
    return "\n".join(lines)
