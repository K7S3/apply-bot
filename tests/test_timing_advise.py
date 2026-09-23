"""Tests for candid.timing_advise (batch-25 advise).

Data isolation: CANDID_DATA_DIR is pointed at a throwaway dir before any
candid import (same pattern as tests/test_ingest_track.py), and each test
monkeypatches timing.load_applications to return fixture data so no real
tracker file is touched. "Today" is passed explicitly to the pure
functions so results are deterministic.
"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, timedelta
from types import SimpleNamespace

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-test-advise-")

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import timing as T  # noqa: E402
from candid import timing_advise as A  # noqa: E402

TODAY = date(2026, 9, 22)

_id = 0


def _app(company, role, *, status, posted_ago=None, applied_ago=None,
         notes="", responded=False):
    """Fixture tracker record. Ages are relative to TODAY."""
    global _id
    _id += 1
    posted = (TODAY - timedelta(days=posted_ago)).isoformat() if posted_ago is not None else None
    applied = (TODAY - timedelta(days=applied_ago)).isoformat() if applied_ago is not None else None
    return {
        "id": _id,
        "company": company,
        "role": role,
        "status": status,
        "notes": notes,
        "posted_date": posted,
        "applied_date": applied,
        "first_response_date": applied if responded else None,
        "date_added": applied,
        "date_updated": applied,
    }


def _fresh_bucket_apps(n, positive):
    """n apps applied 1 day after posting (bucket '0-3 days')."""
    apps = []
    for i in range(n):
        apps.append(_app("FreshCo", f"Role {i}", status="offer" if i < positive else "rejected",
                         posted_ago=20, applied_ago=19, responded=True))
    return apps


def _with_apps(monkeypatch, apps):
    monkeypatch.setattr(T, "load_applications", lambda: apps)


def _run_cmd(fn, ns):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(ns)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# cmd_advise verdicts
# ---------------------------------------------------------------------------

def test_fresh_posting_apply_now(monkeypatch):
    apps = _fresh_bucket_apps(6, 4)
    _with_apps(monkeypatch, apps)
    monkeypatch.setattr(A, "_today", lambda: TODAY)
    out = _run_cmd(A.cmd_advise, SimpleNamespace(
        company="NewCo", role="MLE", posted_date="2026-09-20",
        deadline=None, json=False))
    assert "Verdict: APPLY NOW" in out
    assert "2 days old" in out


def test_stale_thin_data_honesty_note_no_fabricated_rate(monkeypatch):
    # Only 2 apps in the "31+ days" bucket: below MIN_SAMPLE. Two different
    # companies so there is no repost signal (that is a separate verdict path).
    apps = _fresh_bucket_apps(6, 4) + [
        _app("OldCo", "Analyst", status="rejected", posted_ago=60, applied_ago=25, responded=True),
        _app("OlderCo", "Designer", status="applied", posted_ago=70, applied_ago=30),
    ]
    _with_apps(monkeypatch, apps)
    monkeypatch.setattr(A, "_today", lambda: TODAY)
    posted = TODAY - timedelta(days=40)
    result = A.advise_for_job("StaleCo", "SWE", posted, None, apps, today=TODAY)
    assert result["verdict"] != "LOW PRIORITY"
    assert result["honesty_note"], "thin data must produce an honesty note"
    assert "Not enough data" in result["honesty_note"]
    # The note must appear in the human-readable output, not a made-up rate.
    out = _run_cmd(A.cmd_advise, SimpleNamespace(
        company="StaleCo", role="SWE", posted_date=posted.isoformat(),
        deadline=None, json=False))
    assert result["honesty_note"] in out


def test_low_priority_zero_response_decent_sample(monkeypatch):
    apps = _fresh_bucket_apps(6, 4)
    for i in range(6):
        apps.append(_app("LateCo", f"Ops {i}", status="rejected",
                         posted_ago=60, applied_ago=45, responded=True))
    _with_apps(monkeypatch, apps)
    posted = TODAY - timedelta(days=20)  # bucket "15-30 days"
    result = A.advise_for_job("LateCo", "Ops", posted, None, apps, today=TODAY)
    assert result["age_bucket"] == "15-30 days"
    assert result["verdict"] == "LOW PRIORITY"
    assert "0/6" in result["reasons"][0]


def test_consider_waiting_stale_with_repost_signal(monkeypatch):
    apps = _fresh_bucket_apps(6, 4) + [
        _app("ReCo", "DS", status="rejected", posted_ago=90, applied_ago=80, responded=True),
        _app("ReCo", "DS", status="applied", posted_ago=40, applied_ago=30),
    ]
    _with_apps(monkeypatch, apps)
    posted = TODAY - timedelta(days=45)
    result = A.advise_for_job("OtherCo", "SWE", posted, None, apps, today=TODAY)
    assert result["verdict"] == "CONSIDER WAITING"
    assert any("repost" in r.lower() for r in result["reasons"])


def test_best_bucket_covers_age_apply_now(monkeypatch):
    # User's best bucket is "8-14 days" (5/5 positive); posting is 10 days old.
    apps = []
    for i in range(5):
        apps.append(_app("MidCo", f"R{i}", status="offer",
                         posted_ago=30, applied_ago=20, responded=True))
    apps += _fresh_bucket_apps(6, 1)  # weak fresh bucket
    _with_apps(monkeypatch, apps)
    posted = TODAY - timedelta(days=10)
    result = A.advise_for_job("MidCo", "R", posted, None, apps, today=TODAY)
    assert result["verdict"] == "APPLY NOW"
    assert "best posting-age bucket" in result["reasons"][0]


def test_neutral_when_data_thin_and_not_fresh_or_stale(monkeypatch):
    apps = _fresh_bucket_apps(2, 1)  # thin everywhere
    _with_apps(monkeypatch, apps)
    posted = TODAY - timedelta(days=12)  # bucket "8-14 days", no data
    result = A.advise_for_job("ThinCo", "SWE", posted, None, apps, today=TODAY)
    assert result["verdict"] == "NEUTRAL"
    assert result["honesty_note"]


# ---------------------------------------------------------------------------
# deadline countdown
# ---------------------------------------------------------------------------

def test_deadline_countdown_math_and_urgency(monkeypatch):
    apps = _fresh_bucket_apps(6, 4)
    _with_apps(monkeypatch, apps)
    monkeypatch.setattr(A, "_today", lambda: TODAY)
    posted = TODAY - timedelta(days=2)
    deadline = TODAY + timedelta(days=5)
    result = A.advise_for_job("NewCo", "MLE", posted, deadline, apps, today=TODAY)
    assert result["days_until_deadline"] == 5
    assert "5 days left" in result["deadline_urgency"]
    out = _run_cmd(A.cmd_advise, SimpleNamespace(
        company="NewCo", role="MLE", posted_date=posted.isoformat(),
        deadline=deadline.isoformat(), json=False))
    assert "5 days left" in out


def test_deadline_today_and_passed():
    posted = TODAY - timedelta(days=2)
    today_dl = A.advise_for_job("C", "R", posted, TODAY, [], today=TODAY)
    assert today_dl["days_until_deadline"] == 0
    assert "today" in today_dl["deadline_urgency"].lower()
    past = A.advise_for_job("C", "R", posted, TODAY - timedelta(days=3), [], today=TODAY)
    assert past["days_until_deadline"] == -3
    assert past["verdict"] == "NEUTRAL"
    assert "Deadline passed" in past["reasons"][0]


# ---------------------------------------------------------------------------
# cmd_advise --json shape
# ---------------------------------------------------------------------------

def test_advise_json_shape(monkeypatch):
    import json as J
    apps = _fresh_bucket_apps(6, 4)
    _with_apps(monkeypatch, apps)
    monkeypatch.setattr(A, "_today", lambda: TODAY)
    out = _run_cmd(A.cmd_advise, SimpleNamespace(
        company="NewCo", role="MLE", posted_date="2026-09-20",
        deadline="2026-10-01", json=True))
    payload = J.loads(out)
    for key in ("verdict", "company", "role", "posted_date", "posting_age_days",
                "age_bucket", "deadline", "days_until_deadline", "reasons",
                "what_would_change_verdict", "honesty_note", "bucket_stats",
                "overall_response_rate", "repost_series_count"):
        assert key in payload, f"missing key {key}"
    assert payload["verdict"] == "APPLY NOW"
    assert payload["posting_age_days"] == 2
    assert set(payload["bucket_stats"]) == set(T.BUCKETS)


# ---------------------------------------------------------------------------
# reposts: detection + aggregates
# ---------------------------------------------------------------------------

def test_repost_series_detection_incl_notes_flag(monkeypatch):
    apps = [
        _app("Acme Corp", "Data Scientist", status="rejected",
             posted_ago=90, applied_ago=80, responded=True),
        _app("  acme corp ", "data scientist", status="applied",
             posted_ago=30, applied_ago=20),  # same series, messy case/space
        _app("SoloCo", "PM", status="applied", posted_ago=10, applied_ago=5,
             notes="Looks like a repost of the June listing"),
        _app("OtherCo", "SWE", status="applied", posted_ago=10, applied_ago=5),
    ]
    _with_apps(monkeypatch, apps)
    out = _run_cmd(A.cmd_reposts, SimpleNamespace(json=False))
    assert "2 repost series detected" in out
    assert "Acme Corp" in out and "Data Scientist" in out
    assert "flagged via notes" in out


def test_fresh_vs_repost_aggregates(monkeypatch):
    # 3 series: first postings 2/3 positive; repost applications 0/4 positive.
    apps = [
        _app("A", "R", status="offer", posted_ago=90, applied_ago=80, responded=True),
        _app("A", "R", status="rejected", posted_ago=40, applied_ago=30, responded=True),
        _app("B", "R", status="offer", posted_ago=90, applied_ago=80, responded=True),
        _app("B", "R", status="rejected", posted_ago=40, applied_ago=30, responded=True),
        _app("B", "R", status="rejected", posted_ago=20, applied_ago=10, responded=True),
        _app("C", "R", status="rejected", posted_ago=90, applied_ago=80, responded=True),
        _app("C", "R", status="rejected", posted_ago=40, applied_ago=30, responded=True),
    ]
    _with_apps(monkeypatch, apps)
    report = A.repost_report(apps)
    agg = report["aggregate"]
    assert agg["series_count"] == 3
    assert agg["first_postings"]["applications"] == 3
    assert agg["repost_applications"]["applications"] == 4
    assert abs(agg["first_postings"]["response_rate"] - 2 / 3) < 1e-9
    assert agg["repost_applications"]["response_rate"] == 0.0
    assert "Reposts convert at 0%" in report["guidance"]
    assert "67%" in report["guidance"]
    out = _run_cmd(A.cmd_reposts, SimpleNamespace(json=False))
    assert "First postings: 67%" in out
    assert "Reposts: 0%" in out


def test_reposts_empty_state(monkeypatch):
    import json as J
    apps = [_app("SoloCo", "PM", status="applied", posted_ago=10, applied_ago=5)]
    _with_apps(monkeypatch, apps)
    out = _run_cmd(A.cmd_reposts, SimpleNamespace(json=False))
    assert "No reposts detected" in out
    out_json = _run_cmd(A.cmd_reposts, SimpleNamespace(json=True))
    payload = J.loads(out_json)
    assert payload["series"] == []
    assert payload["aggregate"]["series_count"] == 0
    assert payload["guidance"]


def test_reposts_json_shape(monkeypatch):
    import json as J
    apps = [
        _app("Acme", "DS", status="rejected", posted_ago=90, applied_ago=80, responded=True),
        _app("Acme", "DS", status="selected_for_interview", posted_ago=30, applied_ago=20, responded=True),
    ]
    _with_apps(monkeypatch, apps)
    payload = J.loads(_run_cmd(A.cmd_reposts, SimpleNamespace(json=True)))
    s = payload["series"][0]
    for key in ("company", "role", "applications", "dates_applied", "statuses",
                "flagged_by_notes"):
        assert key in s, f"missing key {key}"
    assert s["applications"] == 2
    assert s["dates_applied"] == sorted(s["dates_applied"])


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------

def test_advise_bad_posted_date_exits(monkeypatch):
    _with_apps(monkeypatch, [])
    try:
        _run_cmd(A.cmd_advise, SimpleNamespace(
            company="C", role="R", posted_date="not-a-date",
            deadline=None, json=False))
    except SystemExit as e:
        assert "YYYY-MM-DD" in str(e.code)
    else:
        raise AssertionError("expected SystemExit for bad --posted-date")


def test_advise_missing_posted_date_exits(monkeypatch):
    _with_apps(monkeypatch, [])
    try:
        _run_cmd(A.cmd_advise, SimpleNamespace(
            company="C", role="R", posted_date=None, deadline=None, json=False))
    except SystemExit as e:
        assert "--posted-date" in str(e.code)
    else:
        raise AssertionError("expected SystemExit for missing --posted-date")


def test_real_tracker_file_isolation(monkeypatch, tmp_path):
    """Loading via a real tracker file (not monkeypatched) stays in tmp."""
    from candid import tracker as TR
    path = tmp_path / "tracker.json"
    TR._save([_app("FileCo", "R", status="applied", posted_ago=2, applied_ago=1)], path)
    monkeypatch.setattr(T, "load_applications", lambda: TR._load(path))
    apps = T.load_applications()
    assert len(apps) == 1 and apps[0]["company"] == "FileCo"
    assert path.read_text().strip(), "fixture tracker file must stay intact"
