"""Tests for candid/sprint.py: weekly application sprint planning.

Run: python -m pytest tests/test_sprint.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import sprint as S  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def _iso(d: date) -> str:
    return d.isoformat()


# --- create_sprint -----------------------------------------------------------

def test_create_snaps_wednesday_to_monday():
    # 2026-09-23 is a Wednesday; its Monday is 2026-09-21.
    s = S.create_sprint("2026-09-23", title="Sprint")
    assert s["week_start"] == "2026-09-21"
    assert s["status"] == "active"
    assert s["target_apps"] == 5
    assert s["hours_budget"] == 6.0
    assert s["targets"] == [] and s["time_blocks"] == [] and s["notes"] == []
    assert s["review"] == {} and s["template"] == ""


def test_create_accepts_date_object():
    s = S.create_sprint(date(2026, 9, 22))  # a Tuesday
    assert s["week_start"] == "2026-09-21"


def test_create_defaults_title():
    s = S.create_sprint("2026-09-21")
    assert s["title"] == "Week of 2026-09-21"


def test_create_rejects_duplicate_active_week():
    S.create_sprint("2026-09-21")
    with pytest.raises(S.SprintError):
        S.create_sprint("2026-09-25")  # same week, snaps to same Monday


def test_create_allows_same_week_after_close():
    s = S.create_sprint("2026-09-21")
    S.close_sprint(s["id"])
    s2 = S.create_sprint("2026-09-22")
    assert s2["week_start"] == "2026-09-21"


def test_create_bad_inputs():
    with pytest.raises(S.SprintError):
        S.create_sprint("not-a-date")
    with pytest.raises(S.SprintError):
        S.create_sprint("2026-09-21", target_apps=-1)
    with pytest.raises(S.SprintError):
        S.create_sprint("2026-09-21", hours_budget=0)


# --- get/list ---------------------------------------------------------------

def test_list_and_get_latest():
    a = S.create_sprint("2026-09-21")
    b = S.create_sprint("2026-09-28")
    listed = S.list_sprints()
    assert [s["id"] for s in listed] == [b["id"], a["id"]]
    assert S.get_sprint("latest")["id"] == b["id"]
    assert S.get_sprint(a["id"])["id"] == a["id"]
    with pytest.raises(S.SprintError):
        S.get_sprint(999)
    with pytest.raises(S.SprintError):
        S.get_sprint("bogus")


def test_get_current():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    s = S.create_sprint(monday.isoformat())
    assert S.get_sprint("current")["id"] == s["id"]


def test_get_current_missing():
    with pytest.raises(S.SprintError):
        S.get_sprint("current")
    with pytest.raises(S.SprintError):
        S.get_sprint("latest")


# --- targets -----------------------------------------------------------------

def test_add_remove_target():
    s = S.create_sprint("2026-09-21")
    t = S.add_target(s["id"], "Acme", "ML Engineer", jd_link="http://x", priority="high")
    assert t["company"] == "Acme" and t["priority"] == "high"
    assert t["status"] == "todo" and t["batch"] == ""
    assert t["tracker_id"] is None and t["done_at"] is None

    dup = S.add_target(s["id"], "acme", "ml engineer")
    assert dup.get("duplicate") is True
    assert len(S.get_sprint(s["id"])["targets"]) == 1

    S.remove_target(s["id"], "ACME", "ML Engineer")
    assert S.get_sprint(s["id"])["targets"] == []
    with pytest.raises(S.SprintError):
        S.remove_target(s["id"], "Acme", "ML Engineer")


def test_add_target_validation():
    s = S.create_sprint("2026-09-21")
    with pytest.raises(S.SprintError):
        S.add_target(s["id"], "", "ML Engineer")
    with pytest.raises(S.SprintError):
        S.add_target(s["id"], "Acme", "   ")
    with pytest.raises(S.SprintError):
        S.add_target(s["id"], "Acme", "ML Engineer", priority="urgent")
    with pytest.raises(S.SprintError):
        S.add_target(999, "Acme", "ML Engineer")


# --- batching ----------------------------------------------------------------

def _sprint_with_targets():
    s = S.create_sprint("2026-09-21")
    # Two at the same company -> their own batch.
    S.add_target(s["id"], "Acme", "Backend Engineer")
    S.add_target(s["id"], "Acme", "Frontend Engineer")
    # Singles grouped by role family.
    S.add_target(s["id"], "Beta", "Data Scientist")
    S.add_target(s["id"], "Gamma", "Product Manager")
    S.add_target(s["id"], "Delta", "UX Designer")
    S.add_target(s["id"], "Epsilon", "Janitor")
    return s


def test_batch_targets_company_first_then_family():
    s = _sprint_with_targets()
    grouping = S.batch_targets(s["id"])
    # Company batch first (Acme has 2 targets).
    assert len(grouping["batch-1"]) == 2
    assert {t["company"] for t in grouping["batch-1"]} == {"Acme"}
    # Then families in canonical order: engineering has none left among
    # singles... singles are: Beta/Data Scientist (data), Gamma/Product
    # Manager (product), Delta/UX Designer (design), Epsilon/Janitor (other).
    assert [t["role"] for t in grouping["batch-2"]] == ["Data Scientist"]
    assert [t["role"] for t in grouping["batch-3"]] == ["Product Manager"]
    assert [t["role"] for t in grouping["batch-4"]] == ["UX Designer"]
    assert [t["role"] for t in grouping["batch-5"]] == ["Janitor"]
    # Batch ids are stored on the targets themselves.
    targets = S.get_sprint(s["id"])["targets"]
    assert all(t["batch"].startswith("batch-") for t in targets)


def test_batch_targets_idempotent():
    s = _sprint_with_targets()
    first = S.batch_targets(s["id"])
    second = S.batch_targets(s["id"])
    snap = lambda g: {k: sorted((t["company"], t["role"]) for t in v) for k, v in g.items()}  # noqa: E731
    assert snap(first) == snap(second)


def test_batch_targets_empty_sprint():
    s = S.create_sprint("2026-09-21")
    assert S.batch_targets(s["id"]) == {}


# --- timeboxes ----------------------------------------------------------------

def test_plan_timeboxes_distribution_totals():
    s = S.create_sprint("2026-09-21", hours_budget=6.0)
    blocks = S.plan_timeboxes(s["id"], block_minutes=90)
    # 6h / 90min = 4 blocks: research 1, tailor 2, apply 1, followup 0.
    kinds = [b["kind"] for b in blocks]
    assert len(blocks) == 4
    assert kinds.count("research") == 1
    assert kinds.count("tailor") == 2
    assert kinds.count("apply") == 1
    total_min = sum(
        (int(b["end"][:2]) * 60 + int(b["end"][3:])) - (int(b["start"][:2]) * 60 + int(b["start"][3:]))
        for b in blocks
    )
    assert total_min == 6 * 60
    # Evening schedule, Mon-Fri only.
    assert all(b["day"] in ("mon", "tue", "wed", "thu", "fri") for b in blocks)
    assert all(b["start"] >= "18:00" for b in blocks)
    # Persisted on the sprint.
    assert S.get_sprint(s["id"])["time_blocks"] == blocks


def test_plan_timeboxes_always_has_apply_block():
    s = S.create_sprint("2026-09-21", hours_budget=1.5)
    blocks = S.plan_timeboxes(s["id"], block_minutes=90)
    assert len(blocks) == 1
    assert blocks[0]["kind"] == "apply"


def test_plan_timeboxes_larger_budget():
    s = S.create_sprint("2026-09-21", hours_budget=12.0)
    blocks = S.plan_timeboxes(s["id"], block_minutes=90)
    kinds = [b["kind"] for b in blocks]
    assert len(blocks) == 8
    assert kinds.count("research") == 2
    assert kinds.count("tailor") == 3
    assert kinds.count("apply") == 2
    assert kinds.count("followup") == 1


def test_plan_timeboxes_bad_budget():
    s = S.create_sprint("2026-09-21", hours_budget=0.5)
    with pytest.raises(S.SprintError):
        S.plan_timeboxes(s["id"], block_minutes=90)
    with pytest.raises(S.SprintError):
        S.plan_timeboxes(s["id"], block_minutes=0)


# --- close/reopen -------------------------------------------------------------

def test_close_reopen():
    s = S.create_sprint("2026-09-21")
    assert S.close_sprint(s["id"])["status"] == "closed"
    assert S.get_sprint(s["id"])["status"] == "closed"
    # Idempotent.
    assert S.close_sprint(s["id"])["status"] == "closed"
    assert S.reopen_sprint(s["id"])["status"] == "active"
    assert S.reopen_sprint(s["id"])["status"] == "active"
    with pytest.raises(S.SprintError):
        S.close_sprint(999)


# --- corrupt file --------------------------------------------------------------

def test_corrupt_file_raises_cleanly(data_dir):
    (data_dir / "sprints.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(S.SprintError, match="not valid JSON"):
        S.list_sprints()


def test_non_list_file_raises_cleanly(data_dir):
    (data_dir / "sprints.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    with pytest.raises(S.SprintError, match="JSON list"):
        S.list_sprints()


def test_missing_file_is_empty():
    assert S.list_sprints() == []
