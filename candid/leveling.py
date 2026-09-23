"""Leveling guides: IC ladders at target companies, scope per level, and
cross-company level translation.

Data lives in candid/data/leveling.json (reference approximations, not
official company docs - the disclaimer in the file says so). All matching
is deterministic: levels are identified by code ("E5"), alias ("senior",
"5"), or "aka" entries, and translation works by aligning each level to a
shared "rung" scale (0 = early career ... 5 = distinguished/fellow).

Public API:
    list_companies()                       supported companies + level counts
    normalize_company(key)                 "facebook" -> "meta"
    get_guide(company)                      full ladder dict
    get_level(company, level)               one level dict (normalized)
    scope_expectations(company, level)      (level, guide) with detail
    translate_level(from_co, level, to_co)   rung-aligned translation + caveats
    compare_levels(company, a, b)           what changes from level a to b
    render_*()                              text renderers for the CLI

The CLI hook is `python -m candid leveling <subcommand>`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "leveling.json"


class LevelingError(Exception):
    """Expected leveling failure (unknown company, unknown level, bad data)."""


@lru_cache(maxsize=1)
def _load_data() -> dict:
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LevelingError(f"Could not load leveling data: {exc}") from exc
    if "companies" not in data:
        raise LevelingError("Leveling data file is missing the 'companies' key.")
    return data


def _companies() -> dict:
    return _load_data()["companies"]


def list_companies() -> list[dict]:
    """Supported companies: key, display name, track, level codes."""
    out = []
    for key, co in _companies().items():
        out.append({
            "key": key,
            "name": co.get("name", key),
            "track": co.get("track", ""),
            "levels": [lv["code"] for lv in co.get("levels", [])],
        })
    return out


def normalize_company(key: str) -> str:
    """Canonical company key; aliases like 'facebook'/'aws'/'msft' resolve."""
    want = (key or "").strip().lower()
    for ckey, co in _companies().items():
        if want == ckey or want == co.get("name", "").lower():
            return ckey
        if want in [a.lower() for a in co.get("aliases", [])]:
            return ckey
    known = ", ".join(sorted(_companies()))
    raise LevelingError(f"Unknown company {key!r}. Known: {known}.")


def get_guide(company: str) -> dict:
    """Full ladder dict for a company."""
    ckey = normalize_company(company)
    return _companies()[ckey]


def _level_candidates(level: dict) -> set[str]:
    cands = {level.get("code", "").lower()}
    for aka in level.get("aka", []):
        cands.add(str(aka).lower())
    title = level.get("title", "")
    if title:
        cands.add(title.lower())
    return {c.strip() for c in cands if c.strip()}


def normalize_level(company: str, level: str) -> dict:
    """Find one level dict by code, alias, or title (case-insensitive)."""
    co = get_guide(company)
    want = (level or "").strip().lower()
    # strip a leading company-ish prefix people sometimes type, e.g. "google l5"
    for ckey, cco in _companies().items():
        names = {ckey, cco.get("name", "").lower()} | {a.lower() for a in cco.get("aliases", [])}
        for n in names:
            if want.startswith(n + " "):
                want = want[len(n) + 1:].strip()
    for lv in co.get("levels", []):
        if want in _level_candidates(lv):
            return lv
    codes = ", ".join(lv["code"] for lv in co.get("levels", []))
    raise LevelingError(
        f"Unknown level {level!r} at {co.get('name')}. Levels: {codes}.")


def get_level(company: str, level: str) -> dict:
    """Public alias for normalize_level."""
    return normalize_level(company, level)


def scope_expectations(company: str, level: str) -> tuple[dict, dict]:
    """(level_dict, company_dict) for a company + level."""
    co = get_guide(company)
    return normalize_level(company, level), co


def next_level(company: str, level: str) -> dict | None:
    """The level above the given one, or None at the top of the ladder."""
    co = get_guide(company)
    lv = normalize_level(company, level)
    levels = co.get("levels", [])
    idx = next((i for i, l in enumerate(levels) if l is lv), None)
    if idx is None or idx + 1 >= len(levels):
        return None
    return levels[idx + 1]


def translate_level(from_company: str, level: str, to_company: str) -> dict:
    """Translate a level between companies via the shared rung scale.

    Returns the source level, the closest target level (or None when the
    target ladder does not reach that high), and caveats. Leveling is
    company-internal: this is a planning approximation, not a guarantee.
    """
    src = normalize_level(from_company, level)
    dst_co = get_guide(to_company)
    src_co = get_guide(from_company)
    rung = src.get("rung")
    best, best_gap = None, None
    for lv in dst_co.get("levels", []):
        gap = abs(lv.get("rung", 0) - rung)
        if best is None or gap < best_gap:
            best, best_gap = lv, gap
    result = {
        "from": {"company": src_co.get("name"), "code": src["code"],
                 "title": src.get("title", "")},
        "to": None,
        "rung": rung,
        "caveats": [
            "Leveling is company-internal; translations are approximations.",
            "Down-leveling on hire is common: expect the offer at the translated "
            "level or one rung lower.",
            "Tenure, scope evidence, and interview performance all shift the outcome.",
        ],
    }
    if best is not None and best_gap <= 1:
        result["to"] = {"company": dst_co.get("name"), "code": best["code"],
                        "title": best.get("title", "")}
    return result


def rung_meanings() -> dict:
    return _load_data().get("rung_meanings", {})


def compare_levels(company: str, from_level: str, to_level: str) -> dict:
    """What changes going from one level to another at the same company.

    Returns the two level dicts, scope bullets unique to the target, the
    target's promo criteria, and the typical time between them.
    """
    co = get_guide(company)
    src = normalize_level(company, from_level)
    dst = normalize_level(company, to_level)
    src_bullets = set(src.get("scope", []))
    new_scope = [b for b in dst.get("scope", []) if b not in src_bullets]
    months = dst.get("typical_months_to_next")
    return {
        "company": co.get("name"),
        "from": src,
        "to": dst,
        "new_scope": new_scope,
        "promo_criteria": dst.get("promo_criteria", []),
        "typical_months_to_next": months,
    }


def disclaimer() -> str:
    return _load_data().get("disclaimer", "")


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

def render_company_list() -> str:
    lines = ["Leveling guides available:\n"]
    for co in list_companies():
        lines.append(f"  {co['key']:<10} {co['name']} - {co['track']}")
        lines.append(f"             levels: {', '.join(co['levels'])}")
    lines.append("")
    lines.append("Note: reference approximations for planning. "
                 "Verify against official docs before any promotion decision.")
    return "\n".join(lines)


def render_guide(company: str) -> str:
    co = get_guide(company)
    lines = [f"{co.get('name')} - {co.get('track')}", ""]
    for lv in co.get("levels", []):
        lines.append(f"{lv['code']:<14} {lv.get('title', '')} "
                     f"(typical {lv.get('typical_years', '?')} yrs)")
        lines.append(f"  {lv.get('summary', '')}")
    lines.append("")
    lines.append("Detail one level: "
                 f"python -m candid leveling scope --company {normalize_company(company)} "
                 "--level <code>")
    return "\n".join(lines)


def render_ladder(company: str) -> str:
    co = get_guide(company)
    meanings = rung_meanings()
    lines = [f"{co.get('name')} IC ladder", ""]
    width = max(len(lv["code"]) for lv in co.get("levels", []))
    for lv in reversed(co.get("levels", [])):
        rung = lv.get("rung")
        meaning = meanings.get(str(rung), "")
        lines.append(f"  {lv['code']:<{width}}  {lv.get('title', '')}")
        if meaning:
            lines.append(f"  {'':<{width}}  {meaning}")
        lines.append("    |")
    lines = lines[:-1]  # drop trailing connector
    return "\n".join(lines)


def render_scope(company: str, level: str) -> str:
    lv, co = scope_expectations(company, level)
    lines = [f"{co.get('name')} {lv['code']} - {lv.get('title', '')}",
             f"Typical experience: {lv.get('typical_years', '?')} years", "",
             "Scope expectations:"]
    for b in lv.get("scope", []):
        lines.append(f"  - {b}")
    lines.append("")
    lines.append(f"Promotion criteria (to reach {lv['code']}):")
    for b in lv.get("promo_criteria", []):
        lines.append(f"  - {b}")
    months = lv.get("typical_months_to_next")
    if months:
        lines.append("")
        lines.append(f"Typical time to the next level: ~{months} months.")
    return "\n".join(lines)


def render_translation(from_company: str, level: str, to_company: str) -> str:
    t = translate_level(from_company, level, to_company)
    f, dst = t["from"], t["to"]
    lines = [f"{f['company']} {f['code']} ({f['title']})",
             f"  ~= rung {t['rung']}", ""]
    if dst:
        lines.append(f"Closest match: {dst['company']} {dst['code']} ({dst['title']})")
    else:
        lines.append("No close match: the target ladder does not reach this rung.")
    lines.append("")
    lines.append("Caveats:")
    for c in t["caveats"]:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def render_compare(company: str, from_level: str, to_level: str) -> str:
    c = compare_levels(company, from_level, to_level)
    src, dst = c["from"], c["to"]
    lines = [f"{c['company']}: {src['code']} -> {dst['code']}", "",
             f"What is new at {dst['code']} ({dst.get('title', '')}):"]
    for b in c["new_scope"]:
        lines.append(f"  - {b}")
    lines.append("")
    lines.append(f"Promotion criteria to reach {dst['code']}:")
    for b in c["promo_criteria"]:
        lines.append(f"  - {b}")
    if c["typical_months_to_next"]:
        lines.append("")
        lines.append(f"Typical time in {src['code']} before promotion: "
                     f"~{c['typical_months_to_next']} months.")
    lines.append("")
    lines.append("Assess yourself against this: "
                 f"python -m candid promo checklist --company {normalize_company(company)} "
                 f"--current {src['code']} --target {dst['code']}")
    return "\n".join(lines)
