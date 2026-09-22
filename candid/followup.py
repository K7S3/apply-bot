"""Post-interview follow-ups: thank-you emails and recruiter check-ins.

Drafts are generated from interview context you provide (interviewer name,
topics discussed, your standout moment). Nothing is ever sent automatically —
copy, edit, and send yourself.
"""

from __future__ import annotations

TONE_NOTE = {
    "warm": "warm and genuine",
    "formal": "polished and formal",
    "concise": "short and to the point",
}


def thank_you(name: str, interviewer: str, role: str, company: str,
              topics: str = "", standout: str = "",
              tone: str = "warm") -> str:
    """Draft a thank-you email after an interview round."""
    if tone not in TONE_NOTE:
        raise ValueError(f"Unknown tone '{tone}'. Choose from {list(TONE_NOTE)}.")
    topics = topics or "our conversation about the team's work"
    standout = standout or "how my background maps to the role's challenges"
    if tone == "concise":
        return (
            f"Subject: Thank you — {role} interview\n\n"
            f"Hi {interviewer},\n\n"
            f"Thank you for your time today. I enjoyed {topics}, and I'm excited "
            f"about {standout} at {company}.\n\n"
            f"Happy to share anything else that would be helpful.\n\n"
            f"Best,\n{name}"
        )
    if tone == "formal":
        return (
            f"Subject: Thank you for the {role} interview\n\n"
            f"Dear {interviewer},\n\n"
            f"Thank you for taking the time to speak with me about the {role} "
            f"position at {company}. I found {topics} particularly insightful, and "
            f"our discussion reinforced my enthusiasm — especially {standout}.\n\n"
            f"Please let me know if I can provide any additional information. "
            f"I look forward to hearing about next steps.\n\n"
            f"Sincerely,\n{name}"
        )
    return (
        f"Subject: Great speaking with you!\n\n"
        f"Hi {interviewer},\n\n"
        f"Really enjoyed {topics} — it gave me a clear picture of the problems "
        f"the team is tackling, and I left even more excited about the {role} role. "
        f"{standout[0].upper() + standout[1:] if standout else ''} feels like a great fit "
        f"for what you're building at {company}.\n\n"
        f"Thanks again for your time!\n\n"
        f"Best,\n{name}"
    )


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
    else:
        body = (
            f"Following up on the {role} role at {company} — any updates since "
            f"{last_contact}? Still very interested."
        )
    return (
        f"Subject: Checking in — {role} @ {company}\n\n"
        f"Hi {recruiter},\n\n{body}\n\nBest,\n{name}"
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
    )
