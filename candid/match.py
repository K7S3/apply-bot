"""Job match scoring: score a job description against the user profile.

Score breakdown (0-100):
  - skills match (50 pts): weighted fraction of JD-required skills present in
    the profile. Extraction goes beyond the skill lexicon (quoted phrases,
    capitalized tech terms, "N years of Y" requirements), is section-aware
    (requirements count more than "about us"), classifies must-have vs
    nice-to-have from section headers, and weights rare skills (e.g.
    kubernetes) higher than ubiquitous ones (e.g. python).
  - seniority match (25 pts): an explicit "N+ years" JD requirement is compared
    directly against the profile's years_experience when both exist; otherwise
    title-keyword levels are used as a fallback.
  - domain/keyword match (15 pts): overlap of role-domain keywords.
  - title alignment (10 pts): role family similarity, with expanded families
    (backend/frontend/devops/SWE variants, applied scientist, data roles) and
    "X / Y" title handling.

Also surfaces: matched skills with the JD snippet each appeared in, missing
must-have skills with a one-line pointer on how to close each, gaps, a go /
conditional / no-go recommendation, a parse-confidence note, and - when
salary data exists - the market range for the role (see candid.salary).
"""

from __future__ import annotations

import re
import urllib.request

from candid import config as C


class MatchError(Exception):
    """Raised when a JD cannot be obtained or scored."""


def fetch_jd(source: str, timeout: int = 25) -> str:
    """Get JD text from a URL, a file path, or raw pasted text."""
    from pathlib import Path
    s = (source or "").strip()
    if not s:
        raise MatchError("Empty job description input.")
    if s.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(s, headers={"User-Agent": "candid/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 200:
                raise MatchError("Fetched page had almost no readable text.")
            return text[:20000]
        except MatchError:
            raise
        except Exception as exc:
            raise MatchError(f"Could not fetch JD from URL: {exc}") from exc
    p = Path(s)
    # Only treat the input as a file path when it plausibly is one: pasted
    # or piped JD text (long / multiline) must not reach the filesystem,
    # where an over-long "name" raises OSError instead of returning False.
    if "\n" not in s and len(s) < 1024 and p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 50:
            raise MatchError(f"JD file {p} looks empty.")
        return text[:20000]
    # treat as pasted text
    if len(s) < 50:
        raise MatchError(
            "That doesn't look like a job description (too short). "
            "Paste the full JD text, or pass a URL / file path."
        )
    return s[:20000]


# ---------------------------------------------------------------------------
# JD section splitting + skill extraction
# ---------------------------------------------------------------------------

# header keyword -> (tier, section weight). Tier drives must-have vs
# nice-to-have classification; weight scales the skill's score contribution.
_SECTION_HEADERS: dict[str, tuple[str, float]] = {
    "requirements": ("must", 2.0),
    "required qualifications": ("must", 2.0),
    "minimum qualifications": ("must", 2.0),
    "qualifications": ("must", 2.0),
    "must have": ("must", 2.0),
    "must-have": ("must", 2.0),
    "what you bring": ("must", 2.0),
    "you'll bring": ("must", 2.0),
    "you have": ("must", 2.0),
    "what we're looking for": ("must", 2.0),
    "responsibilities": ("context", 1.5),
    "what you'll do": ("context", 1.5),
    "about the role": ("context", 1.3),
    "the role": ("context", 1.3),
    "job description": ("context", 1.3),
    "preferred qualifications": ("nice", 1.0),
    "nice to have": ("nice", 1.0),
    "nice-to-have": ("nice", 1.0),
    "preferred": ("nice", 1.0),
    "bonus points": ("nice", 1.0),
    "bonus": ("nice", 1.0),
    "pluses": ("nice", 1.0),
    "about us": ("context", 0.5),
    "about the company": ("context", 0.5),
    "who we are": ("context", 0.5),
    "benefits": ("context", 0.4),
    "compensation": ("context", 0.4),
    "pay": ("context", 0.4),
    "salary": ("context", 0.4),
}


def _split_jd_sections(jd: str) -> list[tuple[str, str, float, str]]:
    """Split the JD into (header, tier, weight, text) sections.

    Header detection: a short line ending in ":" containing a known header
    phrase, or a line that is exactly a known header phrase.
    """
    sections: list[tuple[str, str, float, str]] = []
    cur = ("intro", "context", 1.0)
    buf: list[str] = []

    def flush() -> None:
        sections.append((cur[0], cur[1], cur[2], "\n".join(buf)))

    for line in jd.splitlines():
        s = line.strip()
        low = s.lower().rstrip(":")
        looks_header = (s.endswith(":") and len(s) < 80) or (
            low in _SECTION_HEADERS and len(s.split()) <= 5
        )
        key = None
        if looks_header:
            for k in _SECTION_HEADERS:
                if k in low:
                    key = k
                    break
        if key is not None:
            flush()
            tier, weight = _SECTION_HEADERS[key]
            cur = (key, tier, weight)
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


# Rarity multiplier per canonical skill: ubiquitous skills count less than
# rare ones, so matching "kubernetes" (via mlops) beats matching "python".
_SKILL_RARITY: dict[str, float] = {
    "python": 0.7, "sql": 0.8, "excel": 0.7, "statistics": 0.85,
    "data visualization": 0.8, "product analytics": 0.9,
    "machine learning": 1.0, "deep learning": 1.05, "spark": 1.05,
    "cloud": 1.0, "pandas": 1.0, "scikit-learn": 1.05, "xgboost": 1.05,
    "java": 1.0, "c++": 1.0, "javascript": 1.0, "r": 1.0,
    "nlp": 1.2, "llm": 1.2, "mlops": 1.25, "dbt": 1.2,
    "time series": 1.2, "recommendations": 1.25, "optimization": 1.2,
    "finance": 1.1,
}


def _rarity(skill: str) -> float:
    return _SKILL_RARITY.get(skill, 1.0)


# common capitalized words that are never tech terms
_STOPWORDS = {
    "we", "you", "our", "your", "the", "and", "about", "join", "will", "with",
    "for", "from", "role", "team", "company", "job", "work", "new", "senior",
    "junior", "lead", "staff", "remote", "hybrid", "york", "san", "francisco",
    "austin", "boston", "seattle", "chicago", "they", "their", "this", "that",
    "these", "those", "are", "was", "were", "has", "have", "had", "who",
    "what", "when", "where", "how", "why", "not", "but", "all", "any",
    "each", "other", "more", "most", "such", "than", "then", "also", "into",
    "per", "plus", "including", "etc", "ie", "eg", "am", "pm", "us", "ny",
    "nyc", "ca", "tx", "wa", "ma", "il",
}

# proper-noun tech tokens the lexicon may not cover
_KNOWN_TECH = {
    "airflow", "kubernetes", "docker", "terraform", "snowflake", "databricks",
    "kafka", "redis", "graphql", "jenkins", "github", "gitlab", "linux",
    "dbt", "pandas", "numpy", "spark", "hadoop", "tableau", "looker",
    "pytorch", "tensorflow", "xgboost", "sagemaker", "bigquery", "redshift",
    "postgres", "mysql", "sqlite", "mongodb", "cassandra", "elasticsearch",
    "prometheus", "grafana", "ansible", "mlflow", "ray", "dask", "flink",
    "athena", "presto", "trino", "clickhouse", "duckdb", "polars", "onnx",
    "vllm", "huggingface", "datadog", "pagerduty", "okta", "stripe",
    "twilio", "salesforce", "jira", "confluence", "figma", "amplitude",
    "mixpanel", "posthog", "fivetran", "sas", "matlab", "julia", "scala",
    "kotlin", "swift", "rust", "golang", "ruby", "php", "bash", "rest",
    "grpc", "oauth", "saml", "jwt", "nosql", "ci", "cd",
}

_QUOTED_RE = re.compile(r'"([^"\n]{2,60})"|“([^”\n]{2,60})”')
_TECH_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+/#-]*\b")
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)
_YEARS_OF_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience\s+)?"
    r"(?:in|with|as\s+an?\s+)?\s*([A-Za-z][A-Za-z0-9+/#&., ()-]{1,60})", re.I)


def _is_tech_token(tok: str) -> bool:
    if not (2 <= len(tok) <= 30):
        return False
    low = tok.lower()
    if low in _STOPWORDS:
        return False
    if re.search(r"[a-z][A-Z]", tok):      # camelCase / interior caps
        return True
    if re.fullmatch(r"[A-Z0-9+/#-]{2,6}", tok):  # acronyms: SQL, ETL, CI/CD
        return True
    if re.search(r"\d", tok):
        return True
    return low in _KNOWN_TECH


def _looks_technical(phrase: str) -> bool:
    if len(phrase) < 2:
        return False
    words = phrase.split()
    if any(w.lower() in _KNOWN_TECH for w in words):
        return True
    # interior capitals, digits, or symbols suggest a tech term, not prose
    return bool(re.search(r"[a-z][A-Z]|[A-Z][a-z]*[A-Z]|\d|\+|#|/|-", phrase))


def _snippet(text: str, start: int, end: int, radius: int = 45) -> str:
    s = max(0, start - radius)
    e = min(len(text), end + radius)
    frag = re.sub(r"\s+", " ", text[s:e]).strip()
    return ("..." if s > 0 else "") + frag + ("..." if e < len(text) else "")


def _extract_jd(jd: str) -> dict:
    """Rich JD extraction.

    Returns {"items", "must", "nice", "context", "years_required", "signals"}.
    ``items`` maps canonical name -> {"tier", "weight", "evidence", "aliases"};
    free-form terms (quoted phrases, tech tokens) have aliases=None.
    """
    items: dict[str, dict] = {}

    def add(name: str, tier: str, weight: float, evidence: str,
            aliases: list[str] | None) -> None:
        cur = items.get(name)
        if cur is None or weight > cur["weight"]:
            items[name] = {"tier": tier, "weight": weight,
                           "evidence": evidence, "aliases": aliases}

    def covered(phrase: str) -> bool:
        """True if the phrase is already explained by an extracted item."""
        pl = phrase.lower()
        for name, info in items.items():
            for a in info["aliases"] or [name]:
                if C.skill_regex(a).search(pl):
                    return True
        return False

    for _header, tier, sec_weight, text in _split_jd_sections(jd):
        low = text.lower()
        if not low.strip():
            continue
        # 1) lexicon skills
        for canonical, aliases in C.SKILL_LEXICON.items():
            m = None
            for a in aliases:
                m = C.skill_regex(a).search(low)
                if m:
                    break
            if not m:
                continue
            add(canonical, tier, sec_weight * _rarity(canonical),
                _snippet(text, m.start(), m.end()), list(aliases))
        # 2) quoted phrases ("difference-in-differences") - cap at context tier
        for qm in _QUOTED_RE.finditer(text):
            phrase = (qm.group(1) or qm.group(2)).strip()
            if _looks_technical(phrase) and not covered(phrase):
                add(phrase.lower(), tier if tier != "must" else "context",
                    sec_weight * 1.3, _snippet(text, qm.start(), qm.end()), None)
        # 3) capitalized tech tokens (Terraform, ETL) - cap at context tier
        for tm in _TECH_TOKEN_RE.finditer(text):
            tok = tm.group(0)
            if _is_tech_token(tok) and not covered(tok):
                add(tok.lower(), tier if tier != "must" else "context",
                    sec_weight * 1.3, _snippet(text, tm.start(), tm.end()), None)

    # 4) "N+ years of Y" requirements: record the max, and any lexicon skill
    #    named in Y is a genuine requirement -> force must tier.
    years_required: float | None = None
    for m in _YEARS_OF_RE.finditer(jd):
        v = float(m.group(1))
        if v > 40:  # sanity: not a real tenure requirement
            continue
        years_required = v if years_required is None else max(years_required, v)
        y = m.group(2)
        y = re.split(r"[,;]|\s+or\s+|\s+and\s+|\(", y, maxsplit=1)[0].strip()
        if not y:
            continue
        for canonical, aliases in C.SKILL_LEXICON.items():
            hit = None
            for a in aliases:
                hit = C.skill_regex(a).search(y.lower())
                if hit:
                    break
            if hit:
                w = max(items.get(canonical, {}).get("weight", 0.0),
                        2.0 * _rarity(canonical))
                items[canonical] = {
                    "tier": "must", "weight": w,
                    "evidence": _snippet(jd, m.start(), m.end()),
                    "aliases": list(aliases),
                }
    # plain "N years" mentions without "of Y" still count for seniority
    if years_required is None:
        for m in _YEARS_RE.finditer(jd):
            v = float(m.group(1))
            if v > 40:
                continue
            years_required = v if years_required is None else max(years_required, v)

    must = {n for n, i in items.items() if i["tier"] == "must"}
    nice = {n for n, i in items.items() if i["tier"] == "nice"}
    context = {n for n, i in items.items() if i["tier"] == "context"}
    return {"items": items, "must": must, "nice": nice, "context": context,
            "years_required": years_required,
            "signals": len(items)}


def _jd_skills(jd: str) -> tuple[set[str], set[str]]:
    """Return (must_have_skills, nice_to_have_skills) canonical names."""
    ex = _extract_jd(jd)
    return ex["must"], ex["nice"]


def _jd_seniority(jd: str, title: str = "") -> int | None:
    text = f"{title} {jd[:1500]}".lower()
    best: int | None = None
    for kw, rank in C.SENIORITY_KEYWORDS.items():
        if kw in text:
            best = rank if best is None else max(best, rank)
    return best


# role-family keyword sets for title alignment (expanded)
_ROLE_FAMILIES: dict[str, set[str]] = {
    "data_scientist": {"data scientist", "data science"},
    "ml_engineer": {"machine learning engineer", "ml engineer"},
    "applied_scientist": {"applied scientist", "research scientist",
                          "research engineer", "ml scientist", "ai scientist"},
    "data_analyst": {"data analyst", "analytics", "business intelligence",
                     "bi analyst"},
    "data_engineer": {"data engineer", "data engineering", "etl",
                      "analytics engineer"},
    "quant": {"quant", "quantitative", "quantitative researcher", "trader"},
    "software_engineer": {"software engineer", "software developer", "swe",
                         "software development engineer", "sde",
                         "application developer"},
    "backend_engineer": {"backend", "back-end", "api engineer",
                        "services engineer", "server-side", "backend developer"},
    "frontend_engineer": {"frontend", "front-end", "ui engineer",
                         "web developer", "react developer",
                         "frontend developer"},
    "devops_engineer": {"devops", "sre", "site reliability", "platform engineer",
                       "infrastructure engineer", "build engineer"},
    "product_manager": {"product manager", "product management"},
}

# families that are "close enough" for partial title credit
_DATA_CLUSTER = {"data_scientist", "ml_engineer", "applied_scientist",
                 "data_analyst", "data_engineer"}
_ENG_CLUSTER = {"software_engineer", "backend_engineer", "frontend_engineer",
                "devops_engineer"}


def _families_in(text: str) -> set[str]:
    """Role families mentioned in text; handles 'X / Y' titles."""
    found: set[str] = set()
    for part in text.lower().split("/"):
        for fam, kws in _ROLE_FAMILIES.items():
            if any(k in part for k in kws):
                found.add(fam)
    return found


def _profile_role_family(profile: dict) -> str:
    titles = " ".join(e.get("title", "") for e in profile.get("experience", [])).lower()
    skills = set(profile.get("skills", []))
    for fam, kws in _ROLE_FAMILIES.items():
        if any(k in titles for k in kws):
            return fam
    if skills & {"javascript"} or "react" in skills:
        return "frontend_engineer"
    if skills & {"kubernetes", "docker", "terraform"}:
        return "devops_engineer"
    if "deep learning" in skills or "llm" in skills:
        return "ml_engineer"
    if "machine learning" in skills:
        return "data_scientist"
    return "data_analyst"


# one-line pointers for closing a missing must-have skill:
# "learn it" first, "reframe existing experience" second.
_GAP_POINTERS: dict[str, str] = {
    "mlops": "Learn: a short MLOps course plus one Docker + CI deploy project. Reframe: name the deploy steps you already do (containers, pipelines, monitoring) explicitly.",
    "cloud": "Learn: one cloud cert (AWS Solutions Architect Associate is the common pick). Reframe: list the cloud services you have actually touched, even briefly.",
    "dbt": "Learn: dbt's free fundamentals course and one analytics repo. Reframe: your SQL modeling work is the same muscle - say 'dbt-style' only if true, otherwise learn it.",
    "spark": "Learn: a PySpark project over a real dataset (Databricks Community is free). Reframe: large-scale pandas/SQL work shows adjacent data-engineering chops.",
    "deep learning": "Learn: fast.ai or one PyTorch project end to end. Reframe: your classical ML wins still count - position deep learning as the next tool, not a gap in fundamentals.",
    "llm": "Learn: ship one RAG or eval project (LangChain + a small model). Reframe: your NLP/ML modeling experience transfers directly - say so.",
    "nlp": "Learn: one transformer fine-tuning project (Hugging Face course). Reframe: any text-data work you have done counts - name it.",
    "statistics": "Learn: a probability + hypothesis-testing refresher. Reframe: your A/B testing and experiment design work IS statistics - label it that way.",
    "data visualization": "Learn: rebuild one dashboard in the JD's BI tool. Reframe: point to the dashboards and stakeholder-facing charts you have already shipped.",
    "time series": "Learn: one forecasting project (Prophet or statsmodels). Reframe: any trend/seasonality analysis you have done is adjacent - name the methods.",
    "recommendations": "Learn: a small recommender (collaborative filtering on MovieLens). Reframe: ranking, personalization, or matching work you have done is the same family.",
    "optimization": "Learn: one linear-programming or OR-flavored project. Reframe: any resource-allocation or tuning work shows the same thinking.",
    "finance": "Learn: the domain vocabulary (derivatives, risk, valuation basics). Reframe: your modeling rigor transfers - lead with methods, then show domain curiosity.",
    "r": "Learn: port one analysis to R/tidyverse. Reframe: statistical fluency in Python usually satisfies 'R' in practice - say you can pick it up fast, with proof.",
    "excel": "Learn: an afternoon on pivot tables, XLOOKUP, and Power Query. Reframe: you likely already do this - just list it.",
    "sql": "Learn: window functions and query plans on a real dataset. Reframe: surface the SQL you already write inside your bullets.",
    "python": "Learn: there is no shortcut - build fluency with real projects. Reframe: adjacent scripting (R, MATLAB) shows you learn languages fast.",
    "java": "Learn: one Spring or data-processing project. Reframe: JVM-adjacent or strongly-typed language experience transfers.",
    "c++": "Learn: only if the role is truly systems-level; otherwise say so. Reframe: performance-sensitive Python/Cython work is adjacent.",
    "javascript": "Learn: one small React app. Reframe: only matters for frontend-facing roles - otherwise deprioritize.",
    "pandas": "Learn: 10 pandas exercises on messy data. Reframe: you almost certainly use it already - list it.",
    "scikit-learn": "Learn: one end-to-end sklearn pipeline project. Reframe: your XGBoost/modeling work implies it - name it.",
    "xgboost": "Learn: one gradient-boosting project with proper tuning. Reframe: your tree-model experience transfers directly.",
    "product analytics": "Learn: one metrics-deep-dive writeup (funnels, KPIs). Reframe: your experiment and dashboard work is product analytics - label it.",
}


def _gap_pointer(skill: str, profile_skills: set[str]) -> str:
    if skill in _GAP_POINTERS:
        return _GAP_POINTERS[skill]
    toks = set(skill.split())
    for ps in sorted(profile_skills):
        if toks & set(ps.split()):
            return (f"Reframe: your '{ps}' experience is adjacent - name '{skill}' "
                    f"explicitly wherever it applies. Learn: close the rest with a "
                    f"focused project or short course.")
    return (f"Learn: add a small project or short course in '{skill}' and list it "
            f"under skills. Reframe: check whether '{skill}' hides inside work you "
            f"already do, and say so explicitly.")


def _confidence_note(jd: str, ex: dict, jd_level: int | None) -> str:
    n = ex["signals"] + (1 if ex["years_required"] is not None else 0) \
        + (1 if jd_level is not None else 0)
    if len(jd.strip()) < 600 or n < 4:
        return (f"Low parse confidence: thin JD or few recognizable signals "
                f"({n} found). Treat the score as a rough read, not a verdict.")
    if ex["years_required"] is not None and jd_level is not None and n >= 8:
        return (f"High parse confidence: {n} skill/seniority signals, explicit "
                f"{ex['years_required']:g}+ year requirement, and seniority keywords.")
    return f"Medium parse confidence: {n} skill/seniority signals found."


def score_match(profile: dict, jd: str, title: str = "", company: str = "",
                location: str = "") -> dict:
    """Score the JD against the profile. Returns a full breakdown dict."""
    ex = _extract_jd(jd)
    items = ex["items"]
    must, nice, context = ex["must"], ex["nice"], ex["context"]
    pskills = set(profile.get("skills", []))
    prof_text = json_text(profile).lower()

    def _matched(name: str, info: dict) -> bool:
        if info["aliases"] is not None:
            return name in pskills
        # free-form term: look for it in the profile's full text
        return re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])",
                         prof_text) is not None

    matched = {n for n, i in items.items() if _matched(n, i)}
    missing = set(items) - matched
    denom = sum(i["weight"] for i in items.values())
    numer = sum(i["weight"] for n, i in items.items() if n in matched)
    skills_score = round(50 * numer / denom, 1) if denom else 25.0

    # --- seniority: explicit years requirement first, keywords as fallback ---
    jd_years = ex["years_required"]
    jd_level = _jd_seniority(jd, title)
    prof_years = float(profile.get("years_experience") or 0)
    prof_level = {"entry": 0, "junior": 1, "mid": 2, "senior": 3,
                  "lead": 4, "staff": 5, "principal": 6}.get(profile.get("seniority", "mid"), 2)
    if jd_years is not None and prof_years:
        short = jd_years - prof_years
        if short <= 0:
            seniority_score = 25.0
            seniority_note = (f"JD asks for {jd_years:g}+ yrs; you have "
                              f"{prof_years:g} - covered.")
        else:
            seniority_score = max(5.0, round(25 - 5 * short, 1))
            seniority_note = (f"JD asks for {jd_years:g}+ yrs; you have "
                              f"{prof_years:g} ({short:g} yr short).")
        if jd_level is not None and jd_level > prof_level + 1:
            seniority_note += " Title-wise this role also looks like a stretch."
    elif jd_level is None:
        seniority_score = 15.0
        seniority_note = "JD seniority unclear - scored neutrally."
    else:
        gap = abs(prof_level - jd_level)
        seniority_score = [25.0, 20.0, 12.0, 5.0][min(gap, 3)]
        want = C.SENIORITY_LABELS.get(jd_level, "?")
        have = profile.get("seniority", "?")
        seniority_note = f"JD looks '{want}', you read as '{have}'."
        if jd_level > prof_level + 1:
            seniority_note += " This role may be a stretch level-wise."

    # domain keywords: overlap of non-skill substantive words is too noisy;
    # use lexicon-adjacent domain terms instead.
    domain_terms = ["finance", "healthcare", "retail", "marketing", "fraud",
                    "recommendation", "ads", "risk", "supply chain", "genai"]
    jd_low = jd.lower()
    jd_domains = {t for t in domain_terms if t in jd_low}
    prof_domains = {t for t in domain_terms if t in prof_text}
    overlap = jd_domains & prof_domains
    domain_score = round(15 * len(overlap) / max(1, len(jd_domains)), 1) if jd_domains else 8.0

    # --- title alignment via role family ---
    prof_fam = _profile_role_family(profile)
    jd_fams = _families_in(f"{title} {jd[:300]}")
    if prof_fam in jd_fams:
        title_score = 10.0
    elif jd_fams and (
        (prof_fam in _DATA_CLUSTER and jd_fams & _DATA_CLUSTER)
        or (prof_fam in _ENG_CLUSTER and jd_fams & _ENG_CLUSTER)
    ):
        title_score = 6.0
    else:
        title_score = 3.0

    total = round(skills_score + seniority_score + domain_score + title_score, 1)
    if total >= C.SCORE_STRONG_GO:
        verdict, reason = "GO", "Strong fit - worth a tailored application."
    elif total >= C.SCORE_CONDITIONAL_GO:
        verdict, reason = "CONDITIONAL", "Decent fit - apply if the team/mission excites you, and close the gaps below."
    else:
        verdict, reason = "NO-GO", "Weak fit - your time is probably better spent elsewhere."

    gaps: list[str] = []
    for s in sorted(must & missing):
        gaps.append(f"Missing must-have skill: {s}")
    if jd_years is not None and prof_years and jd_years > prof_years + 1:
        gaps.append(f"Seniority gap: role wants {jd_years:g}+ yrs, you have {prof_years:g}")
    elif jd_level is not None and jd_level > prof_level + 1:
        gaps.append(f"Seniority gap: role wants ~{C.SENIORITY_LABELS[jd_level]} level")
    if not overlap and jd_domains:
        gaps.append(f"No overlap on JD domain keywords: {sorted(jd_domains)[:4]}")

    market = _market_snapshot(company, title, location)

    return {
        "score": total,
        "verdict": verdict,
        "verdict_reason": reason,
        "breakdown": {
            "skills": skills_score,
            "seniority": seniority_score,
            "domain": domain_score,
            "title_alignment": title_score,
        },
        "skills_required": sorted(items),
        "skills_matched": sorted(matched),
        "skills_missing": sorted(missing),
        "seniority_note": seniority_note,
        "domain_overlap": sorted(overlap),
        "gaps": gaps,
        "market": market,
        # explainability extras
        "skill_evidence": {n: items[n]["evidence"] for n in sorted(matched)},
        "missing_skill_pointers": {s: _gap_pointer(s, pskills)
                                   for s in sorted(must & missing)},
        "confidence_note": _confidence_note(jd, ex, jd_level),
        "years_required": jd_years,
    }


def json_text(profile: dict) -> str:
    import json as _json
    return _json.dumps(profile)


def _market_snapshot(company: str, title: str, location: str) -> dict | None:
    """Best-effort market pay range for the role (None when unknown)."""
    try:
        from candid import salary
        if not company and not title:
            return None
        return salary.lookup(company=company, title=title, location=location)
    except Exception:
        return None


def render_report(result: dict, company: str = "", title: str = "") -> str:
    """Human-readable match report."""
    b = result["breakdown"]
    lines = [
        f"Match score: {result['score']}/100 - {result['verdict']}",
        result["verdict_reason"],
        result.get("confidence_note", ""),
        "",
        f"  Skills      {b['skills']:>5}/50   matched {len(result['skills_matched'])}/{len(result['skills_required'])}",
        f"  Seniority   {b['seniority']:>5}/25   {result['seniority_note']}",
        f"  Domain      {b['domain']:>5}/15   overlap: {', '.join(result['domain_overlap']) or '-'}",
        f"  Title fit   {b['title_alignment']:>5}/10",
        "",
    ]
    if result["skills_matched"]:
        lines.append("Matched skills (with JD evidence):")
        for s in result["skills_matched"]:
            ev = result.get("skill_evidence", {}).get(s, "")
            lines.append(f"  + {s}" + (f"  e.g. {ev}" if ev else ""))
    if result["skills_missing"]:
        lines.append("Missing skills: " + ", ".join(result["skills_missing"]))
    if result.get("missing_skill_pointers"):
        lines.append("How to close the must-have gaps:")
        for s, tip in result["missing_skill_pointers"].items():
            lines.append(f"  - {s}: {tip}")
    if result["gaps"]:
        lines += ["", "Gaps to close:"] + [f"  * {g}" for g in result["gaps"]]
    m = result.get("market")
    if m and (m.get("p25") or m.get("low")):
        lines += ["", "Market pay (from salary intelligence): " + _fmt_market(m)]
    elif company or title:
        lines += ["", "Market pay: no data yet - import DOL LCA data or parse JDs to build it up."]
    return "\n".join(lines)


def _fmt_market(m: dict) -> str:
    parts = []
    if m.get("p25") and m.get("p75"):
        parts.append(f"${m['p25']:,.0f}-${m['p75']:,.0f}/yr (p25-p75, n={m.get('n', '?')})")
    elif m.get("low") and m.get("high"):
        parts.append(f"${m['low']:,.0f}-${m['high']:,.0f}/yr (posted range)")
    if m.get("source"):
        parts.append(f"[{m['source']}]")
    return " ".join(parts)
