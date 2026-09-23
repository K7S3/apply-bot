"""Watch alerts: match new postings against the profile, store alerts, digest hook.

Works with the monitor engine in ``candid.monitors`` (owned by another
worker). Monitor-engine API used here:

    add_company(name) -> {"key", "name", "sources": [...]}
    remove_company(name) -> True  (raises MonitorError for unknown companies)
    list_companies() -> [{"key", "name", "sources": [{"type","url","label"}]}]
    add_source(company, source_type, url=None, board=None, site=None) -> dict
    poll(company=None, ...) -> {"date", "companies": {key: {"name", "fetched",
        "new", "closed", "reposts", "errors", "skipped"}}, "totals": {...}}
        new/closed/reposts are posting records:
        {"id", "title", "location", "url", "department", "posted_date",
         "first_seen", "last_seen", "status", "closed_at", "repost", ...}
        (reposts are included in "new" with rec["repost"] == True)

Posting records carry no JD text, so scoring falls back to fetching the
posting's own URL (plain HTTPS GET of a public page, like the monitor
engine's feed fetches) when the board text is thin; failures fall back to
the title/location text.

Alert rule: a new posting becomes an alert when its match verdict is GO or
CONDITIONAL, or its score is >= the configured threshold (default 60).
Dedupe: never two *unread* alerts for the same (company, posting).
Reposts (``is_repost=True``) that pass the same gate get their own alert
with kind "repost" and a distinct message.

Alert store layout (candid_data/alerts.json), a JSON list of:

    {"id": int, "kind": "new" | "repost", "company": str, "posting_id": str,
     "title": str, "url": str, "score": float, "verdict": str,
     "message": str, "created_at": iso, "read": bool}

Watch state (candid_data/watch_runs.json) records the last run per company
so `watch status` works from this module's own data. Config
(candid_data/watch_config.json) holds {"alert_threshold": float}.

Everything is local; nothing here sends anything automatically.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from candid import config as C
from candid import match as M


class AlertError(Exception):
    """Raised for invalid alert/watch operations."""


# --- paths (derived from C.DATA_DIR at call time so tests can redirect) ------

_ALERTS_FILE = "alerts.json"
_WATCH_CONFIG_FILE = "watch_config.json"
_WATCH_RUNS_FILE = "watch_runs.json"


def _alerts_path() -> Path:
    return C.DATA_DIR / _ALERTS_FILE


def _config_path() -> Path:
    return C.DATA_DIR / _WATCH_CONFIG_FILE


def _runs_path() -> Path:
    return C.DATA_DIR / _WATCH_RUNS_FILE


# --- alert store --------------------------------------------------------------

def load_alerts(path: str | Path | None = None) -> list[dict]:
    """Load all alerts (read + unread), newest first. [] when none."""
    p = Path(path) if path else _alerts_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AlertError(f"Alert store {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise AlertError(f"Alert store {p} should contain a JSON list.")
    return sorted(data, key=lambda a: a.get("created_at", ""), reverse=True)


def _save_alerts(alerts: list[dict], path: str | Path | None = None) -> None:
    p = Path(path) if path else _alerts_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(alerts, indent=2), encoding="utf-8")


def _next_id(alerts: list[dict]) -> int:
    return max((a.get("id", 0) for a in alerts), default=0) + 1


def _dedupe_key(posting: dict) -> tuple[str, str]:
    """Stable identity for dedupe: (company, id|posting_id|url|title)."""
    company = str(posting.get("company") or "").strip().lower()
    pid = str(posting.get("posting_id") or posting.get("id")
              or posting.get("url") or posting.get("title")
              or "").strip().lower()
    return company, pid


def has_unread_alert(alerts: list[dict], posting: dict) -> bool:
    """True when an unread alert already exists for this posting."""
    key = _dedupe_key(posting)
    return any(not a.get("read", False) and
               _dedupe_key({"company": a.get("company"),
                            "posting_id": a.get("posting_id")}) == key
               for a in alerts)


def create_alert(posting: dict, score: float, verdict: str,
                 *, path: str | Path | None = None) -> dict | None:
    """Create an alert for a posting; None when an unread one already exists.

    kind is "repost" when the posting has is_repost=True, else "new".
    """
    alerts = load_alerts(path)
    if has_unread_alert(alerts, posting):
        return None
    kind = "repost" if (posting.get("is_repost") or posting.get("repost")) else "new"
    company = posting.get("company") or ""
    title = posting.get("title") or ""
    if kind == "repost":
        message = (f"Reposted: {title} @ {company} is back on the board — "
                   f"match {score:g}/100 ({verdict}).")
    else:
        message = (f"New posting: {title} @ {company} — "
                   f"match {score:g}/100 ({verdict}).")
    alert = {
        "id": _next_id(alerts),
        "kind": kind,
        "company": company,
        "posting_id": str(posting.get("posting_id") or posting.get("id")
                          or posting.get("url") or ""),
        "title": title,
        "url": posting.get("url") or "",
        "score": score,
        "verdict": verdict,
        "message": message,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "read": False,
    }
    alerts.append(alert)
    _save_alerts(alerts, path)
    return alert


def mark_read(alert_id: int, *, path: str | Path | None = None) -> dict:
    """Mark an alert read (ack). Returns the alert; raises AlertError if missing."""
    alerts = load_alerts(path)
    for a in alerts:
        if a.get("id") == alert_id:
            a["read"] = True
            _save_alerts(alerts, path)
            return a
    raise AlertError(f"No alert with id {alert_id}. "
                     "Run `python -m candid watch alerts` to see ids.")


def unread_count(alerts: list[dict] | None = None) -> int:
    """Number of unread alerts."""
    return sum(1 for a in (load_alerts() if alerts is None else alerts)
               if not a.get("read", False))


# --- threshold config ---------------------------------------------------------

DEFAULT_ALERT_THRESHOLD = 60.0
_GOOD_VERDICTS = {"GO", "CONDITIONAL"}


def load_watch_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AlertError(f"Watch config {p} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def get_threshold(path: str | Path | None = None) -> float:
    """Configured alert score threshold (default 60)."""
    try:
        return float(load_watch_config(path).get("alert_threshold",
                                                 DEFAULT_ALERT_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_ALERT_THRESHOLD


def set_threshold(n: float, path: str | Path | None = None) -> float:
    """Set the alert score threshold (0-100). Returns the stored value."""
    try:
        val = float(n)
    except (TypeError, ValueError) as exc:
        raise AlertError(f"Threshold must be a number 0-100, got {n!r}.") from exc
    if not 0 <= val <= 100:
        raise AlertError(f"Threshold must be between 0 and 100, got {n}.")
    cfg = load_watch_config(path)
    cfg["alert_threshold"] = val
    p = Path(path) if path else _config_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return val


def passes_gate(result: dict, threshold: float) -> bool:
    """Alert when verdict is GO/CONDITIONAL, or score >= threshold."""
    return result.get("verdict") in _GOOD_VERDICTS or \
        float(result.get("score") or 0) >= threshold


# --- matching ------------------------------------------------------------------

def _posting_jd(posting: dict) -> str:
    """Best available JD text for scoring (posting jd/description, or title)."""
    for key in ("jd", "description", "text", "snippet"):
        v = posting.get(key)
        if v and str(v).strip():
            return str(v)
    parts = [posting.get("title") or "", posting.get("department") or "",
             posting.get("location") or ""]
    return " — ".join(p for p in parts if p)


# below this length the board text is too thin to score on, so we try the
# posting's own page (mirrors match.py's <600 "low parse confidence" cut).
_THIN_TEXT_CHARS = 600


def scoring_text(posting: dict) -> str:
    """Text to score a posting against.

    Board records carry no JD body, so when the board text is thin and the
    posting has a URL, fetch the posting page (plain HTTPS GET, same as the
    monitor engine's feed fetches). Any fetch failure falls back to the
    board text — a run never fails because one page didn't load.
    """
    text = _posting_jd(posting)
    url = posting.get("url") or ""
    if len(text.strip()) >= _THIN_TEXT_CHARS or not url:
        return text
    try:
        return M.fetch_jd(url)
    except M.MatchError:
        return text


def evaluate_postings(new_postings: list[dict], profile: dict,
                      threshold: float | None = None,
                      path: str | Path | None = None) -> dict:
    """Score new postings, create alerts for those passing the gate.

    Returns {"created": [...], "below_threshold": [...], "duplicates": [...],
             "total": int}. ``duplicates`` are postings that passed the gate
    but already have an unread alert (nothing new created). Uses
    candid.match.score_match — scoring logic is not duplicated here.
    """
    thr = get_threshold() if threshold is None else float(threshold)
    created, below, dupes = [], [], []
    for posting in new_postings:
        result = M.score_match(profile, scoring_text(posting),
                               title=posting.get("title") or "",
                               company=posting.get("company") or "",
                               location=posting.get("location") or "")
        score, verdict = result["score"], result["verdict"]
        entry = {"company": posting.get("company") or "",
                 "posting_id": str(posting.get("posting_id")
                                   or posting.get("id") or ""),
                 "title": posting.get("title") or "",
                 "url": posting.get("url") or "",
                 "score": score, "verdict": verdict}
        if not passes_gate(result, thr):
            below.append(entry)
            continue
        alert = create_alert(posting, score, verdict, path=path)
        if alert is None:
            dupes.append(entry)
        else:
            created.append(alert)
    return {"created": created, "below_threshold": below,
            "duplicates": dupes, "total": len(new_postings)}


# --- run state (for `watch status`) ---------------------------------------------

def load_runs(path: str | Path | None = None) -> dict:
    """Per-company last-run state. {} when no run has happened yet."""
    p = Path(path) if path else _runs_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AlertError(f"Watch runs file {p} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def record_run(new_postings: list[dict], closed_postings: list[dict],
               path: str | Path | None = None,
               companies: list[str] | None = None) -> dict:
    """Record per-company counts from a run. Returns the new runs state.

    open = previous open + new - closed (floored at 0). ``companies`` lists
    company names that were polled even with no activity, so `watch status`
    shows a last-run time for every watched company.
    """
    state = load_runs(path)
    companies_state = state.setdefault("companies", {})
    now = datetime.now().isoformat(timespec="seconds")
    new_by_co: dict[str, int] = {}
    for p in new_postings:
        co = p.get("company") or "?"
        new_by_co[co] = new_by_co.get(co, 0) + 1
    closed_by_co: dict[str, int] = {}
    for p in closed_postings:
        co = p.get("company") or "?"
        closed_by_co[co] = closed_by_co.get(co, 0) + 1
    for co in sorted(set(new_by_co) | set(closed_by_co)
                     | set(companies_state) | set(companies or [])):
        prev = companies_state.get(co, {})
        open_now = max(0, int(prev.get("open", 0))
                       + new_by_co.get(co, 0) - closed_by_co.get(co, 0))
        companies_state[co] = {"last_run": now,
                               "new": new_by_co.get(co, 0),
                               "closed": closed_by_co.get(co, 0),
                               "open": open_now}
    state["last_run"] = now
    p = Path(path) if path else _runs_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


# --- digest hook ------------------------------------------------------------------

def get_pending_alerts(path: str | Path | None = None) -> list[dict]:
    """Unread alerts formatted for the weekly coach digest.

    Import-safe: returns [] when the store is missing or unreadable, so a
    digest run never crashes on watch data (batch-2's digest.py may not exist
    yet — nothing here imports it).
    """
    try:
        alerts = load_alerts(path)
    except Exception:
        return []
    return [{"id": a.get("id"),
             "kind": a.get("kind", "new"),
             "company": a.get("company", ""),
             "title": a.get("title", ""),
             "score": a.get("score"),
             "verdict": a.get("verdict", ""),
             "url": a.get("url", ""),
             "message": a.get("message", ""),
             "created_at": a.get("created_at", "")}
            for a in alerts if not a.get("read", False)]


# --- rendering --------------------------------------------------------------------

def render_alerts(alerts: list[dict]) -> str:
    """Human-readable alert list."""
    if not alerts:
        return "No alerts."
    lines = []
    for a in alerts:
        flag = "●" if not a.get("read", False) else "○"
        lines.append(f"{flag} #{a.get('id')} [{a.get('kind', 'new')}] "
                     f"{a.get('title')} @ {a.get('company')} — "
                     f"{a.get('score', '?')}/100 ({a.get('verdict', '?')})")
        if a.get("message"):
            lines.append(f"    {a.get('message')}")
        if a.get("url"):
            lines.append(f"    {a.get('url')}")
    return "\n".join(lines)


def render_run_summary(result: dict, threshold: float,
                       n_closed: int = 0) -> str:
    """Human-readable summary of a watch run."""
    created, below, dupes = (result["created"], result["below_threshold"],
                             result["duplicates"])
    lines = [
        f"Watch run: {result['total']} new posting(s) seen, "
        f"{len(created)} new alert(s), {n_closed} closed.",
        f"Alert gate: verdict GO/CONDITIONAL, or score >= {threshold:g}.",
    ]
    for a in created:
        lines.append(f"  🔔 {a['message']}")
    if below:
        lines.append(f"  {len(below)} posting(s) below threshold (no alert).")
    if dupes:
        lines.append(f"  {len(dupes)} already alerted (deduped, unread).")
    return "\n".join(lines)


def render_status(companies: list[dict], runs: dict,
                  alerts: list[dict]) -> str:
    """Human-readable `watch status` output.

    companies: monitor-engine company entries ({"name", "sources", ...}).
    runs: state from load_runs(). alerts: all alerts from load_alerts().
    """
    runs_cos = runs.get("companies", {}) if runs else {}
    unread_by_co: dict[str, int] = {}
    for a in alerts:
        if not a.get("read", False):
            co = (a.get("company") or "").lower()
            unread_by_co[co] = unread_by_co.get(co, 0) + 1
    names = [c.get("company") or c.get("name", "") for c in companies] \
        or list(runs_cos)
    lines = ["Watched companies:"]
    for name in names:
        r = runs_cos.get(name, {})
        last = r.get("last_run", "never")
        unread = unread_by_co.get(name.lower(), 0)
        lines.append(f"  {name}: last run {last}, open {r.get('open', '?')}, "
                     f"last run new/closed {r.get('new', '?')}/{r.get('closed', '?')}, "
                     f"{unread} unread alert(s)")
    total_unread = sum(1 for a in alerts if not a.get("read", False))
    lines.append(f"Total alerts: {len(alerts)} ({total_unread} unread)")
    return "\n".join(lines)
