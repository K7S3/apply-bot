"""Tests for candid.sprint_exec (sprint execution logging and progress).

Seeds sprints.json directly via JSON; does not depend on candid.sprint.
"""

import json
from datetime import date

import pytest

from candid import sprint_exec as se


def _target(company, role, priority="medium", status="todo", **kw):
    rec = {
        "company": company,
        "role": role,
        "jd_link": "",
        "priority": priority,
        "status": status,
        "batch": "b29",
        "tracker_id": None,
        "done_at": None,
    }
    rec.update(kw)
    return rec


def _sprint(**kw):
    s = {
        "id": 1,
        "week_start": "2026-09-21",  # a Monday
        "title": "Week 1",
        "target_apps": 7,
        "hours_budget": 10.0,
        "targets": [],
        "time_blocks": [],
        "notes": [],
        "status": "active",
        "created_at": "2026-09-21T09:00:00",
        "review": {},
        "template": "",
    }
    s.update(kw)
    return s


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def seed_sprints(data_dir, sprints):
    (data_dir / "sprints.json").write_text(
        json.dumps(sprints), encoding="utf-8"
    )


def seed_tracker(data_dir, apps):
    (data_dir / "tracker.json").write_text(json.dumps(apps), encoding="utf-8")


# --- log / unlog -----------------------------------------------------------


def test_log_application_marks_done(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    rec = se.log_application(1, "acme", "mle")  # case-insensitive
    assert rec["status"] == "done"
    assert rec["done_at"] == date.today().isoformat()
    raw = json.loads((data_dir / "sprints.json").read_text())
    assert raw[0]["targets"][0]["status"] == "done"


def test_log_application_custom_date(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    rec = se.log_application(1, "Acme", "MLE", applied_at="2026-09-22")
    assert rec["done_at"] == "2026-09-22"


def test_log_application_missing_target(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    with pytest.raises(se.SprintExecError, match="Add the target"):
        se.log_application(1, "Other", "SDE")


def test_log_application_bad_tracker_id(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    seed_tracker(data_dir, [{"id": 5, "company": "Acme", "role": "MLE"}])
    with pytest.raises(se.SprintExecError, match="No tracker entry with id 42"):
        se.log_application(1, "Acme", "MLE", tracker_id=42)


def test_log_application_with_tracker_id(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    seed_tracker(data_dir, [{"id": 5, "company": "Acme", "role": "MLE"}])
    rec = se.log_application(1, "Acme", "MLE", tracker_id=5)
    assert rec["tracker_id"] == 5
    assert rec["status"] == "done"


def test_unlog_reverts(data_dir):
    seed_sprints(
        data_dir,
        [
            _sprint(
                targets=[
                    _target(
                        "Acme", "MLE", status="done", tracker_id=5, done_at="2026-09-22"
                    )
                ]
            )
        ],
    )
    rec = se.unlog_application(1, "Acme", "MLE")
    assert rec["status"] == "todo"
    assert rec["done_at"] is None
    assert rec["tracker_id"] is None


def test_missing_sprint(data_dir):
    seed_sprints(data_dir, [_sprint()])
    with pytest.raises(se.SprintExecError, match="No sprint with id 99"):
        se.progress(99)


# --- check-in --------------------------------------------------------------


def test_checkin_adds_note(data_dir):
    seed_sprints(data_dir, [_sprint()])
    se.daily_checkin(1, "applied to Acme", day="2026-09-22")
    notes = json.loads((data_dir / "sprints.json").read_text())[0]["notes"]
    assert notes == [{"date": "2026-09-22", "text": "applied to Acme"}]


def test_checkin_same_day_merges(data_dir):
    seed_sprints(data_dir, [_sprint()])
    se.daily_checkin(1, "applied to Acme", day="2026-09-22")
    se.daily_checkin(1, "emailed recruiter", day="2026-09-22")
    se.daily_checkin(1, "applied to Globex", day="2026-09-23")
    notes = json.loads((data_dir / "sprints.json").read_text())[0]["notes"]
    assert len(notes) == 2  # one entry per day max
    assert notes[0]["text"] == "applied to Acme\nemailed recruiter"
    assert notes[1]["text"] == "applied to Globex"


# --- progress --------------------------------------------------------------


def _sprint_with_done(n_done, n_todo, target_apps=7):
    targets = [
        _target(f"C{i}", "MLE", status="done") for i in range(n_done)
    ] + [_target(f"T{i}", "MLE") for i in range(n_todo)]
    return _sprint(targets=targets, target_apps=target_apps)


def test_progress_on_pace(data_dir):
    # week_start 2026-09-21 (Mon); today 2026-09-24 -> elapsed 3
    # expected = 7 * 3/7 = 3.0; 3 done -> on pace
    seed_sprints(data_dir, [_sprint_with_done(3, 4)])
    p = se.progress(1, today="2026-09-24")
    assert p["done"] == 3
    assert p["total_targets"] == 7
    assert p["target_apps"] == 7
    assert p["pct_of_targets"] == pytest.approx(3 / 7 * 100, abs=0.05)
    assert p["expected_by_now"] == pytest.approx(3.0)
    assert p["on_pace"] is True
    assert len(p["remaining"]) == 4


def test_progress_behind_pace(data_dir):
    seed_sprints(data_dir, [_sprint_with_done(2, 5)])
    p = se.progress(1, today="2026-09-24")
    assert p["expected_by_now"] == pytest.approx(3.0)
    assert p["on_pace"] is False


def test_progress_elapsed_clamped(data_dir):
    seed_sprints(data_dir, [_sprint_with_done(0, 3, target_apps=7)])
    # before the sprint week: elapsed clamped to 0 -> expected 0, still on pace
    p = se.progress(1, today="2026-09-20")
    assert p["expected_by_now"] == 0
    assert p["on_pace"] is True
    # after the week: elapsed clamped to 7 -> expected full target
    p = se.progress(1, today="2026-10-05")
    assert p["expected_by_now"] == pytest.approx(7.0)
    assert p["on_pace"] is False


def test_progress_no_targets(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[])])
    p = se.progress(1, today="2026-09-24")
    assert p["done"] == 0
    assert p["pct_of_targets"] == 0.0
    assert p["remaining"] == []


# --- remaining / link -------------------------------------------------------


def test_remaining_targets_sorted_by_priority(data_dir):
    seed_sprints(
        data_dir,
        [
            _sprint(
                targets=[
                    _target("Low1", "MLE", priority="low"),
                    _target("High1", "MLE", priority="high"),
                    _target("Med1", "MLE", priority="medium"),
                    _target("High2", "MLE", priority="high", status="done"),
                    _target("Med2", "MLE", priority="medium"),
                ]
            )
        ],
    )
    got = se.remaining_targets(1)
    assert [t["company"] for t in got] == ["High1", "Med1", "Med2", "Low1"]
    assert se.remaining_targets(1, priority="high") == [
        t for t in got if t["priority"] == "high"
    ]
    assert se.remaining_targets(1, priority="medium")[0]["priority"] == "medium"


def test_remaining_targets_bad_priority(data_dir):
    seed_sprints(data_dir, [_sprint()])
    with pytest.raises(se.SprintExecError, match="Unknown priority"):
        se.remaining_targets(1, priority="urgent")


def test_link_tracker_without_done(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    seed_tracker(data_dir, [{"id": 7, "company": "Acme", "role": "MLE"}])
    rec = se.link_tracker(1, "ACME", "mle", 7)
    assert rec["tracker_id"] == 7
    assert rec["status"] == "todo"  # not marked done
    raw = json.loads((data_dir / "sprints.json").read_text())
    assert raw[0]["targets"][0]["tracker_id"] == 7


def test_link_tracker_bad_id(data_dir):
    seed_sprints(data_dir, [_sprint(targets=[_target("Acme", "MLE")])])
    seed_tracker(data_dir, [])
    with pytest.raises(se.SprintExecError, match="No tracker entry with id 9"):
        se.link_tracker(1, "Acme", "MLE", 9)
