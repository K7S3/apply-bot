"""Career-pivot reframing: reframe your experience for adjacent roles/titles.

GOLDEN RULE (groundedness is non-negotiable): reframing changes ANGLE, never
FACTS. Every summary sentence, bullet, company, title, date, and metric in
the output comes verbatim from the input profile - nothing is invented.
``credibility_gaps`` states plainly what the target role usually needs that
the profile lacks, phrased as "you'd need to address X". This module must
never imply you are qualified for something the profile doesn't support.

How to extend ADJACENCY:
  1. Add a source key: your current title, normalized to lowercase
     (e.g. "backend engineer"). Matching is fuzzy - if no source key
     matches exactly, the key with the best word overlap against your
     titles/headline wins; if nothing overlaps, every target is ranked
     purely by skill overlap.
  2. Each target is a dict with:
       "title":  the adjacent title (display string),
       "skills": canonical skill names from config.SKILL_LEXICON only -
                 overlap scoring, gap detection, and foregrounding all run
                 on these, so a typo here silently breaks scoring,
       "why":    one sentence on why the pivot is plausible.
"""

from __future__ import annotations

import re

from candid import config as C


class PivotError(Exception):
    """Raised when a pivot request is invalid (empty target title, etc.)."""


# ---------------------------------------------------------------------------
# adjacency map: current title -> plausible pivot targets
# ---------------------------------------------------------------------------

ADJACENCY: dict[str, list[dict]] = {
    "backend engineer": [
        {"title": "platform engineer",
         "skills": ["python", "cloud", "mlops", "sql"],
         "why": "Platform teams are backend work pointed inward: same services, "
                "APIs, and reliability chops, aimed at other engineers."},
        {"title": "devops engineer",
         "skills": ["mlops", "cloud", "python", "sql"],
         "why": "Backend engineers already live in CI/CD, containers, and "
                "cloud infra; the pivot is depth, not a new discipline."},
        {"title": "solutions architect",
         "skills": ["cloud", "python", "sql", "product analytics"],
         "why": "Your systems knowledge transfers to designing solutions for "
                "customers; the new muscle is communication, not code."},
    ],
    "software engineer": [
        {"title": "backend engineer",
         "skills": ["python", "sql", "cloud", "mlops"],
         "why": "A natural specialization: server-side systems, APIs, and "
                "data stores."},
        {"title": "machine learning engineer",
         "skills": ["machine learning", "python", "mlops", "sql"],
         "why": "SWE fundamentals plus modeling; many ML eng roles are "
                "mostly engineering."},
        {"title": "full stack engineer",
         "skills": ["javascript", "python", "sql", "cloud"],
         "why": "You own the server side; adding the UI layer completes "
                "the loop."},
    ],
    "machine learning engineer": [
        {"title": "applied scientist",
         "skills": ["machine learning", "deep learning", "statistics", "python"],
         "why": "Same modeling core with more research flavor; your shipped "
                "models are the proof."},
        {"title": "mlops engineer",
         "skills": ["mlops", "cloud", "python", "machine learning"],
         "why": "You already train and ship models; this doubles down on "
                "the deployment half."},
        {"title": "backend engineer",
         "skills": ["python", "sql", "cloud", "mlops"],
         "why": "ML eng is backend eng with models; the serving and "
                "data-layer work is identical."},
    ],
    "data scientist": [
        {"title": "machine learning engineer",
         "skills": ["machine learning", "python", "mlops", "sql"],
         "why": "Productionizing the models you already build; the gap is "
                "engineering rigor, not math."},
        {"title": "product analyst",
         "skills": ["sql", "product analytics", "statistics",
                    "data visualization"],
         "why": "Your experimentation and metrics work is already product "
                "analytics; this names it."},
        {"title": "data engineer",
         "skills": ["spark", "sql", "python", "cloud"],
         "why": "You know what good data looks like; this pivot builds the "
                "pipelines that produce it."},
    ],
    "data analyst": [
        {"title": "data scientist",
         "skills": ["machine learning", "statistics", "python", "sql"],
         "why": "The classic ladder: your SQL/stats base plus modeling."},
        {"title": "analytics engineer",
         "skills": ["sql", "dbt", "python", "data visualization"],
         "why": "dbt turned analytics into engineering; your modeling "
                "skills transfer almost 1:1."},
        {"title": "product analyst",
         "skills": ["sql", "product analytics", "statistics",
                    "data visualization"],
         "why": "Same toolkit pointed at product decisions instead of "
                "reporting."},
    ],
    "data engineer": [
        {"title": "analytics engineer",
         "skills": ["sql", "dbt", "python", "data visualization"],
         "why": "A narrower, more business-facing slice of the same "
                "pipeline work."},
        {"title": "mlops engineer",
         "skills": ["mlops", "cloud", "python", "machine learning"],
         "why": "Pipelines for models instead of dashboards; orchestration "
                "skills carry over."},
        {"title": "platform engineer",
         "skills": ["python", "cloud", "mlops", "sql"],
         "why": "Data platforms are platforms; your infra instincts apply "
                "directly."},
    ],
    "frontend engineer": [
        {"title": "full stack engineer",
         "skills": ["javascript", "python", "sql", "cloud"],
         "why": "You own the UI; adding the API and data layer completes "
                "the loop."},
        {"title": "backend engineer",
         "skills": ["python", "sql", "cloud", "javascript"],
         "why": "UI engineers who learn the server side become the most "
                "versatile hires on a team."},
        {"title": "solutions architect",
         "skills": ["cloud", "javascript", "sql", "product analytics"],
         "why": "Customer-facing technical depth built on your product "
                "surface experience."},
    ],
    "product manager": [
        {"title": "product analyst",
         "skills": ["sql", "product analytics", "statistics",
                    "data visualization"],
         "why": "You already make metric-driven calls; this adds the "
                "technical depth to prove them."},
        {"title": "solutions architect",
         "skills": ["cloud", "python", "sql", "product analytics"],
         "why": "Customer-facing technical depth built on your product "
                "judgment."},
        {"title": "data analyst",
         "skills": ["sql", "data visualization", "statistics", "excel"],
         "why": "A reset toward hands-on analysis; your stakeholder sense "
                "is the edge."},
    ],
}

# flattened: normalized target title -> target dict (first "why" wins)
def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


_TARGET_INDEX: dict[str, dict] = {}
for _targets in ADJACENCY.values():
    for _t in _targets:
        _TARGET_INDEX.setdefault(_norm_key(_t["title"]), _t)


def _title_words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+/#]+", (s or "").lower()))


# ---------------------------------------------------------------------------
# helpers: matching + grounded skill text scanning
# ---------------------------------------------------------------------------

def _best_source(profile: dict) -> str | None:
    """Find the ADJACENCY source key closest to the profile's titles."""
    titles = [e.get("title", "") for e in profile.get("experience", [])]
    titles.append(profile.get("headline", ""))
    words: set[str] = set()
    for t in titles:
        words |= _title_words(t)
    if not words:
        return None
    best: str | None = None
    best_score = 0.0
    for key in ADJACENCY:
        kw = _title_words(key)
        if not kw:
            continue
        score = len(kw & words) / len(kw)
        if score > best_score:
            best, best_score = key, score
    # require at least half the key's words to match (e.g. "data" alone
    # must not match "data scientist")
    return best if best_score >= 0.5 else None


def _skills_in_text(text: str, vocabulary: set[str]) -> list[str]:
    """Canonical skills from ``vocabulary`` mentioned in ``text`` (in order)."""
    low = (text or "").lower()
    return [s for s in vocabulary
            if any(C.skill_regex(a).search(low)
                   for a in C.SKILL_LEXICON.get(s, [s]))]


def _target_requirements(target_title: str) -> dict:
    """Resolve what a target title usually needs.

    Known targets come from ADJACENCY. Unknown titles fall back to mining
    the title itself for lexicon skills; if that finds nothing, the
    requirement is an honest free-form "domain experience in X" so gaps
    are never empty and never invented.
    """
    norm = _norm_key(target_title)
    if not norm:
        raise PivotError("Target title is empty - pass e.g. 'platform engineer'.")
    hit = _TARGET_INDEX.get(norm)
    if hit:
        return {"title": hit["title"], "skills": list(hit["skills"]),
                "why": hit.get("why", ""), "freeform": [], "known": True}
    found = _skills_in_text(target_title, set(C.SKILL_LEXICON))
    freeform = [] if found else [f"domain experience in {target_title.strip()}"]
    return {"title": target_title.strip(), "skills": found, "why": "",
            "freeform": freeform, "known": False}


def _seniority_rank(label: str) -> int:
    return {"entry": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4,
            "staff": 5, "principal": 6}.get((label or "").lower(), 2)


def _target_seniority_rank(target_title: str) -> int | None:
    best: int | None = None
    for kw, rank in C.SENIORITY_KEYWORDS.items():
        if kw in target_title.lower():
            best = rank if best is None else max(best, rank)
    return best


# one-line context for why a target role usually needs a missing skill
_GAP_CONTEXT: dict[str, str] = {
    "python": "these roles write Python day to day",
    "sql": "these roles query data directly and regularly",
    "machine learning": "modeling is the core of the role, not a side skill",
    "deep learning": "these roles train or fine-tune neural models",
    "statistics": "these roles are expected to reason about uncertainty "
                  "and experiments",
    "data visualization": "these roles communicate through dashboards and "
                          "charts stakeholders actually read",
    "product analytics": "these roles live in funnels, KPIs, and metric "
                         "deep-dives",
    "dbt": "these teams build their pipelines in dbt",
    "spark": "these roles process data at a scale pandas can't handle",
    "mlops": "these roles own the deploy/monitor loop, not just the model",
    "cloud": "these roles ship on cloud infra, not laptops",
    "nlp": "these roles work with text data and language models",
    "llm": "these roles build on top of large language models",
    "scikit-learn": "these roles prototype models in sklearn",
    "xgboost": "tabular modeling here usually means gradient boosting",
    "pandas": "these roles manipulate dataframes daily",
    "time series": "these roles forecast; trend and seasonality are table "
                   "stakes",
    "recommendations": "these roles build ranking/personalization systems",
    "optimization": "these roles frame problems as constrained optimization",
    "javascript": "these roles ship UI code",
    "excel": "these roles still run on spreadsheets for quick analysis",
    "r": "these teams do their stats work in R",
    "finance": "these roles need the domain vocabulary (valuation, risk)",
    "java": "these codebases are JVM shops",
    "c++": "these roles are performance-critical systems work",
}


def _gap_line(skill: str, target_title: str) -> str:
    ctx = _GAP_CONTEXT.get(
        skill,
        f"{target_title}s are typically expected to have hands-on "
        f"{skill} experience",
    )
    return (f"you'd need to address {skill}: {ctx}; this profile shows "
            f"none - plan a project or short course to close it.")


# ---------------------------------------------------------------------------
# suggest_pivots
# ---------------------------------------------------------------------------

def suggest_pivots(profile: dict, n: int = 5) -> list[dict]:
    """Rank adjacent titles by transferable-skill overlap with the profile.

    Each suggestion: target title, overlap %, transferable skills (all in
    the profile), honestly-flagged gaps (none in the profile), and why the
    pivot is plausible.
    """
    pskills = list(profile.get("skills", []))
    pset = set(pskills)
    source = _best_source(profile)
    if source is not None:
        candidates = list(ADJACENCY[source])
    else:  # unknown current title: rank every known target by overlap
        seen: set[str] = set()
        candidates = []
        for targets in ADJACENCY.values():
            for t in targets:
                k = _norm_key(t["title"])
                if k not in seen:
                    seen.add(k)
                    candidates.append(t)

    suggestions = []
    for t in candidates:
        tskills = list(t["skills"])
        transferable = [s for s in tskills if s in pset]
        gaps = [s for s in tskills if s not in pset]
        overlap = round(100 * len(transferable) / len(tskills), 1) if tskills else 0.0
        suggestions.append({
            "target": t["title"],
            "overlap_pct": overlap,
            "transferable": transferable,
            "gaps": gaps,
            "why": t.get("why", ""),
        })
    suggestions.sort(key=lambda s: (-s["overlap_pct"], -len(s["transferable"]),
                                    s["target"]))
    return suggestions[: max(1, n)]


# ---------------------------------------------------------------------------
# reframe
# ---------------------------------------------------------------------------

def _reframed_summary(profile: dict, reqs: dict, foreground: list[str]) -> str:
    """2-3 sentence positioning. Facts only: name, years, titles, companies,
    profile skills. Never invents metrics, skills, or experience."""
    who = (profile.get("name") or "").strip() or "You"
    years = profile.get("years_experience") or 0
    exp = profile.get("experience", [])
    titles = [e.get("title", "") for e in exp if e.get("title")]
    companies = [e.get("company", "") for e in exp if e.get("company")]
    target = reqs["title"]

    if titles and companies:
        s1 = (f"{who} brings {years:g} years as "
              f"{', '.join(titles[:2])} at {', '.join(companies[:2])}.")
    elif titles:
        s1 = f"{who} brings {years:g} years as {', '.join(titles[:2])}."
    else:
        s1 = (f"{who} has no dated experience entries in the profile yet - "
              f"add them before reframing.")

    lead = foreground if foreground else list(profile.get("skills", []))[:3]
    s2 = (f"Established strengths to lead with: {', '.join(lead)}."
          if lead else "No extracted skills to foreground yet.")

    if foreground:
        s3 = (f"For a {target} move, the transferable angle is your "
              f"{', '.join(foreground)} applied to {target}-adjacent problems.")
    else:
        s3 = (f"For a {target} move, the honest read is that none of the "
              f"role's core skills appear in this profile yet - see the "
              f"credibility gaps below.")
    return " ".join([s1, s2, s3])


def _reframe_role(entry: dict, reqs: dict, pset: set[str]) -> dict:
    """Reorder one role's bullets by transferable relevance.

    Bullets are kept VERBATIM - reordering and the angle note are the only
    changes. Facts never change.
    """
    text = f"{entry.get('title', '')} {' '.join(entry.get('bullets', []))}"
    entry_skills = _skills_in_text(text, pset)
    tskills = set(reqs["skills"])
    transferable = [s for s in entry_skills if s in tskills]

    def _bullet_score(b: str) -> int:
        return len(_skills_in_text(b, tskills))

    bullets = list(entry.get("bullets", []))
    bullets.sort(key=_bullet_score, reverse=True)  # stable: ties keep order

    if transferable:
        angle = (f"Emphasize your {', '.join(transferable)} here - that is "
                 f"the {reqs['title']} half of this role. Lead interviews "
                 f"with these bullets first.")
    else:
        angle = ("No direct skill overlap in this role - frame it as "
                 "adjacent execution experience, not core qualification.")
    return {
        "title": entry.get("title", ""),
        "company": entry.get("company", ""),
        "dates": entry.get("dates", ""),
        "bullets": bullets,  # verbatim, reordered
        "angle": angle,
        "transferable_skills": transferable,
    }


def reframe(profile: dict, target_title: str) -> dict:
    """Reframe the profile toward ``target_title``.

    Returns reframed summary angle, per-role bullet rewrites (verbatim
    bullets, reordered + angle notes), skills to foreground, and
    credibility_gaps - explicit "you'd need to address X" lines for what
    the target role usually needs that the profile lacks.
    """
    reqs = _target_requirements(target_title)
    pskills = list(profile.get("skills", []))
    pset = set(pskills)
    tskills = list(reqs["skills"])

    foreground = [s for s in tskills if s in pset]
    gap_skills = [s for s in tskills if s not in pset]
    gaps = [_gap_line(s, reqs["title"]) for s in gap_skills]
    for ff in reqs["freeform"]:
        gaps.append(
            f"you'd need to address {ff}: {reqs['title']} is outside this "
            f"profile's domain - expect to build credibility from scratch "
            f"(training, projects, or adjacent experience)."
        )

    # seniority stretch, stated plainly
    want = _target_seniority_rank(reqs["title"])
    have = _seniority_rank(profile.get("seniority", ""))
    if want is not None and want > have + 1:
        gaps.append(
            f"you'd need to address the seniority bar: '{reqs['title']}' "
            f"reads as a higher level than this profile's "
            f"'{profile.get('seniority', '?')}' - expect scope and "
            f"leadership questions."
        )

    roles = [_reframe_role(e, reqs, pset)
             for e in profile.get("experience", [])]

    overlap = (len(foreground) / len(tskills)) if tskills else 0.0
    if not reqs["known"]:
        read = (f"Far pivot - '{reqs['title']}' is not a known adjacent "
                f"title, so treat every requirement as unproven.")
    elif overlap >= 0.6:
        read = "Near pivot"
    elif overlap >= 0.3:
        read = "Stretch pivot"
    else:
        read = "Far pivot"
    honest_read = (f"{read}: {len(foreground)} of {len(tskills)} core "
                   f"{reqs['title']} skills are already in your profile.")

    return {
        "target_title": reqs["title"],
        "source_title": _best_source(profile) or "",
        "reframed_summary": _reframed_summary(profile, reqs, foreground),
        "roles": roles,
        "skills_to_foreground": foreground,
        "credibility_gaps": gaps,
        "gap_skills": gap_skills + list(reqs["freeform"]),
        "honest_read": honest_read,
    }


# ---------------------------------------------------------------------------
# pivot_plan: 30/60/90 from the credibility gaps
# ---------------------------------------------------------------------------

# skill -> (30-day action, 60-day action, 90-day action); every outcome is a
# concrete, checkable deliverable.
_SKILL_PLAN: dict[str, tuple[tuple[str, str], tuple[str, str], tuple[str, str]]] = {
    "python": (
        ("Solve 30 Python problems (HackerRank mediums or the free CS50P problem sets).",
         "Deliverable: 30 solved problems logged with dates."),
        ("Ship a 300-line automation or API in Python that solves a real problem in your current work.",
         "Deliverable: merged PR or GitHub repo with a README."),
        ("Refactor the project for packaging and tests, then publish it.",
         "Deliverable: public repo with tests passing in CI."),
    ),
    "sql": (
        ("Finish SQLBolt plus the Mode SQL advanced track (window functions, CTEs).",
         "Deliverable: completed track certificate or screenshot."),
        ("Answer 5 real business questions with SQL against a public dataset (e.g. BigQuery public data).",
         "Deliverable: query file plus a results write-up."),
        ("Optimize 3 slow queries using EXPLAIN and document the plan changes.",
         "Deliverable: before/after timing document."),
    ),
    "machine learning": (
        ("Complete one sklearn pipeline tutorial track (e.g. Kaggle Learn machine learning).",
         "Deliverable: finished notebooks, all cells run."),
        ("Build an end-to-end model on a real dataset: train/test split, cross-validation, error analysis.",
         "Deliverable: repo with an evaluation report."),
        ("Enter one Kaggle competition or replicate a paper's baseline.",
         "Deliverable: leaderboard score or replication write-up."),
    ),
    "deep learning": (
        ("Work through fast.ai lessons 1-5 or the PyTorch 60-minute blitz.",
         "Deliverable: completed notebooks, all cells run."),
        ("Train a CNN or Transformer baseline on a standard dataset.",
         "Deliverable: training curves and a model checkpoint in a repo."),
        ("Fine-tune a pretrained model for a new task and write up the results.",
         "Deliverable: published write-up with metrics."),
    ),
    "statistics": (
        ("Work through a hypothesis-testing refresher (Khan Academy or StatQuest).",
         "Deliverable: notes plus 10 practice problems solved."),
        ("Design and analyze an A/B test on synthetic data end to end.",
         "Deliverable: write-up with power analysis and a conclusion."),
        ("Present the analysis to a peer group or post it publicly.",
         "Deliverable: published post or recorded walkthrough."),
    ),
    "data visualization": (
        ("Rebuild one of your existing analyses as a polished dashboard in the target tool.",
         "Deliverable: shareable dashboard link."),
        ("Design a KPI dashboard for a fictional product with 3 stakeholder personas.",
         "Deliverable: dashboard plus a 1-page stakeholder guide."),
        ("Get the dashboard critiqued by 3 analysts and iterate on it.",
         "Deliverable: critique notes plus a v2 link."),
    ),
    "product analytics": (
        ("Write a metrics teardown of a product you use: funnel, retention, 3 KPIs.",
         "Deliverable: 2-page teardown document."),
        ("Run a full funnel and cohort analysis on a public dataset (e.g. Olist).",
         "Deliverable: analysis notebook with recommendations."),
        ("Present the findings to a product-minded peer group.",
         "Deliverable: slide deck plus recorded feedback."),
    ),
    "dbt": (
        ("Finish dbt Fundamentals (free) and build models over the Jaffle Shop project.",
         "Deliverable: completed course plus a working dbt project."),
        ("Port one of your SQL pipelines into dbt with tests and docs.",
         "Deliverable: dbt repo with `dbt test` passing."),
        ("Add CI and a documentation site for the project.",
         "Deliverable: docs site link plus a green CI run."),
    ),
    "spark": (
        ("On Databricks Community Edition, complete the Spark quickstart.",
         "Deliverable: notebooks running on a real cluster."),
        ("Rewrite a pandas pipeline in PySpark on a 1GB+ dataset and benchmark it.",
         "Deliverable: benchmark comparison write-up."),
        ("Implement one streaming or partitioned-ETL job.",
         "Deliverable: repo with the job and run logs."),
    ),
    "mlops": (
        ("Dockerize an existing model: Dockerfile plus requirements, runnable with one command.",
         "Deliverable: repo where `docker build` and `docker run` both work."),
        ("Add CI (GitHub Actions) that trains, evaluates, and blocks on metric regression.",
         "Deliverable: green CI badge plus a passing pipeline run."),
        ("Deploy the model behind a simple API with request logging and a Grafana dashboard.",
         "Deliverable: live endpoint URL plus a dashboard screenshot."),
    ),
    "cloud": (
        ("Finish the free AWS Skill Builder Solutions Architect learning plan.",
         "Deliverable: 80%+ on the official practice exam."),
        ("Re-deploy a personal project to AWS (EC2/ECS plus RDS plus S3).",
         "Deliverable: live URL plus an architecture diagram in the README."),
        ("Write a public post-mortem of one cost or scaling incident you handled.",
         "Deliverable: published post with at least 5 peer comments."),
    ),
    "nlp": (
        ("Work through Hugging Face NLP course chapters 1-4.",
         "Deliverable: completed notebooks, all cells run."),
        ("Fine-tune a transformer on a classification task with proper evaluation.",
         "Deliverable: model plus an evaluation report."),
        ("Ship a small text-feature demo (search or classifier API).",
         "Deliverable: live demo URL plus a write-up."),
    ),
    "llm": (
        ("Build a RAG prototype over your own documents (LangChain plus a small model).",
         "Deliverable: working chat demo answering 10 test questions."),
        ("Add evals: a 50-question golden set with pass-rate tracking.",
         "Deliverable: eval harness plus a baseline score."),
        ("Write up the failure modes you hit and how you mitigated them.",
         "Deliverable: published post."),
    ),
    "scikit-learn": (
        ("Work the sklearn user guide chapters on pipelines and model selection, with exercises.",
         "Deliverable: exercise notebook, all cells run."),
        ("Build a reusable sklearn Pipeline (preprocessing plus model plus calibration).",
         "Deliverable: importable module with tests."),
        ("Contribute a docs fix or example to scikit-learn.",
         "Deliverable: merged PR link or a published example."),
    ),
    "xgboost": (
        ("Finish Kaggle Learn 'Intro to Machine Learning' plus one XGBoost notebook.",
         "Deliverable: completed notebook, all cells run."),
        ("Make a serious attempt at a tabular playground competition.",
         "Deliverable: leaderboard rank plus a tuning write-up."),
        ("Document your gradient-boosting tuning playbook.",
         "Deliverable: 1-page playbook document."),
    ),
    "pandas": (
        ("Do 10 pandas exercises on messy real data (e.g. tidytuesday).",
         "Deliverable: cleaned dataset plus a notebook."),
        ("Build a small data-QA utility: schema checks and anomaly flags.",
         "Deliverable: tested utility repo."),
        ("Benchmark pandas vs polars on your workload and publish the results.",
         "Deliverable: benchmark post."),
    ),
    "time series": (
        ("Work Forecasting: Principles and Practice chapters 1-8, with exercises.",
         "Deliverable: exercise notebook, all cells run."),
        ("Build a forecasting model (Prophet or statsmodels) on a real series with backtesting.",
         "Deliverable: backtest report with error metrics."),
        ("Deploy the forecast as a scheduled job with drift monitoring.",
         "Deliverable: scheduled run plus an alert on drift."),
    ),
    "recommendations": (
        ("Build collaborative filtering on MovieLens (surprise or implicit).",
         "Deliverable: offline evaluation metrics."),
        ("Add a ranking stage and evaluate with NDCG.",
         "Deliverable: evaluation report."),
        ("Write up the system design for a production recommender.",
         "Deliverable: design document."),
    ),
    "optimization": (
        ("Solve 10 linear-programming problems with PuLP.",
         "Deliverable: solved problem set."),
        ("Model a real resource-allocation problem (e.g. scheduling) and solve it.",
         "Deliverable: model plus a solution write-up."),
        ("Compare solver performance and document the trade-offs.",
         "Deliverable: comparison document."),
    ),
    "javascript": (
        ("Work JavaScript.info parts 1-2 and build a to-do app in vanilla JS.",
         "Deliverable: working app."),
        ("Rebuild it in React with hooks and a router.",
         "Deliverable: deployed React app URL."),
        ("Add tests (Vitest) and an accessibility pass.",
         "Deliverable: CI-green repo."),
    ),
    "excel": (
        ("Spend an afternoon on pivot tables, XLOOKUP, and Power Query with a sample workbook.",
         "Deliverable: completed workbook."),
        ("Rebuild a recurring report you own as a parameterized Excel model.",
         "Deliverable: model file actually in use."),
        ("Document the model so a teammate can run it without you.",
         "Deliverable: 1-page runbook."),
    ),
    "r": (
        ("Work R for Data Science chapters on dplyr and ggplot2.",
         "Deliverable: exercise scripts, all run."),
        ("Port one Python analysis to R/tidyverse.",
         "Deliverable: side-by-side comparison."),
        ("Build an R Markdown report end to end.",
         "Deliverable: rendered report."),
    ),
    "finance": (
        ("Watch an intro corporate-finance lecture series (e.g. Damodaran lectures 1-6).",
         "Deliverable: notes plus a vocabulary list."),
        ("Build a DCF valuation model for a public company.",
         "Deliverable: working model spreadsheet."),
        ("Write a 2-page investment-style memo defending a thesis.",
         "Deliverable: memo document."),
    ),
    "java": (
        ("Java refresher: collections, streams, and concurrency basics.",
         "Deliverable: 15 solved exercises."),
        ("Build a small Spring Boot REST service with tests.",
         "Deliverable: tested repo."),
        ("Deploy it with Docker and document the API.",
         "Deliverable: live service plus OpenAPI docs."),
    ),
    "c++": (
        ("Work learncpp.com chapters on memory management and the STL.",
         "Deliverable: completed exercise set."),
        ("Implement a data structure from scratch with benchmarks.",
         "Deliverable: benchmark results."),
        ("Profile and optimize it, then write up the findings.",
         "Deliverable: optimization write-up."),
    ),
}


def _generic_skill_plan(skill: str) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    return (
        (f"Complete a short, named course in {skill} - pick one with a certificate.",
         "Deliverable: certificate or completion screenshot."),
        (f"Build a small end-to-end project that uses {skill}.",
         "Deliverable: repo with a README explaining what you built."),
        (f"Get the project reviewed by 2 practitioners and publish a write-up.",
         "Deliverable: review notes plus a published post."),
    )


def pivot_plan(profile: dict, target_title: str) -> dict:
    """30/60/90-day pivot plan derived from the credibility gaps.

    Every step is actionable and has a verifiable outcome ("Deliverable: ...").
    No vague "learn leadership" - each step names the work and the proof.
    """
    r = reframe(profile, target_title)
    target = r["target_title"]
    steps: list[dict] = []

    for skill in r["gap_skills"]:
        tmpl = _SKILL_PLAN.get(skill, _generic_skill_plan(skill))
        for phase, (action, outcome) in zip(("30", "60", "90"), tmpl):
            steps.append({"phase": phase, "action": action,
                          "outcome": outcome, "addresses": skill})

    # structural steps: positioning, proof, network
    steps.append({
        "phase": "30",
        "action": (f"Rewrite your resume toward {target}: new 2-line pivot "
                   f"summary, bullets reordered per the reframe output."),
        "outcome": "Deliverable: updated one-page resume saved as PDF.",
        "addresses": "positioning",
    })
    steps.append({
        "phase": "60",
        "action": (f"Publish one proof-of-work artifact aimed at {target} "
                   f"hiring managers (repo, post, or dashboard)."),
        "outcome": "Deliverable: public link you can put on your resume.",
        "addresses": "proof of work",
    })
    steps.append({
        "phase": "90",
        "action": (f"Book 5 informational interviews with people holding the "
                   f"{target} title; ask what got them hired."),
        "outcome": ("Deliverable: 5 call notes in one document, with 3 named "
                    "follow-ups."),
        "addresses": "networking",
    })

    phase_order = {"30": 0, "60": 1, "90": 2}
    steps.sort(key=lambda s: (phase_order[s["phase"]], s["addresses"]))
    return {
        "target_title": target,
        "honest_read": r["honest_read"],
        "gaps": r["credibility_gaps"],
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# pivot_brief: markdown export
# ---------------------------------------------------------------------------

def pivot_brief(profile: dict, target_title: str) -> str:
    """Markdown brief combining the reframe, gaps, and 30/60/90 plan."""
    r = reframe(profile, target_title)
    plan = pivot_plan(profile, target_title)
    who = (profile.get("name") or "").strip() or "you"

    lines = [
        f"# Pivot brief: {who} -> {r['target_title']}",
        "",
        f"*{r['honest_read']}*",
        "",
        "## Reframed summary",
        "",
        r["reframed_summary"],
        "",
        "## Per-role reframing",
        "",
    ]
    for role in r["roles"]:
        lines.append(f"### {role['title']} - {role['company']} ({role['dates']})")
        lines.append("")
        lines.append(f"_Angle: {role['angle']}_")
        lines.append("")
        for b in role["bullets"]:
            lines.append(f"- {b}")
        lines.append("")
    fg = ", ".join(r["skills_to_foreground"]) or "(none yet)"
    lines += ["## Skills to foreground", "", fg, ""]
    lines += ["## Credibility gaps", ""]
    if r["credibility_gaps"]:
        for g in r["credibility_gaps"]:
            lines.append(f"- {g}")
    else:
        lines.append("- None: the profile already covers this role's core skills.")
    lines += ["", "## 30/60/90-day plan", ""]
    for phase in ("30", "60", "90"):
        lines.append(f"### Days {phase}")
        lines.append("")
        for s in plan["steps"]:
            if s["phase"] == phase:
                lines.append(f"- **[{s['addresses']}]** {s['action']} "
                             f"*{s['outcome']}*")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
