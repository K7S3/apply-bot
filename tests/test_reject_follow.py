"""Tests for candid.reject_follow (rejection reframe module)."""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-reject-follow"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candid import config as C
from candid import tracker as T
from candid import reject_follow as R


@pytest.fixture(autouse=True)
def wipe_data(tmp_path, monkeypatch):
    """Isolate each test in a fresh data dir."""
    monkeypatch.setattr(C, "DATA_DIR", tmp_path / "data")
    for child in (tmp_path / "data").glob("*.json"):
        child.unlink()
    yield


def _rejected_app(company="Acme", role="ML Engineer"):
    return T.add(company, role, status="rejected", path=C.TRACKER_PATH)


def _applied_app(company="Beta", role="SWE"):
    return T.add(company, role, status="applied", path=C.TRACKER_PATH)


# --- schedule_reapproach --------------------------------------------------------

def test_schedule_validates_months_range():
    app = _rejected_app()
    with pytest.raises(R.RejectFollowError):
        R.schedule_reapproach(app["id"], months=0)
    with pytest.raises(R.RejectFollowError):
        R.schedule_reapproach(app["id"], months=25)


def test_schedule_requires_rejected_status():
    app = _applied_app()
    with pytest.raises(R.RejectFollowError):
        R.schedule_reapproach(app["id"])
    with pytest.raises(R.RejectFollowError):
        R.schedule_reapproach(999999)


def test_schedule_happy_path_and_upsert():
    app = _rejected_app()
    rec = R.schedule_reapproach(app["id"], months=9, note="try again")
    assert rec["company"] == "Acme"
    assert rec["role"] == "ML Engineer"
    assert rec["note"] == "try again"
    due = date.fromisoformat(rec["due_date"])
    assert due.year * 12 + due.month == (date.today().year * 12 + date.today().month + 9)
    # upsert: second call replaces, does not duplicate
    rec2 = R.schedule_reapproach(app["id"], months=6)
    items = R.due_reapproaches("9999-12-31")
    assert len(items) == 1
    assert rec2["due_date"] < rec["due_date"]


# --- due_reapproaches / cancel --------------------------------------------------

def test_due_reapproaches_respects_dates_and_sorting():
    a1 = _rejected_app("Acme", "ML Engineer")
    a2 = _rejected_app("Globex", "SWE")
    a3 = _rejected_app("Initech", "Analyst")
    # schedule all, then rewrite due dates directly for deterministic control
    R.schedule_reapproach(a1["id"])
    R.schedule_reapproach(a2["id"])
    R.schedule_reapproach(a3["id"])
    items = R.due_reapproaches("9999-12-31")
    today = date.today()
    items[0]["due_date"] = (today + timedelta(days=5)).isoformat()
    items[1]["due_date"] = (today - timedelta(days=1)).isoformat()
    items[2]["due_date"] = (today - timedelta(days=10)).isoformat()
    import json as _json
    (C.DATA_DIR / R.REAPPROACH_PATH).write_text(_json.dumps(items), encoding="utf-8")
    due = R.due_reapproaches()
    assert [i["app_id"] for i in due] == [a3["id"], a2["id"]]
    # future one not included
    assert a1["id"] not in [i["app_id"] for i in due]
    # inclusive: due_date == today counts as due
    due_today = R.due_reapproaches(items[1]["due_date"])
    assert any(i["app_id"] == a2["id"] for i in due_today)


def test_cancel_reapproach():
    app = _rejected_app()
    assert R.cancel_reapproach(app["id"]) is False
    R.schedule_reapproach(app["id"])
    assert R.cancel_reapproach(app["id"]) is True
    assert R.cancel_reapproach(app["id"]) is False


# --- feedback flow --------------------------------------------------------------

def test_ask_log_pending_feedback_flow():
    app = _rejected_app()
    rec = R.ask_feedback(app["id"], "Priya (hiring manager)")
    assert rec["feedback"] is None
    assert rec["who"] == "Priya (hiring manager)"
    pending = R.pending_feedback()
    assert len(pending) == 1 and pending[0]["app_id"] == app["id"]
    got = R.log_feedback(app["id"], "Work on system design depth.")
    assert got["feedback"] == "Work on system design depth."
    assert got["received_date"] == date.today().isoformat()
    assert R.pending_feedback() == []


def test_log_feedback_without_ask_raises():
    app = _rejected_app()
    with pytest.raises(R.RejectFollowError):
        R.log_feedback(app["id"], "Some feedback")
    with pytest.raises(R.RejectFollowError):
        R.ask_feedback(123456, "No one")


def test_ask_feedback_upsert():
    app = _rejected_app()
    R.ask_feedback(app["id"], "Alice")
    rec = R.ask_feedback(app["id"], "Bob")
    assert rec["who"] == "Bob"
    assert len(R.pending_feedback()) == 1


# --- draft_response ---------------------------------------------------------------

def test_draft_response_thankyou():
    rej = {"company": "Acme", "role": "ML Engineer"}
    d = R.draft_response(rej, "thankyou")
    assert "Acme" in d["subject"] and "ML Engineer" in d["subject"]
    assert "Acme" in d["body"] and "ML Engineer" in d["body"]
    assert "[Your Name]" in d["body"]


def test_draft_response_feedback():
    rej = {"company": "Globex", "role": "SWE"}
    d = R.draft_response(rej, "feedback")
    assert "Globex" in d["subject"] and "SWE" in d["subject"]
    assert "Globex" in d["body"] and "SWE" in d["body"]
    assert "[Your Name]" in d["body"]
    # asks for specific improvement areas
    assert "improve" in d["body"].lower() or "area" in d["body"].lower()


def test_draft_response_unknown_kind_raises():
    with pytest.raises(R.RejectFollowError):
        R.draft_response({"company": "Acme", "role": "ML Engineer"}, "begging")


# --- to_network ---------------------------------------------------------------------

def test_to_network_dedupes():
    app = _rejected_app()
    contacts = R.to_network(app["id"], ["Alice", "Bob", ""])
    assert len(contacts) == 2
    assert contacts[0]["source"] == "rejected interview"
    assert contacts[0]["company"] == "Acme"
    # same names again -> no duplicates; case-insensitive
    contacts = R.to_network(app["id"], ["alice", "BOB", "Cara"])
    assert [c["name"] for c in contacts] == ["Alice", "Bob", "Cara"]
    assert len(contacts) == 3


def test_to_network_unknown_app_raises():
    with pytest.raises(R.RejectFollowError):
        R.to_network(424242, ["Zed"])


# --- render helpers -------------------------------------------------------------------

def test_render_empty_friendly():
    assert "No" in R.render_reapproaches([]) or "none" in R.render_reapproaches([]).lower()
    assert "none" in R.render_feedback([]).lower() or "No" in R.render_feedback([])
    assert "No" in R.render_contacts([]) or "none" in R.render_contacts([]).lower()


def test_render_one_line_each():
    app = _rejected_app()
    R.schedule_reapproach(app["id"])
    R.ask_feedback(app["id"], "Priya")
    R.to_network(app["id"], ["Priya"])
    lines = R.render_reapproaches(R.due_reapproaches("9999-12-31")).splitlines()
    assert len(lines) == 1 and "Acme" in lines[0]
    lines = R.render_feedback(R.pending_feedback()).splitlines()
    assert len(lines) == 1 and "Priya" in lines[0]
    lines = R.render_contacts(R.to_network(app["id"], [])).splitlines()
    assert len(lines) == 1 and "Priya" in lines[0]
