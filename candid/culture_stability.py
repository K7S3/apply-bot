"""Company culture decoder: stability and trajectory signals.

Turns raw, offline data (WARN layoff filings, DOL H-1B LCA disclosure rows,
curated job postings) into small, source-attributed signal dicts. Two entry
points:

  stability(company, datasets)   -> observational signals about how stable
                                    the company looks right now.
  trajectory(company, datasets)  -> directional signals about where the
                                    company seems to be headed.

Both take ``company`` (a company name string) and ``datasets``, a dict that
may hold any of the keys "warn", "lca", "jobs", each a list of row dicts or
None. The functions are fully defensive: missing or empty datasets produce
a signal with value None and a note of "insufficient data", never a crash
and never invented numbers. Malformed rows (missing company, unparseable
dates, non-dict entries) are skipped quietly and tallied in the signal
note when any were dropped.

Signal shape:
    {"signal": str, "value": str | None, "source": str,
     "as_of": str | None, "note": str}   # "note" optional

Every signal carries a "source" label such as "WARN filings",
"LCA disclosure data", or "curated job postings"; "as_of" holds an
ISO date whenever the signal is time-bounded.

Language rule: trajectory signals are observational only ("hiring
velocity increasing", "layoff filings present in last 12 months",
"median offered wage stable"). Never a definitive causal claim about
the company succeeding or failing.

Usage:
    from candid import culture_stability as cs
    sigs = cs.stability("Acme Corp", {"warn": warn_rows, "lca": lca_rows,
                                      "jobs": job_rows})
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C

# Reuse salary's company normalizer when available; fall back to a local
# copy so this module never breaks if salary moves.
try:
    from candid import salary as _salary  # noqa: F401

    _norm_impl = getattr(_salary, "_norm", None)
except ImportError:  # pragma: no cover - salary is part of the package
    _norm_impl = None


def _norm(s: object) -> str:
    """Normalize a company name for comparison."""
    if _norm_impl is not None:
        try:
            return _norm_impl(s)
        except Exception:
            pass
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


# --- dataset keys, row field aliases ------------------------------------------

DATASET_KEYS = ("warn", "lca", "jobs")

_WARN_DATE_KEYS = ("notice_date", "filed_date", "effective_date", "date",
                   "filing_date", "warn_date")
_WARN_COMPANY_KEYS = ("company", "employer", "employer_name", "company_name")
_WARN_WORKERS_KEYS = ("workers", "affected", "num_workers", "employees",
                      "affected_workers", "number_of_workers")

_LCA_DATE_KEYS = ("case_date", "filed_date", "submit_date", "date",
                  "decision_date", "received_date", "fy")
_LCA_COMPANY_KEYS = ("company", "employer_name", "employer", "company_name")
_LCA_WAGE_KEYS = ("wage", "wage_from", "offered_wage", "wage_rate",
                  "prevailing_wage", "salary", "base_wage")

_JOBS_DATE_KEYS = ("posted_date", "date", "created_at", "scraped_date",
                   "published_date", "posted_on")
_JOBS_COMPANY_KEYS = ("company", "employer", "company_name")

SOURCES = {
    "warn": "WARN filings",
    "lca": "LCA disclosure data",
    "jobs": "curated job postings",
}

# Minimum rows for a trend comparison to be worth reporting; below this the
# signal carries "insufficient data" instead of a noisy direction.
_MIN_TREND_ROWS = 3
_INCREASE_RATIO = 1.25
_DECREASE_RATIO = 0.75
_WAGE_STABLE_BAND = 0.05  # +/-5% counts as stable

# Candidate data-dir filenames used by the DATA_DIR fallback scan.
_WARN_GLOBS = ("warn*.csv", "warn*.json", "layoffs*.csv", "layoffs*.json")
_LCA_GLOBS = ("lca*.csv", "h1b*.csv", "H-1B*.csv")
_JOBS_GLOBS = ("jobs*.json", "jobs*.csv", "postings*.json", "postings*.csv")


# --- row helpers --------------------------------------------------------------

def _rows(datasets: object, key: str) -> list:
    """Return the row list for a dataset key; [] when missing/None/wrong type."""
    if not isinstance(datasets, dict):
        return []
    rows = datasets.get(key)
    if not rows:
        return []
    if isinstance(rows, dict):
        return list(rows.values())
    if isinstance(rows, (list, tuple)):
        return list(rows)
    return []


def _get(row: dict, keys: tuple[str, ...]) -> object:
    """First non-empty value found under any of the given keys."""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _company_of(row: dict, keys: tuple[str, ...]) -> str:
    v = _get(row, keys)
    return _norm(v) if v is not None else ""


def _match_company(row_company: str, target: str) -> bool:
    """Normalized exact or containment match (target may omit suffixes)."""
    if not row_company or not target:
        return False
    return row_company == target or target in row_company


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m",
)


def _parse_date(raw: object) -> date | None:
    """Parse a date from common formats, a datetime, or a fiscal year."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    # FY2024 / 2024 -> use Jan 1 of that year
    m = re.fullmatch(r"(?:FY|fy)?\s*(\d{4})", text)
    if m:
        return date(int(m.group(1)), 1, 1)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:19] if "T" in text or " " in text
                                     else text, fmt).date()
        except ValueError:
            continue
    try:  # ISO with timezone or other separators, last resort
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_number(raw: object) -> float | None:
    """Parse a number from int/float/str (strips $, commas); None on failure."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = re.sub(r"[^\d.\-]", "", str(raw))
    if not text or text in ("-", ".", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _insufficient(signal: str, source: str, as_of: str | None = None,
                  note: str = "insufficient data") -> dict:
    return {"signal": signal, "value": None, "source": source,
            "as_of": as_of, "note": note}


# --- dataset extraction -------------------------------------------------------

def _warn_rows_for(company: str, datasets: object) -> tuple[list[dict], int]:
    """(matched WARN rows, malformed-row count) for the company."""
    target = _norm(company)
    matched: list[dict] = []
    bad = 0
    for row in _rows(datasets, "warn"):
        if not isinstance(row, dict):
            bad += 1
            continue
        if not _match_company(_company_of(row, _WARN_COMPANY_KEYS), target):
            continue
        d = _parse_date(_get(row, _WARN_DATE_KEYS))
        if d is None:
            bad += 1
            continue
        workers = _parse_number(_get(row, _WARN_WORKERS_KEYS))
        matched.append({"date": d, "workers": workers})
    return matched, bad


def _dated_rows_for(company: str, datasets: object, key: str,
                    date_keys: tuple[str, ...],
                    company_keys: tuple[str, ...]) -> tuple[list[date], int]:
    """(matched dates, malformed-row count) for the company from a dataset."""
    target = _norm(company)
    matched: list[date] = []
    bad = 0
    for row in _rows(datasets, key):
        if not isinstance(row, dict):
            bad += 1
            continue
        if not _match_company(_company_of(row, company_keys), target):
            continue
        d = _parse_date(_get(row, date_keys))
        if d is None:
            bad += 1
            continue
        matched.append(d)
    return matched, bad


def _lca_wage_rows_for(company: str, datasets: object) -> tuple[list[tuple[date, float]], int]:
    """(matched (date, wage) rows, malformed-row count) from LCA data."""
    target = _norm(company)
    matched: list[tuple[date, float]] = []
    bad = 0
    for row in _rows(datasets, "lca"):
        if not isinstance(row, dict):
            bad += 1
            continue
        if not _match_company(_company_of(row, _LCA_COMPANY_KEYS), target):
            continue
        d = _parse_date(_get(row, _LCA_DATE_KEYS))
        w = _parse_number(_get(row, _LCA_WAGE_KEYS))
        if d is None or w is None or w <= 0:
            bad += 1
            continue
        matched.append((d, w))
    return matched, bad


def _period_counts(dates: list[date], ref: date,
                   months: int = 6) -> tuple[int, int]:
    """(recent-period count, prior-period count) of dates relative to ref."""
    start_recent = ref - timedelta(days=30 * months)
    start_prior = ref - timedelta(days=30 * 2 * months)
    recent = sum(1 for d in dates if start_recent < d <= ref)
    prior = sum(1 for d in dates if start_prior < d <= start_recent)
    return recent, prior


def _direction(recent: int, prior: int) -> str | None:
    """Directional word from two period counts; None when too thin."""
    total = recent + prior
    if total < _MIN_TREND_ROWS:
        return None
    if prior == 0:
        return "increasing" if recent > 0 else "steady"
    ratio = recent / prior
    if ratio >= _INCREASE_RATIO:
        return "increasing"
    if ratio <= _DECREASE_RATIO:
        return "decreasing"
    return "steady"


# --- DATA_DIR fallback ----------------------------------------------------------

def _load_table_file(path: Path) -> list[dict]:
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = list(data.values())
            return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as fh:
                return [dict(r) for r in csv.DictReader(fh)]
    except (OSError, ValueError, csv.Error):
        return []
    return []


def load_datasets_from_data_dir() -> dict:
    """Scan config.DATA_DIR for WARN/LCA/jobs files; graceful on absence.

    Looks for warn*.csv/json, lca*/h1b*.csv, jobs*/postings*.json/csv under
    DATA_DIR. Returns {"warn": [...], "lca": [...], "jobs": [...]}, with []
    for any kind not found. Purely offline, never raises on bad files.
    """
    out = {"warn": [], "lca": [], "jobs": []}
    globs = (("warn", _WARN_GLOBS), ("lca", _LCA_GLOBS), ("jobs", _JOBS_GLOBS))
    try:
        data_dir = Path(C.DATA_DIR)
        if not data_dir.is_dir():
            return out
        for key, patterns in globs:
            for pat in patterns:
                for path in sorted(data_dir.glob(pat)):
                    out[key].extend(_load_table_file(path))
    except OSError:
        pass
    return out


# --- stability ------------------------------------------------------------------

def stability(company: str, datasets: object) -> list[dict]:
    """Observational stability signals for a company.

    Signals:
      - layoff filings in last 12 months (WARN filings)
      - most recent layoff filing date (WARN filings)
      - LCA filing volume, recent 6 months vs prior 6 (LCA disclosure data)
      - curated job posting volume, recent 6 months vs prior 6 (job postings)

    Any missing/empty dataset yields a signal with value None and note
    "insufficient data". Malformed rows are skipped; when any were skipped
    the signal note says how many.
    """
    if not company or not _norm(company):
        return [_insufficient("company stability overview",
                              "no source", None, "no company name provided")]
    today = date.today()
    as_of = today.isoformat()
    signals: list[dict] = []
    year_ago = today - timedelta(days=365)

    # --- WARN layoff filings --------------------------------------------------
    warn, warn_bad = _warn_rows_for(company, datasets)
    recent_warn = [w for w in warn if w["date"] > year_ago]
    if not warn and warn_bad == 0 and not _rows(datasets, "warn"):
        signals.append(_insufficient("layoff filings in last 12 months",
                                     SOURCES["warn"], as_of))
        signals.append(_insufficient("most recent layoff filing date",
                                     SOURCES["warn"], as_of))
    else:
        total_workers = sum(w["workers"] for w in recent_warn
                            if w["workers"] is not None)
        if recent_warn:
            value = (f"{len(recent_warn)} filing(s) in last 12 months"
                     + (f", {int(total_workers)} workers affected"
                        if total_workers else ""))
            note = (f"{warn_bad} malformed row(s) skipped"
                    if warn_bad else "source: public WARN filings")
        else:
            value = "0 filings in last 12 months"
            note = (f"{warn_bad} malformed row(s) skipped"
                    if warn_bad else "source: public WARN filings")
        signals.append({"signal": "layoff filings in last 12 months",
                        "value": value, "source": SOURCES["warn"],
                        "as_of": as_of, "note": note})
        if warn:
            latest = max(w["date"] for w in warn)
            signals.append({"signal": "most recent layoff filing date",
                            "value": latest.isoformat(),
                            "source": SOURCES["warn"], "as_of": as_of,
                            "note": "latest filing on record"})
        else:
            signals.append(_insufficient("most recent layoff filing date",
                                         SOURCES["warn"], as_of))

    # --- LCA filing volume ----------------------------------------------------
    lca_dates, lca_bad = _dated_rows_for(company, datasets, "lca",
                                         _LCA_DATE_KEYS, _LCA_COMPANY_KEYS)
    if not lca_dates:
        signals.append(_insufficient("LCA filing volume (recent vs prior 6mo)",
                                     SOURCES["lca"], as_of))
    else:
        recent, prior = _period_counts(lca_dates, today)
        note = (f"{lca_bad} malformed row(s) skipped"
                if lca_bad else "counts from disclosure rows with dates")
        signals.append({"signal": "LCA filing volume (recent vs prior 6mo)",
                        "value": f"recent 6 months: {recent}, prior 6 months: {prior}",
                        "source": SOURCES["lca"], "as_of": as_of, "note": note})

    # --- curated job posting volume -------------------------------------------
    job_dates, job_bad = _dated_rows_for(company, datasets, "jobs",
                                         _JOBS_DATE_KEYS, _JOBS_COMPANY_KEYS)
    if not job_dates:
        signals.append(_insufficient("curated job posting volume (recent vs prior 6mo)",
                                     SOURCES["jobs"], as_of))
    else:
        recent, prior = _period_counts(job_dates, today)
        note = (f"{job_bad} malformed row(s) skipped"
                if job_bad else "counts from curated postings with dates")
        signals.append({"signal": "curated job posting volume (recent vs prior 6mo)",
                        "value": f"recent 6 months: {recent}, prior 6 months: {prior}",
                        "source": SOURCES["jobs"], "as_of": as_of, "note": note})

    return signals


# --- trajectory -----------------------------------------------------------------

def trajectory(company: str, datasets: object) -> list[dict]:
    """Directional trajectory signals for a company.

    All values are observational directions ("hiring velocity increasing",
    "layoff filings present in last 12 months", "median offered wage
    stable") or None with an "insufficient data" note. No causal claims
    are made about why a direction moved.

    Signals:
      - layoff activity (WARN filings, last 12 months)
      - LCA filing velocity direction (LCA disclosure data)
      - hiring velocity direction (curated job postings)
      - median offered wage direction (LCA disclosure data)
    """
    if not company or not _norm(company):
        return [_insufficient("company trajectory overview",
                              "no source", None, "no company name provided")]
    today = date.today()
    as_of = today.isoformat()
    signals: list[dict] = []
    year_ago = today - timedelta(days=365)

    # --- layoff activity ------------------------------------------------------
    warn, warn_bad = _warn_rows_for(company, datasets)
    if not warn and not _rows(datasets, "warn"):
        signals.append(_insufficient("layoff activity", SOURCES["warn"], as_of))
    else:
        recent_warn = [w for w in warn if w["date"] > year_ago]
        value = ("layoff filings present in last 12 months"
                 if recent_warn else "no layoff filings in last 12 months")
        signals.append({"signal": "layoff activity", "value": value,
                        "source": SOURCES["warn"], "as_of": as_of,
                        "note": ("observational only; filings are public "
                                 "notices, not a verdict on the company")})

    # --- LCA filing velocity --------------------------------------------------
    lca_dates, lca_bad = _dated_rows_for(company, datasets, "lca",
                                         _LCA_DATE_KEYS, _LCA_COMPANY_KEYS)
    if not lca_dates:
        signals.append(_insufficient("LCA filing velocity", SOURCES["lca"], as_of))
    else:
        recent, prior = _period_counts(lca_dates, today)
        direction = _direction(recent, prior)
        signals.append({
            "signal": "LCA filing velocity",
            "value": (f"LCA filing volume {direction}"
                      if direction else None),
            "source": SOURCES["lca"], "as_of": as_of,
            "note": ("insufficient data" if direction is None
                     else f"recent 6mo={recent}, prior 6mo={prior}"),
        })

    # --- hiring velocity ------------------------------------------------------
    job_dates, job_bad = _dated_rows_for(company, datasets, "jobs",
                                         _JOBS_DATE_KEYS, _JOBS_COMPANY_KEYS)
    if not job_dates:
        signals.append(_insufficient("hiring velocity", SOURCES["jobs"], as_of))
    else:
        recent, prior = _period_counts(job_dates, today)
        direction = _direction(recent, prior)
        signals.append({
            "signal": "hiring velocity",
            "value": (f"hiring velocity {direction}"
                      if direction else None),
            "source": SOURCES["jobs"], "as_of": as_of,
            "note": ("insufficient data" if direction is None
                     else f"recent 6mo={recent}, prior 6mo={prior}"),
        })

    # --- median offered wage --------------------------------------------------
    wage_rows, wage_bad = _lca_wage_rows_for(company, datasets)
    if not wage_rows:
        signals.append(_insufficient("median offered wage", SOURCES["lca"], as_of))
    else:
        start_recent = today - timedelta(days=180)
        recent_w = [w for d, w in wage_rows if start_recent < d <= today]
        prior_w = [w for d, w in wage_rows
                   if today - timedelta(days=360) < d <= start_recent]
        med_recent = _median(recent_w)
        med_prior = _median(prior_w)
        if med_recent is None or med_prior is None or med_prior <= 0:
            signals.append(_insufficient("median offered wage",
                                         SOURCES["lca"], as_of,
                                         "insufficient wage data in one or "
                                         "both periods"))
        else:
            change = (med_recent - med_prior) / med_prior
            if abs(change) <= _WAGE_STABLE_BAND:
                value = "median offered wage stable"
            elif change > 0:
                value = "median offered wage rising"
            else:
                value = "median offered wage declining"
            signals.append({"signal": "median offered wage", "value": value,
                            "source": SOURCES["lca"], "as_of": as_of,
                            "note": (f"recent median ${med_recent:,.0f} vs prior "
                                     f"median ${med_prior:,.0f}")})

    return signals
