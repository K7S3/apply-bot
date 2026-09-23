"""DS portfolio readiness checker + playbook.

Two entry points:

  1. `check` - score the readiness of a data-science portfolio. The input
     is either:
       a) a small YAML/JSON manifest the user writes, listing projects with
          fields like name, description, tech, data_source, metrics_reported,
          baseline, readme_present, code_quality; or
       b) a path to a local directory of project notes (.md / .txt files),
          which are scanned for the same signals.

     Each project gets a 0-100 score across 8 dimensions plus concrete
     improvement suggestions (missing README, no metrics, no baseline,
     no data lineage note, ...).

  2. `guide` - print the DS portfolio playbook: 3-4 project archetypes and
     what recruiters actually look for.

Usage:
    python -m candid ds-portfolio check candid/data/ds_portfolio_sample.json
    python -m candid ds-portfolio check ~/my-portfolio-notes/
    python -m candid ds-portfolio guide

Everything is local: no network calls, no paid APIs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = [
    "DSPortfolioError",
    "load_manifest",
    "projects_from_directory",
    "score_project",
    "check_projects",
    "render_check",
    "render_guide",
    "PORTFOLIO_GUIDE",
    "DIMENSIONS",
]


class DSPortfolioError(Exception):
    """Raised for portfolio-manifest problems."""


# ---------------------------------------------------------------------------
# scoring dimensions
# ---------------------------------------------------------------------------

# dimension key -> (max points, human label)
DIMENSIONS: dict[str, tuple[int, str]] = {
    "description": (10, "Project summary"),
    "tech": (10, "Tech stack listed"),
    "data_source": (10, "Data source noted"),
    "data_lineage": (10, "Data lineage note"),
    "metrics": (20, "Evaluation metrics reported"),
    "baseline": (15, "Baseline comparison"),
    "readme": (15, "README present"),
    "code_quality": (10, "Code quality signals"),
}


def _present(value) -> bool:
    """True when a manifest field carries real content."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return bool(value)


def normalize_project(raw: dict) -> dict:
    """Normalize one raw manifest/directory project into canonical booleans."""
    raw = dict(raw or {})
    cq = raw.get("code_quality") or {}
    if not isinstance(cq, dict):
        cq = {"tests": _present(cq), "lint": _present(cq), "docs": _present(cq)}
    return {
        "name": str(raw.get("name") or "untitled").strip(),
        "description": str(raw.get("description") or "").strip(),
        "tech": raw.get("tech") or [],
        "data_source": raw.get("data_source"),
        "data_lineage": raw.get("data_lineage"),
        "metrics_reported": raw.get("metrics_reported"),
        "baseline": raw.get("baseline"),
        "readme_present": bool(raw.get("readme_present")),
        "code_quality": {
            "tests": bool(cq.get("tests")),
            "lint": bool(cq.get("lint")),
            "docs": bool(cq.get("docs")),
        },
    }


_SUGGESTIONS: dict[str, str] = {
    "description": ("Write a 2-3 sentence summary: the problem you tackled, "
                    "your approach, and the outcome."),
    "tech": ("List the tech stack (Python, scikit-learn, MLflow, ...) so a "
             "recruiter can scan for skills in seconds."),
    "data_source": ("Say where the data came from (e.g. 'Kaggle Telco churn "
                    "dataset', 'public NYC taxi data')."),
    "data_lineage": ("Add a data lineage note: how the data was collected, "
                     "cleaning decisions, and any known biases or gaps."),
    "metrics": ("Report evaluation metrics on a held-out set (accuracy, F1, "
                "RMSE, ...). Numbers beat adjectives."),
    "baseline": ("Compare against a simple baseline (logistic regression, "
                 "majority class, a rule-based heuristic) to show lift."),
    "readme": ("Add a README.md: problem statement, approach, results table, "
               "and exact steps to reproduce."),
    "tests": "Add tests (pytest) covering data loading and the training entry point.",
    "lint": ("Run a formatter/linter (black, ruff) so the code reads as "
             "production-ready."),
    "docs": "Add docstrings to the main functions and a short module-level overview.",
}


def score_project(project: dict) -> dict:
    """Score one project 0-100. Returns {name, dimensions, total, level, suggestions}."""
    p = normalize_project(project)
    dims: dict[str, dict] = {}
    sugg: list[str] = []

    def mark(key: str, ok: bool, max_pts: int | None = None, extra_sugg: list[str] | None = None):
        maxp = DIMENSIONS[key][0] if max_pts is None else max_pts
        dims[key] = {"score": maxp if ok else 0, "max": maxp, "ok": ok}
        if not ok:
            sugg.extend(extra_sugg or [_SUGGESTIONS[key]])

    mark("description", _present(p["description"]) and len(p["description"]) >= 40)
    mark("tech", _present(p["tech"]))
    mark("data_source", _present(p["data_source"]))
    mark("data_lineage", _present(p["data_lineage"]))
    mark("metrics", _present(p["metrics_reported"]))
    mark("baseline", _present(p["baseline"]))
    mark("readme", p["readme_present"])

    # code quality: tests / lint / docs each worth a third
    cq = p["code_quality"]
    cq_score = sum(1 for k in ("tests", "lint", "docs") if cq[k])
    maxp = DIMENSIONS["code_quality"][0]
    dims["code_quality"] = {
        "score": round(maxp * cq_score / 3, 1),
        "max": maxp,
        "ok": cq_score == 3,
    }
    for k in ("tests", "lint", "docs"):
        if not cq[k]:
            sugg.append(_SUGGESTIONS[k])

    total = round(sum(d["score"] for d in dims.values()), 1)
    level = ("Portfolio-ready" if total >= 90 else
             "Interview-ready" if total >= 70 else
             "Getting there" if total >= 40 else
             "Needs work")
    return {
        "name": p["name"],
        "dimensions": dims,
        "total": total,
        "level": level,
        "suggestions": sugg,
    }


# ---------------------------------------------------------------------------
# manifest loading
# ---------------------------------------------------------------------------

def load_manifest(path: str | Path) -> list[dict]:
    """Load a JSON/YAML portfolio manifest; returns the project list."""
    p = Path(path)
    if not p.exists():
        raise DSPortfolioError(
            f"Manifest not found: {p}\n"
            "Next: copy candid/data/ds_portfolio_sample.json and edit it, "
            "or point `check` at a directory of project notes.")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            try:
                import yaml  # optional; JSON always works
            except ImportError:
                raise DSPortfolioError(
                    f"Cannot read {p}: PyYAML is not installed.\n"
                    "Next: save the manifest as JSON instead "
                    "(see candid/data/ds_portfolio_sample.json), or "
                    "`pip install pyyaml`.")
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise DSPortfolioError(
                f"Unsupported manifest format: {p.suffix} "
                "(use .json, .yaml, or .yml).")
    except DSPortfolioError:
        raise
    except Exception as e:
        raise DSPortfolioError(f"Could not parse {p}: {e}")
    if isinstance(data, dict):
        projects = data.get("projects", [])
    elif isinstance(data, list):
        projects = data
    else:
        raise DSPortfolioError(
            f"{p} must contain a list of projects or a "
            "{'projects': [...]} object.")
    if not isinstance(projects, list) or not projects:
        raise DSPortfolioError(f"{p} contains no projects.")
    if not all(isinstance(x, dict) for x in projects):
        raise DSPortfolioError(f"{p}: every project must be an object/dict.")
    return projects


# ---------------------------------------------------------------------------
# directory-of-notes mode
# ---------------------------------------------------------------------------

_TECH_KEYWORDS = [
    "python", "r language", "sql", "pandas", "numpy", "scikit-learn",
    "sklearn", "pytorch", "tensorflow", "keras", "xgboost", "lightgbm",
    "catboost", "spark", "pyspark", "airflow", "docker", "mlflow",
    "fastapi", "dbt", "snowflake", "bigquery", "huggingface",
    "transformers", "matplotlib", "plotly", "seaborn", "jupyter",
    "streamlit", "onnx", "kubeflow",
]

_METRIC_RE = re.compile(
    r"\b(accuracy|auc|roc[\s-]?auc|f1|f1[\s-]?score|precision|recall|"
    r"rmse|mae|mape|r2|r\^2|r-squared|log[\s-]?loss|silhouette|"
    r"perplexity|bleu|rouge|lift|ctr|cvr|map@k|ndcg)\b"
    r"|\b\d+(?:\.\d+)?\s*%", re.I)

_BASELINE_RE = re.compile(r"\bbaseline\b", re.I)
_LINEAGE_RE = re.compile(
    r"\b(data lineage|lineage|data provenance|provenance|data collection|"
    r"collected from|cleaning|preprocessing steps|data quality)\b", re.I)
_SOURCE_RE = re.compile(
    r"\b(data source|dataset|data set|sourced from|kaggle|uci|open data|"
    r"public data|crm export|warehouse)\b", re.I)
_TESTS_RE = re.compile(r"\b(pytest|unit test|integration test|test_)\b", re.I)
_LINT_RE = re.compile(r"\b(ruff|flake8|black|pylint|mypy|isort)\b", re.I)
_DOCS_RE = re.compile(r"\bdocstring\b", re.I)

_NOTE_EXTS = {".md", ".txt", ".rst"}


def _scan_note(text: str) -> dict:
    low = text.lower()
    tech = sorted({kw for kw in _TECH_KEYWORDS if kw in low})
    paras = [q.strip() for q in re.split(r"\n\s*\n", text.strip()) if q.strip()]
    description = next((q for q in paras if len(q) >= 40), paras[0] if paras else "")
    return {
        "description": description,
        "tech": tech,
        "data_source": bool(_SOURCE_RE.search(low)),
        "data_lineage": bool(_LINEAGE_RE.search(low)),
        "metrics_reported": bool(_METRIC_RE.search(low)),
        "baseline": bool(_BASELINE_RE.search(low)),
        "code_quality": {
            "tests": bool(_TESTS_RE.search(low)),
            "lint": bool(_LINT_RE.search(low)),
            "docs": bool(_DOCS_RE.search(low)),
        },
    }


def projects_from_directory(dirpath: str | Path) -> list[dict]:
    """Turn a directory of project notes (.md/.txt) into project dicts."""
    d = Path(dirpath)
    if not d.is_dir():
        raise DSPortfolioError(f"Not a directory: {d}")
    files = sorted(f for f in d.iterdir()
                   if f.is_file() and f.suffix.lower() in _NOTE_EXTS
                   and not f.name.startswith("."))
    if not files:
        raise DSPortfolioError(
            f"No project notes found in {d} "
            f"(looked for {', '.join(sorted(_NOTE_EXTS))} files).")
    readme_present = any(f.stem.lower() == "readme" for f in files)
    projects = []
    for f in files:
        if f.stem.lower() == "readme":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise DSPortfolioError(f"Could not read {f}: {e}")
        name = f.stem.replace("-", " ").replace("_", " ").strip().title()
        projects.append({
            "name": name or f.stem,
            "readme_present": readme_present,
            **_scan_note(text),
        })
    if not projects:
        raise DSPortfolioError(
            f"{d} contains only a README - add one note file per project.")
    return projects


def check_projects(projects: list[dict]) -> dict:
    """Score a list of projects; returns per-project scores + overall summary."""
    scored = [score_project(p) for p in projects]
    totals = [s["total"] for s in scored]
    weakest = min(scored, key=lambda s: s["total"]) if scored else None
    return {
        "projects": scored,
        "count": len(scored),
        "average": round(sum(totals) / len(totals), 1) if totals else 0,
        "weakest": weakest["name"] if weakest else "",
        "portfolio_level": (
            "Portfolio-ready" if totals and min(totals) >= 70
            else "Interview-ready" if totals and min(totals) >= 50
            else "Work to do"),
    }


def render_check(results: dict) -> str:
    lines = [
        f"DS portfolio check: {results['count']} project(s), "
        f"average {results['average']}/100 - {results['portfolio_level']}",
        "",
    ]
    for s in results["projects"]:
        bar = "#" * int(s["total"] // 10) + "-" * (10 - int(s["total"] // 10))
        lines.append(f"{s['name']}: {s['total']}/100 [{bar}] {s['level']}")
        missing = [f"{k} ({d['score']:.0f}/{d['max']})"
                   for k, d in s["dimensions"].items() if not d["ok"]]
        if missing:
            lines.append(f"  gaps: {', '.join(missing)}")
    lines.append("")
    for s in results["projects"]:
        if s["suggestions"]:
            lines.append(f"Fix next for '{s['name']}':")
            for sug in s["suggestions"][:4]:
                lines.append(f"  - {sug}")
            lines.append("")
    if results["weakest"]:
        lines.append(f"Weakest link: {results['weakest']} - fix it first; "
                     "recruiters judge a portfolio by its weakest project.")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# playbook
# ---------------------------------------------------------------------------

PORTFOLIO_GUIDE = """\
DS PORTFOLIO PLAYBOOK
=====================

Recruiters spend ~60 seconds on a portfolio. They scan for: a README they can
skim, a results table with numbers, and proof you can ship. Four project
archetypes cover what DS interviews actually test:

1. END-TO-END ML PIPELINE
   Build: problem framing -> data -> features -> model -> evaluation ->
   deployment or a reproducible training script.
   Example: churn prediction on public telecom data, served behind a small API.
   Recruiters look for:
   - a baseline you beat (logistic regression, majority class, a heuristic)
   - metrics on a held-out set, not just training loss
   - one paragraph on what you would do with 10x more data or latency limits

2. EXPERIMENTATION / CAUSAL INFERENCE STUDY
   Build: an A/B test analysis - power calculation, SRM check, variance
   reduction (CUPED), and a ship/no-ship recommendation.
   Example: re-analyze a public experiment dataset; show the naive result vs.
   the corrected one.
   Recruiters look for:
   - statistical rigor: you checked the assumptions, not just ran a t-test
   - a decision a real team could act on
   - honest discussion of threats to validity

3. NLP / LLM PRODUCT
   Build: a retrieval-augmented QA bot, classifier, or summarizer over a
   real corpus, with an evaluation harness.
   Example: support-ticket triage with an LLM, evaluated against 100
   hand-labeled tickets.
   Recruiters look for:
   - evals beyond vibes: a labeled set, error analysis, failure buckets
   - cost/latency numbers (tokens per query, p95 latency)
   - guardrails: what it refuses, where it hallucinates

4. DATA STORYTELLING / ANALYTICS DEEP-DIVE
   Build: take messy public data, clean it, and find an insight a stakeholder
   would act on. One great chart beats ten mediocre ones.
   Example: NYC taxi or 311 data -> a pricing or operations recommendation.
   Recruiters look for:
   - SQL fluency on real, ugly data
   - a clear recommendation, not just exploration
   - communication: can a non-technical reader follow it?

THE 60-SECOND SCAN (what makes a project pass)
- README.md: problem, approach, results table, how to reproduce
- numbers: metrics, baselines, lift - in a table, not buried in prose
- data lineage: where the data came from, what you cleaned, known biases
- reproducibility: requirements file, one command to rerun the key result
- scope honesty: 3 polished projects beat 8 half-finished notebooks

ANTI-PATTERNS
- Titanic / Iris with no twist: pick datasets with a real question attached
- accuracy-only reporting on imbalanced data
- "I built a model" with no baseline and no held-out evaluation
- notebooks full of dead cells and no narrative markdown
- private repos with no screenshots: if code can't be public, show results

NEXT STEP
Run: python -m candid ds-portfolio check <manifest-or-notes-dir>
See: candid/data/ds_portfolio_sample.json for the manifest format.
"""


def render_guide() -> str:
    return PORTFOLIO_GUIDE
