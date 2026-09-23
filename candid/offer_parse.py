"""Offer letter parser: heuristic extraction from a PDF offer letter.

Reads an offer letter PDF (via pypdf, the same dependency onboard uses for
resume PDFs) and extracts base salary, bonus target %, sign-on, equity
(RSUs/options: share count or dollar value + vesting), start date, and
benefit mentions into the fields the offer normalizer (candid/offer.py)
expects.

The extraction is heuristic regex only. It NEVER invents a number: every
extracted field carries the source snippet it came from, fields that are not
found are left blank, and the missing ones are listed explicitly. The caller
confirms (or passes --yes) before anything is written to offers.json.
"""

from __future__ import annotations

import re
from pathlib import Path

from candid import offer as O

__all__ = [
    "read_letter_text",
    "parse_letter_text",
    "render_extraction",
    "confirm_and_add",
]


# ---------------------------------------------------------------------------
# text extraction (same pypdf dependency as onboard's resume parsing)
# ---------------------------------------------------------------------------

def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # noqa: F401
        except ImportError as exc:
            raise O.OfferError(
                "Reading PDFs needs the 'pypdf' package. Install it with:\n"
                "    pip install pypdf\n"
                "Or export the offer letter as .txt / .md instead."
            ) from exc
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(parts).strip()
    if len(text) < 50:
        raise O.OfferError(
            f"Could not extract text from {path} "
            "(it may be a scanned image PDF — export as text instead)."
        )
    return text


def read_letter_text(path: str | Path) -> str:
    """Read an offer letter (.pdf, .txt, .md) into plain text."""
    p = Path(path)
    if not p.exists():
        raise O.OfferError(f"Offer letter not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix in (".md", ".txt", ".text", ""):
        return p.read_text(encoding="utf-8", errors="replace")
    raise O.OfferError(
        f"Unsupported file type '{suffix}' for {p}. Use a .pdf offer letter."
    )


# ---------------------------------------------------------------------------
# extraction heuristics
# ---------------------------------------------------------------------------

# A dollar amount: $190,000 / $190000 / $190K / $25,000.00
_AMT = r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*([Kk])?\b"


def _money(num: str, k: str | None) -> float:
    val = float(num.replace(",", ""))
    if k:
        val *= 1000
    return val


def _snippet(text: str, match: re.Match, width: int = 140) -> str:
    """The sentence-ish window around a match, as extraction evidence."""
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    # snap to sentence boundaries when cheap
    left = text.rfind(".", 0, match.start())
    if left != -1 and match.start() - left < width:
        start = left + 1
    right = text.find(".", match.end())
    if right != -1 and right - match.end() < width:
        end = right + 1
    return " ".join(text[start:end].split())


def _first(text: str, patterns: list[str]):
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m
    return None


# field -> ordered regexes (first match wins; patterns are most-specific first)
_BASE_PATTERNS = [
    r"annual\s+base\s+salary\s*(?:of|is|:|will\s+be)?\s*" + _AMT,
    r"base\s+salary\s*(?:of|is|:|will\s+be)?\s*" + _AMT,
    r"base\s+pay\s*(?:of|is|:)?\s*" + _AMT,
    r"annual\s+salary\s*(?:of|is|:)?\s*" + _AMT,
]

_BONUS_PCT_PATTERNS = [
    r"target\s+(?:annual\s+)?bonus\s*(?:of|is|:|at)?\s*(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s*%",
    r"bonus\s*(?:of|is|:|at)?\s*(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s*%\s*(?:of\s+(?:your\s+)?base)",
    r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s+(?:your\s+)?base\s+salary\s+)?(?:as\s+a\s+)?(?:target\s+)?bonus",
    r"bonus[^\n.]{0,80}?(\d+(?:\.\d+)?)\s*%",
]

_GUARANTEED_BONUS_PATTERNS = [
    r"guaranteed\s+(?:first[\s-]*year\s+)?(?:annual\s+)?bonus\s*(?:of|is|:)?\s*" + _AMT,
    r"first[\s-]*year\s+(?:guaranteed\s+)?bonus\s*(?:of|is|:)?\s*" + _AMT,
]

_SIGNON_PATTERNS = [
    r"sign(?:ing)?[\s-]*on\s+bonus\s*(?:of|in\s+the\s+amount\s+of|is|:)?\s*" + _AMT,
    _AMT + r"\s+sign(?:ing)?[\s-]*on\s+bonus",
    r"one[\s-]*time\s+(?:cash\s+)?(?:sign(?:ing)?[\s-]*on\s+)?(?:bonus|payment)\s*(?:of|is|:)?\s*" + _AMT,
]

_EQUITY_VALUE_PATTERNS = [
    r"(?:restricted\s+stock\s+units?|RSUs?)\s*(?:with\s+a\s+)?(?:grant\s+)?(?:fair\s+)?value\s+of\s*(?:approximately\s+)?" + _AMT,
    r"grant\s+value\s+of\s*(?:approximately\s+)?" + _AMT,
    _AMT + r"\s*(?:in\s+)?(?:restricted\s+stock\s+units?|RSUs?)\b",
    r"equity\s+(?:grant|award|package)\s*(?:of|valued\s+at|worth|:)?\s*" + _AMT,
    r"grant\s+of\s*" + _AMT + r"\s*(?:in\s+)?(?:restricted\s+stock\s+units?|RSUs?)",
    r"stock\s+option\s+(?:grant|award)\s*(?:of|valued\s+at|worth|:)?\s*" + _AMT,
]

_EQUITY_SHARES_PATTERNS = [
    r"(?<!\$)\b([\d,]+)\s*(?:restricted\s+stock\s+units?|RSUs?)\b",
    r"(?<!\$)\b([\d,]+)\s*stock\s+options?\b",
]

_VEST_YEARS_PATTERNS = [
    r"vest(?:ing)?\s+over\s+(?:a\s+)?(\d+)\s*years?",
    r"(\d+)[\s-]*year\s+vesting",
    r"vesting\s+(?:period|schedule)\s*(?:of|is|:)?\s*(\d+)\s*years?",
]

_START_DATE_PATTERNS = [
    r"(?:anticipated\s+|expected\s+|proposed\s+)?start\s+date\s*(?:of|is|:|will\s+be)?\s*([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
]

# benefit keyword -> canonical label
_BENEFIT_KEYWORDS = [
    ("401(k)", r"401\s*\(k\)"),
    ("health insurance", r"health\s+(?:insurance|coverage|plan)|medical\s+(?:insurance|coverage|plan)"),
    ("dental", r"\bdental\b"),
    ("vision", r"\bvision\b"),
    ("PTO", r"\bPTO\b|paid\s+time\s+off"),
    ("vacation", r"\bvacation\b"),
    ("parental leave", r"parental\s+leave|maternit|paternit"),
    ("life insurance", r"life\s+insurance"),
    ("disability", r"disabilit"),
    ("HSA/FSA", r"\bHSA\b|\bFSA\b"),
]

#: offer fields the normalizer turns into comparable $/yr; reported missing if absent
_CORE_FIELDS = ["base", "bonus_target_pct", "sign_on", "equity_total", "benefits_value"]


def parse_letter_text(text: str) -> dict:
    """Extract offer fields from letter text.

    Returns {"fields", "evidence", "missing", "benefit_mentions"}. "fields"
    holds only what was found, keyed by offer.add() field names; "evidence"
    maps each field to the source snippet; "missing" lists core comp fields
    not found (left blank, never invented).
    """
    flat = " ".join(text.split())
    fields: dict = {}
    evidence: dict = {}

    def take(field: str, patterns: list[str], convert=None):
        m = _first(flat, patterns)
        if not m:
            return
        groups = m.groups()
        val = convert(groups) if convert else _money(*groups[:2])
        fields[field] = val
        evidence[field] = _snippet(flat, m)

    take("base", _BASE_PATTERNS)
    take("bonus_target_pct", _BONUS_PCT_PATTERNS,
         lambda g: float(g[0]))
    take("bonus_first_year_guaranteed", _GUARANTEED_BONUS_PATTERNS)
    take("sign_on", _SIGNON_PATTERNS)
    take("equity_total", _EQUITY_VALUE_PATTERNS)

    # share count (kept in notes; not convertible to $ without a share price)
    m = _first(flat, _EQUITY_SHARES_PATTERNS)
    shares = int(m.group(1).replace(",", "")) if m else 0
    shares_evidence = _snippet(flat, m) if m else ""

    # equity type
    if re.search(r"\brestricted\s+stock\s+units?\b|\bRSUs?\b", flat, re.IGNORECASE):
        fields["equity_type"] = "rsu"
    elif re.search(r"stock\s+options?|\bNSOs?\b|\bISOs?\b", flat, re.IGNORECASE):
        fields["equity_type"] = "options"

    take("vest_years", _VEST_YEARS_PATTERNS, lambda g: int(g[0]))

    # vesting schedule: explicit "25/25/25/25" list, or "25% annually" split
    m = _first(flat, [r"\b(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\b"])
    if m:
        parts = [int(g) for g in m.groups()]
        if sum(parts) == 100:
            fields["vest_schedule"] = "/".join(str(p) for p in parts)
            evidence["vest_schedule"] = _snippet(flat, m)
    else:
        m = _first(flat, [r"(\d+)%\s*(?:vest(?:ing|ed)?\s+)?(?:annually|per\s+year|each\s+year)"])
        if m and 100 % int(m.group(1)) == 0:
            n = 100 // int(m.group(1))
            fields["vest_schedule"] = "/".join([m.group(1)] * n)
            evidence["vest_schedule"] = _snippet(flat, m)

    m = _first(flat, _START_DATE_PATTERNS)
    if m:
        fields["start_date"] = m.group(1)
        evidence["start_date"] = _snippet(flat, m)

    benefit_mentions = [label for label, pat in _BENEFIT_KEYWORDS
                        if re.search(pat, flat, re.IGNORECASE)]
    pto = re.search(r"(\d+)\s+days?\s+(?:of\s+)?(?:paid\s+time\s+off|\bPTO\b)",
                    flat, re.IGNORECASE)
    pto_days = int(pto.group(1)) if pto else 0

    missing = [f for f in _CORE_FIELDS if f not in fields]

    return {
        "fields": fields,
        "evidence": evidence,
        "missing": missing,
        "benefit_mentions": benefit_mentions,
        "equity_shares": shares,
        "equity_shares_evidence": shares_evidence,
        "pto_days": pto_days,
    }


_FIELD_LABELS = {
    "base": "base salary",
    "bonus_target_pct": "bonus target",
    "bonus_first_year_guaranteed": "guaranteed first-year bonus",
    "sign_on": "sign-on bonus",
    "equity_total": "equity grant value",
    "equity_type": "equity type",
    "vest_years": "vesting period",
    "vest_schedule": "vesting schedule",
    "start_date": "start date",
}


def _fmt_value(field: str, val) -> str:
    if field in ("base", "bonus_first_year_guaranteed", "sign_on",
                 "equity_total", "benefits_value"):
        return f"${val:,.0f}"
    if field == "bonus_target_pct":
        return f"{val:g}%"
    if field == "vest_years":
        return f"{int(val)} years"
    return str(val)


def render_extraction(result: dict, company: str, role: str) -> str:
    """Human-readable report: every extracted field + its source snippet."""
    lines = [f"Offer letter parsed: {company} — {role}", ""]
    fields, evidence = result["fields"], result["evidence"]
    if not fields:
        lines.append("No comp fields found in the letter.")
    for field, val in fields.items():
        label = _FIELD_LABELS.get(field, field)
        lines.append(f"{label:<28} {_fmt_value(field, val)}")
        if field in evidence:
            lines.append(f"    ...{evidence[field]}...")
    notes_bits = []
    if result.get("equity_shares"):
        notes_bits.append(
            f"{result['equity_shares']:,} RSUs (share count from letter; "
            "no share price, so not converted to $)")
    if result.get("benefit_mentions"):
        bits = list(result["benefit_mentions"])
        if result.get("pto_days"):
            bits = [b if b != "PTO" else f"PTO ({result['pto_days']} days)"
                    for b in bits]
        notes_bits.append("benefits mentioned: " + ", ".join(bits))
    if notes_bits:
        lines += ["", "Also noted: " + "; ".join(notes_bits) + "."]
    if result["missing"]:
        lines += ["",
                  "Not found in letter (left blank, not guessed): "
                  + ", ".join(result["missing"])]
    return "\n".join(lines)


def confirm_and_add(result: dict, company: str, role: str, *,
                    yes: bool = False, source: str = "") -> dict | None:
    """Print the extraction, confirm, and create the offer record.

    Returns the normalized record, or None if the user declined.
    """
    print(render_extraction(result, company, role))
    if not yes:
        answer = input("\nCreate this offer record? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Not saved. Re-run with different text or add manually with:\n"
                  "    python -m candid offer add --help")
            return None

    fields = dict(result["fields"])
    notes = []
    if result.get("equity_shares"):
        notes.append(f"{result['equity_shares']:,} RSUs per letter "
                     "(share count; grant value used for $ math)")
    if result.get("benefit_mentions"):
        bits = list(result["benefit_mentions"])
        if result.get("pto_days"):
            bits = [b if b != "PTO" else f"PTO ({result['pto_days']} days)"
                    for b in bits]
        notes.append("benefits mentioned in letter: " + ", ".join(bits))
    if source:
        notes.append(f"parsed from {Path(source).name}")
    if notes:
        fields["notes"] = "; ".join(notes)

    rec = O.add({"company": company, "role": role, **fields})
    print(f"\nAdded offer #{rec['id']}: {rec['company']} — "
          f"normalized ${rec['normalized_annual']:,.0f}/yr")
    return rec
