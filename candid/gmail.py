"""Gmail auto-ingest from Google Takeout mbox exports.

Privacy model:
- candid NEVER connects to your Google account. There is no OAuth, no API
  calls, no credentials, no tokens — nothing leaves this machine.
- You export your own mail: Google Takeout (takeout.google.com) →
  deselect all → check "Mail" → Next step → Create export → download, then
  feed the ``.mbox`` file (or a directory of them) to
  ``python -m candid gmail import <file.mbox>``.
- An import only *proposes* tracker entries (company/role/stage extracted
  from recruiter outreach, interview invites, and offer letters). Nothing is
  written to your tracker until you confirm — ``gmail confirm <id>`` or the
  dashboard.
- The mbox file stays where you put it; candid only reads it.

Standard library only (mailbox + email).
"""

from __future__ import annotations

import json
import mailbox
import re
from pathlib import Path

from candid import config as C

# proposal kind -> tracker status written on confirm
KIND_TO_STATUS = {
    "recruiter_outreach": "saved",
    "interview_invite": "selected_for_interview",
    "offer": "offer",
    "rejection": "rejected",
}

TAKEOUT_GUIDE = """\
How to get your Gmail as an mbox file (takes ~2 minutes):

1. Go to https://takeout.google.com and sign in.
2. Click "Deselect all", then scroll down and check "Mail".
   (Click "All Mail data included" if you only want certain labels.)
3. Click "Next step" → leave the defaults → "Create export".
4. Google emails you when the export is ready — download the .zip and
   unzip it. Inside you'll find one or more .mbox files
   (e.g. Takeout/Mail/All mail Including Spam and Trash.mbox).
5. Feed it to candid:
       python -m candid gmail import /path/to/your.mbox

candid never connects to your Google account — you export, you import,
nothing leaves this machine.
"""


class GmailError(Exception):
    """Raised for Gmail import problems."""


# ---------------------------------------------------------------------------
# mbox parsing (stdlib mailbox)
# ---------------------------------------------------------------------------

def iter_mbox_files(path: str | Path) -> list[Path]:
    """A .mbox file, or every .mbox under a directory (Takeout unzips)."""
    p = Path(path).expanduser()
    if p.is_file():
        if p.suffix.lower() != ".mbox":
            raise GmailError(f"{p} is not a .mbox file.")
        return [p]
    if p.is_dir():
        files = sorted(p.rglob("*.mbox"))
        if not files:
            raise GmailError(f"No .mbox files found under {p}.")
        return files
    raise GmailError(f"Not found: {p}")


def _message_text(msg) -> str:
    """Best-effort plain-text body of an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
                    "attachment" not in part.get("Content-Disposition", ""):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload or "")


def parse_mbox(path: str | Path) -> list[dict]:
    """Parse an mbox file into message dicts.

    Each dict: {id, from, subject, date, snippet, body}. ``id`` prefers the
    Message-ID header so re-imports dedupe; falls back to a positional key.
    """
    p = Path(path)
    messages: list[dict] = []
    box = mailbox.mbox(str(p))
    try:
        for i, msg in enumerate(box):
            msg_id = (msg.get("Message-ID") or msg.get("X-GM-THRID")
                      or f"{p.name}#{i}")
            body = _message_text(msg)
            clean = re.sub(r"\s+", " ", body).strip()
            messages.append({
                "id": msg_id.strip(),
                "from": msg.get("From", "") or "",
                "subject": msg.get("Subject", "") or "",
                "date": msg.get("Date", "") or "",
                "snippet": clean[:300],
                "body": clean[:4000],
            })
    finally:
        box.close()
    return messages


# ---------------------------------------------------------------------------
# classification + extraction (pure functions — fully unit-tested)
# ---------------------------------------------------------------------------

_REJECTION = re.compile(
    r"unfortunately|not moving forward|decided to (pursue|move forward with) other|"
    r"regret to inform|won't be (moving|proceeding)", re.I)
_OFFER = re.compile(
    r"offer letter|offer package|congratulations.{0,60}offer|welcome to the team|"
    r"your offer from", re.I)
_INTERVIEW = re.compile(
    r"interview|phone screen|technical screen|onsite|on-site|next round|"
    r"schedule (a|your) (call|interview)|your availability|assessment (link|invite)", re.I)
_RECRUITER = re.compile(
    r"recruit|talent acquisition|talent partner|staffing|reaching out|"
    r"your (profile|background|experience)|open (role|position|opportunity)|"
    r"would you be (open|interested)", re.I)


def classify_message(subject: str, sender: str, snippet: str) -> tuple[str, float]:
    """Classify a message. Returns (kind, confidence). Kinds: interview_invite,
    offer, rejection, recruiter_outreach, other."""
    text = f"{subject} {snippet}"
    if _OFFER.search(text):
        return "offer", 0.85
    if _REJECTION.search(text):
        return "rejection", 0.8
    if _INTERVIEW.search(text):
        return "interview_invite", 0.75
    if _RECRUITER.search(text) or _RECRUITER.search(sender):
        return "recruiter_outreach", 0.6
    return "other", 0.0


def _clean_company(name: str) -> str:
    name = re.sub(r"\s+via\s+LinkedIn\s*$", "", name, flags=re.I)
    name = re.sub(r"\s*(careers|recruiting|talent|hiring|hr|jobs)\s*$", "", name, flags=re.I)
    name = re.sub(r"^[\"']|[\"']$", "", name).strip()
    return name


def extract_company_role(subject: str, sender: str, snippet: str) -> tuple[str, str, float]:
    """Heuristic extraction. Returns (company, role, confidence)."""
    company, role, conf = "", "", 0.3

    # parens first: "Jane Doe (Hooli Talent) via LinkedIn" → Hooli Talent
    # (kept verbatim — it's the org name as the recruiter wrote it)
    paren = re.search(r"\(([^)]+)\)", sender)
    if paren:
        company = re.sub(r"\s+via\s+LinkedIn\s*$", "", paren.group(1),
                         flags=re.I).strip().strip("'\"")
    # display name: "Acme Careers <...>" → Acme
    if not company:
        m = re.match(r'\s*"?([^"<(@]+?)"?\s*(?:<|$)', sender)
        if m:
            company = _clean_company(m.group(1))
    # subject: "Interview with Acme"
    if not company or len(company.split()) > 4:
        m = re.search(r"[Ii]nterview with ([A-Z][\w&.\- ]{1,40})", subject)
        if m:
            company = m.group(1).strip()
            conf = max(conf, 0.6)
    # bare email domain: "jane@hoolistaffing.com" → Hoolistaffing
    if not company:
        m = re.search(r"@([\w-]+)\.", sender)
        dom = m.group(1).lower() if m else ""
        if dom and dom not in ("gmail", "yahoo", "hotmail", "outlook",
                               "linkedin", "aol", "icloud"):
            company = _clean_company(dom)
            conf = max(conf, 0.4)

    # role from subject
    for pat in (r"[Ii]nterview\s+[Ii]nvitation:?\s*([A-Z][\w\s/\-&,+]{2,60})",
                r"[Ii]nterview (?:for|as|:)?\s*([A-Z][\w\s/\-&,+]{2,60}?)(?:\s*[—–|\-]\s*|\s*$)",
                r"[Oo]pportunity:?\s*([A-Z][\w\s/\-&,+]{2,60})",
                r"[Rr]ole:?\s*([A-Z][\w\s/\-&,+]{2,60})",
                r"([A-Z][\w\s/\-&,+]{2,60}?)\s+(?:[Ii]nterview|[Oo]pportunity|[Rr]ole)\b"):
        m = re.search(pat, subject)
        if m:
            role = m.group(1).strip(" -–—|")
            if 2 < len(role) < 70:
                conf = max(conf, 0.6)
                break
    return company.strip(), role.strip(), conf


# ---------------------------------------------------------------------------
# proposals (never silent writes)
# ---------------------------------------------------------------------------

def _load_proposals(path: Path | None = None) -> list[dict]:
    p = Path(path) if path else C.GMAIL_PROPOSALS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_proposals(proposals: list[dict], path: Path | None = None) -> Path:
    p = Path(path) if path else C.GMAIL_PROPOSALS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(proposals, indent=2), encoding="utf-8")
    return p


def import_mbox(path: str | Path, max_messages: int = 0,
                proposals_path: Path | None = None) -> dict:
    """Import a Takeout .mbox file (or directory of them).

    Parses, classifies, and extracts recruiter/interview/offer mail and
    stores NEW proposals (status=pending). Re-imports dedupe on Message-ID.
    Nothing is written to the tracker — confirm each proposal yourself.

    Returns {"files", "messages", "new_proposals", "skipped_other"}.
    """
    files = iter_mbox_files(path)
    proposals = _load_proposals(proposals_path)
    seen_ids = {p.get("message_id") for p in proposals}
    new: list[dict] = []
    total = 0
    skipped_other = 0
    for f in files:
        for msg in parse_mbox(f):
            if max_messages and total >= max_messages:
                break
            total += 1
            if msg["id"] in seen_ids:
                continue
            seen_ids.add(msg["id"])
            kind, conf = classify_message(msg["subject"], msg["from"],
                                          msg["snippet"] + " " + msg["body"][:1500])
            if kind == "other":
                skipped_other += 1
                continue
            company, role, xconf = extract_company_role(msg["subject"],
                                                        msg["from"],
                                                        msg["snippet"])
            new.append({
                "id": max([p.get("id", 0) for p in proposals] + [0]) + len(new) + 1,
                "kind": kind,
                "confidence": round(min(conf + xconf, 1.0) / 2 + 0.25, 2),
                "company": company,
                "role": role,
                "from": msg["from"],
                "subject": msg["subject"],
                "date": msg["date"],
                "snippet": msg["snippet"],
                "message_id": msg["id"],
                "source_file": str(f),
                "status": "pending",
            })
        if max_messages and total >= max_messages:
            break
    if new:
        proposals.extend(new)
        _save_proposals(proposals, proposals_path)
    return {
        "files": [str(f) for f in files],
        "messages": total,
        "new_proposals": new,
        "skipped_other": skipped_other,
    }


def list_proposals(status: str | None = None,
                   path: Path | None = None) -> list[dict]:
    proposals = _load_proposals(path)
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return proposals


def confirm_proposal(proposal_id: int, proposals_path: Path | None = None,
                     tracker_path: Path | None = None) -> dict:
    """User-confirmed: write the proposal into the tracker. Returns the record."""
    from candid import tracker as T
    proposals = _load_proposals(proposals_path)
    p = next((x for x in proposals if x.get("id") == proposal_id), None)
    if p is None:
        raise GmailError(f"No proposal with id {proposal_id}.")
    if p.get("status") != "pending":
        raise GmailError(f"Proposal #{proposal_id} is already {p.get('status')}.")
    status = KIND_TO_STATUS.get(p["kind"], "saved")
    company = p.get("company") or "(unknown company)"
    role = p.get("role") or "(unknown role)"
    apps = T.list_apps(path=tracker_path)
    existing = next((a for a in apps
                     if a["company"].lower() == company.lower()
                     and a["role"].lower() == role.lower()), None)
    if existing:
        rec = T.update(existing["id"], status=status,
                       notes=(existing.get("notes", "")
                              + f" [via Gmail: {p['kind']}]").strip(),
                       path=tracker_path)
    else:
        rec = T.add(company, role, status=status,
                    notes=f"From Gmail: {p['subject'][:120]}", path=tracker_path)
    p["status"] = "confirmed"
    p["tracker_id"] = rec["id"]
    _save_proposals(proposals, proposals_path)
    return rec


def reject_proposal(proposal_id: int, path: Path | None = None) -> None:
    proposals = _load_proposals(path)
    p = next((x for x in proposals if x.get("id") == proposal_id), None)
    if p is None:
        raise GmailError(f"No proposal with id {proposal_id}.")
    p["status"] = "rejected"
    _save_proposals(proposals, path)


def render_import_summary(result: dict) -> str:
    lines = [f"Parsed {result['messages']} message(s) from "
             f"{len(result['files'])} mbox file(s)."]
    new = result["new_proposals"]
    if new:
        lines.append(f"\n✅ {len(new)} new proposal(s) — confirm each before "
                     "anything touches your tracker:\n")
        lines.append(render_proposals(new))
    else:
        lines.append("No new job mail found (everything already imported).")
    return "\n".join(lines)


def render_proposals(proposals: list[dict]) -> str:
    if not proposals:
        return "No Gmail proposals. Run: python -m candid gmail import <file.mbox>"
    lines = [f"{'ID':<4}{'Kind':<20}{'Company':<22}{'Role':<30}Confidence"]
    for p in proposals:
        lines.append(f"{p['id']:<4}{p['kind']:<20}{p.get('company', '')[:21]:<22}"
                     f"{p.get('role', '')[:29]:<30}{p.get('confidence', '')}")
        lines.append(f"     ↳ {p.get('subject', '')[:100]}")
    lines.append("\nNothing is written to your tracker until you confirm:")
    lines.append("  python -m candid gmail confirm <id>   # or reject with: gmail reject <id>")
    return "\n".join(lines)
