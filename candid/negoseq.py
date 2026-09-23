"""Negotiation email sequence builder.

Takes an offer and produces a planned, timed sequence of negotiation emails
rather than a single counter draft: the first counter, a silence nudge, a
call request if email stalls, deadline handling, and acceptance/decline
closers. Adds timing guidance (business-day aware), tone variants
(warm / professional / assertive), BATNA-aware talking points, an anchoring
calculator, recruiter-pushback replies, a multi-lever tradeoff menu, a call /
voicemail script, and a lightweight sequence tracker so you know what to send
next and when.

All drafts are templates you adapt - never send verbatim without reading
them first. This is generic, educational guidance, not legal or financial
advice. Never misrepresent a competing offer.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from candid import config as C


class NegoseqError(Exception):
    """Raised for invalid sequence inputs or operations."""


# ---------------------------------------------------------------------------
# 1. Sequence definition
# ---------------------------------------------------------------------------

#: Ordered steps of a negotiation sequence. ``offset`` is business days after
#: the previous anchor step; the timing engine turns these into real dates.
STEPS = [
    {
        "key": "counter",
        "title": "Counter-offer email",
        "purpose": "Make your first ask: appreciative, specific, with market "
                   "backing and multiple paths to yes.",
        "offset": 1,  # business days after the offer arrives
    },
    {
        "key": "nudge",
        "title": "Silence nudge",
        "purpose": "If you hear nothing for a few business days, re-open the "
                   "thread without sounding anxious.",
        "offset": 3,  # business days after the counter
    },
    {
        "key": "call_request",
        "title": "Call request",
        "purpose": "Email stalls get unblocked by a 15-minute call. Ask for "
                   "one explicitly, with times.",
        "offset": 2,  # business days after the nudge
    },
    {
        "key": "deadline_reply",
        "title": "Deadline response",
        "purpose": "Answer an exploding deadline calmly: counter with a firm "
                   "date you control, keep the bridge intact.",
        "offset": 0,  # anchored to the deadline itself, not the chain
    },
    {
        "key": "accept",
        "title": "Acceptance email",
        "purpose": "Accept in writing, restate the agreed terms so there is a "
                   "paper trail, confirm start date.",
        "offset": 0,
    },
    {
        "key": "decline",
        "title": "Gracious decline",
        "purpose": "Decline warmly, name what you valued, leave the door open "
                   "for a future role or referral.",
        "offset": 0,
    },
]

_STEP_KEYS = [s["key"] for s in STEPS]


def build_sequence(deadline: str | None = None,
                   competing_offer: bool = False) -> list[dict]:
    """Return the ordered negotiation steps for this situation.

    ``deadline`` is an ISO date (YYYY-MM-DD) the offer expires; including it
    keeps the deadline-response step in the plan. ``competing_offer``
    reshapes the counter's talking points (handled by batna_points).
    """
    steps = [dict(s) for s in STEPS]
    if deadline:
        try:
            date.fromisoformat(deadline)
        except ValueError:
            raise NegoseqError(f"deadline must be YYYY-MM-DD, got {deadline!r}")
    for s in steps:
        s["in_plan"] = True
        s["deadline"] = deadline
        s["competing_offer"] = competing_offer
    return steps


# ---------------------------------------------------------------------------
# 2. Tone variants
# ---------------------------------------------------------------------------

TONES = ("warm", "professional", "assertive")

_TONE_OPENERS = {
    "warm": "Thank you so much for the offer - I'm genuinely excited about "
            "{company} and the {role} role, and about working with you.",
    "professional": "Thank you for extending the offer for the {role} role "
                    "at {company}.",
    "assertive": "Thanks for the offer - I'm excited about the {role} role at "
                 "{company}, and I want to make sure the package reflects "
                 "the scope we discussed.",
}

_TONE_CLOSERS = {
    "warm": "Really appreciate you working through this with me - I'm "
            "looking forward to it.",
    "professional": "Appreciate your time working through the details.",
    "assertive": "I'm confident we can land on terms we're both excited "
                 "about. Looking forward to your reply.",
}


def _tone(tone: str) -> str:
    if tone not in TONES:
        raise NegoseqError(f"Tone must be one of {TONES}, got {tone!r}")
    return tone


def _sig(name: str) -> str:
    return f"Best,\n{name}" if name else "Best regards"


# ---------------------------------------------------------------------------
# 3. Step email drafts
# ---------------------------------------------------------------------------

def _counter_body(f: dict, tone: str) -> str:
    return (
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        "I've reviewed the details, and before I sign I'd like to discuss "
        "the compensation package. Based on market data for this level in "
        f"{f['location']}, {f['market_note']}.\n\n"
        f"My target is {f['target_summary']}. {f['levers_sentence']}\n\n"
        f"Would you have 15 minutes {f['call_time']} to talk it through?\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


def _nudge_body(f: dict, tone: str) -> str:
    return (
        f"Hi {f['recruiter']},\n\n"
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        "Circling back on my note from earlier this week - I wanted to check "
        "whether there is any movement on the package discussion, and whether "
        "a quick call would help.\n\n"
        f"I'm free {f['call_time']} if that works on your end.\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


def _call_request_body(f: dict, tone: str) -> str:
    return (
        f"Hi {f['recruiter']},\n\n"
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        "Email threads tend to lose nuance on compensation, so I'd love 15 "
        "minutes to talk through the package directly - I think we can wrap "
        "this up quickly on a call.\n\n"
        f"I'm available {f['call_time']}. If none of those work, suggest a "
        "time and I'll make it happen.\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


def _deadline_reply_body(f: dict, tone: str) -> str:
    return (
        f"Hi {f['recruiter']},\n\n"
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        f"I appreciate the timeline, but I can't make a good decision by "
        f"{f['deadline']} - I still have final rounds in flight that I "
        "committed to before this offer.\n\n"
        f"What I can do is give you a firm answer by {f['later_date']}, and "
        "I'll keep you posted if anything changes sooner. If the deadline is "
        "truly firm, I understand - but I'd rather be honest than accept and "
        "renege.\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


def _accept_body(f: dict, tone: str) -> str:
    return (
        f"Hi {f['recruiter']},\n\n"
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        "I'm delighted to accept the offer. To confirm what we agreed:\n\n"
        f"{f['terms_summary']}\n\n"
        f"I'll plan to start on {f['start_date']}, pending the written offer "
        "letter. Please let me know the next steps on paperwork and "
        "onboarding.\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


def _decline_body(f: dict, tone: str) -> str:
    return (
        f"Hi {f['recruiter']},\n\n"
        f"{_TONE_OPENERS[tone].format(**f)}\n\n"
        "After careful thought, I've decided to go in a different direction. "
        f"{f['decline_reason']} This was a genuinely hard call - I have a lot "
        "of respect for the team and the work.\n\n"
        "I'd love to stay in touch, and I'd be glad to refer strong folks "
        "your way.\n\n"
        f"{_TONE_CLOSERS[tone]}\n\n{_sig(f['name'])}"
    )


_STEP_BUILDERS = {
    "counter": (_counter_body, "Re: Offer - {role} @ {company}"),
    "nudge": (_nudge_body, "Re: Offer - {role} @ {company} (following up)"),
    "call_request": (_call_request_body, "Quick call on the {role} offer?"),
    "deadline_reply": (_deadline_reply_body, "Re: Offer decision timeline"),
    "accept": (_accept_body, "Accepting the {role} offer - {company}"),
    "decline": (_decline_body, "Decision on the {role} offer"),
}

_DEFAULTS = {
    "name": "Your Name",
    "recruiter": "there",
    "role": "the role",
    "company": "the company",
    "location": "your market",
    "market_note": "the range for comparable roles sits above the current offer",
    "target_summary": "a package closer to the top of the band",
    "levers_sentence": "I'm flexible on structure - base, sign-on, equity, "
                       "or a six-month compensation review could all help bridge the gap.",
    "call_time": "tomorrow or Thursday",
    "deadline": "Friday",
    "later_date": "next Wednesday",
    "terms_summary": "- Base: (as agreed)\n- Sign-on: (as agreed)\n- Equity: (as agreed)\n- Start date: (as agreed)",
    "start_date": "(start date)",
    "decline_reason": "The timing and total package aren't quite the right fit for me right now.",
}


def draft_email(step: str, tone: str = "professional", **fields) -> dict:
    """Draft the subject + body for one sequence step in the given tone.

    ``step`` is one of: counter, nudge, call_request, deadline_reply,
    accept, decline. ``tone`` is warm, professional, or assertive.
    """
    if step not in _STEP_BUILDERS:
        raise NegoseqError(
            f"Unknown step {step!r}. Choose from: {', '.join(_STEP_KEYS)}")
    _tone(tone)
    f = dict(_DEFAULTS)
    f.update({k: v for k, v in fields.items() if v})
    builder, subject_t = _STEP_BUILDERS[step]
    return {
        "step": step,
        "tone": tone,
        "subject": subject_t.format(**f),
        "body": builder(f, tone),
    }


# ---------------------------------------------------------------------------
# 4. Timing guidance (business-day aware)
# ---------------------------------------------------------------------------

def add_business_days(d: date, n: int) -> date:
    """Add n business days to d, skipping Saturday and Sunday."""
    if n < 0:
        raise NegoseqError("n must be non-negative")
    out = d
    while n:
        out += timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out


def timing_plan(offer_date: str, deadline: str | None = None) -> list[dict]:
    """Recommended send dates for each step, skipping weekends.

    ``offer_date`` and ``deadline`` are ISO dates. The counter goes out 1
    business day after the offer (24-48h is the sweet spot: fast enough to
    show enthusiasm, slow enough to show you did homework). The deadline
    reply is anchored to the deadline itself, one business day before it.
    """
    try:
        od = date.fromisoformat(offer_date)
    except ValueError:
        raise NegoseqError(f"offer_date must be YYYY-MM-DD, got {offer_date!r}")
    dl = None
    if deadline:
        try:
            dl = date.fromisoformat(deadline)
        except ValueError:
            raise NegoseqError(f"deadline must be YYYY-MM-DD, got {deadline!r}")
        if dl <= od:
            raise NegoseqError("deadline must be after offer_date")

    counter_on = add_business_days(od, 1)
    nudge_on = add_business_days(counter_on, 3)
    call_on = add_business_days(nudge_on, 2)
    plan = [
        {"step": "counter", "send_on": counter_on.isoformat(),
         "why": "24-48h after the offer: shows enthusiasm plus homework."},
        {"step": "nudge", "send_on": nudge_on.isoformat(),
         "why": "3 business days of silence, then one polite re-open."},
        {"step": "call_request", "send_on": call_on.isoformat(),
         "why": "Email stalling? A 15-minute call unblocks more than 10 emails."},
    ]
    if dl:
        reply_on = dl - timedelta(days=1)
        while reply_on.weekday() >= 5:
            reply_on -= timedelta(days=1)
        plan.append({"step": "deadline_reply", "send_on": reply_on.isoformat(),
                     "why": "Answer the exploding deadline one business day "
                            "before it, with your own firm date."})
        plan.append({"step": "accept/decline", "send_on": dl.isoformat(),
                     "why": "Decide by the deadline you agreed to - or the "
                            "firm date you countered with."})
    return plan


# ---------------------------------------------------------------------------
# 5. BATNA-aware talking points
# ---------------------------------------------------------------------------

_BATNA_KINDS = {
    "competing_offer": {
        "strength": "strong",
        "points": [
            "Name the real number and the real deadline - specificity is what "
            "makes a competing offer credible.",
            "Frame this role as your first choice and name why (team, scope, "
            "mission) - you are asking them to win, not to match.",
            "Offer to share the competing letter once terms are agreed, if it "
            "helps with approvals.",
        ],
        "cautions": ["Never invent or inflate a competing offer. Recruiters "
                     "verify, and getting caught ends the process."],
    },
    "current_role": {
        "strength": "medium",
        "points": [
            "Your walk-away is concrete: staying at $X with your current "
            "trajectory. Name it, don't wave at it.",
            "Emphasize what the move costs you (unvested equity, ramp-up, "
            "risk) - the offer has to beat staying, not just match it.",
            "Promotion timeline or upcoming refresh at your current role is "
            "fair game to mention in general terms.",
        ],
        "cautions": ["Don't threaten to quit your current job as leverage; "
                     "it reads as desperation, not strength."],
    },
    "other_finals": {
        "strength": "medium-strong",
        "points": [
            "\"I'm in final rounds at two other companies, expecting decisions "
            "next week\" is honest leverage without a number to defend.",
            "Use the timeline, not the outcome: ask for a decision date that "
            "lets you compare properly.",
            "Keep it truthful - \"finals in flight\" only if they exist.",
        ],
        "cautions": ["Don't name companies or numbers you don't have."],
    },
    "search_only": {
        "strength": "weak",
        "points": [
            "Without a competing lever, your strength is market data: 2-3 "
            "specific data points for this role, level, and location.",
            "Enthusiasm is leverage too: \"this is my top choice and I want "
            "to say yes\" makes them want to close you.",
            "Negotiate structure, not just number: review timelines, sign-on, "
            "and level are all movable when base is not.",
        ],
        "cautions": ["Don't claim \"other options\" vaguely - a specific "
                     "truth beats a vague bluff every time."],
    },
    "none": {
        "strength": "weakest",
        "points": [
            "Be honest with yourself: your BATNA is continuing the search. "
            "That is fine, but it means patience is your strategy.",
            "Lean fully on market data and the cost of the role staying open - "
            "hiring managers feel vacancy pain too.",
            "Ask for non-cash levers freely: start date, remote flexibility, "
            "title, and review timing cost them little.",
        ],
        "cautions": ["Never bluff a competing offer. Ever."],
    },
}


def batna_points(kind: str, detail: str = "") -> dict:
    """Talking points tuned to your BATNA. ``kind`` is one of:
    competing_offer, current_role, other_finals, search_only, none."""
    if kind not in _BATNA_KINDS:
        raise NegoseqError(
            f"Unknown BATNA kind {kind!r}. Choose from: "
            f"{', '.join(_BATNA_KINDS)}")
    info = _BATNA_KINDS[kind]
    points = list(info["points"])
    if detail:
        points.insert(0, f"Your situation: {detail}")
    return {
        "kind": kind,
        "strength": info["strength"],
        "points": points,
        "cautions": list(info["cautions"]),
    }


# ---------------------------------------------------------------------------
# 6. Anchoring calculator
# ---------------------------------------------------------------------------

def _money(n: float) -> str:
    return f"${n:,.0f}"


def anchor_ask(target: float, market_low: float, market_high: float,
               walkaway: float) -> dict:
    """Compute a first-ask anchor from your target and market band.

    The anchor sits ~5-8% above your target (rounded to the nearest $1k) so
    you have room to concede toward the target, but it is capped at the top
    of the market band - an anchor above the band reads as uninformed, not
    confident.
    """
    for label, v in (("target", target), ("market_low", market_low),
                     ("market_high", market_high), ("walkaway", walkaway)):
        if v is None or v <= 0:
            raise NegoseqError(f"{label} must be a positive number")
    if market_low > market_high:
        raise NegoseqError("market_low cannot exceed market_high")
    if target < walkaway:
        raise NegoseqError("target is below your walk-away: rethink the goal "
                           "before negotiating")
    notes = []
    raw = round(target * 1.06 / 1000) * 1000
    ask = raw
    if raw > market_high:
        ask = market_high
        notes.append(f"Raw anchor {_money(raw)} exceeded the market top "
                     f"{_money(market_high)} - capped at the band top. An "
                     "anchor above the band looks uninformed.")
    if target > market_high:
        notes.append(f"Your target {_money(target)} is above the market band "
                     f"{_money(market_low)}-{_money(market_high)} - be ready "
                     "with exceptional-scope justification, or reset the target.")
    if target < market_low:
        notes.append(f"Your target {_money(target)} is below the market band - "
                     "you may be leaving money on the table.")
    notes.append(f"After you name {_money(ask)}, stop talking and let them "
                 "respond. Silence is part of the ask.")
    return {
        "target": target,
        "walkaway": walkaway,
        "market_band": [market_low, market_high],
        "ask": ask,
        "concession_room": ask - target,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 7. Recruiter pushback replies
# ---------------------------------------------------------------------------

PUSHBACKS = {
    "band_max": {
        "tactic": "Accept the constraint, move the fight to another lever.",
        "reply": (
            "I understand the band is firm. If base can't move, can we look "
            "at the other levers - a sign-on to bridge year one, additional "
            "equity, or a written six-month compensation review tied to "
            "performance? I'm flexible on structure."),
    },
    "need_approval": {
        "tactic": "Make it easy for them to sell you internally.",
        "reply": (
            "Totally understand - happy to help make the case. Is there "
            "anything I can provide that would help with approvals: market "
            "data points, details on my competing timeline, or a summary of "
            "the scope we'd discussed? What's a realistic date to hear back?"),
    },
    "firm_deadline": {
        "tactic": "Call the bluff calmly with your own firm date.",
        "reply": (
            "I appreciate the timeline, but I can't make a good decision by "
            "{deadline} - I have final rounds in flight I committed to before "
            "this offer. I can give you a firm answer by {later_date}. If the "
            "deadline is truly firm I understand, but I'd rather be honest "
            "than accept and renege."),
    },
    "budget_freeze": {
        "tactic": "Trade cash for trajectory: level, title, review date.",
        "reply": (
            "I hear you on the budget. If cash is frozen, can we talk about "
            "what isn't: the level, a written promotion and compensation "
            "review at {review_months} months, or a title that reflects the "
            "scope? Getting the trajectory right matters more to me than "
            "squeezing this year's number."),
    },
    "other_candidate": {
        "tactic": "Don't panic-bid against a phantom. Reaffirm fit, hold.",
        "reply": (
            "I understand you have other strong candidates. I'll be direct: "
            "this role is my first choice because of {reason}, and my ask is "
            "{target_summary}. I'm not going to bid against myself - but if "
            "there's a path to that number, I'm ready to sign and close out "
            "my search this week."),
    },
    "verbal_only": {
        "tactic": "Nothing is real until it's written.",
        "reply": (
            "I'm excited about where we landed. Before I give notice anywhere, "
            "could you send the updated terms in writing - base, sign-on, "
            "equity, level, and start date? Once I have the letter, I'll sign "
            "and we can both move forward with confidence."),
    },
}


def pushback_reply(kind: str, **fields) -> dict:
    """Reply draft + tactic for a common recruiter pushback.

    Kinds: band_max, need_approval, firm_deadline, budget_freeze,
    other_candidate, verbal_only.
    """
    if kind not in PUSHBACKS:
        raise NegoseqError(
            f"Unknown pushback {kind!r}. Choose from: {', '.join(PUSHBACKS)}")
    info = PUSHBACKS[kind]
    reply = info["reply"]
    for k, v in fields.items():
        reply = reply.replace("{" + k + "}", str(v))
    return {"kind": kind, "tactic": info["tactic"], "reply": reply}


# ---------------------------------------------------------------------------
# 8. Multi-lever tradeoff menu
# ---------------------------------------------------------------------------

LEVERS = [
    ("base", "Base salary", "Recurring, compounds every raise. Hardest to move; ask first."),
    ("sign_on", "Sign-on bonus", "One-time; easiest approval. Good bridge for a first-year gap."),
    ("equity", "Equity / RSUs", "Big over 4 years; ask about refresh assumptions too."),
    ("level", "Level / title", "Sets your band for every future raise and refresh. Compounds."),
    ("review", "Early comp review", "Written 6-month review with comp true-up turns a 'no' into 'not yet'."),
    ("start_date", "Start date", "Later start can preserve a bonus payout at your current role."),
    ("remote", "Remote flexibility", "Costs them little; worth real money to you. Get it in writing."),
    ("relocation", "Relocation", "Lump sum or temporary housing; often a separate budget line."),
]


def tradeoff_menu(priorities: list[str] | None = None) -> list[dict]:
    """The levers you can trade, ordered by your priorities first.

    ``priorities`` is a list of lever keys (e.g. ["base", "equity"]); unknown
    keys raise NegoseqError.
    """
    keys = [k for k, _, _ in LEVERS]
    if priorities:
        unknown = [p for p in priorities if p not in keys]
        if unknown:
            raise NegoseqError(f"Unknown levers: {', '.join(unknown)}. "
                               f"Choose from: {', '.join(keys)}")
        ordered = [p for p in priorities] + [k for k in keys if k not in priorities]
    else:
        ordered = keys
    info = {k: (label, note) for k, label, note in LEVERS}
    return [{"key": k, "label": info[k][0], "note": info[k][1]} for k in ordered]


def package_ask(levers: dict[str, str]) -> str:
    """Compose a full package ask from lever -> ask-amount pairs.

    Example: package_ask({"base": "$190k", "sign_on": "$25k",
    "review": "6-month written review"}).
    """
    if not levers:
        raise NegoseqError("Give at least one lever -> ask pair")
    keys = [k for k, _, _ in LEVERS]
    unknown = [k for k in levers if k not in keys]
    if unknown:
        raise NegoseqError(f"Unknown levers: {', '.join(unknown)}")
    info = {k: label for k, label, _ in LEVERS}
    lines = [f"- **{info[k]}:** {v}" for k, v in levers.items()]
    return ("Here's the package that would get me to yes:\n\n"
            + "\n".join(lines)
            + "\n\nI'm flexible on how we get there - if one of these is "
              "constrained, I'm open to making it up on another.")


# ---------------------------------------------------------------------------
# 9. Call / voicemail script
# ---------------------------------------------------------------------------

def call_script(recruiter: str = "there", role: str = "the role",
                company: str = "the company", target_summary: str = "",
                batna_kind: str = "search_only",
                voicemail: bool = False) -> str:
    """Talking points for the negotiation call, or a 30-second voicemail."""
    target_summary = target_summary or "a package closer to the top of the band"
    batna = _BATNA_KINDS.get(batna_kind, _BATNA_KINDS["search_only"])
    if voicemail:
        return (
            f"Hi {recruiter}, this is {{your name}} - quick message on the "
            f"{role} offer. I'm excited about {company} and I'd love 15 "
            "minutes to talk through the package; I think we can wrap it up "
            "fast on a call. I'll follow up by email too. Thanks!")
    lines = [
        f"### Call script: {role} @ {company} with {recruiter}",
        "",
        "1. **Open warm:** \"Thanks for making time - I'm excited about this "
        "role, and I want to find the package that gets me to yes.\"",
        f"2. **Name the ask once:** \"{target_summary}.\" Then stop talking.",
        "3. **Anchor to market, not need:** cite 2-3 specific data points "
        "(role, level, location). Never justify with rent or lifestyle.",
        "4. **Trade levers, don't just discount:** \"If base is constrained, "
        "could a sign-on or an early comp review bridge the gap?\"",
        f"5. **BATNA ({batna['strength']}):** {batna['points'][0]}",
        "6. **Close with a date:** \"Can I have until [date] to review the "
        "written terms properly?\"",
        "7. **Never accept on the call.** Always take the terms away in writing.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. Full plan rendering
# ---------------------------------------------------------------------------

def render_plan(company: str, role: str, offer_date: str,
               deadline: str | None = None, tone: str = "professional",
               batna_kind: str = "search_only", **fields) -> str:
    """Render the whole sequence plan as markdown: steps, timing, drafts."""
    _tone(tone)
    steps = build_sequence(deadline=deadline)
    plan = timing_plan(offer_date, deadline)
    send_on = {p["step"]: p["send_on"] for p in plan}
    lines = [f"# Negotiation plan: {role} @ {company}",
             "",
             f"Tone: **{tone}** - BATNA: **{batna_kind}**",
             "",
             "## Steps and timing",
             ""]
    for s in steps:
        if s["key"] in ("accept", "decline"):
            lines.append(f"- **{s['title']}** - when you decide. {s['purpose']}")
        else:
            when = send_on.get(s["key"], "per deadline")
            lines.append(f"- **{s['title']}** - send {when}. {s['purpose']}")
    lines += ["", "## BATNA talking points", ""]
    bp = batna_points(batna_kind)
    lines.append(f"Strength: **{bp['strength']}**")
    for p in bp["points"]:
        lines.append(f"- {p}")
    for c in bp["cautions"]:
        lines.append(f"- ⚠️ {c}")
    lines += ["", "## Drafts", ""]
    for s in steps:
        if s["key"] in ("accept", "decline"):
            continue
        d = draft_email(s["key"], tone, company=company, role=role, **fields)
        lines += [f"### {s['title']} (`{d['subject']}`)", "", d["body"], ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 11. Sequence tracker
# ---------------------------------------------------------------------------

def _store_path() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    d = base / "negoseq"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sequences.json"


def _load() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(seqs: list[dict]) -> None:
    _store_path().write_text(json.dumps(seqs, indent=2))


def start_sequence(company: str, role: str, offer_date: str,
                   deadline: str | None = None, tone: str = "professional",
                   batna_kind: str = "search_only") -> dict:
    """Start tracking a negotiation sequence; returns the record."""
    if not company or not role:
        raise NegoseqError("company and role are required")
    _tone(tone)
    date.fromisoformat(offer_date)  # validates; raises ValueError
    plan = timing_plan(offer_date, deadline)
    seqs = _load()
    rec = {
        "id": len(seqs) + 1,
        "company": company,
        "role": role,
        "offer_date": offer_date,
        "deadline": deadline,
        "tone": tone,
        "batna_kind": batna_kind,
        "plan": plan,
        "log": [],  # entries: {step, status, at}
        "created": date.today().isoformat(),
    }
    seqs.append(rec)
    _save(seqs)
    return rec


def log_email(seq_id: int, step: str,
              status: str = "sent", at: str | None = None) -> dict:
    """Log a step email. Status: planned, sent, replied, done, skipped."""
    if step not in _STEP_KEYS + ["accept/decline"]:
        raise NegoseqError(f"Unknown step {step!r}")
    if status not in ("planned", "sent", "replied", "done", "skipped"):
        raise NegoseqError(f"Bad status {status!r}")
    seqs = _load()
    rec = next((s for s in seqs if s["id"] == seq_id), None)
    if rec is None:
        raise NegoseqError(f"No sequence #{seq_id}")
    entry = {"step": step, "status": status,
             "at": at or date.today().isoformat()}
    rec["log"].append(entry)
    _save(seqs)
    return entry


def get_sequence(seq_id: int) -> dict:
    seqs = _load()
    rec = next((s for s in seqs if s["id"] == seq_id), None)
    if rec is None:
        raise NegoseqError(f"No sequence #{seq_id}")
    return rec


def list_sequences() -> list[dict]:
    return _load()


def next_action(seq_id: int) -> str:
    """What to do next on a sequence, based on what's been logged."""
    rec = get_sequence(seq_id)
    done = {e["step"] for e in rec["log"] if e["status"] in ("sent", "done")}
    for p in rec["plan"]:
        if p["step"] not in done:
            return (f"Next: send the **{p['step']}** email on or after "
                    f"{p['send_on']} ({p['why']})")
    if any(e["status"] == "replied" for e in rec["log"]):
        return ("Next: review their reply against your target and walk-away, "
                "then draft the follow-up or acceptance.")
    return ("Next: decide - send the acceptance or the gracious decline, and "
            "log it with `negoseq track --op log`.")


def render_status(seq_id: int) -> str:
    rec = get_sequence(seq_id)
    lines = [f"# Sequence #{rec['id']}: {rec['role']} @ {rec['company']}",
             f"Offer date: {rec['offer_date']} - deadline: {rec['deadline'] or 'none'}",
             f"Tone: {rec['tone']} - BATNA: {rec['batna_kind']}", "",
             "## Plan"]
    logged = {}
    for e in rec["log"]:
        logged[e["step"]] = e["status"]
    for p in rec["plan"]:
        mark = logged.get(p["step"], "pending")
        lines.append(f"- [x] {p['step']} ({p['send_on']}) - {mark}" if mark != "pending"
                     else f"- [ ] {p['step']} ({p['send_on']}) - pending")
    lines += ["", next_action(seq_id)]
    return "\n".join(lines)
