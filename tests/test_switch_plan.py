"""Tests for candid.switch_plan and candid.switch_signals."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.switch_plan import (  # noqa: E402
    SwitchPlanError,
    build_plan,
    plan_markdown,
)
from candid.switch_signals import (  # noqa: E402
    FRIENDLY_THRESHOLD,
    SwitchSignalsError,
    rank_companies,
    score_company_signals,
)


class TestBuildPlanOrdering:
    def test_orders_by_severity_hardest_first(self):
        gaps = [
            {"skill": "Excel", "severity": "low"},
            {"skill": "Python", "severity": "critical"},
            {"skill": "SQL", "severity": "high"},
            {"skill": "Git", "severity": "medium"},
        ]
        plan = build_plan(gaps, "Data Analyst", weeks=2)
        ordered = [g["skill"] for g in plan["gaps_ordered"]]
        assert ordered == ["Python", "SQL", "Git", "Excel"]

    def test_unknown_severity_becomes_medium_and_stays_deterministic(self):
        gaps = [
            {"skill": "Zebra skill", "severity": "weird"},
            {"skill": "Aardvark skill", "severity": "medium"},
        ]
        plan = build_plan(gaps, "Role", weeks=1)
        ordered = [g["skill"] for g in plan["gaps_ordered"]]
        assert ordered == ["Aardvark skill", "Zebra skill"]
        assert all(g["severity"] == "medium" for g in plan["gaps_ordered"])

    def test_hardest_gap_lands_in_week_one(self):
        gaps = [
            {"skill": "Excel", "severity": "low"},
            {"skill": "Machine Learning", "severity": "critical"},
        ]
        plan = build_plan(gaps, "ML Engineer", weeks=4)
        assert "Machine Learning" in plan["schedule"][0]["skills"]

    def test_schedule_has_requested_week_count(self):
        gaps = [{"skill": "Python", "severity": "high"}]
        plan = build_plan(gaps, "Backend Engineer", weeks=6)
        assert len(plan["schedule"]) == 6
        assert plan["weeks"] == 6
        assert plan["total_gaps"] == 1

    def test_week_numbers_are_sequential(self):
        plan = build_plan([{"skill": "SQL", "severity": "high"}], "Analyst", weeks=3)
        assert [w["week"] for w in plan["schedule"]] == [1, 2, 3]

    def test_every_gap_is_scheduled_exactly_once(self):
        gaps = [
            {"skill": "Python", "severity": "critical"},
            {"skill": "SQL", "severity": "high"},
            {"skill": "Docker", "severity": "medium"},
        ]
        plan = build_plan(gaps, "DevOps Engineer", weeks=2)
        scheduled = [s for w in plan["schedule"] for s in w["skills"]]
        assert sorted(scheduled) == ["Docker", "Python", "SQL"]


class TestPlanContent:
    def test_milestones_present_for_filled_weeks(self):
        plan = build_plan([{"skill": "Python", "severity": "high"}], "Engineer", weeks=2)
        filled = [w for w in plan["schedule"] if w["skills"]]
        assert filled, "expected at least one filled week"
        for week in filled:
            assert week["milestone"], "milestone must be non-empty"
            assert week["proof_of_learning"], "proof of learning must be non-empty"

    def test_known_skill_gets_real_free_resources(self):
        plan = build_plan([{"skill": "Python", "severity": "high"}], "Engineer", weeks=1)
        resources = plan["schedule"][0]["resources"]
        assert any("freeCodeCamp" in r for r in resources)
        assert not any(r.startswith("http") for r in resources)

    def test_unknown_skill_falls_back_to_generic_resources(self):
        plan = build_plan([{"skill": "Underwater Basket Weaving", "severity": "low"}], "Artisan", weeks=1)
        resources = plan["schedule"][0]["resources"]
        assert resources, "fallback resources must be non-empty"
        assert not any(r.startswith("http") for r in resources)

    def test_known_skill_gets_project_deliverable(self):
        plan = build_plan([{"skill": "SQL", "severity": "high"}], "Analyst", weeks=1)
        proof = plan["schedule"][0]["proof_of_learning"].lower()
        assert "github" in proof or "project" in proof or "repo" in proof

    def test_no_fabricated_urls_anywhere_in_plan(self):
        gaps = [
            {"skill": "Python", "severity": "critical"},
            {"skill": "React", "severity": "high"},
            {"skill": "Kubernetes", "severity": "medium"},
        ]
        plan = build_plan(gaps, "Engineer", weeks=3)
        blob = str(plan)
        assert "http://" not in blob and "https://" not in blob and "www." not in blob

    def test_empty_weeks_get_buffer_milestone(self):
        plan = build_plan([{"skill": "SQL", "severity": "high"}], "Analyst", weeks=3)
        empty = [w for w in plan["schedule"] if not w["skills"]]
        assert empty, "expected empty buffer weeks"
        for week in empty:
            assert "review" in week["milestone"].lower()

    def test_build_plan_rejects_bad_input(self):
        import pytest

        with pytest.raises(SwitchPlanError):
            build_plan([], "Engineer")
        with pytest.raises(SwitchPlanError):
            build_plan([{"skill": "Python"}], "Engineer", weeks=0)
        with pytest.raises(SwitchPlanError):
            build_plan([{"skill": "Python"}], "")
        with pytest.raises(SwitchPlanError):
            build_plan([{"skill": "   "}], "Engineer")
        with pytest.raises(SwitchPlanError):
            build_plan(["not-a-dict"], "Engineer")


class TestPlanMarkdown:
    def test_markdown_renders_role_gaps_and_weeks(self):
        plan = build_plan(
            [
                {"skill": "Python", "severity": "critical"},
                {"skill": "SQL", "severity": "high"},
            ],
            "Data Analyst",
            weeks=2,
        )
        md = plan_markdown(plan)
        assert "# Study Plan: Data Analyst" in md
        assert "**Python** (critical)" in md
        assert "## Week 1" in md
        assert "## Week 2" in md
        assert "Milestone" in md
        assert "Proof of learning" in md

    def test_markdown_orders_gaps_hardest_first(self):
        plan = build_plan(
            [
                {"skill": "Excel", "severity": "low"},
                {"skill": "Python", "severity": "critical"},
            ],
            "Analyst",
            weeks=1,
        )
        md = plan_markdown(plan)
        assert md.index("Python") < md.index("Excel")

    def test_markdown_rejects_bad_input(self):
        import pytest

        with pytest.raises(SwitchPlanError):
            plan_markdown({})
        with pytest.raises(SwitchPlanError):
            plan_markdown("not a plan")


class TestScoreCompanySignals:
    def test_explicit_career_change_scores_and_is_friendly(self):
        result = score_company_signals(
            ["We welcome career changers from non-traditional backgrounds."]
        )
        assert result["score"] >= FRIENDLY_THRESHOLD
        assert result["friendly"] is True
        assert "explicit_career_change" in result["signals_found"]
        assert "non_traditional_background" in result["signals_found"]

    def test_signal_weights_match_severity_of_phrasing(self):
        strong = score_company_signals(["We run an apprenticeship program."])
        weak = score_company_signals(["We welcome career transitions."])
        assert strong["score"] > weak["score"]
        assert strong["signals_found"]["apprenticeship"] == 1
        assert weak["signals_found"]["career_transition"] == 1

    def test_multiple_texts_stack_hits(self):
        result = score_company_signals(
            [
                "Bootcamp grads are welcome here.",
                "Another posting: bootcamp graduates encouraged to apply.",
            ]
        )
        assert result["signals_found"]["bootcamp_grad"] == 2
        assert result["score"] == 2 * 2

    def test_equivalent_experience_and_no_degree_phrasing(self):
        result = score_company_signals(
            ["Bachelor's degree or equivalent experience. No degree required for the right candidate."]
        )
        assert "equivalent_experience" in result["signals_found"]
        assert "no_degree_required" in result["signals_found"]
        assert result["friendly"] is True

    def test_neutral_text_has_no_false_positives(self):
        neutral = [
            "We are hiring a senior backend engineer.",
            "Requirements: 5+ years of Python, distributed systems experience.",
            "Benefits include health insurance and a 401k match.",
        ]
        result = score_company_signals(neutral)
        assert result["score"] == 0
        assert result["signals_found"] == {}
        assert result["friendly"] is False

    def test_empty_list_scores_zero(self):
        result = score_company_signals([])
        assert result["score"] == 0
        assert result["friendly"] is False

    def test_matching_is_case_insensitive(self):
        result = score_company_signals(["We love CAREER SWITCHERS and Returnships."])
        assert "explicit_career_switcher" in result["signals_found"]
        assert "returnship" in result["signals_found"]

    def test_rejects_non_list_and_non_string(self):
        import pytest

        with pytest.raises(SwitchSignalsError):
            score_company_signals("a single string")
        with pytest.raises(SwitchSignalsError):
            score_company_signals([123])

    def test_per_signal_cap_prevents_single_phrase_domination(self):
        texts = ["career change"] * 50
        result = score_company_signals(texts)
        assert result["score"] == 6


class TestRankCompanies:
    def test_ranks_by_score_descending(self):
        ranked = rank_companies(
            {
                "NeutralCorp": ["We need 5 years of Go experience."],
                "FriendlyCo": ["We welcome career changers and run an apprenticeship."],
                "MildCo": ["We welcome career transitions."],
            }
        )
        names = [r["company"] for r in ranked]
        assert names == ["FriendlyCo", "MildCo", "NeutralCorp"]
        assert ranked[0]["friendly"] is True
        assert ranked[-1]["friendly"] is False

    def test_ties_broken_by_company_name_deterministically(self):
        ranked = rank_companies(
            {
                "Zebra Inc": ["We welcome career transitions."],
                "Alpha Inc": ["We welcome career transitions."],
            }
        )
        assert [r["company"] for r in ranked] == ["Alpha Inc", "Zebra Inc"]
        assert ranked[0]["score"] == ranked[1]["score"]

    def test_ranked_entries_carry_full_result_shape(self):
        ranked = rank_companies({"Solo": ["Bootcamp grads welcome."]})
        assert len(ranked) == 1
        entry = ranked[0]
        assert entry["company"] == "Solo"
        assert isinstance(entry["score"], int)
        assert isinstance(entry["signals_found"], dict)
        assert isinstance(entry["friendly"], bool)

    def test_rejects_non_dict(self):
        import pytest

        with pytest.raises(SwitchSignalsError):
            rank_companies(["not", "a", "dict"])
