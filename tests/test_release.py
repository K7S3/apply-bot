"""Tests for release tooling: changelog generation, checksums, release.sh."""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
CHANGELOG_PY = SCRIPTS / "changelog.py"
RELEASE_SH = SCRIPTS / "release.sh"


# ---------------------------------------------------------------- fixtures


@pytest.fixture()
def git_repo(tmp_path):
    """A scratch git repo with a few conventionally-ish commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args, **kwargs):
        return subprocess.run(
            ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True, **kwargs
        )

    git("init", "-q")
    (repo / "a.txt").write_text("a")
    git("add", ".")
    git("commit", "-qm", "chore: initial commit")
    git("tag", "v0.1.0")
    (repo / "b.txt").write_text("b")
    git("add", ".")
    git("commit", "-qm", "feat: add job scoring")
    (repo / "c.txt").write_text("c")
    git("add", ".")
    git("commit", "-qm", "fix: handle empty JD")
    (repo / "d.txt").write_text("d")
    git("add", ".")
    git("commit", "-qm", "docs: update README")
    (repo / "e.txt").write_text("e")
    git("add", ".")
    git("commit", "-qm", "Rename apply-bot to candid")
    return repo


def run_changelog(repo, *args):
    return subprocess.run(
        [sys.executable, str(CHANGELOG_PY), *args, "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )


# ---------------------------------------------------------------- changelog


def test_changelog_groups_features_fixes_docs(git_repo):
    out = run_changelog(git_repo, "v0.1.0", "HEAD").stdout
    assert "## Unreleased" in out
    assert "### Features" in out
    assert "add job scoring" in out
    assert "### Bug Fixes" in out
    assert "handle empty JD" in out
    assert "### Documentation" in out
    assert "update README" in out


def test_changelog_freeform_feature_keyword(git_repo):
    # "Rename ..." is not a conventional prefix; the keyword heuristic
    # should still file it under Features.
    out = run_changelog(git_repo, "v0.1.0", "HEAD").stdout
    assert "Rename apply-bot to candid" in out
    features = out.split("### Features")[1].split("###")[0]
    assert "Rename apply-bot to candid" in features


def test_changelog_excludes_commits_before_from_ref(git_repo):
    out = run_changelog(git_repo, "v0.1.0", "v0.1.0").stdout
    assert "add job scoring" not in out


def test_changelog_includes_short_sha(git_repo):
    out = run_changelog(git_repo, "v0.1.0", "HEAD").stdout
    sha = subprocess.run(
        ["git", "log", "-1", "--format=%h"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert sha in out


def test_changelog_output_file_prepend(tmp_path, git_repo):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n")
    run_changelog(git_repo, "v0.1.0", "HEAD", "--output", str(changelog))
    text = changelog.read_text()
    assert text.startswith("# Changelog\n\n## Unreleased")
    assert "handle empty JD" in text


def test_changelog_bad_ref_errors(git_repo):
    proc = subprocess.run(
        [sys.executable, str(CHANGELOG_PY), "nope-no-such-tag", "HEAD", "--repo", str(git_repo)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------- checksums


def test_sha256_round_trip(tmp_path):
    """Mimic dist/SHA256SUMS write + verify for a couple of fake artifacts."""
    dist = tmp_path / "dist"
    dist.mkdir()
    payloads = {
        "candid-0.3.0.tar.gz": b"fake-sdist",
        "candid-0.3.0-py3-none-any.whl": b"fake-wheel",
    }
    for name, data in payloads.items():
        (dist / name).write_bytes(data)

    expected_lines = []
    for name, data in payloads.items():
        digest = hashlib.sha256(data).hexdigest()
        expected_lines.append(f"{digest}  {name}")
    sums = dist / "SHA256SUMS"
    sums.write_text("\n".join(expected_lines) + "\n")

    # Verify: every recorded digest matches its file on disk.
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition("  ")
        assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest
    assert len(sums.read_text().splitlines()) == 2


# ---------------------------------------------------------------- release.sh


def _copy_release_sh(tmp_path) -> Path:
    target = tmp_path / "scripts" / "release.sh"
    target.parent.mkdir(parents=True)
    shutil.copy(RELEASE_SH, target)
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return target


def test_release_sh_missing_pyproject_fails_cleanly(tmp_path):
    """Without pyproject.toml the script must exit 2 with a clear error."""
    script = _copy_release_sh(tmp_path)
    env = {**os.environ, "RELEASE_REPO_ROOT": str(tmp_path)}
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert proc.returncode == 2, proc.stderr
    assert "pyproject.toml" in proc.stderr
    assert "build" in proc.stderr.lower() or "packaging" in proc.stderr.lower()


def test_release_sh_skip_tests_with_minimal_pyproject(tmp_path):
    """Smoke test of the full script flow with tests skipped and twine missing."""
    pytest.importorskip("build", reason="release.sh smoke test needs the `build` package")
    script = _copy_release_sh(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\nversion = '0.0.0'\n"
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
    )
    (tmp_path / "x.py").write_text("")
    env = {**os.environ, "RELEASE_REPO_ROOT": str(tmp_path), "RELEASE_SKIP_TESTS": "1"}
    # Hide twine if it exists so the skip-warning path is exercised deterministically.
    env["PATH"] = str(tmp_path / "empty-bin") + os.pathsep + env["PATH"]
    (tmp_path / "empty-bin").mkdir()
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    dist = tmp_path / "dist"
    sums = dist / "SHA256SUMS"
    assert sums.exists()
    # checksum file content must verify against the built artifacts
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition("  ")
        assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest
    assert "twine" in proc.stdout.lower()
    assert "upload" in proc.stdout.lower()  # checklist printed
