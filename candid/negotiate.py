"""Negotiation support: BATNA framing, recruiter scripts, counter drafts.

All advice is generic and educational. Scripts are templates you adapt —
never send verbatim without reading them first.
"""

from __future__ import annotations

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
    if key not in SCRIPTS:
        raise ValueError(f"Unknown script '{key}'. Choose from: {', '.join(SCRIPTS)}")
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
    parts.append(DONT_SAY)
    return "\n".join(parts)
