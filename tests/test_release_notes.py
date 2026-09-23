"""Tests for candid.release_notes (changelog generation from git history)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_notes as RN  # noqa: E402


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path):
    repo = Path(path)
    _git(repo, "init")
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "user.name", "Tester")
    return repo


def _commit(repo, filename, content, message):
    target = Path(repo) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def test_git_log_non_git_dir_returns_empty(tmp_path):
    assert RN.git_log(tmp_path) == []


def test_git_log_parses_fields(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "hello", "feat: add widget")
    commits = RN.git_log(repo)
    assert len(commits) == 1
    commit = commits[0]
    assert len(commit["hash"]) == 40
    assert commit["author"] == "Tester"
    assert commit["subject"] == "feat: add widget"
    assert len(commit["date"]) == 10  # --date=short -> YYYY-MM-DD


def test_git_log_since_ref(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "one", "feat: first")
    _git(repo, "tag", "v0.1.0")
    _commit(repo, "b.txt", "two", "fix: second")
    assert len(RN.git_log(repo)) == 2
    assert len(RN.git_log(repo, since_ref="v0.1.0")) == 1
    assert RN.git_log(repo, since_ref="v0.1.0")[0]["subject"] == "fix: second"


def test_last_tag_none_without_tags(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "x", "feat: something")
    assert RN.last_tag(repo) is None


def test_last_tag_returns_tag(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "x", "feat: something")
    _git(repo, "tag", "v0.2.0")
    assert RN.last_tag(repo) == "v0.2.0"


def test_last_tag_non_git_dir(tmp_path):
    assert RN.last_tag(tmp_path) is None


def test_group_commits_buckets_by_prefix():
    commits = [
        {"hash": "a" * 40, "date": "2026-09-22", "author": "T", "subject": "feat: add thing"},
        {"hash": "b" * 40, "date": "2026-09-22", "author": "T", "subject": "fix: repair bug"},
        {"hash": "c" * 40, "date": "2026-09-22", "author": "T", "subject": "docs: update readme"},
        {"hash": "d" * 40, "date": "2026-09-22", "author": "T", "subject": "chore: tidy up"},
        {"hash": "e" * 40, "date": "2026-09-22", "author": "T", "subject": "mystery change"},
        {"hash": "f" * 40, "date": "2026-09-22", "author": "T", "subject": "perf: go faster"},
    ]
    groups = RN.group_commits(commits)
    assert [c["subject"] for c in groups["feat"]] == ["feat: add thing"]
    assert [c["subject"] for c in groups["fix"]] == ["fix: repair bug"]
    assert [c["subject"] for c in groups["docs"]] == ["docs: update readme"]
    assert [c["subject"] for c in groups["chore"]] == ["chore: tidy up"]
    assert groups["test"] == []
    # unknown prefix and no-colon subjects land in "other"
    assert {c["subject"] for c in groups["other"]} == {"mystery change", "perf: go faster"}


def test_generate_notes_groups_and_header(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "chore: baseline")
    _git(repo, "tag", "v0.1.0")
    _commit(repo, "a.txt", "one", "feat: add widget")
    _commit(repo, "b.txt", "two", "fix: repair widget")
    notes = RN.generate_notes(repo)
    assert "## Changes since v0.1.0" in notes
    assert "### feat" in notes
    assert "### fix" in notes
    assert "- fix: repair widget (" in notes
    short = RN.git_log(repo, since_ref="v0.1.0")[0]["hash"][:7]
    assert f"({short})" in notes
    assert "2 commit(s)" in notes
    assert "1 contributor(s)" in notes


def test_generate_notes_empty_repo(tmp_path):
    repo = _init_repo(tmp_path)
    assert RN.generate_notes(repo) == "No changes found."


def test_generate_notes_explicit_since_ref(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "one", "feat: first")
    _commit(repo, "b.txt", "two", "feat: second")
    notes = RN.generate_notes(repo, since_ref="HEAD~1")
    assert "## Changes since HEAD~1" in notes
    assert "feat: second" in notes
    assert "feat: first" not in notes


def test_write_changelog_entry_creates_file(tmp_path):
    path = RN.write_changelog_entry(tmp_path, "0.3.0", "## Changes since v0.2.0\n\n- feat: x (abc1234)\n")
    text = path.read_text()
    assert path.name == "CHANGELOG.md"
    assert text.startswith("# Changelog\n")
    assert "## [0.3.0] - " in text
    assert "- feat: x (abc1234)" in text


def test_write_changelog_entry_inserts_under_top_header(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [0.2.0] - 2026-09-01\n\nold stuff\n")
    RN.write_changelog_entry(tmp_path, "0.3.0", "new stuff")
    text = changelog.read_text()
    assert text.startswith("# Changelog\n")
    assert text.index("## [0.3.0]") < text.index("## [0.2.0]")
    assert "new stuff" in text


def test_run_checks_ok_with_commit_count(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "one", "feat: first")
    _git(repo, "tag", "v0.1.0")
    _commit(repo, "b.txt", "two", "fix: second")
    check = RN.run_checks(repo)
    assert check["name"] == "release notes generatable"
    assert check["ok"] is True
    assert "1" in check["detail"]


def test_run_checks_no_tag_counts_total(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.txt", "one", "feat: first")
    check = RN.run_checks(repo)
    assert check["ok"] is True
    assert "1" in check["detail"]


def test_run_checks_fails_outside_git(tmp_path):
    check = RN.run_checks(tmp_path)
    assert check["ok"] is False
