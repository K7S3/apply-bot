"""Academic CV export for candid.

Builds a structured academic CV from the user's stored profile and renders
it as plain text or LaTeX. Groundedness is a hard rule: every section comes
from the profile; sections with no data are omitted, never fabricated.

NOTE: the batch-19 task brief asked to reuse ``candid.tailor.latex_escape``,
but no such helper exists anywhere in this worktree (checked tailor.py and
the whole package), so this module defines its own private ``_latex_escape``.
Nothing is copied from elsewhere; if a shared helper is added later, the
two can be unified.
"""

from __future__ import annotations

import argparse
import unicodedata

# ---------------------------------------------------------------------------
# LaTeX escaping (private; see module docstring for why it lives here)
# ---------------------------------------------------------------------------

_LATEX_REPLACEMENTS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _latex_escape(text: object) -> str:
    """Escape text for LaTeX and make it ASCII-safe.

    Every LaTeX special character (\\ & % $ # _ { } ~ ^) is escaped, and
    non-ASCII characters are transliterated/dropped so the output compiles
    with plain pdflatex.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return "".join(_LATEX_REPLACEMENTS.get(ch, ch) for ch in s)


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------

def _as_str_list(value) -> list[str]:
    """Normalize an optional profile list (strings or dicts) to strings."""
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                out.append(item.strip())
        elif isinstance(item, dict):
            parts = [str(v).strip() for v in item.values() if str(v).strip()]
            if parts:
                out.append(" — ".join(parts))
    return out


def _format_publication(pub) -> str:
    """Format one publication (string or dict) as a citation line."""
    if isinstance(pub, str):
        return pub.strip()
    if isinstance(pub, dict):
        authors = str(pub.get("authors", "")).strip()
        year = str(pub.get("year", "")).strip()
        title = str(pub.get("title", "")).strip()
        venue = str(pub.get("venue", "") or pub.get("journal", "") or pub.get("conference", "")).strip()
        bits: list[str] = []
        if authors:
            bits.append(authors)
        if year:
            bits.append(f"({year})")
        if title:
            bits.append(f'"{title}."')
        if venue:
            bits.append(venue)
        return " ".join(bits).strip() or " — ".join(
            str(v).strip() for v in pub.values() if str(v).strip()
        )
    return str(pub).strip()


# ---------------------------------------------------------------------------
# CV builder
# ---------------------------------------------------------------------------

def build_academic_cv(profile: dict) -> dict:
    """Build a structured academic CV dict from a candid profile.

    Keys present depend on the profile: optional sections (publications,
    teaching, grants, service) appear ONLY when the profile actually has
    them; otherwise they are omitted entirely (no empty sections).
    """
    profile = profile or {}
    cv: dict = {
        "name": profile.get("name", ""),
        "headline": profile.get("headline", ""),
        "location": profile.get("location", ""),
        "summary": profile.get("summary", ""),
        "skills": list(profile.get("skills") or []),
        "education": [
            {
                "school": e.get("school", ""),
                "degree": e.get("degree", ""),
                "dates": e.get("dates", ""),
            }
            for e in (profile.get("education") or [])
            if isinstance(e, dict)
        ],
        "appointments": [
            {
                "title": e.get("title", ""),
                "organization": e.get("company", ""),
                "dates": e.get("dates", ""),
                "bullets": list(e.get("bullets") or []),
            }
            for e in (profile.get("experience") or [])
            if isinstance(e, dict)
        ],
    }

    publications = [
        _format_publication(p)
        for p in (profile.get("publications") or [])
    ]
    publications = [p for p in publications if p]
    if publications:
        cv["publications"] = publications

    teaching = _as_str_list(profile.get("teaching"))
    if teaching:
        cv["teaching"] = teaching

    grants = _as_str_list(profile.get("grants"))
    if grants:
        cv["grants"] = grants

    service = _as_str_list(profile.get("service"))
    if service:
        cv["service"] = service

    return cv


# ---------------------------------------------------------------------------
# text rendering
# ---------------------------------------------------------------------------

def export_text(cv: dict) -> str:
    """Render the CV dict as plain text."""
    lines: list[str] = []
    name = cv.get("name", "")
    lines.append(name)
    lines.append("=" * max(len(name), 1))
    for key in ("headline", "location"):
        if cv.get(key):
            lines.append(cv[key])
    if cv.get("summary"):
        lines.append("")
        lines.append("SUMMARY")
        lines.append(cv["summary"])

    def _section(title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append("")
        lines.append(title.upper())
        for item in items:
            lines.append(f"  - {item}")

    _section("Education", [
        " — ".join(p for p in (e.get("degree"), e.get("school"), e.get("dates")) if p)
        for e in cv.get("education", [])
    ])
    appt_lines: list[str] = []
    for a in cv.get("appointments", []):
        head = " — ".join(p for p in (a.get("title"), a.get("organization"), a.get("dates")) if p)
        appt_lines.append(head)
        for b in a.get("bullets", []):
            appt_lines.append(f"    * {b}")
    _section("Appointments", appt_lines)
    _section("Publications", cv.get("publications", []))
    _section("Teaching", cv.get("teaching", []))

    grants_service = list(cv.get("grants", [])) + list(cv.get("service", []))
    _section("Grants & Service", grants_service)

    _section("Skills", [", ".join(cv.get("skills", []))] if cv.get("skills") else [])
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# LaTeX rendering
# ---------------------------------------------------------------------------

def export_latex(cv: dict) -> str:
    """Render the CV dict as a complete, compilable LaTeX document.

    Sections with no data are omitted (not left empty). All user text is
    passed through _latex_escape; the output is ASCII-safe.
    """
    e = _latex_escape
    out: list[str] = []
    out.append(r"\documentclass[11pt]{article}")
    out.append(r"\usepackage[margin=1in]{geometry}")
    out.append(r"\usepackage{enumitem}")
    out.append(r"\usepackage[hidelinks]{hyperref}")
    out.append(r"\setlength{\parindent}{0pt}")
    out.append(r"\setlength{\parskip}{4pt}")
    out.append(r"\begin{document}")

    name = e(cv.get("name", ""))
    if name:
        out.append(r"{\Large\bfseries " + name + r"}\\[2pt]")
    for key in ("headline", "location"):
        if cv.get(key):
            out.append(e(cv[key]) + r"\\")
    if cv.get("summary"):
        out.append("")
        out.append(r"\section*{Summary}")
        out.append(e(cv["summary"]))

    def _section(title: str, body_lines: list[str]) -> None:
        if not body_lines:
            return
        out.append("")
        out.append(r"\section*{" + e(title) + "}")
        out.append(r"\begin{itemize}[leftmargin=*,itemsep=2pt]")
        out.extend(body_lines)
        out.append(r"\end{itemize}")

    _section("Education", [
        r"\item " + " -- ".join(e(p) for p in (x.get("degree"), x.get("school"), x.get("dates")) if p)
        for x in cv.get("education", [])
    ])

    appt_items: list[str] = []
    for a in cv.get("appointments", []):
        head = " -- ".join(e(p) for p in (a.get("title"), a.get("organization"), a.get("dates")) if p)
        if head:
            appt_items.append(r"\item \textbf{" + head + "}")
        for b in a.get("bullets", []):
            appt_items.append(r"\item[] \hspace{1em}-- " + e(b))
    _section("Appointments", appt_items)

    _section("Publications", [r"\item " + e(p) for p in cv.get("publications", [])])
    _section("Teaching", [r"\item " + e(t) for t in cv.get("teaching", [])])

    grants_service = [r"\item " + e(g) for g in cv.get("grants", [])]
    grants_service += [r"\item " + e(s) for s in cv.get("service", [])]
    _section("Grants and Service", grants_service)

    if cv.get("skills"):
        _section("Skills", [r"\item " + e(", ".join(cv["skills"]))])

    out.append("")
    out.append(r"\end{document}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_academic_cv(a: argparse.Namespace) -> None:
    """CLI handler for `candid academic-cv`."""
    from candid import profile as P
    prof = P.load_profile()
    cv = build_academic_cv(prof)
    if a.text:
        print(export_text(cv))
        return
    tex = export_latex(cv)
    if a.tex:
        with open(a.tex, "w", encoding="utf-8") as f:
            f.write(tex)
        print(f"Saved to {a.tex}")
    else:
        print(tex)


def add_parsers(subparsers) -> None:
    """Register the `academic-cv` subcommand on an argparse subparsers object."""
    s = subparsers.add_parser(
        "academic-cv",
        help="Export an academic CV (text or LaTeX) from your profile.",
        description=(
            "Build an academic CV from your stored profile: education, "
            "appointments, publications, teaching, grants/service. Sections "
            "with no data are omitted, never fabricated."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "examples:",
            "  python -m candid academic-cv                 # LaTeX to stdout",
            "  python -m candid academic-cv --tex cv.tex     # write LaTeX file",
            "  python -m candid academic-cv --text           # plain text to stdout",
        ]),
    )
    s.add_argument("--tex", default="", help="Write LaTeX CV to this file")
    s.add_argument("--text", action="store_true", help="Print plain-text CV instead of LaTeX")
    s.set_defaults(func=cmd_academic_cv)
