"""Tests for candid.crashlog (local structured crash log).

All paths are monkeypatched to a tmp dir; the real user data dir is never
touched.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from candid import crashlog


@pytest.fixture()
def crash_env(tmp_path, monkeypatch):
    """Point the crash-log paths at a tmp dir."""
    log_path = tmp_path / "crash.log"
    last_path = tmp_path / ".last_crash"
    monkeypatch.setattr(crashlog, "CRASH_LOG_PATH", log_path)
    monkeypatch.setattr(crashlog, "CRASH_LAST_PATH", last_path)
    return tmp_path


def _boom() -> None:
    raise ValueError("kaboom")


def _raise(exc):
    raise exc


def test_round_trip_and_newest_first(crash_env):
    try:
        _boom()
    except ValueError as e:
        rec1 = crashlog.log_crash(e, command="candid", argv=["candid", "match"])
    try:
        _raise(RuntimeError("other"))
    except RuntimeError as e:
        rec2 = crashlog.log_crash(e, command="candid", argv=["candid", "tailor"])

    records = crashlog.read_crashes()
    assert len(records) == 2
    # newest first
    assert records[0]["id"] == rec2["id"]
    assert records[1]["id"] == rec1["id"]
    # record shape
    for rec in records:
        assert rec["candid_version"]
        assert rec["python_version"]
        assert rec["platform"]
        assert rec["traceback_hash"] and len(rec["traceback_hash"]) == 16
        assert rec["ts"]
        assert isinstance(rec["frames"], list)
        assert rec["frames"], "expected at least one frame"
        frame = rec["frames"][-1]
        assert set(frame) == {"file", "module", "func", "line"}
        # basenames only: no directory separators in file names
        for f in rec["frames"]:
            assert "/" not in f["file"] and "\\" not in f["file"]
    assert records[1]["exc_type"] == "ValueError"
    assert records[1]["exc_msg"] == "kaboom"
    assert records[1]["command"] == "candid"
    assert records[1]["argv"] == ["candid", "match"]


def test_read_missing_log_returns_empty(crash_env):
    assert crashlog.read_crashes() == []


def test_corrupt_lines_tolerated(crash_env):
    log = crashlog.CRASH_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "not json at all\n"
        '{"id": "abc", "no-ts": true}\n'
        "[1, 2, 3]\n"
        "\n",
        encoding="utf-8",
    )
    try:
        _boom()
    except ValueError as e:
        good = crashlog.log_crash(e)
    records = crashlog.read_crashes()
    assert len(records) == 1
    assert records[0]["id"] == good["id"]


def test_grouping_dedups_identical_tracebacks(crash_env):
    for _ in range(3):
        try:
            _boom()
        except ValueError as e:
            crashlog.log_crash(e)
    try:
        _raise(RuntimeError("different"))
    except RuntimeError as e:
        crashlog.log_crash(e)

    groups = crashlog.group_crashes()
    assert len(groups) == 2
    value_group = next(g for g in groups if g["exc_type"] == "ValueError")
    assert value_group["count"] == 3
    assert value_group["first_ts"] <= value_group["last_ts"]
    assert value_group["sample_id"]
    assert len(value_group["hash"]) == 16
    runtime_group = next(g for g in groups if g["exc_type"] == "RuntimeError")
    assert runtime_group["count"] == 1


def test_rotation_triggers_on_small_max_bytes(crash_env, monkeypatch):
    monkeypatch.setattr(crashlog, "CRASH_LOG_MAX_BYTES", 50)
    monkeypatch.setattr(crashlog, "CRASH_LOG_KEEP", 2)
    try:
        _boom()
    except ValueError as e:
        crashlog.log_crash(e)
        crashlog.log_crash(e)

    log = crashlog.CRASH_LOG_PATH
    # main log rotated away; backups exist
    assert not log.exists() or log.stat().st_size <= 50
    backups = [log.with_name(log.name + f".{i}") for i in (1, 2)]
    assert any(b.exists() for b in backups)
    # never more than KEEP backups
    assert not log.with_name(log.name + ".3").exists()


def test_prune_old_drops_old_records(crash_env, monkeypatch):
    monkeypatch.setattr(crashlog, "CRASH_LOG_MAX_AGE_DAYS", 90)
    log = crashlog.CRASH_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)

    old_ts = (datetime.now(timezone.utc) - timedelta(days=91)).astimezone().isoformat()
    fresh_ts = datetime.now(timezone.utc).astimezone().isoformat()

    def _rec(ts, rid):
        return {
            "id": rid,
            "ts": ts,
            "candid_version": "0.2.0",
            "python_version": "3.11",
            "platform": "x",
            "command": "candid",
            "argv": [],
            "exc_type": "ValueError",
            "exc_msg": "x",
            "traceback_hash": "deadbeefdeadbeef",
            "frames": [],
        }

    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_rec(old_ts, "old-one")) + "\n")
        fh.write(json.dumps(_rec(fresh_ts, "fresh-one")) + "\n")

    crashlog.prune_old()
    records = crashlog.read_crashes()
    assert [r["id"] for r in records] == ["fresh-one"]


def test_hook_logs_and_delegates(crash_env, monkeypatch):
    calls = []

    def fake_previous(exc_type, exc_value, exc_tb):
        calls.append((exc_type, exc_value))

    monkeypatch.setattr(sys, "excepthook", fake_previous)
    previous = crashlog.install_crash_hook()
    assert previous is fake_previous
    try:
        try:
            _boom()
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
    finally:
        crashlog.uninstall_crash_hook(previous)

    assert sys.excepthook is fake_previous
    # previous hook still called (traceback still prints in real use)
    assert len(calls) == 1
    assert calls[0][0] is ValueError
    # and the crash was logged
    records = crashlog.read_crashes()
    assert len(records) == 1
    assert records[0]["exc_type"] == "ValueError"


def test_install_hook_restore_param(crash_env, monkeypatch):
    sentinel = sys.__excepthook__
    monkeypatch.setattr(sys, "excepthook", sentinel)
    prev = crashlog.install_crash_hook()
    assert sys.excepthook is not sentinel
    assert crashlog.install_crash_hook(restore=prev) is None
    assert sys.excepthook is sentinel


def test_last_crash_marker_set_and_cleared(crash_env):
    assert crashlog.check_last_crash() is None
    try:
        _boom()
    except ValueError as e:
        rec = crashlog.log_crash(e)
    found = crashlog.check_last_crash()
    assert found is not None
    assert found["id"] == rec["id"]
    crashlog.clear_last_crash()
    assert crashlog.check_last_crash() is None


def test_log_crash_never_raises_when_unwritable(crash_env, monkeypatch):
    blocker = crash_env / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    monkeypatch.setattr(crashlog, "CRASH_LOG_PATH", blocker / "crash.log")
    monkeypatch.setattr(crashlog, "CRASH_LAST_PATH", blocker / ".last_crash")

    try:
        _boom()
    except ValueError as e:
        rec = crashlog.log_crash(e)  # must not raise

    assert rec["exc_type"] == "ValueError"
    assert rec["id"]
    assert crashlog.read_crashes() == []
    assert crashlog.check_last_crash() is None
    crashlog.rotate_if_needed()  # also must not raise
    crashlog.prune_old()  # also must not raise
