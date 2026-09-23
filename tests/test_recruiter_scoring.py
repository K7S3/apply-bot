"""Tests for candid/recruiter_scoring.py. Fictional fixtures only."""

from __future__ import annotations

import json
from datetime import date

import pytest

from candid import recruiter_scoring as rs

TODAY = date(2026, 9, 22)

RECRUITERS = {
    "Maya Chen": {"kind": "inhouse", "company": "Fictional Corp"},
    "Sam Rivers": {"kind": "agency", "firm": "Fictional Staffing"},
    "Lee Park": {"kind": "inhouse", "company": "Fictional Labs"},
    "No Touch Ned": {"kind": "agency", "firm": "Fictional Staffing"},
    "Ghost Recruiter": {"kind": "agency", "firm": "Fictional Staffing"},
}

THREADS = {
    "Maya Chen": [
        {"date": "2026-09-20", "channel": "email", "replied": True},
        {"date": "2026-09-10", "channel": "linkedin", "replied": True},
        {"date": "2026-08-01", "channel": "email", "replied": False},
        {"date": "2026-07-01", "channel": "email"},  # missing flag: unreplied
    ],
    "Sam Rivers": [
        {"date": "2026-09-21", "channel": "email", "replied": False},
        {"date": "2026-09-15", "channel": "email", "replied": False},
    ],
    "Lee Park": [
        {"date": "2026-06-01", "channel": "email", "replied": True},
    ],
    "Ghost Recruiter": [
        {"date": "2026-09-22", "channel": "email"},  # missing flag: unreplied
    ],
    "Threads Only Theo": [
        {"date": "2026-09-01", "channel": "email", "replied": True},
        {"date": "2026-08-01", "channel": "email", "replied": False},
    ],
}


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    (tmp_path / "recruiters.json").write_text(json.dumps(RECRUITERS))
    (tmp_path / "recruiter_threads.json").write_text(json.dumps(THREADS))
    return tmp_path


# --- response_rate ----------------------------------------------------------

def test_response_rate_zero_touches_returns_none(data_dir):
    assert rs.response_rate("No Touch Ned") is None
    assert rs.response_rate("Nobody At All") is None  # unknown recruiter


def test_response_rate_basic_fraction(data_dir):
    # Maya: 2 replies out of 4 touches (missing flag counts as unreplied)
    assert rs.response_rate("Maya Chen") == pytest.approx(0.5)
    assert rs.response_rate("Sam Rivers") == pytest.approx(0.0)


def test_response_rate_never_divides_by_zero(data_dir, tmp_path):
    (tmp_path / "recruiter_threads.json").write_text(json.dumps({"Maya Chen": []}))
    assert rs.response_rate("Maya Chen") is None


def test_response_rate_missing_files(data_dir, tmp_path, monkeypatch):
    (tmp_path / "recruiter_threads.json").unlink()
    assert rs.response_rate("Maya Chen") is None


# --- scorecard formula ------------------------------------------------------

def test_scorecard_keys_and_types(data_dir):
    card = rs.scorecard("Maya Chen", today=TODAY)
    assert card["recruiter"] == "Maya Chen"
    assert card["response_rate"] == pytest.approx(0.5)
    assert card["total_touches"] == 4
    assert card["replies"] == 2
    assert card["days_since_last_touch"] == 2
    assert card["kind"] == "inhouse"
    assert 0 <= card["worth_replying"] <= 100


def test_scorecard_formula_components(data_dir):
    # Maya: rr=0.5 -> 25; recency 2 days -> 20*(1-2/90); inhouse -> 15;
    # volume 4/10 -> 15*0.4 = 6
    card = rs.scorecard("Maya Chen", today=TODAY)
    expected = 0.5 * 50 + 20 * (1 - 2 / 90) + 15 + 15 * 4 / 10
    assert card["worth_replying"] == pytest.approx(expected, abs=0.01)


def test_scorecard_recency_stale_scores_zero(data_dir):
    # Lee Park: last touch 113 days ago, past the 90-day window.
    card = rs.scorecard("Lee Park", today=TODAY)
    expected = 1.0 * 50 + 0 + 15 + 15 * 1 / 10
    assert card["worth_replying"] == pytest.approx(expected, abs=0.01)


def test_scorecard_no_touches_still_valid(data_dir):
    card = rs.scorecard("No Touch Ned", today=TODAY)
    assert card["response_rate"] is None
    assert card["total_touches"] == 0
    assert card["replies"] == 0
    assert card["days_since_last_touch"] is None
    assert card["kind"] == "agency"
    # agency, no rate, no recency, no volume -> 0
    assert card["worth_replying"] == pytest.approx(0.0)


def test_scorecard_inhouse_bonus_difference(data_dir):
    inhouse = rs.scorecard("Lee Park", today=TODAY)["worth_replying"]
    # A hypothetical agency twin with identical touches gets 15 fewer points.
    assert inhouse - 15 == pytest.approx(
        1.0 * 50 + 0 + 0 + 15 * 1 / 10, abs=0.01)


def test_scorecard_volume_capped(data_dir, tmp_path):
    touches = [{"date": "2026-09-22", "replied": True} for _ in range(30)]
    threads = {"Busy Bee": touches}
    recruiters = {"Busy Bee": {"kind": "agency"}}
    (tmp_path / "recruiter_threads.json").write_text(json.dumps(threads))
    (tmp_path / "recruiters.json").write_text(json.dumps(recruiters))
    card = rs.scorecard("Busy Bee", today=TODAY)
    expected = 1.0 * 50 + 20 * 1.0 + 0 + 15 * 10 / 10  # volume capped at 10
    assert card["worth_replying"] == pytest.approx(expected, abs=0.01)
    assert card["worth_replying"] <= 100


def test_scorecard_determinism(data_dir):
    first = rs.scorecard("Maya Chen", today=TODAY)
    second = rs.scorecard("Maya Chen", today=TODAY)
    assert first == second


def test_scorecard_undated_touch_recency_zero(data_dir, tmp_path):
    threads = {"Undated Uma": [{"channel": "email", "replied": True}]}
    (tmp_path / "recruiter_threads.json").write_text(json.dumps(threads))
    card = rs.scorecard("Undated Uma", today=TODAY)
    assert card["days_since_last_touch"] is None
    # Undated touch still counts toward the reply rate; only recency is 0.
    assert card["worth_replying"] == pytest.approx(1.0 * 50 + 15 * 1 / 10,
                                                   abs=0.01)


# --- ranking ----------------------------------------------------------------

def test_rank_recruiters_order(data_dir):
    ranked = rs.rank_recruiters(today=TODAY)
    names = [c["recruiter"] for c in ranked]
    # All known recruiters present (union of both files).
    assert set(names) == {"Maya Chen", "Sam Rivers", "Lee Park",
                          "No Touch Ned", "Ghost Recruiter", "Threads Only Theo"}
    scores = [c["worth_replying"] for c in ranked]
    assert scores == sorted(scores, reverse=True)
    # Lee Park: 100% reply rate + inhouse bonus should top the list.
    assert names[0] == "Lee Park"
    assert names[1] == "Maya Chen"


def test_rank_recruiters_tie_broken_by_name(data_dir):
    ranked = rs.rank_recruiters(today=TODAY)
    for a, b in zip(ranked, ranked[1:]):
        if a["worth_replying"] == b["worth_replying"]:
            assert a["recruiter"] < b["recruiter"]


def test_rank_recruiters_limit(data_dir):
    ranked = rs.rank_recruiters(limit=2, today=TODAY)
    assert len(ranked) == 2
    assert ranked[0]["worth_replying"] >= ranked[1]["worth_replying"]


def test_rank_recruiters_deterministic(data_dir):
    assert rs.rank_recruiters(today=TODAY) == rs.rank_recruiters(today=TODAY)


# --- agency_vs_inhouse ------------------------------------------------------

def test_agency_vs_inhouse_values(data_dir):
    comp = rs.agency_vs_inhouse(today=TODAY)
    assert set(comp) == {"agency", "inhouse"}
    inhouse = comp["inhouse"]
    assert inhouse["count"] == 2  # Maya Chen, Lee Park
    assert inhouse["avg_response_rate"] == pytest.approx(0.75)  # (0.5 + 1.0)/2
    agency = comp["agency"]
    assert agency["count"] == 3  # Sam Rivers, No Touch Ned, Ghost Recruiter
    # Sam Rivers 0.0, Ghost Recruiter 0.0; No Touch Ned excluded (no touches)
    assert agency["avg_response_rate"] == pytest.approx(0.0)
    assert 0 <= agency["avg_worth_replying"] <= 100
    assert 0 <= inhouse["avg_worth_replying"] <= 100


def test_agency_vs_inhouse_empty_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    # No files at all: both groups present, counts 0, averages None.
    comp = rs.agency_vs_inhouse(today=TODAY)
    assert comp == {
        "agency": {"count": 0, "avg_response_rate": None,
                   "avg_worth_replying": None},
        "inhouse": {"count": 0, "avg_response_rate": None,
                    "avg_worth_replying": None},
    }


def test_agency_vs_inhouse_one_group_empty(data_dir, tmp_path):
    # Only in-house recruiters exist.
    (tmp_path / "recruiters.json").write_text(
        json.dumps({"Solo Inhouse": {"kind": "inhouse"}}))
    comp = rs.agency_vs_inhouse(today=TODAY)
    assert comp["agency"]["count"] == 0
    assert comp["agency"]["avg_response_rate"] is None
    assert comp["agency"]["avg_worth_replying"] is None
    assert comp["inhouse"]["count"] == 1
    assert comp["inhouse"]["avg_response_rate"] is None  # no touches
    assert comp["inhouse"]["avg_worth_replying"] == pytest.approx(15.0)  # bonus only


def test_rank_recruiters_empty_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    assert rs.rank_recruiters(today=TODAY) == []


def test_list_style_threads_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    threads = [
        {"recruiter": "Listy Lou", "date": "2026-09-22", "replied": True},
        {"recruiter": "Listy Lou", "date": "2026-09-21", "replied": False},
    ]
    (tmp_path / "recruiter_threads.json").write_text(json.dumps(threads))
    assert rs.response_rate("Listy Lou") == pytest.approx(0.5)
