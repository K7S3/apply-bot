"""Tests for candid.release_secrets (pre-release secret/PII scan)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_secrets as RS  # noqa: E402


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
    (repo / "candid").mkdir(exist_ok=True)
    return repo


def _check_by_name(checks, name):
    for check in checks:
        if check["name"] == name:
            return check
    raise AssertionError(f"check {name!r} missing")


def test_git_status_short_failure_returns_empty(tmp_path):
    assert RS.git_status_short(tmp_path) == ""


def test_forbidden_profile_yaml_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "profile.yaml").write_text("name: test\n")
    check = _check_by_name(RS.run_checks(repo), "forbidden files clean")
    assert check["ok"] is False
    assert "profile.yaml" in check["detail"]


def test_forbidden_output_dir_detected(tmp_path):
    repo = _init_repo(tmp_path)
    outdir = repo / "output"
    outdir.mkdir()
    (outdir / "report.txt").write_text("data")
    check = _check_by_name(RS.run_checks(repo), "forbidden files clean")
    assert check["ok"] is False
    assert "output" in check["detail"]


def test_forbidden_shim_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "run_ollama_shim.py").write_text("# shim\n")
    check = _check_by_name(RS.run_checks(repo), "forbidden files clean")
    assert check["ok"] is False
    assert "run_ollama_shim.py" in check["detail"]


def test_clean_repo_passes_all_checks(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "mod.py").write_text('VALUE = 1\n')
    checks = RS.run_checks(repo)
    assert len(checks) == 3
    assert all(c["ok"] for c in checks)


def _write_secret_module(repo):
    secret_value = "sk-probe-9f8e7d6c5b4a3210"
    (repo / "candid" / "keys.py").write_text(
        f"api_key = '{secret_value}'\n"
    )
    return secret_value


def test_secret_pattern_reports_file_line_not_value(tmp_path):
    repo = _init_repo(tmp_path)
    secret_value = _write_secret_module(repo)
    check = _check_by_name(RS.run_checks(repo), "no secret patterns")
    assert check["ok"] is False
    assert "candid/keys.py:1" in check["detail"]
    assert secret_value not in check["detail"]


def test_private_key_block_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "tls.py").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n"
    )
    check = _check_by_name(RS.run_checks(repo), "no secret patterns")
    assert check["ok"] is False
    assert "candid/tls.py:1" in check["detail"]
    assert "[private key block]" in check["detail"]
    assert "MIIE" not in check["detail"]


def test_aws_key_and_github_token_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "creds.py").write_text(
        'key_id = "AKIAIOSFODNN7EXAMPLE"\n'
        'gh = "ghp_abcdefghijklmnopqrstuvwx"\n'
    )
    check = _check_by_name(RS.run_checks(repo), "no secret patterns")
    assert check["ok"] is False
    assert "[aws access key id]" in check["detail"]
    assert "[github token]" in check["detail"]
    assert "AKIAIOSFODNN7EXAMPLE" not in check["detail"]
    assert "ghp_abcdefghijklmnopqrstuvwx" not in check["detail"]


def test_pii_email_detected_with_file_line(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "contact.py").write_text(
        '# reach out\nSUPPORT = "help@realmail.com"\n'
    )
    check = _check_by_name(RS.run_checks(repo), "no obvious PII in source")
    assert check["ok"] is False
    assert "candid/contact.py:2" in check["detail"]
    assert "help@realmail.com" not in check["detail"]


def test_pii_phone_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "contact.py").write_text('PHONE = "212-555-0198"\n')
    check = _check_by_name(RS.run_checks(repo), "no obvious PII in source")
    assert check["ok"] is False
    assert "candid/contact.py:1" in check["detail"]
    assert "[phone number]" in check["detail"]
    assert "212-555-0198" not in check["detail"]


def test_pii_example_domain_allowlisted(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "candid" / "docs.py").write_text(
        '# contact alice@example.com or bob@test.com for help\n'
    )
    check = _check_by_name(RS.run_checks(repo), "no obvious PII in source")
    assert check["ok"] is True


def test_secret_scan_skips_tests_and_samples(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "t.py").write_text("api_key = 'sk-hidden-12345678'\n")
    (repo / "samples").mkdir()
    (repo / "samples" / "s.txt").write_text("api_key = 'sk-hidden-12345678'\n")
    check = _check_by_name(RS.run_checks(repo), "no secret patterns")
    assert check["ok"] is True


def test_forbidden_constant_contents():
    assert RS.FORBIDDEN == ("profile.yaml", "output", "run_ollama_shim.py")
