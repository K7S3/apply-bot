"""CLI smoke tests for the sprint command group (candid/__main__.py wiring).

Exercises plan/add-target/batch/timebox/log/status/review through the
argparse parser with a throwaway CANDID_DATA_DIR.

Run: python -m pytest tests/test_sprint_cli.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.__main__ import build_parser, main  # noqa: E402
from candid import sprint as S  # noqa: E402
from candid import sprint_exec as SE  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def _this_monday() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _run(argv, capsys):
    """Parse argv through the real parser and run the dispatch function."""
    args = build_parser().parse_args(argv)
    args.func(args)
    return capsys.readouterr().out


def test_plan_creates_sprint(data_dir, capsys):
    out = _run(["sprint", "plan", "--week", _this_monday(), "--target", "7",
                "--hours", "8"], capsys)
    assert "Created sprint #1" in out
    assert "goal 7 apps" in out
    sprints = S.list_sprints()
    assert len(sprints) == 1
    assert sprints[0]["target_apps"] == 7
    assert sprints[0]["hours_budget"] == 8.0


def test_add_target_to_current(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    out = _run(["sprint", "add-target", "--company", "Acme",
                "--role", "Data Scientist", "--priority", "high"], capsys)
    assert "Data Scientist @ Acme [high]" in out
    sp = S.get_sprint("current")
    assert len(sp["targets"]) == 1


def test_batch_and_timebox(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    _run(["sprint", "add-target", "--company", "Acme",
          "--role", "Data Scientist"], capsys)
    out = _run(["sprint", "batch"], capsys)
    assert "batch-1" in out and "Acme" in out
    out = _run(["sprint", "timebox"], capsys)
    assert "time block(s)" in out
    assert "18:00" in out


def test_log_then_status(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday(), "--target", "2"], capsys)
    _run(["sprint", "add-target", "--company", "Acme",
          "--role", "Data Scientist"], capsys)
    out = _run(["sprint", "log", "--company", "Acme",
                "--role", "Data Scientist"], capsys)
    assert "Logged application" in out
    out = _run(["sprint", "status"], capsys)
    assert "1/1 done" in out
    assert "on pace" in out or "behind pace" in out


def test_review_renders(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    _run(["sprint", "add-target", "--company", "Acme",
          "--role", "Data Scientist"], capsys)
    out = _run(["sprint", "review"], capsys)
    assert "Sprint review" in out
    assert "Targets:" in out


def test_plan_with_template(data_dir, capsys):
    out = _run(["sprint", "plan", "--week", _this_monday(),
                "--template", "steady-5"], capsys)
    assert "template 'steady-5'" in out
    sp = S.get_sprint("current")
    assert sp["template"] == "steady-5"
    assert sp["target_apps"] == 5


def test_templates_save_list_apply(data_dir, capsys):
    out = _run(["sprint", "templates", "save", "--name", "t9",
                "--target", "9", "--hours", "9"], capsys)
    assert "Saved template 't9'" in out
    out = _run(["sprint", "templates", "list"], capsys)
    assert "t9" in out
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    out = _run(["sprint", "templates", "apply", "--name", "t9"], capsys)
    assert "goal 9 apps" in out


def test_export_ics_writes_file(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    _run(["sprint", "timebox"], capsys)
    out_path = str(data_dir / "sprint.ics")
    out = _run(["sprint", "export-ics", "--out", out_path], capsys)
    assert "Exported sprint #1" in out
    content = Path(out_path).read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content and "VEVENT" in content


def test_log_unknown_target_is_friendly(capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["sprint", "log", "--company", "Nope", "--role", "Nothing"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Error:" in err and "Next:" in err


def test_schedule_suggests_tasks(data_dir, capsys):
    _run(["sprint", "plan", "--week", _this_monday()], capsys)
    _run(["sprint", "add-target", "--company", "Acme",
          "--role", "Data Scientist"], capsys)
    _run(["sprint", "timebox"], capsys)
    out = _run(["sprint", "schedule", "--day", "mon"], capsys)
    assert "Plan for 'mon'" in out
    assert "Acme" in out
