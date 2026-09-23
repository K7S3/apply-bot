"""Referral outreach helpers: find alumni/classmates, draft peer-level asks.

candid never scrapes LinkedIn and never sends anything automatically.
This module produces (a) a ready-to-paste search checklist for finding
alumni and classmates at a target company, and (b) message templates
for the new-grad outreach (peer-level, connection-note length).

The actual searching and sending is done by the user in their browser.
"""

from __future__ import annotations

import re

from candid import followup as F


def school_info(profile: dict) -> dict:
    """Return {"school", "class_year"} from the newest education entry.

    class_year is the last 4-digit year found in the entry's dates
    (e.g. "2022 - 2026" -> "2026"). Empty strings when nothing is found.
    """
    entries = profile.get("education") or []
    if not entries:
        return {"school": "", "class_year": ""}
    latest = max(
        entries,
        key=lambda e: int((re.findall(r"(?:19|20)\d{2}", e.get("dates", "") or "") or ["0"])[-1]),
    )
    school = latest.get("school", "") or ""
    years = re.findall(r"(?:19|20)\d{2}", latest.get("dates", "") or "")
    return {"school": school, "class_year": years[-1] if years else ""}


def classmates_search_terms(profile: dict, company: str) -> dict:
    """Build a ready-to-paste alumni search checklist for a target company.

    Returns {"school", "class_year", "company", "linkedin_filters",
    "queries", "steps"} - everything the user needs to find alumni and
    classmates at the company via LinkedIn's own search UI (no scraping).
    """
    info = school_info(profile)
    school, year = info["school"], info["class_year"]
    company = (company or "").strip()

    linkedin_filters = [
        f"LinkedIn People search -> Past Company: {company}"
        + (f" + School: {school}" if school else ""),
        "Sort by: relevance, then filter to 2nd-degree connections first",
        "Tip: on the company's LinkedIn page, open the People tab and filter by school",
    ]
    queries = [
        f'site:linkedin.com/in "{school}" "{company}"' if school else f'site:linkedin.com/in "{company}"',
        f'"{school}" "{company}" new grad' if school else f'"{company}" new grad',
        f'"{school}" "{company}" university recruiting' if school else f'"{company}" university recruiting',
    ]
    steps = [
        f"1. Open LinkedIn People search; set Past Company = {company}"
        + (f"; School = {school}" if school else ""),
        "2. Prioritize 2nd-degree connections and people who joined as new grads",
        "3. Check your school's alumni directory / career center portal too",
        "4. Send the connection note below (warm variant for classmates, cold for alumni)",
        "5. Follow up once after 5-7 days if there is no reply",
    ]
    return {
        "school": school,
        "class_year": year,
        "company": company,
        "linkedin_filters": linkedin_filters,
        "queries": queries,
        "steps": steps,
    }


def render_classmates(profile: dict, company: str) -> str:
    """Render the full classmates helper: checklist + message templates."""
    name = profile.get("name") or "Your Name"
    terms = classmates_search_terms(profile, company)
    info = school_info(profile)
    lines = [
        f"Find alumni/classmates at {company}",
        "=" * 40,
        "",
        "LinkedIn filters (paste into the People search):",
    ]
    lines += [f"  - {f}" for f in terms["linkedin_filters"]]
    lines += ["", "Ready-to-paste web queries:"]
    lines += [f"  - {q}" for q in terms["queries"]]
    lines += ["", "Steps:"]
    lines += [f"  {s}" for s in terms["steps"]]
    lines += ["", "-" * 40, "Cold alumni template (connection-note length):", ""]
    lines.append(F.new_grad_referral_ask(name, "<FirstName>", "<Role>", company,
                                         info["school"], info["class_year"],
                                         variant="cold"))
    lines += ["", "-" * 40, "Warm classmate template (connection-note length):", ""]
    lines.append(F.new_grad_referral_ask(name, "<FirstName>", "<Role>", company,
                                         info["school"], info["class_year"],
                                         variant="warm"))
    lines += ["",
              "DRAFTS ONLY - nothing was sent. Copy, personalize, and send yourself."]
    return "\n".join(lines)
