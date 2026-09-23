"""ritual interviewers: record who's interviewing you and prep angles.

    python -m candid ritual interviewers --company X --role Y \\
        --add "Jane Doe, Hiring Manager" [--round "1"]
    python -m candid ritual interviewers --company X --role Y --list

Interviewer panels live at candid_data/rituals/<ritual_id>/interviewers.json.
The --list view shows quick-glance cards and, for each interviewer role,
suggests likely question angles drawn from the real prep question bank
(candid.prep_questions.GENERIC_BANKS). Those angles are general guidance:
they are never company-verified unless QUESTIONS_DB has the company.
"""

from __future__ import annotations

import json


class RitualError(Exception):
    """Expected failure: reported cleanly, no traceback."""


def _panel_path(company: str, role: str):
    from candid import ritual as R
    rid = R._ritual_id(company, role)
    return R._rituals_dir() / rid / "interviewers.json"


def _load_panel(company: str, role: str) -> list[dict]:
    path = _panel_path(company, role)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        raise RitualError(f"Interviewer panel file is unreadable: {path}")


def _save_panel(company: str, role: str, panel: list[dict]) -> None:
    path = _panel_path(company, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panel, indent=2))


def parse_add(spec: str) -> dict:
    """Parse --add "Name, Title" into a record. Round is set separately."""
    name, _, title = spec.partition(",")
    name, title = name.strip(), title.strip()
    if not name:
        raise RitualError('Could not parse --add. Use: --add "Jane Doe, Hiring Manager"')
    return {"name": name, "title": title or "Interviewer", "round": ""}


# Interviewer-role keywords -> GENERIC_BANKS categories in prep_questions.
_ROLE_ANGLE_MAP: list[tuple[list[str], list[str], str]] = [
    (["recruiter", "talent", "sourcer", "hr", "coordinator", "people"],
     ["behavioral"], "background screen"),
    (["hiring manager", "manager", "director", "vp", "head of", "chief"],
     ["behavioral"], "behavioral / leadership"),
    (["data scientist", "analyst", "data"],
     ["data_analyst", "behavioral"], "case / SQL / stats"),
    (["ml ", "machine learning", "ai ", "research", "scientist"],
     ["ml_engineer", "behavioral"], "ML system design"),
    (["quant", "trading"],
     ["quant", "behavioral"], "quant"),
    (["engineer", "developer", "swe", "software", "backend", "frontend",
      "full stack", "sde", "devops", "infra"],
     ["software_engineer", "behavioral"], "coding / system design"),
    (["design", "ux", "product", "pm"],
     ["behavioral"], "product sense / behavioral"),
]


def suggest_angles(interviewer_title: str) -> tuple[list[str], str]:
    """Return (bank_keys, angle_label) for an interviewer title."""
    title = (interviewer_title or "").lower()
    for keywords, banks, label in _ROLE_ANGLE_MAP:
        if any(k in title for k in keywords):
            return banks, label
    return ["behavioral"], "behavioral (general)"


def _banks():
    """Defensive import of the real prep question bank; empty if missing."""
    try:
        from candid import prep_questions
    except ImportError:
        return {}, {}
    return (getattr(prep_questions, "GENERIC_BANKS", {}) or {},
            getattr(prep_questions, "QUESTIONS_DB", {}) or {})


def add_interviewer(company: str, role: str, spec: str, round_label: str = "") -> dict:
    """Append one interviewer to the panel and persist it."""
    panel = _load_panel(company, role)
    record = parse_add(spec)
    record["round"] = round_label or ""
    panel.append(record)
    _save_panel(company, role, panel)
    return record


def render_card(interviewer: dict, banks: dict, company_verified: bool,
                company: str) -> str:
    """Quick-glance card: who, their angle, sample questions."""
    title = interviewer.get("title", "Interviewer")
    name = interviewer.get("name", "?")
    round_label = interviewer.get("round", "")
    bank_keys, angle_label = suggest_angles(title)
    lines = [f"== {name} - {title}" + (f" (round: {round_label})" if round_label else "")]
    if company_verified:
        lines.append(f"   Likely angle: {angle_label} [company-verified: "
                     f"QUESTIONS_DB has reported questions for {company}]")
    else:
        lines.append(f"   Likely angle: {angle_label} [general guidance, not company-verified]")
    shown = 0
    for key in bank_keys:
        for q in banks.get(key, []):
            if shown >= 3:
                break
            text = q.get("q", "") if isinstance(q, dict) else str(q)
            lines.append(f"   - {text}")
            shown += 1
        if shown >= 3:
            break
    if shown == 0:
        lines.append("   - (question bank unavailable; prep from the prep pack instead)")
    return "\n".join(lines)


def list_interviewers(company: str, role: str) -> str:
    panel = _load_panel(company, role)
    banks, questions_db = _banks()
    key = "".join(company.lower().split())
    company_verified = key in questions_db
    out = [f"Interview panel for {role} at {company} ({len(panel)} interviewer(s)):"]
    if not panel:
        out.append("  (empty - add with --add \"Name, Title\")")
    for iv in panel:
        out.append("")
        out.append(render_card(iv, banks, company_verified, company))
    if company_verified:
        out.append("")
        out.append("Note: QUESTIONS_DB has verified questions for this company;")
        out.append("see `python -m candid prep --company ... --role ...` for the sourced pack.")
    else:
        out.append("")
        out.append("Note: angles above are general guidance from the prep question bank,")
        out.append("not verified as asked at this company.")
    return "\n".join(out)


def run(a) -> int:
    if getattr(a, "add", ""):
        record = add_interviewer(a.company, a.role, a.add,
                                 round_label=getattr(a, "round", "") or "")
        print(f"Added: {record['name']} - {record['title']}"
              + (f" (round: {record['round']})" if record["round"] else ""))
    print("")
    print(list_interviewers(a.company, a.role))
    return 0
