"""Company career-page monitors.

Watch specific companies' public career feeds (Greenhouse JSON boards,
Lever JSON postings API, or a generic RSS/Atom feed) and report what's
new, what's closed, and what's been reposted.

Storage (all under the candid data dir, git-ignored):
    monitors.json        — registry: companies + their feed sources
    monitor_history.json — per-company posting history (first_seen /
                           last_seen / status / miss counts)
    monitor_health.json  — per-source fetch health (consecutive failures)

Only public JSON/RSS endpoints are fetched — no keys, no logins, no
scraping beyond those feeds. HTTP errors, timeouts, and bad payloads are
recorded per source; a run never raises out of a poll.

Pipeline:
    add_company("Acme") → add_source("acme", "greenhouse", board="acmetoken")
    poll() → {"new": [...], "closed": [...], "reposts": [...],
              "errors": [...], "skipped": [...]}
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from candid import config as C
from candid.jobs import _parse_posted_at

USER_AGENT = "candid/0.2 (career-page monitor; personal use, local only)"
FETCH_TIMEOUT = 20

SOURCE_TYPES = ("greenhouse", "lever", "rss")
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false"
LEVER_API = "https://api.lever.co/v0/postings/{site}?mode=json"

# A posting missing from this many consecutive successful fetches is closed.
CLOSED_AFTER_MISSES = 3
# A "new" posting matching a closed one within this window is a repost.
REPOST_WINDOW_DAYS = 90
# Sources failing this many consecutive times are skipped until one works.
MAX_CONSECUTIVE_FAILURES = 5


class MonitorError(Exception):
    """Raised for registry mistakes (unknown company, bad source, dupes)."""


# ---------------------------------------------------------------------------
# paths + tiny JSON helpers
# ---------------------------------------------------------------------------

def _registry_path() -> Path:
    return C.DATA_DIR / "monitors.json"


def _history_path() -> Path:
    return C.DATA_DIR / "monitor_history.json"


def _health_path() -> Path:
    return C.DATA_DIR / "monitor_health.json"


def _load_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return default


def _save_json(path: Path, data: dict) -> None:
    C.ensure_data_dirs()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _today() -> str:
    return date.today().isoformat()


def _company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def _norm_title_location(title: str, location: str) -> tuple[str, str]:
    def n(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return (n(title), n(location))


# ---------------------------------------------------------------------------
# registry — companies and their feed sources
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    return _load_json(_registry_path(), {"companies": {}})


def _save_registry(reg: dict) -> None:
    _save_json(_registry_path(), reg)


def _require_company(reg: dict, name: str) -> tuple[str, dict]:
    key = _company_key(name)
    comp = reg["companies"].get(key)
    if comp is None:
        raise MonitorError(f"Unknown company {name!r}. "
                           f"Known: {', '.join(sorted(reg['companies'])) or 'none'}")
    return key, comp


def add_company(name: str) -> dict:
    """Register a company to monitor. Rejects duplicates (case-insensitive)."""
    name = (name or "").strip()
    if not name:
        raise MonitorError("Company name cannot be empty.")
    key = _company_key(name)
    reg = _load_registry()
    if key in reg["companies"]:
        raise MonitorError(f"Company {name!r} is already monitored.")
    comp = {"key": key, "name": name, "sources": []}
    reg["companies"][key] = comp
    _save_registry(reg)
    return comp


def remove_company(name: str) -> bool:
    """Remove a company, its sources, history, and health state."""
    reg = _load_registry()
    key, _ = _require_company(reg, name)
    del reg["companies"][key]
    _save_registry(reg)
    hist = _load_history()
    hist.get("companies", {}).pop(key, None)
    _save_history(hist)
    health = _load_health()
    for skey in [k for k in health.get("sources", {}) if k.startswith(key + ":")]:
        del health["sources"][skey]
    _save_health(health)
    return True


def list_companies() -> list[dict]:
    reg = _load_registry()
    return [reg["companies"][k] for k in sorted(reg["companies"])]


def get_company(name: str) -> dict:
    reg = _load_registry()
    _, comp = _require_company(reg, name)
    return comp


def _canonical_source(source_type: str, url: str | None,
                      board: str | None, site: str | None) -> dict:
    """Validate a source and return its canonical record."""
    if source_type not in SOURCE_TYPES:
        raise MonitorError(f"Unsupported source type {source_type!r}. "
                           f"Supported: {', '.join(SOURCE_TYPES)}")
    if source_type == "greenhouse":
        board = (board or "").strip()
        if not board:
            raise MonitorError("Greenhouse sources need a board token "
                               "(e.g. board='acmetoken').")
        url = GREENHOUSE_API.format(board=board)
        label = board
    elif source_type == "lever":
        site = (site or "").strip()
        if not site:
            raise MonitorError("Lever sources need a site name "
                               "(e.g. site='acme').")
        url = LEVER_API.format(site=site)
        label = site
    else:  # rss
        url = (url or "").strip()
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise MonitorError(f"RSS sources need an http(s) feed URL, got {url!r}.")
        label = url
    return {"type": source_type, "url": url, "label": label}


def add_source(company: str, source_type: str, url: str | None = None,
               board: str | None = None, site: str | None = None) -> dict:
    """Attach a feed source to a company. Rejects duplicate sources."""
    reg = _load_registry()
    key, comp = _require_company(reg, company)
    src = _canonical_source(source_type, url, board, site)
    for existing in comp["sources"]:
        if existing["url"].lower() == src["url"].lower():
            raise MonitorError(f"Source {src['url']} is already registered "
                               f"for {comp['name']!r}.")
    comp["sources"].append(src)
    _save_registry(reg)
    return src


def remove_source(company: str, index: int) -> dict:
    """Detach a source by its index in the company's source list."""
    reg = _load_registry()
    _, comp = _require_company(reg, company)
    if not isinstance(index, int) or not 0 <= index < len(comp["sources"]):
        raise MonitorError(f"Bad source index {index!r} for {comp['name']!r} "
                           f"({len(comp['sources'])} source(s)).")
    removed = comp["sources"].pop(index)
    _save_registry(reg)
    return removed


def list_sources(company: str) -> list[dict]:
    return get_company(company)["sources"]


# ---------------------------------------------------------------------------
# HTTP + source adapters — each returns normalized postings:
# {id, title, location, url, department, posted_date, raw}
# ---------------------------------------------------------------------------

def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return resp.read()


def _iso_date(value: object) -> str:
    """Best-effort normalize of a posted-date value to YYYY-MM-DD."""
    dt = _parse_posted_at(value)
    if dt is None:
        return ""
    return dt.date().isoformat()


def _parse_rss_date(value: str) -> str:
    """Parse RSS/Atom date strings (RFC-822 pubDate, ISO-8601 updated)."""
    s = (value or "").strip()
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt.date().isoformat()
    except (ValueError, TypeError):
        pass
    return _iso_date(s)


def _adapt_greenhouse(payload: object, company: dict, source: dict) -> list[dict]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    board = source.get("label", "")
    out = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        loc = j.get("location") or {}
        depts = j.get("departments") or []
        jid = j.get("id")
        out.append({
            "id": f"greenhouse:{board}:{jid}",
            "title": str(j.get("title") or "").strip(),
            "location": str(loc.get("name") if isinstance(loc, dict) else loc or "").strip(),
            "url": str(j.get("absolute_url") or ""),
            "department": str(depts[0].get("name") if depts and isinstance(depts[0], dict) else "").strip(),
            "posted_date": _iso_date(j.get("updated_at") or j.get("created_at")),
            "raw": {"board": board, "job_id": jid},
        })
    return out


def _adapt_lever(payload: object, company: dict, source: dict) -> list[dict]:
    jobs = payload if isinstance(payload, list) else []
    site = source.get("label", "")
    out = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        cats = j.get("categories") or {}
        created = j.get("createdAt")
        posted = ""
        if isinstance(created, (int, float)):
            posted = _iso_date(int(created) // 1000 if created > 1e12 else int(created))
        out.append({
            "id": f"lever:{site}:{j.get('id')}",
            "title": str(j.get("text") or "").strip(),
            "location": str(cats.get("location") or "").strip(),
            "url": str(j.get("hostedUrl") or j.get("applyUrl") or ""),
            "department": str(cats.get("department") or cats.get("team") or "").strip(),
            "posted_date": posted,
            "raw": {"site": site, "job_id": j.get("id")},
        })
    return out


def _rss_text(el: ET.Element, names: list[str]) -> str:
    for name in names:
        child = el.find(name)
        if child is not None and (child.text or "").strip():
            return child.text.strip()
    return ""


def _adapt_rss(payload: bytes, company: dict, source: dict) -> list[dict]:
    """Parse RSS 2.0 (channel/item) or Atom (feed/entry)."""
    root = ET.fromstring(payload)
    tag = root.tag
    # strip namespaces: {http://...}feed -> feed
    local = tag.rsplit("}", 1)[-1].lower()
    items: list[ET.Element] = []
    if local == "rss":
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")
        entry_tag = "item"
    elif local == "feed":
        ns = {"a": tag.split("}")[0].strip("{")} if "}" in tag else {}
        items = root.findall("a:entry", ns) if ns else root.findall("entry")
        entry_tag = "entry"
    else:
        # unknown root — try both shapes
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

    out = []
    for it in items:
        ns_uri = tag.split("}")[0].strip("{") if "}" in tag and local == "feed" else ""
        def find(name: str) -> ET.Element | None:  # noqa: B023
            if ns_uri:
                return it.find(f"{{{ns_uri}}}{name}")
            return it.find(name)
        title_el = find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = ""
        if entry_tag == "entry":
            for l in it.findall(f"{{{ns_uri}}}link") if ns_uri else it.findall("link"):
                if l.get("href"):
                    link = l.get("href")
                    break
        else:
            link_el = find("link")
            link = (link_el.text or "").strip() if link_el is not None else ""
        guid_el = find("guid") if entry_tag == "item" else find("id")
        guid = (guid_el.text or "").strip() if guid_el is not None else ""
        pub = ""
        for name in ("pubDate", "published", "updated", "date"):
            el = find(name)
            if el is not None and (el.text or "").strip():
                pub = _parse_rss_date(el.text.strip())
                break
        pid = guid or link or title
        digest = hashlib.sha1(pid.encode("utf-8")).hexdigest()[:16]
        out.append({
            "id": f"rss:{_company_key(company['name'])}:{digest}",
            "title": title,
            "location": "",
            "url": link,
            "department": "",
            "posted_date": pub,
            "raw": {"guid": guid, "link": link},
        })
    return [p for p in out if p["title"]]


_ADAPTERS = {
    "greenhouse": _adapt_greenhouse,
    "lever": _adapt_lever,
    "rss": _adapt_rss,
}


def fetch_source(company: dict, source: dict,
                 http_get=_http_get) -> tuple[list[dict], str | None]:
    """Fetch one source. Returns (postings, error); never raises."""
    try:
        payload = http_get(source["url"])
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code} for {source['url']}: {e.reason}"
    except urllib.error.URLError as e:
        return [], f"Unreachable {source['url']}: {e.reason}"
    except TimeoutError:
        return [], f"Timed out fetching {source['url']} (>{FETCH_TIMEOUT}s)"
    except Exception as e:  # socket.timeout, ssl errors, etc.
        return [], f"Fetch failed for {source['url']}: {e}"

    try:
        if source["type"] == "rss":
            return _ADAPTERS["rss"](payload, company, source), None
        data = json.loads(payload.decode("utf-8", errors="replace"))
        return _ADAPTERS[source["type"]](data, company, source), None
    except json.JSONDecodeError as e:
        return [], f"Bad JSON from {source['url']}: {e}"
    except ET.ParseError as e:
        return [], f"Bad XML from {source['url']}: {e}"
    except Exception as e:
        return [], f"Could not parse {source['url']}: {e}"


# ---------------------------------------------------------------------------
# posting history — first_seen / last_seen / miss counts / status
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    return _load_json(_history_path(), {"companies": {}})


def _save_history(hist: dict) -> None:
    _save_json(_history_path(), hist)


def _load_health() -> dict:
    return _load_json(_health_path(), {"sources": {}})


def _save_health(health: dict) -> None:
    _save_json(_health_path(), health)


def _source_key(company_key: str, source: dict) -> str:
    return f"{company_key}:{source['type']}:{source['label']}"


def get_history(company: str) -> dict:
    """Posting history for a company: {posting_id: record}."""
    hist = _load_history()
    return hist.get("companies", {}).get(_company_key(company), {}).get("postings", {})


def health() -> dict:
    """Per-source health: consecutive failures, last error/ok, skip state."""
    reg = _load_registry()
    h = _load_health()
    out = {}
    for ckey, comp in reg["companies"].items():
        for src in comp["sources"]:
            skey = _source_key(ckey, src)
            st = h.get("sources", {}).get(skey, {})
            fails = st.get("consecutive_failures", 0)
            out[skey] = {
                "company": comp["name"],
                "type": src["type"],
                "label": src["label"],
                "url": src["url"],
                "consecutive_failures": fails,
                "last_error": st.get("last_error", ""),
                "last_ok": st.get("last_ok", ""),
                "status": "skipped" if fails > MAX_CONSECUTIVE_FAILURES
                          else ("failing" if fails else "ok"),
            }
    return out


def diff_fetch(company_key: str, company_name: str, fetched: list[dict],
               successful_sources: set[str],
               closed_after: int = CLOSED_AFTER_MISSES,
               today: str | None = None) -> dict:
    """Compare a fetch against history; update history in place.

    Returns {"new": [...], "closed": [...], "reposts": [...]} where each
    entry is the posting record. Newly closed postings get
    status "closed" + closed_at; reposts (same title+location reopened
    within REPOST_WINDOW_DAYS) are flagged on the new record.
    """
    today = today or _today()
    hist = _load_history()
    comp_hist = hist.setdefault("companies", {}).setdefault(
        company_key, {"name": company_name, "postings": {}})
    postings: dict = comp_hist["postings"]

    seen_ids = {p["id"] for p in fetched}
    new, closed, reposts = [], [], []

    for p in fetched:
        rec = postings.get(p["id"])
        if rec is None:
            rec = {
                "id": p["id"], "title": p["title"], "location": p["location"],
                "url": p["url"], "department": p.get("department", ""),
                "posted_date": p.get("posted_date", ""),
                "first_seen": today, "last_seen": today,
                "miss_count": 0, "status": "open", "closed_at": "",
                "source_keys": [],
                "repost": False, "repost_of": "",
            }
            postings[p["id"]] = rec
            new.append(rec)
        else:
            rec.update({"title": p["title"], "location": p["location"],
                        "url": p["url"] or rec["url"],
                        "department": p.get("department", "") or rec["department"],
                        "posted_date": p.get("posted_date", "") or rec["posted_date"],
                        "last_seen": today, "miss_count": 0})
            if rec["status"] == "closed":
                # a closed posting showing up again is a repost by definition
                rec["status"] = "open"
                rec["closed_at"] = ""
                rec["repost"] = True
                new.append(rec)
        for sk in successful_sources:
            if sk not in rec["source_keys"]:
                rec["source_keys"].append(sk)

    for pid, rec in postings.items():
        if pid in seen_ids or rec["status"] != "open":
            continue
        # Only accrue misses when every source that ever carried this
        # posting was successfully fetched — otherwise absence is not signal.
        if not all(sk in successful_sources for sk in rec["source_keys"]):
            continue
        rec["miss_count"] += 1
        if rec["miss_count"] >= closed_after:
            rec["status"] = "closed"
            rec["closed_at"] = today
            closed.append(rec)

    # repost detection: new posting whose normalized title+location matches a
    # posting closed within REPOST_WINDOW_DAYS (and that isn't the same id)
    for rec in new:
        if rec.get("repost"):
            continue  # already flagged via id match above
        key = _norm_title_location(rec["title"], rec["location"])
        cutoff = (datetime.fromisoformat(today) - timedelta(days=REPOST_WINDOW_DAYS)).date().isoformat()
        for other in postings.values():
            if other["id"] == rec["id"] or other["status"] != "closed":
                continue
            if not other.get("closed_at") or other["closed_at"] < cutoff:
                continue
            if _norm_title_location(other["title"], other["location"]) == key:
                rec["repost"] = True
                rec["repost_of"] = other["id"]
                reposts.append(rec)
                break

    _save_history(hist)
    return {"new": new, "closed": closed, "reposts": reposts}


# ---------------------------------------------------------------------------
# polling — fetch everything, update history + health, summarize
# ---------------------------------------------------------------------------

def poll(company: str | None = None, closed_after: int = CLOSED_AFTER_MISSES,
         http_get=_http_get, today: str | None = None) -> dict:
    """Poll all (or one) companies' sources. Never raises.

    Returns {"date", "companies": {key: {"fetched", "new", "closed",
    "reposts", "errors", "skipped"}}, "totals": {...}}.
    """
    today = today or _today()
    reg = _load_registry()
    companies = reg["companies"]
    if company is not None:
        ckey, comp = _require_company(reg, company)
        companies = {ckey: comp}

    health = _load_health()
    src_health: dict = health.setdefault("sources", {})
    summary = {"date": today, "companies": {},
               "totals": {"new": 0, "closed": 0, "reposts": 0,
                          "errors": 0, "skipped": 0}}

    for ckey, comp in companies.items():
        fetched: list[dict] = []
        errors, skipped = [], []
        successful: set[str] = set()
        for src in comp["sources"]:
            skey = _source_key(ckey, src)
            st = src_health.setdefault(
                skey, {"consecutive_failures": 0, "last_error": "", "last_ok": ""})
            if st["consecutive_failures"] > MAX_CONSECUTIVE_FAILURES:
                skipped.append(f"{src['type']}:{src['label']} "
                               f"(failing {st['consecutive_failures']}x in a row)")
                continue
            postings, err = fetch_source(comp, src, http_get=http_get)
            if err:
                st["consecutive_failures"] += 1
                st["last_error"] = err
                errors.append(err)
            else:
                st["consecutive_failures"] = 0
                st["last_error"] = ""
                st["last_ok"] = today
                successful.add(skey)
                fetched.extend(postings)

        diff = diff_fetch(ckey, comp["name"], fetched, successful,
                          closed_after=closed_after, today=today)
        summary["companies"][ckey] = {
            "name": comp["name"],
            "fetched": len(fetched),
            "new": diff["new"],
            "closed": diff["closed"],
            "reposts": diff["reposts"],
            "errors": errors,
            "skipped": skipped,
        }
        t = summary["totals"]
        t["new"] += len(diff["new"])
        t["closed"] += len(diff["closed"])
        t["reposts"] += len(diff["reposts"])
        t["errors"] += len(errors)
        t["skipped"] += len(skipped)

    _save_health(health)
    return summary


def render_summary(summary: dict) -> str:
    """Human-readable one-screen poll report."""
    lines = [f"Monitor poll — {summary['date']}"]
    t = summary["totals"]
    lines.append(f"new: {t['new']}  closed: {t['closed']}  "
                 f"reposts: {t['reposts']}  errors: {t['errors']}  "
                 f"skipped sources: {t['skipped']}")
    for ckey, c in summary["companies"].items():
        lines.append(f"\n{c['name']} ({c['fetched']} postings fetched)")
        for p in c["new"]:
            tag = " [REPOST]" if p.get("repost") else ""
            lines.append(f"  + {p['title']} — {p['location']}{tag}")
            if p.get("url"):
                lines.append(f"      {p['url']}")
        for p in c["closed"]:
            lines.append(f"  − {p['title']} — {p['location']} (closed)")
        for e in c["errors"]:
            lines.append(f"  ⚠ {e}")
        for s in c["skipped"]:
            lines.append(f"  ⏭ skipped: {s}")
    return "\n".join(lines)
