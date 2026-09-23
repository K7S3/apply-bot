"""Tests for candid.jobs_tz — timezone window inference and overlap math."""

import copy

import pytest

from candid import config as C
from candid import jobs_tz as TZ


def _win(label, lo, hi, conf="high"):
    return {"label": label, "utc_offsets": (lo, hi), "confidence": conf}


# ---------------------------------------------------------------------------
# infer_tz_window
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location,description,lo,hi,conf", [
    # US patterns
    ("Remote, US", "Work across US timezones", -8, -4, "high"),
    ("Remote", "Must overlap PST-EST business hours", -8, -4, "high"),
    ("Remote", "Working hours PT to ET", -8, -4, "high"),
    ("Remote", "Pacific to Eastern coverage", -8, -4, "high"),
    ("Remote", "Keep US hours for standups", -8, -4, "medium"),
    # EMEA / CET
    ("Remote, EMEA", "", 0, 4, "medium"),
    ("Remote", "CET timezone preferred", 0, 4, "medium"),
    ("Remote", "Serving Europe-based clients", 0, 4, "medium"),
    # APAC
    ("Remote, APAC", "", 8, 12, "medium"),
    # anywhere / async / worldwide
    ("Remote", "Work from anywhere, async team", -12, 14, "medium"),
    ("Remote", "Worldwide remote role", -12, 14, "medium"),
    # GMT literals
    ("Remote", "Must be available GMT+5 hours", 5, 5, "high"),
    ("Remote", "Overlap UTC-5 to UTC+1 required", -5, 1, "high"),
    ("Remote", "Working window GMT-8 to GMT-5", -8, -5, "high"),
    # overlap with <city>
    ("Remote", "Need 4h overlap with London team", 0, 0, "high"),
    ("Remote", "Daily overlap with Singapore", 8, 8, "high"),
    ("Remote", "Overlap with the New York office", -5, -5, "high"),
])
def test_infer_tz_window(location, description, lo, hi, conf):
    w = TZ.infer_tz_window(location, description)
    assert w["utc_offsets"] == (lo, hi), w
    assert w["confidence"] == conf, w
    assert isinstance(w["label"], str) and w["label"]


@pytest.mark.parametrize("location,description", [
    ("Remote (New York)", ""),
    ("Onsite, San Francisco", "Come into the office daily"),
    ("", ""),
    ("Hybrid, Berlin", ""),
])
def test_infer_tz_window_unknown(location, description):
    w = TZ.infer_tz_window(location, description)
    assert w["utc_offsets"] is None
    assert w["confidence"] == "low"


def test_infer_tz_window_gmt_range_reversed():
    w = TZ.infer_tz_window("Remote", "GMT+3 to GMT-2")
    assert w["utc_offsets"] == (-2, 3)


# ---------------------------------------------------------------------------
# working_overlap_hours
# ---------------------------------------------------------------------------

def test_overlap_ny_vs_us_window_strong():
    hours = TZ.working_overlap_hours("America/New_York",
                                     _win("us", -8, -4))
    assert hours == 8


def test_overlap_ny_vs_apac_none():
    hours = TZ.working_overlap_hours("America/New_York",
                                     _win("apac", 8, 12))
    assert hours == 0


def test_overlap_ny_vs_emea_workable():
    hours = TZ.working_overlap_hours("America/New_York",
                                     _win("emea", 0, 4))
    assert hours == 3


def test_overlap_london_vs_emea_strong():
    assert TZ.working_overlap_hours("Europe/London", _win("emea", 0, 4)) == 8


def test_overlap_sydney_vs_apac_strong():
    assert TZ.working_overlap_hours("Australia/Sydney", _win("apac", 8, 12)) == 8


def test_overlap_sydney_vs_us_none():
    assert TZ.working_overlap_hours("Australia/Sydney", _win("us", -8, -4)) == 0


def test_overlap_tokyo_vs_anywhere_partial():
    hours = TZ.working_overlap_hours("Asia/Tokyo", _win("any", -12, 14))
    assert 0 <= hours <= 8
    assert hours == 8  # UTC-3..31 covers Tokyo's 9-17 (+9 -> 18..26)


def test_overlap_hours_bounds():
    hours = TZ.working_overlap_hours("America/New_York", _win("x", -12, 14))
    assert 0 <= hours <= 8


def test_overlap_invalid_tz_raises():
    with pytest.raises(ValueError, match="[Tt]imezone"):
        TZ.working_overlap_hours("Not/A_Zone", _win("us", -8, -4))


def test_overlap_empty_string_tz_raises():
    with pytest.raises(ValueError):
        TZ.working_overlap_hours("", _win("us", -8, -4))


def test_overlap_none_window_raises():
    with pytest.raises(ValueError, match="no usable"):
        TZ.working_overlap_hours("America/New_York",
                                 {"label": "unknown", "utc_offsets": None,
                                  "confidence": "low"})


# ---------------------------------------------------------------------------
# overlap_verdict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hours,expected", [
    (8, "strong"), (6, "strong"), (5, "strong"),
    (4, "workable"), (3, "workable"),
    (2, "tight"), (1, "tight"),
    (0, "none"),
])
def test_overlap_verdict_boundaries(hours, expected):
    assert TZ.overlap_verdict(hours) == expected


# ---------------------------------------------------------------------------
# enrich_with_tz
# ---------------------------------------------------------------------------

def test_enrich_adds_keys_without_mutating():
    job = {"title": "ML Engineer", "company": "Acme",
           "location": "Remote, US",
           "description": "Work across US timezones. Async-first."}
    before = copy.deepcopy(job)
    out = TZ.enrich_with_tz(job, "America/New_York")
    assert job == before  # input untouched
    assert out["tz_window"]["utc_offsets"] == (-8, -4)
    assert out["tz_overlap_hours"] == 8
    assert out["tz_verdict"] == "strong"


def test_enrich_unknown_window():
    job = {"title": "ML Engineer", "company": "Acme",
           "location": "Onsite, Berlin", "description": ""}
    out = TZ.enrich_with_tz(job, "America/New_York")
    assert out["tz_window"]["utc_offsets"] is None
    assert out["tz_overlap_hours"] == 0
    assert out["tz_verdict"] == "none"


def test_enrich_apac_job_for_ny():
    job = {"title": "Data Scientist", "company": "Acme",
           "location": "Remote", "description": "APAC coverage needed"}
    out = TZ.enrich_with_tz(job, "America/New_York")
    assert out["tz_overlap_hours"] == 0
    assert out["tz_verdict"] == "none"


# ---------------------------------------------------------------------------
# home_tz_from_config
# ---------------------------------------------------------------------------

def test_home_tz_config_key_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("TZ", raising=False)
    C.save_config({"home_timezone": "Europe/Berlin"})
    assert TZ.home_tz_from_config() == "Europe/Berlin"


def test_home_tz_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("TZ", "Asia/Singapore")
    assert TZ.home_tz_from_config() == "Asia/Singapore"


def test_home_tz_default_new_york(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("TZ", raising=False)
    # fresh config has no home_timezone key
    assert TZ.home_tz_from_config() == "America/New_York"


def test_home_tz_missing_config_never_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_PATH",
                        tmp_path / "does-not-exist" / "config.json")
    monkeypatch.delenv("TZ", raising=False)
    assert TZ.home_tz_from_config() == "America/New_York"
