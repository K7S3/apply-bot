"""Tests for candid.bugreport (consent, report building, diagnostics).

All tests use tmp dirs and monkeypatched path constants; the real user
data dir is never touched.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime
from pathlib import Path

import pytest

from candid import bugreport, config
from candid.bugreport import BugReportError


@pytest.fixture()
def tmp_consent(tmp_path, monkeypatch):
    path = tmp_path / "cfg" / "consent.json"  # parent does not exist yet
    monkeypatch.setattr(config, "CONSENT_PATH", path)
    return path


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    return data


def _record(**overrides):
    node = platform.node().strip()
    base = {
        "id": "crash-1",
        "ts": "2026-09-22T19:00:00+00:00",
        "candid_version": "0.2.0",
        "python": "3.12.3",
        "platform": f"Linux-6.8.0-52-generic-{node}-x86_64",
        "command": "candid tailor",
        "argv": [
            "candid",
            "tailor",
            "--email",
            "keshavan@example.com",
            "--dir",
            "/home/keshavan/resumes",
        ],
        "exc_type": "ValueError",
        "exc_msg": "bad value for user keshavan@example.com at /home/keshavan/x.pdf",
        "traceback_hash": "deadbeef",
        "frames": [
            {"file": "tailor.py", "module": "candid.tailor", "func": "run", "line": 42},
            {"file": "cli.py", "module": "candid.cli", "func": "main", "line": 7},
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture()
def fake_crashes(monkeypatch):
    records = [_record()]
    monkeypatch.setattr(bugreport, "_read_crashes", lambda: list(records))
    return records


# --- consent ---------------------------------------------------------------
def test_consent_undecided_by_default(tmp_consent):
    assert bugreport.get_consent() is None
    assert "UNDECIDED" in bugreport.consent_status()


def test_consent_opt_in_round_trip(tmp_consent):
    bugreport.set_consent(True)
    assert bugreport.get_consent() is True
    payload = json.loads(tmp_consent.read_text(encoding="utf-8"))
    assert payload["crash_share_opt_in"] is True
    assert set(payload.keys()) == {"crash_share_opt_in", "updated"}
    datetime.fromisoformat(payload["updated"])  # must be valid ISO
    assert "OPTED IN" in bugreport.consent_status()


def test_consent_opt_out_round_trip(tmp_consent):
    bugreport.set_consent(False)
    assert bugreport.get_consent() is False
    assert "OPTED OUT" in bugreport.consent_status()
    # Flip back and forth.
    bugreport.set_consent(True)
    assert bugreport.get_consent() is True


def test_consent_corrupt_file_is_undecided(tmp_consent):
    tmp_consent.parent.mkdir(parents=True)
    tmp_consent.write_text("not json {{{", encoding="utf-8")
    assert bugreport.get_consent() is None


# --- report building --------------------------------------------------------
def test_build_report_redacts_pii(fake_crashes):
    report = bugreport.build_report()
    assert "keshavan@example.com" not in report
    assert "/home/keshavan" not in report
    assert "[EMAIL]" in report
    assert "<HOME>" in report
    assert "ValueError" in report
    assert "candid tailor" in report
    assert "[HOST]" in report  # hostname from platform.node()
    assert platform.node().strip() not in report


def test_build_report_audit_section(fake_crashes):
    report = bugreport.build_report()
    assert "## Redaction audit" in report
    assert "email" in report
    assert "home" in report


def test_build_report_no_crashes(monkeypatch, tmp_data):
    monkeypatch.setattr(bugreport, "_read_crashes", lambda: [])
    report = bugreport.build_report()
    assert "No crash records found" in report
    assert "## Diagnostics" in report  # diagnostics still included


def test_build_report_unknown_id_raises(fake_crashes):
    with pytest.raises(BugReportError, match="no-such-id"):
        bugreport.build_report(crash_id="no-such-id")


def test_build_report_selects_crash_id(monkeypatch):
    recs = [_record(id="a"), _record(id="b", exc_type="KeyError")]
    monkeypatch.setattr(bugreport, "_read_crashes", lambda: recs)
    assert "KeyError" in bugreport.build_report(crash_id="b")
    assert "ValueError" in bugreport.build_report(crash_id="a")


# --- diagnostics -------------------------------------------------------------
def test_diagnostics_shape_and_no_secrets(tmp_data, fake_crashes, monkeypatch):
    (tmp_data / "a.json").write_text("x" * 100, encoding="utf-8")
    (tmp_data / "sub").mkdir()
    (tmp_data / "sub" / "b.db").write_text("y" * 50, encoding="utf-8")
    monkeypatch.setattr(bugreport, "_group_count", lambda crashes: 1)

    diag = bugreport.build_diagnostics()
    assert diag["data_dir"] == {"files": 2, "bytes_total": 150}
    assert diag["crashes"]["total_records"] == 1
    assert diag["crashes"]["groups"] == 1
    assert diag["crashes"]["top_exc_types"] == {"ValueError": 1}
    assert isinstance(diag["candid_version"], str)
    assert isinstance(diag["python"], str)

    # Config keys are NAMES only: uppercase strings, no values leaked.
    keys = diag["config_keys_present"]
    assert "DATA_DIR" in keys
    assert all(isinstance(k, str) and k.isupper() for k in keys)

    # Platform is redacted; no raw hostname anywhere in values.
    node = platform.node().strip()
    assert node not in json.dumps(diag)

    # No secret values: every leaf is a plain str/int/dict of those.
    def _check(value):
        if isinstance(value, dict):
            for v in value.values():
                _check(v)
        elif isinstance(value, list):
            for v in value:
                _check(v)
        else:
            assert isinstance(value, (str, int, float, bool))

    _check(diag)


# --- save / share --------------------------------------------------------------
def test_save_report_writes_file(tmp_data, fake_crashes):
    path = bugreport.save_report("# hello")
    assert isinstance(path, Path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# hello"

    explicit = tmp_data / "custom.md"
    assert bugreport.save_report("# x", out_path=explicit) == explicit
    assert explicit.exists()


def test_save_report_default_filename(tmp_data, fake_crashes):
    path = bugreport.save_report("# hello")
    assert path.parent == tmp_data
    assert path.name.startswith("bug-report-")
    assert path.suffix == ".md"


def test_prepare_shareable_refuses_without_opt_in(tmp_consent, tmp_data, fake_crashes):
    with pytest.raises(BugReportError, match=r"candid bug-report --opt-in"):
        bugreport.prepare_shareable()


def test_prepare_shareable_succeeds_when_opted_in(tmp_consent, tmp_data, fake_crashes):
    bugreport.set_consent(True)
    path, instructions = bugreport.prepare_shareable()
    assert path.exists()
    assert "keshavan@example.com" not in path.read_text(encoding="utf-8")
    assert "nothing is transmitted automatically" in instructions
    assert "manually paste" in instructions
