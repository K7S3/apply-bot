"""Thread summaries for context-aware email drafting.

Turns a tracked application's history into a short, deterministic,
template-based timeline: bullets in chronological order, the last contact
date, and open questions.

DRAFTS ONLY: nothing here sends email, opens sockets, or makes network
calls. Deterministic: no LLMs, no randomness, no wall-clock formatting
beyond ISO dates already in the records.
"""

from __future__ import annotations

from datetime import date

from candid.drafting import context as _ctx


def _bullet(text: str) -> str:
    return text.strip()


def _summarize_history(rec: dict) -> list[tuple[date | None, int, str]]:
    """Collect (parsed_date, insertion_order, bullet) timeline events."""
    events: list[tuple[date | None, int, str]] = []
    seq = 0

    def add(when: object, text: str) -> None:
        nonlocal seq
        text = _bullet(text)
        if text:
            events.append((_ctx._parse_iso(when), seq, text))
            seq += 1

    role = str(rec.get("role", "") or "")
    added = rec.get("date_added")
    if added:
        add(added, f"{added}: Added to tracker{f' as {role}' if role else ''}.")

    history = rec.get("status_history")
    if isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict):
                when = entry.get("date", "")
                frm = str(entry.get("from", "") or "")
                to = str(entry.get("to", "") or "")
                note = str(entry.get("note", "") or "").strip()
                if frm and to:
                    text = f"{when}: Status changed: {frm} -> {to}."
                elif to:
                    text = f"{when}: Status set to {to}."
                else:
                    text = f"{when}: {note}" if note else ""
                if note and (frm or to):
                    text += f" Note: {note}"
                add(entry.get("date"), text)
            elif isinstance(entry, str):
                add(None, entry)

    interviewers = rec.get("interviewers") or []
    if isinstance(interviewers, str):
        interviewers = [interviewers]
    interviewers = [str(i).strip() for i in interviewers if str(i).strip()]
    if interviewers:
        add(None, f"Interviewers: {', '.join(interviewers)}.")

    notes = str(rec.get("notes", "") or "").strip()
    if notes:
        add(None, f"Notes: {notes}")

    prep = str(rec.get("prep_pack", "") or "").strip()
    if prep:
        add(None, f"Prep pack: {prep}")

    # Chronological, undated entries last; stable within ties.
    events.sort(key=lambda e: (e[0] is None, e[0] or date.min, e[1]))
    return events


def summarize_thread(
    company: str | None, tracker: object = None
) -> dict:
    """Summarize the email/thread history for ``company``.

    ``tracker`` accepts the same forms as
    :func:`candid.drafting.context.build_context`.

    Returns a dict with keys: company, bullets (chronological timeline
    strings), last_contact (ISO date or ""), open_questions.
    """
    apps = _ctx._resolve_apps(tracker)
    rec = _ctx._find_application(apps, company, None) or {}
    name = str(rec.get("company", "") or (company or "")).strip()

    bullets = [text for _, _, text in _summarize_history(rec)]

    last = _ctx._latest_contact(rec)
    last_contact = last.isoformat() if last else ""

    questions = rec.get("open_questions") or []
    if isinstance(questions, str):
        questions = [questions]
    open_questions = [str(q).strip() for q in questions if str(q).strip()]

    # Template-based nudge question when contact has gone quiet.
    if rec and last and str(rec.get("status", "")) == "applied":
        quiet_days = (date.today() - last).days
        if quiet_days >= 14:
            open_questions.append(
                f"No contact in {quiet_days} days; is a follow-up due?"
            )

    return {
        "company": name,
        "bullets": bullets,
        "last_contact": last_contact,
        "open_questions": open_questions,
    }
