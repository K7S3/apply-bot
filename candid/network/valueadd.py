"""Feature 5 - value-add touchpoint ideas.

Networking that only ever asks for things dies. This module suggests
concrete *give-first* touches tailored to what you know about the contact
(role, company, notes, tags) and drafts the message for the idea you pick.
"""

from __future__ import annotations

import hashlib

from candid.network import contacts as CT

IDEA_KINDS = ["article", "intro", "congrats", "resource", "event", "ask_advice"]

_IDEA_TEMPLATES = {
    "article": ("Share an article",
                "Send them a short article tied to something they care about, "
                "with one line on why you thought of them."),
    "intro": ("Make an introduction",
              "Connect them to someone in your network who shares an interest "
              "or could help with something they mentioned."),
    "congrats": ("Congratulate a win",
                 "A promotion, launch, talk, or funding news - a short sincere "
                 "note goes further than a like."),
    "resource": ("Share a resource",
                 "A tool, template, dataset, or repo that maps to a problem "
                 "they mentioned."),
    "event": ("Invite to an event",
              "A meetup, talk, or conference they would genuinely enjoy - "
              "offer to go together."),
    "ask_advice": ("Ask for their advice",
                   "People like being helpful. Ask a specific question in "
                   "their area of expertise, then report back what you did."),
}


def idea_kinds() -> list[str]:
    return list(IDEA_KINDS)


def _deterministic_pick(contact: dict, n: int) -> list[str]:
    """Pick n idea kinds deterministically from the contact's profile."""
    seed = f"{contact['id']}|{contact['name']}|{contact['role']}|" \
           f"{contact['company']}|{' '.join(contact['tags'])}|{contact['notes']}"
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    kinds = list(IDEA_KINDS)
    # Boost kinds that match signals in the profile.
    text = (contact["role"] + " " + contact["notes"] + " "
            + " ".join(contact["tags"])).lower()
    boosted: list[str] = []
    if any(w in text for w in ("hiring", "recruit", "talent", "team")):
        boosted.append("intro")
    if any(w in text for w in ("speak", "talk", "conference", "meetup", "event")):
        boosted.append("event")
    if any(w in text for w in ("launch", "founder", "startup", "product")):
        boosted.append("congrats")
    if any(w in text for w in ("research", "paper", "phd", "ml", "data")):
        boosted.append("article")
    ordered = boosted + [k for k in kinds if k not in boosted]
    # Deterministic rotation by hash so different contacts get different mixes.
    rot = h % len(ordered)
    ordered = ordered[rot:] + ordered[:rot]
    seen, out = set(), []
    for k in ordered:
        if k not in seen:
            seen.add(k)
            out.append(k)
        if len(out) == n:
            break
    return out


def suggest_ideas(contact_id: int, n: int = 3) -> list[dict]:
    """Suggest n value-add touch ideas for a contact."""
    contact = CT.get_contact(contact_id)
    n = max(1, min(int(n), len(IDEA_KINDS)))
    ideas = []
    for kind in _deterministic_pick(contact, n):
        title, why = _IDEA_TEMPLATES[kind]
        ideas.append({"kind": kind, "title": title, "why": why})
    return ideas


def draft_value_add(your_name: str, contact_id: int, kind: str,
                    detail: str = "") -> str:
    """Draft the actual message for a chosen value-add idea."""
    contact = CT.get_contact(contact_id)
    if kind not in _IDEA_TEMPLATES:
        raise ValueError(f"Unknown idea kind '{kind}'. Choose from: "
                         f"{', '.join(IDEA_KINDS)}.")
    detail = detail.strip() or "[the specific article / person / resource]"
    first = contact["name"].split()[0]
    bodies = {
        "article": (
            f"Hi {first},\n\nI came across {detail} and immediately thought "
            f"of our conversation about {contact['met_at_event'] or 'your work'}. "
            f"Figured it might be useful - no reply needed.\n\nBest,\n{your_name}"),
        "intro": (
            f"Hi {first},\n\nYou mentioned {detail} - I know someone who "
            f"might be worth meeting on that front. Happy to make a double "
            f"opt-in intro if you're interested; just say the word.\n\nBest,\n{your_name}"),
        "congrats": (
            f"Hi {first},\n\nSaw the news about {detail} - congratulations, "
            f"that's a big deal. Hope you're taking a moment to enjoy it.\n\nBest,\n{your_name}"),
        "resource": (
            f"Hi {first},\n\nRemember you mentioning {detail}? I put together "
            f"/ found something that might help - sharing it here in case "
            f"it's useful. Happy to walk you through it.\n\nBest,\n{your_name}"),
        "event": (
            f"Hi {first},\n\nThere's {detail} coming up and it struck me as "
            f"very much your thing. I'm planning to go - want to join? "
            f"Could be a good excuse to catch up in person.\n\nBest,\n{your_name}"),
        "ask_advice": (
            f"Hi {first},\n\nI keep thinking about something you said regarding "
            f"{detail}. I'm facing a version of that now - would you have 15 "
            f"minutes to share how you'd think about it? Would really value "
            f"your take.\n\nThanks,\n{your_name}"),
    }
    return f"Subject: Thought of you\n\n{bodies[kind]}"


def render_ideas(contact_id: int, ideas: list[dict]) -> str:
    contact = CT.get_contact(contact_id)
    lines = [f"Value-add ideas for {contact['name']}:"]
    for i, idea in enumerate(ideas):
        lines.append(f"  {i}. [{idea['kind']}] {idea['title']}: {idea['why']}")
    lines.append("Draft one with: candid network value-add "
                 f"{contact_id} --kind <kind> --detail \"...\"")
    return "\n".join(lines)
