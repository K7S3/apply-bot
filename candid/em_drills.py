"""Engineering-manager interview prep: people-leadership drills + hiring-loop simulator.

Two tracks:

  drill         — interactive roleplay scenarios for EM interviews:
                  underperformer 1:1, conflict between two reports,
                  hard skip-level feedback, and leading an incident
                  postmortem. You type your response; a local,
                  deterministic rubric scores it on empathy, directness,
                  action plan, and follow-up, then gives concrete feedback.
  hiring-loop   — practice the hiring-manager round from the other side:
                  read a fictional candidate packet, write a hire/no-hire
                  debrief, then get calibrated feedback on how well you
                  evaluated (evidence use, bar consistency, decision clarity).

Everything runs locally and deterministically. Optional AI-interviewer
variants reuse the mock.py Gemini fast path and degrade gracefully
offline (they fall back to the local rubric instead of failing).

Session reports are saved to candid_data/em_drills/.

Usage:
    python -m candid em drill --list
    python -m candid em drill --scenario underperformer
    python -m candid em drill --scenario postmortem --ai
    python -m candid em hiring-loop --list
    python -m candid em hiring-loop --packet maya
"""

from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from candid import config as C

SESSIONS_DIR_NAME = "em_drills"


class EMDrillsError(Exception):
    """Raised for em-drills usage errors."""


def _sessions_dir() -> Path:
    d = C.DATA_DIR / SESSIONS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# shared leadership rubric (empathy, directness, action plan, follow-up)
# ---------------------------------------------------------------------------

DIMENSIONS = [
    {
        "id": "empathy",
        "label": "Empathy",
        "weight": 3,
        "check": "Acknowledge the human in the room: name what they may be feeling, "
                 "listen before prescribing, and show you care about them, not just the output.",
        "signals": [
            "i understand", "i hear you", "that sounds", "appreciate",
            "i know this is", "tough", "support", "recognize",
            "thank you", "your perspective", "i can see", "that must",
            "how you feel", "space to", "listening",
        ],
        "anti": ["not my problem", "deal with it", "grow up"],
        "tips": [
            "Name the feeling you see ('this can't be easy to hear') before moving to the problem.",
            "Ask one genuine question about their view before stating yours.",
        ],
    },
    {
        "id": "directness",
        "label": "Directness",
        "weight": 3,
        "check": "Say the true thing plainly: name the specific behavior and its impact. "
                 "No hedging, no laundering the message through 'leadership'.",
        "signals": [
            "specifically", "missed", "did not", "didn't",
            "expectation", "not acceptable", "clear", "honest",
            "straight", "deferred", "will not", "won't",
            "the decision", "impact was", "the problem",
            "what i need", "what we need",
        ],
        "anti": ["leadership decided", "not my call", "they decided",
                 "hr says", "kind of", "sort of", "perhaps", "maybe"],
        "tips": [
            "Replace hedges ('maybe', 'sort of') with the concrete observation and its impact.",
            "Own the message yourself: 'I decided' beats 'leadership decided' every time.",
        ],
    },
    {
        "id": "action_plan",
        "label": "Action plan",
        "weight": 2,
        "check": "End with a concrete plan: who does what by when. Vague encouragement is not a plan.",
        "signals": [
            "next step", "plan", "by friday", "by monday", "this week",
            "timeline", "owner", "action item", "will do", "agree",
            "deadline", "steps", "two weeks", "follow through",
            "commit to", "document", "write up",
        ],
        "anti": ["figure it out", "try harder", "do better", "just fix it", "should know"],
        "tips": [
            "Attach a date and an owner to every commitment in the conversation.",
            "End the talk by asking them to restate the plan in their own words.",
        ],
    },
    {
        "id": "follow_up",
        "label": "Follow-up",
        "weight": 2,
        "check": "Schedule the next touchpoint. One conversation rarely fixes anything; "
                 "the follow-up is where accountability lives.",
        "signals": [
            "follow up", "check in", "next week", "next 1:1",
            "revisit", "circle back", "update me", "keep me posted",
            "schedule", "touch base", "next time we",
        ],
        "anti": ["good luck", "hope it works", "fingers crossed"],
        "tips": [
            "Book the follow-up before the conversation ends ('let's check in next Tuesday').",
            "Say what you'll do between now and then so it's not one-sided.",
        ],
    },
]


def _dim_by_id(dim_id: str) -> dict:
    for d in DIMENSIONS:
        if d["id"] == dim_id:
            return d
    raise EMDrillsError(f"Unknown rubric dimension '{dim_id}'.")


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "id": "underperformer",
        "title": "The performance conversation",
        "role": "You are the EM. Your counterpart is Alex, a mid-level engineer on your team.",
        "setup": (
            "Alex has missed two consecutive sprint commitments, and peer feedback says "
            "their PRs have gotten slower with review comments going unaddressed. It is "
            "the start of your 1:1. Type exactly what you would say to open this "
            "conversation and steer it somewhere constructive. Keep it realistic, "
            "as if Alex is on the other end of the call."
        ),
        "good": [
            "Name the pattern with specifics (which commitments, what feedback), not a vague 'things aren't great'.",
            "Separate the person from the behavior: firm on the standard, curious about the cause.",
            "Listen for what's underneath: overload, unclear scope, something personal, or a motivation dip.",
            "Agree on a concrete improvement plan with a timeline, and book the check-ins.",
        ],
    },
    {
        "id": "conflict",
        "title": "Two reports in conflict",
        "role": "You are the EM. Priya and Jordan, both senior engineers on your team, are at odds.",
        "setup": (
            "Priya and Jordan disagree on the design of a new internal API. The debate has "
            "moved from design docs into Slack threads and is getting personal; engineers "
            "on the team are starting to take sides. You have pulled them into a room. "
            "Type what you would say to reset the room and drive this to a decision."
        ),
        "good": [
            "Name the dynamic, not just the topic: the team is splitting and the process broke.",
            "Move the debate to decision criteria and owners instead of relitigating opinions.",
            "Timebox the decision and be explicit that you will break the tie if they can't.",
            "Reset the working norm: disagreement is fine, personal threads are not.",
        ],
    },
    {
        "id": "skip-level",
        "title": "Hard skip-level feedback",
        "role": "You are the EM, in a skip-level with your director. Your report is Sam.",
        "setup": (
            "Sam has been pushing hard for a promotion to senior engineer, and your director "
            "has now decided the promo packet will be deferred: the gap is cross-team "
            "collaboration, with two incidents where Sam shipped without looping in the "
            "partner team. You must deliver this news to Sam tomorrow. Type what you would say."
        ),
        "good": [
            "Deliver the deferral directly and kindly: no delaying, no softening into ambiguity.",
            "Own the message yourself; don't launder it through 'leadership decided'.",
            "Cite the specific incidents as evidence, then map the exact gap to the promo bar.",
            "Give a real path forward, and don't promise a timeline you can't keep.",
        ],
    },
    {
        "id": "postmortem",
        "title": "Leading the incident postmortem",
        "role": "You are the EM, opening the postmortem meeting.",
        "setup": (
            "A bad deploy took checkout down for 47 minutes during peak traffic. Root cause "
            "looks like an untested migration script. Two of your engineers are involved, "
            "and the room is tense: the on-call engineer looks miserable. Type your opening "
            "remarks as the EM: set the tone, frame the goal, and get the review started right."
        ),
        "good": [
            "Establish blamelessness explicitly: we are here for the system, not the person.",
            "Acknowledge the impact and thank the responders before diving into the timeline.",
            "Drive toward root cause and concrete action items with owners and dates.",
            "Name the process gap (untested migrations) so it becomes a systemic fix.",
        ],
    },
]


def list_scenarios() -> list[dict]:
    """Lightweight scenario summaries for listing."""
    return [{"id": s["id"], "title": s["title"], "role": s["role"]} for s in SCENARIOS]


def get_scenario(scenario_id: str) -> dict:
    for s in SCENARIOS:
        if s["id"] == scenario_id:
            return s
    known = ", ".join(s["id"] for s in SCENARIOS)
    raise EMDrillsError(f"Unknown scenario '{scenario_id}'. Known: {known}")


def pick_scenario(seed: int | None = None) -> dict:
    return get_scenario(random.Random(seed).choice([s["id"] for s in SCENARIOS]))


def render_scenario_list() -> str:
    lines = ["EM scenario drills (local rubric):", ""]
    for i, s in enumerate(SCENARIOS, 1):
        lines.append(f"  {i}. {s['id']:<15} {s['title']}")
        lines.append(f"      {s['role']}")
    lines.append("")
    lines.append("Run: python -m candid em drill --scenario <id>")
    lines.append("Optional AI counterpart: append --ai (needs network + the stored credential)")
    return "\n".join(lines)


def render_scenario(s: dict) -> str:
    lines = [f"### Drill: {s['title']}", "", s["role"], "", "**Situation**", "", s["setup"], "",
             "**What 'good' looks like** (revealed after your attempt):", ""]
    for g in s["good"]:
        lines.append(f"  • {g}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# rubric scoring (deterministic, heuristic - same honesty as score_star)
# ---------------------------------------------------------------------------

def _find_hit(text: str, signal: str) -> str | None:
    """Return a short quote around the first occurrence of `signal` in `text`."""
    low = text.lower()
    sig = signal.lower()
    idx = low.find(sig)
    if idx == -1:
        return None
    start = max(0, idx - 40)
    end = min(len(text), idx + len(sig) + 40)
    quote = text[start:end].strip().replace("\n", " ")
    return ("..." if start > 0 else "") + quote + ("..." if end < len(text) else "")


def score_response(scenario_id: str, response: str) -> dict:
    """Score a drill response against the rubric. Deterministic.

    Each dimension: base 2, +1 per distinct signal hit (cap 3 bonus -> 5 max),
    -1 if any anti-pattern fires. Empty responses score 1 across the board.
    Overall is the weight-normalized mean of dimension scores.
    """
    get_scenario(scenario_id)  # validates the id
    low = response.lower()
    words = len(response.split())
    dims = []
    for dim in DIMENSIONS:
        hits = [s for s in dim["signals"] if s.lower() in low]
        anti = [s for s in dim["anti"] if s.lower() in low]
        if not response.strip():
            score = 1
        else:
            score = 2 + min(3, len(hits))
            if anti:
                score -= 1
            score = max(1, min(5, score))
        dims.append({
            "id": dim["id"],
            "label": dim["label"],
            "weight": dim["weight"],
            "score": score,
            "hits": hits,
            "anti": anti,
        })
    total_w = sum(d["weight"] for d in dims)
    overall = round(sum(d["score"] * d["weight"] for d in dims) / total_w, 1)
    notes = []
    if response.strip() and words < 30:
        notes.append(f"Short response ({words} words): a real conversation is longer - "
                     "say more and the rubric can find more to score.")
    return {
        "scenario": scenario_id,
        "overall": overall,
        "max": 5,
        "dims": dims,
        "word_count": words,
        "notes": notes,
    }


def render_feedback(result: dict, scenario: dict) -> str:
    """Concrete, rubric-grounded feedback. Only quotes the user's own words."""
    lines = [
        f"Rubric score: {result['overall']}/{result['max']}  "
        f"({scenario['title']})",
        "",
    ]
    for d in result["dims"]:
        dim = _dim_by_id(d["id"])
        score = d["score"]
        if score >= 4:
            quote = _find_hit(_LAST_RESPONSE, d["hits"][0]) if _LAST_RESPONSE else None
            line = f"  ✅ {d['label']} {score}/5 - strong."
            if quote:
                line += f' You said: "{quote}"'
            lines.append(line)
        elif score >= 3:
            lines.append(f"  ⚠️  {d['label']} {score}/5 - developing. {dim['tips'][0]}")
        else:
            lines.append(f"  ❌ {d['label']} {score}/5 - missing. {dim['tips'][0]}")
        for a in d["anti"]:
            lines.append(f"      ⛔ Anti-pattern to drop: '{a}'. {dim['tips'][1] if len(dim['tips']) > 1 else ''}")
    if result["notes"]:
        lines += [""] + [f"Note: {n}" for n in result["notes"]]
    lines += ["", "**What 'good' looks like here:**"]
    for g in scenario["good"]:
        lines.append(f"  • {g}")
    return "\n".join(lines)


# holds the last scored response so render_feedback can quote it;
# set by score_response_with_quotes wrapper used in interactive flow.
_LAST_RESPONSE = ""


def score_response_with_quotes(scenario_id: str, response: str) -> dict:
    """score_response plus a remembered copy of the text for quoting."""
    global _LAST_RESPONSE
    _LAST_RESPONSE = response
    return score_response(scenario_id, response)


# ---------------------------------------------------------------------------
# interactive drill flow
# ---------------------------------------------------------------------------

def _read_response(input_fn=None) -> str:
    print("\nType your response below (end with a line containing only EOF):")
    lines: list[str] = []
    try:
        while True:
            line = (input_fn() if input_fn else input())
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def _choose_scenario_interactive(input_fn=None) -> dict:
    print(render_scenario_list())
    read = input_fn or input
    try:
        choice = read("\nPick a scenario [1-4] (or name): ").strip().lower()
    except EOFError:
        choice = ""
    if choice.isdigit() and 1 <= int(choice) <= len(SCENARIOS):
        return SCENARIOS[int(choice) - 1]
    for s in SCENARIOS:
        if choice == s["id"]:
            return s
    print("Defaulting to the first scenario.\n")
    return SCENARIOS[0]


def _save_session(report: dict) -> Path:
    d = _sessions_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = d / f"{stamp}_{report['track']}_{report['item']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def run_drill(scenario_id: str | None = None, input_fn=None,
              seed: int | None = None) -> dict:
    """Run one interactive drill. Returns the session report."""
    scenario = get_scenario(scenario_id) if scenario_id else _choose_scenario_interactive(input_fn)
    print(render_scenario(scenario))
    t0 = datetime.now()
    response = _read_response(input_fn)
    result = score_response_with_quotes(scenario["id"], response)
    print("\n" + "=" * 60)
    print(render_feedback(result, scenario))
    print("=" * 60)
    report = {
        "track": "em_drill",
        "item": scenario["id"],
        "outcome": "completed",
        "overall": result["overall"],
        "max": result["max"],
        "dims": [{k: d[k] for k in ("id", "label", "score", "hits", "anti")} for d in result["dims"]],
        "word_count": result["word_count"],
        "response": response[:2000],
        "at": t0.isoformat(timespec="seconds"),
    }
    _save_session(report)
    print(f"\nSession saved to {_sessions_dir()}/")
    return report


# ---------------------------------------------------------------------------
# hiring-loop simulator
# ---------------------------------------------------------------------------

PACKETS = [
    {
        "id": "maya",
        "name": "Maya Chen",
        "target_role": "Senior Backend Engineer",
        "summary": [
            "7 years backend (Java/Kotlin), last 2 at a mid-size fintech on the payments team.",
            "Led a migration from a monolith billing module to event-driven services; quotes 40% latency reduction.",
            "4 jobs in 5 years (each 12-18 months); says she 'optimizes for scope and learning'.",
        ],
        "scorecards": [
            {"interviewer": "R. Alvarez", "round": "Coding",
             "rating": "Strong hire",
             "notes": "Solved cleanly, handled follow-ups, clear complexity analysis."},
            {"interviewer": "T. Osei", "round": "System design",
             "rating": "Hire",
             "notes": "Good tradeoff discussion on exactly-once vs at-least-once delivery."},
            {"interviewer": "D. Park", "round": "Behavioral",
             "rating": "Lean hire",
             "notes": "Strong ownership stories. One note: 'talks over people when excited' - "
                      "no concrete example given."},
        ],
        "evidence": [
            {"fact": "40% latency reduction on the billing migration", "keys": ["latency", "migration", "billing", "40"]},
            {"fact": "4 jobs in 5 years, each 12-18 months", "keys": ["4 jobs", "tenure", "12-18", "job"]},
            {"fact": "Coding round: strong hire with clear complexity analysis", "keys": ["coding", "complexity", "strong hire"]},
            {"fact": "The 'talks over people' note had no concrete example", "keys": ["no concrete example", "no example", "talks over"]},
        ],
        "calibrated": "hire",
        "rationale": (
            "Consistent strong technical signal across coding and design, plus a measured "
            "ownership story in behavioral. The short tenures are worth a retention conversation "
            "but are explained and not disqualifying for a senior hire. The 'talks over people' "
            "flag is a single uncited note from one interviewer - it should not carry weight "
            "against the rest of the packet."
        ),
        "trap": "Overweighting the one uncited 'talks over people' note, or treating 12-18 month tenures as an automatic reject.",
    },
    {
        "id": "devon",
        "name": "Devon Okafor",
        "target_role": "Senior Backend Engineer",
        "summary": [
            "5 years backend (Python/Go), currently at a logistics startup.",
            "Very articulate: polished stories about scaling the dispatch service 10x.",
            "References uniformly describe him as 'great to work with' but none would rehire into the same role.",
        ],
        "scorecards": [
            {"interviewer": "R. Alvarez", "round": "Coding",
             "rating": "No hire",
             "notes": "Needed heavy hints; solution was O(n^2) after 25 minutes of guidance."},
            {"interviewer": "T. Osei", "round": "System design",
             "rating": "Lean no-hire",
             "notes": "Hand-wavy on tradeoffs; skipped the failure-mode discussion entirely."},
            {"interviewer": "D. Park", "round": "Behavioral",
             "rating": "Hire",
             "notes": "Polished STAR stories, but every story is 'we' - could not pin down his own contribution."},
        ],
        "evidence": [
            {"fact": "Needed heavy hints in coding; solution was O(n^2)", "keys": ["heavy hints", "hints", "o(n^2)", "coding"]},
            {"fact": "Skipped the failure-mode discussion in system design", "keys": ["failure-mode", "failure mode", "design", "tradeoffs"]},
            {"fact": "Behavioral stories are all 'we' with no personal contribution", "keys": ["we", "own contribution", "contribution"]},
            {"fact": "References would not rehire him into the same role", "keys": ["rehire", "references"]},
        ],
        "calibrated": "no-hire",
        "rationale": (
            "Below-bar technical signal in both coding and design is the core of the packet, "
            "and the behavioral round shows polish without attributable impact. Charisma in the "
            "room is not evidence; the references not rehiring into the same role is a "
            "consistent, independent negative signal."
        ),
        "trap": "Letting a smooth behavioral performance and 'great to work with' references paper over below-bar technical rounds.",
    },
    {
        "id": "priya",
        "name": "Priya Raman",
        "target_role": "Senior Backend Engineer",
        "summary": [
            "6 years backend (Java), currently at a large bank on the ledger team.",
            "Quiet and methodical: asked careful clarifying questions before writing code.",
            "Mentions she is slow to warm up in design discussions but lands on solid answers.",
        ],
        "scorecards": [
            {"interviewer": "R. Alvarez", "round": "Coding",
             "rating": "Strong hire",
             "notes": "Excellent: tested edge cases unprompted, clean and readable code."},
            {"interviewer": "T. Osei", "round": "System design",
             "rating": "Lean hire",
             "notes": "Needed drawing out, but the final design was solid and she caught the "
                      "consistency requirement on her own."},
            {"interviewer": "D. Park", "round": "Behavioral",
             "rating": "No hire",
             "notes": "'Communication style won't cut it at staff level' - a style preference "
                      "with no cited incident of miscommunication."},
        ],
        "evidence": [
            {"fact": "Coding: excellent, tested edge cases unprompted", "keys": ["edge cases", "coding", "excellent"]},
            {"fact": "Design: slow start but caught the consistency requirement herself", "keys": ["consistency", "design", "slow"]},
            {"fact": "The no-hire note cites communication 'style', with no cited miscommunication", "keys": ["style", "no cited", "miscommunication"]},
        ],
        "calibrated": "hire",
        "rationale": (
            "The technical bar is met: strong coding plus a design that lands solidly once she "
            "warms up. The dissenting note is about style preference, not signal: it cites no "
            "actual miscommunication. Calibrate on the bar, not on whether someone matches your "
            "personal communication template."
        ),
        "trap": "Treating a quiet communication style as a signal problem, or letting one stylistic dissent veto a packet that meets the bar.",
    },
]


def list_packets() -> list[dict]:
    return [{"id": p["id"], "name": p["name"], "target_role": p["target_role"]}
            for p in PACKETS]


def get_packet(packet_id: str) -> dict:
    for p in PACKETS:
        if p["id"] == packet_id:
            return p
    known = ", ".join(p["id"] for p in PACKETS)
    raise EMDrillsError(f"Unknown packet '{packet_id}'. Known: {known}")


def pick_packet(seed: int | None = None) -> dict:
    return get_packet(random.Random(seed).choice([p["id"] for p in PACKETS]))


def render_packet_list() -> str:
    lines = ["Hiring-loop candidate packets (all fictional):", ""]
    for i, p in enumerate(PACKETS, 1):
        lines.append(f"  {i}. {p['id']:<8} {p['name']} - {p['target_role']}")
    lines.append("")
    lines.append("Run: python -m candid em hiring-loop [--packet <id>]")
    return "\n".join(lines)


def render_packet(p: dict) -> str:
    lines = [f"### Candidate packet: {p['name']} ({p['target_role']})", "",
             "**Background**"]
    for b in p["summary"]:
        lines.append(f"  • {b}")
    lines.append("")
    lines.append("**Interview scorecards**")
    for c in p["scorecards"]:
        lines.append(f"  [{c['rating']}] {c['interviewer']} - {c['round']}")
        lines.append(f"      {c['notes']}")
    lines += ["", "You are the hiring manager. Write your debrief below: start with your "
                   "verdict (hire / no-hire), then your reasoning. Cite the packet's "
                   "evidence - the interviewers' notes, not vibes."]
    return "\n".join(lines)


_CLICHE = ["gut feeling", "vibe", "culture fit", "just feels"]


def _normalize_verdict(text: str) -> str | None:
    low = text.lower()
    if re.search(r"\bno[\s\-_]?hire\b", low):
        return "no-hire"
    if re.search(r"\bhire\b", low):
        return "hire"
    return None


def grade_debrief(packet_id: str, verdict: str, reasoning: str) -> dict:
    """Grade a hiring debrief. Deterministic and evidence-grounded.

    verdict: the user's stated call ('hire' or 'no-hire').
    reasoning: the user's written reasoning.

    Scores:
      decision_clarity - an explicit verdict was stated (5) or not (1).
      evidence_use    - fraction of the packet's key evidence points cited (1-5).
      calibration     - matches the hidden calibrated bar (5) or not (2).
    Overall is the mean, rounded to 1 decimal.
    """
    packet = get_packet(packet_id)
    combined = (verdict + " " + reasoning).lower()
    stated = _normalize_verdict(verdict) or _normalize_verdict(reasoning)

    # evidence citation: a point counts as cited when at least half its keys appear
    cited, missed = [], []
    for ev in packet["evidence"]:
        keys = [k.lower() for k in ev["keys"]]
        hits = sum(1 for k in keys if k in combined)
        (cited if hits >= max(1, len(keys) / 2) else missed).append(ev["fact"])

    evidence_score = 1 + round(4 * (len(cited) / max(1, len(packet["evidence"]))))
    evidence_score = max(1, min(5, evidence_score))

    decision_score = 5 if stated else 1
    calibration_score = 5 if stated and stated == packet["calibrated"] else 2

    words = len(reasoning.split())
    cliches = [c for c in _CLICHE if c in combined]
    notes = []
    if words < 60 and reasoning.strip():
        notes.append(f"Thin reasoning ({words} words): a debrief should cite specific evidence.")
    if cliches:
        notes.append("Avoid ungrounded language in debriefs: "
                     + ", ".join(f"'{c}'" for c in cliches)
                     + " - point at evidence instead.")

    overall = round((decision_score + evidence_score + calibration_score) / 3, 1)
    return {
        "packet": packet_id,
        "stated_verdict": stated,
        "decision_clarity": decision_score,
        "evidence_use": evidence_score,
        "calibration": calibration_score,
        "overall": overall,
        "max": 5,
        "cited": cited,
        "missed": missed,
        "cliches": cliches,
        "notes": notes,
        "calibrated_verdict": packet["calibrated"],
    }


def render_debrief_feedback(grade: dict, packet: dict) -> str:
    lines = [
        f"Debrief grade: {grade['overall']}/{grade['max']}  ({packet['name']})",
        "",
        f"  Decision clarity: {grade['decision_clarity']}/5 - "
        + ("you stated an explicit verdict."
           if grade["stated_verdict"] else "no explicit hire/no-hire verdict found - state your call first."),
        f"  Evidence use:     {grade['evidence_use']}/5 - cited {len(grade['cited'])}/{len(grade['cited']) + len(grade['missed'])} key points.",
        f"  Calibration:      {grade['calibration']}/5 - "
        + (f"matches the calibrated bar ({grade['calibrated_verdict']})."
           if grade["stated_verdict"] == grade["calibrated_verdict"]
           else f"diverges from the calibrated bar ({grade['calibrated_verdict']})."),
        "",
    ]
    if grade["cited"]:
        lines.append("Evidence you used:")
        lines += [f"  + {c}" for c in grade["cited"]]
    if grade["missed"]:
        lines += ["", "Evidence you missed:"]
        lines += [f"  – {m}" for m in grade["missed"]]
    lines += ["", "**Calibrated read on this packet:**", f"  {packet['rationale']}", "",
              f"Common trap here: {packet['trap']}"]
    if grade["notes"]:
        lines += [""] + [f"Note: {n}" for n in grade["notes"]]
    return "\n".join(lines)


def _choose_packet_interactive(input_fn=None) -> dict:
    print(render_packet_list())
    read = input_fn or input
    try:
        choice = read("\nPick a packet [1-3] (or name): ").strip().lower()
    except EOFError:
        choice = ""
    if choice.isdigit() and 1 <= int(choice) <= len(PACKETS):
        return PACKETS[int(choice) - 1]
    for p in PACKETS:
        if choice == p["id"]:
            return p
    print("Defaulting to the first packet.\n")
    return PACKETS[0]


def run_hiring_loop(packet_id: str | None = None, input_fn=None) -> dict:
    """Run one hiring-loop practice session. Returns the session report."""
    packet = get_packet(packet_id) if packet_id else _choose_packet_interactive(input_fn)
    print(render_packet(packet))
    t0 = datetime.now()
    read = input_fn or input
    print("\nYour verdict (hire / no-hire):")
    try:
        verdict = read("> ").strip()
    except EOFError:
        verdict = ""
    print("Your reasoning (end with a line containing only EOF):")
    lines: list[str] = []
    try:
        while True:
            line = read() if input_fn else input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    reasoning = "\n".join(lines)
    grade = grade_debrief(packet["id"], verdict, reasoning)
    print("\n" + "=" * 60)
    print(render_debrief_feedback(grade, packet))
    print("=" * 60)
    report = {
        "track": "em_hiring_loop",
        "item": packet["id"],
        "outcome": "completed",
        "overall": grade["overall"],
        "max": grade["max"],
        "stated_verdict": grade["stated_verdict"],
        "calibrated_verdict": grade["calibrated_verdict"],
        "cited": grade["cited"],
        "missed": grade["missed"],
        "verdict": verdict,
        "reasoning": reasoning[:2000],
        "at": t0.isoformat(timespec="seconds"),
    }
    _save_session(report)
    print(f"\nSession saved to {_sessions_dir()}/")
    return report


# ---------------------------------------------------------------------------
# optional AI-interviewer hooks (Gemini fast path; graceful offline fallback)
# ---------------------------------------------------------------------------

AI_PERSONAS = {
    "drill": {
        "name": "Leadership drill coach",
        "system": (
            "You are an executive coach running an engineering-manager interview drill. "
            "Style: realistic roleplay, then honest feedback. Rules: (1) Play the counterpart "
            "described in the scenario setup, staying in character - react naturally to what the "
            "candidate says, escalate or soften based on their approach. (2) Keep each reply to "
            "a few sentences so the candidate drives the conversation. (3) When they say "
            "done/feedback, stop roleplaying and produce: scores 1-5 for empathy, directness, "
            "action plan, and follow-up; 2-3 strengths with quotes; 2-3 gaps; and 2 concrete "
            "lines they could have said instead."
        ),
    },
    "hiring_loop": {
        "name": "Hiring committee chair",
        "system": (
            "You are a hiring committee chair helping an engineering manager practice the "
            "hiring-manager round. Style: sharp, evidence-driven. Rules: (1) Present the "
            "candidate packet neutrally. (2) After their debrief, probe: 'what evidence supports "
            "that?', 'which interviewer signal are you discounting and why?', 'what would change "
            "your mind?'. (3) When they say done/feedback, produce: scores 1-5 for evidence use, "
            "bar consistency, decision clarity; where they over/under-weighted signals; and the "
            "calibrated read with rationale."
        ),
    },
}


def _gemini_available() -> bool:
    return (Path("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py").exists())


def ai_drill(scenario_id: str | None = None, input_fn=None) -> dict:
    """Roleplay a scenario with the AI as your counterpart. Falls back to the
    local rubric drill when offline or when the credential is unavailable."""
    scenario = get_scenario(scenario_id) if scenario_id else pick_scenario()
    if not _gemini_available():
        print("AI interviewer unavailable (no network path / credential). "
              "Falling back to the local rubric drill.\n")
        return run_drill(scenario["id"], input_fn=input_fn)
    try:
        from candid import mock as _mock
        persona = AI_PERSONAS["drill"]
        opener = (f"Scenario: {scenario['title']}.\n{scenario['role']}\n"
                  f"Situation:\n{scenario['setup']}\n\n"
                  f"You are the counterpart in this scenario. Start in character, briefly, "
                  f"and let the candidate lead the conversation.")
        messages = [{"role": "user", "parts": [{"text": opener}]}]
        print(f"🤖 {persona['name']} — type your answers. Commands: done (get feedback) | quit\n")
        reply = _mock._gemini_chat(persona["system"], messages)
        messages.append({"role": "model", "parts": [{"text": reply}]})
        print(f"Counterpart: {reply}\n")
        t0 = datetime.now()
        while True:
            try:
                user = (input_fn() if input_fn else input("You: ")).strip()
            except EOFError:
                user = "quit"
            if user.lower() in ("quit", "exit"):
                print("Session ended without feedback.")
                return {"track": "em_drill_ai", "item": scenario["id"],
                        "outcome": "abandoned", "at": t0.isoformat(timespec="seconds")}
            messages.append({"role": "user", "parts": [{"text": user}]})
            if user.lower() in ("done", "feedback", "finish"):
                messages.append({"role": "user", "parts": [{
                    "text": "The candidate is done. Now stop roleplaying and give final "
                            "feedback in this exact format:\n"
                            "Scores (1-5): empathy, directness, action plan, follow-up\n"
                            "Strengths (with quotes):\n- ...\nGaps:\n- ...\n"
                            "Lines they could have said instead:\n- ..."}]})
                feedback = _mock._gemini_chat(persona["system"], messages)
                print(f"\n{'='*60}\n📋 FEEDBACK\n{'='*60}\n{feedback}\n")
                report = {"track": "em_drill_ai", "item": scenario["id"],
                          "outcome": "completed",
                          "at": t0.isoformat(timespec="seconds"),
                          "notes": feedback[:2000]}
                _save_session(report)
                return report
            reply = _mock._gemini_chat(persona["system"], messages)
            messages.append({"role": "model", "parts": [{"text": reply}]})
            print(f"\nCounterpart: {reply}\n")
    except Exception as e:
        print(f"AI interviewer failed ({e}). Falling back to the local rubric drill.\n")
        return run_drill(scenario["id"], input_fn=input_fn)


def ai_hiring_loop(packet_id: str | None = None, input_fn=None) -> dict:
    """Committee-chair dialogue for the hiring loop. Same graceful fallback."""
    packet = get_packet(packet_id) if packet_id else pick_packet()
    if not _gemini_available():
        print("AI interviewer unavailable (no network path / credential). "
              "Falling back to the local hiring-loop.\n")
        return run_hiring_loop(packet["id"], input_fn=input_fn)
    try:
        from candid import mock as _mock
        persona = AI_PERSONAS["hiring_loop"]
        opener = (f"You are presenting this candidate packet to the candidate, who plays the "
                  f"hiring manager:\n\n{render_packet(packet)}\n\n"
                  f"Present it briefly, then ask for their debrief.")
        messages = [{"role": "user", "parts": [{"text": opener}]}]
        print(f"🤖 {persona['name']} — type your answers. Commands: done (get feedback) | quit\n")
        reply = _mock._gemini_chat(persona["system"], messages)
        messages.append({"role": "model", "parts": [{"text": reply}]})
        print(f"Chair: {reply}\n")
        t0 = datetime.now()
        while True:
            try:
                user = (input_fn() if input_fn else input("You: ")).strip()
            except EOFError:
                user = "quit"
            if user.lower() in ("quit", "exit"):
                print("Session ended without feedback.")
                return {"track": "em_hiring_loop_ai", "item": packet["id"],
                        "outcome": "abandoned", "at": t0.isoformat(timespec="seconds")}
            messages.append({"role": "user", "parts": [{"text": user}]})
            if user.lower() in ("done", "feedback", "finish"):
                messages.append({"role": "user", "parts": [{
                    "text": "The candidate is done. Give final feedback in this exact format:\n"
                            "Scores (1-5): evidence use, bar consistency, decision clarity\n"
                            "Over/under-weighted signals:\n- ...\n"
                            f"Calibrated read:\n{packet['rationale']}"}]})
                feedback = _mock._gemini_chat(persona["system"], messages)
                print(f"\n{'='*60}\n📋 FEEDBACK\n{'='*60}\n{feedback}\n")
                report = {"track": "em_hiring_loop_ai", "item": packet["id"],
                          "outcome": "completed",
                          "at": t0.isoformat(timespec="seconds"),
                          "notes": feedback[:2000]}
                _save_session(report)
                return report
            reply = _mock._gemini_chat(persona["system"], messages)
            messages.append({"role": "model", "parts": [{"text": reply}]})
            print(f"\nChair: {reply}\n")
    except Exception as e:
        print(f"AI interviewer failed ({e}). Falling back to the local hiring-loop.\n")
        return run_hiring_loop(packet["id"], input_fn=input_fn)
