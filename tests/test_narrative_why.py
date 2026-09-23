"""Tests for candid.narrative_why (batch 82 worker D): why-us connector + timing coach."""

import json
import os

import pytest

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-narrative-why-env-setup"

from candid import config as C  # noqa: E402
from candid import narrative_why as NW  # noqa: E402

PROFILE = {
    "name": "Test User",
    "headline": "ML engineer",
    "location": "NYC",
    "summary": "ML engineer with ads ranking experience.",
    "skills": ["python", "machine learning", "sql"],
    "experience": [
        {"title": "Software Engineer", "company": "BigTech",
         "dates": "2022-2026", "bullets": ["shipped ranking models"]},
        {"title": "Data Analyst", "company": "StartupCo",
         "dates": "2020-2022", "bullets": ["built dashboards"]},
    ],
    "education": [{"school": "State U", "degree": "BS CS", "dates": "2016-2020"}],
    "years_experience": 6.0,
    "seniority": "senior",
    "source_files": [],
}


@pytest.fixture()
def datadir(tmp_path, monkeypatch):
    """Isolate data dir per test; rebind lazily-resolved paths."""
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    (tmp_path / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
    return tmp_path


def _words(n):
    return " ".join(f"word{i}" for i in range(n))


def _narrative(datadir):
    p = datadir / "narrative.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# --- why_us groundedness ---------------------------------------------------

def test_why_us_uses_only_supplied_company_facts(datadir):
    facts = "Acme is opening an NYC applied-AI lab for ads ranking."
    text = NW.why_us("Acme", "ML Engineer", company_facts=facts)
    assert facts in text
    assert "[fill in:" not in text
    # nothing invented about the company beyond the supplied facts
    lowered = text.lower()
    for invented in ("market leader", "world-class", "pioneering", "cutting-edge"):
        assert invented not in lowered
    stored = _narrative(datadir)["why_us"]["Acme"]
    assert stored["role"] == "ML Engineer"
    assert stored["approved"] is False
    assert stored["text"] == text


def test_why_us_placeholder_when_no_facts(datadir):
    text = NW.why_us("BetaCorp", "Data Scientist")
    assert "[fill in: what excites you about BetaCorp]" in text


def test_why_us_jd_overlap_grounded_by_lexicon(datadir):
    jd = "We need python and machine learning for ads ranking models."
    text = NW.why_us("Acme", "ML Engineer", jd_text=jd, company_facts="x")
    assert "python" in text.lower()
    assert "machine learning" in text.lower()
    # lexicon alias in the JD should NOT credit a skill the user lacks
    jd2 = "We need kubernetes and tensorflow wizards."
    text2 = NW.why_us("Gamma", "ML Engineer", jd_text=jd2)
    assert "tensorflow" not in text2.lower()  # user's canonical skills lack it
    assert "kubernetes" not in text2.lower()


def test_why_us_no_overlap_no_sentence(datadir):
    jd = "We need rust systems programmers."
    text = NW.why_us("Delta", "ML Engineer", jd_text=jd)
    assert "maps to the skills" not in text.lower()


# --- arc read vs fallback --------------------------------------------------

def test_why_us_reads_arc_from_narrative_json(datadir):
    arc = {"seniority": "staff", "years_experience": 9,
           "latest_roles": ["Staff Engineer at FancyCo"],
           "top_skills": ["llm"]}
    p = datadir / "narrative.json"
    p.write_text(json.dumps({"arc": arc, "pitches": {"2min": "keep me"}}),
                 encoding="utf-8")
    text = NW.why_us("Acme", "ML Engineer", company_facts="facts here")
    assert "staff" in text.lower()
    assert "9 years" in text
    assert "FancyCo" in text


def test_why_us_falls_back_to_profile_arc(datadir):
    text = NW.why_us("Acme", "ML Engineer", company_facts="facts here")
    assert "senior" in text.lower()
    assert "6 years" in text
    assert "Software Engineer at BigTech" in text


def test_why_us_requires_company_and_role(datadir):
    with pytest.raises(NW.NarrativeError):
        NW.why_us("", "ML Engineer")
    with pytest.raises(NW.NarrativeError):
        NW.why_us("Acme", "")


# --- timing math -----------------------------------------------------------

def test_timing_math_140_words_is_60_seconds(datadir):
    report = NW.timing(_words(140), target="30s")
    assert report["word_count"] == 140
    assert report["seconds"] == 60
    assert report["word_budget"] == 70  # 30s at 140wpm


def test_timing_verdict_within(datadir):
    report = NW.timing(_words(280), target="2min")
    assert report["verdict"] == "within"
    assert report["word_gap"] == 0


def test_timing_verdict_under_and_over(datadir):
    under = NW.timing(_words(140), target="2min")
    assert under["verdict"] == "under"
    assert "add" in under["gap_tip"]
    over = NW.timing(_words(400), target="2min")
    assert over["verdict"] == "over"
    assert "cut" in over["gap_tip"]


def test_timing_ten_percent_boundary_is_within(datadir):
    # 280-word budget: exactly +10% (308 words) still counts as within
    report = NW.timing(_words(308), target="2min")
    assert report["verdict"] == "within"
    # just past the boundary tips over
    report2 = NW.timing(_words(310), target="2min")
    assert report2["verdict"] == "over"


def test_timing_flags_long_sentences(datadir):
    long_sentence = " ".join(f"w{i}" for i in range(35)) + "."
    boundary = " ".join(f"w{i}" for i in range(28)) + "."
    report = NW.timing(f"{long_sentence} {boundary}", target="30s")
    assert len(report["long_sentences"]) == 1
    assert report["long_sentences"][0]["words"] == 35
    assert any("split them" in t for t in report["tips"])


def test_timing_flags_filler_phrases(datadir):
    text = "Um, so basically I was like, you know, actually working, sort of."
    report = NW.timing(text, target="30s")
    found = {f["phrase"] for f in report["fillers"]}
    assert {"um", "like", "you know", "basically", "actually", "sort of"} <= found
    assert any("Filler" in t for t in report["tips"])


def test_timing_pause_tip_and_paragraph_budgets(datadir):
    text = f"{_words(50)}\n\n{_words(50)}"
    report = NW.timing(text, target="2min")
    assert "hook" in report["pause_tip"].lower()
    assert len(report["paragraph_budgets"]) == 2
    assert report["paragraph_budgets"][0]["budget_words"] == 140


def test_timing_bad_target(datadir):
    with pytest.raises(NW.NarrativeError):
        NW.timing("hello world", target="10min")


# --- timing_report ---------------------------------------------------------

def test_timing_report_reads_stored_pitch(datadir):
    pitch = _words(280)
    (datadir / "narrative.json").write_text(
        json.dumps({"pitches": {"2min": pitch}}), encoding="utf-8")
    report = NW.timing_report("2min")
    assert report["verdict"] == "within"
    stored = _narrative(datadir)["timing"]["2min"]
    assert stored["word_count"] == 280


def test_timing_report_missing_pitch(datadir):
    with pytest.raises(NW.NarrativeError):
        NW.timing_report("5min")


# --- approve ----------------------------------------------------------------

def test_approve_why_us(datadir):
    NW.why_us("Acme", "ML Engineer", company_facts="facts")
    approved = NW.approve_why_us("Acme")
    assert approved["approved"] is True
    assert _narrative(datadir)["why_us"]["Acme"]["approved"] is True


def test_approve_why_us_missing_draft(datadir):
    with pytest.raises(NW.NarrativeError):
        NW.approve_why_us("Nobody")


# --- errors and state hygiene ----------------------------------------------

def test_missing_profile_raises_friendly_error(datadir):
    (datadir / "profile.json").unlink()
    with pytest.raises(NW.NarrativeError, match="profile"):
        NW.why_us("Acme", "ML Engineer", company_facts="facts")


def test_sibling_keys_preserved(datadir):
    (datadir / "narrative.json").write_text(
        json.dumps({"arc": {"seniority": "senior"}, "pitches": {"2min": _words(10)}}),
        encoding="utf-8")
    NW.why_us("Acme", "ML Engineer", company_facts="facts")
    data = _narrative(datadir)
    assert data["arc"] == {"seniority": "senior"}
    assert "2min" in data["pitches"]
    NW.timing_report("2min")
    data2 = _narrative(datadir)
    assert data2["arc"] == {"seniority": "senior"}
    assert "Acme" in data2["why_us"]
    assert "2min" in data2["timing"]
