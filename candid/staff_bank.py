"""Staff/principal engineer interview question bank + behavioral rubrics.

Scope: staff-and-above loops (levels 6/7 as generic labels - see
LEVELS_DISCLAIMER). These banks are *practice prompts*, not reported
company questions: every entry carries source="candid practice prompt"
so the tooling never fabricates "asked at company X" claims.

Question bank: QUESTIONS keyed by dimension -
  scope | influence | ambiguity | org-design | mentorship
Entry fields: q, dimension, level (subset of [6, 7]), good_signals,
follow_ups, source.

Rubrics: RUBRICS keyed by dimension -
  technical-judgment | org-influence | mentorship |
  delivery-through-others | ambiguity-handling
Each rubric: 1-4 scale with observable signals per level.

Usage (module-level; the top-level CLI wires these subcommands):
  staff questions [--dimension D] [--level 6|7] [--limit N] [--json]
  staff rubric list | --dimension D
"""

from __future__ import annotations

import argparse
import json


class StaffError(Exception):
    """Raised for bad staff-bank requests (unknown dimension, bad level)."""


LEVELS_DISCLAIMER = (
    "Levels 6/7 are generic labels for staff/principal-caliber scope. "
    "Level numbering varies by company (some use L6/L7, some use "
    "E6/E7, IC6/IC7, or entirely different ladders). Map to the "
    "target company's ladder before using level filters."
)

SOURCE_TAG = "candid practice prompt"

DIMENSIONS = ["scope", "influence", "ambiguity", "org-design", "mentorship"]

RUBRIC_DIMENSIONS = [
    "technical-judgment",
    "org-influence",
    "mentorship",
    "delivery-through-others",
    "ambiguity-handling",
]


# ---------------------------------------------------------------------------
# Question bank: ~40 practice questions across 5 staff dimensions.
# ---------------------------------------------------------------------------

QUESTIONS: dict[str, list[dict]] = {
    "scope": [
        {
            "q": "Tell me about the largest technical system or program you owned end to end. What was the scope, and how did you define it?",
            "dimension": "scope",
            "level": [6, 7],
            "good_signals": [
                "Names the boundaries of ownership (teams, services, users affected)",
                "Explains how scope was negotiated, not just assigned",
                "Quantifies impact in business terms where possible",
            ],
            "follow_ups": [
                "What did you explicitly decide NOT to own, and why?",
                "How did the scope change over time?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a time you drove a multi-team technical initiative. How did you keep the teams aligned?",
            "dimension": "scope",
            "level": [6, 7],
            "good_signals": [
                "Describes concrete alignment mechanisms (RFCs, shared milestones, decision logs)",
                "Shows they handled conflicting team incentives",
                "Outcome tied to delivery, not just activity",
            ],
            "follow_ups": [
                "What broke down, and how did you fix it?",
                "How did you measure progress across teams?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Walk me through the most complex technical tradeoff you have made. What were you optimizing for?",
            "dimension": "scope",
            "level": [6],
            "good_signals": [
                "Lays out options with explicit tradeoffs (cost, latency, operability, speed)",
                "Names who the decision affected and how they were informed",
                "Acknowledges what they would do differently with hindsight",
            ],
            "follow_ups": [
                "Who disagreed with your call, and what convinced them (or not)?",
                "How did the tradeoff hold up over time?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you set technical direction for an organization, not just your team.",
            "dimension": "scope",
            "level": [7],
            "good_signals": [
                "Shows the direction influenced multiple teams or a whole org",
                "Explains the mechanism (vision doc, platform bet, standards)",
                "Evidence of adoption, not just publication",
            ],
            "follow_ups": [
                "How did you get buy-in from teams that did not report to you?",
                "What failed in the rollout?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe the largest system you helped deprecate or migrate. How did you manage the risk?",
            "dimension": "scope",
            "level": [6],
            "good_signals": [
                "Structured migration plan (strangler pattern, dual-run, rollback criteria)",
                "Stakeholder communication handled explicitly",
                "Quantifies risk reduction and final outcome",
            ],
            "follow_ups": [
                "How did you handle teams that resisted migrating?",
                "What was your rollback plan, and did you ever use it?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you decide what technical work is worth doing when the roadmap is full?",
            "dimension": "scope",
            "level": [6, 7],
            "good_signals": [
                "Has a repeatable prioritization framework, not vibes",
                "Connects technical work to business leverage",
                "Can say no and defend it",
            ],
            "follow_ups": [
                "Give an example of an important technical bet you killed.",
                "How do you handle tech debt vs. feature pressure?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you inherited a struggling project or system. What did you do first?",
            "dimension": "scope",
            "level": [6],
            "good_signals": [
                "Diagnosed before prescribing (metrics, interviews, code archaeology)",
                "Sequenced stabilization before ambition",
                "Built trust with the existing team rather than replacing them",
            ],
            "follow_ups": [
                "What did you find that surprised you?",
                "How did you rebuild confidence in the system?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe your approach to building a multi-year technical vision. How do you keep it grounded?",
            "dimension": "scope",
            "level": [7],
            "good_signals": [
                "Vision tied to staged, falsifiable milestones",
                "Connects to business strategy, not technology for its own sake",
                "Shows how the vision changed with new information",
            ],
            "follow_ups": [
                "How do you prevent a vision doc from becoming shelfware?",
                "How do you incorporate dissenting views into it?",
            ],
            "source": SOURCE_TAG,
        },
    ],
    "influence": [
        {
            "q": "Tell me about a time you changed a decision made by leadership or a peer team. How did you do it?",
            "dimension": "influence",
            "level": [6, 7],
            "good_signals": [
                "Shows data or a prototype rather than opinion",
                "Picked the right forum and timing for the challenge",
                "Maintained the relationship regardless of outcome",
            ],
            "follow_ups": [
                "What would you do differently in how you framed it?",
                "When is it right NOT to push back?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a time you aligned stakeholders with conflicting goals behind one technical plan.",
            "dimension": "influence",
            "level": [6],
            "good_signals": [
                "Surfaces each party's real incentives",
                "Found the shared interest or made the tradeoff explicit",
                "Documented the decision and its rationale",
            ],
            "follow_ups": [
                "What did you concede, and what did you hold firm on?",
                "How did you handle someone who agreed in the room but blocked later?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you influence engineers who do not report to you?",
            "dimension": "influence",
            "level": [6, 7],
            "good_signals": [
                "Concrete mechanisms: RFCs, office hours, pairing, design reviews",
                "Reputation-based: they cite prior helpful interactions",
                "Respects team autonomy while raising the bar",
            ],
            "follow_ups": [
                "Give an example where your influence changed a team's design.",
                "What do you do when a team ignores your advice?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a technical proposal or RFC you wrote that had wide impact.",
            "dimension": "influence",
            "level": [6],
            "good_signals": [
                "Proposal was legible to non-experts and rigorous for experts",
                "Drove to a decision, not just discussion",
                "Followed through on implementation consequences",
            ],
            "follow_ups": [
                "How did you handle the strongest objection to it?",
                "What would you change about how you wrote it?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a disagreement with product management about priorities. How did you resolve it?",
            "dimension": "influence",
            "level": [6],
            "good_signals": [
                "Translated technical concerns into product/business language",
                "Proposed alternatives instead of just blocking",
                "Kept the partnership healthy afterward",
            ],
            "follow_ups": [
                "When do you defer to product, and when do you escalate?",
                "How do you avoid becoming the 'team of no'?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you built a coalition to get a risky or unpopular technical bet funded.",
            "dimension": "influence",
            "level": [7],
            "good_signals": [
                "Identified and won over key sponsors early",
                "De-risked the bet with prototypes or staged funding",
                "Owned the outcome, including failure modes",
            ],
            "follow_ups": [
                "How did you handle the bet failing?",
                "What did the coalition cost you politically?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you communicate a complex technical problem to executives?",
            "dimension": "influence",
            "level": [6, 7],
            "good_signals": [
                "Leads with the decision needed and the recommendation",
                "Adapts depth to audience without dumbing down",
                "Honest about uncertainty and unknowns",
            ],
            "follow_ups": [
                "Give an example of a one-page memo that worked.",
                "How do you deliver bad news upward?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you gave hard technical feedback to a peer or senior leader. What happened?",
            "dimension": "influence",
            "level": [6],
            "good_signals": [
                "Direct but respectful; focused on the work, not the person",
                "Picked a private, timely setting",
                "Shows the feedback changed something",
            ],
            "follow_ups": [
                "How did they react initially?",
                "What did you learn about giving feedback at your level?",
            ],
            "source": SOURCE_TAG,
        },
    ],
    "ambiguity": [
        {
            "q": "Tell me about a time you were handed a vague problem with no clear owner. How did you proceed?",
            "dimension": "ambiguity",
            "level": [6, 7],
            "good_signals": [
                "Defined the problem before solving it",
                "Created clarity for others, not just themselves",
                "Set decision points and checkpoints",
            ],
            "follow_ups": [
                "How did you know when you had defined it well enough?",
                "What did you do when the definition turned out wrong?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a project where the requirements changed mid-flight. How did you adapt?",
            "dimension": "ambiguity",
            "level": [6],
            "good_signals": [
                "Separated sunk work from reusable work",
                "Re-planned transparently with stakeholders",
                "Protected team morale during the pivot",
            ],
            "follow_ups": [
                "How did you decide what to keep vs. throw away?",
                "What process change came out of it?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a zero-to-one project: something that did not exist before you started it.",
            "dimension": "ambiguity",
            "level": [6, 7],
            "good_signals": [
                "Started with the smallest falsifiable bet",
                "Validated with users or data before scaling investment",
                "Shows the path from ambiguity to a shipped product",
            ],
            "follow_ups": [
                "What was your first prototype, and what did it teach you?",
                "When did you decide to double down vs. kill it?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you make decisions with incomplete information?",
            "dimension": "ambiguity",
            "level": [6],
            "good_signals": [
                "Explicit about what is known vs. assumed",
                "Uses reversible vs. irreversible framing",
                "Sets a timebox and a review point",
            ],
            "follow_ups": [
                "Give an example of a decision you reversed. What triggered it?",
                "How do you avoid analysis paralysis in your team?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time two teams both thought they owned the same problem. What did you do?",
            "dimension": "ambiguity",
            "level": [6],
            "good_signals": [
                "Surfaced the overlap explicitly rather than letting it fester",
                "Proposed a clean ownership boundary both sides could accept",
                "Followed through until the boundary held",
            ],
            "follow_ups": [
                "How did you handle the team that lost the turf?",
                "Did the boundary survive contact with reality?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a situation where the success metric was unclear. How did you define done?",
            "dimension": "ambiguity",
            "level": [6, 7],
            "good_signals": [
                "Proposed concrete metrics and got agreement before building",
                "Distinguished leading indicators from lagging ones",
                "Revisited the definition as they learned",
            ],
            "follow_ups": [
                "What metric did you wish you had defined earlier?",
                "How do you handle stakeholders who move the goalposts?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you explored a research-style or speculative idea that did not pan out.",
            "dimension": "ambiguity",
            "level": [7],
            "good_signals": [
                "Timeboxed the exploration with a clear kill criterion",
                "Extracted reusable learnings from the failure",
                "Communicated the outcome honestly to sponsors",
            ],
            "follow_ups": [
                "How did you decide when to stop?",
                "What did the failure teach the org?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you prioritize when everything is ambiguous and everything claims to be urgent?",
            "dimension": "ambiguity",
            "level": [6, 7],
            "good_signals": [
                "Has a stated method for triaging under uncertainty",
                "Escalates the ambiguity itself rather than guessing silently",
                "Protects focus time against urgency theater",
            ],
            "follow_ups": [
                "Give an example of saying no to something urgent.",
                "How do you keep a team calm in that environment?",
            ],
            "source": SOURCE_TAG,
        },
    ],
    "org-design": [
        {
            "q": "Tell me about a time you helped shape how teams were organized (a reorg, a new team, a platform split).",
            "dimension": "org-design",
            "level": [6, 7],
            "good_signals": [
                "Explains the problem the old structure caused (Conway's-law thinking)",
                "Involved affected people in the redesign",
                "Measured whether the new structure worked",
            ],
            "follow_ups": [
                "What went wrong with the old structure concretely?",
                "What would you change about the redesign?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you think about the platform vs. product team split? Give an example where you got it right or wrong.",
            "dimension": "org-design",
            "level": [7],
            "good_signals": [
                "Discusses platform as a product with internal customers",
                "Names the failure modes (ivory tower, misaligned incentives)",
                "Concrete example, not just theory",
            ],
            "follow_ups": [
                "How do you keep platform teams close to real users?",
                "When should a platform team say no to a feature request?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you designed a hiring bar or interview process for senior engineers.",
            "dimension": "org-design",
            "level": [6],
            "good_signals": [
                "Defines what 'bar' means in observable terms",
                "Addresses bias and calibration explicitly",
                "Shows the process improved hiring outcomes",
            ],
            "follow_ups": [
                "How do you calibrate interviewers?",
                "What do you do when the panel disagrees?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you balance process (reviews, RFCs, on-call) against team autonomy and speed?",
            "dimension": "org-design",
            "level": [6],
            "good_signals": [
                "Process justified by the failure it prevents, not habit",
                "Differentiates by risk level",
                "Willing to remove process that is not earning its keep",
            ],
            "follow_ups": [
                "Give an example of process you removed.",
                "How do you handle a team that wants to skip reviews?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe how you would set up the engineering culture and practices for a brand-new team.",
            "dimension": "org-design",
            "level": [6, 7],
            "good_signals": [
                "Prioritizes a few high-leverage practices (reviews, on-call, planning)",
                "Culture as behaviors and defaults, not posters",
                "Plans for how the culture survives growth",
            ],
            "follow_ups": [
                "What is the first practice you would install, and why?",
                "How do you handle the first culture violation?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you influenced an organization's technical career ladder or leveling criteria.",
            "dimension": "org-design",
            "level": [7],
            "good_signals": [
                "Identifies a real gap the ladder change fixed",
                "Worked with HR/leadership, not around them",
                "Shows how the change affected real promotion decisions",
            ],
            "follow_ups": [
                "How do you write criteria that are not gameable?",
                "How do you handle someone who meets the letter but not the spirit?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you handle technical debt at the organizational level?",
            "dimension": "org-design",
            "level": [6, 7],
            "good_signals": [
                "Frames debt as a portfolio with interest rates",
                "Has a mechanism for paying it down (allocation, debt sprints, quality bars)",
                "Connects debt to business risk, not aesthetics",
            ],
            "follow_ups": [
                "Give an example of debt you chose to carry deliberately.",
                "How do you prevent debt from becoming invisible?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you had to reduce scope, headcount, or investment in your area. How did you decide what to cut?",
            "dimension": "org-design",
            "level": [7],
            "good_signals": [
                "Clear, defensible criteria for what stayed and what went",
                "Honest, early communication with affected people",
                "Protected the highest-leverage work",
            ],
            "follow_ups": [
                "What did you get wrong in the cuts?",
                "How did you keep the remaining team motivated?",
            ],
            "source": SOURCE_TAG,
        },
    ],
    "mentorship": [
        {
            "q": "Tell me about an engineer you mentored who grew significantly. What did you actually do?",
            "dimension": "mentorship",
            "level": [6, 7],
            "good_signals": [
                "Specific actions (stretch assignments, feedback, sponsorship), not vibes",
                "Shows the mentee's agency, not taking all the credit",
                "Names the outcome in concrete terms",
            ],
            "follow_ups": [
                "What did the mentee struggle with most?",
                "How did your approach change as they grew?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Describe a time you coached a struggling senior engineer. How did you handle it?",
            "dimension": "mentorship",
            "level": [6],
            "good_signals": [
                "Diagnosed root cause (skill, motivation, environment) before acting",
                "Set clear expectations with a timeline",
                "Honest about when coaching was not enough",
            ],
            "follow_ups": [
                "How did the first conversation go?",
                "What would you do differently?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you give feedback to engineers more senior than you?",
            "dimension": "mentorship",
            "level": [6, 7],
            "good_signals": [
                "Leads with curiosity and specific observations",
                "Chooses the right setting and timing",
                "Shows it landed and changed something",
            ],
            "follow_ups": [
                "Give an example where it went badly. What did you learn?",
                "How do you handle defensiveness?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you deliberately delegated something hard instead of doing it yourself.",
            "dimension": "mentorship",
            "level": [6],
            "good_signals": [
                "Explains the growth rationale, not just workload",
                "Provided safety nets without hovering",
                "Accepted a slower or imperfect result for the learning",
            ],
            "follow_ups": [
                "What safety nets did you put in place?",
                "How did you resist the urge to take it back?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you build a culture of strong code and design reviews?",
            "dimension": "mentorship",
            "level": [6],
            "good_signals": [
                "Models the behavior (thorough, kind, fast reviews)",
                "Teaches reviewers what good looks like",
                "Treats review as mentorship, not gatekeeping",
            ],
            "follow_ups": [
                "How do you handle nitpicky or hostile reviewers?",
                "How do you keep review latency low without lowering the bar?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time you sponsored someone: put your own credibility behind their promotion or opportunity.",
            "dimension": "mentorship",
            "level": [7],
            "good_signals": [
                "Distinguishes sponsorship from mentorship (public advocacy, not just advice)",
                "Names the risk they took on the person",
                "Shows the outcome",
            ],
            "follow_ups": [
                "What evidence did you present to the decision-makers?",
                "What happened if the person stumbled?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "How do you mentor engineers across teams or organizations, not just your own?",
            "dimension": "mentorship",
            "level": [6, 7],
            "good_signals": [
                "Scalable mechanisms (office hours, guilds, written guides)",
                "Respects the mentee's manager rather than routing around them",
                "Shows org-wide leverage",
            ],
            "follow_ups": [
                "How do you avoid becoming a bottleneck for advice?",
                "How do you measure whether it is working?",
            ],
            "source": SOURCE_TAG,
        },
        {
            "q": "Tell me about a time your mentee taught you something or proved you wrong.",
            "dimension": "mentorship",
            "level": [6],
            "good_signals": [
                "Genuine humility; admits the error concretely",
                "Shows two-way learning is part of their mentoring philosophy",
                "Changed a practice as a result",
            ],
            "follow_ups": [
                "What did you change about how you mentor afterward?",
                "How do you create space for mentees to challenge you?",
            ],
            "source": SOURCE_TAG,
        },
    ],
}


# ---------------------------------------------------------------------------
# Behavioral rubrics: 1-4 scale, observable signals per level.
# ---------------------------------------------------------------------------

RUBRICS: dict[str, dict] = {
    "technical-judgment": {
        "dimension": "technical-judgment",
        "description": "Quality of technical decisions: tradeoffs, depth, and long-term thinking.",
        "levels": {
            1: [
                "Decisions described as gut feel or 'the obvious choice'",
                "No mention of alternatives considered or tradeoffs",
                "Optimizes for what is easiest now without considering future cost",
            ],
            2: [
                "Can name alternatives when prompted",
                "Tradeoffs discussed at surface level (faster vs. slower)",
                "Decisions hold up within one team but do not consider wider impact",
            ],
            3: [
                "Proactively lays out options with explicit tradeoff dimensions",
                "Incorporates non-functional concerns (operability, cost, security) into decisions",
                "Decisions hold up across teams; can defend them with data",
            ],
            4: [
                "Judgment trusted org-wide; decisions become reference examples",
                "Anticipates second-order effects and plans for them",
                "Knows when to decide fast vs. when to invest in analysis",
            ],
        },
    },
    "org-influence": {
        "dimension": "org-influence",
        "description": "Ability to move people and decisions without relying on authority.",
        "levels": {
            1: [
                "Influence limited to direct teammates or assigned work",
                "Relies on title or escalation to get things done",
                "Avoids disagreement; goes along with the room",
            ],
            2: [
                "Persuades within own team using reasoning and prototypes",
                "Writes clear proposals but they rarely travel beyond the team",
                "Challenges decisions privately, not in the right forums",
            ],
            3: [
                "Moves cross-team decisions through RFCs, data, and coalition-building",
                "Adapts communication to audience (engineer, PM, exec)",
                "Known as someone whose input changes outcomes",
            ],
            4: [
                "Shapes org-level direction; leadership seeks their read before deciding",
                "Builds durable alignment mechanisms, not one-off wins",
                "Influence persists after they leave the room (docs, norms, mentees)",
            ],
        },
    },
    "mentorship": {
        "dimension": "mentorship",
        "description": "Growing other engineers: coaching, feedback, and sponsorship.",
        "levels": {
            1: [
                "Mentorship is ad hoc or nonexistent",
                "Feedback is vague ('good job') or avoided",
                "Hoards hard problems; does not delegate for growth",
            ],
            2: [
                "Answers questions and helps unblock juniors",
                "Gives feedback when asked, mostly on code",
                "Occasionally delegates stretch work",
            ],
            3: [
                "Proactively coaches with specific, actionable feedback",
                "Delegates deliberately for growth with appropriate safety nets",
                "Mentees show measurable growth tied to their guidance",
            ],
            4: [
                "Builds mentorship systems (guilds, review culture, onboarding) that scale",
                "Sponsors people: spends own credibility on others' advancement",
                "Develops other mentors; leadership pipeline is a visible outcome",
            ],
        },
    },
    "delivery-through-others": {
        "dimension": "delivery-through-others",
        "description": "Getting complex work shipped by coordinating people and teams.",
        "levels": {
            1: [
                "Delivers own work; coordination is someone else's job",
                "Multi-team efforts stall on their watch",
                "No clear method for tracking or unblocking dependencies",
            ],
            2: [
                "Coordinates within own team effectively",
                "Flags cross-team blockers but waits for others to resolve them",
                "Plans exist but break down under change",
            ],
            3: [
                "Drives multi-team delivery with explicit milestones and owners",
                "Proactively resolves or routes around blockers",
                "Re-plans transparently when scope or priorities shift",
            ],
            4: [
                "Delivers org-scale programs with many moving parts",
                "Builds delivery muscle in the org (planning norms, decision cadence)",
                "Reliably lands ambiguous, high-stakes work through other people",
            ],
        },
    },
    "ambiguity-handling": {
        "dimension": "ambiguity-handling",
        "description": "Creating clarity and momentum when the problem, owner, or success metric is unclear.",
        "levels": {
            1: [
                "Waits for requirements to be fully specified before starting",
                "Paralyzed or thrashy when priorities shift",
                "Escalates ambiguity upward without proposing a framing",
            ],
            2: [
                "Makes progress on well-framed ambiguous tasks",
                "Asks good clarifying questions but does not drive the framing",
                "Adapts to change reactively",
            ],
            3: [
                "Defines the problem and success criteria before building",
                "Timeboxes exploration with explicit kill criteria",
                "Creates clarity for the team, not just themselves",
            ],
            4: [
                "Turns org-level ambiguity into funded, staffed programs",
                "Sets decision frameworks others reuse",
                "Comfortable killing their own work when the evidence changes",
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_dimensions() -> list[str]:
    """Question-bank dimensions."""
    return list(DIMENSIONS)


def get_questions(
    dimension: str | None = None,
    level: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return question entries, optionally filtered by dimension and level.

    level: 6 or 7 (generic staff/principal labels; see LEVELS_DISCLAIMER).
    """
    if dimension is not None and dimension not in QUESTIONS:
        raise StaffError(
            f"Unknown dimension {dimension!r}. Choose from: {', '.join(DIMENSIONS)}"
        )
    if level is not None and level not in (6, 7):
        raise StaffError(f"level must be 6 or 7, got {level!r}")
    if limit is not None and limit < 0:
        raise StaffError(f"limit must be >= 0, got {limit!r}")

    dims = [dimension] if dimension else DIMENSIONS
    out: list[dict] = []
    for d in dims:
        for entry in QUESTIONS[d]:
            if level is not None and level not in entry["level"]:
                continue
            out.append(entry)
    if limit is not None:
        out = out[:limit]
    return out


def get_rubric(dimension: str) -> dict:
    """Return the 1-4 behavioral rubric for a rubric dimension."""
    if dimension not in RUBRICS:
        raise StaffError(
            f"Unknown rubric dimension {dimension!r}. "
            f"Choose from: {', '.join(RUBRIC_DIMENSIONS)}"
        )
    return RUBRICS[dimension]


def format_question(q: dict) -> str:
    """Render one question entry as readable text."""
    levels = "/".join(str(lv) for lv in q["level"])
    lines = [
        f"[{q['dimension']} | level {levels}] {q['q']}",
        f"  Source: {q['source']}",
        "  Good signals:",
    ]
    lines.extend(f"    - {s}" for s in q["good_signals"])
    lines.append("  Follow-ups:")
    lines.extend(f"    - {s}" for s in q["follow_ups"])
    return "\n".join(lines)


def format_rubric(r: dict) -> str:
    """Render one rubric as readable text."""
    lines = [f"Rubric: {r['dimension']}", f"  {r['description']}", ""]
    for lv in sorted(r["levels"]):
        lines.append(f"  Level {lv}:")
        lines.extend(f"    - {s}" for s in r["levels"][lv])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level CLI: main(argv) -> int
# ---------------------------------------------------------------------------

def _cmd_questions(args: argparse.Namespace) -> int:
    qs = get_questions(
        dimension=args.dimension, level=args.level, limit=args.limit
    )
    if args.json:
        print(json.dumps(qs, indent=2))
    else:
        print(f"# Staff interview questions ({len(qs)} shown)")
        print(f"# {LEVELS_DISCLAIMER}\n")
        for q in qs:
            print(format_question(q))
            print()
    return 0


def _cmd_rubric(args: argparse.Namespace) -> int:
    if args.list:
        print("Rubric dimensions:")
        for d in RUBRIC_DIMENSIONS:
            print(f"  - {d}")
        return 0
    if not args.dimension:
        raise StaffError("pass --dimension D or use 'rubric list'")
    r = get_rubric(args.dimension)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(format_rubric(r))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="staff", description="Staff/principal interview prep: question bank and behavioral rubrics.")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("questions", help="List practice questions",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff questions --dimension influence\n  python -m candid staff questions --level 7 --json")
    q.add_argument("--dimension", choices=DIMENSIONS, default=None,
                   help="Filter by question dimension")
    q.add_argument("--level", type=int, choices=[6, 7], default=None,
                   help="Filter by level (generic staff/principal labels; levels vary by company)")
    q.add_argument("--limit", type=int, default=None, help="Max questions to show")
    q.add_argument("--json", action="store_true", help="Emit JSON")
    q.set_defaults(func=_cmd_questions)

    r = sub.add_parser("rubric", help="Show behavioral rubrics",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff rubric list\n  python -m candid staff rubric --dimension mentorship")
    r.add_argument("list", nargs="?", default=None,
                   help="Use 'rubric list' to show rubric dimensions")
    r.add_argument("--dimension", choices=RUBRIC_DIMENSIONS, default=None,
                   help="Rubric dimension to show")
    r.add_argument("--json", action="store_true", help="Emit JSON")
    r.set_defaults(func=_cmd_rubric)
    return p


def main(argv: list[str] | None = None) -> int:
    """Module CLI entry point. Returns process exit code."""
    args = build_parser().parse_args(argv)
    if args.cmd == "rubric" and args.list not in (None, "list"):
        raise StaffError("usage: staff rubric list | staff rubric --dimension D")
    try:
        return args.func(args)
    except StaffError as e:
        import sys
        sys.stderr.write(f"staff: error: {e}\n")
        return 2
