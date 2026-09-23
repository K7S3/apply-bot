"""Tests for candid.jobs_remote_filters (remote-job curation filters).

Run: python -m pytest tests/test_remote_filters.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.jobs_remote_filters import (  # noqa: E402
    normalize_remote_location,
    remote_only_filter,
    remote_keyword_boost,
    remote_rank_adjust,
)


def _job(title="Engineer", location="", remote=False, description=""):
    return {"title": title, "company": "Acme", "location": location,
            "remote": remote, "description": description}


# ---------------------------------------------------------------------------
# normalize_remote_location
# ---------------------------------------------------------------------------

def test_bucket_mapping_anywhere():
    for loc in ("Worldwide", "worldwide", "Anywhere", "Remote (anywhere)",
                "Global", "Work from anywhere", "Fully remote",
                "Remote", "remote", "REMOTE", "Remote-friendly",
                "Location-independent", "100% Remote", "Remotely"):
        assert normalize_remote_location(loc) == "anywhere", loc


def test_bucket_mapping_us_only():
    for loc in ("US", "us", "U.S.", "USA", "United States",
                "Remote - US", "Remote-US", "Remote in US",
                "Remote (US Only)", "US Only", "United States only",
                "US-based", "US Remote", "American"):
        assert normalize_remote_location(loc) == "us-only", loc


def test_bucket_mapping_americas():
    for loc in ("Americas", "North America", "LATAM", "Latin America",
                "Remote - Americas"):
        assert normalize_remote_location(loc) == "americas", loc


def test_bucket_mapping_emea():
    for loc in ("EMEA", "emea", "Remote - EMEA"):
        assert normalize_remote_location(loc) == "emea", loc


def test_bucket_mapping_europe():
    for loc in ("Europe", "EU only", "EU", "European Union",
                "Remote - Europe", "UK", "United Kingdom", "EU-based"):
        assert normalize_remote_location(loc) == "europe", loc


def test_bucket_mapping_apac():
    for loc in ("APAC", "apac", "Asia-Pacific", "Remote - APAC", "Australia"):
        assert normalize_remote_location(loc) == "apac", loc


def test_bucket_mapping_hybrid():
    for loc in ("Hybrid", "hybrid", "New York (Hybrid)",
                "Hybrid - 2 days in office"):
        assert normalize_remote_location(loc) == "hybrid", loc


def test_bucket_mapping_onsite():
    for loc in ("On-site", "Onsite", "In office", "Office-based",
                "New York, NY (On-site)", "In-person", "Work from office",
                "Must be in the office"):
        assert normalize_remote_location(loc) == "onsite", loc


def test_city_anchored_remote_is_unknown():
    for loc in ("New York (Remote)", "San Francisco, CA - Remote",
                "Berlin (Remote)", "Remote, London"):
        assert normalize_remote_location(loc) == "unknown", loc


def test_empty_and_plain_places_are_unknown():
    for loc in ("", "   ", "New York, NY", "Berlin, Germany", "London"):
        assert normalize_remote_location(loc) == "unknown", loc


def test_hybrid_wins_over_remote_qualifier():
    assert normalize_remote_location("Remote / Hybrid") == "hybrid"


def test_onsite_wins_over_remote_qualifier():
    assert normalize_remote_location("Remote, on-site interviews") == "onsite"


def test_none_location_is_unknown():
    assert normalize_remote_location(None) == "unknown"


# ---------------------------------------------------------------------------
# remote_only_filter
# ---------------------------------------------------------------------------

def test_filter_keeps_clear_remote_jobs():
    jobs = [
        _job("A", "Worldwide", True),
        _job("B", "Remote - US", True),
        _job("C", "EMEA", True),
        _job("D", "Remote", True),
    ]
    kept = remote_only_filter(jobs)
    assert [j["title"] for j in kept] == ["A", "B", "C", "D"]


def test_filter_drops_remote_false():
    jobs = [_job("A", "Worldwide", False), _job("B", "Remote", False)]
    assert remote_only_filter(jobs) == []


def test_filter_drops_remote_true_but_onsite_bucket():
    # Per spec, only "onsite"/"unknown" buckets are excluded; "hybrid" passes
    # (a hybrid role is still partially remote).
    jobs = [_job("A", "New York, NY (On-site)", True),
            _job("B", "Hybrid", True)]
    kept = remote_only_filter(jobs)
    assert [j["title"] for j in kept] == ["B"]


def test_filter_drops_remote_true_but_unknown_bucket():
    # Strict curation: city-anchored "remote" without a resolvable region is out.
    jobs = [_job("A", "New York (Remote)", True),
            _job("B", "Berlin, Germany", True)]
    assert remote_only_filter(jobs) == []


def test_filter_drops_unknown_location_with_remote_true():
    assert remote_only_filter([_job("A", "", True)]) == []


def test_filter_keeps_order_and_ignores_extra_keys():
    jobs = [_job("Z", "APAC", 1), _job("Y", "Americas", "yes")]
    kept = remote_only_filter(jobs)
    assert [j["title"] for j in kept] == ["Z", "Y"]


# ---------------------------------------------------------------------------
# remote_keyword_boost
# ---------------------------------------------------------------------------

def test_boost_range():
    for title, desc in [
        ("", ""),
        ("Backend Engineer", "Work from anywhere. Async team. Fully remote."),
        ("X", "Must be in office. Hybrid 3 days."),
        ("Engineer", "x" * 4000),
    ]:
        b = remote_keyword_boost(title, desc)
        assert 0.0 <= b <= 1.0, (title, desc[:30], b)


def test_boost_monotonic_in_signals():
    base = ("Engineer", "Great team, good pay.")
    more = ("Engineer", "Great team. Fully remote, distributed team, "
                         "async communication, home office stipend, flexible hours.")
    assert remote_keyword_boost(*more) > remote_keyword_boost(*base)


def test_boost_zero_without_signals():
    assert remote_keyword_boost("Backend Engineer", "Great team, good pay.") == 0.0


def test_boost_positive_signals():
    b = remote_keyword_boost(
        "Senior Engineer (Remote-first)",
        "We are a distributed team working async. Work from anywhere; "
        "no office. Home office stipend and flexible hours.")
    assert b > 0.4


def test_boost_red_flags_dampen():
    friendly = "Fully remote, distributed team, async, flexible hours."
    flagged = friendly + " Must be in office. Hybrid 3 days."
    b_friendly = remote_keyword_boost("Engineer", friendly)
    b_flagged = remote_keyword_boost("Engineer", flagged)
    assert 0.0 <= b_flagged < b_friendly


def test_boost_single_signal_counts_once():
    once = remote_keyword_boost("E", "async async async async")
    twice = remote_keyword_boost("E", "async, distributed team")
    assert twice > once  # presence-based, not count-based


def test_boost_handles_none_inputs():
    assert 0.0 <= remote_keyword_boost(None, None) <= 1.0


# ---------------------------------------------------------------------------
# remote_rank_adjust
# ---------------------------------------------------------------------------

def test_adjust_adds_boost_points():
    job = _job("Engineer", "Worldwide", True,
               "Fully remote, distributed team, async. Work from anywhere.")
    boost = remote_keyword_boost(job["title"], job["description"])
    adjusted = remote_rank_adjust(70.0, job)
    assert adjusted == min(100.0, 70.0 + boost * 10.0)
    assert adjusted > 70.0


def test_adjust_leaves_plain_jobs_unchanged():
    job = _job("Engineer", "Worldwide", True, "Great team, good pay.")
    assert remote_rank_adjust(70.0, job) == 70.0


def test_adjust_clamps_high():
    job = _job("Engineer", "Worldwide", True,
               "Fully remote, remote-first, distributed team, async, "
               "work from anywhere, no office, home office stipend, "
               "flexible hours.")
    assert remote_rank_adjust(98.0, job) == 100.0


def test_adjust_clamps_low_and_accepts_edges():
    job = _job("Engineer", "Worldwide", True, "")
    assert remote_rank_adjust(-5.0, job) == 0.0
    assert remote_rank_adjust(0.0, job) == 0.0
    assert remote_rank_adjust(100.0, job) == 100.0


def test_adjust_is_non_decreasing_in_boost():
    plain = _job("E", "Worldwide", True, "Good team.")
    friendly = _job("E", "Worldwide", True,
                    "Fully remote, distributed team, async, flexible hours.")
    assert remote_rank_adjust(60.0, friendly) >= remote_rank_adjust(60.0, plain)
