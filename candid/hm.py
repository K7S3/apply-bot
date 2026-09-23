"""Hiring-manager dossier store: notes on hiring managers, with meeting briefs.

Stored as JSON at candid_data/hm_dossiers.json (git-ignored).

Groundedness rule: briefs may only restate what is in the dossier
(notes / interests / sources / role fields) or overlap with supplied
JD text. Anything speculative is prefixed with "verify:" and no facts
are ever invented.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C


class HmError(Exception):
    """Raised for invalid dossier operations."""


# Fields users are allowed to set via update_dossier. "id", "created" and
# "updated" are managed internally.
KNOWN_FIELDS = (
    "name",
    "title",
    "company",
    "team",
    "notes",
    "sources",
    "interests",
    "contact_hint",
)


def _path(path: str | Path | None = None) -> Path:
    """Resolve the dossier file path.

    CANDID_DATA_DIR is read per call (not via the import-time
    C.HM_PATH constant) so tests can re-point it freely.
    """
    if path is not None:
        return Path(path)
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser() / "hm_dossiers.json"
    return C.HM_PATH


def _load(path: str | Path | None = None) -> list[dict]:
    p = _path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HmError(f"Dossier file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HmError(f"Dossier file {p} should contain a JSON list.")
    return data


def _save(dossiers: list[dict], path: str | Path | None = None) -> Path:
    """Atomic write (tmp file + rename) so a crash never leaves half a file."""
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(dossiers, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_dossier(name: str, title: str = "", company: str = "", team: str = "",
                notes: str = "", sources: list[str] | None = None,
                interests: list[str] | None = None, contact_hint: str = "",
                path: str | Path | None = None) -> dict:
    """Add a hiring-manager dossier. Returns the new record (a copy)."""
    if not name or not name.strip():
        raise HmError("Dossier name is required and cannot be empty.")
    dossiers = _load(path)
    existing_ids = {d.get("id") for d in dossiers}
    new_id = uuid.uuid4().hex[:8]
    while new_id in existing_ids:  # vanishingly unlikely; stay correct anyway
        new_id = uuid.uuid4().hex[:8]
    rec = {
        "id": new_id,
        "name": name.strip(),
        "title": title.strip(),
        "company": company.strip(),
        "team": team.strip(),
        "notes": notes.strip(),
        "sources": [str(s).strip() for s in (sources or []) if str(s).strip()],
        "interests": [str(i).strip() for i in (interests or []) if str(i).strip()],
        "contact_hint": contact_hint.strip(),
        "created": _now(),
        "updated": _now(),
    }
    dossiers.append(rec)
    _save(dossiers, path)
    return {**rec}


def list_dossiers(path: str | Path | None = None) -> list[dict]:
    """Return all dossiers as dicts."""
    return [{**d} for d in _load(path)]


def get_dossier(ref: str, path: str | Path | None = None) -> dict:
    """Fetch one dossier by id or case-insensitive name substring.

    Raises HmError when nothing matches, or when the substring is
    ambiguous (the error message lists the candidates).
    """
    dossiers = _load(path)
    if not ref:
        raise HmError("A dossier id or name is required.")
    hits = [d for d in dossiers if d.get("id") == ref]
    if not hits:
        q = ref.lower()
        hits = [d for d in dossiers if q in d.get("name", "").lower()]
    if not hits:
        raise HmError(f"No dossier found for '{ref}'.")
    if len(hits) > 1:
        cands = "; ".join(f"{d.get('name')} (id {d.get('id')})" for d in hits)
        raise HmError(f"'{ref}' is ambiguous; matches: {cands}. Use an id.")
    return {**hits[0]}


def update_dossier(ref: str, path: str | Path | None = None, **fields) -> dict:
    """Update dossier fields. Only KNOWN_FIELDS are allowed."""
    unknown = [k for k in fields if k not in KNOWN_FIELDS]
    if unknown:
        raise HmError(f"Unknown dossier field(s): {', '.join(unknown)}. "
                      f"Allowed: {', '.join(KNOWN_FIELDS)}.")
    dossiers = _load(path)
    rec = get_dossier(ref, path=path)
    for i, d in enumerate(dossiers):
        if d.get("id") == rec["id"]:
            for key, val in fields.items():
                if key in ("sources", "interests"):
                    d[key] = [str(v).strip() for v in (val or []) if str(v).strip()]
                else:
                    d[key] = str(val).strip() if val is not None else ""
            d["updated"] = _now()
            rec = {**d}
            break
    _save(dossiers, path)
    return rec


def delete_dossier(ref: str, path: str | Path | None = None) -> bool:
    """Delete a dossier by id or name substring. Returns True on success."""
    dossiers = _load(path)
    rec = get_dossier(ref, path=path)
    remaining = [d for d in dossiers if d.get("id") != rec["id"]]
    _save(remaining, path)
    return True


# --- brief helpers ------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[.\n;]+", text) if p.strip()]
    return [p for p in parts if len(p) > 3]


def _jd_skill_overlap(jd_text: str, dossier_text: str, limit: int = 6) -> list[str]:
    """Canonical skills from SKILL_LEXICON present in BOTH jd and dossier.

    Uses the shared regex helper so e.g. 'ml' doesn't match 'family'.
    """
    overlap = []
    for skill, aliases in C.SKILL_LEXICON.items():
        in_jd = any(C.skill_regex(a).search(jd_text) for a in aliases)
        if not in_jd:
            continue
        in_dossier = any(C.skill_regex(a).search(dossier_text) for a in aliases)
        if in_dossier:
            overlap.append(skill)
    return overlap[:limit]


def _first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def manager_brief(ref: str, jd_text: str = "",
                  path: str | Path | None = None) -> dict:
    """Build a meeting brief for the hiring manager.

    Everything returned is derived only from the dossier
    (notes/interests/sources/role fields) plus keywords verified to
    appear in both the JD and the dossier. Speculative items are
    prefixed with "verify:"; no facts are invented.
    """
    d = get_dossier(ref, path=path)
    name = d.get("name", "")
    title = d.get("title", "")
    company = d.get("company", "")
    team = d.get("team", "")
    notes = d.get("notes", "")
    sources = d.get("sources", []) or []
    interests = d.get("interests", []) or []
    first = _first_name(name)

    role_bits = [b for b in (title, company) if b]
    summary = f"{name}" + (f" — {' at '.join(role_bits)}" if role_bits else "")
    if team:
        summary += f" (team: {team})"
    if notes:
        clip = notes if len(notes) <= 400 else notes[:400] + "..."
        summary += f". Notes: {clip}"

    talking_points: list[str] = []
    for s in _sentences(notes)[:4]:
        talking_points.append(f"From your notes: {s}")
    for i in interests[:4]:
        talking_points.append(f"Shared interest to mention: {i}")
    dossier_text = " ".join([notes, team, title, " ".join(interests)])
    for skill in _jd_skill_overlap(jd_text, dossier_text):
        talking_points.append(
            f"JD overlap: '{skill}' appears in both the JD and your dossier notes")
    for src in sources[:4]:
        talking_points.append(
            f"verify: re-check '{src}' for anything new before the call")

    openers: list[str] = []
    role_desc = " / ".join(b for b in (title, team, company) if b)
    if role_desc:
        openers.append(
            f"Hi {first}, I saw you're {role_desc} — curious what the team "
            f"is prioritizing this year.")
    if interests:
        openers.append(
            f"Hi {first}, noticed from your profile that you're into "
            f"{interests[0]} — would love to hear how you got into it.")
    openers.append(
        f"Hi {first}, thanks for taking the time — what's top of mind "
        f"for you heading into this role?")
    if sources:
        openers.append(
            f"verify: tailor an opener to their latest {sources[0]} activity "
            f"(check it before the call; don't quote stale notes)")
    else:
        openers.append(
            f"verify: draft an opener from their bio once you research it "
            f"(not in your notes yet)")
    openers = openers[:3]

    questions: list[str] = []
    if team:
        questions.append(f"What are the {team}'s top priorities this quarter?")
    if notes:
        sents = _sentences(notes)
        if sents:
            questions.append(
                f"Your notes say: '{sents[0]}' — ask them to tell you more.")
    if title:
        questions.append(
            f"What's the biggest challenge for a {title}"
            + (f" on {team}" if team else "") + " right now?")
    if not questions:
        questions.append(
            "What does success look like in this role in the first 6 months?")
    questions = questions[:3]

    return {
        "summary": summary,
        "talking_points": talking_points,
        "openers": openers,
        "questions_to_ask": questions,
    }
