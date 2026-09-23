"""USAJOBS federal job search — opt-in source (needs a FREE API key).

Sign up: https://developer.usajobs.gov/SignUp — the key is free and instant
(no approval wait). Then set the env var CANDID_USAJOBS_KEY, or pass
``api_key=...`` explicitly.

Two ways to use:

1. With a key: ``search()`` hits the live USAJOBS search API and returns
   normalized job dicts (``source="usajobs"``) in the jobs.py format:
   {source, source_id, title, company, location, url, description,
   salary_text, remote (bool), posted_at}.
2. Without a key: ``sample_announcements()`` returns a small bundled set of
   clearly-labeled SAMPLE postings (fictional) so scoring, filtering and the
   tracker still work offline. Samples are marked SAMPLE everywhere — they
   are never presented as real postings.

``parse_announcement()`` extracts a structured detail dict from one
announcement payload (title, agency, pay plan/grade, series, hiring paths,
closing date, duty locations, remote/telework, clearance, citizenship,
questionnaire flag). It is defensive: USAJOBS payloads vary, so missing
fields become None (never a crash).

Wiring into jobs.curate (for the worker wiring this in): this source is
opt-in because it needs a key and search parameters. Either
``adapt_search_results(raw_payload)`` to normalize a payload you already
fetched, or register a no-arg adapter::

    import candid.usajobs as U, candid.jobs as J
    J.ADAPTERS["usajobs"] = U.opt_in_adapter("data scientist", location="New York")
    J.curate(profile, role, sources=["usajobs"])

Network: urllib only (stdlib), same as the other adapters. Failures are
raised as UsajobsError (a JobsError subclass), never raw tracebacks.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from candid.jobs import JobsError

API_URL = "https://data.usajobs.gov/api/search"
USER_AGENT = "candid/0.1 (personal job curation; contact: user-local)"
FETCH_TIMEOUT = 20
ENV_KEY = "CANDID_USAJOBS_KEY"
SIGNUP_URL = "https://developer.usajobs.gov/SignUp"
MAX_RESULTS_PER_PAGE = 500

__all__ = [
    "UsajobsError",
    "search",
    "adapt_search_results",
    "sample_announcements",
    "parse_announcement",
    "opt_in_adapter",
]


class UsajobsError(JobsError):
    """USAJOBS failure: missing API key, HTTP error, timeout, bad payload.

    Subclasses JobsError so the curate pipeline can catch it like any other
    source failure.
    """


# ---------------------------------------------------------------------------
# API key handling
# ---------------------------------------------------------------------------

def _resolve_key(api_key: str | None) -> str:
    """Return the API key, or raise a friendly UsajobsError explaining signup."""
    key = (api_key or os.environ.get(ENV_KEY) or "").strip()
    if key:
        return key
    raise UsajobsError(
        "USAJOBS search needs a free API key, and none was provided. "
        f"Sign up at {SIGNUP_URL} (free, takes ~2 minutes, no approval wait), "
        f"then either set the environment variable {ENV_KEY}=<your key> or "
        "pass api_key=... explicitly. "
        "Everything else works without a key: call sample_announcements() "
        "for clearly-labeled SAMPLE (fictional) postings, or "
        "parse_announcement() on any announcement payload you already have."
    )


def _fetch_json(url: str, api_key: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Authorization-Key": api_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise UsajobsError(
                "USAJOBS returned 401 Unauthorized — the API key is missing or "
                "invalid. Double-check your key (env "
                f"{ENV_KEY}) or get a fresh free one at {SIGNUP_URL}."
            ) from exc
        raise UsajobsError(f"USAJOBS API error (HTTP {exc.code}): {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise UsajobsError(f"USAJOBS unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UsajobsError("USAJOBS request timed out — try again.") from exc
    except json.JSONDecodeError as exc:
        raise UsajobsError("USAJOBS returned an unexpected (non-JSON) response.") from exc


# ---------------------------------------------------------------------------
# search adapter
# ---------------------------------------------------------------------------

def _search_url(keyword: str, location: str | None, series: str | None,
                grade: str | None, results_per_page: int) -> str:
    """Build the GET URL for the USAJOBS search endpoint."""
    params: dict[str, str] = {"Keyword": keyword}
    if location:
        params["LocationName"] = location
    if series:
        params["JobCategoryCode"] = series
    if grade:
        g = grade.strip()
        if "-" in g:
            lo, hi = g.split("-", 1)
            params["PayGradeLow"] = lo.strip()
            params["PayGradeHigh"] = hi.strip()
        else:
            params["PayGradeLow"] = g
            params["PayGradeHigh"] = g
    params["ResultsPerPage"] = str(max(1, min(results_per_page, MAX_RESULTS_PER_PAGE)))
    return API_URL + "?" + urllib.parse.urlencode(params)


def search(keyword: str, location: str | None = None, series: str | None = None,
           grade: str | None = None, results_per_page: int = 25,
           api_key: str | None = None) -> list[dict]:
    """Search USAJOBS and return normalized job dicts (source="usajobs").

    ``series`` is the 4-digit occupation series (e.g. "1550" = Computer
    Science); ``grade`` is a GS grade or range like "12" or "12-13".
    ``api_key`` defaults to the CANDID_USAJOBS_KEY env var; without a key a
    friendly UsajobsError is raised explaining the free signup.
    """
    key = _resolve_key(api_key)
    payload = _fetch_json(_search_url(keyword, location, series, grade,
                                      results_per_page), key)
    return adapt_search_results(payload)


def opt_in_adapter(keyword: str, **kwargs) -> object:
    """Build a no-arg adapter for jobs.ADAPTERS (opt-in; needs the API key).

    Example (for the wiring worker)::

        J.ADAPTERS["usajobs"] = U.opt_in_adapter("data scientist", location="New York")

    ``kwargs`` are forwarded to search() (location, series, grade,
    results_per_page, api_key).
    """
    def _fetch() -> list[dict]:
        return search(keyword, **kwargs)
    _fetch.__name__ = "usajobs_adapter"
    return _fetch


# ---------------------------------------------------------------------------
# normalization: raw USAJOBS payload -> jobs.py normalized dicts
# ---------------------------------------------------------------------------

def _descriptor(item: dict) -> dict:
    """Extract the MatchedObjectDescriptor from a search-result item.

    Accepts the full search payload (uses the first item), a search-result
    item wrapper, or a bare descriptor dict. Returns {} when unrecognizable.
    """
    if not isinstance(item, dict):
        return {}
    if "MatchedObjectDescriptor" in item and isinstance(item["MatchedObjectDescriptor"], dict):
        return item["MatchedObjectDescriptor"]
    sr = item.get("SearchResult")
    if isinstance(sr, dict):
        items = sr.get("SearchResultItems") or []
        if items and isinstance(items[0], dict):
            d = items[0].get("MatchedObjectDescriptor")
            if isinstance(d, dict):
                return d
        return {}
    if "PositionTitle" in item or "PositionID" in item:
        return item  # already a bare descriptor
    return {}


def _items(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    sr = payload.get("SearchResult")
    if not isinstance(sr, dict):
        return []
    items = sr.get("SearchResultItems")
    return [i for i in (items or []) if isinstance(i, dict)]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _description(descriptor: dict) -> str:
    """Compose a plain-text description from the descriptor's content sections."""
    parts = []
    summary = descriptor.get("QualificationSummary")
    if summary:
        parts.append(str(summary))
    for section in descriptor.get("PositionFormattedDescription") or []:
        if not isinstance(section, dict):
            continue
        content = section.get("Content")
        if content:
            label = section.get("Label") or ""
            parts.append(f"{label}: {content}" if label else str(content))
    details = _details(descriptor)
    for key in ("JobSummary", "MajorDuties", "Requirements", "Qualifications"):
        val = details.get(key)
        if val:
            parts.append(f"{key}: {val}")
    return _strip_html("\n\n".join(parts))[:4000]


def _details(descriptor: dict) -> dict:
    ua = descriptor.get("UserArea")
    if not isinstance(ua, dict):
        return {}
    det = ua.get("Details")
    return det if isinstance(det, dict) else {}


def _salary_text(descriptor: dict) -> str:
    for rem in descriptor.get("PositionRemuneration") or []:
        if not isinstance(rem, dict):
            continue
        desc = (rem.get("Description") or "").strip()
        if desc:
            return desc
        lo, hi = rem.get("MinimumRange"), rem.get("MaximumRange")
        if lo or hi:
            return f"${lo or '?'} - ${hi or '?'}"
    return ""


def _location(descriptor: dict) -> str:
    display = (descriptor.get("PositionLocationDisplay") or "").strip()
    if display:
        return display
    cities = []
    for loc in descriptor.get("PositionLocation") or []:
        if not isinstance(loc, dict):
            continue
        city = (loc.get("CityName") or "").strip()
        state = (loc.get("StateName") or loc.get("CountrySubDivisionCode") or "").strip()
        label = ", ".join(p for p in (city, state) if p)
        if label and label not in cities:
            cities.append(label)
    return "; ".join(cities)


def _is_remote(descriptor: dict, location: str) -> bool:
    details = _details(descriptor)
    if details.get("RemoteIndicator") is True:
        return True
    val = descriptor.get("RemoteIndicator")
    if val is True:
        return True
    low = location.lower()
    return "remote" in low and "remote area" not in low


def _adapt_descriptor(descriptor: dict) -> dict:
    position_id = (descriptor.get("PositionID")
                   or descriptor.get("ControlNumber")
                   or descriptor.get("MatchedObjectId") or "")
    location = _location(descriptor)
    apply_uris = descriptor.get("ApplyURI") or []
    url = descriptor.get("PositionURI") or ""
    if not url and apply_uris:
        url = str(apply_uris[0] or "")
    return {
        "source": "usajobs",
        "source_id": f"usajobs:{position_id}",
        "title": (descriptor.get("PositionTitle") or "").strip(),
        "company": (descriptor.get("OrganizationName")
                    or descriptor.get("DepartmentName") or "").strip(),
        "location": location,
        "url": url,
        "description": _description(descriptor),
        "salary_text": _salary_text(descriptor),
        "remote": _is_remote(descriptor, location),
        "posted_at": str(descriptor.get("PublicationStartDate")
                         or descriptor.get("PositionStartDate") or ""),
    }


def adapt_search_results(payload: dict) -> list[dict]:
    """Normalize a raw USAJOBS search payload to jobs.py job dicts.

    Pure function — no network. Defensive: malformed items are skipped,
    a malformed payload yields [].
    """
    out = []
    for item in _items(payload):
        descriptor = _descriptor(item)
        if not descriptor:
            continue
        try:
            out.append(_adapt_descriptor(descriptor))
        except Exception:
            continue  # never let one bad item kill the batch
    return out


# ---------------------------------------------------------------------------
# sample announcements (offline, clearly labeled SAMPLE — never live data)
# ---------------------------------------------------------------------------

_SAMPLES: list[dict] = [
    {
        "source": "usajobs", "source_id": "usajobs:SAMPLE-1550-001",
        "title": "[SAMPLE] Computer Scientist, GS-12/13",
        "company": "Department of Commerce (SAMPLE AGENCY)",
        "location": "Washington, District of Columbia",
        "url": "https://www.usajobs.gov/",
        "description": (
            "[SAMPLE - not a real posting] Develop and evaluate machine "
            "learning models for economic forecasting. Requires Python, "
            "statistical modeling, and experience with large datasets. "
            "Full-time, telework eligible."
        ),
        "salary_text": "$99,200 - $153,354 per year",
        "remote": False, "posted_at": "",
    },
    {
        "source": "usajobs", "source_id": "usajobs:SAMPLE-1550-002",
        "title": "[SAMPLE] Data Scientist (Remote), GS-11/12",
        "company": "Department of Health and Human Services (SAMPLE AGENCY)",
        "location": "Remote",
        "url": "https://www.usajobs.gov/",
        "description": (
            "[SAMPLE - not a real posting] Analyze public-health datasets, "
            "build dashboards, and automate reporting pipelines with SQL and "
            "Python. Remote work authorized from anywhere in the U.S."
        ),
        "salary_text": "$82,764 - $128,956 per year",
        "remote": True, "posted_at": "",
    },
    {
        "source": "usajobs", "source_id": "usajobs:SAMPLE-2210-001",
        "title": "[SAMPLE] IT Specialist (Application Software), GS-9/11",
        "company": "Department of Veterans Affairs (SAMPLE AGENCY)",
        "location": "Austin, Texas",
        "url": "https://www.usajobs.gov/",
        "description": (
            "[SAMPLE - not a real posting] Maintain veteran-facing web "
            "services; JavaScript and REST APIs. Open to the public; "
            "veterans' preference applies."
        ),
        "salary_text": "$63,091 - $98,305 per year",
        "remote": False, "posted_at": "",
    },
    {
        "source": "usajobs", "source_id": "usajobs:SAMPLE-0601-001",
        "title": "[SAMPLE] General Health Scientist, GS-13",
        "company": "Centers for Disease Control and Prevention (SAMPLE AGENCY)",
        "location": "Atlanta, Georgia",
        "url": "https://www.usajobs.gov/",
        "description": (
            "[SAMPLE - not a real posting] Lead epidemiological studies and "
            "coordinate multi-site data collection. Requires U.S. citizenship "
            "and a background investigation."
        ),
        "salary_text": "$117,962 - $153,354 per year",
        "remote": False, "posted_at": "",
    },
]


def sample_announcements() -> list[dict]:
    """Bundled SAMPLE announcements for offline use (fictional postings).

    Every record is clearly labeled SAMPLE in its title, description and
    source_id — never invent live data. The records are already in the
    jobs.py normalized format, so filtering/scoring/tracker flows work
    without an API key.
    """
    return [dict(s) for s in _SAMPLES]


# ---------------------------------------------------------------------------
# announcement detail parser
# ---------------------------------------------------------------------------

def _grade_codes(descriptor: dict) -> list[str]:
    codes: list[str] = []
    for g in descriptor.get("JobGrade") or []:
        if not isinstance(g, dict):
            continue
        code = str(g.get("Code") or "").strip()
        if code and code not in codes:
            codes.append(code)
    for key in ("LowGrade", "HighGrade"):
        code = str(descriptor.get(key) or "").strip()
        if code and code not in codes:
            codes.append(code)
    return [c for c in codes if re.fullmatch(r"\d{1,2}", c)]


def _pay_plan(descriptor: dict) -> str | None:
    for key in ("PayPlan", "PositionPayPlan", "payPlan"):
        val = descriptor.get(key)
        if val:
            return str(val).strip().upper() or None
    return None


def _series(descriptor: dict) -> str | None:
    for cat in descriptor.get("JobCategory") or []:
        if not isinstance(cat, dict):
            continue
        code = str(cat.get("Code") or "").strip()
        if re.fullmatch(r"\d{4}", code):
            return code
    # last resort: a 4-digit series in the title, e.g. "Computer Scientist (1550)"
    m = re.search(r"\((\d{4})\)", descriptor.get("PositionTitle") or "")
    return m.group(1) if m else None


def _who_may_apply(descriptor: dict, details: dict) -> str | None:
    wma = details.get("WhoMayApply")
    if isinstance(wma, dict):
        name = (wma.get("Name") or "").strip()
        if name:
            return name
    elif isinstance(wma, str) and wma.strip():
        return wma.strip()
    wma = descriptor.get("WhoMayApply")
    if isinstance(wma, str) and wma.strip():
        return wma.strip()
    paths = _hiring_path_codes(details)
    names = [n for n in (_hiring_path_name(p) for p in paths) if n]
    return "; ".join(names) if names else None


def _hiring_path_codes(details: dict) -> list[str]:
    raw = details.get("HiringPaths")
    if not isinstance(raw, list):
        return []
    return [str(p).strip().lower() for p in raw if str(p).strip()]


_HIRING_PATH_NAMES: dict[str, str] = {
    "public": "The public",
    "fed-competitive": "Federal employees - Competitive service",
    "fed-excepted": "Federal employees - Excepted service",
    "fed": "Federal employees",
    "vet": "Veterans",
    "vet-preference": "Veterans with preference",
    "disabled": "Individuals with disabilities",
    "ses": "Senior Executives",
    "military-spouses": "Military spouses",
    "peace-corps": "Peace Corps & AmeriCorps VISTA",
    "students": "Students",
    "recent-grads": "Recent graduates",
}


def _hiring_path_name(code: str) -> str | None:
    if code in _HIRING_PATH_NAMES:
        return _HIRING_PATH_NAMES[code]
    for prefix, name in _HIRING_PATH_NAMES.items():
        if code.startswith(prefix):
            return name
    return code.replace("-", " ").title() or None


def _hiring_path_flags(codes: list[str]) -> dict[str, bool]:
    return {
        "public": any(c == "public" or c.startswith("public-") for c in codes),
        "federal_employee": any(c.startswith("fed") for c in codes),
        "veteran": any(p == "vet" or p.startswith("vet-") or p.startswith("vet_")
                       for c in codes for p in re.split(r"[-_/]", c)),
    }


def _duty_locations(descriptor: dict) -> list[str]:
    locs: list[str] = []
    for loc in descriptor.get("PositionLocation") or []:
        if not isinstance(loc, dict):
            continue
        city = (loc.get("CityName") or "").strip()
        state = (loc.get("StateName") or loc.get("CountrySubDivisionCode")
                 or loc.get("CountryCode") or "").strip()
        label = ", ".join(p for p in (city, state) if p)
        if label and label not in locs:
            locs.append(label)
    if not locs:
        display = (descriptor.get("PositionLocationDisplay") or "").strip()
        if display:
            locs.append(display)
    return locs


def _questionnaire_required(descriptor: dict, details: dict) -> bool:
    """True when the announcement requires an online questionnaire/assessment."""
    for key, val in details.items():
        if re.search(r"questionnaire|assessment", str(key), re.IGNORECASE):
            if val:
                return True
    for key, val in descriptor.items():
        if re.search(r"questionnaire|assessment", str(key), re.IGNORECASE):
            if val:
                return True
    apply_uris = descriptor.get("ApplyURI") or []
    return bool(details.get("ApplyOnlineUrl")
                or (isinstance(apply_uris, list) and any(apply_uris)))


def parse_announcement(payload: dict) -> dict:
    """Parse one USAJOBS announcement into a structured detail dict.

    Accepts the full search payload, a search-result item wrapper, or a bare
    MatchedObjectDescriptor. Defensive: USAJOBS payloads vary; any missing
    field becomes None (or False/empty for flags/lists) — never an exception.
    """
    d = _descriptor(payload) if isinstance(payload, dict) else {}
    details = _details(d)
    codes = _hiring_path_codes(details)
    grades = _grade_codes(d)
    plan = _pay_plan(d)

    if len(grades) >= 2:
        grade_range = f"{plan + ' ' if plan else ''}{grades[0]}-{grades[-1]}"
    elif len(grades) == 1:
        grade_range = f"{plan + ' ' if plan else ''}{grades[0]}"
    else:
        grade_range = None

    clearance = details.get("SecurityClearance")
    if isinstance(clearance, dict):
        clearance = (clearance.get("Name") or clearance.get("Code") or "").strip() or None
    elif clearance is not None:
        clearance = str(clearance).strip() or None

    citizenship = None
    for key in ("CitizenshipRequired", "IsCitizenshipRequired", "Citizenship"):
        val = details.get(key)
        if val is not None and str(val).strip():
            citizenship = val if isinstance(val, bool) else str(val).strip()
            break

    return {
        "title": (d.get("PositionTitle") or "").strip() or None,
        "agency": (d.get("OrganizationName") or d.get("DepartmentName") or "").strip() or None,
        "pay_plan": plan,
        "grade_range": grade_range,
        "occupation_series": _series(d),
        "who_may_apply": _who_may_apply(d, details),
        "hiring_paths": _hiring_path_flags(codes),
        "closing_date": str(d.get("PositionEndDate") or "").strip() or None,
        "duty_locations": _duty_locations(d),
        "remote": _is_remote(d, _location(d)),
        "telework_eligible": bool(details.get("TeleworkEligible")),
        "clearance_required": clearance,
        "citizenship_required": citizenship,
        "questionnaire_required": _questionnaire_required(d, details),
    }
