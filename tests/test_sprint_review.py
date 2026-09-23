"""Tests for candid.sprint_review (sprint review and continuity).

Uses pytest with tmp_path + CANDID_DATA_DIR; sprints.json is seeded
directly. Modules that bind DATA_DIR at import time are reloaded per test
so each test gets an isolated data dir.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    import candid.config as C
    importlib.reload(C)
    import candid.tracker as T
    importlib.reload(T)
    import candid.sprint_review as SR
    importlib.reload(SR)
    return tmp_path, SR


def _seed(data_dir_fx, sprints):
    tmp_path, SR = data_dir_fx
    (tmp_path / "sprints.json").write_text(
        json.dumps(sprints), encoding="utf-8")
    return SR


def _sprint(sid, week, targets, **kw):
    d = {
        "id": sid,
        "week_start": week,
        "title": f"Week of {week}",
        "target_apps": 3,
        "hours_budget": 5.0,
        "targets": targets,
        "time_blocks": [],
        "notes": [],
        "status": "active",
        "created_at": "2026-09-22T00:00:00+00:00",
        "review": {},
        "template": "default",
    }
    d.update(kw)
    return d


def _target(company, status="todo", priority="high", batch="a", tracker_id=None):
    return {
        "company": company,
        "role": "Engineer",
        "jd_link": "",
        "priority": priority,
        "status": status,
        "batch": batch,
        "tracker_id": tracker_id,
        "done_at": "2026-09-22" if status == "done" else None,
    }


# ---------------------------------------------------------------------------
# review math + storing
# ---------------------------------------------------------------------------

def test_review_math_and_stored(data_dir):
    sprints = [_sprint(1, "2026-09-21", [
        _target("Acme", "done", "high", "a"),
        _target("Beta", "done", "high", "a"),
        _target("Gamma", "todo", "low", "b"),
    ], notes=[{"text": "n1"}, {"text": "n2"}])]
    SR = _seed(data_dir, sprints)

    rev = SR.review_sprint(1)
    assert rev["targets_done"] == 2
    assert rev["targets_total"] == 3
    assert rev["target_apps"] == 3
    assert rev["completion_pct"] == pytest.approx(66.7)
    assert rev["hit_target"] is False  # 2 done < goal of 3
    assert rev["by_priority"]["high"] == {"done": 2, "total": 2}
    assert rev["by_priority"]["low"] == {"done": 0, "total": 1}
    assert rev["by_batch"]["a"] == {"done": 2, "total": 2}
    assert rev["by_batch"]["b"] == {"done": 0, "total": 1}
    assert rev["notes_count"] == 2
    assert rev["generated_at"]

    stored = SR.get_sprint(1)["review"]
    assert stored == rev
    # status untouched
    assert SR.get_sprint(1)["status"] == "active"


def test_review_hit_target_when_goal_met(data_dir):
    sprints = [_sprint(1, "2026-09-21", [
        _target("Acme", "done"), _target("Beta", "done"), _target("Gamma", "done"),
    ])]
    SR = _seed(data_dir, sprints)
    rev = SR.review_sprint(1)
    assert rev["hit_target"] is True
    assert rev["completion_pct"] == 100.0


def test_review_missing_sprint_raises(data_dir):
    tmp_path, SR = data_dir
    with pytest.raises(SR.SprintReviewError):
        SR.review_sprint(99)


def test_review_enriches_with_tracker_outcomes(data_dir):
    tmp_path, SR = data_dir
    import candid.tracker as T
    a = T.add("Acme", "Engineer", status="applied")
    b = T.add("Beta", "Engineer", status="selected_for_interview")
    _seed(data_dir, [_sprint(1, "2026-09-21", [
        _target("Acme", "done", tracker_id=a["id"]),
        _target("Beta", "todo", tracker_id=b["id"]),
        _target("Gamma", "todo"),  # no tracker link
    ])])
    rev = SR.review_sprint(1)
    assert rev["tracker_outcomes"]["applied"] == 1
    assert rev["tracker_outcomes"]["selected_for_interview"] == 1


def test_review_tracker_missing_is_fine(data_dir):
    tmp_path, SR = data_dir
    _seed(data_dir, [_sprint(1, "2026-09-21", [
        _target("Acme", "done", tracker_id=12345),  # dangling id
    ])])
    rev = SR.review_sprint(1)
    assert rev["tracker_outcomes"] == {}
    assert rev["targets_done"] == 1


# ---------------------------------------------------------------------------
# carryover
# ---------------------------------------------------------------------------

def test_carryover_copies_only_todos_and_closes_old(data_dir):
    sprints = [_sprint(1, "2026-09-21", [
        _target("Acme", "done", "high", "a"),
        _target("Beta", "todo", "low", "b"),
        _target("Gamma", "todo", "low", "b"),
    ])]
    SR = _seed(data_dir, sprints)

    new = SR.carryover(1)
    assert new["week_start"] == "2026-09-28"  # next Monday
    assert new["title"] == "Week of 2026-09-28 (carryover)"
    assert new["target_apps"] == 3
    assert new["hours_budget"] == 5.0
    assert new["status"] == "active"
    assert new["id"] == 2
    companies = [t["company"] for t in new["targets"]]
    assert companies == ["Beta", "Gamma"]  # done one left behind
    assert all(t["status"] == "todo" and t["done_at"] is None for t in new["targets"])
    assert new["review"] == {}

    old = SR.get_sprint(1)
    assert old["status"] == "closed"
    assert old["review"]["targets_done"] == 1  # auto-reviewed on close


def test_carryover_explicit_week_snapped_to_monday(data_dir):
    SR = _seed(data_dir, [_sprint(1, "2026-09-21", [])])
    new = SR.carryover(1, new_week_start="2026-10-07")  # a Wednesday
    assert new["week_start"] == "2026-10-05"


def test_carryover_duplicate_week_raises(data_dir):
    sprints = [
        _sprint(1, "2026-09-21", [], status="closed"),
        _sprint(2, "2026-09-28", [], status="active"),
    ]
    SR = _seed(data_dir, sprints)
    with pytest.raises(SR.SprintReviewError):
        SR.carryover(1)  # would land on 2026-09-28, taken


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def test_compare_deltas(data_dir):
    sprints = [
        _sprint(1, "2026-09-21", [
            _target("Acme", "done"), _target("Beta", "todo"),
        ], target_apps=3),
        _sprint(2, "2026-09-28", [
            _target("Acme", "done"), _target("Beta", "done"),
            _target("Gamma", "done"),
        ], target_apps=5),
    ]
    SR = _seed(data_dir, sprints)
    d = SR.compare_sprints(1, 2)
    assert d["target_apps"] == 2
    assert d["done"] == 2
    assert d["completion_pct"] == pytest.approx(50.0)  # 100 - 50
    assert d["hit_target"] == (False, False)  # 1<3, 3<5


def test_compare_generates_missing_reviews_on_the_fly(data_dir):
    SR = _seed(data_dir, [
        _sprint(1, "2026-09-21", [_target("Acme", "done")]),
        _sprint(2, "2026-09-28", [_target("Acme", "done")]),
    ])
    d = SR.compare_sprints(1, 2)
    assert d["done"] == 0
    # nothing written: stored reviews still empty
    assert SR.get_sprint(1)["review"] == {}


# ---------------------------------------------------------------------------
# streaks
# ---------------------------------------------------------------------------

def _hit_sprint(sid, week, hit):
    status = "done" if hit else "todo"
    return _sprint(sid, week, [_target("Acme", status)],
                   status="closed", target_apps=1)


def test_streaks_gap_breaks_chain(data_dir):
    # hits 9/07, 9/14, miss 9/21 (gap week 9/28 entirely missing), hits 10/05, 10/12
    sprints = [
        _hit_sprint(1, "2026-09-07", True),
        _hit_sprint(2, "2026-09-14", True),
        _hit_sprint(3, "2026-09-21", False),
        _hit_sprint(4, "2026-10-05", True),
        _hit_sprint(5, "2026-10-12", True),
    ]
    SR = _seed(data_dir, sprints)
    # stored reviews: generate them so streaks read hit_target
    for s in sprints:
        SR.review_sprint(s["id"])
    st = SR.streaks()
    assert st["current_streak"] == 2   # 10/05, 10/12 (gap before 10/05 breaks)
    assert st["best_streak"] == 2      # 9/07+9/14 and 10/05+10/12


def test_streaks_current_zero_when_latest_missed(data_dir):
    sprints = [
        _hit_sprint(1, "2026-09-07", True),
        _hit_sprint(2, "2026-09-14", False),
    ]
    SR = _seed(data_dir, sprints)
    for s in sprints:
        SR.review_sprint(s["id"])
    st = SR.streaks()
    assert st["current_streak"] == 0
    assert st["best_streak"] == 1


def test_streaks_no_closed_sprints(data_dir):
    SR = _seed(data_dir, [_sprint(1, "2026-09-21", [])])
    assert SR.streaks() == {"current_streak": 0, "best_streak": 0}


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_render_review_contains_key_numbers(data_dir):
    sprints = [_sprint(1, "2026-09-21", [
        _target("Acme", "done", "high", "a"),
        _target("Beta", "todo", "high", "a"),
        _target("Gamma", "todo", "low", "b"),
    ], target_apps=3)]
    SR = _seed(data_dir, sprints)
    SR.review_sprint(1)
    text = SR.render_review(1)
    assert "Week of 2026-09-21" in text
    assert "1/3 done" in text
    assert "33.3%" in text
    assert "Goal: 3 applications - MISSED" in text
    assert "high: 1/2 done" in text
    assert "a: 1/2 done" in text
    assert "b: 0/1 done" in text


def test_render_hit_verdict(data_dir):
    SR = _seed(data_dir, [_sprint(1, "2026-09-21",
                                       [_target("Acme", "done")], target_apps=1)])
    SR.review_sprint(1)
    assert "HIT" in SR.render_review(1)
