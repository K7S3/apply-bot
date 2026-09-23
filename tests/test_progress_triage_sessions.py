"""Tests for candid CLI interactive mode: progress.py, triage.py, sessions.py.

Run: cd <repo> && python -m pytest tests/test_progress_triage_sessions.py -q
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="candid-test-pts-"))
os.environ["CANDID_DATA_DIR"] = str(_TMP / "data")
os.environ["CANDID_CONFIG_DIR"] = str(_TMP / "config")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import progress as PR  # noqa: E402
from candid import sessions  # noqa: E402
from candid import tracker as T  # noqa: E402
from candid import triage as TR  # noqa: E402


# --- helpers -----------------------------------------------------------------


class FakeStream:
    """A stream double with controllable isatty()."""

    def __init__(self, tty: bool):
        self._tty = tty
        self.chunks: list[str] = []

    def isatty(self) -> bool:
        return self._tty

    def write(self, s: str) -> None:
        self.chunks.append(s)

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def _tracker_file(tmp_path: Path) -> Path:
    """Tracker file path that never touches real user data."""
    return tmp_path / "tracker.json"


def _seed_tracker(path: Path) -> None:
    """Three apps with distinct date_updated values for ordering tests."""
    apps = [
        {"id": 1, "company": "OldCorp", "role": "Engineer", "jd_link": "",
         "status": "applied", "notes": "first", "date_added": "2026-09-01",
         "date_updated": "2026-09-10", "prep_pack": ""},
        {"id": 2, "company": "MidCorp", "role": "Analyst", "jd_link": "",
         "status": "saved", "notes": "", "date_added": "2026-09-02",
         "date_updated": "2026-09-20", "prep_pack": ""},
        {"id": 3, "company": "NewCorp", "role": "Designer", "jd_link": "",
         "status": "selected_for_interview", "notes": "", "date_added": "2026-09-03",
         "date_updated": "2026-09-22", "prep_pack": ""},
    ]
    path.write_text(json.dumps(apps), encoding="utf-8")


# --- Progress: TTY bar --------------------------------------------------------


def test_progress_bar_renders_to_fake_tty():
    s = FakeStream(tty=True)
    with PR.Progress("Refreshing jobs", total=10, stream=s) as p:
        p.update(5, msg="halfway")
        p.update(5, msg="done")
    assert "\r" in s.text
    assert "[##########] 10/10" in s.text
    assert "Refreshing jobs" in s.text
    assert "done" in s.text
    # cleaned up with a newline on exit (last chunk is the newline)
    assert s.chunks[-1] == "\n"


def test_progress_partial_bar_shape():
    s = FakeStream(tty=True)
    with PR.Progress("Loading", total=10, stream=s) as p:
        p.update(5)
    assert "[#####-----] 5/10" in s.text


def test_progress_clamps_past_total():
    s = FakeStream(tty=True)
    with PR.Progress("Loading", total=10, stream=s) as p:
        p.update(99)
    assert "99/10" in s.text
    assert "[##########]" in s.text  # bar never overflows


def test_progress_no_total_is_plain_counter():
    s = FakeStream(tty=True)
    with PR.Progress("Scanning", stream=s) as p:
        p.update(3)
    assert "Scanning 3" in s.text
    assert "[" not in s.text


def test_progress_tty_flag_overrides_stream():
    s = FakeStream(tty=True)  # forced off anyway
    with PR.Progress("X", total=5, stream=s, tty=False) as p:
        p.update(2)
    assert "\r" not in s.text


# --- Progress: non-TTY silence ------------------------------------------------


def test_progress_non_tty_is_silent_except_start_end():
    s = FakeStream(tty=False)
    with PR.Progress("Refreshing jobs", total=50, stream=s) as p:
        for _ in range(50):
            p.update(1, msg="spinning hard")
    assert "\r" not in s.text
    assert len(s.chunks) == 2  # one start line, one end line
    assert s.chunks[0].startswith("Refreshing jobs... ")
    assert s.chunks[1].startswith("done in ") and s.chunks[1].endswith("s\n")


def test_progress_non_tty_never_breaks_piped_output():
    s = FakeStream(tty=False)
    with PR.Progress("Jobs", stream=s) as p:
        p.update(0, msg="nothing yet")
    for chunk in s.chunks:
        assert "\r" not in chunk and "\x1b" not in chunk


# --- Spinner ------------------------------------------------------------------


def test_spinner_tty_animates_and_cleans_up():
    s = FakeStream(tty=True)
    with PR.spin("Working", stream=s, interval=0.01):
        time.sleep(0.08)
    assert "\r" in s.text  # at least one animated frame
    assert s.chunks[-1] == "\n"


def test_spinner_non_tty_prints_start_end_only():
    s = FakeStream(tty=False)
    with PR.spin("Working", stream=s):
        time.sleep(0.02)
    assert "\r" not in s.text
    assert s.text == "Working... done\n"


# --- Triage: scripted happy paths ---------------------------------------------


def test_triage_keep_keeps_everything(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    out = FakeStream(tty=True)
    res = TR.triage(answers=["k", "k", "k"], path=path, stream=out)
    assert res == {"reviewed": 3, "updated": 0, "archived": 0, "quit": False}
    apps = T.list_apps(path=path)
    assert [a["status"] for a in apps] == ["applied", "saved", "selected_for_interview"]
    # apps were reviewed least-recently-updated first: OldCorp, MidCorp, NewCorp
    import re as _re
    ids = [l for l in out.text.splitlines() if _re.match(r"\[\d+\]", l)]
    assert len(ids) == 3
    assert ids[0].startswith("[1] OldCorp")
    assert ids[1].startswith("[2] MidCorp")
    assert ids[2].startswith("[3] NewCorp")


def test_triage_update_stage_uses_real_statuses(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    out = FakeStream(tty=True)
    res = TR.triage(answers=["u", "offer", "q"], path=path, stream=out)
    assert res["updated"] == 1 and res["quit"] is True and res["reviewed"] == 2
    app = next(a for a in T.list_apps(path=path) if a["id"] == 1)
    assert app["status"] == "offer"
    # the stage prompt lists tracker's real status set
    for st in C.STATUSES:
        assert st in out.text


def test_triage_update_stage_reprompts_on_bad_status(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    res = TR.triage(answers=["u", "hired", "rejected", "q"], path=path,
                    stream=FakeStream(tty=True))
    assert res["updated"] == 1
    app = next(a for a in T.list_apps(path=path) if a["id"] == 1)
    assert app["status"] == "rejected"


def test_triage_note_appends_to_existing_notes(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    res = TR.triage(answers=["n", "heard back", "q"], path=path,
                    stream=FakeStream(tty=True))
    assert res["updated"] == 1 and res["quit"] is True
    app = next(a for a in T.list_apps(path=path) if a["id"] == 1)
    assert app["notes"] == "first\nheard back"


def test_triage_archive_uses_withdrawn(tmp_path):
    assert TR.ARCHIVE_STATUS == "withdrawn"  # "archived" not in tracker's statuses
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    out = FakeStream(tty=True)
    res = TR.triage(answers=["a", "q"], path=path, stream=out)
    assert res == {"reviewed": 2, "updated": 0, "archived": 1, "quit": True}
    app = next(a for a in T.list_apps(path=path) if a["id"] == 1)
    assert app["status"] == "withdrawn"
    assert "withdrawn" in out.text


def test_triage_quit_first_reviews_one(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    res = TR.triage(answers=["q"], path=path, stream=FakeStream(tty=True))
    assert res == {"reviewed": 1, "updated": 0, "archived": 0, "quit": True}


def test_triage_exhausted_answers_quits_gracefully(tmp_path):
    path = _tracker_file(tmp_path)
    _seed_tracker(path)
    res = TR.triage(answers=[], path=path, stream=FakeStream(tty=True))
    assert res["quit"] is True and res["reviewed"] == 1


def test_triage_empty_tracker(tmp_path):
    path = _tracker_file(tmp_path)
    path.write_text("[]", encoding="utf-8")
    out = FakeStream(tty=True)
    res = TR.triage(answers=["k"], path=path, stream=out)
    assert res == {"reviewed": 0, "updated": 0, "archived": 0, "quit": False}
    assert "No applications" in out.text


def test_triage_non_tty_without_answers_raises():
    with patch("sys.stdin") as fake_stdin:
        fake_stdin.isatty.return_value = False
        with pytest.raises(TR.TriageError):
            TR.triage(path="/nonexistent.json", stream=FakeStream(tty=False))


# --- Sessions -----------------------------------------------------------------


def test_sessions_round_trip():
    answers = {"q1": "yes", "q2": ["a", "b"], "n": 3}
    p = sessions.save_session("apply-flow", answers)
    assert p.is_file()
    assert sessions.load_session("apply-flow") == answers
    assert "apply-flow" in sessions.list_sessions()
    assert sessions.clear_session("apply-flow") is True
    assert sessions.load_session("apply-flow") is None
    assert sessions.clear_session("apply-flow") is False  # already gone
    assert "apply-flow" not in sessions.list_sessions()


def test_sessions_list_sorted():
    for name in ["zeta", "alpha", "mid"]:
        sessions.save_session(name, {})
    try:
        assert sessions.list_sessions() == ["alpha", "mid", "zeta"]
    finally:
        for name in ["zeta", "alpha", "mid"]:
            sessions.clear_session(name)


def test_sessions_name_sanitized():
    p = sessions.save_session("My Fancy Session!", {"a": 1})
    assert p.name == "my-fancy-session-.json"
    assert sessions.load_session("My Fancy Session!") == {"a": 1}
    assert sessions.clear_session("My Fancy Session!") is True


@pytest.mark.parametrize("bad", ["", "   "])
def test_sessions_bad_names_rejected(bad):
    with pytest.raises(ValueError):
        sessions.save_session(bad, {})
    with pytest.raises(ValueError):
        sessions.load_session(bad)


def test_sessions_corrupt_file_returns_none():
    p = sessions.save_session("corrupt-me", {"ok": True})
    p.write_text("{not valid json", encoding="utf-8")
    assert sessions.load_session("corrupt-me") is None
    p.unlink()


def test_sessions_non_dict_json_returns_none():
    p = sessions.save_session("listy", {"ok": True})
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert sessions.load_session("listy") is None
    p.unlink()


def test_sessions_missing_returns_none():
    assert sessions.load_session("never-saved") is None


def test_sessions_honors_config_dir_at_call_time(monkeypatch):
    first = _TMP / "cfg-first"
    second = _TMP / "cfg-second"
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(first))
    sessions.save_session("roamer", {"v": 1})
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(second))
    assert sessions.load_session("roamer") is None  # not visible under new dir
    assert (first / "wizard_sessions" / "roamer.json").is_file()
    assert not (second / "wizard_sessions").exists()
    sessions.clear_session("roamer")  # no-op under second dir


def test_sessions_save_rejects_non_dict():
    with pytest.raises(ValueError):
        sessions.save_session("nope", ["not", "a", "dict"])
