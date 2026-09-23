"""Windows-support hardening IO tests: atomic writes, file locks, judge subprocess flags.

These run on every platform but assert the Windows-safe behavior:
- atomic_write never leaves temp files and preserves content exactly
- file_lock can be acquired and released repeatedly without error
- mock_judge's subprocess.run uses shell=False and passes creationflags
  (CREATE_NO_WINDOW on Windows) so no console window pops up
"""

import json
import os
import subprocess
from types import SimpleNamespace

from candid import mock_judge
from candid.atomic import atomic_write, file_lock


def _leftover_tmps(directory):
    return [p for p in os.listdir(directory)
            if p.startswith(".atomic-") and p.endswith(".tmp")]


def test_atomic_write_str_round_trip(tmp_path):
    target = tmp_path / "profile.json"
    data = '{"name": "Keshavan", "note": "caf\u00e9 \u2615 unicode"}'
    atomic_write(target, data)
    assert target.read_text(encoding="utf-8") == data
    assert _leftover_tmps(tmp_path) == []


def test_atomic_write_bytes_round_trip(tmp_path):
    target = tmp_path / "blob.bin"
    data = b"\x00\x01\x02binary\xff"
    atomic_write(target, data)
    assert target.read_bytes() == data
    assert _leftover_tmps(tmp_path) == []


def test_atomic_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "tracker.json"
    atomic_write(target, "[]")
    assert json.loads(target.read_text(encoding="utf-8")) == []
    assert _leftover_tmps(tmp_path / "deep" / "nested") == []


def test_atomic_write_overwrites_cleanly(tmp_path):
    target = tmp_path / "t.json"
    target.write_text("old", encoding="utf-8")
    atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert _leftover_tmps(tmp_path) == []


def test_file_lock_acquire_release_twice(tmp_path):
    target = tmp_path / "tracker.json"
    with file_lock(target):
        pass
    with file_lock(target):
        pass
    assert (tmp_path / "tracker.json.lock").exists()


def test_file_lock_protects_write(tmp_path):
    """Two sequential locked saves both land, with atomic content each time."""
    target = tmp_path / "tracker.json"
    for payload in ('["a"]', '["b"]'):
        with file_lock(target):
            atomic_write(target, payload)
    import json as _json
    assert _json.loads(target.read_text(encoding="utf-8")) == ["b"]


def test_mock_judge_subprocess_is_windows_safe(tmp_path, monkeypatch):
    """Capture the subprocess.run kwargs the judge uses and assert safety."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        assert argv == ["X", "-I", "runner.py"]  # sanity: called as expected
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"verdict": "accepted"}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Simulate Windows so CREATE_NO_WINDOW has a real non-zero value.
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(mock_judge.sys, "executable", "X")

    result = mock_judge._run_single_test(tmp_path, "solve", "exact", [1], 1, 2.0)
    assert result["verdict"] == "accepted"

    kwargs = captured["kwargs"]
    assert isinstance(captured["argv"], list)  # argv list, never a string command
    assert kwargs.get("shell") is False
    assert "creationflags" in kwargs  # CREATE_NO_WINDOW on Windows
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs.get("text") is True
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"
    assert "timeout" in kwargs
    # cwd must be an absolute, resolved path (tmp_path is already resolved here)
    assert os.path.isabs(kwargs["cwd"])
