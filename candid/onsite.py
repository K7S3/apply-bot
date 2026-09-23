"""Onsite day planner: build the interview day, then run it well.

Ten pieces, one command group:

1.  Schedule builder  (`onsite plan`, `onsite add-round`) — add rounds with
    start time, kind, duration, interviewer, and location. Overlaps are
    rejected; back-to-back rounds are fine.
2.  Printable timeline (`onsite timeline`) — the day rendered with computed
    end times, breaks between rounds, and flags for tight gaps.
3.  Logistics checklist (`onsite checklist`, `onsite check`) — generated from
    the day's mode (onsite / virtual / hybrid); check items off as you go.
4.  Per-round prep reminders (`onsite prep`) — what to review before each
    round, keyed off the round kind.
5.  Energy management (`onsite energy`) — sleep target, meal windows, real
    breaks vs back-to-back stretches, caffeine cutoff, hydration.
6.  Morning-of timeline (`onsite morning`) — work backwards from the first
    round: wake-up, leave-by (commute + buffer), arrival.
7.  Questions to ask (`onsite questions`) — a question bank per round kind.
8.  Packing support — folded into the logistics checklist (documents, tech,
    comfort categories).
9.  Per-round notes (`onsite notes`) — capture impressions while the day is
    fresh, per round or for the whole day.
10. Day summary (`onsite summary`) — export the day (timeline, notes,
    checklist state, follow-up reminders) to Markdown.

Stored as JSON at candid_data/onsite.json (git-ignored). Everything is
deterministic and offline: no clocks, no network, no invented data — every
time shown is computed from the schedule you entered.
"""

from __future__ import annotations

import json
import shlex
from datetime import date, timedelta
from pathlib import Path

from candid import config as C


class OnsiteError(Exception):
    """Raised for invalid onsite operations."""


ONSITE_PATH = C.DATA_DIR / "onsite.json"

MODES = ("onsite", "virtual", "hybrid")

# Round kinds with their default durations (minutes) and short labels.
ROUND_KINDS = {
    "coding": {"default_minutes": 45, "label": "Coding"},
    "system-design": {"default_minutes": 60, "label": "System design"},
    "behavioral": {"default_minutes": 45, "label": "Behavioral"},
    "hiring-manager": {"default_minutes": 30, "label": "Hiring manager"},
    "recruiter": {"default_minutes": 30, "label": "Recruiter screen"},
    "presentation": {"default_minutes": 60, "label": "Presentation"},
    "lunch": {"default_minutes": 45, "label": "Lunch"},
    "break": {"default_minutes": 15, "label": "Break"},
    "tour": {"default_minutes": 20, "label": "Office tour"},
}

# What to review before each kind of round. Generic technique reminders —
# they never claim anything about the user's background.
PREP_REMINDERS = {
    "coding": [
        "Warm up this morning with 1-2 easy/medium problems; stop 30 min before the round.",
        "Narrate your thinking out loud the whole time — silence reads as stuck.",
        "State the brute force first, then optimize; name the data structure before you code it.",
        "Leave 5 minutes at the end to test with an example and check edge cases.",
    ],
    "system-design": [
        "Run the 4-step frame: clarify requirements, sketch the high level, deep-dive one component, wrap with trade-offs.",
        "Ask about scale numbers before designing — don't guess QPS or storage.",
        "Have one scaling story and one failure story from your own work ready.",
        "Draw the boxes first, then talk; point at the diagram as you reason.",
    ],
    "behavioral": [
        "Pick 3 STAR stories that map to likely themes (conflict, ownership, mistakes, influence).",
        "End each story with what you learned or would do differently.",
        "Prepare your 'why this company, why this role' answer in under 90 seconds.",
        "Have one genuine weakness-with-a-plan answer; don't pick a humblebrag.",
    ],
    "hiring-manager": [
        "Prepare your 2-minute career narrative arc: where you've been, why here, why now.",
        "Bring 3 questions about the team: roadmap, success metrics, how they work day to day.",
        "Know what scope and growth look like at this level; ask how they define it.",
        "This round is mutual fit — be honest about what you want from a manager.",
    ],
    "recruiter": [
        "Confirm the day's schedule, round order, and who you'll meet.",
        "Ask about timeline, next steps, and comp bands if they haven't shared them.",
        "Share your constraints early (other processes, start-date needs).",
        "Get the interviewers' names/titles so you can prep and follow up.",
    ],
    "presentation": [
        "Dry-run the full talk out loud with a timer — cut to fit, then cut 10% more.",
        "Test screen share, clicker/remote, and fonts on the actual machine or link.",
        "Prepare a 2-slide appendix for the likeliest deep-dive questions.",
        "Open with the problem and why it mattered, not with your title slide.",
    ],
    "lunch": [
        "Keep it light — heavy food plus afternoon rounds is a bad combo.",
        "Ask about team culture, rituals, and what people do for fun.",
        "This is still an interview: stay curious, stay professional, don't gossip.",
        "Note names and anything personal to reference in thank-you notes.",
    ],
    "break": [
        "Stand up, stretch, drink water. Step outside if you can.",
        "Glance at your prep notes for the next round — one page only.",
        "Reset: two slow breaths before you walk into the next room.",
    ],
    "tour": [
        "Ask where the team sits and how the floor is organized.",
        "Notice the vibe: noise level, whiteboards, how people interact.",
        "Good small-talk fuel for later rounds ('I saw the X lab on the tour...').",
    ],
}

# Questions to ask the interviewer, per round kind.
ASK_QUESTIONS = {
    "coding": [
        "What does the day-to-day engineering work look like on this team?",
        "How does the team do code review, and what does 'good code' mean here?",
        "What's the most technically interesting problem the team solved recently?",
    ],
    "system-design": [
        "What are the hardest scaling or reliability challenges the team faces right now?",
        "How are architecture decisions made — RFCs, design reviews, tech leads?",
        "Where is the system most painful to change, and what's the plan?",
    ],
    "behavioral": [
        "What does success look like in this role in the first 90 days?",
        "How does the team handle disagreement on technical direction?",
        "What kind of person thrives here — and who struggles?",
    ],
    "hiring-manager": [
        "What are the team's top priorities for the next two quarters?",
        "How do you measure success for this role, and how is feedback given?",
        "What would make someone in this role promotable in a year?",
    ],
    "recruiter": [
        "What's the timeline from here, and what are the remaining steps?",
        "What are the comp bands for this level, and how is leveling decided?",
        "Is there anything in my background the hiring team wants to dig into?",
    ],
    "presentation": [
        "How much of this role is presenting or cross-functional communication?",
        "Who's the audience for technical presentations on the team?",
        "What feedback do you have on how I structured the talk?",
    ],
    "lunch": [
        "What's your favorite thing about working here?",
        "How does the team socialize — lunches, offsites, rituals?",
        "What surprised you most when you joined?",
    ],
    "break": [
        "Any advice for the rest of my day here?",
    ],
    "tour": [
        "Where does this team sit relative to its partners?",
        "How often is the team in the office vs remote?",
    ],
}

# (category, label) checklist items. Base applies to every mode.
BASE_CHECKLIST = [
    ("research", "Save every interviewer's name + role for the day"),
    ("research", "Read the company's recent news/blog; note 2 talking points"),
    ("research", "Prepare your 'why this company, why this role' answer"),
    ("prep", "Pick 3 STAR stories mapped to likely behavioral themes"),
    ("prep", "Rehearse your 2-minute career narrative out loud once"),
    ("prep", "Write 3 questions to ask per interviewer"),
    ("documents", "Resume accessible (printed copies or on your phone)"),
]

ONSITE_CHECKLIST = [
    ("documents", "Photo ID for building check-in"),
    ("logistics", "Office address + directions saved offline"),
    ("logistics", "Transit/parking plan, with a backup option"),
    ("logistics", "Plan to arrive 15 minutes early"),
    ("comfort", "Outfit laid out the night before"),
    ("comfort", "Notebook + pen"),
    ("comfort", "Water bottle + light snack"),
    ("comfort", "Phone charger / battery pack"),
    ("comfort", "Breath mints"),
]

VIRTUAL_CHECKLIST = [
    ("tech", "Quiet room booked; door closed"),
    ("tech", "Camera + mic tested in the meeting app"),
    ("tech", "Laptop charger plugged in"),
    ("tech", "Backup internet ready (phone hotspot)"),
    ("tech", "Close distracting tabs; silence notifications"),
    ("tech", "Do-not-disturb status on chat apps"),
    ("comfort", "Water nearby; light on your face, not behind you"),
]

HYBRID_CHECKLIST = [
    ("logistics", "Video links saved for the remote rounds"),
]

CATEGORIES = ("research", "prep", "documents", "logistics", "tech", "comfort")

ARRIVE_EARLY_MIN = 15
TRAVEL_BUFFER_MIN = 15
MORNING_ROUTINE_MIN = 90
VIRTUAL_WAKE_MIN = 60
SLEEP_HOURS = 8
CAFFEINE_CUTOFF_HOURS = 6
TIGHT_GAP_MIN = 10
LUNCH_WINDOW = (11 * 60, 14 * 60)  # 11:00-14:00


# --- storage ---------------------------------------------------------------

def _load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else ONSITE_PATH
    if not p.exists():
        return {"plans": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OnsiteError(f"Onsite file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("plans"), list):
        raise OnsiteError(f"Onsite file {p} should contain an object with a 'plans' list.")
    return data


def _save(data: dict, path: str | Path | None = None) -> Path:
    p = Path(path) if path else ONSITE_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _next_id(items: list[dict]) -> int:
    return max((i.get("id", 0) for i in items), default=0) + 1


# --- parsing / validation ----------------------------------------------------

def _parse_date(s: str) -> str:
    try:
        return date.fromisoformat(s.strip()).isoformat()
    except ValueError:
        raise OnsiteError(
            f"Bad date {s!r}: use YYYY-MM-DD (e.g. {date.today().isoformat()})."
        ) from None


def _parse_time(s: str) -> int:
    """'HH:MM' (24h) -> minutes since midnight."""
    t = s.strip()
    parts = t.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise OnsiteError(f"Bad time {s!r}: use 24h HH:MM, e.g. '10:00' or '14:30'.")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise OnsiteError(f"Bad time {s!r}: hour 0-23, minute 0-59.")
    return h * 60 + m


def _fmt(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


#: Public alias: minutes-since-midnight -> "HH:MM" (for CLI rendering).
fmt_time = _fmt


def _check_kind(kind: str) -> str:
    k = kind.strip().lower().replace("_", "-")
    if k not in ROUND_KINDS:
        raise OnsiteError(
            f"Unknown round kind {kind!r}. Choose from: {', '.join(sorted(ROUND_KINDS))}."
        )
    return k


def _check_minutes(minutes: int) -> int:
    if not 5 <= minutes <= 480:
        raise OnsiteError(f"Round length {minutes} is out of range (5-480 minutes).")
    return minutes


def parse_round_spec(spec: str) -> dict:
    """Parse 'START KIND MINUTES [TITLE...]' e.g. '10:00 coding 45 Coding - Jane'."""
    try:
        tokens = shlex.split(spec)
    except ValueError as exc:
        raise OnsiteError(f"Could not parse round {spec!r}: {exc}") from None
    if len(tokens) < 3:
        raise OnsiteError(
            f"Round spec needs at least START KIND MINUTES, e.g. '10:00 coding 45'. Got: {spec!r}"
        )
    start = _parse_time(tokens[0])
    kind = _check_kind(tokens[1])
    try:
        minutes = _check_minutes(int(tokens[2]))
    except ValueError:
        raise OnsiteError(
            f"Bad duration {tokens[2]!r} in {spec!r}: minutes must be a whole number."
        ) from None
    title = " ".join(tokens[3:]).strip() or ROUND_KINDS[kind]["label"]
    return {"start": start, "kind": kind, "minutes": minutes, "title": title}


def _rounds_overlap(a: dict, b: dict) -> bool:
    a_end, b_end = a["start"] + a["minutes"], b["start"] + b["minutes"]
    return a["start"] < b_end and b["start"] < a_end


def _sorted_rounds(plan: dict) -> list[dict]:
    return sorted(plan.get("rounds", []), key=lambda r: r["start"])


# --- plans ---------------------------------------------------------------------

def _checklist_for_mode(mode: str) -> list[dict]:
    items = list(BASE_CHECKLIST)
    if mode == "onsite":
        items += ONSITE_CHECKLIST
    elif mode == "virtual":
        items += VIRTUAL_CHECKLIST
    else:  # hybrid
        items += ONSITE_CHECKLIST + HYBRID_CHECKLIST
    return [
        {"id": i + 1, "category": cat, "label": label, "done": False}
        for i, (cat, label) in enumerate(items)
    ]


def create_plan(company: str, role: str, date_str: str, *,
               mode: str = "onsite", location: str = "",
               commute_min: int = 0, rounds: tuple[str, ...] = (),
               path: str | Path | None = None) -> dict:
    """Create an interview-day plan. Returns the plan record.

    If the same company+role+date already has a plan, returns the EXISTING
    record (a copy) with ``"duplicate": True`` — no write happens.
    """
    if not company or not role:
        raise OnsiteError("Both --company and --role are required for a day plan.")
    mode = mode.strip().lower()
    if mode not in MODES:
        raise OnsiteError(f"Unknown mode {mode!r}. Choose from: {', '.join(MODES)}.")
    if commute_min < 0 or commute_min > 600:
        raise OnsiteError(f"Commute {commute_min} is out of range (0-600 minutes).")
    day = _parse_date(date_str)
    data = _load(path)
    for p in data["plans"]:
        if (p["company"].lower() == company.lower()
                and p["role"].lower() == role.lower()
                and p["date"] == day):
            return {**p, "duplicate": True}
    plan = {
        "id": _next_id(data["plans"]),
        "company": company.strip(),
        "role": role.strip(),
        "date": day,
        "mode": mode,
        "location": location.strip(),
        "commute_min": commute_min,
        "rounds": [],
        "checklist": _checklist_for_mode(mode),
        "day_notes": "",
    }
    data["plans"].append(plan)
    for spec in rounds:
        _add_round_to_plan(plan, parse_round_spec(spec))
    _save(data, path)
    return plan


def _add_round_to_plan(plan: dict, spec: dict, *,
                       interviewer: str = "", where: str = "") -> dict:
    for existing in plan["rounds"]:
        if _rounds_overlap(spec, existing):
            raise OnsiteError(
                f"Round '{spec['title']}' ({_fmt(spec['start'])}-{_fmt(spec['start'] + spec['minutes'])}) "
                f"overlaps '{existing['title']}' ({_fmt(existing['start'])}-{_fmt(existing['start'] + existing['minutes'])}). "
                f"Pick a start time at or after {_fmt(existing['start'] + existing['minutes'])}."
            )
    rnd = {
        "id": _next_id(plan["rounds"]),
        "kind": spec["kind"],
        "title": spec["title"],
        "start": spec["start"],
        "minutes": spec["minutes"],
        "interviewer": interviewer.strip(),
        "location": where.strip(),
        "notes": "",
    }
    plan["rounds"].append(rnd)
    return rnd


def add_round(plan_id: int, spec: str, *, interviewer: str = "",
              where: str = "", path: str | Path | None = None) -> dict:
    """Add a round to a plan. Returns the new round record."""
    data = _load(path)
    plan = _find_plan(data, plan_id)
    rnd = _add_round_to_plan(plan, parse_round_spec(spec),
                             interviewer=interviewer, where=where)
    _save(data, path)
    return rnd


def _find_plan(data: dict, plan_id: int) -> dict:
    for p in data["plans"]:
        if p.get("id") == plan_id:
            return p
    known = ", ".join(f"#{p['id']} {p['company']} {p['date']}" for p in data["plans"])
    raise OnsiteError(
        f"No day plan with id {plan_id}." + (f" Known plans: {known}." if known else " No plans yet — create one with `onsite plan`.")
    )


def get_plan(plan_id: int, path: str | Path | None = None) -> dict:
    """Return the plan record, or raise OnsiteError."""
    return _find_plan(_load(path), plan_id)


def latest_plan(path: str | Path | None = None) -> dict:
    """Return the most recently created plan, or raise OnsiteError."""
    data = _load(path)
    if not data["plans"]:
        raise OnsiteError("No day plans yet — create one with `onsite plan --company ... --role ... --date YYYY-MM-DD`.")
    return max(data["plans"], key=lambda p: p["id"])


def list_plans(path: str | Path | None = None) -> list[dict]:
    """List plans, newest first."""
    return sorted(_load(path)["plans"], key=lambda p: p["id"], reverse=True)


def remove_round(plan_id: int, round_id: int, path: str | Path | None = None) -> None:
    """Remove a round from a plan."""
    data = _load(path)
    plan = _find_plan(data, plan_id)
    kept = [r for r in plan["rounds"] if r.get("id") != round_id]
    if len(kept) == len(plan["rounds"]):
        raise OnsiteError(f"Plan #{plan_id} has no round with id {round_id}.")
    plan["rounds"] = kept
    _save(data, path)


def delete_plan(plan_id: int, path: str | Path | None = None) -> None:
    """Delete a whole day plan."""
    data = _load(path)
    kept = [p for p in data["plans"] if p.get("id") != plan_id]
    if len(kept) == len(data["plans"]):
        raise OnsiteError(f"No day plan with id {plan_id}.")
    data["plans"] = kept
    _save(data, path)


# --- timeline --------------------------------------------------------------------

def _gaps(plan: dict) -> list[dict]:
    """Gaps between consecutive rounds: [{'after': title, 'before': title, 'minutes': n, 'start': m}]."""
    rounds = _sorted_rounds(plan)
    gaps = []
    for prev, nxt in zip(rounds, rounds[1:]):
        prev_end = prev["start"] + prev["minutes"]
        gap = nxt["start"] - prev_end
        if gap > 0:
            gaps.append({"after": prev["title"], "before": nxt["title"],
                         "minutes": gap, "start": prev_end})
    return gaps


def timeline(plan_id: int, path: str | Path | None = None) -> str:
    """Render the day as a printable timeline with gap analysis."""
    plan = get_plan(plan_id, path)
    rounds = _sorted_rounds(plan)
    lines = [
        f"Interview day: {plan['role']} @ {plan['company']}",
        f"Date: {plan['date']} · Mode: {plan['mode']}"
        + (f" · {plan['location']}" if plan["location"] else ""),
        "",
    ]
    if not rounds:
        lines.append("(no rounds yet — add some with `onsite add-round`)")
        return "\n".join(lines)
    for r in rounds:
        end = r["start"] + r["minutes"]
        who = f" — {r['interviewer']}" if r["interviewer"] else ""
        where = f" · {r['location']}" if r["location"] else ""
        lines.append(f"{_fmt(r['start'])}-{_fmt(end)}  {r['title']} ({r['minutes']}m){who}{where}")
    flags = []
    for g in _gaps(plan):
        if g["minutes"] < TIGHT_GAP_MIN:
            flags.append(
                f"Only {g['minutes']}m between '{g['after']}' and '{g['before']}' — "
                f"back-to-back. Use the 2-minute reset: water, stand, breathe."
            )
    kinds = {r["kind"] for r in rounds}
    if "lunch" not in kinds and not any(
            g["minutes"] >= 30 and LUNCH_WINDOW[0] <= g["start"] + g["minutes"] // 2 <= LUNCH_WINDOW[1]
            for g in _gaps(plan)):
        flags.append("No lunch window in the schedule — eat a solid breakfast and pack a snack.")
    if flags:
        lines += ["", "Flags:"]
        lines += [f"  ! {f}" for f in flags]
    total = rounds[-1]["start"] + rounds[-1]["minutes"] - rounds[0]["start"]
    lines += ["", f"Day span: {total // 60}h {total % 60}m across {len(rounds)} rounds."]
    return "\n".join(lines)


# --- checklist ---------------------------------------------------------------------

def render_checklist(plan_id: int, path: str | Path | None = None) -> str:
    """Render the logistics checklist grouped by category."""
    plan = get_plan(plan_id, path)
    items = plan.get("checklist", [])
    done = sum(1 for i in items if i["done"])
    lines = [f"Logistics checklist — {plan['company']} {plan['date']} ({done}/{len(items)} done)", ""]
    for cat in CATEGORIES:
        cat_items = [i for i in items if i["category"] == cat]
        if not cat_items:
            continue
        lines.append(f"{cat.upper()}:")
        for i in cat_items:
            box = "[x]" if i["done"] else "[ ]"
            lines.append(f"  {box} #{i['id']} {i['label']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def set_check(plan_id: int, item_id: int, done: bool,
              path: str | Path | None = None) -> dict:
    """Mark a checklist item done (or not done). Returns the item."""
    data = _load(path)
    plan = _find_plan(data, plan_id)
    for item in plan.get("checklist", []):
        if item.get("id") == item_id:
            item["done"] = done
            _save(data, path)
            return item
    raise OnsiteError(
        f"Plan #{plan_id} has no checklist item #{item_id} "
        f"(items are #1-#{len(plan.get('checklist', []))})."
    )


# --- prep reminders ------------------------------------------------------------------

def prep_reminders(plan_id: int, round_id: int | None = None,
                   path: str | Path | None = None) -> str:
    """Per-round prep reminders, for one round or the whole day in order."""
    plan = get_plan(plan_id, path)
    rounds = _sorted_rounds(plan)
    if round_id is not None:
        rounds = [r for r in rounds if r["id"] == round_id]
        if not rounds:
            raise OnsiteError(f"Plan #{plan_id} has no round with id {round_id}.")
    if not rounds:
        raise OnsiteError(f"Plan #{plan_id} has no rounds yet — add some with `onsite add-round`.")
    lines = [f"Prep reminders — {plan['role']} @ {plan['company']} ({plan['date']})", ""]
    for r in rounds:
        lines.append(f"## {_fmt(r['start'])} {r['title']} [{r['kind']}]")
        for tip in PREP_REMINDERS[r["kind"]]:
            lines.append(f"  - {tip}")
        lines.append("")
    return "\n".join(lines).rstrip()


# --- energy plan -----------------------------------------------------------------------

def _wake_and_bedtime(first_start: int, mode: str) -> tuple[int, int]:
    """(wake_minutes, bedtime_minutes_previous_evening)."""
    if mode == "virtual":
        wake = first_start - VIRTUAL_WAKE_MIN
    else:
        wake = first_start - MORNING_ROUTINE_MIN
    bedtime = wake - SLEEP_HOURS * 60
    return wake, bedtime


def energy_plan(plan_id: int, path: str | Path | None = None) -> str:
    """Sleep, meals, breaks, and caffeine guidance computed from the schedule."""
    plan = get_plan(plan_id, path)
    rounds = _sorted_rounds(plan)
    if not rounds:
        raise OnsiteError(f"Plan #{plan_id} has no rounds yet — add some with `onsite add-round`.")
    first_start = rounds[0]["start"]
    wake, bedtime = _wake_and_bedtime(first_start, plan["mode"])
    lines = [
        f"Energy plan — {plan['role']} @ {plan['company']} ({plan['date']})",
        "",
        "SLEEP",
        f"  - Bedtime the night before: {_fmt(bedtime)} (for {SLEEP_HOURS}h before a {_fmt(wake)} wake-up)",
        f"  - No screens after {_fmt(bedtime + 30)}; lay out everything tonight",
        "",
        "MEALS",
    ]
    lunch_rounds = [r for r in rounds if r["kind"] == "lunch"]
    if lunch_rounds:
        r = lunch_rounds[0]
        lines.append(f"  - Lunch is on the schedule: {_fmt(r['start'])}-{_fmt(r['start'] + r['minutes'])} — keep it light")
    else:
        midday = [g for g in _gaps(plan)
                  if g["minutes"] >= 30 and LUNCH_WINDOW[0] <= g["start"] + g["minutes"] // 2 <= LUNCH_WINDOW[1]]
        if midday:
            g = max(midday, key=lambda g: g["minutes"])
            lines.append(f"  - No lunch round, but there's a {g['minutes']}m gap at {_fmt(g['start'])} — eat then")
        else:
            lines.append("  - No lunch window: eat a big breakfast and pack a real snack")
    lines += ["", "BREAKS"]
    gaps = _gaps(plan)
    real = [g for g in gaps if g["minutes"] >= TIGHT_GAP_MIN]
    tight = [g for g in gaps if g["minutes"] < TIGHT_GAP_MIN]
    if real:
        for g in real:
            lines.append(f"  - {_fmt(g['start'])} ({g['minutes']}m): real break — stand, water, fresh air")
    if tight:
        for g in tight:
            lines.append(f"  - {_fmt(g['start'])} ({g['minutes']}m): back-to-back — 2-minute reset only (water, breathe, stand)")
    if not gaps:
        lines.append("  - Single round: no in-day breaks to plan around")
    lines += [
        "",
        "CAFFEINE + HYDRATION",
        f"  - Last caffeine by {_fmt(bedtime - CAFFEINE_CUTOFF_HOURS * 60)} ({CAFFEINE_CUTOFF_HOURS}h before bed)",
        "  - One glass of water per gap; keep the bottle where you can see it",
        "  - Skip the second coffee after 14:00 if you want to sleep at " + _fmt(bedtime),
    ]
    return "\n".join(lines)


# --- morning-of timeline -----------------------------------------------------------------

def morning_plan(plan_id: int, path: str | Path | None = None) -> str:
    """Reverse timeline: wake-up, leave-by, arrival, from the first round."""
    plan = get_plan(plan_id, path)
    rounds = _sorted_rounds(plan)
    if not rounds:
        raise OnsiteError(f"Plan #{plan_id} has no rounds yet — add some with `onsite add-round`.")
    first = rounds[0]["start"]
    lines = [f"Morning of {plan['date']} — {plan['role']} @ {plan['company']}", ""]
    if plan["mode"] == "virtual":
        wake = first - VIRTUAL_WAKE_MIN
        _, bedtime = _wake_and_bedtime(first, plan["mode"])
        lines += [
            f"  {_fmt(bedtime)} (night before)  Bedtime — {SLEEP_HOURS}h of sleep",
            f"  {_fmt(wake)}  Wake up, shower, breakfast, review one page of notes",
            f"  {_fmt(first - 10)}  Log in early; camera/mic check",
            f"  {_fmt(first)}  First round: {rounds[0]['title']}",
        ]
    else:
        arrive = first - ARRIVE_EARLY_MIN
        leave = arrive - plan["commute_min"] - TRAVEL_BUFFER_MIN
        wake = leave - MORNING_ROUTINE_MIN
        _, bedtime = _wake_and_bedtime(first, plan["mode"])
        lines += [
            f"  {_fmt(bedtime)} (night before)  Bedtime — {SLEEP_HOURS}h of sleep",
            f"  {_fmt(wake)}  Wake up, shower, dress, breakfast",
            f"  {_fmt(leave)}  Leave (commute {plan['commute_min']}m + {TRAVEL_BUFFER_MIN}m buffer)",
            f"  {_fmt(arrive)}  Arrive {ARRIVE_EARLY_MIN}m early — check in, breathe, review notes",
            f"  {_fmt(first)}  First round: {rounds[0]['title']}",
        ]
    lines += ["", "Everything above is computed from your schedule — adjust the commute with `onsite plan` if it changes."]
    return "\n".join(lines)


# --- questions to ask ----------------------------------------------------------------------

def questions(kind: str | None = None, plan_id: int | None = None,
              path: str | Path | None = None) -> str:
    """Question bank: for one kind, or per-round for a whole plan."""
    if plan_id is not None:
        plan = get_plan(plan_id, path)
        rounds = _sorted_rounds(plan)
        if not rounds:
            raise OnsiteError(f"Plan #{plan_id} has no rounds yet — add some with `onsite add-round`.")
        lines = [f"Questions to ask — {plan['role']} @ {plan['company']} ({plan['date']})", ""]
        for r in rounds:
            lines.append(f"## {r['title']} [{r['kind']}]")
            for q in ASK_QUESTIONS[r["kind"]]:
                lines.append(f"  - {q}")
            lines.append("")
        return "\n".join(lines).rstrip()
    if kind is None:
        raise OnsiteError("Pass --kind (e.g. coding) or --plan-id.")
    k = _check_kind(kind)
    lines = [f"Questions to ask in a {ROUND_KINDS[k]['label'].lower()} round:", ""]
    lines += [f"  - {q}" for q in ASK_QUESTIONS[k]]
    return "\n".join(lines)


# --- notes + summary --------------------------------------------------------------------------

def set_notes(plan_id: int, text: str, round_id: int | None = None,
              path: str | Path | None = None) -> None:
    """Save free-text notes for the day or for one round."""
    if not text.strip():
        raise OnsiteError("Notes can't be blank.")
    data = _load(path)
    plan = _find_plan(data, plan_id)
    if round_id is None:
        plan["day_notes"] = text.strip()
    else:
        for r in plan["rounds"]:
            if r.get("id") == round_id:
                r["notes"] = text.strip()
                break
        else:
            raise OnsiteError(f"Plan #{plan_id} has no round with id {round_id}.")
    _save(data, path)


def summary(plan_id: int, out: str | Path | None = None,
            path: str | Path | None = None) -> Path:
    """Export the day to Markdown: timeline, notes, checklist, follow-ups."""
    plan = get_plan(plan_id, path)
    items = plan.get("checklist", [])
    done = sum(1 for i in items if i["done"])
    lines = [
        f"# Interview day — {plan['role']} @ {plan['company']}",
        "",
        f"Date: {plan['date']} · Mode: {plan['mode']}"
        + (f" · {plan['location']}" if plan["location"] else ""),
        "",
        "## Timeline",
        "",
    ]
    for r in _sorted_rounds(plan):
        end = r["start"] + r["minutes"]
        who = f" with {r['interviewer']}" if r["interviewer"] else ""
        where = f" ({r['location']})" if r["location"] else ""
        lines.append(f"- **{_fmt(r['start'])}-{_fmt(end)}** {r['title']}{who}{where}")
        if r["notes"]:
            lines.append(f"  - Notes: {r['notes']}")
    lines += ["", "## Day notes", ""]
    lines.append(plan["day_notes"] or "_No day notes captured._")
    lines += ["", "## Logistics checklist", "",
              f"{done}/{len(items)} done."]
    for i in items:
        box = "x" if i["done"] else " "
        lines.append(f"- [{box}] {i['label']}")
    lines += [
        "",
        "## Follow-ups",
        "",
        "- Send thank-you notes within 24 hours — same evening is ideal.",
        "- Note one specific thing per interviewer while it's fresh.",
        "- If the recruiter gave a timeline, set a check-in for 2 days past it.",
    ]
    dest = Path(out) if out else C.DATA_DIR / f"onsite_{plan_id}_summary.md"
    C.ensure_data_dirs()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def render_plans(plans: list[dict]) -> str:
    """One-line-per-plan listing."""
    if not plans:
        return "No day plans yet."
    lines = []
    for p in plans:
        n = len(p.get("rounds", []))
        lines.append(
            f"#{p['id']}  {p['date']}  {p['role']} @ {p['company']} "
            f"[{p['mode']}] — {n} round{'s' if n != 1 else ''}"
        )
    return "\n".join(lines)
