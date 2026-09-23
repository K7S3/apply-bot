"""Company culture decoder: work-style, benefits, and flag signals from JDs.

Reads the raw text of job descriptions and extracts three kinds of
evidence, every item backed by a verbatim quote so nothing is invented:

  1. Work-style signals: remote/hybrid/onsite policy, async-first language,
     timezone requirements, on-call expectations, travel.
  2. Benefits: PTO, 401k, health, equity, stipends, parental leave.
  3. Red/amber/green flags from a curated pattern library
     ("we're a family", "rockstar", "unlimited PTO", "async-first", ...).

Everything runs offline on the JD text you already have — no network, no
scraping, no paid APIs. When nothing matches, the lists come back empty;
we never fabricate a signal.

Usage:
    from candid import culture_signals as CS
    job = {"id": 1, "title": "Backend Engineer", "company": "Acme",
           "description": "...jd text..."}
    print(CS.analyze_jd(job))
    print(CS.company_jd_signals("Acme", [job]))
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# pattern libraries — every hit is backed by the verbatim regex match
# ---------------------------------------------------------------------------

def _rx(pat: str) -> re.Pattern:
    return re.compile(pat, re.IGNORECASE)


# (label, pattern)
WORKSTYLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("remote-first", _rx(r"remote[-\s]?first")),
    ("fully remote", _rx(r"fully remote")),
    ("hybrid", _rx(r"\bhybrid\b")),
    ("onsite", _rx(r"\bon[-\s]?site\b")),
    ("async-first", _rx(r"async[-\s]?first")),
    ("timezone requirements", _rx(
        r"\b(?:US|EU|EST|PST|CST|MST|GMT|UTC)\s*time[-\s]?zones?\b"
        r"|time[-\s]?zone overlap with [^\n.]{1,60}"
        r"|must (?:be|work) in [^\n.]{1,60}time[-\s]?zones?")),
    ("on-call", _rx(r"on[-\s]?call(?:\s+(?:rotation|duty|schedule))?")),
    ("travel", _rx(r"\d{1,3}%\s*travel|travel\s+up\s+to\s+\d+%?|occasional travel")),
]

# (label, pattern)
BENEFIT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PTO", _rx(r"unlimited (?:PTO|paid time off)"
                r"|\d+\s*(?:days?|weeks?)\s+(?:of\s+)?(?:paid\s+)?time off"
                r"|\bPTO\b")),
    ("401k", _rx(r"401\(k\)(?:\s+match(?:ing)?(?:\s+up to\s+\d+%?)?)?")),
    ("health insurance", _rx(r"(?:comprehensive\s+|full\s+)?health(?:care)?\s+"
                             r"(?:coverage|insurance|benefits?)"
                             r"|medical,\s*dental")),
    ("equity", _rx(r"\bstock options\b|\bRSUs?\b|\bequity\b")),
    ("stipends", _rx(r"(?:home office|wellness|learning|equipment)\s+stipend")),
    ("parental leave", _rx(r"(?:paid\s+)?parental leave")),
]

# (label, severity, pattern, why) — severity: red | amber | green
FLAG_PATTERNS: list[tuple[str, str, re.Pattern, str]] = [
    ("we are a family", "red",
     _rx(r"we(?:'re|\s+are)\s+(?:like\s+)?a family"),
     "Family framing can blur work/life boundaries and excuse overwork."),
    ("rockstar / ninja culture", "red",
     _rx(r"\b(?:rockstars?|ninjas?|gurus?|10x)\b"),
     "Hype titles often signal vague expectations and burnout-prone cultures."),
    ("wear many hats", "red",
     _rx(r"wear\s+(?:many|multiple)\s+hats"),
     "Usually means understaffed teams and undefined scope."),
    ("fast-paced environment", "red",
     _rx(r"fast[-\s]?paced\s+environment"),
     "Can mean exciting growth, but most often signals chronic urgency, "
     "context-switching, and long hours; ask what a typical week looks like."),
    ("competitive salary (vague)", "amber",
     _rx(r"competitive\s+(?:salary|compensation|pay)"),
     "Vague pay language; ask for the actual range before investing time."),
    ("unlimited PTO", "amber",
     _rx(r"unlimited\s+(?:PTO|paid time off)"),
     "Unlimited PTO often correlates with people taking less time off."),
    ("async-first", "green",
     _rx(r"async[-\s]?first"),
     "Async-first cultures respect deep work and flexible hours."),
    ("no-meeting days", "green",
     _rx(r"no[-\s]?meeting\s+days?"),
     "Protected focus time is a healthy signal."),
    ("transparent salary bands", "green",
     _rx(r"transparent\s+salary\s+bands?|salary\s+bands?\s+are\s+(?:public|transparent)"),
     "Pay transparency signals fair compensation practices."),
    ("defined on-call rotation", "green",
     _rx(r"(?:defined|fair|reasonable|sustainable)\s+on[-\s]?call\s+rotation"),
     "Explicit on-call expectations protect off-hours time."),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _source(job: dict) -> str:
    jid = job.get("id", job.get("source_id", "?"))
    return f"JD #{jid} '{job.get('title', '')}'"


def _scan_simple(patterns: list[tuple[str, re.Pattern]],
                 text: str, source: str) -> list[dict]:
    """First verbatim hit per label. Returns [{label, quote, source}]."""
    items, seen = [], set()
    for label, rx in patterns:
        if label in seen:
            continue
        m = rx.search(text)
        if m:
            seen.add(label)
            items.append({"label": label, "quote": m.group(0).strip(),
                          "source": source})
    return items


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def analyze_jd(job: dict) -> dict:
    """Extract work-style, benefits, and flag signals from one JD.

    ``job`` is a dict with keys id/title/company/description (a
    ``source_id`` is accepted as the id fallback). Returns
    {"workstyle": [...], "benefits": [...], "flags": [...]} where each
    item is {"label", "quote", "source"} (flags add "severity" and
    "why"). Every quote is a verbatim substring of the description;
    no matches means empty lists, never invented signals.
    """
    source = _source(job)
    text = job.get("description") or ""
    flags = []
    seen = set()
    for label, severity, rx, why in FLAG_PATTERNS:
        if label in seen:
            continue
        m = rx.search(text)
        if m:
            seen.add(label)
            flags.append({"label": label, "severity": severity,
                          "quote": m.group(0).strip(), "why": why,
                          "source": source})
    return {
        "workstyle": _scan_simple(WORKSTYLE_PATTERNS, text, source),
        "benefits": _scan_simple(BENEFIT_PATTERNS, text, source),
        "flags": flags,
    }


def company_jd_signals(company: str, jobs: list[dict]) -> dict:
    """Aggregate analyze_jd() over a company's postings.

    ``jobs`` is the list of job dicts (already fetched via candid/jobs.py);
    only jobs whose company matches (case-insensitive) are analyzed. If
    none match, the whole list is analyzed as a defensive fallback.
    Returns {"company", "job_count", "workstyle", "benefits", "flags",
    "sources"} where each list is deduped by (label, quote) and
    "sources" holds the unique source strings in first-seen order.
    """
    want = (company or "").strip().lower()
    matching = [j for j in jobs
                if str(j.get("company", "")).strip().lower() == want]
    pool = matching if matching else jobs

    agg: dict[str, list[dict]] = {"workstyle": [], "benefits": [], "flags": []}
    seen: set[tuple[str, str]] = set()
    sources: list[str] = []
    for job in pool:
        result = analyze_jd(job)
        for key in agg:
            for item in result[key]:
                marker = (item["label"], item["quote"])
                if marker in seen:
                    continue
                seen.add(marker)
                agg[key].append(item)
                if item["source"] not in sources:
                    sources.append(item["source"])
    return {"company": company, "job_count": len(pool),
            "workstyle": agg["workstyle"], "benefits": agg["benefits"],
            "flags": agg["flags"], "sources": sources}
