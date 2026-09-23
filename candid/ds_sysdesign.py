"""ML system design drills for the Data Scientist track.

Six seeded scenarios (feature store for real-time ranking, batch
retraining pipeline, model serving with shadow deploy, experimentation
platform, data quality monitoring, vector search for retrieval). Each
scenario has architecture questions and a structured critique rubric
(data flow, feature engineering, training/serving skew, latency,
monitoring, feedback loops).

The interactive drill reuses the engine in candid.ds_case: it walks
through the questions, collects typed answers, and scores coverage
against the rubric with per-dimension feedback.

Everything runs locally; session reports are saved under
candid_data/ds_drill_sessions/.

Usage:
    python -m candid ds-sysdesign list
    python -m candid ds-sysdesign show feature-store
    python -m candid ds-sysdesign drill feature-store
"""

from __future__ import annotations

import json
from pathlib import Path

from candid import ds_case as _base

DATA = Path(__file__).parent / "data"


class DSSysDesignError(Exception):
    """Raised for ds-sysdesign usage errors."""


# ---------------------------------------------------------------------------
# scenario bank
# ---------------------------------------------------------------------------

def _scenarios_path() -> Path:
    p = DATA / "ds_sysdesign.json"
    if not p.exists():
        raise DSSysDesignError(
            "Scenario bank not found: candid/data/ds_sysdesign.json is missing.")
    return p


def _all_scenarios() -> list[dict]:
    return json.loads(_scenarios_path().read_text(encoding="utf-8"))["scenarios"]


def list_scenarios() -> list[dict]:
    """Lightweight rows for `ds-sysdesign list`."""
    return [{"id": s["id"], "title": s["title"], "goal": s["goal"]}
            for s in _all_scenarios()]


def get_scenario(scenario_id: str) -> dict:
    for s in _all_scenarios():
        if s["id"] == scenario_id:
            return s
    known = ", ".join(s["id"] for s in _all_scenarios())
    raise DSSysDesignError(f"Unknown scenario '{scenario_id}'. Known: {known}")


def render_scenario(s: dict) -> str:
    lines = [
        f"### {s['title']}  [{s['id']}]",
        "",
        s["context"],
        "",
        f"**Goal:** {s['goal']}",
        "",
        "**Architecture questions:**",
    ]
    for i, q in enumerate(s["questions"], 1):
        lines.append(f"  {i}. {q['question']}")
    lines += ["", "**Critique rubric:**"]
    for r in s["rubric"]:
        lines.append(f"  - {r['dimension']} (weight {r['weight']}): {r['check']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ds-sysdesign entry points (drill engine shared with ds_case)
# ---------------------------------------------------------------------------

def drill(scenario_id: str, answers: list[str] | None = None) -> dict:
    """Run an interactive drill for a scenario. Returns the session report."""
    s = get_scenario(scenario_id)
    return _base.run_drill(
        kind="ds_sysdesign",
        item_id=scenario_id,
        title=s["title"],
        context=s["context"],
        lead=f"Goal: {s['goal']}",
        probes=s["questions"],
        rubric=s["rubric"],
        answers=answers,
    )
