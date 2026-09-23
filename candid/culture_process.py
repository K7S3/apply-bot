"""Company culture decoder: interview-process transparency plus a prep hook.

This module answers "what does this company's interview process actually
look like?" using ONLY evidence already in the user's data:

  1. Interview-process transparency - ``process_profile(company, ctx)``
     scans the user's own sources (prep question bank entries, personal
     interview debriefs, tracker notes) for the named company, matches
     interview-stage keywords (recruiter screen, technical phone screen,
     hiring manager, take-home, onsite), and returns each detected stage
     with verbatim quotes and their source labels. Nothing is invented:
     stages appear only when the evidence says so, and every quote is a
     verbatim substring of the text it came from.
  2. Prep hook - ``attach_culture_to_prep(company, pack)`` returns a copy
     of a prep pack dict with a ``"culture"`` key added, so culture
     context composes with whatever pack shape the caller uses. The pack
     itself is never mutated.

Usage:
    from candid import culture_process as cp

    ctx = {
        "debriefs": [
            {"company": "Acme", "date": "2026-08-01",
             "text": "Started with a 30-min recruiter screen ..."},
        ],
        "prep_bank": [{"company": "Acme", "question": "..."}],
        "tracker": [{"company": "Acme", "notes": "...", "status": "..."}],
    }
    profile = cp.process_profile("Acme", ctx)

    pack = {"company": "Acme", "role": "SWE", "ctx": ctx}
    enriched = cp.attach_culture_to_prep("Acme", pack)  # pack unchanged
"""

from __future__ import annotations

import re


# Canonical stage order, each paired with the keyword phrases that signal
# it in evidence text (all matching is case-insensitive). Longer phrases
# are listed first so a sentence like "technical phone screen" is credited
# to the most specific stage it mentions.
_STAGES: list[tuple[str, tuple[str, ...]]] = [
    ("recruiter screen", (
        "recruiter screen", "recruiter call", "recruiter phone",
        "recruiter chat", "hr screen", "hr call", "recruiter",
    )),
    ("technical phone screen", (
        "technical phone screen", "phone screen", "technical screen",
        "coding screen", "codesignal", "karat", "phone interview",
        "tech screen",
    )),
    ("hiring manager", (
        "hiring manager", "hm interview", "hm round", "manager round",
        "team lead interview",
    )),
    ("take-home", (
        "take-home", "take home", "takehome", "home assignment",
        "coding assignment",
    )),
    ("onsite", (
        "virtual onsite", "onsite", "on-site", "on site", "final round",
        "loop interview", "panel interview", "superday", "super day",
    )),
]

_STAGE_ORDER = [name for name, _ in _STAGES]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _normalize_company(name: str) -> str:
    """Normalize a company name for comparison (case/whitespace)."""
    return " ".join(str(name or "").split()).lower()


def _sentences(text: str) -> list[str]:
    """Split text into sentences, keeping each verbatim (stripped)."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(str(text)) if s.strip()]


def _detect_stages(text: str) -> dict[str, str]:
    """Map each detected stage to the first evidence sentence naming it.

    Returns {stage_name: sentence}. A sentence is only ever a verbatim
    substring of the input text.
    """
    lowered = str(text).lower()
    found: dict[str, str] = {}
    for stage, keywords in _STAGES:
        hits = [kw for kw in keywords if kw in lowered]
        if not hits:
            continue
        for sentence in _sentences(text):
            slow = sentence.lower()
            if any(kw in slow for kw in hits):
                found[stage] = sentence
                break
    return found


def _collect_evidence(company: str, ctx: dict) -> list[tuple[str, str, str]]:
    """Gather (text, source_label, stage_text) evidence for one company.

    stage_text is the text used for stage keyword matching (same as the
    quote source text here, so quotes stay verbatim).
    """
    want = _normalize_company(company)
    items: list[tuple[str, str, str]] = []

    for entry in ctx.get("prep_bank") or []:
        if not isinstance(entry, dict):
            continue
        if _normalize_company(entry.get("company", "")) != want:
            continue
        question = str(entry.get("question", "")).strip()
        if question:
            items.append((question, "prep question bank", question))

    for entry in ctx.get("debriefs") or []:
        if not isinstance(entry, dict):
            continue
        if _normalize_company(entry.get("company", "")) != want:
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        date = str(entry.get("date", "")).strip()
        label = f"interview debrief {date}" if date else "interview debrief"
        items.append((text, label, text))

    for entry in ctx.get("tracker") or []:
        if not isinstance(entry, dict):
            continue
        if _normalize_company(entry.get("company", "")) != want:
            continue
        notes = str(entry.get("notes", "")).strip()
        if notes:
            items.append((notes, "tracker note", notes))

    return items


def process_profile(company: str, ctx: dict | None = None) -> dict:
    """Build an interview-process profile for a company from user evidence.

    company: the company to profile.
    ctx: optional evidence context with any of "prep_bank" (list of dicts
        with company/question), "debriefs" (list of dicts with
        company/text/date), "tracker" (list of application dicts with
        company/notes/status). Missing keys are treated as [].

    Returns a dict with:
        "company": the company name as passed in,
        "stages": a list of {"stage", "evidence"} in canonical interview
            order, where each evidence item is {"quote", "source"} and
            every quote is a verbatim substring of its source text,
        "coverage": {source_label: count of evidence items used},
        "note": a summary, or "no verified interview-process data for
            <company>" when nothing was found.
    """
    ctx = ctx or {}
    stages_evidence: dict[str, list[dict]] = {name: [] for name in _STAGE_ORDER}
    coverage: dict[str, int] = {}

    for _text, source, stage_text in _collect_evidence(company, ctx):
        for stage, quote in _detect_stages(stage_text).items():
            stages_evidence[stage].append({"quote": quote, "source": source})
            coverage[source] = coverage.get(source, 0) + 1

    stages = [
        {"stage": name, "evidence": stages_evidence[name]}
        for name in _STAGE_ORDER
        if stages_evidence[name]
    ]

    if not stages:
        note = f"no verified interview-process data for {company}"
    else:
        total = sum(len(s["evidence"]) for s in stages)
        srcs = len(coverage)
        note = (
            f"Built from {total} evidence item{'s' if total != 1 else ''} "
            f"across {srcs} source{'s' if srcs != 1 else ''}."
        )

    return {
        "company": company,
        "stages": stages,
        "coverage": coverage,
        "note": note,
    }


def _load_values(company: str) -> list:
    """Best-effort company values via candid.culture_values, else [].

    Any failure (missing module, missing data, bad input) falls back to
    an empty list so the hook never breaks pack building.
    """
    try:
        from candid.culture_values import load_values  # type: ignore
    except Exception:
        return []
    try:
        values = load_values(company)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    return values


def attach_culture_to_prep(company: str, pack: dict) -> dict:
    """Return a NEW prep pack dict with a "culture" key added.

    company: the company the pack is for.
    pack: a prep pack dict (any shape). If it carries a "ctx" key with
        the evidence context (prep_bank/debriefs/tracker), that context
        feeds the process profile; otherwise the profile is built from
        empty context.

    The input pack is never mutated. The "culture" value is
    {"process": process_profile(...), "values": [...]} where values come
    from candid.culture_values.load_values on a best-effort basis
    ([] when that module or data is unavailable).
    """
    if not isinstance(pack, dict):
        raise TypeError(f"pack must be a dict, got {type(pack).__name__}")
    ctx = pack.get("ctx") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    new_pack = dict(pack)
    new_pack["culture"] = {
        "process": process_profile(company, ctx),
        "values": _load_values(company),
    }
    return new_pack
