"""ML case-interview drills for the Data Scientist track.

Eight seeded case scenarios (churn prediction, recommender, fraud
detection, ETA prediction, ad ranking, customer LTV, demand forecasting,
content moderation). Each case has business context, a core ML question,
probing questions for the key decisions, and a six-dimension scoring
rubric (problem framing, metrics choice, data/baseline, modeling,
evaluation, deployment/monitoring).

The interactive drill walks through the probes, collects typed answers,
and scores coverage against the rubric with per-dimension feedback. The
scoring is a transparent keyword-signal heuristic, and it says so.

Everything runs locally; session reports are saved under
candid_data/ds_drill_sessions/.

Usage:
    python -m candid ds-case list
    python -m candid ds-case show churn-prediction
    python -m candid ds-case drill churn-prediction
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from candid import config as C

DATA = Path(__file__).parent / "data"
SESSIONS_DIR = C.DATA_DIR / "ds_drill_sessions"


class DSCaseError(Exception):
    """Raised for ds-case usage errors."""


# ---------------------------------------------------------------------------
# case bank
# ---------------------------------------------------------------------------

def _cases_path() -> Path:
    p = DATA / "ds_cases.json"
    if not p.exists():
        raise DSCaseError("Case bank not found: candid/data/ds_cases.json is missing.")
    return p


def _all_cases() -> list[dict]:
    return json.loads(_cases_path().read_text(encoding="utf-8"))["cases"]


def list_cases() -> list[dict]:
    """Lightweight rows for `ds-case list`."""
    return [{"id": c["id"], "title": c["title"],
             "core_question": c["core_question"]} for c in _all_cases()]


def get_case(case_id: str) -> dict:
    for c in _all_cases():
        if c["id"] == case_id:
            return c
    known = ", ".join(c["id"] for c in _all_cases())
    raise DSCaseError(f"Unknown case '{case_id}'. Known: {known}")


def render_case(c: dict) -> str:
    lines = [
        f"### {c['title']}  [{c['id']}]",
        "",
        c["business_context"],
        "",
        f"**Core question:** {c['core_question']}",
        "",
        "**Probing questions:**",
    ]
    for i, pr in enumerate(c["probes"], 1):
        lines.append(f"  {i}. {pr['question']}")
    lines += ["", "**Scoring rubric:**"]
    for r in c["rubric"]:
        lines.append(f"  - {r['dimension']} (weight {r['weight']}): {r['check']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# rubric coverage scoring (shared with ds_sysdesign)
# ---------------------------------------------------------------------------

def score_coverage(text: str, rubric: list[dict]) -> dict:
    """Score rubric coverage of free text via keyword signals.

    Heuristic, and honest about it: a dimension counts as covered when the
    text mentions at least `needed` (default 2) of its signal phrases.
    """
    low = (text or "").lower()
    dims = []
    for item in rubric:
        matched = [s for s in item.get("signals", []) if s.lower() in low]
        needed = int(item.get("needed", 2))
        covered = len(matched) >= needed
        dims.append({
            "dimension": item["dimension"],
            "weight": item["weight"],
            "check": item["check"],
            "matched": matched,
            "needed": needed,
            "covered": covered,
        })
    earned = sum(d["weight"] for d in dims if d["covered"])
    total = sum(d["weight"] for d in dims)
    pct = round(100 * earned / total) if total else 0
    return {"dims": dims, "earned": earned, "total": total,
            "pct": pct, "level": _level(pct)}


def _level(pct: float) -> str:
    if pct >= 80:
        return "Strong - interview-ready on this case"
    if pct >= 60:
        return "Solid - a few gaps to close"
    if pct >= 40:
        return "Developing - notable gaps"
    return "Needs work - revisit the fundamentals"


def render_feedback(title: str, coverage: dict) -> str:
    lines = [
        "=" * 60,
        f"RUBRIC COVERAGE - {title}",
        "=" * 60,
        f"Score: {coverage['earned']}/{coverage['total']} ({coverage['pct']}%)",
        f"Level: {coverage['level']}",
        "",
        "(Heuristic: a dimension counts as covered when your answers "
        "mention its key ideas.)",
        "",
    ]
    for d in coverage["dims"]:
        icon = "OK " if d["covered"] else "MISS"
        lines.append(f"[{icon}] {d['dimension']} (weight {d['weight']})")
        if d["matched"]:
            lines.append(f"       mentioned: {', '.join(d['matched'])}")
        if not d["covered"]:
            lines.append(f"       work on: {d['check']}")
    missed = [d for d in coverage["dims"] if not d["covered"]]
    if missed:
        lines += ["", "Study next:"]
        for d in missed:
            lines.append(f"  - {d['dimension']}: {d['check']}")
    else:
        lines += ["", "Clean sweep - every rubric dimension covered."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# interactive drill (shared with ds_sysdesign)
# ---------------------------------------------------------------------------

def read_answer_interactive(n: int, total: int) -> str:
    print(f"Your answer [{n}/{total}] - type it as you would speak it.")
    print("End with a line containing only EOF, or press Ctrl-D. "
          "Empty answer = skip.")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def run_drill(kind: str, item_id: str, title: str, context: str, lead: str,
              probes: list[dict], rubric: list[dict],
              answers: list[str] | None = None) -> dict:
    """Shared drill engine.

    kind: "ds_case" or "ds_sysdesign" (used in the session report).
    lead: the core question / goal line shown up front.
    probes: [{"question": ..., "strong": ...}, ...].
    answers: when given, bypasses stdin (used by tests and scripting).
    Returns the session report dict.
    """
    print(f"### Drill: {title}\n")
    print(context)
    print(f"\n{lead}\n")
    print("Answer each probe out loud or type it below. "
          "After the drill you get rubric coverage feedback.\n")

    collected: list[str] = []
    for i, pr in enumerate(probes, 1):
        print(f"--- Probe {i}/{len(probes)} ---")
        print(f"Q: {pr['question']}\n")
        if answers is not None:
            ans = answers[i - 1] if i - 1 < len(answers) else ""
        else:
            ans = read_answer_interactive(i, len(probes))
            strong = pr.get("strong", "")
            if strong:
                print(f"\nStrong answers touch on: {strong}\n")
            else:
                print()
        collected.append(ans)

    # Score the answers only - never the probe questions themselves.
    coverage = score_coverage("\n\n".join(collected), rubric)
    report = {
        "kind": kind,
        "item": item_id,
        "title": title,
        "at": datetime.now().isoformat(timespec="seconds"),
        "answers": collected,
        "coverage": {
            "earned": coverage["earned"],
            "total": coverage["total"],
            "pct": coverage["pct"],
            "level": coverage["level"],
            "dims": [
                {"dimension": d["dimension"], "covered": d["covered"],
                 "matched": d["matched"]}
                for d in coverage["dims"]
            ],
        },
    }
    path = _save_session(report)
    print(render_feedback(title, coverage))
    print(f"\nSession saved to {path}")
    return report


def _save_session(report: dict) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SESSIONS_DIR / f"{stamp}_{report['kind']}_{report['item']}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# ds-case entry points
# ---------------------------------------------------------------------------

def drill(case_id: str, answers: list[str] | None = None) -> dict:
    """Run an interactive drill for a case. Returns the session report."""
    case = get_case(case_id)
    return run_drill(
        kind="ds_case",
        item_id=case_id,
        title=case["title"],
        context=case["business_context"],
        lead=f"Core question: {case['core_question']}",
        probes=case["probes"],
        rubric=case["rubric"],
        answers=answers,
    )
