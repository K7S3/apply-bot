"""Tests for candid.privacy_purge (privacy export / purge commands)."""

import os
import shutil
import zipfile
from argparse import Namespace
from pathlib import Path

# Test isolation: must be set before importing candid.
os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privpurge"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privpurge-config"

import pytest  # noqa: E402

from candid import config  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_purge as pp  # noqa: E402

DATA = Path(os.environ["CANDID_DATA_DIR"])


@pytest.fixture(autouse=True)
def _redirect_data_dir(monkeypatch):
    """Keep tests order-independent: config.DATA_DIR binds at first import,
    so point it (and privacy's derived paths) at this file's data dir."""
    monkeypatch.setattr(config, "DATA_DIR", DATA)
    monkeypatch.setattr(P, "PRIVACY_EXPORT_DIR", DATA / "privacy_exports")
    monkeypatch.setattr(P, "AUDIT_LOG_PATH", DATA / "privacy_audit.jsonl")
    yield


def make_args(**kwargs):
    base = dict(category="profile", out=None, redact=False, yes=False,
                export_first=False, keep_days=None)
    base.update(kwargs)
    return Namespace(**base)


@pytest.fixture()
def profile_data():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "profile.json").write_text(
        '{"name": "Keshavan", "email": "keshavan@example.com", "phone": "+1-555-010-1234"}',
        encoding="utf-8",
    )
    yield
    shutil.rmtree(DATA, ignore_errors=True)


@pytest.fixture()
def tailored_data():
    DATA.mkdir(parents=True, exist_ok=True)
    sub = DATA / "tailored"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "resume.txt").write_text("Keshavan <keshavan@example.com> resume", encoding="utf-8")
    (sub / "cover.md").write_text("# Cover letter\ncontact keshavan@example.com", encoding="utf-8")
    (sub / "blob.bin").write_bytes(b"\x00\x01\x02\x03")
    yield
    shutil.rmtree(DATA, ignore_errors=True)


def test_export_creates_zip_with_category_files(profile_data):
    rc = pp.cmd_export(make_args(category="profile"))
    assert rc == 0
    exports = list((DATA / "privacy_exports").glob("profile-*.zip"))
    assert len(exports) == 1
    with zipfile.ZipFile(exports[0]) as zf:
        assert zf.namelist() == ["profile.json"]
        content = zf.read("profile.json").decode("utf-8")
    assert "keshavan@example.com" in content


def test_export_redact_removes_email(profile_data):
    rc = pp.cmd_export(make_args(category="profile", redact=True))
    assert rc == 0
    exports = list((DATA / "privacy_exports").glob("profile-*.zip"))
    assert len(exports) == 1
    with zipfile.ZipFile(exports[0]) as zf:
        content = zf.read("profile.json").decode("utf-8")
    assert "keshavan@example.com" not in content
    assert "[REDACTED-EMAIL]" in content
    assert "[REDACTED-PHONE]" in content


def test_export_to_out_path(profile_data, tmp_path):
    out = tmp_path / "my-export.zip"
    rc = pp.cmd_export(make_args(category="profile", out=str(out)))
    assert rc == 0
    assert out.exists()


def test_export_audits(profile_data):
    pp.cmd_export(make_args(category="profile"))
    entries = P.read_audit_log(limit=10)
    assert any(e["action"] == "export" and "profile" in e["detail"] for e in entries)


def test_export_unknown_category_exits_2():
    with pytest.raises(SystemExit) as exc:
        pp.cmd_export(make_args(category="nope"))
    assert exc.value.code == 2


def test_export_empty_category_exits_2():
    with pytest.raises(SystemExit) as exc:
        pp.cmd_export(make_args(category="prep"))
    assert exc.value.code == 2


def test_purge_deletes_files_and_frees_bytes(profile_data):
    before = P.category_bytes("profile")
    assert before > 0
    rc = pp.cmd_purge(make_args(category="profile", yes=True))
    assert rc == 0
    assert P.category_files("profile") == []
    assert not (DATA / "profile.json").exists()
    assert P.category_bytes("profile") == 0
    entries = P.read_audit_log(limit=10)
    assert any(
        e["action"] == "purge" and f"files=1" in e["detail"] and f"freed_bytes={before}" in e["detail"]
        for e in entries
    )


def test_purge_removes_empty_dirs(tailored_data):
    rc = pp.cmd_purge(make_args(category="tailored", yes=True))
    assert rc == 0
    assert P.category_files("tailored") == []
    assert not (DATA / "tailored").exists()


def test_purge_declined_confirmation_deletes_nothing(profile_data, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    rc = pp.cmd_purge(make_args(category="profile"))
    assert rc == 0
    assert (DATA / "profile.json").exists()
    assert P.category_files("profile") != []


def test_purge_no_yes_flag_asks_confirmation(profile_data, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    rc = pp.cmd_purge(make_args(category="profile"))
    assert rc == 0
    assert not (DATA / "profile.json").exists()
    out = capsys.readouterr().out
    assert "Purged" in out


def test_purge_export_first_leaves_export_behind(profile_data):
    rc = pp.cmd_purge(make_args(category="profile", yes=True, export_first=True))
    assert rc == 0
    assert not (DATA / "profile.json").exists()
    exports = list((DATA / "privacy_exports").glob("profile-*.zip"))
    assert len(exports) == 1
    with zipfile.ZipFile(exports[0]) as zf:
        assert "profile.json" in zf.namelist()


def test_purge_keep_days_skips_new_files(profile_data):
    # File is fresh (newer than 30 days), so keep-days matches nothing and
    # purge refuses rather than deleting.
    with pytest.raises(SystemExit) as exc:
        pp.cmd_purge(make_args(category="profile", yes=True, keep_days=30))
    assert exc.value.code == 2
    assert (DATA / "profile.json").exists()


def test_purge_keep_days_deletes_old_files(profile_data):
    old = (DATA / "profile.json")
    mtime = old.stat().st_mtime - 31 * 86400
    os.utime(old, (mtime, mtime))
    rc = pp.cmd_purge(make_args(category="profile", yes=True, keep_days=30))
    assert rc == 0
    assert not old.exists()


def test_purge_unknown_category_exits_2():
    with pytest.raises(SystemExit) as exc:
        pp.cmd_purge(make_args(category="nope", yes=True))
    assert exc.value.code == 2


def test_purge_empty_category_refuses():
    with pytest.raises(SystemExit) as exc:
        pp.cmd_purge(make_args(category="prep", yes=True))
    assert exc.value.code == 2


def test_add_parsers_registers_both_commands():
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    pp.add_parsers(sub)
    args = parser.parse_args(["export", "profile"])
    assert args.func is pp.cmd_export
    assert args.redact is False
    args = parser.parse_args(["purge", "tracker", "--yes", "--export-first", "--keep-days", "7"])
    assert args.func is pp.cmd_purge
    assert args.yes is True and args.export_first is True and args.keep_days == 7
