"""Timed take-home assignment simulator for the Data Scientist track.

Practice drills only: every prompt is a synthetic exercise with a generated
CSV (no real company take-homes, no real data). The flow mirrors how actual
take-homes work so you can rehearse under time pressure:

    python -m candid ds-takehome list
    python -m candid ds-takehome show churn-risk
    python -m candid ds-takehome start churn-risk --hours 8
    # ... work on it, write your report ...
    python -m candid ds-takehome submit churn-risk report.md

`submit` scans your report for the expected deliverable sections and gives
completeness feedback. It is explicitly a completeness check, NOT a grading:
it cannot judge the quality of your analysis.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from candid import config as C


class TakeHomeError(Exception):
    """Raised when a take-home prompt cannot be listed/started/submitted."""


# ---------------------------------------------------------------------------
# Prompt catalog
# ---------------------------------------------------------------------------
# Each prompt: id, title, default_hours, background, data description,
# tasks, starter checklist, deliverable sections.
# A section = {"name": ..., "keywords": [...]} — submit() marks a section
# present if its name appears as a heading OR all keywords appear in the text.

PROMPTS: list[dict] = [
    {
        "id": "churn-risk",
        "title": "Subscriber Churn Analysis",
        "default_hours": 8,
        "background": (
            "You are the data scientist for a B2C subscription product with "
            "~40k active subscribers. Leadership believes churn is rising but "
            "nobody can say which customers are at risk or why. A CSV of "
            "subscriber attributes and a churn flag was pulled from the "
            "warehouse this morning."
        ),
        "data": (
            "subscribers.csv — 500 synthetic rows. Columns: customer_id, "
            "tenure_months, plan (basic/pro/enterprise), monthly_spend, "
            "support_tickets (last 90d), last_login_days_ago, churned (0/1). "
            "Generate it with `ds-takehome csv churn-risk -o subscribers.csv`. "
            "There are no missing values to clean; the signal is in the "
            "relationships, not the formatting."
        ),
        "tasks": [
            "Profile the dataset: distributions, segments, and the base churn rate.",
            "Identify the strongest drivers of churn (statistical or modeled — your choice).",
            "Build a simple churn-risk score and show it separates churners from retained customers.",
            "Propose 3 concrete retention actions, prioritized by expected impact vs. effort.",
        ],
        "checklist": [
            "Load the CSV and sanity-check row counts, ranges, and the churn rate",
            "Write down 3 hypotheses about churn BEFORE you look at correlations",
            "Compare churn by plan, tenure band, and support-ticket count",
            "Fit a baseline model (logistic regression is fine) and report its AUC",
            "Check your top-3 findings on a second slice of the data (holdout sanity check)",
            "Draft the executive summary first, then the supporting analysis",
            "Re-read your report: could a non-technical VP act on it?",
        ],
        "sections": [
            {"name": "Executive Summary", "keywords": ["executive summary", "churn rate", "recommend"]},
            {"name": "Data Overview", "keywords": ["data", "rows", "columns"]},
            {"name": "Exploratory Findings", "keywords": ["findings", "distribution", "churn"]},
            {"name": "Churn Drivers", "keywords": ["driver", "tenure", "support"]},
            {"name": "Recommendations", "keywords": ["recommend", "retention", "action"]},
            {"name": "Reproducibility Notes", "keywords": ["reproduc", "method", "model"]},
        ],
    },
    {
        "id": "pricing-elasticity",
        "title": "Pricing Elasticity Write-Up",
        "default_hours": 6,
        "background": (
            "The pricing team ran a 4-week geo experiment: 6 markets saw a 10% "
            "price increase, 6 matched markets stayed at the base price. They "
            "hand you weekly revenue and units per market and ask the only "
            "question that matters: what happens to revenue if we roll this "
            "out everywhere?"
        ),
        "data": (
            "pricing.csv — 480 synthetic rows. Columns: market_id, week, "
            "treated (0/1), price, units_sold, revenue. Generate it with "
            "`ds-takehome csv pricing-elasticity -o pricing.csv`. Assume the "
            "market pairing in the file is correct; focus on estimation, not "
            "on re-matching."
        ),
        "tasks": [
            "Estimate the price elasticity of demand from the experiment.",
            "Quantify the uncertainty (confidence interval) around your estimate.",
            "Project revenue under: no change, 10% rollout, 15% rollout.",
            "Write the decision memo pricing leadership would actually read.",
        ],
        "checklist": [
            "Plot treated vs control revenue over the 4 weeks before modeling",
            "Check for pre-period balance: do treated and control look alike before week 1?",
            "Choose an estimator (diff-in-diff is the natural start) and justify it in one paragraph",
            "Compute standard errors — an elasticity without uncertainty is a guess",
            "Translate elasticity into revenue scenarios with explicit assumptions",
            "State your recommendation and what would change your mind",
            "Keep the memo under 2 pages; push math to an appendix",
        ],
        "sections": [
            {"name": "Summary & Recommendation", "keywords": ["recommend", "elasticity", "revenue"]},
            {"name": "Methodology", "keywords": ["method", "diff", "experiment"]},
            {"name": "Elasticity Estimates", "keywords": ["elasticity", "confidence", "interval"]},
            {"name": "Revenue Implications", "keywords": ["revenue", "scenario", "rollout"]},
            {"name": "Limitations", "keywords": ["limitation", "assumption", "risk"]},
        ],
    },
    {
        "id": "anomaly-detection",
        "title": "Anomaly Detection Narrative",
        "default_hours": 4,
        "background": (
            "The payments team pages you at 9am: yesterday's transaction volume "
            "looked 'weird' and nobody can tell whether it was a fraud wave, a "
            "partner outage, or a data pipeline hiccup. You get 60 days of "
            "hourly transaction counts and a mandate to explain what happened."
        ),
        "data": (
            "payments.csv — ~1,440 synthetic rows. Columns: timestamp, "
            "transactions, approved, declined. Generate it with "
            "`ds-takehome csv anomaly-detection -o payments.csv`. The anomaly "
            "is real and planted; your job is to find it and characterize it."
        ),
        "tasks": [
            "Detect anomalous periods with a defensible method (no black boxes).",
            "Characterize each anomaly: when, how big, which sub-metric moved.",
            "Write the incident narrative: what most likely happened, in plain language.",
            "Propose an alerting rule that would have caught this without drowning the team in pages.",
        ],
        "checklist": [
            "Plot the full 60 days first — look before you model",
            "Decompose trend/seasonality before calling anything anomalous",
            "Pick a detection method you can explain to an on-call engineer",
            "For each flag: duration, magnitude vs baseline, which metric moved",
            "Write the most likely story AND one alternative story",
            "Draft the alert rule with an explicit precision/recall tradeoff",
            "Note what extra data would settle the ambiguity",
        ],
        "sections": [
            {"name": "Summary", "keywords": ["summary", "anomaly", "detected"]},
            {"name": "Detection Method", "keywords": ["method", "threshold", "baseline"]},
            {"name": "Findings", "keywords": ["findings", "anomaly", "timestamp"]},
            {"name": "Operational Recommendations", "keywords": ["recommend", "alert", "monitor"]},
            {"name": "False-Positive Analysis", "keywords": ["false", "positive", "precision"]},
        ],
    },
    {
        "id": "funnel-ab",
        "title": "A/B Test Readout",
        "default_hours": 5,
        "background": (
            "Growth shipped a redesigned signup flow to 50% of new visitors "
            "two weeks ago. The primary metric is signup conversion; "
            "guardrails are bounce rate and time-to-signup. The experiment "
            "just hit its planned sample size and the PM wants a ship/no-ship "
            "decision by end of day."
        ),
        "data": (
            "experiment.csv — 20,000 synthetic rows. Columns: user_id, "
            "variant (control/treatment), signed_up (0/1), bounced (0/1), "
            "days_to_signup. Generate it with `ds-takehome csv funnel-ab "
            "-o experiment.csv`. Randomization is clean; your job is the "
            "analysis and the call."
        ),
        "tasks": [
            "Validate the experiment: SRM check, guardrail metrics, segment sanity.",
            "Estimate the treatment effect on signup conversion with uncertainty.",
            "Check heterogeneity: does the effect hold across key segments?",
            "Make the ship/no-ship call and defend it in one page.",
        ],
        "checklist": [
            "Run a sample-ratio-mismatch check before anything else",
            "Compare guardrail metrics (bounce, time-to-signup) between variants",
            "Estimate the lift with a confidence interval, not just a p-value",
            "Slice by at least 2 dimensions (e.g. device, traffic source if present)",
            "Decide your significance bar BEFORE you see the result",
            "Write the decision memo: call, evidence, risks, follow-ups",
            "Propose the next experiment regardless of the outcome",
        ],
        "sections": [
            {"name": "Summary & Decision", "keywords": ["decision", "ship", "conversion"]},
            {"name": "Experiment Design Check", "keywords": ["randomization", "srm", "sample"]},
            {"name": "Results", "keywords": ["lift", "confidence", "p-value"]},
            {"name": "Segment Analysis", "keywords": ["segment", "heterogeneity", "device"]},
            {"name": "Recommendation & Follow-ups", "keywords": ["recommend", "follow", "next"]},
        ],
    },
    {
        "id": "ltv-model",
        "title": "Customer LTV Modeling — Scoping Exercise",
        "default_hours": 8,
        "background": (
            "Marketing wants to bid smarter on paid acquisition: they need a "
            "predicted 12-month LTV per customer to set CAC targets. There is "
            "no LTV model today. You have 18 months of cohort revenue data and "
            "are asked to scope — and prototype — the modeling approach."
        ),
        "data": (
            "ltv.csv — 2,000 synthetic rows. Columns: customer_id, "
            "cohort_month, acquisition_channel, first_order_value, "
            "orders_12m, revenue_12m. Generate it with `ds-takehome csv "
            "ltv-model -o ltv.csv`. The ask is a scoping doc plus a working "
            "prototype, not a production model."
        ),
        "tasks": [
            "Assess the data: what predicts 12-month revenue, and what's missing?",
            "Prototype an LTV model and evaluate it honestly (out-of-time validation).",
            "Define the business decision the model enables and the metric that proves value.",
            "Write the scoping doc: approach, evaluation, risks, and what v1 ships.",
        ],
        "checklist": [
            "Plot cohort revenue curves — do they stabilize or keep diverging?",
            "Compare acquisition channels on early LTV signal, not just volume",
            "Validate out-of-time (train on old cohorts, test on recent ones)",
            "Report error in dollars, not just R² — the business thinks in dollars",
            "Identify the top 3 data gaps that would most improve the model",
            "Define the decision: which CAC targets change, and by how much?",
            "Scope v1 ruthlessly: what ships in 4 weeks vs what waits",
        ],
        "sections": [
            {"name": "Summary", "keywords": ["summary", "ltv", "model"]},
            {"name": "Data Assessment", "keywords": ["data", "cohort", "channel"]},
            {"name": "Modeling Approach", "keywords": ["model", "feature", "validation"]},
            {"name": "Evaluation Plan", "keywords": ["evaluat", "metric", "error"]},
            {"name": "Business Impact", "keywords": ["business", "cac", "impact"]},
        ],
    },
    {
        "id": "metrics-review",
        "title": "Metrics Deep Dive",
        "default_hours": 3,
        "background": (
            "The weekly business review deck lands on your desk with one "
            "chart circled in red: 'Weekly Active Buyers' dropped 12% "
            "week-over-week. The CEO wants to know by tomorrow whether this "
            "is noise, seasonality, or something broken."
        ),
        "data": (
            "metrics.csv — 26 synthetic rows. Columns: week, active_buyers, "
            "new_buyers, repeat_buyers, avg_order_value, site_visits. Generate "
            "it with `ds-takehome csv metrics-review -o metrics.csv`. Small "
            "data, big ambiguity — that is the point."
        ),
        "tasks": [
            "Decompose the 12% drop: which sub-metric and which buyer segment moved?",
            "Rule hypotheses in or out with the data you have.",
            "Propose the 3 fastest diagnostic queries you'd run next.",
            "Write the one-page brief the CEO actually reads.",
        ],
        "checklist": [
            "Recompute the 12%: is it real or a denominator artifact?",
            "Split the drop: new vs repeat buyers, and by week-over-week vs trend",
            "Check seasonality: what did the same week look like last quarter?",
            "List 5 hypotheses, then kill at least 3 with data",
            "Distinguish 'we know' from 'we suspect' in the write-up",
            "End with: what we do this week, and what we watch",
            "One page. If it needs two pages, the thinking isn't done.",
        ],
        "sections": [
            {"name": "Summary", "keywords": ["summary", "drop", "buyers"]},
            {"name": "Metric Definitions", "keywords": ["metric", "defin", "active"]},
            {"name": "Trend Analysis", "keywords": ["trend", "week", "seasonal"]},
            {"name": "Root-Cause Hypotheses", "keywords": ["hypothes", "cause", "ruled"]},
            {"name": "Dashboard Sketch", "keywords": ["dashboard", "monitor", "watch"]},
        ],
    },
]


def list_prompts() -> list[dict]:
    """All take-home prompts in catalog order."""
    return PROMPTS


def get_prompt(prompt_id: str) -> dict:
    """Fetch one prompt by id, or raise TakeHomeError."""
    for p in PROMPTS:
        if p["id"] == prompt_id:
            return p
    known = ", ".join(p["id"] for p in PROMPTS)
    raise TakeHomeError(f"Unknown take-home {prompt_id!r}. Known: {known}.")


# ---------------------------------------------------------------------------
# Synthetic CSV generators (fixed seeds → reproducible practice data)
# ---------------------------------------------------------------------------

def _gen_rows(prompt_id: str) -> tuple[list[str], list[list]]:
    rng = random.Random(20260922)
    if prompt_id == "churn-risk":
        header = ["customer_id", "tenure_months", "plan", "monthly_spend",
                  "support_tickets", "last_login_days_ago", "churned"]
        rows = []
        for i in range(500):
            tenure = rng.randint(1, 36)
            plan = rng.choice(["basic", "basic", "pro", "enterprise"])
            spend = round({"basic": 19, "pro": 49, "enterprise": 199}[plan]
                          * rng.uniform(0.9, 1.3), 2)
            tickets = rng.randint(0, 8) if rng.random() < 0.3 else rng.randint(0, 2)
            idle = rng.randint(0, 60)
            risk = (0.05 + 0.25 * (tickets >= 3) + 0.20 * (idle > 21)
                    + 0.15 * (tenure < 4) - 0.10 * (plan == "enterprise"))
            churned = 1 if rng.random() < max(0.01, min(0.85, risk)) else 0
            rows.append([f"C{i:04d}", tenure, plan, spend, tickets, idle, churned])
        return header, rows
    if prompt_id == "pricing-elasticity":
        header = ["market_id", "week", "treated", "price", "units_sold", "revenue"]
        rows = []
        for m in range(12):
            treated = 1 if m >= 6 else 0
            base_units = rng.randint(800, 1500)
            for w in range(1, 5):
                price = 100 * (1.10 if treated and w > 1 else 1.0)
                units = int(base_units * (0.88 if treated and w > 1 else 1.0)
                            * rng.uniform(0.92, 1.08))
                rows.append([f"M{m:02d}", w, treated, round(price, 2), units,
                             round(units * price, 2)])
        return header, rows
    if prompt_id == "anomaly-detection":
        header = ["timestamp", "transactions", "approved", "declined"]
        rows = []
        base = datetime(2026, 7, 24, 0, 0, 0)
        for h in range(60 * 24):
            ts = base + timedelta(hours=h)
            daily = 1 + 0.6 * math.sin(2 * math.pi * (h % 24) / 24)
            vol = int(400 * daily * rng.uniform(0.9, 1.1))
            # planted anomaly: a 30-hour dip on days 41-42 (partner outage shape)
            if 41 * 24 <= h < 42 * 24 + 6:
                vol = int(vol * 0.25)
            approved = int(vol * rng.uniform(0.93, 0.97))
            rows.append([ts.isoformat(timespec="hours"), vol, approved,
                         vol - approved])
        return header, rows
    if prompt_id == "funnel-ab":
        header = ["user_id", "variant", "signed_up", "bounced", "days_to_signup"]
        rows = []
        for i in range(20000):
            variant = "treatment" if i % 2 else "control"
            p_sign = 0.145 if variant == "treatment" else 0.12
            signed = 1 if rng.random() < p_sign else 0
            bounced = 1 if rng.random() < (0.30 if variant == "control" else 0.29) else 0
            days = rng.randint(0, 6) if signed else ""
            rows.append([f"U{i:05d}", variant, signed, bounced, days])
        return header, rows
    if prompt_id == "ltv-model":
        header = ["customer_id", "cohort_month", "acquisition_channel",
                  "first_order_value", "orders_12m", "revenue_12m"]
        rows = []
        channels = ["paid_search", "paid_social", "organic", "referral"]
        for i in range(2000):
            ch = rng.choice(channels)
            fov = round(rng.uniform(20, 120), 2)
            orders = max(1, int(rng.gauss(4, 3)))
            mult = {"referral": 1.3, "organic": 1.15, "paid_search": 1.0,
                    "paid_social": 0.85}[ch]
            rev = round(fov * orders * mult * rng.uniform(0.8, 1.2), 2)
            rows.append([f"L{i:04d}", f"2025-{rng.randint(1,12):02d}", ch, fov,
                         orders, rev])
        return header, rows
    if prompt_id == "metrics-review":
        header = ["week", "active_buyers", "new_buyers", "repeat_buyers",
                  "avg_order_value", "site_visits"]
        rows = []
        base = datetime(2026, 3, 30)
        for w in range(26):
            visits = int(rng.gauss(95000, 4000))
            new = int(rng.gauss(5200, 300))
            repeat = int(rng.gauss(14800, 500))
            # planted drop in the last week: repeat buyers fall off a cliff
            if w == 25:
                repeat = int(repeat * 0.82)
            active = new + repeat
            rows.append([(base + timedelta(weeks=w)).date().isoformat(), active,
                         new, repeat, round(rng.uniform(68, 74), 2), visits])
        return header, rows
    raise TakeHomeError(f"No CSV generator for {prompt_id!r}.")


def write_sample_csv(prompt_id: str, dest: str | Path) -> Path:
    """Generate the synthetic practice CSV for a prompt."""
    get_prompt(prompt_id)  # validates the id
    header, rows = _gen_rows(prompt_id)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return dest


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_list() -> str:
    lines = ["Data Scientist take-home drills (synthetic practice data):", ""]
    for p in PROMPTS:
        lines.append(f"  {p['id']:<18} {p['title']:<32} ~{p['default_hours']}h")
    lines += ["",
              "Run `python -m candid ds-takehome show <id>` for the full brief.",
              "Generate the practice CSV with `ds-takehome csv <id> -o data.csv`."]
    return "\n".join(lines)


def render_prompt(p: dict) -> str:
    lines = [
        f"# Take-Home Drill: {p['title']}",
        f"*Suggested timebox: ~{p['default_hours']} hours. Synthetic practice "
        "data — this is a drill, not a real company assignment.*",
        "",
        "## Background",
        "",
        p["background"],
        "",
        "## Data",
        "",
        p["data"],
        "",
        "## Tasks",
        "",
    ]
    lines += [f"{i}. {t}" for i, t in enumerate(p["tasks"], 1)]
    lines += ["", "## Starter checklist", ""]
    lines += [f"- [ ] {c}" for c in p["checklist"]]
    lines += ["", "## Expected deliverable sections", ""]
    lines += [f"- {s['name']}" for s in p["sections"]]
    lines += ["",
              "_Your `submit` report must cover these sections. The completeness "
              "check looks for each one; it does not grade your analysis._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State: start / submit
# ---------------------------------------------------------------------------

def _state_path() -> Path:
    C.ensure_data_dirs()
    return C.DATA_DIR / "ds_takehome.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def start(prompt_id: str, hours: int | None = None) -> str:
    """Record the start of a timed drill; returns the brief + deadline."""
    p = get_prompt(prompt_id)
    hours = hours if hours and hours > 0 else p["default_hours"]
    now = datetime.now()
    deadline = now + timedelta(hours=hours)
    state = _load_state()
    state[prompt_id] = {
        "prompt_id": prompt_id,
        "title": p["title"],
        "started_at": now.isoformat(timespec="seconds"),
        "hours": hours,
        "deadline": deadline.isoformat(timespec="seconds"),
        "submitted_at": None,
    }
    _save_state(state)
    return "\n".join([
        f"⏱  Started '{p['title']}' ({prompt_id}) — {hours}h timebox.",
        f"   Deadline: {deadline.strftime('%a %Y-%m-%d %H:%M')} local.",
        "",
        render_prompt(p),
    ])


def _section_present(text: str, section: dict) -> bool:
    """A section counts as present if its name appears as a heading,
    or all of its keywords appear anywhere in the text."""
    low = text.lower()
    name = section["name"].lower()
    for line in text.splitlines():
        stripped = line.strip().lower().lstrip("#*-").strip()
        if stripped.startswith(name):
            return True
    keywords = [k.lower() for k in section["keywords"]]
    return bool(keywords) and all(k in low for k in keywords)


def check_completeness(prompt_id: str, text: str) -> dict:
    """Scan a submission for the expected sections. Returns a report dict."""
    p = get_prompt(prompt_id)
    found, missing = [], []
    for s in p["sections"]:
        (found if _section_present(text, s) else missing).append(s["name"])
    total = len(p["sections"])
    return {
        "prompt_id": prompt_id,
        "title": p["title"],
        "sections_found": found,
        "sections_missing": missing,
        "completeness_pct": round(100 * len(found) / total) if total else 0,
    }


def render_completeness(report: dict) -> str:
    total = len(report["sections_found"]) + len(report["sections_missing"])
    lines = [
        "## Submission completeness check",
        "",
        "> This is a **completeness check, not a grading**. It only verifies "
        "that each expected deliverable section appears in your report — it "
        "says nothing about the quality of your analysis.",
        "",
        f"Sections found: {len(report['sections_found'])}/{total} "
        f"({report['completeness_pct']}%)",
        "",
    ]
    for name in report["sections_found"]:
        lines.append(f"  ✅ {name}")
    for name in report["sections_missing"]:
        lines.append(f"  ❌ {name} — missing; add this section before submitting for real")
    return "\n".join(lines)


def submit(prompt_id: str, file: str | Path) -> str:
    """Record a submission and return completeness feedback."""
    p = get_prompt(prompt_id)
    path = Path(file)
    if not path.exists():
        raise TakeHomeError(f"Submission file not found: {file}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise TakeHomeError(f"Submission file is empty: {file}")
    report = check_completeness(prompt_id, text)
    state = _load_state()
    entry = state.get(prompt_id, {"prompt_id": prompt_id, "title": p["title"]})
    now = datetime.now()
    entry.update({
        "submitted_at": now.isoformat(timespec="seconds"),
        "submission_file": str(path),
        "completeness_pct": report["completeness_pct"],
        "sections_missing": report["sections_missing"],
    })
    if entry.get("deadline"):
        try:
            late = now > datetime.fromisoformat(entry["deadline"])
            entry["submitted_late"] = late
        except ValueError:
            pass
    state[prompt_id] = entry
    _save_state(state)
    lines = [f"📝 Submitted '{p['title']}' from {path}."]
    if entry.get("submitted_late"):
        lines.append("   ⚠️  Past your timebox deadline — in a real take-home this would count against you.")
    lines += ["", render_completeness(report)]
    return "\n".join(lines)


def status() -> str:
    """One-line status per started drill."""
    state = _load_state()
    if not state:
        return "No take-home drills started yet. Run `ds-takehome list` to browse."
    lines = []
    for pid, e in state.items():
        mark = "✅ submitted" if e.get("submitted_at") else "⏱  in progress"
        dl = f", deadline {e['deadline']}" if e.get("deadline") else ""
        pct = (f", completeness {e['completeness_pct']}%" if e.get("completeness_pct") is not None else "")
        lines.append(f"  {pid:<18} {mark}{dl}{pct}")
    return "Take-home drill status:\n" + "\n".join(lines)
