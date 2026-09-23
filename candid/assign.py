"""Take-home assignment planner: structure, milestones, time-boxing, review.

candid plans and organizes your take-home assignment. It never writes the
assignment for you: there is no code generation, no solution sketching, no
answer key. ``assign solve`` exists only to say so out loud.

Given an assignment type and a deadline, the planner produces:

- a milestone breakdown with calendar due dates,
- a day-by-day time-boxed schedule (with a submission buffer held back),
- a workload fit check (required hours vs. the hours you actually have),
- a project file map and README skeleton (structure, never content),
- a self-review rubric you run yourself before submitting.

Plans persist under ``DATA_DIR / "assignments.json"`` (git-ignored).
Everything here is offline and deterministic.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C


class AssignError(Exception):
    """Raised for invalid planner input or operations."""


def _data_dir() -> Path:
    """Resolve the data dir at call time so CANDID_DATA_DIR always wins."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _store_path() -> Path:
    return _data_dir() / "assignments.json"


def _load() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        raise AssignError(
            f"Could not read {p}. Delete it or fix the JSON to continue."
        )
    return data if isinstance(data, list) else []


def _save(plans: list[dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plans, indent=2))


def _next_id(plans: list[dict]) -> int:
    return max((pl["id"] for pl in plans), default=0) + 1


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
#
# Each template is an assignment archetype: typical total hours, phases with
# hour shares (must sum to 1.0), a file map (names only, never code), a
# README skeleton, and review rubric items. Nothing here tells you *how* to
# solve anything; it tells you how to organize the work.

TEMPLATES: dict[str, dict] = {
    "data-pipeline": {
        "label": "Data pipeline",
        "blurb": "Ingest, transform, and load/serve a dataset (ETL/ELT style).",
        "typical_hours": 12.0,
        "keywords": ["pipeline", "etl", "elt", "ingest", "transform", "csv",
                     "parquet", "dataset", "dataframe", "pandas", "spark"],
        "phases": [
            ("Understand and scope", 0.15,
             "Re-read the prompt twice. List the required inputs, outputs, "
             "and edge cases. Decide what is explicitly out of scope and "
             "write that down so you do not gold-plate."),
            ("Scaffold and I/O", 0.20,
             "Project layout, dependency file, and the read/write path "
             "end to end on a tiny sample before any real logic."),
            ("Core transforms", 0.30,
             "The main transformation logic, one rule at a time, checking "
             "output against a hand-computed example as you go."),
            ("Edge cases and tests", 0.15,
             "Empty inputs, malformed rows, duplicates, type surprises. "
             "A few focused tests that prove each one is handled."),
            ("README and packaging", 0.10,
             "Run instructions from a clean checkout, approach and "
             "tradeoffs, what you would do with more time."),
            ("Self-review and submit", 0.10,
             "Run the rubric below, re-read the prompt once more, then "
             "package and submit inside the buffer window."),
        ],
        "file_map": ["README.md", "requirements.txt", ".gitignore",
                     "src/pipeline.py", "src/__init__.py",
                     "tests/test_pipeline.py", "data/sample_input.csv"],
        "readme_sections": ["What this does", "How to run",
                            "Input and output format", "Approach and tradeoffs",
                            "What I would do with more time", "Time spent"],
        "review": [
            ("io-roundtrip", "I/O works from a clean checkout",
             "Clone into a fresh directory (or wipe outputs) and run your "
             "own instructions exactly as written."),
            ("edge-cases", "Edge cases handled and named",
             "Empty input, malformed rows, duplicates: each either handled "
             "or explicitly listed as out of scope in the README."),
            ("determinism", "Output is deterministic",
             "Run it twice on the same input and diff the outputs."),
        ],
    },
    "rest-api": {
        "label": "REST API",
        "blurb": "Design and implement a small HTTP service with endpoints.",
        "typical_hours": 10.0,
        "keywords": ["api", "rest", "endpoint", "http", "flask", "fastapi",
                     "server", "crud", "json api"],
        "phases": [
            ("Understand and scope", 0.15,
             "List every endpoint, its inputs, and its expected responses "
             "before writing code. Decide auth/persistence simplifications "
             "and note them."),
            ("Scaffold and one endpoint", 0.20,
             "Framework skeleton, one working endpoint with a manual smoke "
             "test via curl or the docs UI."),
            ("Remaining endpoints", 0.30,
             "Implement the rest one at a time, smoke-testing each before "
             "moving on."),
            ("Validation and errors", 0.15,
             "Bad input, missing fields, not-found cases: every endpoint "
             "returns a sensible status code and message."),
            ("README and packaging", 0.10,
             "Run instructions, endpoint table with examples, approach and "
             "tradeoffs."),
            ("Self-review and submit", 0.10,
             "Run the rubric below, re-read the prompt once more, then "
             "package and submit inside the buffer window."),
        ],
        "file_map": ["README.md", "requirements.txt", ".gitignore",
                     "src/app.py", "src/__init__.py",
                     "tests/test_api.py"],
        "readme_sections": ["What this does", "How to run",
                            "Endpoints (method, path, example)",
                            "Approach and tradeoffs",
                            "What I would do with more time", "Time spent"],
        "review": [
            ("endpoint-table", "Every endpoint documented with an example",
             "Method, path, sample request and response for each one."),
            ("error-codes", "Errors return sensible status codes",
             "400 for bad input, 404 for missing resources, no stack "
             "traces leaked to the client."),
            ("clean-run", "Service starts from a clean checkout",
             "Follow your own README steps exactly, in a fresh directory."),
        ],
    },
    "web-app": {
        "label": "Web app",
        "blurb": "A small front-end (plus any backend it needs) for a user task.",
        "typical_hours": 14.0,
        "keywords": ["frontend", "front-end", "react", "ui", "web app",
                     "website", "dashboard ui", "single-page"],
        "phases": [
            ("Understand and scope", 0.15,
             "List the user flows the prompt actually requires. Sketch "
             "each screen on paper before touching code; cut ruthlessly."),
            ("Scaffold and first screen", 0.20,
             "Project skeleton, routing, and the single most important "
             "screen working end to end."),
            ("Remaining screens and flows", 0.30,
             "Build the other required flows one at a time, clicking "
             "through each like a reviewer would."),
            ("Polish and edge states", 0.15,
             "Loading, empty, and error states. Mobile-ish widths if the "
             "role cares about them."),
            ("README and packaging", 0.10,
             "Run instructions, what was built and what was cut, approach "
             "and tradeoffs."),
            ("Self-review and submit", 0.10,
             "Run the rubric below, re-read the prompt once more, then "
             "package and submit inside the buffer window."),
        ],
        "file_map": ["README.md", "package.json", ".gitignore",
                     "src/App.jsx", "src/components/", "src/styles.css"],
        "readme_sections": ["What this does", "How to run",
                            "User flows implemented",
                            "What was cut and why", "Approach and tradeoffs",
                            "What I would do with more time", "Time spent"],
        "review": [
            ("happy-path", "Every required flow works by clicking",
             "Walk each required user flow start to finish like a "
             "reviewer with no context."),
            ("edge-states", "Loading, empty, and error states exist",
             "No blank screens or silent failures on the required flows."),
            ("scope-cut", "Cuts are documented, not hidden",
             "Anything the prompt asked for that you skipped is named in "
             "the README with a one-line reason."),
        ],
    },
    "ml-model": {
        "label": "ML model",
        "blurb": "Train and evaluate a model on a provided dataset.",
        "typical_hours": 12.0,
        "keywords": ["model", "machine learning", "ml", "train", "classifier",
                     "regression", "sklearn", "pytorch", "dataset", "accuracy",
                     "prediction"],
        "phases": [
            ("Understand and scope", 0.15,
             "Define the target metric and the baseline you must beat. "
             "Check the data for leaks, missing values, and label quality."),
            ("Baseline and evaluation", 0.20,
             "A dumb baseline (majority class, mean) with a proper "
             "train/validation split before any real modeling."),
            ("Feature work and modeling", 0.30,
             "Iterate on features and one or two models. Track every "
             "experiment's validation score in a few lines of notes."),
            ("Error analysis", 0.15,
             "Look at actual mistakes the model makes. One round of "
             "targeted fixes beats three rounds of blind tuning."),
            ("README and packaging", 0.10,
             "How to reproduce (seed, commands), metric table, approach "
             "and tradeoffs."),
            ("Self-review and submit", 0.10,
             "Run the rubric below, re-read the prompt once more, then "
             "package and submit inside the buffer window."),
        ],
        "file_map": ["README.md", "requirements.txt", ".gitignore",
                     "src/train.py", "src/evaluate.py", "src/features.py",
                     "notebooks/exploration.ipynb"],
        "readme_sections": ["What this does", "How to reproduce",
                            "Metric table (baseline vs final)",
                            "Approach and tradeoffs",
                            "What I would do with more time", "Time spent"],
        "review": [
            ("reproducible", "Results reproduce from a clean checkout",
             "Fixed seed, documented commands, same metric when re-run."),
            ("baseline-beaten", "A baseline is reported and beaten",
             "The README shows the dumb baseline's score next to yours."),
            ("no-leak", "No train/test leakage",
             "You can say exactly how the split was made and why no "
             "information leaks across it."),
        ],
    },
    "algorithm-pack": {
        "label": "Algorithm problem set",
        "blurb": "A set of timed coding problems to solve independently.",
        "typical_hours": 6.0,
        "keywords": ["algorithm", "coding challenge", "leetcode",
                     "problem set", "data structure", "hackerrank"],
        "phases": [
            ("Understand and scope", 0.20,
             "Read every problem fully before starting any. Rank them by "
             "difficulty and decide your time budget per problem."),
            ("Solve easy first", 0.30,
             "Bank the easy wins under time pressure to build momentum."),
            ("Tackle the hard ones", 0.30,
             "Time-box each hard problem. If you stall past the box, write "
             "down your approach and move on; partial reasoning counts."),
            ("Test and clean up", 0.10,
             "Edge cases per problem, remove debug prints, make sure each "
             "solution runs as submitted."),
            ("Self-review and submit", 0.10,
             "Run the rubric below, re-read each problem statement once "
             "more, then submit inside the buffer window."),
        ],
        "file_map": ["README.md", "solutions/problem_1.py",
                     "solutions/problem_2.py", "notes/approaches.md"],
        "readme_sections": ["Problem list", "Approach per problem",
                            "Time spent per problem"],
        "review": [
            ("all-attempted", "Every problem has an attempt",
             "Even a partial approach note beats a blank submission."),
            ("edge-cases", "Edge cases tested per problem",
             "Empty input, single element, max constraints: at least "
             "thought through for each."),
            ("clean-submit", "Submissions are clean",
             "No debug prints, no commented-out experiments, each file "
             "runs standalone."),
        ],
    },
    "generic": {
        "label": "Generic take-home",
        "blurb": "Anything else: scope it, build it, document it.",
        "typical_hours": 10.0,
        "keywords": [],
        "phases": [
            ("Understand and scope", 0.20,
             "Re-read the prompt twice. Write down exactly what done "
             "looks like and what is out of scope."),
            ("Scaffold the skeleton", 0.20,
             "Project layout and the thinnest end-to-end path working "
             "before any depth."),
            ("Core work", 0.30,
             "The main deliverable, built in small verifiable steps."),
            ("Harden and document", 0.15,
             "Edge cases, cleanup, and a README someone else could "
             "follow."),
            ("Self-review and submit", 0.15,
             "Run the rubric below, re-read the prompt once more, then "
             "package and submit inside the buffer window."),
        ],
        "file_map": ["README.md", "requirements.txt", ".gitignore",
                     "src/", "tests/"],
        "readme_sections": ["What this does", "How to run",
                            "Approach and tradeoffs",
                            "What I would do with more time", "Time spent"],
        "review": [
            ("requirements-met", "Every requirement is visibly met",
             "Go through the prompt line by line and confirm each one."),
            ("clean-run", "It runs from a clean checkout",
             "Follow your own README steps exactly, in a fresh directory."),
            ("scope-honest", "Cuts and caveats are documented",
             "Anything skipped or simplified is named with a reason."),
        ],
    },
}

#: Review items every template shares, checked in addition to the
#: template-specific ones.
GLOBAL_REVIEW = [
    ("prompt-reread", "Re-read the prompt one final time",
     "Check each requirement against what you actually built."),
    ("time-box", "Stayed inside the time box",
     "Note where the time went; resist the urge to keep polishing past "
     "the buffer."),
    ("no-secrets", "No secrets or personal data in the submission",
     "API keys, tokens, and personal files do not belong in the repo or "
     "zip you send."),
]

#: Fraction of available time held back as the submission buffer.
BUFFER_FRACTION = 0.10

SOLVE_REFUSAL = (
    "candid plans and organizes take-home assignments; it does not do them "
    "for you. There is no solve/code/write command, and there never will "
    "be: the work has to be yours for the submission to mean anything.\n\n"
    "What candid *can* do:\n"
    "  python -m candid assign templates            # pick a structure template\n"
    "  python -m candid assign plan --template rest-api --company Acme "
    "--role \"Backend Engineer\" --deadline 2026-09-29 --hours-per-day 3\n"
    "  python -m candid assign schedule --id 1      # day-by-day time boxes\n"
    "  python -m candid assign review --id 1        # self-review rubric\n"
)


# ---------------------------------------------------------------------------
# Templates: read API
# ---------------------------------------------------------------------------

def list_templates() -> list[dict]:
    """Summaries of every assignment template."""
    return [
        {"name": name,
         "label": t["label"],
         "blurb": t["blurb"],
         "typical_hours": t["typical_hours"],
         "phases": len(t["phases"])}
        for name, t in TEMPLATES.items()
    ]


def get_template(name: str) -> dict:
    """Full template dict; raises AssignError on unknown name."""
    key = (name or "").strip().lower().replace("_", "-")
    if key not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise AssignError(
            f"Unknown template {name!r}. Known templates: {known}. "
            "See `python -m candid assign templates`."
        )
    return TEMPLATES[key]


def suggest_template(text: str) -> dict:
    """Suggest the best template for a free-text assignment description.

    Keyword scoring only; falls back to ``generic`` when nothing matches.
    Returns {"template": name, "label": ..., "score": int, "matched": [...]}.
    """
    words = (text or "").lower()
    best, best_score, best_hits = "generic", 0, []
    for name, t in TEMPLATES.items():
        hits = [kw for kw in t["keywords"]
                if re.search(r"\b" + re.escape(kw) + r"\b", words)]
        if len(hits) > best_score:
            best, best_score, best_hits = name, len(hits), hits
    return {"template": best,
            "label": TEMPLATES[best]["label"],
            "score": best_score,
            "matched": best_hits}


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _parse_deadline(raw: str) -> date:
    try:
        dl = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise AssignError(
            f"Bad deadline {raw!r}. Use YYYY-MM-DD, e.g. 2026-09-29."
        )
    if dl <= date.today():
        raise AssignError(
            f"Deadline {raw} is not in the future. Pick a date after today "
            f"({date.today().isoformat()})."
        )
    return dl


def _check_shares(template: dict) -> None:
    total = sum(share for _, share, _ in template["phases"])
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise AssignError(
            f"Template phase shares sum to {total}, not 1.0. "
            "This is a candid bug; please report it."
        )


def _milestone_dates(shares: list[float], days: int,
                     today: date, deadline: date) -> list[date]:
    """Spread phase due dates across the available days.

    Cumulative share of the window per phase, at least one day apart,
    last milestone due on the deadline.
    """
    cum, dues = 0.0, []
    for share in shares:
        cum += share
        dues.append(today + timedelta(days=max(1, math.ceil(days * cum))))
    # enforce strictly increasing, capped at the deadline
    for i in range(1, len(dues)):
        if dues[i] <= dues[i - 1]:
            dues[i] = dues[i - 1] + timedelta(days=1)
    dues[-1] = deadline
    for i in range(len(dues) - 2, -1, -1):
        if dues[i] >= dues[i + 1]:
            dues[i] = dues[i + 1] - timedelta(days=1)
    return dues


def _build_milestones(template: dict, deadline: date) -> list[dict]:
    _check_shares(template)
    today = date.today()
    days = (deadline - today).days
    total = template["typical_hours"]
    shares = [share for _, share, _ in template["phases"]]
    dues = _milestone_dates(shares, days, today, deadline)
    milestones, acc = [], 0.0
    for i, (phase, share, guidance) in enumerate(template["phases"]):
        if i < len(template["phases"]) - 1:
            hrs = round(total * share, 1)
            acc += hrs
        else:
            hrs = round(total - acc, 1)  # absorb rounding on the last phase
        milestones.append({
            "id": f"m{i + 1}",
            "phase": phase,
            "title": phase,
            "due": dues[i].isoformat(),
            "est_hours": hrs,
            "guidance": guidance,
            "done": False,
        })
    return milestones


def _build_review(template: dict) -> list[dict]:
    items = []
    for rid, label, hint in GLOBAL_REVIEW + template["review"]:
        items.append({"id": rid, "label": label, "hint": hint, "done": False})
    return items


def create_plan(template: str, company: str, role: str, deadline: str,
                hours_per_day: float, notes: str = "") -> dict:
    """Create a plan and persist it. Returns the plan dict (with fit check)."""
    t = get_template(template)
    if not company.strip():
        raise AssignError("Company is required: --company \"Acme\".")
    if not role.strip():
        raise AssignError("Role is required: --role \"Data Engineer\".")
    try:
        hpd = float(hours_per_day)
    except (TypeError, ValueError):
        raise AssignError(
            f"Bad --hours-per-day {hours_per_day!r}. Use a number like 2 or 3.5."
        )
    if hpd <= 0 or hpd > 24:
        raise AssignError("--hours-per-day must be between 0 and 24.")
    dl = _parse_deadline(deadline)
    plans = _load()
    plan = {
        "id": _next_id(plans),
        "template": template.strip().lower().replace("_", "-"),
        "template_label": t["label"],
        "company": company.strip(),
        "role": role.strip(),
        "notes": notes.strip(),
        "created": date.today().isoformat(),
        "deadline": dl.isoformat(),
        "hours_per_day": hpd,
        "typical_hours": t["typical_hours"],
        "milestones": _build_milestones(t, dl),
        "review": _build_review(t),
    }
    plan["fit"] = fit_report(plan)
    plans.append(plan)
    _save(plans)
    return plan


def get_plan(plan_id: int) -> dict:
    for pl in _load():
        if pl["id"] == plan_id:
            return pl
    raise AssignError(
        f"No plan with id {plan_id}. See `python -m candid assign list`."
    )


def list_plans() -> list[dict]:
    return _load()


def delete_plan(plan_id: int) -> dict:
    plans = _load()
    kept = [pl for pl in plans if pl["id"] != plan_id]
    if len(kept) == len(plans):
        raise AssignError(
            f"No plan with id {plan_id}. See `python -m candid assign list`."
        )
    _save(kept)
    return {"deleted": plan_id}


def _persist(plan: dict) -> None:
    plans = _load()
    for i, pl in enumerate(plans):
        if pl["id"] == plan["id"]:
            plans[i] = plan
            _save(plans)
            return
    raise AssignError(f"Plan #{plan['id']} disappeared. Re-run the command.")


def complete_milestone(plan_id: int, milestone_id: str, done: bool = True) -> dict:
    plan = get_plan(plan_id)
    mid = milestone_id.strip().lower()
    for m in plan["milestones"]:
        if m["id"] == mid:
            m["done"] = done
            _persist(plan)
            return m
    known = ", ".join(m["id"] for m in plan["milestones"])
    raise AssignError(
        f"Unknown milestone {milestone_id!r} in plan #{plan_id}. "
        f"Known: {known}."
    )


def check_item(plan_id: int, item_id: str, done: bool = True) -> dict:
    plan = get_plan(plan_id)
    iid = item_id.strip().lower()
    for item in plan["review"]:
        if item["id"] == iid:
            item["done"] = done
            _persist(plan)
            return item
    known = ", ".join(r["id"] for r in plan["review"])
    raise AssignError(
        f"Unknown review item {item_id!r} in plan #{plan_id}. "
        f"Known: {known}."
    )


def plan_status(plan_id: int) -> dict:
    """Progress summary: milestone and review counts, overdue flags."""
    plan = get_plan(plan_id)
    today = date.today().isoformat()
    milestones = plan["milestones"]
    done_m = sum(1 for m in milestones if m["done"])
    overdue = [m["id"] for m in milestones
               if not m["done"] and m["due"] < today]
    review = plan["review"]
    done_r = sum(1 for r in review if r["done"])
    next_up = next((m for m in milestones if not m["done"]), None)
    return {
        "id": plan["id"],
        "company": plan["company"],
        "role": plan["role"],
        "template_label": plan["template_label"],
        "deadline": plan["deadline"],
        "milestones_done": done_m,
        "milestones_total": len(milestones),
        "review_done": done_r,
        "review_total": len(review),
        "overdue": overdue,
        "next_up": (next_up["id"] + " - " + next_up["title"]
                    + " (due " + next_up["due"] + ")") if next_up else None,
        "complete": done_m == len(milestones) and done_r == len(review),
    }


# ---------------------------------------------------------------------------
# Fit check: required hours vs. hours actually available
# ---------------------------------------------------------------------------

def fit_report(plan: dict) -> dict:
    """Compare template hours against available hours minus the buffer."""
    today = date.today()
    deadline = datetime.strptime(plan["deadline"], "%Y-%m-%d").date()
    days = max(1, (deadline - today).days)
    available = round(days * plan["hours_per_day"], 1)
    buffer_hours = round(available * BUFFER_FRACTION, 1)
    work_hours = round(available - buffer_hours, 1)
    required = plan["typical_hours"]
    ratio = round(required / work_hours, 2) if work_hours > 0 else float("inf")
    if ratio <= 1.0:
        verdict = "ok"
        suggestions = [
            "The plan fits. Keep the buffer untouched until the final "
            "self-review.",
        ]
    elif ratio <= 1.25:
        verdict = "tight"
        suggestions = [
            "Trim scope early: decide now which phase gets cut first if "
            "you fall behind.",
            "Protect the buffer: move one low-value phase into it only if "
            "you are ahead of schedule.",
        ]
    else:
        verdict = "over"
        suggestions = [
            "You need more time than you have. Options: raise --hours-per-day, "
            "negotiate a later deadline, or pick a smaller scope and say so "
            "in the README.",
            "Do not eat the submission buffer: submitting untested work "
            "reads worse than submitting narrower work.",
        ]
    return {
        "days": days,
        "available_hours": available,
        "buffer_hours": buffer_hours,
        "work_hours": work_hours,
        "required_hours": required,
        "ratio": ratio,
        "verdict": verdict,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Time-boxed schedule
# ---------------------------------------------------------------------------

def timebox_schedule(plan_id: int) -> list[dict]:
    """Day-by-day work blocks for a plan.

    Milestone hours are laid across the days at ``hours_per_day``; whatever
    capacity is left over (including the 10% buffer) becomes buffer blocks
    for final self-review and submission.
    """
    plan = get_plan(plan_id)
    today = date.today()
    deadline = datetime.strptime(plan["deadline"], "%Y-%m-%d").date()
    days = max(1, (deadline - today).days)
    hpd = plan["hours_per_day"]
    fit = fit_report(plan)
    work_budget = fit["work_hours"]

    remaining = [(m["id"], m["title"], m["est_hours"])
                 for m in plan["milestones"]]
    blocks: list[dict] = []
    assigned = 0.0
    idx = 0
    for d in range(1, days + 1):
        day = today + timedelta(days=d)
        cap = hpd
        # fill the day with milestone work while budget remains
        while cap > 0.01 and idx < len(remaining) and assigned < work_budget - 1e-9:
            mid, title, hrs = remaining[idx]
            take = min(cap, hrs, work_budget - assigned)
            take = round(take, 1)
            if take <= 0:
                break
            blocks.append({"date": day.isoformat(), "kind": "work",
                           "milestone_id": mid, "milestone": title,
                           "hours": take})
            cap = round(cap - take, 1)
            assigned = round(assigned + take, 1)
            hrs = round(hrs - take, 1)
            if hrs <= 0.01:
                idx += 1
            else:
                remaining[idx] = (mid, title, hrs)
        if cap > 0.01:
            blocks.append({"date": day.isoformat(), "kind": "buffer",
                           "milestone_id": "", "milestone": "Submission buffer",
                           "hours": round(cap, 1)})
    return blocks


# ---------------------------------------------------------------------------
# Replan: move the deadline, keep completed work
# ---------------------------------------------------------------------------

def replan(plan_id: int, new_deadline: str) -> dict:
    """Recompute milestone dates for a new deadline.

    Completed milestones keep their done flag; only dates change.
    """
    plan = get_plan(plan_id)
    dl = _parse_deadline(new_deadline)
    template = get_template(plan["template"])
    fresh = _build_milestones(template, dl)
    done_ids = {m["id"] for m in plan["milestones"] if m["done"]}
    for old, new in zip(plan["milestones"], fresh):
        new["done"] = old["id"] in done_ids
    plan["deadline"] = dl.isoformat()
    plan["milestones"] = fresh
    plan["fit"] = fit_report(plan)
    _persist(plan)
    return plan


# ---------------------------------------------------------------------------
# File map + README skeleton
# ---------------------------------------------------------------------------

def file_map(template_name: str) -> list[str]:
    return list(get_template(template_name)["file_map"])


def readme_skeleton(template_name: str) -> list[str]:
    return list(get_template(template_name)["readme_sections"])


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def export_markdown(plan_id: int) -> str:
    plan = get_plan(plan_id)
    t = get_template(plan["template"])
    fit = plan["fit"]
    lines = [
        f"# Take-home plan: {plan['role']} @ {plan['company']}",
        "",
        f"Template: {t['label']} | Deadline: {plan['deadline']} | "
        f"{plan['hours_per_day']} hrs/day | ~{plan['typical_hours']} hrs total",
    ]
    if plan["notes"]:
        lines += ["", f"Notes: {plan['notes']}"]
    lines += ["", "## Fit check",
              f"- Available: {fit['available_hours']} hrs over {fit['days']} days",
              f"- Buffer held back: {fit['buffer_hours']} hrs",
              f"- Verdict: {fit['verdict'].upper()}"]
    for s in fit["suggestions"]:
        lines.append(f"  - {s}")
    lines += ["", "## Milestones"]
    for m in plan["milestones"]:
        box = "x" if m["done"] else " "
        lines.append(f"- [{box}] {m['id']}: {m['title']} "
                     f"(due {m['due']}, ~{m['est_hours']} hrs)")
        lines.append(f"  - {m['guidance']}")
    lines += ["", "## Time-boxed schedule"]
    for b in timebox_schedule(plan_id):
        if b["kind"] == "work":
            lines.append(f"- {b['date']}: {b['milestone']} "
                         f"({b['milestone_id']}) - {b['hours']} hrs")
        else:
            lines.append(f"- {b['date']}: BUFFER - {b['hours']} hrs "
                         f"(self-review, package, submit)")
    lines += ["", "## Suggested project layout"]
    for f in t["file_map"]:
        lines.append(f"- `{f}`")
    lines += ["", "## README skeleton"]
    for i, sec in enumerate(t["readme_sections"], 1):
        lines.append(f"{i}. {sec}")
    lines += ["", "## Self-review checklist"]
    for r in plan["review"]:
        box = "x" if r["done"] else " "
        lines.append(f"- [{box}] {r['label']}")
        lines.append(f"  - {r['hint']}")
    lines += ["",
              "_Generated by candid. candid plans the work; the work is yours._"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Renderers (CLI text)
# ---------------------------------------------------------------------------

def render_templates() -> str:
    lines = ["Take-home templates (structure, never solutions):", ""]
    for s in list_templates():
        lines.append(f"  {s['name']:15} ~{s['typical_hours']:>4} hrs  "
                     f"{s['label']} - {s['blurb']}")
    lines += ["",
              "See one in detail: python -m candid assign show <name>",
              "Suggest from a prompt: python -m candid assign suggest --text \"...\""]
    return "\n".join(lines)


def render_template_detail(name: str) -> str:
    t = get_template(name)
    lines = [f"{t['label']} ({name})", t["blurb"],
             f"Typical effort: ~{t['typical_hours']} hrs", "",
             "Phases:"]
    for phase, share, guidance in t["phases"]:
        lines.append(f"  - {phase} (~{round(t['typical_hours'] * share, 1)} hrs)")
        lines.append(f"    {guidance}")
    lines += ["", "Suggested project layout:"]
    for f in t["file_map"]:
        lines.append(f"  - {f}")
    lines += ["", "README skeleton:"]
    for i, sec in enumerate(t["readme_sections"], 1):
        lines.append(f"  {i}. {sec}")
    lines += ["", "Self-review rubric (in addition to the global items):"]
    for rid, label, hint in t["review"]:
        lines.append(f"  - [{rid}] {label}: {hint}")
    return "\n".join(lines)


def render_suggestion(sug: dict) -> str:
    if sug["score"]:
        matched = ", ".join(sug["matched"])
        return (f"Suggested template: {sug['template']} ({sug['label']}) "
                f"[matched: {matched}]\n"
                f"See it: python -m candid assign show {sug['template']}")
    return ("No strong match; the generic template fits anything.\n"
            "See it: python -m candid assign show generic")


def render_fit(fit: dict) -> str:
    verdict_word = {"ok": "FITS", "tight": "TIGHT", "over": "OVERCOMMITTED"}
    lines = [
        "Fit check:",
        f"  Available: {fit['available_hours']} hrs over {fit['days']} days "
        f"({fit['buffer_hours']} hrs held as submission buffer)",
        f"  Template needs: ~{fit['required_hours']} hrs",
        f"  Verdict: {verdict_word[fit['verdict']]}",
    ]
    for s in fit["suggestions"]:
        lines.append(f"  - {s}")
    return "\n".join(lines)


def render_plan(plan: dict) -> str:
    lines = [
        f"Plan #{plan['id']}: {plan['role']} @ {plan['company']}",
        f"Template: {plan['template_label']} ({plan['template']}) | "
        f"Deadline: {plan['deadline']} | {plan['hours_per_day']} hrs/day",
        "",
        render_fit(plan["fit"]),
        "",
        "Milestones:",
    ]
    for m in plan["milestones"]:
        mark = "[x]" if m["done"] else "[ ]"
        lines.append(f"  {mark} {m['id']}: {m['title']} "
                     f"(due {m['due']}, ~{m['est_hours']} hrs)")
    lines += ["",
              "Next:",
              f"  python -m candid assign schedule --id {plan['id']}   "
              "# day-by-day time boxes",
              f"  python -m candid assign done --id {plan['id']} --milestone m1",
              f"  python -m candid assign review --id {plan['id']}     "
              "# self-review rubric",
              f"  python -m candid assign export --id {plan['id']} --out plan.md"]
    return "\n".join(lines)


def render_plans(plans: list[dict]) -> str:
    if not plans:
        return ("No take-home plans yet.\n"
                "Start one: python -m candid assign plan --template rest-api "
                "--company Acme --role \"Backend Engineer\" "
                "--deadline 2026-09-29 --hours-per-day 3")
    lines = ["Take-home plans:", ""]
    for pl in plans:
        st = plan_status(pl["id"])
        lines.append(
            f"  #{pl['id']}  {pl['role']} @ {pl['company']} "
            f"[{pl['template_label']}] due {pl['deadline']} - "
            f"{st['milestones_done']}/{st['milestones_total']} milestones, "
            f"{st['review_done']}/{st['review_total']} review items")
    return "\n".join(lines)


def render_status(st: dict) -> str:
    lines = [
        f"Plan #{st['id']}: {st['role']} @ {st['company']} "
        f"[{st['template_label']}]",
        f"Deadline: {st['deadline']}",
        f"Milestones: {st['milestones_done']}/{st['milestones_total']} done",
        f"Self-review: {st['review_done']}/{st['review_total']} done",
    ]
    if st["overdue"]:
        lines.append(f"Overdue: {', '.join(st['overdue'])} - replan or catch up: "
                     f"python -m candid assign replan --id {st['id']} "
                     "--deadline YYYY-MM-DD")
    if st["next_up"]:
        lines.append(f"Next up: {st['next_up']}")
    if st["complete"]:
        lines.append("All milestones and review items are done. Ship it.")
    return "\n".join(lines)


def render_schedule(blocks: list[dict]) -> str:
    lines = ["Time-boxed schedule (10% buffer held back):", ""]
    for b in blocks:
        if b["kind"] == "work":
            lines.append(f"  {b['date']}  {b['hours']:>4} hrs  "
                         f"{b['milestone']} ({b['milestone_id']})")
        else:
            lines.append(f"  {b['date']}  {b['hours']:>4} hrs  "
                         f"BUFFER: final self-review, package, submit")
    return "\n".join(lines)


def render_review(plan: dict) -> str:
    lines = [f"Self-review checklist for plan #{plan['id']} "
             f"({plan['role']} @ {plan['company']}):",
             "Check items off as you complete them. Be honest; the rubric "
             "only works if you are.", ""]
    for r in plan["review"]:
        mark = "[x]" if r["done"] else "[ ]"
        lines.append(f"  {mark} {r['id']}: {r['label']}")
        lines.append(f"       {r['hint']}")
    lines += ["",
              f"Check one off: python -m candid assign check --id {plan['id']} "
              "--item <item-id>"]
    return "\n".join(lines)
