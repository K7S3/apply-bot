"""Export candid artifacts to external formats (Obsidian, .eml, vCard).

This module is wired into the CLI by the coordinator (phase 2) via
``register(subparsers)``, which adds a top-level ``export`` command:

    python -m candid export prep-obsidian --company X --role Y --out ~/vault
    python -m candid export followup-eml --kind thank-you --company X --out f.eml
    python -m candid export contact-vcard --name "Jane Doe" --email j@x.com

Everything here consumes the *real* outputs of the other modules
(``prep.build_pack`` packs from ``config.PREP_PACKS_DIR``,
``followup.thank_you`` / ``check_in`` / ``referral_ask`` drafts) -
nothing is invented.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from candid import config as C


class ExportError(Exception):
    """Raised when an export cannot be produced."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_slug(company: str, role: str) -> str:
    """Mirror prep.py's filename slug so we can find saved packs."""
    return "".join(
        c if c.isalnum() or c in "-_" else "_" for c in f"{company}-{role}"
    )[:60]


def _fs_name(text: str) -> str:
    """Sanitize a name for use as a file/folder name (keeps it readable)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip().strip(".")
    return name or "untitled"


def find_prep_pack(company: str, role: str) -> Path | None:
    """Locate the newest saved prep pack for a company/role.

    Matches prep.py's ``{date}_{safe}.md`` naming first, then falls back to
    the pack's own title line (``# Interview Prep — {role} @ {company}``).
    Returns None when nothing matches.
    """
    d = C.PREP_PACKS_DIR
    if not d.is_dir():
        return None
    slug = _safe_slug(company, role)
    candidates: list[tuple[str, Path]] = []
    for p in sorted(d.glob("*.md")):
        hit = slug and slug in p.stem
        if not hit:
            try:
                first = p.read_text(encoding="utf-8").splitlines()[:3]
            except OSError:
                continue
            title = " ".join(first).lower()
            hit = (company.lower() in title and role.lower() in title)
        if hit:
            # filename prefix is YYYY-MM-DD; sort newest-first by name.
            candidates.append((p.name, p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _split_pack_sections(markdown: str) -> list[tuple[str, str]]:
    """Split a prep-pack markdown into (heading, body) pairs on ## headings."""
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if heading is not None:
                sections.append((heading, "\n".join(body).strip()))
            heading = m.group(1)
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, "\n".join(body).strip()))
    return sections


def _classify(h: str) -> str:
    """Classify a pack section heading into an Obsidian note bucket."""
    low = h.lower()
    if "company-specific" in low or "general preparation" in low or "mock interview" in low:
        return "questions"
    if "concept" in low or "deep-dive" in low:
        return "concepts"
    if "star" in low:
        return "star"
    if "checklist" in low or "compensation" in low or "priority focus" in low:
        return "checklist"
    return "misc"


# ---------------------------------------------------------------------------
# 1. prep -> Obsidian vault folder
# ---------------------------------------------------------------------------

def export_prep_obsidian(company: str, role: str, out_dir: str | Path) -> Path:
    """Split a saved prep pack into an Obsidian vault folder.

    Creates ``<out_dir>/Prep - <company> - <role>/`` containing an index note
    (YAML frontmatter + [[wikilinks]]) and four child notes. Returns the
    folder path. Raises ExportError when no pack is found.
    """
    pack = find_prep_pack(company, role)
    if pack is None:
        raise ExportError(
            f"No prep pack found for {role!r} @ {company!r} in "
            f"{C.PREP_PACKS_DIR}. Build one first: "
            f"`python -m candid prep --company {company!r} --role {role!r}`"
        )
    markdown = pack.read_text(encoding="utf-8")

    buckets: dict[str, list[tuple[str, str]]] = {
        "questions": [], "concepts": [], "star": [], "checklist": [], "misc": [],
    }
    for heading, body in _split_pack_sections(markdown):
        buckets[_classify(heading)].append((heading, body))

    folder = Path(out_dir) / _fs_name(f"Prep - {company} - {role}")
    folder.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    tag_company = re.sub(r"\W+", "", company.replace(" ", "_")).lower() or "company"

    def _note(title: str, parts: list[tuple[str, str]], fallback: str) -> str:
        lines = [f"# {title}", ""]
        if parts:
            for heading, body in parts:
                lines += [f"## {heading}", "", body, ""]
        else:
            lines += [fallback, ""]
        return "\n".join(lines).rstrip() + "\n"

    questions_md = _note(
        "Questions",
        buckets["questions"],
        "_No question sections were found in this pack._",
    )
    concepts_md = _note(
        "Concepts",
        buckets["concepts"],
        "_No concept deep-dives were found in this pack._",
    )
    star_md = _note(
        "STAR stories",
        buckets["star"],
        "_No STAR prompts were found in this pack - write 3 STAR stories from "
        "your proudest projects._",
    )
    checklist_parts = buckets["checklist"]
    misc_extra = buckets["misc"]
    checklist_md = _note(
        "Checklist",
        checklist_parts + misc_extra,
        "_No checklist sections were found in this pack._",
    )

    (folder / "Questions.md").write_text(questions_md, encoding="utf-8")
    (folder / "Concepts.md").write_text(concepts_md, encoding="utf-8")
    (folder / "STAR stories.md").write_text(star_md, encoding="utf-8")
    (folder / "Checklist.md").write_text(checklist_md, encoding="utf-8")

    index = "\n".join([
        "---",
        f"company: {company}",
        f"role: {role}",
        f"date: {today}",
        f"tags: [interview-prep, {tag_company}]",
        f"source: {pack.name}",
        "---",
        "",
        f"# Prep — {role} @ {company}",
        "",
        f"Interview prep pack split from `{pack.name}` ({today}).",
        "",
        "## Notes",
        "",
        "- [[Questions]]",
        "- [[Concepts]]",
        "- [[STAR stories]]",
        "- [[Checklist]]",
        "",
    ])
    (folder / _fs_name(f"Prep - {company} - {role}.md")).write_text(index, encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# 2. follow-up draft -> .eml
# ---------------------------------------------------------------------------

_FOLLOWUP_KINDS = ("thank-you", "check-in", "referral")
_FOLLOWUP_GENERATORS = {
    "thank-you": ("thank_you", "thank-you email"),
    "check-in": ("check_in", "recruiter check-in"),
    "referral": ("referral_ask", "referral request"),
}


def _sender_name(override: str = "") -> str:
    if override:
        return override
    try:
        from candid import profile as P
        return P.load_profile().get("name", "") or ""
    except Exception:
        return ""


def export_followup_eml(kind: str, company: str, role: str = "",
                        to: str = "", out: str | Path = "followup.eml",
                        counterparty: str = "", tone: str = "warm",
                        sender_name: str = "", sender_email: str = "") -> Path:
    """Generate a follow-up draft via followup.py and write it as an .eml file.

    The draft's own ``Subject:`` line becomes the message header; the
    trailing ``*Timing: ...*`` note from the draft is kept in the body.
    ``to`` may be empty: the To: header is then left blank but present.
    """
    if kind not in _FOLLOWUP_GENERATORS:
        raise ExportError(f"Unknown kind {kind!r}. Choose from {list(_FOLLOWUP_GENERATORS)}.")
    func_name, _label = _FOLLOWUP_GENERATORS[kind]

    name = _sender_name(sender_name)
    cp = counterparty or "there"
    from candid import followup as F
    gen = getattr(F, func_name)
    if func_name == "thank_you":
        draft = gen(name, cp, role, company, tone=tone)
    elif func_name == "check_in":
        draft = gen(name, cp, role, company, tone=tone)
    else:
        draft = gen(name, cp, role, company)

    subject, _, body = draft.partition("\n\n")
    subject = subject.removeprefix("Subject:").strip()
    body = body.strip() + "\n"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email or name or "me"
    msg["To"] = to or ""
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    out_path = Path(out)
    if out_path.parent != Path("."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(msg.as_string(), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# 3. contact -> vCard 3.0
# ---------------------------------------------------------------------------

def _vcard_escape(text: str) -> str:
    return (text.replace("\\", "\\\\")
                 .replace("\n", "\\n")
                 .replace(";", "\\;")
                 .replace(",", "\\,"))


def _vcard_text(name: str, email: str, phone: str = "",
                org: str = "", title: str = "") -> str:
    parts = name.strip().split()
    family, given = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (name.strip(), "")
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{_vcard_escape(family)};{_vcard_escape(given)};;;",
        f"FN:{_vcard_escape(name.strip())}",
    ]
    if org:
        lines.append(f"ORG:{_vcard_escape(org)}")
    if title:
        lines.append(f"TITLE:{_vcard_escape(title)}")
    if email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_vcard_escape(email)}")
    if phone:
        lines.append(f"TEL;TYPE=WORK,VOICE:{_vcard_escape(phone)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def export_contact_vcard(name: str, email: str, phone: str = "",
                         org: str = "", title: str = "",
                         out: str | Path = "contact.vcf") -> Path:
    """Write a single contact as a vCard 3.0 (.vcf) file. Returns the path."""
    if not name.strip():
        raise ExportError("A contact name is required for a vCard.")
    out_path = Path(out)
    if out_path.parent != Path("."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_vcard_text(name, email, phone, org, title),
                        encoding="utf-8", newline="")
    return out_path


# ---------------------------------------------------------------------------
# CLI wiring (coordinator calls register() in phase 2)
# ---------------------------------------------------------------------------

def cmd_prep_obsidian(args: argparse.Namespace) -> int:
    try:
        folder = export_prep_obsidian(args.company, args.role, args.out)
    except ExportError as e:
        print(f"export: {e}")
        return 1
    print(f"Wrote Obsidian notes to {folder}")
    return 0


def cmd_followup_eml(args: argparse.Namespace) -> int:
    try:
        path = export_followup_eml(
            kind=args.kind, company=args.company, role=args.role,
            to=args.to, out=args.out, counterparty=args.counterparty,
            tone=args.tone, sender_name=args.sender_name,
            sender_email=args.sender_email,
        )
    except ExportError as e:
        print(f"export: {e}")
        return 1
    print(f"Wrote {path}")
    return 0


def cmd_contact_vcard(args: argparse.Namespace) -> int:
    try:
        path = export_contact_vcard(
            name=args.name, email=args.email, phone=args.phone,
            org=args.org, title=args.title, out=args.out,
        )
    except ExportError as e:
        print(f"export: {e}")
        return 1
    print(f"Wrote {path}")
    return 0


def register(subparsers) -> None:
    """Register the top-level ``export`` command on an argparse subparsers.

    Adds ``export`` with subcommands ``prep-obsidian``, ``followup-eml``,
    and ``contact-vcard``. Call it like:

        sub = parser.add_subparsers(dest="cmd", required=True)
        exports.register(sub)
    """
    p = subparsers.add_parser(
        "export", help="Export candid artifacts to other formats "
                       "(Obsidian, .eml, vCard).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python -m candid export prep-obsidian --company X --role Y --out vault/\n"
               "  python -m candid export followup-eml --kind thank-you --company X --out mail.eml\n"
               "  python -m candid export contact-vcard --name \"Jane Doe\" --email jane@x.com")
    sub = p.add_subparsers(dest="export_cmd", required=True,
                           metavar="<format>",
                           help="export format")

    s = sub.add_parser("prep-obsidian",
                       help="Split a saved interview prep pack into an "
                            "Obsidian vault folder.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid export prep-obsidian "
                              "--company X --role Y --out vault/")
    s.add_argument("--company", required=True, help="Company name")
    s.add_argument("--role", required=True, help="Role title")
    s.add_argument("--out", required=True,
                   help="Vault directory; the prep folder is created inside it")
    s.set_defaults(func=cmd_prep_obsidian)

    s = sub.add_parser("followup-eml",
                       help="Generate a follow-up draft and save it as an "
                            ".eml email file.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid export followup-eml --kind thank-you "
                              "--company X --out mail.eml")
    s.add_argument("--kind", required=True, choices=list(_FOLLOWUP_KINDS),
                   help="thank-you | check-in | referral")
    s.add_argument("--company", required=True, help="Company name")
    s.add_argument("--role", default="", help="Role title")
    s.add_argument("--to", default="",
                   help="Recipient email (To: left blank if omitted)")
    s.add_argument("--counterparty", default="",
                   help="Interviewer / recruiter / contact name "
                        "(defaults to a generic greeting)")
    s.add_argument("--tone", default="warm",
                   choices=["warm", "formal", "concise", "enthusiastic"],
                   help="Draft tone (thank-you / check-in only)")
    s.add_argument("--sender-name", default="",
                   help="Your name (defaults to profile name)")
    s.add_argument("--sender-email", default="",
                   help="Your email for the From: header")
    s.add_argument("--out", required=True, help="Output .eml file path")
    s.set_defaults(func=cmd_followup_eml)

    s = sub.add_parser("contact-vcard",
                       help="Write a contact as a vCard 3.0 (.vcf) file.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n"
                              "  python -m candid export contact-vcard "
                              "--name \"Jane Doe\" --email jane@x.com --out jane.vcf")
    s.add_argument("--name", required=True, help="Contact full name")
    s.add_argument("--email", required=True, help="Contact email")
    s.add_argument("--phone", default="", help="Phone number")
    s.add_argument("--org", default="", help="Organization / company")
    s.add_argument("--title", default="", help="Job title")
    s.add_argument("--out", default="contact.vcf",
                   help="Output .vcf file path (default: contact.vcf)")
    s.set_defaults(func=cmd_contact_vcard)
