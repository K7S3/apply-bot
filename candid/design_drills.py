"""Design interview drills: critique practice, whiteboard challenges, rapid-fire Q&A, portfolio talk timer.

Four offline, deterministic drills for product/UX design interview prep:

  critique      - react to a realistic design scenario in writing, then compare
                  against a model critique and self-score on a 0-3 rubric.
  whiteboard    - timed design exercise with constraints, expected artifacts,
                  and a post-exercise self-review checklist.
  rapid-fire    - follow-up questions on design tradeoffs with strong-answer
                  pointers.
  presentation  - build a timed talk track for a portfolio presentation and
                  save it as Markdown under DATA_DIR/design_packs/.

All question banks are local and deterministic (no AI, no network, no logins).
The interactive wrappers (critique_drill, whiteboard_drill, rapid_fire) read
from stdin via input(); every scoring, timing, allocation, and rendering
decision lives in pure functions so tests can cover the logic without stdin.

Usage:
    from candid import design_drills as DD

    DD.critique_drill()              # interactive critique practice
    DD.whiteboard_drill(minutes=30)  # interactive timed exercise
    DD.rapid_fire(n=5)               # interactive tradeoff Q&A
    DD.presentation_plan(total_minutes=10)  # builds + saves talk track

    DD.score_critique({"observation_quality": 2, "rationale": 3,
                       "prioritization": 1, "constructive_suggestions": 2})
    DD.build_presentation_plan(total_minutes=10)
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from candid import config as C


class DesignDrillError(Exception):
    """Raised for design-drill usage errors (unknown id, bad scores, ...)."""


def design_packs_dir() -> Path:
    """User data dir for saved design drill artifacts (created on demand)."""
    d = C.DATA_DIR / "design_packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 1. Design-critique drills
# ---------------------------------------------------------------------------

RUBRIC_DIMENSIONS: list[tuple[str, str, str]] = [
    ("observation_quality",
     "Observation quality",
     "Did you name specific, concrete details in the design, not vague impressions?"),
    ("rationale",
     "Rationale",
     "Did you connect each issue to user impact or business risk?"),
    ("prioritization",
     "Prioritization",
     "Did you rank issues by severity instead of listing them flat?"),
    ("constructive_suggestions",
     "Constructive suggestions",
     "Did you propose concrete alternatives, not just complaints?"),
]
RUBRIC_MAX_PER_DIM = 3
RUBRIC_MAX_TOTAL = len(RUBRIC_DIMENSIONS) * RUBRIC_MAX_PER_DIM


SCENARIOS: list[dict] = [
    {
        "id": "kyc-onboarding",
        "title": "Banking app cuts onboarding from 12 screens to 3",
        "product_context": (
            "Northwind Bank's mobile app. Signup completion sits at 22% and the "
            "growth team has a target of 40% by end of quarter."
        ),
        "design_decision": (
            "Collapse onboarding into 3 screens by deferring identity verification "
            "until the user makes their first deposit."
        ),
        "visual_description": (
            "[Image placeholder: three bright screens. Screen 1 shows a smiling "
            "illustration and a large 'Get started in 30 seconds' button. Screen 2 "
            "has name and email fields. Screen 3 shows confetti and 'You're in!'. "
            "ID documents are not mentioned anywhere.]"
        ),
        "stakeholder_constraints": [
            "KYC regulations require identity verification before an account can transact",
            "Fraud team has a hard ceiling on first-month fraud loss",
            "Support is already swamped with verification-failure calls",
        ],
        "model_critique": [
            "The core tradeoff is mislabeled as pure friction reduction: deferring ID "
            "verification does not remove it, it moves failure later, when the user is "
            "more invested and support cost per case is higher.",
            "Regulatory risk is unaddressed: if 'You're in!' grants any transactional "
            "ability before verification, the design violates KYC, not just best practice.",
            "Better approach is progressive verification: verify identity inline with "
            "clear progress, document-scan fallbacks, and honest time estimates.",
            "Success metric should pair signup completion with verification completion "
            "within 7 days and fraud loss, not completion alone.",
            "Accessibility gap: the confetti success state gives no text alternative for "
            "what actually happened or what comes next.",
        ],
    },
    {
        "id": "pricing-dark-pattern",
        "title": "SaaS pricing page pre-selects annual billing",
        "product_context": (
            "A B2B SaaS startup whose growth team is compensated on new ARR. "
            "Checkout happens on a single pricing page."
        ),
        "design_decision": (
            "Default the billing toggle to annual (paid upfront) with the monthly "
            "option in smaller grey text below."
        ),
        "visual_description": (
            "[Image placeholder: pricing page with a prominent toggle. 'Annual - save "
            "20%' is highlighted in brand blue and pre-selected. 'Monthly' appears "
            "beneath in 12px grey text. The total charge '$1,188 billed today' is in "
            "light grey at the bottom of the card.]"
        ),
        "stakeholder_constraints": [
            "Growth team wants a conversion and ARR lift this quarter",
            "Legal is worried about chargeback rates and refund requests",
            "Brand team markets the company as 'the honest alternative'",
        ],
        "model_critique": [
            "This is a dark pattern (sneak-into-basket variant): the default exploits "
            "inattention rather than expressing preference, which contradicts the "
            "'honest alternative' brand promise.",
            "Short-term ARR lift is likely real, but expect it to be paid back in "
            "chargebacks, refunds, and trust damage that shows up in NRR, not in the "
            "growth team's quarterly dashboard.",
            "Fix the information hierarchy instead: equal visual weight for both "
            "options, total charge in high-contrast type next to the CTA.",
            "A fair test: default annual for one cohort, neutral choice for another, "
            "and compare 90-day net revenue after refunds, not day-0 ARR.",
            "Legal exposure grows with scale: regulators increasingly treat "
            "pre-selected recurring charges as deceptive.",
        ],
    },
    {
        "id": "dashboard-density",
        "title": "Analytics dashboard shows 24 KPIs on one screen",
        "product_context": (
            "An internal analytics tool for retail executives who asked for "
            "'everything at a glance' during stakeholder interviews."
        ),
        "design_decision": (
            "Fit all 24 requested KPIs on a single dashboard using compact cards "
            "and 10px chart labels."
        ),
        "visual_description": (
            "[Image placeholder: a dense grid of 24 small cards, each with a "
            "sparkline and a number. Labels are tiny. Three cards use red/green "
            "color alone to signal good vs bad. No clear visual hierarchy; the eye "
            "has nowhere to land first.]"
        ),
        "stakeholder_constraints": [
            "Executives insist they want every metric visible without scrolling",
            "Several execs are over 55 and view the dashboard on laptops",
            "The data team cannot guarantee all 24 metrics refresh at the same cadence",
        ],
        "model_critique": [
            "Taking 'everything at a glance' literally confuses a stakeholder request "
            "with a user need: nobody can act on 24 numbers at once, so the dashboard "
            "optimizes for the demo, not the decision.",
            "Hierarchy is missing: the 3-4 metrics tied to this week's decisions "
            "should dominate; the rest belong one click away.",
            "Accessibility failures are concrete: 10px labels fail WCAG text sizing, "
            "and red/green-only encoding fails color-blind users.",
            "Stale-data risk: with mixed refresh cadences, a single screen implies a "
            "single 'as of' time that is false for some cards. Show per-card timestamps.",
            "Better pattern: an exception-based summary up top ('3 metrics need "
            "attention') with drill-downs, plus a customizable watchlist.",
        ],
    },
    {
        "id": "grocery-login-wall",
        "title": "Grocery app requires an account before checkout",
        "product_context": (
            "A grocery delivery app whose core audience skews 55+. Marketing wants "
            "email capture to grow the CRM list."
        ),
        "design_decision": (
            "Require account creation (email + password + verification code) before "
            "the user can place their first order."
        ),
        "visual_description": (
            "[Image placeholder: a full-screen login wall over a dimmed cart. "
            "'Create your account to continue' headline, email and password fields, "
            "'Send verification code' button. The cart total is hidden behind the "
            "overlay. No guest option is visible.]"
        ),
        "stakeholder_constraints": [
            "Marketing's OKR is CRM list growth this half",
            "Core audience is older adults with low tolerance for multi-step auth",
            "Support sees high call volume from password-reset issues already",
        ],
        "model_critique": [
            "The login wall taxes the highest-intent moment: a user with a full cart "
            "is being asked to do unrelated work, which is exactly where drop-off "
            "hurts most.",
            "For the 55+ audience, email verification codes are a known failure "
            "point (spam folders, expired codes, typed on a different device).",
            "Decouple identity from ordering: allow guest checkout with just phone "
            "number for delivery updates, then offer account creation post-purchase "
            "when the value (order history, re-order) is tangible.",
            "Marketing still gets its emails: capture at the receipt step with a "
            "clear value exchange instead of a wall.",
            "Measure: checkout completion rate for guest vs forced-account cohorts, "
            "plus support contacts per order.",
        ],
    },
    {
        "id": "support-chatbot-only",
        "title": "Support replaced by an AI chatbot with no human handoff",
        "product_context": (
            "A consumer fintech app cutting support costs. Leadership wants to "
            "replace tier-1 human agents with an AI chatbot."
        ),
        "design_decision": (
            "Route all support through the chatbot; remove the 'talk to a human' "
            "option to keep containment high."
        ),
        "visual_description": (
            "[Image placeholder: a chat window. The bot gives a wrong answer about "
            "a disputed charge, the user types 'let me talk to a person', and the "
            "bot replies 'I can help with that! Could you rephrase?' in an endless "
            "loop. There is no escape hatch in the UI.]"
        ),
        "stakeholder_constraints": [
            "Leadership target: cut support cost per ticket by 60%",
            "CSAT is currently 4.6/5 and the board watches it",
            "Regulated product: disputed transactions have legal response deadlines",
        ],
        "model_critique": [
            "Optimizing for containment instead of resolution: a looped user is "
            "'contained' by the metric but has a failed experience and a likely "
            "regulator complaint.",
            "No graceful degradation: the design needs explicit handoff triggers "
            "(repeated rephrases, sentiment drop, regulated topics like disputes) "
            "with full conversation context passed to the agent.",
            "The visual shows the worst failure mode with no recovery path; every "
            "conversational UI needs an always-visible exit.",
            "Measure resolution rate and reopen rate, not containment; segment by "
            "topic so regulated issues can never be bot-only.",
            "Cost math should include the expensive failures: one mishandled dispute "
            "costs more than dozens of human-handled tickets.",
        ],
    },
]


def list_scenarios() -> list[dict]:
    """Summaries of the critique scenario bank (id, title, product_context)."""
    return [
        {"id": s["id"], "title": s["title"], "product_context": s["product_context"]}
        for s in SCENARIOS
    ]


def get_scenario(scenario_id: str) -> dict:
    """Return the full scenario dict for scenario_id (raises if unknown)."""
    for s in SCENARIOS:
        if s["id"] == scenario_id:
            return s
    raise DesignDrillError(
        f"Unknown scenario {scenario_id!r}. Available: "
        + ", ".join(s["id"] for s in SCENARIOS)
    )


_DIM_FEEDBACK: dict[str, dict[str, str]] = {
    "observation_quality": {
        "low": "Name concrete details: layout, copy, hierarchy, states. Quote the design, don't summarize it.",
        "mid": "Good specifics. Push further: which exact element causes the problem, and for whom?",
        "high": "Strong: your observations are specific enough that someone could redraw the issue from your words.",
    },
    "rationale": {
        "low": "Tie each issue to a consequence: who is harmed, what breaks, what it costs. 'This is bad' is not rationale.",
        "mid": "You linked issues to impact. Next: quantify or rank the impact so tradeoffs are discussable.",
        "high": "Strong: each issue lands because the user or business consequence is explicit.",
    },
    "prioritization": {
        "low": "Rank by severity: what must change before ship vs what is polish. Interviewers watch for this explicitly.",
        "mid": "Some ranking present. Make it sharper: name your #1 must-fix and defend it in one sentence.",
        "high": "Strong: clear severity ordering, which is exactly what senior interviewers score.",
    },
    "constructive_suggestions": {
        "low": "Propose alternatives, not just complaints. Even a rough direction ('try progressive verification') counts.",
        "mid": "You offered fixes. Strengthen them: name the tradeoff your alternative accepts.",
        "high": "Strong: actionable alternatives that show design judgment, not just taste.",
    },
}

_BANDS = [
    (9, "Interview-ready", "This is the bar. Keep the reps up and vary the scenarios."),
    (6, "Developing", "Solid foundation. Pick your lowest dimension and drill it next."),
    (0, "Building", "Normal for early reps. Re-read the model critique and try the same scenario again tomorrow."),
]


def score_critique(answers: dict[str, int]) -> dict:
    """Score a self-assessed critique rubric and return feedback.

    answers maps each rubric dimension id to a 0-3 self score.
    Returns total, percent, band, and per-dimension feedback text.
    """
    dims = [d for d, _, _ in RUBRIC_DIMENSIONS]
    unknown = [k for k in answers if k not in dims]
    missing = [d for d in dims if d not in answers]
    if unknown or missing:
        raise DesignDrillError(
            f"answers must cover exactly {dims}; got unknown={unknown}, missing={missing}"
        )
    for dim, v in answers.items():
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= RUBRIC_MAX_PER_DIM:
            raise DesignDrillError(
                f"Score for {dim!r} must be an int 0-{RUBRIC_MAX_PER_DIM}, got {v!r}"
            )
    total = sum(answers[d] for d in dims)
    percent = round(100 * total / RUBRIC_MAX_TOTAL)
    band, band_note = next((b, n) for thresh, b, n in _BANDS if total >= thresh)
    feedback = {}
    for dim in dims:
        v = answers[dim]
        tier = "low" if v <= 1 else "mid" if v == 2 else "high"
        feedback[dim] = _DIM_FEEDBACK[dim][tier]
    return {
        "scores": {d: answers[d] for d in dims},
        "total": total,
        "max_total": RUBRIC_MAX_TOTAL,
        "percent": percent,
        "band": band,
        "band_note": band_note,
        "feedback": feedback,
    }


def _prompt_score(label: str) -> int:
    while True:
        raw = input(f"  {label} (0-3): ").strip()
        if raw in ("0", "1", "2", "3"):
            return int(raw)
        print("  Enter 0, 1, 2, or 3.")


def _read_multiline(prompt: str) -> str:
    print(prompt)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines).strip()


def critique_drill(scenario_id: str | None = None) -> dict:
    """Interactive design-critique drill.

    Presents a scenario, collects the user's written critique, shows the model
    critique plus the self-score rubric, and returns the scored result.
    """
    sc = get_scenario(scenario_id) if scenario_id else SCENARIOS[0]
    print(f"\n=== Design critique drill: {sc['title']} ===")
    print(f"\nProduct context: {sc['product_context']}")
    print(f"\nDesign decision: {sc['design_decision']}")
    print(f"\n{sc['visual_description']}")
    print("\nStakeholder constraints:")
    for c in sc["stakeholder_constraints"]:
        print(f"  - {c}")
    critique = _read_multiline(
        "\nWrite your critique below (what is wrong, why it matters, what you would "
        "change). Finish with an empty line:"
    )
    if not critique:
        print("(No critique entered; showing the model critique anyway.)")
    print("\n--- Model critique ---")
    for i, point in enumerate(sc["model_critique"], 1):
        print(f"  {i}. {point}")
    print("\n--- Self-score rubric (be honest) ---")
    answers = {}
    for dim, label, desc in RUBRIC_DIMENSIONS:
        print(f"\n{label}: {desc}")
        answers[dim] = _prompt_score(label)
    result = score_critique(answers)
    print(f"\nScore: {result['total']}/{result['max_total']} ({result['percent']}%) - {result['band']}")
    print(result["band_note"])
    for dim, label, _ in RUBRIC_DIMENSIONS:
        print(f"\n{label} ({answers[dim]}/3): {result['feedback'][dim]}")
    return {"scenario": sc["id"], "critique": critique, "score": result}


# ---------------------------------------------------------------------------
# 2. Whiteboard challenge drills
# ---------------------------------------------------------------------------

WHITEBOARD_RUBRIC: list[tuple[str, str, str]] = [
    ("problem_framing",
     "Problem framing",
     "Did you restate the problem, define success, and scope what is out of scope?"),
    ("user_empathy",
     "User empathy",
     "Did you name the user, their context, and what makes them different from you?"),
    ("ideation_breadth",
     "Ideation breadth",
     "Did you explore at least two distinct directions before converging?"),
    ("prioritization",
     "Prioritization",
     "Did you make explicit tradeoffs and defend what you cut?"),
    ("communication",
     "Communication",
     "Did you narrate your thinking out loud and land a clear summary?"),
]

EXERCISES: list[dict] = [
    {
        "id": "grocery-checkout-seniors",
        "title": "Checkout flow for a grocery app for older adults",
        "prompt": "Design a checkout flow for a grocery delivery app whose core users are adults over 65.",
        "context": "Users shop weekly, often on tablets, and call support when confused. Business goal: raise checkout completion from 61%.",
        "constraints": [
            "Type must stay legible at large text sizes without breaking layout",
            "Assume low tolerance for multi-step authentication",
            "Support in-store pickup as well as delivery",
        ],
        "expected_artifacts": [
            "End-to-end user flow (cart to confirmation)",
            "3 key screens sketched with annotations",
            "One edge case (e.g. item out of stock) and how the flow handles it",
        ],
    },
    {
        "id": "transit-delay-alerts",
        "title": "Real-time delay alerts for a commuter transit app",
        "prompt": "Design how a commuter transit app warns riders about delays and helps them reroute.",
        "context": "Riders check the app in a rush, often underground with spotty connectivity. Trust is fragile after a bad alert.",
        "constraints": [
            "Alerts must be glanceable in under 3 seconds",
            "Must work with stale data (tunnels, dead zones)",
            "Avoid alert fatigue: not every 2-minute delay deserves a push",
        ],
        "expected_artifacts": [
            "Alert taxonomy (what triggers which severity)",
            "Lock-screen / push notification design",
            "Reroute suggestion flow with fallback when data is stale",
        ],
    },
    {
        "id": "medication-adherence",
        "title": "Medication adherence feature for a health app",
        "prompt": "Design a feature that helps patients take the right medication at the right time.",
        "context": "Missed doses are usually about routine disruption, not motivation. Many users manage meds for a parent, not themselves.",
        "constraints": [
            "Must handle complex schedules (e.g. twice daily with food)",
            "Design for caregivers acting on someone else's behalf",
            "Never shame the user for a missed dose",
        ],
        "expected_artifacts": [
            "Daily routine view showing what is due and what is done",
            "Missed-dose recovery flow",
            "Caregiver notification design with privacy boundaries",
        ],
    },
    {
        "id": "split-bill",
        "title": "Splitting a restaurant bill in a payments app",
        "prompt": "Design splitting a restaurant bill among friends inside a payments app.",
        "context": "The awkward moment is at the table, with social pressure and mental math. Someone always ordered the expensive wine.",
        "constraints": [
            "Must work when not everyone has the app installed",
            "Handle uneven splits (item-level, not just even division)",
            "Someone has to cover tax and tip fairly",
        ],
        "expected_artifacts": [
            "Bill-capture entry point (photo, manual, or merchant integration)",
            "Split-configuration screen for uneven shares",
            "Nudge/reminder flow for the friend who 'forgets' to pay",
        ],
    },
    {
        "id": "ev-road-trip",
        "title": "Finding and paying for EV charging on a road trip",
        "prompt": "Design finding, reserving, and paying for EV charging during a road trip.",
        "context": "Range anxiety peaks in unfamiliar areas. Drivers plan around charging stops the way they plan around fuel stops.",
        "constraints": [
            "Charger availability data is unreliable; design for disappointment",
            "Payment must work across networks with one account",
            "Glanceable while driving (passenger use) and detailed when parked",
        ],
        "expected_artifacts": [
            "Route view with charging stops as first-class waypoints",
            "Charger detail screen with honest availability states",
            "One-tap payment and receipt flow across networks",
        ],
    },
]


def list_exercises() -> list[dict]:
    """Summaries of the whiteboard exercise bank (id, title, prompt)."""
    return [
        {"id": e["id"], "title": e["title"], "prompt": e["prompt"]}
        for e in EXERCISES
    ]


def get_exercise(exercise_id: str) -> dict:
    """Return the full exercise dict for exercise_id (raises if unknown)."""
    for e in EXERCISES:
        if e["id"] == exercise_id:
            return e
    raise DesignDrillError(
        f"Unknown exercise {exercise_id!r}. Available: "
        + ", ".join(e["id"] for e in EXERCISES)
    )


REVIEW_CHECKLIST: list[str] = [
    "Did you restate the problem in your own words before sketching?",
    "Did you name the primary user and one thing that makes them different from you?",
    "Did you sketch at least two distinct approaches before committing to one?",
    "Did you call out what you are NOT solving (explicit scope cuts)?",
    "Did you walk through the happy path end to end out loud?",
    "Did you name one edge case and show how the design handles it?",
    "Did you tie at least one design choice to a metric you would track?",
    "Did you summarize the solution in under 60 seconds at the end?",
]


def review_checklist() -> list[str]:
    """Post-exercise self-review checklist questions."""
    return list(REVIEW_CHECKLIST)


def evaluate_review(answers: list[bool]) -> dict:
    """Score yes/no self-review answers into a verdict."""
    if not answers or any(not isinstance(a, bool) for a in answers):
        raise DesignDrillError("answers must be a non-empty list of bools")
    yes = sum(answers)
    total = len(answers)
    pct = round(100 * yes / total)
    if pct >= 75:
        verdict = "Strong whiteboard run"
    elif pct >= 50:
        verdict = "Solid, tighten the gaps"
    else:
        verdict = "Re-run with the checklist in hand"
    return {"yes": yes, "total": total, "percent": pct, "verdict": verdict}


def format_time_left(total_seconds: int) -> str:
    """Format seconds as MM:SS (e.g. 90 -> '01:30')."""
    if total_seconds < 0:
        raise DesignDrillError("total_seconds must be >= 0")
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def countdown(total_seconds: int, tick_interval: int = 60,
              sleep_fn=None, out_fn=None) -> None:
    """Count down total_seconds, printing remaining time every tick_interval.

    sleep_fn and out_fn are injectable for tests (defaults: time.sleep, print).
    """
    import time as _time
    sleep_fn = sleep_fn or _time.sleep
    out_fn = out_fn or print
    if total_seconds < 0:
        raise DesignDrillError("total_seconds must be >= 0")
    if tick_interval <= 0:
        raise DesignDrillError("tick_interval must be > 0")
    out_fn(f"Timer started: {format_time_left(total_seconds)} - go.")
    remaining = total_seconds
    while remaining > 0:
        step = min(tick_interval, remaining)
        sleep_fn(step)
        remaining -= step
        out_fn(f"Time left: {format_time_left(remaining)}")
    out_fn("Time's up! Pens down.")


def whiteboard_drill(exercise_id: str | None = None, minutes: int = 30) -> dict:
    """Interactive timed whiteboard exercise with a self-review checklist."""
    if minutes <= 0:
        raise DesignDrillError("minutes must be > 0")
    ex = get_exercise(exercise_id) if exercise_id else EXERCISES[0]
    print(f"\n=== Whiteboard drill ({minutes} min): {ex['title']} ===")
    print(f"\nPrompt: {ex['prompt']}")
    print(f"Context: {ex['context']}")
    print("\nConstraints:")
    for c in ex["constraints"]:
        print(f"  - {c}")
    print("\nExpected artifacts:")
    for a in ex["expected_artifacts"]:
        print(f"  - {a}")
    print("\nEvaluation rubric the interviewer is using:")
    for _dim, label, desc in WHITEBOARD_RUBRIC:
        print(f"  - {label}: {desc}")
    input("\nPress Enter when ready to start the timer...")
    countdown(minutes * 60)
    print("\n--- Self-review checklist (y/n) ---")
    answers = []
    for q in review_checklist():
        while True:
            raw = input(f"{q} [y/n]: ").strip().lower()
            if raw in ("y", "yes"):
                answers.append(True)
                break
            if raw in ("n", "no"):
                answers.append(False)
                break
            print("  Answer y or n.")
    result = evaluate_review(answers)
    print(f"\nSelf-review: {result['yes']}/{result['total']} ({result['percent']}%) - {result['verdict']}")
    return {"exercise": ex["id"], "minutes": minutes, "review": result}


# ---------------------------------------------------------------------------
# 3. Design-decision rapid-fire
# ---------------------------------------------------------------------------

RAPID_QUESTIONS: list[dict] = [
    {
        "id": "why-this-over-that",
        "question": "Why did you choose this approach over the obvious alternative?",
        "strong_pointers": [
            "Name the alternative explicitly, don't let the interviewer supply it.",
            "State the criteria you traded off (e.g. speed vs flexibility, clarity vs density).",
            "Say what evidence would change your mind.",
        ],
        "weak_signals": ["'It just felt cleaner'", "Can't name any alternative you considered"],
    },
    {
        "id": "measure-success",
        "question": "How would you measure whether this design is successful?",
        "strong_pointers": [
            "Give one leading indicator (behavior change) and one lagging indicator (outcome).",
            "Name a counter-metric that would catch harm (e.g. support contacts, task time).",
            "Say how long you'd wait before calling it.",
        ],
        "weak_signals": ["Only vanity metrics like page views", "No idea what 'good' looks like numerically"],
    },
    {
        "id": "what-did-you-cut",
        "question": "What did you cut from the design, and why?",
        "strong_pointers": [
            "Cutting is a feature: name what didn't make it and the principle behind the cut.",
            "Show you protected the core user job while trimming nice-to-haves.",
            "Mention what you'd add back first if scope expanded.",
        ],
        "weak_signals": ["'We built everything'", "Cuts sound arbitrary rather than principled"],
    },
    {
        "id": "scale-10x",
        "question": "How does this hold up at 10x the users, content, or complexity?",
        "strong_pointers": [
            "Identify what breaks first (density, performance, moderation, support load).",
            "Sketch the structural change you'd make, not just 'add pagination'.",
            "Separate what scales technically from what scales cognitively.",
        ],
        "weak_signals": ["'It should be fine'", "Only technical scaling, ignoring human scaling"],
    },
    {
        "id": "riskiest-assumption",
        "question": "What is the riskiest assumption in this design?",
        "strong_pointers": [
            "Name the belief that, if wrong, invalidates the design (not a minor detail).",
            "Say how you'd de-risk it cheaply: prototype, concierge test, data cut.",
            "Distinguish desirability risk from feasibility risk.",
        ],
        "weak_signals": ["Can't name one", "Names a trivial risk like a color choice"],
    },
    {
        "id": "edge-case",
        "question": "Walk me through what happens when the unhappy path hits, e.g. the data is missing or the user makes an error.",
        "strong_pointers": [
            "Pick the most likely failure, not the most exotic one.",
            "Show the empty/error state and the recovery path, not just an error message.",
            "Explain how the user knows what to do next.",
        ],
        "weak_signals": ["'That won't happen'", "Error state is just a red banner with no next step"],
    },
    {
        "id": "simpler-version",
        "question": "Why build this instead of the much simpler version?",
        "strong_pointers": [
            "Steel-man the simple version first, then show what it fails to do.",
            "Tie the extra complexity to a specific user need or business outcome.",
            "Acknowledge the cost honestly; simplicity is a real competitor.",
        ],
        "weak_signals": ["Dismissing the simple version without engaging it", "Complexity with no named beneficiary"],
    },
    {
        "id": "new-vs-power-user",
        "question": "How does this work for a first-time user versus a power user?",
        "strong_pointers": [
            "Show the onboarding ramp: what the first run looks like vs day 30.",
            "Name the power-user accelerators (shortcuts, bulk actions, customization).",
            "Explain how you keep the simple path simple while adding power.",
        ],
        "weak_signals": ["Designing only for yourself", "Power features cluttering the first-run experience"],
    },
    {
        "id": "two-more-weeks",
        "question": "If you had two more weeks, what would you do with them?",
        "strong_pointers": [
            "Prioritize like a PM: highest-uncertainty item first, not polish.",
            "Split the time between validation (testing) and craft.",
            "Show you know what 'done enough to learn' looks like.",
        ],
        "weak_signals": ["'Just polish the visuals'", "A laundry list with no prioritization"],
    },
    {
        "id": "stakeholder-feedback",
        "question": "How did stakeholder or user feedback change this design?",
        "strong_pointers": [
            "Tell it as a before/after: what you believed, what you heard, what changed.",
            "Show you can disagree and commit: not every input becomes a change.",
            "Credit the source; it shows you actually do research.",
        ],
        "weak_signals": ["'Nobody had feedback'", "Every change framed as your own idea"],
    },
]


def get_rapid_questions(n: int = 5) -> list[dict]:
    """Return the first n rapid-fire questions (deterministic order)."""
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise DesignDrillError(f"n must be a positive int, got {n!r}")
    return RAPID_QUESTIONS[: min(n, len(RAPID_QUESTIONS))]


def rapid_fire(n: int = 5) -> dict:
    """Interactive rapid-fire round: answer tradeoff questions, then see pointers."""
    questions = get_rapid_questions(n)
    print(f"\n=== Design rapid-fire: {len(questions)} questions ===")
    print("Answer out loud (or type a few notes), then compare against the pointers.\n")
    for i, q in enumerate(questions, 1):
        print(f"Q{i}: {q['question']}")
        input("Your answer (Enter when done): ")
        print("Strong-answer pointers:")
        for p in q["strong_pointers"]:
            print(f"  + {p}")
        print("Weak signals to avoid:")
        for w in q["weak_signals"]:
            print(f"  - {w}")
        if i < len(questions):
            input("\nEnter for the next question...")
            print()
    print("Rapid-fire complete. Re-run with a different n to vary the set.")
    return {"answered": len(questions), "question_ids": [q["id"] for q in questions]}


# ---------------------------------------------------------------------------
# 4. Portfolio presentation timer
# ---------------------------------------------------------------------------

# (checkpoint id, display name, fraction of total time, speaker-note prompts)
CHECKPOINTS: list[tuple[str, str, float, list[str]]] = [
    ("hook", "Hook: the problem", 0.10, [
        "State the user pain in one sentence.",
        "Give one number that makes it real.",
        "Say why it mattered to the business.",
    ]),
    ("project_1", "Project 1 deep-dive", 0.35, [
        "Context and your role in 30 seconds.",
        "Show the before state.",
        "Walk the key decision and the tradeoff you weighed.",
        "End with the outcome metric.",
    ]),
    ("project_2", "Project 2", 0.25, [
        "Why this project shows range beyond project 1.",
        "One hard constraint and how you designed around it.",
        "Outcome or key learning.",
    ]),
    ("process", "How you work", 0.15, [
        "How you start ambiguous work.",
        "How you use research and critique.",
        "How you partner with engineering.",
    ]),
    ("qa_buffer", "Q&A buffer", 0.15, [
        "Prepare 2 questions you want them to ask.",
        "Have one failure story ready.",
        "Close with what you want to do next.",
    ]),
]
MIN_PRESENTATION_MINUTES = 5


def _allocate_minutes(total: int, fractions: list[float]) -> list[int]:
    """Split total minutes by fractions; the parts always sum exactly to total.

    Every checkpoint gets at least 1 minute (callers must pass a total >= the
    number of checkpoints); the leftover is dealt by largest remainder.
    """
    n = len(fractions)
    base = [1] * n
    leftover = total - n
    raw = [leftover * f for f in fractions]
    extra = [int(r) for r in raw]
    remainder = leftover - sum(extra)
    order = sorted(range(n), key=lambda i: (raw[i] - extra[i]), reverse=True)
    for i in order[:remainder]:
        extra[i] += 1
    return [b + e for b, e in zip(base, extra)]


def build_presentation_plan(total_minutes: int = 10) -> dict:
    """Build a timed talk track: checkpoints with minutes and start offsets."""
    if isinstance(total_minutes, bool) or not isinstance(total_minutes, int):
        raise DesignDrillError(f"total_minutes must be an int, got {total_minutes!r}")
    if total_minutes < MIN_PRESENTATION_MINUTES:
        raise DesignDrillError(
            f"total_minutes must be >= {MIN_PRESENTATION_MINUTES}, got {total_minutes}"
        )
    fractions = [f for _, _, f, _ in CHECKPOINTS]
    minutes = _allocate_minutes(total_minutes, fractions)
    checkpoints = []
    start = 0
    for (cid, name, _frac, prompts), m in zip(CHECKPOINTS, minutes):
        checkpoints.append({
            "id": cid,
            "name": name,
            "minutes": m,
            "starts_at_minute": start,
            "ends_at_minute": start + m,
            "speaker_prompts": list(prompts),
        })
        start += m
    return {
        "total_minutes": total_minutes,
        "checkpoints": checkpoints,
        "created": datetime.now().isoformat(timespec="seconds"),
    }


def render_plan_markdown(plan: dict) -> str:
    """Render a presentation plan as Markdown."""
    total = plan["total_minutes"]
    lines = [
        f"# Portfolio presentation plan ({total} minutes)",
        "",
        f"_Created {plan.get('created', '')}. Checkpoints must sum to {total} minutes._",
        "",
        "| # | Checkpoint | Minutes | Starts at |",
        "|---|------------|---------|-----------|",
    ]
    for i, cp in enumerate(plan["checkpoints"], 1):
        lines.append(
            f"| {i} | {cp['name']} | {cp['minutes']} | {cp['starts_at_minute']}:00 |"
        )
    lines.append("")
    for i, cp in enumerate(plan["checkpoints"], 1):
        lines.append(f"## {i}. {cp['name']} ({cp['minutes']} min, starts {cp['starts_at_minute']}:00)")
        lines.append("")
        lines.append("Speaker prompts:")
        for p in cp["speaker_prompts"]:
            lines.append(f"- {p}")
        lines.append("")
    lines.append("## Delivery tips")
    lines.append("")
    lines.extend([
        "- Rehearse with a real timer; the Q&A buffer is sacred, not spare time.",
        "- If a checkpoint runs long, cut scope, never steal from Q&A.",
        "- End each project on the outcome metric, not on process detail.",
    ])
    return "\n".join(lines) + "\n"


def save_presentation_plan(plan: dict, filename: str | None = None) -> Path:
    """Save the rendered plan as Markdown under DATA_DIR/design_packs/."""
    d = design_packs_dir()
    if filename is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"presentation-plan-{plan['total_minutes']}min-{stamp}.md"
    path = d / filename
    path.write_text(render_plan_markdown(plan), encoding="utf-8")
    return path


def presentation_plan(total_minutes: int = 10) -> Path:
    """Build a timed portfolio talk track and save it as Markdown.

    Returns the path of the saved file.
    """
    plan = build_presentation_plan(total_minutes)
    path = save_presentation_plan(plan)
    print(f"\n=== Portfolio presentation plan: {total_minutes} minutes ===")
    for cp in plan["checkpoints"]:
        print(f"  {cp['starts_at_minute']:>2}:00  {cp['name']} ({cp['minutes']} min)")
    print(f"\nSaved to {path}")
    return path


__all__ = [
    "DesignDrillError",
    "design_packs_dir",
    "SCENARIOS",
    "list_scenarios",
    "get_scenario",
    "RUBRIC_DIMENSIONS",
    "score_critique",
    "critique_drill",
    "WHITEBOARD_RUBRIC",
    "EXERCISES",
    "list_exercises",
    "get_exercise",
    "review_checklist",
    "evaluate_review",
    "format_time_left",
    "countdown",
    "whiteboard_drill",
    "RAPID_QUESTIONS",
    "get_rapid_questions",
    "rapid_fire",
    "CHECKPOINTS",
    "build_presentation_plan",
    "render_plan_markdown",
    "save_presentation_plan",
    "presentation_plan",
]
