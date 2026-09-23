"""GitHub project matcher: fetch the user's PUBLIC repos and match them to JDs.

Uses the no-key GitHub public API
(https://api.github.com/users/{user}/repos). Keyword extraction covers
repo names, descriptions, topics, and languages. Results are cached in the
git-ignored user data dir; a stale cache is reused gracefully when offline.

Matching is keyword-overlap ONLY and is always labeled as such — candid
never claims a project demonstrates a skill it doesn't. The repo's own
name/description/topics are the only facts ever cited.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C

API_BASE = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 5  # 500 repos is plenty for matching purposes
CACHE_TTL_SECONDS = 24 * 3600


class GithubError(Exception):
    """Raised when GitHub projects can't be fetched and no cache exists."""


# ---------------------------------------------------------------------------
# fetching + cache
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _validate_username(username: str) -> str:
    u = (username or "").strip()
    if not u or not _USERNAME_RE.match(u):
        raise GithubError(
            f"'{username}' doesn't look like a GitHub username.\n"
            "Next: run `python -m candid profile github --help`."
        )
    return u


def _api_request(url: str, timeout: int) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "candid/0.2 (+https://github.com/K7S3/candid)",
            "Accept": "application/vnd.github+json, "
                      "application/vnd.github.mercy-preview+json",
        },
    )


def fetch_repos(username: str, timeout: int = 25,
                max_pages: int = MAX_PAGES) -> list[dict]:
    """Fetch public repos for ``username`` from the no-key GitHub API.

    Raises GithubError on network/API failures (callers may fall back to
    the cache via fetch_or_cached).
    """
    user = _validate_username(username)
    repos: list[dict] = []
    for page in range(1, max_pages + 1):
        url = (f"{API_BASE}/users/{urllib.parse.quote(user)}"
               f"/repos?per_page={PER_PAGE}&page={page}"
               f"&type=owner&sort=updated&direction=desc")
        try:
            with urllib.request.urlopen(_api_request(url, timeout),
                                        timeout=timeout) as resp:
                if resp.status == 404:
                    raise GithubError(
                        f"GitHub user '{user}' not found (404). "
                        "Check the spelling.\n"
                        "Next: run `python -m candid profile github --help`."
                    )
                if resp.status == 403:
                    raise GithubError(
                        f"GitHub rate-limited this IP (403). "
                        "Wait a few minutes and retry with the same command — "
                        "the cache from this run is kept.\n"
                        "Next: run `python -m candid profile github --help`."
                    )
                if resp.status != 200:
                    raise GithubError(
                        f"GitHub API returned HTTP {resp.status}.\n"
                        "Next: run `python -m candid profile github --help`."
                    )
                page_repos = json.loads(resp.read().decode("utf-8"))
        except GithubError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GithubError(
                    f"GitHub user '{user}' not found (404). Check the spelling.\n"
                    "Next: run `python -m candid profile github --help`."
                ) from exc
            if exc.code == 403:
                raise GithubError(
                    "GitHub rate-limited this IP (403). Wait a few minutes and "
                    "retry — the cache from this run is kept.\n"
                    "Next: run `python -m candid profile github --help`."
                ) from exc
            raise GithubError(
                f"GitHub API error (HTTP {exc.code}).\n"
                "Next: run `python -m candid profile github --help`."
            ) from exc
        except Exception as exc:  # URLError, timeouts, JSON decode
            raise GithubError(
                f"Could not reach the GitHub API: {exc}.\n"
                "Next: run `python -m candid profile github --help`."
            ) from exc
        if not page_repos:
            break
        repos.extend(page_repos)
        if len(page_repos) < PER_PAGE:
            break
    return repos


def cache_path() -> Path:
    return C.DATA_DIR / "github_projects.json"


def save_cache(username: str, repos: list[dict]) -> Path:
    """Write the fetched repos (simplified) to the local cache."""
    C.ensure_data_dirs()
    payload = {
        "username": username,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "repos": [simplify_repo(r) for r in repos],
    }
    path = cache_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_cache() -> dict | None:
    """Return the cached payload, or None when there is no cache."""
    path = cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "repos" not in payload:
        return None
    return payload


def cache_age_seconds(payload: dict) -> float | None:
    try:
        fetched = datetime.fromisoformat(payload.get("fetched_at", ""))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds()


def fetch_or_cached(username: str, refresh: bool = False,
                    timeout: int = 25) -> tuple[list[dict], str]:
    """Fetch repos, honoring the cache.

    Returns (repos, source) where source is one of:
      "api"           — fresh from the GitHub API (cache rewritten)
      "cache"         — fresh-enough cache, no network call made
      "cache-stale"   — network failed, fell back to an old cache
    Raises GithubError when neither the network nor a cache is available.
    """
    user = _validate_username(username)
    cached = load_cache()
    if not refresh and cached and cached.get("username", "").lower() == user.lower():
        age = cache_age_seconds(cached)
        if age is not None and age < CACHE_TTL_SECONDS:
            return cached["repos"], "cache"
    try:
        repos = fetch_repos(user, timeout=timeout)
    except GithubError as exc:
        if cached and cached.get("username", "").lower() == user.lower():
            return cached["repos"], "cache-stale"
        raise GithubError(
            f"{exc}\nNo cached projects for '{user}' to fall back on."
        ) from exc
    save_cache(user, repos)
    return [simplify_repo(r) for r in repos], "api"


# ---------------------------------------------------------------------------
# keyword extraction + JD matching
# ---------------------------------------------------------------------------

_COMMON_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with",
    "by", "from", "as", "at", "is", "are", "be", "this", "that", "it",
    "my", "your", "our", "using", "use", "used", "built", "build", "based",
    "simple", "small", "project", "projects", "app", "tool", "tools",
    "library", "framework", "demo", "example", "examples", "test", "tests",
    "testing", "code", "repo", "repository", "awesome", "personal", "new",
    "old", "one", "two", "first", "final", "version", "v1", "v2",
}


def simplify_repo(repo: dict) -> dict:
    """Keep only the fields the matcher needs."""
    topics = repo.get("topics") or []
    language = (repo.get("language") or "").strip()
    return {
        "name": repo.get("name") or "",
        "full_name": repo.get("full_name") or "",
        "description": (repo.get("description") or "").strip(),
        "url": repo.get("html_url") or "",
        "language": language,
        "topics": [str(t).lower() for t in topics if t],
        "stars": int(repo.get("stargazers_count") or 0),
        "updated_at": (repo.get("updated_at") or "")[:10],
    }


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#]*")


def repo_keywords(repo: dict) -> set[str]:
    """Keyword set for a repo: name tokens, description words, topics, language.

    Only the repo's own metadata — never invented. Hyphenated names are
    split ("k8s-deploy-helper" -> k8s, deploy, helper).
    """
    kws: set[str] = set()
    name_bits = re.split(r"[-_]+", (repo.get("name") or "").lower())
    for token in name_bits:
        token = token.strip()
        if len(token) >= 2 and token not in _COMMON_WORDS:
            kws.add(token)
    for token in _TOKEN_RE.findall((repo.get("description") or "").lower()):
        if len(token) >= 3 and token not in _COMMON_WORDS:
            kws.add(token)
    for topic in repo.get("topics", []):
        t = str(topic).lower().strip()
        if t:
            kws.add(t)
    lang = (repo.get("language") or "").lower().strip()
    if lang:
        kws.add(lang)
    return kws


def _jd_tokens(jd: str) -> set[str]:
    from candid.match import _STOPWORDS
    from candid import skills as SK
    toks = set()
    for token in _TOKEN_RE.findall((jd or "").lower()):
        if len(token) >= 3 and token not in _COMMON_WORDS and token not in _STOPWORDS:
            toks.add(token)
    # short tech tokens (py, js, ts) still count when they are known aliases;
    # plain 2-letter English words ("go", "do", "us") must NOT match.
    for token in _TOKEN_RE.findall((jd or "").lower()):
        if 2 <= len(token) < 3 and token not in _COMMON_WORDS \
                and SK.canonical(token) != token:
            toks.add(token)
    return toks


def keyword_overlap(repo: dict, jd: str) -> set[str]:
    """Shared keywords between the repo's metadata and the JD (alias-aware).

    Returns the repo's own keywords (readable in reports); matching is done
    on canonical forms, so JD "k8s" overlaps repo topic "kubernetes".
    """
    from candid import skills as SK
    jd_canon = {SK.canonical(t) for t in _jd_tokens(jd)}
    return {k for k in repo_keywords(repo) if SK.canonical(k) in jd_canon}


def best_project_for_jd(repos: list[dict], jd: str) -> dict | None:
    """The repo with the most JD keyword overlap, or None when no overlap.

    Returns {"repo": simplified repo dict, "overlap": sorted keyword list}.
    Ties break toward more stars. Pure keyword overlap — labeled as such
    everywhere it is shown.
    """
    best: dict | None = None
    best_overlap: set[str] = set()
    best_stars = -1
    for repo in repos or []:
        ov = keyword_overlap(repo, jd)
        stars = int(repo.get("stars") or 0)
        if ov and (len(ov) > len(best_overlap)
                   or (len(ov) == len(best_overlap) and stars > best_stars)):
            best, best_overlap, best_stars = repo, ov, stars
    if best is None:
        return None
    return {"repo": best, "overlap": sorted(best_overlap)}


# ---------------------------------------------------------------------------
# profile storage + rendering
# ---------------------------------------------------------------------------

def store_in_profile(username: str, repos: list[dict],
                     profile: dict | None = None) -> dict:
    """Store simplified repos (+precomputed keywords) in the user profile."""
    from candid import profile as P
    prof = profile if profile is not None else P.load_profile()
    prof["github_user"] = username
    prof["github_projects"] = [
        {**r, "keywords": sorted(repo_keywords(r))} for r in repos
    ]
    prof["github_fetched_at"] = datetime.now(timezone.utc).isoformat()
    C.ensure_data_dirs()
    C.PROFILE_PATH.write_text(json.dumps(prof, indent=2), encoding="utf-8")
    return prof


def render_projects(repos: list[dict], limit: int = 10) -> str:
    """Short summary of fetched repos for the CLI."""
    if not repos:
        return "No public repos found for this user."
    lines = []
    shown = repos[:limit]
    for r in shown:
        name = r.get("name") or r.get("full_name") or "(unnamed)"
        lang = r.get("language") or "?"
        desc = (r.get("description") or "").strip()
        if len(desc) > 70:
            desc = desc[:67] + "..."
        bits = f"{name} [{lang}]"
        if desc:
            bits += f" — {desc}"
        lines.append("  " + bits)
    if len(repos) > limit:
        lines.append(f"  ... and {len(repos) - limit} more")
    return "\n".join(lines)
