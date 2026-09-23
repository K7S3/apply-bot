"""Cold outreach sequences and follow-up escalation ladders.

Everything here is drafts - nothing is ever sent automatically. Each touch is
a starting template: copy it, fill in the bracketed bits with your own words,
and send it yourself.

Two tools:

- plan_sequence / render_sequence: a 4-touch cold outreach sequence with
  deliberate spacing (day 0, 4, 11, 21) so you stay visible without pestering.
- ladder / render_ladder: a 3-stage follow-up escalation ladder for when a
  recruiter goes quiet after contact, ending with a graceful close that
  keeps the door open.

Timing language matches candid.followup (5-7 business days after last
contact) and candid.nudges (FOLLOW_UP_AFTER_DAYS = 5): this module only
supplies the draft copy and timing notes, never the reminder scheduling.
"""

from __future__ import annotations


class OutreachError(ValueError):
    """Bad input to an outreach builder. Message tells you how to fix it."""


def _require(value: str, field: str) -> str:
    """Strip a required string; raise an actionable error if it is empty."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise OutreachError(
            f"{field} is required and cannot be blank. "
            f"Pass it like {field.lower().replace(' ', '_')}='...', "
            "e.g. name='Keshavan', role='ML Engineer', company='Acme'."
        )
    return cleaned


# spacing of the cold outreach touches, in days after the first send
SEQUENCE_DAYS = [0, 4, 11, 21]
# spacing of the escalation ladder stages, in days after the previous stage
LADDER_STAGE_DAYS = [0, 7, 14]


def _default_context(role: str, company: str) -> str:
    return (
        f"I have been following what {company} is building, and the {role} "
        "role lines up closely with the kind of work I do best."
    )


def plan_sequence(name: str, target_name: str, role: str, company: str,
                  context: str = "") -> list[dict]:
    """Build a 4-touch cold outreach sequence as a list of touch dicts.

    Each touch: {step, subject, body, send_after_days, timing_note}.
    Spacing: initial (day 0), light bump (day 4), value-add (day 11),
    graceful close (day 21). If any touch gets a reply, stop the sequence.
    """
    name = _require(name, "Your name")
    target_name = _require(target_name, "Target name")
    role = _require(role, "Role")
    company = _require(company, "Company")
    context = (context or "").strip() or _default_context(role, company)

    touch1_subject = f"Quick intro - {role} at {company}"
    touch1_body = (
        f"Hi {target_name},\n\n"
        f"I'm {name}. {context}\n\n"
        "Would you be open to a brief intro chat about how I could contribute? "
        "Happy to work around your schedule.\n\n"
        f"Best,\n{name}"
    )
    touch1_note = (
        "Send on day 0 (today). Morning on a Tuesday-Thursday works best. "
        "If they reply, stop the sequence - this plan is for silence only."
    )

    touch2_subject = f"Bumping this up - {role} at {company}"
    touch2_body = (
        f"Hi {target_name},\n\n"
        "Just floating my note from a few days ago back to the top of your "
        f"inbox. I'm {name}, and I'm keen to talk about the {role} role at "
        f"{company} if the team is still hiring for it.\n\n"
        "Even a two-line reply ('not now' or 'not the right fit') would be "
        "appreciated - no hard feelings either way.\n\n"
        f"Best,\n{name}"
    )
    touch2_note = (
        "Send 4 days after touch 1, only if you heard nothing. Keep it light - "
        "the job of this email is just to be seen, not to re-pitch."
    )

    touch3_subject = f"Thought you might find this relevant - {company}"
    touch3_body = (
        f"Hi {target_name},\n\n"
        f"I came across something in {company}'s recent work that I couldn't "
        "help but notice: [insert a genuine observation here - a product "
        "launch, a blog post, an open-source release, a talk someone on the "
        "team gave]. It lines up with problems I have solved in the past, and "
        "it is part of why I am so interested in the "
        f"{role} role.\n\n"
        "If it would be useful, I can write up a short take on how I would "
        "approach that kind of challenge. Worth a quick call to compare notes?\n\n"
        f"Best,\n{name}"
    )
    touch3_note = (
        "Send 11 days after touch 1, only if still silent. This is the "
        "value-add touch: lead with a real observation about the company's "
        "work, not another pitch about yourself. Replace the bracketed part "
        "with something specific you actually noticed."
    )

    touch4_subject = f"Closing the loop - {role} at {company}"
    touch4_body = (
        f"Hi {target_name},\n\n"
        "I have reached out a couple of times about the "
        f"{role} role at {company}, so I'll keep this last one short: I "
        "don't want to be a pest, and I get that the timing might just be "
        "off.\n\n"
        "If there is interest now or later, I'm easy to reach. Otherwise, "
        "feel free to ignore this and I'll close the loop on my end.\n\n"
        f"All the best with what the team is building,\n{name}"
    )
    touch4_note = (
        "Send 21 days after touch 1 - this is the final touch, always. "
        "The graceful breakup respects their inbox and often gets the "
        "polite reply ('not now, but ping me later') that keeps the door open."
    )

    return [
        {"step": 1, "subject": touch1_subject, "body": touch1_body,
         "send_after_days": SEQUENCE_DAYS[0], "timing_note": touch1_note},
        {"step": 2, "subject": touch2_subject, "body": touch2_body,
         "send_after_days": SEQUENCE_DAYS[1], "timing_note": touch2_note},
        {"step": 3, "subject": touch3_subject, "body": touch3_body,
         "send_after_days": SEQUENCE_DAYS[2], "timing_note": touch3_note},
        {"step": 4, "subject": touch4_subject, "body": touch4_body,
         "send_after_days": SEQUENCE_DAYS[3], "timing_note": touch4_note},
    ]


def render_sequence(name: str, target_name: str, role: str, company: str,
                    context: str = "") -> str:
    """Render the cold outreach sequence as Markdown, with timing notes."""
    touches = plan_sequence(name, target_name, role, company, context)
    name = (name or "").strip()
    target_name = (target_name or "").strip()
    role = (role or "").strip()
    company = (company or "").strip()
    lines = [
        f"# Cold outreach sequence: {role} at {company}",
        "",
        f"From **{name}** to **{target_name}** - 4 touches over 21 days.",
        "Send each touch only if the previous one got no reply.",
        "",
    ]
    for t in touches:
        lines.append(
            f"## Touch {t['step']} - day {t['send_after_days']}")
        lines.append("")
        lines.append(f"**Subject:** {t['subject']}")
        lines.append("")
        lines.append(f"*Timing: {t['timing_note']}*")
        lines.append("")
        lines.append(t["body"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def ladder(name: str, recruiter_name: str, role: str, company: str,
           last_contact: str = "") -> list[dict]:
    """Build a 3-stage follow-up escalation ladder.

    Each stage: {stage, subject, body, timing_note}.
    Stage 1 is a polite nudge 5-7 business days after last contact
    (compatible with candid.nudges FOLLOW_UP_AFTER_DAYS = 5 and the
    candid.followup check-in timing note), stage 2 is firmer with a
    clear ask and deadline (+7 days), stage 3 closes the loop while
    leaving the door open (+7 more days). Move to the next stage only
    if the previous one got no reply.
    """
    name = _require(name, "Your name")
    recruiter_name = _require(recruiter_name, "Recruiter name")
    role = _require(role, "Role")
    company = _require(company, "Company")
    last_contact = (last_contact or "").strip() or "our last conversation"

    stage1_subject = f"Checking in - {role} at {company}"
    stage1_body = (
        f"Hi {recruiter_name},\n\n"
        f"Wanted to check in on the {role} process at {company}. It's been "
        f"a little while since {last_contact}, and I wanted to see where "
        "things stand on timing or next steps.\n\n"
        "I'm still very interested. Happy to provide anything that would "
        "help move things along.\n\n"
        f"Best,\n{name}"
    )
    stage1_note = (
        "Send 5-7 business days after your last contact, or 2 days past any "
        "timeline the recruiter gave you - whichever is later. (Matches the "
        "candid.followup check-in timing and the candid.nudges follow_up_due "
        "threshold of 5 days.)"
    )

    stage2_subject = f"Following up - next steps for {role} at {company}"
    stage2_body = (
        f"Hi {recruiter_name},\n\n"
        f"Following up once more on the {role} role at {company}. I know "
        "things get busy, so I want to be direct: could you let me know by "
        "[date, about a week from now] whether I'm still in the running, "
        "and what the timeline looks like if so?\n\n"
        "A clear yes, no, or 'not yet' all work for me - I just want to plan "
        "my side accordingly.\n\n"
        f"Thanks,\n{name}"
    )
    stage2_note = (
        "Send about 7 days after stage 1 if still silent. This is the "
        "firmer nudge: one clear ask (status + timeline) and a concrete "
        "deadline. Replace the bracketed date before sending."
    )

    stage3_subject = f"Closing the loop - {role} at {company}"
    stage3_body = (
        f"Hi {recruiter_name},\n\n"
        "I have checked in a couple of times without hearing back, so I'll "
        "assume the timing isn't right for the "
        f"{role} role at {company} and close the loop on my end.\n\n"
        "No hard feelings at all - if things change down the line, I'd love "
        "to reconnect. Wishing you and the team well.\n\n"
        f"Best,\n{name}"
    )
    stage3_note = (
        "Send about 7 days after stage 2 - the final nudge, always. It ends "
        "the thread on a warm note, keeps the relationship intact, and often "
        "prompts the honest answer you were waiting for."
    )

    return [
        {"stage": 1, "subject": stage1_subject, "body": stage1_body,
         "timing_note": stage1_note},
        {"stage": 2, "subject": stage2_subject, "body": stage2_body,
         "timing_note": stage2_note},
        {"stage": 3, "subject": stage3_subject, "body": stage3_body,
         "timing_note": stage3_note},
    ]


def render_ladder(name: str, recruiter_name: str, role: str, company: str,
                  last_contact: str = "") -> str:
    """Render the follow-up escalation ladder as Markdown, with timing notes."""
    stages = ladder(name, recruiter_name, role, company, last_contact)
    name = (name or "").strip()
    recruiter_name = (recruiter_name or "").strip()
    role = (role or "").strip()
    company = (company or "").strip()
    lines = [
        f"# Follow-up escalation ladder: {role} at {company}",
        "",
        f"From **{name}** to **{recruiter_name}** - 3 stages, escalating only "
        "on silence.",
        "",
    ]
    for s in stages:
        lines.append(f"## Stage {s['stage']}")
        lines.append("")
        lines.append(f"**Subject:** {s['subject']}")
        lines.append("")
        lines.append(f"*Timing: {s['timing_note']}*")
        lines.append("")
        lines.append(s["body"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
