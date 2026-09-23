"""Feature 9 - thank-you drafts after help or referrals.

Distinct from interview thank-yous (candid.followup): these are for the
networking side - someone made an intro, gave advice, referred you, or
helped in some other way. Includes timing guidance.
"""

from __future__ import annotations

TONE_NOTE = {
    "warm": "warm and genuine",
    "formal": "polished and formal",
    "concise": "short and to the point",
}

TIMING = {
    "referral": "Send within 24 hours of the referral - and again with an "
                "update once you hear back from the company.",
    "intro": "Thank the connector the same day the intro email goes out.",
    "advice": "Thank them within a day or two; the real thank-you is "
              "reporting back what you did with their advice.",
    "help": "Send within 48 hours while the help is fresh.",
}


def thank_you(your_name: str, helper: str, kind: str = "help",
              what: str = "", specifics: str = "",
              tone: str = "warm") -> str:
    """Draft a thank-you note to someone who helped you network.

    kind: referral | intro | advice | help
    """
    if kind not in TIMING:
        raise ValueError(f"Unknown kind '{kind}'. Choose from: "
                         f"{', '.join(TIMING)}.")
    if tone not in TONE_NOTE:
        raise ValueError(f"Unknown tone '{tone}'. Choose from: "
                         f"{list(TONE_NOTE)}.")
    what = what.strip() or "your help"
    specifics = specifics.strip()
    first = helper.split()[0]

    subjects = {
        "referral": f"Thank you for the referral - {what}",
        "intro": f"Thank you for the intro to {what}",
        "advice": "Thank you for the advice",
        "help": f"Thank you - {what}",
    }
    openers = {
        "referral": f"wanted to thank you for referring me for {what}",
        "intro": f"thank you for introducing me around {what}",
        "advice": "thank you for the thoughtful advice",
        "help": f"thank you for helping with {what}",
    }
    if tone == "concise":
        body = (f"Hi {first},\n\nJust {openers[kind]}. Really appreciate you "
                f"taking the time.\n\nBest,\n{your_name}")
    elif tone == "formal":
        body = (f"Dear {helper},\n\nI wanted to express my sincere gratitude - "
                f"{openers[kind]}. Your support means a great deal, and I "
                f"will keep you posted on how it goes.\n\n"
                f"With appreciation,\n{your_name}")
    else:
        extra = f" {specifics}" if specifics else ""
        body = (f"Hi {first},\n\nI just wanted to say {openers[kind]} - "
                f"it genuinely helped.{extra}\n\n"
                f"I'll keep you posted on how things go, and please let me "
                f"know if there's ever anything I can do for you.\n\n"
                f"Thanks again,\n{your_name}")
    return (f"Subject: {subjects[kind]}\n\n{body}"
            f"\n\n*Timing: {TIMING[kind]}*")
