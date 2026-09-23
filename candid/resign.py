"""Resignation support: a resignation letter generator and conversation tips.

Everything here is a draft or generic advice. Nothing is sent anywhere -
copy the letter, edit it, and deliver it yourself.

The letter never badmouths anyone. An optional reason is kept to one
neutral line when you supply it. Two tones:

  - "gracious" (default): standard, thankful, offers transition help.
  - "brief": short and professional, minimal detail.
"""

from __future__ import annotations


class ResignError(ValueError):
    """Raised for invalid resignation inputs."""


_LETTER_TONES = ("gracious", "brief")


def _require(label: str, value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ResignError(f"Resignation letter needs a {label}.")
    return value


def _one_neutral_line(reason: str) -> str:
    """Collapse a reason into a single neutral line (no line breaks)."""
    return " ".join(str(reason).split())


def letter(name: str, manager_name: str, company: str, last_day: str,
           tone: str = "gracious", reason: str = "") -> str:
    """Generate a resignation letter.

    ``reason`` is optional; when given it is reduced to one neutral line.
    The letter never criticizes the company, the manager, or the team.
    """
    if tone not in _LETTER_TONES:
        raise ResignError(f"Unknown tone '{tone}'. Choose from {list(_LETTER_TONES)}.")
    name = _require("name", name)
    manager_name = _require("manager name", manager_name)
    company = _require("company", company)
    last_day = _require("last day", last_day)

    reason_line = ""
    clean_reason = _one_neutral_line(reason)
    if clean_reason:
        reason_line = f" This decision reflects {clean_reason}."

    if tone == "brief":
        body = (
            f"Dear {manager_name},\n\n"
            f"Please accept this letter as formal notice of my resignation "
            f"from {company}, effective {last_day}.{reason_line}\n\n"
            f"Thank you for the opportunities here. I am glad to help with "
            f"the handover during my notice period.\n\n"
            f"Best regards,\n{name}"
        )
    else:
        body = (
            f"Dear {manager_name},\n\n"
            f"Please accept this letter as formal notice of my resignation "
            f"from {company}. My last working day will be {last_day}."
            f"{reason_line}\n\n"
            f"Thank you for the opportunities for professional growth you "
            f"have given me. I have genuinely enjoyed working with you and "
            f"the team, and I appreciate the support I have received during "
            f"my time here.\n\n"
            f"I want to make this transition as smooth as possible. Over the "
            f"next few weeks I am happy to document my work, hand off open "
            f"projects, and train whoever takes over my responsibilities - "
            f"just let me know what would help most.\n\n"
            f"Thanks again for everything, and I wish you and the team "
            f"continued success.\n\n"
            f"Sincerely,\n{name}"
        )
    return body


def talking_points() -> list:
    """Dos and don'ts for the resignation conversation.

    The letter is the paperwork; this is the 5-minute conversation that
    comes first.
    """
    return [
        "Do: tell your manager first, before coworkers, Slack, or LinkedIn.",
        "Do: have your resignation letter ready to hand over in the meeting.",
        "Do: keep it short - state your decision, your last day, and your thanks.",
        "Do: expect an exit interview and keep any feedback constructive.",
        "Don't: accept a counteroffer on the spot - say you need time to think it over.",
        "Don't: badmouth anyone or anything - stay positive and neutral.",
        "Don't: over-explain or apologize at length - a calm decision needs no defense.",
        "Don't: burn bridges - you may work with these people again someday.",
    ]
