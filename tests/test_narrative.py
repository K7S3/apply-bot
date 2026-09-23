"""Tests for candid.narrative: career narrative builder."""

from __future__ import annotations

import re

import pytest

from candid import narrative
from candid.narrative import (
    NarrativeError,
    build_narrative,
    elevator_pitch,
    story_arc,
)


def sample_profile() -> dict:
    return {
        "name": "Keshavan Seshadri",
        "headline": "Machine Learning Engineer",
        "location": "New York, NY",
        "summary": "",
        "skills": ["python", "machine learning", "sql", "llm"],
        "experience": [
            {
                "title": "Software Engineer, Machine Learning",
                "company": "Meta",
                "dates": "2026 - Present",
                "bullets": [
                    "Built an ads ranking model that improved CTR by 12%",
                    "Led migration of training pipelines to PyTorch",
                ],
            },
            {
                "title": "Data Scientist",
                "company": "StartupX",
                "dates": "2023 - 2026",
                "bullets": [
                    "Shipped churn prediction model reducing churn 8%",
                    "Wrote SQL dashboards for the product team",
                ],
            },
            {
                "title": "Software Engineer",
                "company": "ConsultCo",
                "dates": "2021 - 2023",
                "bullets": ["Built internal tools in python"],
            },
        ],
        "education": [],
        "years_experience": 5.5,
        "seniority": "mid",
        "domains": ["data science", "ads / monetization"],
        "source_files": [],
    }


def test_narrative_contains_all_employers_in_order():
    text = build_narrative(sample_profile(), length="2min")
    # present role comes first ...
    assert text.index("Meta") < text.index("ConsultCo")
    # ... then the past arc runs oldest -> newest
    past = text.split("## Past")[1]
    assert past.index("ConsultCo") < past.index("StartupX") < past.index("Meta")


def test_narrative_no_invented_transition_reasons():
    text = build_narrative(sample_profile(), length="2min")
    low = text.lower()
    # transitions must be neutral: no invented reasons for leaving
    for phrase in ("fired", "laid off", "quit because", "better offer",
                   "higher salary", "promotion", "wanted to leave",
                   "looking for a new challenge", "toxic"):
        assert phrase not in low
    # allowed neutral phrasing
    assert "moved to" in low


def test_narrative_focus_clause_only_when_evidenced():
    # every "to focus on X" clause must be grounded: X appears in the
    # *next* role's title/bullets, otherwise the transition stays neutral
    profile = sample_profile()
    text = build_narrative(profile, length="2min")
    assert "to focus on" in text.lower()
    for m in re.finditer(r"to focus on (\w[\w ]*?)[.\n]", text):
        skill = m.group(1).strip().lower()
        nxt_text = " ".join(
            (e.get("title") or "") + " " + " ".join(
                str(b) for b in (e.get("bullets") or []))
            for e in profile["experience"]
        ).lower()
        assert skill in nxt_text, f"ungrounded focus clause: {skill}"


def test_narrative_lengths_have_word_budgets():
    short = build_narrative(sample_profile(), length="60s")
    long = build_narrative(sample_profile(), length="2min")
    assert len(short.split()) <= 160
    assert len(long.split()) <= 330
    assert len(short.split()) < len(long.split())


def test_narrative_future_uses_target_roles_or_placeholder():
    profile = sample_profile()
    profile["target_roles"] = ["Staff ML Engineer"]
    assert "Staff ML Engineer" in build_narrative(profile)
    profile2 = sample_profile()
    assert "[fill in" in build_narrative(profile2)


def test_narrative_rejects_unknown_length():
    with pytest.raises(NarrativeError):
        build_narrative(sample_profile(), length="10min")


def test_narrative_rejects_empty_experience():
    with pytest.raises(NarrativeError):
        build_narrative({"name": "X", "experience": []})


def test_story_arc_through_line():
    arc = story_arc(sample_profile())
    assert "Software Engineer" in arc
    assert "Data Scientist" in arc
    assert "Software Engineer, Machine Learning" in arc
    assert "data science" in arc or "machine learning" in arc


def test_story_arc_rejects_empty():
    with pytest.raises(NarrativeError):
        story_arc({"experience": []})


@pytest.mark.parametrize("audience", ["recruiter", "hiring-manager", "networking"])
def test_elevator_pitch_variants(audience):
    pitch = elevator_pitch(sample_profile(), audience=audience)
    assert pitch.strip()
    assert "Meta" in pitch or "Machine Learning" in pitch


def test_elevator_pitch_rejects_unknown_audience():
    with pytest.raises(NarrativeError):
        elevator_pitch(sample_profile(), audience="journalist")


def test_determinism():
    profile = sample_profile()
    assert build_narrative(profile) == build_narrative(profile)
    assert story_arc(profile) == story_arc(profile)
    assert elevator_pitch(profile) == elevator_pitch(profile)
