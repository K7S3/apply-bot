"""Post-interview thank-you sequencer: one step per interviewer, per
application.

Each step carries its interviewer, round, a draft (via
followup.thank_you()), timing guidance, and a pending/sent status.
Stored as JSON at candid_data/thankyou_sequences.json (git-ignored),
keyed by app_id.

Nothing is ever sent automatically — you copy the draft and send it
yourself.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from candid import config as C
from candid import followup as F

FILENAME = "thankyou_sequences.json"

#: Lifecycle of a single thank-you step.
STEP_STATUSES = ("pending", "sent")

#: When each thank-you should go out.
TIMING_GUIDANCE = (
    "Send the same evening as the interview (within 24h); "
    "next morning at the latest."
)


class ThankYouError(Exception):
    """Raised for invalid thank-you sequence operations."""


def _default_path() -> Path:
    """Data path. CANDID_DATA_DIR is re-read at call time so tests can
    point it at a tmp dir even after candid.config was imported."""
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    return base / FILENAME


def _resolve(path: str | Path | None) -> Path:
    return Path(path) if path else _default_path()


def _load(path: str | Path | None = None) -> dict:
    p = _resolve(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThankYouError(
            f"Thank-you file {p} is not valid JSON: {exc}. "
            "Fix or delete the file, then run `python -m candid thanks list`."
        ) from exc
    if not isinstance(data, dict):
        raise ThankYouError(
            f"Thank-you file {p} should contain a JSON object keyed by app_id. "
            "Fix or delete the file, then run `python -m candid thanks list`."
        )
    return data


def _save(seqs: dict, path: str | Path | None = None) -> Path:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(seqs, indent=2), encoding="utf-8")
    return p


def _today_iso() -> str:
    return date.today().isoformat()


def plan(app_id: int, *, role: str, company: str,
         interviewers: list[dict],
         path: str | Path | None = None) -> dict:
    """Create a thank-you sequence for an application.

    ``interviewers``: list of {name, round, topics?, standout?, email?}.
    Re-planning an app_id replaces the existing sequence. Returns it.
    """
    if not app_id or app_id < 1:
        raise ThankYouError(
            f"Invalid app_id {app_id!r}. "
            "Run `python -m candid track list` to see application ids, "
            "then `python -m candid thanks plan --help`."
        )
    if not role or not company:
        raise ThankYouError(
            "Both role and company are required. "
            "Run `python -m candid thanks plan --help`."
        )
    if not interviewers:
        raise ThankYouError(
            "Give at least one interviewer (--interviewer \"Name: round\"). "
            "Run `python -m candid thanks plan --help`."
        )
    steps = []
    for i, iv in enumerate(interviewers, start=1):
        name = (iv.get("name") or "").strip()
        if not name:
            raise ThankYouError(
                f"Interviewer #{i} has no name. "
                "Run `python -m candid thanks plan --help`."
            )
        steps.append({
            "step": i,
            "interviewer": name,
            "round": (iv.get("round") or "").strip(),
            "topics": (iv.get("topics") or "").strip(),
            "standout": (iv.get("standout") or "").strip(),
            "email": (iv.get("email") or "").strip(),
            "status": "pending",
            "timing": TIMING_GUIDANCE,
            "date_created": _today_iso(),
            "date_sent": "",
        })
    seq = {
        "app_id": app_id,
        "role": role,
        "company": company,
        "status": "pending",
        "steps": steps,
        "date_created": _today_iso(),
        "date_updated": _today_iso(),
    }
    seqs = _load(path)
    seqs[str(app_id)] = seq
    _save(seqs, path)
    return seq


def get_sequence(app_id: int, path: str | Path | None = None) -> dict:
    """Return the sequence for app_id or raise."""
    seqs = _load(path)
    seq = seqs.get(str(app_id))
    if seq is None:
        raise ThankYouError(
            f"No thank-you sequence for app #{app_id}. "
            "Create one with `python -m candid thanks plan --app-id "
            f"{app_id} --help`."
        )
    return seq


def list_sequences(*, status: str | None = None,
                   path: str | Path | None = None) -> list[dict]:
    """All sequences, optionally filtered to those with any pending step
    (status='pending') or fully sent (status='sent')."""
    if status is not None and status not in ("pending", "sent"):
        raise ThankYouError(
            f"Unknown status '{status}'. Choose from: pending, sent. "
            "Run `python -m candid thanks list --help`."
        )
    seqs = sorted(_load(path).values(), key=lambda s: s.get("app_id", 0))
    if status == "pending":
        return [s for s in seqs
                if any(st["status"] == "pending" for st in s["steps"])]
    if status == "sent":
        return [s for s in seqs
                if s["steps"] and all(st["status"] == "sent" for st in s["steps"])]
    return seqs


def _step(seq: dict, step_no: int) -> dict:
    for st in seq["steps"]:
        if st["step"] == step_no:
            return st
    raise ThankYouError(
        f"No step {step_no} in the sequence for app #{seq['app_id']} "
        f"(has {len(seq['steps'])} step(s)). "
        "Run `python -m candid thanks list --app-id "
        f"{seq['app_id']}` to see steps."
    )


def draft(app_id: int, step_no: int, *, name: str = "Your Name",
          tone: str = "warm", path: str | Path | None = None) -> str:
    """Draft the thank-you for one step via followup.thank_you()."""
    seq = get_sequence(app_id, path)
    st = _step(seq, step_no)
    return F.thank_you(
        name, st["interviewer"], seq["role"], seq["company"],
        topics=st.get("topics") or "", standout=st.get("standout") or "",
        tone=tone,
    )


def mark_sent(app_id: int, step_no: int,
              path: str | Path | None = None) -> dict:
    """Mark one step sent. Returns the updated sequence."""
    seqs = _load(path)
    seq = seqs.get(str(app_id))
    if seq is None:
        raise ThankYouError(
            f"No thank-you sequence for app #{app_id}. "
            "Run `python -m candid thanks list` to see planned sequences."
        )
    st = _step(seq, step_no)
    if st["status"] == "sent":
        raise ThankYouError(
            f"Step {step_no} (to {st['interviewer']}) is already marked sent. "
            "Run `python -m candid thanks list --app-id "
            f"{app_id}` to review."
        )
    st["status"] = "sent"
    st["date_sent"] = _today_iso()
    seq["date_updated"] = _today_iso()
    if all(s["status"] == "sent" for s in seq["steps"]):
        seq["status"] = "sent"
    _save(seqs, path)
    return seq


def pending_steps(path: str | Path | None = None) -> list[dict]:
    """Every unsent step across all sequences, app order."""
    out: list[dict] = []
    for seq in list_sequences(status="pending", path=path):
        for st in seq["steps"]:
            if st["status"] == "pending":
                out.append({
                    "app_id": seq["app_id"],
                    "role": seq["role"],
                    "company": seq["company"],
                    "step": st["step"],
                    "interviewer": st["interviewer"],
                    "round": st.get("round", ""),
                    "timing": st.get("timing", ""),
                })
    return out


def render_sequence(seq: dict) -> str:
    """Checklist-style rendering of one sequence."""
    lines = [
        f"App #{seq['app_id']}: {seq['role']} @ {seq['company']} "
        f"[{seq['status']}]",
    ]
    for st in seq["steps"]:
        box = "✅" if st["status"] == "sent" else "⬜"
        rnd = f" ({st['round']})" if st.get("round") else ""
        lines.append(
            f"  {box} step {st['step']}: {st['interviewer']}{rnd} — {st['status']}"
            + (f" (sent {st['date_sent']})" if st.get("date_sent") else "")
        )
    lines.append(f"  ⏰ {TIMING_GUIDANCE}")
    return "\n".join(lines)


def render_pending(steps: list[dict]) -> str:
    """Nudge-style rendering of pending_steps()."""
    if not steps:
        return "All thank-you notes are sent. 🎉"
    lines = [f"📌 {len(steps)} thank-you note(s) still pending:", ""]
    for s in steps:
        rnd = f" ({s['round']})" if s.get("round") else ""
        lines.append(
            f"• Step {s['step']} to {s['interviewer']}{rnd} — "
            f"{s['role']} @ {s['company']} (app #{s['app_id']})"
        )
        lines.append(
            f"  → After you send it, mark it: python -m candid thanks mark-sent "
            f"--app-id {s['app_id']} --step {s['step']}"
        )
    return "\n".join(lines)
