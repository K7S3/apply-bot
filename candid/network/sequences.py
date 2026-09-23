"""Feature 2 - post-event follow-up sequences.

Start a follow-up sequence when you meet someone (conference, meetup,
informational interview, recruiter call, coffee chat, referral intro).
Each template is a list of steps with day offsets; starting a sequence
schedules concrete due dates you can check with `candid network due`.
"""

from __future__ import annotations

from datetime import date, timedelta

from candid.network import _store as S
from candid.network import contacts as CT

_STORE = "sequences.json"
_EMPTY = {"next_id": 1, "sequences": []}

# offset_days, kind, title, guidance
SEQUENCE_TEMPLATES: dict[str, list[tuple[int, str, str, str]]] = {
    "conference": [
        (0, "note", "Same-day connection note",
         "Reference one specific thing from your conversation so they remember you."),
        (1, "email", "Follow-up email",
         "Thank them, restate the one idea you discussed, propose a concrete next step."),
        (7, "value_add", "First value-add touch",
         "Share something useful: an article, an intro, a resource tied to what they care about."),
        (30, "check_in", "One-month check-in",
         "Short note: what you did with their advice, or a relevant update from your side."),
    ],
    "meetup": [
        (0, "note", "Same-day connection note",
         "Reference the meetup and one topic you discussed."),
        (2, "email", "Follow-up email",
         "Keep it short; suggest coffee or a 20-min call if the conversation clicked."),
        (21, "check_in", "Three-week check-in",
         "Share a quick update or something you promised to send."),
    ],
    "informational": [
        (0, "email", "Same-day thank-you",
         "Thank them for their time; name the single most useful thing they said."),
        (3, "note", "Act on their advice, then tell them",
         "If they suggested a person, article, or approach - do it, then report back briefly."),
        (30, "value_add", "Give back",
         "Share something useful for them. Informational interviews work when they go both ways."),
        (90, "check_in", "Quarterly update",
         "One-paragraph update on where you landed; keep the door open."),
    ],
    "recruiter_call": [
        (0, "email", "Same-day thank-you + materials",
         "Thank them and attach (or link) your resume while you are top of mind."),
        (7, "check_in", "One-week check-in",
         "Ask about timeline / next steps if you have not heard back."),
        (21, "check_in", "Three-week nudge",
         "Polite bump with one new datapoint (a new project, a competing process)."),
    ],
    "coffee_chat": [
        (0, "email", "Same-day thank-you",
         "Thank them for the coffee and their time; reference the best part of the chat."),
        (14, "value_add", "Two-week value-add",
         "Send the article/intro/resource you mentioned, or one you found since."),
        (60, "check_in", "Two-month check-in",
         "Suggest a second coffee or a quick call to keep the thread alive."),
    ],
    "referral_intro": [
        (0, "email", "Intro thank-you to the connector",
         "Thank the person who made the intro the same day; CC etiquette applies."),
        (1, "email", "First note to the new contact",
         "Move the connector to BCC, introduce yourself crisply, propose a 20-min call."),
        (14, "check_in", "Two-week follow-up",
         "If no reply, one polite bump. If it went well, suggest the next step."),
    ],
}


def templates() -> list[str]:
    return sorted(SEQUENCE_TEMPLATES)


def _db() -> dict:
    return S.load(_STORE, _EMPTY)


def _persist(db: dict) -> None:
    S.save(_STORE, db)


def start_sequence(contact_id: int, template: str,
                   start_on: str | None = None, today: date | None = None) -> dict:
    """Start a follow-up sequence for a contact. Raises on bad input."""
    CT.get_contact(contact_id)  # validates the contact exists
    if template not in SEQUENCE_TEMPLATES:
        raise ValueError(
            f"Unknown template '{template}'. Choose from: {', '.join(templates())}.")
    start = date.fromisoformat(S.parse_date(start_on, "start_on"))
    db = _db()
    steps = []
    for offset, kind, title, guidance in SEQUENCE_TEMPLATES[template]:
        steps.append({
            "offset_days": offset,
            "kind": kind,
            "title": title,
            "guidance": guidance,
            "due": (start + timedelta(days=offset)).isoformat(),
            "status": "pending",
            "completed_on": None,
        })
    rec = {
        "id": db["next_id"],
        "contact_id": int(contact_id),
        "template": template,
        "started_on": start.isoformat(),
        "steps": steps,
    }
    db["sequences"].append(rec)
    db["next_id"] += 1
    _persist(db)
    return rec


def get_sequence(seq_id: int) -> dict:
    for s in _db()["sequences"]:
        if s["id"] == int(seq_id):
            return s
    raise ValueError(f"No sequence with id {seq_id}.")


def list_sequences(contact_id: int | None = None) -> list[dict]:
    seqs = _db()["sequences"]
    if contact_id is not None:
        seqs = [s for s in seqs if s["contact_id"] == int(contact_id)]
    return seqs


def _set_step_status(seq_id: int, step_idx: int, status: str,
                     today: date | None = None) -> dict:
    db = _db()
    for s in db["sequences"]:
        if s["id"] == int(seq_id):
            if not 0 <= int(step_idx) < len(s["steps"]):
                raise ValueError(
                    f"Step {step_idx} out of range (sequence has {len(s['steps'])} steps).")
            step = s["steps"][int(step_idx)]
            step["status"] = status
            step["completed_on"] = (today or date.today()).isoformat() \
                if status == "done" else None
            _persist(db)
            return s
    raise ValueError(f"No sequence with id {seq_id}.")


def complete_step(seq_id: int, step_idx: int,
                  today: date | None = None) -> dict:
    return _set_step_status(seq_id, step_idx, "done", today)


def skip_step(seq_id: int, step_idx: int) -> dict:
    return _set_step_status(seq_id, step_idx, "skipped")


def sequence_progress(seq: dict) -> tuple[int, int]:
    done = sum(1 for st in seq["steps"] if st["status"] == "done")
    return done, len(seq["steps"])


def due_steps(today: date | None = None) -> list[tuple[dict, dict]]:
    """All pending steps whose due date has arrived, oldest first."""
    today = today or date.today()
    out = []
    for s in _db()["sequences"]:
        for st in s["steps"]:
            if st["status"] == "pending" and st["due"] <= today.isoformat():
                out.append((s, st))
    out.sort(key=lambda pair: pair[1]["due"])
    return out


def render_sequence(seq: dict) -> str:
    contact = CT.get_contact(seq["contact_id"])
    done, total = sequence_progress(seq)
    lines = [f"Sequence #{seq['id']} - {seq['template']} for {contact['name']} "
             f"({done}/{total} done, started {seq['started_on']})"]
    for i, st in enumerate(seq["steps"]):
        mark = {"pending": "[ ]", "done": "[x]", "skipped": "[-]"}[st["status"]]
        lines.append(f"  {mark} step {i}: due {st['due']} - {st['title']} "
                     f"({st['kind']})")
        lines.append(f"      {st['guidance']}")
    return "\n".join(lines)
