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
from candid.contexts import ctx_value

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
# Matching is case-insensitive and ignores surrounding whitespace.
_LCA_COLUMNS: dict[str, list[str]] = {
    "company": ["EMPLOYER_NAME", "Employer Name", "EMPLOYER_NAME ",
                "Company Name", "Employer"],
    "title": ["JOB_TITLE", "Job Title", "SOC_TITLE", "Occupational Title",
              "OCCUPATIONAL_TITLE"],
    "city": ["WORKSITE_CITY", "Worksite City", "EMPLOYER_CITY", "City"],
    "state": ["WORKSITE_STATE", "Worksite State", "EMPLOYER_STATE", "State"],
    "worksite": ["WORKSITE", "Worksite", "WORKSITE_ADDRESS", "Worksite Address"],
    "wage_from": ["WAGE_RATE_OF_PAY_FROM", "Wage Rate of Pay From",
                  "WAGE_RATE_OF_PAY", "Wage Rate of Pay", "WAGE_FROM",
                  "Prevailing Wage From"],
    "wage_to": ["WAGE_RATE_OF_PAY_TO", "Wage Rate of Pay To",
                "WAGE_TO", "Prevailing Wage To"],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "Wage Unit of Pay", "PAY_UNIT",
                  "Wage Unit"],
    "case_no": ["CASE_NUMBER", "Case Number", "Case No"],
    "status": ["CASE_STATUS", "Case Status", "Status"],
}


def _norm_header(h: str) -> str:
    return (h or "").strip().upper()


def _build_picker(fieldnames: list[str] | None) -> dict[str, str]:
    """Map each canonical field to the actual header present in the file."""
    picker: dict[str, str] = {}
    if not fieldnames:
        return picker
    have = {_norm_header(h): h for h in fieldnames if h}
    for field, variants in _LCA_COLUMNS.items():
        for v in variants:
            key = _norm_header(v)
            if key in have and field not in picker:
                picker[field] = have[key]
                break
    return picker


def _pick(row: dict, picker: dict[str, str], field: str) -> str:
    header = picker.get(field)
    if header is None:
        return ""
    return (row.get(header) or "").strip()


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
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        # sniff delimiter; DOL files are comma-separated
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        picker = _build_picker(reader.fieldnames)
        for n, row in enumerate(reader, 1):
            if limit and n > limit:
                break
            if progress_every and n % progress_every == 0:
                print(f"  ... {n} rows scanned ({imported} imported)")
            if not any((v or "").strip() for v in row.values()):
                skipped += 1  # blank row
                continue
            try:
                if only_certified:
                    status = _pick(row, picker, "status").upper()
                    # 'CERTIFIED-WITHDRAWN' contains CERTIFIED but is not a live case
                    certified = status.startswith("CERTIFIED") and "WITHDRAWN" not in status
                    if status and not certified:
                        skipped += 1
                        continue
                company = _pick(row, picker, "company")
                title = _pick(row, picker, "title")
                wage_from = _parse_wage(_pick(row, picker, "wage_from"))
                if not company or not title or not wage_from:
                    skipped += 1
                    continue
                wage_to = _parse_wage(_pick(row, picker, "wage_to")) or wage_from
                unit = _pick(row, picker, "wage_unit").lower()
                mult = 1
                for key, m in _UNIT_MULT.items():
                    if key in unit:
                        mult = m
                        break
                low, high = sorted((wage_from * mult, wage_to * mult))
                if low <= 0 or high <= 0:
                    skipped += 1
                    continue
                city = _pick(row, picker, "city")
                state = _pick(row, picker, "state")
                location = ", ".join(x for x in (city, state) if x) or _pick(row, picker, "worksite")
                case_no = _pick(row, picker, "case_no")
                conn.execute(
                    """INSERT INTO ranges
                       (company, title, location, low, high, currency, pay_period,
                        source, source_detail, retrieved_at)
                       VALUES (?, ?, ?, ?, ?, 'USD', 'year', 'dol_lca', ?, ?)""",
                    (company, title, location, low, high,
                     f"LCA {case_no}".strip(), now),
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


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """Linear-interpolation percentile of an already-sorted value list."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return round(sorted_vals[0], 2)
    k = (n - 1) * p / 100
    f, c = int(k), min(int(k) + 1, n - 1)
    return round(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f), 2)


def lookup(company: str = "", title: str = "", location: str | None = None,
           path: str | Path | None = None) -> dict:
    """Fuzzy lookup. Returns {p25, median, p75, n, sources, matches}.

    Strategy: score rows by company token overlap, title token overlap, and
    location match; use the best-scoring bucket with >= 5 rows, else fall
    back to any posted job_post range for the company/title.

    ``location`` defaults to the active context (salary.location), honoring a
    per-company override for the lookup company; with no active context it
    falls back to "" (no location filter). An explicitly passed location
    always wins.
    """
    if location is None:
        location = ctx_value("salary.location", "", company=company or None) or ""
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

    sources = sorted({f"{r[5]}:{r[6]}" for r in bucket if r[5]})
    return {
        "p25": _percentile(mids, 25), "median": _percentile(mids, 50),
        "p75": _percentile(mids, 75), "n": n,
        "sources": sources[:8],
        "matches": [
            {"company": r[0], "title": r[1], "location": r[2],
             "low": r[3], "high": r[4], "source": r[5]} for r in bucket[:10]
        ],
    }


def aggregate_by_title(title: str, path: str | Path | None = None) -> dict:
    """Aggregate pay across companies for a job title.

    Rows are grouped by normalized company; each company's midpoint
    (median of its rows) feeds the p25/median/p75 so one heavy filer
    can't dominate. Returns
    {title, p25, median, p75, n (companies), companies: [{company, median, rows}]}.
    """
    conn = connect(path)
    rows = conn.execute(
        "SELECT company, title, location, low, high, source, source_detail FROM ranges"
    ).fetchall()
    conn.close()

    t_toks = set(_norm(title).split())
    by_company: dict[str, dict] = {}
    for r in rows:
        if not t_toks or t_toks & set(_norm(r[1]).split()):
            key = _norm(r[0])
            entry = by_company.setdefault(
                key, {"company": r[0], "mids": []})
            entry["mids"].append((r[3] + r[4]) / 2)

    companies = []
    for entry in by_company.values():
        mids = sorted(entry["mids"])
        companies.append({
            "company": entry["company"],
            "median": _percentile(mids, 50),
            "rows": len(mids),
        })
    meds = sorted(c["median"] for c in companies if c["median"] is not None)
    return {
        "title": title,
        "p25": _percentile(meds, 25),
        "median": _percentile(meds, 50),
        "p75": _percentile(meds, 75),
        "n": len(meds),
        "companies": sorted(companies, key=lambda c: c["median"] or 0,
                            reverse=True),
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
        f"Salary for '{what}' (n={result['n']} data point{'s' if result['n'] != 1 else ''}):",
        f"  p25    ${result['p25']:,.0f}/yr",
        f"  median ${result['median']:,.0f}/yr",
        f"  p75    ${result['p75']:,.0f}/yr",
        "",
    ]
    srcs = result.get("sources", [])
    if srcs:
        from collections import Counter
        kinds = Counter(s.split(":", 1)[0] for s in srcs)
        breakdown = ", ".join(f"{k} ({v} source ref{'s' if v != 1 else ''})"
                              for k, v in sorted(kinds.items()))
        lines.append(f"Sources: {breakdown} — attribution per row below.")
        lines.append("")
    matches = result.get("matches", [])
    if matches:
        lines.append("Top matches (range = annualized $/yr):")
        for m in matches[:8]:
            rng = f"${m['low']:,.0f}–${m['high']:,.0f}"
            lines.append(f"  • {m['company']} — {m['title']} "
                         f"({m['location'] or 'no location'}): {rng} "
                         f"[{m['source']}]")
    lines.append("")
    lines.append("Tip: use these bands in `python -m candid negotiate` "
                 "when a range comes up.")
    return "\n".join(lines)


def render_title_aggregation(agg: dict) -> str:
    """Render aggregate_by_title output."""
    if not agg.get("n"):
        return (f"No salary data for title '{agg.get('title')}'. "
                "Import DOL LCA data or parse posted ranges first.")
    lines = [
        f"Pay across companies for '{agg['title']}' ({agg['n']} companies):",
        f"  p25    ${agg['p25']:,.0f}/yr",
        f"  median ${agg['median']:,.0f}/yr",
        f"  p75    ${agg['p75']:,.0f}/yr",
        "",
        "By company (median of that company's rows):",
    ]
    for c in agg["companies"][:12]:
        lines.append(f"  • {c['company']}: ${c['median']:,.0f}/yr "
                     f"({c['rows']} row{'s' if c['rows'] != 1 else ''})")
    return "\n".join(lines)
