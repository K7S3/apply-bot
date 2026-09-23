"""Tests for candid.narrative_arc (batch 82a).

Pattern: point CANDID_DATA_DIR at a throwaway dir BEFORE importing candid
modules, then rebind C.DATA_DIR / C.PROFILE_PATH per-test with monkeypatch
so same-process runs stay isolated.
"""
import json
import os
import tempfile

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-narr-test-"))

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from candid import config as C  # noqa: E402
from candid import narrative_arc as NA  # noqa: E402


def _rich_profile() -> dict:
    return {
        "name": "Alex Rivera",
        "headline": "Machine Learning Engineer",
        "location": "New York, NY",
        "summary": "ML engineer with five years of experience.",
        "skills": ["python", "machine learning", "sql", "spark", "mlops"],
        "experience": [
            {"title": "Machine Learning Engineer", "company": "Meridian Financial",
             "dates": "2022 - Present",
             "bullets": [
                 "Shipped a churn prediction model that reduced customer attrition by 12 percent.",
                 "Led migration of batch scoring pipelines to Spark, cutting nightly runtime by 40 percent.",
                 "Built experimentation dashboards used by three product teams to track model impact.",
                 "Mentored two junior engineers on model evaluation and code review practices.",
             ]},
            {"title": "Data Analyst", "company": "Northwind Traders",
             "dates": "2020 - 2022",
             "bullets": [
                 "Automated weekly revenue reporting, saving roughly ten hours of manual work per month.",
                 "Partnered with marketing to run A/B tests that lifted email conversion by 8 percent.",
                 "Cleaned and documented core sales datasets used across the analytics team.",
             ]},
            {"title": "Junior Developer", "company": "Brightline Media",
             "dates": "2019 - 2020",
             "bullets": [
                 "Built internal dashboards that cut ad-hoc reporting requests in half.",
                 "Fixed a long-standing data duplication bug in the ETL job.",
             ]},
        ],
        "education": [
            {"school": "State University", "degree": "B.S. Computer Science", "dates": "2015 - 2019"}
        ],
        "years_experience": 5.5,
        "seniority": "mid",
        "domains": ["data science"],
        "target_roles": ["Staff Machine Learning Engineer"],
        "source_files": [],
    }


def _sparse_profile() -> dict:
    return {
        "name": "Jane Doe",
        "headline": "",
        "location": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "years_experience": 0.0,
        "seniority": "entry",
    }


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Fresh temp data dir with a rich profile.json written into it."""
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    monkeypatch.setattr(C, "PROFILE_PATH", tmp_path / "profile.json")
    (tmp_path / "profile.json").write_text(json.dumps(_rich_profile()), encoding="utf-8")
    return tmp_path


@pytest.fixture
def empty_dir(tmp_path, monkeypatch):
    """Fresh temp data dir with NO profile.json (missing-profile cases)."""
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    monkeypatch.setattr(C, "PROFILE_PATH", tmp_path / "profile.json")
    return tmp_path


# ---------------------------------------------------------------------------
# arc
# ---------------------------------------------------------------------------

def test_arc_has_three_segments(data_dir):
    arc = NA.build_arc()
    assert set(arc) == {"past", "present", "future"}
    for seg in arc.values():
        assert "text" in seg and "sources" in seg


def test_arc_segments_cite_sources(data_dir):
    arc = NA.build_arc()
    assert arc["past"]["sources"], "past should cite sources"
    assert arc["present"]["sources"], "present should cite sources"
    for seg in ("past", "present"):
        for src in arc[seg]["sources"]:
            assert src.startswith("exp") or src.startswith("edu"), src


def test_past_uses_earliest_roles_and_education(data_dir):
    arc = NA.build_arc()
    # oldest entry is index 2; education id edu0 must be cited too
    assert "edu0" in arc["past"]["sources"]
    assert any(s.startswith("exp2-") for s in arc["past"]["sources"])
    assert "Brightline Media" in arc["past"]["text"]
    assert "State University" in arc["past"]["text"]


def test_present_uses_current_role_and_skills(data_dir):
    arc = NA.build_arc()
    assert "Meridian Financial" in arc["present"]["text"]
    assert "python" in arc["present"]["text"]
    assert all(s.startswith("exp0-") for s in arc["present"]["sources"])


def test_future_uses_target_roles(data_dir):
    arc = NA.build_arc()
    assert "Staff Machine Learning Engineer" in arc["future"]["text"]
    assert "[fill in:" not in arc["future"]["text"]


def test_future_placeholder_without_targets(data_dir):
    prof = _rich_profile()
    prof.pop("target_roles", None)
    arc = NA.build_arc(prof)
    assert arc["future"]["text"] == \
        "Looking ahead, I'm headed toward [fill in: where you're headed]."


def test_no_em_dashes_anywhere(data_dir):
    arc = NA.build_arc()
    for length in ("30s", "2min", "5min"):
        pitch = NA.generate_pitch(length)
        assert "\u2014" not in pitch["text"], f"em dash in {length} pitch"
    for seg in arc.values():
        assert "\u2014" not in seg["text"]


# ---------------------------------------------------------------------------
# pitches
# ---------------------------------------------------------------------------

def _in_range(pitch: dict, length: str):
    lo, hi = NA.PITCH_LENGTHS[length]
    assert lo <= pitch["word_count"] <= hi, (
        f"{length}: {pitch['word_count']} words not in [{lo}, {hi}]"
    )
    assert pitch["word_count"] == len(pitch["text"].split())


def test_pitch_30s_word_count(data_dir):
    _in_range(NA.generate_pitch("30s"), "30s")


def test_pitch_2min_word_count(data_dir):
    _in_range(NA.generate_pitch("2min"), "2min")


def test_pitch_5min_word_count(data_dir):
    _in_range(NA.generate_pitch("5min"), "5min")


def test_pitch_quotes_bullets_verbatim(data_dir):
    bullet = "Shipped a churn prediction model that reduced customer attrition by 12 percent."
    pitch = NA.generate_pitch("2min")
    assert f'"{bullet}"' in pitch["text"]
    assert pitch["sources"], "pitch should record quoted bullet ids"


def test_sparse_profile_gets_placeholders(data_dir, tmp_path):
    pitch = NA.generate_pitch("30s", profile=_sparse_profile())
    assert "[fill in:" in pitch["text"]
    _in_range(pitch, "30s")


def test_sparse_profile_5min_still_in_range(data_dir):
    pitch = NA.generate_pitch("5min", profile=_sparse_profile(), regenerate=True)
    assert "[fill in:" in pitch["text"]
    _in_range(pitch, "5min")


def test_unknown_length_raises(data_dir):
    with pytest.raises(NA.NarrativeError):
        NA.generate_pitch("10min")


def test_missing_profile_raises_friendly_error(empty_dir):
    with pytest.raises(NA.NarrativeError) as excinfo:
        NA.build_arc()
    assert "onboarding" in str(excinfo.value).lower()
    with pytest.raises(NA.NarrativeError):
        NA.generate_pitch("30s")


# ---------------------------------------------------------------------------
# state: drafts, determinism, sibling keys
# ---------------------------------------------------------------------------

def test_save_arc_round_trip(data_dir):
    arc = NA.save_arc()
    assert NA.get_arc() == arc
    on_disk = json.loads((data_dir / "narrative.json").read_text(encoding="utf-8"))
    assert on_disk["arc"] == arc


def test_sibling_keys_preserved(data_dir):
    other = {"theirs": {"x": 1}}
    (data_dir / "narrative.json").write_text(json.dumps(other), encoding="utf-8")
    NA.save_arc()
    NA.generate_pitch("30s")
    on_disk = json.loads((data_dir / "narrative.json").read_text(encoding="utf-8"))
    assert on_disk["theirs"] == {"x": 1}
    assert "arc" in on_disk and "pitches" in on_disk


def test_pitch_draft_cached_and_regenerated(data_dir):
    first = NA.generate_pitch("30s")
    cached = NA.generate_pitch("30s")
    assert cached == first
    assert NA.get_pitch("30s") == first

    # a changed profile does not move the cached draft...
    prof2 = _rich_profile()
    prof2["name"] = "Somebody Else"
    still_cached = NA.generate_pitch("30s", profile=prof2)
    assert still_cached == first
    # ...until regenerate=True rebuilds it deterministically
    fresh = NA.generate_pitch("30s", profile=prof2, regenerate=True)
    assert "Somebody Else" in fresh["text"]
    assert fresh == NA.generate_pitch("30s", profile=prof2, regenerate=True)


def test_regeneration_deterministic(data_dir):
    a = NA.generate_pitch("2min", regenerate=True)
    b = NA.generate_pitch("2min", regenerate=True)
    assert a["text"] == b["text"]
    assert NA.build_arc() == NA.build_arc()


def test_get_pitch_none_when_missing(empty_dir):
    assert NA.get_pitch("2min") is None
    assert NA.get_arc() is None
