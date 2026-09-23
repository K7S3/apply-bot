"""Staff/principal-track interview prep: ambiguity drill + leveling calibration.

Two tools in one module:

1. Ambiguity drill. Staff+ interviews probe how you handle deliberately
   underspecified problems. AMBIGUITY_SCENARIOS ships ~8 vague briefs, each
   with a decomposition checklist (clarifying questions, unknowns,
   milestones, risks). score_answer() grades a free-text answer with a
   keyword-and-structure HEURISTIC (clearly labeled as such, never a human
   grader) and returns coaching tips.

2. Leveling calibration. LEVEL_EXPECTATIONS holds generic expectations for
   L5/L6/L7 across five dimensions (technical depth, scope, influence,
   mentorship, ambiguity), with a prominent disclaimer that real levels vary
   by company. self_rate() validates the user's own 1-4 ratings, persists
   them to DATA_DIR/staff_level.json, and returns a gap analysis with
   concrete next steps. Gaps are also offered to the study-plan module via a
   best-effort hook that degrades gracefully when candid.study is absent.

CLI (wired by the parent as `python -m candid staff ...`; argv here is
everything after `staff`):

    staff ambiguity [--list] [--scenario ID] [--answer-file F]
    staff level [--table] [--rate dim=1-4 ...] [--target L6|L7] [--json]

All data is local. No network, no paid APIs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import json
import re
import sys

from candid import config as _cfg


class StaffError(Exception):
    """Expected staff-assess failure: bad scenario id, bad ratings, bad flags."""


# ---------------------------------------------------------------------------
# 1. Ambiguity drill
# ---------------------------------------------------------------------------

AMBIGUITY_SCENARIOS: list[dict] = [
    {
        "id": "stalled-migration",
        "title": "The VP says the migration is stalled",
        "brief": (
            "Your VP stops you in the hallway: 'The ads serving migration off "
            "the legacy stack is stalled. I need you to get it moving.' That is "
            "the whole brief. Two teams are involved, the timeline was 'Q3', "
            "and nobody can tell you what 'done' means."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What does 'done' mean for this migration: traffic cutover, decommission, or both?",
                "Who asked for this migration and what business outcome does it serve?",
                "Which two teams are involved, and who currently owns the schedule?",
                "What does 'stalled' mean here: blocked, slow, or deprioritized?",
            ],
            "unknowns": [
                "Actual migration progress versus the Q3 timeline",
                "Blockers each team is hitting (technical, staffing, dependencies)",
                "Whether the legacy stack has a hard decommission date",
                "What happens to each team's other commitments during the migration",
            ],
            "milestones": [
                "Write down a shared definition of done and get both teams to sign off",
                "Publish a current-state audit: what is migrated and what is not",
                "Propose a phased cutover plan with rollback criteria",
                "Set a weekly 30-minute sync with a single owner until it is done",
            ],
            "risks": [
                "Declaring victory at partial cutover while the legacy stack quietly stays up",
                "One team doing all the work while the other disengages",
                "A rushed cutover breaking serving during a revenue-critical period",
                "Fixing the schedule without addressing why it stalled (it will stall again)",
            ],
        },
    },
    {
        "id": "build-vs-buy",
        "title": "Build or buy: the feature store question",
        "brief": (
            "The CTO asks for a recommendation by Friday: build a feature store "
            "in-house or buy a vendor solution. The ML teams are split, the "
            "budget owner is skeptical of vendors, and the only hard requirement "
            "anyone states is 'it has to be fast'."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What does 'fast' mean: p99 latency numbers, throughput, freshness SLAs?",
                "Which teams will use it in year one, and what are their actual access patterns?",
                "What is the real budget envelope, including headcount to build and maintain?",
                "What happens if we do nothing for six months?",
            ],
            "unknowns": [
                "True cost of building: eng-years, maintenance tail, on-call burden",
                "Vendor lock-in risk and data-egress costs",
                "Whether existing infra already covers 80 percent of the need",
                "Who owns the decision if the recommendation is contested",
            ],
            "milestones": [
                "Interview 3-5 ML teams and write up concrete requirements",
                "Build a total-cost-of-ownership model for build versus 2-3 vendors",
                "Run a two-week spike or vendor POC against the top requirements",
                "Present a recommendation with a rollback plan on Friday",
            ],
            "risks": [
                "Optimizing for the loudest team instead of the common case",
                "Underestimating the maintenance tail of a build decision",
                "Picking a vendor that cannot meet latency SLAs at our scale",
                "Analysis paralysis: missing Friday with a 'need more data' answer",
            ],
        },
    },
    {
        "id": "p99-spike",
        "title": "p99 latency doubled and nobody owns serving",
        "brief": (
            "Ranking p99 latency doubled overnight. The serving stack was split "
            "across three teams in the last reorg and nobody claims ownership. "
            "The on-call rotations point at each other. Revenue impact is unclear "
            "but the ads team is nervous."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "When exactly did the spike start, and what changed in that window (deploys, config, traffic)?",
                "Who is the current on-call for each piece of the serving path?",
                "Is the spike global or isolated to certain models, regions, or traffic slices?",
                "What is the actual revenue or user impact so far?",
            ],
            "unknowns": [
                "Which component in the serving path is the bottleneck",
                "Whether this is a regression or a traffic-pattern change",
                "Who has the authority to roll back or hotfix each service",
                "Whether the doubled p99 is real or a measurement artifact",
            ],
            "milestones": [
                "Establish a single incident commander and a shared status doc",
                "Bisect the timeline: correlate the spike with deploys and config changes",
                "Mitigate first (rollback, shed load, add capacity), then root-cause",
                "Assign permanent ownership of the serving path before closing the incident",
            ],
            "risks": [
                "Three parallel investigations duplicating work and confusing the timeline",
                "Fixing symptoms (more capacity) while the regression stays in",
                "No owner means the postmortem actions die quietly",
                "Declaring 'resolved' on a metric dip without understanding the cause",
            ],
        },
    },
    {
        "id": "shadow-roadmaps",
        "title": "Three teams building the same thing",
        "brief": (
            "You discover by accident that three teams are each building "
            "model-monitoring dashboards. Each believes theirs is the official "
            "one. There is no shared plan, and each team has already spent a "
            "quarter on it."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What problem is each team actually solving: are the use cases really identical?",
                "Who funded each effort and what did they promise their stakeholders?",
                "Is there an existing platform or standard these should build on?",
                "What would each team need to see to converge on one solution?",
            ],
            "unknowns": [
                "How much overlap versus genuine difference in requirements",
                "Sunk cost and political cost of asking a team to stop",
                "Whether a single solution can serve all three use cases",
                "Who has the authority to declare one canonical effort",
            ],
            "milestones": [
                "Map the three efforts: scope, users, timeline, sunk cost",
                "Identify the genuinely shared core versus team-specific needs",
                "Propose a convergence plan: one platform, team-specific extensions",
                "Get explicit agreement (and a named owner) before anyone writes more code",
            ],
            "risks": [
                "Forcing convergence on the wrong solution and losing all three teams",
                "Letting it ride: three half-maintained dashboards forever",
                "The conversation becoming about credit and headcount instead of users",
                "A top-down mandate that nobody adopts",
            ],
        },
    },
    {
        "id": "fuzzy-h2-goal",
        "title": "Turn 'improve ML quality' into an H2 plan",
        "brief": (
            "H2 planning starts Monday. The org goal handed to you is 'improve ML "
            "quality'. No metrics, no owner, no baseline. You are expected to turn "
            "it into a plan the org can execute."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "Whose quality: which models, which teams, which users feel the pain?",
                "How is quality measured today, and do we trust those numbers?",
                "What quality problems cost the most (revenue, trust, velocity)?",
                "What resources and headcount are actually available in H2?",
            ],
            "unknowns": [
                "Baseline metrics for whatever 'quality' ends up meaning",
                "Which quality levers are actually movable in one half",
                "Competing org priorities that will fight for the same eng time",
                "Whether 'quality' means model metrics, system reliability, or both",
            ],
            "milestones": [
                "Define quality in measurable terms with 2-3 candidate metrics",
                "Establish baselines and pick one north-star metric plus guardrails",
                "Propose 3-5 bets mapped to the metric, sized for H2 capacity",
                "Set a monthly review cadence with a single owner per bet",
            ],
            "risks": [
                "Picking a metric that is easy to game instead of one that matters",
                "A plan so broad it means nothing ('everyone improve quality')",
                "No baseline means no way to show progress at the end of H2",
                "Planning in a vacuum while teams commit to conflicting roadmaps",
            ],
        },
    },
    {
        "id": "orphan-monolith",
        "title": "The monolith everyone depends on and nobody owns",
        "brief": (
            "The recommendations monolith serves half the company's traffic. Every "
            "team depends on it, nobody owns it, on-call is miserable, and deploys "
            "are frozen most weeks. Leadership wants a plan, not complaints."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What breaks most often, and what does on-call pain actually cost?",
                "Which teams depend on which parts of the monolith?",
                "What has been tried before, and why did it stall?",
                "What does leadership need: stability now, or a path to decomposition?",
            ],
            "unknowns": [
                "The real dependency graph (docs are stale; the code is the truth)",
                "Whether the monolith can be stabilized without a rewrite",
                "Team capacity to take on ownership or extraction work",
                "What 'done' looks like: stable monolith versus decomposed services",
            ],
            "milestones": [
                "Stabilize first: unfreeze deploys, fix the top 3 on-call pain points",
                "Map dependencies and identify natural seams for extraction",
                "Propose an ownership model: one owning team plus contribution norms",
                "Lay out a phased strangler plan with success metrics per phase",
            ],
            "risks": [
                "Proposing a big-bang rewrite that never ships",
                "Stabilization work being invisible and unrewarded",
                "Extracting services along the wrong seams and making things worse",
                "Ownership assigned on paper but not in practice",
            ],
        },
    },
    {
        "id": "exec-two-minutes",
        "title": "The CEO asks about model explainability at all-hands",
        "brief": (
            "At all-hands, the CEO asks you directly: 'Why can't our models "
            "explain themselves?' You have about two minutes, a non-technical "
            "audience, and no slides. The question is vague but the room is watching."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What decision is the explanation for: regulators, customers, or internal debugging?",
                "Is this about one product's models or all of them?",
                "What prompted the question: a customer ask, a press story, a compliance review?",
                "What would a good answer unlock for the business?",
            ],
            "unknowns": [
                "Which explainability techniques we already use versus what is missing",
                "Regulatory or contractual obligations around explanations",
                "The cost and accuracy tradeoff of more interpretable models",
                "Whether 'explain' means global understanding or per-decision reasons",
            ],
            "milestones": [
                "Give a crisp 2-minute answer: what we can explain today, what we cannot, and why",
                "Follow up with a one-pager on options and costs",
                "Pilot explainability tooling on the highest-stakes model",
                "Report back at the next all-hands with progress",
            ],
            "risks": [
                "Overpromising ('we will make everything explainable by Q4')",
                "A purely technical answer that loses the room",
                "Treating it as a research problem when it is a product and compliance question",
                "No follow-up: the question resurfaces next quarter, unanswered",
            ],
        },
    },
    {
        "id": "staff-standoff",
        "title": "Two staff engineers, one storage layer, zero progress",
        "brief": (
            "Two staff engineers disagree loudly about the storage layer for the new "
            "training platform: one wants a managed service, the other wants to build "
            "on open-source. The project is stuck, the team is taking sides, and the "
            "deadline is not moving."
        ),
        "decomposition_checklist": {
            "clarifying_questions": [
                "What are the actual requirements: scale, latency, durability, cost envelope?",
                "What is each person's real concern underneath the position (cost? control? past experience?)",
                "What did the original design review decide, if anything?",
                "What is the cost of another month of standoff versus a wrong-but-reversible choice?",
            ],
            "unknowns": [
                "Whether the requirements genuinely discriminate between the options",
                "How reversible each choice is (the real decision criterion)",
                "Team expertise to operate either option",
                "What the team needs from you: a decision, a process, or air cover",
            ],
            "milestones": [
                "Write down requirements and decision criteria both sides accept",
                "Time-box a spike or POC on the top 2-3 discriminating criteria",
                "Make the call with written rationale, or escalate with a recommendation",
                "Set a revisit date so the decision does not become permanent by default",
            ],
            "risks": [
                "Winning the argument but losing the engineer",
                "Deciding by seniority or loudness instead of criteria",
                "A compromise that gets the worst of both options",
                "The standoff becoming about status rather than storage",
            ],
        },
    },
]

_DIMENSION_IDS = (
    "clarifying_questions",
    "unknowns",
    "milestones",
    "risks",
)

# Generic structural probes per dimension (regex fragments, case-insensitive).
_DIM_PROBES: dict[str, list[str]] = {
    "clarifying_questions": [
        r"\?", r"\bwho\b", r"\bwhat\b", r"\bwhen\b", r"\bwhere\b", r"\bwhy\b",
        r"\bhow\b", r"\bwhich\b", r"clarif", r"\bask\b", r"question",
        r"confirm", r"understand",
    ],
    "unknowns": [
        r"unknown", r"unclear", r"don'?t know", r"do not know", r"need to find",
        r"assum", r"missing", r"not sure", r"verify", r"validate",
    ],
    "milestones": [
        r"milestone", r"\bweek\b", r"phase", r"\bstep\b", r"first", r"\bthen\b",
        r"\bnext\b", r"\bplan\b", r"timeline", r"roadmap", r"deadline",
        r"\bmvp\b", r"pilot", r"rollout", r"cutover",
    ],
    "risks": [
        r"risk", r"trade-?off", r"concern", r"fail", r"mitigat", r"rollback",
        r"downside", r"blast radius", r"watch out", r"stall",
    ],
}

_DIM_TIPS: dict[str, str] = {
    "clarifying_questions": (
        "Tip: start every ambiguous brief with questions, not answers. Ask who the "
        "stakeholder is, what 'done' means, and what the real deadline and "
        "decision-maker are. Questions asked out loud beat assumptions kept quiet."
    ),
    "unknowns": (
        "Tip: name what you do not know explicitly. Staff-level answers separate "
        "facts from assumptions and say how each unknown will be resolved (a "
        "measurement, a conversation, a spike), not just that it exists."
    ),
    "milestones": (
        "Tip: convert the fog into a sequence. Propose concrete first steps with "
        "owners and time boxes: an audit this week, a decision doc next week, a "
        "pilot after that. Ambiguity shrinks when there is a next step."
    ),
    "risks": (
        "Tip: name the failure modes before they name you. Every plan needs its "
        "top risks and mitigations: what breaks, who gets hurt, and what the "
        "rollback is. Interviewers listen for this explicitly."
    ),
}

_STOPWORDS = frozenset(
    "the a an and or of to in for on with is are was were be been by as at "
    "from that this it its into out over under between what when where who "
    "which how why does did has have had will would could should can cannot "
    "not no nor but if then than so such each other their there here all any "
    "more most per versus via".split()
)


def list_scenarios() -> list[dict]:
    """Return the ambiguity scenarios (id + title only)."""
    return [{"id": s["id"], "title": s["title"]} for s in AMBIGUITY_SCENARIOS]


def get_scenario(scenario_id: str) -> dict:
    """Return the full scenario dict for an id, else raise StaffError."""
    for s in AMBIGUITY_SCENARIOS:
        if s["id"] == scenario_id:
            return s
    known = ", ".join(s["id"] for s in AMBIGUITY_SCENARIOS)
    raise StaffError(f"Unknown scenario {scenario_id!r}. Known: {known}")


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", text.lower())
    return [w for w in words if len(w) >= 4 and w not in _STOPWORDS]


def _item_touched(item: str, answer_lc: str) -> str | None:
    """Return the first checklist-item keyword found in the answer, else None."""
    for kw in _keywords(item):
        if re.search(r"\b" + re.escape(kw) + r"\b", answer_lc):
            return kw
    return None


def score_answer(scenario_id: str, answer_text: str) -> dict:
    """Score a free-text answer against a scenario's decomposition checklist.

    This is a keyword-and-structure HEURISTIC, not a human grader: it checks
    whether the answer touches each checklist item (via keyword overlap) and
    whether it shows the structural markers of each dimension (questions,
    unknowns named, milestones proposed, risks flagged). It cannot judge
    quality, correctness, or insight. The returned dict says so explicitly.
    """
    scenario = get_scenario(scenario_id)
    text = answer_text or ""
    lc = text.lower()

    dimensions: dict[str, dict] = {}
    for dim in _DIMENSION_IDS:
        items = scenario["decomposition_checklist"][dim]
        hits, misses = [], []
        for item in items:
            (hits if _item_touched(item, lc) else misses).append(item)
        coverage = len(hits) / len(items) if items else 0.0
        probes = _DIM_PROBES[dim]
        probe_hits = sum(1 for p in probes if re.search(p, lc))
        probe_score = probe_hits / len(probes) if probes else 0.0
        score = round(0.7 * coverage + 0.3 * probe_score, 2)
        dimensions[dim] = {
            "score": score,
            "checklist_hits": hits,
            "checklist_misses": misses,
            "tip": _DIM_TIPS[dim] if misses else "",
        }

    overall = round(sum(d["score"] for d in dimensions.values()) / len(dimensions), 2)
    band = "strong" if overall >= 0.7 else "solid" if overall >= 0.4 else "developing"
    structure = {
        "word_count": len(text.split()),
        "question_count": text.count("?"),
        "has_list": bool(re.search(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", text)),
    }
    return {
        "scenario_id": scenario_id,
        "title": scenario["title"],
        "heuristic": True,
        "heuristic_note": (
            "Keyword-and-structure heuristic, NOT a human grader. It rewards "
            "covering the checklist topics and using the right structure "
            "(questions, named unknowns, milestones, risks); it cannot judge "
            "correctness, depth, or insight. Use it for practice reps, not verdicts."
        ),
        "dimensions": dimensions,
        "overall": {"score": overall, "band": band},
        "structure": structure,
    }


def format_scenario_list() -> str:
    lines = ["Ambiguity drill scenarios (staff-track):", ""]
    for s in AMBIGUITY_SCENARIOS:
        lines.append(f"  {s['id']:<18} {s['title']}")
    lines += [
        "",
        "Show one:  staff ambiguity --scenario <id>",
        "Practice:   staff ambiguity --scenario <id> --answer-file answer.txt",
        "            (or pipe/stdin: staff ambiguity --scenario <id> < answer.txt)",
    ]
    return "\n".join(lines)


def format_scenario(scenario: dict) -> str:
    labels = {
        "clarifying_questions": "Clarifying questions to ask",
        "unknowns": "Unknowns to surface",
        "milestones": "Milestones to propose",
        "risks": "Risks to name",
    }
    lines = [f"Scenario: {scenario['title']} ({scenario['id']})", "", scenario["brief"], ""]
    for dim in _DIMENSION_IDS:
        lines.append(f"{labels[dim]}:")
        for item in scenario["decomposition_checklist"][dim]:
            lines.append(f"  - {item}")
        lines.append("")
    lines.append(
        "Practice: write your decomposition, then score it with\n"
        f"  staff ambiguity --scenario {scenario['id']} --answer-file answer.txt"
    )
    return "\n".join(lines).rstrip()


def format_score(score: dict) -> str:
    labels = {
        "clarifying_questions": "Clarifying questions",
        "unknowns": "Unknowns surfaced",
        "milestones": "Milestones proposed",
        "risks": "Risks named",
    }
    st = score["structure"]
    lines = [
        f"Ambiguity drill: {score['title']} ({score['scenario_id']})",
        "NOTE: heuristic scoring, not a human grader. See docs/staff_assess.md.",
        "",
        f"Overall: {score['overall']['score']:.2f} ({score['overall']['band']})",
        f"Words: {st['word_count']} | Questions asked: {st['question_count']} | "
        f"Uses a list: {'yes' if st['has_list'] else 'no'}",
        "",
    ]
    for dim in _DIMENSION_IDS:
        d = score["dimensions"][dim]
        lines.append(f"{labels[dim]}: {d['score']:.2f}")
        for item in d["checklist_hits"]:
            lines.append(f"  [hit]  {item}")
        for item in d["checklist_misses"]:
            lines.append(f"  [miss] {item}")
        if d["tip"]:
            lines.append(f"  {d['tip']}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# 2. Leveling calibration
# ---------------------------------------------------------------------------

LEVEL_DISCLAIMER = (
    "DISCLAIMER: levels vary widely by company. These are GENERIC staff-track "
    "expectations for practice and self-reflection, not any employer's actual "
    "leveling rubric. Always calibrate against the specific company's leveling "
    "guide and your recruiter's guidance before an interview loop."
)

DIMENSIONS = ("technical_depth", "scope", "influence", "mentorship", "ambiguity")

DIM_LABELS = {
    "technical_depth": "Technical depth",
    "scope": "Scope",
    "influence": "Influence",
    "mentorship": "Mentorship",
    "ambiguity": "Ambiguity handling",
}

LEVELS = ("L5", "L6", "L7")

LEVEL_EXPECTATIONS: dict[str, dict] = {
    "L5": {
        "label": "Senior engineer (generic L5)",
        "expectations": {
            "technical_depth": "Deep expertise in one or two areas; ships complex work independently.",
            "scope": "Owns team-level projects end to end.",
            "influence": "Influences the immediate team and close partners through code and reviews.",
            "mentorship": "Mentors junior engineers; gives useful, timely code reviews.",
            "ambiguity": "Handles moderately ambiguous tasks; asks good questions to clarify them.",
        },
        "min_rating": {d: 2 for d in DIMENSIONS},
    },
    "L6": {
        "label": "Staff engineer (generic L6)",
        "expectations": {
            "technical_depth": "Deep across multiple areas; sets technical direction for the org.",
            "scope": "Owns multi-team or org-level initiatives with several stakeholders.",
            "influence": "Drives alignment across teams; writes the docs and RFCs others follow.",
            "mentorship": "Grows senior engineers; raises the bar through reviews and guidance.",
            "ambiguity": "Thrives in high ambiguity; decomposes vague org-level problems into plans.",
        },
        "min_rating": {d: 3 for d in DIMENSIONS},
    },
    "L7": {
        "label": "Principal engineer (generic L7)",
        "expectations": {
            "technical_depth": "Company-recognized authority; shapes technology strategy.",
            "scope": "Owns company-level technical bets spanning multiple orgs.",
            "influence": "Influences company strategy; externally visible (talks, standards, publications).",
            "mentorship": "Develops staff-level engineers; creates org-wide engineering practices.",
            "ambiguity": "Defines the problem space itself; creates clarity where none exists.",
        },
        "min_rating": {d: 4 for d in DIMENSIONS},
    },
}

NEXT_STEPS: dict[str, str] = {
    "technical_depth": (
        "Pick one area adjacent to your depth and ship something real in it: a "
        "design doc, a prototype, or a production change. Staff depth is breadth "
        "with judgment, not just one specialty."
    ),
    "scope": (
        "Volunteer to own a workstream spanning two teams, with stakeholders "
        "outside your own. Practice writing the one-page plan that others execute "
        "against, then run the weekly sync that keeps it honest."
    ),
    "influence": (
        "Write the RFC or decision doc for your team's next contentious choice, "
        "with options, tradeoffs, and a recommendation. Staff-level influence is "
        "written down and adopted, not won in meetings."
    ),
    "mentorship": (
        "Mentor one engineer more senior than 'junior': do regular design reviews "
        "with them and track their growth over a quarter. Staff mentorship grows "
        "seniors, not just interns."
    ),
    "ambiguity": (
        "Take the next vague ask you receive and return a decomposition: "
        "questions, unknowns, milestones, risks. Run this module's ambiguity "
        "drill weekly until decomposing first becomes habit."
    ),
}


def _level_path():
    return _cfg.DATA_DIR / "staff_level.json"


def level_table() -> dict:
    """Return the generic leveling table plus its disclaimer."""
    return {
        "disclaimer": LEVEL_DISCLAIMER,
        "levels": LEVELS,
        "dimensions": [
            {"id": d, "label": DIM_LABELS[d]} for d in DIMENSIONS
        ],
        "expectations": {
            lvl: {
                "label": LEVEL_EXPECTATIONS[lvl]["label"],
                "dimensions": {
                    d: {
                        "expectation": LEVEL_EXPECTATIONS[lvl]["expectations"][d],
                        "min_rating": LEVEL_EXPECTATIONS[lvl]["min_rating"][d],
                    }
                    for d in DIMENSIONS
                },
            }
            for lvl in LEVELS
        },
    }


def _study_plan_hook(items: list[dict]) -> dict:
    """Best-effort handoff of gaps to the study-plan module.

    Tries candid.study entry points (record_gaps, add_items, add_goals) and
    degrades gracefully when the module - or a recognized entry point - is
    absent. The gap items are always returned so callers can consume them.
    """
    try:
        study = importlib.import_module("candid.study")
    except Exception:
        return {
            "consumed": False,
            "reason": "candid.study is not available in this worktree",
            "items": items,
        }
    for attr in ("record_gaps", "add_items", "add_goals"):
        fn = getattr(study, attr, None)
        if callable(fn):
            try:
                fn(items)
            except Exception as exc:  # never let the hook break self-rating
                return {
                    "consumed": False,
                    "reason": f"candid.study.{attr} raised: {exc}",
                    "items": items,
                }
            return {"consumed": True, "via": f"candid.study.{attr}", "items": items}
    return {
        "consumed": False,
        "reason": "candid.study has no recognized gap entry point",
        "items": items,
    }


def self_rate(ratings: dict, target: str = "L6") -> dict:
    """Validate the USER's own 1-4 self-ratings, persist them, return gaps.

    ratings maps dimension id -> int 1-4. target is a generic level (L5/L6/L7).
    A gap is any dimension rated below the target level's minimum expectation.
    Each gap carries a concrete next-step suggestion. Never invents ratings:
    every number here comes from the caller.
    """
    if target not in LEVELS:
        raise StaffError(f"Unknown target level {target!r}. Choose from {', '.join(LEVELS)}.")
    if not isinstance(ratings, dict):
        raise StaffError("ratings must be a dict of dimension -> 1-4.")
    missing = [d for d in DIMENSIONS if d not in ratings]
    if missing:
        raise StaffError(
            "Missing dimensions: " + ", ".join(missing) +
            ". Rate all of: " + ", ".join(DIMENSIONS)
        )
    extra = [d for d in ratings if d not in DIMENSIONS]
    if extra:
        raise StaffError(f"Unknown dimensions: {', '.join(extra)}. Use: {', '.join(DIMENSIONS)}")
    clean: dict[str, int] = {}
    for dim in DIMENSIONS:
        v = ratings[dim]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 4:
            raise StaffError(
                f"Rating for {dim!r} must be an integer 1-4, got {v!r}."
            )
        clean[dim] = v

    expected = LEVEL_EXPECTATIONS[target]["min_rating"]
    gaps = []
    for dim in DIMENSIONS:
        if clean[dim] < expected[dim]:
            gaps.append({
                "dimension": dim,
                "label": DIM_LABELS[dim],
                "rating": clean[dim],
                "expected_min": expected[dim],
                "expectation": LEVEL_EXPECTATIONS[target]["expectations"][dim],
                "next_step": NEXT_STEPS[dim],
            })

    _cfg.ensure_data_dirs()
    record = {
        "target": target,
        "ratings": clean,
        "gap_dimensions": [g["dimension"] for g in gaps],
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    path = _level_path()
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    study_items = [
        {
            "dimension": g["dimension"],
            "label": g["label"],
            "rating": g["rating"],
            "expected_min": g["expected_min"],
            "next_step": g["next_step"],
            "source": "staff_assess.self_rate",
            "target_level": target,
        }
        for g in gaps
    ]
    return {
        "target": target,
        "target_label": LEVEL_EXPECTATIONS[target]["label"],
        "ratings": clean,
        "expected_min": dict(expected),
        "gaps": gaps,
        "saved_to": str(path),
        "study_plan": _study_plan_hook(study_items),
    }


def load_ratings() -> dict | None:
    """Load the persisted self-ratings, or None if never rated."""
    path = _level_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def format_level_table() -> str:
    lines = [LEVEL_DISCLAIMER, ""]
    for lvl in LEVELS:
        info = LEVEL_EXPECTATIONS[lvl]
        lines.append(f"{lvl} - {info['label']}")
        for dim in DIMENSIONS:
            lines.append(
                f"  {DIM_LABELS[dim]:<18} (min rating {info['min_rating'][dim]}/4): "
                f"{info['expectations'][dim]}"
            )
        lines.append("")
    lines.append(
        "Self-rate: staff level --rate technical_depth=3 --rate scope=2 "
        "--target L6"
    )
    return "\n".join(lines).rstrip()


def format_self_rate(result: dict) -> str:
    lines = [
        f"Self-rating vs {result['target']} ({result['target_label']})",
        "",
        "Your ratings (1-4):",
    ]
    for dim in DIMENSIONS:
        mark = "GAP" if any(g["dimension"] == dim for g in result["gaps"]) else "ok "
        lines.append(
            f"  [{mark}] {DIM_LABELS[dim]:<18} {result['ratings'][dim]} "
            f"(expected min {result['expected_min'][dim]})"
        )
    lines.append("")
    if not result["gaps"]:
        lines.append(
            f"No gaps: your ratings meet the generic {result['target']} bar on all "
            "dimensions. Keep evidence handy: interviewers probe with stories, not scores."
        )
    else:
        lines.append(f"Gaps vs {result['target']} ({len(result['gaps'])}):")
        for g in result["gaps"]:
            lines += [
                "",
                f"- {g['label']}: rated {g['rating']}, expected min {g['expected_min']}",
                f"  Expectation: {g['expectation']}",
                f"  Next step: {g['next_step']}",
            ]
    hook = result["study_plan"]
    lines += [
        "",
        f"Saved to {result['saved_to']}",
        "Study-plan hook: "
        + (
            f"consumed via {hook['via']}"
            if hook["consumed"]
            else f"not consumed ({hook['reason']}); gap items are in --json output"
        ),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_answer_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise StaffError(f"Cannot read answer file {path!r}: {exc}")


def _read_answer_stdin() -> str:
    if sys.stdin.isatty():
        sys.stderr.write(
            "Type or paste your answer below, then press Ctrl-D (Ctrl-Z on Windows) "
            "to score it.\n"
        )
    return sys.stdin.read()


def _parse_rate(entries: list[str]) -> dict:
    ratings: dict[str, int] = {}
    for entry in entries:
        if "=" not in entry:
            raise StaffError(
                f"Bad --rate value {entry!r}: use dim=1-4, e.g. --rate scope=3."
            )
        raw_dim, raw_val = entry.split("=", 1)
        dim = raw_dim.strip().lower().replace("-", "_").replace(" ", "_")
        if dim not in DIMENSIONS:
            raise StaffError(
                f"Unknown dimension {raw_dim!r}. Use: {', '.join(DIMENSIONS)}"
            )
        try:
            val = int(raw_val.strip())
        except ValueError:
            raise StaffError(
                f"Bad rating {raw_val!r} for {dim}: must be an integer 1-4."
            )
        ratings[dim] = val
    return ratings


def _cmd_ambiguity(a) -> int:
    if a.list or (not a.scenario and not a.answer_file):
        print(format_scenario_list())
        return 0
    if not a.scenario:
        sys.stderr.write(
            "Error: --scenario ID is required with --answer-file.\n"
            "Run `staff ambiguity --list` to see scenario ids.\n"
        )
        return 2
    try:
        scenario = get_scenario(a.scenario)
    except StaffError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    if a.answer_file:
        try:
            answer = _read_answer_file(a.answer_file)
        except StaffError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return 1
        print(format_score(score_answer(a.scenario, answer)))
        return 0
    if not sys.stdin.isatty():
        # Piped stdin: score it directly. Under test harnesses stdin may be
        # unreadable; fall back to showing the scenario in that case.
        try:
            piped = sys.stdin.read()
        except OSError:
            piped = ""
        if piped.strip():
            print(format_score(score_answer(a.scenario, piped)))
            return 0
        print(format_scenario(scenario))
        return 0
    # interactive terminal: show the scenario, then read the answer
    print(format_scenario(scenario))
    print()
    answer = _read_answer_stdin()
    if not answer.strip():
        sys.stderr.write("No answer entered; nothing scored.\n")
        return 1
    print()
    print(format_score(score_answer(a.scenario, answer)))
    return 0


def _cmd_level(a) -> int:
    rated = bool(a.rate)
    if a.table or not rated:
        print(format_level_table())
    if not rated:
        return 0
    try:
        entries = [e for group in a.rate for e in group]
        ratings = _parse_rate(entries)
        result = self_rate(ratings, target=a.target)
    except StaffError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    if a.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_self_rate(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="staff",
        description="Staff/principal-track prep: ambiguity drill + leveling calibration.",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<subcommand>")

    s = sub.add_parser(
        "ambiguity",
        help="Practice decomposing deliberately underspecified staff-level problems.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n  python -m candid staff ambiguity\n  python -m candid staff ambiguity --scenario p99-spike --answer-file answer.txt",
    )
    s.add_argument("--list", action="store_true", help="List all scenarios")
    s.add_argument("--scenario", metavar="ID", help="Scenario id (see --list)")
    s.add_argument("--answer-file", metavar="F",
                   help="File with your answer text; scored against the checklist")
    s.set_defaults(func=_cmd_ambiguity)

    s = sub.add_parser(
        "level",
        help="Leveling calibration: generic L5/L6/L7 expectations + self-rating.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n  python -m candid staff level --table\n  python -m candid staff level --rate technical-depth=3 --target L6",
    )
    s.add_argument("--table", action="store_true",
                   help="Show the generic leveling table")
    s.add_argument("--rate", action="append", nargs="+", default=[],
                   metavar="dim=1-4",
                   help="Self-rating, repeatable or space-separated: "
                        "--rate technical_depth=3 --rate scope=2 ...")
    s.add_argument("--target", default="L6", choices=list(LEVELS),
                   help="Target level for gap analysis (default: L6)")
    s.add_argument("--json", action="store_true",
                   help="Print the self-rating result as JSON (for scripting)")
    s.set_defaults(func=_cmd_level)
    return p


def main(argv=None) -> int:
    """Entry point. argv holds args after `staff`. Returns process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except StaffError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
