"""Job curation: discover open postings, score them against the profile,
and feed the best into the application tracker.

Sources are free public JSON APIs that need no key, no login, and no
scraping: each adapter is a small function you can extend. Boards that sit
behind logins or forbid automated access (LinkedIn, Indeed, …) are
deliberately out of scope — for those, paste the JD into
``python -m candid match`` / ``tailor`` instead. See
``docs/adding_sources.md`` and the README for honest coverage notes.

Pipeline:
    jobs curate --role "Data Scientist" --location "New York" [--remote] [--level senior]
        → fetch from adapters → filter/rank → score vs profile →
          new finds enter the tracker as status ``saved`` with match score
          and a one-line "why this fits" note.
    jobs list [--status saved]   → curated pipeline with scores + apply URLs
    jobs refresh                → re-run curation; report only what's new

Everything is stored locally (tracker JSON + candid_data/jobs.json).
Fetched listings are treated as *data* — never executed as code.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from candid import config as C

def _state_path() -> Path:
    return C.DATA_DIR / "jobs.json"
USER_AGENT = "candid/0.1 (personal job curation; contact: user-local)"
FETCH_TIMEOUT = 20
MAX_PER_SOURCE = 100
DEFAULT_LIMIT = 15


class JobsError(Exception):
    """Raised for curation failures."""


# ---------------------------------------------------------------------------
# adapters — each returns normalized job dicts:
# {source, source_id, title, company, location, url, description,
#  salary_text, remote (bool), posted_at}
# ---------------------------------------------------------------------------

def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _get_text(url: str) -> str:
    """Fetch a URL as text (for RSS/XML feeds). 20s timeout, UA set."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _adapt_arbeitnow() -> list[dict]:
    """Arbeitnow job board API — free, no key. EU-skewed coverage."""
    try:
        payload = _get_json("https://www.arbeitnow.com/api/job-board-api")
    except Exception as exc:
        raise JobsError(f"Arbeitnow unreachable: {exc}") from exc
    items = payload.get("data", []) if isinstance(payload, dict) else []
    out = []
    for j in items[:MAX_PER_SOURCE]:
        desc = re.sub(r"<[^>]+>", " ", j.get("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        out.append({
            "source": "arbeitnow",
            "source_id": f"arbeitnow:{j.get('slug')}",
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company_name") or "").strip(),
            "location": (j.get("location") or "").strip(),
            "url": j.get("url") or "",
            "description": desc[:4000],
            "salary_text": "",
            "remote": bool(j.get("remote")),
            "posted_at": str(j.get("created_at") or ""),
        })
    return out


_MOJIBAKE_MARKERS = set("ÃØÙàâäåæçèéêëìíîïðñòóôõöøùúûýþÿĀā")
_C1 = set(range(0x80, 0xA0))


def _fix_mojibake(s: str) -> str:
    """Repair double-encoded UTF-8 (e.g. RemoteOK serves some locations as
    mojibake like 'Ø¯Ø¨Ù\\x8a' instead of 'دبي'). Only touches strings that
    look mojibake-y and round-trip cleanly through latin-1 -> UTF-8."""
    if not s or not any(ord(c) > 127 for c in s):
        return s
    if not any(ord(c) in _C1 or c in _MOJIBAKE_MARKERS for c in s):
        return s
    try:
        fixed = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return fixed


def _adapt_remoteok() -> list[dict]:
    """RemoteOK API — free, no key, remote-only. Needs a User-Agent."""
    try:
        payload = _get_json("https://remoteok.com/api")
    except Exception as exc:
        raise JobsError(f"RemoteOK unreachable: {exc}") from exc
    items = payload if isinstance(payload, list) else []
    out = []
    for j in items[:MAX_PER_SOURCE]:
        if not isinstance(j, dict) or "position" not in j:
            continue  # first element is a legal notice
        desc = re.sub(r"<[^>]+>", " ", j.get("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        salary_text = ""
        if j.get("salary_min") or j.get("salary_max"):
            salary_text = f"${j.get('salary_min') or '?'} - ${j.get('salary_max') or '?'}"
        out.append({
            "source": "remoteok",
            "source_id": f"remoteok:{j.get('id')}",
            "title": _fix_mojibake((j.get("position") or "").strip()),
            "company": _fix_mojibake((j.get("company") or "").strip()),
            "location": _fix_mojibake((j.get("location") or "Remote").strip()),
            "url": j.get("url") or "",
            "description": desc[:4000],
            "salary_text": salary_text,
            "remote": True,
            "posted_at": str(j.get("date") or ""),
        })
    return out


ADAPTERS: dict[str, object] = {
    "arbeitnow": _adapt_arbeitnow,
    "remoteok": _adapt_remoteok,
}
# Batch-14 adds eight more adapter keys (built on sibling branches):
#   wellfound, builtin, dice, authenticjobs, remotive, weworkremotely,
#   fourdayweek, remoteco
# The dedupe / freshness / saved-search machinery below is adapter-agnostic:
# it works with just the two baseline feeds and with all ten boards.


# ---------------------------------------------------------------------------
# cross-board dedupe
# ---------------------------------------------------------------------------

def _richness(job: dict) -> tuple[int, int]:
    """Richness key for dedupe: (has salary_text, description length)."""
    sal = 1 if (job.get("salary_text") or "").strip() else 0
    return (sal, len(job.get("description") or ""))


def dedupe_cross_board(jobs: list[dict]) -> list[dict]:
    """Collapse cross-board duplicates (same normalized title+company).

    Keeps the listing with the richest data (has ``salary_text`` wins, then
    longer description) and records the merged source names on the keeper as
    ``also_seen_on``. Stable: ties keep the first-seen copy. Robust to any
    adapter mix — works with just arbeitnow/remoteok or all ten boards, and
    ignores extra keys (e.g. ``extras``) that some adapters add.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for job in jobs:
        key = _norm_key(job.get("title", ""), job.get("company", ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(job)
    out = []
    for key in order:
        copies = groups[key]
        best = max(range(len(copies)),
                   key=lambda i: (_richness(copies[i]), -i))
        keeper = dict(copies[best])
        merged = [c.get("source") for i, c in enumerate(copies)
                  if i != best and c.get("source")]
        existing = list(keeper.get("also_seen_on") or [])
        keeper["also_seen_on"] = existing + [s for s in merged
                                             if s not in existing]
        out.append(keeper)
    return out


def _adapt_dice() -> list[dict]:
    """Dice (dice.com) — tech jobs. Currently a documented no-op.

    Checked 2026-09-22: Dice has no public no-login, no-key search endpoint.
    The official Jobs API was shut down ~2017; the old public RSS feed
    (dice.com/jobs/rss) now serves the HTML search page instead of RSS; and
    direct requests from programmatic clients are blocked. Scraping the
    JS-driven search page is out of scope per the source rules (no scraping,
    no auth, no keys). This adapter therefore returns no listings and never
    invents them. It stays registered so that if Dice ever publishes a
    public feed again, re-enabling is a one-line change.
    """
    return []

ADAPTERS["dice"] = _adapt_dice


def _adapt_authenticjobs() -> list[dict]:
    """Authentic Jobs — public RSS feed of job listings, no key, no login."""
    try:
        text = _get_text("https://authenticjobs.com/?feed=job_feed")
    except Exception as exc:
        raise JobsError(f"Authentic Jobs unreachable: {exc}") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise JobsError(f"Authentic Jobs feed malformed: {exc}") from exc
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    out = []
    for item in items[:MAX_PER_SOURCE]:
        # Local-name lookup keeps working even if the custom namespace
        # (https://authenticjobs.com) ever changes.
        def field(name: str) -> str:
            for child in item:
                if child.tag.rsplit("}", 1)[-1] == name:
                    return (child.text or "").strip()
            return ""

        guid = field("guid") or field("link")
        company = field("company") or field("creator")
        html = field("encoded") or field("description")
        desc = re.sub(r"<[^>]+>", " ", html)
        desc = re.sub(r"\s+", " ", desc).strip()
        posted = field("pubDate")
        try:
            posted = parsedate_to_datetime(posted).date().isoformat()
        except (TypeError, ValueError):
            posted = str(posted)
        out.append({
            "source": "authenticjobs",
            "source_id": f"authenticjobs:{guid.strip()}",
            "title": _fix_mojibake(field("title")),
            "company": _fix_mojibake(company),
            "location": _fix_mojibake(field("location")),
            "url": field("link"),
            "description": _fix_mojibake(desc)[:4000],
            "salary_text": "",  # the feed carries no salary data
            "remote": "remote" in field("location").lower(),
            "posted_at": posted,
        })
    return out

ADAPTERS["authenticjobs"] = _adapt_authenticjobs


# ---------------------------------------------------------------------------
# batch-14 niche boards — one adapter + its registration per board, kept
# adjacent so parallel workers' additions merge without conflicts
# ---------------------------------------------------------------------------

def _get_text(url: str) -> str:
    """Fetch a page body as text. Polite: real User-Agent, 20s timeout."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _clean_html(text: str, limit: int = 4000) -> str:
    """Strip tags/entities, collapse whitespace, trim, cap length."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


_BUILTIN_JOBS_URL = "https://builtin.com/jobs"


def _builtin_posted_at(label: str) -> str:
    """Best-effort conversion of Built In's relative posted labels
    ('Yesterday', '3 days ago', '2w') into an ISO date. '' when unknown."""
    label = (label or "").lower().replace("reposted", "").strip()
    if not label or label in {"today", "just now", "new"}:
        days = 0
    elif label == "yesterday":
        days = 1
    elif re.fullmatch(r"(\d+)\s*(?:minutes?|mins?|hours?|hrs?)\s*ago", label):
        days = 0  # "6 minutes ago", "3 hours ago" — today
    else:
        m = (re.fullmatch(r"(\d+)\s*(?:days?|d)\s*ago", label)
             or re.fullmatch(r"(\d+)\s*d", label))
        if m:
            days = int(m.group(1))
        else:
            m = (re.fullmatch(r"(\d+)\s*(?:weeks?|w)\s*ago", label)
                 or re.fullmatch(r"(\d+)\s*w", label))
            if m:
                days = 7 * int(m.group(1))
            else:
                m = re.fullmatch(r"(\d+)\s*(?:months?|mo)\s*ago", label)
                if m:
                    days = 30 * int(m.group(1))
                else:
                    return ""
    return (datetime.now().date() - timedelta(days=days)).isoformat()


def _builtin_salary_chip(chip: str) -> bool:
    low = chip.lower()
    return ("$" in chip or re.search(r"\d\s*k\b", low)) and bool(
        re.search(r"\d", chip))


def _adapt_builtin() -> list[dict]:
    """Built In (builtin.com) tech/startup listings.

    No public JSON API exists (probed 2026-09-22: /api/jobs 404s; the
    /jobs/api/search route and Accept: application/json both return the
    server-rendered HTML page), so this parses the public server-rendered
    listing page: the embedded schema.org ItemList JSON-LD (title, url,
    description) plus the server-rendered job cards (company, work mode,
    location, salary, seniority). One request per run; polite headers.

    Extras captured where present: work_mode, seniority, industry.
    Company size/stage and funding are NOT on the listing page (detail
    pages only, which we do not fetch — one request per run).
    """
    try:
        page = _get_text(_BUILTIN_JOBS_URL)
    except Exception as exc:
        raise JobsError(f"Built In unreachable: {exc}") from exc

    # 1) embedded JSON-LD: absolute job url -> item (title/description)
    by_url: dict[str, dict] = {}
    for m in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            page, re.S):
        try:
            doc = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        graph = doc.get("@graph") if isinstance(doc, dict) else None
        for node in graph or []:
            if not isinstance(node, dict) or node.get("@type") != "ItemList":
                continue
            for item in node.get("itemListElement") or []:
                url = item.get("url") if isinstance(item, dict) else ""
                if url:
                    by_url[str(url).rstrip("/")] = item

    # 2) server-rendered job cards, split on their id markers
    marks = list(re.finditer(r'id="job-card-(\d+)"', page))
    out = []
    for i, mark in enumerate(marks):
        job_id = mark.group(1)
        end = marks[i + 1].start() if i + 1 < len(marks) else mark.start() + 20000
        seg = page[mark.start():end]

        tag = re.search(r'<a\s[^>]*data-id="job-card-title"[^>]*>(.*?)</a>',
                        seg, re.S)
        if not tag:
            continue  # malformed card — skip, don't fail the run
        href = re.search(r'href="([^"]+)"', tag.group(0))
        url = ("https://builtin.com" + href.group(1)) if href else ""
        title = _clean_html(tag.group(1), limit=200)

        comp = re.search(r'data-id="company-title"[^>]*>.*?<span>(.*?)</span>',
                         seg, re.S)
        company = _clean_html(comp.group(1), limit=200) if comp else ""

        posted_m = re.search(
            r'<i class="fa-regular fa-clock[^>]*></i>(.*?)</span>', seg, re.S)
        posted_at = _builtin_posted_at(posted_m.group(1)) if posted_m else ""

        chips = []
        for c in re.findall(
                r'<span class="font-barlow text-gray-04[^"]*"[^>]*>(.*?)</span>',
                seg, re.S):
            t = _clean_html(c, limit=120)
            if t and t not in chips:
                chips.append(t)

        work_mode = location = salary_text = seniority = ""
        for chip in chips:
            low = chip.lower()
            if _builtin_salary_chip(chip):
                salary_text = chip
            elif "level" in low or low in {"junior", "senior", "entry"}:
                seniority = chip
            elif any(k in low for k in
                     ("remote", "hybrid", "office", "on-site", "on site")):
                work_mode = chip
            elif not location:
                location = chip

        desc = ""
        item = by_url.get(url.rstrip("/"))
        if isinstance(item, dict):
            desc = _clean_html(str(item.get("description") or ""))
        if not desc:  # fall back to the card's own description block
            dm = re.search(
                r'<div class="fs-sm fw-regular mb-md text-gray-04">(.*?)</div>',
                seg, re.S)
            if dm:
                desc = _clean_html(dm.group(1))

        ind = re.search(r'<div class="mb-md fs-xs fw-bold">([^<>]{1,80})</div>',
                        seg)
        industry = _clean_html(ind.group(1), limit=80) if ind else ""

        out.append({
            "source": "builtin",
            "source_id": f"builtin:{job_id}",
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": desc[:4000],
            "salary_text": salary_text,
            "remote": "remote" in work_mode.lower()
                      or location.lower() == "remote",
            "posted_at": posted_at,
            "work_mode": work_mode,
            "seniority": seniority,
            "industry": industry,
        })
        if len(out) >= MAX_PER_SOURCE:
            break
    return out


_REMOTIVE_API = "https://remotive.com/api/remote-jobs"


def _adapt_remotive(search: str | None = None) -> list[dict]:
    """Remotive public API — free, no key. Remote-only job board.

    ``search`` optionally filters server-side (e.g. ``?search=engineer``);
    with no argument the adapter fetches the general feed.
    """
    url = _REMOTIVE_API
    if search:
        url += f"?search={urllib.parse.quote_plus(search)}"
    try:
        payload = _get_json(url)
    except Exception as exc:
        raise JobsError(f"Remotive unreachable: {exc}") from exc
    items = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise JobsError("Remotive returned an unexpected payload shape")
    out = []
    for j in items[:MAX_PER_SOURCE]:
        if not isinstance(j, dict):
            continue
        desc = _clean_html(j.get("description") or "")
        job_type = str(j.get("job_type") or "").replace("_", " ").strip()
        category = _fix_mojibake(str(j.get("category") or "").strip())
        tags = " / ".join(p for p in (category, job_type) if p)
        if tags:
            desc += f" [category: {tags}]"
        desc = desc[:4000]
        location = _fix_mojibake(str(j.get("candidate_required_location") or "").strip())
        out.append({
            "source": "remotive",
            "source_id": f"remotive:{j.get('id')}",
            "title": _fix_mojibake(str(j.get("title") or "").strip()),
            "company": _fix_mojibake(str(j.get("company_name") or "").strip()),
            "location": location or "Remote",
            "url": j.get("url") or "",
            "description": desc,
            "salary_text": str(j.get("salary") or "").strip(),
            "remote": True,
            "posted_at": str(j.get("publication_date") or ""),
        })
    return out


ADAPTERS["remotive"] = _adapt_remotive


_WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]


def _wwr_split_title(title: str) -> tuple[str, str]:
    """WWR item titles use the 'Company: Title' convention. Split off the
    company name; titles without a colon keep the whole title as the job
    title with an empty company."""
    title = _fix_mojibake(title.strip())
    title = re.sub(r"\s*[\[(]remote[\])]\s*$", "", title, flags=re.IGNORECASE)
    if ": " in title:
        company, job_title = title.split(": ", 1)
        return company.strip(), job_title.strip()
    return "", title.strip()


def _adapt_weworkremotely(categories: list[str] | None = None) -> list[dict]:
    """We Work Remotely RSS feeds — free, no key. Remote-only.

    ``categories`` overrides the default feed list; capped at 3 feeds per
    run to stay polite.
    """
    feeds = list(categories) if categories else list(_WWR_FEEDS)
    out: list[dict] = []
    for feed_url in feeds[:3]:
        try:
            raw = _get_text(feed_url)
        except Exception as exc:
            raise JobsError(f"We Work Remotely unreachable ({feed_url}): {exc}") from exc
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise JobsError(f"We Work Remotely feed unparseable ({feed_url}): {exc}") from exc
        for item in root.iter("item"):
            if len(out) >= MAX_PER_SOURCE:
                break
            company, job_title = _wwr_split_title(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or "").strip() or link
            desc = _clean_html(item.findtext("description") or "")
            category = _fix_mojibake((item.findtext("category") or "").strip())
            if category:
                desc += f" [category: {category}]"
            desc = desc[:4000]
            region = _fix_mojibake((item.findtext("region") or "").strip())
            out.append({
                "source": "weworkremotely",
                "source_id": f"weworkremotely:{guid}",
                "title": job_title,
                "company": company,
                "location": region or "Remote",
                "url": link,
                "description": desc,
                "salary_text": "",
                "remote": True,
                "posted_at": (item.findtext("pubDate") or "").strip(),
            })
        if len(out) >= MAX_PER_SOURCE:
            break
    return out


ADAPTERS["builtin"] = _adapt_builtin


_WELLFOUND_JOBS_URL = "https://wellfound.com/jobs/search"


def _wellfound_find_jobs(obj: object) -> list[dict]:
    """Recursively collect job-shaped dicts from an embedded payload.

    Wellfound's schema is not documented; a dict counts as a job when it
    carries a title-like key plus a company-like key with a non-empty
    string title.
    """
    found: list[dict] = []
    if isinstance(obj, dict):
        low = {str(k).lower(): k for k in obj.keys()}
        tkey = next((low[k] for k in ("title", "jobtitle", "job_title")
                     if k in low), None)
        ckey = next((low[k] for k in ("company", "companyname", "company_name")
                     if k in low), None)
        if tkey and ckey and isinstance(obj[tkey], str) and obj[tkey].strip():
            found.append(obj)
        else:
            for v in obj.values():
                found.extend(_wellfound_find_jobs(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_wellfound_find_jobs(v))
    return found


def _wellfound_str(val: object) -> str:
    if isinstance(val, dict):  # company may be nested {"name": ...}
        for k in ("name", "companyName", "title"):
            if isinstance(val.get(k), str):
                return val[k].strip()
        return ""
    return str(val or "").strip()


def _adapt_wellfound() -> list[dict]:
    """Wellfound (wellfound.com, formerly AngelList Talent) startup jobs.

    Limitation (verified 2026-09-22): Wellfound exposes no clean public
    JSON/API endpoint for job search, and the public server-rendered
    /jobs/search page is a client-rendered Next.js shell — its embedded
    __NEXT_DATA__ carries only viewer/feature-flag state, no listings.
    Results load via JS (Apollo GraphQL), which is out of scope, so this
    adapter currently returns []. The embedded payload is re-checked on
    every run, so if Wellfound ever server-renders listings again they
    will be normalized and picked up without code changes. Never invents
    listings.
    """
    try:
        page = _get_text(_WELLFOUND_JOBS_URL)
    except Exception as exc:
        raise JobsError(f"Wellfound unreachable: {exc}") from exc

    jobs: list[dict] = []
    for m in re.finditer(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                         page, re.S):
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        jobs.extend(_wellfound_find_jobs(payload))

    out = []
    for j in jobs[:MAX_PER_SOURCE]:
        low = {str(k).lower(): v for k, v in j.items()}
        title = _wellfound_str(low.get("title") or low.get("jobtitle")
                               or low.get("job_title"))
        if not title:
            continue
        company = _wellfound_str(low.get("company") or low.get("companyname")
                                 or low.get("company_name"))
        jid = _wellfound_str(low.get("id") or low.get("jobid")
                             or low.get("job_id") or low.get("slug"))
        url = _wellfound_str(low.get("url") or low.get("joburl")
                             or low.get("job_url"))
        if not url and jid:
            url = f"https://wellfound.com/jobs/{jid}"
        out.append({
            "source": "wellfound",
            "source_id": f"wellfound:{jid or url or title}",
            "title": title,
            "company": company,
            "location": _wellfound_str(low.get("location")),
            "url": url,
            "description": _clean_html(str(low.get("description") or "")),
            "salary_text": _wellfound_str(low.get("salary") or low.get("salary_text")),
            "remote": bool(low.get("remote")),
            "posted_at": _wellfound_str(low.get("posted_at") or low.get("created_at")),
        })
    return out


ADAPTERS["wellfound"] = _adapt_wellfound
ADAPTERS["weworkremotely"] = _adapt_weworkremotely


# ---------------------------------------------------------------------------
# batch-14 niche boards — each adapter registers itself directly next to its
# function so parallel workers' additions merge without conflicts.
# ---------------------------------------------------------------------------

_FOURDAYWEEK_API = "https://4dayweek.io/api/jobs"

_FOURDAYWEEK_SCHEDULES = {
    "4_day_week": "4-day week",
    "4_day_week_pro_rata": "4-day week (pro rata)",
    "compressed_week": "compressed work week",
    "rotating_4_day": "rotating 4-day schedule",
}


def _fourdayweek_location(j: dict) -> str:
    parts: list[str] = []
    for loc in j.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        city = (loc.get("city") or "").strip()
        country = (loc.get("country") or "").strip()
        if city and country:
            parts.append(f"{city}, {country}")
        elif country or city:
            parts.append(country or city)
    if j.get("work_arrangement") == "remote":
        return f"Remote ({parts[0]})" if len(set(parts)) == 1 else "Remote"
    return parts[0] if parts else ""


def _fourdayweek_posted_at(j: dict) -> str:
    try:
        return datetime.fromtimestamp(int(j.get("posted") or 0),
                                      tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _norm_fourdayweek(j: dict) -> dict:
    """Normalize one 4dayweek.io list-feed job dict."""
    company = (j.get("company_name") or "").strip()
    if not company:
        comp = j.get("company")
        if isinstance(comp, dict):
            company = (comp.get("name") or "").strip()
    slug = (j.get("slug") or "").strip()
    bits = ["4dayweek.io posting — roles with a 4-day week / reduced-hours schedule."]
    sched = _FOURDAYWEEK_SCHEDULES.get(j.get("schedule_type") or "")
    if sched:
        bits.append(f"Schedule: {sched}.")
    if j.get("work_arrangement"):
        bits.append(f"Arrangement: {j['work_arrangement']}.")
    if j.get("category"):
        bits.append(f"Category: {j['category']}.")
    if j.get("work_life_score") is not None:
        bits.append(f"Work-life score: {j['work_life_score']}/100.")
    return {
        "source": "fourdayweek",
        "source_id": f"fourdayweek:{j.get('id')}",
        "title": _fix_mojibake((j.get("title") or "").strip()),
        "company": _fix_mojibake(company),
        "location": _fix_mojibake(_fourdayweek_location(j)),
        "url": f"https://4dayweek.io/job/{slug}" if slug else "",
        "description": " ".join(bits)[:4000],
        "salary_text": "",
        "remote": j.get("work_arrangement") == "remote",
        "posted_at": _fourdayweek_posted_at(j),
    }


def _adapt_fourdayweek() -> list[dict]:
    """4dayweek.io public JSON feed — 4-day-week / reduced-hours roles.

    No key, no login. Paginates ?page=N (25/page) until MAX_PER_SOURCE or
    the feed reports has_more=False; expired postings are skipped.
    Honest limits: the list feed carries no job descriptions or salary, so
    ``description`` is a short summary (schedule/arrangement/category) and
    ``salary_text`` is blank — nothing is scraped or invented.
    Job-page URLs (https://4dayweek.io/job/{slug}) verified 2026-09-22.
    """
    out: list[dict] = []
    page = 1
    while len(out) < MAX_PER_SOURCE:
        try:
            payload = _get_json(f"{_FOURDAYWEEK_API}?page={page}")
        except Exception as exc:
            raise JobsError(f"4dayweek.io unreachable: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise JobsError("4dayweek.io: unexpected response shape "
                            "(expected {'jobs': [...]})")
        for j in payload["jobs"]:
            if not isinstance(j, dict) or j.get("is_expired"):
                continue
            out.append(_norm_fourdayweek(j))
            if len(out) >= MAX_PER_SOURCE:
                break
        if not payload.get("has_more") or not payload["jobs"]:
            break
        page += 1
    return out


ADAPTERS["fourdayweek"] = _adapt_fourdayweek


_REMOTECO_FEED = "https://remote.co/remote-jobs/feed/"


def _norm_remoteco_item(item: ET.Element) -> dict:
    """Normalize one Remote.co RSS <item> (WordPress feed)."""

    def text(tag: str) -> str:
        el = item.find(tag)
        return (el.text or "").strip() if el is not None else ""

    creator = ""
    for tag in ("{http://purl.org/dc/elements/1.1/}creator", "creator"):
        el = item.find(tag)
        if el is not None and (el.text or "").strip():
            creator = el.text.strip()
            break
    link = text("link")
    guid = text("guid") or link
    desc = re.sub(r"<[^>]+>", " ", text("description") or "")
    desc = re.sub(r"\s+", " ", desc).strip()
    posted = text("pubDate")
    try:
        posted_at = parsedate_to_datetime(posted).date().isoformat()
    except (TypeError, ValueError):
        posted_at = posted
    return {
        "source": "remoteco",
        "source_id": f"remoteco:{guid}",
        "title": _fix_mojibake(text("title")),
        "company": _fix_mojibake(creator),
        "location": "Remote",  # remote.co lists remote-only roles
        "url": link,
        "description": desc[:4000],
        "salary_text": "",
        "remote": True,
        "posted_at": posted_at,
    }


def _adapt_remoteco() -> list[dict]:
    """Remote.co public RSS feed — remote-only postings. No key, no login.

    Checked 2026-09-22: the feed URL is public, but the server silently
    drops automated requests — every fetch from our network times out with
    zero bytes (an independent June 2026 probe recorded the same timeout
    for this exact URL). There is no login or key path, so when the feed is
    unreachable the adapter returns [] instead of failing the run — no
    listings are invented. When the feed does respond, items are parsed with
    stdlib xml.etree only (no new dependencies); malformed feeds raise
    JobsError. See docs/adding_sources.md for the full note.
    """
    try:
        raw = _get_text(_REMOTECO_FEED)
    except urllib.error.HTTPError as exc:
        raise JobsError(f"Remote.co feed HTTP {exc.code}") from exc
    except Exception:
        # unreachable (silently-dropped connections as of 2026-09-22) — empty
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise JobsError(f"Remote.co feed is not valid RSS: {exc}") from exc
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall("item")
    if channel is None and not items:
        raise JobsError("Remote.co feed: no RSS channel/items found")
    return [_norm_remoteco_item(i) for i in items[:MAX_PER_SOURCE]]


ADAPTERS["remoteco"] = _adapt_remoteco


# ---------------------------------------------------------------------------
# filtering / ranking / scoring
# ---------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", (s or "").lower()))


def _role_phrases(role: str) -> list[str]:
    """Multi-word phrases from the wanted role, longest first.

    A title containing the literal phrase 'data scientist' is a stronger
    signal than one containing 'data' and 'scientist' separately.
    """
    toks = [t for t in re.findall(r"[a-z0-9+#]+", (role or "").lower())
            if t not in {"a", "the", "and", "for", "of"}]
    phrases: list[str] = []
    for size in (3, 2):
        for i in range(len(toks) - size + 1):
            phrases.append(" ".join(toks[i:i + size]))
    return phrases


def _norm_key(title: str, company: str) -> tuple[str, str]:
    """Normalized (title, company) for cross-source dedupe."""
    def n(s) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return (n(title), n(company))


def _relevance(job: dict, role_terms: set[str],
               role_phrases: tuple[str, ...] = ()) -> float:
    """Keyword relevance of a job to the wanted role (title counts 3x).

    Multi-word role phrases in the title score a bonus above per-token
    overlap, so 'Data Scientist' outranks 'Scientist, Data Platform'.
    """
    title_toks, desc_toks = _tokens(job["title"]), _tokens(job["description"])
    overlap = role_terms & title_toks
    score = 3.0 * len(overlap)
    score += 1.0 * len(role_terms & desc_toks - overlap)
    title_low, desc_low = job["title"].lower(), job["description"].lower()
    for phrase in role_phrases:
        if phrase and phrase in title_low:
            score += 4.0
        elif phrase and phrase in desc_low:
            score += 1.5
    return score if job["title"] else 0.0


def _level_ok(title: str, level: str | None) -> bool:
    if not level:
        return True
    want = {"entry": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4,
            "staff": 5, "principal": 6}.get(level.lower())
    if want is None:
        return True
    low = title.lower()
    found = None
    for kw, rank in C.SENIORITY_KEYWORDS.items():
        if kw in low:
            found = rank if found is None else max(found, rank)
    if found is None:
        return True  # no level in title — don't exclude
    return abs(found - want) <= 1


#: Dice-style tech gate for --tech-only: title must contain one of these.
#: Advisory, not a taxonomy — a tech job whose title carries none of these
#: keywords is filtered OUT, so this flag is deliberately opt-in.
TECH_KEYWORDS = {
    "engineer", "engineering", "developer", "software", "data", "devops",
    "sre", "platform", "backend", "frontend", "fullstack", "full-stack",
    "full-stack", "mobile", "ios", "android", "qa", "test", "testing",
    "security", "cloud", "infrastructure", "architect", "scientist",
    "analyst", "analytics", "machine", "learning", "ml", "ai",
    "python", "java", "javascript", "typescript", "react", "golang",
    "rust", "kubernetes", "reliability", "systems", "embedded",
    "firmware", "database", "mlops", "research", "technical",
}


def _tech_ok(title: str) -> bool:
    """True when the title contains at least one TECH_KEYWORDS token."""
    return bool(_tokens(title) & TECH_KEYWORDS)


def _norm_stage(stage: str) -> str:
    """Canonical stage key: 'Series A' / 'series_a' / 'SeriesA' -> 'series-a'."""
    s = (stage or "").lower().replace("_", "-").replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    aliases = {"seriesa": "series-a", "seriesb": "series-b",
               "seriesc": "series-c", "pre-seed": "preseed"}
    return aliases.get(s, s)


def _stage_ok(job: dict, stage: str | None) -> bool:
    """Startup-stage filter. Only applies where the adapter supplies stage
    metadata (Wellfound / Built In adapters put it in ``extras.stage``);
    jobs without stage metadata pass through untouched."""
    if not stage:
        return True
    extras = job.get("extras") or {}
    job_stage = extras.get("stage") if isinstance(extras, dict) else None
    if not job_stage:
        return True  # no metadata — don't exclude
    return _norm_stage(str(job_stage)) == _norm_stage(stage)


def _salary_min(salary_text: str) -> float | None:
    """Annualized low end of a salary_text range, or None when unparseable."""
    from candid import salary as S
    if not (salary_text or "").strip():
        return None
    parsed = S.parse_posted_range(salary_text)
    return parsed["low"] if parsed else None


def _salary_ok(job: dict, min_salary: float | None) -> bool:
    """Min-salary filter. Only applies where salary_text parses to a number;
    jobs without parseable salary data pass through untouched."""
    if min_salary is None:
        return True
    low = _salary_min(job.get("salary_text") or "")
    if low is None:
        return True  # no salary metadata — don't exclude
    return low >= min_salary


def _location_ok(job: dict, location: str, remote: bool) -> bool:
    if remote:
        return job["remote"] or "remote" in job["location"].lower()
    if not location:
        return True
    # A named-location search must actually mention the location; remote
    # postings only qualify when the user asked for remote (or no location).
    return location.lower() in job["location"].lower()


def _parse_posted_at(raw: str) -> datetime | None:
    """Parse a posted_at value defensively. None when unparseable.

    Accepts ISO strings ('2026-09-20', '2026-09-20T10:00:00Z'),
    epoch seconds/millis, and a few common date formats.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10}(\.\d+)?", s):
        try:
            return datetime.fromtimestamp(float(s))
        except (ValueError, OSError, OverflowError):
            return None
    if re.fullmatch(r"\d{13}", s):
        try:
            return datetime.fromtimestamp(int(s) / 1000)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y",
                "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


def _fresh_enough(job: dict, days: int | None, now: datetime) -> bool:
    """Recency gate: keep jobs posted within N days, or with unparseable dates."""
    if days is None or days < 0:
        return True
    posted = _parse_posted_at(job.get("posted_at", ""))
    if posted is None:
        return True  # can't tell — don't drop it
    if posted > now:
        return True  # future-dated — don't drop it
    return (now - posted).days <= days


def filter_jobs(jobs: list[dict], role: str, location: str = "",
                remote: bool = False, level: str | None = None,
                limit: int = DEFAULT_LIMIT, days: int | None = None,
                exclude_ids: set[str] | None = None,
                stage: str | None = None, min_salary: float | None = None,
                tech_only: bool = False) -> list[dict]:
    """Filter + rank raw adapter output for the requested role.

    ``days``: keep only jobs posted within the last N days (jobs with
    unparseable/missing dates are kept). ``exclude_ids``: skip jobs whose
    ``source_id`` (or ``id``) is in the set (dashboard dismiss support).
    Cross-source dupes (same normalized title+company) are collapsed,
    keeping the highest-relevance copy.

    Board-aware filters (opt-in, silently ignored where metadata is absent):
    ``stage`` matches adapter-supplied ``extras.stage`` (Wellfound/Built In);
    jobs without stage metadata pass through. ``min_salary`` keeps jobs
    whose ``salary_text`` parses to an annualized low >= N; jobs without
    parseable salary pass through. ``tech_only`` requires a tech keyword
    in the title (always available, so always enforced when set).
    """
    role_terms = _tokens(role) - {"a", "the", "and", "for"}
    role_phrases = tuple(_role_phrases(role))
    excluded = set(exclude_ids or ())
    now = datetime.now()
    best: dict[tuple[str, str], tuple[float, dict]] = {}
    for job in jobs:
        sid = job.get("source_id") or job.get("id")
        if sid and sid in excluded:
            continue
        if not _level_ok(job["title"], level):
            continue
        if not _location_ok(job, location, remote):
            continue
        if not _fresh_enough(job, days, now):
            continue
        if not _stage_ok(job, stage):
            continue
        if not _salary_ok(job, min_salary):
            continue
        if tech_only and not _tech_ok(job["title"]):
            continue
        rel = _relevance(job, role_terms, role_phrases)
        if rel <= 0:
            continue
        key = _norm_key(job.get("title", ""), job.get("company", ""))
        if key not in best or rel > best[key][0]:
            best[key] = (rel, job)
    ranked = sorted(best.values(), key=lambda x: -x[0])
    return [j for _, j in ranked[:limit]]


def score_job(profile: dict, job: dict) -> dict:
    """Score one job against the profile. Returns {score, verdict, why, salary}."""
    from candid import match as M
    from candid import salary as S
    jd_text = f"{job['title']}\n{job['company']}\n{job['description']}"
    result = M.score_match(profile, jd_text, title=job["title"],
                           company=job["company"], location=job["location"])
    matched = result["skills_matched"][:3]
    why = f"{result['verdict']} ({result['score']}/100)"
    if matched:
        why += f" — matches your {', '.join(matched)}"
    if result["gaps"]:
        why += f"; gap: {result['gaps'][0]}"
    salary_range = S.parse_posted_range(job["description"] + " " + job["salary_text"])
    return {"score": result["score"], "verdict": result["verdict"], "why": why,
            "salary": salary_range, "breakdown": result["breakdown"]}


# ---------------------------------------------------------------------------
# persistence + tracker integration
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_run": "", "seen": {}}


def _save_state(state: dict) -> None:
    C.ensure_data_dirs()
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# freshness tracking — per-listing first_seen / last_seen in jobs.json state
# ---------------------------------------------------------------------------

STALE_AFTER_DAYS = 30


def _sighting_key(title: str, company: str) -> str:
    t, c = _norm_key(title, company)
    return f"{t}|{c}"


def _record_sightings(jobs: list[dict], state: dict, now_iso: str) -> None:
    """Stamp first_seen / last_seen for every deduped listing in this run.

    A sighting keyed on normalized (title, company) remembers its first and
    latest sighting; a new ``source_id`` for an already-seen key marks it as
    reposted (``reposted_at``). This is what powers ``jobs freshness``.
    """
    sightings = state.setdefault("sightings", {})
    for job in jobs:
        key = _sighting_key(job.get("title", ""), job.get("company", ""))
        if not key.strip("|"):
            continue
        sid = job.get("source_id") or ""
        rec = sightings.get(key)
        if rec is None:
            sightings[key] = {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "first_seen": now_iso,
                "last_seen": now_iso,
                "source_id": sid,
                "source_ids": [sid] if sid else [],
                "reposted_at": None,
                "also_seen_on": list(job.get("also_seen_on") or []),
            }
            continue
        if sid and sid not in rec.get("source_ids", []):
            rec.setdefault("source_ids", []).append(sid)
            rec["reposted_at"] = now_iso  # same norm key, new source id
        rec["last_seen"] = now_iso
        if sid:
            rec["source_id"] = sid
        for src in job.get("also_seen_on") or []:
            if src not in rec.setdefault("also_seen_on", []):
                rec["also_seen_on"].append(src)


def freshness_report(state: dict | None = None, now: datetime | None = None,
                     stale_days: int = STALE_AFTER_DAYS,
                     limit: int = 25) -> dict:
    """Classify sightings into new / reposted / stale.

    - ``new``: first seen during the latest run (first_seen >= prev_last_run;
      with no previous run, everything seen in the only run counts as new).
    - ``reposted``: same normalized (title, company) sighted under a new
      ``source_id`` (reposted_at set), most recent first.
    - ``stale``: not seen in the last ``stale_days`` days.
    """
    state = state if state is not None else _load_state()
    now = now or datetime.now()
    sightings = state.get("sightings", {})
    window_start = state.get("prev_last_run") or state.get("last_run") or ""

    def _dt(s: str) -> datetime | None:
        try:
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    new, reposted, stale = [], [], []
    for rec in sightings.values():
        first, last = _dt(rec.get("first_seen", "")), _dt(rec.get("last_seen", ""))
        rep_at = _dt(rec.get("reposted_at") or "")
        entry = {"title": rec.get("title", ""), "company": rec.get("company", ""),
                 "source_id": rec.get("source_id", ""),
                 "first_seen": rec.get("first_seen", ""),
                 "last_seen": rec.get("last_seen", ""),
                 "reposted_at": rec.get("reposted_at")}
        if window_start and rec.get("first_seen", "") >= window_start:
            new.append(entry)
        if rep_at:
            reposted.append(entry)
        if last is None or (now - last).days > stale_days:
            stale.append(entry)
    new.sort(key=lambda e: e["first_seen"])
    reposted.sort(key=lambda e: e["reposted_at"] or "", reverse=True)
    stale.sort(key=lambda e: e["last_seen"])
    return {"since": window_start, "as_of": now.isoformat(timespec="seconds"),
            "new": new[:limit], "reposted": reposted[:limit],
            "stale": stale[:limit],
            "totals": {"new": len(new), "reposted": len(reposted),
                       "stale": len(stale), "tracked": len(sightings)}}


def render_freshness(rep: dict) -> str:
    """Human-readable freshness report."""
    lines = [f"Freshness (as of {rep['as_of']})"
             + (f", new since {rep['since']}" if rep.get("since") else "")]
    lines.append(f"\nNEW since last run ({rep['totals']['new']}):")
    if rep["new"]:
        for e in rep["new"]:
            lines.append(f"  + {e['title']} @ {e['company']} "
                         f"[{e['source_id']}] (first seen {e['first_seen'][:10]})")
    else:
        lines.append("  (none)")
    lines.append(f"\nREPOSTED — same posting, new source id ({rep['totals']['reposted']}):")
    if rep["reposted"]:
        for e in rep["reposted"]:
            lines.append(f"  ~ {e['title']} @ {e['company']} "
                         f"[{e['source_id']}] (reposted {(e['reposted_at'] or '')[:10]})")
    else:
        lines.append("  (none)")
    lines.append(f"\nSTALE — not seen in 30 days ({rep['totals']['stale']}):")
    if rep["stale"]:
        for e in rep["stale"]:
            lines.append(f"  - {e['title']} @ {e['company']} "
                         f"(last seen {(e['last_seen'] or '?')[:10]})")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# saved searches — persist curation params in jobs.json, re-run on demand
# ---------------------------------------------------------------------------

def save_search(name: str, role: str, location: str = "", remote: bool = False,
                sources: list[str] | None = None, level: str | None = None,
                days: int | None = None, min_score: float = 0,
                stage: str | None = None, min_salary: float | None = None,
                tech_only: bool = False) -> dict:
    """Persist a named curation search to jobs.json. Raises JobsError on an
    empty name or unknown source."""
    name = (name or "").strip()
    if not name:
        raise JobsError("Search name is required (--name).")
    unknown = [s for s in (sources or []) if s not in ADAPTERS]
    if unknown:
        raise JobsError(f"Unknown source(s): {', '.join(unknown)}. "
                        f"Available: {', '.join(ADAPTERS)}")
    state = _load_state()
    searches = state.setdefault("saved_searches", {})
    searches[name] = {
        "role": role, "location": location, "remote": bool(remote),
        "sources": sources, "level": level, "days": days,
        "min_score": min_score or 0, "stage": stage,
        "min_salary": min_salary, "tech_only": bool(tech_only),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_state(state)
    return searches[name]


def list_searches() -> dict:
    """Return {name: params} for all saved searches."""
    return _load_state().get("saved_searches", {})


def delete_search(name: str) -> bool:
    """Remove a saved search. Returns True when it existed."""
    state = _load_state()
    searches = state.get("saved_searches", {})
    if name not in searches:
        return False
    del searches[name]
    _save_state(state)
    return True


def render_searches(searches: dict) -> str:
    if not searches:
        return ("No saved searches yet. Run:\n"
                "  python -m candid jobs search-save --name NAME --role \"Data Scientist\" "
                "--location \"New York\"")
    lines = ["Saved searches:"]
    for name, p in sorted(searches.items()):
        bits = [f"--role \"{p.get('role', '')}\""]
        if p.get("location"):
            bits.append(f"--location \"{p['location']}\"")
        if p.get("remote"):
            bits.append("--remote")
        if p.get("sources"):
            bits.append(f"--sources {','.join(p['sources'])}")
        if p.get("level"):
            bits.append(f"--level {p['level']}")
        if p.get("stage"):
            bits.append(f"--stage {p['stage']}")
        if p.get("min_salary"):
            bits.append(f"--min-salary {p['min_salary']:g}")
        if p.get("tech_only"):
            bits.append("--tech-only")
        lines.append(f"  {name}: jobs curate {' '.join(bits)}")
    return "\n".join(lines)


def run_search(name: str, profile: dict) -> dict:
    """Re-run curation with a saved search's params. Returns the curate result."""
    searches = list_searches()
    if name not in searches:
        known = ", ".join(sorted(searches)) or "(none)"
        raise JobsError(f"No saved search named '{name}'. Saved: {known}")
    p = searches[name]
    return curate(profile, role=p.get("role", ""), location=p.get("location", ""),
                  remote=p.get("remote", False), level=p.get("level"),
                  limit=DEFAULT_LIMIT, sources=p.get("sources"),
                  days=p.get("days"), min_score=p.get("min_score", 0),
                  stage=p.get("stage"), min_salary=p.get("min_salary"),
                  tech_only=p.get("tech_only", False))


def _already_tracked(company: str, role: str) -> dict | None:
    from candid import tracker as T
    for a in T.list_apps():
        if (a["company"].strip().lower() == company.strip().lower()
                and a["role"].strip().lower() == role.strip().lower()):
            return a
    return None


def _tracked_keys() -> set[tuple[str, str]]:
    """Normalized (role, company) keys of everything already in the tracker."""
    from candid import tracker as T
    return {_norm_key(a.get("role", ""), a.get("company", "")) for a in T.list_apps()}


def curate(profile: dict, role: str, location: str = "", remote: bool = False,
           level: str | None = None, limit: int = DEFAULT_LIMIT,
           sources: list[str] | None = None, days: int | None = None,
           min_score: float = 0, stage: str | None = None,
           min_salary: float | None = None, tech_only: bool = False) -> dict:
    """Run one curation pass.

    Returns {fetched, candidates, added, skipped, skipped_low_score, errors}.
    ``days`` filters to postings from the last N days (unparseable dates are
    kept). ``min_score`` gates tracker writes: jobs scoring below it are NOT
    added — they are stashed in jobs.json under ``skipped_low_score`` so a
    lower threshold can pick them up later. ``stage`` / ``min_salary`` /
    ``tech_only`` are board-aware filters (see filter_jobs): they only bite
    where adapters supply the metadata, ignored silently otherwise.

    Every run dedupes across boards (keeping the richest copy, with
    ``also_seen_on`` recorded) and stamps per-listing first_seen/last_seen
    for ``jobs freshness``.
    """
    from candid import tracker as T
    from candid import salary as S

    wanted = sources or list(ADAPTERS)
    unknown = [s for s in wanted if s not in ADAPTERS]
    if unknown:
        raise JobsError(f"Unknown source(s): {', '.join(unknown)}. Available: {', '.join(ADAPTERS)}")

    raw: list[dict] = []
    errors: list[str] = []
    for name in wanted:
        try:
            raw.extend(ADAPTERS[name]())  # type: ignore[operator]
        except JobsError as e:
            errors.append(str(e))

    # cross-board dedupe before filtering: one (richest) copy per
    # normalized title+company, merged source names in also_seen_on
    raw = dedupe_cross_board(raw)

    state = _load_state()
    now_iso = datetime.now().isoformat(timespec="seconds")
    _record_sightings(raw, state, now_iso)

    candidates = filter_jobs(raw, role, location, remote, level, limit,
                             days=days, stage=stage, min_salary=min_salary,
                             tech_only=tech_only)
    seen: dict = state.get("seen", {})
    tracked = _tracked_keys()

    added, skipped, low_score = [], [], []
    for job in candidates:
        if job["source_id"] in seen or _already_tracked(job["company"], job["title"]):
            skipped.append(job)
            continue
        if _norm_key(job["title"], job["company"]) in tracked:
            skipped.append(job)  # near-dupe of something already tracked
            continue
        scored = score_job(profile, job)
        if scored["score"] < min_score:
            low_score.append({
                "source_id": job["source_id"], "title": job["title"],
                "company": job["company"], "location": job["location"],
                "url": job["url"], "score": scored["score"],
                "skipped_at": datetime.now().isoformat(timespec="seconds"),
            })
            continue
        notes = f"[curated {datetime.now().date().isoformat()}] match {scored['score']}/100 — {scored['why']}"
        if scored["salary"]:
            notes += f" | posted pay ${scored['salary']['low']:,.0f}–${scored['salary']['high']:,.0f}/yr"
            try:
                S.ingest_posted_range(job["company"], job["title"],
                                      job["description"] + " " + job["salary_text"],
                                      location=job["location"],
                                      source_detail=job["url"] or job["source"])
            except Exception:
                pass
        rec = T.add(job["company"] or "(unknown company)", job["title"],
                    jd_link=job["url"], status="saved", notes=notes)
        if rec.get("duplicate"):
            # lost the race with a concurrent add — treat as skipped
            skipped.append(job)
            continue
        # attach curation metadata for the downstream flow
        T.update(rec["id"], notes=notes)
        rec.update({"source": job["source"], "source_url": job["url"],
                    "match_score": scored["score"], "jd_text": job["description"][:4000]})
        _stash_job_meta(rec["id"], rec)
        seen[job["source_id"]] = rec["id"]
        tracked.add(_norm_key(job["title"], job["company"]))
        added.append({**job, **scored, "app_id": rec["id"]})

    if low_score:
        stash = state.setdefault("skipped_low_score", [])
        known = {e.get("source_id") for e in stash}
        stash.extend(e for e in low_score if e["source_id"] not in known)
        state["skipped_low_score"] = stash[-500:]  # bounded

    state["prev_last_run"] = state.get("last_run", "")
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    state["seen"] = seen
    _save_state(state)
    return {"fetched": len(raw), "candidates": len(candidates),
            "added": added, "skipped": len(skipped),
            "skipped_low_score": len(low_score), "errors": errors}


def _stash_job_meta(app_id: int, meta: dict) -> None:
    """Keep curation metadata (url, score, jd text) alongside the tracker record.

    Stored in candid_data/job_meta.json keyed by tracker id — the tracker
    JSON stays human-editable while the verbose payload lives here.
    """
    from candid import tracker as T
    path = C.DATA_DIR / "job_meta.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[str(app_id)] = {k: meta.get(k) for k in
                         ("source", "source_url", "match_score", "jd_text")}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_job_meta(app_id: int) -> dict:
    path = C.DATA_DIR / "job_meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(str(app_id), {})
    except json.JSONDecodeError:
        return {}


def refresh(profile: dict, role: str, location: str = "", remote: bool = False,
            level: str | None = None, limit: int = DEFAULT_LIMIT,
            sources: list[str] | None = None, days: int | None = None,
            min_score: float = 0, stage: str | None = None,
            min_salary: float | None = None, tech_only: bool = False) -> dict:
    """Re-run curation; the result's ``added`` holds only genuinely new jobs."""
    return curate(profile, role, location, remote, level, limit, sources=sources,
                  days=days, min_score=min_score, stage=stage,
                  min_salary=min_salary, tech_only=tech_only)


def render_curated(result: dict) -> str:
    lines = [
        f"Fetched {result['fetched']} postings → {result['candidates']} relevant candidates."
    ]
    if result["errors"]:
        lines += ["Source errors:"] + [f"  ⚠️ {e}" for e in result["errors"]]
    if result["added"]:
        lines.append(f"\n✅ {len(result['added'])} new → tracker (status: saved):")
        for j in result["added"]:
            line = (f"  [#{j['app_id']}] {j['title']} @ {j['company']} "
                    f"({j['location']}) — {j['score']}/100 [{j['source']}]")
            if j.get("also_seen_on"):
                line += f" (also seen on {', '.join(j['also_seen_on'])})"
            lines.append(line)
            if j["url"]:
                lines.append(f"      apply: {j['url']}")
    else:
        lines.append("\nNo new jobs since last run.")
    if result.get("skipped_low_score"):
        lines.append(f"({result['skipped_low_score']} below the match-score gate — "
                     "stashed, not added)")
    if result["skipped"]:
        lines.append(f"({result['skipped']} already tracked — skipped)")
    lines.append("\nNext: tailor → python -m candid tailor resume --app-id <id> --company X --role Y")
    return "\n".join(lines)


def render_saved() -> str:
    """Show the curated pipeline: saved jobs with scores and apply links."""
    from candid import tracker as T
    apps = T.list_apps(status="saved")
    if not apps:
        return ("No saved jobs yet. Run:\n"
                "  python -m candid jobs curate --role \"Data Scientist\" --location \"New York\"")
    lines = [f"{'ID':<4}{'Score':<7}{'Title':<34}{'Company':<22}Apply URL"]
    for a in apps:
        meta = get_job_meta(a["id"])
        score = meta.get("match_score", "—")
        url = meta.get("source_url") or a.get("jd_link") or ""
        lines.append(f"{a['id']:<4}{str(score):<7}{a['role'][:33]:<34}"
                     f"{a['company'][:21]:<22}{url[:60]}")
    return "\n".join(lines)
