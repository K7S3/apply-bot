"""Tests for candid.networking: one-page networking brief."""

from __future__ import annotations

import pytest

from candid import networking
from candid.networking import NetworkingError, build_brief, save_brief


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    return d


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
                    "Mentored 3 junior engineers",
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
        ],
        "education": [],
        "years_experience": 5.5,
        "seniority": "mid",
        "domains": ["data science", "ads / monetization"],
        "source_files": [],
    }


def test_brief_has_all_sections():
    brief = build_brief(sample_profile(), target_roles=["Senior ML Engineer"],
                        ask="An intro to the hiring manager for the ML role.")
    for section in ("## Who I am", "## Career highlights",
                    "## What I'm looking for", "## My ask",
                    "## Conversation starters"):
        assert section in brief
    assert "Senior ML Engineer" in brief
    assert "intro to the hiring manager" in brief


def test_brief_highlights_top_impact_bullets():
    brief = build_brief(sample_profile())
    # metric-bearing bullets should win the impact ranking
    assert "improved CTR by 12%" in brief
    assert "reducing churn 8%" in brief
    assert brief.count("\n- ") >= 3


def test_brief_no_targets_infers_and_labels():
    brief = build_brief(sample_profile())
    assert "(inferred)" in brief
    # no invented target companies
    for company in ("Google", "OpenAI", "Meta (target)"):
        assert company not in brief.split("## What I'm looking for")[1] \
            .split("## My ask")[0]


def test_brief_no_ask_uses_fill_in_placeholders():
    brief = build_brief(sample_profile())
    ask_section = brief.split("## My ask")[1].split("## Conversation starters")[0]
    assert "[fill in" in ask_section


def test_brief_starters_come_from_domains():
    brief = build_brief(sample_profile())
    starters = brief.split("## Conversation starters")[1]
    assert "ads" in starters.lower() or "ranking" in starters.lower()


def test_brief_rejects_empty_experience():
    with pytest.raises(NetworkingError):
        build_brief({"name": "X", "experience": []})


def test_save_brief_defaults_to_data_dir(data_dir):
    path = save_brief(sample_profile(), target_roles=["ML Engineer"])
    assert path == data_dir / "networking_brief.md"
    assert path.exists()
    assert "## Who I am" in path.read_text(encoding="utf-8")


def test_save_brief_explicit_path(tmp_path):
    dest = tmp_path / "brief.md"
    path = save_brief(sample_profile(), path=dest, ask="Coffee chat?")
    assert path == dest
    assert "Coffee chat?" in dest.read_text(encoding="utf-8")


def test_determinism():
    profile = sample_profile()
    assert build_brief(profile) == build_brief(profile)
