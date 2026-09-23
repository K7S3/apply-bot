"""Staff/principal-engineer interview prep: cross-org influence scenarios and
mentorship/team-health topics.

All content here is *practice guidance* (frameworks, checklists, signals to
demonstrate), labeled as such, it never invents the user's experience or
metrics. Candidates must fill in their own real stories.

Conventions follow candid.prep_questions: every scenario/topic carries a
``source`` label. Here everything is authored practice material, labeled
"candid practice prompt".

Provenance: content in this module is original practice guidance written by
Keta for the candid project (2026-09-22), not scraped from anywhere. Per
project rules it never claims to be real interviewer speech or reported
questions, and it must never be mixed into the researched question banks in
candid.prep_questions without an explicit source change.
"""

from __future__ import annotations

import argparse
import json
import sys

SOURCE_LABEL = "candid practice prompt"

# ---------------------------------------------------------------------------
# Cross-org influence scenarios
# ---------------------------------------------------------------------------

INFLUENCE_SCENARIOS: list[dict] = [
    {
        "id": "disagree-commit",
        "title": "Disagree and commit with a partner team",
        "situation": (
            "You and a partner team (or a senior leader) disagreed on a major "
            "technical direction, e.g. build vs. buy, architecture choice, or "
            "rollout order. The decision went against your recommendation."
        ),
        "staff_lens": (
            "Are you big enough to lose well? Staff engineers regularly lose "
            "arguments. Interviewers watch for whether you then commit fully "
            "and help the chosen path succeed, or whether you keep relitigating, "
            "withdraw, or quietly sabotage by deprioritizing it."
        ),
        "strong_moves": [
            "State your disagreement on the record, with the reasoning and the "
            "tradeoffs as you saw them, so the decision log is honest.",
            "Once decided, commit publicly and shift your energy to making the "
            "chosen path work, the best version of disagree-and-commit.",
            "Set up a lightweight review: agree on what evidence would reopen "
            "the question, so a change of mind later is data-driven, not "
            "political.",
            "Brief your own team once, clearly, on why the decision stands, so "
            "rumor and resentment do not fill the gap.",
        ],
        "pitfalls": [
            "Saying you 'committed' but describing how you starved the effort of "
            "attention or advocated against it behind the scenes.",
            "Framing the other side as incompetent rather than optimizing for "
            "different constraints.",
            "Reopening the debate at every setback without new evidence.",
        ],
    },
    {
        "id": "decision-no-authority",
        "title": "Driving a decision with no formal authority",
        "situation": (
            "A cross-team decision was stuck, no single owner, everyone waiting "
            "on everyone else. You were not anyone's boss and could not force an "
            "outcome."
        ),
        "staff_lens": (
            "This is the signature staff motion: creating forward progress from "
            "ambiguity without authority. Interviewers look for how you build "
            "alignment, evidence, pre-wires, options with recommendations, not "
            "how loudly you argued."
        ),
        "strong_moves": [
            "Frame the decision crisply: what is decided, who is affected, what "
            "the options and their tradeoffs are, and your recommendation.",
            "Pre-wire with the most affected stakeholders 1:1 before the group "
            "forum, so the meeting confirms rather than debates.",
            "Name a deadline and a default: 'if we cannot reach consensus by "
            "Friday, I will recommend X to leadership.'",
            "Write the decision down and circulate it, so alignment survives the "
            "meeting.",
        ],
        "pitfalls": [
            "Describing persuasion as charisma or 'getting buy-in' without naming "
            "concrete mechanisms (writing, pre-wires, deadlines).",
            "Going around dissenters instead of engaging them; the dissent shows "
            "up later as resistance.",
            "Claiming the decision for yourself rather than the group, "
            "interviewers notice who takes credit.",
        ],
    },
    {
        "id": "kill-own-project",
        "title": "Killing your own project",
        "situation": (
            "You were deep into a project, maybe you proposed it and led it, "
            "when evidence showed it should not continue: better alternative, "
            "shifting priorities, or diminishing returns."
        ),
        "staff_lens": (
            "Can you separate your ego from the work? Senior leaders need to "
            "know you will stop spending the org's money when the bet is dead. "
            "This is also where they check you handle the human side: the "
            "people who built it need a landing."
        ),
        "strong_moves": [
            "Name the evidence that changed your mind explicitly, numbers, "
            "constraints, or strategy shifts, not vague 'priorities changed'.",
            "Bring the kill recommendation yourself before someone else has to; "
            "owning the stop is the leadership move.",
            "Salvage deliberately: document learnings, reuse components, and "
            "make sure the people on it land on good next work.",
            "Communicate the stop as clearly as you communicated the start; "
            "silence reads as embarrassment.",
        ],
        "pitfalls": [
            "Dragging the project on for months past the point of doubt, hoping "
            "it recovers.",
            "Blaming leadership or 'politics' for the kill instead of describing "
            "the real signals.",
            "Forgetting the team in the story, interviewers notice when the "
            "people who did the work vanish from your narrative.",
        ],
    },
    {
        "id": "conflict-resolution",
        "title": "Resolving a conflict between two teams",
        "situation": (
            "Two teams under different managers were in conflict, over API "
            "ownership, roadmap order, headcount, or who owns an outage. You had "
            "no authority over either team."
        ),
        "staff_lens": (
            "Staff engineers are the org's conflict resolution layer. The "
            "question is whether you mediate structurally (align incentives, "
            "clarify ownership, design the interface) rather than just smoothing "
            "over the argument."
        ),
        "strong_moves": [
            "Diagnose the incentive mismatch first: the conflict is usually a "
            "symptom of teams being measured against incompatible goals.",
            "Get both sides' real constraints on the table in a shared forum, "
            "often each side is optimizing against imagined, not actual, "
            "constraints of the other.",
            "Propose a structural fix (ownership boundary, SLA, joint "
            "milestone) rather than a one-time compromise.",
            "Follow up after the fix to check it held; resolution that decays "
            "in two weeks was not a resolution.",
        ],
        "pitfalls": [
            "Picking a side and lobbying against the other team.",
            "Presenting a truce as a resolution, no structural change means the "
            "fight recurs.",
            "Making it about personalities rather than incentives and "
            "ownership.",
        ],
    },
    {
        "id": "deprecate-beloved-system",
        "title": "Deprecating a system people love",
        "situation": (
            "You led the deprecation or migration away from a system with loyal "
            "internal users, something people had built careers around or "
            "loved using. The change was right and unpopular."
        ),
        "staff_lens": (
            "Can you drive change through a population that resists it? "
            "Interviewers look for empathy plus relentlessness: acknowledging "
            "the loss honestly while not wavering on the direction, and for a "
            "migration plan that respects users' time."
        ),
        "strong_moves": [
            "Communicate the 'why' early and repeatedly: costs, risks, or "
            "capabilities, not just 'leadership decided'.",
            "Provide a real migration path with support: docs, office hours, "
            "tooling, and a long enough runway.",
            "Listen to objections seriously; sometimes the loudest resistor is "
            "surfacing a genuine gap in the replacement.",
            "Hold the line once the decision is final, waffling destroys trust "
            "faster than the deprecation itself.",
        ],
        "pitfalls": [
            "Dismissing users as 'resistant to change' instead of hearing their "
            "legitimate costs.",
            "Announcing a hard cutoff with no migration support, then blaming "
            "teams that miss it.",
            "Softening the message so much that people keep investing in the "
            "dying system.",
        ],
    },
    {
        "id": "standards-adoption",
        "title": "Getting org-wide adoption of a standard or platform",
        "situation": (
            "You championed a standard, a platform, a set of practices, a "
            "security or reliability bar, and needed teams that did not report "
            "to you to adopt it."
        ),
        "staff_lens": (
            "Mandates do not work at staff level; adoption does. Interviewers "
            "evaluate whether you made the right thing the easy thing (tooling, "
            "defaults, paved roads) instead of relying on policy or nagging."
        ),
        "strong_moves": [
            "Make adoption cheaper than resistance: golden paths, templates, "
            "automation, so the default choice is the standard.",
            "Find early adopters and make them successful publicly; social proof "
            "beats memos.",
            "Measure adoption and publish the metric; visibility creates "
            "accountability without authority.",
            "Keep a feedback loop open and iterate the standard; adoption "
            "stalls when the standard ignores real team needs.",
        ],
        "pitfalls": [
            "Pushing a mandate from above and calling it influence.",
            "Building the 'perfect' standard in isolation, then being surprised "
            "nobody adopts it.",
            "Treating non-adopters as problems rather than as data about what "
            "the standard lacks.",
        ],
    },
    {
        "id": "tech-debt-escalation",
        "title": "Escalating tech debt to business leadership",
        "situation": (
            "You needed leadership to invest in paying down technical debt or "
            "reliability work that had no direct feature payoff, and business "
            "leaders were focused on the roadmap."
        ),
        "staff_lens": (
            "Can you translate engineering pain into business language? Staff "
            "engineers secure investment by connecting debt to velocity, risk, "
            "and cost, not by complaining that the code is ugly."
        ),
        "strong_moves": [
            "Quantify: incident cost, on-call burden, lead-time slowdown, or "
            "customer impact, attach numbers to the pain.",
            "Frame the ask as an investment with a return, not a tax: 'two "
            "sprints now saves X per quarter.'",
            "Bring a concrete, bounded proposal (scope, timeline, success "
            "criteria) rather than an open-ended complaint.",
            "Tie the work to a business moment leaders care about: a launch, a "
            "compliance deadline, a reliability target.",
        ],
        "pitfalls": [
            "Framing the request as engineering aesthetics ('the code is a "
            "mess') instead of business impact.",
            "Asking for a blank check ('we need a quarter to rewrite') with no "
            "scope or success criteria.",
            "Escalating without first trying to make the case with data.",
        ],
    },
    {
        "id": "inherited-mess",
        "title": "Inheriting someone else's failing project",
        "situation": (
            "You took over a struggling project, team, or system you did not "
            "create, failing milestones, low morale, unclear direction, and "
            "had to turn it around."
        ),
        "staff_lens": (
            "How do you handle other people's failures without blame? "
            "Interviewers watch for a fair diagnosis, respect for the people "
            "involved, and a turnaround plan that is structural, not heroic."
        ),
        "strong_moves": [
            "Diagnose before prescribing: talk to the team, read the history, "
            "separate people problems from structural ones.",
            "Describe what happened structurally and blamelessly: the setup, "
            "the constraints, the decisions, without criticizing predecessors "
            "by name.",
            "Reset expectations honestly with stakeholders, new scope, timeline, "
            "or explicit kill, rather than silently absorbing the deficit.",
            "Invest in the existing team rather than replacing them; trust is "
            "the first thing you rebuild.",
        ],
        "pitfalls": [
            "Badmouthing the previous owner to look good by comparison.",
            "Trying to hero-fix everything yourself instead of rebuilding the "
            "team's capability.",
            "Pretending the plan is fine while the project keeps failing.",
        ],
    },
    {
        "id": "vendor-open-source",
        "title": "Choosing between a vendor and building in-house",
        "situation": (
            "You had to recommend build vs. buy (or vendor vs. open source) for "
            "a significant capability, with real money and long-term lock-in at "
            "stake."
        ),
        "staff_lens": (
            "Staff engineers are trusted with economic judgment. Interviewers "
            "want a total-cost-of-ownership analysis, licensing, integration, "
            "maintenance, lock-in, and the opportunity cost of your own "
            "engineers, not a technology beauty contest."
        ),
        "strong_moves": [
            "Compare total cost over 3+ years: license, integration, ongoing "
            "maintenance, and exit cost.",
            "Name what is core vs. commodity: build where it differentiates, "
            "buy where it does not.",
            "Prototype the riskiest assumption before committing, a week of "
            "spike beats a quarter of regret.",
            "Document the decision and its review date; build/buy answers "
            "expire as vendors and needs change.",
        ],
        "pitfalls": [
            "Deciding on technology preference alone, ignoring cost and "
            "lock-in.",
            "Underestimating maintenance: 'we can build it in a month' without "
            "pricing the years of ownership.",
            "Letting the loudest engineer or a vendor's sales team drive the "
            "decision.",
        ],
    },
    {
        "id": "org-design",
        "title": "Shaping an org or team structure change",
        "situation": (
            "You influenced how teams were organized, a reorg, a new team "
            "spin-up, a change in ownership boundaries, as an individual "
            "contributor, not as a manager with that authority."
        ),
        "staff_lens": (
            "The highest-leverage staff work is organizational. Interviewers "
            "check that you thought in terms of ownership, communication paths, "
            "and incentives, and that you navigated the politics without "
            "playing them."
        ),
        "strong_moves": [
            "Start from the problem the structure causes: handoffs, unclear "
            "ownership, misaligned incentives, not the structure itself.",
            "Propose options with tradeoffs and let decision-makers choose; "
            "your job is clarity, not a power grab.",
            "Think about the people: who gains, who loses, and how the change "
            "affects careers and morale.",
            "Stay engaged after the change to help it settle; org charts "
            "without follow-through just move the dysfunction.",
        ],
        "pitfalls": [
            "Designing the org around yourself or your allies.",
            "Treating the reorg as the fix rather than a means to fix "
            "ownership and incentive problems.",
            "Dropping the change on people without preparing them.",
        ],
    },
]


# ---------------------------------------------------------------------------
# Mentorship and team-health topics
# ---------------------------------------------------------------------------

MENTOR_TOPICS: dict[str, dict] = {
    "growing-engineers": {
        "title": "Growing engineers",
        "guiding_principles": [
            "Growth is owned by the engineer; your job is to create the "
            "conditions: scope, feedback, and honest signal about the gap.",
            "Stretch assignments beat advice: people grow by doing work "
            "slightly beyond their current level, with a safety net.",
            "Give feedback that is specific, timely, and tied to impact, "
            "vague praise ('great job') teaches nothing.",
            "Calibrate to the person: different engineers need different "
            "things (sponsorship, hard feedback, new domain, visibility).",
        ],
        "practice_questions": [
            {
                "q": "How do you help a strong senior engineer grow toward staff?",
                "good_signals": [
                    "Describe raising their scope deliberately: from owning a "
                    "component to owning outcomes across teams.",
                    "Mention exposing them to ambiguity and cross-org work, not "
                    "just harder technical problems.",
                    "Talk about giving them honest signal on the actual gaps, "
                    "visibility, influence, writing, rather than cheerleading.",
                ],
            },
            {
                "q": "Tell me about someone you mentored. What changed for them?",
                "good_signals": [
                    "Name a specific person-level outcome (a promotion, a new "
                    "capability, an expanded scope), not just 'we had good "
                    "1:1s'.",
                    "Show the mechanism: what you actually did (found them a "
                    "stretch project, gave hard feedback, sponsored them in "
                    "calibration).",
                    "Acknowledge what they did vs. what you did, do not take "
                    "credit for their growth.",
                ],
            },
            {
                "q": "How do you mentor someone whose skills differ from yours?",
                "good_signals": [
                    "Admit the limit of your expertise and describe how you "
                    "still add value: questions, sponsorship, finding them a "
                    "better technical mentor.",
                    "Avoid pretending to coach what you cannot evaluate; "
                    "connect them with someone who can.",
                ],
            },
            {
                "q": "How do you give an engineer a stretch assignment without setting them up to fail?",
                "good_signals": [
                    "Describe the safety net: clear scope, checkpoints, an "
                    "explicit 'ask for help' norm.",
                    "Explain how you calibrate the stretch: just beyond current "
                    "level, reversible failure modes.",
                    "Mention staying close early and loosening as they prove "
                    "out.",
                ],
            },
        ],
        "red_flags": [
            "Taking credit for a mentee's promotion as if you caused it.",
            "Describing mentorship as advice-giving rather than creating "
            "opportunities and feedback loops.",
            "Only mentoring people who remind you of yourself.",
            "Never having given hard, career-relevant feedback, if every "
            "mentorship story is positive, you are not mentoring, you are "
            "cheerleading.",
        ],
    },
    "hiring-bar": {
        "title": "Holding the hiring bar",
        "guiding_principles": [
            "The bar is the team you will have in two years; every hire is a "
            "vote on it. A weak hire costs far more than an empty seat.",
            "Evaluate against the role's actual needs, not against yourself or "
            "an idealized candidate.",
            "Structured, consistent evaluation beats gut feel: same questions, "
            "same rubric, written feedback before discussion.",
            "Diversity of the pipeline is part of the bar, a narrow funnel is "
            "a process failure, not a talent shortage.",
        ],
        "practice_questions": [
            {
                "q": "How do you evaluate candidates for senior/staff roles differently from junior roles?",
                "good_signals": [
                    "Shift the criteria explicitly: from execution skill to "
                    "scope, judgment, influence, and ambiguity tolerance.",
                    "Describe probing for real scope: 'what did YOU decide vs. "
                    "what was decided for you?'",
                    "Mention looking for evidence of raising the people around "
                    "them, not just personal output.",
                ],
            },
            {
                "q": "Tell me about a time you argued against hiring someone the team liked.",
                "good_signals": [
                    "Name the specific bar concern and the evidence for it, "
                    "not a vibe.",
                    "Show you raised it clearly in the debrief even though it "
                    "was unpopular; that is what the bar is for.",
                    "Describe the outcome honestly, including if you were "
                    "overruled, and what you did after.",
                ],
            },
            {
                "q": "How do you reduce bias in your hiring process?",
                "good_signals": [
                    "Name concrete mechanisms: structured rubrics, written "
                    "feedback before discussion, consistent questions.",
                    "Acknowledge bias is a process problem, not an individual "
                    "virtue, good intentions are not a mechanism.",
                    "Mention pipeline work: where you source, who screens, how "
                    "job posts are written.",
                ],
            },
            {
                "q": "What does 'raising the bar' mean in practice on an interview loop?",
                "good_signals": [
                    "Describe asking questions that reveal the candidate's "
                    "ceiling, not just their floor.",
                    "Explain that raising the bar sometimes means a strong no "
                    "on a good candidate who is not right for the role.",
                    "Connect it to team composition: what the team lacks, not "
                    "just individual brilliance.",
                ],
            },
        ],
        "red_flags": [
            "Lowering the bar to fill a seat faster, or describing headcount "
            "pressure as a reason to hire someone you had doubts about.",
            "Evaluating candidates by 'culture fit' as a vague likability "
            "test rather than concrete values and working norms.",
            "Never having said no to a hire, or only saying no to weak "
            "candidates, never to popular ones.",
            "Confusing pedigree (school, past employer) with evidence of "
            "capability.",
        ],
    },
    "underperformance": {
        "title": "Handling underperformance",
        "guiding_principles": [
            "Address it early and directly: small gaps become big ones when "
            "feedback is delayed. Silence is read as approval.",
            "Diagnose before judging: is it a skills gap, a motivation gap, a "
            "role mismatch, or a personal crisis? Different causes need "
            "different responses.",
            "Be specific and documented: what is expected, what is happening, "
            "what improvement looks like, by when.",
            "Protect the team too: prolonged underperformance is unfair to the "
            "people carrying the load.",
        ],
        "practice_questions": [
            {
                "q": "Tell me about a time you dealt with an underperforming teammate or report.",
                "good_signals": [
                    "Show you acted early with direct, specific feedback, not "
                    "after months of frustration.",
                    "Describe diagnosing the cause before prescribing (skills, "
                    "motivation, fit, personal circumstances).",
                    "Mention a clear improvement plan with expectations and a "
                    "timeline, and following through either way.",
                ],
            },
            {
                "q": "How do you give feedback to someone who is defensive or senior to you?",
                "good_signals": [
                    "Lead with specific observations and impact, not labels "
                    "('the rollout slipped two weeks' not 'you are unreliable').",
                    "Describe creating safety: private setting, asking for "
                    "their view first, focusing on the work.",
                    "Show persistence: one hard conversation that goes badly is "
                    "not the end of the feedback.",
                ],
            },
            {
                "q": "When is it time to manage someone out?",
                "good_signals": [
                    "Frame it as a kindness after a fair process: clear "
                    "expectations, real support, documented chances.",
                    "Acknowledge the human cost honestly rather than hiding "
                    "behind process language.",
                    "Mention what it taught you about hiring or onboarding, "
                    "treating it as a system signal, not just an individual "
                    "failure.",
                ],
            },
            {
                "q": "How do you distinguish a performance problem from a management problem?",
                "good_signals": [
                    "Ask whether expectations were ever clear and whether the "
                    "person had the tools and support to meet them.",
                    "Describe checking your own contribution first: unclear "
                    "priorities, missing context, wrong role fit.",
                    "Show you fix the system when the pattern repeats across "
                    "people.",
                ],
            },
        ],
        "red_flags": [
            "Avoiding the conversation for months and hoping the problem fixes "
            "itself.",
            "Surprising someone with a formal performance process they never "
            "saw coming, that is a management failure, not a process.",
            "Describing managing someone out with satisfaction rather than "
            "gravity.",
            "Blaming the person without examining whether expectations, "
            "support, or role fit were the real problem.",
        ],
    },
    "feedback": {
        "title": "Giving and receiving feedback",
        "guiding_principles": [
            "Feedback is a gift only if it is usable: specific, timely, and "
            "about behavior and impact, not character.",
            "The ratio matters less than the honesty: people need hard truths "
            "delivered kindly more than they need praise sandwiches.",
            "Receiving feedback well is the harder skill: listen fully, ask "
            "clarifying questions, and follow up on what you changed.",
            "Normalize it culturally: regular lightweight feedback beats rare "
            "heavyweight reviews.",
        ],
        "practice_questions": [
            {
                "q": "Tell me about the hardest feedback you have received. What did you do with it?",
                "good_signals": [
                    "Name real, uncomfortable feedback, not a humblebrag "
                    "('I work too hard').",
                    "Describe your initial reaction honestly, then what you "
                    "actually changed.",
                    "Show follow-through: you checked back with the person, or "
                    "the change is visible in how you work now.",
                ],
            },
            {
                "q": "How do you give critical feedback to a peer or a manager?",
                "good_signals": [
                    "Describe going direct and private, with specific examples "
                    "and the impact they had.",
                    "Show you separate the person from the behavior and offer "
                    "a path forward, not just criticism.",
                    "For upward feedback: frame it in terms of their goals and "
                    "ask permission when the power dynamic makes it risky.",
                ],
            },
            {
                "q": "How do you build a feedback culture on a team?",
                "good_signals": [
                    "Model it first: ask for feedback publicly and act on it "
                    "visibly.",
                    "Create low-stakes rituals (retros, peer feedback rounds) "
                    "so feedback is routine, not dramatic.",
                    "Reward people who give hard feedback well, what gets "
                    "recognized gets repeated.",
                ],
            },
            {
                "q": "Tell me about feedback you gave that did not land. What did you learn?",
                "good_signals": [
                    "Own your part: timing, framing, or relationship, not "
                    "just 'they were defensive'.",
                    "Describe what you changed in your approach afterward.",
                    "Show you tried again rather than writing the person off.",
                ],
            },
        ],
        "red_flags": [
            "Claiming you rarely receive critical feedback, it means people "
            "do not feel safe giving it to you.",
            "Giving feedback only in formal reviews instead of in the moment.",
            "The praise sandwich or feedback so softened it is unusable.",
            "Getting defensive in the interview itself when probed, "
            "interviewers notice.",
        ],
    },
    "team-health": {
        "title": "Team health",
        "guiding_principles": [
            "Health is observable: delivery predictability, review latency, "
            "on-call burden, attrition signals, and whether people speak up in "
            "meetings.",
            "Psychological safety is the foundation: people must be able to "
            "raise risks and admit mistakes without punishment.",
            "Sustainable pace beats heroic pace: a team that needs heroes has "
            "a process problem.",
            "Health is maintained, not achieved: retros, 1:1s, and load "
            "balancing are ongoing practices, not one-time fixes.",
        ],
        "practice_questions": [
            {
                "q": "How do you know if a team is healthy? What do you measure or observe?",
                "good_signals": [
                    "Name concrete signals: delivery predictability, on-call "
                    "load distribution, review turnaround, meeting "
                    "participation, attrition risk.",
                    "Distinguish lagging indicators (attrition) from leading "
                    "ones (silence in retros, uneven load).",
                    "Mention talking to the humans, not just reading metrics, "
                    "skip-levels, 1:1s, hallway signal.",
                ],
            },
            {
                "q": "Tell me about a time you improved the health of a struggling team.",
                "good_signals": [
                    "Diagnose first: what was actually wrong (unclear "
                    "ownership, overload, conflict, lack of purpose).",
                    "Describe structural changes, not just morale events, "
                    "rebalanced on-call, clarified ownership, fixed the retro "
                    "so it produces action.",
                    "Show the before/after in observable terms.",
                ],
            },
            {
                "q": "How do you handle burnout, yours or a teammate's?",
                "good_signals": [
                    "Treat it as a workload and expectations problem first, "
                    "not a resilience problem.",
                    "Describe concrete actions: rebalancing load, cutting "
                    "scope, enforcing real time off.",
                    "For your own: show you have a sustainable operating model, "
                    "not just endurance.",
                ],
            },
            {
                "q": "How do you create psychological safety on a team?",
                "good_signals": [
                    "Model vulnerability: admit your own mistakes publicly and "
                    "thank people who surface bad news.",
                    "Design for it structurally: blameless postmortems, "
                    "written dissent channels, rotating who speaks first.",
                    "Show you respond to bad news with curiosity, not "
                    "punishment, people watch what happens to the messenger.",
                ],
            },
        ],
        "red_flags": [
            "Treating team health as HR's job or as morale events (pizza, "
            "off-sites) rather than structural work.",
            "Normalizing heroics and all-nighters as a sign of a strong "
            "team.",
            "Measuring health only by velocity or output metrics.",
            "Ignoring early signals (quiet retros, uneven on-call load) until "
            "someone quits.",
        ],
    },
}


class StaffError(Exception):
    """Error for invalid staff-lead requests (unknown ids/topics, bad flags)."""


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def list_influence_scenarios() -> list[str]:
    """Return the ids of all cross-org influence scenarios."""
    return [s["id"] for s in INFLUENCE_SCENARIOS]


def get_influence_scenario(scenario_id: str) -> dict:
    """Return one scenario by id, or raise StaffError."""
    for s in INFLUENCE_SCENARIOS:
        if s["id"] == scenario_id:
            return s
    raise StaffError(
        f"Unknown influence scenario: {scenario_id!r}. "
        f"Available: {', '.join(list_influence_scenarios())}"
    )


def list_mentor_topics() -> list[str]:
    """Return the keys of all mentorship/team-health topics."""
    return list(MENTOR_TOPICS)


def get_mentor_topic(topic: str) -> dict:
    """Return one mentor topic by key, or raise StaffError."""
    try:
        return MENTOR_TOPICS[topic]
    except KeyError:
        raise StaffError(
            f"Unknown mentor topic: {topic!r}. "
            f"Available: {', '.join(list_mentor_topics())}"
        ) from None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_influence(s: dict) -> str:
    """Render one influence scenario as readable prep text."""
    lines = [
        f"Scenario: {s['title']}",
        f"Source: {SOURCE_LABEL}",
        "",
        "The situation:",
        f"  {s['situation']}",
        "",
        "What interviewers are really evaluating:",
        f"  {s['staff_lens']}",
        "",
        "Strong moves:",
    ]
    lines += [f"  - {m}" for m in s["strong_moves"]]
    lines += ["", "Pitfalls to avoid:"]
    lines += [f"  - {p}" for p in s["pitfalls"]]
    lines += [
        "",
        "How to use this: pick a real story from your own experience that fits "
        "the situation. Walk through what you did using the strong moves as a "
        "checklist, and make sure your telling avoids the pitfalls. Do not "
        "invent details.",
    ]
    return "\n".join(lines)


def format_mentor(t: dict) -> str:
    """Render one mentor topic as readable prep text."""
    lines = [
        f"Topic: {t['title']}",
        f"Source: {SOURCE_LABEL}",
        "",
        "Guiding principles:",
    ]
    lines += [f"  - {p}" for p in t["guiding_principles"]]
    lines += ["", "Practice questions:"]
    for pq in t["practice_questions"]:
        lines.append(f"  Q: {pq['q']}")
        lines.append("  Good signals:")
        lines += [f"    - {sig}" for sig in pq["good_signals"]]
        lines.append("")
    lines.append("Red flags (what NOT to say or do):")
    lines += [f"  - {r}" for r in t["red_flags"]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON output (for --json)
# ---------------------------------------------------------------------------

def _scenario_payload(s: dict) -> dict:
    return {
        "id": s["id"],
        "title": s["title"],
        "situation": s["situation"],
        "staff_lens": s["staff_lens"],
        "strong_moves": list(s["strong_moves"]),
        "pitfalls": list(s["pitfalls"]),
        "source": SOURCE_LABEL,
    }


def _topic_payload(t: dict, key: str) -> dict:
    return {
        "topic": key,
        "title": t["title"],
        "guiding_principles": list(t["guiding_principles"]),
        "practice_questions": [
            {"q": pq["q"], "good_signals": list(pq["good_signals"])}
            for pq in t["practice_questions"]
        ],
        "red_flags": list(t["red_flags"]),
        "source": SOURCE_LABEL,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="staff",
        description="Staff/principal interview prep: cross-org influence "
                    "scenarios and mentorship/team-health topics.",
    )
    sub = p.add_subparsers(dest="what", required=True)

    inf = sub.add_parser("influence", help="Cross-org influence scenarios.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff influence\n  python -m candid staff influence --scenario kill-own-project")
    inf.add_argument("--list", action="store_true",
                     help="List scenario ids and titles.")
    inf.add_argument("--scenario", metavar="ID",
                     help="Show one scenario by id.")
    inf.add_argument("--json", action="store_true",
                     help="Emit JSON instead of readable text.")

    men = sub.add_parser("mentor", help="Mentorship and team-health topics.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff mentor\n  python -m candid staff mentor --topic underperformance")
    men.add_argument("--list", action="store_true",
                     help="List topic keys and titles.")
    men.add_argument("--topic", metavar="TOPIC",
                     help="Show one topic by key.")
    men.add_argument("--json", action="store_true",
                     help="Emit JSON instead of readable text.")
    return p


def main(argv=None) -> int:
    """CLI entry: staff influence | staff mentor. Returns exit code."""
    args = _build_parser().parse_args(argv)

    if args.what == "influence":
        if args.scenario:
            try:
                s = get_influence_scenario(args.scenario)
            except StaffError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 2
            if args.json:
                print(json.dumps(_scenario_payload(s), indent=2))
            else:
                print(format_influence(s))
            return 0
        if args.json:
            print(json.dumps(
                [_scenario_payload(s) for s in INFLUENCE_SCENARIOS], indent=2))
        elif args.list or True:
            for s in INFLUENCE_SCENARIOS:
                print(f"{s['id']}: {s['title']}")
        return 0

    # mentor
    if args.topic:
        try:
            t = get_mentor_topic(args.topic)
        except StaffError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
    elif not args.list and not args.json:
        print(format_mentor(MENTOR_TOPICS["growing-engineers"]))
        return 0
    else:
        t = None

    if args.json:
        if args.topic:
            print(json.dumps(_topic_payload(t, args.topic), indent=2))
        else:
            print(json.dumps(
                {k: _topic_payload(v, k) for k, v in MENTOR_TOPICS.items()},
                indent=2))
    elif args.list:
        for key in list_mentor_topics():
            print(f"{key}: {MENTOR_TOPICS[key]['title']}")
    else:
        print(format_mentor(t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
