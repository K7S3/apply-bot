"""University career-board RSS registry + research-career feed adapters.

Two features in one module:

1. A generic RSS/Atom fetcher (stdlib ``xml.etree`` only - no feedparser,
   no extra deps) plus a user-managed registry of university career-board
   feeds stored at ``DATA_DIR/academic_feeds.json``. Commands::

       python -m candid feeds add "MIT Careers" https://example.edu/jobs.rss
       python -m candid feeds list
       python -m candid feeds remove "MIT Careers"

2. Built-in adapters for public research-career boards - currently Nature
   Careers (Science Careers and jobs.ac.uk were evaluated at build time
   and dropped: no working public job RSS found - see
   docs/batch19/feeds.md). The adapter is an *opt-in* source for
   ``jobs curate``::

       python -m candid jobs curate --role "Postdoc" --sources naturecareers

   The ``academic`` source fetches every feed in the user's registry.

Everything is public, no-login, no-key RSS. Boards that hide their listings
behind logins or JavaScript (most Symplicity/Workday university portals) are
deliberately out of scope - see docs/batch19/feeds.md for honest coverage
notes. Fetched listings are treated as *data* - never executed as code.

This module is import-safe: it only touches argparse, stdlib, and
``candid.config``. The CLI wiring lives in ``add_parsers()``; the
coordinator wires it into ``__main__.py``. ``candid/jobs.py`` registers the
adapters below as opt-in sources (``EXTRA_ADAPTERS``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape as _unescape

from candid import config as C

USER_AGENT = "candid/0.2 (personal job curation; contact: user-local)"
FETCH_TIMEOUT = 20
MAX_PER_FEED = 100
REGISTRY_FILENAME = "academic_feeds.json"


class FeedsError(Exception):
    """Raised for feed fetch/parse failures and registry errors."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_get(url: str) -> bytes:
    """GET a URL with a polite User-Agent. Raises FeedsError on failure."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": ("application/rss+xml, application/atom+xml, "
                       "application/xml, text/xml, */*;q=0.8"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise FeedsError(f"HTTP {status} fetching {url}")
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise FeedsError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise FeedsError(f"unreachable {url}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise FeedsError(f"network error fetching {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# RSS / Atom parsing (stdlib xml.etree only)
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _inner_text(elem: ET.Element) -> str:
    return "".join(elem.itertext()).strip()


def _child_text(elem: ET.Element, names: set[str]) -> str:
    """First non-empty text among children whose local tag name matches."""
    for child in elem:
        if _local(child.tag) in names:
            text = _inner_text(child)
            if text:
                return text
    return ""


def _link_url(item: ET.Element, is_atom: bool) -> str:
    if not is_atom:
        return _child_text(item, {"link"})
    # Atom: <link href="..." rel="alternate"/> - prefer alternate/self links
    best = ""
    for child in item:
        if _local(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if not href:
            continue
        rel = child.attrib.get("rel", "alternate")
        if rel == "alternate":
            return href
        best = best or href
    return best


def _entry_from_element(item: ET.Element, is_atom: bool) -> dict:
    desc = _child_text(item, {"encoded"})  # content:encoded (namespaced)
    if not desc:
        desc = _child_text(item, {"description", "summary", "content"})
    return {
        "title": _child_text(item, {"title"}),
        "url": _link_url(item, is_atom),
        "guid": _child_text(item, {"guid", "id"}),
        "description": desc,
        "posted_at": _child_text(item, {"pubDate", "published", "updated",
                                        "date"}),
        "author": _child_text(item, {"author", "creator", "publisher"}),
        "location": _child_text(item, {"location", "coverage"}),
    }


def parse_feed(xml_bytes: bytes) -> dict:
    """Parse RSS 2.0 / Atom / RSS 1.0 bytes.

    Returns {"title", "link", "entries": [entry dicts]}.
    Raises FeedsError when the bytes are not a recognizable feed.
    An empty-but-valid feed returns zero entries (callers decide whether
    that is an error - adapters treat it as one, the registry verifier
    reports it).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise FeedsError(f"not parseable XML: {exc}") from exc

    kind = _local(root.tag).lower()
    entries: list[dict] = []
    title = link = ""
    if kind == "rss":
        channel = next((c for c in root if _local(c.tag) == "channel"), None)
        if channel is None:
            raise FeedsError("RSS feed has no <channel>")
        title = _child_text(channel, {"title"})
        link = _child_text(channel, {"link"})
        items = [c for c in channel if _local(c.tag) == "item"]
        entries = [_entry_from_element(i, False) for i in items]
    elif kind == "feed":  # Atom
        title = _child_text(root, {"title"})
        link = _link_url(root, True)
        entries = [_entry_from_element(c, True)
                   for c in root if _local(c.tag) == "entry"]
    elif kind == "rdf":  # RSS 1.0
        channel = next((c for c in root if _local(c.tag) == "channel"), None)
        if channel is not None:
            title = _child_text(channel, {"title"})
            link = _child_text(channel, {"link"})
        entries = [_entry_from_element(c, False)
                   for c in root if _local(c.tag) == "item"]
    else:
        raise FeedsError(f"unrecognized feed format (root <{kind}>) - "
                         "expected RSS or Atom")
    return {"title": title, "link": link, "entries": entries}


def fetch_entries(url: str, max_entries: int = MAX_PER_FEED) -> list[dict]:
    """Fetch a feed URL and return its parsed entries (newest first).

    Raises FeedsError on network failure, unparseable XML, or a feed with
    zero usable entries.
    """
    xml_bytes = _http_get(url)
    if len(xml_bytes) > 5_000_000:
        raise FeedsError(f"feed too large ({len(xml_bytes)} bytes): {url}")
    feed = parse_feed(xml_bytes)
    entries = [e for e in feed["entries"] if e["title"] or e["url"]]
    if not entries:
        name = feed["title"] or url
        raise FeedsError(f"feed has no usable entries: {name}")
    return entries[:max_entries]


def verify_feed(url: str) -> dict:
    """Probe a feed without raising: returns {ok, entries, title, message}."""
    try:
        xml_bytes = _http_get(url)
    except FeedsError as exc:
        return {"ok": False, "entries": 0, "title": "", "message": str(exc)}
    try:
        feed = parse_feed(xml_bytes)
    except FeedsError as exc:
        return {"ok": False, "entries": 0, "title": "",
                "message": f"parse failed: {exc}"}
    usable = [e for e in feed["entries"] if e["title"] or e["url"]]
    if not usable:
        return {"ok": False, "entries": 0, "title": feed["title"],
                "message": "valid feed but zero entries"}
    return {"ok": True, "entries": len(usable), "title": feed["title"],
            "message": f"{len(usable)} entries"}


# ---------------------------------------------------------------------------
# normalization to the jobs.py job-dict schema
# ---------------------------------------------------------------------------

_STRIP_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_LOCATION_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
_SALARY_RES = [
    re.compile(r"\$\s?[\d,]+(?:\.\d+)?\s?[kK]?\s*(?:[-–—]|to)\s*\$?\s?[\d,]+(?:\.\d+)?\s?[kK]?"),
    re.compile(r"£\s?[\d,]+(?:\s*(?:[-–—]|to)\s*£?\s?[\d,]+)?"),
    re.compile(r"€\s?[\d,]+(?:\s*(?:[-–—]|to)\s*€?\s?[\d,]+)?"),
]
_REMOTE_RE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b", re.I)


def _strip_html(raw: str) -> str:
    text = _STRIP_TAGS.sub(" ", raw or "")
    return _WS.sub(" ", _unescape(text)).strip()


def _normalize_posted_at(raw: str) -> str:
    """Best-effort normalize a feed date to YYYY-MM-DD; raw when unparseable."""
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
        return dt.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _split_location(title: str) -> tuple[str, str]:
    """Pull a trailing location like 'Postdoc (Cambridge, UK)' off a title.

    Only when the parenthetical contains a comma - 'Researcher (AI)' stays
    in the title. Returns (clean_title, location).
    """
    m = _LOCATION_PAREN.search(title or "")
    if m and "," in m.group(1):
        return title[:m.start()].strip(), m.group(1).strip()
    return (title or "").strip(), ""


def _extract_salary(text: str) -> str:
    for rx in _SALARY_RES:
        m = rx.search(text or "")
        if m:
            return m.group(0).strip()
    return ""


_DESC_EMPLOYER_RE = re.compile(r"^(?P<co>.+?)\s*\((?P<loc>[^()]*)\)\s*$")


def normalize_job(source: str, source_label: str, entry: dict,
                  employer_sep: str | None = None,
                  desc_employer: bool = False) -> dict:
    """Normalize one parsed feed entry to the jobs.py job-dict schema.

    ``employer_sep``: some boards (Madgex-powered: Nature Careers, Inside
    Higher Ed, THE UniJobs) prefix titles as ``"Employer: Title"`` - split
    on the separator to recover company and title separately.
    ``desc_employer``: HigherEdJobs puts ``"Employer (City, ST)"`` in the
    description - parse company/location out of it.
    """
    title = (entry.get("title") or "").strip()
    company = (entry.get("author") or "").strip()
    location = (entry.get("location") or "").strip()
    description = _strip_html(entry.get("description") or "")
    if employer_sep and employer_sep in title:
        left, right = title.split(employer_sep, 1)
        if left.strip() and right.strip():
            company, title = left.strip(), right.strip()
    if desc_employer and not location:
        m = _DESC_EMPLOYER_RE.match(description)
        if m and m.group("co").strip():
            company = m.group("co").strip()
            location = m.group("loc").strip()
            description = ""
    title, loc = _split_location(title)
    location = location or loc
    url = (entry.get("url") or "").strip()
    guid = (entry.get("guid") or url).strip()
    source_id = f"{source}:{hashlib.sha1(guid.encode('utf-8')).hexdigest()[:12]}"
    company = company or source_label
    remote = bool(_REMOTE_RE.search(f"{title} {location} {description[:500]}"))
    return {
        "source": source,
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": description[:4000],
        "salary_text": _extract_salary(f"{title} {description[:1500]}"),
        "remote": remote,
        "posted_at": _normalize_posted_at(entry.get("posted_at") or ""),
    }


# ---------------------------------------------------------------------------
# research-career adapters (opt-in sources for `jobs curate`)
# ---------------------------------------------------------------------------

# Verified public RSS endpoints (each fetched and parsed at build time;
# see docs/batch19/feeds.md). Key = `jobs curate --sources` name.
#
# Only Nature Careers survived verification: Science Careers has no public
# job RSS (science.org blocks bots; the one working Atypon feed is the
# Science journal table of contents, not jobs), and jobs.ac.uk's
# /search/rss/ returns HTTP 500 with no feed advertised on the site.
RESEARCH_SOURCES: dict[str, tuple[str, str]] = {
    "naturecareers": (
        "Nature Careers",
        "https://www.nature.com/naturecareers/jobsrss/",
    ),
}

# Per-source normalization options (see normalize_job).
_RESEARCH_OPTIONS: dict[str, dict] = {
    "naturecareers": {"employer_sep": ": "},
}


def adapt_research_feed(key: str) -> list[dict]:
    """Fetch one research-career feed and normalize to job dicts.

    Raises FeedsError on failure (``candid.jobs`` converts to JobsError).
    """
    if key not in RESEARCH_SOURCES:
        raise FeedsError(f"unknown research source: {key}")
    label, url = RESEARCH_SOURCES[key]
    opts = _RESEARCH_OPTIONS.get(key, {})
    try:
        entries = fetch_entries(url)
    except FeedsError as exc:
        raise FeedsError(f"{label}: {exc}") from exc
    return [normalize_job(key, label, e, **opts) for e in entries]


# ---------------------------------------------------------------------------
# user-managed registry: DATA_DIR/academic_feeds.json
# ---------------------------------------------------------------------------

# Seeds verified at build time with real HTTP fetches (each returned a
# parseable feed with real job entries). Anything that 404'd, needed
# JS/login, or came back empty was dropped - see docs/batch19/feeds.md for
# the dropped list and honest coverage notes.
#
# Per-feed normalization options are understood by fetch_registry:
#   employer_sep - split "Employer: Title" titles (Madgex boards)
#   desc_employer - parse "Employer (City, ST)" out of the description
DEFAULT_FEEDS: list[dict] = [
    {"name": "Nature Careers",
     "url": "https://www.nature.com/naturecareers/jobsrss/",
     "verified": True, "employer_sep": ": "},
    {"name": "Inside Higher Ed Careers",
     "url": "https://careers.insidehighered.com/jobsrss/",
     "verified": True, "employer_sep": ": "},
    {"name": "THE UniJobs",
     "url": "https://www.timeshighereducation.com/unijobs/jobsrss/",
     "verified": True, "employer_sep": ": "},
    {"name": "HigherEdJobs - Science Faculty",
     "url": "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=108",
     "verified": True, "desc_employer": True},
    {"name": "HigherEdJobs - Engineering Faculty",
     "url": "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=120",
     "verified": True, "desc_employer": True},
]


def _registry_path():
    return C.DATA_DIR / REGISTRY_FILENAME


def _load_registry() -> dict:
    p = _registry_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("feeds", [])
                data.setdefault("removed", [])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"feeds": [], "removed": []}


def _save_registry(data: dict) -> None:
    C.ensure_data_dirs()
    _registry_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _removed_match(rec: dict, removed: list) -> bool:
    for r in removed:
        if not isinstance(r, dict):
            continue
        if (r.get("url") or "").lower() == (rec.get("url") or "").lower():
            return True
        if (r.get("name") or "").lower() == (rec.get("name") or "").lower():
            return True
    return False


def registry_list() -> list[dict]:
    """All registry feeds: verified seeds (minus user-removed) + user adds."""
    data = _load_registry()
    removed = data.get("removed", [])
    out = []
    for seed in DEFAULT_FEEDS:
        if not _removed_match(seed, removed):
            out.append({**seed, "seed": True})
    for rec in data.get("feeds", []):
        out.append({**rec, "seed": False})
    return out


def registry_add(name: str, url: str, verify: bool = True) -> dict:
    """Add a feed. Verifies with a live fetch unless verify=False.

    Raises FeedsError on bad URL, duplicate, or failed verification.
    """
    name = (name or "").strip()
    url = (url or "").strip()
    if not name:
        raise FeedsError("feed name is required")
    if not re.match(r"^https?://", url, re.I):
        raise FeedsError(f"not an http(s) URL: {url}")
    existing = {_u.lower() for _u in
                [r.get("url", "") for r in registry_list()]}
    if url.lower() in existing:
        raise FeedsError(f"feed already registered: {url}")
    rec: dict = {"name": name, "url": url,
                 "added_at": datetime.now().isoformat(timespec="seconds"),
                 "verified": False, "entries_checked": 0, "feed_title": ""}
    if verify:
        probe = verify_feed(url)
        if not probe["ok"]:
            raise FeedsError(f"verification failed for {url}: {probe['message']}")
        rec.update({"verified": True, "entries_checked": probe["entries"],
                    "feed_title": probe["title"]})
    data = _load_registry()
    # re-adding a removed seed un-removes it
    data["removed"] = [r for r in data.get("removed", [])
                       if not _removed_match({"name": name, "url": url}, [r])]
    data["feeds"].append(rec)
    _save_registry(data)
    return rec


def registry_remove(name_or_url: str) -> dict:
    """Remove a feed by name or URL. Seeds are recorded as removed.

    Raises FeedsError when nothing matches.
    """
    key = (name_or_url or "").strip().lower()
    if not key:
        raise FeedsError("name or URL is required")
    data = _load_registry()
    for i, rec in enumerate(data.get("feeds", [])):
        if rec.get("name", "").lower() == key or rec.get("url", "").lower() == key:
            gone = data["feeds"].pop(i)
            _save_registry(data)
            return gone
    for seed in DEFAULT_FEEDS:
        if seed.get("name", "").lower() == key or seed.get("url", "").lower() == key:
            data["removed"].append({"name": seed["name"], "url": seed["url"]})
            _save_registry(data)
            return {**seed, "seed": True}
    raise FeedsError(f"no registered feed matches: {name_or_url}")


def fetch_registry() -> tuple[list[dict], list[str]]:
    """Fetch every registry feed; returns (jobs, errors).

    Errors are also echoed to stderr so a failing feed is visible without
    losing the jobs that did fetch.
    """
    jobs: list[dict] = []
    errors: list[str] = []
    for rec in registry_list():
        url = rec.get("url", "")
        label = rec.get("name") or url
        opts = {"employer_sep": rec.get("employer_sep"),
                "desc_employer": bool(rec.get("desc_employer"))}
        try:
            entries = fetch_entries(url)
        except FeedsError as exc:
            msg = f"{label}: {exc}"
            errors.append(msg)
            print(f"⚠️  feed error: {msg}", file=sys.stderr)
            continue
        jobs.extend(normalize_job("academic", label, e, **opts)
                    for e in entries)
    return jobs, errors


def adapt_academic_registry() -> list[dict]:
    """The ``academic`` opt-in source: all registry feeds normalized.

    Raises FeedsError when the registry is empty or every feed failed.
    """
    if not registry_list():
        raise FeedsError("no feeds registered - add one with "
                         "`python -m candid feeds add <name> <url>`")
    jobs, errors = fetch_registry()
    if not jobs:
        raise FeedsError("all feeds failed: " + "; ".join(errors))
    return jobs


# ---------------------------------------------------------------------------
# CLI: `candid feeds add|list|remove` (wired into __main__.py by coordinator)
# ---------------------------------------------------------------------------

def cmd_feeds_add(args: argparse.Namespace) -> int:
    try:
        rec = registry_add(args.name, args.url,
                           verify=not getattr(args, "no_verify", False))
    except FeedsError as exc:
        print(f"❌ {exc}")
        return 1
    print(f"✅ Added '{rec['name']}' → {rec['url']}")
    if rec.get("verified"):
        title = rec.get("feed_title") or "(untitled feed)"
        print(f"   verified live: {rec['entries_checked']} entries "
              f"('{title}')")
    else:
        print("   (added without verification - run `feeds list` to check)")
    return 0


def cmd_feeds_list(args: argparse.Namespace) -> int:
    feeds = registry_list()
    if getattr(args, "json", False):
        print(json.dumps(feeds, indent=2))
        return 0
    if not feeds:
        print("No feeds registered. Add one:\n"
              "  python -m candid feeds add \"MIT Careers\" https://example.edu/jobs.rss")
        return 0
    print(f"{'Name':<28}{'Verified':<10}{'URL'}")
    for rec in feeds:
        tag = "seed" if rec.get("seed") else "user"
        ver = "✅" if rec.get("verified") else "—"
        print(f"{rec.get('name', '')[:27]:<28}{ver:<10}{rec.get('url', '')}  [{tag}]")
    return 0


def cmd_feeds_remove(args: argparse.Namespace) -> int:
    try:
        gone = registry_remove(args.name_or_url)
    except FeedsError as exc:
        print(f"❌ {exc}")
        return 1
    print(f"✅ Removed '{gone.get('name')}' ({gone.get('url')})")
    return 0


def cmd_feeds(args: argparse.Namespace) -> int:
    if args.what == "add":
        return cmd_feeds_add(args)
    if args.what == "list":
        return cmd_feeds_list(args)
    if args.what == "remove":
        return cmd_feeds_remove(args)
    print(f"unknown feeds subcommand: {args.what}")
    return 1


def add_parsers(subparsers) -> None:
    """Register the ``feeds`` command tree. Import-safe: argparse only."""
    p = subparsers.add_parser(
        "feeds",
        help="Manage university/research RSS job feeds.",
        description=("Curate university career-board and research-career RSS "
                     "feeds. `feeds list` shows the registry; the registry "
                     "feeds become the opt-in `academic` source for "
                     "`jobs curate`. The built-in Nature Careers source is "
                     "always available via `jobs curate --sources`."),
    )
    sub = p.add_subparsers(dest="what", required=True)

    pa = sub.add_parser("add", help="Add a feed to the registry.")
    pa.add_argument("name", help="Display name, e.g. \"MIT Careers\"")
    pa.add_argument("url", help="Public RSS/Atom feed URL")
    pa.add_argument("--no-verify", action="store_true",
                    help="Skip the live verification fetch (not recommended)")

    pl = sub.add_parser("list", help="List registry feeds.")
    pl.add_argument("--json", action="store_true",
                    help="Machine-readable output")

    pr = sub.add_parser("remove", help="Remove a feed by name or URL.")
    pr.add_argument("name_or_url", help="Feed name or URL as shown by `list`")

    p.set_defaults(func=cmd_feeds)
