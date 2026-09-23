"""Tests for candid.switch_skills and candid.switch_readiness (career-switcher track)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import switch_readiness as sr  # noqa: E402
from candid import switch_skills as ss  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect CANDID_DATA_DIR at call time (honored by save_switch_report)."""
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


def _skills(*pairs):
    return [{"skill": s, "context": c} for s, c in pairs]


class TestNormalization:
    def test_alias_k8s(self):
        assert ss.canonical_skill("k8s") == "kubernetes"

    def test_alias_ab_testing(self):
        assert ss.canonical_skill("A/B testing") == "experimentation"
        assert ss.canonical_skill("AB Testing") == "experimentation"

    def test_alias_plural_and_case(self):
        assert ss.canonical_skill("  REST APIs ") == "rest api"

    def test_alias_people_management(self):
        assert ss.canonical_skill("People Management") == "team leadership"

    def test_unknown_skill_keeps_normalized_form(self):
        assert ss.canonical_skill("Rust") == "rust"

    def test_normalize_rejects_non_string(self):
        with pytest.raises(ss.SwitchSkillsError):
            ss.normalize_skill(123)


class TestMapTransferable:
    def test_direct_match(self):
        out = ss.map_transferable(_skills(("Python", "3 years")), ["Python"])
        assert len(out) == 1
        m = out[0]
        assert m["strength"] == "direct"
        assert m["skill"] == "Python"
        assert m["matched_as"] == "Python"
        assert m["evidence"] == "3 years"

    def test_alias_gives_direct_match(self):
        out = ss.map_transferable(_skills(("k8s", "ran clusters")), ["Kubernetes"])
        assert out[0]["strength"] == "direct"

    def test_adjacent_match(self):
        out = ss.map_transferable(_skills(("SQL", "wrote queries")), ["Data engineering"])
        assert out[0]["strength"] == "adjacent"
        assert out[0]["matched_as"] == "Data engineering"

    def test_foundational_match(self):
        out = ss.map_transferable(_skills(("Reporting", "weekly dashboards")),
                                  ["Data reporting"])
        assert out[0]["strength"] == "foundational"

    def test_ranking_direct_first(self):
        skills = _skills(("Reporting", "x"), ("SQL", "y"), ("Python", "z"))
        reqs = ["Data reporting", "Data engineering", "Python"]
        out = ss.map_transferable(skills, reqs)
        strengths = [m["strength"] for m in out]
        assert strengths == ["direct", "adjacent", "foundational"]

    def test_one_mapping_per_skill_picks_best(self):
        # Python is adjacent to Data science but direct for Python
        out = ss.map_transferable(_skills(("Python", "x")), ["Data science", "Python"])
        assert len(out) == 1
        assert out[0]["matched_as"] == "Python"
        assert out[0]["strength"] == "direct"

    def test_unmatched_skill_omitted(self):
        out = ss.map_transferable(_skills(("Pottery", "hobby")), ["Kubernetes"])
        assert out == []

    def test_deterministic_ordering(self):
        skills = _skills(("Teaching", "a"), ("Writing", "b"), ("Sales", "c"))
        reqs = ["Training", "Communication", "Negotiation"]
        assert ss.map_transferable(skills, reqs) == ss.map_transferable(skills, reqs)

    def test_evidence_is_verbatim(self):
        ctx = "Led a 5-person team at Initech (2021-2024)"
        out = ss.map_transferable(_skills(("Teaching", ctx)), ["Training"])
        assert out[0]["evidence"] == ctx


class TestSkillGapSummary:
    PROFILE = _skills(("Python", "x"), ("SQL", "y"), ("Teaching", "z"))

    def test_covered_partial_missing_split(self):
        s = ss.skill_gap_summary(self.PROFILE, ["Python", "Data engineering", "Kubernetes"])
        assert [e["requirement"] for e in s["covered"]] == ["Python"]
        assert [e["requirement"] for e in s["partial"]] == ["Data engineering"]
        assert s["missing"] == ["Kubernetes"]

    def test_covered_lists_matched_skills(self):
        s = ss.skill_gap_summary(self.PROFILE, ["Python"])
        assert s["covered"][0]["matched_skills"] == [
            {"skill": "Python", "strength": "direct"}]

    def test_partial_records_best_strength(self):
        s = ss.skill_gap_summary(self.PROFILE, ["Data engineering"])
        assert s["partial"][0]["best_strength"] == "adjacent"

    def test_missing_keeps_jd_order(self):
        s = ss.skill_gap_summary(self.PROFILE, ["Kubernetes", "Rust"])
        assert s["missing"] == ["Kubernetes", "Rust"]


class TestErrors:
    def test_skills_must_be_list(self):
        with pytest.raises(ss.SwitchSkillsError):
            ss.map_transferable("Python", ["Python"])

    def test_skill_dict_needs_skill_key(self):
        with pytest.raises(ss.SwitchSkillsError):
            ss.map_transferable([{"context": "x"}], ["Python"])

    def test_requirements_must_be_nonempty(self):
        with pytest.raises(ss.SwitchSkillsError):
            ss.map_transferable(_skills(("Python", "x")), [])

    def test_requirement_must_be_string(self):
        with pytest.raises(ss.SwitchSkillsError):
            ss.skill_gap_summary(_skills(("Python", "x")), [None])

    def test_empty_skills_allowed(self):
        s = ss.skill_gap_summary([], ["Python"])
        assert s["covered"] == [] and s["partial"] == [] and s["missing"] == ["Python"]


class TestSaveSwitchReport:
    def test_writes_under_candid_data_dir(self, data_dir):
        mappings = ss.map_transferable(_skills(("Python", "x")), ["Python"])
        summary = ss.skill_gap_summary(_skills(("Python", "x")), ["Python"])
        path = ss.save_switch_report("Data Scientist", mappings, summary)
        assert path.exists()
        assert str(data_dir) in str(path)
        payload = json.loads(path.read_text())
        assert payload["target_role"] == "Data Scientist"
        assert payload["mappings"] == mappings
        assert payload["summary"] == summary

    def test_rejects_bad_target_role(self, data_dir):
        with pytest.raises(ss.SwitchSkillsError):
            ss.save_switch_report("", [], {})


class TestReadinessScore:
    def test_perfect_switcher_scores_100(self):
        r = sr.readiness_score(_skills(("Python", "x"), ("SQL", "y")),
                               ["Python", "SQL"], years_experience=6)
        assert r["score"] == 100
        assert r["grade"] == "A"
        assert r["top_gaps"] == []
        assert r["quick_wins"] == []

    def test_result_shape(self):
        r = sr.readiness_score(_skills(("Teaching", "x")), ["Training", "Kubernetes"])
        assert set(r) == {"score", "grade", "breakdown", "top_gaps", "quick_wins",
                          "target_role"}
        assert set(r["breakdown"]) == {"coverage", "gap_control", "adjacent_experience"}
        assert 0 <= r["score"] <= 100

    def test_breakdown_components_sum_to_score(self):
        r = sr.readiness_score(_skills(("SQL", "x")), ["Data engineering", "Kubernetes"],
                               years_experience=2)
        b = r["breakdown"]
        assert b["coverage"] == 12.5      # (0 + 0.5*1 partial) / 2 * 50
        assert b["gap_control"] == 22.5   # 30 - 7.5*1 missing
        assert b["adjacent_experience"] == 8.0
        assert r["score"] == int(round(12.5 + 22.5 + 8.0))

    def test_top_gaps_capped_at_three_in_jd_order(self):
        r = sr.readiness_score(_skills(("Pottery", "x")),
                               ["K1", "K2", "K3", "K4", "K5"])
        assert r["top_gaps"] == ["K1", "K2", "K3"]

    def test_quick_wins_reference_real_skills_only(self):
        skills = _skills(("SQL", "wrote queries"))
        r = sr.readiness_score(skills, ["Data engineering"])
        assert len(r["quick_wins"]) == 1
        win = r["quick_wins"][0]
        assert "SQL" in win and "Data engineering" in win
        assert r["breakdown"]["coverage"] == 25.0

    def test_all_missing_scores_zero_gaps(self):
        r = sr.readiness_score(_skills(("Pottery", "x")),
                               ["K1", "K2", "K3", "K4"])
        assert r["breakdown"]["gap_control"] == 0.0
        assert r["score"] <= 20  # only experience can add

    def test_deterministic(self):
        kw = dict(years_experience=3, target_role="Analyst")
        a = sr.readiness_score(_skills(("SQL", "x")), ["Data engineering"], **kw)
        b = sr.readiness_score(_skills(("SQL", "x")), ["Data engineering"], **kw)
        assert a == b

    def test_target_role_passthrough(self):
        r = sr.readiness_score(_skills(("Python", "x")), ["Python"],
                               target_role="  Data Scientist ")
        assert r["target_role"] == "Data Scientist"


class TestGradesAndExperience:
    @pytest.mark.parametrize("score,grade", [(100, "A"), (85, "A"), (84, "B"),
                                             (70, "B"), (69, "C"), (55, "C"),
                                             (54, "D"), (40, "D"), (39, "F"), (0, "F")])
    def test_grade_boundaries(self, score, grade):
        assert sr.grade_for(score) == grade

    @pytest.mark.parametrize("years,pts", [(10, 20), (5, 20), (4, 15), (3, 15),
                                           (2, 8), (1, 8), (0.5, 4), (0, 0)])
    def test_experience_points(self, years, pts):
        assert sr.experience_points(years) == pts

    def test_negative_years_rejected(self):
        with pytest.raises(sr.ReadinessError):
            sr.experience_points(-1)

    def test_non_numeric_years_rejected(self):
        with pytest.raises(sr.ReadinessError):
            sr.experience_points("five")

    def test_bad_requirements_raise_readiness_error(self):
        with pytest.raises(sr.ReadinessError):
            sr.readiness_score(_skills(("Python", "x")), [])
