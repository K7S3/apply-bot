"""Tests for candid.reject_report."""

import os
import sys

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-reject-report"
sys.path.insert(0, "/home/hatch/workspace/candid-batch87")

import pytest  # noqa: E402

from candid import config as C  # noqa: E402
from candid import reject_report as rr  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data_dir():
    # Wipe the data dir before each test; the env var above fixed it pre-import.
    if C.DATA_DIR.exists():
        for child in C.DATA_DIR.iterdir():
            if child.is_file():
                child.unlink()
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    yield


def _rejection(app_id=1, stage="technical", notes=""):
    return {
        "app_id": app_id,
        "company": "Acme",
        "role": "ML Engineer",
        "stage": stage,
        "reason_notes": notes,
        "feedback": "",
    }


# --- log_change / changes_since ----------------------------------------------------------------

def test_log_change_round_trip():
    entry = rr.log_change(3, "Rewrote resume bullets to match the JD")
    assert entry["app_id"] == 3
    assert entry["text"] == "Rewrote resume bullets to match the JD"
    assert entry["date"]  # ISO date string
    assert rr.CHANGES_PATH.exists()

    back = rr.changes_since(3)
    assert len(back) == 1
    assert back[0]["text"] == "Rewrote resume bullets to match the JD"


def test_log_change_empty_text_raises():
    with pytest.raises(rr.RejectReportError):
        rr.log_change(1, "   ")
    with pytest.raises(rr.RejectReportError):
        rr.log_change(1, "")


def test_changes_since_filters_by_app_id():
    rr.log_change(1, "first change for app 1")
    rr.log_change(2, "change for app 2")
    rr.log_change(1, "second change for app 1")
    entries = rr.changes_since(1)
    assert [e["text"] for e in entries] == ["first change for app 1", "second change for app 1"]
    assert rr.changes_since(99) == []


def test_log_change_custom_path(tmp_path):
    path = tmp_path / "changes.json"
    entry = rr.log_change(7, "custom path change", path=path)
    assert entry["app_id"] == 7
    assert rr.changes_since(7, path=path)[0]["text"] == "custom path change"
    # Default path untouched.
    assert not rr.CHANGES_PATH.exists()


# --- build_report ----------------------------------------------------------------

def test_build_report_defaults_empty():
    report = rr.build_report()
    assert report["total_rejected"] == 0
    assert report["by_category"] == {}
    assert report["by_stage"] == {}
    assert report["reapproaches_due_count"] == 0
    assert report["pending_feedback_count"] == 0
    assert report["changes_logged"] == 0
    assert report["morale"]["applications"] == 0


def test_build_report_aggregates_categories_and_stages():
    rejections = [
        _rejection(stage="technical", notes="not enough years of experience"),
        _rejection(stage="onsite", notes="ghosted, never heard back"),
        _rejection(stage="onsite", notes="went dark after the loop"),
        _rejection(stage="recruiter_screen", notes=""),
    ]
    report = rr.build_report(
        rejections=rejections,
        reapproaches_due=[{"company": "OldCo"}],
        pending_feedback=rejections[:2],
        apps=[{"id": 1, "status": "applied"}],
    )
    assert report["total_rejected"] == 4
    assert report["by_category"] == {"experience_gap": 1, "ghosted": 2, "unstated": 1}
    assert report["by_stage"] == {"technical": 1, "onsite": 2, "recruiter_screen": 1}
    assert report["reapproaches_due_count"] == 1
    assert report["pending_feedback_count"] == 2
    assert report["morale"]["applications"] == 1
    assert report["morale"]["rejections"] == 4


def test_build_report_counts_changes_logged():
    rr.log_change(1, "first improvement")
    rr.log_change(2, "second improvement")
    report = rr.build_report()
    assert report["changes_logged"] == 2


# --- render ----------------------------------------------------------------

def test_render_contains_section_headers():
    report = rr.build_report(
        rejections=[_rejection(stage="technical", notes="hiring freeze")],
        reapproaches_due=[{"company": "OldCo"}],
        pending_feedback=[{"app_id": 1}],
        apps=[{"id": 1, "status": "applied"}],
    )
    out = rr.render(report)
    for header in (
        "Rejections",
        "By category",
        "By stage",
        "Re-approaches due",
        "Feedback pending",
        "Improvements logged",
        "Morale",
    ):
        assert header in out
    assert "headcount_freeze" in out
    assert "technical" in out
    assert report["morale"]["line"] in out
