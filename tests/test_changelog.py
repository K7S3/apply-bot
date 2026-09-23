"""Tests for candid.changelog.

Builds a throwaway git repo per test (init, config, controlled commits
with conventional prefixes, a breaking change, and non-conventional
messages), then exercises get_commits, categorization, grouping, bump
suggestion, stats, renderers, and check_against_file.

Run: python3 -m pytest tests/test_changelog.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.changelog import (  # noqa: E402
    ChangelogError,
    categorize,
    check_against_file,
    get_commits,
    group_commits,
    render_github,
    render_json,
    render_markdown,
    render_plain,
    stats,
    suggest_bump,
)


def _git(repo, *args, env=None):
    full = dict(os.environ)
    if env:
        full.update(env)
    subprocess.run(
        ["git", *args], cwd=str(repo), env=full,
        check=True, capture_output=True, text=True,
    )


def _commit(repo, message, body="", author="Alice", email="alice@example.com", day=1):
    (repo / "note.txt").write_text(f"{message}\n{day}\n")
    stamp = f"2026-01-{day:02d}T10:00:00+00:00"
    env = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    full_msg = f"{message}\n\n{body}" if body else message
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", full_msg, env=env)


@pytest.fixture()
def repo(tmp_path):
    """Repo with 12 commits; tag v0.1.0 after the first two."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _commit(r, "chore: initial project scaffold", author="Carol", day=1)
    _commit(r, "feat: add job search filters", author="Alice", day=2)
    _git(r, "tag", "v0.1.0")
    _commit(r, "fix(auth): correct token refresh bug", author="Bob", day=3)
    _commit(r, "docs: update README with install guide", author="Alice", day=4)
    _commit(r, "feat(api)!: remove legacy endpoint",
            body="BREAKING CHANGE: the /v1 endpoint is gone",
            author="Alice", day=5)
    _commit(r, "Add dark mode toggle", author="Bob", day=6)
    _commit(r, "perf: speed up matching loop", author="Alice", day=7)
    _commit(r, "refactor: cleanup tracker internals", author="Bob", day=8)
    _commit(r, "test: add tracker regression tests", author="Alice", day=9)
    _commit(r, "chore: bump pypdf from 3.0 to 3.1", author="Alice", day=10)
    _commit(r, "misc tweaks", author="Bob", day=11)
    return r


# ---------------------------------------------------------------- get_commits

def test_get_commits_default_since_uses_most_recent_tag(repo):
    commits = get_commits(repo=repo)
    # 9 commits after v0.1.0, newest first
    assert len(commits) == 9
    assert commits[0]["subject"] == "misc tweaks"
    assert commits[-1]["subject"] == "fix(auth): correct token refresh bug"
    first = commits[0]
    for key in ("sha", "short", "subject", "body", "author", "email",
                "date", "raw"):
        assert key in first, key
    assert len(first["sha"]) == 40
    assert first["date"].startswith("2026-01-11")
    assert "BREAKING CHANGE" in commits[6]["body"]
    # authors alternate as scripted
    assert commits[0]["author"] == "Bob"
    assert commits[6]["author"] == "Alice"


def test_get_commits_accepts_str_repo_and_explicit_since(repo):
    commits = get_commits(since="v0.1.0", repo=str(repo))
    assert len(commits) == 9
    assert commits[0]["subject"] == "misc tweaks"


def test_get_commits_no_tags_returns_all(tmp_path):
    r = tmp_path / "notags"
    r.mkdir()
    _git(r, "init", "-q")
    _commit(r, "feat: first thing", day=1)
    _commit(r, "fix: second thing", day=2)
    commits = get_commits(repo=r)
    assert [c["subject"] for c in commits] == ["fix: second thing",
                                              "feat: first thing"]


def test_get_commits_empty_repo_returns_empty(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    _git(r, "init", "-q")
    assert get_commits(repo=r) == []


def test_get_commits_not_a_repo_raises(tmp_path):
    with pytest.raises(ChangelogError, match="not a git repository"):
        get_commits(repo=tmp_path)


def test_get_commits_bad_since_raises(repo):
    with pytest.raises(ChangelogError):
        get_commits(since="no-such-tag-xyz", repo=repo)


# ---------------------------------------------------------------- categorize

@pytest.mark.parametrize("subject,body,expected", [
    ("feat: add job search filters", "", ("feat", False)),
    ("feat(api)!: remove legacy endpoint", "", ("feat", True)),
    ("fix(auth): correct token refresh bug", "", ("fix", False)),
    ("docs: update README", "", ("docs", False)),
    ("perf: speed up matching", "", ("perf", False)),
    ("refactor: cleanup internals", "", ("refactor", False)),
    ("test: add regression tests", "", ("test", False)),
    ("chore(deps): bump pypdf", "", ("chore", False)),
    ("wip: something random", "", ("other", False)),
    ("fix: drop bad cache", "BREAKING CHANGE: cache format v2", ("fix", True)),
    ("docs: rewrite guide", "breaking-change: new URL scheme", ("docs", True)),
    ("BREAKING: drop python 3.9", "", ("other", True)),
    ("Add dark mode toggle", "", ("feat", False)),
    ("Fix crash on startup", "", ("fix", False)),
    ("Speed up queries", "", ("perf", False)),
    ("Improve docs landing page", "", ("docs", False)),
    ("Bump actions/checkout to v4", "", ("chore", False)),
    ("Clean up temp files", "", ("refactor", False)),
    ("Add tests for tracker", "", ("feat", False)),  # feat checked before test
    ("misc tweaks", "", ("other", False)),
])
def test_categorize(subject, body, expected):
    assert categorize(subject, body) == expected


def test_categorize_breaking_case_insensitive_body():
    assert categorize("fix: x", "this is a breaking change: api v2")[1] is True


# ---------------------------------------------------------------- grouping

def test_group_commits(repo):
    groups = group_commits(get_commits(repo=repo))
    assert list(groups.keys()) == ["breaking", "feat", "fix", "perf", "docs",
                                   "refactor", "test", "chore", "other"]
    assert [e["subject"] for e in groups["breaking"]] == \
        ["feat(api)!: remove legacy endpoint"]
    # breaking commit appears ONLY under breaking
    all_subjects = [e["subject"] for k, v in groups.items() if k != "breaking"
                    for e in v]
    assert "feat(api)!: remove legacy endpoint" not in all_subjects
    assert [e["subject"] for e in groups["feat"]] == ["Add dark mode toggle"]
    assert [e["subject"] for e in groups["fix"]] == \
        ["fix(auth): correct token refresh bug"]
    assert [e["subject"] for e in groups["other"]] == ["misc tweaks"]
    entry = groups["fix"][0]
    assert set(entry.keys()) == {"short", "subject", "author"}
    assert entry["author"] == "Bob"
    assert len(entry["short"]) == 7


# ---------------------------------------------------------------- suggest_bump

def _c(subject, body=""):
    return {"subject": subject, "body": body}


def test_suggest_bump_levels():
    assert suggest_bump([_c("feat(api)!: drop v1",
                            "BREAKING CHANGE: gone")]) == "major"
    assert suggest_bump([_c("feat: new thing"),
                         _c("fix: bug")]) == "minor"
    assert suggest_bump([_c("fix: bug"), _c("docs: readme")]) == "patch"
    assert suggest_bump([_c("perf: faster")]) == "patch"
    assert suggest_bump([_c("chore: bump x")]) == "none"
    assert suggest_bump([_c("misc tweaks")]) == "none"
    assert suggest_bump([_c("chore: bump x"), _c("misc")]) == "none"
    assert suggest_bump([]) == "none"


# ---------------------------------------------------------------- stats

def test_stats(repo):
    s = stats(get_commits(repo=repo))
    assert s["total"] == 9
    assert s["by_category"]["breaking"] == 1
    assert s["by_category"]["feat"] == 1      # "Add dark mode toggle"
    assert s["by_category"]["fix"] == 1
    assert s["by_category"]["docs"] == 1
    assert s["by_category"]["perf"] == 1
    assert s["by_category"]["refactor"] == 1
    assert s["by_category"]["test"] == 1
    assert s["by_category"]["chore"] == 1
    assert s["by_category"]["other"] == 1
    assert s["authors"] == {"Alice": 5, "Bob": 4}
    assert s["first_date"].startswith("2026-01-03")
    assert s["last_date"].startswith("2026-01-11")


def test_stats_empty():
    s = stats([])
    assert s["total"] == 0
    assert s["authors"] == {}
    assert s["first_date"] is None
    assert s["last_date"] is None


# ---------------------------------------------------------------- renderers

def _render_inputs(repo):
    commits = get_commits(repo=repo)
    return group_commits(commits), stats(commits)


def test_render_markdown(repo):
    groups, s = _render_inputs(repo)
    md = render_markdown(groups, s, version="0.2.0", since="v0.1.0")
    assert md.startswith("## [0.2.0] - ")
    assert "Changes since `v0.1.0`." in md
    for section in ("### Breaking Changes", "### Features", "### Bug Fixes",
                    "### Performance", "### Documentation", "### Refactoring",
                    "### Tests", "### Chores", "### Other"):
        assert section in md, section
    assert "feat(api)!: remove legacy endpoint" in md
    assert "misc tweaks" in md
    assert "### Stats" in md
    assert "9 commits" in md


def test_render_markdown_skips_empty_sections_and_unreleased(repo):
    groups, s = _render_inputs(repo)
    only_chore = {k: (v if k == "chore" else []) for k, v in groups.items()}
    md = render_markdown(only_chore, s)
    assert md.startswith("## Unreleased")
    assert "### Chores" in md
    assert "### Features" not in md
    assert "### Breaking Changes" not in md


def test_render_markdown_no_stats(repo):
    groups, _ = _render_inputs(repo)
    md = render_markdown(groups, None, include_stats=False)
    assert "### Stats" not in md


def test_render_plain(repo):
    groups, s = _render_inputs(repo)
    text = render_plain(groups, s, version="0.2.0")
    assert text.startswith("Changelog - 0.2.0")
    assert "BREAKING CHANGES" in text
    assert "BUG FIXES" in text
    assert "###" not in text  # no markdown syntax
    assert "feat(api)!: remove legacy endpoint" in text


def test_render_github(repo):
    groups, s = _render_inputs(repo)
    body = render_github(groups, s, version="0.2.0", since="v0.1.0",
                         repo_url="https://github.com/K7S3/candid")
    assert body.startswith("## What's Changed")
    assert "### Breaking Changes" in body
    assert "feat(api)!: remove legacy endpoint" in body
    assert ("**Full Changelog**: "
            "https://github.com/K7S3/candid/compare/v0.1.0...0.2.0") in body


def test_render_github_no_compare_line_without_repo_url(repo):
    groups, s = _render_inputs(repo)
    body = render_github(groups, s, version="0.2.0", since="v0.1.0")
    assert "Full Changelog" not in body


def test_render_json(repo):
    groups, s = _render_inputs(repo)
    payload = json.loads(render_json(groups, s, version="0.2.0",
                                     since="v0.1.0"))
    assert payload["version"] == "0.2.0"
    assert payload["since"] == "v0.1.0"
    assert payload["stats"]["total"] == 9
    assert [e["subject"] for e in payload["groups"]["breaking"]] == \
        ["feat(api)!: remove legacy endpoint"]
    assert set(payload["groups"].keys()) == {"breaking", "feat", "fix",
                                             "perf", "docs", "refactor",
                                             "test", "chore", "other"}


# ---------------------------------------------------------------- check_against_file

_CHANGELOG = """# Changelog

## [0.2.0] - 2026-09-01

### Features

- Add dark mode toggle (`abc1234`) - Bob

### Bug Fixes

- fix(auth): correct token refresh bug (`def5678`) - Bob

## [0.1.0] - 2026-01-02

### Chores

- chore: initial project scaffold (`1111111`) - Carol
"""


def test_check_against_file_ok(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG)
    generated = [
        {"subject": "Add dark mode toggle"},
        {"subject": "fix(auth): correct token refresh bug"},
    ]
    ok, missing = check_against_file(path, generated)
    assert ok is True
    assert missing == []


def test_check_against_file_missing(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG)
    generated = [
        {"subject": "Add dark mode toggle"},
        {"subject": "feat(api)!: remove legacy endpoint"},
    ]
    ok, missing = check_against_file(path, generated)
    assert ok is False
    assert missing == ["feat(api)!: remove legacy endpoint"]


def test_check_against_file_accepts_groups_dict(repo, tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG)
    groups = group_commits(get_commits(repo=repo))
    ok, missing = check_against_file(path, groups)
    assert ok is False
    # only the two subjects present in the first section are found
    assert "misc tweaks" in missing
    assert "Add dark mode toggle" not in missing
    assert "fix(auth): correct token refresh bug" not in missing


def test_check_against_file_ignores_later_sections(tmp_path):
    # "chore: initial project scaffold" is in the second section only
    path = tmp_path / "CHANGELOG.md"
    path.write_text(_CHANGELOG)
    ok, missing = check_against_file(
        path, [{"subject": "chore: initial project scaffold"}])
    assert ok is False
    assert missing == ["chore: initial project scaffold"]
