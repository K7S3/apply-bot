"""Tests for candid.drafting.context.build_context.

Deterministic, no network, no LLM. Uses tmp_path fixtures and passes an
explicit tracker path so the real user data dir is never touched.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import context as ctx  # noqa: E402
from candid import tracker as T  # noqa: E402


def _write_record(path: Path, **overrides) -> Path:
    """Write one tracker record (with extra fields tracker.add lacks) to path."""
    rec = {
        "id": 1,
        "company": "Acme Corp",
        "role": "ML Engineer",
        "jd_link": "",
        "status": "applied",
        "notes": "Referral from Priya.",
        "date_added": (date.today() - timedelta(days=10)).isoformat(),
        "date_updated": (date.today() - timedelta(days=5)).isoformat(),
        "prep_pack": "",
        "interviewers": ["Dana Lee", "Omar Reyes"],
        "status_history": [
            {"date": (date.today() - timedelta(days=10)).isoformat(),
             "from": "saved", "to": "applied"},
            {"date": (date.today() - timedelta(days=8)).isoformat(),
             "from": "", "to": "applied",
             "note": "Recruiter confirmed receipt."},
        ],
        "open_questions": ["Ask about team size?"],
    }
    rec.update(overrides)
    path.write_text(json.dumps([rec]), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# missing application -> empty-but-valid packet, never an exception
# ---------------------------------------------------------------------------

def test_missing_app_empty_packet(tmp_path):
    p = tmp_path / "tracker.json"
    p.write_text("[]", encoding="utf-8")
    packet = ctx.build_context("Nobody Inc", tracker=p)
    assert packet["found"] is False
    assert packet["company"] == "Nobody Inc"
    assert packet["role"] == ""
    assert packet["status"] == ""
    assert packet["stage"] == ""
    assert packet["applied_date"] == ""
    assert packet["days_since_applied"] is None
    assert packet["last_contact"] == ""
    assert packet["days_since_last_contact"] is None
    assert packet["interviewers"] == []
    assert packet["notes"] == ""
    assert packet["company_notes"] == ""
    assert packet["open_questions"] == []
    assert packet["application_id"] is None


def test_missing_tracker_file_empty_packet(tmp_path):
    packet = ctx.build_context("Nobody Inc", tracker=tmp_path / "nope.json")
    assert packet["found"] is False
    assert packet["days_since_last_contact"] is None


def test_malformed_tracker_never_raises(tmp_path):
    p = tmp_path / "tracker.json"
    p.write_text("{not valid json", encoding="utf-8")
    packet = ctx.build_context("Acme Corp", tracker=p)
    assert packet["found"] is False
    assert packet["role"] == ""


def test_tracker_list_form(tmp_path):
    recs = [{"id": 7, "company": "Acme Corp", "role": "Data Scientist",
             "status": "saved", "date_added": "2026-09-01"}]
    packet = ctx.build_context("acme corp", tracker=recs)
    assert packet["found"] is True
    assert packet["application_id"] == 7
    assert packet["role"] == "Data Scientist"


# ---------------------------------------------------------------------------
# days-since math
# ---------------------------------------------------------------------------

def test_days_since_contact_math(tmp_path):
    p = _write_record(tmp_path / "tracker.json")
    packet = ctx.build_context("Acme Corp", tracker=p)
    assert packet["found"] is True
    assert packet["role"] == "ML Engineer"
    assert packet["stage"] == "applied" == packet["status"]
    assert packet["days_since_applied"] == 10
    assert packet["days_since_last_contact"] == 5
    assert packet["last_contact"] == (date.today() - timedelta(days=5)).isoformat()
    assert packet["interviewers"] == ["Dana Lee", "Omar Reyes"]
    assert packet["notes"] == "Referral from Priya."
    assert packet["open_questions"] == ["Ask about team size?"]


def test_bad_dates_yield_none_not_exceptions(tmp_path):
    p = _write_record(tmp_path / "tracker.json",
                      date_added="not-a-date", date_updated="",
                      status_history=[{"date": "junk"}])
    packet = ctx.build_context("Acme Corp", tracker=p)
    assert packet["found"] is True
    assert packet["applied_date"] == ""
    assert packet["days_since_applied"] is None
    assert packet["days_since_last_contact"] is None


def test_app_id_selects_record(tmp_path):
    p = tmp_path / "tracker.json"
    T.add("Acme Corp", "ML Engineer", path=p)
    T.add("Acme Corp", "Data Analyst", path=p)
    apps = T.list_apps(path=p)
    second = [a for a in apps if a["role"] == "Data Analyst"][0]
    packet = ctx.build_context("Acme Corp", tracker=p, app_id=second["id"])
    assert packet["found"] is True
    assert packet["role"] == "Data Analyst"


# ---------------------------------------------------------------------------
# company notes
# ---------------------------------------------------------------------------

def test_company_notes_loaded(tmp_path):
    p = _write_record(tmp_path / "tracker.json")
    (tmp_path / "company_notes.json").write_text(
        json.dumps({"acme corp": "Series C, hybrid NYC."}), encoding="utf-8")
    packet = ctx.build_context("Acme Corp", tracker=p)
    assert packet["company_notes"] == "Series C, hybrid NYC."


def test_company_notes_missing_file_ok(tmp_path):
    p = _write_record(tmp_path / "tracker.json")
    packet = ctx.build_context("Acme Corp", tracker=p)
    assert packet["company_notes"] == ""


# ---------------------------------------------------------------------------
# drafts-only: no email sending or network in the module
# ---------------------------------------------------------------------------

FORBIDDEN = ("smtplib", "requests", "urllib", "socket")


def test_no_sending_or_network_imports():
    src = Path(ctx.__file__).read_text(encoding="utf-8")
    for mod in FORBIDDEN:
        assert f"import {mod}" not in src, f"forbidden import: {mod}"
