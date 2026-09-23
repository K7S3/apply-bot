"""Alumni network mapper.

Turn your LinkedIn connections into a warm-outreach map: who you know at
target companies, which shared schools or employers give you a natural
opener, and who to contact first.

Source data: LinkedIn's official export only (Settings → Data privacy →
Get a copy of your data). No scraping, no logins. ``Connections.csv`` in
the export carries name, company, position and connected-on date — email
addresses are deliberately dropped on import, same as ``linkedin.py``.

One honest limitation, stated up front: ``Connections.csv`` does NOT
include anyone's school. School overlap therefore needs a tiny bit of
your own input — an enrichment CSV (``alumni enrich --csv schools.csv``)
with columns::

    name,school,grad_year,prev_company,start_year,end_year,notes

One row per fact; several rows per person are fine (two schools, three
past jobs). A filled-in example lives at
``samples/candid/sample_enrichment.csv``.

Everything is stored in ``candid_data/network.json`` (git-ignored, never
committed). All scoring is deterministic and explainable — every point
carries its reason, and drafts only use facts already in the network.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

from candid import config as C


class AlumniError(Exception):
    """Raised for alumni-mapper problems (bad file, unknown contact, ...)."""


NETWORK_FILENAME = "network.json"

INTERACTION_KINDS = ("met", "emailed", "called", "coffee", "messaged", "other")

DRAFT_KINDS = ("referral", "info-chat", "reconnect")

# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def network_path() -> Path:
    return C.DATA_DIR / NETWORK_FILENAME


def blank_network() -> dict:
    return {"contacts": [], "interactions": [],
            "meta": {"imported_at": "", "source": "", "enriched_at": ""}}


def load_network() -> dict:
    p = network_path()
    if not p.exists():
        return blank_network()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return blank_network()
    net = blank_network()
    if isinstance(data, dict):
        net["contacts"] = data.get("contacts", []) or []
        net["interactions"] = data.get("interactions", []) or []
        if isinstance(data.get("meta"), dict):
            net["meta"].update(data["meta"])
    return net


def save_network(net: dict) -> Path:
    C.ensure_data_dirs()
    p = network_path()
    p.write_text(json.dumps(net, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

_CORP_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "llc", "ltd", "limited",
    "co", "company", "gmbh", "plc", "pte", "pvt", "srl", "sas", "bv", "ab",
    "oy", "as", "sa", "ag", "holdings", "holding", "group", "labs",
    "technologies", "technology", "tech",
}

_SCHOOL_GENERIC = {
    "university", "college", "school", "institute", "of", "the", "at",
    "de", "a", "an", "for",
}

_WS_PUNCT = re.compile(r"[^\w\s]")
_WS_MULTI = re.compile(r"\s+")


def _clean(s: str) -> str:
    s = _WS_PUNCT.sub(" ", (s or "").lower())
    return _WS_MULTI.sub(" ", s).strip()


def norm_name(name: str) -> str:
    """Lowercase, punctuation-free, single-spaced."""
    return _clean(name)


def norm_company(name: str) -> str:
    """Normalize a company name for overlap matching.

    Strips corporate suffixes (Inc, LLC, Corp, ...) so "Acme Inc." matches
    "acme". Conservative: only trailing suffix tokens are dropped.
    """
    toks = _clean(name).split()
    while len(toks) > 1 and toks[-1] in _CORP_SUFFIXES:
        toks.pop()
    return " ".join(toks)


def norm_school(name: str) -> str:
    """Normalize a school to its distinctive tokens, sorted.

    Generic words (university, college, institute, of, the, ...) are
    dropped, so "University of Texas at Austin" and "Texas Austin" both
    become "austin texas". Write school names in full in the enrichment
    file — abbreviations like "UT Austin" will NOT match.
    """
    toks = [t for t in _clean(name).split() if t not in _SCHOOL_GENERIC]
    return " ".join(sorted(toks))


def companies_match(a: str, b: str) -> bool:
    """True if two company names refer to the same company (fuzzy)."""
    na, nb = norm_company(a), norm_company(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    # token-subset match, but the shorter side needs at least 2 tokens,
    # or 1 token of length >= 5 ("acme" vs "acme corporation" matches;
    # "meta" vs "metals" does not).
    if ta <= tb or tb <= ta:
        short = ta if len(ta) <= len(tb) else tb
        if len(short) >= 2:
            return True
        if len(short) == 1 and len(next(iter(short))) >= 5:
            return True
    return False


def schools_match(a: str, b: str) -> bool:
    """True if two school names match after normalization (exact tokens)."""
    na, nb = norm_school(a), norm_school(b)
    return bool(na) and na == nb


# ---------------------------------------------------------------------------
# Connections.csv parsing (LinkedIn official export format)
# ---------------------------------------------------------------------------

# Real LinkedIn Connections.csv headers:
# First Name, Last Name, URL, Email Address, Company, Position, Connected On
_CONN_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y",
                      "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y")


def _get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and (row[n] or "").strip():
            return row[n].strip()
    low = {k.lower(): v for k, v in row.items() if k}
    for n in names:
        v = low.get(n.lower(), "")
        if v and v.strip():
            return v.strip()
    return ""


def _parse_connected_on(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in _CONN_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _row_to_contact(row: dict) -> dict | None:
    first = _get(row, "First Name", "FirstName")
    last = _get(row, "Last Name", "LastName")
    name = f"{first} {last}".strip() or _get(row, "Name", "Full Name")
    if not name:
        return None
    return {
        "name": name,
        "company": _get(row, "Company", "Organization"),
        "position": _get(row, "Position", "Title", "Headline"),
        "connected_on": _parse_connected_on(_get(row, "Connected On", "ConnectedOn", "Date")),
        "url": _get(row, "URL", "Profile URL", "Link"),
        # Email addresses are deliberately NOT imported (privacy).
        "schools": [],
        "history": [],
        "notes": "",
    }


def parse_connections_csv(path: str | Path) -> list[dict]:
    """Parse a raw Connections.csv file into contact records."""
    p = Path(path)
    if not p.exists():
        raise AlumniError(f"File not found: {p}")
    try:
        raw = p.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise AlumniError(f"Couldn't read {p}: {e}")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise AlumniError(f"{p} has no header row — is this a Connections.csv?")
    contacts = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        c = _row_to_contact(row)
        if c:
            contacts.append(c)
    if not contacts:
        raise AlumniError(f"No contacts parsed from {p}. Expected LinkedIn "
                          "Connections.csv columns (First Name, Last Name, "
                          "Company, Position, Connected On).")
    return contacts


def parse_connections_zip(zip_path: str | Path) -> list[dict]:
    """Parse Connections.csv out of a full LinkedIn data-export ZIP."""
    p = Path(zip_path)
    if not p.exists():
        raise AlumniError(f"File not found: {p}")
    if not zipfile.is_zipfile(p):
        raise AlumniError(f"Not a ZIP file: {p}")
    with zipfile.ZipFile(p) as zf:
        target = next((n for n in zf.namelist()
                       if Path(n).name.lower() == "connections.csv"), None)
        if target is None:
            names = [Path(n).name for n in zf.namelist()
                     if n.lower().endswith(".csv")]
            raise AlumniError(
                "No Connections.csv in this export. "
                f"CSVs found: {', '.join(sorted(set(names))) or 'none'}. "
                "Request the larger archive: LinkedIn → Settings & Privacy → "
                "Data privacy → Get a copy of your data.")
        raw = zf.read(target).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    contacts = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        c = _row_to_contact(row)
        if c:
            contacts.append(c)
    if not contacts:
        raise AlumniError("Connections.csv in the ZIP held no parseable contacts.")
    return contacts


def import_connections(source: str | Path, replace: bool = False) -> dict:
    """Import connections into candid_data/network.json.

    ``source`` is a Connections.csv path or a LinkedIn export ZIP (auto
    detected by extension). With replace=False (default) existing contacts
    are kept and any enrichment (schools/history/notes) survives a
    re-import; new rows merge by normalized name.
    """
    p = Path(source)
    contacts = (parse_connections_zip(p) if p.suffix.lower() == ".zip"
                else parse_connections_csv(p))
    net = blank_network() if replace else load_network()
    existing = {norm_name(c["name"]): c for c in net["contacts"]}
    added, updated = 0, 0
    for c in contacts:
        key = norm_name(c["name"])
        if key in existing:
            old = existing[key]
            # refresh volatile fields, keep enrichment
            for f in ("company", "position", "connected_on", "url"):
                if c[f]:
                    old[f] = c[f]
            updated += 1
        else:
            net["contacts"].append(c)
            existing[key] = c
            added += 1
    net["meta"]["imported_at"] = date.today().isoformat()
    net["meta"]["source"] = str(p)
    save_network(net)
    return {"added": added, "updated": updated,
            "total": len(net["contacts"]), "source": str(p),
            "replaced": replace}


# ---------------------------------------------------------------------------
# enrichment (schools, past companies, tenure)
# ---------------------------------------------------------------------------

def parse_enrichment_csv(path: str | Path) -> list[dict]:
    """Parse the enrichment CSV: name,school,grad_year,prev_company,
    start_year, end_year, notes. One row per fact; several rows per person."""
    p = Path(path)
    if not p.exists():
        raise AlumniError(f"File not found: {p}")
    raw = p.read_text(encoding="utf-8-sig")
    # allow '#' comment lines at the top (as in the shipped sample)
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if not reader.fieldnames or "name" not in {f.lower() for f in reader.fieldnames}:
        raise AlumniError(
            f"{p} needs a header with at least a 'name' column. Expected: "
            "name,school,grad_year,prev_company,start_year,end_year,notes")
    rows = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        name = _get(row, "name")
        if not name:
            continue
        rows.append({
            "name": name,
            "school": _get(row, "school"),
            "grad_year": _get(row, "grad_year", "graduation_year"),
            "prev_company": _get(row, "prev_company", "past_company", "company"),
            "start_year": _get(row, "start_year"),
            "end_year": _get(row, "end_year"),
            "notes": _get(row, "notes"),
        })
    if not rows:
        raise AlumniError(f"No enrichment rows parsed from {p}.")
    return rows


def _to_year(raw: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", raw or "")
    return int(m.group(0)) if m else None


def enrich_contacts(rows: list[dict]) -> dict:
    """Merge enrichment rows into the stored network. Returns stats."""
    net = load_network()
    by_name = {norm_name(c["name"]): c for c in net["contacts"]}
    matched, unmatched, facts = 0, 0, 0
    for r in rows:
        c = by_name.get(norm_name(r["name"]))
        if c is None:
            unmatched += 1
            continue
        matched += 1
        if r["school"] and r["school"] not in c["schools"]:
            entry = r["school"]
            if r["grad_year"]:
                entry = f"{entry} ({r['grad_year']})"
            c["schools"].append(entry)
            facts += 1
        if r["prev_company"]:
            sy, ey = _to_year(r["start_year"]), _to_year(r["end_year"])
            hist = {"company": r["prev_company"],
                    "start_year": sy or 0, "end_year": ey or 0}
            if not any(companies_match(h["company"], hist["company"])
                       for h in c["history"]):
                c["history"].append(hist)
                facts += 1
        if r["notes"]:
            c["notes"] = (c["notes"] + " " + r["notes"]).strip() if c["notes"] else r["notes"]
            facts += 1
    net["meta"]["enriched_at"] = date.today().isoformat()
    save_network(net)
    return {"rows": len(rows), "matched": matched, "unmatched": unmatched,
            "facts_added": facts, "contacts": len(net["contacts"])}

# ---------------------------------------------------------------------------
# facts derived from the user's own profile
# ---------------------------------------------------------------------------

_SCHOOL_HINT = re.compile(r"\b(university|college|institute|school)\b", re.I)
_DEGREE_HINT = re.compile(
    r"\b(B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|Ph\.?D\.?|MBA|"
    r"Bachelor'?s?|Master'?s?|Doctorate)\b", re.I)


def user_schools(profile: dict) -> list[str]:
    """School names from the user's profile education entries.

    Resume parsing occasionally swaps school/degree (e.g. school="B.S.
    Statistics", degree="University of Texas at Austin"), so the degree
    field is also accepted when it clearly names an institution — and a
    school field that merely names a degree is dropped in that case.
    """
    out = []
    for e in profile.get("education", []) or []:
        school = (e.get("school") or "").strip()
        degree = (e.get("degree") or "").strip()
        degree_is_school = bool(degree) and bool(_SCHOOL_HINT.search(degree))
        if degree_is_school and degree not in out:
            out.append(degree)
        if school and school not in out:
            if degree_is_school and _DEGREE_HINT.search(school):
                continue
            out.append(school)
    return out


def user_companies(profile: dict) -> list[dict]:
    """Employers from the user's profile: [{company, current, start_year, end_year}]."""
    out = []
    for e in profile.get("experience", []) or []:
        comp = (e.get("company") or "").strip()
        if not comp or any(companies_match(comp, x["company"]) for x in out):
            continue
        dates = e.get("dates", "") or ""
        years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", dates)]
        current = bool(re.search(r"present|now|current", dates, re.I)) or not years
        out.append({"company": comp, "current": current,
                    "start_year": min(years) if years else 0,
                    "end_year": max(years) if years else 0})
    # first entry with no usable dates is most likely the current job
    if out and not any(x["current"] for x in out):
        out[0]["current"] = True
    return out


def _years_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    if not all((a_start, a_end, b_start, b_end)):
        return False
    return max(a_start, b_start) <= min(a_end, b_end)


def contact_schools(contact: dict) -> list[str]:
    """School names on a contact, without any '(grad year)' suffix."""
    return [re.sub(r"\s*\(\d{4}\)\s*$", "", s).strip()
            for s in contact.get("schools", [])]


def contact_all_companies(contact: dict) -> list[str]:
    comps = []
    if contact.get("company"):
        comps.append(contact["company"])
    for h in contact.get("history", []) or []:
        if h.get("company"):
            comps.append(h["company"])
    return comps


# ---------------------------------------------------------------------------
# overlap detectors
# ---------------------------------------------------------------------------

def school_overlap(network: dict, profile: dict) -> list[dict]:
    """Contacts sharing one of the user's schools (needs enrichment)."""
    mine = user_schools(profile)
    if not mine:
        return []
    hits = []
    for c in network.get("contacts", []):
        shared = [s for s in contact_schools(c)
                  if any(schools_match(s, m) for m in mine)]
        if shared:
            hits.append({"contact": c, "schools": sorted(set(shared))})
    hits.sort(key=lambda h: (-len(h["schools"]), h["contact"]["name"].lower()))
    return hits


def company_overlap(network: dict, profile: dict) -> list[dict]:
    """Contacts at the user's current/past employers, with tenure overlap."""
    mine = user_companies(profile)
    if not mine:
        return []
    hits = []
    for c in network.get("contacts", []):
        shared = []
        for m in mine:
            where = None
            if c.get("company") and companies_match(c["company"], m["company"]):
                where = "current"
            else:
                for h in c.get("history", []) or []:
                    if companies_match(h.get("company", ""), m["company"]):
                        where = "past"
                        break
            if where:
                overlapped = False
                span = ""
                if where == "past":
                    h = next(x for x in c["history"]
                             if companies_match(x.get("company", ""), m["company"]))
                    overlapped = _years_overlap(
                        h.get("start_year", 0), h.get("end_year", 0),
                        m["start_year"], m["end_year"])
                    if overlapped:
                        a = max(h.get("start_year", 0), m["start_year"])
                        b = min(h.get("end_year", 0), m["end_year"])
                        span = f"{a}–{b}"
                shared.append({"company": m["company"], "where": where,
                               "tenure_overlap": overlapped, "span": span,
                               "user_current": m["current"]})
        if shared:
            hits.append({"contact": c, "companies": shared})
    hits.sort(key=lambda h: (
        -sum(1 for s in h["companies"] if s["tenure_overlap"]),
        -sum(1 for s in h["companies"] if s["user_current"]),
        h["contact"]["name"].lower()))
    return hits


# ---------------------------------------------------------------------------
# seniority
# ---------------------------------------------------------------------------

def seniority_rank(title: str) -> int:
    """Map a job title to candid's seniority rank (uses config keywords).

    Takes the highest-rank keyword found; defaults to mid (2) when the
    title carries no seniority signal.
    """
    t = (title or "").lower()
    ranks = [rank for kw, rank in C.SENIORITY_KEYWORDS.items() if kw in t]
    return max(ranks) if ranks else 2


def user_seniority_rank(profile: dict) -> int:
    label = (profile.get("seniority") or "").lower()
    rev = {v.lower(): k for k, v in C.SENIORITY_LABELS.items()}
    if label in rev:
        return rev[label]
    titles = [e.get("title", "") for e in profile.get("experience", []) or []]
    ranks = [seniority_rank(t) for t in titles if t]
    return max(ranks) if ranks else 2


# ---------------------------------------------------------------------------
# warmth scoring — deterministic, every point explained
# ---------------------------------------------------------------------------

def _role_keywords(text: str) -> set[str]:
    stop = {"and", "the", "for", "with", "senior", "sr", "junior", "lead",
            "staff", "principal", "engineer", "engineering", "manager",
            "analyst", "scientist", "developer", "associate"}
    toks = {t for t in re.findall(r"[a-z]{3,}", (text or "").lower())}
    return toks - stop


def _days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return None
    return (date.today() - d).days


def last_interaction(network: dict, name: str) -> dict | None:
    key = norm_name(name)
    hits = [i for i in network.get("interactions", [])
            if norm_name(i.get("name", "")) == key and i.get("date")]
    hits.sort(key=lambda i: i["date"], reverse=True)
    return hits[0] if hits else None


def interaction_count(network: dict, name: str) -> int:
    key = norm_name(name)
    return sum(1 for i in network.get("interactions", [])
               if norm_name(i.get("name", "")) == key)


def warmth_score(contact: dict, profile: dict, target_company: str = "",
                 target_role: str = "", network: dict | None = None) -> dict:
    """Explainable 0–100 warmth score for reaching out to ``contact``.

    Signals: 1st-degree base, shared school, target-company employment,
    shared employers, tenure overlap, recency (connected or interacted),
    prior interactions, seniority proximity, role-keyword overlap.
    Returns {"score": int, "reasons": [(points, label), ...]}.
    """
    net = network or {"contacts": [], "interactions": []}
    score = 0
    reasons: list[tuple[int, str]] = []

    def add(pts: int, label: str):
        nonlocal score
        score += pts
        reasons.append((pts, label))

    add(20, "1st-degree connection")

    mine_schools = user_schools(profile)
    shared_schools = [s for s in contact_schools(contact)
                      if any(schools_match(s, m) for m in mine_schools)]
    if shared_schools:
        add(25, f"Shared school: {', '.join(sorted(set(shared_schools)))}")

    if target_company and contact.get("company") and \
            companies_match(contact["company"], target_company):
        add(20, f"Works at {target_company.strip()}")

    mine = user_companies(profile)
    shared_employers = []
    for m in mine:
        if any(companies_match(c, m["company"]) for c in contact_all_companies(contact)):
            shared_employers.append(m["company"])
    if shared_employers:
        add(15, f"Shared employer: {', '.join(sorted(set(shared_employers)))}")
        # tenure overlap at any shared employer
        for m in mine:
            for h in contact.get("history", []) or []:
                if companies_match(h.get("company", ""), m["company"]) and \
                        _years_overlap(h.get("start_year", 0), h.get("end_year", 0),
                                       m["start_year"], m["end_year"]):
                    a = max(h["start_year"], m["start_year"])
                    b = min(h["end_year"], m["end_year"])
                    add(10, f"Overlapped at {m['company']} ({a}–{b})")
                    break
            else:
                continue
            break

    dc = _days_since(contact.get("connected_on", ""))
    li = last_interaction(net, contact["name"])
    di = _days_since(li["date"]) if li else None
    if dc is not None and dc <= 365:
        add(8, f"Connected recently ({contact['connected_on'][:7]})")
    elif di is not None and di <= 90:
        add(8, f"Recent interaction ({li['date'][:10]}, {li.get('kind', 'note')})")
    n_int = interaction_count(net, contact["name"])
    if n_int:
        add(5, f"Interacted before ({n_int} logged)")

    if abs(seniority_rank(contact.get("position", "")) -
           user_seniority_rank(profile)) <= 1:
        add(5, "Similar seniority")

    if target_role:
        ck, tk = _role_keywords(contact.get("position", "")), _role_keywords(target_role)
        shared = sorted(ck & tk)
        if len(shared) >= 2:
            add(10, f"Role overlap: {', '.join(shared[:4])}")
        elif shared:
            add(5, f"Role overlap: {shared[0]}")

    return {"score": min(score, 100), "reasons": reasons}


# ---------------------------------------------------------------------------
# warm-path finder
# ---------------------------------------------------------------------------

def warm_paths(network: dict, profile: dict, target_company: str,
               target_role: str = "", limit: int = 10) -> dict:
    """Ranked warm routes into ``target_company``.

    direct: 1st-degree contacts currently there.
    bridges: 1st-degree contacts who used to work there — they can intro
    you to former colleagues. Both ranked by warmth_score.
    """
    if not (target_company or "").strip():
        raise AlumniError("warm_paths needs a target company.")
    direct, bridges = [], []
    for c in network.get("contacts", []):
        w = warmth_score(c, profile, target_company, target_role, network)
        entry = {"contact": c, "score": w["score"], "reasons": w["reasons"]}
        if c.get("company") and companies_match(c["company"], target_company):
            direct.append(entry)
        elif any(companies_match(h.get("company", ""), target_company)
                 for h in c.get("history", []) or []):
            bridges.append(entry)
    key = lambda e: (-e["score"], e["contact"]["name"].lower())
    direct.sort(key=key)
    bridges.sort(key=key)
    return {"company": target_company.strip(), "role": target_role.strip(),
            "direct": direct[:limit], "bridges": bridges[:limit],
            "total_direct": len(direct), "total_bridges": len(bridges)}

# ---------------------------------------------------------------------------
# outreach prioritization
# ---------------------------------------------------------------------------

def _tier(score: int) -> str:
    if score >= 65:
        return "this-week"
    if score >= 40:
        return "nurture"
    return "low"


def prioritize(network: dict, profile: dict,
               targets: list[tuple[str, str]] | None = None,
               limit: int = 25) -> list[dict]:
    """Rank contacts into an outreach queue.

    ``targets``: optional [(company, role)] list. With targets, each
    contact is scored against its best-fit target:
    composite = 0.5*warmth + 0.3*role_fit + 0.2*company_fit.
    Without targets, the queue is pure warmth order.
    Tiers: >=65 "this-week", >=40 "nurture", else "low".
    """
    queue = []
    for c in network.get("contacts", []):
        if targets:
            best = None
            for company, role in targets:
                w = warmth_score(c, profile, company, role, network)["score"]
                ck, tk = _role_keywords(c.get("position", "")), _role_keywords(role)
                role_fit = round(100 * len(ck & tk) / len(tk)) if tk else 50
                if c.get("company") and companies_match(c["company"], company):
                    company_fit = 100
                elif any(companies_match(h.get("company", ""), company)
                         for h in c.get("history", []) or []):
                    company_fit = 60
                else:
                    company_fit = 20
                comp = round(0.5 * w + 0.3 * role_fit + 0.2 * company_fit)
                if best is None or comp > best["score"]:
                    why = ([f"at {company.strip()}"] if company_fit == 100 else
                           ([f"ex-{company.strip()} (can bridge)"] if company_fit == 60 else []))
                    best = {"score": comp, "company": company.strip(),
                            "role": role.strip(), "why": why, "warmth": w}
            entry = {"contact": c, "score": best["score"],
                     "tier": _tier(best["score"]),
                     "target_company": best["company"], "target_role": best["role"],
                     "why": best["why"], "warmth": best["warmth"]}
        else:
            w = warmth_score(c, profile, network=network)
            entry = {"contact": c, "score": w["score"],
                     "tier": _tier(w["score"]),
                     "target_company": "", "target_role": "",
                     "why": [r[1] for r in w["reasons"][1:3]],
                     "warmth": w["score"]}
        queue.append(entry)
    queue.sort(key=lambda e: (-e["score"], e["contact"]["name"].lower()))
    return queue[:limit]


# ---------------------------------------------------------------------------
# outreach drafts — template-based, only uses facts already in the network
# ---------------------------------------------------------------------------

def _first(name: str) -> str:
    return (name or "").strip().split()[0] if name and name.strip() else "there"


def _opener(contact: dict, profile: dict) -> str:
    mine = user_schools(profile)
    shared = [s for s in contact_schools(contact)
              if any(schools_match(s, m) for m in mine)]
    if shared:
        return f"Fellow {shared[0]} alum here"
    mine_cos = [m["company"] for m in user_companies(profile)]
    for comp in contact_all_companies(contact):
        if any(companies_match(comp, m) for m in mine_cos):
            return f"Fellow ex-{comp} here"
    pos = contact.get("position") or "your work"
    comp = contact.get("company") or "your company"
    if contact.get("position") and contact.get("company"):
        return f"I noticed your work as {pos} at {comp}"
    return "I came across your profile"


def draft_outreach(contact: dict, profile: dict, kind: str = "referral",
                   target_company: str = "", target_role: str = "") -> str:
    """Draft a warm outreach message. Deterministic templates only — no
    invented facts. ``kind``: referral | info-chat | reconnect."""
    if kind not in DRAFT_KINDS:
        raise AlumniError(f"kind must be one of {DRAFT_KINDS}, got {kind!r}.")
    u_name = (profile.get("name") or "A job seeker").strip()
    u_first = _first(u_name)
    c_first = _first(contact.get("name", ""))
    opener = _opener(contact, profile)
    comp = (contact.get("company") or "").strip()
    pos = (contact.get("position") or "").strip()
    tc = target_company.strip()
    tr = target_role.strip()

    if kind == "referral":
        if not tc:
            raise AlumniError("Referral drafts need a target company.")
        role_bit = f" for the {tr} role" if tr else ""
        body = (
            f"Hi {c_first},\n\n"
            f"{opener} — I hope you're doing well! I'm exploring opportunities"
            f"{role_bit} at {tc}, and given your experience as {pos or 'a team member'}"
            f"{f' at {comp}' if comp else ''}, I'd love your perspective.\n\n"
            f"If you think I'd be a fit, would you be comfortable referring me? "
            f"Happy to share my resume and a blurb to make it easy — no worries "
            f"at all if not.\n\n"
            f"Thanks so much,\n{u_name}"
        )
    elif kind == "info-chat":
        role_bit = f" for {tr} roles" if tr else ""
        co_bit = f" at {tc}" if tc else (f" at {comp}" if comp else "")
        body = (
            f"Hi {c_first},\n\n"
            f"{opener} — I'm exploring{role_bit}{co_bit} and would love to hear "
            f"about your experience{' on the team' if co_bit else ''}. "
            f"Would you be open to a 15-minute chat sometime in the next week "
            f"or two? Happy to work around your schedule.\n\n"
            f"Thanks,\n{u_name} ({_first(u_name)} — "
            f"{(profile.get('headline') or 'job seeker').strip()})"
        )
    else:  # reconnect
        body = (
            f"Hi {c_first},\n\n"
            f"It's been a while since we connected — I hope "
            f"{f'{comp} is treating you well' if comp else 'you are doing well'}. "
            f"{opener}, and I wanted to rekindle the connection.\n\n"
            f"I'm currently {((profile.get('headline') or 'exploring new opportunities').strip())} "
            f"— would love to catch up and hear what you're working on these days. "
            f"Coffee or a quick call sometime?\n\n"
            f"Best,\n{u_first}"
        )
    return body


# ---------------------------------------------------------------------------
# coverage map
# ---------------------------------------------------------------------------

def coverage(network: dict, profile: dict, target_companies: list[str]) -> dict:
    """Per-company warm-contact coverage vs a target list, plus gaps."""
    per_company = []
    for tc in target_companies:
        tc = tc.strip()
        if not tc:
            continue
        direct = [c for c in network.get("contacts", [])
                  if c.get("company") and companies_match(c["company"], tc)]
        bridges = [c for c in network.get("contacts", [])
                   if not (c.get("company") and companies_match(c["company"], tc))
                   and any(companies_match(h.get("company", ""), tc)
                           for h in c.get("history", []) or [])]
        scored = sorted(
            (warmth_score(c, profile, tc, network=network) for c in direct),
            key=lambda w: -w["score"])
        warmest = None
        if direct:
            best_i = max(range(len(direct)), key=lambda i: scored[i]["score"])
            warmest = {"name": direct[best_i]["name"],
                       "position": direct[best_i].get("position", ""),
                       "score": scored[best_i]["score"]}
        per_company.append({"company": tc, "contacts": len(direct),
                            "bridges": len(bridges), "warmest": warmest})
    gaps = [p["company"] for p in per_company
            if p["contacts"] == 0 and p["bridges"] == 0]
    per_school = []
    for s in user_schools(profile):
        n = sum(1 for c in network.get("contacts", [])
                if any(schools_match(x, s) for x in contact_schools(c)))
        per_school.append({"school": s, "contacts": n})
    per_company.sort(key=lambda p: (-p["contacts"], -p["bridges"], p["company"].lower()))
    return {"per_company": per_company, "gaps": gaps, "per_school": per_school}


# ---------------------------------------------------------------------------
# interaction log + freshness
# ---------------------------------------------------------------------------

def log_interaction(name: str, kind: str, note: str = "",
                    when: str = "") -> dict:
    """Log an interaction with a contact (feeds freshness + warmth)."""
    if kind not in INTERACTION_KINDS:
        raise AlumniError(f"kind must be one of {INTERACTION_KINDS}, got {kind!r}.")
    net = load_network()
    if not any(norm_name(c["name"]) == norm_name(name)
               for c in net["contacts"]):
        sugg = _suggest_names(net, name)
        hint = f" Did you mean: {', '.join(sugg)}?" if sugg else ""
        raise AlumniError(f"No contact named {name!r} in the network.{hint}")
    when = when or date.today().isoformat()
    try:
        date.fromisoformat(when[:10])
    except ValueError:
        raise AlumniError(f"Bad date {when!r} — use YYYY-MM-DD.")
    rec = {"name": name.strip(), "kind": kind, "note": note.strip(),
           "date": when[:10]}
    net["interactions"].append(rec)
    save_network(net)
    return rec


def _suggest_names(network: dict, name: str, limit: int = 3) -> list[str]:
    q = norm_name(name)
    scored = []
    for c in network.get("contacts", []):
        n = norm_name(c["name"])
        if q in n or n in q:
            scored.append((0, c["name"]))
        else:
            common = len(set(q.split()) & set(n.split()))
            if common:
                scored.append((-common, c["name"]))
    scored.sort()
    return [s[1] for s in scored[:limit]]


def find_contact(network: dict, name: str) -> dict:
    """Find one contact by name; raises AlumniError with suggestions."""
    key = norm_name(name)
    for c in network.get("contacts", []):
        if norm_name(c["name"]) == key:
            return c
    sugg = _suggest_names(network, name)
    hint = f" Did you mean: {', '.join(sugg)}?" if sugg else ""
    raise AlumniError(f"No contact named {name!r} in the network.{hint}")


def freshness(network: dict, profile: dict, stale_days: int = 365,
              quiet_days: int = 180) -> list[dict]:
    """Stale-contact detector: connected long ago + no recent interaction.

    Returns the re-engagement queue, warmest first.
    """
    queue = []
    for c in network.get("contacts", []):
        dc = _days_since(c.get("connected_on", ""))
        li = last_interaction(network, c["name"])
        di = _days_since(li["date"]) if li else None
        stale = (dc is not None and dc > stale_days and
                 (li is None or (di is not None and di > quiet_days)))
        if stale:
            w = warmth_score(c, profile, network=network)
            queue.append({
                "contact": c,
                "days_since_connected": dc,
                "days_since_interaction": di,
                "last_kind": li.get("kind") if li else None,
                "warmth": w["score"],
            })
    queue.sort(key=lambda e: (-e["warmth"], e["contact"]["name"].lower()))
    return queue


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def stats(network: dict) -> dict:
    """Network overview: size, top companies/schools, growth, interactions."""
    contacts = network.get("contacts", [])
    comp_hist: dict[str, int] = {}
    comp_display: dict[str, str] = {}
    school_hist: dict[str, int] = {}
    by_year: dict[str, int] = {}
    for c in contacts:
        if c.get("company"):
            k = norm_company(c["company"])
            comp_hist[k] = comp_hist.get(k, 0) + 1
            comp_display.setdefault(k, c["company"])
        for s in contact_schools(c):
            k = norm_school(s)
            school_hist[k] = school_hist.get(k, 0) + 1
        if c.get("connected_on"):
            y = c["connected_on"][:4]
            by_year[y] = by_year.get(y, 0) + 1
    top_companies = [{"company": comp_display[k], "contacts": v}
                     for k, v in sorted(comp_hist.items(), key=lambda kv: -kv[1])[:10]]
    top_schools = [{"school": k, "contacts": v}
                   for k, v in sorted(school_hist.items(), key=lambda kv: -kv[1])[:10]]
    return {
        "total_contacts": len(contacts),
        "with_company": sum(1 for c in contacts if c.get("company")),
        "with_position": sum(1 for c in contacts if c.get("position")),
        "enriched_schools": sum(1 for c in contacts if c.get("schools")),
        "with_history": sum(1 for c in contacts if c.get("history")),
        "interactions_logged": len(network.get("interactions", [])),
        "top_companies": top_companies,
        "top_schools": top_schools,
        "connections_by_year": dict(sorted(by_year.items())),
        "imported_at": network.get("meta", {}).get("imported_at", ""),
        "enriched_at": network.get("meta", {}).get("enriched_at", ""),
    }


# ---------------------------------------------------------------------------
# render helpers (CLI text output)
# ---------------------------------------------------------------------------

def _contact_line(c: dict) -> str:
    bits = [c.get("name", "")]
    if c.get("position"):
        bits.append(c["position"])
    if c.get("company"):
        bits.append(f"@ {c['company']}")
    return " — ".join(bits)


def render_overlap(title: str, hits: list[dict], detail: str) -> str:
    lines = [f"{title}: {len(hits)} contact(s)"]
    for h in hits[:20]:
        c = h["contact"]
        d = ", ".join(
            (x if isinstance(x, str) else
             f"{x['company']} ({x['where']}" +
             (f", overlapped {x['span']}" if x.get("tenure_overlap") else "") + ")")
            for x in h[detail])
        lines.append(f"  • {_contact_line(c)}")
        lines.append(f"    ↳ {d}")
    if len(hits) > 20:
        lines.append(f"  … and {len(hits) - 20} more (use --json)")
    return "\n".join(lines)


def render_warm_paths(wp: dict) -> str:
    lines = [f"Warm paths into {wp['company']}"
             + (f" ({wp['role']})" if wp.get("role") else "")
             + f": {wp['total_direct']} direct, {wp['total_bridges']} bridges"]
    if wp["direct"]:
        lines.append("Direct (work there now):")
        for e in wp["direct"]:
            c = e["contact"]
            lines.append(f"  • {_contact_line(c)}  [warmth {e['score']}]")
            for pts, why in e["reasons"][:3]:
                lines.append(f"      +{pts} {why}")
    if wp["bridges"]:
        lines.append("Bridges (worked there before — ask for an intro):")
        for e in wp["bridges"]:
            c = e["contact"]
            lines.append(f"  • {_contact_line(c)}  [warmth {e['score']}]")
    if not wp["direct"] and not wp["bridges"]:
        lines.append("  No warm paths yet — import more connections or enrich "
                     "past employers.")
    return "\n".join(lines)


def render_queue(queue: list[dict]) -> str:
    lines = [f"Outreach queue: {len(queue)} contact(s)"]
    cur = None
    for e in queue:
        if e["tier"] != cur:
            cur = e["tier"]
            label = {"this-week": "CONTACT THIS WEEK",
                     "nurture": "NURTURE", "low": "LOW PRIORITY"}[cur]
            lines.append(f"── {label} ──")
        c = e["contact"]
        tgt = f" → {e['target_company']}" + \
              (f" ({e['target_role']})" if e.get("target_role") else "") \
              if e.get("target_company") else ""
        lines.append(f"  • {_contact_line(c)}  [score {e['score']}{tgt}]")
        if e.get("why"):
            lines.append(f"    ↳ {'; '.join(e['why'][:3])}")
    return "\n".join(lines)


def render_coverage(cov: dict) -> str:
    lines = ["Network coverage:"]
    for p in cov["per_company"]:
        w = (f", warmest: {p['warmest']['name']} "
             f"({p['warmest']['position']}, warmth {p['warmest']['score']})"
             if p["warmest"] else ", warmest: —")
        lines.append(f"  • {p['company']}: {p['contacts']} contact(s), "
                     f"{p['bridges']} bridge(s){w}")
    if cov["gaps"]:
        lines.append("Gaps (no contacts, no bridges): " + ", ".join(cov["gaps"]))
    else:
        lines.append("No gaps — every target company has a warm path.")
    if cov["per_school"]:
        lines.append("By school: " + "; ".join(
            f"{s['school']} ({s['contacts']})" for s in cov["per_school"]))
    return "\n".join(lines)


def render_freshness(queue: list[dict]) -> str:
    lines = [f"Stale contacts needing re-engagement: {len(queue)}"]
    for e in queue[:20]:
        c = e["contact"]
        last = (f"{e['days_since_interaction']}d ago ({e['last_kind']})"
                if e["days_since_interaction"] is not None else "never")
        lines.append(f"  • {_contact_line(c)}  [warmth {e['warmth']}]")
        lines.append(f"    ↳ connected {e['days_since_connected']}d ago, "
                     f"last interaction: {last}")
    if len(queue) > 20:
        lines.append(f"  … and {len(queue) - 20} more (use --json)")
    return "\n".join(lines)


def render_stats(s: dict) -> str:
    lines = [
        f"Network: {s['total_contacts']} contacts "
        f"({s['with_company']} with company, {s['with_position']} with position)",
        f"Enriched: {s['enriched_schools']} with schools, "
        f"{s['with_history']} with job history; "
        f"{s['interactions_logged']} interactions logged.",
    ]
    if s["top_companies"]:
        lines.append("Top companies: " + "; ".join(
            f"{x['company']} ({x['contacts']})" for x in s["top_companies"][:8]))
    if s["top_schools"]:
        lines.append("Top schools: " + "; ".join(
            f"{x['school']} ({x['contacts']})" for x in s["top_schools"][:8]))
    if s["connections_by_year"]:
        lines.append("Connected by year: " + ", ".join(
            f"{y}: {n}" for y, n in s["connections_by_year"].items()))
    return "\n".join(lines)
