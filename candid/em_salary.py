"""EM salary bands: management-title pay bands from the salary database.

Filters candid.salary's `ranges` table to management titles (engineering
manager, EM, director) and reports p25/median/p75 bands per title, plus an
overall management band. Data sparsity is reported honestly - thin bands are
labeled indicative, and an empty database says so instead of guessing.

Usage:
    python -m candid em salary
    python -m candid em salary --title "Engineering Manager" --location "New York"
    python -m candid em salary --json
"""

from __future__ import annotations

import re
from pathlib import Path

from candid import salary as S

# (regex, label). First match wins; order matters.
_MGMT_TITLE_RULES: list[tuple["re.Pattern[str]", str]] = [
    (re.compile(
        r"\b(?:senior|sr\.?|staff|principal|software|software\s+engineering|"
        r"engineering)\s+(?:engineering\s+)?manag(?:er|ement|ing)|"
        r"\bengineering\s+mgr\b", re.I),
     "Engineering Manager"),
    (re.compile(r"(?:^|[\s(\-/])em(?:[\s),\-/]|$)", re.I), "EM"),
    (re.compile(r"\bdirector\b", re.I), "Director"),
]

_LABEL_ORDER = ["Engineering Manager", "EM", "Director"]

#: Below this many data points a band is indicative, not authoritative.
SPARSE_N = 5


def classify_mgmt_title(title: str) -> dict | None:
    """Map a raw title to a management bucket, or None if not management.

    Returns {"label": ..., "bare_director": bool}. A title of exactly
    "Director" is included (per the track spec) but flagged, since it may
    not be an engineering role.
    """
    t = (title or "").strip()
    for rx, label in _MGMT_TITLE_RULES:
        if rx.search(t):
            return {"label": label,
                    "bare_director": t.lower() == "director"}
    return None


def mgmt_rows(title: str = "", location: str = "",
              path: str | Path | None = None) -> list[dict]:
    """All salary rows whose title is a management title.

    Optional substring filters: `title` narrows the matched management
    titles, `location` narrows the row location. Case-insensitive.
    """
    conn = S.connect(path)
    raw = conn.execute(
        "SELECT company, title, location, low, high, source, source_detail "
        "FROM ranges"
    ).fetchall()
    conn.close()

    t_filt = S._norm(title)
    loc_filt = S._norm(location)
    out = []
    for r in raw:
        cls = classify_mgmt_title(r[1])
        if cls is None:
            continue
        if t_filt and t_filt not in S._norm(r[1]):
            continue
        if loc_filt and loc_filt not in S._norm(r[2]):
            continue
        out.append({
            "company": r[0], "title": r[1], "location": r[2],
            "low": r[3], "high": r[4], "source": r[5],
            "source_detail": r[6],
            "label": cls["label"], "bare_director": cls["bare_director"],
        })
    return out


def _band(rows: list[dict]) -> dict:
    mids = sorted((r["low"] + r["high"]) / 2 for r in rows)
    by_company: dict[str, dict] = {}
    for r in rows:
        key = S._norm(r["company"])
        entry = by_company.setdefault(
            key, {"company": r["company"], "mids": []})
        entry["mids"].append((r["low"] + r["high"]) / 2)
    companies = [
        {"company": e["company"],
         "median": S._percentile(sorted(e["mids"]), 50),
         "rows": len(e["mids"])}
        for e in by_company.values()
    ]
    return {
        "n": len(mids),
        "n_companies": len(by_company),
        "p25": S._percentile(mids, 25),
        "median": S._percentile(mids, 50),
        "p75": S._percentile(mids, 75),
        "companies": sorted(companies,
                            key=lambda c: c["median"] or 0, reverse=True)[:8],
    }


def mgmt_bands(title: str = "", location: str = "",
               path: str | Path | None = None) -> dict:
    """p25/median/p75 bands for management titles.

    Returns {"bands": [...per label...], "overall": {...}, "notes": [...],
    "title_filter", "location_filter"}. Sparse or empty data is labeled,
    never padded.
    """
    rows = mgmt_rows(title=title, location=location, path=path)
    bands = []
    for label in _LABEL_ORDER:
        bucket = [r for r in rows if r["label"] == label]
        if not bucket:
            continue
        b = _band(bucket)
        b["label"] = label
        bands.append(b)

    overall = _band(rows) if rows else {
        "n": 0, "n_companies": 0, "p25": None, "median": None,
        "p75": None, "companies": []}

    notes: list[str] = []
    if not rows:
        notes.append(
            "No management-title rows in the salary database. Build it with:\n"
            "  python -m candid salary import-lca <dol_h1b_csv>\n"
            "  python -m candid salary parse-range --company X "
            "--role \"Engineering Manager\" --jd jd.txt")
    else:
        for b in bands:
            if b["n"] < SPARSE_N:
                notes.append(
                    f"Sparse: only {b['n']} data point"
                    f"{'s' if b['n'] != 1 else ''} for '{b['label']}' - "
                    "treat this band as indicative, not authoritative.")
        if any(r["bare_director"] for r in rows):
            notes.append(
                "Some rows are titled just 'Director' and may not be "
                "engineering roles - narrow with --title (e.g. --title "
                "\"Director of Engineering\") if the band looks off.")
        notes.append(
            "Bands come from DOL H-1B disclosures and posted ranges already "
            "in your salary database - they skew toward larger employers "
            "and disclosed postings, not the whole market.")

    return {
        "title_filter": title, "location_filter": location,
        "bands": bands, "overall": overall, "notes": notes,
    }


def render_bands(result: dict) -> str:
    """Render mgmt_bands() output as human-readable text."""
    n = result["overall"]["n"]
    filt = " ".join(x for x in (f"title~'{result['title_filter']}'"
                                if result["title_filter"] else "",
                                f"location~'{result['location_filter']}'"
                                if result["location_filter"] else "") if x)
    lines = [f"EM SALARY BANDS (n={n} management-title data point"
             f"{'s' if n != 1 else ''})"]
    if filt:
        lines.append(f"Filters: {filt}")
    lines.append("")

    def _band_lines(b: dict, label: str) -> list[str]:
        tag = (f" (sparse: n={b['n']})" if b["n"] < SPARSE_N else "")
        out = [f"{label} - n={b['n']} across "
               f"{b['n_companies']} "
               f"{'company' if b['n_companies'] == 1 else 'companies'}{tag}",
               f"  p25    ${b['p25']:,.0f}/yr",
               f"  median ${b['median']:,.0f}/yr",
               f"  p75    ${b['p75']:,.0f}/yr"]
        return out

    for b in result["bands"]:
        lines += _band_lines(b, b["label"]) + [""]
    if n:
        lines += _band_lines(result["overall"], "All management titles") + [""]
    if result["notes"]:
        lines.append("Notes:")
        lines += [f"  - {note}" for note in result["notes"]]
        lines.append("")
    lines.append("Tip: enrich the database, then re-run - "
                 "`python -m candid salary parse-range --company X "
                 "--role \"Engineering Manager\" --jd jd.txt`")
    return "\n".join(lines)
