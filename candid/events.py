"""Conference and meetup finder: public tech event listings, relevance
ranking against your profile, and a per-event networking-goal planner.

The dataset (``candid/data/events.json``) is a curated list of well-known
public tech conferences and recurring meetups — no login, no scraping,
no paid API. Each entry carries ``date_confidence``:

* ``verified`` — the dates were checked against the organizer's site.
* ``typical``   — the event recurs annually; the dates follow its usual
  season but are NOT verified. Confirm on the organizer site before booking.
* ``recurring`` — a repeating local meetup; the listed date is the next
  expected occurrence, not a confirmed one.

Pipeline:
    events list [--city NYC] [--virtual] [--topic python] [--free] [--days 90]
    events rank [--limit 10]            # score upcoming events vs your profile
    events show <id>                   # full detail card
    events plan <id>                   # networking-goal planner (saved locally)
    events save <id>                   # park it in the tracker (status: saved)
    events watch add|list|remove <id>  # watchlist of events you're eyeing
    events upcoming [--watched-only]   # what's next on the calendar
    events debrief <id> --contacts ... # post-event follow-up drafts
    events calendar --out events.ics   # ICS export, import anywhere
    events budget <id> [--travel 400 --nights 3 --hotel 200 --budget 2000]
    events topics                       # topic taxonomy with counts

Everything is stored locally (candid_data/event_plans/, events_watch.json).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from candid import config as C

DATA_FILE = Path(__file__).parent / "data" / "events.json"

CONFIDENCE_LABEL = {
    "verified": "dates verified",
    "typical": "dates follow the event's usual season — NOT verified, confirm on organizer site",
    "recurring": "repeating meetup — date is the next expected occurrence, not confirmed",
}

REQUIRED_FIELDS = {"id", "name", "city", "start", "end", "topics", "roles", "url"}

_TODAY: date | None = None  # test hook


class EventsError(Exception):
    """Raised for event-finder failures."""


def _today() -> date:
    return _TODAY or date.today()


def _state_dir() -> Path:
    d = C.DATA_DIR / "event_plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _watch_path() -> Path:
    return C.DATA_DIR / "events_watch.json"


# ---------------------------------------------------------------------------
# dataset loading / validation
# ---------------------------------------------------------------------------

def load_events() -> list[dict]:
    """Load and validate the curated event dataset."""
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EventsError(f"Could not read the events dataset: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise EventsError("Events dataset is empty or malformed.")
    seen: set[str] = set()
    for i, ev in enumerate(raw):
        if not isinstance(ev, dict):
            raise EventsError(f"Event #{i} is not an object.")
        missing = REQUIRED_FIELDS - set(ev)
        if missing:
            raise EventsError(f"Event #{i} ({ev.get('id', '?')}) missing fields: {sorted(missing)}")
        if ev["id"] in seen:
            raise EventsError(f"Duplicate event id: {ev['id']}")
        seen.add(ev["id"])
        for f in ("start", "end"):
            try:
                datetime.strptime(ev[f], "%Y-%m-%d")
            except ValueError:
                raise EventsError(f"Event {ev['id']}: bad {f} date '{ev[f]}' (need YYYY-MM-DD)") from None
        if ev["start"] > ev["end"]:
            raise EventsError(f"Event {ev['id']}: start is after end.")
        if ev.get("date_confidence", "typical") not in CONFIDENCE_LABEL:
            raise EventsError(f"Event {ev['id']}: bad date_confidence '{ev.get('date_confidence')}'.")
    return raw


def get_event(event_id: str, events: list[dict] | None = None) -> dict:
    events = events or load_events()
    for ev in events:
        if ev["id"] == event_id:
            return ev
    raise EventsError(
        f"No event with id '{event_id}'. Run `python -m candid events list` to see ids.\n"
        "Next: run `python -m candid events list`."
    )


def is_upcoming(ev: dict, today: date | None = None) -> bool:
    today = today or _today()
    return ev["end"] >= today.isoformat()


def days_until(ev: dict, today: date | None = None) -> int:
    today = today or _today()
    start = datetime.strptime(ev["start"], "%Y-%m-%d").date()
    return (start - today).days


# ---------------------------------------------------------------------------
# listing / filtering
# ---------------------------------------------------------------------------

def list_events(*, city: str = "", virtual_only: bool = False, topic: str = "",
                free_only: bool = False, days: int | None = None,
                include_past: bool = False, limit: int = 25,
                events: list[dict] | None = None,
                today: date | None = None) -> list[dict]:
    """Filter the dataset. Returns events sorted by start date."""
    today = today or _today()
    out = []
    for ev in (events or load_events()):
        if not include_past and not is_upcoming(ev, today):
            continue
        if city and city.lower() not in (ev.get("city") or "").lower():
            continue
        if virtual_only and ev.get("format") not in ("virtual", "hybrid"):
            continue
        if topic and topic.lower() not in [t.lower() for t in ev.get("topics", [])]:
            continue
        if free_only and (ev.get("cost_usd") or 0) > 0:
            continue
        if days is not None and days_until(ev, today) > days:
            continue
        out.append(ev)
    out.sort(key=lambda e: e["start"])
    return out[: max(limit, 0)] if limit else out


def render_list(events: list[dict], today: date | None = None) -> str:
    today = today or _today()
    if not events:
        return ("No events match. Try widening the filters "
                "(`python -m candid events list --help`).")
    lines = [f"{'ID':<28}{'DATES':<24}{'WHERE':<16}{'COST':<10}WHAT"]
    for ev in events:
        d = days_until(ev, today)
        when = "in {}d".format(d) if d >= 0 else "ended"
        dates = f"{ev['start']} ({when})" if ev["start"] == ev["end"] \
            else f"{ev['start']}->{ev['end']} ({when})"
        cost = "FREE" if not (ev.get("cost_usd") or 0) else f"${ev['cost_usd']:,}"
        conf = "" if ev.get("date_confidence") == "verified" else " *"
        where = ev.get("city", "?")
        if ev.get("format") == "virtual":
            where = "Virtual"
        elif ev.get("format") == "hybrid":
            where += " + virtual"
        lines.append(f"{ev['id']:<28}{dates:<24}{where:<16}{cost:<10}{ev['name']}{conf}")
    if any(ev.get("date_confidence") != "verified" for ev in events):
        lines.append("\n* " + CONFIDENCE_LABEL["typical"])
    return "\n".join(lines)


def render_show(ev: dict, today: date | None = None) -> str:
    today = today or _today()
    d = days_until(ev, today)
    when = f"starts in {d} days" if d > 0 else ("starts today" if d == 0 else "already ended")
    cost = "FREE" if not (ev.get("cost_usd") or 0) else f"${ev['cost_usd']:,} ({ev.get('cost_note', '')})".rstrip(" ()")
    lines = [
        f"{ev['name']} — {ev.get('edition', '')}".rstrip(" —"),
        f"  When:   {ev['start']} → {ev['end']}  ({when})",
        f"  Dates:  {CONFIDENCE_LABEL.get(ev.get('date_confidence', 'typical'))}",
        f"  Where:  {ev.get('city', '?')}, {ev.get('country', '')}  [{ev.get('format', 'in-person')}]".rstrip(),
        f"  Cost:   {cost}",
        f"  Topics: {', '.join(ev.get('topics', []))}",
        f"  For:    {', '.join(ev.get('roles', []))}  ({ev.get('audience', 'all-levels')})",
        f"  Link:   {ev.get('url', '')}",
        "",
        ev.get("description", ""),
    ]
    net = ev.get("networking") or []
    if net:
        lines += ["", "Networking angles:"]
        lines += [f"  • {n}" for n in net]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# relevance ranking vs profile
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", (text or "").lower()))


def _role_tokens(profile: dict) -> set[str]:
    toks: set[str] = set()
    for field in ("headline",):
        toks |= _tokens(profile.get(field) or "")
    for r in profile.get("target_roles") or []:
        toks |= _tokens(r)
    for exp in profile.get("experience") or []:
        toks |= _tokens(exp.get("title") or "")
    return {t for t in toks if len(t) > 2}


def _skill_tokens(profile: dict) -> set[str]:
    toks: set[str] = set()
    for s in profile.get("skills") or []:
        toks |= _tokens(s)
    for d in profile.get("domains") or []:
        toks |= _tokens(d)
    for exp in profile.get("experience") or []:
        for b in exp.get("bullets") or []:
            toks |= _tokens(b)
    return {t for t in toks if len(t) > 2}


_SENIORITY_ORDER = ["student", "entry", "junior", "mid", "senior", "staff", "principal", "lead", "executive"]
_AUDIENCE_MAP = {
    "all-levels": _SENIORITY_ORDER,
    "early-career": ["student", "entry", "junior", "mid"],
    "mid-senior": ["mid", "senior", "staff", "lead"],
    "senior": ["senior", "staff", "principal", "lead", "executive"],
}


def _seniority_score(profile: dict, ev: dict) -> tuple[float, str]:
    prof_sen = (profile.get("seniority") or "mid").lower()
    aud = ev.get("audience", "all-levels")
    ok = _AUDIENCE_MAP.get(aud, _SENIORITY_ORDER)
    if prof_sen in ok:
        return 10.0, f"audience '{aud}' fits your seniority ({prof_sen})"
    return 3.0, f"audience '{aud}' is a stretch for {prof_sen}-level — go for breadth, not recruiting"


def score_event(profile: dict, ev: dict, today: date | None = None) -> dict:
    """Score 0-100 with component breakdown and 'why' bullets."""
    today = today or _today()
    rtoks, stoks = _role_tokens(profile), _skill_tokens(profile)
    why: list[str] = []
    total = 0.0

    # 1. role match (35): event roles vs headline/target roles
    best, best_role = 0.0, ""
    for role in ev.get("roles", []):
        rset = _tokens(role)
        if not rset:
            continue
        overlap = len(rset & rtoks) / len(rset)
        if overlap > best:
            best, best_role = overlap, role
    role_pts = round(best * 35, 1)
    total += role_pts
    if best >= 0.5:
        why.append(f"role fit: '{best_role}' matches your headline/target roles (+{role_pts})")
    elif best > 0:
        why.append(f"partial role fit: '{best_role}' (+{role_pts})")

    # 2. skill/topic match (35): event topics vs skills+domains
    hits: list[str] = []
    for t in ev.get("topics", []):
        tt = _tokens(t)
        if tt & stoks:
            hits.append(t)
    skill_pts = round(min(len(hits) / max(len(ev.get("topics", [])) or 1, 1), 1.0) * 35, 1)
    # small bonus for many distinct topic hits
    skill_pts = min(35.0, skill_pts + min(len(hits), 5))
    total += skill_pts
    if hits:
        why.append(f"topic fit: {', '.join(hits[:5])} overlap your skills/domains (+{skill_pts})")

    # 3. seniority fit (10)
    sen_pts, sen_why = _seniority_score(profile, ev)
    total += sen_pts
    why.append(sen_why + f" (+{sen_pts})")

    # 4. logistics (20): format, location, cost
    log_pts, log_why = 0.0, []
    fmt = ev.get("format", "in-person")
    if fmt in ("virtual", "hybrid"):
        log_pts += 8
        log_why.append("virtual/hybrid option — no travel needed")
    prof_city = (profile.get("location") or "").lower()
    ev_city = (ev.get("city") or "").lower()
    if prof_city and ev_city and prof_city.split(",")[0].strip() in ev_city:
        log_pts += 7
        log_why.append(f"in your city ({ev.get('city')}) — no travel")
    cost = ev.get("cost_usd") or 0
    if cost == 0:
        log_pts += 5
        log_why.append("free to attend")
    elif cost <= 700:
        log_pts += 3
        log_why.append(f"affordable ticket (${cost:,})")
    else:
        log_pts -= 3
        log_why.append(f"pricey ticket (${cost:,}) — needs a business case")
    d = days_until(ev, today)
    if 14 <= d <= 120:
        log_pts += 2
        log_why.append("good planning window")
    total += max(log_pts, 0)
    if log_why:
        why.append("logistics: " + "; ".join(log_why))

    score = max(0, min(100, round(total, 1)))
    verdict = "GO" if score >= 65 else ("CONDITIONAL" if score >= 40 else "SKIP")
    return {
        "id": ev["id"], "name": ev["name"], "score": score, "verdict": verdict,
        "components": {"role": role_pts, "skills": skill_pts,
                       "seniority": sen_pts, "logistics": round(max(log_pts, 0), 1)},
        "why": why, "days_until": d, "cost_usd": cost,
        "date_confidence": ev.get("date_confidence", "typical"),
    }


def rank_events(profile: dict, events: list[dict] | None = None,
                limit: int = 10, today: date | None = None) -> list[dict]:
    today = today or _today()
    events = [e for e in (events or load_events()) if is_upcoming(e, today)]
    ranked = [score_event(profile, e, today) for e in events]
    ranked.sort(key=lambda r: (-r["score"], r["days_until"]))
    return ranked[: max(limit, 0)] if limit else ranked


def render_ranked(ranked: list[dict]) -> str:
    if not ranked:
        return "No upcoming events to rank."
    lines = ["Ranked by fit to your profile (role 35 · skills 35 · seniority 10 · logistics 20):", ""]
    for i, r in enumerate(ranked, 1):
        conf = "" if r["date_confidence"] == "verified" else " *"
        lines.append(f"{i}. [{r['verdict']}] {r['score']:.0f} — {r['name']} ({r['id']}){conf} — in {r['days_until']}d")
        for w in r["why"][:3]:
            lines.append(f"      · {w}")
    if any(r["date_confidence"] != "verified" for r in ranked):
        lines.append("\n* " + CONFIDENCE_LABEL["typical"])
    lines.append("\nNext: `python -m candid events plan <id>` to build your networking plan.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# networking-goal planner
# ---------------------------------------------------------------------------

_ARCHETYPE_BY_TOPIC = {
    "ai-ml": "ML engineers shipping models to production",
    "llm": "engineers building LLM apps and agents",
    "data": "data engineers and analytics leaders",
    "data-engineering": "data platform engineers",
    "python": "Python core contributors and library maintainers",
    "devops": "platform/SRE engineers fighting toil",
    "kubernetes": "CNCF project maintainers",
    "cloud": "cloud architects and FinOps folks",
    "open-source": "maintainers looking for contributors",
    "career": "recruiters and hiring managers",
    "startups": "founders and early employees",
    "research": "PhD students and research scientists",
    "frontend": "frontend engineers and DX tooling authors",
    "web": "full-stack builders",
    "security": "security engineers and AppSec teams",
    "sre": "SREs who've survived real incidents",
    "observability": "observability vendors and practitioners",
    "leadership": "engineering managers and directors",
    "diversity": "ERG leaders and D&I program owners",
    "enterprise-ai": "enterprise AI buyers with real budgets",
    "analytics": "analytics engineers and BI leaders",
    "mlops": "MLOps engineers running models at scale",
    "deep-learning": "deep-learning researchers",
    "reinforcement-learning": "RL researchers and practitioners",
    "software": "staff+ engineers",
    "architecture": "staff/principal engineers",
    "react": "React core team and ecosystem authors",
    "javascript": "JS tooling maintainers",
    "design": "design engineers",
    "distributed-systems": "distributed systems engineers",
    "monitoring": "on-call engineers",
    "reliability": "reliability engineers",
    "platform-engineering": "platform team leads",
    "aws": "AWS heroes and SA teams",
    "gcp": "Google Cloud engineers",
    "azure": "Azure engineers",
    "copilot": "AI coding-assistant builders",
}


def _conversation_starters(profile: dict, ev: dict) -> list[str]:
    skills = (profile.get("skills") or [])[:3]
    skill_bit = f" (I work with {', '.join(skills)})" if skills else ""
    topics = ev.get("topics", [])[:3]
    return [
        f"\"What's the most interesting talk you've seen so far?\"{skill_bit}",
        "\"What are you building right now?\" — then listen for a real problem",
        f"\"How are you thinking about {' / '.join(topics)} this year?\"",
        "\"What's one thing you learned here that changes how you'll work Monday?\"",
        "\"Are you hiring, or is your team growing?\" — direct beats clever",
    ]


def plan_event(profile: dict, event_id: str, *, goals: list[str] | None = None,
               target_contacts: int = 5, today: date | None = None) -> dict:
    """Build a networking-goal plan for one event. Saves JSON + Markdown."""
    today = today or _today()
    ev = get_event(event_id)
    headline = profile.get("headline") or "technologist"
    topics = ev.get("topics", [])
    archetypes = []
    for t in topics:
        a = _ARCHETYPE_BY_TOPIC.get(t)
        if a and a not in archetypes:
            archetypes.append(a)
    archetypes = archetypes[:4] or ["fellow practitioners in your field"]

    default_goals = [
        f"Meet {target_contacts} new people in your target field and exchange contacts",
        f"Learn one concrete technique in {topics[0] if topics else 'your field'} you can apply within 2 weeks",
        "Attend 1 session outside your comfort zone and write up 3 takeaways",
        "Identify 2 companies/teams you'd want to work with and find someone from each",
        "Follow up with every new contact within 48 hours (see `events debrief`)",
    ]
    plan = {
        "event_id": ev["id"],
        "event_name": ev["name"],
        "dates": f"{ev['start']} → {ev['end']}",
        "city": ev.get("city"),
        "format": ev.get("format"),
        "url": ev.get("url"),
        "generated": today.isoformat(),
        "date_confidence": ev.get("date_confidence", "typical"),
        "goals": goals or default_goals,
        "who_to_meet": archetypes,
        "conversation_starters": _conversation_starters(profile, ev),
        "elevator_pitch": (
            f"\"I'm {profile.get('name') or 'a ' + headline} — {headline}. "
            f"Lately I've been working on {topics[0] if topics else 'my craft'} and I'm here "
            f"to meet people doing {topics[1] if len(topics) > 1 else 'interesting work'} in production. "
            f"What brought you here?\""
        ),
        "session_strategy": [
            "Day 1: attend 1 flagship keynote + 2 deep technical talks; spend the rest in the hallway/expo",
            "Prioritize small-room workshops over big keynotes for real conversations",
            "Skip one talk block per day for the hallway track — that's where jobs are found",
            "If there's a job fair, go early on day 1 with a one-pager of your background",
        ],
        "pre_event_checklist": [
            "Update LinkedIn headline and 'open to work' settings",
            "Print or prepare a digital one-pager / QR code to your portfolio",
            "Research 5 speakers or companies; prepare one specific question each",
            "Set a daily contact goal and a note-taking system (phone notes are fine)",
            "Confirm travel + lodging; virtual? test your setup and block your calendar",
        ],
        "follow_up_targets": [
            "Recruiters from companies on your target list",
            "Speakers whose work overlaps your skills",
            "Fellow attendees you had real conversations with (not just card swaps)",
        ],
    }
    d = _state_dir()
    (d / f"{ev['id']}.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (d / f"{ev['id']}.md").write_text(render_plan(plan), encoding="utf-8")
    return plan


def render_plan(plan: dict) -> str:
    L = [f"# Networking plan: {plan['event_name']}",
         f"{plan['dates']} · {plan.get('city')} · [{plan.get('format')}]",
         f"Dates: {CONFIDENCE_LABEL.get(plan.get('date_confidence', 'typical'))}",
         f"Link: {plan.get('url', '')}", "",
         "## Goals"]
    L += [f"{i}. {g}" for i, g in enumerate(plan["goals"], 1)]
    L += ["", "## Who to meet"]
    L += [f"  • {a}" for a in plan["who_to_meet"]]
    L += ["", "## Conversation starters"]
    L += [f"  • {s}" for s in plan["conversation_starters"]]
    L += ["", "## Your elevator pitch", "", plan["elevator_pitch"], "",
          "## Session strategy"]
    L += [f"  • {s}" for s in plan["session_strategy"]]
    L += ["", "## Pre-event checklist"]
    L += [f"  - [ ] {c}" for c in plan["pre_event_checklist"]]
    L += ["", "## Follow-up targets"]
    L += [f"  • {t}" for t in plan["follow_up_targets"]]
    L += ["", "After the event: `python -m candid events debrief "
          + plan["event_id"] + " --contacts \"Name, Role, Company; ...\"`"]
    return "\n".join(L)


def load_plan(event_id: str) -> dict:
    p = _state_dir() / f"{event_id}.json"
    if not p.exists():
        raise EventsError(
            f"No plan saved for '{event_id}'. Run `python -m candid events plan {event_id}` first.")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# tracker integration
# ---------------------------------------------------------------------------

def save_to_tracker(event_id: str) -> dict:
    """Park an event in the application tracker (status 'saved')."""
    from candid import tracker as T
    ev = get_event(event_id)
    cost = "FREE" if not (ev.get("cost_usd") or 0) else f"${ev['cost_usd']:,}"
    notes = (f"Event: {ev['name']} ({ev.get('edition', '')}) — "
             f"{ev['start']} → {ev['end']}, {ev.get('city')} "
             f"[{ev.get('format')}], {cost}. Topics: {', '.join(ev.get('topics', []))}. "
             f"Dates: {ev.get('date_confidence')}.")
    edition = (ev.get("edition") or "").strip()
    role = f"Attendee ({edition})" if edition and edition != "monthly" else "Attendee"
    rec = T.add(company=ev["name"], role=role,
                jd_link=ev.get("url", ""), status="saved", notes=notes)
    return rec


# ---------------------------------------------------------------------------
# watchlist
# ---------------------------------------------------------------------------

def _load_watch() -> list[str]:
    p = _watch_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_watch(ids: list[str]) -> None:
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _watch_path().write_text(json.dumps(ids, indent=2), encoding="utf-8")


def watch_add(event_id: str) -> list[str]:
    get_event(event_id)  # validates
    ids = _load_watch()
    if event_id not in ids:
        ids.append(event_id)
    _save_watch(ids)
    return ids


def watch_remove(event_id: str) -> list[str]:
    ids = [i for i in _load_watch() if i != event_id]
    _save_watch(ids)
    return ids


def watch_list(events: list[dict] | None = None, today: date | None = None) -> list[dict]:
    ids = set(_load_watch())
    return [e for e in (events or load_events()) if e["id"] in ids]


def upcoming_digest(days: int = 90, watched_only: bool = False,
                    today: date | None = None) -> list[dict]:
    """Events starting within `days`, optionally restricted to the watchlist."""
    today = today or _today()
    pool = watch_list(today=today) if watched_only else load_events()
    return [e for e in list_events(days=days, events=pool, today=today)
            if is_upcoming(e, today)]


def render_digest(events: list[dict], today: date | None = None, title: str = "Upcoming events") -> str:
    today = today or _today()
    lines = [f"== {title} ==", ""]
    if not events:
        lines.append("Nothing on the calendar. Add some with `events watch add <id>`.")
        return "\n".join(lines)
    for ev in events:
        d = days_until(ev, today)
        cost = "FREE" if not (ev.get("cost_usd") or 0) else f"${ev['cost_usd']:,}"
        conf = "" if ev.get("date_confidence") == "verified" else " *"
        lines.append(f"• in {d}d — {ev['name']} ({ev['id']}){conf}: "
                     f"{ev['start']} → {ev['end']}, {ev.get('city')} [{ev.get('format')}], {cost}")
    if any(ev.get("date_confidence") != "verified" for ev in events):
        lines.append("\n* " + CONFIDENCE_LABEL["typical"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# post-event debrief: follow-up drafts
# ---------------------------------------------------------------------------

def parse_contacts(raw: str) -> list[dict]:
    """Parse 'Name, Role, Company; Name, Role, Company' into dicts."""
    out = []
    for chunk in (raw or "").split(";"):
        parts = [p.strip() for p in chunk.split(",")]
        if not any(parts):
            continue
        out.append({
            "name": parts[0] if len(parts) > 0 else "",
            "role": parts[1] if len(parts) > 1 else "",
            "company": parts[2] if len(parts) > 2 else "",
            "note": parts[3] if len(parts) > 3 else "",
        })
    return [c for c in out if c["name"]]


def debrief(profile: dict, event_id: str, contacts: list[dict],
            today: date | None = None) -> dict:
    """Draft a follow-up email per contact met at the event. Saves Markdown."""
    today = today or _today()
    ev = get_event(event_id)
    name = profile.get("name") or "there"
    headline = profile.get("headline") or "technologist"
    drafts = []
    for c in contacts:
        who = c["name"]
        context = c.get("note") or f"your talk on {ev['name']}"
        subject = f"Great meeting you at {ev['name']}"
        body = (
            f"Hi {who.split()[0]},\n\n"
            f"It was great meeting you at {ev['name']} — I really enjoyed {context}.\n\n"
            f"I'm {name}, a {headline}. I'd love to stay in touch"
            f"{' and hear more about what your team is building' if c.get('company') else ''}.\n\n"
            f"{'Are you open to a quick coffee chat sometime next week?' if c.get('role') else 'Would love to keep the conversation going.'}\n\n"
            f"Best,\n{name}"
        )
        drafts.append({"to": who, "role": c.get("role", ""), "company": c.get("company", ""),
                       "subject": subject, "body": body})
    result = {"event_id": ev["id"], "event_name": ev["name"],
              "date": today.isoformat(), "drafts": drafts}
    d = _state_dir()
    lines = [f"# Debrief: {ev['name']} ({today.isoformat()})", ""]
    for dr in drafts:
        lines += [f"## To: {dr['to']}"
                  + (f" — {dr['role']}" if dr["role"] else "")
                  + (f" @ {dr['company']}" if dr["company"] else ""),
                  f"Subject: {dr['subject']}", "", dr["body"], "", "---", ""]
    lines.append("Tip: send within 48 hours while the conversation is fresh.")
    (d / f"{ev['id']}_debrief.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def render_debrief(result: dict) -> str:
    lines = [f"Debrief drafts for {result['event_name']} "
             f"(saved to candid_data/event_plans/{result['event_id']}_debrief.md):", ""]
    for dr in result["drafts"]:
        lines += [f"To: {dr['to']}"
                  + (f" — {dr['role']}" if dr["role"] else "")
                  + (f" @ {dr['company']}" if dr["company"] else ""),
                  f"Subject: {dr['subject']}", "", dr["body"], "", "---", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ICS calendar export
# ---------------------------------------------------------------------------

def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def export_ics(events: list[dict], dest: str | Path) -> Path:
    """Write an .ics file for the given events (import into any calendar)."""
    dest = Path(dest)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//candid//events//EN",
             "X-WR-CALNAME:candid tech events"]
    for ev in events:
        start = ev["start"].replace("-", "")
        end = (datetime.strptime(ev["end"], "%Y-%m-%d").date() + timedelta(days=1)).strftime("%Y%m%d")
        summary = f"{ev['name']} ({ev.get('edition', '')})".rstrip(" ()")
        desc = _ics_escape(
            f"{ev.get('description', '')}\nTopics: {', '.join(ev.get('topics', []))}\n"
            f"Cost: {'FREE' if not (ev.get('cost_usd') or 0) else '$' + str(ev.get('cost_usd'))}\n"
            f"Dates: {ev.get('date_confidence')} — confirm on organizer site\n{ev.get('url', '')}")
        loc = _ics_escape(f"{ev.get('city', '')}, {ev.get('country', '')}".strip(", "))
        lines += ["BEGIN:VEVENT", f"UID:{ev['id']}@candid.local", f"DTSTAMP:{now}",
                  f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}",
                  f"SUMMARY:{_ics_escape(summary)}", f"LOCATION:{loc}",
                  f"DESCRIPTION:{desc}", f"URL:{ev.get('url', '')}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    dest.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# budget planner
# ---------------------------------------------------------------------------

def budget_plan(event_id: str, *, travel_usd: float = 0.0, nights: int = 0,
                hotel_per_night: float = 0.0, per_diem: float = 75.0,
                budget: float | None = None) -> dict:
    """Estimate total attendance cost and compare against a budget."""
    ev = get_event(event_id)
    ticket = float(ev.get("cost_usd") or 0)
    start = datetime.strptime(ev["start"], "%Y-%m-%d").date()
    end = datetime.strptime(ev["end"], "%Y-%m-%d").date()
    event_days = max((end - start).days + 1, 1)
    hotel = nights * hotel_per_night
    meals = event_days * per_diem
    total = ticket + travel_usd + hotel + meals
    breakdown = {"ticket": ticket, "travel": travel_usd,
                 "hotel": hotel, "meals_incidentals": meals}
    verdict = "within budget" if budget is None or total <= budget else "OVER budget"
    return {"event_id": ev["id"], "event_name": ev["name"],
            "breakdown": breakdown, "total": round(total, 2),
            "budget": budget, "verdict": verdict, "event_days": event_days}


def render_budget(b: dict) -> str:
    lines = [f"Budget plan: {b['event_name']} ({b['event_days']} days)", ""]
    for k, v in b["breakdown"].items():
        lines.append(f"  {k:<18} ${v:>9,.2f}")
    lines.append(f"  {'TOTAL':<18} ${b['total']:>9,.2f}")
    if b["budget"] is not None:
        lines.append(f"  {'your budget':<18} ${b['budget']:>9,.2f}")
        lines.append(f"\nVerdict: {b['verdict']}")
        if b["verdict"] == "OVER budget":
            over = b["total"] - b["budget"]
            lines.append(f"Over by ${over:,.2f} — consider: virtual pass, fewer hotel nights, "
                         "early-bird/volunteer ticket, or asking your employer to sponsor.")
    else:
        lines.append("\nPass --budget N to compare against your spending limit.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# topic taxonomy
# ---------------------------------------------------------------------------

def topics(events: list[dict] | None = None, today: date | None = None,
           upcoming_only: bool = True) -> list[tuple[str, int]]:
    """(topic, count) sorted by count desc."""
    today = today or _today()
    counts: dict[str, int] = {}
    for ev in (events or load_events()):
        if upcoming_only and not is_upcoming(ev, today):
            continue
        for t in ev.get("topics", []):
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def render_topics(pairs: list[tuple[str, int]]) -> str:
    lines = ["Event topics (upcoming events):", ""]
    for topic, n in pairs:
        lines.append(f"  {topic:<24} {n} event{'s' if n != 1 else ''}")
    lines.append("\nFilter with: `python -m candid events list --topic <name>`")
    return "\n".join(lines)
