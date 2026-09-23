"""Portfolio project descriptions from OFFLINE GitHub repo metadata.

The input is repo metadata the user supplies (a repos.json export, a
copy-paste, whatever) — this module makes NO network calls and reads no
live GitHub data. A future online fetcher can plug in here: it would
produce the same dict shape that ``load_repos`` reads. (Batch-3's GitHub
work may add such a fetcher; this module stays offline regardless.)

Repo dict shape:
{
  "name": str,                 # required
  "description": str,          # short repo description (may be "")
  "language": str,             # primary language (may be "")
  "topics": [str, ...],        # GitHub topics (may be [])
  "stars": int, "forks": int,  # (may be 0)
  "readme_excerpt": str,       # first lines of the README (may be "")
  "url": str,                  # repo URL (may be "")
}

GROUND RULE: ``describe_repo`` derives everything from the supplied
metadata only. If the README excerpt is missing it says so and produces
a thinner description; it never invents tech stacks, features, or
achievements that are not in the metadata.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class PortfolioError(Exception):
    """Raised when repo metadata cannot be read or is invalid."""


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_repos(path: str | Path) -> list[dict]:
    """Read a repos.json file (a JSON list of repo dicts) into memory.

    Raises PortfolioError if the file is missing, not valid JSON, not a
    list, or any entry lacks a ``name``.
    """
    p = Path(path)
    if not p.exists():
        raise PortfolioError(f"File not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PortfolioError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PortfolioError(f"{p} must contain a JSON list of repos, not {type(data).__name__}.")
    return [_validate_repo(entry, i) for i, entry in enumerate(data)]


def _validate_repo(entry: object, index: int) -> dict:
    if not isinstance(entry, dict):
        raise PortfolioError(f"Repo at index {index} is not an object.")
    if not (entry.get("name") or "").strip():
        raise PortfolioError(f"Repo at index {index} has no 'name'.")
    return {
        "name": str(entry.get("name")).strip(),
        "description": str(entry.get("description") or "").strip(),
        "language": str(entry.get("language") or "").strip(),
        "topics": [str(t).strip() for t in (entry.get("topics") or []) if str(t).strip()],
        "stars": int(entry.get("stars") or 0),
        "forks": int(entry.get("forks") or 0),
        "readme_excerpt": str(entry.get("readme_excerpt") or "").strip(),
        "url": str(entry.get("url") or "").strip(),
    }


def describe_single(name: str, **fields) -> dict:
    """Convenience: describe one repo supplied as keyword arguments.

    Example:
        describe_single("candid", language="Python",
                        description="job-search copilot",
                        topics=["cli", "jobs"])
    """
    return describe_repo({"name": name, **fields})


# ---------------------------------------------------------------------------
# describing
# ---------------------------------------------------------------------------

def _first_sentence(text: str, limit: int = 200) -> str:
    """Trim text to its first sentence (or ``limit`` chars)."""
    text = " ".join(text.split())
    for sep in (". ", ".\n", "!", "?", " | "):
        if sep in text:
            text = text.split(sep, 1)[0].rstrip(".!?")
            break
    text = text.strip().rstrip(".")
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut if cut else text[:limit]
    return text


def _stack_line(repo: dict) -> str:
    parts = []
    if repo["language"]:
        parts.append(repo["language"])
    parts.extend(t for t in repo["topics"] if t.lower() != repo["language"].lower())
    return ", ".join(parts)


def _sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ? boundaries."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s.strip()]


def describe_repo(repo: dict) -> dict:
    """Write a polished headline plus 2-4 resume-ready bullets from metadata.

    Everything returned is derived ONLY from the repo dict. When
    ``readme_excerpt`` is missing, ``missing_readme`` is True and the
    description is explicitly thinner instead of invented.
    """
    repo = _validate_repo(repo, 0)  # idempotent: also normalizes ad-hoc dicts
    name = repo["name"]
    description = repo["description"]
    readme = repo["readme_excerpt"]
    url = repo["url"]

    # --- headline: 1-2 lines -------------------------------------------------
    stack = _stack_line(repo)
    if description:
        headline = f"{name} - {description}"
    elif readme:
        headline = f"{name} - {_first_sentence(readme)}"
    else:
        headline = name
    if stack:
        headline += f"  [{stack}]"

    # --- bullets: only what the metadata evidences -------------------------
    bullets: list[str] = []
    desc_lead = _first_sentence(description, 220) if description else ""
    if desc_lead:
        bullets.append(f"{desc_lead}.")
    elif readme:
        bullets.append(f"{_first_sentence(readme, 220)}.")
    if stack:
        bullets.append(f"Built with {stack}.")
    if readme:
        # One more README detail, only if it adds something genuinely new.
        for sentence in _sentences(readme)[1:]:
            detail = _first_sentence(sentence, 160)
            joined = " ".join(bullets).lower()
            if detail and detail.lower() not in joined and len(detail.split()) >= 4:
                bullets.append(f"{detail}.")
                break
    if repo["stars"] or repo["forks"]:
        bullets.append(f"{repo['stars']} stars, {repo['forks']} forks on GitHub.")
    while len(bullets) < 2:
        # Never invent content to fill the quota: state the limitation.
        bullets.append(f"Repo URL: {url or name} - add a one-line note about what it does.")

    missing_readme = not bool(readme)
    caveat = None
    if missing_readme:
        caveat = (
            f"No README excerpt was supplied for '{name}', so this description "
            "is based on the repo's short description, language, and topics only. "
            "Paste the README excerpt into repos.json to get a richer write-up."
        )

    return {
        "name": name,
        "url": url,
        "headline": headline,
        "bullets": bullets[:4],
        "topics_used": repo["topics"],
        "missing_readme": missing_readme,
        "caveat": caveat,
    }


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

def _skill_aliases(profile_skills: list[str]) -> dict[str, list[str]]:
    """Canonical profile skill -> list of match strings (lexicon + itself)."""
    from candid import config as C
    out: dict[str, list[str]] = {}
    for skill in profile_skills:
        aliases = list(C.SKILL_LEXICON.get(skill, []))
        if skill not in aliases:
            aliases.append(skill)
        out[skill] = aliases
    return out


def rank_repos(repos: list[dict], profile_skills: list[str]) -> list[dict]:
    """Rank repos by overlap between repo metadata and profile skills.

    A skill counts once per repo no matter how many times its aliases
    appear. Ties break on stars, then forks, then name. Returns copies of
    the repo dicts with a ``match_score`` key added; never mutates input.
    """
    from candid import config as C

    aliases = _skill_aliases(profile_skills or [])

    ranked = []
    for repo in repos:
        haystack = " ".join([
            repo.get("name", ""), repo.get("description", ""),
            repo.get("language", ""), " ".join(repo.get("topics") or []),
            repo.get("readme_excerpt", ""),
        ]).lower()
        matched = [
            skill for skill, words in aliases.items()
            if any(C.skill_regex(w).search(haystack) for w in words)
        ]
        copy = dict(repo)
        copy["match_score"] = len(matched)
        copy["matched_skills"] = sorted(matched)
        ranked.append(copy)

    ranked.sort(key=lambda r: (-r["match_score"],
                               -(r.get("stars") or 0),
                               -(r.get("forks") or 0),
                               str(r.get("name", ""))))
    return ranked


# ---------------------------------------------------------------------------
# resume section
# ---------------------------------------------------------------------------

def portfolio_section(repos: list[dict], top_n: int = 4) -> str:
    """Render a markdown 'Projects' section ready to paste into a resume.

    Takes repos in the order given (call ``rank_repos`` first to put the
    most relevant projects on top) and describes each with ``describe_repo``.
    Repos with a missing README excerpt get a slim, honest description plus
    an HTML-comment reminder that is invisible in the rendered resume but
    visible to the user editing the markdown.
    """
    chosen = list(repos)[:max(1, top_n)]
    lines = ["## Projects", ""]
    for repo in chosen:
        d = describe_repo(repo)
        title = f"**{d['name']}**"
        if d["url"]:
            title += f" ([{d['url']}]({d['url']}))"
        lines.append(f"{title} - {d['headline']}")
        for b in d["bullets"]:
            lines.append(f"- {b}")
        if d["missing_readme"]:
            lines.append(
                f"<!-- portfolio: '{d['name']}' has no README excerpt; "
                "add one to repos.json for a richer description -->"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
