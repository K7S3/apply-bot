"""Transferable-skills mapping for career switchers.

Given the user's profile skills (each a {"skill", "context"} dict) and the
target role's requirements (strings pulled from a job description), this
module ranks how well each profile skill transfers:

    strength in {"direct", "adjacent", "foundational"}
      direct       -- the skill is the requirement (after alias resolution,
                      e.g. "k8s" -> "Kubernetes")
      adjacent     -- the skill is a known neighbor of the requirement
                      (e.g. "SQL" -> "data engineering")
      foundational -- generic token/stem overlap suggests a base to build on
                      (e.g. "statistics" -> "machine learning")

Entry points:
    map_transferable(profile_skills, requirements)
        -> ranked list of {"skill", "matched_as", "evidence", "strength"}
    skill_gap_summary(profile_skills, requirements)
        -> {"covered": [...], "partial": [...], "missing": [...]}
    save_switch_report(target_role, mappings, summary, path=None)
        -> writes a JSON report under CANDID_DATA_DIR/switch_reports/

Everything is deterministic and local: no network, no APIs, no scraping.
Evidence strings are copied verbatim from the user's own context; nothing
is invented about the user's experience.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class SwitchSkillsError(Exception):
    """Raised for bad input to the transferable-skills mapping."""


# ---------------------------------------------------------------------------
# Normalization, aliases, adjacency
# ---------------------------------------------------------------------------

# Built-in alias / synonym table. Keys are normalized phrases
# (lowercase, punctuation collapsed, naive de-pluralization applied);
# values are the canonical skill name used for matching.
ALIASES = {
    # infrastructure / platform shorthand
    "k8s": "kubernetes",
    "ci cd": "continuous integration",
    "cicd": "continuous integration",
    # data / ML shorthand
    "ml": "machine learning",
    "dl": "deep learning",
    "ds": "data science",
    "ai": "artificial intelligence",
    "genai": "generative ai",
    "gen ai": "generative ai",
    "nlp": "natural language processing",
    "llm": "large language model",
    "a b testing": "experimentation",
    "ab testing": "experimentation",
    "a b test": "experimentation",
    "ab test": "experimentation",
    "hypothesis testing": "experimentation",
    "data viz": "data visualization",
    "bi": "business intelligence",
    "etl": "data pipeline",
    # languages / tools
    "js": "javascript",
    "ts": "typescript",
    "gcp": "google cloud",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "restful": "rest api",
    "rdbms": "sql",
    # people / product shorthand
    "pm": "product management",
    "ux": "user experience",
    "ui": "user interface",
    "qa": "quality assurance",
    "kpi": "metrics",
    "okr": "goal setting",
    "people management": "team leadership",
    "stakeholder management": "cross functional collaboration",
}

# Domain adjacency: canonical skill -> set of canonical neighbors.
# Written in plain phrases here; _ADJACENCY below is canonicalized at load
# so keys/values always match what canonical_skill() produces.
_RAW_ADJACENCY = {
    "data analysis": {"data science", "business intelligence", "statistics",
                      "reporting", "sql", "experimentation"},
    "sql": {"database", "data engineering", "postgresql", "data pipeline",
            "data analysis"},
    "python": {"programming", "software engineering", "data science",
               "automation", "scripting"},
    "programming": {"software engineering", "software development",
                    "computer science", "coding"},
    "machine learning": {"statistics", "data science", "artificial intelligence",
                         "deep learning", "predictive modeling", "experimentation"},
    "statistics": {"data science", "experimentation", "quantitative analysis",
                   "metrics", "research"},
    "experimentation": {"product management", "data science", "research",
                        "metrics"},
    "data science": {"data engineering", "analytics", "business intelligence",
                     "research"},
    "data engineering": {"data pipeline", "database", "sql", "cloud",
                         "software engineering"},
    "project management": {"product management", "program management", "agile",
                           "scrum", "team leadership", "cross functional collaboration"},
    "product management": {"agile", "scrum", "user experience", "metrics",
                           "cross functional collaboration"},
    "teaching": {"training", "mentoring", "communication", "public speaking",
                 "documentation"},
    "customer support": {"communication", "customer success", "troubleshooting",
                         "documentation"},
    "sales": {"business development", "customer success", "negotiation",
              "communication", "account management"},
    "marketing": {"content creation", "communication", "analytics", "seo",
                  "social media"},
    "finance": {"accounting", "financial modeling", "excel", "quantitative analysis"},
    "design": {"user experience", "user interface", "figma", "prototyping"},
    "writing": {"communication", "documentation", "content creation",
                "technical writing"},
    "leadership": {"team leadership", "mentoring", "management",
                   "cross functional collaboration"},
    "research": {"analysis", "experimentation", "data analysis", "writing"},
    "operations": {"process improvement", "project management", "logistics",
                   "supply chain"},
    "kubernetes": {"docker", "devops", "cloud", "infrastructure"},
    "javascript": {"typescript", "frontend", "web development", "react"},
    "cloud": {"aws", "google cloud", "azure", "devops", "infrastructure"},
    "cybersecurity": {"networking", "linux", "risk management", "compliance"},
}

_STRENGTH_RANK = {"direct": 0, "adjacent": 1, "foundational": 2}


# Words ending in these are never de-pluralized ("kubernetes" must not
# become "kubernete"). Words ending in "is" are stemmed except for the
# known no-stem exceptions below ("apis" -> "api", but "analysis" stays).
_PROTECTED_ENDINGS = ("ss", "us", "es", "os", "as")
_NO_STEM_IS = {"analysis", "thesis", "crisis", "basis", "diagnosis", "synopsis"}


def _stem_word(word: str) -> str:
    """Conservative de-pluralization for matching ('apis' -> 'api')."""
    if len(word) > 3 and word.endswith("s") \
            and not word.endswith(_PROTECTED_ENDINGS) \
            and not (word.endswith("is") and word in _NO_STEM_IS):
        return word[:-1]
    return word


def _stem_phrase(phrase: str) -> str:
    return " ".join(_stem_word(w) for w in phrase.split(" "))


def normalize_skill(text: str) -> str:
    """Lowercase and collapse punctuation/whitespace (no stemming)."""
    if not isinstance(text, str):
        raise SwitchSkillsError(f"skill must be a string, got {type(text).__name__}")
    t = text.strip().lower().replace("&", " and ")
    t = re.sub(r"[/\-_.]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def canonical_skill(text: str) -> str:
    """Resolve aliases after normalization, then de-pluralize tokens."""
    norm = normalize_skill(text)
    resolved = ALIASES.get(norm, norm)
    return _stem_phrase(resolved)


# Canonicalized adjacency: lookup is bidirectional (checked both directions).
ADJACENCY: dict[str, set[str]] = {
    canonical_skill(k): {canonical_skill(v) for v in vals}
    for k, vals in _RAW_ADJACENCY.items()
}


def _match_pair(skill_canon: str, req_canon: str) -> str | None:
    """Strength of the match between two canonical phrases, or None."""
    if skill_canon == req_canon:
        return "direct"
    if skill_canon in ADJACENCY.get(req_canon, set()) or \
            req_canon in ADJACENCY.get(skill_canon, set()):
        return "adjacent"
    s_tokens, r_tokens = set(skill_canon.split()), set(req_canon.split())
    if not s_tokens or not r_tokens:
        return None
    if not (s_tokens & r_tokens):
        return None
    if skill_canon in req_canon or req_canon in skill_canon:
        return "foundational"
    overlap = len(s_tokens & r_tokens) / min(len(s_tokens), len(r_tokens))
    if overlap >= 0.5:
        return "foundational"
    return None


def _validate_skills(profile_skills) -> list[dict]:
    if not isinstance(profile_skills, list):
        raise SwitchSkillsError("profile_skills must be a list of {'skill', 'context'} dicts")
    out = []
    for i, item in enumerate(profile_skills):
        if not isinstance(item, dict) or "skill" not in item:
            raise SwitchSkillsError(
                f"profile_skills[{i}] must be a dict with a 'skill' key")
        skill = item["skill"]
        if not isinstance(skill, str) or not skill.strip():
            raise SwitchSkillsError(f"profile_skills[{i}]['skill'] must be a non-empty string")
        out.append({
            "index": i,
            "skill": skill.strip(),
            "context": str(item.get("context", "") or ""),
            "canonical": canonical_skill(skill),
        })
    return out


def _validate_requirements(requirements) -> list[dict]:
    if not isinstance(requirements, list) or not requirements:
        raise SwitchSkillsError("requirements must be a non-empty list of strings")
    out = []
    for i, req in enumerate(requirements):
        if not isinstance(req, str) or not req.strip():
            raise SwitchSkillsError(f"requirements[{i}] must be a non-empty string")
        out.append({
            "index": i,
            "requirement": req.strip(),
            "canonical": canonical_skill(req),
        })
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_transferable(profile_skills: list[dict], requirements: list[str]) -> list[dict]:
    """Map each profile skill to its best-matching target requirement.

    Returns one entry per matched skill, ranked direct > adjacent >
    foundational, ties broken by original skill order (deterministic):

        {"skill": <original name>, "matched_as": <requirement string>,
         "evidence": <verbatim context from the profile>, "strength": ...}
    """
    skills = _validate_skills(profile_skills)
    reqs = _validate_requirements(requirements)

    mappings: list[dict] = []
    for skill in skills:
        best: tuple[str, int] | None = None  # (strength, requirement index)
        for req in reqs:
            strength = _match_pair(skill["canonical"], req["canonical"])
            if strength is None:
                continue
            if best is None or (_STRENGTH_RANK[strength], req["index"]) < \
                    (_STRENGTH_RANK[best[0]], best[1]):
                best = (strength, req["index"])
        if best is not None:
            strength, req_idx = best
            mappings.append({
                "skill": skill["skill"],
                "matched_as": reqs[req_idx]["requirement"],
                "evidence": skill["context"],
                "strength": strength,
                "_skill_index": skill["index"],
                "_req_index": req_idx,
            })

    mappings.sort(key=lambda m: (_STRENGTH_RANK[m["strength"]],
                                 m["_skill_index"], m["_req_index"]))
    for m in mappings:
        m.pop("_skill_index", None)
        m.pop("_req_index", None)
    return mappings


def skill_gap_summary(profile_skills: list[dict], requirements: list[str]) -> dict:
    """Summarize which requirements are covered, partial, or missing.

    covered -- at least one profile skill matches directly.
    partial -- only adjacent/foundational matches exist.
    missing -- no match at all.
    """
    skills = _validate_skills(profile_skills)
    reqs = _validate_requirements(requirements)

    by_req: dict[int, list[tuple[str, str]]] = {r["index"]: [] for r in reqs}
    for skill in skills:
        for req in reqs:
            strength = _match_pair(skill["canonical"], req["canonical"])
            if strength is not None:
                by_req[req["index"]].append((skill["skill"], strength))

    covered, partial, missing = [], [], []
    for req in reqs:
        hits = by_req[req["index"]]
        entry = {"requirement": req["requirement"],
                 "matched_skills": [{"skill": s, "strength": st} for s, st in hits]}
        if any(st == "direct" for _, st in hits):
            covered.append(entry)
        elif hits:
            best = min(hits, key=lambda h: _STRENGTH_RANK[h[1]])
            entry["best_strength"] = best[1]
            partial.append(entry)
        else:
            missing.append(req["requirement"])
    return {"covered": covered, "partial": partial, "missing": missing}


def save_switch_report(target_role: str, mappings: list[dict], summary: dict,
                       path: str | Path | None = None) -> Path:
    """Persist a transferable-skills report as JSON.

    The report dir is resolved from CANDID_DATA_DIR at call time so tests
    can redirect it with monkeypatch. Returns the path written.
    """
    from candid import config as C

    if not isinstance(target_role, str) or not target_role.strip():
        raise SwitchSkillsError("target_role must be a non-empty string")
    if not isinstance(mappings, list) or not isinstance(summary, dict):
        raise SwitchSkillsError("mappings must be a list and summary must be a dict")

    out_dir = C._data_dir() / "switch_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", target_role.lower()).strip("-") or "role"
    out_path = Path(path) if path else out_dir / f"{slug}-switch-report.json"
    payload = {
        "target_role": target_role.strip(),
        "mappings": mappings,
        "summary": summary,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return out_path
