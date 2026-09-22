"""Interview prep pack generator.

For a role with status selected_for_interview (or any role), builds a
Markdown prep pack:

  1. Company-specific questions — ONLY questions actually reported for that
     company, each with its source attribution. If none are known for the
     company, the pack says so explicitly instead of inventing questions.
  2. General role-family questions — clearly labeled as general prep, not
     company-verified.
  3. Concept deep-dives relevant to the question categories.
  4. A profile/JD-tailored mock interview (question + talking points drawn
     from the user's real experience — never fabricated).
  5. Salary benchmark for the role, if data exists.
  6. Day-before checklist.

Usage:
    python -m candid prep --company "Capital One" --role "Data Scientist" \\
        --jd jd.txt [--app-id 3]

The pack is saved to candid_data/prep_packs/ and linked to the tracker entry.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from candid.prep_questions import QUESTIONS_DB, GENERIC_BANKS
from candid import config as C
from candid import prep_concepts as PC
from candid import tracker as T


def _find_company(company: str) -> str | None:
    """Normalize a company name to a QUESTIONS_DB slug, or None."""
    slug = "".join(c for c in company.lower() if c.isalnum())
    return slug if slug in QUESTIONS_DB else None


class PrepError(Exception):
    """Raised when a prep pack cannot be built."""


_NO_COMPANY_NOTE = (
    "> **No verified company-specific questions found.** We could not find "
    "publicly reported interview questions for this company in our bank. "
    "The questions below are general {family} preparation, and the concept "
    "deep-dives cover the topics most commonly asked for this role family. "
    "If you find real reported questions, add them to "
    "`candid/prep_questions.py` (see `docs/adding_questions.md`) so future "
    "packs include them."
)


def _tailored_mock(profile: dict, role: str, company: str,
                   categories: list[str]) -> str:
    """Deterministic mock Q&A scaffold grounded in the profile."""
    name = profile.get("name") or "you"
    bullets: list[str] = []
    for e in profile.get("experience", [])[:2]:
        for b in e.get("bullets", [])[:2]:
            bullets.append((e.get("title", ""), e.get("company", ""), b))
    lines = ["### Mock interview (tailored to your background)", ""]
    qas = [
        ("Walk me through your background in 2 minutes.",
         f"Hit: your {len(profile.get('experience', []))} most recent roles, "
         f"one line of impact each, land on why {company or 'this role'}."),
        ("Tell me about the hardest technical problem you've solved recently.",
         "Use STAR. Strongest candidate from your resume: "
         + (f"\"{bullets[0][2][:90]}…\" ({bullets[0][0]} @ {bullets[0][1]})" if bullets else "pick your proudest production story.")),
        ("How would you approach this role's core problem in the first 90 days?",
         "Structure: understand the metrics → talk to stakeholders → one quick win → roadmap."),
    ]
    # add one category-flavored question
    if "ml" in categories or "system_design" in categories:
        qas.append(("Design an ML system for one of the company's core products end to end.",
                    "Cover: data sources, features, training, serving, monitoring, rollback. "
                    "See the ML system design deep-dive below."))
    if "stats" in categories:
        qas.append(("How would you design an A/B test for a new feature here?",
                    "Cover: metric hierarchy, randomization unit, runtime, guardrails. "
                    "See the A/B testing deep-dive below."))
    if "sql" in categories:
        qas.append(("Write SQL to compute a core business metric from raw event tables.",
                    "Narrate as you go; window functions are the usual tool. "
                    "See the SQL deep-dive below."))
    for i, (q, tips) in enumerate(qas, 1):
        lines += [f"**Q{i}. {q}**", "", f"*Talking points:* {tips}", ""]
    lines.append(f"*Tip for {name}: answer out loud and time yourself — 2 minutes per question.*")
    return "\n".join(lines)


def build_pack(profile: dict, company: str, role: str, jd: str = "",
               app_id: int | None = None, location: str = "") -> tuple[str, Path]:
    """Build the prep pack markdown. Returns (markdown, saved_path)."""
    slug = _find_company(company)
    company_qs = QUESTIONS_DB.get(slug, []) if slug else []
    family = _role_family(profile, role)

    generic_qs: list[dict] = []
    for bank in GENERIC_BANKS.values():
        generic_qs.extend(bank[:4])

    categories: list[str] = []
    seen = set()
    for q in company_qs:
        if q["category"] not in seen:
            categories.append(q["category"])
            seen.add(q["category"])
    if not categories:
        categories = ["ml", "stats", "behavioral"]

    concept_tags: list[str] = []
    for cat in categories:
        concept_tags.extend(PC.CATEGORY_CONCEPTS.get(cat, []))
    concept_tags.extend(PC.ROLE_FAMILY_CONCEPTS.get(family, []))
    concept_tags = list(dict.fromkeys(concept_tags))

    market_line = _market_line(company, role, location)

    lines = [
        f"# Interview Prep — {role} @ {company}",
        f"*Generated {date.today().isoformat()} · role family: {family.replace('_', ' ')}*",
        "",
        "## 1. Company-specific questions (reported by candidates)",
        "",
    ]
    if company_qs:
        cur_cat = None
        for q in company_qs:
            if q["category"] != cur_cat:
                cur_cat = q["category"]
                lines += [f"### {cur_cat.replace('_', ' ').title()}", ""]
            lines.append(f"- {q['q']}")
            reported = f" (reported {q['reported']})" if q.get("reported") else ""
            lines.append(f"  ↳ *Source: {q['source']}{reported}*")
            if q.get("url"):
                lines.append(f"    {q['url']}")
        lines.append("")
        lines.append(
            "_These are questions candidates publicly reported for this company. "
            "Treat them as representative of style and topics, not a leaked list._"
        )
    else:
        lines.append(_NO_COMPANY_NOTE.format(family=family.replace("_", " ")))
    lines += [
        "",
        "## 2. General preparation questions",
        "",
        "_General {family} prep — not verified as asked at this company._".format(
            family=family.replace("_", " ")),
        "",
    ]
    for i, q in enumerate(generic_qs[:12], 1):
        lines.append(f"{i}. {q['q']}")
    lines += ["", "## 3. Concept deep-dives", ""]
    for tag in concept_tags[:6]:
        if tag in PC.CONCEPTS:
            lines += [PC.CONCEPTS[tag], ""]
    lines += ["## 4. " + _tailored_mock(profile, role, company, categories).lstrip("# ").rstrip(),
              ""]
    lines += ["## 5. Compensation benchmark", "", market_line, ""]
    lines += ["## 6. " + PC.DAY_BEFORE_CHECKLIST.lstrip("# ").rstrip(), ""]
    lines.append("---")
    lines.append(
        "_Question bank: `candid/prep_questions.py` — add new reported questions "
        "there with source attribution. Company questions are never fabricated._"
    )

    markdown = "\n".join(lines)
    C.ensure_data_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{company}-{role}")[:60]
    out = C.PREP_PACKS_DIR / f"{date.today().isoformat()}_{safe}.md"
    out.write_text(markdown, encoding="utf-8")

    if app_id is not None:
        try:
            T.update(app_id, prep_pack=str(out))
        except T.TrackerError:
            pass
    return markdown, out


def _role_family(profile: dict, role: str) -> str:
    from candid.match import _profile_role_family, _ROLE_FAMILIES
    role_low = role.lower()
    for fam, kws in _ROLE_FAMILIES.items():
        if any(k in role_low for k in kws):
            return fam
    return _profile_role_family(profile)


def _market_line(company: str, role: str, location: str) -> str:
    try:
        from candid import salary
        m = salary.lookup(company=company, title=role, location=location)
        if m and (m.get("p25") or m.get("low")):
            from candid.match import _fmt_market
            return "Market range for this role: " + _fmt_market(m)
    except Exception:
        pass
    return (
        "No salary data for this company/role yet. "
        "Build it with `python -m candid salary import-lca <dol_csv>` or by parsing "
        "posted ranges (`salary parse-range`), then re-run this prep pack."
    )
