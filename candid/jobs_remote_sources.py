"""Remote-first job board adapters: We Work Remotely, Himalayas, Jobspresso, Remotive.

Each adapter returns normalized job dicts with the same shape jobs.py uses:
{source, source_id, title, company, location, url, description, salary_text,
 remote (bool), posted_at} — and every job here has ``remote=True`` since all
four boards are remote-only.

Feeds only: public RSS or public JSON endpoints that need no key, no login,
and no HTML page scraping. Descriptions embedded in the feeds are stripped of
HTML tags before returning.

Usage:
    from candid.jobs_remote_sources import REMOTE_ADAPTERS
    jobs = REMOTE_ADAPTERS["remotive"]()

``MAX_PER_SOURCE`` caps each adapter's output (same constant jobs.py uses).
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# jobs.py never imports this module, so importing it here is not circular.
from candid.jobs import FETCH_TIMEOUT, JobsError, MAX_PER_SOURCE, USER_AGENT


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, source: str) -> bytes:
    """GET a feed URL with our User-Agent; wrap any failure in JobsError."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return resp.read()
    except Exception as exc:
        raise JobsError(f"{source} unreachable: {exc}") from exc


def _get_json(url: str, source: str) -> object:
    data = _fetch(url, source)
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise JobsError(f"{source} returned invalid JSON: {exc}") from exc


def _get_rss(url: str, source: str) -> ET.Element:
    data = _fetch(url, source)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise JobsError(f"{source} returned malformed XML: {exc}") from exc


def _strip_html(raw: object) -> str:
    """Drop HTML tags/entities from feed-embedded descriptions.

    Tags are stripped *before* unescaping so that unescaped text like
    ``&lt;3`` can never be mistaken for a tag and eaten.
    """
    text = re.sub(r"<[^>]+>", " ", str(raw or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_html_lines(raw: object) -> str:
    """HTML -> plain text that keeps block boundaries as newlines.

    Used when labeled fields (``Company:``, ``Location:``) must be found
    on their own lines, which a full whitespace collapse would destroy.
    """
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h[1-6][^>]*>", "\n",
                  str(raw or ""), flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _iter_feed_items(root: ET.Element):
    """Yield <item> (RSS) or <entry> (Atom) elements from a feed document."""
    for child in root.iter():
        name = _localname(child.tag)
        if name in ("item", "entry"):
            yield child


def _child_text(item: ET.Element, *names: str) -> str:
    """Text of the first child whose local tag name matches, else ''."""
    for child in item:
        if _localname(child.tag) in names and child.text:
            return child.text
    return ""


def _slug_from_url(url: str) -> str:
    return _clean(url).rstrip("/").rsplit("/", 1)[-1]


def _job(source: str, source_id: str, title: str, company: str,
         location: str, url: str, description: str, salary_text: str,
         posted_at: str) -> dict:
    return {
        "source": source,
        "source_id": f"{source}:{source_id}",
        "title": _clean(title),
        "company": _clean(company),
        "location": _clean(location) or "Remote",
        "url": _clean(url),
        "description": _clean(description)[:4000],
        "salary_text": _clean(salary_text)[:200],
        "remote": True,
        "posted_at": _clean(posted_at),
    }


def _labeled_field(text: str, label: str) -> str:
    """Pull a 'Label: value' line out of plain text (Jobspresso-style)."""
    m = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# 1. We Work Remotely — public RSS per category, remote-only board.
#    Item titles are "Company: Job Title"; location is not always a separate
#    element, so it defaults to "Remote".
# ---------------------------------------------------------------------------

_WWR_CATEGORIES = [
    "remote-programming-jobs",
    "remote-devops-sysadmin-jobs",
    "remote-design-jobs",
]


def fetch_weworkremotely() -> list[dict]:
    """We Work Remotely public RSS feeds (programming, devops, design).

    One category failing (renamed slug, bad day) does not kill the others;
    only when every category fails does the adapter raise.
    """
    source = "weworkremotely"
    out: list[dict] = []
    errors: list[str] = []
    seen_ids: set[str] = set()  # a posting can sit in two categories
    for cat in _WWR_CATEGORIES:
        url = f"https://weworkremotely.com/categories/{cat}.rss"
        try:
            root = _get_rss(url, source)
        except JobsError as exc:
            errors.append(str(exc))
            continue
        for item in _iter_feed_items(root):
            if len(out) >= MAX_PER_SOURCE:
                break
            link = _child_text(item, "link")
            guid = _child_text(item, "guid")
            if not link:
                continue
            raw_title = _child_text(item, "title")
            # "Lemon.io: Senior .NET Full-stack Developer" -> company, title
            company, _, title = raw_title.partition(":")
            if not title.strip():
                company, title = "", raw_title
            location = _child_text(item, "region", "location") or "Remote"
            slug = _slug_from_url(guid or link)
            sid = slug or guid or link
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            out.append(_job(
                source, sid,
                title, company, location, link,
                _strip_html(_child_text(item, "description")),
                "", _child_text(item, "pubDate", "published", "updated"),
            ))
    if not out and errors:
        raise JobsError("; ".join(errors))
    return out[:MAX_PER_SOURCE]


# ---------------------------------------------------------------------------
# 2. Himalayas — documented public JSON API first, RSS fallback.
#    The API has served 404s historically, so the fallback matters.
# ---------------------------------------------------------------------------

_HIMALAYAS_API = "https://himalayas.app/api/jobs"
_HIMALAYAS_RSS = "https://himalayas.app/rss"


def _pick(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return ""


def _adapt_himalayas_json(payload: object) -> list[dict] | None:
    """Return jobs from the JSON payload, or None if the shape is unknown."""
    if isinstance(payload, dict):
        if "jobs" not in payload and "data" not in payload:
            return None  # unrecognized shape — let the caller try RSS
        items = payload.get("jobs", payload.get("data", []))
    elif isinstance(payload, list):
        items = payload
    else:
        return None
    if not isinstance(items, list):
        return None
    out = []
    for j in items:
        if not isinstance(j, dict):
            continue
        title = _pick(j, "title", "jobTitle", "name")
        url = _pick(j, "applicationLink", "url", "link", "jobUrl")
        if not title or not url:
            continue
        salary = _pick(j, "salary", "salaryRange", "compensation")
        if not salary:
            lo = _pick(j, "minSalary", "salaryMin")
            hi = _pick(j, "maxSalary", "salaryMax")
            if lo or hi:
                salary = f"{lo or '?'} - {hi or '?'}"
        out.append(_job(
            "himalayas",
            _pick(j, "id", "guid", "slug") or _slug_from_url(url),
            title,
            _pick(j, "companyName", "company_name", "company"),
            _pick(j, "locationRestrictions", "location",
                  "candidateRequiredLocation") or "Remote",
            url,
            _strip_html(_pick(j, "description", "jobDescription", "excerpt")),
            salary,
            _pick(j, "pubDate", "publicationDate", "publishedAt",
                  "createdAt", "date"),
        ))
        if len(out) >= MAX_PER_SOURCE:
            break
    return out


def fetch_himalayas() -> list[dict]:
    """Himalayas public jobs API, falling back to their RSS feed."""
    try:
        payload = _get_json(_HIMALAYAS_API, "himalayas")
        jobs = _adapt_himalayas_json(payload)
    except JobsError:
        jobs = None
    if jobs is not None:
        return jobs

    # JSON API missing/changed shape — try the public RSS feed.
    root = _get_rss(_HIMALAYAS_RSS, "himalayas")
    out = []
    for item in _iter_feed_items(root):
        link = _child_text(item, "link", "id")
        raw_title = _child_text(item, "title")
        if not raw_title or not link:
            continue
        company, _, title = raw_title.partition(":")
        if not title.strip():
            company, title = "", raw_title
        desc = _strip_html(_child_text(item, "description", "summary",
                                       "content"))
        out.append(_job(
            "himalayas", _slug_from_url(link) or link, title, company,
            "Remote", link, desc, "",
            _child_text(item, "pubDate", "published", "updated"),
        ))
        if len(out) >= MAX_PER_SOURCE:
            break
    return out[:MAX_PER_SOURCE]


# ---------------------------------------------------------------------------
# 3. Jobspresso — public WordPress RSS feed, remote-only board.
# ---------------------------------------------------------------------------

_JOBSPRESSO_FEED = "https://jobspresso.co/feed/"


def fetch_jobspresso() -> list[dict]:
    """Jobspresso public RSS feed (remote-only board)."""
    source = "jobspresso"
    root = _get_rss(_JOBSPRESSO_FEED, source)
    out = []
    for item in _iter_feed_items(root):
        link = _child_text(item, "link")
        raw_title = _child_text(item, "title")
        if not raw_title or not link:
            continue
        raw_desc = _child_text(item, "description")
        # Keep block boundaries so labeled Company:/Location: lines survive.
        plain = _strip_html_lines(raw_desc)
        # Title may be "Role" or "Role at Company"; description may also
        # carry labeled Company:/Location: lines (WP job posts).
        title, company = raw_title, ""
        if " at " in raw_title:
            title, _, company = raw_title.rpartition(" at ")
        company = _labeled_field(plain, "Company") or company
        location = _labeled_field(plain, "Location") or "Remote"
        out.append(_job(
            source, _slug_from_url(link) or link, title, company,
            location, link, plain, "",
            _child_text(item, "pubDate", "published", "updated"),
        ))
        if len(out) >= MAX_PER_SOURCE:
            break
    return out[:MAX_PER_SOURCE]


# ---------------------------------------------------------------------------
# 4. Remotive — free public JSON API, no key. Remote-only board.
#    Courtesy: their docs ask for at most a few requests per day and to
#    attribute listings to Remotive (the API url is the canonical link).
# ---------------------------------------------------------------------------

_REMOTIVE_API = "https://remotive.com/api/remote-jobs"


def fetch_remotive() -> list[dict]:
    """Remotive public API (https://remotive.com/api/remote-jobs)."""
    source = "remotive"
    payload = _get_json(_REMOTIVE_API, source)
    if isinstance(payload, dict):
        items = payload.get("jobs", [])
    elif isinstance(payload, list):
        items = payload
    else:
        raise JobsError("remotive returned an unexpected JSON shape")
    if not isinstance(items, list):
        raise JobsError("remotive returned an unexpected JSON shape")
    out = []
    for j in items:
        if not isinstance(j, dict):
            continue
        job_id = j.get("id")
        title = _clean(j.get("title"))
        url = _clean(j.get("url"))
        if not job_id or not title or not url:
            continue
        loc = _clean(j.get("candidate_required_location")) or "Remote"
        out.append(_job(
            source, str(job_id), title,
            _clean(j.get("company_name")),
            loc, url,
            _strip_html(j.get("description")),
            _clean(j.get("salary")),
            _clean(j.get("publication_date")),
        ))
        if len(out) >= MAX_PER_SOURCE:
            break
    return out[:MAX_PER_SOURCE]


REMOTE_ADAPTERS = {
    "weworkremotely": fetch_weworkremotely,
    "himalayas": fetch_himalayas,
    "jobspresso": fetch_jobspresso,
    "remotive": fetch_remotive,
}
