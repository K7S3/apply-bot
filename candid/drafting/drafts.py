"""Template-based email draft generator for candid.

This module *generates draft text only*. It never sends email, opens
sockets, or touches the network. Drafts are returned as plain dicts for
the user to review, copy, and send themselves.

Placeholders follow Python ``str.format`` syntax (``{company}``,
``{role}``, ...). Any placeholder that has no value in the supplied
context is left in place verbatim and reported in the ``missing`` list
of the returned dict, so the user can fill it in by hand.
"""

from __future__ import annotations

from string import Formatter

#: All supported draft kinds. New kinds must be added here AND in
#: ``_TEMPLATES`` (tests enforce this).
KINDS = [
    "thank_you",
    "check_in",
    "referral_request",
    "post_interview",
    "offer_stall",
    "rejection_thanks",
    "cold_intro",
]

#: Supported tones. Every kind provides a "professional" template;
#: other tones fall back to it when not defined for a given kind.
TONES = ["professional", "friendly", "concise"]

_FORMATTER = Formatter()


def _fill(template: str, context: dict) -> tuple[str, list[str]]:
    """Fill ``{placeholders}`` from ``context``.

    Returns ``(filled_text, missing)`` where ``missing`` lists the
    placeholder names that had no value. Unfilled placeholders stay in
    the text as-is (e.g. ``{company}``) so they are visible to the
    user.
    """
    missing: list[str] = []
    parts: list[str] = []
    for literal, field, fmt, conv in _FORMATTER.parse(template):
        parts.append(literal)
        if field is None:
            continue
        if conv or fmt:
            # We only support plain {name} placeholders.
            missing.append(field)
            parts.append("{" + field + "}")
            continue
        if field in context and context[field] is not None and context[field] != "":
            parts.append(str(context[field]))
        else:
            missing.append(field)
            parts.append("{" + field + "}")
    return "".join(parts), missing


_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    # ------------------------------------------------------------------
    # thank_you: right after applying or a screening call.
    # ------------------------------------------------------------------
    "thank_you": {
        "professional": {
            "subject": "Thank you - {role} at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "Thank you for taking the time to speak with me about the {role} "
                "position at {company}.\n"
                "I enjoyed learning more about {topic} and I am excited about the "
                "opportunity to contribute.\n"
                "Please let me know if I can share anything further.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Great speaking with you - {role} at {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thanks so much for chatting with me today about the {role} role at {company}!\n"
                "I really enjoyed hearing about {topic}, and I'm excited about what the team is building.\n"
                "Happy to share anything else that would be helpful.\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Thanks - {role}, {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thank you for your time today discussing the {role} role at {company}.\n"
                "I'm excited about the opportunity and happy to provide anything further.\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # check_in: polite follow-up after applying with no response yet.
    # ------------------------------------------------------------------
    "check_in": {
        "professional": {
            "subject": "Checking in - {role} application at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "I hope you are well. I applied for the {role} position at {company} on "
                "{applied_date} and wanted to check whether the role is still open.\n"
                "I would welcome the chance to discuss how my background fits the team's needs.\n"
                "Thank you for your consideration.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Quick check-in on my {role} application",
            "body": (
                "Hi {contact_name},\n\n"
                "Hope you're doing well! I applied for the {role} role at {company} on "
                "{applied_date} and wanted to check in on the status.\n"
                "I'd love to chat about how I could contribute to the team.\n"
                "Thanks so much!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Follow-up: {role} application ({company})",
            "body": (
                "Hi {contact_name},\n\n"
                "Following up on my application for the {role} role at {company}, submitted "
                "{applied_date}.\n"
                "Is the role still open, and is there anything else I can provide?\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # referral_request: ask a contact for an employee referral.
    # ------------------------------------------------------------------
    "referral_request": {
        "professional": {
            "subject": "Referral request - {role} at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "I hope this message finds you well. I noticed the {role} opening at {company} "
                "and, given your experience there, I would be grateful for a referral.\n"
                "I've attached my resume for your reference, and I'm happy to share a short "
                "summary of why I'm a strong fit.\n"
                "I completely understand if it isn't possible - thank you either way.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Could you refer me for the {role} role?",
            "body": (
                "Hi {contact_name},\n\n"
                "Hope you're doing well! I saw the {role} opening at {company} and it looks "
                "like a great fit.\n"
                "Would you be open to referring me? I've attached my resume to make it easy.\n"
                "No worries at all if not - appreciate you considering it!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Referral for {role} at {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Would you be open to referring me for the {role} role at {company}?\n"
                "Resume attached; happy to share a short blurb on my fit.\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # post_interview: thank-you after an interview round.
    # ------------------------------------------------------------------
    "post_interview": {
        "professional": {
            "subject": "Thank you for the interview - {role} at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "Thank you for the conversation with {interviewer_names} about the {role} "
                "position at {company}.\n"
                "Our discussion of {topic} reinforced my enthusiasm for the role and the team.\n"
                "I look forward to hearing about next steps.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Thanks for a great interview - {role} at {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thanks so much for arranging the interview with {interviewer_names} for the "
                "{role} role at {company}!\n"
                "I really enjoyed our conversation about {topic}, and I'm even more excited "
                "about the opportunity.\n"
                "Looking forward to next steps!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Thanks - {role} interview at {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thank you for the interview with {interviewer_names} for the {role} role.\n"
                "I enjoyed discussing {topic} and remain excited about the opportunity.\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # offer_stall: politely ask for more time to decide on an offer.
    # ------------------------------------------------------------------
    "offer_stall": {
        "professional": {
            "subject": "Offer decision timeline - {role} at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "Thank you again for the offer for the {role} position at {company} - I am "
                "genuinely excited about the opportunity.\n"
                "To make a thoughtful decision, would it be possible to extend the deadline "
                "to {decision_date}?\n"
                "I appreciate your understanding and will confirm by then either way.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Quick ask on the offer timeline ({role}, {company})",
            "body": (
                "Hi {contact_name},\n\n"
                "Thank you so much for the offer for the {role} role at {company} - I'm really "
                "excited about it!\n"
                "Would it be possible to have until {decision_date} to make my final decision? "
                "I want to give it the thought it deserves.\n"
                "Really appreciate your flexibility!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Offer deadline extension request - {role}, {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thank you for the {role} offer at {company}.\n"
                "Would an extension to {decision_date} be possible so I can decide carefully?\n"
                "I will confirm by then either way.\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # rejection_thanks: gracious reply to a rejection, keeping the door open.
    # ------------------------------------------------------------------
    "rejection_thanks": {
        "professional": {
            "subject": "Thank you - {role} at {company}",
            "body": (
                "Dear {contact_name},\n\n"
                "Thank you for letting me know about your decision on the {role} position at "
                "{company}.\n"
                "I appreciated the chance to speak with the team, and I remain enthusiastic "
                "about {company} - please keep me in mind for future openings.\n"
                "I wish you and the team every success.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Thanks for the update - {role} at {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thanks for the update on the {role} role at {company}.\n"
                "I really enjoyed meeting the team, and I'd love to be considered for future "
                "openings - {company} is doing exciting work.\n"
                "Wishing you all the best!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "Thank you - {role}, {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "Thank you for the update on the {role} role.\n"
                "I'd welcome consideration for future openings at {company}.\n\n"
                "{user_name}"
            ),
        },
    },
    # ------------------------------------------------------------------
    # cold_intro: cold outreach to a hiring manager or team member.
    # ------------------------------------------------------------------
    "cold_intro": {
        "professional": {
            "subject": "Introduction - {user_name}, {target_role} candidate",
            "body": (
                "Dear {contact_name},\n\n"
                "I'm {user_name}, a {target_role} based in {location}. I came across {company} "
                "through {source} and was impressed by the team's work on {topic}.\n"
                "I'd welcome a brief conversation about whether my background could be a fit "
                "for your team.\n"
                "Thank you for your time.\n\n"
                "Best regards,\n{user_name}"
            ),
        },
        "friendly": {
            "subject": "Hello from a fellow {target_role} - loved what {company} is doing",
            "body": (
                "Hi {contact_name},\n\n"
                "I'm {user_name}, a {target_role} based in {location}! I found {company} through "
                "{source} and was really impressed by the work on {topic}.\n"
                "Would you be open to a quick chat about the team and any upcoming roles?\n"
                "Thanks so much for your time!\n\n"
                "Best,\n{user_name}"
            ),
        },
        "concise": {
            "subject": "{target_role} interested in {company}",
            "body": (
                "Hi {contact_name},\n\n"
                "I'm {user_name}, a {target_role} based in {location} who found {company} via "
                "{source}.\n"
                "Open to a brief chat about fit for your team?\n\n"
                "{user_name}"
            ),
        },
    },
}


def _templates_for(kind: str) -> dict[str, dict[str, str]]:
    """Return the tone->template mapping for ``kind`` (KeyError if unknown)."""
    if kind not in _TEMPLATES:
        raise ValueError(
            f"Unknown draft kind {kind!r}. Supported kinds: {sorted(_TEMPLATES)}"
        )
    return _TEMPLATES[kind]


def generate(kind: str, context: dict, tone: str = "professional") -> dict:
    """Generate a draft email of the given ``kind``.

    Args:
        kind: one of :data:`KINDS` (e.g. ``"thank_you"``).
        context: mapping of placeholder names to values, e.g.
            ``{"company": "Acme", "role": "MLE", "contact_name": "Priya",
            "user_name": "Keshavan"}``.
        tone: ``"professional"`` (default), ``"friendly"``, or ``"concise"``.

    Returns:
        dict with keys:

        - ``subject``: filled subject line.
        - ``body``: filled email body.
        - ``kind``: the requested kind.
        - ``tone``: the tone used (falls back to ``"professional"``).
        - ``missing``: sorted list of placeholder names with no value in
          ``context``. Their ``{placeholder}`` text is left in place in
          ``subject``/``body`` for the user to fill in.

    This function only builds text. It never sends anything.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown draft kind {kind!r}. Expected one of {KINDS}.")
    tone_key = tone if tone in TONES else "professional"
    variants = _templates_for(kind)
    tpl = variants.get(tone_key, variants["professional"])

    subject, missing_s = _fill(tpl["subject"], context)
    body, missing_b = _fill(tpl["body"], context)
    missing = sorted(set(missing_s) | set(missing_b))
    return {
        "subject": subject,
        "body": body,
        "kind": kind,
        "tone": tone_key,
        "missing": missing,
    }
