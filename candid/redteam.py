"""Resume red-team: adversarial review from a skeptical hiring manager.

``review`` takes a resume as markdown text or as a profile dict (the shape
``candid.profile.build_profile`` returns) and returns findings, each one
{severity, category, quote, critique, fix}. ``hiring_manager_summary`` gives
a blunt 5-line verdict; ``prioritized_fixes`` orders the top 5 fixes by
impact.

STRICT RULES (groundedness is non-negotiable):
  - Critique ONLY what is evidenced in the input. Every finding carries a
    ``quote`` copied verbatim from the input it critiques.
  - Never accuse the candidate of lying about specific facts. Items that
    cannot be verified from the resume are phrased as "verify" questions,
    e.g. "What was the baseline for this 50% claim?" - never "this is false".
  - No invented counter-examples: the module never makes up what the
    candidate did or did not do; it only questions what is written.

Categories: vague-bullet, overclaim-risk, inconsistency, ats-risk,
buzzword-density, gap-explanation.
"""

from __future__ import annotations

import re
from datetime import date


class RedTeamError(Exception):
    """Raised when the input to review() is not usable."""


# ---------------------------------------------------------------------------
# input normalization
# ---------------------------------------------------------------------------

_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTHS = "|".join(_MONTH_ABBR + ["sept"])


def _bullets_from_markdown(text: str) -> list[str]:
    bullets = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^[-\*\u2022\u00b7\u25aa\u25ab>\+]\s+", stripped):
            bullets.append(re.sub(r"^[-\*\u2022\u00b7\u25aa\u25ab>\+]\s+", "", stripped))
        elif re.match(r"^\d{1,2}[.)]\s+", stripped):
            bullets.append(re.sub(r"^\d{1,2}[.)]\s+", "", stripped))
    return [b for b in bullets if len(b) >= 10]


def _headers_from_markdown(text: str) -> list[str]:
    headers = []
    for line in text.splitlines():
        # Only ## and deeper: a single-# line is usually the candidate's name.
        if re.match(r"^#{2,4}\s+\S", line):
            headers.append(line.strip().strip("#").strip())
        elif (stripped := line.strip()) and stripped.isupper() \
                and len(stripped) < 40 and len(stripped.split()) <= 4:
            headers.append(stripped)
    return headers


_RANGE_LINE_RE = re.compile(
    rf"((?:{_MONTHS})[a-z]*\.?\s*\d{{4}}|\d{{4}})\s*[-\u2013\u2014]\s*"
    rf"((?:{_MONTHS})[a-z]*\.?\s*\d{{4}}|\d{{4}}|present|current|now)",
    re.I,
)


def _entries_from_markdown(text: str) -> list[dict]:
    """Pseudo-entries from lines carrying a date range.

    ``source`` keeps the full original line so findings can quote it
    verbatim; title is the text before the range.
    """
    entries = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) > 200:
            continue
        m = _RANGE_LINE_RE.search(stripped)
        if not m:
            continue
        head = re.sub(r"^[-\*\u2022\u00b7>\+]\s*", "", stripped[:m.start()]).strip(" -–—|,")
        entries.append({"title": head, "company": "", "dates": m.group(0),
                        "bullets": [], "source": stripped})
    return entries


def _summary_from_markdown(text: str) -> str:
    """Grab plain (non-bullet) text under a Summary/Profile/Objective header."""
    lines = text.splitlines()
    capturing = False
    out = []
    for line in lines:
        stripped = line.strip()
        clean = re.sub(r"^#+\s*", "", stripped).lower().strip(":")
        if re.match(r"^#{1,4}\s+\S", line) or \
                (stripped.isupper() and len(stripped) < 40):
            capturing = clean in ("summary", "profile", "objective")
            continue
        if capturing:
            if re.match(r"^[-\*\u2022\u00b7>\+]\s+|^\d{1,2}[.)]\s+", stripped):
                continue
            if stripped:
                out.append(stripped)
    return " ".join(out)[:600]


def _experience_from_profile(profile: dict) -> list[dict]:
    return [e for e in profile.get("experience", []) if isinstance(e, dict)]


def _normalize(markdown_or_profile) -> dict:
    """Return {'bullets': [...], 'summary': str, 'headers': [...],
    'entries': [...], 'raw': str} for either input type."""
    if isinstance(markdown_or_profile, dict):
        profile = markdown_or_profile
        entries = []
        for e in _experience_from_profile(profile):
            e = dict(e)  # don't mutate the caller's profile
            e["source"] = (f"{e.get('title', '')} - {e.get('company', '')}, "
                           f"{e.get('dates', '')}").strip(" -,")
            entries.append(e)
        bullets = [b for e in entries for b in e.get("bullets", []) if b]
        summary = str(profile.get("summary") or "")
        edu = [f"{e.get('school', '')} {e.get('degree', '')} {e.get('dates', '')}".strip()
               for e in profile.get("education", [])]
        raw = "\n".join(bullets + [summary] + edu)
        headers = [e["source"] for e in entries if e["source"]]
        return {"bullets": bullets, "summary": summary, "headers": headers,
                "entries": entries, "raw": raw}
    if isinstance(markdown_or_profile, str):
        text = markdown_or_profile
        if len(text.strip()) < 50:
            raise RedTeamError("Input text is too short to review.")
        bullets = _bullets_from_markdown(text)
        summary = _summary_from_markdown(text)
        raw = text
        return {"bullets": bullets, "summary": summary,
                "headers": _headers_from_markdown(text),
                "entries": _entries_from_markdown(text), "raw": raw}
    raise RedTeamError("review() needs markdown text or a profile dict.")


# ---------------------------------------------------------------------------
# individual checks — each returns findings with verbatim quotes
# ---------------------------------------------------------------------------

_WEAK_VERBS = [
    "responsible for", "worked on", "helped with", "helped", "assisted",
    "involved in", "tasked with", "participated in", "contributed to",
    "supported", "liaised", "handled",
]
_RESULT_WORDS = ["%", "increased", "decreased", "reduced", "improved", "grew",
                 "growth", "revenue", "saved", "cut", "delivered", "shipped",
                 "launched", "led", "owned", "drove", "built", "designed",
                 "number", "users", "customers", "million", "billion"]


def _check_vague_bullets(norm: dict) -> list[dict]:
    findings = []
    for bullet in norm["bullets"]:
        low = bullet.lower()
        weak = [w for w in _WEAK_VERBS if w in low]
        has_result = any(w in low for w in _RESULT_WORDS) or bool(re.search(r"\d", bullet))
        if weak and not has_result:
            findings.append({
                "severity": "medium",
                "category": "vague-bullet",
                "quote": bullet,
                "critique": (
                    f"Leans on the weak verb '{weak[0]}' and states no outcome - "
                    "a skeptical reader has no idea what actually changed."
                ),
                "fix": "Rewrite as outcome-first: what you did, how, and the "
                       "measurable result (scope, users, time, or money).",
            })
    return findings


_NUMBER_RE = re.compile(r"\d+\s?%|\d+\s?x\b|\$\s?[\d,]+|\b\d[\d,]*\s?(million|billion|k\b|users|customers|ms|s\b)")
_SCOPE_WORDS = ["baseline", "from", "to ", "vs", "versus", "compared",
                "across", "baseline:", "benchmark", "previously"]


def _check_overclaim_risk(norm: dict) -> list[dict]:
    findings = []
    for bullet in norm["bullets"]:
        low = bullet.lower()
        m = _NUMBER_RE.search(bullet)
        if m and not any(w in low for w in _SCOPE_WORDS):
            findings.append({
                "severity": "medium",
                "category": "overclaim-risk",
                "quote": bullet,
                "critique": (
                    f"Big number ('{m.group(0)}') with no context - no baseline, "
                    "scope, or timeframe is stated. A hiring manager will "
                    "interrogate this in the first interview, so it must be "
                    "defensible as written. (Flagged as a verify item, not "
                    "an accusation: the number may be exactly right.)"
                ),
                "fix": "Add the missing context or confirm it before the "
                       "interview: what was the baseline, over what period, "
                       "and for how many users/requests?",
            })
    return findings


_BUZZWORDS = [
    "synergy", "synergies", "leverage", "leveraging", "ninja", "guru",
    "rockstar", "rock star", "go-getter", "self-starter", "thought leader",
    "disruptive", "bleeding edge", "passionate", "detail-oriented",
    "results-driven", "results oriented", "dynamic", "utilize",
]


def _check_buzzwords(norm: dict) -> list[dict]:
    findings = []
    texts = list(norm["bullets"])
    if norm["summary"]:
        texts.append(norm["summary"])
    for text in texts:
        low = text.lower()
        hits = [b for b in _BUZZWORDS if re.search(rf"\b{re.escape(b)}\b", low)]
        if len(hits) >= 2:
            findings.append({
                "severity": "medium" if len(hits) >= 4 else "low",
                "category": "buzzword-density",
                "quote": text,
                "critique": (
                    f"Packs in buzzwords ({', '.join(hits)}) that every resume "
                    "uses - they signal filler rather than substance, and a "
                    "skimming manager discounts the whole line."
                ),
                "fix": "Cut the buzzwords and replace each with one concrete "
                       "fact: a tool, a number, or a named outcome.",
            })
        elif len(hits) == 1 and len(text.split()) <= 12:
            findings.append({
                "severity": "low",
                "category": "buzzword-density",
                "quote": text,
                "critique": f"'{hits[0]}' is doing all the work in a very short line.",
                "fix": "Replace the buzzword with what you actually did.",
            })
    return findings


_ATS_MENTIONS = ["two-column", "two column", "table", "graphic", "icon",
                 "chart", "infographic", "text box"]
_STANDARD_HEADERS = {
    "experience", "work experience", "employment", "professional experience",
    "education", "skills", "technical skills", "core skills", "projects",
    "summary", "objective", "profile", "certifications", "publications",
    "awards", "languages", "interests", "contact",
}


def _check_ats_risk(norm: dict) -> list[dict]:
    findings = []
    low = norm["raw"].lower()
    lines = norm["raw"].splitlines()
    for word in _ATS_MENTIONS:
        for line in lines:
            if word in line.lower() and len(line.strip()) >= 10:
                findings.append({
                    "severity": "medium",
                    "category": "ats-risk",
                    "quote": line.strip(),
                    "critique": (
                        f"Mentions '{word}' - tables, graphics, and multi-column "
                        "layouts routinely break ATS parsing, so content in them "
                        "may never be read at all."
                    ),
                    "fix": "Use a single-column layout with plain text; keep "
                           "tables and graphics out of the resume.",
                })
                break
        else:
            continue
        break
    for header in norm["headers"]:
        clean = re.sub(r"^#+\s*", "", header).lower().strip().strip(":")
        if clean and clean not in _STANDARD_HEADERS and len(clean.split()) <= 4:
            findings.append({
                "severity": "low",
                "category": "ats-risk",
                "quote": header,
                "critique": (
                    f"Unusual section header '{header}'. Non-standard headers "
                    "can confuse ATS section detection and puzzle a 30-second "
                    "skim-reader."
                ),
                "fix": "Rename to a standard header (Experience, Skills, "
                       "Projects, Education) unless you have a strong reason.",
            })
    return findings


def _month_index(token: str) -> tuple[int, int] | None:
    m = re.match(rf"(?:({_MONTHS})[a-z]*\.?\s*)?(\d{{4}})", token.strip(), re.I)
    if not m:
        return None
    mon = m.group(1)
    year = int(m.group(2))
    if not mon:
        return (year, 6)  # year-only: treat as mid-year
    month = _MONTH_ABBR.index(mon.lower().replace("sept", "sep")[:3]) + 1
    return (year, month)


def _extract_range(dates: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Parse 'Jan 2020 - Mar 2022' into ((2020,1),(2022,3))."""
    if not dates:
        return None
    parts = re.split(r"\s*[-\u2013\u2014]|\bto\b\s*", dates.strip(), maxsplit=1,
                     flags=re.I)
    if len(parts) != 2:
        return None
    start = _month_index(parts[0])
    end_raw = parts[1].strip().lower()
    if re.match(r"^(present|current|now)", end_raw):
        end = (date.today().year, date.today().month)
    else:
        end = _month_index(parts[1])
    if not start or not end:
        return None
    return (start, end)


def _check_inconsistency(norm: dict) -> list[dict]:
    findings = []
    entries = norm["entries"]
    ranges = []
    for e in entries:
        r = _extract_range(e.get("dates", ""))
        ranges.append((e, r))

    # end-before-start within a single entry
    for e, r in ranges:
        if r and r[1] < r[0]:
            quote = e.get("source") or \
                f"{e.get('title', '')} - {e.get('company', '')}, {e.get('dates', '')}".strip(" -,")
            findings.append({
                "severity": "high",
                "category": "inconsistency",
                "quote": quote,
                "critique": (
                    "The end date is earlier than the start date. A manager "
                    "reading this assumes a typo at best - at worst, they stop "
                    "trusting every other date on the page."
                ),
                "fix": "Correct the dates; double-check the month order.",
            })

    # same company, overlapping ranges, different titles
    for i in range(len(ranges)):
        for j in range(i + 1, len(ranges)):
            (ei, ri), (ej, rj) = ranges[i], ranges[j]
            if not (ri and rj):
                continue
            same_company = (ei.get("company") or "").strip().lower() == \
                           (ej.get("company") or "").strip().lower() != ""
            overlap = ri[0] <= rj[1] and rj[0] <= ri[1]
            if same_company and overlap and \
                    (ei.get("title") or "").strip().lower() != \
                    (ej.get("title") or "").strip().lower():
                ci = (f"{ei.get('title', '')} - {ei.get('company', '')}, "
                      f"{ei.get('dates', '')}")
                cj = (f"{ej.get('title', '')} - {ej.get('company', '')}, "
                      f"{ej.get('dates', '')}")
                quote = f"{ei.get('source') or ci}  /  {ej.get('source') or cj}"
                findings.append({
                    "severity": "medium",
                    "category": "inconsistency",
                    "quote": quote,
                    "critique": (
                        "Two overlapping entries at the same company list "
                        "different titles. Is this a promotion shown twice, "
                        "or two roles? As written it reads as a conflict."
                    ),
                    "fix": "Merge into one entry with a promotion line, or "
                           "make the non-overlapping date ranges explicit.",
                })

    # summary claims a title seniority that never appears in experience
    summary = (norm["summary"] or "").lower()
    titles = " ".join(e.get("title", "") for e in entries).lower()
    for level in ("senior", "staff", "principal", "lead", "manager", "director"):
        if re.search(rf"\b{level}\b", summary) and level not in titles and titles:
            quote = norm["summary"][:160]
            findings.append({
                "severity": "medium",
                "category": "inconsistency",
                "quote": quote,
                "critique": (
                    f"The summary uses '{level}' but no experience entry has "
                    "it in its title. A manager will ask which role earned "
                    "that level - if none did, the summary overreaches."
                ),
                "fix": "Either align the summary wording with an actual "
                       "title, or make clear the seniority claim is supported "
                       "by scope described in the bullets.",
            })
            break
    return findings


def _check_gaps(norm: dict) -> list[dict]:
    findings = []
    entries = norm["entries"]
    spans = []
    for e in entries:
        r = _extract_range(e.get("dates", ""))
        if r:
            spans.append((r, e))
    spans.sort(key=lambda s: s[0][0])
    for (r1, e1), (r2, e2) in zip(spans, spans[1:]):
        gap_months = (r2[0][0] - r1[1][0]) * 12 + (r2[0][1] - r1[1][1])
        if gap_months > 6:
            # Quote the later entry's own line verbatim; the critique names
            # the gap length and the earlier role it follows.
            quote = e2.get("source") or \
                f"{e2.get('title', '')}, {e2.get('dates', '')}"
            years = gap_months // 12
            months = gap_months % 12
            length = f"{years}y {months}m" if years else f"{months} months"
            earlier = e1.get("source") or \
                f"{e1.get('title', '')} ({e1.get('dates', '')})"
            findings.append({
                "severity": "low",
                "category": "gap-explanation",
                "quote": quote,
                "critique": (
                    f"About {length} between this role and the previous one "
                    f"({earlier}) with no explanation in the resume. Gaps are "
                    "neutral - life happens - but an unexplained one invites "
                    "the manager to invent a story."
                ),
                "fix": "Add one short line covering the gap (contract work, "
                       "study, caregiving, job search) so you control the "
                       "narrative.",
            })
    return findings


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

_FINDING_KEYS = ("severity", "category", "quote", "critique", "fix")


def review(markdown_or_profile) -> list[dict]:
    """Adversarial review of a resume (markdown text or profile dict).

    Returns findings ordered high -> medium -> low. Every finding's
    ``quote`` is copied verbatim from the input; nothing is invented.
    """
    norm = _normalize(markdown_or_profile)
    findings = (
        _check_inconsistency(norm)
        + _check_overclaim_risk(norm)
        + _check_vague_bullets(norm)
        + _check_buzzwords(norm)
        + _check_ats_risk(norm)
        + _check_gaps(norm)
    )
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["category"]))
    for f in findings:
        assert set(f) == set(_FINDING_KEYS), f"malformed finding: {f}"
    return findings


def hiring_manager_summary(findings: list[dict]) -> str:
    """Blunt 5-line verdict: does this survive a 30-second scan, and why."""
    highs = [f for f in findings if f["severity"] == "high"]
    mediums = [f for f in findings if f["severity"] == "medium"]
    lows = [f for f in findings if f["severity"] == "low"]

    if highs:
        verdict = "DOES NOT SURVIVE the 30-second scan."
        why = f"{len(highs)} high-severity issue(s) - " + "; ".join(
            f["category"].replace("-", " ") for f in highs[:2])
    elif len(mediums) >= 3:
        verdict = "BORDERLINE - it survives only if the reader is generous."
        why = f"{len(mediums)} medium-severity issues competing for attention"
    elif mediums or lows:
        verdict = "SURVIVES, but leaves points on the table."
        why = "no fatal flaws, but fixable weaknesses a sharper resume would not have"
    else:
        verdict = "SURVIVES the 30-second scan."
        why = "no red flags found - the scan passes without friction"

    top = findings[0] if findings else None
    if top:
        first_noticed = (f"First thing a skeptic notices: {top['category']} - "
                         f"'{top['quote'][:90]}'")
        biggest_risk = f"Biggest risk: {top['critique'][:110]}"
        advice = f"Fix first: {top['fix'][:110]}"
    else:
        first_noticed = "First thing a skeptic notices: nothing objectionable."
        biggest_risk = "Biggest risk: none found - the resume reads clean."
        advice = "Fix first: nothing urgent; tighten wording where you can."

    lines = [
        f"Verdict: {verdict}",
        f"Why: {why}.",
        first_noticed,
        biggest_risk,
        advice,
    ]
    return "\n".join(lines)


_FIX_PRIORITY = ["inconsistency", "overclaim-risk", "vague-bullet",
                 "ats-risk", "buzzword-density", "gap-explanation"]
_SEV_RANK = {"high": 0, "medium": 1, "low": 2}


def prioritized_fixes(findings: list[dict]) -> list[dict]:
    """Top 5 fixes ordered by impact (severity, then category priority)."""
    ordered = sorted(
        findings,
        key=lambda f: (_SEV_RANK[f["severity"]],
                       _FIX_PRIORITY.index(f["category"])
                       if f["category"] in _FIX_PRIORITY else 99),
    )
    return [
        {"severity": f["severity"], "category": f["category"],
         "quote": f["quote"], "fix": f["fix"]}
        for f in ordered[:5]
    ]
