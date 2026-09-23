"""Nonprofit / mission-driven interview prep.

A question bank of real nonprofit interview questions found through public
web research (each entry carries a verified source URL, same schema as
``candid.prep_questions``), plus:

- ``get_questions`` / ``render_questions`` for CLI display,
- ``org_status`` for a transparent, heuristic nonprofit-likelihood check
  with a PSLF explainer (links only, no scraping, no network calls),
- ``mission_pitch_helper`` to scaffold a "why this mission" answer from
  the user's own background text. It structures their words and invents
  nothing.

All data is baked in. Nothing here makes network calls.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Nonprofit question bank: real questions from published nonprofit
# interviewing guides. Fields mirror prep_questions.QUESTIONS_DB:
# q, category, source, url, reported.
# Categories used here: "mission" (alignment), "behavioral", "situational".
# Every URL below was fetched and confirmed to list the question.
# ---------------------------------------------------------------------------

NONPROFIT_QUESTIONS: list[dict] = [
    {
        "q": "Describe your passion for our mission.",
        "category": "mission",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "Why do you want to work for our nonprofit?",
        "category": "mission",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "Could you describe a few situations in which your work was criticized? How did you handle it?",
        "category": "behavioral",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "What improvements did you enact in your last position? What were some obstacles you faced?",
        "category": "behavioral",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "What skills or abilities have you not yet put into play in your career?",
        "category": "behavioral",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "What motivates you?",
        "category": "behavioral",
        "source": "Alabama Association of Nonprofits - 'How to Answer Tough Interview Questions'",
        "url": "https://careers.alabamanonprofits.org/career-resources/get-the-job-2/how-to-answer-tough-interview-questions-9",
        "reported": "undated guide",
    },
    {
        "q": "Tell me about your approach to motivating employees.",
        "category": "situational",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "Do you feel comfortable working within a limited budget?",
        "category": "situational",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "Describe a successful fundraising campaign you spearheaded. What do you think of our nonprofit's current fundraising strategy?",
        "category": "situational",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "How comfortable are you working with volunteers?",
        "category": "situational",
        "source": "TruPath Search - 'Top 8 Nonprofit Interview Questions To Ask'",
        "url": "https://trupathsearch.com/top-8-nonprofit-interview-questions-to-ask/",
        "reported": "undated guide",
    },
    {
        "q": "What are the resources you'll need for your campaign?",
        "category": "situational",
        "source": "Idealist - Marcella Vitulli, 'How to Approach a Nonprofit Job Interview with a For-Profit Attitude (and Resume)'",
        "url": "https://www.idealist.org/en/careers/how-to-approach-a-nonprofit-job-interview-with-a-for-profit-attitude-and-resume",
        "reported": "undated guide",
    },
    {
        "q": "What will be your outreach plan to make sure your audiences and influential players in your space hear about it?",
        "category": "situational",
        "source": "Idealist - Marcella Vitulli, 'How to Approach a Nonprofit Job Interview with a For-Profit Attitude (and Resume)'",
        "url": "https://www.idealist.org/en/careers/how-to-approach-a-nonprofit-job-interview-with-a-for-profit-attitude-and-resume",
        "reported": "undated guide",
    },
    {
        "q": "How will you measure your campaign's success?",
        "category": "situational",
        "source": "Idealist - Marcella Vitulli, 'How to Approach a Nonprofit Job Interview with a For-Profit Attitude (and Resume)'",
        "url": "https://www.idealist.org/en/careers/how-to-approach-a-nonprofit-job-interview-with-a-for-profit-attitude-and-resume",
        "reported": "undated guide",
    },
]

VALID_CATEGORIES = {"mission", "behavioral", "situational"}

# Keyword markers used by org_status(). Heuristic only: a match means the
# name *looks* nonprofit-ish, not that the org is one.
NONPROFIT_MARKERS = [
    "foundation",
    "fund",
    "charity",
    "nonprofit",
    "non-profit",
    "institute",
    "coalition",
    "alliance",
    "center for",
    "association",
    "trust",
    "society",
    "philanthropy",
    "relief",
    "mission-driven",
]

PSLF_NOTE = (
    "Public Service Loan Forgiveness (PSLF): employment with a 501(c)(3) "
    "nonprofit or a government employer (federal, state, local, or tribal) "
    "generally qualifies as qualifying employment for PSLF; other employer "
    "types may also qualify under PSLF rules. Confirm this employer's "
    "tax-exempt status with the IRS Tax Exempt Organization Search "
    "(https://apps.irs.gov/app/eos/) and confirm your own eligibility "
    "at https://studentaid.gov/manage-loans/forgiveness-cancellation/"
    "public-service."
)


def get_questions(category: str | None = None,
                  limit: int = 10) -> list[dict]:
    """Return nonprofit interview questions, optionally filtered.

    Args:
        category: one of "mission", "behavioral", "situational", or None
            for all categories.
        limit: maximum number of questions returned.

    Returns:
        List of question dicts from NONPROFIT_QUESTIONS, in bank order.
        An unknown category returns an empty list.
    """
    if limit <= 0:
        return []
    if category is None:
        pool = list(NONPROFIT_QUESTIONS)
    else:
        pool = [q for q in NONPROFIT_QUESTIONS
                if q["category"] == category.strip().lower()]
    return pool[:limit]


def render_questions(questions: list[dict]) -> str:
    """Render questions for CLI display, grouped by category.

    Mirrors the markdown style used by candid.prep.build_pack: a heading
    per category, one bullet per question, source on its own line.
    """
    if not questions:
        return "_No nonprofit interview questions matched your filter._"

    lines = ["## Nonprofit interview questions", ""]
    cur_cat = None
    for i, q in enumerate(questions, 1):
        if q["category"] != cur_cat:
            cur_cat = q["category"]
            lines += [f"### {cur_cat.replace('_', ' ').title()}", ""]
        lines.append(f"{i}. {q['q']}")
        lines.append(f"   _Source: {q['source']} ({q['reported']})_")
        lines.append(f"   _{q['url']}_")
        lines.append("")
    return "\n".join(lines).rstrip()


def org_status(company: str) -> dict:
    """Heuristic nonprofit-likelihood check for an employer name.

    Keyword matching only; no lookups, no invented facts. Every matched
    keyword is listed in "signals" so the caller can see exactly why the
    flag was raised.

    Returns:
        {"company", "looks_nonprofit", "signals", "pslf_note"}
    """
    name = (company or "").strip()
    lowered = name.lower()
    signals = [m for m in NONPROFIT_MARKERS if m in lowered]
    return {
        "company": name,
        "looks_nonprofit": bool(signals),
        "signals": signals,
        "pslf_note": PSLF_NOTE,
    }


def mission_pitch_helper(mission: str, background: str) -> str:
    """Scaffold a 'why this mission' answer from the user's own words.

    This never invents experience: it quotes the mission and background
    text the user provided, and wraps them in a plain speaking structure
    with bracketed blanks for anything not yet written. Connective
    sentences express intent only (e.g. wanting to contribute), which is
    the user's stated desire, not a fabricated credential.

    Args:
        mission: the org's mission statement or a one-line summary, as
            written by the user.
        background: the user's own background text (what they have done
            or care about), in their own words.

    Returns:
        Markdown text the user can fill in and speak from.
    """
    mission = mission.strip() or "[their mission, in your words]"
    background = background.strip() or "[your background, in your words]"
    return f"""# Why This Mission - Pitch Scaffold

_Built only from your words below. Nothing was added: no roles, no years,
no achievements, no numbers. Fill the [brackets] with your own specifics._

## Their mission (your summary)

> {mission}

## Your background (your words, verbatim)

> {background}

## The scaffold

**1. Hook - what drew you in (30 seconds)**

- "What pulled me toward {mission} is..."
- Name the specific part of the mission that connects to your background:
  [the part of the mission, from your summary above]

**2. Connection - where your background meets their cause**

- Pull one line from your background above and finish this thought:
  "Because I have [done/cared about: one fact from your background],
  this mission matters to me personally, because..."
- Nonprofits screen for genuine connection to *their* org, not causes in
  general. Tie it to something specific in the mission summary above.

**3. Contribution - what you want to do there**

- "What I want to contribute is [your skill, from your background],
  applied to [their program or problem, from the mission]."
- Keep it forward-looking: this is intent, not a claim about past wins.

**4. Close - why now**

- "I want this role, at this org, now, because [your honest reason]."

## Self-check before you deliver

- Every fact you mention also appears in "Your background" above.
- The mission reference is specific enough that it would not work for
  a different org.
- You have said what you want to give, not just what the cause is.
"""
