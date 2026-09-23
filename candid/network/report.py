"""Feature 10 - networking activity report.

Aggregate stats over the contact book: growth, touchpoint mix, warmth
distribution, sequence completion. Rendered as Markdown, optionally
exported to a file.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from candid.network import _store as S
from candid.network import contacts as CT
from candid.network import sequences as SQ
from candid.network import touchpoints as TP
from candid.network import warmth as W


def stats(today: date | None = None, window_days: int = 90) -> dict:
    today = today or date.today()
    window_start = (today - timedelta(days=window_days)).isoformat()
    contacts = CT.list_contacts()
    touches = TP.all_touchpoints()
    recent = [t for t in touches if t["happened_on"] >= window_start]
    new_contacts = [c for c in contacts
                    if c.get("created_at", "") >= window_start]
    warmth = W.all_warmth(today)
    tiers = Counter(s["tier"] for s in warmth)
    seqs = SQ.list_sequences()
    seq_done = sum(1 for s in seqs
                   if all(st["status"] in ("done", "skipped") for st in s["steps"]))
    avg_warmth = round(sum(s["score"] for s in warmth) / len(warmth), 1) \
        if warmth else 0.0
    return {
        "as_of": today.isoformat(),
        "window_days": window_days,
        "contacts_total": len(contacts),
        "contacts_new": len(new_contacts),
        "touchpoints_total": len(touches),
        "touchpoints_recent": len(recent),
        "touchpoints_by_kind": dict(Counter(t["kind"] for t in recent)),
        "avg_warmth": avg_warmth,
        "warmth_tiers": dict(tiers),
        "sequences_total": len(seqs),
        "sequences_completed": seq_done,
        "warmest": [{"name": s["name"], "score": s["score"],
                     "tier": s["tier"]} for s in warmth[:5]],
        "coldest_valuable": [
            {"name": s["name"], "score": s["score"], "tier": s["tier"],
             "value": s["value"]}
            for s in sorted(warmth, key=lambda x: x["score"])
            if s["value"] >= 4][:5],
    }


def render_report(st: dict) -> str:
    lines = [
        f"# Networking report ({st['as_of']}, last {st['window_days']}d)",
        "",
        f"- Contacts: **{st['contacts_total']}** "
        f"({st['contacts_new']} new in window)",
        f"- Touchpoints: **{st['touchpoints_recent']}** in window "
        f"({st['touchpoints_total']} all time)",
        f"- Average warmth: **{st['avg_warmth']}/100**",
        f"- Warmth tiers: " + (", ".join(
            f"{t}: {n}" for t, n in sorted(st["warmth_tiers"].items()))
            if st["warmth_tiers"] else "- Warmth tiers: none yet"),
        f"- Sequences: **{st['sequences_completed']}/{st['sequences_total']}** completed",
        "",
        "## Touchpoint mix (window)",
    ]
    if st["touchpoints_by_kind"]:
        for kind, n in sorted(st["touchpoints_by_kind"].items(),
                              key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {kind}: {n}")
    else:
        lines.append("- none logged yet")
    lines.append("")
    lines.append("## Warmest relationships")
    for w in st["warmest"]:
        lines.append(f"- {w['name']}: {w['score']}/100 ({w['tier']})")
    if not st["warmest"]:
        lines.append("- none yet")
    lines.append("")
    lines.append("## Coldest high-value contacts (revive these)")
    for w in st["coldest_valuable"]:
        lines.append(f"- {w['name']}: {w['score']}/100 ({w['tier']}, "
                     f"value {w['value']}/5)")
    if not st["coldest_valuable"]:
        lines.append("- none - all high-value contacts are warm")
    return "\n".join(lines)


def export_report(today: date | None = None, window_days: int = 90,
                  path: str | None = None) -> Path:
    st = stats(today, window_days)
    md = render_report(st)
    out = Path(path) if path else \
        S.net_dir() / f"network-report-{st['as_of']}.md"
    out.write_text(md, encoding="utf-8")
    return out
