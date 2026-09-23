"""H-1B sponsorship likelihood: a per-company score from imported DOL LCA rows.

`salary import-lca` records every scanned disclosure row (company, case
status, fiscal year) in the `lca_sponsor` table, including rows the salary
import itself skips (denied / withdrawn cases) — those are exactly what the
approval-consistency component needs.

The score is purely a function of those rows: filing volume, approval
consistency, and recency. Nothing is fetched, scraped, or invented. No
rows -> an explicit "insufficient data" verdict, never a fabricated score.
"""

from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

from candid import config as C

SPONSOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS lca_sponsor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    case_no TEXT DEFAULT '',
    status TEXT DEFAULT '',
    fiscal_year INTEGER DEFAULT 0,
    recorded_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lca_sponsor_company ON lca_sponsor(company);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lca_sponsor_case
    ON lca_sponsor(company, case_no, fiscal_year);
"""

#: Fewer than this many filings -> the score is shown but labeled a small sample.
SMALL_SAMPLE_N = 10


class SponsorError(Exception):
    """Raised for sponsorship CLI/data problems."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SPONSOR_SCHEMA)


def fiscal_year_from_name(csv_path: str | Path) -> int:
    """Best-effort fiscal-year detection from the DOL file name.

    DOL disclosure files are named like H-1B_Disclosure_Data_FY2024.csv.
    Returns 0 when no year is found (treated as "oldest" in recency weighting).
    """
    m = re.search(r"FY\s?(\d{4})", Path(csv_path).name, re.I)
    return int(m.group(1)) if m else 0


def record_rows(conn: sqlite3.Connection, rows: list[dict],
                fiscal_year: int = 0) -> int:
    """Record raw LCA disclosure rows (all statuses) for sponsorship scoring.

    Rows are dicts with keys: company, case_no, status, fiscal_year.
    Dedupes on (company, case_no, fiscal_year) when a case number exists;
    rows without a case number are always inserted. Returns rows recorded.
    """
    ensure_schema(conn)
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    recorded = 0
    for r in rows:
        company = (r.get("company") or "").strip()
        if not company:
            continue
        case_no = (r.get("case_no") or "").strip()
        status = (r.get("status") or "").strip().upper()
        fy = int(r.get("fiscal_year") or fiscal_year or 0)
        if case_no:
            cur = conn.execute(
                """INSERT OR IGNORE INTO lca_sponsor
                   (company, case_no, status, fiscal_year, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (company, case_no, status, fy, now))
            recorded += cur.rowcount
        else:
            conn.execute(
                """INSERT INTO lca_sponsor
                   (company, case_no, status, fiscal_year, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (company, case_no, status, fy, now))
            recorded += 1
    return recorded


def lca_loaded(path: str | Path | None = None) -> bool:
    """True when any LCA disclosure rows have been recorded for scoring."""
    from candid import salary as S
    conn = S.connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM lca_sponsor").fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    conn.close()
    return n > 0


# ---------------------------------------------------------------------------
# company matching
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _matches(query: str, employer: str) -> bool:
    """Fuzzy employer match: every query token must appear in the employer name.

    "Google" matches "GOOGLE LLC"; "Capital One" matches "Capital One
    Services, LLC". Query tokens are matched as whole words, so "Bank" does
    not match "BankUnited"... it actually does, by design: short queries are
    broad. Prefer the full employer name for precision.
    """
    q_toks = set(_norm(query).split())
    e_toks = set(_norm(employer).split())
    return bool(q_toks) and q_toks <= e_toks


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _is_certified(status: str) -> bool:
    s = (status or "").upper()
    return s.startswith("CERTIFIED") and "WITHDRAWN" not in s


def _is_denied(status: str) -> bool:
    s = (status or "").upper()
    return s.startswith("DENIED") or s.startswith("REJECTED") or s == "INVALIDATED"


def _is_withdrawn(status: str) -> bool:
    return "WITHDRAWN" in (status or "").upper()


def _recency_weight(year: int, newest: int) -> float:
    if year <= 0:
        return 0.2
    gap = newest - year
    return {0: 1.0, 1: 0.8, 2: 0.6, 3: 0.4}.get(gap, 0.2)


def score_company(company: str, path: str | Path | None = None) -> dict:
    """Score a company's H-1B sponsorship likelihood 0-100 from LCA rows.

    Returns a dict with the score and every underlying number:
    n (total filings), certified / denied / withdrawn counts, approval_rate,
    recency_score, volume_score, fiscal years seen, plus flags
    `insufficient` (no rows -> no score) and `small_sample` (n < 10).
    """
    from candid import salary as S
    conn = S.connect(path)
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT company, status, fiscal_year FROM lca_sponsor").fetchall()
    conn.close()

    matched = [r for r in rows if _matches(company, r[0])]
    n = len(matched)
    if n == 0:
        return {"company": company, "matched_name": "", "n": 0,
                "certified": 0, "denied": 0, "withdrawn": 0, "other": 0,
                "approval_rate": 0.0, "recency_score": 0.0, "volume_score": 0.0,
                "score": None, "years": [], "small_sample": False,
                "insufficient": True}

    years = sorted({int(r[2]) for r in matched if int(r[2]) > 0})
    # recency is relative to the newest year in the whole dataset, so a
    # company whose filings are all old scores lower than one filing now
    all_years = [int(r[2]) for r in rows if int(r[2]) > 0]
    newest = max(all_years) if all_years else 0

    certified = sum(1 for r in matched if _is_certified(r[1]))
    denied = sum(1 for r in matched if _is_denied(r[1]))
    withdrawn = sum(1 for r in matched
                    if _is_withdrawn(r[1]) and not _is_certified(r[1]))
    other = n - certified - denied - withdrawn

    approval = certified / n
    w_sum = sum(_recency_weight(int(r[2]), newest) for r in matched)
    w_cert = sum(_recency_weight(int(r[2]), newest)
                 for r in matched if _is_certified(r[1]))
    recency = (w_cert / w_sum) if w_sum else 0.0
    volume = min(1.0, math.log10(n + 1) / math.log10(SMALL_SAMPLE_N * 10 + 1))

    score = round(100 * (0.45 * approval + 0.30 * recency + 0.25 * volume))

    # canonical display name: the most common raw employer spelling
    from collections import Counter
    matched_name = Counter(r[0] for r in matched).most_common(1)[0][0]

    return {
        "company": company,
        "matched_name": matched_name,
        "n": n,
        "certified": certified,
        "denied": denied,
        "withdrawn": withdrawn,
        "other": other,
        "approval_rate": round(approval, 3),
        "recency_score": round(recency, 3),
        "volume_score": round(volume, 3),
        "score": score,
        "years": years,
        "small_sample": n < SMALL_SAMPLE_N,
        "insufficient": False,
    }


def render_score(res: dict, company: str = "") -> str:
    """Human-readable sponsorship report. Never fabricates a score."""
    if res.get("insufficient"):
        return (
            f"Insufficient LCA data for '{company or res.get('company')}' - "
            "no H-1B filings found.\n"
            "Import DOL disclosure data first:\n"
            "  python -m candid salary import-lca <dol_h1b_csv>"
        )
    years = (f"FY{res['years'][0]}-FY{res['years'][-1]}"
             if len(res["years"]) > 1 else
             (f"FY{res['years'][0]}" if res["years"] else "year unknown"))
    lines = [
        f"H-1B sponsorship likelihood for '{res['matched_name']}' "
        f"(matched '{res['company']}'): {res['score']}/100",
        f"  Filings: {res['n']} total - {res['certified']} certified, "
        f"{res['denied']} denied, {res['withdrawn']} withdrawn ({years})",
        f"  Approval consistency: {res['approval_rate']:.0%}  "
        f"Recency: {res['recency_score']:.2f}  Filing volume: {res['volume_score']:.2f}",
    ]
    if res["small_sample"]:
        lines.append(
            f"  Small sample (n={res['n']} < {SMALL_SAMPLE_N}) - "
            "directional only, not decisive.")
    lines.append(
        "  Estimate from the DOL H-1B LCA disclosure rows you imported. "
        "See docs/sponsorship.md for the formula and its limits.")
    return "\n".join(lines)


def sponsor_line(company: str, path: str | Path | None = None) -> str | None:
    """One-line sponsorship summary for the `match` report.

    Returns None when no LCA data is loaded at all (so `match` stays quiet)
    or when no company was given; otherwise a line with the score or an
    explicit insufficient-data note.
    """
    if not company or not lca_loaded(path):
        return None
    res = score_company(company, path=path)
    if res.get("insufficient"):
        return ("H-1B sponsorship: no LCA filings found for this company - "
                "import data with `python -m candid salary import-lca <csv>`.")
    sample = " (small sample)" if res["small_sample"] else ""
    return (f"H-1B sponsorship likelihood: {res['score']}/100{sample} "
            f"(n={res['n']} filings, {res['approval_rate']:.0%} certified) - "
            "estimate from DOL LCA data.")
