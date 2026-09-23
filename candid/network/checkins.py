"""Feature 8 - quarterly re-engagement planner.

Picks the contacts most worth reviving this quarter: cooling or cold
relationships with high value, ranked by value first then by how far the
warmth has slipped. Produces a concrete plan - who, why, and what to say.
"""

from __future__ import annotations

from datetime import date

from candid.network import warmth as W
from candid.network import valueadd as VA

# Contacts quieter than this count as "due for revival".
REVIVE_QUIET_DAYS = 60
# How many people to put on this week's revival list.
WEEKLY_BATCH = 5

_TIER_SUGGESTION = {
    "cold": "Re-introduce yourself with context; lead with a value-add, not an ask.",
    "cooling": "A value-add touch or a short catch-up note fits here.",
    "active": "They're fine - a light touch keeps the momentum.",
    "warm": "No revival needed; keep the normal cadence.",
}


def candidates(today: date | None = None) -> list[dict]:
    """Contacts worth reviving, ranked best-first."""
    today = today or date.today()
    out = []
    for s in W.all_warmth(today):
        last = s["days_since_last_touch"]
        quiet = last is None or last >= REVIVE_QUIET_DAYS
        slipping = s["tier"] in ("cold", "cooling")
        if quiet or slipping:
            out.append(s)
    # Value first (5..1), then lowest warmth first.
    out.sort(key=lambda s: (-s["value"], s["score"]))
    return out


def build_plan(today: date | None = None,
               batch_size: int = WEEKLY_BATCH) -> dict:
    """Build the quarterly plan: this week's batch + the backlog."""
    cands = candidates(today)
    this_week, backlog = cands[:batch_size], cands[batch_size:]
    plan = []
    for s in this_week:
        ideas = VA.suggest_ideas(s["contact_id"], n=1)
        plan.append({
            **s,
            "suggested_action": _TIER_SUGGESTION[s["tier"]],
            "idea": ideas[0] if ideas else None,
        })
    return {
        "generated": (today or date.today()).isoformat(),
        "this_week": plan,
        "backlog_count": len(backlog),
        "backlog": backlog,
        "total_candidates": len(cands),
    }


def render_plan(plan: dict) -> str:
    lines = [f"Quarterly re-engagement plan (generated {plan['generated']}):"]
    if not plan["this_week"]:
        lines.append("  Nobody needs reviving - your network is warm.")
        return "\n".join(lines)
    lines.append(f"  This week ({len(plan['this_week'])} of "
                 f"{plan['total_candidates']} candidates):")
    for p in plan["this_week"]:
        last = p["days_since_last_touch"]
        last_txt = f"{last}d quiet" if last is not None else "no touches logged"
        lines.append(f"    - {p['name']} ({p['tier']}, {p['score']}/100, "
                     f"value {p['value']}/5, {last_txt})")
        lines.append(f"      {p['suggested_action']}")
        if p["idea"]:
            lines.append(f"      Idea: [{p['idea']['kind']}] {p['idea']['title']}")
    if plan["backlog_count"]:
        lines.append(f"  Backlog: {plan['backlog_count']} more "
                     f"(run again next week).")
    return "\n".join(lines)
