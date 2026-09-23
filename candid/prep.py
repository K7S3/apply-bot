"""Interview prep pack generator.

For a role with status selected_for_interview (or any role), builds a
Markdown prep pack:

  1. Company-specific questions — ONLY questions actually reported for that
     company, each with its source attribution. If none are known for the
     company, the pack says so explicitly instead of inventing questions.
  2. General role-family questions — clearly labeled as general prep, not
     company-verified.
  3. Concept deep-dives relevant to the question categories. When match
     `gaps` are passed, gap-related deep-dives are ordered first.
  4. A profile/JD-tailored mock interview (question + talking points drawn
     from the user's real experience — never fabricated).
  5. STAR story prompts mapped to the user's strongest resume bullets.
  6. Salary benchmark for the role, if data exists, plus comp talking points.
  7. Company-research checklist.
  8. Day-before checklist.

Usage:
    python -m candid prep --company "Capital One" --role "Data Scientist" \\
        --jd jd.txt [--app-id 3]

Pass the gaps list from `match.score_match(jd)["gaps"]` (via --gaps in a
future CLI flag, or programmatically) to prioritize weak areas.

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


# ---------------------------------------------------------------------------
# New-grad question banks: entry-level fundamentals.
#
# These are general, widely-asked entry-level topics - they are labeled as
# general preparation in the pack, never attributed to a specific company.
# Weights express how much of the pack each area gets for a new grad.
# ---------------------------------------------------------------------------

NEW_GRAD_BANKS: dict[str, list[dict]] = {
    "dsa": [
        {"q": "What is Big-O notation? Compare the time and space complexity of a hash map lookup vs a linear scan.", "category": "dsa_fundamentals"},
        {"q": "Implement a function to reverse a singly linked list, iteratively and recursively. What is the complexity?", "category": "dsa_fundamentals"},
        {"q": "Given an array of integers, find two that sum to a target. Walk through the brute-force and hash-map solutions.", "category": "dsa_fundamentals"},
        {"q": "When would you use a stack vs a queue? Give a real example of each.", "category": "dsa_fundamentals"},
        {"q": "Explain breadth-first search and depth-first search. When does each make sense?", "category": "dsa_fundamentals"},
        {"q": "Implement binary search. What are the preconditions, and what is the complexity?", "category": "dsa_fundamentals"},
        {"q": "How does quicksort work at a high level, and why is it O(n log n) on average but O(n^2) in the worst case?", "category": "dsa_fundamentals"},
        {"q": "Explain how a hash map handles collisions (chaining vs open addressing).", "category": "dsa_fundamentals"},
    ],
    "oop": [
        {"q": "What are the four pillars of OOP? Give a concrete code example of each.", "category": "oop"},
        {"q": "Inheritance vs composition: which do you prefer and why? Give an example where composition is cleaner.", "category": "oop"},
        {"q": "What is polymorphism? Show how it simplifies a design.", "category": "oop"},
        {"q": "Abstract class vs interface: how do you decide which to use?", "category": "oop"},
        {"q": "What does encapsulation buy you in a large codebase? How does it relate to API design?", "category": "oop"},
    ],
    "sql_basics": [
        {"q": "Explain INNER JOIN, LEFT JOIN, RIGHT JOIN, and FULL OUTER JOIN with a small example.", "category": "sql_basics"},
        {"q": "What is the difference between WHERE and HAVING? When must you use GROUP BY?", "category": "sql_basics"},
        {"q": "Write a query that finds the top 3 departments by average salary using aggregate functions.", "category": "sql_basics"},
        {"q": "How do NULLs behave in comparisons and aggregates? How do you handle them safely?", "category": "sql_basics"},
        {"q": "What does an index do, and what is the cost of adding one?", "category": "sql_basics"},
    ],
    "os_networking": [
        {"q": "Process vs thread: what is shared, what is not? When would you use multiprocessing over multithreading?", "category": "os_networking"},
        {"q": "What is a deadlock? Describe the four necessary conditions and one way to prevent it.", "category": "os_networking"},
        {"q": "Walk through what happens when you type a URL into a browser and press enter (DNS, TCP/TLS, HTTP).", "category": "os_networking"},
        {"q": "TCP vs UDP: what guarantees does TCP give, and what does it cost?", "category": "os_networking"},
        {"q": "Stack vs heap memory: what lives where, and what happens on a stack overflow?", "category": "os_networking"},
        {"q": "What is caching, and where can caches live in a web request path?", "category": "os_networking"},
    ],
    "behavioral": [
        {"q": "Tell me about a team project (school, hackathon, or open source) where you had to divide work and hit a deadline.", "category": "new_grad_behavioral"},
        {"q": "Describe a time you had to learn a new technology or skill quickly for a project. How did you approach it?", "category": "new_grad_behavioral"},
        {"q": "Tell me about a time you received critical feedback on your work (code review, grade, internship review). What did you change?", "category": "new_grad_behavioral"},
        {"q": "Describe a situation where the requirements were ambiguous and you had limited experience to draw on. What did you do?", "category": "new_grad_behavioral"},
        {"q": "Why this company, and why this role as your first full-time job? What do you want to learn here?", "category": "new_grad_behavioral"},
        {"q": "Tell me about a bug or problem that took you much longer to solve than expected. How did you get unstuck?", "category": "new_grad_behavioral"},
    ],
}

# How many questions each area contributes to a new-grad pack, in order.
NEW_GRAD_WEIGHTS: dict[str, int] = {
    "dsa": 4,
    "sql_basics": 3,
    "oop": 3,
    "os_networking": 3,
    "behavioral": 5,
}


def select_new_grad_questions(
    banks: dict[str, list[dict]] | None = None,
    weights: dict[str, int] | None = None,
) -> list[dict]:
    """Pure selection: weighted, ordered new-grad questions.

    Fundamentals (DSA, SQL, OOP, OS/networking) come before advanced topics;
    behavioral questions round out the set. Never touches company data.
    """
    banks = NEW_GRAD_BANKS if banks is None else banks
    weights = NEW_GRAD_WEIGHTS if weights is None else weights
    out: list[dict] = []
    for area in weights:
        out.extend(banks.get(area, [])[: weights[area]])
    return out


_NEW_GRAD_STAR_ROTATION = [
    "Tell me about a time you worked on a team project with a real deadline.",
    "Tell me about a time you learned something technical fast under pressure.",
    "Tell me about a time you received tough feedback and changed course.",
    "Tell me about a time you owned an ambiguous problem with no playbook.",
    "Tell me about a time you debugged something hard and finally cracked it.",
]

NEW_GRAD_DEEPDIVES: list[str] = [
    """### Fundamentals First: Arrays, Hash Maps, and Big-O

**The idea in 60 seconds.** Entry-level coding rounds test whether you can
pick the right data structure and reason about cost. Arrays give O(1) index
access but O(n) inserts in the middle; hash maps give average O(1) lookup
at the cost of extra memory; trees and heaps add ordering guarantees at
O(log n). Interviewers care less about memorized solutions than about you
saying "this is O(n^2), I can get O(n) with a hash map" *before* writing code.

**How to practice.** For every problem: state the brute force and its Big-O,
name the bottleneck, then optimize. Say the complexity out loud - it is half
the score.""",
    """### SQL Fundamentals: Joins, Grouping, and NULLs

**The idea in 60 seconds.** New-grad SQL rounds stay at the basics: join the
right tables, filter with WHERE, aggregate with GROUP BY, and filter groups
with HAVING. The two classic traps: NULL silently breaking comparisons
(`WHERE x != NULL` matches nothing - use `IS NULL`), and forgetting that
non-aggregated SELECT columns must appear in GROUP BY.

**How to practice.** Write 10 queries against any sample dataset covering:
inner/left join, self-join, GROUP BY + HAVING, and a subquery. Narrate the
row flow: "first we join, then we filter, then we group." """,
    """### The Web Request Lifecycle (OS + Networking in One)

**The idea in 60 seconds.** "What happens when you type a URL?" is the most
common entry-level systems question because it touches everything: DNS
resolves the name, TCP + TLS set up a secure channel, HTTP requests the
resource, caches (browser, CDN) may short-circuit it, and the server's
processes/threads handle it concurrently. You do not need distributed-systems
depth - you need the full path in order, with one sentence per hop.

**How to answer.** Draw the pipeline left to right, name each hop, and for
each hop say what could go wrong (DNS fails, TLS handshake slow, cache
stale). That shows systems thinking without advanced system design.""",
    """### OOP Design: Composition Over Inheritance

**The idea in 60 seconds.** Entry-level OOP questions reward clean modeling,
not design patterns trivia. Encapsulation hides internals behind a small
API; inheritance shares behavior but couples classes; composition builds
behavior from small parts and is usually more flexible. When asked to model
something (a deck of cards, a parking lot), start with nouns as classes,
verbs as methods, and keep each class to one job.

**How to practice.** Model two small domains on paper: list classes,
their state, their public methods, and where you'd use composition instead
of inheritance. Talk through tradeoffs out loud.""",
]

NEW_GRAD_SYSTEM_DESIGN_NOTE = """### A note on system design for new grads

_System design expectations are much lighter for entry-level roles._ Most
new-grad loops do not include a dedicated system-design round; when they do,
interviewers look for structured thinking, not a production-ready design.
Focus your energy where it is actually graded:

- **Coding rounds (highest weight):** DSA fundamentals + clean code.
- **Behavioral rounds:** teamwork, learning speed, feedback, ambiguity.
- **If a design question appears:** draw boxes and arrows, name the data
  flow, mention scaling in one sentence ("add a cache here, shard there"),
  and ask clarifying questions before designing. That is usually enough.
"""


def new_grad_sections(profile: dict) -> tuple[list[dict], list[str], str]:
    """Pure helper: (questions, deep-dives, system-design note) for new grads.

    Pulls in project bullets as STAR story sources alongside resume bullets.
    """
    return select_new_grad_questions(), list(NEW_GRAD_DEEPDIVES), NEW_GRAD_SYSTEM_DESIGN_NOTE


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

# gap text (lowercased) -> question category, for prioritizing deep-dives.
# Match gaps look like "Missing must-have skill: sql" or "Seniority gap: ...".
_GAP_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("sql", "sql"),
    ("experiment", "stats"),
    ("a/b", "stats"),
    ("statistic", "stats"),
    ("causal", "stats"),
    ("probability", "stats"),
    ("machine learning", "ml"),
    ("deep learning", "ml"),
    ("llm", "ml"),
    ("model", "ml"),
    ("system design", "system_design"),
    ("distributed", "system_design"),
    ("python", "python"),
    ("coding", "python"),
    ("behavioral", "behavioral"),
    ("leadership", "behavioral"),
    ("communication", "behavioral"),
    ("stakeholder", "behavioral"),
    ("product sense", "product"),
    ("metric", "product"),
    ("case", "case"),
    ("seniority", "behavioral"),
]


def _gap_categories(gaps: list[str]) -> list[str]:
    """Map match-gap strings to question categories, most frequent first."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for gap in gaps or []:
        low = str(gap).lower()
        for keyword, category in _GAP_CATEGORY_KEYWORDS:
            if keyword in low:
                if category not in counts:
                    order.append(category)
                counts[category] = counts.get(category, 0) + 1
                break
    return sorted(order, key=lambda c: -counts[c])


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
    if "sql" in categories or "sql_basics" in categories:
        qas.append(("Write SQL to compute a core business metric from raw event tables.",
                    "Narrate as you go; window functions are the usual tool. "
                    "See the SQL deep-dive below."))
    if "dsa_fundamentals" in categories:
        qas.append(("Solve a classic array/hash-map problem (e.g. two sum) out loud.",
                    "State the brute force and its Big-O first, then optimize. "
                    "See the fundamentals deep-dive below."))
    for i, (q, tips) in enumerate(qas, 1):
        lines += [f"**Q{i}. {q}**", "", f"*Talking points:* {tips}", ""]
    lines.append(f"*Tip for {name}: answer out loud and time yourself — 2 minutes per question.*")
    return "\n".join(lines)


def _top_bullets(profile: dict, limit: int = 5, include_projects: bool = False,
               ) -> list[tuple[str, str, str]]:
    """Strongest resume bullets: most recent experience, numbers first.

    When include_projects is True (new-grad mode), project bullets are mixed
    in so STAR stories can draw on school/side projects too.
    """
    bullets: list[tuple[str, str, str]] = []
    for e in profile.get("experience", [])[:3]:
        for b in e.get("bullets", [])[:3]:
            text = str(b).strip()
            if text:
                bullets.append((e.get("title", ""), e.get("company", ""), text))
    if include_projects:
        for p in profile.get("projects", [])[:3]:
            for b in p.get("bullets", [])[:3]:
                text = str(b).strip()
                if text:
                    bullets.append((p.get("name", ""), "project", text))
    bullets.sort(key=lambda t: (any(ch.isdigit() for ch in t[2]), len(t[2])),
                 reverse=True)
    return bullets[:limit]


_STAR_QUESTION_ROTATION = [
    "Tell me about a time you drove measurable impact.",
    "Tell me about a time you solved a hard technical problem.",
    "Tell me about a time you influenced people without authority.",
    "Tell me about a time something you owned failed.",
    "Tell me about a time you had to move fast with incomplete information.",
]


def _star_prompts(profile: dict, new_grad: bool = False) -> str:
    """Behavioral prompts, each mapped to one of the user's real bullets.

    In new-grad mode the question rotation is entry-level (teamwork on
    school projects, learning fast, feedback, ambiguity, debugging) and
    project bullets join the pool alongside resume bullets.
    """
    rotation = _NEW_GRAD_STAR_ROTATION if new_grad else _STAR_QUESTION_ROTATION
    lines = [
        "### STAR story prompts (from your resume)",
        "",
        "_Each classic behavioral question is paired with one of your strongest "
        "resume bullets. Draft each answer as Situation → Task → Action → Result, "
        "150+ words, said out loud - never invent details that are not in the bullet._",
        "",
    ]
    top = _top_bullets(profile, include_projects=new_grad)
    if not top:
        lines += ["_No resume bullets found - write 3 STAR stories from your "
                  "proudest projects before interview day._", ""]
        return "\n".join(lines)
    for i, (title, company, bullet) in enumerate(top):
        q = rotation[i % len(rotation)]
        at = f" ({title} @ {company})" if title or company else ""
        lines += [
            f"**{q}**",
            "",
            f"> Your bullet{at}: \"{bullet}\"",
            "",
            "*STAR scaffold:* Situation (team, stakes, one line) → Task (what you "
            "personally owned) → Action (2-3 concrete steps *you* took) → Result "
            "(the metric in the bullet above, plus what you learned).",
            "",
        ]
    return "\n".join(lines)


def _research_checklist(company: str) -> str:
    co = company or "the company"
    items = [
        f"{co}'s core products and how it makes money (one sentence each)",
        "Last 2 product launches or earnings highlights - one talking point each",
        "The team's mission and how this role connects to it",
        "Interviewers' backgrounds (LinkedIn) - one tailored question per interviewer",
        f"{co}'s engineering blog: skim 2 posts, note one idea you can reference",
        "Top 2 competitors and what differentiates this company",
        f"Recent news about {co} in the last 90 days (funding, launches, reorgs)",
        "Glassdoor/Blind themes: what employees praise and what they complain about",
    ]
    lines = ["### Company-research checklist", ""]
    lines += [f"- [ ] {item}" for item in items]
    lines.append("")
    return "\n".join(lines)


def _comp_talking_points(company: str, role: str, location: str) -> str:
    """Talking points derived from salary.lookup - empty when no data."""
    try:
        from candid import salary
        m = salary.lookup(company=company, title=role, location=location)
    except Exception:
        return ""
    if not (m and (m.get("p25") or m.get("median"))):
        return ""
    n = m.get("n", 0)

    def _f(x):
        return f"${x:,.0f}" if x else "-"

    return "\n".join([
        "**Comp talking points (from market data):**",
        "",
        f"- Market range from {n} data point(s): {_f(m.get('p25'))} (p25) – "
        f"{_f(m.get('p75'))} (p75), median {_f(m.get('median'))}.",
        "- Anchor as a range, not a number: 'based on the market for this role "
        "and level, I am targeting the X–Y band.'",
        "- If their number lands below median, trade structure before walking: "
        "a sign-on or extra equity can bridge the gap without moving the base band.",
        "- Never name your current salary first; let them anchor, then respond "
        "with your researched range.",
        "",
    ])


def build_pack(profile: dict, company: str, role: str, jd: str = "",
               app_id: int | None = None, location: str = "",
               gaps: list[str] | None = None, new_grad: bool = False
               ) -> tuple[str, Path]:
    """Build the prep pack markdown. Returns (markdown, saved_path).

    gaps: optional list of match-gap strings (from
    ``match.score_match(jd)["gaps"]``). Gap-related concept deep-dives and
    mock questions are prioritized when provided.

    new_grad: entry-level mode. Question selection is weighted toward
    fundamentals (DSA, SQL, OOP, OS/networking) with a new-grad behavioral
    set, concept deep-dives prioritize fundamentals over advanced system
    design, and the pack notes the lighter system-design expectations.
    """
    gaps = [str(g) for g in (gaps or []) if str(g).strip()]
    gap_cats = _gap_categories(gaps)

    slug = _find_company(company)
    company_qs = QUESTIONS_DB.get(slug, []) if slug else []
    family = _role_family(profile, role)

    if new_grad:
        generic_qs = select_new_grad_questions()
        _, new_grad_dd, ng_sysdesign_note = new_grad_sections(profile)
    else:
        generic_qs = []
        for bank in GENERIC_BANKS.values():
            generic_qs.extend(bank[:4])
        new_grad_dd, ng_sysdesign_note = [], ""

    categories: list[str] = []
    seen = set()
    for cat in gap_cats:  # gaps first: they steer the mock-question flavors too
        categories.append(cat)
        seen.add(cat)
    for q in company_qs:
        if q["category"] not in seen:
            categories.append(q["category"])
            seen.add(q["category"])
    if not categories:
        categories = (["dsa_fundamentals", "sql_basics", "new_grad_behavioral"]
                      if new_grad else ["ml", "stats", "behavioral"])

    concept_tags: list[str] = []
    for cat in gap_cats:
        concept_tags.extend(PC.CATEGORY_CONCEPTS.get(cat, []))
    for cat in categories:
        concept_tags.extend(PC.CATEGORY_CONCEPTS.get(cat, []))
    concept_tags.extend(PC.ROLE_FAMILY_CONCEPTS.get(family, []))
    concept_tags = list(dict.fromkeys(concept_tags))

    market_line = _market_line(company, role, location)
    talking_points = _comp_talking_points(company, role, location)

    lines = [
        f"# Interview Prep — {role} @ {company}",
        f"*Generated {date.today().isoformat()} · role family: {family.replace('_', ' ')}*",
        "",
    ]
    if new_grad:
        lines += [
            "_Entry-level mode: questions are weighted toward fundamentals "
            "(data structures/algorithms, OOP, SQL, OS/networking) with a "
            "new-grad behavioral set. System-design expectations are lighter "
            "for new grads - see the note in the deep-dives section._",
            "",
        ]
    if gaps:
        lines += [
            "## Priority focus (from your match gaps)",
            "",
            "_These came from matching your profile against the role - the "
            "deep-dives and questions below are ordered to hit them first._",
            "",
        ]
        lines += [f"- {g}" for g in gaps[:8]]
        if gap_cats:
            lines += ["", f"_Targeted topics: {', '.join(c.replace('_', ' ') for c in gap_cats)}._"]
        lines += [""]

    lines += [
        "## 1. Company-specific questions (reported by candidates)",
        "",
    ]
    if company_qs:
        cur_cat = None
        for q in company_qs:
            if q["category"] != cur_cat:
                cur_cat = q["category"]
                lines += [f"### {cur_cat.replace('_', ' ').title()}", ""]
            qline = f"- {q['q']}"
            tags = []
            if q.get("difficulty"):
                tags.append(q["difficulty"])
            if q.get("frequency"):
                tags.append(f"{q['frequency']} frequency")
            if tags:
                qline += f" _[{', '.join(tags)}]_"
            lines.append(qline)
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
    lines += ["", "## 2. General preparation questions", "",
              "_General {family} prep - not verified as asked at this company._".format(
                  family=("entry-level fundamentals" if new_grad
                          else family.replace("_", " "))), ""]
    for i, q in enumerate(generic_qs if new_grad else generic_qs[:12], 1):
        lines.append(f"{i}. {q['q']}")
    lines += ["", "## 3. Concept deep-dives", ""]
    if new_grad:
        lines += ["### Entry-level concept deep-dives (fundamentals first)", "",
                  "_For new-grad loops, fundamentals are graded more than advanced "
                  "system design. Master these before touching distributed systems._", ""]
        for dd in new_grad_dd:
            lines += [dd, ""]
        lines += [ng_sysdesign_note, ""]
        lines += ["### Advanced deep-dives (only if you have time)", ""]
    if gap_cats:
        lines += [f"_Ordered for your gaps first ({', '.join(c.replace('_', ' ') for c in gap_cats)})._", ""]
    for tag in concept_tags[:8]:
        if tag in PC.CONCEPTS:
            lines += [PC.CONCEPTS[tag], ""]
    lines += ["## 4. " + _tailored_mock(profile, role, company, categories).lstrip("# ").rstrip(),
              ""]
    lines += ["## 5. " + _star_prompts(profile, new_grad=new_grad).lstrip("# ").rstrip(), ""]
    lines += ["## 6. Compensation benchmark", "", market_line, ""]
    if talking_points:
        lines += [talking_points]
    lines += ["## 7. " + _research_checklist(company).lstrip("# ").rstrip(), ""]
    lines += ["## 8. " + PC.DAY_BEFORE_CHECKLIST.lstrip("# ").rstrip(), ""]
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
