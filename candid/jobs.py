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

import json
import re
import urllib.request
from datetime import datetime
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


# ---------------------------------------------------------------------------
# filtering / ranking / scoring
# ---------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", (s or "").lower()))


def _relevance(job: dict, role_terms: set[str]) -> float:
    """Keyword relevance of a job to the wanted role (title counts 3x)."""
    title_toks, desc_toks = _tokens(job["title"]), _tokens(job["description"])
    overlap = role_terms & title_toks
    score = 3.0 * len(overlap)
    score += 1.0 * len(role_terms & desc_toks - overlap)
    # small bonus for seniority-signal words matching the requested level is
    # applied by the caller; here just avoid empty titles
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


def _location_ok(job: dict, location: str, remote: bool) -> bool:
    if remote:
        return job["remote"] or "remote" in job["location"].lower()
    if not location:
        return True
    # A named-location search must actually mention the location; remote
    # postings only qualify when the user asked for remote (or no location).
    return location.lower() in job["location"].lower()


def filter_jobs(jobs: list[dict], role: str, location: str = "",
                remote: bool = False, level: str | None = None,
                limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Filter + rank raw adapter output for the requested role."""
    role_terms = _tokens(role) - {"a", "the", "and", "for"}
    ranked = []
    for job in jobs:
        if not _level_ok(job["title"], level):
            continue
        if not _location_ok(job, location, remote):
            continue
        rel = _relevance(job, role_terms)
        if rel <= 0:
            continue
        ranked.append((rel, job))
    ranked.sort(key=lambda x: -x[0])
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


def _already_tracked(company: str, role: str) -> dict | None:
    from candid import tracker as T
    for a in T.list_apps():
        if (a["company"].strip().lower() == company.strip().lower()
                and a["role"].strip().lower() == role.strip().lower()):
            return a
    return None


def curate(profile: dict, role: str, location: str = "", remote: bool = False,
           level: str | None = None, limit: int = DEFAULT_LIMIT,
           sources: list[str] | None = None) -> dict:
    """Run one curation pass. Returns {fetched, candidates, added, skipped, errors}."""
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

    candidates = filter_jobs(raw, role, location, remote, level, limit)
    state = _load_state()
    seen: dict = state.get("seen", {})

    added, skipped = [], []
    for job in candidates:
        if job["source_id"] in seen or _already_tracked(job["company"], job["title"]):
            skipped.append(job)
            continue
        scored = score_job(profile, job)
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
        # attach curation metadata for the downstream flow
        T.update(rec["id"], notes=notes)
        rec.update({"source": job["source"], "source_url": job["url"],
                    "match_score": scored["score"], "jd_text": job["description"][:4000]})
        _stash_job_meta(rec["id"], rec)
        seen[job["source_id"]] = rec["id"]
        added.append({**job, **scored, "app_id": rec["id"]})

    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    state["seen"] = seen
    _save_state(state)
    return {"fetched": len(raw), "candidates": len(candidates),
            "added": added, "skipped": len(skipped), "errors": errors}


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
            sources: Optional[List[str]] = None) -> dict:
    """Re-run curation; the result's ``added`` holds only genuinely new jobs."""
    return curate(profile, role, location, remote, level, limit, sources=sources)


def render_curated(result: dict) -> str:
    lines = [
        f"Fetched {result['fetched']} postings → {result['candidates']} relevant candidates."
    ]
    if result["errors"]:
        lines += ["Source errors:"] + [f"  ⚠️ {e}" for e in result["errors"]]
    if result["added"]:
        lines.append(f"\n✅ {len(result['added'])} new → tracker (status: saved):")
        for j in result["added"]:
            lines.append(f"  [#{j['app_id']}] {j['title']} @ {j['company']} "
                         f"({j['location']}) — {j['score']}/100 [{j['source']}]")
            if j["url"]:
                lines.append(f"      apply: {j['url']}")
    else:
        lines.append("\nNo new jobs since last run.")
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
