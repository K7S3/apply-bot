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
                exclude_ids: set[str] | None = None) -> list[dict]:
    """Filter + rank raw adapter output for the requested role.

    ``days``: keep only jobs posted within the last N days (jobs with
    unparseable/missing dates are kept). ``exclude_ids``: skip jobs whose
    ``source_id`` (or ``id``) is in the set (dashboard dismiss support).
    Cross-source dupes (same normalized title+company) are collapsed,
    keeping the highest-relevance copy.
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
           min_score: float = 0) -> dict:
    """Run one curation pass.

    Returns {fetched, candidates, added, skipped, skipped_low_score, errors}.
    ``days`` filters to postings from the last N days (unparseable dates are
    kept). ``min_score`` gates tracker writes: jobs scoring below it are NOT
    added — they are stashed in jobs.json under ``skipped_low_score`` so a
    lower threshold can pick them up later.
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

    candidates = filter_jobs(raw, role, location, remote, level, limit, days=days)
    state = _load_state()
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
            sources: Optional[List[str]] = None, days: int | None = None,
            min_score: float = 0) -> dict:
    """Re-run curation; the result's ``added`` holds only genuinely new jobs."""
    return curate(profile, role, location, remote, level, limit, sources=sources,
                  days=days, min_score=min_score)


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
