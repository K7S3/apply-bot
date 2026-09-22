"""Post-interview follow-ups: thank-you emails and recruiter check-ins.

Drafts are generated from interview context you provide (interviewer name,
topics discussed, your standout moment). Nothing is ever sent automatically —
copy, edit, and send yourself.

Every draft includes a subject line and a short timing note (when to send it).
"""

from __future__ import annotations

TONE_NOTE = {
    "warm": "warm and genuine",
    "formal": "polished and formal",
    "concise": "short and to the point",
    "enthusiastic": "upbeat and openly excited",
}

# When to send each kind of follow-up.
TIMING = {
    "thank_you": "Send within 24 hours of the interview - same evening is ideal, next morning at the latest.",
    "check_in": "Send 5-7 business days after your last contact, or 2 days past any timeline the recruiter gave you - whichever is later.",
    "referral_ask": "Send on a weekday morning; give your contact at least a week before any application deadline.",
}


def _timing_line(kind: str) -> str:
    return f"\n\n*Timing: {TIMING[kind]}*"


def thank_you(name: str, interviewer: str, role: str, company: str,
              topics: str = "", standout: str = "",
              tone: str = "warm") -> str:
    """Draft a thank-you email after an interview round."""
    if tone not in TONE_NOTE:
        raise ValueError(f"Unknown tone '{tone}'. Choose from {list(TONE_NOTE)}.")
    topics = topics or "our conversation about the team's work"
    standout = standout or "how my background maps to the role's challenges"
    if tone == "concise":
        draft = (
            f"Subject: Thank you — {role} interview\n\n"
            f"Hi {interviewer},\n\n"
            f"Thank you for your time today. I enjoyed {topics}, and I'm excited "
            f"about {standout} at {company}.\n\n"
            f"Happy to share anything else that would be helpful.\n\n"
            f"Best,\n{name}"
        )
    elif tone == "formal":
        draft = (
            f"Subject: Thank you for the {role} interview\n\n"
            f"Dear {interviewer},\n\n"
            f"Thank you for taking the time to speak with me about the {role} "
            f"position at {company}. I found {topics} particularly insightful, and "
            f"our discussion reinforced my enthusiasm — especially {standout}.\n\n"
            f"Please let me know if I can provide any additional information. "
            f"I look forward to hearing about next steps.\n\n"
            f"Sincerely,\n{name}"
        )
    elif tone == "enthusiastic":
        draft = (
            f"Subject: So excited about the {role} role!\n\n"
            f"Hi {interviewer},\n\n"
            f"I had to write right away - I loved {topics}! It is exactly the "
            f"kind of problem I want to be working on, and {standout} has me "
            f"even more fired up about the {role} role at {company}.\n\n"
            f"Whatever the next step looks like, count me in.\n\n"
            f"Best,\n{name}"
        )
    else:
        draft = (
            f"Subject: Great speaking with you!\n\n"
            f"Hi {interviewer},\n\n"
            f"Really enjoyed {topics} - it gave me a clear picture of the problems "
            f"the team is tackling, and I left even more excited about the {role} role. "
            f"{standout[0].upper() + standout[1:] if standout else ''} feels like a great fit "
            f"for what you're building at {company}.\n\n"
            f"Thanks again for your time!\n\n"
            f"Best,\n{name}"
        )
    return draft + _timing_line("thank_you")


def check_in(name: str, recruiter: str, role: str, company: str,
             last_contact: str = "", tone: str = "concise") -> str:
    """Draft a recruiter check-in after a quiet stretch."""
    last_contact = last_contact or "we last spoke"
    if tone == "formal":
        body = (
            f"I wanted to follow up on the {role} position at {company}. "
            f"Since {last_contact}, I wanted to check whether there are any updates "
            f"on the process or timeline. I remain very interested in the role."
        )
    elif tone == "warm":
        body = (
            f"Hope you're doing well! Just checking in on the {role} role — "
            f"it's been a little while since {last_contact} and I wanted to see "
            f"where things stand. Still very excited about {company}!"
        )
    elif tone == "enthusiastic":
        body = (
            f"Hi! I keep thinking about the {role} role at {company} - the "
            f"conversations so far have me genuinely excited. It's been a bit "
            f"since {last_contact}, so I wanted to check in: any updates on "
            f"timeline or next steps? I'm ready whenever you are!"
        )
    else:
        body = (
            f"Following up on the {role} role at {company} — any updates since "
            f"{last_contact}? Still very interested."
        )
    return (
        f"Subject: Checking in — {role} @ {company}\n\n"
        f"Hi {recruiter},\n\n{body}\n\nBest,\n{name}"
        + _timing_line("check_in")
    )


def referral_ask(name: str, contact: str, role: str, company: str,
                 connection: str = "") -> str:
    """Draft a referral request to a contact at the company."""
    connection = connection or "your experience there"
    return (
        f"Subject: Quick favor — referral for {role} @ {company}\n\n"
        f"Hi {contact},\n\n"
        f"Hope you're well! I'm applying for the {role} role at {company} — "
        f"{connection} is a big part of why I'm excited about it. "
        f"Would you be comfortable referring me? Happy to send over my resume "
        f"and a blurb to make it easy.\n\n"
        f"No worries at all if not — appreciate you either way!\n\n"
        f"Best,\n{name}"
        + _timing_line("referral_ask")
    )
