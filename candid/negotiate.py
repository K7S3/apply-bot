"""Negotiation support: BATNA framing, recruiter scripts, counter drafts.

All advice is generic and educational. Scripts are templates you adapt —
never send verbatim without reading them first.
"""

from __future__ import annotations

import re

BATNA_GUIDE = """### Know your BATNA (Best Alternative To a Negotiated Agreement)

Your BATNA is what happens if you walk away: staying put, another offer, or
keeping the search going. Negotiation leverage comes from the *strength* of
that alternative, not from bluffing about it.

1. **Name it concretely.** "Stay at current role at $X with promotion track"
   beats "I have options."
2. **Never lie about a competing offer.** Recruiters verify; getting caught
   ends the process.
3. **Separate the people from the problem.** You're solving "how do we get to
   a number we both feel good about" — not fighting the recruiter.
4. **Negotiate the whole package**, not just base: sign-on, equity refresh
   assumptions, level, start date, remote flexibility, and review timeline.
5. **Get the final offer in writing** before you resign anywhere.
"""

SCRIPTS = {
    "lowball_anchor": """### Script: the number is below your range

"Thanks for the offer — I'm excited about the team and the work. I want to be
transparent: the base is below what I'd need to make a move. Based on my
research for {role} roles at this level in {location}, the market is around
{market_range}, and my current comp is {current_comp}.

Could we get the base to {target}? I'm flexible on structure — a sign-on or
additional equity could help bridge the gap if base is constrained by band."

*Why it works:* appreciative, specific, gives them multiple paths to yes.""",
    "competing_offer": """### Script: you have a competing offer

"I want to be upfront: I have another offer at {competing_total}, but this
role is my first choice because of {reason}. If you can get to {target}, I'm
ready to sign and close out my search this week.

I can share the competing offer letter once we agree on terms, if that's
helpful for approvals."

*Rules:* only say this if it's true; name a real number; give a deadline you
control.""",
    "exploding_deadline": """### Script: pressuring deadline

"I appreciate the timeline, but I can't make a good decision by {date} — I
still have final rounds in flight that I committed to before this offer. What
I *can* do is give you a firm answer by {later_date}, and I'll keep you
posted if anything changes sooner.

If the deadline is truly firm, I understand — but I'd rather be honest than
accept and renege."

*Why it works:* exploding offers rely on panic; a calm, specific counter-date
calls the bluff without burning the bridge.""",
    "level_pushback": """### Script: offered a lower level than expected

"Thanks for the offer. One thing I want to discuss is leveling — the scope we
discussed (owning {scope}) maps to {target_level} in my experience, and the
comp difference between levels is significant over four years of vesting.
Could we revisit the level, or align on what a promotion to {target_level}
would take in the first year, in writing?"

*Why it works:* level compounds — it sets your band for every future raise
and refresh.""",
    "leveling_up_push": """### Script: push for a higher level (not just more money)

"Thanks for the offer - I'm excited about the role. Before we talk numbers, I
want to make sure the level is right: the scope we discussed (owning {scope})
looks like {target_level} work to me, and leveling affects my comp band, equity
refreshers, and growth trajectory for the next four years.

If {offered_level} is where you see me starting, can we put a written plan in
place - what I'd need to demonstrate in the first {review_months} months to earn
{target_level}, with a compensation true-up at that point?"

*Why it works:* you are negotiating trajectory, not just salary - and a written
plan turns a "no" on level into a "yes, with milestones." Get the plan in the
offer letter, not just verbal.""",
    "remote_flexibility": """### Script: remote / hybrid flexibility ask

"I'm excited about the offer and the team. One thing that matters a lot for how
I do my best work: flexibility on where I work. Would {remote_ask} be possible -
for example, {example_schedule}?

I'm fully committed to being present for {onsite_commitment} (team onsites,
planning weeks, customer visits). For me this is about sustained focus time, not
about opting out."

*Why it works:* you name the specific ask, pre-empt the collaboration worry, and
frame it as a performance point rather than a perk. Ask before you sign -
flexibility agreed verbally has a way of evaporating.""",
}

PRECALL_CHECKLIST = """### Pre-call checklist (10 minutes before any negotiation call)

- [ ] Your target number, your walk-away number, and your BATNA - written down, in front of you
- [ ] The 2-3 market data points you will cite (role, level, location)
- [ ] Which levers you will trade: base, sign-on, equity, level, start date, remote
- [ ] One sentence on why *this* role excites you (enthusiasm is leverage too)
- [ ] Silence practice: after you name your number, stop talking and let them respond
- [ ] Never accept on the call: "I'm excited - can I have until [date] to review properly?"
- [ ] Water nearby; smile - they can hear it on the phone
"""

DONT_SAY = """### What not to say (and what to say instead)

- ❌ "I need at least $X because of my rent/lifestyle."
  ✅ "The market for this role/level is $X–$Y."
- ❌ "I have no other offers." (even if true — say "I'm in late stages elsewhere")
- ❌ Your exact current salary, if your state protects it — give a range or total comp instead.
- ❌ "This is my dream job, I'll take anything." — enthusiasm is fine; desperation kills leverage.
- ❌ Accepting on the call. Always: "I'm excited — can I have until [date] to review properly?"
- ❌ Negotiating over email-only when stuck — a 10-minute call unblocks more than 10 emails.
- ❌ Threatening to walk away unless you will. Empty threats end negotiations permanently.
"""

COUNTER_TEMPLATE = """Subject: Re: Offer — {role} @ {company}

Hi {recruiter},

Thank you so much for the offer — I'm genuinely excited about {company} and the {role} role.

I've reviewed the details, and I'd like to discuss two adjustments:

1. **Base salary:** {base_ask_reason}
2. **{second_item}:** {second_ask_reason}

Based on market data for this level in {location}, I believe {target_summary} reflects
both the market and the scope of the role. I'm flexible on structure — happy to discuss
sign-on, equity, or a six-month compensation review to get there.

I'm confident we can land somewhere we're both excited about. Would you have 15 minutes
{call_time} to talk it through?

Best,
{name}
"""


def get_script(key: str, **fields) -> str:
    """Render a negotiation script template with your specifics."""
    if key in EXPECTATION_SCRIPTS:
        return expectation_script(
            name=str(fields.get("name", "")),
            role=str(fields.get("role", "")),
            company=str(fields.get("company", "")),
            title=str(fields.get("title", "")),
            location=str(fields.get("location", "")),
            variant=EXPECTATION_SCRIPTS[key],
        )
    if key not in SCRIPTS:
        known = list(SCRIPTS) + list(EXPECTATION_SCRIPTS)
        raise ValueError(f"Unknown script '{key}'. Choose from: {', '.join(known)}")
    out = SCRIPTS[key]
    for k, v in fields.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def counter_email(name: str, recruiter: str, role: str, company: str,
                  location: str, base_ask_reason: str, second_item: str = "Sign-on bonus",
                  second_ask_reason: str = "", target_summary: str = "",
                  call_time: str = "tomorrow") -> str:
    """Draft a counter-offer email from your specifics."""
    return COUNTER_TEMPLATE.format(
        name=name, recruiter=recruiter, role=role, company=company,
        location=location, base_ask_reason=base_ask_reason,
        second_item=second_item,
        second_ask_reason=second_ask_reason or "to bridge the first-year gap",
        target_summary=target_summary or "a package in this range",
        call_time=call_time,
    )


def render_playbook() -> str:
    """Full negotiation playbook: BATNA + checklist + all scripts + don't-say list."""
    parts = [BATNA_GUIDE, "", PRECALL_CHECKLIST, ""]
    for key in SCRIPTS:
        parts.append(SCRIPTS[key].split("\n")[0])
        parts.append("(run `negotiate script --which {}` with your details to fill it in)".format(key))
        parts.append("")
    parts.append("### Script: 'What are your salary expectations?' (three variants)")
    parts.append("(run `negotiate script --which expectation_range|expectation_deflect|expectation_anchor` with your details)")
    parts.append("")
    parts.append(DONT_SAY)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# "What are your salary expectations?" scripts (grounded in salary data)
# ---------------------------------------------------------------------------

EXPECTATION_VARIANTS = ("range", "deflect", "anchor")

# Key-table registration so get_script() can render these like the static
# templates above. Each key maps to the variant passed to expectation_script().
EXPECTATION_SCRIPTS = {
    "expectation_range": "range",
    "expectation_deflect": "deflect",
    "expectation_anchor": "anchor",
}


def _money(value) -> str:
    """Format a number as $X,XXX. Empty string for None."""
    if value is None:
        return ""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return ""


def _salary_stats(company: str, title: str, location: str) -> dict:
    """Look up salary stats, returning {} when there is no usable data.

    Never raises for missing data; a SalaryError from the lookup is treated
    the same as an empty database so scripts fall back honestly.
    """
    from candid import salary  # lazy: keeps this module import-light

    try:
        result = salary.lookup(company, title, location)
    except Exception:
        return {}
    if not result or not result.get("n"):
        return {}
    stats = {k: result.get(k) for k in ("p25", "median", "p75", "n", "sources")}
    if stats.get("median") is None:
        return {}
    return stats


def expectation_script(name: str, role: str, company: str, title: str = "",
                       location: str = "", variant: str = "range") -> str:
    """Answer script for 'What are your salary expectations?'.

    Variants:
      - "range": states a researched range from your local salary database
        (p25/median/p75), anchored toward the top of the range.
      - "deflect": turns the question around and asks for the budgeted band.
      - "anchor": states one confident number at/above the median, justified
        by the data and the scope of the role.

    When the database has no usable data, the script says so honestly and
    falls back to the deflect approach instead of inventing numbers.
    """
    if not name or not name.strip():
        raise ValueError("expectation_script needs a name.")
    if not role or not role.strip():
        raise ValueError("expectation_script needs a role.")
    if not company or not company.strip():
        raise ValueError("expectation_script needs a company.")
    if variant not in EXPECTATION_VARIANTS:
        raise ValueError(
            f"Unknown variant '{variant}'. Choose from: {', '.join(EXPECTATION_VARIANTS)}")

    name, role, company = name.strip(), role.strip(), company.strip()
    title = (title or role).strip()
    location = (location or "").strip()
    where = f" in {location}" if location else ""

    if variant == "deflect":
        return _expectation_deflect(name, role, company, where)

    stats = _salary_stats(company, title, location)
    if not stats:
        # No usable data: never invent numbers. The deflect approach is the
        # honest fallback for both "range" and "anchor".
        return _expectation_no_data(name, role, company, title, location, variant)

    if variant == "range":
        return _expectation_range(name, role, company, title, where, stats)
    return _expectation_anchor(name, role, company, where, stats)


def _expectation_range(name, role, company, title, where, stats) -> str:
    p25, median, p75 = stats["p25"], stats["median"], stats["p75"]
    n = stats["n"]
    target = f"{_money(median)} to {_money(p75)}"
    return f"""### Script: salary expectations - researched range

Say this (adapt the numbers to your voice), {name}:

"Based on my research for {role} roles at companies like {company}{where}, the
market range is roughly {_money(p25)} to {_money(p75)}, with a median around
{_money(median)}. Given the scope of this role and my experience, I'd be looking
at the upper part of that range - around {target}. That said, I don't want to
get too anchored on one number this early. What's the budgeted band for the
role?"

Talking points:
- You answered with data, not a single number. Ranges keep you flexible while
  still sounding informed.
- Citing p25 / median / p75 from {n} data points in your local salary database
  shows homework instead of a guess.
- You anchored toward the top ({target}) and then handed the question back by
  asking for their band.
- Never state your exact current salary first. Talk market range or total comp
  instead."""


def _expectation_deflect(name, role, company, where) -> str:
    return f"""### Script: salary expectations - deflect to their band

Say this, {name}:

"Before I give you a number, can you share the budgeted band for this role at
{company}? I want to make sure we're in the same ballpark before we go deeper -
it saves us both time."

If they push for a number anyway:

"I understand you need a number. I'm targeting market rate for {role} at this
level{where}, and I'm flexible on structure - base, sign-on, and equity all
matter to me. What's the range you've budgeted?"

Talking points:
- Whoever names a number first anchors the negotiation. Make it them.
- Stay warm and collaborative, not evasive: you're saving both sides time.
- If they truly won't share a band, give a wide researched range next - never a
  single number out of thin air."""


def _expectation_anchor(name, role, company, where, stats) -> str:
    median, p75 = stats["median"], stats["p75"]
    anchor = p75 if p75 and p75 >= median else median
    return f"""### Script: salary expectations - confident anchor

Say this, {name}:

"Based on my research - {_money(median)} is roughly the median for {role}-level
roles{where} - and the scope of this team, I'm targeting {_money(anchor)} in
total comp. I'm excited about {company} specifically, and I'm flexible on how we
get there across base, sign-on, and equity."

Talking points:
- One confident number, anchored at/above the median ({_money(median)}) and
  justified by market data plus the scope of the role.
- Saying "total comp" and "flexible on structure" gives them room to maneuver
  inside a fixed base band.
- After you name the number, stop talking and let them respond."""


def _expectation_no_data(name, role, company, title, location, variant) -> str:
    what = " ".join(x for x in (company, title, location) if x)
    return f"""### Script: salary expectations - no local data (honest fallback)

Say this, {name}:

"To be honest, I haven't researched this specific band yet, so I don't want to
throw out a number that isn't grounded. What's the budgeted range for this role?
Once I know that, I can tell you quickly whether we're in the same ballpark."

Talking points:
- No usable salary data was found in your local database for '{what}', so this
  script invents no numbers. Quoting a made-up figure is worse than deflecting.
- Asking for the budgeted band is the strongest move when you lack data, and it
  is exactly what the "deflect" variant does.
- Add data before the next conversation: import DOL LCA rows or parse the
  posted range from the job description with the salary module, then re-run the
  "{variant}" variant for a data-backed answer."""


# ---------------------------------------------------------------------------
# Counteroffer conversation simulator (text-based recruiter persona)
# ---------------------------------------------------------------------------
#
# Fully deterministic: the recruiter's lines are fixed per scenario and phase,
# chosen by round number, with simple rule-based reactions to keywords in your
# messages (competing offer, walk-away, anchor numbers, deadlines).

_COUNTER_SCENARIOS = ("lowball", "competing_offer", "exploding_deadline",
                      "level_pushback")
# Accepts the lowball_anchor script key as an alias for the lowball scenario.
_SCENARIO_ALIASES = {"lowball_anchor": "lowball"}

_COUNTER_PHASES = ("probe", "pressure", "concession")


def _phase_for(round_num: int) -> str:
    if round_num <= 1:
        return "probe"
    if round_num <= 3:
        return "pressure"
    return "concession"


# Recruiter lines per scenario and phase. {placeholders} are filled from the
# current-offer dict; lines are picked deterministically by round number.
_RECRUITER_LINES = {
    "lowball": {
        "probe": [
            "Thanks for getting back to me on the offer. I want to make sure we "
            "land somewhere good - what number were you hoping to see on base?",
            "Help me understand the gap - is it base specifically, or the total "
            "package?",
        ],
        "pressure": [
            "I have to be straight with you: the band for this level tops out near "
            "{band_top}. What flexibility do you have on sign-on or equity instead?",
            "The hiring manager is excited about you, but I need something concrete "
            "to take back - what is the minimum base that works?",
        ],
        "concession": [
            "Good news - I got approval to move base to {improved}. That is the top "
            "of what I can do. Can we close this week?",
            "I have pushed as far as I can on base. What I can add is a {sign_on} "
            "sign-on. Does that get us there?",
        ],
    },
    "competing_offer": {
        "probe": [
            "Appreciate you telling me. Where are you in that process, and what is "
            "their timeline?",
            "Is the other role comparable in scope? I want to make sure we are "
            "comparing the right things.",
        ],
        "pressure": [
            "I cannot match a number I cannot see - if you can share the competing "
            "offer letter, I can take it to comp for an exception.",
            "The team wants you, but exceptions need justification. What exactly "
            "would it take for you to sign here this week?",
        ],
        "concession": [
            "I have got approval to match at {improved} total comp. I need your word "
            "you will sign this week if I put it in writing.",
            "Here is my best: {improved} base plus an early performance review at "
            "six months with a comp true-up. Can we lock this in?",
        ],
    },
    "exploding_deadline": {
        "probe": [
            "Quick flag: we do need a decision by Friday - the headcount is tied to "
            "this quarter's plan. What would help you decide by then?",
            "I know the timeline is tight. Is the blocker comp, or do you need more "
            "time with the team?",
        ],
        "pressure": [
            "I pushed, but the deadline is real - if the req lapses we restart the "
            "search. Can you give me a yes or no by Friday?",
            "Help me help you: if I get you a revised number by Thursday, can you "
            "commit Friday?",
        ],
        "concession": [
            "I got you until Monday - that is the absolute limit. Will a revised "
            "offer by Friday get us to a yes?",
            "Final ask from my side: I will put our best number in writing Friday "
            "morning. Can you decide by end of day Monday?",
        ],
    },
    "level_pushback": {
        "probe": [
            "I hear you on leveling. The panel's read was {level} - which parts of "
            "the scope were you expecting to map higher?",
            "Leveling is about demonstrated scope. What have you owned at the "
            "{target} level that I can take back to the panel?",
        ],
        "pressure": [
            "I will be honest: a level change this late needs a strong case. Can "
            "you point me to specific scope - team size, systems owned, business "
            "impact?",
            "The comp team will not move level without new evidence. Is there "
            "anything from your background I have not surfaced yet?",
        ],
        "concession": [
            "I cannot move the level today, but I can get a written six-month "
            "promotion plan with a comp true-up into the offer letter. Does that "
            "work?",
            "Here is what I can do: start at {level} with a formal early review and "
            "the {target} band as the stated goal. Fair?",
        ],
    },
}

# Rule-based keyword reactions. Checked before the phase line; each fires once.
_FLAG_REPLIES = {
    "competing_offer": (
        "You mentioned another offer in play - I want to take that seriously. "
        "What stage is that process at, and is there a number where you would "
        "sign here this week?"
    ),
    "walkaway": (
        "I hear you, and I do not want comp to be the reason we lose you. Let me "
        "take this back to the hiring manager - can you give me until tomorrow?"
    ),
    "deadline": (
        "Noted on the timeline pressure. If I can get you a revised number "
        "before your deadline, can you commit to a decision then?"
    ),
}

_FLAG_PATTERNS = {
    "competing_offer": ("competing offer", "other offer", "another offer",
                        "competing"),
    "walkaway": ("walk away", "walkaway", "walk-away", "cannot accept",
                 "can't accept", "not able to accept", "decline the offer"),
    "deadline": ("deadline", "exploding", "need more time"),
}

_ANCHOR_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*([kK])?|\b([\d,]+)\s*[kK]\b")


def _parse_anchor(text: str) -> str | None:
    """Pull the first money-like figure out of user text, e.g. '$180k'."""
    m = _ANCHOR_RE.search(text or "")
    if not m:
        return None
    if m.group(1):
        value = float(m.group(1).replace(",", ""))
        if m.group(2):
            value *= 1000
    else:
        value = float(m.group(3).replace(",", "")) * 1000
    if value <= 0:
        return None
    return _money(value)


def _detect_flags(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {flag for flag, pats in _FLAG_PATTERNS.items()
            if any(p in lowered for p in pats)}


def _fill(template: str, offer: dict) -> str:
    """Fill recruiter-line placeholders from the current-offer dict."""
    base = offer.get("base")
    improved = None
    if isinstance(base, (int, float)) and base > 0:
        improved = round(base * 1.06 / 1000) * 1000
    fill = {
        "base": _money(base) if base else "the current base",
        "improved": _money(improved) if improved else "an improved number",
        "band_top": _money(improved) if improved else "the top of the band",
        "sign_on": _money(offer.get("sign_on")) if offer.get("sign_on")
        else "one-time",
        "level": str(offer.get("level", "the offered level")),
        "target": str(offer.get("target_level", "the next level")),
    }
    try:
        return template.format(**fill)
    except (KeyError, IndexError, ValueError):
        return template


def _check_session(session) -> dict:
    if not isinstance(session, dict) or "scenario" not in session \
            or "history" not in session or "round" not in session:
        raise ValueError("Invalid counter session. Start one with "
                         "start_counter_session().")
    return session


def start_counter_session(current_offer: dict, batna: dict,
                          scenario: str = "lowball") -> dict:
    """Start a counteroffer practice session with a recruiter persona.

    current_offer: e.g. {"base": 160000, "sign_on": 20000, "equity": 100000,
        "level": "L4", "target_level": "L5"}.
    batna: e.g. {"description": "Stay at current role", "value": 190000}.
    scenario: one of "lowball", "competing_offer", "exploding_deadline",
        "level_pushback" ("lowball_anchor" is accepted as an alias).
    """
    if not isinstance(current_offer, dict):
        raise ValueError("current_offer must be a dict.")
    if not isinstance(batna, dict):
        raise ValueError("batna must be a dict.")
    scenario = _SCENARIO_ALIASES.get(scenario, scenario)
    if scenario not in _COUNTER_SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario}'. Choose from: "
            f"{', '.join(_COUNTER_SCENARIOS)}")
    return {
        "scenario": scenario,
        "round": 0,
        "phase": "probe",
        "current_offer": dict(current_offer),
        "batna": dict(batna),
        "history": [],
        "flags": set(),
        "answered_flags": set(),
        "user_anchor": None,
    }


def counter_recruiter_reply(session: dict) -> str:
    """Return the recruiter persona's deterministic next message.

    Progresses through probe -> pressure -> concession phases by round number,
    and reacts once to keywords spotted in your messages (competing offer,
    walk-away, deadline pressure). Appends the message to the session history.
    """
    session = _check_session(session)
    scenario = session["scenario"]
    round_num = session["round"]
    phase = _phase_for(round_num)
    session["phase"] = phase

    text = None
    for flag in ("competing_offer", "walkaway", "deadline"):
        if flag in session["flags"] and flag not in session["answered_flags"]:
            text = _FLAG_REPLIES[flag]
            session["answered_flags"].add(flag)
            break
    if text is None:
        lines = _RECRUITER_LINES[scenario][phase]
        phase_start = {"probe": 0, "pressure": 2, "concession": 4}[phase]
        text = _fill(lines[(round_num - phase_start) % len(lines)],
                     session["current_offer"])
    session["history"].append({"speaker": "recruiter", "text": text})
    return text


def counter_user_reply(session: dict, text: str) -> dict:
    """Record your message, detect keywords, and advance the round.

    Returns the updated session dict.
    """
    session = _check_session(session)
    if not text or not str(text).strip():
        raise ValueError("counter_user_reply needs a non-empty message.")
    text = str(text).strip()
    session["history"].append({"speaker": "you", "text": text})
    session["flags"] |= _detect_flags(text)
    anchor = _parse_anchor(text)
    if anchor and not session["user_anchor"]:
        session["user_anchor"] = anchor
    session["round"] += 1
    session["phase"] = _phase_for(session["round"])
    return session


def counter_transcript(session: dict) -> str:
    """Render the full practice conversation as Markdown, plus a debrief."""
    session = _check_session(session)
    scenario = session["scenario"]
    offer = session["current_offer"]
    batna = session["batna"]

    offer_bits = []
    if offer.get("base"):
        offer_bits.append(f"base {_money(offer['base'])}")
    if offer.get("sign_on"):
        offer_bits.append(f"sign-on {_money(offer['sign_on'])}")
    if offer.get("equity"):
        offer_bits.append(f"equity {_money(offer['equity'])}")
    if offer.get("level"):
        offer_bits.append(f"level {offer['level']}")
    offer_line = ", ".join(offer_bits) or "no details recorded"

    lines = [
        f"## Counteroffer practice - {scenario} scenario",
        "",
        f"**Current offer:** {offer_line}",
        f"**Your BATNA:** {batna.get('description', 'not recorded')}",
        "",
        "### Conversation",
        "",
    ]
    round_num = 0
    for msg in session["history"]:
        if msg["speaker"] == "recruiter":
            round_num += 1
            lines.append(f"**Round {round_num} - Recruiter:** {msg['text']}")
        else:
            lines.append(f"**Round {round_num} - You:** {msg['text']}")
        lines.append("")

    lines.append("### Debrief")
    lines.append("")
    lines.append("**What worked**")
    worked = []
    if session["round"] >= 1:
        worked.append(
            "You did not accept on the spot - every calm round of back-and-forth "
            "is leverage.")
    user_text = " ".join(m["text"] for m in session["history"]
                         if m["speaker"] == "you").lower()
    if "market" in user_text or "median" in user_text or "p25" in user_text:
        worked.append(
            "You cited market data - objective framing beats personal need.")
    if "competing_offer" in session["flags"]:
        worked.append(
            "You surfaced a competing offer - that creates real urgency. Only "
            "ever say this if it is true.")
    if session["user_anchor"]:
        worked.append(
            f"You named a specific number ({session['user_anchor']}) - specific "
            "beats asking for 'more money'.")
    if "walkaway" in session["flags"]:
        worked.append(
            "You named a walk-away - powerful, but only use it if you will "
            "actually walk.")
    if "deadline" in session["flags"]:
        worked.append(
            "You addressed the timeline directly instead of letting it pressure "
            "you.")
    if not worked:
        worked.append(
            "The session just started - say your first line to get feedback.")
    for w in worked:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("**Try next**")
    nxt = []
    if not session["user_anchor"]:
        nxt.append(
            "Name a specific target number next - recruiters cannot hit a "
            "target they cannot see.")
    if session["phase"] == "probe":
        nxt.append(
            "Keep asking questions before conceding anything - information "
            "first, numbers second.")
    elif session["phase"] == "pressure":
        nxt.append(
            "Move this to a 10-minute call - calls unblock more than text "
            "threads.")
    else:
        nxt.append(
            "Get any revised number in writing before you decide, and confirm "
            "level and start date in the same letter.")
    nxt.append(
        "Rehearse your BATNA line out loud once before the real call - "
        "knowing your walk-away keeps you calm.")
    for n in nxt:
        lines.append(f"- {n}")
    return "\n".join(lines)
