"""Startup digest: new matches, hiring-signal movers, startup interviews.

    python -m candid startups digest [--json]

Three sections, all local data, read defensively:

  1. New registry matches - watchlist alerts logged since the last digest.
  2. Hiring-signal movers - companies whose curated-job presence moved the
     most since the last digest. Reuses W2's ``compute_signals`` when
     available (``candid.startup_signals.compute_signals``); otherwise falls
     back to a local per-company count delta. A missing signal source
     degrades to an informational note, never a crash.
  3. Startup interviews this week - tracker entries in
     ``selected_for_interview`` touched in the last 7 days.

Expected failures raise ``StartupDigestError`` (clean errors, no tracebacks).
No network calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from candid import config as C


class StartupDigestError(Exception):
    """Raised for digest failures (expected, user-facing)."""


def _state_path() -> Path:
    return C.DATA_DIR / "startup_digest_state.json"


def _alerts_path() -> Path:
    return C.DATA_DIR / "startup_alerts.jsonl"


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_alerts() -> list[dict]:
    alerts: list[dict] = []
    p = _alerts_path()
    if not p.exists():
        return alerts
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(a, dict):
                alerts.append(a)
    except OSError:
        pass
    return alerts


def _curated_jobs() -> list[dict]:
    """Jobs known to jobs.json (same defensive read as startup_watch)."""
    from candid import startup_watch as W
    return W._curated_jobs()


# --- section 1: new registry matches -----------------------------------------

def new_matches_since(cutoff: datetime | None) -> list[dict]:
    """Watchlist alerts logged after ``cutoff`` (all alerts if None)."""
    out: list[dict] = []
    for a in _read_alerts():
        ts = _parse_ts(a.get("alerted_at", ""))
        if cutoff is None or (ts is not None and ts > cutoff):
            out.append(a)
    return out


# --- section 2: hiring-signal movers ------------------------------------------

def _local_signals(jobs: list[dict]) -> dict[str, int]:
    """Fallback signal: curated-job count per company."""
    counts: dict[str, int] = {}
    for j in jobs:
        c = (j.get("company") or "").strip() or "(unknown)"
        counts[c] = counts.get(c, 0) + 1
    return counts


def signal_movers(jobs: list[dict], prev_snapshot: dict[str, int],
                  top_n: int = 5) -> list[dict]:
    """Biggest hiring-signal movers since the previous snapshot.

    Tries W2's ``compute_signals`` first (defensively); on any failure
    falls back to a local per-company count delta. Returns rows
    {company, previous, current, delta} sorted by |delta| desc.
    """
    current: dict[str, int] = {}
    used = "local"
    try:
        from candid import startup_signals as SS  # W2's module (may not exist)
        fn = getattr(SS, "compute_signals", None)
        if callable(fn):
            # W2 signature: compute_signals(min_postings=2, now=None) -> list of
            # per-company rows ({company, postings_total, postings_per_30d,
            # trend, ...}). Adapt rows to per-company counts.
            rows = fn()
            if isinstance(rows, list):
                current = {str(r.get("company") or "").strip(): int(r.get("postings_total") or 0)
                           for r in rows if isinstance(r, dict) and r.get("company")}
                current = {k: v for k, v in current.items() if k}
                used = "startup_signals"
    except Exception:
        current = {}
    if not current:
        current = _local_signals(jobs)
        used = "local"

    rows: list[dict] = []
    for company in set(current) | set(prev_snapshot):
        prev = int(prev_snapshot.get(company, 0))
        now = int(current.get(company, 0))
        if now != prev:
            rows.append({"company": company, "previous": prev,
                         "current": now, "delta": now - prev})
    rows.sort(key=lambda r: (-abs(r["delta"]), -r["current"], r["company"]))
    for r in rows:
        r["source"] = used
    return rows[:top_n]


# --- section 3: startup interviews this week ----------------------------------

def interviews_this_week() -> list[dict]:
    """Tracker entries in selected_for_interview touched in the last 7 days."""
    try:
        from candid import tracker as T
        apps = T.list_apps(status="selected_for_interview")
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    out: list[dict] = []
    for a in apps:
        ts = _parse_ts(a.get("date_updated") or a.get("date_added") or "")
        if ts is not None and ts >= cutoff:
            out.append(a)
    return out


# --- build / render -----------------------------------------------------------

def build_digest() -> dict:
    """Compute all three sections and advance the digest watermark.

    Returns {"new_matches": [...], "signal_movers": [...],
    "interviews_this_week": [...]}. The watermark and signal snapshot are
    updated afterwards so the next digest only shows what is new.
    """
    state = _load_state()
    cutoff = _parse_ts(state.get("last_digest_at", "")) if state.get("last_digest_at") else None
    jobs = _curated_jobs()

    digest = {
        "new_matches": new_matches_since(cutoff),
        "signal_movers": signal_movers(jobs, state.get("signals_snapshot", {})),
        "interviews_this_week": interviews_this_week(),
    }

    state["last_digest_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["signals_snapshot"] = _local_signals(jobs)
    C.ensure_data_dirs()
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    return digest


def _arrow(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def render_text(d: dict) -> str:
    lines = ["Startup digest", "=" * 14, ""]
    lines.append("1. New watchlist matches")
    lines.append("-" * 24)
    if d["new_matches"]:
        for a in d["new_matches"]:
            lines.append(f"  - {a.get('name')} -> {a.get('title')} @ {a.get('company')}"
                         + (f"  {a['url']}" if a.get("url") else ""))
    else:
        lines.append("  No new matches since the last digest.")
    lines.append("")
    lines.append("2. Hiring-signal movers")
    lines.append("-" * 23)
    if d["signal_movers"]:
        for r in d["signal_movers"]:
            lines.append(f"  - {r['company']}: {_arrow(r['delta'])} "
                         f"({r['previous']} -> {r['current']})")
    else:
        lines.append("  No hiring-signal data yet. Run `python -m candid jobs curate ...` first.")
    lines.append("")
    lines.append("3. Startup interviews this week")
    lines.append("-" * 31)
    if d["interviews_this_week"]:
        for a in d["interviews_this_week"]:
            lines.append(f"  - {a.get('role')} @ {a.get('company')} "
                         f"(updated {a.get('date_updated') or a.get('date_added') or '?'})")
    else:
        lines.append("  No interviews this week.")
    return "\n".join(lines)


def render_markdown(d: dict) -> str:
    lines = ["# Startup digest", ""]
    lines.append("## 1. New watchlist matches")
    lines.append("")
    if d["new_matches"]:
        for a in d["new_matches"]:
            lines.append(f"- **{a.get('name')}** -> {a.get('title')} @ {a.get('company')}"
                         + (f"  ({a['url']})" if a.get("url") else ""))
    else:
        lines.append("_No new matches since the last digest._")
    lines.append("")
    lines.append("## 2. Hiring-signal movers")
    lines.append("")
    if d["signal_movers"]:
        lines.append("| Company | Change | Before | Now |")
        lines.append("|---|---|---|---|")
        for r in d["signal_movers"]:
            lines.append(f"| {r['company']} | {_arrow(r['delta'])} | "
                         f"{r['previous']} | {r['current']} |")
    else:
        lines.append("_No hiring-signal data yet. Run `python -m candid jobs curate ...` first._")
    lines.append("")
    lines.append("## 3. Startup interviews this week")
    lines.append("")
    if d["interviews_this_week"]:
        for a in d["interviews_this_week"]:
            lines.append(f"- **{a.get('role')}** @ {a.get('company')} "
                         f"(updated {a.get('date_updated') or a.get('date_added') or '?'})")
    else:
        lines.append("_No interviews this week._")
    return "\n".join(lines) + "\n"
