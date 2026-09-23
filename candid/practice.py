"""Live-coding practice harness: timed, distraction-free coding sessions.

Builds on the mock-interview judge (candid.mock_judge) with a practice-first
flow: a countdown timer with milestone warnings, an optional focus lock that
blocks hints and solutions while the clock runs, think-aloud prompts at
intervals (logged to the session transcript), phase-based time budgets
(plan / code / test / review), judge-backed attempts during the session,
a structured per-session review, and automatic pattern tags.

After the session the harness keeps you honest:
  - session history with tag / outcome / problem filters
  - aggregate stats (solve rate, avg duration, per-tag breakdown, streak)
  - a spaced-repetition revisit queue for problems you failed or solved weakly
  - named routines (e.g. "warmup", "interview-sim") that run several timed
    problems back to back

Everything except reading the problem bank runs locally and
deterministically. Sessions live under CANDID_DATA_DIR / practice_sessions/.

Usage:
    python -m candid practice start --problem max-subarray --minutes 45 --focus
    python -m candid practice list --tag topic:arrays --outcome solved
    python -m candid practice show --session p20260922_101500
    python -m candid practice stats
    python -m candid practice queue
    python -m candid practice tag --session p20260922_101500 --add needs-drill
    python -m candid practice routine run --name warmup
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from candid import config as C
from candid import mock as M
from candid import mock_judge as J


class PracticeError(Exception):
    """Raised for practice-harness usage errors."""


def _data_dir() -> Path:
    """Resolve the data dir at call time so CANDID_DATA_DIR overrides work."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _sessions_dir() -> Path:
    d = _data_dir() / "practice_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _data_dir() / "practice_index.json"


def _routines_path() -> Path:
    return _data_dir() / "practice_routines.json"


# ---------------------------------------------------------------------------
# clock (injectable for tests)
# ---------------------------------------------------------------------------

class Clock:
    """Wall-clock source. Subclass / replace in tests."""

    def now(self) -> float:
        return time.time()


class FakeClock(Clock):
    """Manual clock for deterministic tests."""

    def __init__(self, start: float = 0.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# timer with milestone warnings
# ---------------------------------------------------------------------------

MILESTONES = (0.25, 0.50, 0.75, 0.90)


class SessionTimer:
    """Countdown timer that reports newly-crossed milestone fractions."""

    def __init__(self, budget_s: float, clock: Clock | None = None):
        if budget_s <= 0:
            raise PracticeError("Session length must be positive.")
        self.budget_s = float(budget_s)
        self.clock = clock or Clock()
        self._start: float | None = None
        self._fired: set[float] = set()

    def start(self) -> None:
        self._start = self.clock.now()

    @property
    def started(self) -> bool:
        return self._start is not None

    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        return max(0.0, self.clock.now() - self._start)

    def remaining(self) -> float:
        return max(0.0, self.budget_s - self.elapsed())

    def expired(self) -> bool:
        return self.elapsed() >= self.budget_s

    def due_milestones(self) -> list[float]:
        """Milestone fractions crossed since the last call (each fires once)."""
        if self._start is None:
            return []
        frac = self.elapsed() / self.budget_s
        out = [m for m in MILESTONES if m not in self._fired and frac >= m]
        self._fired.update(out)
        return out

    def render_remaining(self) -> str:
        r = int(self.remaining())
        return f"{r // 60:02d}:{r % 60:02d} left"


# ---------------------------------------------------------------------------
# phases: plan / code / test / review
# ---------------------------------------------------------------------------

DEFAULT_PHASE_SPLIT: list[tuple[str, float]] = [
    ("plan", 0.10),
    ("code", 0.60),
    ("test", 0.20),
    ("review", 0.10),
]

PHASE_NAMES = [name for name, _ in DEFAULT_PHASE_SPLIT]


class PhasePlan:
    """Maps elapsed seconds to the current phase of the session."""

    def __init__(self, split: list[tuple[str, float]] | None = None):
        split = split or list(DEFAULT_PHASE_SPLIT)
        total = sum(f for _, f in split)
        if not split or abs(total - 1.0) > 1e-6:
            raise PracticeError("Phase fractions must sum to 1.0.")
        self.split = [(name, f / total) for name, f in split]

    def bounds(self, budget_s: float) -> list[tuple[str, float, float]]:
        """[(phase, start_s, end_s)] for a budget."""
        out, cursor = [], 0.0
        for name, frac in self.split:
            end = cursor + frac * budget_s
            out.append((name, cursor, end))
            cursor = end
        return out

    def current(self, elapsed_s: float, budget_s: float) -> str:
        for name, start, end in self.bounds(budget_s):
            if elapsed_s < end:
                return name
        return self.split[-1][0]

    def minutes_per_phase(self, budget_s: float) -> dict[str, float]:
        return {name: round((end - start) / 60, 1)
                for name, start, end in self.bounds(budget_s)}


def parse_phases(spec: str | None) -> list[tuple[str, float]] | None:
    """Parse 'plan:10,code:60,test:20,review:10' into a phase split."""
    if not spec:
        return None
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    split = []
    for p in parts:
        if ":" not in p:
            raise PracticeError(
                f"Bad phase spec '{p}'. Use name:percent, e.g. plan:10,code:60,test:20,review:10.")
        name, pct = p.split(":", 1)
        name = name.strip().lower()
        if name not in PHASE_NAMES:
            raise PracticeError(f"Unknown phase '{name}'. Choose from: {', '.join(PHASE_NAMES)}.")
        try:
            split.append((name, float(pct.strip()) / 100.0))
        except ValueError:
            raise PracticeError(f"Bad percent in phase spec '{p}'.") from None
    names = [n for n, _ in split]
    if sorted(names) != sorted(PHASE_NAMES):
        raise PracticeError(
            f"Phase spec must cover all phases: {', '.join(PHASE_NAMES)}.")
    return split


# ---------------------------------------------------------------------------
# think-aloud prompts
# ---------------------------------------------------------------------------

THINK_ALOUD_PROMPTS = [
    "Say it out loud: what is your current plan in one or two sentences?",
    "Think aloud: what are you unsure about right now?",
    "Narrate: what did your last attempt teach you about the problem?",
    "Think aloud: if you were explaining your approach to an interviewer, what would you say?",
    "Check in: are you still on your plan, or have you drifted? Say why.",
    "Think aloud: what is the trickiest edge case, and how are you handling it?",
]


def think_aloud_due(session: dict, interval_s: float) -> str | None:
    """Return the next think-aloud prompt if one is due, else None.

    Due when at least `interval_s` seconds passed since session start or the
    last think-aloud entry. Prompts cycle through THINK_ALOUD_PROMPTS.
    """
    if interval_s <= 0:
        return None
    entries = session.get("think_aloud", [])
    elapsed = session.get("_elapsed_s", 0.0)
    last_at = entries[-1]["at_s"] if entries else 0.0
    if elapsed - last_at >= interval_s:
        return THINK_ALOUD_PROMPTS[len(entries) % len(THINK_ALOUD_PROMPTS)]
    return None


# ---------------------------------------------------------------------------
# focus lock: what is blocked while the clock runs
# ---------------------------------------------------------------------------

def focus_allows(command: str, focus: bool, session_over: bool) -> tuple[bool, str]:
    """Whether `command` is allowed right now under focus mode."""
    if not focus or session_over:
        return True, ""
    if command in ("hint", "solution"):
        return False, (
            f"'{command}' is locked while focus mode is on - finish the session "
            "or run without --focus to use hints. (This is the point: no peeking.)")
    return True, ""


# ---------------------------------------------------------------------------
# session records
# ---------------------------------------------------------------------------

def _new_id() -> str:
    # Microsecond resolution: two sessions created within the same wall-clock
    # second still get distinct ids (session files and the index upsert by id,
    # so same-second ids would silently overwrite each other).
    return "p" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def new_session(problem: dict, minutes: float, focus: bool = True,
                think_every_s: float = 600.0,
                phases: list[tuple[str, float]] | None = None) -> dict:
    """Create a fresh session record (timer not started yet)."""
    if minutes <= 0:
        raise PracticeError("--minutes must be positive.")
    return {
        "id": _new_id(),
        "problem": {k: problem[k] for k in ("id", "title", "topic", "difficulty")},
        "minutes": minutes,
        "budget_s": minutes * 60.0,
        "focus": focus,
        "think_every_s": think_every_s,
        "phases": phases or list(DEFAULT_PHASE_SPLIT),
        "started_at": None,
        "ended_at": None,
        "outcome": None,          # solved | gave_up | timed_out | abandoned
        "final_verdict": None,
        "attempts": [],           # [{n, at_s, verdict, passed, total}]
        "hints_used": 0,
        "think_aloud": [],        # [{at_s, prompt, answer}]
        "transcript": [],         # event log lines
        "phase_log": [],          # [{phase, entered_at_s}]
        "tags": [],
        "review": None,
        "revisit": {"count": 0, "next_due": None},
        "duration_s": None,
        "_elapsed_s": 0.0,        # scratch: updated by the runner
    }


def log_event(session: dict, text: str) -> None:
    session["transcript"].append(f"[{session['_elapsed_s']:7.1f}s] {text}")


# ---------------------------------------------------------------------------
# judging inside a session
# ---------------------------------------------------------------------------

def judge_attempt(session: dict, problem: dict, code: str,
                  final: bool = False) -> dict:
    """Judge `code`; mid-session runs use visible tests only, the final run
    uses the full suite (visible + hidden). Records the attempt on the session."""
    target = problem if final else dict(problem, hidden_tests=[])
    result = J.judge(target, code)
    tests = result.get("tests", [])
    attempt = {
        "n": len(session["attempts"]) + 1,
        "at_s": round(session["_elapsed_s"], 1),
        "verdict": result["verdict"],
        "passed": sum(1 for t in tests if t.get("verdict") == "accepted"),
        "total": len(tests),
        "final": final,
    }
    session["attempts"].append(attempt)
    return result


# ---------------------------------------------------------------------------
# review: auto observations + reflection answers
# ---------------------------------------------------------------------------

REVIEW_QUESTIONS = [
    ("went_well", "What went well in this session?"),
    ("stuck", "Where did you get stuck, and what unblocked you (or didn't)?"),
    ("drill", "What pattern or technique will you drill because of this session?"),
    ("next_time", "What will you do differently in the next timed session?"),
]


def auto_observations(session: dict) -> list[str]:
    """Data-derived observations for the per-session review."""
    obs = []
    attempts = _coding_attempts(session)
    budget = session.get("budget_s", 0) or 1
    dur = session.get("duration_s") or 0
    outcome = session.get("outcome")
    if outcome == "solved":
        obs.append(f"Solved in {dur / 60:.1f} of {budget / 60:.0f} budgeted minutes.")
        if len(attempts) == 1:
            obs.append("First-attempt solve - strong pattern recognition under time pressure.")
    elif outcome == "timed_out":
        obs.append("Ran out the clock - the plan phase may need to be shorter or the approach simpler.")
    elif outcome == "gave_up":
        obs.append("Gave up before time expired - consider staying with the problem until the timer ends.")
    if len(attempts) > 3:
        obs.append(f"{len(attempts)} attempts - practice a systematic debug loop (reproduce, isolate, fix).")
    if session.get("hints_used", 0) >= 2:
        obs.append("Relied on multiple hints - drill this topic untimed before the next timed session.")
    if dur > budget:
        obs.append(f"Finished {(dur - budget) / 60:.1f} min over budget - tighten the plan/code split.")
    ta = session.get("think_aloud", [])
    if ta:
        answered = sum(1 for e in ta if e.get("answer", "").strip())
        obs.append(f"Think-aloud: answered {answered}/{len(ta)} prompts - "
                   + ("good narration habit." if answered == len(ta)
                      else "try answering every prompt out loud next time."))
    else:
        obs.append("No think-aloud entries - turn prompts on (--think-every) to practice narrating.")
    return obs


def build_review(session: dict, answers: dict[str, str]) -> dict:
    """Assemble the per-session review from auto observations + reflections."""
    return {
        "at": datetime.now().isoformat(timespec="seconds"),
        "observations": auto_observations(session),
        "answers": {key: answers.get(key, "").strip() for key, _ in REVIEW_QUESTIONS},
    }


def render_review(session: dict) -> str:
    r = session.get("review") or {}
    lines = ["--- Session review ---"]
    for o in r.get("observations", []):
        lines.append(f"  - {o}")
    if r.get("answers"):
        lines.append("")
        for key, q in REVIEW_QUESTIONS:
            a = r["answers"].get(key, "")
            lines.append(f"Q: {q}")
            lines.append(f"A: {a or '(skipped)'}")
            lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# pattern tags
# ---------------------------------------------------------------------------

TAG_RE = re.compile(r"^[a-z0-9][a-z0-9:\-]{0,39}$")


def normalize_tag(tag: str) -> str:
    t = tag.strip().lower().replace(" ", "-").replace("_", "-")
    t = re.sub(r"[^a-z0-9:\-]", "", t).strip("-").strip(":")
    if not TAG_RE.match(t):
        raise PracticeError(
            f"Bad tag '{tag}'. Use lowercase letters, digits, hyphens and "
            "colons (max 40 chars).")
    return t


def auto_tags(problem: dict) -> list[str]:
    """Problem-derived tags: topic and difficulty."""
    return [f"topic:{problem.get('topic', '?')}", f"diff:{problem.get('difficulty', '?')}"]


def _coding_attempts(session: dict) -> list[dict]:
    """Attempts where the user actually submitted code (excludes the final
    verification run, which re-judges the last submission)."""
    return [a for a in session.get("attempts", []) if not a.get("final")]


def behavior_tags(session: dict) -> list[str]:
    """Behavioral pattern tags derived from how the session went."""
    tags = []
    attempts = _coding_attempts(session)
    outcome = session.get("outcome")
    budget = session.get("budget_s", 0) or 1
    dur = session.get("duration_s") or 0
    if outcome == "solved" and len(attempts) == 1 and not session.get("hints_used"):
        tags.append("first-try-solve")
    if session.get("hints_used", 0) >= 2:
        tags.append("hint-dependent")
    if len(attempts) > 3:
        tags.append("debug-heavy")
    if outcome == "timed_out" or dur > budget:
        tags.append("time-pressure")
    if outcome == "gave_up":
        tags.append("gave-up-early")
    if session.get("review"):
        tags.append("reviewed")
    ta = session.get("think_aloud", [])
    if ta and all(e.get("answer", "").strip() for e in ta):
        tags.append("narrated-well")
    return tags


def finalize_tags(session: dict, problem: dict, extra: list[str] | None = None) -> list[str]:
    tags = auto_tags(problem) + behavior_tags(session)
    for t in extra or []:
        tags.append(normalize_tag(t))
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def add_tags(session: dict, tags: list[str]) -> list[str]:
    for t in tags:
        nt = normalize_tag(t)
        if nt not in session["tags"]:
            session["tags"].append(nt)
    return session["tags"]


def remove_tags(session: dict, tags: list[str]) -> list[str]:
    drop = {normalize_tag(t) for t in tags}
    session["tags"] = [t for t in session["tags"] if t not in drop]
    return session["tags"]


# ---------------------------------------------------------------------------
# persistence: sessions + index
# ---------------------------------------------------------------------------

def _strip_scratch(session: dict) -> dict:
    return {k: v for k, v in session.items() if not k.startswith("_")}


def save_session(session: dict) -> Path:
    """Write the session JSON and refresh the index entry."""
    if not session.get("ended_at"):
        raise PracticeError("Cannot save a session that has not ended.")
    clean = _strip_scratch(session)
    path = _sessions_dir() / f"{session['id']}.json"
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    _upsert_index(session)
    return path


def _read_index() -> list[dict]:
    p = _index_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _write_index(entries: list[dict]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _upsert_index(session: dict) -> None:
    entry = {
        "id": session["id"],
        "problem_id": session["problem"]["id"],
        "title": session["problem"]["title"],
        "topic": session["problem"]["topic"],
        "difficulty": session["problem"]["difficulty"],
        "outcome": session.get("outcome"),
        "final_verdict": session.get("final_verdict"),
        "duration_s": session.get("duration_s"),
        "attempts": len(session.get("attempts", [])),
        "hints_used": session.get("hints_used", 0),
        "at": session.get("started_at"),
        "tags": session.get("tags", []),
        "revisit_next_due": (session.get("revisit") or {}).get("next_due"),
        "revisit_count": (session.get("revisit") or {}).get("count", 0),
    }
    entries = [e for e in _read_index() if e.get("id") != session["id"]]
    entries.append(entry)
    entries.sort(key=lambda e: e.get("at") or "", reverse=True)
    _write_index(entries)


def load_session(session_id: str) -> dict:
    p = _sessions_dir() / f"{session_id}.json"
    if not p.exists():
        known = [e["id"] for e in _read_index()[:10]]
        hint = f" Recent: {', '.join(known)}." if known else ""
        raise PracticeError(f"Unknown session '{session_id}'.{hint}")
    return json.loads(p.read_text(encoding="utf-8"))


def list_sessions(tag: str | None = None, outcome: str | None = None,
                  problem: str | None = None, limit: int = 20) -> list[dict]:
    entries = _read_index()
    if tag:
        entries = [e for e in entries if tag in e.get("tags", [])]
    if outcome:
        if outcome not in ("solved", "gave_up", "timed_out", "abandoned"):
            raise PracticeError(f"Unknown outcome '{outcome}'.")
        entries = [e for e in entries if e.get("outcome") == outcome]
    if problem:
        entries = [e for e in entries if e.get("problem_id") == problem]
    return entries[:max(1, limit)]


def render_session_list(entries: list[dict]) -> str:
    if not entries:
        return "No practice sessions yet. Start one with: python -m candid practice start --help"
    lines = [f"{'ID':<20}{'Problem':<28}{'Outcome':<11}{'Time':<8}Tags"]
    for e in entries:
        dur = e.get("duration_s") or 0
        tags = ",".join(e.get("tags", [])[:3])
        lines.append(f"{e['id']:<20}{e.get('title','')[:27]:<28}"
                     f"{(e.get('outcome') or '?'):<11}{dur / 60:>5.1f}m  {tags}")
    return "\n".join(lines)


def render_session_detail(session: dict) -> str:
    p = session["problem"]
    lines = [
        f"### Practice session {session['id']}",
        f"Problem: {p['title']} [{p['topic']} - {p['difficulty']}]",
        f"Outcome: {session.get('outcome')} "
        f"(final verdict: {session.get('final_verdict') or 'n/a'})",
        f"Budget: {session['minutes']} min - "
        f"took {(session.get('duration_s') or 0) / 60:.1f} min",
        f"Attempts: {len(session.get('attempts', []))} - "
        f"hints: {session.get('hints_used', 0)} - "
        f"focus: {'on' if session.get('focus') else 'off'}",
        f"Tags: {', '.join(session.get('tags', [])) or '(none)'}",
    ]
    ta = session.get("think_aloud", [])
    if ta:
        lines += ["", "Think-aloud:"]
        for e in ta:
            lines.append(f"  [{e['at_s']:.0f}s] {e['prompt']}")
            lines.append(f"    -> {e.get('answer') or '(no answer recorded)'}")
    ev = session.get("transcript", [])
    if ev:
        lines += ["", "Event log:"]
        lines += [f"  {line}" for line in ev[-12:]]
    if session.get("review"):
        lines += ["", render_review(session)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def compute_stats(entries: list[dict] | None = None) -> dict:
    """Aggregate stats over practice sessions."""
    entries = _read_index() if entries is None else entries
    done = [e for e in entries if e.get("outcome") != "abandoned"]
    solved = [e for e in done if e.get("outcome") == "solved"]
    durations = [e["duration_s"] for e in done if e.get("duration_s")]
    by_tag: dict[str, dict] = {}
    for e in done:
        for t in e.get("tags", []):
            b = by_tag.setdefault(t, {"sessions": 0, "solved": 0})
            b["sessions"] += 1
            if e.get("outcome") == "solved":
                b["solved"] += 1
    for b in by_tag.values():
        b["solve_rate"] = round(b["solved"] / b["sessions"], 2) if b["sessions"] else 0.0
    by_problem: dict[str, dict] = {}
    for e in done:
        b = by_problem.setdefault(e.get("problem_id", "?"),
                                  {"title": e.get("title", "?"), "sessions": 0, "solved": 0})
        b["sessions"] += 1
        if e.get("outcome") == "solved":
            b["solved"] += 1
    return {
        "total_sessions": len(done),
        "solved": len(solved),
        "solve_rate": round(len(solved) / len(done), 2) if done else 0.0,
        "avg_duration_min": round(sum(durations) / len(durations) / 60, 1) if durations else 0.0,
        "streak_days": _streak_days(done),
        "by_tag": by_tag,
        "by_problem": by_problem,
    }


def _streak_days(entries: list[dict]) -> int:
    """Consecutive days with at least one finished session, ending at the
    most recent session day (or today if there is a session today)."""
    days = set()
    for e in entries:
        at = e.get("at")
        if at:
            try:
                days.add(datetime.fromisoformat(at).date().isoformat())
            except ValueError:
                continue
    if not days:
        return 0
    latest = max(days)
    streak, day = 0, datetime.fromisoformat(latest).date()
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def render_stats(stats: dict) -> str:
    lines = [
        "--- Practice stats ---",
        f"Sessions: {stats['total_sessions']} - solved: {stats['solved']} "
        f"({stats['solve_rate']:.0%}) - avg: {stats['avg_duration_min']} min",
        f"Current streak: {stats['streak_days']} day(s)",
    ]
    if stats["by_tag"]:
        lines.append("\nBy tag (sessions, solve rate):")
        for tag, b in sorted(stats["by_tag"].items(),
                             key=lambda kv: kv[1]["sessions"], reverse=True)[:12]:
            lines.append(f"  {tag:<22} {b['sessions']:>3}  {b['solve_rate']:.0%}")
    if stats["by_problem"]:
        lines.append("\nBy problem:")
        for pid, b in sorted(stats["by_problem"].items(),
                             key=lambda kv: kv[1]["sessions"], reverse=True)[:12]:
            lines.append(f"  {pid:<24} {b['sessions']:>2}x  solved {b['solved']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# revisit queue: spaced repetition for failed / weak sessions
# ---------------------------------------------------------------------------

REVISIT_INTERVALS_DAYS = [1, 3, 7, 14, 30]


def needs_revisit(session: dict) -> bool:
    """True when the session outcome (or weakness) warrants a revisit."""
    if session.get("outcome") in ("gave_up", "timed_out"):
        return True
    if session.get("outcome") == "solved":
        if session.get("hints_used", 0) >= 2 or len(_coding_attempts(session)) > 3:
            return True
    return False


def revisit_reason(session: dict) -> str:
    outcome = session.get("outcome")
    if outcome == "gave_up":
        return "gave up - retry the full problem"
    if outcome == "timed_out":
        return "timed out - retry with a tighter plan"
    if session.get("hints_used", 0) >= 2:
        return "solved but hint-dependent - retry clean"
    if len(_coding_attempts(session)) > 3:
        return "solved but debug-heavy - retry for fluency"
    return "scheduled revisit"


def schedule_revisit(session: dict, now: datetime | None = None) -> str | None:
    """Set next_due from the SM-2-lite ladder. Returns the ISO due date or None."""
    if not needs_revisit(session):
        session["revisit"] = {"count": 0, "next_due": None}
        return None
    now = now or datetime.now()
    count = (session.get("revisit") or {}).get("count", 0)
    days = REVISIT_INTERVALS_DAYS[min(count, len(REVISIT_INTERVALS_DAYS) - 1)]
    due = (now + timedelta(days=days)).isoformat(timespec="seconds")
    session["revisit"] = {"count": count, "next_due": due}
    return due


def record_revisit(session: dict, outcome: str,
                   now: datetime | None = None) -> str | None:
    """After re-attempting a queued problem, advance or retire the schedule."""
    rev = session.setdefault("revisit", {"count": 0, "next_due": None})
    if outcome == "solved" and session.get("hints_used", 0) < 2 \
            and len(_coding_attempts(session)) <= 3:
        rev["count"] = 0
        rev["next_due"] = None
        return None
    rev["count"] = rev.get("count", 0) + 1
    now = now or datetime.now()
    days = REVISIT_INTERVALS_DAYS[min(rev["count"], len(REVISIT_INTERVALS_DAYS) - 1)]
    rev["next_due"] = (now + timedelta(days=days)).isoformat(timespec="seconds")
    return rev["next_due"]


def due_queue(now: datetime | None = None) -> list[dict]:
    """Queued revisits whose due date has passed, most overdue first."""
    now = now or datetime.now()
    out = []
    for e in _read_index():
        due = e.get("revisit_next_due")
        if not due:
            continue
        try:
            due_dt = datetime.fromisoformat(due)
        except ValueError:
            continue
        if due_dt <= now:
            out.append({
                "session_id": e["id"],
                "problem_id": e.get("problem_id"),
                "title": e.get("title"),
                "due": due,
                "overdue_days": (now - due_dt).days,
                "revisits": e.get("revisit_count", 0),
            })
    out.sort(key=lambda q: q["overdue_days"], reverse=True)
    return out


def render_queue(queue: list[dict]) -> str:
    if not queue:
        return ("Revisit queue is clear. Failed or weak sessions land here "
                "automatically - keep practicing and they will show up.")
    lines = ["--- Revisit queue (spaced repetition) ---"]
    for q in queue:
        od = q["overdue_days"]
        when = f"{od}d overdue" if od > 0 else "due today"
        lines.append(f"  {q['problem_id']:<24} {when:<12} "
                     f"(from session {q['session_id']}, revisit #{q['revisits'] + 1})")
    lines.append("\nRe-attempt with: python -m candid practice start --problem <id>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# routines: named multi-problem practice plans
# ---------------------------------------------------------------------------

BUILTIN_ROUTINES: dict[str, list[dict]] = {
    "warmup": [
        {"problem": None, "difficulty": "easy", "minutes": 20,
         "note": "one easy problem to get the fingers moving"},
    ],
    "interview-sim": [
        {"problem": None, "difficulty": "medium", "minutes": 45,
         "note": "round 1 - medium, full interview pacing"},
        {"problem": None, "difficulty": "medium", "minutes": 45,
         "note": "round 2 - medium, full interview pacing"},
    ],
    "dp-drill": [
        {"problem": None, "difficulty": "easy", "minutes": 25, "topic": "dp",
         "note": "dp warmup"},
        {"problem": None, "difficulty": "medium", "minutes": 40, "topic": "dp",
         "note": "dp stretch"},
    ],
}


def _read_routines() -> dict:
    p = _routines_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _write_routines(routines: dict) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _routines_path().write_text(json.dumps(routines, indent=2), encoding="utf-8")


def list_routines() -> dict[str, list[dict]]:
    saved = _read_routines()
    merged = dict(BUILTIN_ROUTINES)
    merged.update(saved)
    return merged


def get_routine(name: str) -> list[dict]:
    routines = list_routines()
    if name not in routines:
        raise PracticeError(
            f"Unknown routine '{name}'. Known: {', '.join(sorted(routines))}.")
    return routines[name]


def validate_routine_steps(steps: list[dict]) -> list[dict]:
    """Normalize routine steps; each needs a problem id or pickable filters."""
    out = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise PracticeError(f"Routine step {i + 1} must be an object.")
        minutes = s.get("minutes", 30)
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            raise PracticeError(f"Routine step {i + 1}: bad minutes '{s.get('minutes')}'.")
        if minutes <= 0:
            raise PracticeError(f"Routine step {i + 1}: minutes must be positive.")
        step = {"problem": s.get("problem"), "topic": s.get("topic"),
                "difficulty": s.get("difficulty"), "minutes": minutes,
                "note": s.get("note", "")}
        if not step["problem"] and not (step["topic"] or step["difficulty"]):
            raise PracticeError(
                f"Routine step {i + 1}: give a problem id or a topic/difficulty to pick from.")
        if step["problem"]:
            M.get_problem(step["problem"])  # validates the id exists
        out.append(step)
    if not out:
        raise PracticeError("A routine needs at least one step.")
    return out


def save_routine(name: str, steps: list[dict]) -> str:
    name = normalize_tag(name)
    if name in BUILTIN_ROUTINES:
        raise PracticeError(f"'{name}' is a built-in routine - pick another name.")
    steps = validate_routine_steps(steps)
    routines = _read_routines()
    routines[name] = steps
    _write_routines(routines)
    return name


def delete_routine(name: str) -> None:
    routines = _read_routines()
    if name not in routines:
        raise PracticeError(f"No saved routine '{name}'.")
    del routines[name]
    _write_routines(routines)


def parse_steps_spec(spec: str) -> list[dict]:
    """Parse 'max-subarray:20,climbing-stairs:25' into routine steps."""
    steps = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise PracticeError(
                f"Bad step '{part}'. Use problem:minutes, e.g. max-subarray:20.")
        pid, mins = part.split(":", 1)
        try:
            minutes = float(mins)
        except ValueError:
            raise PracticeError(f"Bad minutes in step '{part}'.") from None
        steps.append({"problem": pid.strip(), "minutes": minutes})
    return steps


def render_routines(routines: dict[str, list[dict]]) -> str:
    lines = ["--- Practice routines ---"]
    for name in sorted(routines):
        builtin = " (built-in)" if name in BUILTIN_ROUTINES else ""
        lines.append(f"\n{name}{builtin}:")
        for i, s in enumerate(routines[name], 1):
            what = s.get("problem") or (
                f"pick {s.get('difficulty') or 'any'}"
                f"{'/' + s['topic'] if s.get('topic') else ''}")
            note = f" - {s['note']}" if s.get("note") else ""
            lines.append(f"  {i}. {what} - {s['minutes']:g} min{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# finishing a session
# ---------------------------------------------------------------------------

def finalize_session(session: dict, problem: dict, outcome: str,
                     final_code: str | None = None,
                     extra_tags: list[str] | None = None) -> dict:
    """Judge the final code (if any), tag, schedule a revisit, and save."""
    timer_note = ""
    if final_code and final_code.strip():
        result = judge_attempt(session, problem, final_code, final=True)
        session["final_verdict"] = result["verdict"]
    elif outcome == "solved":
        raise PracticeError("Outcome 'solved' needs final code to judge.")
    session["ended_at"] = datetime.now().isoformat(timespec="seconds")
    session["outcome"] = outcome
    session["duration_s"] = round(session["_elapsed_s"], 1)
    session["tags"] = finalize_tags(session, problem, extra_tags)
    due = schedule_revisit(session)
    if due:
        timer_note = f"Revisit scheduled: {due[:10]} ({revisit_reason(session)})."
    save_session(session)
    return {"due": due, "note": timer_note}


def _collect_review_answers(input_fn, print_fn) -> dict[str, str]:
    print_fn("\n--- Session review: 4 quick reflections (Enter to skip) ---")
    answers = {}
    for key, question in REVIEW_QUESTIONS:
        print_fn(f"\nQ: {question}")
        try:
            answers[key] = input_fn("> ").strip()
        except EOFError:
            answers[key] = ""
    return answers


def _print_phase_banner(print_fn, phase: str, bounds: dict[str, float]) -> None:
    print_fn(f"\n--- phase: {phase.upper()} (~{bounds[phase]:.0f} min) ---")


# ---------------------------------------------------------------------------
# interactive timed session
# ---------------------------------------------------------------------------

def run_session(problem_id: str | None = None, topic: str | None = None,
                difficulty: str | None = None, minutes: float = 45.0,
                focus: bool = True, think_every_s: float = 600.0,
                phases: list[tuple[str, float]] | None = None,
                input_fn=input, print_fn=print, clock: Clock | None = None,
                seed: int | None = None, skip_review: bool = False,
                extra_tags: list[str] | None = None) -> dict:
    """Run one timed practice session. Returns the saved session dict."""
    clock = clock or Clock()
    problem = M.get_problem(problem_id) if problem_id else M.pick_problem(
        topic, difficulty, seed)
    plan = PhasePlan(phases)
    session = new_session(problem, minutes, focus, think_every_s, plan.split)
    timer = SessionTimer(session["budget_s"], clock)
    bounds = plan.minutes_per_phase(session["budget_s"])

    if focus:
        print_fn("\n" * 2 + "=" * 60)
        print_fn("FOCUS MODE - hints and solutions are locked until the session ends.")
        print_fn("=" * 60)
    print_fn(f"\n### {problem['title']}  [{problem['topic']} - {problem['difficulty']}]")
    print_fn(f"\n{problem['statement']}\n")
    print_fn(f"Write: `{problem['function']}`\n")
    for t in problem.get("visible_tests", []):
        print_fn(f"  example: {t['args']} -> {t['expected']}")
    print_fn(f"\nBudget: {minutes:g} min | phases: "
             + ", ".join(f"{n} ~{bounds[n]:.0f}m" for n, _ in plan.split))
    print_fn("Commands: run | done | hint | solution | think | time | quit")
    if think_every_s > 0:
        print_fn(f"Think-aloud prompts every {think_every_s / 60:g} min - answer out loud, "
                 "then type a one-line note.")

    timer.start()
    session["started_at"] = datetime.now().isoformat(timespec="seconds")
    current_phase = plan.current(0.0, session["budget_s"])
    session["phase_log"].append({"phase": current_phase, "entered_at_s": 0.0})
    _print_phase_banner(print_fn, current_phase, bounds)
    last_code: str | None = None

    def sync(silent: bool = False) -> str:
        """Update elapsed, fire milestones / phase changes / think-aloud."""
        session["_elapsed_s"] = timer.elapsed()
        if timer.expired():
            return "expired"
        for m in timer.due_milestones():
            print_fn(f"\n[TIMER] {int(m * 100)}% of your time is gone - {timer.render_remaining()}.")
        phase = plan.current(session["_elapsed_s"], session["budget_s"])
        nonlocal current_phase
        if phase != current_phase:
            current_phase = phase
            session["phase_log"].append(
                {"phase": phase, "entered_at_s": round(session["_elapsed_s"], 1)})
            _print_phase_banner(print_fn, phase, bounds)
        prompt = think_aloud_due(session, think_every_s)
        if prompt and not silent:
            print_fn(f"\n[THINK ALOUD] {prompt}")
            try:
                answer = input_fn("note> ").strip()
            except EOFError:
                answer = ""
            session["think_aloud"].append(
                {"at_s": round(session["_elapsed_s"], 1),
                 "prompt": prompt, "answer": answer})
            log_event(session, "think-aloud answered" if answer else "think-aloud skipped")
        return "ok"

    def read_code() -> str:
        print_fn("Paste your solution (define the required function). End with a line 'EOF'.")
        lines: list[str] = []
        try:
            while True:
                line = input_fn()
                if line.strip() == "EOF":
                    break
                lines.append(line)
        except EOFError:
            pass
        return "\n".join(lines)

    outcome: str | None = None
    while outcome is None:
        state = sync()
        if state == "expired":
            print_fn("\n[TIMER] TIME'S UP - finalizing with your last submitted code.")
            log_event(session, "timer expired")
            outcome = "timed_out"
            break
        try:
            cmd = input_fn("\n> ").strip().lower()
        except EOFError:
            cmd = "quit"
        if cmd in ("quit", "exit"):
            print_fn("Session abandoned - nothing saved.")
            session["outcome"] = "abandoned"
            return session
        elif cmd == "time":
            print_fn(f"[TIMER] {timer.render_remaining()} - phase: {current_phase}.")
        elif cmd == "think":
            print_fn(f"[THINK ALOUD] {THINK_ALOUD_PROMPTS[len(session['think_aloud']) % len(THINK_ALOUD_PROMPTS)]}")
            try:
                answer = input_fn("note> ").strip()
            except EOFError:
                answer = ""
            session["think_aloud"].append(
                {"at_s": round(session["_elapsed_s"], 1),
                 "prompt": "manual think-aloud", "answer": answer})
        elif cmd in ("hint", "solution"):
            ok, reason = focus_allows(cmd, focus, False)
            if not ok:
                print_fn(reason)
                log_event(session, f"blocked {cmd} (focus lock)")
                continue
            if cmd == "hint":
                hints = problem.get("hints", [])
                if session["hints_used"] < len(hints):
                    print_fn(f"\nHint {session['hints_used'] + 1}: {hints[session['hints_used']]}\n")
                    session["hints_used"] += 1
                    log_event(session, "hint used")
                else:
                    print_fn("No more hints.")
            else:
                print_fn("\n--- Reference solution ---\n")
                print_fn(problem["reference_solution"])
                print_fn(f"\nComplexity: {problem['complexity']}\n")
                log_event(session, "solution revealed - session marked gave_up")
                outcome = "gave_up"
        elif cmd == "run":
            code = read_code()
            if not code.strip():
                print_fn("Empty - nothing to judge.")
                continue
            last_code = code
            print_fn("\nJudging against visible tests...\n")
            result = judge_attempt(session, problem, code, final=False)
            tests = result["tests"]
            passed = sum(1 for t in tests if t.get("verdict") == "accepted")
            print_fn(f"{result['verdict'].upper()} - {passed}/{len(tests)} visible tests passed.")
            for line in J.failing_details(result):
                print_fn(line)
            log_event(session, f"attempt {len(session['attempts'])}: {result['verdict']} "
                               f"({passed}/{len(tests)} visible)")
            if result["verdict"] == "accepted":
                print_fn("All visible tests pass. Type 'done' to run the full suite, "
                         "or keep refining.")
        elif cmd == "done":
            if not last_code:
                print_fn("No code submitted yet - use 'run' first, or 'quit' to abandon.")
                continue
            outcome = "solved"
        else:
            print_fn("Unknown command. Try: run | done | hint | solution | think | time | quit")

    session["_elapsed_s"] = timer.elapsed()
    final = finalize_session(session, problem, outcome,
                             final_code=last_code if outcome != "abandoned" else None,
                             extra_tags=extra_tags)
    print_fn(f"\nOutcome: {outcome} - final verdict: {session.get('final_verdict') or 'n/a'} - "
             f"{session['duration_s'] / 60:.1f} min used.")
    if final["note"]:
        print_fn(final["note"])
    print_fn(f"Tags: {', '.join(session['tags'])}")

    if not skip_review:
        answers = _collect_review_answers(input_fn, print_fn)
        session["review"] = build_review(session, answers)
        # re-save with review attached (tags gain "reviewed")
        session["tags"] = finalize_tags(session, problem, extra_tags)
        save_session(session)
        print_fn("\n" + render_review(session))
    print_fn(f"\nSaved to {_sessions_dir()}/")
    return session


def run_routine(name: str, focus: bool = True, think_every_s: float = 600.0,
                input_fn=input, print_fn=print, clock: Clock | None = None,
                skip_review: bool = False) -> list[dict]:
    """Run every step of a named routine back to back. Returns session dicts."""
    steps = get_routine(name)
    print_fn(f"\n### Routine: {name} ({len(steps)} steps)")
    sessions = []
    used: set[str] = set()
    for i, step in enumerate(steps, 1):
        print_fn(f"\n{'=' * 60}\nStep {i}/{len(steps)}: "
                 f"{step.get('note') or step.get('problem') or 'pick a problem'}")
        pid = step.get("problem")
        if not pid:
            pool = [p for p in M.list_problems(step.get("topic"), step.get("difficulty"))
                    if p["id"] not in used]
            if not pool:
                raise PracticeError("Routine ran out of fresh problems to pick.")
            import random
            pid = random.choice(pool)["id"]
        used.add(pid)
        sessions.append(run_session(problem_id=pid, minutes=step["minutes"],
                                    focus=focus, think_every_s=think_every_s,
                                    input_fn=input_fn, print_fn=print_fn,
                                    clock=clock, skip_review=skip_review))
        if i < len(steps):
            print_fn("\n--- break: stretch, water, breathe. Press Enter for the next step. ---")
            try:
                input_fn()
            except EOFError:
                pass
    solved = sum(1 for s in sessions if s.get("outcome") == "solved")
    print_fn(f"\nRoutine '{name}' done: {solved}/{len(sessions)} solved.")
    return sessions
