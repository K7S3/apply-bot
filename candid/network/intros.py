"""Feature 7 - double opt-in introduction builder.

Good intros are double opt-in: you ask each side for permission before
connecting them. This drafts (a) the permission ask and (b) the actual
intro email once both sides say yes. Nothing is sent automatically.
"""

from __future__ import annotations

from candid.network import contacts as CT


def _first(name: str) -> str:
    return name.split()[0] if name else "there"


def intro_ask(your_name: str, asker_id: int, target_id: int,
              context: str = "") -> str:
    """Draft asking the *target* for permission to introduce the asker.

    Use when someone asks you for an intro: you check with the target first.
    """
    asker = CT.get_contact(asker_id)
    target = CT.get_contact(target_id)
    if asker_id == target_id:
        raise ValueError("Cannot introduce a contact to themselves.")
    context = context.strip() or "a conversation that could be useful for both of you"
    return (
        f"Subject: Quick intro request - {asker['name']}\n\n"
        f"Hi {_first(target['name'])},\n\n"
        f"{_first(asker['name'])} {_opt(asker)} asked if I'd connect you two "
        f"for {context}. {_one_line(asker)}\n\n"
        f"Totally fine to say no - but if you're open to it, I'll make a "
        f"short intro email and get out of the way.\n\n"
        f"Best,\n{your_name}"
    )


def _opt(contact: dict) -> str:
    role = contact["role"]
    company = contact["company"]
    who = f"{role}" if role else "a contact of mine"
    if company:
        who += f" at {company}"
    return f"({who})"


def _one_line(contact: dict) -> str:
    bits = []
    if contact["role"] or contact["company"]:
        bits.append(f"{contact['role']}{', ' if contact['role'] and contact['company'] else ''}{contact['company']}".strip(", "))
    if contact["notes"]:
        bits.append(contact["notes"].split(".")[0])
    return ("Background: " + "; ".join(b for b in bits if b) + ".") if bits else ""


def intro_email(your_name: str, a_id: int, b_id: int,
                shared_context: str = "", ask: str = "") -> str:
    """Draft the intro email once both sides opted in.

    Convention: the person who benefits most / asked for the intro goes in
    To; move yourself to BCC after sending.
    """
    a = CT.get_contact(a_id)
    b = CT.get_contact(b_id)
    if a_id == b_id:
        raise ValueError("Cannot introduce a contact to themselves.")
    shared_context = shared_context.strip() or "your shared interests"
    ask = ask.strip() or "I'll let you two take it from here"
    return (
        f"Subject: Intro: {a['name']} <> {b['name']}\n\n"
        f"Hi {_first(a['name'])} and {_first(b['name'])},\n\n"
        f"Connecting you two around {shared_context}.\n\n"
        f"{_first(a['name'])} - {_one_line(a) or 'a contact I think highly of.'}\n"
        f"{_first(b['name'])} - {_one_line(b) or 'a contact I think highly of.'}\n\n"
        f"{ask} - moving myself to BCC.\n\n"
        f"Best,\n{your_name}"
    )


def intro_checklist() -> str:
    return (
        "Double opt-in intro checklist:\n"
        "  1. Ask the target (busier / more senior side) for permission first.\n"
        "  2. Ask the requester what they'd like the target to know.\n"
        "  3. Send one short email with both opted in; put the asker in To.\n"
        "  4. Move yourself to BCC so they can talk freely.\n"
        "  5. Follow up with both sides once - did they connect?"
    )
