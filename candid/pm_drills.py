"""PM interview drills: product sense, metrics, and estimation.

Three drill types, all runnable non-interactively (so they are testable)
and interactively via the CLI. No network, no LLM, no paid APIs — every
drill is self-contained in the local banks below, and every attempt is
scored deterministically:

  product-sense — prompt bank. Each prompt ships CIRCLES framework hints,
                  an example strong *outline* (not a full answer), and a
                  1-5 self-score rubric. You submit an answer and your own
                  rubric scores.
  metrics       — scenario bank. Each scenario has an expected structure
                  (north_star, guardrails, supporting_metrics,
                  segmentation). Submit an answer, then `--reveal` shows the
                  expected structure so you can self-compare.
  estimate      — Fermi / market-sizing questions with an acceptable range
                  (low, high) and a worked estimate. The checker tells you
                  in/out of range and shows the worked reasoning.

Attempts are appended to ``<CANDID_DATA_DIR>/pm_drills.json``.

Usage:
    python -m candid pm drill product-sense [--prompt-id N]
    python -m candid pm drill product-sense --prompt-id 0 --answer "text" \\
        --score user_clarity=4,structure=3,user_empathy=4,creativity=3,prioritization=4
    python -m candid pm drill metrics --scenario-id 0 --answer "..."
    python -m candid pm drill metrics --scenario-id 0 --reveal
    python -m candid pm drill estimate --qid 0 --answer 50000
    python -m candid pm drill stats [--json]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C

def _attempts_file() -> Path:
    """Attempts file under the CANDID_DATA_DIR-overridable data dir.

    Resolved lazily (not at import) so tests can re-point CANDID_DATA_DIR
    before importing this module.
    """
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    return base / "pm_drills.json"


class DrillsError(Exception):
    """Raised for PM drill usage errors."""


# ---------------------------------------------------------------------------
# product-sense bank
# ---------------------------------------------------------------------------

RUBRIC_DIMS = (
    "user_clarity",
    "structure",
    "user_empathy",
    "creativity",
    "prioritization",
)

# aliases accepted in --score key=val pairs
SCORE_ALIASES = {
    "clarity": "user_clarity",
    "userclarity": "user_clarity",
    "user_clarity": "user_clarity",
    "structure": "structure",
    "empathy": "user_empathy",
    "user_empathy": "user_empathy",
    "creativity": "creativity",
    "prioritization": "prioritization",
    "priority": "prioritization",
}

CIRCLES_STEPS = [
    "C — Comprehend the situation: restate the prompt, ask clarifying questions.",
    "I — Identify the customer: pick a specific user segment and their job to be done.",
    "R — Report customer needs: list the user's pain points, in their words.",
    "C — Cut through prioritization: pick the highest-impact pain to solve first.",
    "L — List solutions: brainstorm broadly before narrowing.",
    "E — Evaluate tradeoffs: weigh impact vs effort, risks, and what you de-prioritize.",
    "S — Summarize your recommendation: what you'd build first and how you'd measure it.",
]

PRODUCT_SENSE_PROMPTS: list[dict] = [
    {
        "id": 0,
        "title": "Improve onboarding for a fitness app",
        "prompt": "You're the PM for a fitness app with 2M MAU but only 25% of new "
                  "users complete their first workout. How would you improve onboarding?",
        "framework": "CIRCLES",
        "framework_steps": CIRCLES_STEPS,
        "example_outline": (
            "Strong outlines here usually: pick one segment (e.g. first-time gym-goers), "
            "name 2-3 onboarding drop-off reasons (friction in goal-setting, too many "
            "permissions, generic workout plans), propose 2-3 fixes (adaptive quiz that "
            "generates a day-one plan under 10 minutes, social-accountability nudge, "
            "deferred permission asks), prioritize by effort/impact, and name a metric "
            "(first-workout completion within 48h)."
        ),
        "rubric": RUBRIC_DIMS,
    },
    {
        "id": 1,
        "title": "Design a feature for Airbnb hosts",
        "prompt": "Airbnb wants a new feature that helps hosts earn more from "
                  "existing listings. What would you design?",
        "framework": "CIRCLES",
        "framework_steps": CIRCLES_STEPS,
        "example_outline": (
            "Strong outlines here usually: pick a host segment (e.g. single-property "
            "hosts with mid-week vacancy), name the pain (empty Tuesday nights, "
            "pricing anxiety), propose levers (smart-pricing nudges, mid-week experience "
            "bundles, co-host marketplace), prioritize one lever with an impact/effort "
            "table, and name guardrails (guest satisfaction, review scores)."
        ),
        "rubric": RUBRIC_DIMS,
    },
    {
        "id": 2,
        "title": "Grow Spotify in emerging markets",
        "prompt": "Spotify's growth has stalled in a price-sensitive emerging market. "
                  "Design a growth strategy for the next 12 months.",
        "framework": "CIRCLES",
        "framework_steps": CIRCLES_STEPS,
        "example_outline": (
            "Strong outlines here usually: segment (prepaid mobile users, students), "
            "name the blockers (data cost, payment rails, local content gaps), propose "
            "moves (offline-first tier, carrier billing bundles, regional playlists), "
            "prioritize with a reach/effort matrix, and define success (paid "
            "conversion rate, 90-day retention of new cohorts)."
        ),
        "rubric": RUBRIC_DIMS,
    },
    {
        "id": 3,
        "title": "Reduce churn for a B2B SaaS",
        "prompt": "A B2B project-management SaaS loses 8% of customers monthly. "
                  "How would you diagnose and reduce churn?",
        "framework": "CIRCLES",
        "framework_steps": CIRCLES_STEPS,
        "example_outline": (
            "Strong outlines here usually: separate voluntary vs involuntary churn and "
            "segment by plan size, hypothesize causes (onboarding gaps, missing "
            "integrations, champion turnover), propose fixes (usage-triggered CSM "
            "playbooks, dunning for failed payments, champion-change alerts), and name "
            "the north star (net revenue retention) with guardrails (support cost, NPS)."
        ),
        "rubric": RUBRIC_DIMS,
    },
    {
        "id": 4,
        "title": "Launch a kids mode for YouTube",
        "prompt": "YouTube asks you to design a safe, engaging kids mode from scratch. "
                  "Walk through your approach.",
        "framework": "CIRCLES",
        "framework_steps": CIRCLES_STEPS,
        "example_outline": (
            "Strong outlines here usually: identify two users (kids 6-12 and parents), "
            "name parent needs (screen-time control, content safety) vs kid needs "
            "(fun, age-fit discovery), propose controls + a kid-safe feed, evaluate "
            "tradeoffs (engagement vs safety, moderation cost), and define success "
            "(parent trust survey, % of watch time in kids mode, safety incident rate)."
        ),
        "rubric": RUBRIC_DIMS,
    },
]


def list_product_sense() -> list[dict]:
    """Summaries of every product-sense prompt in the bank."""
    return [{"id": p["id"], "title": p["title"], "prompt": p["prompt"]}
            for p in PRODUCT_SENSE_PROMPTS]


def get_product_sense(prompt_id: int) -> dict:
    """Full prompt record (prompt + hints + example outline + rubric)."""
    for p in PRODUCT_SENSE_PROMPTS:
        if p["id"] == int(prompt_id):
            return p
    known = ", ".join(str(p["id"]) for p in PRODUCT_SENSE_PROMPTS)
    raise DrillsError(f"Unknown product-sense prompt id {prompt_id}. Known ids: {known}")


def render_product_sense(p: dict) -> str:
    lines = [
        f"### Product sense drill #{p['id']}: {p['title']}",
        "",
        p["prompt"],
        "",
        f"**Framework: {p['framework']}**",
    ]
    for step in p["framework_steps"]:
        lines.append(f"  • {step}")
    lines += ["", "**Example strong outline (structure, not a full answer):**", "",
              p["example_outline"], "", "**Self-score rubric (1-5 each):**"]
    lines += [f"  • {d}" for d in p["rubric"]]
    return "\n".join(lines)


def parse_scores(raw: str) -> dict[str, int]:
    """Parse '--score k=v,k=v' into {dim: score}. Raises DrillsError on bad input."""
    if not raw.strip():
        raise DrillsError("Empty --score value. Expected e.g. "
                          "--score user_clarity=4,structure=3")
    scores: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            raise DrillsError(f"Bad score pair '{pair}'. Expected key=value.")
        key, val = (s.strip() for s in pair.split("=", 1))
        dim = SCORE_ALIASES.get(key.lower())
        if dim is None:
            raise DrillsError(
                f"Unknown rubric dimension '{key}'. "
                f"Choose from: {', '.join(RUBRIC_DIMS)}")
        try:
            score = int(val)
        except ValueError:
            raise DrillsError(f"Score for '{key}' must be an integer 1-5, got '{val}'.")
        if not 1 <= score <= 5:
            raise DrillsError(f"Score for '{key}' must be 1-5, got {score}.")
        scores[dim] = score
    return scores


def submit_product_sense(prompt_id: int, answer: str,
                         scores: dict[str, int] | None = None) -> dict:
    """Record a product-sense attempt. Returns the attempt record."""
    prompt = get_product_sense(prompt_id)
    if not answer or not answer.strip():
        raise DrillsError("Answer cannot be empty.")
    scores = scores or {}
    unknown = set(scores) - set(RUBRIC_DIMS)
    if unknown:
        raise DrillsError(f"Unknown rubric dimensions: {', '.join(sorted(unknown))}. "
                          f"Choose from: {', '.join(RUBRIC_DIMS)}")
    for dim, val in scores.items():
        if not isinstance(val, int) or isinstance(val, bool) or not 1 <= val <= 5:
            raise DrillsError(f"Score for '{dim}' must be an integer 1-5, got {val!r}.")
    attempt = {
        "type": "product-sense",
        "item_id": prompt["id"],
        "item_title": prompt["title"],
        "answer": answer.strip(),
        "scores": scores,
        "rubric_avg": (round(sum(scores.values()) / len(scores), 2)
                       if scores else None),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    _store_attempt(attempt)
    return attempt


def render_product_sense_result(prompt: dict, attempt: dict) -> str:
    lines = [f"✅ Submitted product-sense attempt for '{prompt['title']}' (prompt #{prompt['id']})."]
    if attempt["scores"]:
        lines.append("Your self-scores:")
        for dim in RUBRIC_DIMS:
            if dim in attempt["scores"]:
                lines.append(f"  • {dim}: {attempt['scores'][dim]}/5")
        lines.append(f"Average: {attempt['rubric_avg']}/5")
        weak = [d for d in RUBRIC_DIMS if attempt["scores"].get(d, 5) <= 2]
        if weak:
            lines.append("Weakest areas: " + ", ".join(weak) +
                         " — revisit the CIRCLES steps above.")
    else:
        lines.append("No self-scores given. Re-run with --score to track your rubric.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# metrics bank
# ---------------------------------------------------------------------------

METRICS_SCENARIOS: list[dict] = [
    {
        "id": 0,
        "title": "DAU dropped 10% week-over-week",
        "scenario": "Your consumer app's DAU dropped 10% week-over-week. "
                    "How do you diagnose it, and what metrics would you define?",
        "expected": {
            "north_star": "Weekly active users engaging with core value (e.g. "
                          "weekly completed core actions per user) — the single "
                          "metric that captures value delivery.",
            "guardrails": "Crash-free rate, app latency p95, notification opt-out "
                          "rate, support ticket volume — metrics that must not "
                          "degrade while you fix DAU.",
            "supporting_metrics": "DAU/WAU/MAU stickiness, new vs returning split, "
                                  "session length, core-action conversion funnel, "
                                  "acquisition (installs, activation rate), "
                                  "notification open rate.",
            "segmentation": "By platform (iOS/Android/web), app version, cohort "
                            "(new vs tenured), geography, acquisition channel, and "
                            "core-feature users vs casual browsers — to isolate "
                            "whether the drop is a release bug, a cohort effect, or "
                            "an external event.",
        },
    },
    {
        "id": 1,
        "title": "Success metrics for a new checkout flow",
        "scenario": "You're launching a redesigned checkout flow for an e-commerce "
                    "site. Define the success metrics before launch.",
        "expected": {
            "north_star": "Checkout conversion rate (sessions reaching checkout that "
                          "complete payment) or revenue per session.",
            "guardrails": "Payment error rate, page load time, fraud/chargeback "
                          "rate, customer support contacts per order.",
            "supporting_metrics": "Funnel step conversion (cart -> shipping -> "
                                  "payment -> confirm), cart abandonment rate, "
                                  "average order value, payment-method mix, time to "
                                  "complete checkout.",
            "segmentation": "By device (mobile/desktop), new vs returning "
                            "customers, guest vs logged-in, geography, and payment "
                            "method — a redesign often helps one segment and hurts "
                            "another.",
        },
    },
    {
        "id": 2,
        "title": "Measure a referral program",
        "scenario": "Your team ships a referral program: users get credit for "
                    "inviting friends. How do you measure whether it works?",
        "expected": {
            "north_star": "Referred-user activation rate or net new activated users "
                          "attributable to referrals (k-factor adjusted).",
            "guardrails": "Fraud/abuse rate (self-referrals, fake accounts), "
                          "referrer churn, support cost per referral.",
            "supporting_metrics": "Invite send rate, invite-to-signup conversion, "
                                  "signup-to-activation conversion, k-factor, "
                                  "referral credit redemption rate, LTV of referred "
                                  "vs organic users.",
            "segmentation": "By referrer cohort (power users vs casuals), channel "
                            "(SMS/email/social), and referred-user geography — "
                            "abuse and quality concentrate in specific slices.",
        },
    },
    {
        "id": 3,
        "title": "Experiment: new ranking algorithm",
        "scenario": "You A/B test a new feed ranking algorithm. What metrics do you "
                    "watch, and how do you decide to ship?",
        "expected": {
            "north_star": "Long-term retention (e.g. D30 retention) or sessions per "
                          "user per week — the durable value metric, not a "
                          "vanity engagement spike.",
            "guardrails": "Diversity of content consumed, report/block rate, "
                          "creator-side metrics, latency, time spent on low-quality "
                          "content.",
            "supporting_metrics": "DAU/WAU, session length, likes/comments/shares "
                                  "per session, scroll depth, % of sessions with a "
                                  "meaningful interaction.",
            "segmentation": "By user tenure, heavy vs light users, content "
                            "vertical, and device — ranking changes almost always "
                            "have heterogeneous treatment effects. Check SRM and "
                            "pre-period balance first.",
        },
    },
]


def list_metrics() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "scenario": s["scenario"]}
            for s in METRICS_SCENARIOS]


def get_metrics_scenario(scenario_id: int) -> dict:
    for s in METRICS_SCENARIOS:
        if s["id"] == int(scenario_id):
            return s
    known = ", ".join(str(s["id"]) for s in METRICS_SCENARIOS)
    raise DrillsError(f"Unknown metrics scenario id {scenario_id}. Known ids: {known}")


def render_metrics_scenario(s: dict) -> str:
    return (f"### Metrics drill #{s['id']}: {s['title']}\n\n{s['scenario']}\n\n"
            "Structure your answer as:\n"
            "  • north_star — the single metric that captures value\n"
            "  • guardrails — metrics that must not degrade\n"
            "  • supporting_metrics — diagnostic/funnel metrics\n"
            "  • segmentation — the slices that isolate the cause")


def reveal_metrics(scenario_id: int) -> str:
    s = get_metrics_scenario(scenario_id)
    e = s["expected"]
    return "\n".join([
        f"--- Expected structure: {s['title']} (scenario #{s['id']}) ---",
        "",
        f"north_star:\n  {e['north_star']}",
        "",
        f"guardrails:\n  {e['guardrails']}",
        "",
        f"supporting_metrics:\n  {e['supporting_metrics']}",
        "",
        f"segmentation:\n  {e['segmentation']}",
        "",
        "Compare with your answer: did you cover all four? "
        "Where did your structure differ?",
    ])


def submit_metrics(scenario_id: int, answer: str) -> dict:
    scenario = get_metrics_scenario(scenario_id)
    if not answer or not answer.strip():
        raise DrillsError("Answer cannot be empty.")
    attempt = {
        "type": "metrics",
        "item_id": scenario["id"],
        "item_title": scenario["title"],
        "answer": answer.strip(),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    _store_attempt(attempt)
    return attempt


# ---------------------------------------------------------------------------
# estimation bank
# ---------------------------------------------------------------------------

ESTIMATION_QUESTIONS: list[dict] = [
    {
        "id": 0,
        "title": "Uber rides per day in NYC",
        "question": "How many Uber rides happen per day in New York City?",
        "framework_steps": [
            "Start from the population: ~8.3M people in NYC.",
            "Estimate the share that uses ride-hail regularly (say 15-25%).",
            "Estimate rides per user per week (say 2-3).",
            "Divide by 7 for daily, then split Uber's share of ride-hail (~60-70% vs Lyft).",
            "Sanity-check against known anchors (taxi medallion trip counts).",
        ],
        "low": 150_000,
        "high": 600_000,
        "worked": ("8.3M people x 20% regular ride-hail users = 1.66M users. "
                   "2.5 rides/week each = 4.15M rides/week across all apps. "
                   "Uber share ~65% = 2.7M/week, /7 = ~385k/day. "
                   "Acceptable range: 150k-600k/day."),
    },
    {
        "id": 1,
        "title": "Basketballs to fill a school bus",
        "question": "How many basketballs would it take to fill a school bus?",
        "framework_steps": [
            "Estimate the bus interior volume (length x width x height).",
            "Estimate a basketball's volume (sphere, ~24 cm diameter).",
            "Divide, then apply a packing efficiency (~65% for random spheres).",
            "Subtract space taken by seats (or state the assumption).",
        ],
        "low": 2_000,
        "high": 6_000,
        "worked": ("Bus interior ~ 10m x 2.4m x 1.9m = ~45 m^3. Basketball radius "
                   "0.12m -> volume ~0.0072 m^3. 45/0.0072 = ~6,200 spheres; "
                   "x 65% packing = ~4,000. Acceptable range: 2,000-6,000."),
    },
    {
        "id": 2,
        "title": "Google searches per day in the US",
        "question": "How many Google searches happen per day in the United States?",
        "framework_steps": [
            "Start from US population (~340M) or internet users (~310M).",
            "Estimate daily searchers vs non-searchers.",
            "Estimate searches per searcher per day.",
            "Multiply; sanity-check against the ~8.5B global searches/day anchor.",
        ],
        "low": 500_000_000,
        "high": 2_000_000_000,
        "worked": ("~310M US internet users; ~70% search daily = 217M searchers. "
                   "~5 searches/day each = ~1.1B/day. Global anchor 8.5B/day with "
                   "US ~13% share = ~1.1B/day. Acceptable range: 0.5B-2B/day."),
    },
    {
        "id": 3,
        "title": "Revenue of a NYC coffee shop",
        "question": "Estimate the annual revenue of a typical independent coffee "
                    "shop in Manhattan.",
        "framework_steps": [
            "Estimate customers per day (foot traffic x capture rate).",
            "Estimate average ticket (drink + pastry attach rate).",
            "Multiply by operating days per year.",
            "Segment weekday vs weekend if you want precision.",
        ],
        "low": 300_000,
        "high": 1_500_000,
        "worked": ("~300 customers/day x $6.50 avg ticket = ~$1,950/day. "
                   "x 360 days = ~$700k/year. Acceptable range: $300k-$1.5M."),
    },
]


def list_estimation() -> list[dict]:
    return [{"id": q["id"], "title": q["title"], "question": q["question"]}
            for q in ESTIMATION_QUESTIONS]


def get_estimation(qid: int) -> dict:
    for q in ESTIMATION_QUESTIONS:
        if q["id"] == int(qid):
            return q
    known = ", ".join(str(q["id"]) for q in ESTIMATION_QUESTIONS)
    raise DrillsError(f"Unknown estimation question id {qid}. Known ids: {known}")


def render_estimation(q: dict) -> str:
    lines = [f"### Estimation drill #{q['id']}: {q['title']}", "", q["question"], "",
             "**Framework steps:**"]
    lines += [f"  {i}. {s}" for i, s in enumerate(q["framework_steps"], 1)]
    lines += ["", "Give a single number (commas and k/m suffixes OK)."]
    return "\n".join(lines)


def parse_estimate(raw: str | int | float) -> float:
    """Parse '50000', '50,000', '50k', '1.2M' into a float."""
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower().replace(",", "").replace("$", "")
    mult = 1.0
    if s.endswith("k"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000.0, s[:-1]
    elif s.endswith("b"):
        mult, s = 1_000_000_000.0, s[:-1]
    try:
        value = float(s) * mult
    except ValueError:
        raise DrillsError(f"Could not parse '{raw}' as a number. "
                          "Examples: 50000, 50k, 1.2M.")
    return value


def check_estimate(qid: int, answer: str | int | float) -> dict:
    """Check an answer against the acceptable range. Returns the verdict dict."""
    q = get_estimation(qid)
    value = parse_estimate(answer)
    in_range = q["low"] <= value <= q["high"]
    return {
        "qid": q["id"],
        "title": q["title"],
        "answer": value,
        "low": q["low"],
        "high": q["high"],
        "in_range": in_range,
        "worked": q["worked"],
    }


def submit_estimate(qid: int, answer: str | int | float) -> dict:
    """Record an estimation attempt. Returns the attempt (with correctness)."""
    result = check_estimate(qid, answer)
    attempt = {
        "type": "estimate",
        "item_id": result["qid"],
        "item_title": result["title"],
        "answer": result["answer"],
        "low": result["low"],
        "high": result["high"],
        "in_range": result["in_range"],
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    _store_attempt(attempt)
    return attempt


def render_estimate_result(result: dict) -> str:
    icon = "✅" if result["in_range"] else "❌"
    verdict = "IN RANGE" if result["in_range"] else "OUT OF RANGE"
    return "\n".join([
        f"{icon} {verdict} — your answer: {result['answer']:,.0f} "
        f"(acceptable: {result['low']:,.0f} - {result['high']:,.0f})",
        "",
        f"Worked reasoning: {result['worked']}",
    ])


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _store_attempt(attempt: dict) -> Path:
    path = _attempts_file()
    attempts = load_attempts()
    attempts.append(attempt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attempts, indent=2), encoding="utf-8")
    return path


def load_attempts() -> list[dict]:
    path = _attempts_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def drill_stats() -> dict:
    """Aggregate stats: attempts per type, estimation accuracy, streaks."""
    attempts = load_attempts()
    by_type: dict[str, int] = {"product-sense": 0, "metrics": 0, "estimate": 0}
    for a in attempts:
        t = a.get("type")
        if t in by_type:
            by_type[t] += 1

    est = [a for a in attempts if a.get("type") == "estimate"]
    est_correct = sum(1 for a in est if a.get("in_range"))
    accuracy = round(est_correct / len(est), 3) if est else None

    rubric_avgs: dict[str, float] = {}
    ps = [a for a in attempts if a.get("type") == "product-sense" and a.get("scores")]
    if ps:
        for dim in RUBRIC_DIMS:
            vals = [a["scores"][dim] for a in ps if dim in a["scores"]]
            if vals:
                rubric_avgs[dim] = round(sum(vals) / len(vals), 2)

    days = sorted({a["at"][:10] for a in attempts if a.get("at")})
    current_streak = _current_streak(days)
    best_streak = _best_streak(days)

    return {
        "total_attempts": len(attempts),
        "by_type": by_type,
        "estimate_accuracy": accuracy,
        "estimate_correct": est_correct,
        "estimate_total": len(est),
        "rubric_avgs": rubric_avgs,
        "current_streak_days": current_streak,
        "best_streak_days": best_streak,
        "last_attempt": attempts[-1]["at"] if attempts else None,
    }


def _current_streak(days: list[str]) -> int:
    if not days:
        return 0
    day_set = set(days)
    today = date.today()
    if today.isoformat() not in day_set and (today - timedelta(days=1)).isoformat() not in day_set:
        return 0
    d = today if today.isoformat() in day_set else today - timedelta(days=1)
    streak = 0
    while d.isoformat() in day_set:
        streak += 1
        d -= timedelta(days=1)
    return streak


def _best_streak(days: list[str]) -> int:
    best = run = 0
    prev: date | None = None
    for ds in days:
        d = date.fromisoformat(ds)
        run = run + 1 if prev and d == prev + timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def render_stats(s: dict) -> str:
    lines = [
        "--- Drill stats ---",
        f"Total attempts: {s['total_attempts']}",
        "By type:",
    ]
    for t in ("product-sense", "metrics", "estimate"):
        lines.append(f"  • {t}: {s['by_type'][t]}")
    if s["estimate_accuracy"] is None:
        lines.append("Estimation accuracy: no attempts yet")
    else:
        lines.append(f"Estimation accuracy: {s['estimate_correct']}/{s['estimate_total']} "
                     f"({s['estimate_accuracy']:.0%})")
    if s["rubric_avgs"]:
        lines.append("Product-sense rubric averages:")
        for dim, avg in s["rubric_avgs"].items():
            lines.append(f"  • {dim}: {avg}/5")
    lines.append(f"Current streak: {s['current_streak_days']} day(s)")
    lines.append(f"Best streak: {s['best_streak_days']} day(s)")
    if s["last_attempt"]:
        lines.append(f"Last attempt: {s['last_attempt']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# interactive helpers (bonus; flags above are the mandatory path)
# ---------------------------------------------------------------------------

def read_multiline(prompt: str = "Your answer (end with a line containing only EOF):") -> str:
    print(prompt)
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


def read_scores_interactive() -> dict[str, int]:
    print("Self-score each rubric dimension 1-5 (Enter to skip scoring).")
    scores: dict[str, int] = {}
    try:
        for dim in RUBRIC_DIMS:
            raw = input(f"  {dim}: ").strip()
            if not raw:
                continue
            val = int(raw)
            if not 1 <= val <= 5:
                print(f"  Skipping {dim}: must be 1-5.")
                continue
            scores[dim] = val
    except (EOFError, ValueError):
        pass
    return scores


def interactive_product_sense(prompt_id: int | None = None) -> dict:
    p = get_product_sense(prompt_id) if prompt_id is not None else \
        get_product_sense(__import__("random").choice([x["id"] for x in PRODUCT_SENSE_PROMPTS]))
    print(render_product_sense(p))
    print()
    answer = read_multiline()
    scores = read_scores_interactive()
    attempt = submit_product_sense(p["id"], answer, scores or None)
    print()
    print(render_product_sense_result(p, attempt))
    return attempt


def interactive_metrics(scenario_id: int | None = None) -> dict:
    s = get_metrics_scenario(scenario_id) if scenario_id is not None else \
        get_metrics_scenario(__import__("random").choice([x["id"] for x in METRICS_SCENARIOS]))
    print(render_metrics_scenario(s))
    print()
    answer = read_multiline()
    attempt = submit_metrics(s["id"], answer)
    print()
    print("Recorded. Run `drill metrics --scenario-id "
          f"{s['id']} --reveal` to compare with the expected structure.")
    return attempt


def interactive_estimate(qid: int | None = None) -> dict:
    q = get_estimation(qid) if qid is not None else \
        get_estimation(__import__("random").choice([x["id"] for x in ESTIMATION_QUESTIONS]))
    print(render_estimation(q))
    print()
    try:
        raw = input("Your estimate: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        raise DrillsError("No answer given.")
    result = check_estimate(q["id"], raw)
    attempt = submit_estimate(q["id"], raw)
    print()
    print(render_estimate_result(result))
    return attempt


# ---------------------------------------------------------------------------
# CLI wiring: register_pm(pm_subparsers)
# ---------------------------------------------------------------------------

def cmd_drill(a) -> None:
    """Dispatch the `drill` sub-action. Imported lazily via register_pm."""
    if a.action == "product-sense":
        if a.answer is not None:
            scores = parse_scores(a.score) if a.score else None
            attempt = submit_product_sense(a.prompt_id, a.answer, scores)
            p = get_product_sense(a.prompt_id)
            out = render_product_sense_result(p, attempt)
            if a.json:
                print(json.dumps(attempt, indent=2))
            else:
                print(out)
        elif a.interactive:
            interactive_product_sense(a.prompt_id)
        else:
            p = get_product_sense(a.prompt_id)
            if a.json:
                print(json.dumps(p, indent=2))
            else:
                print(render_product_sense(p))
    elif a.action == "metrics":
        if a.reveal:
            text = reveal_metrics(a.scenario_id)
            print(json.dumps({"scenario_id": a.scenario_id, "expected": text},
                             indent=2) if a.json else text)
        elif a.answer is not None:
            attempt = submit_metrics(a.scenario_id, a.answer)
            if a.json:
                print(json.dumps(attempt, indent=2))
            else:
                print(f"✅ Recorded metrics attempt for scenario #{a.scenario_id}. "
                      f"Run `drill metrics --scenario-id {a.scenario_id} --reveal` "
                      "to compare with the expected structure.")
        elif a.interactive:
            interactive_metrics(a.scenario_id)
        else:
            s = get_metrics_scenario(a.scenario_id)
            if a.json:
                print(json.dumps({k: s[k] for k in ("id", "title", "scenario")}, indent=2))
            else:
                print(render_metrics_scenario(s))
    elif a.action == "estimate":
        if a.answer is not None:
            result = check_estimate(a.qid, a.answer)
            submit_estimate(a.qid, a.answer)
            if a.json:
                print(json.dumps({k: v for k, v in result.items() if k != "worked"},
                                 indent=2))
            else:
                print(render_estimate_result(result))
        elif a.interactive:
            interactive_estimate(a.qid)
        else:
            q = get_estimation(a.qid)
            if a.json:
                print(json.dumps({k: q[k] for k in ("id", "title", "question",
                                                    "framework_steps")}, indent=2))
            else:
                print(render_estimation(q))
    elif a.action == "stats":
        s = drill_stats()
        print(json.dumps(s, indent=2) if a.json else render_stats(s))


def register_pm(pm_subparsers) -> None:
    """Register the `drill` command under the `pm` parser.

    Called by the CLI builder (candid/__main__.py) with the `pm`
    subparsers object. Expects the coordinator to do:
        pm = _sub(sub, "pm", "PM interview prep: drills.", [...])
        pm_sub = _nested(pm)
        register_pm(pm_sub)
    """
    d = pm_subparsers.add_parser(
        "drill", help="PM drills: product sense, metrics, estimation.",
        formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
        epilog=("examples:\n"
                "  python -m candid pm drill product-sense\n"
                "  python -m candid pm drill product-sense --prompt-id 0 "
                "--answer \"...\" --score user_clarity=4,structure=4\n"
                "  python -m candid pm drill metrics --scenario-id 0 --answer \"...\"\n"
                "  python -m candid pm drill metrics --scenario-id 0 --reveal\n"
                "  python -m candid pm drill estimate --qid 0 --answer 50000\n"
                "  python -m candid pm drill stats --json"))

    act = d.add_subparsers(dest="action", required=True, title="drill type",
                           metavar="<type>")

    ps = act.add_parser("product-sense", help="Product-sense drill with CIRCLES hints.")
    ps.add_argument("--prompt-id", type=int, default=0,
                    help="Prompt id (default 0).")
    ps.add_argument("--answer", default=None,
                    help="Your answer text (non-interactive submit).")
    ps.add_argument("--score", default=None,
                    help="Self-scores, e.g. --score user_clarity=4,structure=3")
    ps.add_argument("--interactive", action="store_true",
                    help="Answer via stdin prompts.")
    ps.add_argument("--json", action="store_true", help="Machine-readable output.")

    m = act.add_parser("metrics", help="Metrics drill with expected-structure reveal.")
    m.add_argument("--scenario-id", type=int, default=0, help="Scenario id (default 0).")
    m.add_argument("--answer", default=None, help="Your answer text.")
    m.add_argument("--reveal", action="store_true",
                   help="Show the expected structure for self-comparison.")
    m.add_argument("--interactive", action="store_true", help="Answer via stdin prompts.")
    m.add_argument("--json", action="store_true", help="Machine-readable output.")

    e = act.add_parser("estimate", help="Fermi estimation drill with range checking.")
    e.add_argument("--qid", type=int, default=0, help="Question id (default 0).")
    e.add_argument("--answer", default=None,
                   help="Your numeric estimate (e.g. 50000, 50k, 1.2M).")
    e.add_argument("--interactive", action="store_true", help="Answer via stdin prompts.")
    e.add_argument("--json", action="store_true", help="Machine-readable output.")

    s = act.add_parser("stats", help="Drill stats: attempts, accuracy, streaks.")
    s.add_argument("--json", action="store_true", help="Machine-readable output.")

    d.set_defaults(func=cmd_drill)
