"""Skills radar: map profile skills against next-level role requirements.

Ten concrete features in one module:

 1. AXES: a canonical 8-axis skill taxonomy (Languages, ML & AI, ...).
    Maps every skill from config.SKILL_LEXICON plus an extended alias
    lexicon (pytorch, kubernetes, react, ...) onto radar axes.
 2. skill_proficiency(): 0-100 proficiency per skill, scored from profile
    evidence (skills section, experience bullets, recency) - deterministic,
    no network, no LLM.
 3. axis_coverage(): per-axis 0-100 coverage with diminishing returns, so
    depth (high proficiency in one skill) and breadth (several mid skills)
    both move the needle.
 4. ROLE_TARGETS: a built-in catalog of next-level role archetypes
    (senior-swe, staff-swe, senior-ml, staff-ml, senior-ds, senior-de,
    senior-fe, eng-manager) with per-axis and per-skill requirements,
    plus custom targets loaded from JSON.
 5. gap_analysis(): required-vs-current per axis and per skill, sorted
    by impact for a chosen target role.
 6. prioritize_gaps(): ordered learning plan. Ranks gap skills by
    benefit-per-hour (gap size x axis weight x market demand, divided by
    estimated study hours), then topologically orders so prerequisites
    (python before pytorch) come first.
 7. render_ascii_radar(): terminal radar chart plotting current coverage
    against target requirements, with JSON and Markdown variants.
 8. evidence_for_axis(): trace every axis score back to the resume
    experience entries that evidence it.
 9. skill snapshots + trend(): store dated radar snapshots in
    candid_data/skills_snapshots.json and show per-axis growth over time.
10. plan_report(): export the full picture (radar, gaps, prioritized plan,
    evidence) as Markdown or JSON for interview prep / LinkedIn work.

Everything is deterministic and offline. Pass explicit ``when``/``today``
arguments for deterministic tests.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime
from pathlib import Path

from candid import config as C

SNAPSHOT_FILENAME = "skills_snapshots.json"


class SkillsRadarError(Exception):
    """Raised for bad targets, missing snapshots, and other radar problems."""


# ---------------------------------------------------------------------------
# 1. taxonomy: axes + extended skill lexicon
# ---------------------------------------------------------------------------

# Axis -> canonical skill names. Every config.SKILL_LEXICON skill appears
# exactly once here; EXTRA_SKILL_ALIASES adds skills the lexicon lacks.
AXES: dict[str, list[str]] = {
    "Languages": [
        "python", "java", "javascript", "typescript", "c++", "golang",
        "rust", "scala", "kotlin", "swift", "r",
    ],
    "ML & AI": [
        "machine learning", "deep learning", "nlp", "llm", "recommendations",
        "scikit-learn", "xgboost", "time series", "optimization", "pytorch",
        "tensorflow", "keras", "reinforcement learning", "computer vision",
        "genai",
    ],
    "Data & Analytics": [
        "sql", "pandas", "spark", "dbt", "statistics", "data visualization",
        "product analytics", "excel", "airflow", "bigquery", "snowflake",
        "tableau", "power bi",
    ],
    "Systems & Backend": [
        "system design", "distributed systems", "api design", "microservices",
        "caching", "message queues", "kafka", "grpc", "concurrency",
    ],
    "Cloud & DevOps": [
        "cloud", "mlops", "aws", "gcp", "azure", "docker", "kubernetes",
        "ci/cd", "terraform", "monitoring",
    ],
    "Frontend & Mobile": [
        "react", "vue", "angular", "ios", "android", "flutter", "react native",
        "ui/ux", "html/css",
    ],
    "Leadership & People": [
        "leadership", "mentoring", "cross-functional", "communication",
        "project management", "stakeholder management", "hiring",
        "performance reviews",
    ],
    "Domain & Research": [
        "finance", "research", "publications", "experimentation",
        "a/b testing", "causal inference",
    ],
}

#: canonical skill -> extra aliases beyond config.SKILL_LEXICON.
EXTRA_SKILL_ALIASES: dict[str, list[str]] = {
    "pytorch": ["pytorch", "torch"],
    "tensorflow": ["tensorflow", "tf.keras"],
    "keras": ["keras"],
    "golang": ["golang", "go"],
    "rust": ["rust"],
    "typescript": ["typescript", "ts"],
    "scala": ["scala"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud"],
    "azure": ["azure"],
    "docker": ["docker"],
    "kubernetes": ["kubernetes", "k8s"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration"],
    "terraform": ["terraform"],
    "monitoring": ["monitoring", "observability", "prometheus", "grafana"],
    "react": ["react", "reactjs", "react.js"],
    "vue": ["vue", "vuejs"],
    "angular": ["angular"],
    "ios": ["ios", "swiftui"],
    "android": ["android"],
    "flutter": ["flutter"],
    "react native": ["react native"],
    "ui/ux": ["ui/ux", "ux", "user experience"],
    "html/css": ["html", "css"],
    "airflow": ["airflow"],
    "kafka": ["kafka"],
    "grpc": ["grpc"],
    "microservices": ["microservices", "microservice"],
    "api design": ["api design", "rest api", "restful"],
    "system design": ["system design"],
    "distributed systems": ["distributed system"],
    "caching": ["caching", "cache", "redis", "memcached"],
    "message queues": ["message queue", "rabbitmq", "sqs"],
    "concurrency": ["concurrency", "concurrent", "parallelism", "multithreading"],
    "leadership": ["leadership", "led team", "tech lead"],
    "mentoring": ["mentoring", "mentored", "mentor"],
    "cross-functional": ["cross-functional", "cross functional"],
    "communication": ["communication", "communicated"],
    "project management": ["project management"],
    "stakeholder management": ["stakeholder"],
    "hiring": ["hiring", "interviewing", "recruiting"],
    "performance reviews": ["performance review"],
    "research": ["research"],
    "publications": ["publication", "published", "paper"],
    "experimentation": ["experimentation", "experiment"],
    "a/b testing": ["a/b testing", "ab testing", "a/b test"],
    "causal inference": ["causal inference"],
    "bigquery": ["bigquery"],
    "snowflake": ["snowflake"],
    "tableau": ["tableau"],
    "power bi": ["power bi", "powerbi"],
    "computer vision": ["computer vision"],
    "reinforcement learning": ["reinforcement learning"],
    "genai": ["genai", "generative ai"],
}

#: canonical skill -> direct prerequisites (used by the learning plan).
PREREQUISITES: dict[str, list[str]] = {
    "pytorch": ["python"],
    "tensorflow": ["python"],
    "keras": ["python"],
    "scikit-learn": ["python", "statistics"],
    "xgboost": ["python", "statistics"],
    "deep learning": ["machine learning"],
    "nlp": ["machine learning"],
    "llm": ["deep learning"],
    "genai": ["llm"],
    "reinforcement learning": ["machine learning"],
    "computer vision": ["deep learning"],
    "recommendations": ["machine learning"],
    "time series": ["statistics"],
    "optimization": ["machine learning"],
    "dbt": ["sql"],
    "spark": ["sql"],
    "airflow": ["python"],
    "pandas": ["python"],
    "data visualization": ["statistics"],
    "product analytics": ["statistics"],
    "causal inference": ["statistics"],
    "experimentation": ["statistics"],
    "a/b testing": ["statistics"],
    "kubernetes": ["docker"],
    "terraform": ["cloud"],
    "monitoring": ["cloud"],
    "ci/cd": ["cloud"],
    "mlops": ["cloud"],
    "react": ["javascript"],
    "vue": ["javascript"],
    "angular": ["typescript"],
    "flutter": [],
    "react native": ["react", "javascript"],    "distributed systems": ["system design"],
    "microservices": ["api design"],
    "message queues": ["distributed systems"],
    "kafka": ["message queues"],
    "grpc": ["api design"],
    "performance reviews": ["leadership"],
    "hiring": ["leadership"],
    "mentoring": ["communication"],
    "project management": ["communication"],
    "stakeholder management": ["communication"],
}

#: relative market demand per skill (1.0 = average). Multiplies benefit in
#: the learning plan so high-demand gaps outrank niche ones.
MARKET_DEMAND: dict[str, float] = {
    "python": 1.6, "llm": 1.8, "genai": 1.7, "deep learning": 1.5,
    "machine learning": 1.5, "sql": 1.4, "pytorch": 1.4, "kubernetes": 1.4,
    "aws": 1.4, "system design": 1.5, "react": 1.3, "typescript": 1.3,
    "nlp": 1.3, "statistics": 1.3, "leadership": 1.3, "spark": 1.2,
    "docker": 1.2, "gcp": 1.2, "data visualization": 1.1, "dbt": 1.2,
    "mlops": 1.3, "java": 1.1, "golang": 1.2, "rust": 1.1, "excel": 0.6,
    "r": 0.8, "tableau": 0.9, "power bi": 0.9,
}

#: study hours needed to raise proficiency by one point (skill-specific).
HOURS_PER_POINT: dict[str, float] = {
    "system design": 3.0, "distributed systems": 3.0,
    "deep learning": 2.5, "reinforcement learning": 2.8,
    "causal inference": 2.5, "leadership": 2.0,
    "llm": 2.0, "genai": 2.0, "kubernetes": 2.0,
    "excel": 0.5, "tableau": 0.6, "power bi": 0.6,
    "sql": 0.8, "python": 1.0, "communication": 0.8,
}
DEFAULT_HOURS_PER_POINT = 1.5
DEFAULT_DEMAND = 1.0


def axis_for_skill(skill: str) -> str | None:
    """Return the radar axis a canonical skill belongs to (None if unknown)."""
    s = skill.strip().lower()
    for axis, skills in AXES.items():
        if s in skills:
            return axis
    return None


def all_canonical_skills() -> list[str]:
    """Every canonical skill the radar knows, axis by axis."""
    return [s for axis in AXES for s in AXES[axis]]


def _alias_regex(alias: str) -> re.Pattern:
    """Word-aware regex for one alias.

    Single-character aliases like 'r' or 'go' get strict word boundaries;
    multi-word aliases allow flexible whitespace; 'c++' style tokens keep
    their punctuation.
    """
    a = alias.strip()
    if len(a) <= 2:
        return re.compile(r"(?<![a-z0-9+#])" + re.escape(a) + r"(?![a-z0-9+#])", re.I)
    body = re.escape(a).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I)


def _regexes_for(skill: str) -> list[re.Pattern]:
    """All matching regexes for a canonical skill: lexicon aliases first."""
    regexes: list[re.Pattern] = []
    for alias in C.SKILL_LEXICON.get(skill, []):
        try:
            regexes.append(C.skill_regex(alias))
        except Exception:
            regexes.append(_alias_regex(alias))
    for alias in EXTRA_SKILL_ALIASES.get(skill, []):
        regexes.append(_alias_regex(alias))
    if not regexes:  # fallback: the canonical name itself
        regexes.append(_alias_regex(skill))
    return regexes


_REGEX_CACHE: dict[str, list[re.Pattern]] = {}


def skill_hit(skill: str, text: str) -> bool:
    """True if any alias of a canonical skill appears in the text.

    Case-insensitive, mirroring profile._extract_skills (which lowercases
    the text before matching lexicon regexes, since C.skill_regex is
    case-sensitive by design).
    """
    if not text:
        return False
    key = skill.strip().lower()
    if key not in _REGEX_CACHE:
        _REGEX_CACHE[key] = _regexes_for(key)
    low = text.lower()
    return any(r.search(low) for r in _REGEX_CACHE[key])


def mention_count(skill: str, text: str) -> int:
    """Number of alias occurrences of a skill in the text (case-insensitive)."""
    if not text:
        return 0
    key = skill.strip().lower()
    if key not in _REGEX_CACHE:
        _REGEX_CACHE[key] = _regexes_for(key)
    low = text.lower()
    return sum(len(r.findall(low)) for r in _REGEX_CACHE[key])


# ---------------------------------------------------------------------------
# 2. proficiency scoring (per skill, 0-100)
# ---------------------------------------------------------------------------

# Evidence weights: presence in the skills section is the strongest single
# signal; experience evidence is weighted by recency so a skill used in the
# latest role counts more than one from 10 years ago.
_BASE_IN_SKILLS_SECTION = 45
_RECENCY_WEIGHTS = (18, 10)  # entry 0 (most recent), entry 1, then 5 each
_RECENCY_TAIL = 5
_HEADLINE_SUMMARY_BONUS = 5
_PER_MENTION = 1
_MENTION_CAP = 10
_RECENCY_CAP = 30


def _profile_skill_names(profile: dict) -> set[str]:
    return {str(s).strip().lower() for s in profile.get("skills", [])}


def skill_proficiency(skill: str, profile: dict) -> dict:
    """Score one skill 0-100 from profile evidence.

    Returns {"score": int, "breakdown": {...}} where breakdown names each
    contributing signal, so the number is always explainable.
    """
    canon = skill.strip().lower()
    breakdown: dict[str, int | list[str]] = {}
    total = 0

    # 1. explicit skills section
    in_skills = canon in _profile_skill_names(profile)
    if in_skills:
        total += _BASE_IN_SKILLS_SECTION
        breakdown["skills_section"] = _BASE_IN_SKILLS_SECTION

    # 2. experience evidence, weighted by recency (most recent entry first)
    experience = profile.get("experience", [])
    recency_pts = 0
    used_in: list[str] = []
    for i, entry in enumerate(experience):
        text = " ".join([
            str(entry.get("title", "")),
            str(entry.get("company", "")),
            " ".join(str(b) for b in entry.get("bullets", [])),
        ])
        if skill_hit(canon, text):
            w = (_RECENCY_WEIGHTS[i] if i < len(_RECENCY_WEIGHTS)
                 else _RECENCY_TAIL)
            recency_pts += w
            used_in.append(str(entry.get("title", "")) or f"role {i + 1}")
    recency_pts = min(recency_pts, _RECENCY_CAP)
    if recency_pts:
        total += recency_pts
        breakdown["experience_recency"] = recency_pts
        breakdown["used_in_roles"] = used_in

    # 3. headline / summary mention
    head = " ".join([str(profile.get("headline", "")),
                     str(profile.get("summary", ""))])
    if skill_hit(canon, head):
        total += _HEADLINE_SUMMARY_BONUS
        breakdown["headline_summary"] = _HEADLINE_SUMMARY_BONUS

    # 4. mention frequency across bullets (depth signal, capped)
    bullet_text = " ".join(
        str(b) for e in experience for b in e.get("bullets", []))
    mentions = mention_count(canon, bullet_text)
    freq = min(mentions * _PER_MENTION, _MENTION_CAP)
    if freq:
        total += freq
        breakdown["bullet_mentions"] = freq

    return {"score": int(min(100, total)), "breakdown": breakdown}


def all_proficiencies(profile: dict) -> dict[str, dict]:
    """Proficiency for every canonical skill; nonzero entries only."""
    out: dict[str, dict] = {}
    for skill in all_canonical_skills():
        scored = skill_proficiency(skill, profile)
        if scored["score"] > 0:
            out[skill] = scored
    return out


# ---------------------------------------------------------------------------
# 3. axis coverage (per radar axis, 0-100)
# ---------------------------------------------------------------------------

# Top-k skill weights: the strongest skill counts most, then diminishing
# returns. Breadth still helps via the diversity multiplier.
_AXIS_TOP_WEIGHTS = (1.0, 0.6, 0.4, 0.25, 0.15)
_DIVERSITY_PER_SKILL = 0.05
_DIVERSITY_CAP = 1.25


def axis_coverage(profile: dict) -> dict[str, dict]:
    """Per-axis coverage 0-100.

    Each axis aggregates its skills with diminishing returns: the top
    skill weighs 1.0, the next 0.6, and so on. A diversity multiplier
    (up to +25%) rewards breadth. Returns {axis: {"score", "top_skills",
    "n_skills"}}.
    """
    profs = all_proficiencies(profile)
    out: dict[str, dict] = {}
    for axis, skills in AXES.items():
        scored = sorted(
            ((s, profs[s]["score"]) for s in skills if s in profs),
            key=lambda kv: -kv[1],
        )
        if not scored:
            out[axis] = {"score": 0, "top_skills": [], "n_skills": 0}
            continue
        num = 0.0
        den = 0.0
        for i, (_, p) in enumerate(scored[: len(_AXIS_TOP_WEIGHTS)]):
            w = _AXIS_TOP_WEIGHTS[i]
            num += w * p
            den += w
        base = num / den if den else 0.0
        diversity = min(1.0 + _DIVERSITY_PER_SKILL * len(scored),
                        _DIVERSITY_CAP)
        score = int(min(100, round(base * diversity)))
        out[axis] = {
            "score": score,
            "top_skills": [s for s, _ in scored[:3]],
            "n_skills": len(scored),
        }
    return out


def radar_scores(profile: dict) -> dict[str, int]:
    """Just the axis -> score mapping (for charts and snapshots)."""
    return {axis: info["score"] for axis, info in axis_coverage(profile).items()}


# ---------------------------------------------------------------------------
# 4. next-level role requirement catalog
# ---------------------------------------------------------------------------

# Each target: label, blurb, per-axis required scores, per-skill required
# proficiency, and per-axis importance weights (gap x weight = impact).
ROLE_TARGETS: dict[str, dict] = {
    "senior-swe": {
        "label": "Senior Software Engineer",
        "blurb": "Owns systems end-to-end; designs, ships, mentors.",
        "axes": {"Languages": 70, "Systems & Backend": 70, "Cloud & DevOps": 55,
                 "Frontend & Mobile": 35, "Data & Analytics": 40,
                 "ML & AI": 25, "Leadership & People": 60,
                 "Domain & Research": 30},
        "skills": {"system design": 75, "python": 70, "leadership": 65,
                   "communication": 70, "mentoring": 60, "aws": 55,
                   "sql": 60, "monitoring": 55, "api design": 70},
        "weights": {"Languages": 1.0, "Systems & Backend": 1.2,
                    "Leadership & People": 1.2, "Cloud & DevOps": 1.0,
                    "Data & Analytics": 0.8, "Frontend & Mobile": 0.6,
                    "ML & AI": 0.6, "Domain & Research": 0.5},
    },
    "staff-swe": {
        "label": "Staff Software Engineer",
        "blurb": "Sets technical direction across teams; force multiplier.",
        "axes": {"Languages": 75, "Systems & Backend": 85, "Cloud & DevOps": 65,
                 "Frontend & Mobile": 40, "Data & Analytics": 50,
                 "ML & AI": 35, "Leadership & People": 80,
                 "Domain & Research": 45},
        "skills": {"system design": 90, "distributed systems": 85,
                   "leadership": 80, "communication": 85,
                   "stakeholder management": 75, "mentoring": 75,
                   "project management": 70},
        "weights": {"Systems & Backend": 1.3, "Leadership & People": 1.3,
                    "Languages": 0.9, "Cloud & DevOps": 0.9,
                    "Data & Analytics": 0.7, "Domain & Research": 0.6,
                    "ML & AI": 0.5, "Frontend & Mobile": 0.4},
    },
    "senior-ml": {
        "label": "Senior ML Engineer",
        "blurb": "Ships ML to production; owns modeling + serving.",
        "axes": {"ML & AI": 75, "Languages": 70, "Data & Analytics": 65,
                 "Cloud & DevOps": 60, "Systems & Backend": 55,
                 "Leadership & People": 55, "Domain & Research": 45,
                 "Frontend & Mobile": 20},
        "skills": {"machine learning": 80, "python": 75, "deep learning": 70,
                   "pytorch": 70, "mlops": 65, "sql": 65,
                   "experimentation": 65, "communication": 65,
                   "system design": 60},
        "weights": {"ML & AI": 1.3, "Languages": 1.0, "Data & Analytics": 1.0,
                    "Cloud & DevOps": 1.0, "Systems & Backend": 0.8,
                    "Leadership & People": 0.9, "Domain & Research": 0.6,
                    "Frontend & Mobile": 0.3},
    },
    "staff-ml": {
        "label": "Staff ML Engineer",
        "blurb": "ML technical leader; research taste + production rigor.",
        "axes": {"ML & AI": 88, "Languages": 75, "Data & Analytics": 70,
                 "Cloud & DevOps": 65, "Systems & Backend": 60,
                 "Leadership & People": 75, "Domain & Research": 60,
                 "Frontend & Mobile": 20},
        "skills": {"machine learning": 90, "deep learning": 85,
                   "llm": 75, "pytorch": 80, "python": 80,
                   "experimentation": 80, "leadership": 75,
                   "communication": 80, "research": 65},
        "weights": {"ML & AI": 1.4, "Leadership & People": 1.1,
                    "Languages": 1.0, "Data & Analytics": 0.9,
                    "Cloud & DevOps": 0.9, "Domain & Research": 0.7,
                    "Systems & Backend": 0.7, "Frontend & Mobile": 0.2},
    },
    "senior-ds": {
        "label": "Senior Data Scientist",
        "blurb": "Drives decisions with data; experimentation rigor.",
        "axes": {"Data & Analytics": 80, "ML & AI": 65, "Languages": 60,
                 "Domain & Research": 65, "Leadership & People": 60,
                 "Systems & Backend": 40, "Cloud & DevOps": 40,
                 "Frontend & Mobile": 20},
        "skills": {"statistics": 85, "sql": 80, "python": 70,
                   "experimentation": 80, "a/b testing": 75,
                   "data visualization": 70, "causal inference": 60,
                   "communication": 75, "stakeholder management": 65},
        "weights": {"Data & Analytics": 1.3, "Domain & Research": 1.1,
                    "ML & AI": 1.0, "Languages": 0.9,
                    "Leadership & People": 1.0, "Systems & Backend": 0.6,
                    "Cloud & DevOps": 0.6, "Frontend & Mobile": 0.2},
    },
    "senior-de": {
        "label": "Senior Data Engineer",
        "blurb": "Builds reliable data platforms at scale.",
        "axes": {"Data & Analytics": 80, "Systems & Backend": 65,
                 "Cloud & DevOps": 65, "Languages": 65, "ML & AI": 30,
                 "Leadership & People": 55, "Domain & Research": 30,
                 "Frontend & Mobile": 15},
        "skills": {"sql": 85, "python": 75, "spark": 75, "airflow": 70,
                   "dbt": 65, "aws": 60, "docker": 60,
                   "data visualization": 30, "communication": 65},
        "weights": {"Data & Analytics": 1.3, "Systems & Backend": 1.0,
                    "Cloud & DevOps": 1.0, "Languages": 1.0,
                    "Leadership & People": 0.9, "ML & AI": 0.5,
                    "Domain & Research": 0.4, "Frontend & Mobile": 0.2},
    },
    "senior-fe": {
        "label": "Senior Frontend Engineer",
        "blurb": "Owns user-facing surfaces; performance + craft.",
        "axes": {"Frontend & Mobile": 80, "Languages": 70,
                 "Systems & Backend": 50, "Cloud & DevOps": 45,
                 "Data & Analytics": 35, "Leadership & People": 60,
                 "ML & AI": 20, "Domain & Research": 30},
        "skills": {"react": 80, "javascript": 80, "typescript": 70,
                   "ui/ux": 65, "html/css": 75, "api design": 60,
                   "communication": 65, "leadership": 60},
        "weights": {"Frontend & Mobile": 1.3, "Languages": 1.1,
                    "Leadership & People": 1.0, "Systems & Backend": 0.8,
                    "Cloud & DevOps": 0.7, "Data & Analytics": 0.6,
                    "Domain & Research": 0.4, "ML & AI": 0.3},
    },
    "eng-manager": {
        "label": "Engineering Manager",
        "blurb": "Delivers through people; hiring, coaching, delivery.",
        "axes": {"Leadership & People": 85, "Systems & Backend": 55,
                 "Languages": 50, "Cloud & DevOps": 45,
                 "Data & Analytics": 45, "Domain & Research": 40,
                 "ML & AI": 25, "Frontend & Mobile": 25},
        "skills": {"leadership": 90, "communication": 90,
                   "project management": 80, "stakeholder management": 80,
                   "hiring": 75, "mentoring": 80,
                   "performance reviews": 70},
        "weights": {"Leadership & People": 1.4, "Systems & Backend": 0.8,
                    "Languages": 0.7, "Data & Analytics": 0.7,
                    "Cloud & DevOps": 0.6, "Domain & Research": 0.5,
                    "ML & AI": 0.3, "Frontend & Mobile": 0.3},
    },
}


def list_targets() -> list[dict]:
    """All built-in role targets: [{name, label, blurb}]."""
    return [{"name": n, "label": t["label"], "blurb": t["blurb"]}
            for n, t in ROLE_TARGETS.items()]


def load_target(name_or_path: str) -> dict:
    """Load a role target by built-in name or a JSON file path.

    Custom JSON format: {"label": str, "blurb": str, "axes": {axis: 0-100},
    "skills": {skill: 0-100}, "weights": {axis: float}}. Missing axes /
    skills default to 0 required / 1.0 weight.
    """
    key = name_or_path.strip().lower()
    if key in ROLE_TARGETS:
        return {"name": key, **ROLE_TARGETS[key]}
    p = Path(name_or_path)
    if not p.exists():
        known = ", ".join(sorted(ROLE_TARGETS))
        raise SkillsRadarError(
            f"Unknown role target '{name_or_path}'. Built-in targets: {known}.\n"
            "Or pass a JSON file with axes/skills/weights."
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SkillsRadarError(f"Cannot read target file {p}: {exc}") from exc
    for section in ("axes", "skills", "weights"):
        if section in data and not isinstance(data[section], dict):
            raise SkillsRadarError(
                f"Target file {p}: '{section}' must be an object.")
    return {"name": p.stem, "label": data.get("label", p.stem),
            "blurb": data.get("blurb", "custom target"),
            "axes": data.get("axes", {}), "skills": data.get("skills", {}),
            "weights": data.get("weights", {})}


def target_axes_required(target: dict) -> dict[str, int]:
    return {a: int(target.get("axes", {}).get(a, 0)) for a in AXES}


def target_axis_weight(target: dict, axis: str) -> float:
    return float(target.get("weights", {}).get(axis, 1.0))


# ---------------------------------------------------------------------------
# 5. gap analysis
# ---------------------------------------------------------------------------

def gap_analysis(profile: dict, target: dict) -> dict:
    """Required-vs-current for one role target.

    Returns {"target", "axes": [...], "skills": [...], "summary"} where each
    axis row is {axis, current, required, gap, weight, impact, status} and
    each skill row is {skill, axis, current, required, gap, impact, status}.
    status is "met" (gap <= 0), "near" (gap <= 10), or "gap".
    Sorted by impact descending: biggest weighted gaps first.
    """
    axes_cov = axis_coverage(profile)
    profs = all_proficiencies(profile)
    required_axes = target_axes_required(target)

    axis_rows: list[dict] = []
    for axis in AXES:
        current = axes_cov[axis]["score"]
        required = required_axes[axis]
        gap = max(0, required - current)
        weight = target_axis_weight(target, axis)
        axis_rows.append({
            "axis": axis, "current": current, "required": required,
            "gap": gap, "weight": round(weight, 2),
            "impact": round(gap * weight, 1),
            "status": "met" if gap <= 0 else ("near" if gap <= 10 else "gap"),
            "top_skills": axes_cov[axis]["top_skills"],
        })
    axis_rows.sort(key=lambda r: -r["impact"])

    skill_rows: list[dict] = []
    for skill, required in (target.get("skills") or {}).items():
        canon = skill.strip().lower()
        current = profs.get(canon, {"score": 0})["score"]
        gap = max(0, int(required) - current)
        axis = axis_for_skill(canon) or "Other"
        weight = target_axis_weight(target, axis)
        skill_rows.append({
            "skill": canon, "axis": axis, "current": current,
            "required": int(required), "gap": gap,
            "weight": round(weight, 2), "impact": round(gap * weight, 1),
            "status": "met" if gap <= 0 else ("near" if gap <= 10 else "gap"),
        })
    skill_rows.sort(key=lambda r: -r["impact"])

    n_gap = sum(1 for r in axis_rows if r["status"] == "gap")
    return {
        "target": target.get("name"), "label": target.get("label"),
        "axes": axis_rows, "skills": skill_rows,
        "summary": {
            "n_axis_gaps": n_gap,
            "n_skill_gaps": sum(1 for r in skill_rows if r["status"] == "gap"),
            "top_axis_gap": axis_rows[0]["axis"] if axis_rows else None,
            "readiness": _readiness(axis_rows),
        },
    }


def _readiness(axis_rows: list[dict]) -> int:
    """0-100 readiness: 100 when every axis requirement is met."""
    if not axis_rows:
        return 0
    ratios = []
    for r in axis_rows:
        req = r["required"]
        ratios.append(1.0 if req <= 0 else min(1.0, r["current"] / req))
    return int(round(100 * sum(ratios) / len(ratios)))


# ---------------------------------------------------------------------------
# 6. gap prioritization: the ordered learning plan
# ---------------------------------------------------------------------------

def _unmet_prereqs(skill: str, profs: dict[str, dict]) -> list[str]:
    """Prerequisites the profile does not yet demonstrate (>= 60)."""
    out = []
    for pre in PREREQUISITES.get(skill, []):
        if profs.get(pre, {"score": 0})["score"] < 60:
            out.append(pre)
    return out


def prioritize_gaps(profile: dict, target: dict,
                    max_items: int = 12) -> list[dict]:
    """Order gap skills into a learning plan.

    Each item: {skill, axis, gap, hours, demand, ratio, prereqs, why}.
    Ranking is greedy benefit-per-hour: pick the available (all prereqs
    either known or already planned) skill with the highest ratio each
    round, so prerequisites naturally surface first. Deterministic.
    """
    analysis = gap_analysis(profile, target)
    profs = all_proficiencies(profile)
    gaps = [r for r in analysis["skills"] if r["status"] == "gap"]
    if not gaps:
        return []

    items: dict[str, dict] = {}
    for g in gaps:
        skill = g["skill"]
        hours = round(g["gap"] * HOURS_PER_POINT.get(skill,
                                                     DEFAULT_HOURS_PER_POINT), 1)
        demand = MARKET_DEMAND.get(skill, DEFAULT_DEMAND)
        benefit = g["impact"] * demand
        items[skill] = {
            "skill": skill, "axis": g["axis"], "gap": g["gap"],
            "current": g["current"], "required": g["required"],
            "hours": hours, "demand": demand,
            "ratio": round(benefit / max(hours, 0.1), 3),
            "prereqs": _unmet_prereqs(skill, profs),
            "why": (f"Closes {g['gap']}pts of the {g['axis']} gap for "
                    f"{target.get('label')} (demand x{demand})."),
        }

    # Greedy topological pick: among items whose prereqs are all known or
    # already planned, take the highest ratio. A prereq that is itself a
    # gap is always scheduled (it will become available once planned).
    planned: list[dict] = []
    planned_skills: set[str] = set()
    remaining = dict(items)
    guard = 0
    while remaining and guard < len(items) * 3:
        guard += 1
        available = [
            it for it in remaining.values()
            if all(p in planned_skills or
                   profs.get(p, {"score": 0})["score"] >= 60
                   for p in it["prereqs"])
        ]
        if not available:
            # Cycle or missing prereq not in gaps: force the prereq itself
            # into the plan as a step, then continue.
            stuck = max(remaining.values(), key=lambda it: it["ratio"])
            missing = [p for p in stuck["prereqs"]
                       if p not in planned_skills]
            if missing:
                pre = missing[0]
                pre_gap = max(0, 60 - profs.get(pre, {"score": 0})["score"])
                pre_hours = round(pre_gap * HOURS_PER_POINT.get(
                    pre, DEFAULT_HOURS_PER_POINT), 1)
                remaining[pre] = {
                    "skill": pre, "axis": axis_for_skill(pre) or "Other",
                    "gap": pre_gap,
                    "current": profs.get(pre, {"score": 0})["score"],
                    "required": 60, "hours": pre_hours,
                    "demand": MARKET_DEMAND.get(pre, DEFAULT_DEMAND),
                    "ratio": stuck["ratio"],
                    "prereqs": [],
                    "why": f"Prerequisite for {stuck['skill']}.",
                }
                continue
            available = [stuck]
        nxt = max(available, key=lambda it: (it["ratio"], -it["hours"]))
        planned.append(nxt)
        planned_skills.add(nxt["skill"])
        del remaining[nxt["skill"]]

    return planned[:max_items]


# ---------------------------------------------------------------------------
# 7. radar-chart visualization
# ---------------------------------------------------------------------------

_RADAR_W = 44
_RADAR_H = 23
_RADAR_R = 10
_CURRENT_GLYPH = "\u25cf"   # ●
_TARGET_GLYPH = "\u25c7"    # ◇


def render_ascii_radar(current: dict[str, int],
                       target: dict[str, int] | None = None,
                       width: int = _RADAR_W,
                       height: int = _RADAR_H) -> str:
    """Draw an ASCII radar chart of per-axis scores (0-100).

    ``current`` maps axis name -> score; ``target`` (optional) overlays the
    required scores. Axes are the 8 canonical AXES in fixed order, starting
    at the top and going clockwise.
    """
    axes = list(AXES)
    n = len(axes)
    cx, cy = width // 2, height // 2
    canvas = [[" " for _ in range(width)] for _ in range(height)]

    def put(x: int, y: int, ch: str) -> None:
        if 0 <= x < width and 0 <= y < height:
            canvas[y][x] = ch

    # spokes + ring ticks
    points: dict[str, tuple[int, int]] = {}
    for i, axis in enumerate(axes):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        for r in range(1, _RADAR_R + 1):
            x = cx + int(round(r * math.cos(ang) * 1.9))
            y = cy + int(round(r * math.sin(ang)))
            put(x, y, "." if r % 5 else "+")
        # label just outside the ring
        lx = cx + int(round((_RADAR_R + 2) * math.cos(ang) * 1.9))
        ly = cy + int(round((_RADAR_R + 2) * math.sin(ang)))
        label = axis.replace(" & ", "&")
        start = max(0, min(width - len(label), lx - len(label) // 2))
        for j, ch in enumerate(label):
            put(start + j, max(0, min(height - 1, ly)), ch)
        points[axis] = (ang, None)

    def _plot(scores: dict[str, int], glyph: str) -> None:
        for i, axis in enumerate(axes):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            r = _RADAR_R * max(0, min(100, scores.get(axis, 0))) / 100.0
            x = cx + int(round(r * math.cos(ang) * 1.9))
            y = cy + int(round(r * math.sin(ang)))
            put(x, y, glyph)

    if target:
        _plot(target, _TARGET_GLYPH)
    _plot(current, _CURRENT_GLYPH)

    lines = ["".join(row).rstrip() for row in canvas]
    header = "skills radar (● you" + ("  ◇ target" if target else "") + ")"
    return header + "\n" + "\n".join(lines).rstrip("\n")


def render_radar_table(current: dict[str, int],
                       target: dict[str, int] | None = None) -> str:
    """Markdown-friendly axis table to accompany the chart."""
    rows = ["| axis | you | target | gap |",
            "|---|---|---|---|"]
    for axis in AXES:
        you = current.get(axis, 0)
        req = (target or {}).get(axis, 0)
        rows.append(f"| {axis} | {you} | {req} | {max(0, req - you)} |")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# 8. evidence mapping: trace scores back to experience entries
# ---------------------------------------------------------------------------

def evidence_for_axis(profile: dict, axis: str,
                      top: int = 5) -> list[dict]:
    """Resume entries that evidence one radar axis.

    Each row: {title, company, dates, matched_skills, n_bullets, bullets}.
    Entries are ranked by how many of the axis's skills they mention.
    """
    if axis not in AXES:
        raise SkillsRadarError(
            f"Unknown axis '{axis}'. Axes: {', '.join(AXES)}.")
    axis_skills = AXES[axis]
    rows: list[dict] = []
    for entry in profile.get("experience", []):
        text = " ".join([
            str(entry.get("title", "")),
            " ".join(str(b) for b in entry.get("bullets", [])),
        ])
        matched = [s for s in axis_skills if skill_hit(s, text)]
        if not matched:
            continue
        bullets = [b for b in entry.get("bullets", [])
                   if any(skill_hit(s, str(b)) for s in matched)]
        rows.append({
            "title": entry.get("title", ""),
            "company": entry.get("company", ""),
            "dates": entry.get("dates", ""),
            "matched_skills": matched,
            "n_bullets": len(bullets),
            "bullets": bullets[:3],
        })
    rows.sort(key=lambda r: (-len(r["matched_skills"]), -r["n_bullets"]))
    return rows[:top]


def evidence_summary(profile: dict) -> dict[str, list[dict]]:
    """evidence_for_axis() for every axis (top 3 entries each)."""
    return {axis: evidence_for_axis(profile, axis, top=3) for axis in AXES}


# ---------------------------------------------------------------------------
# 9. snapshots + trend
# ---------------------------------------------------------------------------

def _snapshot_path() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override) if override else C.DATA_DIR
    return base / SNAPSHOT_FILENAME


def load_snapshots() -> list[dict]:
    """All stored snapshots, oldest first ([] when none)."""
    p = _snapshot_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def take_snapshot(profile: dict,
                  when: date | datetime | str | None = None) -> dict:
    """Store a dated radar snapshot; return it. Pass ``when`` for tests."""
    if when is None:
        stamp = date.today().isoformat()
    elif isinstance(when, (date, datetime)):
        stamp = when.isoformat()[:10]
    else:
        stamp = str(when)[:10]
    snap = {
        "date": stamp,
        "axes": radar_scores(profile),
        "skills": {s: v["score"] for s, v in all_proficiencies(profile).items()},
        "seniority": profile.get("seniority", ""),
    }
    snaps = load_snapshots()
    snaps = [s for s in snaps if s.get("date") != stamp]
    snaps.append(snap)
    snaps.sort(key=lambda s: s.get("date", ""))
    p = _snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snaps, indent=2), encoding="utf-8")
    return snap


def trend(snapshots: list[dict] | None = None) -> dict:
    """Per-axis and per-skill growth from the first to the latest snapshot.

    Returns {"from", "to", "axes": [{axis, before, after, delta}], ...}.
    Empty dict when fewer than 2 snapshots exist.
    """
    snaps = load_snapshots() if snapshots is None else snapshots
    if len(snaps) < 2:
        return {}
    first, last = snaps[0], snaps[-1]
    axes_rows = []
    for axis in AXES:
        before = (first.get("axes") or {}).get(axis, 0)
        after = (last.get("axes") or {}).get(axis, 0)
        axes_rows.append({"axis": axis, "before": before, "after": after,
                          "delta": after - before})
    axes_rows.sort(key=lambda r: -r["delta"])
    skill_rows = []
    skills = set(first.get("skills", {})) | set(last.get("skills", {}))
    for s in sorted(skills):
        before = first.get("skills", {}).get(s, 0)
        after = last.get("skills", {}).get(s, 0)
        if after != before:
            skill_rows.append({"skill": s, "before": before, "after": after,
                               "delta": after - before})
    skill_rows.sort(key=lambda r: -r["delta"])
    return {"from": first.get("date"), "to": last.get("date"),
            "axes": axes_rows, "skills": skill_rows}


# ---------------------------------------------------------------------------
# 10. plan report (markdown / json export)
# ---------------------------------------------------------------------------

def _md_bar(score: int, width: int = 20) -> str:
    filled = int(round(score / 100 * width))
    return "█" * filled + "░" * (width - filled)


def plan_report(profile: dict, target: dict,
                max_plan: int = 10) -> dict:
    """Everything for a report: radar, gaps, plan, evidence, trend."""
    current = radar_scores(profile)
    required = target_axes_required(target)
    analysis = gap_analysis(profile, target)
    return {
        "profile": profile.get("name", ""),
        "target": target.get("name"),
        "target_label": target.get("label"),
        "radar_ascii": render_ascii_radar(current, required),
        "radar_table": render_radar_table(current, required),
        "current": current,
        "required": required,
        "gaps": analysis,
        "plan": prioritize_gaps(profile, target, max_items=max_plan),
        "evidence": evidence_summary(profile),
        "trend": trend(),
    }


def report_markdown(report: dict) -> str:
    """Render a plan_report() as Markdown."""
    L: list[str] = []
    name = report.get("profile") or "you"
    L.append(f"# Skills radar: {name} → {report.get('target_label')}")
    L.append("")
    L.append(f"Readiness: **{report['gaps']['summary']['readiness']}/100** "
             f"· target `{report.get('target')}`")
    L.append("")
    L.append("## Radar")
    L.append("")
    L.append("```")
    L.append(report["radar_ascii"])
    L.append("```")
    L.append("")
    L.append(report["radar_table"])
    L.append("")
    L.append("## Top axis gaps")
    L.append("")
    for row in report["gaps"]["axes"][:5]:
        L.append(f"- **{row['axis']}**: {row['current']} → {row['required']} "
                 f"(gap {row['gap']}) — strongest: "
                 f"{', '.join(row['top_skills']) or 'none yet'}")
    L.append("")
    L.append("## Learning plan (prioritized)")
    L.append("")
    plan = report["plan"]
    if not plan:
        L.append("No skill gaps for this target — nothing to learn. "
                 "Pick a harder target.")
    for i, step in enumerate(plan, 1):
        pre = (f" (after: {', '.join(step['prereqs'])})"
               if step["prereqs"] else "")
        L.append(f"{i}. **{step['skill']}**{pre} — {step['current']} → "
                 f"{step['required']} (~{step['hours']}h). {step['why']}")
    L.append("")
    L.append("## Evidence highlights")
    L.append("")
    for axis, rows in report["evidence"].items():
        if not rows:
            continue
        r0 = rows[0]
        L.append(f"- **{axis}**: {r0['title']} @ {r0['company']} "
                 f"({', '.join(r0['matched_skills'][:4])})")
    trend_data = report.get("trend") or {}
    if trend_data:
        L.append("")
        L.append(f"## Trend ({trend_data['from']} → {trend_data['to']})")
        L.append("")
        for row in trend_data["axes"][:5]:
            sign = "+" if row["delta"] >= 0 else ""
            L.append(f"- {row['axis']}: {row['before']} → {row['after']} "
                     f"({sign}{row['delta']})")
    return "\n".join(L) + "\n"
