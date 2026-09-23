"""JD change detection: snapshots, diffs, repost detection, and alerts.

A job posting is a moving target: companies quietly edit requirements,
move the salary band, flip remote to hybrid, or repost the same role under
a new title with altered requirements. ``jdwatch`` tracks that.

Features (all local, deterministic, stdlib only):

1.  **Snapshots** — content-addressed (sha256 of normalized JD text)
    snapshot store per company+role, persisted as JSONL.
2.  **Normalization** — HTML/markdown/whitespace folding so trivial markup
    edits don't count as changes.
3.  **Change detection** — structured old-vs-new comparison: salary band,
    location, employment type, requirements, body text.
4.  **Requirement diff** — bullet/line extraction with added / removed /
    reworded requirement reporting.
5.  **Diff rendering** — human-readable unified diff of two postings.
6.  **Repost detection** — fuzzy similarity across postings finds roles that
    were reposted with altered requirements.
7.  **Severity classification** — cosmetic / minor / material with reason
    codes.
8.  **Alerts** — recorded when a tracked role's JD changes at or above a
    severity threshold; unread/read tracking, no duplicates.
9.  **Change timeline** — per-role chronological change history.
10. **Salary-band deltas** — reuses ``candid.salary.parse_posted_range`` to
    report band moves between snapshots.
11. **Digest** — markdown summary of every JD change in a time window.

Data lives in the candid data dir (``CANDID_DATA_DIR`` wins):

- ``jd_snapshots.jsonl`` — one row per snapshot
- ``jd_watch.json``     — explicitly watched company+role pairs
- ``jdwatch_alerts.jsonl`` — emitted alerts

The CLI entry point is ``python -m candid jdwatch <subcommand>``.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from candid import config as C
from candid import salary as S


class JDWatchError(Exception):
    """Raised for invalid jdwatch operations."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """Resolve the data dir at call time so CANDID_DATA_DIR always wins."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _snapshots_path() -> Path:
    return _data_dir() / "jd_snapshots.jsonl"


def _watch_path() -> Path:
    return _data_dir() / "jd_watch.json"


def _alerts_path() -> Path:
    return _data_dir() / "jdwatch_alerts.jsonl"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _role_key(company: str, role: str) -> str:
    """Stable identity for a tracked posting: normalized company + role."""
    c = " ".join(company.strip().casefold().split())
    r = " ".join(role.strip().casefold().split())
    if not c or not r:
        raise JDWatchError("Both --company and --role are required.")
    return f"{c}\x00{r}"


def _display_key(key: str) -> str:
    c, r = key.split("\x00", 1)
    return f"{c} | {r}"


# ---------------------------------------------------------------------------
# 1-2. normalization + hashing
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_MD_RE = re.compile(r"[*_`~#>|]+")
_WS_RE = re.compile(r"\s+")


def normalize_jd(text: str) -> str:
    """Fold a JD to comparable text: strip HTML/markdown, collapse whitespace.

    Case is preserved here (diffs stay readable); hashing lowercases.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TAG_RE.sub(" ", text)          # strip HTML tags
    text = _MD_RE.sub(" ", text)           # strip markdown noise
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _semantic_fold(text: str) -> str:
    """Aggressive fold for cosmetic detection: alphanumerics only, lowercase."""
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def snapshot_hash(text: str) -> str:
    """Content address of a JD: sha256 of the normalized, lowercased text."""
    return hashlib.sha256(normalize_jd(text).casefold().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 4. requirement extraction + diff
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-*•–—+>]\s+|\d{1,2}[.)]\s+)(.+)$")
_REQ_HEADING_RE = re.compile(
    r"(?i)^(requirements?|qualifications?|what\s+you('ll| will)?\s+need|"
    r"must[-\s]?haves?|nice[-\s]?to[-\s]?haves?|preferred\s+qualifications?|"
    r"you('ll| will)?\s+(bring|have)|basic\s+qualifications?)\s*:?\s*$"
)
_SECTION_END_RE = re.compile(
    r"^(?:[A-Z][A-Za-z /&'\-.]{2,60}:\s*|[A-Z][A-Z /&'\-.]{2,60})\s*$")


def extract_requirements(text: str) -> list[str]:
    """Pull requirement bullets from JD text.

    Matches explicit bullets anywhere, plus plain lines under a
    Requirements/Qualifications-style heading. Returns the raw bullet
    strings (order preserved, duplicates dropped).
    """
    reqs: list[str] = []
    seen: set[str] = set()
    in_section = False
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if in_section:
                in_section = False
            continue
        if _REQ_HEADING_RE.match(line):
            in_section = True
            continue
        bullet = _BULLET_RE.match(raw_line)
        if bullet:
            item = _WS_RE.sub(" ", bullet.group(1)).strip()
        elif in_section and len(line) > 8 and not _SECTION_END_RE.match(line):
            item = line
        else:
            if in_section and _SECTION_END_RE.match(line):
                in_section = False
            continue
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            reqs.append(item)
    return reqs


def _norm_req(item: str) -> str:
    return _WS_RE.sub(" ", item).strip().casefold()


def diff_requirements(old: list[str], new: list[str]) -> dict:
    """Line-level diff of two requirement lists.

    Returns ``{"added": [...], "removed": [...], "modified": [(old, new)]}``
    where *modified* pairs up replaced lines that are still similar
    (rewordings); dissimilar replacements become add+remove pairs.
    """
    old_n = [_norm_req(x) for x in old]
    new_n = [_norm_req(x) for x in new]
    sm = difflib.SequenceMatcher(None, old_n, new_n, autojunk=False)
    added, removed, modified = [], [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            removed.extend(old[i1:i2])
        elif tag == "insert":
            added.extend(new[j1:j2])
        else:  # replace: pair up similar lines as rewordings
            o_seg, n_seg = old[i1:i2], new[j1:j2]
            for o_item, n_item in zip(o_seg, n_seg):
                ratio = difflib.SequenceMatcher(
                    None, _norm_req(o_item), _norm_req(n_item),
                    autojunk=False).ratio()
                if ratio >= 0.6:
                    modified.append((o_item, n_item))
                else:
                    removed.append(o_item)
                    added.append(n_item)
            if len(o_seg) > len(n_seg):
                removed.extend(o_seg[len(n_seg):])
            elif len(n_seg) > len(o_seg):
                added.extend(n_seg[len(o_seg):])
    return {"added": added, "removed": removed, "modified": modified}


# ---------------------------------------------------------------------------
# 3/10. field extraction: salary band, location, employment type
# ---------------------------------------------------------------------------

_LOCATION_LINE_RE = re.compile(r"(?im)^\s*locations?\s*[:\-–]\s*(.+?)\s*$")
_WORK_MODEL_RE = re.compile(r"(?i)\b(remote(?:-first| friendly)?|hybrid|on[\s-]?site)\b")
_EMP_TYPE_RE = re.compile(
    r"(?i)\b(full[\s-]?time|part[\s-]?time|contract(?:or)?|temporary|temp\b|internship)\b")


def extract_salary_band(text: str) -> dict | None:
    """Posted pay band via the shared salary parser (annualized USD)."""
    try:
        return S.parse_posted_range(text or "")
    except Exception:
        return None


def extract_location_hint(text: str) -> str:
    """Best-effort location signal: explicit Location line, else work model."""
    text = text or ""
    m = _LOCATION_LINE_RE.search(text)
    if m:
        return _WS_RE.sub(" ", m.group(1)).strip().casefold()
    m = _WORK_MODEL_RE.search(text)
    if m:
        model = m.group(1).casefold().replace(" ", "").replace("-", "")
        if model.startswith("remote"):
            return "remote"
        if model == "hybrid":
            return "hybrid"
        return "onsite"
    return ""


def extract_employment_type(text: str) -> str:
    """Best-effort employment type: full-time / part-time / contract / ..."""
    m = _EMP_TYPE_RE.search(text or "")
    if not m:
        return ""
    t = m.group(1).casefold().replace(" ", "").replace("-", "")
    if t.startswith("full"):
        return "full-time"
    if t.startswith("part"):
        return "part-time"
    if t.startswith("contract"):
        return "contract"
    if t.startswith("intern"):
        return "internship"
    return "temporary"


# ---------------------------------------------------------------------------
# 3/7. change detection + severity classification
# ---------------------------------------------------------------------------

SEVERITIES = ("cosmetic", "minor", "material")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

MATERIAL_REASONS = {
    "salary_changed", "salary_added", "salary_removed",
    "location_changed", "employment_type_changed",
    "requirements_added", "requirements_removed",
    "body_rewritten",
}
MINOR_REASONS = {
    "requirements_reworded", "body_edited",
}


def _pct_delta(old: float, new: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _fmt_band(band: dict | None) -> str:
    """Human-readable pay band, e.g. $150,000-$180,000/yr."""
    if not band:
        return "none listed"
    lo, hi = band.get("low"), band.get("high")
    try:
        return f"${float(lo):,.0f}-${float(hi):,.0f}/yr"
    except (TypeError, ValueError):
        return str(band)


def _change_summary(change: dict) -> str:
    bits = []
    for r in change.get("reasons", []):
        if r == "salary_changed":
            f = change["fields"].get("salary", {})
            bits.append(f"salary band {_fmt_band(f.get('old'))} -> {_fmt_band(f.get('new'))}")
        elif r == "salary_added":
            bits.append("salary band added")
        elif r == "salary_removed":
            bits.append("salary band removed")
        elif r == "location_changed":
            f = change["fields"].get("location", {})
            bits.append(f"location {f.get('old')} -> {f.get('new')}")
        elif r == "employment_type_changed":
            f = change["fields"].get("employment_type", {})
            bits.append(f"employment type {f.get('old')} -> {f.get('new')}")
        elif r == "requirements_added":
            n = len(change["fields"].get("requirements_added", []))
            bits.append(f"{n} requirement(s) added")
        elif r == "requirements_removed":
            n = len(change["fields"].get("requirements_removed", []))
            bits.append(f"{n} requirement(s) removed")
        elif r == "requirements_reworded":
            bits.append("requirements reworded")
        elif r == "body_rewritten":
            bits.append("posting substantially rewritten")
        elif r == "body_edited":
            bits.append("body text edited")
        elif r == "formatting_only":
            bits.append("formatting only")
    return "; ".join(bits) or "changed"


def detect_changes(old_text: str, new_text: str) -> dict:
    """Structured old-vs-new JD comparison.

    Returns ``{"changed": bool, "severity": ..., "reasons": [...],
    "fields": {...}, "requirements": {...}, "similarity": float,
    "summary": str}``. ``changed`` is False only when the normalized texts
    are identical.
    """
    old_norm, new_norm = normalize_jd(old_text), normalize_jd(new_text)
    result: dict = {
        "changed": False, "severity": "cosmetic", "reasons": [],
        "fields": {}, "requirements": {"added": [], "removed": [], "modified": []},
        "similarity": 1.0, "summary": "no changes",
    }
    if old_norm.casefold() == new_norm.casefold():
        return result
    result["changed"] = True
    reasons: list[str] = []
    fields: dict = {}

    # cosmetic? (only markup/whitespace/punctuation-level differences)
    if _semantic_fold(old_norm) == _semantic_fold(new_norm):
        result["reasons"] = ["formatting_only"]
        result["fields"]["note"] = "Text identical after aggressive folding."
        result["summary"] = _change_summary(result)
        return result

    # salary band
    old_band, new_band = extract_salary_band(old_text), extract_salary_band(new_text)
    if old_band and new_band:
        if old_band["low"] != new_band["low"] or old_band["high"] != new_band["high"]:
            reasons.append("salary_changed")
            fields["salary"] = {
                "old": old_band, "new": new_band,
                "low_delta_pct": _pct_delta(old_band["low"], new_band["low"]),
                "high_delta_pct": _pct_delta(old_band["high"], new_band["high"]),
            }
    elif new_band and not old_band:
        reasons.append("salary_added")
        fields["salary"] = {"old": None, "new": new_band}
    elif old_band and not new_band:
        reasons.append("salary_removed")
        fields["salary"] = {"old": old_band, "new": None}

    # location
    old_loc, new_loc = extract_location_hint(old_text), extract_location_hint(new_text)
    if new_loc and old_loc != new_loc:
        reasons.append("location_changed")
        fields["location"] = {"old": old_loc or None, "new": new_loc}

    # employment type
    old_et, new_et = extract_employment_type(old_text), extract_employment_type(new_text)
    if old_et and new_et and old_et != new_et:
        reasons.append("employment_type_changed")
        fields["employment_type"] = {"old": old_et, "new": new_et}

    # requirements
    req_delta = diff_requirements(extract_requirements(old_text),
                                  extract_requirements(new_text))
    result["requirements"] = req_delta
    if req_delta["added"]:
        reasons.append("requirements_added")
        fields["requirements_added"] = req_delta["added"]
    if req_delta["removed"]:
        reasons.append("requirements_removed")
        fields["requirements_removed"] = req_delta["removed"]
    if req_delta["modified"]:
        reasons.append("requirements_reworded")
        fields["requirements_reworded"] = [
            {"old": o, "new": n} for o, n in req_delta["modified"]]

    # body similarity
    sim = difflib.SequenceMatcher(None, old_norm.casefold(),
                                  new_norm.casefold(), autojunk=False).ratio()
    result["similarity"] = round(sim, 3)
    if sim < 0.6 and (req_delta["added"] or req_delta["removed"]):
        reasons.append("body_rewritten")
    elif not reasons:
        reasons.append("body_edited")

    result["reasons"] = reasons
    result["fields"] = fields
    result["severity"] = classify_severity(reasons)
    result["summary"] = _change_summary(result)
    return result


def classify_severity(reasons: list[str]) -> str:
    """Map reason codes to cosmetic / minor / material (highest wins)."""
    rank = 0
    for r in reasons:
        if r in MATERIAL_REASONS:
            return "material"
        if r in MINOR_REASONS:
            rank = max(rank, 1)
        elif r == "formatting_only":
            rank = max(rank, 0)
    return SEVERITIES[rank] if rank else ("cosmetic" if reasons else "cosmetic")


def default_threshold() -> str:
    """Alert threshold: env CANDID_JDWATCH_THRESHOLD or 'minor'."""
    t = os.environ.get("CANDID_JDWATCH_THRESHOLD", "minor").strip().lower()
    return t if t in _SEV_RANK else "minor"


def meets_threshold(severity: str, threshold: str | None = None) -> bool:
    """True when *severity* is at or above *threshold*."""
    threshold = threshold or default_threshold()
    return _SEV_RANK.get(severity, 0) >= _SEV_RANK.get(threshold, 1)


# ---------------------------------------------------------------------------
# 5. diff rendering
# ---------------------------------------------------------------------------

def _diff_lines(text: str) -> list[str]:
    """Line structure for display diffs: raw lines, trailing space stripped,
    blank lines dropped (normalization is only for change *detection*)."""
    return [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")
            if ln.strip()]


def render_diff(old_text: str, new_text: str, *, context: int = 3,
                old_label: str = "old", new_label: str = "new") -> str:
    """Unified diff of two postings with a plain-language summary header."""
    change = detect_changes(old_text, new_text)
    lines = [f"severity: {change['severity']}"]
    if change["reasons"]:
        lines.append("reasons: " + ", ".join(change["reasons"]))
    else:
        lines.append("no changes")
        return "\n".join(lines)
    old_lines = _diff_lines(old_text) or [""]
    new_lines = _diff_lines(new_text) or [""]
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=old_label,
                                tofile=new_label, n=context, lineterm="")
    lines.append("")
    lines.extend(diff)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 1. snapshot store
# ---------------------------------------------------------------------------

def _snapshot_rows() -> list[dict]:
    return _read_jsonl(_snapshots_path())


def get_snapshots(company: str, role: str) -> list[dict]:
    """All snapshots for a posting, oldest first."""
    key = _role_key(company, role)
    return [r for r in _snapshot_rows() if r.get("key") == key]


def list_snapshot_keys() -> list[dict]:
    """One summary row per tracked posting (latest snapshot each)."""
    latest: dict[str, dict] = {}
    for r in _snapshot_rows():
        k = r.get("key", "")
        if not k or k not in latest or r.get("captured_at", "") >= latest[k].get("captured_at", ""):
            latest[k] = r
    return [
        {"key": k, "company": r.get("company", ""), "role": r.get("role", ""),
         "snapshots": sum(1 for x in _snapshot_rows() if x.get("key") == k),
         "last_captured": r.get("captured_at", ""), "sha256": r.get("sha256", "")}
        for k, r in sorted(latest.items())
    ]


def snapshot_jd(company: str, role: str, text: str, *, url: str = "",
                source: str = "", threshold: str | None = None) -> dict:
    """Capture a JD snapshot for a tracked posting.

    Returns ``{"status": "new"|"unchanged"|"changed", "key", "sha256",
    "captured_at", "change": {...}|None, "alert": {...}|None}``.
    On ``changed`` with severity at/above *threshold* an alert is recorded.
    """
    if not (text or "").strip():
        raise JDWatchError("Empty JD text: nothing to snapshot.")
    key = _role_key(company, role)
    sha = snapshot_hash(text)
    now = _utcnow()
    prev = get_snapshots(company, role)
    last = prev[-1] if prev else None

    if last and last.get("sha256") == sha:
        return {"status": "unchanged", "key": key, "sha256": sha,
                "captured_at": last.get("captured_at", now),
                "change": None, "alert": None}

    row = {"key": key, "company": company.strip(), "role": role.strip(),
           "url": url or (last.get("url", "") if last else ""),
           "source": source or (last.get("source", "") if last else ""),
           "sha256": sha, "captured_at": now, "text": text}
    _append_jsonl(_snapshots_path(), row)

    change = None
    alert = None
    if last:
        change = detect_changes(last.get("text", ""), text)
        change["old_sha256"] = last.get("sha256", "")
        change["new_sha256"] = sha
        if change["changed"] and meets_threshold(change["severity"], threshold):
            alert = record_alert(company=company.strip(), role=role.strip(),
                                 key=key, severity=change["severity"],
                                 reasons=change["reasons"],
                                 summary=_change_summary(change),
                                 old_sha=last.get("sha256", ""), new_sha=sha)
    return {"status": "new" if not last else "changed", "key": key,
            "sha256": sha, "captured_at": now,
            "change": change, "alert": alert}


# ---------------------------------------------------------------------------
# 6. repost detection
# ---------------------------------------------------------------------------

def find_reposts(company: str | None = None,
                 min_similarity: float = 0.75) -> list[dict]:
    """Find postings that look like reposts of each other.

    Compares the latest snapshot of every tracked posting pair; pairs with
    similarity in ``[min_similarity, 1.0]`` are reported, with the
    requirement delta between them so altered requirements stand out.
    """
    keys = list_snapshot_keys()
    if company:
        want = company.strip().casefold()
        keys = [k for k in keys if k["company"].strip().casefold() == want]
    latest_text: dict[str, tuple[str, str, str]] = {}
    for k in keys:
        snaps = [r for r in _snapshot_rows() if r.get("key") == k["key"]]
        if snaps:
            latest_text[k["key"]] = (k["company"], k["role"], snaps[-1].get("text", ""))
    ids = sorted(latest_text)
    out = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            ca, ra, ta = latest_text[a]
            cb, rb, tb = latest_text[b]
            sim = difflib.SequenceMatcher(
                None, normalize_jd(ta).casefold(), normalize_jd(tb).casefold(),
                autojunk=False).ratio()
            if sim < min_similarity:
                continue
            req_delta = diff_requirements(extract_requirements(ta),
                                          extract_requirements(tb))
            out.append({
                "posting_a": {"company": ca, "role": ra},
                "posting_b": {"company": cb, "role": rb},
                "similarity": round(sim, 3),
                "identical": sim >= 0.999,
                "requirements_added_in_b": req_delta["added"],
                "requirements_removed_in_b": req_delta["removed"],
                "requirements_reworded": [
                    {"old": o, "new": n} for o, n in req_delta["modified"]],
            })
    out.sort(key=lambda d: -d["similarity"])
    return out


# ---------------------------------------------------------------------------
# 8. alerts
# ---------------------------------------------------------------------------

def record_alert(*, company: str, role: str, key: str, severity: str,
                 reasons: list[str], summary: str,
                 old_sha: str, new_sha: str) -> dict:
    """Append an alert unless the identical (key, new_sha) alert exists."""
    for a in _read_jsonl(_alerts_path()):
        if a.get("key") == key and a.get("new_sha") == new_sha:
            return a  # already alerted; no duplicates
    rows = _read_jsonl(_alerts_path())
    alert = {"id": (max([a.get("id", 0) for a in rows]) + 1) if rows else 1,
             "company": company, "role": role, "key": key,
             "severity": severity, "reasons": reasons, "summary": summary,
             "old_sha": old_sha, "new_sha": new_sha,
             "captured_at": _utcnow(), "read": False}
    _append_jsonl(_alerts_path(), alert)
    return alert


def list_alerts(*, unread_only: bool = False) -> list[dict]:
    rows = _read_jsonl(_alerts_path())
    if unread_only:
        rows = [a for a in rows if not a.get("read")]
    return sorted(rows, key=lambda a: a.get("captured_at", ""), reverse=True)


def mark_alerts_read() -> int:
    """Mark every alert read. Returns the number marked."""
    path = _alerts_path()
    rows = _read_jsonl(path)
    n = 0
    for a in rows:
        if not a.get("read"):
            a["read"] = True
            n += 1
    if n:
        path.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n"
                                for a in rows), encoding="utf-8")
    return n


# ---------------------------------------------------------------------------
# 9. timeline
# ---------------------------------------------------------------------------

def timeline(company: str, role: str) -> list[dict]:
    """Chronological change history for a posting (oldest first)."""
    snaps = get_snapshots(company, role)
    events = []
    for i, s in enumerate(snaps):
        if i == 0:
            events.append({"captured_at": s.get("captured_at", ""),
                           "event": "first_seen",
                           "sha256": s.get("sha256", "")[:12],
                           "severity": None, "summary": "First snapshot captured."})
            continue
        change = detect_changes(snaps[i - 1].get("text", ""), s.get("text", ""))
        events.append({"captured_at": s.get("captured_at", ""),
                       "event": "changed" if change["changed"] else "recaptured",
                       "sha256": s.get("sha256", "")[:12],
                       "severity": change["severity"] if change["changed"] else None,
                       "reasons": change["reasons"],
                       "similarity": change["similarity"],
                       "summary": _change_summary(change)})
    return events


# ---------------------------------------------------------------------------
# 11. digest
# ---------------------------------------------------------------------------

def digest(days: int = 7) -> str:
    """Markdown digest of every JD change captured in the last *days* days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 0))
    changed: dict[str, list[dict]] = {}
    for row in _snapshot_rows():
        try:
            ts = datetime.fromisoformat(row.get("captured_at", ""))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        changed.setdefault(row.get("key", ""), []).append(row)
    lines = [f"# JD change digest — last {days} day(s)", ""]
    if not changed:
        lines.append("No JD snapshots captured in this window.")
        return "\n".join(lines) + "\n"
    for key in sorted(changed):
        snaps = sorted(changed[key], key=lambda r: r.get("captured_at", ""))
        company = snaps[-1].get("company", "")
        role = snaps[-1].get("role", "")
        lines.append(f"## {company} — {role}")
        for i, s in enumerate(snaps):
            if i == 0:
                lines.append(f"- {s.get('captured_at', '')}: first snapshot")
                continue
            ch = detect_changes(snaps[i - 1].get("text", ""), s.get("text", ""))
            sev = ch["severity"].upper() if ch["changed"] else "UNCHANGED"
            lines.append(f"- {s.get('captured_at', '')}: **{sev}** — {_change_summary(ch)}")
        lines.append("")
    alerts = [a for a in list_alerts()
              if _within(a.get("captured_at", ""), cutoff)]
    if alerts:
        lines.append(f"### Alerts emitted ({len(alerts)})")
        for a in alerts:
            lines.append(f"- [{a['severity']}] {a['company']} — {a['role']}: {a['summary']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _within(iso: str, cutoff: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


# ---------------------------------------------------------------------------
# watch list (explicitly watched postings)
# ---------------------------------------------------------------------------

def _read_watch() -> list[dict]:
    path = _watch_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_watch(rows: list[dict]) -> None:
    path = _watch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def watch(company: str, role: str) -> dict:
    """Mark a company+role as watched. Idempotent."""
    key = _role_key(company, role)
    rows = _read_watch()
    if not any(r.get("key") == key for r in rows):
        rows.append({"key": key, "company": company.strip(),
                     "role": role.strip(), "added_at": _utcnow()})
        _write_watch(rows)
        return {"watched": True, "company": company.strip(), "role": role.strip()}
    return {"watched": False, "company": company.strip(), "role": role.strip(),
            "note": "already watched"}


def unwatch(company: str, role: str) -> dict:
    key = _role_key(company, role)
    rows = _read_watch()
    kept = [r for r in rows if r.get("key") != key]
    _write_watch(kept)
    return {"unwatched": len(kept) != len(rows)}


def list_watched() -> list[dict]:
    return sorted(_read_watch(), key=lambda r: (r.get("company", ""), r.get("role", "")))
