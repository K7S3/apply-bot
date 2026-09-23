"""Tests for the Designer-track module (candid.design).

Run: cd ~/workspace/candid-batch94 && python -m pytest tests/test_design.py -q

CANDID_DATA_DIR is monkeypatched per-test so the real data dir is untouched.
"""
import pytest

from candid import design as D


@pytest.fixture()
def packs_dir(tmp_path, monkeypatch):
    target = tmp_path / "design_packs"
    monkeypatch.setattr(D, "DESIGN_PACKS_DIR", target)
    return target


@pytest.fixture()
def designer_profile():
    return {
        "name": "Test Designer",
        "headline": "Product Designer",
        "skills": ["Figma", "prototyping", "user research"],
        "summary": "Product designer with 4 years of experience.",
        "experience": [
            {
                "title": "Product Designer",
                "company": "Fictional Co",
                "bullets": [
                    "Ran 12 usability testing sessions and redesigned onboarding, lifting activation 18%",
                    "Built clickable prototypes in Figma for the checkout flow",
                    "Contributed components to the company design system",
                ],
            }
        ],
        "projects": [
            {"title": "Onboarding redesign",
             "description": "End-to-end UX for mobile onboarding with user interviews and prototypes"},
        ],
    }


# --- 1. portfolio review prep packs ------------------------------------------

class TestBuildDesignPrep:
    def test_writes_pack_file(self, packs_dir, designer_profile):
        md, path = D.build_design_prep("Acme", "Product Designer", designer_profile)
        assert path.exists()
        assert path.parent == packs_dir
        assert path.suffix == ".md"
        assert "Acme" in path.name and "Product_Designer" in path.name
        assert md == path.read_text(encoding="utf-8")

    def test_honest_labeling_no_company_claims(self, packs_dir, designer_profile):
        md, _ = D.build_design_prep("Acme", "Product Designer", designer_profile)
        assert "No company-verified" in md
        assert "general" in md.lower() and "prep" in md.lower()
        # never claims questions came from the company
        assert "reported for Acme" not in md
        assert "asked at Acme" not in md

    def test_all_categories_present(self, packs_dir, designer_profile):
        md, _ = D.build_design_prep("Acme", "Product Designer", designer_profile)
        for title in ["Portfolio walkthrough", "Design process",
                      "Handling critique", "Collaboration",
                      "Design systems", "Accessibility"]:
            assert title in md

    def test_out_dir_override(self, tmp_path, designer_profile):
        custom = tmp_path / "custom"
        md, path = D.build_design_prep("Acme", "UX Designer", designer_profile,
                                       out_dir=custom)
        assert path.parent == custom
        assert path.exists()

    def test_empty_role_raises(self, packs_dir, designer_profile):
        with pytest.raises(D.DesignError):
            D.build_design_prep("Acme", "  ", designer_profile)


# --- 2. portfolio gap analyzer -------------------------------------------------

class TestAnalyzePortfolioGaps:
    JD = ("We need a product designer with strong prototyping skills, "
          "motion design experience, and a deep understanding of accessibility "
          "(WCAG). Must collaborate with cross-functional stakeholders.")

    def test_detects_jd_skills(self, designer_profile):
        result = D.analyze_portfolio_gaps(designer_profile, self.JD)
        assert "prototyping" in result["jd_skills"]
        assert "motion design" in result["jd_skills"]
        assert "accessibility" in result["jd_skills"]

    def test_covered_vs_missing(self, designer_profile):
        result = D.analyze_portfolio_gaps(designer_profile, self.JD)
        # portfolio mentions prototypes, usability testing, design system
        assert "prototyping" in result["covered"]
        assert "user research" in result["covered"] or "user research" not in result["jd_skills"]
        # no motion design anywhere in the profile
        assert "motion design" in result["missing"]
        assert "prototyping" not in result["missing"]

    def test_missing_has_concrete_suggestions(self, designer_profile):
        result = D.analyze_portfolio_gaps(designer_profile, self.JD)
        for skill in result["missing"]:
            suggestion = result["suggestions"][skill]
            assert suggestion and len(suggestion) > 20
        assert "prototype" in result["suggestions"]["motion design"].lower()

    def test_empty_jd(self, designer_profile):
        result = D.analyze_portfolio_gaps(designer_profile, "")
        assert result["jd_skills"] == []
        assert result["covered"] == []
        assert result["missing"] == []

    def test_render_gap_report(self, designer_profile):
        result = D.analyze_portfolio_gaps(designer_profile, self.JD)
        md = D.render_gap_report(result)
        assert "Portfolio Gap Report" in md
        assert "motion design" in md
        assert "covered" in md and "missing" in md
        # grounding: never fabricate
        assert "never fabricate" in md.lower()

    def test_render_empty_report(self, designer_profile):
        md = D.render_gap_report(D.analyze_portfolio_gaps(designer_profile, ""))
        assert "Portfolio Gap Report" in md
        assert "No design skills" in md


# --- 3. design concept deep-dives ----------------------------------------------

EXPECTED_SLUGS = [
    "usability_heuristics",
    "user_research_methods",
    "wcag_accessibility",
    "design_systems_tokens",
    "prototyping_fidelity",
    "information_architecture",
    "interaction_design_principles",
    "visual_hierarchy",
]


class TestDesignConcepts:
    def test_all_slugs_present(self):
        for slug in EXPECTED_SLUGS:
            assert slug in D.DESIGN_CONCEPTS

    def test_concept_structure(self):
        for slug in EXPECTED_SLUGS:
            text = D.get_concept(slug)
            assert "The idea in 60 seconds" in text
            assert "When to use" in text
            assert "Interview angle" in text

    def test_unknown_slug_raises(self):
        with pytest.raises(D.DesignError) as exc:
            D.get_concept("quantum_design")
        assert "usability_heuristics" in str(exc.value)  # lists valid slugs

    def test_slug_normalization(self):
        assert D.get_concept("WCAG-Accessibility") == D.get_concept("wcag_accessibility")


# --- 4. self-critique checklist --------------------------------------------------

class TestSelfCritiqueChecklist:
    def test_all_heuristics_present(self):
        md = D.self_critique_checklist("Onboarding redesign")
        for item in ["Clarity of user goal", "Visual hierarchy", "Consistency",
                     "Accessibility", "Error handling", "Mobile",
                     "Empty states"]:
            assert item in md

    def test_scored_and_fillable(self):
        md = D.self_critique_checklist("Onboarding redesign")
        assert "Onboarding redesign" in md
        assert "1-5" in md or "1 - 5" in md
        assert "Score" in md
        # tally: 8 items x 5
        assert "/ 40" in md

    def test_guidance_per_item(self):
        md = D.self_critique_checklist("Checkout flow")
        assert "contrast" in md.lower()
        assert "Guidance" in md

    def test_empty_desc_fallback(self):
        md = D.self_critique_checklist("")
        assert "your project" in md
