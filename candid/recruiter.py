"""Recruiter and networking outreach drafts.

LinkedIn connection notes tied to the referral finder, recruiter email
reply templates (interested / not interested / need details), and a
recruiter call-prep checklist.

Everything here is a draft for you to copy, edit, and send yourself.
Nothing is ever sent automatically, and nothing requires network access.
"""

from __future__ import annotations

MAX_NOTE_LEN = 300


class RecruiterError(Exception):
    """Raised for recruiter-module problems (e.g. referral finder missing)."""


def _require(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} must be a non-empty string.")
    return value


# ---------------------------------------------------------------------------
# LinkedIn connection notes
# ---------------------------------------------------------------------------

def connection_note(name: str, contact_name: str, company: str, role: str,
                    context: str = "") -> str:
    """Draft a short LinkedIn-style connection note (under 300 characters).

    Personalized from who the contact is (title/company), what you are after
    (role at company), and an optional context line. No generic flattery.
    """
    name = _require(name, "name")
    contact_name = _require(contact_name, "contact_name")
    company = _require(company, "company")
    role = _require(role, "role")
    context = (context or "").strip()
    if context and context[-1] not in ".!?:;":
        context += "."

    note = (
        f"Hi {contact_name.split()[0]}, I'm {name}, exploring {role} roles at "
        f"{company}."
    )
    if context:
        note += f" {context}"
    note += " Would love to connect and hear how you're finding it there."
    if len(note) > MAX_NOTE_LEN:
        # Trim from the middle: keep the personalized frame and the sign-off,
        # cut the context down to size.
        frame = (
            f"Hi {contact_name.split()[0]}, I'm {name}, exploring {role} "
            f"roles at {company}."
        )
        tail = " Would love to connect and hear how you're finding it there."
        room = MAX_NOTE_LEN - len(frame) - len(tail)
        context = (context or "").strip()
        if room > 3 and context:
            note = frame + " " + context[:room - 3].rstrip() + "..." + tail
        else:
            note = frame + tail
    return note


def connection_notes_for_company(name: str, company: str, role: str,
                                 top_n: int = 3) -> list[dict]:
    """Build connection notes for the top referral candidates at a company.

    Uses the batch-2 referral finder (``candid.referrals``) defensively:
    if it is not importable, raises RecruiterError suggesting you pass
    contacts explicitly via :func:`connection_note` instead.

    Returns a list of {contact_name, position, company, why_this_contact,
    note}, best candidate first.
    """
    name = _require(name, "name")
    company = _require(company, "company")
    role = _require(role, "role")
    if top_n < 1:
        raise ValueError("top_n must be at least 1.")

    try:
        from candid import referrals
    except ImportError:
        referrals = None
    if referrals is None or not hasattr(referrals, "find_referrals"):
        raise RecruiterError(
            "The referral finder (candid.referrals) is not available in this "
            "install. Build your contact list yourself and call "
            "connection_note(name, contact_name, company, role, context=...) "
            "for each person directly.")

    results = referrals.find_referrals([company]) or {}
    contacts = results.get(company, []) or []
    notes = []
    for c in contacts[:top_n]:
        if not isinstance(c, dict):
            continue
        contact_name = (c.get("name") or "").strip()
        if not contact_name:
            continue
        position = (c.get("position") or "").strip()
        why = (c.get("rank_reason") or "").strip() or "1st-degree connection"
        context = why
        if position:
            context = f"As a {position} at {company}: {context}"
        notes.append({
            "contact_name": contact_name,
            "position": position,
            "company": company,
            "why_this_contact": why,
            "note": connection_note(name, contact_name, company, role,
                                    context=context),
        })
    return notes


# ---------------------------------------------------------------------------
# Recruiter reply templates
# ---------------------------------------------------------------------------

_REPLY_KINDS = ("interested", "not_interested", "need_details")

REPLY_TIMING = {
    "interested": "Reply within 24 hours - fast, warm replies signal real interest.",
    "not_interested": "Reply within 2-3 days; declining promptly is a courtesy that keeps the relationship warm.",
    "need_details": "Reply within 24 hours with your questions - don't let a good role go cold while you decide.",
}


def recruiter_reply(kind: str, name: str, recruiter_name: str, role: str,
                    company: str, detail: str = "") -> dict:
    """Draft a reply to a recruiter outreach email.

    kind: "interested" (enthusiastic, asks for next steps / a call),
          "not_interested" (polite decline, keeps the door open),
          "need_details" (asks for comp band, leveling, interview process
          before deciding).

    Returns {"kind", "subject", "body", "timing_note"}.
    """
    if kind not in _REPLY_KINDS:
        raise ValueError(
            f"Unknown reply kind '{kind}'. Choose from {list(_REPLY_KINDS)}.")
    name = _require(name, "name")
    recruiter_name = _require(recruiter_name, "recruiter_name")
    role = _require(role, "role")
    company = _require(company, "company")
    detail = (detail or "").strip()

    if kind == "interested":
        extra = f" {detail}" if detail else ""
        subject = f"Re: {role} @ {company} - interested"
        body = (
            f"Hi {recruiter_name},\n\n"
            f"Thanks for reaching out - the {role} role at {company} sounds "
            f"great, and I'd love to learn more.{extra}\n\n"
            "Would you be open to a quick call this week to walk through "
            "the role, the team, and next steps? I'm generally free "
            "afternoons ET and can work around your schedule.\n\n"
            "Looking forward to it!\n\n"
            f"Best,\n{name}"
        )
    elif kind == "not_interested":
        extra = f" {detail}" if detail else ""
        subject = f"Re: {role} @ {company} - thanks, not the right fit now"
        body = (
            f"Hi {recruiter_name},\n\n"
            f"Thanks for thinking of me for the {role} role at {company}. "
            f"After some thought I don't think it's the right fit for me "
            f"right now.{extra}\n\n"
            "I'd love to stay in touch - please do keep me in mind for "
            "future roles in this space. Wishing you luck filling this one!\n\n"
            f"Best,\n{name}"
        )
    else:  # need_details
        extra = f" {detail}" if detail else ""
        subject = f"Re: {role} @ {company} - a few questions"
        body = (
            f"Hi {recruiter_name},\n\n"
            f"Thanks for reaching out about the {role} role at {company} - "
            f"it's interesting, and before I decide I'd love a bit more "
            f"detail:{extra}\n\n"
            "- What is the compensation band and leveling for this role?\n"
            "- What does the interview process look like, and what is the timeline?\n"
            "- Is this a new role or a backfill, and which team would I join?\n\n"
            "Happy to jump on a quick call if that's easier.\n\n"
            f"Best,\n{name}"
        )
    return {
        "kind": kind,
        "subject": subject,
        "body": body,
        "timing_note": REPLY_TIMING[kind],
    }


def render_reply(reply: dict) -> str:
    """Render a recruiter_reply() dict as Markdown."""
    if not isinstance(reply, dict) or not reply.get("subject") or not reply.get("body"):
        raise ValueError("reply must be a dict with at least 'subject' and 'body'.")
    md = f"## {reply['subject']}\n\n{reply['body']}\n"
    if reply.get("timing_note"):
        md += f"\n*Timing: {reply['timing_note']}*"
    return md


# ---------------------------------------------------------------------------
# Recruiter call prep
# ---------------------------------------------------------------------------

CALL_QUESTIONS = (
    "What is the compensation band and how is the role leveled?",
    "What team would I join, and who is the hiring manager?",
    "What does the interview process look like, and what is the timeline?",
    "Is visa sponsorship or transfer support available, if relevant?",
    "What is the remote / hybrid policy for this role?",
    "Is this a new role or a backfill - why is it open?",
)

CALL_RED_FLAGS = (
    "Vague or evasive answers about compensation.",
    "Pressure to decide quickly or accept on the spot.",
    "No written offer letter, or reluctance to put terms in writing.",
    "The role described differs from the job posting.",
    "Unwilling to share the interview steps or timeline.",
    "Badmouthing the previous person in the role or other candidates.",
)


def call_prep(role: str, company: str) -> dict:
    """Build a recruiter call-prep checklist for a role.

    Returns {"role", "company", "questions_to_ask", "red_flags"}.
    """
    role = _require(role, "role")
    company = _require(company, "company")
    return {
        "role": role,
        "company": company,
        "questions_to_ask": list(CALL_QUESTIONS),
        "red_flags": list(CALL_RED_FLAGS),
    }


def render_call_prep(prep: dict) -> str:
    """Render a call_prep() dict as a Markdown checklist."""
    if not isinstance(prep, dict) or not prep.get("questions_to_ask"):
        raise ValueError("prep must be a call_prep() dict.")
    lines = [f"## Call prep: {prep.get('role', '?')} @ {prep.get('company', '?')}",
             "", "### Questions to ask"]
    lines += [f"- [ ] {q}" for q in prep["questions_to_ask"]]
    lines += ["", "### Red flags"]
    lines += [f"- {f}" for f in prep.get("red_flags", [])]
    return "\n".join(lines) + "\n"
