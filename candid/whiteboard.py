"""Whiteboard practice mode: system-design whiteboard drills.

`mock design` gives you a prompt and a rubric; whiteboard mode turns that
into a full practice loop:

  drills      list/search the drill bank (10 seeded system-design drills)
  plan        timed phase plan for a drill (clarify / high-level / deep dive / wrap-up)
  narrate     describe-your-diagram flow: guided narration checkpoints that
              capture what you said about your diagram, section by section
  components  expected-component checklist with coverage scoring
  outline     reference outline for a drill (for post-session self-comparison)
  feedback    structured rubric feedback on a session (clarity, completeness,
              depth, communication) with strengths, gaps, and next steps
  drill       timed practice run with phase prompts; saves a session record
  followups   follow-up question bank per drill (+ quiz mode)
  history     session history, per-drill best scores, rubric trends
  rubric      print the evaluation rubric

Everything runs locally and deterministically. Session records (narration
notes, component checks, feedback) live under
``CANDID_DATA_DIR/whiteboard_sessions/``.

Usage:
    python -m candid whiteboard drills --difficulty hard
    python -m candid whiteboard plan --drill chat-system --minutes 45
    python -m candid whiteboard narrate --drill url-shortener
    python -m candid whiteboard feedback --session wb20260922-001 \\
        --clarity 4 --completeness 3 --depth 4 --communication 5
"""

from __future__ import annotations

import difflib
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path

from candid import config as C

DATA_FILE = Path(__file__).parent / "data" / "whiteboard_drills.json"

DIFFICULTIES = ["easy", "medium", "hard"]

DIMENSIONS = ["clarity", "completeness", "depth", "communication"]


class WhiteboardError(Exception):
    """Raised for whiteboard usage errors."""


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

_data_cache: dict | None = None


def _data() -> dict:
    global _data_cache
    if _data_cache is None:
        try:
            _data_cache = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WhiteboardError(f"Drill bank is unreadable ({DATA_FILE}): {exc}")
    return _data_cache


def _sessions_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    d = base / "whiteboard_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_drills(difficulty: str | None = None, topic: str | None = None) -> list[dict]:
    """List drills, optionally filtered by difficulty and/or topic substring."""
    drills = _data()["drills"]
    if difficulty:
        difficulty = difficulty.lower()
        if difficulty not in DIFFICULTIES:
            raise WhiteboardError(
                f"Unknown difficulty '{difficulty}'. Choose from: {', '.join(DIFFICULTIES)}."
            )
        drills = [d for d in drills if d["difficulty"] == difficulty]
    if topic:
        t = topic.lower()
        drills = [d for d in drills
                  if t in d["title"].lower()
                  or any(t in x.lower() for x in d.get("topics", []))]
    return drills


def get_drill(drill_id: str) -> dict:
    """Fetch one drill by id, with a close-match hint on typos."""
    drills = _data()["drills"]
    for d in drills:
        if d["id"] == drill_id:
            return d
    ids = [d["id"] for d in drills]
    hint = difflib.get_close_matches(drill_id, ids, n=1, cutoff=0.6)
    msg = f"Unknown drill '{drill_id}'."
    if hint:
        msg += f" Did you mean '{hint[0]}'?"
    msg += f" Run `python -m candid whiteboard drills` to list all {len(ids)}."
    raise WhiteboardError(msg)


def suggest_drill(difficulty: str | None = None, topic: str | None = None,
                  avoid: list[str] | None = None,
                  seed: int | None = None) -> dict:
    """Pick a drill at random, preferring ones not in `avoid` (recently done)."""
    pool = list_drills(difficulty=difficulty, topic=topic)
    if not pool:
        raise WhiteboardError("No drills match those filters. Loosen them and retry.")
    fresh = [d for d in pool if d["id"] not in set(avoid or [])]
    rng = random.Random(seed)
    return rng.choice(fresh or pool)


def rubric() -> list[dict]:
    return _data()["rubric"]


def narration_sections() -> list[dict]:
    return _data()["narration_sections"]


# ---------------------------------------------------------------------------
# 1. plan — timed phase plan
# ---------------------------------------------------------------------------

def plan_drill(drill_id: str, minutes: int = 45) -> dict:
    """Build a timed phase plan for a drill.

    Phase shares come from the drill bank; minutes are allocated proportionally
    and rounded so they always sum exactly to the requested total.
    """
    if minutes < 10:
        raise WhiteboardError("Plan at least 10 minutes for a drill.")
    drill = get_drill(drill_id)
    phases = _data()["phases"]
    shares = [p["share"] for p in phases]
    raw = [minutes * s for s in shares]
    alloc = [int(x) for x in raw]
    # hand the leftover minutes to the largest fractional parts so the sum is exact
    leftover = minutes - sum(alloc)
    order = sorted(range(len(phases)), key=lambda i: raw[i] - alloc[i], reverse=True)
    for i in order[:leftover]:
        alloc[i] += 1
    return {
        "drill_id": drill["id"],
        "drill_title": drill["title"],
        "total_minutes": minutes,
        "phases": [
            {"id": p["id"], "name": p["name"], "cue": p["cue"], "minutes": alloc[i]}
            for i, p in enumerate(phases)
        ],
    }


def render_plan(plan: dict) -> str:
    lines = [f"### {plan['drill_title']} — {plan['total_minutes']}-minute whiteboard plan\n"]
    for i, ph in enumerate(plan["phases"], 1):
        lines.append(f"{i}. {ph['name']} ({ph['minutes']} min)")
        lines.append(f"   {ph['cue']}")
    lines.append("\nTip: when a phase ends, move on. A finished board beats a perfect corner.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# session persistence
# ---------------------------------------------------------------------------

def _new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    existing = sorted(_sessions_dir().glob(f"wb{stamp}-*.json"))
    n = len(existing) + 1
    return f"wb{stamp}-{n:03d}"


def _save_session(session: dict) -> Path:
    p = _sessions_dir() / f"{session['id']}.json"
    p.write_text(json.dumps(session, indent=2), encoding="utf-8")
    return p


def load_session(session_id: str) -> dict:
    p = _sessions_dir() / f"{session_id}.json"
    if not p.exists():
        raise WhiteboardError(
            f"No session '{session_id}'. Run `python -m candid whiteboard history` to list sessions."
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WhiteboardError(f"Session file {p} is not valid JSON: {exc}") from exc


def _start_session(drill_id: str, kind: str) -> dict:
    drill = get_drill(drill_id)
    return {
        "id": _new_session_id(),
        "kind": kind,
        "drill_id": drill["id"],
        "drill_title": drill["title"],
        "started": datetime.now().isoformat(timespec="seconds"),
        "narration": {},
        "components_checked": [],
        "feedback": None,
    }


# ---------------------------------------------------------------------------
# 2. narrate — describe-your-diagram flow
# ---------------------------------------------------------------------------

def narrate(drill_id: str, notes: dict[str, str] | None = None,
            save: bool = True, echo: bool = True) -> dict:
    """Guided describe-your-diagram flow.

    Walks the five narration sections (requirements recap, components, data
    flow, failure & scale, tradeoffs). With ``notes`` given, each section's
    text is taken from the mapping (non-interactive, test-friendly); otherwise
    the candidate types each section, ending input with EOF.
    Returns the saved session record.
    """
    drill = get_drill(drill_id)
    sections = narration_sections()
    session = _start_session(drill_id, "narrate")
    if echo:
        print(f"### Describe your diagram: {drill['title']}\n")
        print(f"Prompt: {drill['prompt']}\n")
    captured: dict[str, str] = {}
    for sec in sections:
        if echo:
            print(f"--- {sec['title']} ---")
            print(f"{sec['cue']}")
            for tip in sec["tips"]:
                print(f"  tip: {tip}")
        if notes is not None:
            text = notes.get(sec["id"], "").strip()
        else:
            print("(type your narration, end with EOF)")
            lines: list[str] = []
            try:
                while True:
                    line = input()
                    if line.strip() == "EOF":
                        break
                    lines.append(line)
            except EOFError:
                pass
            text = "\n".join(lines).strip()
        captured[sec["id"]] = text
        if echo:
            words = len(text.split())
            print(f"  captured {words} words.\n")
    session["narration"] = captured
    empty = [s["title"] for s in sections if not captured[s["id"]]]
    session["narration_gaps"] = empty
    if save:
        _save_session(session)
        if echo:
            print(f"Session saved: {session['id']}")
            if empty:
                print("Sections left blank: " + ", ".join(empty))
    return session


def render_narration(session: dict) -> str:
    sections = {s["id"]: s["title"] for s in narration_sections()}
    lines = [f"### Narration — {session['drill_title']} ({session['id']})\n"]
    for sec_id, title in sections.items():
        lines.append(f"**{title}**")
        text = (session.get("narration") or {}).get(sec_id, "")
        lines.append(text if text.strip() else "_(blank)_")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. components — expected-component checklist
# ---------------------------------------------------------------------------

def component_checklist(drill_id: str) -> list[dict]:
    return get_drill(drill_id)["expected_components"]


def check_components(drill_id: str, checked: list[str],
                     session_id: str | None = None) -> dict:
    """Score component coverage: which expected boxes the candidate drew.

    Matching is case-insensitive and accepts unique prefixes, so
    ``--check cache`` matches "Cache". Unknown names raise WhiteboardError
    listing the valid components.
    """
    drill = get_drill(drill_id)
    expected = [c["name"] for c in drill["expected_components"]]
    lowered = {c["name"].lower(): c["name"] for c in drill["expected_components"]}
    resolved: list[str] = []
    unknown: list[str] = []
    for name in checked:
        key = name.strip().lower()
        if key in lowered:
            resolved.append(lowered[key])
        else:
            matches = [n for n in expected if n.lower().startswith(key)]
            if len(matches) == 1:
                resolved.append(matches[0])
            else:
                unknown.append(name)
    if unknown:
        raise WhiteboardError(
            f"Unknown component(s): {', '.join(unknown)}. "
            f"Expected one of: {', '.join(expected)}."
        )
    resolved = sorted(set(resolved))
    missed = [c for c in expected if c not in resolved]
    coverage = round(len(resolved) / len(expected) * 100) if expected else 100
    result = {
        "drill_id": drill["id"],
        "drill_title": drill["title"],
        "checked": resolved,
        "missed": missed,
        "coverage_pct": coverage,
    }
    if session_id:
        session = load_session(session_id)
        session["components_checked"] = resolved
        session["component_coverage_pct"] = coverage
        _save_session(session)
        result["session_id"] = session_id
    return result


def render_checklist(drill_id: str, checked: list[str] | None = None) -> str:
    drill = get_drill(drill_id)
    checked_set = set(checked or [])
    lines = [f"### Component checklist — {drill['title']}\n"]
    for c in drill["expected_components"]:
        mark = "[x]" if c["name"] in checked_set else "[ ]"
        lines.append(f"{mark} {c['name']}: {c['why']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. outline — reference outline for self-comparison
# ---------------------------------------------------------------------------

def reference_outline(drill_id: str) -> dict:
    drill = get_drill(drill_id)
    return {
        "drill_id": drill["id"],
        "drill_title": drill["title"],
        "prompt": drill["prompt"],
        "scale": drill.get("scale", ""),
        "functional": drill.get("functional", []),
        "non_functional": drill.get("non_functional", []),
        "api_sketch": drill.get("api_sketch", []),
        "data_model": drill.get("data_model", []),
        "components": [c["name"] for c in drill.get("expected_components", [])],
        "deep_dives": drill.get("deep_dives", []),
        "pitfalls": drill.get("pitfalls", []),
    }


def render_outline(outline: dict) -> str:
    lines = [f"### Reference outline — {outline['drill_title']}",
             f"_{outline['prompt']}_", ""]
    if outline["scale"]:
        lines += [f"Scale: {outline['scale']}", ""]
    for label, key in [("Functional requirements", "functional"),
                       ("Non-functional requirements", "non_functional"),
                       ("API sketch", "api_sketch"),
                       ("Data model", "data_model"),
                       ("Deep-dive topics", "deep_dives"),
                       ("Common pitfalls", "pitfalls")]:
        items = outline.get(key) or []
        if items:
            lines.append(f"**{label}**")
            lines.extend(f"  • {i}" for i in items)
            lines.append("")
    if outline["components"]:
        lines.append("**Expected components**")
        lines.extend(f"  • {c}" for c in outline["components"])
    lines.append("")
    lines.append("Compare against your board: which sections did you skip, and why?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. feedback — structured rubric feedback
# ---------------------------------------------------------------------------

_NEXT_STEPS = {
    "clarity": ("Open with a 60-second requirements recap before drawing anything, "
                "and narrate each arrow as you draw it."),
    "completeness": ("Run the 4-phase plan (clarify / high-level / deep dive / wrap-up) "
                     "with a timer so no section gets skipped."),
    "depth": ("Pick the single hardest component and go three levels deeper "
              "instead of covering everything shallowly."),
    "communication": ("Think out loud continuously: say what you are about to draw, "
                      "then draw it, then say what you drew."),
}

_VERDICTS = [
    (4.5, "whiteboard-ready"),
    (3.5, "solid"),
    (2.5, "developing"),
    (0.0, "needs work"),
]


def score_feedback(ratings: dict[str, int], notes: str = "") -> dict:
    """Score 1-5 ratings per rubric dimension into structured feedback.

    Returns the weighted score, per-dimension verdicts, strengths (dims >= 4),
    gaps (dims <= 2), and concrete next steps for each gap.
    """
    dims = {d["dimension"].lower(): d["weight"] for d in rubric()}
    for dim in DIMENSIONS:
        if dim not in ratings:
            raise WhiteboardError(f"Missing rating for '{dim}'. Rate all of: {', '.join(DIMENSIONS)}.")
        r = ratings[dim]
        if not isinstance(r, int) or not 1 <= r <= 5:
            raise WhiteboardError(f"Rating for '{dim}' must be an integer 1-5, got {r!r}.")
    if set(ratings) - set(DIMENSIONS):
        raise WhiteboardError(f"Unknown dimension(s): {sorted(set(ratings) - set(DIMENSIONS))}.")
    total_w = sum(dims[d] for d in DIMENSIONS)
    score = round(sum(ratings[d] * dims[d] for d in DIMENSIONS) / total_w, 1)

    def verdict(r: int) -> str:
        return "strong" if r >= 4 else ("solid" if r == 3 else "needs work")

    breakdown = {d: {"rating": ratings[d], "verdict": verdict(ratings[d]),
                     "weight": dims[d]} for d in DIMENSIONS}
    strengths = [d for d in DIMENSIONS if ratings[d] >= 4]
    gaps = [d for d in DIMENSIONS if ratings[d] <= 2]
    next_steps = [_NEXT_STEPS[d] for d in gaps]
    if not gaps:
        if all(ratings[d] >= 4 for d in DIMENSIONS):
            next_steps = ["Stretch: retry the drill one difficulty up with 10 fewer minutes, "
                          "or teach the design to someone else."]
        else:
            lowest = min(DIMENSIONS, key=lambda d: ratings[d])
            next_steps = [f"No weak dimensions. Consolidate: re-run the drill and turn "
                          f"'{lowest}' from solid into a strength."]
    overall = next(v for bound, v in _VERDICTS if score >= bound)
    return {
        "ratings": ratings,
        "score": score,
        "verdict": overall,
        "breakdown": breakdown,
        "strengths": strengths,
        "gaps": gaps,
        "next_steps": next_steps,
        "notes": notes.strip(),
    }


def attach_feedback(session_id: str, ratings: dict[str, int], notes: str = "") -> dict:
    """Attach structured feedback to a saved session."""
    session = load_session(session_id)
    feedback = score_feedback(ratings, notes)
    session["feedback"] = feedback
    _save_session(session)
    return session


def render_feedback(feedback: dict) -> str:
    lines = [f"### Whiteboard feedback — {feedback['score']}/5 ({feedback['verdict']})\n"]
    for dim in DIMENSIONS:
        b = feedback["breakdown"][dim]
        lines.append(f"  {dim:<13} {b['rating']}/5 — {b['verdict']} (weight {b['weight']})")
    if feedback["strengths"]:
        lines.append("\nStrengths: " + ", ".join(feedback["strengths"]))
    if feedback["gaps"]:
        lines.append("Gaps: " + ", ".join(feedback["gaps"]))
    lines.append("\nNext steps:")
    for i, step in enumerate(feedback["next_steps"], 1):
        lines.append(f"  {i}. {step}")
    if feedback["notes"]:
        lines.append(f"\nNotes: {feedback['notes']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. drill — timed practice run
# ---------------------------------------------------------------------------

def run_drill(drill_id: str, minutes: int = 45, wait: bool = True,
              echo: bool = True) -> dict:
    """Run a timed practice session: show the plan, step through phases.

    ``wait=False`` skips the press-Enter prompts (scripting/tests).
    Returns the saved session record.
    """
    plan = plan_drill(drill_id, minutes)
    drill = get_drill(drill_id)
    session = _start_session(drill_id, "timed")
    session["plan"] = plan
    if echo:
        print(f"### Timed drill: {drill['title']} ({minutes} min)\n")
        print(f"Prompt: {drill['prompt']}\n")
        print("Draw on a real board or paper. Talk out loud the whole time.\n")
    for i, ph in enumerate(plan["phases"], 1):
        if echo:
            print(f"--- Phase {i}/{len(plan['phases'])}: {ph['name']} ({ph['minutes']} min) ---")
            print(ph["cue"])
            if wait:
                try:
                    input("Press Enter when this phase ends... ")
                except EOFError:
                    pass
                print()
    if echo:
        print("Time. Put the marker down.")
        print("Next: `whiteboard narrate --drill {0}` to capture what you said, "
              "then `whiteboard feedback` once you have rated yourself.".format(drill_id))
    _save_session(session)
    if echo:
        print(f"Session saved: {session['id']}")
    return session


# ---------------------------------------------------------------------------
# 7. followups — follow-up question bank + quiz
# ---------------------------------------------------------------------------

def list_followups(drill_id: str) -> list[dict]:
    return get_drill(drill_id).get("followups", [])


def quiz_followup(drill_id: str, index: int | None = None,
                  answer: str | None = None,
                  seed: int | None = None, echo: bool = True) -> dict:
    """Ask one follow-up; capture the answer for the session notes.

    ``index`` picks a specific question (0-based); otherwise one is chosen at
    random. ``answer`` supplies the response non-interactively.
    """
    followups = list_followups(drill_id)
    if not followups:
        raise WhiteboardError(f"Drill '{drill_id}' has no follow-up questions.")
    if index is not None:
        if not 0 <= index < len(followups):
            raise WhiteboardError(
                f"Follow-up index {index} out of range (0-{len(followups) - 1}).")
        q = followups[index]
    else:
        q = random.Random(seed).choice(followups)
    if echo:
        print(f"### Follow-up ({get_drill(drill_id)['title']})\n\n{q['q']}\n")
        print(f"Why they ask: {q['why']}\n")
    if answer is None and echo:
        print("(answer out loud, or type it and end with EOF)")
        lines: list[str] = []
        try:
            while True:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line)
        except EOFError:
            pass
        answer = "\n".join(lines).strip()
    return {"drill_id": drill_id, "question": q["q"],
            "why": q["why"], "answer": (answer or "").strip()}


# ---------------------------------------------------------------------------
# 8. history — sessions, best scores, trends
# ---------------------------------------------------------------------------

def session_history(drill_id: str | None = None) -> list[dict]:
    """All saved sessions, newest first; optionally filtered to one drill."""
    sessions = []
    for p in _sessions_dir().glob("wb*.json"):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if drill_id and s.get("drill_id") != drill_id:
            continue
        sessions.append(s)
    sessions.sort(key=lambda s: s.get("started", ""), reverse=True)
    return sessions


def drill_stats() -> dict:
    """Per-drill aggregates: sessions, best/average score, rubric-dimension averages."""
    stats: dict[str, dict] = {}
    for s in session_history():
        d = stats.setdefault(s["drill_id"], {
            "drill_id": s["drill_id"],
            "drill_title": s.get("drill_title", s["drill_id"]),
            "sessions": 0, "scores": [],
            "dim_totals": {d: 0 for d in DIMENSIONS},
            "dim_counts": {d: 0 for d in DIMENSIONS},
        })
        d["sessions"] += 1
        fb = s.get("feedback")
        if fb:
            d["scores"].append(fb["score"])
            for dim in DIMENSIONS:
                d["dim_totals"][dim] += fb["ratings"][dim]
                d["dim_counts"][dim] += 1
    out = {}
    for drill_id, d in stats.items():
        dim_avgs = {dim: round(d["dim_totals"][dim] / d["dim_counts"][dim], 1)
                    for dim in DIMENSIONS if d["dim_counts"][dim]}
        out[drill_id] = {
            "drill_id": drill_id,
            "drill_title": d["drill_title"],
            "sessions": d["sessions"],
            "best_score": max(d["scores"]) if d["scores"] else None,
            "avg_score": round(sum(d["scores"]) / len(d["scores"]), 1) if d["scores"] else None,
            "dimension_avgs": dim_avgs,
        }
    return out


def render_history(sessions: list[dict], stats: dict) -> str:
    lines = ["### Whiteboard sessions\n"]
    if not sessions:
        return "No whiteboard sessions yet. Run `python -m candid whiteboard drill --drill url-shortener`."
    for s in sessions[:20]:
        fb = s.get("feedback")
        score = f"{fb['score']}/5 ({fb['verdict']})" if fb else "no feedback yet"
        lines.append(f"  {s['id']}  {s['drill_title']:<28} {s['kind']:<7} {score}")
    if stats:
        lines.append("\nPer-drill progress:")
        for drill_id in sorted(stats):
            st = stats[drill_id]
            best = f"best {st['best_score']}/5" if st["best_score"] is not None else "unscored"
            lines.append(f"  {st['drill_title']:<28} {st['sessions']} session(s), {best}")
            if st["dimension_avgs"]:
                dims = ", ".join(f"{k} {v}" for k, v in st["dimension_avgs"].items())
                lines.append(f"    avg dims: {dims}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI helpers (rendering)
# ---------------------------------------------------------------------------

def render_drills(drills: list[dict]) -> str:
    lines = [f"{'ID':<18}{'Title':<28}{'Difficulty':<10}Topics"]
    for d in drills:
        lines.append(f"{d['id']:<18}{d['title'][:27]:<28}{d['difficulty']:<10}"
                     f"{', '.join(d.get('topics', []))}")
    return "\n".join(lines)


def render_rubric() -> str:
    lines = ["### Whiteboard rubric (rate yourself 1-5 after each drill)\n"]
    for r in rubric():
        lines.append(f"**{r['dimension']}** (weight {r['weight']}): {r['good']}")
        for c in r["checks"]:
            lines.append(f"  • {c}")
        lines.append("")
    return "\n".join(lines)


def drills_json(drills: list[dict]) -> str:
    slim = [{k: d[k] for k in ("id", "title", "difficulty", "topics", "minutes")
             if k in d} for d in drills]
    return json.dumps(slim, indent=2)
