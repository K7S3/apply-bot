"""Feature 4 - relationship warmth tracking.

Warmth is a 0-100 score per contact: every logged touchpoint adds warmth
weighted by kind, and warmth decays exponentially with a configurable
half-life (default 45 days, via CANDID_WARMTH_HALF_LIFE). Meeting someone
recently also counts as a small touch.

Tiers: warm (>=70), active (>=40), cooling (>=15), cold (<15).
"""

from __future__ import annotations

import os
from datetime import date

from candid.network import touchpoints as TP
from candid.network import contacts as CT


def half_life_days() -> float:
    try:
        return max(1.0, float(os.environ.get("CANDID_WARMTH_HALF_LIFE", "45")))
    except ValueError:
        return 45.0


def tier(score: float) -> str:
    if score >= 70:
        return "warm"
    if score >= 40:
        return "active"
    if score >= 15:
        return "cooling"
    return "cold"


def warmth_score(contact_id: int, today: date | None = None) -> float:
    """Compute the 0-100 warmth score for a contact."""
    today = today or date.today()
    hl = half_life_days()
    total = 0.0
    for t in TP.touchpoints_for(contact_id):
        days = (today - date.fromisoformat(t["happened_on"])).days
        if days < 0:
            continue  # future-dated touches don't count yet
        weight = TP.KIND_WEIGHTS.get(t["kind"], 1.0)
        total += weight * 25.0 * (0.5 ** (days / hl))
    # Meeting them counts as a small initial touch.
    try:
        contact = CT.get_contact(contact_id)
        met_days = (today - date.fromisoformat(contact["met_at"])).days
        if met_days >= 0:
            total += 12.0 * (0.5 ** (met_days / hl))
    except ValueError:
        pass
    return round(min(100.0, total), 1)


def warmth_summary(contact_id: int, today: date | None = None) -> dict:
    contact = CT.get_contact(contact_id)
    score = warmth_score(contact_id, today)
    return {
        "contact_id": contact["id"],
        "name": contact["name"],
        "score": score,
        "tier": tier(score),
        "days_since_last_touch": TP.days_since_last_touch(contact_id, today),
        "touch_count": len(TP.touchpoints_for(contact_id)),
        "value": contact["value"],
    }


def all_warmth(today: date | None = None) -> list[dict]:
    """Warmth summaries for every contact, warmest first."""
    out = [warmth_summary(c["id"], today) for c in CT.list_contacts()]
    return sorted(out, key=lambda s: s["score"], reverse=True)


def render_warmth(summary: dict) -> str:
    last = summary["days_since_last_touch"]
    last_txt = f"{last}d ago" if last is not None else "never"
    return (f"{summary['name']}: {summary['score']}/100 "
            f"({summary['tier']}, last touch {last_txt}, "
            f"{summary['touch_count']} touches, value {summary['value']}/5)")
