"""Competing-offer leverage playbook.

Turns the raw offers in ``candid.offer`` into usable negotiation leverage:
how to use competing offers ethically, how to coordinate their timelines,
what to say in each scenario, and what your BATNA actually is.

The ten features:

1.  register()          competing-offer register: status, deadline, contact
2.  ethical_playbook()  how to use competing offers without bluffing or lying
3.  build_timeline()    coordinate deadlines: what to extend, what to accelerate
4.  get_script()        eight scripts, one per leverage scenario
5.  batna_report()      your BATNA from real offers + walk-away / target numbers
6.  extension_email()   deadline-extension draft for a specific offer
7.  deadline_report()   urgency table + exploding-offer warnings
8.  log_disclosure()    honesty log of every competing offer you mentioned
9.  leverage_score()    0-100 strength score + which levers to pull next
10. decision_plan()     accept / negotiate / hold / decline per offer + if-thens

Comp math comes from candid.offer (normalized annual comp) - it is never
recomputed here. Storage is candid_data/leverage.json (git-ignored).
Everything is template text you adapt; never send verbatim without reading.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C
from candid import offer as O


class LeverageError(Exception):
    """Raised for invalid leverage data or operations."""


STATUSES = ("verbal", "written", "signed", "declined", "expired")
ACTIVE_STATUSES = ("verbal", "written")
CHANNELS = ("call", "email", "in-person", "text")


def _path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return C.DATA_DIR / "leverage.json"


def _load(path: str | Path | None = None) -> dict:
    p = _path(path)
    if not p.exists():
        return {"offers": [], "disclosures": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LeverageError(f"Leverage file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LeverageError(f"Leverage file {p} should hold an object.")
    data.setdefault("offers", [])
    data.setdefault("disclosures", [])
    return data


def _save(data: dict, path: str | Path | None = None) -> None:
    p = _path(path)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_date(s: str | None, field: str = "deadline") -> str | None:
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise LeverageError(f"{field} must be YYYY-MM-DD, got '{s}'.")
    return s


def _today(today: str | date | None) -> date:
    if today is None:
        return date.today()
    if isinstance(today, date):
        return today
    try:
        return datetime.strptime(today, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise LeverageError(f"today must be YYYY-MM-DD, got '{today}'.")


def _offer_by_id(offer_id: int, path: str | Path | None = None) -> dict:
    for o in O.list_offers(path):
        if o.get("id") == offer_id:
            return o
    raise LeverageError(
        f"No offer #{offer_id} in the offer register. "
        "Add it first: python -m candid offer add --company ...")


def _fmt(x) -> str:
    try:
        return f"${float(x or 0):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


# ---------------------------------------------------------------------------
# 1. Competing-offer register
# ---------------------------------------------------------------------------

def register(offer_id: int, status: str = "written",
             deadline: str | None = None, contact: str = "",
             contact_email: str = "", notes: str = "",
             path: str | Path | None = None) -> dict:
    """Attach leverage metadata (status, deadline, contact) to an offer.

    ``status`` is verbal / written / signed / declined / expired. Only
    verbal and written offers count as leverage; a verbal offer is weak
    leverage because it can evaporate.
    """
    offer = _offer_by_id(offer_id)
    if status not in STATUSES:
        raise LeverageError(
            f"Unknown status '{status}'. Choose from: {', '.join(STATUSES)}")
    deadline = _parse_date(deadline)
    data = _load(path)
    entry = {
        "offer_id": offer_id,
        "company": offer.get("company", ""),
        "role": offer.get("role", ""),
        "status": status,
        "deadline": deadline,
        "contact": contact,
        "contact_email": contact_email,
        "notes": notes,
    }
    for i, e in enumerate(data["offers"]):
        if e.get("offer_id") == offer_id:
            data["offers"][i] = entry
            break
    else:
        data["offers"].append(entry)
    _save(data, path)
    return entry


def list_registered(path: str | Path | None = None,
                    today: str | date | None = None) -> list[dict]:
    """Registered offers enriched with comp + days-left, earliest deadline first."""
    t = _today(today)
    offers = {o.get("id"): o for o in O.list_offers()}
    out = []
    for e in _load(path)["offers"]:
        o = offers.get(e.get("offer_id"), {})
        days_left = None
        if e.get("deadline"):
            days_left = (datetime.strptime(e["deadline"], "%Y-%m-%d").date() - t).days
        out.append({**e,
                    "normalized_annual": o.get("normalized_annual"),
                    "days_left": days_left})
    out.sort(key=lambda e: (e["days_left"] is None, e["days_left"] if e["days_left"] is not None else 0))
    return out


def render_register(entries: list[dict]) -> str:
    """Text table of the competing-offer register."""
    if not entries:
        return ("No competing offers registered. Add one with:\n"
                "  python -m candid offer add --company Acme --role ...   (record the offer)\n"
                "  python -m candid leverage add --offer-id 1 --status written --deadline 2026-10-15")
    lines = [f"{'ID':<4}{'Company':<18}{'Status':<9}{'Deadline':<12}{'Days left':<10}{'Normalized $/yr':<16}Contact",
             "-" * 88]
    for e in entries:
        dl = e["days_left"]
        dl_s = "n/a" if dl is None else (f"{dl}d OVERDUE" if dl < 0 else f"{dl}d")
        lines.append(f"{e['offer_id']:<4}{str(e.get('company',''))[:17]:<18}"
                     f"{e.get('status',''):<9}{str(e.get('deadline') or '-'):12}"
                     f"{dl_s:<10}{_fmt(e.get('normalized_annual')):<16}{e.get('contact','')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Ethical leverage playbook
# ---------------------------------------------------------------------------

ETHICAL_PLAYBOOK = """### The ethical competing-offer playbook

Leverage works because it is *true*. The moment a recruiter suspects a bluff,
you lose not just the negotiation but the offer. These are the rules:

**1. Only cite offers that exist.**
A verbal "we'd love to have you" is not an offer. Cite it as "late stages"
at most. Never invent a number, a company, or a deadline.

**2. Share proof when asked — and expect to be asked.**
Have the offer letter ready (PDF). Redact what is genuinely private, but the
company name, role, level, and total comp should be visible. If you cannot
share it, say why once ("they asked me not to circulate it") — then accept
that the leverage is weaker.

**3. Name real numbers, not vibes.**
"I have a competing offer at $235k total comp" beats "I have a much better
offer." Precision signals truth.

**4. Never use a deadline you do not have.**
"They need an answer Friday" must be a real Friday. Recruiters talk to each
other; fake urgency is the fastest way to get your offer pulled.

**5. Disclose to accelerate, not to threaten.**
Frame: "You're my first choice; I want to give you a chance to compete"
— not "beat this or I walk." Threats end negotiations; enthusiasm plus a
real alternative moves numbers.

**6. Keep every story consistent — log what you said.**
If you tell company A the competing offer is $240k and company B it is
$260k, you will get caught. Use `leverage log` after every disclosure so
your numbers match everywhere.

**7. Don't pit companies against each other in rounds.**
One honest disclosure per company is leverage. Five rounds of "they just
raised, can you go higher" is an auction — good companies walk away from
auctions.

**8. Respect exploding offers honestly.**
If a deadline is truly firm, say so and decide. Accepting just to keep
negotiating elsewhere, then reneging, burns the bridge permanently — and
this industry is small.

**9. Your BATNA is your floor, not your opener.**
Open with your target (BATNA + stretch); let the BATNA be the quiet reason
you can walk away. Leading with "well, I already have X" caps you at X.

**10. Get everything in writing before you sign or resign.**
Verbal improvements evaporate. The final number lives in the offer letter
or it does not exist.
"""


def ethical_playbook() -> str:
    """The ethical competing-offer playbook (feature 2)."""
    return ETHICAL_PLAYBOOK


# ---------------------------------------------------------------------------
# 3. Timeline coordination
# ---------------------------------------------------------------------------

def _urgency(days_left: int | None) -> str:
    if days_left is None:
        return "no deadline"
    if days_left < 0:
        return "expired"
    if days_left <= 3:
        return "urgent"
    if days_left <= 7:
        return "soon"
    return "on track"


def build_timeline(today: str | date | None = None,
                   path: str | Path | None = None) -> dict:
    """Coordinate all offer deadlines into an ordered action plan.

    Returns {"today", "entries", "actions"} where actions are sequenced:
    defuse the earliest deadline first, then accelerate the rest.
    """
    t = _today(today)
    entries = [e for e in list_registered(path, today=t)
               if e.get("status") in ACTIVE_STATUSES]
    for e in entries:
        e["urgency"] = _urgency(e["days_left"])

    actions: list[str] = []
    by_company = {e["offer_id"]: e.get("company", "?") for e in entries}
    dated = [e for e in entries if e["days_left"] is not None]

    for e in entries:
        dl, co = e["days_left"], e.get("company", "?")
        if e["urgency"] == "expired":
            actions.append(
                f"EXPIRED: {co}'s deadline passed — mark it expired "
                f"(`leverage add --offer-id {e['offer_id']} --status expired`) "
                "or confirm an extension in writing.")
        elif e["urgency"] == "urgent":
            actions.append(
                f"DAY 0 (now): {co} decides in {dl}d — request an extension today "
                f"(`leverage extend --offer-id {e['offer_id']} --days 7`) "
                "or finalize your decision.")
        elif e["urgency"] == "soon":
            actions.append(
                f"THIS WEEK: {co} decides in {dl}d — disclose it to your other "
                "final-round companies to accelerate them "
                "(`leverage script --which accelerate_process`).")
        elif e["urgency"] == "no deadline":
            actions.append(
                f"NO DEADLINE: {co} has no recorded deadline — ask your contact "
                f"{e.get('contact') or '(recruiter)'} for the decision timeline "
                f"and register it (`leverage add --offer-id {e['offer_id']} --deadline YYYY-MM-DD`).")

    dated_sorted = sorted(dated, key=lambda e: e["days_left"])
    for i in range(len(dated_sorted) - 1):
        a, b = dated_sorted[i], dated_sorted[i + 1]
        gap = b["days_left"] - a["days_left"]
        if 0 <= gap <= 7 and a["days_left"] >= 0:
            actions.append(
                f"OVERLAP: {a['company']} ({a['days_left']}d) and {b['company']} "
                f"({b['days_left']}d) decide within a week of each other — use the "
                f"earlier deadline to accelerate the later one, and ask the earlier "
                f"for an extension to cover the gap ({gap}d).")

    if not entries:
        actions.append("No active competing offers registered — add them with "
                       "`leverage add --offer-id N --status written --deadline YYYY-MM-DD`.")
    elif not any(e["urgency"] in ("urgent", "soon", "expired") for e in entries):
        actions.append("No deadline pressure right now — keep final rounds moving "
                       "and re-check weekly.")

    return {"today": t.isoformat(), "entries": entries, "actions": actions,
            "by_company": by_company}


def render_timeline(plan: dict) -> str:
    """Render the coordination timeline as text."""
    lines = [f"### Leverage timeline (as of {plan['today']})", ""]
    if plan["entries"]:
        lines.append(f"{'Company':<18}{'Status':<9}{'Deadline':<12}{'Left':<8}Urgency")
        lines.append("-" * 64)
        for e in plan["entries"]:
            dl = e["days_left"]
            dl_s = "n/a" if dl is None else f"{dl}d"
            lines.append(f"{str(e.get('company',''))[:17]:<18}{e.get('status',''):<9}"
                         f"{str(e.get('deadline') or '-'):12}{dl_s:<8}{e['urgency']}")
        lines.append("")
    lines.append("Sequenced actions (do these in order):")
    for i, a in enumerate(plan["actions"], 1):
        lines.append(f"  {i}. {a}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Scenario scripts
# ---------------------------------------------------------------------------

LEVERAGE_SCRIPTS = {
    "first_disclosure": """### Script: first mention of a competing offer

Hi {recruiter},

Quick heads-up on timing: I have a competing offer from {competing_company}
at {competing_total} total comp, and they need an answer by {deadline}.

I want to be upfront because this role is my first choice — {reason}. If we
can get to {target}, I'm ready to sign and close out my search this week.

Happy to share the offer letter once we agree on terms, if that helps with
approvals.

*Rules:* only send this if every fact in it is true. One disclosure per
company; then log it (`leverage log`).""",

    "accelerate_process": """### Script: ask a company to accelerate

Hi {recruiter},

I wanted to share a timing update: I'm holding a written offer from
{other_company} with a decision deadline of {decision_date}, and I'm
currently {current_stage} with {company}.

{company} is genuinely where I'd rather be — but I can't let the other
offer lapse without an answer. Is there any way to compress the remaining
steps into the next {days} days? I'm happy to make myself available
anytime, including evenings.

Thanks for considering it.

*Why it works:* you give them a real reason to move fast without making it
a threat — and you show flexibility on scheduling.""",

    "extension_request": """### Script: ask for a deadline extension (call version)

"I really appreciate the offer — I'm taking it seriously, which is exactly
why I want to ask for a few more days. I have {reason}, and I don't want to
give you a rushed answer I'd regret.

Could we move the decision date from {current_deadline} to {new_date}? I'll
have a firm answer for you by then, and I'll keep you posted if anything
changes sooner."

*Why it works:* you frame the delay as respect for *their* offer, not as
stalling. Always propose a specific new date — "more time" sounds evasive.

(See also: `leverage extend` drafts this as an email.)""",

    "share_offer_letter": """### Script: sharing the offer letter as proof

"Happy to share it — I've attached the letter from {company}. I've redacted
{redacted} since that's personal, but the role, level, and comp are all
visible.

One note: they asked me not to circulate it widely, so I'd appreciate you
keeping it between us and the hiring committee."

*Rules:* only share a real letter. Never Photoshop a number — background
checks and recruiter networks will end your candidacy everywhere if you do.
Redact sparingly; heavy redaction reads as hiding something.""",

    "match_ask": """### Script: ask company B to match/beat company A

Hi {recruiter},

I've now got the written offer from {other_company}: {other_total} total
comp ({breakdown}).

I prefer {company} — the team and the scope are a better fit for me. But
the gap is real, and I'd be leaving money on the table. If you can get to
{target}, I'll sign with {company} and withdraw from the other process
this week.

Can we make that work?

*Why it works:* you name the exact number, give a clear decision rule, and
offer something in return (withdrawing elsewhere). Never run this more than
once per company.""",

    "best_and_final": """### Script: ask for best-and-final

Hi {recruiter},

I want to be respectful of everyone's time, so let me be direct: I have
{competing_summary}, and I need to decide by {deadline}.

{company} is my top choice. Rather than going back and forth, could you take
one shot at your best-and-final number? If you can reach {target}, I'll
accept and we can both move on.

Whatever you come back with, I'll give you a final answer by {deadline}.

*Why it works:* best-and-final only works once, and only when the deadline
is real. It converts a haggling dynamic into a single decision.""",

    "exploding_response": """### Script: respond to an exploding offer

"I understand the timeline, and I appreciate you being direct about it. I
can't accept by {deadline} in good conscience — I have a competing process
at {other_company} wrapping up {needed_date}, and I committed to seeing it
through before I decide anything.

Here's what I can promise: a firm, final answer by {needed_date}. If the
deadline is truly immovable, I understand — but I'd rather be honest now
than accept and renege later, which helps neither of us."

*Why it works:* you call the bluff calmly, give them a concrete alternative
date, and make reneging — the thing they fear most — the reason to grant
the extension. Log the real deadline; never invent one.""",

    "decline_graceful": """### Script: decline while keeping the door (and the leverage) open

Hi {recruiter},

Thank you — sincerely — for the offer and for how well-run this process
was. After a lot of thought, I've decided to accept {accepted_company}.

This was a close call: {genuine_positive}. I'd love to stay in touch, and
if things change down the road, {company} would be my first call.

If you're open to it, I'd also appreciate staying connected with {hiring_manager}
— I have a lot of respect for the team being built there.

*Why it works:* a graceful decline keeps a warm backup (offers fall apart),
protects your reputation, and — used honestly — the fact of the declined
offer is still true leverage history. Never decline a real offer just to
manufacture leverage; that is bluffing with extra steps.""",
}


def get_script(key: str, **fields) -> str:
    """Render a leverage script template with your specifics."""
    if key not in LEVERAGE_SCRIPTS:
        raise LeverageError(
            f"Unknown script '{key}'. Choose from: {', '.join(LEVERAGE_SCRIPTS)}")
    out = LEVERAGE_SCRIPTS[key]
    for k, v in fields.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def render_script_index() -> str:
    """One-line index of the eight leverage scripts."""
    first_lines = {
        "first_disclosure": "first mention of a competing offer (with proof offered)",
        "accelerate_process": "ask a slow company to compress remaining steps",
        "extension_request": "ask for a later decision date (call version)",
        "share_offer_letter": "how to share the letter as proof, safely",
        "match_ask": "ask company B to match/beat company A's written number",
        "best_and_final": "one-shot best-and-final ask against a real deadline",
        "exploding_response": "calm pushback on an exploding offer",
        "decline_graceful": "decline well; keep the door and reputation open",
    }
    lines = ["Leverage scripts (render one with `leverage script --which KEY --set k=v`):", ""]
    for key in LEVERAGE_SCRIPTS:
        lines.append(f"  {key:<18} {first_lines[key]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. BATNA integration
# ---------------------------------------------------------------------------

def batna_report(path: str | Path | None = None,
                 today: str | date | None = None) -> dict:
    """Compute your BATNA from registered offers.

    BATNA = best *written* offer by normalized annual comp. A verbal-only
    BATNA is flagged as weak. Walk-away = BATNA value; target = BATNA + ~7%.
    """
    t = _today(today)
    entries = [e for e in list_registered(path, today=t)
               if e.get("status") in ACTIVE_STATUSES
               and (e.get("days_left") is None or e["days_left"] >= 0)]
    written = [e for e in entries if e["status"] == "written"]
    pool = written or entries
    pool = sorted(pool, key=lambda e: e.get("normalized_annual") or 0, reverse=True)

    if not pool:
        report = (
            "### Your BATNA\n\n"
            "No active competing offers registered, so your BATNA right now is "
            "whatever happens if you walk away: staying in your current role or "
            "keeping the search going.\n\n"
            "That is a *weak* BATNA for negotiation — your first job is to create "
            "a real alternative: accelerate one pipeline to a written offer "
            "(`leverage timeline`), then re-run this report.")
        return {"batna": None, "basis": "no active offers", "walk_away": None,
                "target": None, "weak": True, "report": report}

    best = pool[0]
    value = best.get("normalized_annual") or 0
    weak = not written
    basis = (f"best written offer: {best['company']}" if written
             else f"best verbal offer only: {best['company']} (weak — get it in writing)")
    walk_away = round(value, 2)
    target = round(value * 1.07, 2)

    lines = [
        "### Your BATNA",
        "",
        f"Basis: {basis}",
        f"BATNA value (normalized $/yr): {_fmt(value)}",
        f"Walk-away number: {_fmt(walk_away)} — do not accept below this without",
        "  a non-comp reason you can name out loud.",
        f"Opening target: {_fmt(target)} — BATNA + ~7%; this is your ask.",
        "",
    ]
    if weak:
        lines.append(
            "WARNING: your BATNA is verbal-only. Verbal offers evaporate — push "
            "for the written letter before you cite this number anywhere.")
    if len(pool) > 1:
        lines.append(
            f"Backup alternatives: {', '.join(e['company'] for e in pool[1:3])}.")
    lines += [
        "",
        "BATNA rules: it must be real (logged, with a deadline), current (not "
        "expired), and yours (not a friend's offer). Re-run this after every "
        "new written offer — your walk-away moves when your BATNA moves.",
    ]
    return {"batna": best, "basis": basis, "walk_away": walk_away,
            "target": target, "weak": weak, "report": "\n".join(lines)}


# ---------------------------------------------------------------------------
# 6. Extension-request email drafts
# ---------------------------------------------------------------------------

EXTENSION_REASONS = {
    "final-rounds": "I have final-round interviews I committed to before this offer, and I want to see them through",
    "family-decision": "this is a big move and I want to discuss it properly with my family",
    "logistics": "I'm working through relocation and start-date logistics that affect the decision",
}


def extension_email(name: str, recruiter: str, company: str, role: str,
                    current_deadline: str, new_date: str,
                    reason: str = "final-rounds") -> str:
    """Draft a deadline-extension email. Reason is a key or free text."""
    reason_text = EXTENSION_REASONS.get(reason, reason)
    return f"""Subject: Re: Offer — {role} @ {company} (timeline)

Hi {recruiter},

Thank you again for the offer — I'm excited about {company} and I'm taking
the decision seriously, which is why I'm writing.

{reason_text[0].upper() + reason_text[1:]}, and I don't want to give you a
rushed answer. Would it be possible to move the decision date from
{current_deadline} to {new_date}?

I can promise a firm answer by {new_date}, and I'll keep you posted if
anything changes sooner.

Thanks for understanding,

{name}
"""


def extension_email_for(offer_id: int, days: int,
                        reason: str = "final-rounds", name: str = "Your Name",
                        today: str | date | None = None,
                        path: str | Path | None = None) -> str:
    """Draft an extension email for a registered offer, computing the new date."""
    if days < 1:
        raise LeverageError("days must be >= 1.")
    t = _today(today)
    entries = {e["offer_id"]: e for e in list_registered(path, today=t)}
    entry = entries.get(offer_id)
    if entry is None:
        raise LeverageError(f"Offer #{offer_id} is not in the leverage register. "
                            "Add it: python -m candid leverage add --offer-id N ...")
    offer = _offer_by_id(offer_id)
    base = t
    if entry.get("deadline"):
        base = max(t, datetime.strptime(entry["deadline"], "%Y-%m-%d").date())
    new_date = (base + timedelta(days=days)).isoformat()
    return extension_email(
        name=name,
        recruiter=entry.get("contact") or "there",
        company=entry.get("company") or "",
        role=offer.get("role", ""),
        current_deadline=entry.get("deadline") or t.isoformat(),
        new_date=new_date,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# 7. Deadline tracker
# ---------------------------------------------------------------------------

def deadline_report(today: str | date | None = None,
                    path: str | Path | None = None) -> dict:
    """Urgency table for every active offer + warnings."""
    t = _today(today)
    entries = [e for e in list_registered(path, today=t)
               if e.get("status") in ACTIVE_STATUSES]
    for e in entries:
        e["urgency"] = _urgency(e["days_left"])
    warnings: list[str] = []
    for e in entries:
        dl, co = e["days_left"], e.get("company", "?")
        if e["urgency"] == "expired":
            warnings.append(f"{co}: deadline passed — confirm extension or mark expired.")
        elif e["urgency"] == "urgent":
            warnings.append(f"{co}: decides in {dl}d — extension or decision needed NOW.")
        elif e["status"] == "verbal":
            warnings.append(f"{co}: verbal only — a verbal 'offer' can vanish; get it in writing.")
        if e["days_left"] is None:
            warnings.append(f"{co}: no deadline recorded — ask for the timeline.")
    return {"today": t.isoformat(), "entries": entries, "warnings": warnings}


def render_deadlines(report: dict) -> str:
    """Render the deadline tracker as text."""
    lines = [f"### Offer deadlines (as of {report['today']})", ""]
    if report["entries"]:
        lines.append(f"{'Company':<18}{'Status':<9}{'Deadline':<12}{'Left':<8}Urgency")
        lines.append("-" * 64)
        for e in report["entries"]:
            dl = e["days_left"]
            dl_s = "n/a" if dl is None else f"{dl}d"
            lines.append(f"{str(e.get('company',''))[:17]:<18}{e.get('status',''):<9}"
                         f"{str(e.get('deadline') or '-'):12}{dl_s:<8}{e['urgency']}")
        lines.append("")
    if report["warnings"]:
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  ! {w}")
    else:
        lines.append("No warnings — deadlines are under control.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. Disclosure (honesty) log
# ---------------------------------------------------------------------------

def log_disclosure(company: str, person: str, channel: str, said: str,
                   path: str | Path | None = None) -> dict:
    """Log a competing-offer disclosure so every story stays consistent.

    Log *what you actually said* — the number, the company, the deadline.
    If it differs anywhere, fix it with the recruiter before it spreads.
    """
    if not company or not str(company).strip():
        raise LeverageError("Disclosure needs a company.")
    if not said or not str(said).strip():
        raise LeverageError("Disclosure needs what you said (the --said text).")
    if channel not in CHANNELS:
        raise LeverageError(
            f"Unknown channel '{channel}'. Choose from: {', '.join(CHANNELS)}")
    data = _load(path)
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "company": company,
        "person": person,
        "channel": channel,
        "said": said,
    }
    data["disclosures"].append(rec)
    _save(data, path)
    return rec


def list_disclosures(path: str | Path | None = None) -> list[dict]:
    """All logged disclosures, newest last."""
    return _load(path)["disclosures"]


def render_disclosures(records: list[dict]) -> str:
    """Render the disclosure log as text."""
    if not records:
        return ("No disclosures logged. After every call/email where you mention "
                "a competing offer, run:\n"
                "  python -m candid leverage log --company Acme --person Jane "
                "--channel call --said \"...\"")
    lines = ["### Disclosure log (what you claimed, to whom, when)", ""]
    for r in records:
        lines.append(f"- {r['ts']} | {r['company']} / {r['person']} ({r['channel']})")
        lines.append(f"  said: {r['said']}")
    lines += ["", "Consistency check: re-read this before every negotiation call. "
                  "If two entries disagree, correct the record with the recruiter."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. Leverage strength score
# ---------------------------------------------------------------------------

def leverage_score(today: str | date | None = None,
                   path: str | Path | None = None) -> dict:
    """0-100 score of how much negotiating leverage you actually have."""
    t = _today(today)
    entries = [e for e in list_registered(path, today=t)
               if e.get("status") in ACTIVE_STATUSES
               and (e.get("days_left") is None or e["days_left"] >= 0)]
    written = [e for e in entries if e["status"] == "written"]
    n, nw = len(entries), len(written)

    written_pts = {0: 0, 1: 20, 2: 30}.get(min(nw, 2), 40)
    dated = [e["days_left"] for e in entries if e["days_left"] is not None]
    earliest = min(dated) if dated else None
    if earliest is None:
        runway_pts = 10
    elif earliest >= 14:
        runway_pts = 25
    elif earliest >= 7:
        runway_pts = 15
    elif earliest >= 4:
        runway_pts = 8
    else:
        runway_pts = 3
    breadth_pts = 20 if n >= 2 else (10 if n == 1 else 0)

    penalties: list[str] = []
    score = written_pts + runway_pts + breadth_pts
    if n > 0 and nw == 0:
        score -= 10
        penalties.append("verbal-only (-10): no written offer yet")
    if earliest is not None and earliest <= 3:
        score -= 10
        penalties.append("exploding deadline (-10): a decision is due within 3 days")
    score = max(0, min(100, score))

    verdict = ("strong — you can credibly push for best-and-final" if score >= 70
               else "moderate — real leverage, but mind the weak spots" if score >= 40
               else "weak — build leverage before you negotiate hard")
    levers: list[str] = []
    if nw == 0 and n > 0:
        levers.append("Convert a verbal to written: ask for the offer letter today.")
    if n < 2:
        levers.append("Get a second live process: leverage needs at least two alternatives.")
    if earliest is not None and earliest <= 7:
        levers.append("Defuse the earliest deadline first (`leverage extend`), then negotiate.")
    if earliest is None and n > 0:
        levers.append("Pin down real deadlines — unknown timelines are not leverage.")
    if score >= 70:
        levers.append("Use it: ask your top choice for best-and-final (`leverage script --which best_and_final`).")

    return {"score": score, "verdict": verdict,
            "components": {"written_offers": written_pts, "runway": runway_pts,
                           "breadth": breadth_pts, "penalties": penalties,
                           "n_offers": n, "n_written": nw,
                           "earliest_deadline_days": earliest},
            "levers": levers}


def render_score(result: dict) -> str:
    """Render the leverage score as text."""
    c = result["components"]
    lines = [
        "### Leverage score",
        "",
        f"Score: {result['score']}/100 — {result['verdict']}",
        "",
        f"  Written offers: {c['written_offers']}/40 ({c['n_written']} written of {c['n_offers']} active)",
        f"  Runway:         {c['runway']}/25 (earliest deadline: "
        f"{c['earliest_deadline_days']}d)" if c["earliest_deadline_days"] is not None
        else "  Runway:         10/25 (no deadlines recorded)",
        f"  Breadth:        {c['breadth']}/20",
    ]
    if c["penalties"]:
        lines.append("  Penalties:      " + "; ".join(c["penalties"]))
    if result["levers"]:
        lines.append("")
        lines.append("Pull these levers next:")
        for lv in result["levers"]:
            lines.append(f"  - {lv}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. Decision plan
# ---------------------------------------------------------------------------

def decision_plan(today: str | date | None = None,
                  path: str | Path | None = None) -> dict:
    """Accept / negotiate / hold / decline recommendation per offer + if-thens."""
    t = _today(today)
    score = leverage_score(today=t, path=path)
    batna = batna_report(today=t, path=path)
    ranked = sorted(
        [e for e in list_registered(path, today=t)
         if e.get("status") in ACTIVE_STATUSES
         and (e.get("days_left") is None or e["days_left"] >= 0)],
        key=lambda e: e.get("normalized_annual") or 0, reverse=True)

    recommendations: list[dict] = []
    for i, e in enumerate(ranked):
        co, dl = e.get("company", "?"), e["days_left"]
        comp = _fmt(e.get("normalized_annual"))
        if i == 0:
            if dl is not None and dl <= 5:
                action, why = ("decide",
                               f"top offer ({comp}) but only {dl}d left — "
                               "finalize terms now, then decide")
            elif score["score"] >= 70:
                action, why = ("negotiate",
                               f"top offer ({comp}) and leverage is strong — "
                               "push for best-and-final")
            else:
                action, why = ("negotiate",
                               f"top offer ({comp}) — negotiate, but build "
                               "leverage in parallel (score is not strong yet)")
        else:
            if e["status"] == "verbal":
                action, why = ("hold",
                               f"backup ({comp}) — get it in writing, then it "
                               "becomes real leverage")
            else:
                action, why = ("hold",
                               f"backup ({comp}) — keep warm and accelerate; "
                               "it is your BATNA insurance")
        recommendations.append({"offer_id": e["offer_id"], "company": co,
                                "action": action, "why": why})

    branches: list[str] = []
    if ranked:
        top = ranked[0]
        tgt = batna.get("target")
        branches.append(
            f"If {top['company']} reaches {_fmt(tgt)} → accept and close the search.")
        for e in ranked[1:]:
            branches.append(
                f"If {e['company']} beats {top['company']} by >5% on normalized comp "
                f"→ switch your top choice and re-run this plan.")
        branches.append(
            f"If nothing improves by the earliest deadline → accept the BATNA "
            f"({batna['basis']}) rather than letting it expire.")
        branches.append(
            "If a new written offer arrives → re-register it and re-run "
            "`leverage decide`; your walk-away moves with your BATNA.")
    else:
        branches.append("No active offers — the plan is pipeline: get to final "
                        "rounds in at least two places before negotiating.")

    return {"today": t.isoformat(), "score": score["score"],
            "walk_away": batna.get("walk_away"), "target": batna.get("target"),
            "recommendations": recommendations, "branches": branches}


def render_decision(plan: dict) -> str:
    """Render the decision plan as text."""
    lines = [f"### Decision plan (as of {plan['today']})",
             f"Leverage score: {plan['score']}/100 · "
             f"Walk-away: {_fmt(plan['walk_away'])} · "
             f"Target: {_fmt(plan['target'])}",
             ""]
    if plan["recommendations"]:
        lines.append("Per-offer recommendation:")
        for r in plan["recommendations"]:
            lines.append(f"  [{r['action'].upper():<9}] {r['company']}: {r['why']}")
        lines.append("")
    lines.append("If-then branches:")
    for b in plan["branches"]:
        lines.append(f"  - {b}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Glue: one-page negotiation brief for a single offer
# ---------------------------------------------------------------------------

def negotiation_brief(offer_id: int, today: str | date | None = None,
                      path: str | Path | None = None) -> str:
    """One page: BATNA, deadline, leverage score, and the script to use."""
    t = _today(today)
    offer = _offer_by_id(offer_id)
    entries = {e["offer_id"]: e for e in list_registered(path, today=t)}
    entry = entries.get(offer_id, {})
    batna = batna_report(today=t, path=path)
    score = leverage_score(today=t, path=path)

    is_batna = batna.get("batna") and batna["batna"]["offer_id"] == offer_id
    script_key = ("best_and_final" if score["score"] >= 70 and not is_batna
                  else "match_ask" if not is_batna else "extension_request")

    lines = [
        f"### Negotiation brief: {offer.get('company', '')} — {offer.get('role', '')}",
        "",
        f"Offer: {_fmt(offer.get('normalized_annual'))}/yr normalized "
        f"(base {_fmt(offer.get('base'))}, year-1 {_fmt(offer.get('year1_total'))})",
        f"Status: {entry.get('status', 'not registered')} · "
        f"Deadline: {entry.get('deadline') or 'not recorded'} · "
        f"Contact: {entry.get('contact') or '—'}",
        f"Your BATNA: {batna['basis']} ({_fmt(batna.get('walk_away'))}/yr)",
        f"Walk-away: {_fmt(batna.get('walk_away'))} · "
        f"Target ask: {_fmt(batna.get('target'))}",
        f"Leverage score: {score['score']}/100 ({score['verdict']})",
        "",
        f"Suggested script: {script_key}",
        f"  python -m candid leverage script --which {script_key} --set company=...",
        "",
        "Before the call: re-read your disclosure log (`leverage log --list`) so "
        "every number you cite matches what you already said.",
    ]
    return "\n".join(lines)
