"""PM concept deep-dives for the product-manager interview track.

Each concept is a self-contained PM fundamental: a summary, the key points
to internalize, common pitfalls that sink candidates, and the interview
angle - how it actually shows up in PM interviews.
"""

from __future__ import annotations

import argparse
import json
import re

from candid.pm_questions import PMError


def _concept(name: str, summary: str, key_points: list[str],
             pitfalls: list[str], interview_angle: str) -> dict:
    return {
        "name": name,
        "summary": summary,
        "key_points": key_points,
        "pitfalls": pitfalls,
        "interview_angle": interview_angle,
    }


PM_CONCEPTS: dict[str, dict] = {
    "funnels": _concept(
        name="Funnel Analysis",
        summary=("A funnel maps the steps a user takes toward a goal "
                 "(visit -> signup -> onboarding -> purchase) and measures the "
                 "conversion rate at each step. The biggest leak gets "
                 "attention first; small leaks are usually noise."),
        key_points=[
            "Define the funnel steps from the user's perspective, not the system's.",
            "Report both absolute conversion and relative drop-off per step.",
            "Segment funnels by cohort, channel, device, and geography before concluding anything.",
            "The largest absolute drop-off is usually where a fix pays off most.",
            "Track funnel health over time - a sudden step-change signals an incident, a slow drift signals a product problem.",
        ],
        pitfalls=[
            "Optimizing a step with a tiny user base while a massive leak elsewhere goes untouched.",
            "Treating correlation as causation: a funnel drop after a launch may be seasonality or a traffic mix shift.",
            "Forgetting that improving one step can starve the next (e.g. more signups of lower intent).",
        ],
        interview_angle=("Shows up as metric-change/root-cause questions: "
                        "'checkout conversion dropped 20% - what do you do?' "
                        "Walk the funnel step by step and name the segment you'd "
                        "check first."),
    ),
    "retention_cohorts": _concept(
        name="Retention & Cohort Analysis",
        summary=("Retention measures whether users come back; cohort analysis "
                 "groups users by start date to see if the product is getting "
                 "better over time. A healthy product has flattening retention "
                 "curves; a leaky one never flattens."),
        key_points=[
            "Pick the right retention definition: N-day, unbounded, or rolling retention, matched to the product's natural usage cadence.",
            "Cohort by signup week/month to separate product improvements from mix shifts.",
            "Early retention (day 1 / week 1) is usually about onboarding and activation, not the core value prop.",
            "Smile-shaped curves (new users churning, old users sticky) mean you have an activation problem.",
            "Compare retention across segments to find who the product really works for.",
        ],
        pitfalls=[
            "Quoting a single retention number without saying which definition and which cohort.",
            "Confusing reactivation with retention - win-back campaigns inflate the number without improving the product.",
            "Celebrating aggregate retention improvements that are just mix shifts toward stickier cohorts.",
        ],
        interview_angle=("Classic in metrics rounds: 'engagement is down 10% "
                        "month on month.' A strong answer reaches for cohorts "
                        "immediately - is it new users not sticking, or old "
                        "users leaving?"),
    ),
    "north_star": _concept(
        name="North Star Metric",
        summary=("The north star is the single metric that best captures the "
                 "core value your product delivers to customers. Everything "
                 "the team does should, directly or indirectly, move it."),
        key_points=[
            "A good north star is a leading indicator of long-term value, not a lagging one.",
            "It must be understandable, measurable, and hard to game.",
            "Pair it with guardrails: metrics that must not regress while the north star grows.",
            "Examples: Airbnb's 'nights booked', Spotify's 'time spent listening', Stripe's payment volume processed.",
            "Every team-level metric should ladder up to it.",
        ],
        pitfalls=[
            "Picking revenue as the north star for a product whose value is user engagement - revenue is a lagging outcome.",
            "A north star the team can't actually move (e.g. company-level revenue for a feature team).",
            "Gaming: optimizing the metric instead of the underlying value (e.g. 'messages sent' driving spam).",
        ],
        interview_angle=("Asked directly ('what should Airbnb's north star "
                        "metric be?') and probed indirectly in product-sense "
                        "answers: candidates who can't name the success metric "
                        "for their own proposal fail the round."),
    ),
    "okrs": _concept(
        name="OKRs (Objectives & Key Results)",
        summary=("Objectives state an ambitious qualitative goal; key results "
                 "are 2-4 measurable outcomes that prove it happened. They "
                 "align teams without dictating how the work gets done."),
        key_points=[
            "Objectives are inspiring and directional; key results are numeric and verifiable.",
            "Stretch is the point: hitting 70% of an ambitious OKR beats sandbagging an easy one.",
            "Limit to 3-5 objectives per team per quarter - more means no real priorities.",
            "Key results should measure outcomes (activation rate), not outputs (ship feature X).",
            "Review weekly, score honestly at quarter end, and carry learnings forward.",
        ],
        pitfalls=[
            "Writing tasks as key results ('launch v2') - that's a roadmap item, not an outcome.",
            "Setting 100% as the expectation, which teaches teams to aim low.",
            "Cascading OKRs so rigidly that teams optimize for their number instead of the company's goal.",
        ],
        interview_angle=("Behavioral and execution rounds: 'tell me about a "
                        "goal you set and missed.' Interviewers look for "
                        "outcome-oriented thinking and honest scoring."),
    ),
    "prioritization": _concept(
        name="Prioritization: RICE & MoSCoW",
        summary=("RICE scores features by Reach x Impact x Confidence / "
                 "Effort to rank them numerically. MoSCoW buckets them into "
                 "Must, Should, Could, and Won't have for the next release. "
                 "Both are tools, not oracles."),
        key_points=[
            "RICE forces you to quantify assumptions - especially Confidence, which is where hand-waving hides.",
            "Use RICE for ranking a backlog; use MoSCoW for scoping a specific release or MVP.",
            "Always sanity-check the output: if the #1 ranked item feels wrong, interrogate the inputs, not the math.",
            "Reach should be users affected per time period, not 'everyone eventually'.",
            "Effort must include engineering, design, and ongoing maintenance - not just build time.",
        ],
        pitfalls=[
            "Treating the score as truth when the inputs are guesses - garbage in, gospel out.",
            "Ignoring strategic bets that score poorly on RICE but matter for the company's future.",
            "Prioritizing without talking to engineering about real effort estimates.",
        ],
        interview_angle=("Execution staple: 'how would you prioritize 3 "
                        "features?' Name a framework, work it live, and say "
                        "out loud which input you'd validate first."),
    ),
    "ab_testing": _concept(
        name="A/B Testing for PMs",
        summary=("Randomize users into control and treatment, measure the "
                 "difference on a primary metric, and ship only if the lift is "
                 "statistically significant, practically meaningful, and "
                 "guardrails stay green."),
        key_points=[
            "Define the metric hierarchy before launch: primary metric, guardrails, diagnostics.",
            "Size the test for power (usually 80%) and fix the runtime in advance - no peeking.",
            "Randomize at the right unit (user, session, geo) to avoid interference.",
            "A statistically significant but tiny lift is usually not worth shipping.",
            "Segment results by platform, cohort, and user type - aggregate wins can hide segment losses.",
        ],
        pitfalls=[
            "Peeking: checking daily and stopping at the first significant result inflates false positives.",
            "Novelty effect: users engage with the new thing because it's new, then revert.",
            "Running too many tests at once without accounting for interaction effects.",
            "Shipping on the primary metric while a guardrail quietly regressed.",
        ],
        interview_angle=("The analytical round's favorite: 'devise an A/B "
                        "test to improve Google Maps.' Lead with metrics and "
                        "randomization unit, then sizing, then the launch "
                        "rule - including what you'd do if guardrails trip."),
    ),
    "unit_economics": _concept(
        name="Unit Economics: LTV & CAC",
        summary=("Unit economics ask whether one customer is worth acquiring: "
                 "lifetime value (LTV) must comfortably exceed customer "
                 "acquisition cost (CAC). The ratio and the payback period "
                 "tell you if the business model works."),
        key_points=[
            "LTV = average revenue per user x gross margin x average lifetime (often 1/churn rate).",
            "CAC includes fully-loaded acquisition spend: ads, sales team, discounts, onboarding costs.",
            "Healthy SaaS rule of thumb: LTV/CAC >= 3, CAC payback under 12 months - but the right bar varies by business.",
            "Cohort LTV by channel: paid and organic users have very different economics.",
            "Improving retention is usually the highest-leverage way to improve LTV.",
        ],
        pitfalls=[
            "Blended CAC hiding a channel that loses money on every customer.",
            "Counting revenue without margin - LTV on gross revenue overstates the economics.",
            "Assuming today's retention persists forever when projecting LTV for young cohorts.",
        ],
        interview_angle=("Strategy and estimation rounds: 'estimate YouTube's "
                        "daily revenue' often leads into 'is this business "
                        "healthy?' Knowing LTV/CAC cold separates PMs who "
                        "think in business terms from feature-listers."),
    ),
    "network_effects": _concept(
        name="Network Effects",
        summary=("A product has network effects when each new user makes it "
                 "more valuable for existing users. They create defensibility "
                 "but also a cold-start problem: the product is weakest when "
                 "it most needs users."),
        key_points=[
            "Direct effects (messaging apps), indirect/two-sided effects (marketplaces: more buyers attract more sellers), and data network effects (more usage improves the model).",
            "Defensibility comes from the effect, not the feature - features get copied, networks don't.",
            "Cold start is the hard part: seed supply, single-player utility, or come-for-the-tool-stay-for-the-network.",
            "Negative network effects exist too: congestion, spam, and noise grow with the network.",
            "Measure with same-side vs cross-side elasticity, not vanity user counts.",
        ],
        pitfalls=[
            "Calling any growth loop a network effect - virality (invites) is not a network effect.",
            "Ignoring the cold-start plan when proposing a marketplace or social product.",
            "Assuming network effects are permanent: multi-tenanting and switching-cost erosion kill them.",
        ],
        interview_angle=("Product-sense design questions for social and "
                        "marketplace products ('design WhatsApp for students'): "
                        "a strong answer names the network effect and the "
                        "cold-start strategy explicitly."),
    ),
    "pricing": _concept(
        name="Pricing & Packaging",
        summary=("Pricing captures value; packaging (tiers, plans, bundles) "
                 "segments customers so each pays according to their "
                 "willingness to pay. The most common failure is pricing the "
                 "feature instead of the value."),
        key_points=[
            "Value-based pricing beats cost-plus and competitor-matching: price the outcome, not the input.",
            "Good packaging aligns the pricing metric with customer value (seats, usage, transactions).",
            "Test willingness to pay with Van Westendorp surveys, conjoint analysis, or - best - actual experiments.",
            "Freemium works when the free tier has near-zero marginal cost and a natural upgrade trigger.",
            "Grandfathering and migration plans matter: price changes anger existing customers more than they attract new ones.",
        ],
        pitfalls=[
            "Too many tiers: choice paralysis kills conversion.",
            "A pricing metric customers can't predict or control (bill shock).",
            "Discounting to close deals, which permanently resets the reference price.",
        ],
        interview_angle=("Strategy questions: 'how would you monetize this?' "
                        "Interviewers want the value metric named, two or three "
                        "tiers sketched, and the upgrade trigger identified."),
    ),
    "gtm": _concept(
        name="Go-to-Market (GTM)",
        summary=("GTM is the plan for getting a product into users' hands: "
                 "who it's for, why they'll care, how they'll hear about it, "
                 "and what success looks like in the first 90 days."),
        key_points=[
            "Start with ICP (ideal customer profile) and the single wedge use case.",
            "Pick channels that match the ICP: PLG, sales-assisted, partnerships, or community - not all of them.",
            "Launch in phases: alpha with design partners, beta for feedback, GA for scale.",
            "Define launch success metrics up front: activation, not just signups.",
            "Plan the feedback loop: how learnings from early users change the roadmap.",
        ],
        pitfalls=[
            "Launching to everyone at once with no design partners and no feedback channel.",
            "Measuring launch success by press coverage instead of activation and retention.",
            "No rollback or kill criteria: every launch needs a 'what if it flops' plan.",
        ],
        interview_angle=("Execution and strategy: 'how would you launch a new "
                        "ChatGPT model?' A strong answer sequences the rollout, "
                        "names the wedge audience, and sets measurable launch "
                        "goals."),
    ),
    "experimentation_pitfalls": _concept(
        name="Experimentation Pitfalls",
        summary=("Most failed experiments fail for the same handful of "
                 "reasons: interference between test groups, novelty effects, "
                 "peeking at results early, and seasonality. Knowing the "
                 "failure modes is what makes experiment results trustworthy."),
        key_points=[
            "Interference: in social/marketplace products, treating one user affects others - use cluster randomization or switchbacks.",
            "Novelty/primacy effects: run long enough to see the effect decay, or split new vs existing users.",
            "Peeking inflates false positives: pre-register the primary metric and the stopping rule.",
            "Seasonality and day-of-week effects: short tests miss weekly cycles.",
            "SRM (sample ratio mismatch): if the split isn't 50/50 as designed, the randomization is broken - stop and debug.",
        ],
        pitfalls=[
            "Trusting a test with SRM because 'the result looks plausible'.",
            "Declaring victory on week 1 of a novelty-driven lift.",
            "User-level randomization in a product with strong network effects.",
        ],
        interview_angle=("Analytical deep-dives after you propose a test: the "
                        "interviewer will attack your design with one of these "
                        "pitfalls. Naming them first shows seniority."),
    ),
    "stakeholder_mgmt": _concept(
        name="Stakeholder Management",
        summary=("PMs have responsibility without authority, so progress runs "
                 "on alignment: knowing who decides, who influences, and who "
                 "just needs to be informed - and keeping each in the right "
                 "loop."),
        key_points=[
            "Map stakeholders on influence vs interest; manage each quadrant differently.",
            "Disagree and commit needs a real decision log: what was decided, by whom, and why.",
            "Bring data and a recommendation to contentious meetings - never just the problem.",
            "Pre-wire: socialize a proposal 1:1 with key stakeholders before the big review.",
            "Escalation is a tool, not a failure - escalate with options, not complaints.",
        ],
        pitfalls=[
            "Surprising a powerful stakeholder in a group meeting.",
            "Confusing consensus (everyone agrees) with alignment (everyone commits).",
            "Letting the loudest stakeholder override the quiet data.",
        ],
        interview_angle=("Behavioral core: 'tell me about a time you handled a "
                        "difficult stakeholder' or 'navigated competing "
                        "leadership priorities.' Have two stories ready, each "
                        "with a measurable outcome."),
    ),
    "root_cause": _concept(
        name="Root-Cause Analysis (Metrics Changes)",
        summary=("When a metric moves unexpectedly, the job is to isolate the "
                 "cause systematically: validate the data, segment the change, "
                 "generate hypotheses, and test them in order of likelihood - "
                 "without jumping to a fix."),
        key_points=[
            "Step 0: check the data itself - instrumentation changes, logging bugs, and definition changes cause most 'mysteries'.",
            "Segment by time (when exactly did it change?), cohort, platform, geography, and traffic source.",
            "External factors: holidays, competitor launches, PR events, app-store featuring.",
            "Internal factors: releases, experiments, marketing campaigns, pricing changes.",
            "State the answer as: cause, evidence, confidence level, and recommended action.",
        ],
        pitfalls=[
            "Proposing fixes before diagnosing - the classic junior move.",
            "Stopping at the first plausible hypothesis (usually 'the last release did it').",
            "Forgetting to check whether the metric definition or pipeline changed.",
        ],
        interview_angle=("The execution round in a nutshell: 'a metric dropped "
                        "30% overnight - what do you do?' Meta and Amazon ask "
                        "variants of this constantly. Structure beats speed."),
    ),
    "strategy_frameworks": _concept(
        name="Product Strategy Frameworks",
        summary=("Strategy frameworks turn 'what should we do?' into a "
                 "structured argument: where to play, how to win, and what "
                 "would have to be true. The framework is scaffolding - the "
                 "judgment is the building."),
        key_points=[
            "Porter's Five Forces: map competitive pressure (rivals, entrants, substitutes, supplier and buyer power).",
            "Moats: what makes the position defensible - network effects, data, brand, switching costs, scale economies.",
            "SWOT is for brainstorming, not decisions; pair it with a concrete recommendation.",
            "Ansoff matrix: market penetration vs product development vs market development vs diversification.",
            "Always end with: the bet, the alternatives rejected, and the metrics that would prove you wrong.",
        ],
        pitfalls=[
            "Framework bingo: naming five frameworks without using any of them to decide something.",
            "Ignoring the company's actual strengths - strategy must start from what you're good at.",
            "A 10-year vision with no 1-year milestones.",
        ],
        interview_angle=("Google's strategy round is famous for pushback: "
                        "'what's the biggest threat to YouTube?' Lead with a "
                        "thesis about the business model, then defend it - "
                        "the interviewer will challenge every unsupported "
                        "claim."),
    ),
}

#: Category -> concept keys, for linking questions to deep-dives
PM_CATEGORY_CONCEPTS: dict[str, list[str]] = {
    "product_sense": ["funnels", "north_star", "network_effects"],
    "metrics": ["north_star", "retention_cohorts", "funnels", "ab_testing"],
    "execution": ["root_cause", "experimentation_pitfalls", "stakeholder_mgmt"],
    "estimation": ["unit_economics", "funnels"],
    "behavioral": ["stakeholder_mgmt", "okrs"],
    "strategy": ["strategy_frameworks", "network_effects", "pricing", "gtm",
                 "unit_economics"],
    "ai_pm": ["ab_testing", "gtm", "experimentation_pitfalls"],
}


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    """Loose normalization: lowercase, whitespace/hyphens to underscores,
    everything else non-alphanumeric dropped."""
    s = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return re.sub(r"[^a-z0-9_]", "", s)


def list_concepts() -> list[str]:
    """Return the concept keys in display order."""
    return list(PM_CONCEPTS)


def get_concept(name: str) -> dict:
    """Return the deep-dive dict for a concept key or display name.

    Matching is case-insensitive and ignores spaces, hyphens, and
    punctuation. Raises PMError for unknown concepts.
    """
    key = _norm_name(name)
    if key in PM_CONCEPTS:
        return PM_CONCEPTS[key]
    for k, c in PM_CONCEPTS.items():
        if _norm_name(c["name"]) == key:
            return c
    raise PMError(f"Unknown PM concept {name!r}. "
                  f"Available: {', '.join(list_concepts())}")


def concepts_for_category(category: str) -> list[dict]:
    """Deep-dives relevant to a question category."""
    cat = (category or "").strip().lower().replace(" ", "_").replace("-", "_")
    return [PM_CONCEPTS[k] for k in PM_CATEGORY_CONCEPTS.get(cat, [])
            if k in PM_CONCEPTS]


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def _render_concept(c: dict) -> str:
    lines = [f"### {c['name']}", "", c["summary"], "",
             "**Key points**"]
    lines += [f"- {p}" for p in c["key_points"]]
    lines += ["", "**Pitfalls**"]
    lines += [f"- {p}" for p in c["pitfalls"]]
    lines += ["", f"**Interview angle.** {c['interview_angle']}"]
    return "\n".join(lines)


def _cmd_concepts(args: argparse.Namespace) -> None:
    if args.name:
        items = [get_concept(args.name)]
    else:
        items = [PM_CONCEPTS[k] for k in list_concepts()]
    if args.json:
        print(json.dumps(items, indent=2))
    else:
        print("\n\n".join(_render_concept(c) for c in items))


def register_pm(pm_subparsers) -> None:
    """Add the `concepts` subcommand to a `pm` parent parser."""
    s = pm_subparsers.add_parser(
        "concepts",
        help="PM concept deep-dives (funnels, retention, North Star, ...).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("examples:\n"
                "  python -m candid pm concepts\n"
                "  python -m candid pm concepts --name north_star\n"
                "  python -m candid pm concepts --name \"A/B Testing\" --json"),
    )
    s.add_argument("--name", default=None,
                   help="Show one concept by key or display name")
    s.add_argument("--json", action="store_true",
                   help="Print concepts as JSON")
    s.set_defaults(func=_cmd_concepts)
