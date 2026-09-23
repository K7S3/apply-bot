"""Tests for candid/linkedin_optimize.py.

CANDID_DATA_DIR is pointed at a tmp_path before any candid import, so
nothing touches the real user data dir.
"""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    d = tmp_path / "candid_data"
    d.mkdir()
    monkeypatch.setenv("CANDID_DATA_DIR", str(d))
    # config reads the env var at import time; make sure we import after
    for mod in [m for m in list(sys.modules) if m.startswith("candid")]:
        del sys.modules[mod]
    yield d


def _mods():
    from candid import linkedin_optimize as LO
    from candid import profile as P
    return LO, P


def _fixture_profile():
    """Hand-built profile with known, controlled contents."""
    return {
        "name": "Alex Rivera",
        "headline": "Data Scientist",
        "location": "San Francisco, CA",
        "summary": "Data scientist with 4 years of experience building ML products.",
        "skills": ["python", "sql", "machine learning", "xgboost",
                   "statistics", "pandas", "scikit-learn", "dbt"],
        "experience": [
            {"title": "Senior Data Scientist",
             "company": "Meridian Financial",
             "dates": "Jan 2022 - Present",
             "bullets": [
                 "Built real-time fraud detection with XGBoost, cutting fraud losses 22%",
                 "Designed A/B testing framework used by 6 product teams",
                 "Wrote SQL pipelines over 2B-row event tables",
             ]},
            {"title": "Data Analyst",
             "company": "Northwind Retail",
             "dates": "Jun 2020 - Dec 2021",
             "bullets": ["Built dbt models and Looker dashboards"]},
        ],
        "education": [{"school": "University of Texas at Austin",
                       "degree": "B.S. Statistics", "dates": "2016 - 2020"}],
        "years_experience": 4.0,
        "seniority": "senior",
        "domains": ["data science", "finance"],
        "source_files": ["test"],
    }


# ---------------------------------------------------------------------------
# headlines
# ---------------------------------------------------------------------------

class TestHeadlines:
    def test_three_headlines_within_limit(self):
        LO, _ = _mods()
        heads = LO.suggest_headline(_fixture_profile())
        assert len(heads) == 3
        assert all(len(h) <= 220 for h in heads)
        assert all(h.strip() for h in heads)

    def test_n_parameter(self):
        LO, _ = _mods()
        heads = LO.suggest_headline(_fixture_profile(), n=5)
        assert len(heads) == 5
        assert all(len(h) <= 220 for h in heads)

    def test_headlines_use_real_title_and_company(self):
        LO, _ = _mods()
        heads = LO.suggest_headline(_fixture_profile())
        joined = " | ".join(heads)
        assert "Senior Data Scientist" in joined
        assert "Meridian Financial" in joined

    def test_headline_no_experience_raises(self):
        LO, _ = _mods()
        with pytest.raises(LO.LinkedInOptimizeError):
            LO.suggest_headline({"skills": ["python"]})


# ---------------------------------------------------------------------------
# about
# ---------------------------------------------------------------------------

class TestAbout:
    def test_about_structure(self):
        LO, _ = _mods()
        about = LO.suggest_about(_fixture_profile())
        paras = [p for p in about.split("\n\n") if p.strip()]
        assert 2 <= len(paras) <= 3
        assert paras[0].startswith("I'm")
        assert "Open to work" not in about

    def test_open_to_work_opt_in_only(self):
        LO, _ = _mods()
        prof = _fixture_profile()
        assert "Open to work" not in LO.suggest_about(prof)
        assert "Open to work" in LO.suggest_about(prof, open_to_work=True)

    def test_about_uses_real_facts(self):
        LO, _ = _mods()
        about = LO.suggest_about(_fixture_profile())
        assert "Meridian Financial" in about
        assert "22%" in about  # metric from a real bullet

    def test_about_no_experience_raises(self):
        LO, _ = _mods()
        with pytest.raises(LO.LinkedInOptimizeError):
            LO.suggest_about({})


# ---------------------------------------------------------------------------
# polish_about: voice preservation
# ---------------------------------------------------------------------------

class TestPolish:
    def test_first_person_stays_first_person(self):
        LO, _ = _mods()
        out = LO.polish_about(
            "i'm a data scientist. i build fraud models for fintech.",
            _fixture_profile())
        assert set(out) == {"polished", "voice_notes", "changes"}
        assert "I'm" in out["polished"]
        assert " he " not in " " + out["polished"].lower() + " "
        assert " she " not in " " + out["polished"].lower() + " "
        assert any("first-person" in n for n in out["voice_notes"])

    def test_emoji_preserved(self):
        LO, _ = _mods()
        out = LO.polish_about(
            "Data scientist 🚀 turning data into decisions ✨",
            _fixture_profile())
        assert "🚀" in out["polished"]
        assert "✨" in out["polished"]
        assert any("Emoji" in n for n in out["voice_notes"])

    def test_grammar_and_tightening(self):
        LO, _ = _mods()
        out = LO.polish_about(
            "i utilize python in order to build models , and i love it",
            _fixture_profile())
        assert "I utilize" not in out["polished"]
        assert "I use python to build models" in out["polished"]
        assert " ," not in out["polished"]
        assert out["changes"]  # changes were recorded

    def test_empty_text_raises(self):
        LO, _ = _mods()
        with pytest.raises(LO.LinkedInOptimizeError):
            LO.polish_about("   ", _fixture_profile())

    def test_third_person_kept_third_person(self):
        LO, _ = _mods()
        out = LO.polish_about(
            "Alex Rivera is a data scientist. He builds fraud models.",
            _fixture_profile())
        assert " I " not in " " + out["polished"] + " "
        assert any("third-person" in n for n in out["voice_notes"])


# ---------------------------------------------------------------------------
# experience
# ---------------------------------------------------------------------------

class TestExperience:
    def test_per_role_structure(self):
        LO, _ = _mods()
        roles = LO.suggest_experience(_fixture_profile())
        assert len(roles) == 2
        r0 = roles[0]
        assert r0["title"] == "Senior Data Scientist"
        assert r0["company"] == "Meridian Financial"
        assert r0["title_line"] == "Senior Data Scientist | Meridian Financial"
        assert 1 <= len(r0["bullet_suggestions"]) <= 5
        # bullets are distilled from real resume bullets, verbatim
        assert any("22%" in b for b in r0["bullet_suggestions"])
        assert "xgboost" in r0["skills_to_tag"]

    def test_title_inflation_flagged(self):
        LO, _ = _mods()
        roles = LO.suggest_experience(
            _fixture_profile(),
            about_text=("As a principal data scientist at Meridian Financial "
                        "I lead the team."))
        assert any("mismatch" in f.lower() for f in roles[0]["flags"])

    def test_matching_title_not_flagged(self):
        LO, _ = _mods()
        roles = LO.suggest_experience(
            _fixture_profile(),
            about_text="As a Senior Data Scientist at Meridian Financial I ship models.")
        assert not any("mismatch" in f.lower() for f in roles[0]["flags"])


# ---------------------------------------------------------------------------
# keyword gaps
# ---------------------------------------------------------------------------

class TestKeywordGaps:
    def test_gaps_are_suggestions_not_additions(self):
        LO, _ = _mods()
        prof = _fixture_profile()
        before = copy.deepcopy(prof)
        gaps = LO.keyword_gaps(prof)
        assert prof == before  # never auto-added / never mutated
        assert gaps
        for g in gaps:
            assert set(g) == {"keyword", "source", "why", "note"}
            assert "only if" in g["note"].lower() or "if true" in g["note"].lower()
            assert not LO._has_skill(prof, g["keyword"])  # truly missing

    def test_known_skills_not_reported(self):
        LO, _ = _mods()
        gaps = LO.keyword_gaps(_fixture_profile())
        kws = {g["keyword"] for g in gaps}
        assert "python" not in kws
        assert "sql" not in kws
        assert "machine learning" not in kws


# ---------------------------------------------------------------------------
# no-invention property across all outputs
# ---------------------------------------------------------------------------

class TestNoInvention:
    DECOYS = ["cobol", "Chief Executive Officer", "FakeCorp Industries",
              "quantum teleportation"]

    def test_no_decoy_content_anywhere(self):
        LO, _ = _mods()
        prof = _fixture_profile()
        outputs = []
        outputs += LO.suggest_headline(prof, n=5)
        outputs.append(LO.suggest_about(prof, open_to_work=True))
        out = LO.polish_about("i'm a data scientist who loves sql", prof)
        outputs.append(out["polished"])
        for role in LO.suggest_experience(prof):
            outputs.append(role["title_line"])
            outputs += role["bullet_suggestions"]
            outputs += role["flags"]
        outputs += [g["keyword"] for g in LO.keyword_gaps(prof)]
        outputs.append(LO.full_report(prof))
        blob = "\n".join(outputs).lower()
        for decoy in self.DECOYS:
            assert decoy.lower() not in blob, f"invented content: {decoy}"

    def test_every_named_skill_comes_from_profile(self):
        LO, _ = _mods()
        prof = _fixture_profile()
        blob = "\n".join(LO.suggest_headline(prof, n=5)).lower()
        for skill in ("cobol", "rust", "golang"):
            assert skill not in blob


# ---------------------------------------------------------------------------
# full report
# ---------------------------------------------------------------------------

class TestFullReport:
    def test_report_sections(self):
        LO, _ = _mods()
        md = LO.full_report(_fixture_profile())
        for section in ("Headline options", "About section",
                        "Experience", "Keyword gaps"):
            assert section in md
        assert "Senior Data Scientist" in md

    def test_report_does_not_mutate_profile(self):
        LO, _ = _mods()
        prof = _fixture_profile()
        before = copy.deepcopy(prof)
        LO.full_report(prof, open_to_work=True)
        assert prof == before


# ---------------------------------------------------------------------------
# CANDID_DATA_DIR override honored end-to-end
# ---------------------------------------------------------------------------

class TestDataDirOverride:
    def test_onboard_and_load_use_tmp_data_dir(self, tmp_path, monkeypatch):
        from candid import config as C
        from candid import profile as P
        from candid import linkedin_optimize as LO
        assert str(C.PROFILE_PATH).startswith(str(tmp_path))
        sample = (ROOT / "samples" / "candid" / "sample_resume.md").read_text()
        # write profile via onboard using default (overridden) path
        tmp_resume = tmp_path / "resume.md"
        tmp_resume.write_text(sample)
        P.onboard(resume_path=tmp_resume)
        assert C.PROFILE_PATH.exists()
        prof = P.load_profile()
        heads = LO.suggest_headline(prof)
        assert len(heads) == 3
        # the file landed in the tmp dir, not the real data dir
        assert json.loads(C.PROFILE_PATH.read_text())["name"] == "Alex Rivera"
