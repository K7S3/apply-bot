"""ritual cooldown: 5-minute post-interview guided cooldown + debrief capture.

    python -m candid ritual cooldown --company X --role Y

Walks you through a short cooldown (breathe, reset), then captures the
debrief: what they asked, what stumped you, weak spots in your answers,
the interview vibe, and next steps. Saved to
candid_data/debriefs/<ritual_id>.json - the schema batch 2's debrief loop
is expected to consume:

    {"company": ..., "role": ..., "date": "YYYY-MM-DD",
     "questions_asked": [...], "stumped_by": [...], "weak_spots": [...],
     "vibe": "...", "next_steps": [...]}

Ends with a reminder to send thank-you notes via
`python -m candid followup thank-you`.
"""

from __future__ import annotations

import json
from datetime import date


class RitualError(Exception):
    """Expected failure: reported cleanly, no traceback."""


COOLDOWN_SCRIPT = [
    "=== 5-minute post-interview cooldown ===",
    "",
    "The interview is done. You did the hard part.",
    "",
    "Minute 1 - Breathe. In for 4 counts, hold for 4, out for 4.",
    "           Do that three times before you touch your phone.",
    "",
    "Minute 2 - Reset. Unclench your jaw, drop your shoulders,",
    "           drink water. The outcome is out of your hands now.",
    "",
    "Minute 3-5 - Debrief. Capture what happened while it is fresh.",
    "           Answer the prompts below honestly; short is fine.",
    "",
]


def _prompt(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _prompt_list(header: str) -> list[str]:
    print(f"\n{header}")
    print("  (one per line, blank line when done)")
    items = []
    while True:
        line = _prompt("  > ")
        if not line:
            break
        items.append(line)
    return items


def collect_debrief() -> dict:
    """Interactive debrief prompts; returns the list/scalar fields."""
    questions = _prompt_list("1. What did they ask?")
    stumped = _prompt_list("2. What stumped you? (blank line to skip)")
    weak = _prompt_list("3. Weak spots in your answers? Be specific. (blank line to skip)")
    print("\n4. Overall vibe? (e.g. warm / neutral / tough / rushed)")
    vibe = _prompt("  > ")
    steps = _prompt_list("5. Next steps? (e.g. recruiter follow-up by Friday)")
    return {
        "questions_asked": questions,
        "stumped_by": stumped,
        "weak_spots": weak,
        "vibe": vibe,
        "next_steps": steps,
    }


def _debrief_path(company: str, role: str):
    from candid import config, ritual as R
    rid = R._ritual_id(company, role)
    return config.DATA_DIR / "debriefs" / f"{rid}.json"


def save_debrief(company: str, role: str, fields: dict) -> str:
    """Write the debrief JSON with the batch-2 schema; return the path."""
    record = {
        "company": company,
        "role": role,
        "date": date.today().isoformat(),
        "questions_asked": fields.get("questions_asked", []),
        "stumped_by": fields.get("stumped_by", []),
        "weak_spots": fields.get("weak_spots", []),
        "vibe": fields.get("vibe", ""),
        "next_steps": fields.get("next_steps", []),
    }
    path = _debrief_path(company, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    return str(path)


def run(a) -> int:
    print("\n".join(COOLDOWN_SCRIPT))
    fields = collect_debrief()
    path = save_debrief(a.company, a.role, fields)
    print(f"\nDebrief saved to {path}")
    n_q = len(fields["questions_asked"])
    print(f"Captured {n_q} question(s), {len(fields['stumped_by'])} stumper(s), "
          f"{len(fields['next_steps'])} next step(s).")
    print("")
    print("Reminder: send thank-you notes within 24 hours:")
    print(f"  python -m candid followup thank-you --person \"<interviewer name>\" "
          f"--role \"{a.role}\" --company \"{a.company}\"")
    return 0
