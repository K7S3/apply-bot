"""Interactive mock interviews: coding judge, AI interviewer, behavioral, system design.

Tracks:
  coding      — pick a problem from the local bank, submit a solution file or
                paste code, get a judge verdict (accepted / wrong answer /
                time limit exceeded / runtime error) with failing-case details.
  ai          — conversational AI interviewer (Gemini fast path) that asks the
                question, probes your approach, and scores you at the end.
  behavioral  — STAR questions with a rubric self-check (+ optional AI feedback).
  design      — system-design prompt with rubric and sample answer structure.

Everything except the AI dialogue runs locally and deterministically.
Session reports (scores, strengths, gaps, study plan) are saved to
candid_data/mock_sessions/.

Usage:
    python -m candid mock list [--topic arrays] [--difficulty medium]
    python -m candid mock coding [--topic dp] [--difficulty easy]
    python -m candid mock run --problem two-sum --file solution.py
    python -m candid mock hint --problem two-sum
    python -m candid mock ai --track coding --topic graphs
    python -m candid mock behavioral
    python -m candid mock design
"""

from __future__ import annotations

import json
import random
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from candid import config as C
from candid import mock_judge as J

DATA = Path(__file__).parent / "data"
SESSIONS_DIR = C.DATA_DIR / "mock_sessions"

# area -> concept deep-dive tags (see candid.prep_concepts) for study plans
AREA_CONCEPTS: dict[str, list[str]] = {
    "a/b testing": ["ab_testing"],
    "experimentation": ["ab_testing"],
    "sql": ["sql_window", "star_schema"],
    "metrics": ["metrics_trees"],
    "ml fundamentals": ["xgboost_vs_rf", "transformers"],
    "ml systems": ["ml_system_design", "rag_design"],
    "llm": ["llm_eval", "rag_design"],
    "statistics": ["pvalues", "causal_inference"],
    "gpu": ["gpu_training"],
}


class MockError(Exception):
    """Raised for mock-interview usage errors."""


# ---------------------------------------------------------------------------
# problem bank
# ---------------------------------------------------------------------------

def _problems_dir() -> Path:
    d = DATA / "problems"
    if not d.exists():
        raise MockError("Problem bank not found. Run scripts/seed_problems.py first.")
    return d


def list_problems(topic: str | None = None, difficulty: str | None = None) -> list[dict]:
    out = []
    for f in sorted(_problems_dir().glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if topic and p.get("topic") != topic:
            continue
        if difficulty and p.get("difficulty") != difficulty:
            continue
        out.append({k: p[k] for k in ("id", "title", "topic", "difficulty", "function")})
    return out


def get_problem(problem_id: str) -> dict:
    f = _problems_dir() / f"{problem_id}.json"
    if not f.exists():
        known = [p["id"] for p in list_problems()]
        raise MockError(f"Unknown problem '{problem_id}'. Known: {', '.join(known)}")
    return json.loads(f.read_text(encoding="utf-8"))


def pick_problem(topic: str | None = None, difficulty: str | None = None,
                 seed: int | None = None) -> dict:
    pool = list_problems(topic, difficulty)
    if not pool:
        raise MockError("No problems match that topic/difficulty. Try `mock list`.")
    rng = random.Random(seed)
    return get_problem(rng.choice(pool)["id"])


def render_problem(p: dict, show_hidden_count: bool = True) -> str:
    lines = [
        f"### {p['title']}  [{p['topic']} · {p['difficulty']}]",
        "",
        p["statement"],
        "",
        f"Write: `{p['function']}`",
        "",
        "**Visible examples:**",
    ]
    for t in p.get("visible_tests", []):
        lines.append(f"  input: {t['args']}  ->  {t['expected']}")
    if show_hidden_count:
        lines.append(f"\n(+ {len(p.get('hidden_tests', []))} hidden tests)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# coding sessions
# ---------------------------------------------------------------------------

def read_solution_interactive() -> str:
    print("Paste your solution below (define the required function).")
    print("End with a line containing only EOF, or press Ctrl-D.")
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


def run_problem(problem_id: str, code: str) -> dict:
    """Judge `code` against a problem. Returns the judge result dict."""
    problem = get_problem(problem_id)
    return J.judge(problem, code)


def render_verdict(problem_id: str, result: dict) -> str:
    """Readable verdict block: outcome, pass counts, then failure details."""
    v = result["verdict"]
    icon = {"accepted": "✅", "wrong_answer": "❌", "time_limit_exceeded": "⏱️",
            "runtime_error": "💥"}.get(v, "❓")
    tests = result.get("tests", [])
    n = len(tests)
    passed = sum(1 for t in tests if t.get("verdict") == "accepted")
    vis = [t for t in tests if not t.get("hidden")]
    vis_passed = sum(1 for t in vis if t.get("verdict") == "accepted")
    lines = [
        f"{icon} {v.replace('_', ' ').upper()} - {problem_id}",
        f"{passed}/{n} tests passed ({vis_passed}/{len(vis)} visible, "
        f"{passed - vis_passed}/{n - len(vis)} hidden)",
    ]
    summary = result.get("summary", "")
    if summary:
        lines.append(summary)
    lines.append("")
    lines += J.failing_details(result)
    if v == "time_limit_exceeded":
        lines += ["",
                  "Tip: infinite loops fail fast here - add a progress print or a "
                  "loop counter locally to find where it spins."]
    return "\n".join(lines).strip()


def interactive_coding(topic: str | None = None, difficulty: str | None = None,
                       problem_id: str | None = None, solution_file: str | None = None,
                       seed: int | None = None) -> dict:
    """Full interactive coding session. Returns the session report."""
    problem = get_problem(problem_id) if problem_id else pick_problem(topic, difficulty, seed)
    print(render_problem(problem))
    print()

    hints_used = 0
    attempts = 0
    transcript: list[str] = []
    t0 = datetime.now()

    while True:
        if solution_file:
            code = Path(solution_file).read_text(encoding="utf-8")
        else:
            code = read_solution_interactive()
        if not code.strip():
            print("Empty solution — type 'quit' to exit, or paste code.")
            cmd = input("> ").strip().lower()
            if cmd == "quit":
                return _session_report("coding", problem["id"], "abandoned", attempts,
                                       hints_used, t0, None)
            continue
        attempts += 1
        print("\nRunning judge...\n")
        result = J.judge(problem, code)
        print(render_verdict(problem["id"], result))
        transcript.append(f"attempt {attempts}: {result['verdict']}")
        if result["verdict"] == "accepted":
            break
        print()
        cmd = input("What next? [retry] paste again · [hint] · [solution] reveal · [quit]\n> ").strip().lower()
        if cmd == "hint":
            hints = problem.get("hints", [])
            if hints_used < len(hints):
                print(f"\n💡 Hint {hints_used + 1}: {hints[hints_used]}\n")
                hints_used += 1
            else:
                print("\nNo more hints — the reference solution is the next step.\n")
        elif cmd == "solution":
            print("\n--- Reference solution ---\n")
            print(problem["reference_solution"])
            print(f"\nComplexity: {problem['complexity']}\n")
            break
        elif cmd == "quit":
            break
        # else: retry loop

    report = _session_report("coding", problem["id"],
                             "solved" if result["verdict"] == "accepted" else "gave_up",
                             attempts, hints_used, t0, result["verdict"])
    _save_session(report)
    print("\n" + _render_report(report))
    return report


def show_solution(problem_id: str) -> str:
    p = get_problem(problem_id)
    return (f"--- Reference solution: {p['title']} ---\n\n{p['reference_solution']}\n"
            f"Complexity: {p['complexity']}")


# ---------------------------------------------------------------------------
# AI interviewer (Gemini fast path)
# ---------------------------------------------------------------------------

def _gemini_chat(system: str, messages: list[dict], model: str = "gemini-3.6-flash") -> str:
    """One Gemini call with conversation history. Only the dialogue uses the network."""
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import url_with_surrogate_query_param, read_json_response
    import urllib.error

    base = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    url = url_with_surrogate_query_param(base, "custom.google-gemini",
                                         allowed_hosts=["generativelanguage.googleapis.com"])
    payload = {
        "contents": messages,
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = read_json_response(resp)
    except urllib.error.HTTPError as e:
        raise MockError(f"Gemini request failed (HTTP {e.code}). Check the google-gemini skill.") from e
    except Exception as e:
        raise MockError(f"Gemini request failed: {e}. The AI interviewer needs network + the stored credential.") from e
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise MockError("Gemini returned an unexpected response shape.") from e


def _load_personas() -> dict:
    return json.loads((DATA / "personas.json").read_text(encoding="utf-8"))


def ai_interview(track: str = "coding", topic: str | None = None,
                 difficulty: str | None = None, problem_id: str | None = None) -> dict:
    """Conversational AI interviewer session. Returns the session report."""
    personas = _load_personas()
    if track not in personas:
        raise MockError(f"Unknown AI track '{track}'. Choose from: {', '.join(personas)}")
    persona = personas[track]

    if track == "coding":
        problem = get_problem(problem_id) if problem_id else pick_problem(topic, difficulty)
        opener = (f"Here is the candidate's problem:\n\n{render_problem(problem, show_hidden_count=False)}\n\n"
                  f"Reference solution (for your eyes only — never reveal unless they give up):\n"
                  f"{problem['reference_solution']}\nComplexity: {problem['complexity']}\n\n"
                  f"Start the interview: greet the candidate briefly and present the problem.")
    elif track == "behavioral":
        q = _pick_behavioral()
        opener = (f"Behavioral theme: {q['theme']}. Question: {q['question']}\n"
                  f"What 'good' looks like: {q['what_good_looks_like']}\n\nStart the interview.")
    else:
        q = _pick_design()
        opener = (f"System design prompt ({q['level']}): {q['prompt']}\n"
                  f"Strong answer structure: {'; '.join(q['sample_structure'])}\n\nStart the interview.")

    messages = [{"role": "user", "parts": [{"text": opener}]}]
    print(f"🤖 {persona['name']} — type your answers. Commands: hint | done (get feedback) | quit\n")
    reply = _gemini_chat(persona["system"], messages)
    messages.append({"role": "model", "parts": [{"text": reply}]})
    print(f"Interviewer: {reply}\n")

    t0 = datetime.now()
    transcript = [f"interviewer: {reply}"]
    while True:
        try:
            user = input("You: ").strip()
        except EOFError:
            user = "quit"
        if user.lower() in ("quit", "exit"):
            print("Session ended without feedback.")
            return _session_report(f"ai_{track}", problem_id or q["id"], "abandoned",
                                   0, 0, t0, None)
        if user.lower() == "hint" and track == "coding":
            hints = problem.get("hints", [])
            print(f"💡 {hints[0] if hints else 'Think about the brute force first, then optimize.'}\n")
            continue
        messages.append({"role": "user", "parts": [{"text": user}]})
        transcript.append(f"you: {user}")
        if user.lower() in ("done", "feedback", "finish"):
            messages.append({"role": "user", "parts": [{
                "text": "The candidate is done. Now give final feedback in this exact format:\n"
                        "Scores (1-5): <area>: <score> ...\nStrengths:\n- ...\nGaps:\n- ...\nStudy plan:\n- ..."}]})
            feedback = _gemini_chat(persona["system"], messages)
            print(f"\n{'='*60}\n📋 FEEDBACK\n{'='*60}\n{feedback}\n")
            transcript.append(f"feedback: {feedback}")
            report = _session_report(f"ai_{track}", problem_id or q.get("id", track),
                                     "completed", len(transcript), 0, t0, "feedback_given",
                                     notes=feedback)
            _save_session(report)
            return report
        reply = _gemini_chat(persona["system"], messages)
        messages.append({"role": "model", "parts": [{"text": reply}]})
        transcript.append(f"interviewer: {reply}")
        print(f"\nInterviewer: {reply}\n")


# ---------------------------------------------------------------------------
# behavioral + system design tracks (local)
# ---------------------------------------------------------------------------

def _pick_behavioral(theme: str | None = None) -> dict:
    data = json.loads((DATA / "behavioral.json").read_text(encoding="utf-8"))
    qs = data["tracks"]["behavioral"]
    if theme:
        qs = [q for q in qs if q["theme"] == theme]
        if not qs:
            # Fall back to leadership-principle drills (candid.behavioral):
            # `mock behavioral --theme bias_action` just works.
            try:
                from candid import behavioral as B
                lp = B.mock_question(theme)
            except Exception:
                lp = None
            if lp is not None:
                return lp
            raise MockError(f"Unknown behavioral theme '{theme}'.")
    return random.choice(qs)


def _behavioral_rubric() -> list[dict]:
    return json.loads((DATA / "behavioral.json").read_text(encoding="utf-8"))["rubric"]


def score_star(answer: str) -> dict:
    """Heuristic STAR self-check. Honest about being a heuristic."""
    rubric = _behavioral_rubric()
    low = answer.lower()
    dims = []
    for item in rubric:
        hits = sum(1 for s in item["signals"] if s.lower() in low)
        present = hits >= (2 if item["dimension"] == "Action" else 1)
        dims.append({"dimension": item["dimension"], "present": present,
                     "check": item["check"]})
    score = sum(d["present"] * next(r["weight"] for r in rubric if r["dimension"] == d["dimension"])
                for d in dims)
    max_score = sum(r["weight"] for r in rubric)
    missing = [d for d in dims if not d["present"]]
    return {"score": score, "max": max_score, "dims": dims, "missing": missing}


def behavioral_session(theme: str | None = None, ai_feedback: bool = False) -> dict:
    q = _pick_behavioral(theme)
    print(f"### Behavioral — {q['theme']}\n\n**{q['question']}**\n")
    print("Answer out loud or type it below (end with a line containing only EOF):")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    answer = "\n".join(lines)
    if len(answer.strip()) < 50:
        print("That answer is very short — a strong STAR answer is usually 150+ words.")
    result = score_star(answer)
    print(f"\nSTAR self-check: {result['score']}/{result['max']}")
    for d in result["dims"]:
        print(f"  {'✅' if d['present'] else '❌'} {d['dimension']}: {d['check']}")
    notes = f"STAR self-check {result['score']}/{result['max']}."
    if ai_feedback and answer.strip():
        persona = _load_personas()["behavioral"]
        fb = _gemini_chat(persona["system"], [{"role": "user", "parts": [{
            "text": f"Question: {q['question']}\nCandidate answer:\n{answer}\n\n"
                    "Give feedback in the format: Scores (1-5), Strengths, Gaps, STAR tips."}]}])
        print(f"\n📋 AI FEEDBACK\n{fb}\n")
        notes += f"\nAI feedback:\n{fb}"
    report = _session_report("behavioral", q["id"], "completed", 1, 0,
                             datetime.now(), f"{result['score']}/{result['max']}", notes=notes)
    _save_session(report)
    print("\n" + _render_report(report))
    return report


def _pick_design(level: str | None = None) -> dict:
    data = json.loads((DATA / "system_design.json").read_text(encoding="utf-8"))
    prompts = data["prompts"]
    if level:
        prompts = [p for p in prompts if p["level"] == level]
        if not prompts:
            raise MockError(f"Unknown design level '{level}'.")
    return random.choice(prompts)


def design_session(level: str | None = None, ai_feedback: bool = False) -> dict:
    data = json.loads((DATA / "system_design.json").read_text(encoding="utf-8"))
    q = _pick_design(level)
    print(f"### System Design ({q['level']})\n\n**{q['prompt']}**\n")
    print("Strong answers follow this structure:")
    for i, step in enumerate(q["sample_structure"], 1):
        print(f"  {i}. {step}")
    print("\nRubric (what you're scored on):")
    for item in data["rubric"]:
        print(f"  • {item['dimension']} (weight {item['weight']}): {'; '.join(item['checks'])}")
    print("\nTalk through your design out loud (or type an outline, end with EOF).")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    outline = "\n".join(lines)
    notes = f"Prompt: {q['id']}. What 'good' looks like: {q['what_good_looks_like']}"
    if ai_feedback and outline.strip():
        persona = _load_personas()["ml"]
        fb = _gemini_chat(persona["system"], [{"role": "user", "parts": [{
            "text": f"Design prompt: {q['prompt']}\nCandidate outline:\n{outline}\n\n"
                    "Give feedback: Scores (1-5) for system thinking, trade-off reasoning, "
                    "communication; Strengths; Gaps; Study plan."}]}])
        print(f"\n📋 AI FEEDBACK\n{fb}\n")
        notes += f"\nAI feedback:\n{fb}"
    report = _session_report("design", q["id"], "completed", 1, 0,
                             datetime.now(), "self_reviewed", notes=notes)
    _save_session(report)
    print("\n" + _render_report(report))
    return report


# ---------------------------------------------------------------------------
# session reports
# ---------------------------------------------------------------------------

def _session_report(track: str, item: str, outcome: str, attempts: int,
                    hints_used: int, started: datetime, verdict: str | None,
                    notes: str = "") -> dict:
    duration = (datetime.now() - started).total_seconds()
    strengths, gaps = _strengths_gaps(track, outcome, verdict, attempts, hints_used)
    return {
        "track": track,
        "item": item,
        "outcome": outcome,
        "verdict": verdict,
        "attempts": attempts,
        "hints_used": hints_used,
        "duration_s": round(duration, 1),
        "at": started.isoformat(timespec="seconds"),
        "strengths": strengths,
        "gaps": gaps,
        "study_plan": _study_plan(track, gaps),
        "notes": notes[:2000],
    }


def _strengths_gaps(track: str, outcome: str, verdict: str | None,
                    attempts: int, hints_used: int) -> tuple[list[str], list[str]]:
    strengths, gaps = [], []
    if outcome == "solved" or verdict == "accepted":
        strengths.append("Solved the problem against all visible + hidden tests.")
        if attempts == 1:
            strengths.append("First-attempt solve — strong pattern recognition.")
        if hints_used == 0:
            strengths.append("No hints needed.")
    if outcome == "gave_up":
        gaps.append("Did not reach a working solution — revisit the problem's topic fundamentals.")
    if hints_used >= 2:
        gaps.append("Needed multiple hints — drill more problems in this topic before interview day.")
    if attempts and attempts > 3:
        gaps.append(f"Took {attempts} attempts — practice debugging systematically (reproduce, isolate, fix).")
    if track.startswith("ai_"):
        gaps.append("Review the AI feedback above for communication and approach gaps.")
    if not strengths and not gaps:
        strengths.append("Completed the session — reps matter more than any single outcome.")
    return strengths, gaps


def _study_plan(track: str, gaps: list[str]) -> list[dict]:
    plan = []
    if track == "coding":
        plan.append({"action": "Drill 3 more problems in the weak topic from the local bank",
                     "command": "python -m candid mock list --topic <topic>",
                     "concepts": []})
    for gap in gaps:
        low = gap.lower()
        for area, concepts in AREA_CONCEPTS.items():
            if area in low and concepts:
                plan.append({"action": f"Review deep-dive: {area}",
                             "command": "see candid/prep_concepts.py",
                             "concepts": concepts})
    plan.append({"action": "Re-run a full prep pack for your target role",
                 "command": "python -m candid prep --company X --role Y",
                 "concepts": []})
    return plan


def _save_session(report: dict) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SESSIONS_DIR / f"{stamp}_{report['track']}_{report['item']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _render_report(r: dict) -> str:
    lines = [
        "--- Session report ---",
        f"Track: {r['track']} · Item: {r['item']} · Outcome: {r['outcome']}",
        f"Attempts: {r['attempts']} · Hints: {r['hints_used']} · "
        f"Duration: {r['duration_s']:.0f}s",
    ]
    if r["strengths"]:
        lines += ["", "Strengths:"] + [f"  + {s}" for s in r["strengths"]]
    if r["gaps"]:
        lines += ["", "Gaps:"] + [f"  – {g}" for g in r["gaps"]]
    if r["study_plan"]:
        lines += ["", "Study plan:"]
        for s in r["study_plan"]:
            lines.append(f"  • {s['action']}")
            if s.get("command"):
                lines.append(f"    {s['command']}")
            if s.get("concepts"):
                lines.append(f"    deep-dives: {', '.join(s['concepts'])}")
    lines.append(f"\nSaved to {SESSIONS_DIR}/")
    return "\n".join(lines)
