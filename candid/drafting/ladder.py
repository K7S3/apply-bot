"""Follow-up tone ladder: escalate follow-up tone by days since last contact.

Deterministic, template-based, and stage-aware. Nothing here sends email,
opens sockets, or makes network calls -- it only computes the rung and
renders draft text the user can review, copy, and send themselves.

Rungs (base thresholds, in days of silence):
    1 gentle nudge        3-7 days
    2 warm check-in       8-14 days
    3 firmer nudge        15-21 days
    4 break-up / close the loop   22+ days
    0 too early           < 3 days (no follow-up yet)

Stage adjustments shift the *effective* day count before mapping to a
rung, because some stages escalate faster than others:
    - post-interview (selected_for_interview): faster (+2 effective days)
    - offer: slower (-3 effective days), offers take patience
    - everything else (applied, saved, rejected, withdrawn): 0
"""

from __future__ import annotations

# --- rung table: rung -> (first_day, last_day, name, tone, guidance) -------
_RUNGS = {
    0: (
        "Too early to follow up",
        "none",
        "Wait until at least day 3 of silence before following up. "
        "Following up earlier usually reads as impatience.",
    ),
    1: (
        "Gentle nudge",
        "gentle",
        "Keep it light: one or two sentences, assume good intent, express "
        "continued interest, no urgency. Do not apologize for following up.",
    ),
    2: (
        "Warm check-in",
        "warm",
        "Restate your enthusiasm, add one small thing of value (a link, a "
        "thought, availability), and make replying effortless with a single "
        "easy question.",
    ),
    3: (
        "Firmer nudge",
        "firm",
        "Be direct about the timeline: name the silence, ask for a concrete "
        "next step or an honest no. Respectful, specific, no guilt-tripping.",
    ),
    4: (
        "Break-up / close the loop",
        "final",
        "Offer a graceful exit: say you'll assume it's a no and move on "
        "unless they say otherwise. Short, gracious, leaves the door open.",
    ),
}

# (day_start, rung) boundaries on *effective* days; searched in order.
_BOUNDARIES = [(22, 4), (15, 3), (8, 2), (3, 1)]

# stage -> effective-day offset (positive = escalates faster)
_STAGE_OFFSETS = {
    "selected_for_interview": 2,
    "offer": -3,
}


def ladder_for(days_since_contact: int, stage: str) -> dict:
    """Map days of silence + application stage to a tone-ladder rung.

    Returns {"rung", "rung_name", "tone", "guidance"}.

    Post-interview stages escalate faster (+2 effective days); the offer
    stage runs slower (-3 effective days). Unknown stages use no offset.
    """
    days = max(0, int(days_since_contact))
    offset = _STAGE_OFFSETS.get((stage or "").strip(), 0)
    effective = days + offset
    rung = 0
    for day_start, r in _BOUNDARIES:
        if effective >= day_start:
            rung = r
            break
    name, tone, guidance = _RUNGS[rung]
    return {
        "rung": rung,
        "rung_name": name,
        "tone": tone,
        "guidance": guidance,
        "stage": (stage or "").strip(),
        "days_since_contact": days,
        "effective_days": effective,
    }


# --- deterministic rung templates ------------------------------------------
_TEMPLATES = {
    1: {
        "subject": "Following up: {role} at {company}",
        "body": (
            "Hi {contact_name},\n\n"
            "Just a gentle nudge on my application for the {role} role at "
            "{company}. I'm still very interested, and happy to share "
            "anything that would help at this stage.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
    2: {
        "subject": "Checking in on {role} at {company}",
        "body": (
            "Hi {contact_name},\n\n"
            "Circling back on the {role} role at {company}. I'm excited about "
            "the team and the work, so I wanted to check in and see where "
            "things stand.\n\n"
            "Is there anything else I can share that would be helpful?\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
    3: {
        "subject": "Next steps for {role} at {company}?",
        "body": (
            "Hi {contact_name},\n\n"
            "I last reached out on {last_contact_date} about the {role} role "
            "at {company}, and I haven't heard back, so I wanted to be "
            "direct: is this still moving forward?\n\n"
            "A quick yes or no is perfectly fine, I just appreciate knowing "
            "where things stand.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
    4: {
        "subject": "Closing the loop on {role} at {company}",
        "body": (
            "Hi {contact_name},\n\n"
            "I'll assume the timing isn't right for the {role} role at "
            "{company} and stop following up, unless I hear otherwise. No "
            "hard feelings at all, and I'd love to stay in touch for future "
            "roles.\n\n"
            "Wishing you and the team the best,\n"
            "{sender_name}"
        ),
    },
    0: {
        "subject": "Follow-up draft: {role} at {company} (not due yet)",
        "body": (
            "Hi {contact_name},\n\n"
            "Not due yet, draft only. Your last contact about the {role} role "
            "at {company} was on {last_contact_date}; wait until at least "
            "3 days of silence before following up.\n\n"
            "Best,\n"
            "{sender_name}"
        ),
    },
}


def render_ladder_draft(ladder: dict, context: dict) -> dict:
    """Render a deterministic draft for a ladder rung.

    ladder: a dict from ladder_for() (uses its "rung" key).
    context: keys used are company, role, contact_name, last_contact_date,
    and optionally sender_name. Missing keys fall back to placeholders;
    empty/blank values are treated as missing too.

    Returns {"subject", "body"}.
    """
    ctx = context or {}
    rung = int((ladder or {}).get("rung", 0))
    template = _TEMPLATES.get(rung, _TEMPLATES[0])
    fields = {
        "company": (ctx.get("company") or "[company]").strip() or "[company]",
        "role": (ctx.get("role") or "[role]").strip() or "[role]",
        "contact_name": (ctx.get("contact_name") or "there").strip() or "there",
        "last_contact_date": (ctx.get("last_contact_date") or "[date]").strip()
        or "[date]",
        "sender_name": (ctx.get("sender_name") or "[your name]").strip()
        or "[your name]",
    }
    return {
        "subject": template["subject"].format(**fields),
        "body": template["body"].format(**fields),
        "rung": rung,
    }
