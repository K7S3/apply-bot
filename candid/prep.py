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
    if "sql" in categories:
        qas.append(("Write SQL to compute a core business metric from raw event tables.",
                    "Narrate as you go; window functions are the usual tool. "
                    "See the SQL deep-dive below."))
    for i, (q, tips) in enumerate(qas, 1):
        lines += [f"**Q{i}. {q}**", "", f"*Talking points:* {tips}", ""]
    lines.append(f"*Tip for {name}: answer out loud and time yourself — 2 minutes per question.*")
    return "\n".join(lines)


def _top_bullets(profile: dict, limit: int = 5) -> list[tuple[str, str, str]]:
    """Strongest resume bullets: most recent experience, numbers first."""
    bullets: list[tuple[str, str, str]] = []
    for e in profile.get("experience", [])[:3]:
        for b in e.get("bullets", [])[:3]:
            text = str(b).strip()
            if text:
                bullets.append((e.get("title", ""), e.get("company", ""), text))
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


def _star_prompts(profile: dict) -> str:
    """Behavioral prompts, each mapped to one of the user's real bullets."""
    lines = [
        "### STAR story prompts (from your resume)",
        "",
        "_Each classic behavioral question is paired with one of your strongest "
        "resume bullets. Draft each answer as Situation → Task → Action → Result, "
        "150+ words, said out loud - never invent details that are not in the bullet._",
        "",
    ]
    top = _top_bullets(profile)
    if not top:
        lines += ["_No resume bullets found - write 3 STAR stories from your "
                  "proudest projects before interview day._", ""]
        return "\n".join(lines)
    for i, (title, company, bullet) in enumerate(top):
        q = _STAR_QUESTION_ROTATION[i % len(_STAR_QUESTION_ROTATION)]
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
               gaps: list[str] | None = None) -> tuple[str, Path]:
    """Build the prep pack markdown. Returns (markdown, saved_path).

    gaps: optional list of match-gap strings (from
    ``match.score_match(jd)["gaps"]``). Gap-related concept deep-dives and
    mock questions are prioritized when provided.
    """
    gaps = [str(g) for g in (gaps or []) if str(g).strip()]
    gap_cats = _gap_categories(gaps)

    slug = _find_company(company)
    company_qs = QUESTIONS_DB.get(slug, []) if slug else []
    family = _role_family(profile, role)

    generic_qs: list[dict] = []
    for bank in GENERIC_BANKS.values():
        generic_qs.extend(bank[:4])

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
        categories = ["ml", "stats", "behavioral"]

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
    if gap_cats:
        lines += [f"_Ordered for your gaps first ({', '.join(c.replace('_', ' ') for c in gap_cats)})._", ""]
    for tag in concept_tags[:8]:
        if tag in PC.CONCEPTS:
            lines += [PC.CONCEPTS[tag], ""]
    lines += ["## 4. " + _tailored_mock(profile, role, company, categories).lstrip("# ").rstrip(),
              ""]
    lines += ["## 5. " + _star_prompts(profile).lstrip("# ").rstrip(), ""]
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

# ---------------------------------------------------------------------------
# Data Scientist track (additive: `python -m candid prep ds <role-title>`)
# ---------------------------------------------------------------------------
# Everything below is new for batch-92. Nothing above this line was changed,
# so the legacy `prep --company X --role Y` path is byte-identical.


def _ds_stats_topics() -> tuple[list[str], str]:
    """Statistics refresher topics, preferring the sibling ds_stats module.

    Returns (topics, source_label). The sibling module may not exist in
    every checkout (parallel batches), so the import is defensive: any
    failure falls back to the built-in pointer list. The sibling exposes
    topics either as a module-level list or as a no-arg ``topics()``
    function; both shapes are handled.
    """
    try:
        from candid import ds_stats  # type: ignore
    except Exception:
        return list(_DS_STATS_FALLBACK), "built-in refresher pointers"
    for attr in ("STATS_TOPICS", "TOPICS", "DS_STATS_TOPICS", "topics"):
        candidate = getattr(ds_stats, attr, None)
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:
                continue
        if candidate:
            try:
                titles = [_ds_topic_title(t) for t in candidate]
            except TypeError:
                continue
            if titles:
                return titles, f"candid/ds_stats.py:{attr}"
    return list(_DS_STATS_FALLBACK), "built-in refresher pointers"


def _ds_topic_title(topic) -> str:
    """Normalize a ds_stats topic entry (str, dict, or tuple) to a title."""
    if isinstance(topic, str):
        return topic
    if isinstance(topic, dict):
        for key in ("title", "name", "topic", "label"):
            if topic.get(key):
                return str(topic[key])
        return str(topic)
    if isinstance(topic, (list, tuple)) and topic:
        return str(topic[0])
    return str(topic)


_DS_STATS_FALLBACK: tuple[str, ...] = (
    "Hypothesis testing: null/alternative, p-values, Type I vs Type II errors",
    "Confidence intervals: what they mean, and what they don't",
    "A/B test design: randomization unit, sample size, power, MDE",
    "Multiple testing: Bonferroni, FDR, and when peeking invalidates results",
    "Bayesian basics: priors, posteriors, and when Bayes beats frequentism",
    "Regression: OLS assumptions, regularization, interpreting coefficients",
    "Causal inference: confounding, diff-in-diff, propensity scores, DAGs",
    "Probability distributions: when to reach for binomial/Poisson/normal",
    "Simpson's paradox and aggregation pitfalls in metrics",
    "Bootstrapping: quick uncertainty estimates without closed forms",
)

_DS_ML_CASES: tuple[tuple[str, str], ...] = (
    ("Churn / retention prediction",
     "Framing: classification vs survival; features from event history; "
     "evaluation by lift in the top decile, not just AUC."),
    ("Fraud / anomaly detection",
     "Framing: extreme class imbalance; precision-recall tradeoffs; "
     "human-in-the-loop review economics."),
    ("Recommendation",
     "Framing: candidate generation vs ranking; offline metrics (NDCG) vs "
     "online A/B; cold start and popularity bias."),
    ("Demand / revenue forecasting",
     "Framing: horizon and granularity; backtesting discipline; "
     "how forecast error flows into inventory or staffing decisions."),
    ("Pricing / elasticity",
     "Framing: causal estimate from experiments or quasi-experiments; "
     "from elasticity to the revenue-optimal price."),
    ("Customer segmentation",
     "Framing: clustering for action (who gets which treatment); "
     "stability of segments over time; connecting segments to P&L."),
)

_DS_SQL_DRILLS: tuple[tuple[str, str], ...] = (
    ("Window functions",
     "ROW_NUMBER/RANK for dedup, LAG/LEAD for period-over-period, running "
     "totals with SUM() OVER (... ROWS BETWEEN)."),
    ("Joins and fan-out traps",
     "One-to-many joins inflating aggregates; pre-aggregate before joining; "
     "LEFT vs INNER and what each implies about the question."),
    ("Cohort retention",
     "First-event per user, cohort month bucketing, retention matrix via "
     "conditional aggregation."),
    ("Funnel analysis",
     "Event-sequence funnels with conditional counts; conversion between "
     "steps; drop-off attribution."),
    ("Sessionization",
     "Grouping events into sessions with timestamp gaps; session-level "
     "metrics from raw event tables."),
    ("Date spines and gaps",
     "Generating a calendar spine, LEFT JOINing sparse facts, COALESCE "
     "for missing periods."),
)


def _ds_sql_drills() -> tuple[list[tuple[str, str]], str]:
    """SQL drill pointers, preferring the sibling ds_sql question bank.

    Returns (drills, source_label); defensive like _ds_stats_topics.
    """
    try:
        from candid import ds_sql  # type: ignore
        questions = ds_sql.list_questions()
    except Exception:
        return list(_DS_SQL_DRILLS), "built-in drill pointers"
    by_topic: dict[str, int] = {}
    for q in questions or []:
        topic = str(q.get("topic") or "general")
        by_topic[topic] = by_topic.get(topic, 0) + 1
    if not by_topic:
        return list(_DS_SQL_DRILLS), "built-in drill pointers"
    drills = [
        (topic.replace("_", " ").title(),
         f"{n} drill(s) in the sibling question bank (`candid/ds_sql.py`) — "
         "work them against a scratch database until the syntax is muscle memory.")
        for topic, n in sorted(by_topic.items())
    ]
    return drills, "candid/ds_sql.py question bank"


def _ds_company_questions(company: str) -> str:
    """Company-question section via prep's existing sourced-question mechanism."""
    slug = _find_company(company)
    company_qs = QUESTIONS_DB.get(slug, []) if slug else []
    lines = ["### Company-reported questions", ""]
    if company_qs:
        cur_cat = None
        for q in company_qs[:15]:
            if q["category"] != cur_cat:
                cur_cat = q["category"]
                lines += [f"**{cur_cat.replace('_', ' ').title()}**", ""]
            lines.append(f"- {q['q']}")
            reported = f" (reported {q['reported']})" if q.get("reported") else ""
            lines.append(f"  ↳ *Source: {q['source']}{reported}*")
        lines += ["",
                  "_Questions candidates publicly reported for this company — "
                  "representative of style and topics, not a leaked list._"]
    else:
        lines.append(
            "> **No verified company-specific questions found.** The drills "
            "below are general Data Scientist preparation, not verified as "
            "asked at this company. Add reported questions to "
            "`candid/prep_questions.py` (see `docs/adding_questions.md`) so "
            "future packs include them."
        )
    return "\n".join(lines)


def build_ds_pack(profile: dict, role: str, company: str = "", jd: str = "",
                  app_id: int | None = None, location: str = "") -> tuple[str, Path]:
    """Build a Data Scientist interview prep pack.

    Sections: statistics refresher pointers (from sibling ``candid/ds_stats``
    when available, else built-in pointers), ML case list, SQL drills, and a
    company-question section using prep's existing sourced-question mechanism.
    Written to the same output location/format as ``build_pack``.
    """
    topics, topics_source = _ds_stats_topics()
    sql_drills, sql_source = _ds_sql_drills()
    market_line = _market_line(company, role, location)
    talking_points = _comp_talking_points(company, role, location)

    lines = [
        f"# DS Interview Prep — {role}" + (f" @ {company}" if company else ""),
        f"*Generated {date.today().isoformat()} · Data Scientist track*",
        "",
        "## 1. Statistics refresher",
        "",
        f"_Topic pointers ({topics_source}). Work each until you can explain "
        "it on a whiteboard in 3 minutes._",
        "",
    ]
    lines += [f"- [ ] {t}" for t in topics]
    lines += [
        "",
        "## 2. ML case list",
        "",
        "_Classic DS interview cases. For each, practice: problem framing → "
        "metric choice → model choice → evaluation → business decision._",
        "",
    ]
    for title, pointer in _DS_ML_CASES:
        lines += [f"### {title}", "", pointer, ""]
    lines += [
        "## 3. SQL drills",
        "",
        f"_Drill pointers ({sql_source}). Narrate your reasoning out loud as "
        "you write._",
        "",
    ]
    for title, pointer in sql_drills:
        lines += [f"### {title}", "", pointer, ""]
    lines += [
        "## 4. " + _ds_company_questions(company or "").lstrip("# ").rstrip(),
        "",
        "## 5. STAR story prompts (from your resume)",
        "",
    ]
    lines.append(_star_prompts(profile).split("\n", 2)[-1])
    lines += ["", "## 6. Compensation benchmark", "", market_line, ""]
    if talking_points:
        lines += [talking_points]
    lines += ["## 7. " + _research_checklist(company or "the company").lstrip("# ").rstrip(), ""]
    lines += ["## 8. " + PC.DAY_BEFORE_CHECKLIST.lstrip("# ").rstrip(), ""]
    lines.append("---")
    lines.append(
        "_Statistics topics: `candid/ds_stats.py` when present, else built-in "
        "pointers. Company questions are never fabricated — see "
        "`candid/prep_questions.py`._"
    )

    markdown = "\n".join(lines)
    C.ensure_data_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"ds-{company}-{role}")[:60]
    out = C.PREP_PACKS_DIR / f"{date.today().isoformat()}_{safe}.md"
    out.write_text(markdown, encoding="utf-8")

    if app_id is not None:
        try:
            T.update(app_id, prep_pack=str(out))
        except T.TrackerError:
            pass
    return markdown, out
