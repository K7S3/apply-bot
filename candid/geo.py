"""Location arbitrage: rank remote roles by pay vs cost of living.

Effective pay = nominal pay adjusted to national-average dollars using the
bundled COL table (candid/data/col_index.json). Every figure shown is an
estimate: COL indices are metro approximations, and pay comes from posted
ranges, not verified offers.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from candid import config as C

BUNDLED_COL_PATH = C.PACKAGE_ROOT / "data" / "col_index.json"


def _override_path() -> Path:
    """User-overridable COL table location."""
    d = os.environ.get("CANDID_CONFIG_DIR") or str(Path.home() / ".config" / "candid")
    return Path(d) / "col_index.json"


def load_col_index() -> dict:
    """Load the COL table: user override wins, bundled table is the fallback.

    Returns {"meta": {...}, "aliases": {...}, "metros": {key: {label, index}}}.
    """
    path = _override_path()
    if not path.exists():
        path = BUNDLED_COL_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Could not read COL table at {path}: {e}") from e
    if "metros" not in data:
        raise ValueError(f"COL table at {path} has no 'metros' section.")
    return data


def _norm_loc(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def find_metro(location: str, table: dict | None = None) -> tuple[str, dict] | None:
    """Resolve a location string to a COL metro entry.

    Accepts "New York, NY", "Austin TX", and aliases like "nyc", "sf", "dc".
    Returns (key, {"label", "index"}) or None.
    """
    table = table or load_col_index()
    metros = table["metros"]
    aliases = {k.lower(): v for k, v in table.get("aliases", {}).items()}
    q = _norm_loc(location)
    if not q:
        return None
    if q in metros:
        return q, metros[q]
    if q in aliases and aliases[q] in metros:
        return aliases[q], metros[aliases[q]]
    # "Austin, TX" vs "austin tx": try comma/no-comma variants
    variants = {q.replace(",", ""), q.replace(",", ", ")}
    for v in variants:
        if v in metros:
            return v, metros[v]
        if v in aliases and aliases[v] in metros:
            return aliases[v], metros[aliases[v]]
    # last resort: city-name prefix match ("New York" -> "new york, ny")
    city = q.split(",")[0].strip()
    for key, entry in metros.items():
        if key.split(",")[0].strip() == city:
            return key, entry
    return None


def list_metros(table: dict | None = None) -> list[str]:
    table = table or load_col_index()
    return [e["label"] for e in table["metros"].values()]


def effective_pay(nominal: float, index: float) -> float:
    """Adjust nominal $/yr to national-average dollars. Pure math, no judgment."""
    if index <= 0:
        raise ValueError("COL index must be positive.")
    return round(nominal * 100.0 / index, 2)


def rank_remote_jobs(jobs: list[dict], metro_key: str, index: float) -> dict:
    """Rank remote jobs by effective pay at the given metro.

    Jobs need a parseable pay range (from salary_text or description);
    jobs without one are counted in `skipped_no_pay`. Returns
    {"rows": [...], "skipped_no_pay": int} with rows sorted by effective
    pay, descending. Each row: {title, company, location, url, low, high,
    nominal_mid, effective}.
    """
    from candid import salary as S
    rows, skipped = [], 0
    for job in jobs:
        parsed = S.parse_posted_range(
            (job.get("salary_text") or "") + " " + (job.get("description") or ""))
        if not parsed:
            skipped += 1
            continue
        mid = (parsed["low"] + parsed["high"]) / 2
        rows.append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": job.get("url", ""),
            "low": parsed["low"],
            "high": parsed["high"],
            "nominal_mid": round(mid, 2),
            "effective": effective_pay(mid, index),
        })
    rows.sort(key=lambda r: -r["effective"])
    return {"rows": rows, "skipped_no_pay": skipped, "_metro_key": metro_key}


def render_ranking(ranked: dict, metro_label: str, index: float,
                   limit: int = 15,
                   compare: tuple[str, dict] | None = None) -> str:
    """Render the effective-pay ranking. All figures labeled as estimates."""
    rows = ranked["rows"][:limit]
    lines = [
        f"Remote roles ranked by effective pay (est.) - {metro_label} "
        f"(COL index {index}, 100 = US average):",
        "",
        f"  {'Effective (est)':<16}{'Nominal (est)':<15}{'Role':<36}Company",
    ]
    for r in rows:
        eff = f"${r['effective']:,.0f}/yr"
        nom = f"${r['nominal_mid']:,.0f}/yr"
        title = (r["title"] or "?")[:35]
        comp = (r["company"] or "?")[:24]
        line = f"  {eff:<16}{nom:<15}{title:<36}{comp}"
        if compare:
            ckey, centry = compare
            line += f"   | {centry['label']}: ${effective_pay(r['nominal_mid'], centry['index']):,.0f}/yr (est)"
        lines.append(line)
    if not rows:
        lines.append("  (no remote roles with a parseable pay range)")
    if ranked.get("skipped_no_pay"):
        lines.append(f"\n({ranked['skipped_no_pay']} remote role(s) skipped: "
                     "no parseable pay range)")
    lines += [
        "",
        "Estimates: effective pay = posted-range midpoint adjusted by the COL "
        "index (national-average dollars). Posted ranges are not verified "
        "offers; COL indices are metro approximations - see "
        "candid/data/col_index.json for the source.",
        "Arbitrage view: re-run with a different --location and compare "
        "effective pay for the same roles.",
    ]
    return "\n".join(lines)
