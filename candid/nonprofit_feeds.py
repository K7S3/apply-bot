"""Nonprofit / mission-driven job feeds for the ``jobs curate`` pipeline.

Sources here must be genuinely public: no API key, no login, no scraping,
polite User-Agent only. Each adapter returns the same normalized job dicts
as :mod:`candid.jobs` adapters:
{source, source_id, title, company, location, url, description,
 salary_text, remote (bool), posted_at} and raises ``JobsError`` on failure.

Source verification notes (honest status, verified 2026-09-22):

- ReliefWeb Jobs *REST API* (https://api.reliefweb.int/v1/jobs) is
  decommissioned: the server answers ``410 Gone`` with "use version 'v2'
  instead". The v2 API is not usable either: it requires a registered
  *approved appname* and rejects unknown names with
  ``403 "You are not using an approved appname"`` (registration is a
  human approval flow, so it fails our no-key, fully-automated bar).
  The adapter below therefore uses ReliefWeb's public **Jobs RSS feed**
  (https://reliefweb.int/jobs/rss.xml), which is a documented public
  endpoint that returned 200 OK with 20 current postings, no credentials
  needed. RSS items carry: title, link/guid, pubDate, an HTML description
  (``Country:`` / ``Organization:`` divs), categories (country,
  organization, career category, listing type such as "Job"/"Consultancy",
  theme), and an author (the organization).

- A genuinely independent second source (Idealist, WorkForGood,
  UN Volunteers, B Work, All for Good, Catchafire, Devex) could NOT be
  verified this run: Idealist's API historically needs an API key, Devex
  is login-walled (both excluded on sight), and live web research for the
  remaining candidates was unavailable, so no claim is made and no feed
  is fabricated. Instead, ``adapt_reliefweb_volunteer()`` exposes the
  same ReliefWeb feed filtered to bridge roles (type in Internship /
  Volunteering / Fellowship), which is what the coordinator asked for as
  the honest fallback. The bridge filter reads the RSS item's listing
  type, so it is accurate whenever ReliefWeb posts such roles (the
  snapshot above only contained Job/Consultancy entries).
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET

# NOTE: FETCH_TIMEOUT, MAX_PER_SOURCE, USER_AGENT, and JobsError are
# imported lazily from candid.jobs inside _fetch_rss() rather than at
# module top: jobs.py merges NONPROFIT_ADAPTERS into its ADAPTERS registry,
# so a top-level import here would be circular.

SOURCE_NAME = "reliefweb"
RSS_URL = "https://reliefweb.int/jobs/rss.xml"

# ReliefWeb listing types we treat as "bridge roles" (internships,
# volunteering, fellowships) rather than regular employment.
BRIDGE_TYPES = frozenset({"Internship", "Volunteering", "Fellowship"})


def _fetch_rss() -> list[dict]:
    """Download the ReliefWeb Jobs RSS feed and return raw item dicts."""
    from candid.jobs import FETCH_TIMEOUT, MAX_PER_SOURCE, USER_AGENT, JobsError
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
    except Exception as exc:
        raise JobsError(f"ReliefWeb unreachable: {exc}") from exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise JobsError(f"ReliefWeb returned malformed RSS: {exc}") from exc
    items = root.findall(".//item")
    out: list[dict] = []
    for item in items[:MAX_PER_SOURCE]:
        text = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
        desc_html = text("description")
        # The description divs are the authoritative source for
        # organization and country; fall back to author/categories.
        org = _extract_div(desc_html, "Organization:") or text("author")
        country = _extract_div(desc_html, "Country:")
        categories = [(c.text or "").strip() for c in item.findall("category")]
        listing_type = next(
            (c for c in categories if c in BRIDGE_TYPES
             or c in ("Job", "Consultancy")),
            "",
        )
        if not country:
            country = next(
                (c for c in categories
                 if c not in BRIDGE_TYPES and c != "Job" and c != "Consultancy"
                 and c != org),
                "",
            )
        guid = text("guid") or text("link")
        job_id = re.search(r"/(\d+)(?:/|$)", guid)
        out.append({
            "title": text("title"),
            "organization": org,
            "location": country,
            "url": text("link") or guid,
            "source_id": job_id.group(1) if job_id else guid,
            "listing_type": listing_type,
            "description": _strip_html(desc_html),
            "posted_at": text("pubDate"),
        })
    return out


def _extract_div(html: str, prefix: str) -> str:
    """Pull the text after ``prefix`` inside a description div."""
    m = re.search(r"<div[^>]*>\s*" + re.escape(prefix) + r"\s*([^<]*)</div>",
                  html, re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _strip_html(html: str) -> str:
    desc = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", desc).strip()


def _remote(location: str) -> bool:
    loc = location.strip().lower()
    return loc in {"world", "remote", "home-based", "home based", "global"}


def _normalize(item: dict) -> dict:
    return {
        "source": SOURCE_NAME,
        "source_id": f"{SOURCE_NAME}:{item['source_id']}",
        "title": item["title"],
        "company": item["organization"],
        "location": item["location"],
        "url": item["url"],
        "description": item["description"][:4000],
        "salary_text": "",
        "remote": _remote(item["location"]),
        "posted_at": item["posted_at"],
    }


def adapt_reliefweb_jobs() -> list[dict]:
    """ReliefWeb humanitarian jobs (public RSS — free, no key, no login).

    Listing types covered: Job, Consultancy.
    """
    return [_normalize(item) for item in _fetch_rss()]


def adapt_reliefweb_volunteer() -> list[dict]:
    """ReliefWeb bridge roles: Internships / Volunteering / Fellowships.

    Same public RSS feed as :func:`adapt_reliefweb_jobs`, filtered to the
    listing types that make good mission-aligned bridge roles. May
    legitimately return an empty list when ReliefWeb has no such postings
    in the current feed.
    """
    return [
        _normalize(item)
        for item in _fetch_rss()
        if item["listing_type"] in BRIDGE_TYPES
    ]


NONPROFIT_ADAPTERS: dict[str, object] = {
    "reliefweb": adapt_reliefweb_jobs,
    "reliefweb_volunteer": adapt_reliefweb_volunteer,
}
