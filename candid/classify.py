"""Recruiter message classifier (heuristic, fully offline).

Buckets inbound mail from a Gmail Takeout mbox into:

- direct_outreach   a real person at the hiring company (hiring manager,
                    team lead, founder, ...)
- agency_outreach   a third-party recruiter / staffing agency
- interview_invite  interview invites / scheduling ("book a time",
                    "share your availability", phone screens, ...)
- unsure            ambiguous - never forced into a wrong bucket

Every classification carries human-readable reasons naming the signals
that fired, so you can see exactly why a message landed in its bucket.

Interview invites become tracker *proposals* (pending), routed through
the existing ``gmail confirm`` / ``gmail reject`` flow - nothing touches
the tracker until you confirm.

Heuristic rules only: sender domain vs company domain, subject keywords,
body signals. No model downloads, no network, stdlib only. The rules and
their limits are documented in docs/classify.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from candid import gmail as G

BUCKETS = ("direct_outreach", "agency_outreach", "interview_invite", "unsure")

BUCKET_LABELS = {
    "direct_outreach": "Direct outreach (hiring company)",
    "agency_outreach": "Agency / third-party recruiter",
    "interview_invite": "Interview invites / scheduling",
    "unsure": "Unsure (review manually)",
}


class ClassifyError(Exception):
    """Raised for classifier problems."""


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

# Strong: any single hit means "interview invite / scheduling".
_STRONG_INTERVIEW = [
    (re.compile(r"calendly\.com|cal\.com/|calendly", re.I),
     "contains a scheduling link (Calendly/Cal.com)"),
    (re.compile(r"\binterview (invitation|invite|scheduled|confirmed)\b", re.I),
     "says 'interview invitation/invite'"),
    (re.compile(r"\b(phone|technical) screen\b", re.I),
     "mentions a phone/technical screen"),
    (re.compile(r"\bon-?site interview\b", re.I),
     "mentions an onsite interview"),
    (re.compile(r"\b(final|next) round\b", re.I),
     "mentions a final/next round"),
    (re.compile(r"\bshare (?:me )?your availability\b"
                r"|\bsend (?:me |over )?your availability\b", re.I),
     "asks you to share your availability"),
    (re.compile(r"\bcalendar (?:invite|invitation)\b", re.I),
     "mentions a calendar invite"),
    (re.compile(r"\bcoding (?:challenge|assessment)\b|\btake-?home\b|\bhirevue\b", re.I),
     "mentions a coding assessment/take-home"),
]

# Weak: needs 2+ hits. A single "let's schedule a call" in first-touch
# outreach is an intro chat, not an interview invite.
_WEAK_INTERVIEW = [
    (re.compile(r"\binterview\b", re.I), "mentions an interview"),
    (re.compile(r"\bschedul\w*\b", re.I), "mentions scheduling"),
    (re.compile(r"\bon-?site\b", re.I), "mentions onsite"),
    (re.compile(r"\bavailability\b", re.I), "mentions availability"),
]

# A person writing as the company itself.
_DIRECT = [
    (re.compile(r"\bhiring manager\b", re.I),
     "says 'hiring manager'"),
    (re.compile(r"\bmy team\b", re.I),
     "talks about 'my team'"),
    (re.compile(r"\bi'?m (?:the|an?|our) [^.\n]{1,60}?\s+at\s+[A-Z][\w&.'-]*", re.I),
     "introduces themselves as a <title> at <company>"),
    (re.compile(r"\bwe'?re hiring\b", re.I),
     "says \"we're hiring\""),
    (re.compile(r"\bi lead\b", re.I),
     "says 'I lead' (a team)"),
    (re.compile(r"\b(engineering manager|director of engineering|"
                r"vp of engineering|cto|ceo|co-?founder)\b", re.I),
     "sender/title is a company-side leader"),
]

# A third party selling someone else's opening.
_AGENCY = [
    (re.compile(r"\bmy client\b|\bour client\b|\bthe client\b", re.I),
     "talks about 'my/our/the client' (third party)"),
    (re.compile(r"\bc2c\b|\bcorp[- ]to[- ]corp\b", re.I),
     "mentions C2C/corp-to-corp"),
    (re.compile(r"\b(w2|1099)\b", re.I),
     "mentions W2/1099 contract terms"),
    (re.compile(r"\$\s?\d+\s?/\s?hr", re.I),
     "quotes an hourly rate"),
    (re.compile(r"\bhot requirement\b|\burgent requirement\b", re.I),
     "uses staffing-style 'hot/urgent requirement' language"),
    (re.compile(r"\bdear (candidate|job seeker|applicant)\b", re.I),
     "addresses 'dear candidate' (mass outreach)"),
    (re.compile(r"\bcontract (?:opportunity|position|role)\b", re.I),
     "describes a contract opportunity"),
]

_FREE_MAIL = ("gmail", "yahoo", "hotmail", "outlook", "icloud", "aol",
              "proton", "protonmail", "gmx", "yandex", "zoho", "fastmail")

# Keywords in the sender's domain root that mark a staffing/recruiting firm.
_AGENCY_DOMAIN_KW = ("staffing", "recruit", "talent", "headhunt",
                     "workforce", "placement")


def _dedup(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _addr_parts(sender: str) -> tuple[str, str, str]:
    """Split a From header into (display name, email, domain root)."""
    sender = sender or ""
    m = re.search(r"<([^<>@\s]+@[^<>\s]+)>", sender)
    email = m.group(1) if m else (sender.strip() if "@" in sender else "")
    display = re.sub(r"<[^<>]*>", "", sender).strip().strip('"').strip()
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    root = domain.split(".")[0] if domain else ""
    return display, email, root


def _agency_domain(root: str) -> bool:
    return bool(root) and root not in _FREE_MAIL and \
        any(k in root for k in _AGENCY_DOMAIN_KW)


def _agency_evidence(sender: str, subject: str, body: str) -> list[str]:
    ev: list[str] = []
    _, _, root = _addr_parts(sender)
    text = f"{subject or ''}\n{body or ''}"
    if _agency_domain(root):
        ev.append(f"sender domain '{root}' looks like a staffing/recruiting firm")
    for rx, reason in _AGENCY:
        if rx.search(text):
            ev.append(reason)
    return _dedup(ev)


def _direct_evidence(sender: str, subject: str, body: str) -> list[str]:
    ev: list[str] = []
    display, email, root = _addr_parts(sender)
    text = f"{subject or ''}\n{body or ''}"
    body_low = (body or "").lower()
    for rx, reason in _DIRECT:
        if rx.search(text):
            ev.append(reason)
    if root and root not in _FREE_MAIL and not _agency_domain(root):
        if len(root) >= 4 and re.search(r"\b" + re.escape(root) + r"\w*", body_low):
            ev.append(f"sender domain '{root}' matches a company named in the message")
        if re.match(r'^\s*"?[A-Z][\w.\'-]+ [A-Z][\w.\'-]+', display):
            ev.append(f"sender looks like a person at a company domain "
                      f"({email or root})")
    return _dedup(ev)


def _sender_note(agency: list[str], direct: list[str]) -> str:
    if agency:
        return "sender shows agency/third-party signals"
    if direct:
        return "sender shows company-side (direct) signals"
    return "no clear sender-type signal"


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def classify_recruiter(sender: str, subject: str,
                       body: str) -> tuple[str, list[str]]:
    """Classify one message. Returns (bucket, reasons).

    Buckets: direct_outreach, agency_outreach, interview_invite, unsure.
    ``reasons`` is a list of human-readable strings naming the signals
    that fired. Ambiguous mail lands in "unsure" - it is never forced
    into a wrong bucket.
    """
    text = f"{subject or ''}\n{body or ''}"
    strong = _dedup(r for rx, r in _STRONG_INTERVIEW if rx.search(text))
    weak = _dedup(r for rx, r in _WEAK_INTERVIEW if rx.search(text))
    agency = _agency_evidence(sender, subject, body)
    direct = _direct_evidence(sender, subject, body)

    # Interview intent wins over sender type: an interview invite from an
    # agency recruiter is still something you need to schedule.
    if strong or len(weak) >= 2:
        reasons = strong + weak
        reasons.append(_sender_note(agency, direct))
        return "interview_invite", _dedup(reasons)

    if agency and direct:
        return "unsure", _dedup([
            "conflicting signals (agency: " + "; ".join(agency) + ")",
            "conflicting signals (direct: " + "; ".join(direct) + ")",
            "not forced into a bucket - review this one manually",
        ])

    if agency:
        return "agency_outreach", agency
    if direct:
        return "direct_outreach", direct

    if weak:
        return "unsure", [
            "only a single weak scheduling/interview mention ("
            + "; ".join(weak)
            + ") - not enough to call it an interview invite",
        ]
    return "unsure", ["no recruiter, agency, or interview signals found"]


# ---------------------------------------------------------------------------
# mbox driver: classify every message, propose interview invites
# ---------------------------------------------------------------------------

def classify_mbox(path: str | Path, *, max_messages: int = 0,
                  proposals_path: Path | None = None) -> dict:
    """Classify every message in a Takeout .mbox file (or directory).

    Returns {"files", "messages", "buckets", "new_proposals",
    "skipped_duplicates"}. ``buckets`` maps each bucket name to a list of
    {"message", "reasons"}.

    Messages in the interview_invite bucket become pending tracker
    proposals via gmail.draft_proposals (same dedupe as gmail import).
    Nothing is written to the tracker - confirm each proposal with
    ``gmail confirm <id>``.
    """
    files = G.iter_mbox_files(path)
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    invites: list[dict] = []
    total = 0
    for f in files:
        for msg in G.parse_mbox(f):
            if max_messages and total >= max_messages:
                break
            total += 1
            msg = dict(msg)
            msg["source_file"] = str(f)
            bucket, reasons = classify_recruiter(msg["from"], msg["subject"],
                                                 msg["body"])
            buckets[bucket].append({"message": msg, "reasons": reasons})
            if bucket == "interview_invite":
                msg["classify_confidence"] = min(
                    0.55 + 0.08 * len(reasons), 0.95)
                msg["classify_reasons"] = reasons
                invites.append(msg)
        if max_messages and total >= max_messages:
            break
    prop = (G.draft_proposals(invites, kind="interview_invite",
                              proposals_path=proposals_path)
            if invites else {"new_proposals": [], "skipped_duplicates": 0})
    return {
        "files": [str(f) for f in files],
        "messages": total,
        "buckets": buckets,
        "new_proposals": prop["new_proposals"],
        "skipped_duplicates": prop["skipped_duplicates"],
    }


def render_classify_summary(res: dict) -> str:
    """Human-readable listing of messages by bucket, with reasons."""
    lines = [f"Classified {res['messages']} message(s) from "
             f"{len(res['files'])} mbox file(s)."]
    for bucket in BUCKETS:
        items = res["buckets"][bucket]
        lines.append(f"\n## {BUCKET_LABELS[bucket]} - {len(items)}")
        for item in items[:50]:
            msg = item["message"]
            subj = (msg.get("subject") or "(no subject)")[:90]
            sender = (msg.get("from") or "(unknown sender)")[:70]
            lines.append(f"  * {subj}")
            lines.append(f"    from: {sender}")
            lines.append(f"    why: {'; '.join(item['reasons'])}")
        if len(items) > 50:
            lines.append(f"  ... and {len(items) - 50} more")
    new = res["new_proposals"]
    if new:
        lines.append(f"\n✅ {len(new)} interview invite(s) became pending "
                     f"proposal(s). Confirm each before anything touches "
                     f"your tracker:\n")
        lines.append(G.render_proposals(new))
    else:
        lines.append("\nNo interview invites found - nothing proposed.")
    if res.get("skipped_duplicates"):
        lines.append(f"({res['skipped_duplicates']} invite(s) already "
                     f"proposed - skipped.)")
    return "\n".join(lines)
