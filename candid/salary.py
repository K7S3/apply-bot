"""Salary intelligence: local SQLite database of pay data.

Two kinds of records, both with source attribution:
  1. Posted ranges parsed from job descriptions ("source='job_post'").
  2. DOL H-1B LCA disclosure rows imported from the public CSV files
     ("source='dol_lca'").

Schema (table `ranges`):
    id, company, title, location, low, high, currency,
    source, source_detail, retrieved_at

Usage:
    python -m candid salary lookup --company "Capital One" --title "Data Scientist" --location "New York"
    python -m candid salary import-lca ~/downloads/H-1B_Disclosure_Data_FY2024.csv
    python -m candid salary parse-range --company X --role Y --text "$120,000 - $150,000 a year"
"""

from __future__ import annotations

import csv
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from candid import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    low REAL NOT NULL,
    high REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    pay_period TEXT DEFAULT 'year',
    source TEXT NOT NULL,            -- 'job_post' | 'dol_lca' | 'manual'
    source_detail TEXT DEFAULT '',   -- URL, file name, case number...
    retrieved_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ranges_company ON ranges(company);
CREATE INDEX IF NOT EXISTS idx_ranges_title ON ranges(title);
CREATE INDEX IF NOT EXISTS idx_ranges_location ON ranges(location);
"""


class SalaryError(Exception):
    """Raised for salary DB problems."""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    C.ensure_data_dirs()
    db = Path(path) if path else C.SALARY_DB
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA)
    return conn


def add_range(company: str, title: str, low: float, high: float, *,
              location: str = "", currency: str = "USD", pay_period: str = "year",
              source: str = "manual", source_detail: str = "",
              path: str | Path | None = None) -> int:
    """Insert one pay range. Returns the row id."""
    if not company or not title:
        raise SalaryError("Salary ranges need at least company and title.")
    if low <= 0 or high <= 0 or low > high:
        raise SalaryError(f"Invalid range: low={low}, high={high}.")
    conn = connect(path)
    cur = conn.execute(
        """INSERT INTO ranges
           (company, title, location, low, high, currency, pay_period,
            source, source_detail, retrieved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (company.strip(), title.strip(), location.strip(), low, high,
         currency, pay_period, source, source_detail, date.today().isoformat()),
    )
    conn.commit()
    row_id = cur.lastrowid or 0
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# parsing posted ranges from JD text
# ---------------------------------------------------------------------------

_MONEY = r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kK])?"
# a range looks like: $120k - $150k | 120,000 to 150,000 per year | salary range: $90K–$110K
_RANGE_RE = re.compile(
    _MONEY + r"\s*(?:-|–|—|to)\s*" + _MONEY
    + r"(?:\s*(?:per\s+)?(year|yr|annual|annum|hour|hr|month|mo|week|wk))?",
    re.I,
)
_PERIOD_RE = re.compile(r"per\s+(year|yr|annual|annum|hour|hr|month|mo|week|wk)", re.I)

_PERIOD_MULT = {"year": 1, "yr": 1, "annual": 1, "annum": 1,
                "month": 12, "mo": 12, "week": 52, "wk": 52, "hour": 2080, "hr": 2080}


def _to_num(raw: str, k: str) -> float:
    n = float(raw.replace(",", ""))
    return n * 1000 if k else n


def parse_posted_range(text: str) -> dict | None:
    """Extract the first plausible $low–$high range from JD text.

    Returns {low, high, pay_period} annualized to USD/year, or None.
    """
    for m in _RANGE_RE.finditer(text):
        num1, k1, num2, k2, period = m.groups()
        period = (period or "").lower()
        if not period:
            pm = _PERIOD_RE.search(text[max(0, m.start() - 60):m.end() + 30])
            period = pm.group(1).lower() if pm else "year"
        mult = _PERIOD_MULT.get(period, 1)
        low = _to_num(num1, k1) * mult
        high = _to_num(num2, k2) * mult
        if low <= 0 or high <= 0 or low > high:
            continue
        if high > 5_000_000 or low < 10_000 and mult == 1:
            # sanity: ignore fragments like years "2024 - 2025"
            continue
        return {"low": round(low, 2), "high": round(high, 2), "pay_period": "year"}
    return None


def ingest_posted_range(company: str, title: str, jd_text: str, *,
                        location: str = "", source_detail: str = "",
                        path: str | Path | None = None) -> dict | None:
    """Parse a JD's disclosed range and store it. Returns the parsed range or None."""
    parsed = parse_posted_range(jd_text)
    if not parsed:
        return None
    add_range(company, title, parsed["low"], parsed["high"], location=location,
              pay_period="year", source="job_post", source_detail=source_detail, path=path)
    return parsed


# ---------------------------------------------------------------------------
# DOL H-1B LCA disclosure import
# ---------------------------------------------------------------------------

# DOL column names drift by year; map every known variant to a canonical field.
_LCA_COLUMNS: dict[str, list[str]] = {
    "company": ["EMPLOYER_NAME", "Employer Name", "EMPLOYER_NAME "],
    "title": ["JOB_TITLE", "Job Title", "SOC_TITLE"],
    "city": ["WORKSITE_CITY", "Worksite City", "EMPLOYER_CITY"],
    "state": ["WORKSITE_STATE", "Worksite State", "EMPLOYER_STATE"],
    "worksite": ["WORKSITE", "Worksite", "WORKSITE_ADDRESS"],
    "wage_from": ["WAGE_RATE_OF_PAY_FROM", "Wage Rate of Pay From", "WAGE_RATE_OF_PAY"],
    "wage_to": ["WAGE_RATE_OF_PAY_TO", "Wage Rate of Pay To"],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "Wage Unit of Pay", "PAY_UNIT"],
    "case_no": ["CASE_NUMBER", "Case Number"],
    "status": ["CASE_STATUS", "Case Status"],
}


def _pick(row: dict, field: str) -> str:
    for variant in _LCA_COLUMNS[field]:
        for key in row:
            if key.strip().upper() == variant.strip().upper():
                return (row[key] or "").strip()
    return ""


_WAGE_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _parse_wage(raw: str) -> float | None:
    m = _WAGE_RE.search(raw.replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


_UNIT_MULT = {"year": 1, "yr": 1, "annual": 1, "hour": 2080, "hr": 2080,
              "week": 52, "wk": 52, "month": 12, "mo": 12, "bi-weekly": 26}


def import_lca(csv_path: str | Path, *, path: str | Path | None = None,
               only_certified: bool = True, limit: int | None = None,
               progress_every: int = 50000) -> dict:
    """Import a DOL H-1B disclosure CSV. Returns {imported, skipped} counts.

    Never executes anything from the file — pure CSV parsing.
    """
    p = Path(csv_path)
    if not p.exists():
        raise SalaryError(f"LCA file not found: {p}")
    conn = connect(path)
    imported = skipped = 0
    now = datetime.now().isoformat(timespec="seconds")
    with p.open(newline="", encoding="utf-8", errors="replace") as f:
        # sniff delimiter; DOL files are comma-separated
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for n, row in enumerate(reader, 1):
            if limit and n > limit:
                break
            if progress_every and n % progress_every == 0:
                print(f"  ... {n} rows scanned ({imported} imported)")
            try:
                if only_certified:
                    status = _pick(row, "status").upper()
                    if status and "CERTIFIED" not in status:
                        skipped += 1
                        continue
                company = _pick(row, "company")
                title = _pick(row, "title")
                wage_from = _parse_wage(_pick(row, "wage_from"))
                if not company or not title or not wage_from:
                    skipped += 1
                    continue
                wage_to = _parse_wage(_pick(row, "wage_to")) or wage_from
                unit = _pick(row, "wage_unit").lower()
                mult = 1
                for key, m in _UNIT_MULT.items():
                    if key in unit:
                        mult = m
                        break
                low, high = sorted((wage_from * mult, wage_to * mult))
                city = _pick(row, "city")
                state = _pick(row, "state")
                location = ", ".join(x for x in (city, state) if x) or _pick(row, "worksite")
                conn.execute(
                    """INSERT INTO ranges
                       (company, title, location, low, high, currency, pay_period,
                        source, source_detail, retrieved_at)
                       VALUES (?, ?, ?, ?, ?, 'USD', 'year', 'dol_lca', ?, ?)""",
                    (company, title, location, low, high,
                     f"LCA {_pick(row, 'case_no')}".strip(), now),
                )
                imported += 1
            except Exception:
                skipped += 1
    conn.commit()
    conn.close()
    return {"imported": imported, "skipped": skipped}


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def lookup(company: str = "", title: str = "", location: str = "",
           path: str | Path | None = None) -> dict:
    """Fuzzy lookup. Returns {p25, median, p75, n, sources, matches}.

    Strategy: score rows by company token overlap, title token overlap, and
    location match; use the best-scoring bucket with >= 5 rows, else fall
    back to any posted job_post range for the company/title.
    """
    conn = connect(path)
    rows = conn.execute(
        "SELECT company, title, location, low, high, source, source_detail FROM ranges"
    ).fetchall()
    conn.close()

    c_toks = set(_norm(company).split())
    t_toks = set(_norm(title).split())
    loc = _norm(location)

    scored: list[tuple[int, tuple]] = []
    for r in rows:
        rc, rt, rl = _norm(r[0]), _norm(r[1]), _norm(r[2])
        score = 0
        if c_toks and c_toks & set(rc.split()):
            score += 3 * len(c_toks & set(rc.split()))
        if t_toks and t_toks & set(rt.split()):
            score += 2 * len(t_toks & set(rt.split()))
        if loc and loc in rl:
            score += 2
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {"p25": None, "median": None, "p75": None, "n": 0,
                "sources": [], "matches": []}

    best = scored[0][0]
    bucket = [r for s, r in scored if s == best]
    if len(bucket) < 5:
        # widen: take top-3 score tiers
        tiers = sorted({s for s, _ in scored}, reverse=True)[:3]
        bucket = [r for s, r in scored if s in tiers]

    mids = sorted((r[3] + r[4]) / 2 for r in bucket)
    n = len(mids)

    def pct(p: float) -> float:
        if n == 1:
            return round(mids[0], 2)
        k = (n - 1) * p / 100
        f, c = int(k), min(int(k) + 1, n - 1)
        return round(mids[f] + (mids[c] - mids[f]) * (k - f), 2)

    sources = sorted({f"{r[5]}:{r[6]}" for r in bucket if r[5]})
    return {
        "p25": pct(25), "median": pct(50), "p75": pct(75), "n": n,
        "sources": sources[:8],
        "matches": [
            {"company": r[0], "title": r[1], "location": r[2],
             "low": r[3], "high": r[4], "source": r[5]} for r in bucket[:10]
        ],
    }


def render_lookup(result: dict, company: str = "", title: str = "",
                  location: str = "") -> str:
    if not result.get("n"):
        return (
            f"No salary data for company='{company}' title='{title}' location='{location}'.\n"
            "Build the database with:\n"
            "  python -m candid salary import-lca <dol_h1b_csv>\n"
            "  python -m candid salary parse-range --company X --role Y --jd job.txt"
        )
    what = " ".join(x for x in (company, title, location) if x)
    lines = [
        f"Salary data for '{what}' (n={result['n']}):",
        f"  p25:    ${result['p25']:,.0f}/yr",
        f"  median: ${result['median']:,.0f}/yr",
        f"  p75:    ${result['p75']:,.0f}/yr",
        "",
        "Sources (attribution preserved per row):",
    ]
    lines += [f"  • {s}" for s in result["sources"]]
    return "\n".join(lines)
