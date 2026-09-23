"""Company briefs for interview prep packs.

Attaches a sourced "Company brief" section to prep packs:

- **Wikipedia API** (no key): company summary + infobox basics
  (founded, headquarters, industry, employees, type, key people).
- **SEC EDGAR** (no key): for public US companies, highlights from the
  latest 10-K - revenue, net income, total assets, employee count -
  pulled from the XBRL company-facts feed.

Honesty rules (same as the "no verified questions" fallback in prep):

- Every fact carries its source label. Numbers are never estimated or
  filled in.
- If a source has nothing for the company, the brief says so explicitly
  ("no verified data found") instead of inventing funding, headcount,
  or financials.

Caching: API responses are cached under ``candid_data/briefs_cache/``.
``get_brief(company, refresh=True)`` (or ``prep brief --refresh``)
re-fetches; otherwise the cache is used. When the network is
unavailable, candid falls back to the cache, or to the "no verified
data" note when there is no cache.

SEC EDGAR requires a User-Agent carrying a contact email; the default
uses a placeholder (see docs/briefs.md). Set CANDID_SEC_CONTACT to
e.g. "Your Name you@example.com" to identify yourself properly.

Usage:
    python -m candid prep brief --company "Acme Corp"
    python -m candid prep brief --company "Acme Corp" --refresh
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from candid import config as C

USER_AGENT = os.environ.get("CANDID_SEC_CONTACT", "").strip()
if not USER_AGENT or "@" not in USER_AGENT:
    # SEC EDGAR requires a User-Agent carrying a contact email (their WAF
    # 403s requests without one). The default is a documented placeholder;
    # set CANDID_SEC_CONTACT to e.g. "Your Name you@example.com" to
    # identify yourself properly per the SEC's fair-access policy.
    USER_AGENT = "candid-jobsearch-copilot/0.2.0 (admin@example.com)"

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_HTTP_TIMEOUT = 20

#: infobox key -> display label (Wikipedia company infobox fields)
_WIKI_FACTS = {
    "type": "Type",
    "industry": "Industry",
    "founded": "Founded",
    "founder": "Founder(s)",
    "founders": "Founder(s)",
    "hq_location": "Headquarters",
    "hq_location_city": "Headquarters",
    "location": "Headquarters",
    "num_employees": "Employees",
    "revenue": "Revenue",
    "parent": "Parent",
    "key_people": "Key people",
}

#: display label -> us-gaap concepts to try (first with the freshest 10-K wins)
_EDGAR_CONCEPTS: list[tuple[str, list[str]]] = [
    ("Revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "SalesRevenueNet", "Revenues"]),
    ("Net income", ["NetIncomeLoss"]),
    ("Total assets", ["Assets"]),
    ("Total liabilities", ["Liabilities"]),
    ("Employees", ["Employees"]),
]


class BriefError(Exception):
    """Raised when a company brief cannot be produced at all."""


def cache_dir() -> Path:
    d = C.DATA_DIR / "briefs_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(company: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in company.lower())
    return re.sub(r"_+", "_", slug).strip("_") or "company"


def _http_json(url: str, params: dict | None = None) -> dict | None:
    """GET a JSON endpoint with a proper User-Agent; None on any failure."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

def _strip_wiki(text: str) -> str:
    """Best-effort removal of wiki markup from an infobox value."""
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    # keep the value part of common value templates before dropping the rest
    text = re.sub(r"\{\{[Uu][Ss]\$\|([^}]*)\}\}", r"$\1", text)
    text = re.sub(r"\{\{[Uu]sd\|([^}]*)\}\}", r"$\1", text)
    text = re.sub(r"\{\{cvt\|([^|}]*)\|[^}]*\}\}", r"\1", text)
    text = re.sub(r"\{\{[Ss]tart date and age\|(\d{4})(?:\|[^}]*)?\}\}", r"\1", text)
    # drop remaining templates (e.g. {{start date and age|...}})
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    # [[link|label]] -> label ; [[link]] -> link
    text = re.sub(r"\[\[([^|\]]*\|)?([^\]]+)\]\]", r"\2", text)
    # drop a trailing infobox closer (the last field's value may include "}}")
    text = re.sub(r"\}{2,}\s*$", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip(" ;,")
    return text


def _infobox_fields(wikitext: str) -> dict[str, str]:
    """Parse {{Infobox company ...}} fields from article wikitext."""
    m = re.search(r"\{\{\s*[Ii]nfobox\s+company\b", wikitext)
    if not m:
        return {}
    depth = 0
    start = m.start()
    i = m.start()
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    body = wikitext[m.end():i]
    fields: dict[str, str] = {}
    # split on top-level "|" boundaries (ignore pipes inside {{ }} or [[ ]])
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    for part in parts:
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip().lower()
        val = _strip_wiki(val)
        if key and val and key not in fields:
            fields[key] = val
    return fields


def _funding_mention(summary: str) -> str:
    """Pull a funding sentence from the summary, if Wikipedia mentions one."""
    for sent in re.split(r"(?<=[.!?])\s+", summary):
        low = sent.lower()
        if ("funding" in low or "raised" in low) and re.search(r"\$\s?[\d,.]+\s*(million|billion|m\b|bn\b)", low):
            return sent.strip()
    return ""


def _is_disambiguation(page: dict) -> bool:
    if "disambiguation" in (page.get("pageprops") or {}):
        return True
    extract = (page.get("extract") or "").strip().lower()
    return extract.endswith("may refer to:") or "may refer to:" in extract[:120]


def fetch_wikipedia(company: str) -> dict:
    """Query the Wikipedia API. Never raises; returns a parsed dict."""
    out: dict = {
        "found": False, "title": "", "url": "",
        "summary": "", "facts": {}, "funding_mention": "",
    }
    candidates = [company, f"{company} (company)", f"{company} Inc",
                  f"{company}, Inc."]
    page: dict = {}
    for title in candidates:
        data = _http_json(_WIKI_API, {
            "action": "query", "format": "json", "redirects": "1",
            "prop": "extracts|info|pageprops", "inprop": "url",
            "exintro": "1", "explaintext": "1", "exsectionformat": "plain",
            "titles": title,
        })
        pages = (data or {}).get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {}) if pages else {}
        if page and "missing" not in page and not _is_disambiguation(page):
            break
        page = {}
    if not page:
        return out
    title = page.get("title", "")
    summary = (page.get("extract") or "").strip()
    if not summary:
        return out
    out.update({
        "found": True, "title": title,
        "url": page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
        "summary": summary[:900] + ("…" if len(summary) > 900 else ""),
        "funding_mention": _funding_mention(summary),
    })
    # infobox basics from the article wikitext
    wt = _http_json(_WIKI_API, {
        "action": "query", "format": "json", "redirects": "1",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "titles": title,
    })
    try:
        pages = (wt or {}).get("query", {}).get("pages", {})
        pg = next(iter(pages.values()), {})
        wikitext = pg.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
        if not wikitext:  # newer API shape
            wikitext = pg.get("revisions", [{}])[0].get("*", "")
        for key, val in _infobox_fields(wikitext).items():
            if key in _WIKI_FACTS and val:
                out["facts"][_WIKI_FACTS[key]] = val
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[.,]", "", name)
    for suffix in (" inc", " corp", " corporation", " company", " co",
                   " llc", " ltd", " limited", " plc", " group", " holdings"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return re.sub(r"\s+", " ", name).strip()


def _edgar_cik(company: str) -> tuple[str, str] | None:
    """Resolve a company name to (10-digit CIK, ticker). None when no match."""
    data = _http_json(_SEC_TICKERS)
    if not data:
        return None
    want = _normalize_name(company)
    exact = None
    for entry in data.values():
        title = str(entry.get("title", ""))
        norm = _normalize_name(title)
        if norm == want:
            exact = entry
            break
    if exact is None:
        for entry in data.values():
            title = str(entry.get("title", ""))
            norm = _normalize_name(title)
            if norm and (norm in want or want in norm):
                exact = entry
                break
    if exact is None:
        return None
    cik = str(exact.get("cik_str", "")).zfill(10)
    return (cik, str(exact.get("ticker", "")).upper()) if cik.strip("0") else None


def _latest_10k_date(cik: str) -> str:
    subs = _http_json(_SEC_SUBMISSIONS.format(cik=cik))
    if not subs:
        return ""
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    for form, fdate in zip(forms, dates):
        if form == "10-K":
            return fdate
    return ""


def _edgar_facts(cik: str) -> dict[str, dict]:
    """Latest 10-K values for the highlight concepts. Never raises.

    For aliased concepts the row with the freshest period end wins, so a
    stale legacy concept (e.g. us-gaap:Revenues superseded by
    RevenueFromContractWithCustomerExcludingAssessedTax) can never shadow
    the current one.
    """
    data = _http_json(_SEC_COMPANYFACTS.format(cik=cik))
    out: dict[str, dict] = {}
    if not data:
        return out
    facts = data.get("facts", {}).get("us-gaap", {})
    for label, concepts in _EDGAR_CONCEPTS:
        best: dict | None = None
        for concept in concepts:
            node = facts.get(concept, {})
            units = node.get("units", {})
            series = units.get("USD") or units.get("pure") or []
            rows = [r for r in series if r.get("form") == "10-K" and r.get("end")]
            if not rows:
                continue
            latest = max(rows, key=lambda r: r.get("end", ""))
            if best is None or latest.get("end", "") > best.get("end", ""):
                best = latest
        if not best:
            continue
        try:
            value = float(best.get("val"))
        except (TypeError, ValueError):
            continue
        out[label] = {
            "value": value,
            "fy": (best.get("end") or "")[:4],
            "filed": best.get("filed", ""),
        }
    return out


def fetch_edgar(company: str) -> dict:
    """10-K highlights from SEC EDGAR. Never raises; empty when not found."""
    out: dict = {
        "found": False, "cik": "", "ticker": "",
        "latest_10k_date": "", "facts": {}, "note": "",
    }
    resolved = _edgar_cik(company)
    if not resolved:
        out["note"] = (f"No SEC EDGAR filer found matching \"{company}\" - "
                       "it may be private, non-US, or listed under a different name.")
        return out
    cik, ticker = resolved
    out.update({"found": True, "cik": cik, "ticker": ticker,
                "latest_10k_date": _latest_10k_date(cik),
                "facts": _edgar_facts(cik)})
    if not out["facts"]:
        out["note"] = (f"EDGAR filer found (CIK {cik}, ticker {ticker}) but no "
                       "10-K XBRL facts were available.")
    return out


# ---------------------------------------------------------------------------
# Orchestration: get_brief + render
# ---------------------------------------------------------------------------

_NO_DATA_NOTE = (
    "> **No verified company data found.** We could not pull funding, "
    "headcount, or financial facts for \"{company}\" from Wikipedia or "
    "SEC EDGAR (offline, or no match in either source). Nothing here is "
    "estimated - check the company's investor-relations page and recent "
    "press, then re-run `python -m candid prep brief --company \"{company}\" "
    "--refresh`."
)


def get_brief(company: str, refresh: bool = False) -> dict:
    """Build (or load from cache) the company brief.

    Never raises on network failure: falls back to cache, then to the
    "no verified data" shape.
    """
    company = (company or "").strip()
    if not company:
        raise BriefError("A company name is required.")
    path = cache_dir() / f"{_slug(company)}.json"
    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            brief = cached.get("brief") or {}
            brief["from_cache"] = True
            return brief
        except Exception:
            pass
    brief = {
        "company": company,
        "generated": date.today().isoformat(),
        "from_cache": False,
    }
    # never let a transport failure escape: fall back to the "no data" shape
    try:
        brief["wikipedia"] = fetch_wikipedia(company)
    except Exception:
        brief["wikipedia"] = {"found": False, "facts": {}}
    try:
        brief["edgar"] = fetch_edgar(company)
    except Exception:
        brief["edgar"] = {"found": False, "facts": {}, "note": ""}
    try:
        path.write_text(json.dumps(
            {"fetched_at": time.time(), "brief": brief},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return brief


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e12:
        return f"{sign}${v / 1e12:,.1f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:,.1f}M"
    return f"{sign}${v:,.0f}"


def _fmt_count(value: float) -> str:
    return f"{value:,.0f}"


def render_brief(brief: dict) -> str:
    """Render the brief as Markdown. Every fact carries its source."""
    company = brief.get("company", "")
    wiki = brief.get("wikipedia", {}) or {}
    edgar = brief.get("edgar", {}) or {}
    lines = [f"## Company brief - {company}", ""]
    if brief.get("from_cache"):
        lines.append("_Loaded from local cache - re-run with `--refresh` for fresh data._")
        lines.append("")

    if wiki.get("found"):
        lines += [f"**{wiki.get('title', company)}** *(Source: Wikipedia)*  ", ""]
        if wiki.get("summary"):
            lines += [wiki["summary"], ""]
        if wiki.get("url"):
            lines.append(f"[Wikipedia article]({wiki['url']})")
            lines.append("")
        for label, val in wiki.get("facts", {}).items():
            lines.append(f"- **{label}:** {val}  *(Source: Wikipedia infobox)*")
        if wiki.get("funding_mention"):
            lines.append(f"- **Funding (mentioned):** {wiki['funding_mention']}  "
                         "*(Source: Wikipedia article text)*")
        if wiki.get("facts") or wiki.get("funding_mention"):
            lines.append("")
    else:
        lines.append("_No Wikipedia page found for this company - "
                     "no headcount/founding basics available from Wikipedia._")
        lines.append("")

    if edgar.get("found"):
        facts = edgar.get("facts", {})
        ticker = edgar.get("ticker", "")
        lines.append(f"**SEC EDGAR** - CIK {edgar.get('cik', '')}"
                    + (f", ticker {ticker}" if ticker else ""))
        lines.append("*(Source: SEC EDGAR)*")
        lines.append("")
        if edgar.get("latest_10k_date"):
            lines.append(f"- **Latest 10-K filed:** {edgar['latest_10k_date']}  "
                         "*(Source: SEC EDGAR submissions)*")
        for label, info in facts.items():
            val = info.get("value", 0)
            money = _fmt_money(val) if label != "Employees" else _fmt_count(val)
            fy = info.get("fy", "")
            lines.append(f"- **{label}{' (FY' + fy + ')' if fy else ''}:** {money}  "
                         "*(Source: SEC EDGAR 10-K XBRL, us-gaap)*")
        if not facts and edgar.get("note"):
            lines.append(f"_{edgar['note']}_")
        lines.append("")
    else:
        note = edgar.get("note") or "No SEC EDGAR filer found."
        lines.append(f"_{note}_")
        lines.append("")

    if not wiki.get("found") and not (edgar.get("found") and edgar.get("facts")):
        lines.append(_NO_DATA_NOTE.format(company=company))
        lines.append("")
    lines.append("---")
    lines.append("_Company brief: facts are labeled with their source. "
                 "Verify anything you will quote in an interview against the "
                 "company's own investor-relations page._")
    return "\n".join(lines)
