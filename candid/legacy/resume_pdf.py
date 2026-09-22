"""Convert the Gemini-cleaned resume text into a PDF for upload.

Job portals (Workday, iCIMS, Avature, etc.) expect doc/rtf/pdf — a .txt upload
is often rejected. This keeps the pipeline dependency-light by using fpdf2
with its built-in Helvetica font; unicode characters outside latin-1 are
mapped to ASCII equivalents so the PDF renders everywhere.
"""

from __future__ import annotations

from pathlib import Path

_REPLACEMENTS = {
    "\u2022": "-",      # bullet
    "\u2014": "--",     # em dash
    "\u2013": "-",      # en dash
    "\u2018": "'",      # left single quote
    "\u2019": "'",      # right single quote
    "\u201c": '"',      # left double quote
    "\u201d": '"',      # right double quote
    "\u2026": "...",    # ellipsis
    "\u00a0": " ",      # non-breaking space
    "\u2192": "->",     # right arrow
    "\u00b2": "2",      # superscript two
}


def _sanitize(text: str) -> str:
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def text_to_pdf(text: str, dest: str | Path) -> Path:
    """Write plain-text resume to a simple, ATS-friendly PDF. Returns dest."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    dest = Path(dest)
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10.5)
    mc = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for raw_line in _sanitize(text).splitlines():
        line = raw_line.rstrip()
        if not line:
            pdf.ln(4)
            continue
        # ALL-CAPS short lines are section headers -> bold, slightly larger.
        if line.isupper() and len(line) < 40 and line.replace(" ", "").isalpha():
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 6, line, **mc)
            pdf.set_font("Helvetica", size=10.5)
        else:
            pdf.multi_cell(0, 5.5, line, **mc)

    pdf.output(str(dest))
    return dest
