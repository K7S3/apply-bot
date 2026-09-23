"""Career story builder (batch 82, worker D): "why us" connector + story timing coach.

This module owns the "why_us" and "timing" keys inside DATA_DIR/"narrative.json".
Other keys in that file (notably "arc" and "pitches", written by sibling
workers) are loaded and preserved but never overwritten.

Why-us connector
----------------
why_us(company, role, jd_text=None, company_facts=None) builds a short
paragraph linking the user's career arc to a specific company/role. The arc
comes from the shared narrative.json "arc" key (read defensively); when it is
absent, a minimal arc is built from the profile (seniority, years, latest
roles, top skills). Groundedness is a hard rule: company-specific claims may
ONLY come from the user-supplied company_facts string or from jd_text. Anything
else about the company is the literal placeholder
"[fill in: what excites you about <company>]". Company facts are never invented.

Story timing coach
------------------
timing(text, target="2min") scores a pitch draft: word count, estimated
speaking seconds at 140 wpm, per-paragraph word budgets against the target
length, and deterministic pacing tips (long sentences, filler phrases, a pause
after the hook, and an over/under/within-10% verdict with a concrete word gap).

timing_report(length) reads the stored pitch for that length from
narrative.json "pitches" (read-only) and stores the timing report under
"timing".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config as C
from candid import profile as P


class NarrativeError(Exception):
    """Raised for invalid narrative builder operations."""


# --- constants -------------------------------------------------------------

WPM = 140
LONG_SENTENCE_WORDS = 28
TARGET_SECONDS = {"30s": 30, "2min": 120, "5min": 300}

_FILLER_RE = re.compile(
    r"\b(um|like|you know|basically|actually|sort of)\b", re.IGNORECASE
)
_SENTENCE_RE = re.compile(r"[.!?]+")


# --- state helpers ---------------------------------------------------------

def _narrative_path() -> Path:
    """Resolve DATA_DIR/narrative.json lazily so tests can rebind C.DATA_DIR."""
    return C.DATA_DIR / "narrative.json"


def _load_narrative() -> dict:
    p = _narrative_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NarrativeError(f"Narrative file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NarrativeError(f"Narrative file {p} should contain a JSON object.")
    return data


def _save_narrative(data: dict) -> Path:
    """Write back the whole file so sibling keys are preserved."""
    p = _narrative_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _load_profile() -> dict:
    try:
        # Path computed from C.DATA_DIR lazily so test rebinding works.
        return P.load_profile(C.DATA_DIR / "profile.json")
    except P.OnboardError as exc:
        raise NarrativeError(
            "No user profile found, so there is no career story to build from. "
            "Run onboarding first, e.g. `candid onboard --resume your_resume.pdf`, "
            "then try again."
        ) from exc


# --- arc -------------------------------------------------------------------

def _minimal_arc(profile: dict) -> dict:
    """Build a minimal arc summary straight from the profile fields."""
    experience = profile.get("experience") or []
    latest_roles = []
    for entry in experience[:2]:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        company = (entry.get("company") or "").strip()
        if title and company:
            latest_roles.append(f"{title} at {company}")
        elif title:
            latest_roles.append(title)
    return {
        "seniority": profile.get("seniority") or "",
        "years_experience": profile.get("years_experience"),
        "latest_roles": latest_roles,
        "top_skills": list(profile.get("skills") or [])[:8],
    }


def _arc(profile: dict, narrative: dict) -> dict:
    """Read the arc from narrative.json "arc", falling back to the profile."""
    arc = narrative.get("arc")
    if isinstance(arc, dict) and arc:
        return arc
    return _minimal_arc(profile)


def _arc_sentence(arc: dict) -> str:
    # Worker A's arc shape: {"past": {"text", "sources"}, "present": {...},
    # "future": {...}}. Prefer the present segment's own wording.
    present = arc.get("present")
    if isinstance(present, dict) and present.get("text"):
        words = str(present["text"]).split()
        condensed = " ".join(words[:28])
        return condensed + ("" if len(words) <= 28 else "...")
    if isinstance(present, str) and present.strip():
        return present.strip()
    seniority = (arc.get("seniority") or "").strip()
    years = arc.get("years_experience")
    latest = arc.get("latest_roles") or []
    bits = []
    who = f"I am a {seniority} engineer" if seniority else "I am an engineer"
    bits.append(who)
    if isinstance(years, (int, float)) and years > 0:
        bits.append(f"with {years:g} years of experience")
    if latest:
        bits.append(f"most recently {latest[0]}")
    return " ".join(bits) + "."


# --- JD overlap ------------------------------------------------------------

def _skills_in(text: str) -> set[str]:
    """Canonical skills whose lexicon aliases match the given text."""
    found: set[str] = set()
    lowered = text.lower()
    for canonical, aliases in C.SKILL_LEXICON.items():
        for alias in aliases:
            if C.skill_regex(alias).search(lowered):
                found.add(canonical)
                break
    return found


def _jd_overlap_sentence(company: str, role: str, jd_text: str, profile: dict) -> str:
    """Sentence grounded ONLY by config.SKILL_LEXICON matching against jd_text."""
    jd_skills = _skills_in(jd_text)
    profile_skills = {str(s).lower() for s in (profile.get("skills") or [])}
    overlap = sorted(jd_skills & profile_skills)
    if not overlap:
        return ""
    listed = ", ".join(overlap[:3])
    return (
        f"That background lines up with what {company} needs for this {role}: "
        f"my experience in {listed} maps to the skills in the posting."
    )


# --- why-us connector ------------------------------------------------------

def why_us(company: str, role: str, jd_text: str | None = None,
           company_facts: str | None = None) -> str:
    """Build a short "why us / why this role" paragraph for company and role.

    Groundedness: company-specific claims may ONLY come from the user-supplied
    company_facts string or jd_text. When no company facts are available, the
    paragraph ends with the literal placeholder
    "[fill in: what excites you about <company>]" instead of inventing any.
    The draft is stored under narrative.json "why_us" keyed by company with
    approved=False.
    """
    if not company or not role:
        raise NarrativeError("Both company and role are required to build a why-us draft.")
    profile = _load_profile()
    narrative = _load_narrative()
    arc = _arc(profile, narrative)

    sentences = [_arc_sentence(arc)]
    if jd_text:
        overlap = _jd_overlap_sentence(company, role, jd_text, profile)
        if overlap:
            sentences.append(overlap)
    if company_facts and company_facts.strip():
        sentences.append(f"What draws me to {company}: {company_facts.strip()}")
    else:
        sentences.append(f"[fill in: what excites you about {company}]")
    text = " ".join(sentences)

    why_us_store = narrative.get("why_us")
    if not isinstance(why_us_store, dict):
        why_us_store = {}
        narrative["why_us"] = why_us_store
    why_us_store[company] = {"role": role, "text": text, "approved": False}
    _save_narrative(narrative)
    return text


def approve_why_us(company: str) -> dict:
    """Mark the stored why-us draft for company as approved. Returns it."""
    narrative = _load_narrative()
    why_us_store = narrative.get("why_us")
    if not isinstance(why_us_store, dict) or company not in why_us_store:
        raise NarrativeError(
            f"No why-us draft stored for '{company}'. Build one first with why_us()."
        )
    why_us_store[company]["approved"] = True
    _save_narrative(narrative)
    return why_us_store[company]


# --- story timing coach ----------------------------------------------------

def _word_list(text: str) -> list[str]:
    return text.split()


def _paragraphs(text: str) -> list[str]:
    return [p for p in (p.strip() for p in re.split(r"\n\s*\n", text)) if p]


def _long_sentences(text: str) -> list[dict]:
    flagged = []
    for sentence in _SENTENCE_RE.split(text):
        words = sentence.split()
        if len(words) > LONG_SENTENCE_WORDS:
            preview = sentence.strip()
            if len(preview) > 90:
                preview = preview[:87] + "..."
            flagged.append({"words": len(words), "preview": preview})
    return flagged


def _filler_hits(text: str) -> list[dict]:
    counts: dict[str, int] = {}
    order: list[str] = []
    for m in _FILLER_RE.finditer(text):
        phrase = m.group(1).lower()
        if phrase not in counts:
            counts[phrase] = 0
            order.append(phrase)
        counts[phrase] += 1
    return [{"phrase": p, "count": counts[p]} for p in order]


def timing(text: str, target: str = "2min") -> dict:
    """Score a pitch draft for a target speaking length.

    Returns word count, estimated speaking seconds at 140 wpm, per-paragraph
    word budgets against the target, pacing tips (long sentences over 28
    words, filler phrases, a pause after the hook), and an over/under/within
    verdict against the target within a 10% tolerance, with a concrete
    word-gap tip.
    """
    if target not in TARGET_SECONDS:
        raise NarrativeError(
            f"Unknown target '{target}'. Choose from: {', '.join(TARGET_SECONDS)}"
        )
    target_seconds = TARGET_SECONDS[target]
    budget_words = target_seconds / 60 * WPM

    words = _word_list(text)
    n = len(words)
    seconds = round(n / WPM * 60)

    paras = _paragraphs(text)
    n_paras = max(len(paras), 1)
    para_budget = budget_words / n_paras
    paragraph_budgets = [
        {
            "paragraph": i + 1,
            "words": len(_word_list(p)),
            "budget_words": round(para_budget),
            "delta_words": round(len(_word_list(p)) - para_budget),
        }
        for i, p in enumerate(paras)
    ] if paras else [{"paragraph": 1, "words": n, "budget_words": round(budget_words),
                     "delta_words": round(n - budget_words)}]

    long_sentences = _long_sentences(text)
    fillers = _filler_hits(text)

    tips: list[str] = []
    if long_sentences:
        tips.append(
            f"{len(long_sentences)} sentence(s) run over {LONG_SENTENCE_WORDS} words; "
            "split them into shorter spoken beats."
        )
    if fillers:
        names = ", ".join(f["phrase"] for f in fillers)
        tips.append(
            f"Filler phrases spotted ({names}); rehearse those lines without them."
        )
    tips.append("Pause after your opening hook sentence so the listener can land on it.")
    if n_paras > 1 and paragraph_budgets:
        over = [b for b in paragraph_budgets if b["delta_words"] > 0]
        if over:
            tips.append(
                f"Paragraph(s) {', '.join(str(b['paragraph']) for b in over)} are over "
                "their word budget; trim there first."
            )

    gap = round(n - budget_words)
    ratio = n / budget_words if budget_words else 0
    if abs(ratio - 1) <= 0.10 + 1e-9:  # epsilon for float boundary (308/280 == 1.1)
        verdict = "within"
        gap_tip = "Right on target: within 10% of the word budget."
    elif gap > 0:
        verdict = "over"
        gap_tip = f"Over by about {gap} words: cut roughly {gap} words to hit {target}."
    else:
        verdict = "under"
        gap_tip = f"Under by about {-gap} words: add roughly {-gap} words to fill {target}."

    return {
        "target": target,
        "target_seconds": target_seconds,
        "word_count": n,
        "seconds": seconds,
        "word_budget": round(budget_words),
        "paragraph_budgets": paragraph_budgets,
        "long_sentences": long_sentences,
        "fillers": fillers,
        "pause_tip": "Pause after the opening hook sentence to let it land.",
        "tips": tips,
        "verdict": verdict,
        "word_gap": gap,
        "gap_tip": gap_tip,
    }


def timing_report(length: str) -> dict:
    """Time the stored pitch for length ("pitches" key, read-only) and store it.

    Reads the pitch from narrative.json "pitches" (never writes there) and
    stores the report under the "timing" key. Returns the report.
    """
    narrative = _load_narrative()
    pitches = narrative.get("pitches")
    if not isinstance(pitches, dict) or not pitches.get(length):
        raise NarrativeError(
            f"No stored pitch found for length '{length}'. "
            "Store a pitch under narrative.json \"pitches\" first."
        )
    stored = pitches[length]
    # Worker A stores pitch records as dicts {text, word_count, ...}; accept
    # plain strings too.
    text = stored.get("text") if isinstance(stored, dict) else stored
    if not isinstance(text, str) or not text.strip():
        raise NarrativeError(
            f"Stored pitch for length '{length}' has no text to time."
        )
    report = timing(text, target=length)
    timing_store = narrative.get("timing")
    if not isinstance(timing_store, dict):
        timing_store = {}
        narrative["timing"] = timing_store
    timing_store[length] = report
    _save_narrative(narrative)
    return report
