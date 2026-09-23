"""Tests for candid/drafting/scheduler.py (follow-up suggestions).

pytest-style with tmp_path fixtures. Output-only: never sends, never
mutates the tracker file. Uses a fixed "today" so days_stale is exact.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from candid.drafting import scheduler as S  # noqa: E402

TODAY = date(2026, 9, 22)


def _app(app_id, company, status, days_ago, role="ML Engineer"):
    d = TODAY - timedelta(days=days_ago)
    return {
        "id": app_id,
        "company": company,
        "role": role,
        "status": status,
        "notes": "",
        "date_added": d.isoformat(),
        "date_updated": d.isoformat(),
        "prep_pack": "",
    }


@pytest.fixture()
def apps():
    return [
        _app(1, "Acme", "applied", 16),
        _app(2, "Freshco", "applied", 1),          # fresh: skipped
        _app(3, "InterviewInc", "selected_for_interview", 6),  # interview ladder
        _app(4, "SavedCorp", "saved", 30),         # wrong status: skipped
        _app(5, "RejectedLtd", "rejected", 30),    # wrong status: skipped
        _app(6, "OfferCo", "offer", 9),            # offer: slower ladder
    ]


@pytest.fixture()
def tracker_json(tmp_path, apps):
    p = tmp_path / "tracker.json"
    p.write_text(json.dumps(apps), encoding="utf-8")
    return p


def test_output_shape_and_fields(apps):
    out = S.suggest_followups(apps, today=TODAY)
    assert all(set(s) >= {"app_id", "company", "role", "days_stale",
                          "ladder", "suggested_subject"} for s in out)
    for s in out:
        assert isinstance(s["ladder"], dict)
        assert set(s["ladder"]) >= {"rung", "rung_name", "tone", "guidance"}
        assert isinstance(s["suggested_subject"], str) and s["suggested_subject"]


def test_skips_fresh_apps(apps):
    out = S.suggest_followups(apps, today=TODAY)
    assert all(s["days_stale"] >= 3 for s in out)
    assert {s["company"] for s in out} == {"Acme", "InterviewInc", "OfferCo"}


def test_correct_rungs():
    apps = [
        _app(1, "Acme", "applied", 16),
        _app(2, "InterviewInc", "selected_for_interview", 6),  # eff 8 -> rung 2
        _app(3, "OfferCo", "offer", 9),  # eff 6 -> rung 1
    ]
    out = {s["app_id"]: s for s in S.suggest_followups(apps, today=TODAY)}
    assert out[1]["ladder"]["rung"] == 3
    assert out[1]["days_stale"] == 16
    assert out[2]["ladder"]["rung"] == 2
    assert out[3]["ladder"]["rung"] == 1


def test_sorted_most_stale_first(apps):
    out = S.suggest_followups(apps, today=TODAY)
    stales = [s["days_stale"] for s in out]
    assert stales == sorted(stales, reverse=True)


def test_accepts_tracker_json_path(tracker_json):
    out = S.suggest_followups(tracker_json, today=TODAY)
    assert {s["company"] for s in out} == {"Acme", "InterviewInc", "OfferCo"}


def test_never_mutates_tracker_file(tracker_json):
    before = tracker_json.read_text(encoding="utf-8")
    S.suggest_followups(tracker_json, today=TODAY)
    assert tracker_json.read_text(encoding="utf-8") == before


def test_never_mutates_app_dicts(apps):
    snapshot = json.dumps(apps)
    S.suggest_followups(apps, today=TODAY)
    assert json.dumps(apps) == snapshot


def test_config_overrides():
    apps = [_app(1, "Acme", "applied", 16), _app(2, "Other", "saved", 30)]
    out = S.suggest_followups(apps, today=TODAY,
                              config={"eligible_statuses": {"applied"},
                                      "fresh_days": 20})
    assert out == []  # 16d is below the custom 20d fresh threshold
    out = S.suggest_followups(apps, today=TODAY,
                              config={"eligible_statuses": {"saved"},
                                      "fresh_days": 3})
    assert len(out) == 1 and out[0]["company"] == "Other"


def test_unparseable_dates_are_skipped():
    bad = _app(1, "Acme", "applied", 16)
    bad["date_updated"] = "not-a-date"
    bad["date_added"] = ""
    assert S.suggest_followups([bad], today=TODAY) == []


def test_suggested_subject_matches_rung_draft():
    apps = [_app(1, "Acme", "applied", 16)]
    s = S.suggest_followups(apps, today=TODAY)[0]
    assert "Acme" in s["suggested_subject"]
    assert "ML Engineer" in s["suggested_subject"]
    assert s["suggested_subject"].startswith("Next steps")
