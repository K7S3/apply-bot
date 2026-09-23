"""Tests for candid.mission_fit: taxonomy sanity, classifier accuracy,
mission_fit_score behavior, and render output."""

from __future__ import annotations

import pytest

from candid.mission_fit import (
    CAUSE_AREAS,
    classify_causes,
    mission_fit_score,
    render_mission_fit,
)

EDUCATION_JD = """About us: Bright Futures is a nonprofit dedicated to educational
equity for underserved communities. We partner with public schools to improve
literacy and classroom outcomes.
The role: As a backend engineer you will build our tutoring platform used by
teachers and students. You will work with the curriculum team to add
scholarship application tracking and mentor matching for K-12 programs."""

CLIMATE_JD = """About us: GreenGrid is a climate nonprofit tackling climate change
through renewable energy deployment. Our solar programs cut carbon emissions
and advance sustainability in frontline communities.
The role: Data engineer needed to model biodiversity impacts and build our
recycling and clean energy dashboards supporting conservation efforts."""

SAAS_JD = """About the company: Acme Cloud is a Series C B2B SaaS platform for
sales teams. We offer competitive pay, equity, and great benefits.
Responsibilities: Build and scale our billing microservices on Kubernetes,
own CI/CD pipelines, and partner with product on feature launches.
Requirements: 5+ years of Python, experience with Postgres and Redis."""


# ---------------------------------------------------------------------------
# taxonomy sanity
# ---------------------------------------------------------------------------

EXPECTED_AREAS = {
    "education", "health", "climate_environment", "human_rights",
    "poverty_hunger", "disaster_relief", "animals", "arts_culture",
    "economic_development", "peace_conflict", "gender_equality",
    "tech_for_good",
}


def test_taxonomy_has_expected_areas():
    assert set(CAUSE_AREAS.keys()) == EXPECTED_AREAS


def test_every_area_has_at_least_ten_keywords():
    for area, keywords in CAUSE_AREAS.items():
        assert len(keywords) >= 10, f"{area} has only {len(keywords)} keywords"


def test_keywords_lowercase_and_unique_within_area():
    for area, keywords in CAUSE_AREAS.items():
        lowered = [kw.strip().lower() for kw in keywords]
        assert keywords == lowered, f"{area} has non-lowercase/unstripped keywords"
        assert len(set(lowered)) == len(lowered), f"{area} has duplicate keywords"


# ---------------------------------------------------------------------------
# classifier
# ---------------------------------------------------------------------------

def test_education_jd_scores_education_top():
    scored = classify_causes(EDUCATION_JD)
    assert scored, "expected cause hits for the education JD"
    assert scored[0][0] == "education"
    assert 0 < scored[0][1] <= 1.0


def test_climate_jd_scores_climate_top():
    scored = classify_causes(CLIMATE_JD)
    assert scored, "expected cause hits for the climate JD"
    assert scored[0][0] == "climate_environment"


def test_generic_saas_jd_is_weak_or_empty():
    scored = classify_causes(SAAS_JD)
    assert all(score < 0.15 for _, score in scored), scored


def test_classifier_is_sorted_descending_and_deterministic():
    first = classify_causes(EDUCATION_JD)
    second = classify_causes(EDUCATION_JD)
    assert first == second
    scores = [s for _, s in first]
    assert scores == sorted(scores, reverse=True)


def test_empty_text_yields_no_causes():
    assert classify_causes("") == []
    assert classify_causes("   ") == []


# ---------------------------------------------------------------------------
# mission_fit_score
# ---------------------------------------------------------------------------

def test_no_cause_interests_returns_none_score():
    result = mission_fit_score(EDUCATION_JD, {})
    assert result["score"] is None
    assert result["note"] == "set cause interests to enable mission-fit scoring"
    assert result["top_jd_causes"][0] == "education"


def test_overlap_drives_score():
    profile = {"cause_interests": ["education"]}
    result = mission_fit_score(EDUCATION_JD, profile)
    assert result["score"] is not None and 0 <= result["score"] <= 100
    assert "education" in result["matched_causes"]
    # same JD with a non-overlapping interest must score lower
    other = mission_fit_score(EDUCATION_JD, {"cause_interests": ["animals"]})
    assert other["score"] is not None
    assert result["score"] > other["score"]


def test_overlap_math_matches_documented_formula():
    jd_causes = classify_causes(EDUCATION_JD)
    interests = ["education"]
    matched = [(a, s) for a, s in jd_causes if a in interests]
    overlap = sum(s for _, s in matched) / len(matched)
    clarity = sum(s for _, s in jd_causes[:3]) / min(3, len(jd_causes))
    expected = round(60 * overlap + 40 * clarity)
    result = mission_fit_score(EDUCATION_JD, {"cause_interests": interests})
    assert result["score"] == expected


def test_no_jd_signal_scores_zero_and_notes_for_profit():
    result = mission_fit_score(SAAS_JD, {"cause_interests": ["education"]})
    scored = classify_causes(SAAS_JD)
    if not scored:
        assert result["score"] == 0
        assert "for-profit" in result["note"]


def test_weak_but_nonzero_jd_signal_scores_low():
    jd = "We build dashboards. Our team values sustainability in the office."
    result = mission_fit_score(jd, {"cause_interests": ["climate_environment"]})
    assert result["score"] is not None and result["score"] <= 40


def test_unknown_interest_keys_are_ignored():
    profile = {"cause_interests": ["education", "not_a_real_area"]}
    result = mission_fit_score(EDUCATION_JD, profile)
    assert "not_a_real_area" not in result["matched_causes"]
    assert "education" in result["matched_causes"]


def test_missing_cause_interests_key_treated_as_none():
    result = mission_fit_score(EDUCATION_JD, {"name": "Keshavan"})
    assert result["score"] is None


@pytest.mark.parametrize("jd,interest,area", [
    (EDUCATION_JD, ["education"], "education"),
    (CLIMATE_JD, ["climate_environment"], "climate_environment"),
])
def test_end_to_end_match_parametrized(jd, interest, area):
    result = mission_fit_score(jd, {"cause_interests": interest})
    assert result["score"] is not None and result["score"] > 0
    assert area in result["matched_causes"]
    assert result["top_jd_causes"][0] == area


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_render_contains_key_lines():
    result = mission_fit_score(EDUCATION_JD, {"cause_interests": ["education"]})
    out = render_mission_fit(result)
    assert "Mission fit" in out
    assert f"score: {result['score']}/100" in out
    assert "education" in out
    assert "note:" in out


def test_render_handles_none_score():
    result = mission_fit_score(EDUCATION_JD, {})
    out = render_mission_fit(result)
    assert "score: n/a" in out
    assert "set cause interests" in out
