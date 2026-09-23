"""Tests for the career-switcher interview prep modules.

Modules under test: candid.switch_interview (classic switcher questions with
the hook-bridge-proof-close framework, grounded answer assembly) and
candid.switch_stories (STAR re-framing toward a target role, fixed-taxonomy
competency tagging).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import switch_interview as SI
from candid import switch_stories as SS


# ---------------------------------------------------------------------------
# switch_interview.switcher_questions
# ---------------------------------------------------------------------------

class TestSwitcherQuestions:
    def test_returns_four_classic_questions(self):
        qs = SI.switcher_questions("Product Manager")
        assert len(qs) == 4
        texts = [q["question"] for q in qs]
        assert any("switching" in t.lower() for t in texts)
        assert any("ramp up" in t.lower() for t in texts)
        assert any("overqualified" in t.lower() or "underqualified" in t.lower()
                   for t in texts)

    def test_target_role_substituted_in_question(self):
        qs = SI.switcher_questions("Data Scientist")
        assert any("Data Scientist" in q["question"] for q in qs)

    def test_every_question_has_framework(self):
        for q in SI.switcher_questions("Software Engineer"):
            assert set(q["framework"]) == set(SI.FRAMEWORK_STEPS)
            for step, desc in q["framework"].items():
                assert isinstance(desc, str) and len(desc) > 10

    def test_every_question_has_do_and_dont_guidance(self):
        for q in SI.switcher_questions("Product Manager"):
            assert isinstance(q["do"], list) and len(q["do"]) >= 2
            assert isinstance(q["dont"], list) and len(q["dont"]) >= 2
            assert all(isinstance(x, str) and x for x in q["do"] + q["dont"])
            assert "why_asked" in q and len(q["why_asked"]) > 10

    def test_questions_have_stable_ids(self):
        ids = {q["id"] for q in SI.switcher_questions("Product Manager")}
        assert ids == {"why_switching", "why_role_industry", "ramp_up",
                       "over_under_qualified"}

    def test_blank_target_role_raises(self):
        with pytest.raises(SI.SwitcherQuestionError):
            SI.switcher_questions("   ")


# ---------------------------------------------------------------------------
# switch_interview.build_answer
# ---------------------------------------------------------------------------

class TestBuildAnswer:
    FACTS = {
        "motivating_experience": "I built an internal tool our PMs loved using",
        "current_role": "Backend engineer for 6 years",
        "target_role": "Product Manager",
    }

    def test_draft_uses_supplied_facts_verbatim(self):
        ans = SI.build_answer("why_switching", dict(self.FACTS))
        assert "I built an internal tool our PMs loved using" in ans["draft"]
        assert "Backend engineer for 6 years" in ans["draft"]
        assert ans["missing_facts"] == []

    def test_missing_facts_become_placeholders(self):
        ans = SI.build_answer("why_switching", {"target_role": "Product Manager"})
        assert "[PLACEHOLDER: motivating_experience]" in ans["draft"]
        assert "[PLACEHOLDER: current_role]" in ans["draft"]
        assert set(ans["missing_facts"]) == {"motivating_experience", "current_role"}

    def test_no_invented_facts_when_empty(self):
        ans = SI.build_answer("ramp_up", {})
        draft = ans["draft"]
        # Every sentence containing a needed fact must be a placeholder marker.
        assert draft.count("[PLACEHOLDER") >= 3
        # The placeholder keys must match the question's needed facts.
        assert set(ans["missing_facts"]) == set(
            SI.QUESTIONS["ramp_up"]["needed_facts"]
        )

    def test_framework_steps_present_in_draft(self):
        ans = SI.build_answer("why_role_industry", dict(self.FACTS,
                                                       why_this_company="Acme's API-first model",
                                                       relevant_experience="shipped developer tools"))
        for step in SI.FRAMEWORK_STEPS:
            assert step in ans["framework_steps"]
            assert f"[{step.upper()}]" in ans["draft"]

    def test_unknown_question_id_raises(self):
        with pytest.raises(SI.SwitcherQuestionError):
            SI.build_answer("why_so_serious", {})

    def test_non_dict_facts_raises(self):
        with pytest.raises(SI.SwitcherQuestionError):
            SI.build_answer("why_switching", ["not", "a", "dict"])

    def test_all_four_questions_build_answers(self):
        base = dict(self.FACTS)
        base.update({
            "why_this_company": "mission fit",
            "relevant_experience": "side projects",
            "learning_done": "took a PM course",
            "ramp_plan": "30/60/90 plan",
            "transferable_skill": "technical judgment",
            "seniority_context": "senior IC",
            "what_you_learn": "product discovery",
            "gap_closure_example": "learned SQL on the job",
        })
        for q in SI.switcher_questions("Product Manager"):
            ans = SI.build_answer(q["id"], base)
            assert ans["question_id"] == q["id"]
            assert ans["draft"].startswith("Question:")
            assert ans["missing_facts"] == []


# ---------------------------------------------------------------------------
# switch_stories.tag_competencies
# ---------------------------------------------------------------------------

MIGRATION_STORY = {
    "situation": "Our checkout pipeline was failing under load.",
    "task": "I led a team of four to migrate it to a new architecture.",
    "action": "I wrote the migration plan, presented it to stakeholders, "
              "and refactored the core modules.",
    "result": "Latency dropped 40% and customer complaints fell.",
}


class TestTagCompetencies:
    def test_tags_from_fixed_taxonomy_only(self):
        tags = SS.tag_competencies(MIGRATION_STORY)
        assert tags
        assert all(t in SS.COMPETENCY_TAXONOMY for t in tags)

    def test_tags_follow_taxonomy_order(self):
        tags = SS.tag_competencies(MIGRATION_STORY)
        assert tags == sorted(tags, key=SS.COMPETENCY_TAXONOMY.index)

    def test_technical_story_gets_technical_depth(self):
        assert "technical depth" in SS.tag_competencies(MIGRATION_STORY)

    def test_leadership_story_gets_leadership(self):
        assert "leadership" in SS.tag_competencies(MIGRATION_STORY)

    def test_empty_story_gets_no_tags(self):
        assert SS.tag_competencies({"situation": "x", "task": "y",
                                    "action": "z", "result": "w"}) == []

    def test_non_dict_raises(self):
        with pytest.raises(SS.StoryError):
            SS.tag_competencies("not a dict")


# ---------------------------------------------------------------------------
# switch_stories.reframe_story
# ---------------------------------------------------------------------------

class TestReframeStory:
    def test_reframe_returns_expected_shape(self):
        out = SS.reframe_story(MIGRATION_STORY, "Product Manager")
        assert set(out) == {"reframed", "competencies_highlighted",
                            "suggested_followups"}
        assert isinstance(out["reframed"], str) and len(out["reframed"]) > 50

    def test_competencies_from_taxonomy_only(self):
        out = SS.reframe_story(MIGRATION_STORY, "Product Manager")
        assert out["competencies_highlighted"]
        assert all(c in SS.COMPETENCY_TAXONOMY
                   for c in out["competencies_highlighted"])

    def test_reframe_reuses_story_words_no_invention(self):
        out = SS.reframe_story(MIGRATION_STORY, "Software Engineer")
        reframed_lower = out["reframed"].lower()
        # The story's own substantive words must appear in the reframe.
        for word in ("checkout", "pipeline", "latency", "migrate"):
            assert word in reframed_lower

    def test_pm_role_emphasizes_customer_and_communication(self):
        out = SS.reframe_story(MIGRATION_STORY, "Product Manager")
        assert "communication" in out["competencies_highlighted"]

    def test_followups_tie_to_highlighted_competencies(self):
        out = SS.reframe_story(MIGRATION_STORY, "Data Scientist")
        assert len(out["suggested_followups"]) == len(out["competencies_highlighted"])
        for comp, fu in zip(out["competencies_highlighted"],
                            out["suggested_followups"]):
            assert comp in fu

    def test_unknown_role_falls_back_to_generic_angle(self):
        out = SS.reframe_story(MIGRATION_STORY, "UX Researcher")
        assert out["competencies_highlighted"]
        assert all(c in SS.COMPETENCY_TAXONOMY
                   for c in out["competencies_highlighted"])

    def test_missing_star_field_raises(self):
        bad = dict(MIGRATION_STORY)
        del bad["result"]
        with pytest.raises(SS.StoryError):
            SS.reframe_story(bad, "Product Manager")

    def test_blank_target_role_raises(self):
        with pytest.raises(SS.StoryError):
            SS.reframe_story(MIGRATION_STORY, "  ")

    def test_non_dict_story_raises(self):
        with pytest.raises(SS.StoryError):
            SS.reframe_story(None, "Product Manager")
