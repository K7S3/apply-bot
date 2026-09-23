"""Shared configuration for the candid package.

All user data lives under DATA_DIR (git-ignored). Everything is
config-driven: edit the constants or data files here to extend behavior.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


def _data_dir() -> Path:
    """User data dir. Overridable via CANDID_DATA_DIR (used by tests)."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / "candid_data"


def _config_dir() -> Path:
    """Per-user config dir. Overridable via CANDID_CONFIG_DIR."""
    override = os.environ.get("CANDID_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "candid"


# --- user data (git-ignored) -------------------------------------------------
DATA_DIR = _data_dir()
CONFIG_DIR = _config_dir()
PROFILE_PATH = DATA_DIR / "profile.json"
TRACKER_PATH = DATA_DIR / "tracker.json"
OFFERS_PATH = DATA_DIR / "offers.json"
TEMPLATES_USER_DIR = CONFIG_DIR / "packs"  # installed template packs (<name>@<version>)
SALARY_DB = DATA_DIR / "salary.db"
PREP_PACKS_DIR = DATA_DIR / "prep_packs"
TAILOR_DIR = DATA_DIR / "tailored"
GMAIL_PROPOSALS_PATH = DATA_DIR / "gmail_proposals.json"

# --- sample data (committed; clearly fictional) ------------------------------
SAMPLES_DIR = PROJECT_ROOT / "samples" / "candid"

# --- application tracker statuses --------------------------------------------
STATUSES = [
    "saved",
    "applied",
    "selected_for_interview",
    "rejected",
    "offer",
    "withdrawn",
]
# Responses = the company got back to you in any substantive way.
RESPONSE_STATUSES = {"selected_for_interview", "rejected", "offer"}

# --- match scoring ------------------------------------------------------------
SCORE_STRONG_GO = 70
SCORE_CONDITIONAL_GO = 50

# --- seniority mapping (title keywords -> level rank) ---------------------------
SENIORITY_KEYWORDS: dict[str, int] = {
    "intern": 0,
    "new grad": 0,
    "junior": 1,
    "associate": 2,
    "mid": 2,
    "senior": 3,
    "sr.": 3,
    "sr ": 3,
    "lead": 4,
    "staff": 5,
    "principal": 6,
    "distinguished": 7,
    "director": 7,
    "vp": 8,
    "vice president": 8,
}
SENIORITY_LABELS = {
    0: "entry",
    1: "junior",
    2: "mid",
    3: "senior",
    4: "lead",
    5: "staff",
    6: "principal",
    7: "director+",
    8: "vp+",
}

# --- skill lexicon for JD/profile matching ------------------------------------
# Canonical skill -> aliases. Extend freely.
SKILL_LEXICON: dict[str, list[str]] = {
    "python": ["python", "py"],
    "sql": ["sql", "postgres", "mysql", "bigquery", "snowflake", "redshift"],
    "r": ["\\br\\b", "r programming"],
    "machine learning": ["machine learning", "ml"],
    "deep learning": ["deep learning", "neural network", "pytorch", "tensorflow", "keras", "jax"],
    "llm": ["llm", "large language model", "gpt", "claude", "gemini", "rag", "langchain", "langgraph", "prompt engineering", "fine-tuning", "genai", "generative ai"],
    "nlp": ["nlp", "natural language processing", "transformer", "bert"],
    "statistics": ["statistics", "statistical", "hypothesis testing", "a/b test", "ab test", "experimentation", "causal inference"],
    "data visualization": ["tableau", "power bi", "looker", "d3", "matplotlib", "visualization", "dashboard"],
    "spark": ["spark", "pyspark", "hadoop", "mapreduce"],
    "mlops": ["mlops", "model deployment", "docker", "kubernetes", "ci/cd", "airflow", "kubeflow", "sagemaker", "vertex ai"],
    "cloud": ["aws", "azure", "gcp", "cloud"],
    "excel": ["excel", "vba", "sheets"],
    "java": ["java"],
    "c++": ["c++"],
    "javascript": ["javascript", "typescript", "react"],
    "xgboost": ["xgboost", "gradient boosting", "gbm", "lightgbm", "catboost"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "pandas": ["pandas", "numpy"],
    "dbt": ["dbt"],
    "product analytics": ["product analytics", "metrics", "kpi", "funnel"],
    "time series": ["time series", "forecasting", "arima", "prophet"],
    "recommendations": ["recommendation", "recommender", "collaborative filtering"],
    "optimization": ["optimization", "linear programming", "operations research"],
    "finance": ["finance", "financial modeling", "valuation", "derivatives", "options"],
}


@lru_cache(maxsize=1024)
def skill_regex(alias: str) -> "re.Pattern[str]":
    """Compile a skill alias into a safe regex.

    Plain words get word boundaries (so ``excel`` doesn't match
    "excellent" and ``py`` doesn't match "happy"); symbols like ``c++``
    are escaped literally.

    Compiled patterns are cached — this is called in hot loops during
    JD scoring, so recompiling every call was a real drag.
    """
    esc = re.escape(alias)
    if alias[:1].isalnum() or alias[:1] == "_":
        esc = r"\b" + esc
    if alias[-1:].isalnum() or alias[-1:] == "_":
        esc = esc + r"\b"
    return re.compile(esc)


def ensure_data_dirs() -> None:
    """Create the git-ignored user data directories if missing."""
    for d in (DATA_DIR, PREP_PACKS_DIR, TAILOR_DIR):
        d.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Module-level logger. Level from CANDID_LOG_LEVEL (default WARNING)."""
    logger = logging.getLogger(f"candid.{name}")
    if not logging.getLogger("candid").handlers:
        logging.basicConfig(
            level=os.environ.get("CANDID_LOG_LEVEL", "WARNING").upper(),
            format="%(levelname)s [candid.%(name)s] %(message)s",
        )
    return logger
