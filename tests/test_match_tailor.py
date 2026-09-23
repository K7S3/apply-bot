"""Tests for the candid.match / candid.tailor quality improvements.

Covers: section-weighted skill extraction, "N+ years" seniority parsing,
evidence snippets, missing-skill pointers, title-alignment variants, the ATS
keyword check, the what-changed summary, the never-invent guarantee, and
score_match() backward compatibility.

Run: CANDID_DATA_DIR=<system-temp-dir>/candid-test-match python3 -m unittest tests.test_match_tailor -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = str(
    Path(tempfile.gettempdir()) / "candid-test-match")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "samples" / "candid"


def _mini_profile(**kw):
    prof = {
        "name": "Test User",
        "location": "New York, NY",
        "headline": "Data Scientist",
        "seniority": "mid",
        "years_experience": 4.0,
        "skills": ["python", "sql"],
        "experience": [
            {"title": "Data Scientist", "company": "Initech", "dates": "2023 - Present",
             "bullets": ["Built models with python", "Wrote SQL reports"]},
        ],
        "education": [],
    }
    prof.update(kw)
    return prof


def _sample_profile():
    from candid import profile as P
    return P.build_profile([(SAMPLES / "sample_resume.md").read_text()])


def _sample_jd():
    return (SAMPLES / "sample_jd.txt").read_text()


class SectionWeightedExtractionTest(unittest.TestCase):
    def test_must_vs_nice_from_headers(self):
        from candid.match import _extract_jd
        jd = "Requirements:\n- python\n\nNice to have:\n- dbt\n"
        ex = _extract_jd(jd)
        self.assertIn("python", ex["must"])
        self.assertIn("dbt", ex["nice"])
        self.assertNotIn("dbt", ex["must"])

    def test_requirements_outweigh_about_us(self):
        from candid.match import _extract_jd
        jd = "Requirements:\n- python\n\nAbout us:\nWe use excel every day.\n"
        ex = _extract_jd(jd)
        self.assertGreater(ex["items"]["python"]["weight"],
                           ex["items"]["excel"]["weight"])
        self.assertEqual(ex["items"]["excel"]["tier"], "context")

    def test_quoted_phrase_extraction(self):
        from candid.match import _extract_jd
        jd = 'Requirements:\n- Experience with "event-driven architecture" at scale\n'
        ex = _extract_jd(jd)
        self.assertIn("event-driven architecture", ex["items"])

    def test_quoted_prose_is_ignored(self):
        from candid.match import _extract_jd
        jd = 'About us:\nWe value "excellent communication skills" highly\n'
        ex = _extract_jd(jd)
        self.assertNotIn("excellent communication skills", ex["items"])

    def test_capitalized_tech_token_extraction(self):
        from candid.match import _extract_jd
        jd = "Requirements:\n- Terraform experience\n"
        ex = _extract_jd(jd)
        self.assertIn("terraform", ex["items"])
        # free-form terms never get must-have tier (too noisy)
        self.assertEqual(ex["items"]["terraform"]["tier"], "context")

    def test_rarity_weighting(self):
        from candid.match import _extract_jd
        jd = "Requirements:\n- python\n- kubernetes\n"
        ex = _extract_jd(jd)
        # kubernetes (mlops, rare) must outweigh python (ubiquitous)
        self.assertGreater(ex["items"]["mlops"]["weight"],
                           ex["items"]["python"]["weight"])

    def test_years_of_y_requirement(self):
        from candid.match import _extract_jd
        jd = "Requirements:\n- 5+ years of experience with machine learning\n"
        ex = _extract_jd(jd)
        self.assertEqual(ex["years_required"], 5.0)
        self.assertIn("machine learning", ex["must"])

    def test_jd_skills_backward_compat(self):
        from candid.match import _jd_skills
        must, nice = _jd_skills("Requirements:\n- python\n\nNice to have:\n- dbt\n")
        self.assertIsInstance(must, set)
        self.assertIsInstance(nice, set)
        self.assertIn("python", must)
        self.assertIn("dbt", nice)


class SeniorityYearsTest(unittest.TestCase):
    JD_YEARS = "We are hiring a data scientist with 6+ years of experience building models."

    def test_years_shortfall_penalty(self):
        from candid import match as M
        prof = _mini_profile(years_experience=2.0)
        r = M.score_match(prof, self.JD_YEARS, title="Data Scientist")
        self.assertEqual(r["breakdown"]["seniority"], 5.0)  # 25 - 5*4
        self.assertIn("6", r["seniority_note"])
        self.assertIn("2", r["seniority_note"])

    def test_years_covered_full_marks(self):
        from candid import match as M
        prof = _mini_profile(years_experience=7.0)
        r = M.score_match(prof, self.JD_YEARS, title="Data Scientist")
        self.assertEqual(r["breakdown"]["seniority"], 25.0)
        self.assertIn("covered", r["seniority_note"])

    def test_keyword_fallback_without_years(self):
        from candid import match as M
        jd = ("We are hiring a senior data scientist to join the team. "
              "Python and SQL required for this role, plus machine learning.")
        prof = _mini_profile(seniority="senior", years_experience=5.0)
        r = M.score_match(prof, jd, title="Senior Data Scientist")
        self.assertEqual(r["breakdown"]["seniority"], 25.0)
        self.assertIn("senior", r["seniority_note"])

    def test_years_requirement_without_profile_years_falls_back(self):
        from candid import match as M
        prof = _mini_profile(years_experience=0)
        r = M.score_match(prof, "Need 8+ years of experience. Senior data scientist.",
                          title="Senior Data Scientist")
        self.assertIn("senior", r["seniority_note"])  # keyword fallback, no crash


class ExplainabilityTest(unittest.TestCase):
    def test_evidence_snippets(self):
        from candid import match as M
        r = M.score_match(_sample_profile(), _sample_jd(),
                          title="Senior Data Scientist")
        ev = r["skill_evidence"]["python"]
        self.assertTrue(ev)
        self.assertIn("python", ev.lower())

    def test_missing_skill_pointers(self):
        from candid import match as M
        jd = "Requirements:\n- 3+ years of experience\n- Kubernetes\n- Terraform\n"
        r = M.score_match(_mini_profile(), jd, title="Data Scientist")
        self.assertIn("mlops", r["missing_skill_pointers"])
        tip = r["missing_skill_pointers"]["mlops"]
        self.assertTrue(tip.strip())
        self.assertNotIn("\n", tip)  # one line
        # terraform is context-tier: no pointer required, must-have only
        self.assertNotIn("terraform", r["missing_skill_pointers"])

    def test_confidence_low_for_thin_jd(self):
        from candid import match as M
        r = M.score_match(_mini_profile(), "Requirements:\n- python\n",
                          title="Data Scientist")
        self.assertTrue(r["confidence_note"].startswith("Low"))

    def test_confidence_high_for_rich_jd(self):
        from candid import match as M
        r = M.score_match(_sample_profile(), _sample_jd(),
                          title="Senior Data Scientist")
        self.assertTrue(r["confidence_note"].startswith("High"))


class TitleAlignmentTest(unittest.TestCase):
    def _prof_with_title(self, title):
        return _mini_profile(experience=[
            {"title": title, "company": "Initech", "dates": "2023",
             "bullets": ["did things"]},
        ])

    def test_backend_variant(self):
        from candid import match as M
        r = M.score_match(self._prof_with_title("Backend Engineer"),
                          "Build APIs and services.", title="Backend Engineer")
        self.assertEqual(r["breakdown"]["title_alignment"], 10.0)

    def test_slash_title(self):
        from candid import match as M
        r = M.score_match(self._prof_with_title("Senior Data Scientist"),
                          "ML platform work.", title="ML Engineer / Data Scientist")
        self.assertEqual(r["breakdown"]["title_alignment"], 10.0)

    def test_sibling_family_partial_credit(self):
        from candid import match as M
        r = M.score_match(self._prof_with_title("Senior Data Scientist"),
                          "Research-heavy role.", title="Applied Scientist")
        self.assertEqual(r["breakdown"]["title_alignment"], 6.0)

    def test_unrelated_title(self):
        from candid import match as M
        r = M.score_match(self._prof_with_title("Senior Data Scientist"),
                          "Make espresso.", title="Barista")
        self.assertEqual(r["breakdown"]["title_alignment"], 3.0)


class TailorAtsTest(unittest.TestCase):
    def test_ats_section_present(self):
        from candid import tailor as T
        out = T.build_resume(_sample_profile(), _sample_jd(),
                             company="Acme Analytics", role="Senior Data Scientist")
        self.assertIn("ATS KEYWORD CHECK", out)
        self.assertIn("Covered (", out)
        self.assertIn("Missing from this resume (", out)

    def test_ats_missing_lists_real_gap(self):
        from candid import tailor as T
        prof = _mini_profile(skills=["python"], experience=[])
        out = T.build_resume(prof, "Requirements:\n- python\n- dbt\n")
        ats = out.split("ATS KEYWORD CHECK")[1].split("WHAT CHANGED")[0]
        self.assertIn("python", ats.split("Missing")[0])  # covered line
        self.assertIn("dbt", ats.split("Missing from this resume")[1])


class TailorWhatChangedTest(unittest.TestCase):
    def _promo_profile(self):
        return _mini_profile(
            skills=["python", "dbt"],
            experience=[{
                "title": "Analyst", "company": "Initech", "dates": "2023",
                "bullets": [
                    "Attended team standups and wrote docs",
                    "Fixed bugs in legacy code",
                    "Helped onboard new hires",
                    "Refactored 2 modules",
                    "Rebuilt pipelines with dbt, cutting runtime 40%",
                ],
            }],
        )

    def test_what_changed_section_present(self):
        from candid import tailor as T
        out = T.build_resume(self._promo_profile(), "Requirements:\n- dbt\n- python\n")
        self.assertIn("WHAT CHANGED", out)

    def test_promotion_and_trim_detected(self):
        from candid import tailor as T
        out = T.build_resume(self._promo_profile(), "Requirements:\n- dbt\n- python\n")
        changed = out.split("WHAT CHANGED")[1]
        self.assertIn("promoted 2 to top", changed)
        self.assertIn("dbt", changed)
        self.assertIn("trimmed 1", changed)

    def test_no_reorder_message_when_already_ordered(self):
        from candid import tailor as T
        prof = _mini_profile(experience=[{
            "title": "Data Scientist", "company": "Initech", "dates": "2023",
            "bullets": ["Built models with python"],
        }])
        out = T.build_resume(prof, "Requirements:\n- python\n")
        self.assertIn("No reordering needed", out.split("WHAT CHANGED")[1])


class TailorSummaryProofTest(unittest.TestCase):
    def test_summary_leads_with_strongest_proof(self):
        from candid import tailor as T
        prof = _mini_profile(
            seniority="senior", years_experience=5.0,
            skills=["python", "xgboost"],
            experience=[{
                "title": "Data Scientist", "company": "Initech", "dates": "2023",
                "bullets": ["Cut fraud losses 22% with XGBoost",
                            "Wrote documentation"],
            }],
        )
        out = T.build_resume(prof, "Requirements:\n- xgboost\n- python\n")
        summary = out.split("EXPERIENCE")[0]
        self.assertIn("Cut fraud losses 22%", summary)


class NeverInventTest(unittest.TestCase):
    def test_no_invented_companies_skills_or_bullets(self):
        from candid import tailor as T
        prof = _sample_profile()
        jd = _sample_jd()
        out = T.build_resume(prof, jd, company="Acme Analytics",
                             role="Senior Data Scientist")
        body = out.split("Tailored for")[0]
        # the hiring company must not leak into the resume body
        self.assertNotIn("Acme Analytics", body)
        # every bullet comes verbatim from the profile
        profile_bullets = {b for e in prof["experience"] for b in e["bullets"]}
        bullet_lines = [l[2:] for l in body.splitlines() if l.startswith("• ")]
        self.assertTrue(bullet_lines)
        for b in bullet_lines:
            self.assertIn(b, profile_bullets, f"invented bullet: {b!r}")
        # skills section lists only profile skills
        skills_block = body.split("SKILLS")[1].split("ATS KEYWORD CHECK")[0]
        listed: list[str] = []
        for line in skills_block.splitlines():
            line = line.strip()
            if line.startswith("Most relevant to this role: "):
                listed += line[len("Most relevant to this role: "):].split(", ")
            elif line.startswith("Also: "):
                listed += line[len("Also: "):].split(", ")
        self.assertTrue(listed)
        for s in listed:
            self.assertIn(s, prof["skills"], f"invented skill: {s!r}")

    def test_cover_letter_proof_comes_from_profile(self):
        from candid import tailor as T
        prof = _sample_profile()
        out = T.build_cover_letter(prof, _sample_jd(), "Acme Analytics",
                                   "Senior Data Scientist", tone="confident")
        profile_bullets = {b for e in prof["experience"] for b in e["bullets"]}
        # the proof sentence is a re-cased profile bullet, not invented text
        self.assertTrue(any(
            b[:30].lower() in out.lower() for b in profile_bullets))


class BackwardCompatTest(unittest.TestCase):
    REQUIRED_KEYS = {"score", "verdict", "verdict_reason", "breakdown",
                     "skills_required", "skills_matched", "skills_missing",
                     "seniority_note", "domain_overlap", "gaps", "market"}

    def test_score_match_keys_and_shapes(self):
        from candid import match as M
        r = M.score_match(_sample_profile(), _sample_jd(),
                          title="Senior Data Scientist",
                          company="Acme Analytics", location="New York, NY")
        self.assertTrue(self.REQUIRED_KEYS <= set(r))
        self.assertEqual(set(r["breakdown"]),
                         {"skills", "seniority", "domain", "title_alignment"})
        self.assertIsInstance(r["score"], (int, float))
        self.assertIn(r["verdict"], ("GO", "CONDITIONAL", "NO-GO"))
        self.assertIsInstance(r["verdict_reason"], str)
        for k in ("skills_required", "skills_matched", "skills_missing",
                  "domain_overlap", "gaps"):
            self.assertIsInstance(r[k], list)
            self.assertTrue(all(isinstance(x, str) for x in r[k]), k)
        self.assertIsInstance(r["seniority_note"], str)
        self.assertTrue(r["market"] is None or isinstance(r["market"], dict))
        # new explainability keys are additive
        for k in ("skill_evidence", "missing_skill_pointers",
                  "confidence_note", "years_required"):
            self.assertIn(k, r, k)
        self.assertIsInstance(r["skill_evidence"], dict)
        self.assertIsInstance(r["missing_skill_pointers"], dict)
        self.assertIsInstance(r["confidence_note"], str)

    def test_breakdown_sums_to_score(self):
        from candid import match as M
        r = M.score_match(_sample_profile(), _sample_jd(),
                          title="Senior Data Scientist")
        b = r["breakdown"]
        self.assertEqual(
            round(b["skills"] + b["seniority"] + b["domain"] + b["title_alignment"], 1),
            r["score"])

    def test_render_report_plain_text(self):
        from candid import match as M
        r = M.score_match(_sample_profile(), _sample_jd(),
                          title="Senior Data Scientist", company="Acme Analytics")
        report = M.render_report(r, company="Acme Analytics",
                                 title="Senior Data Scientist")
        self.assertIsInstance(report, str)
        self.assertIn("Match score", report)
        self.assertNotIn("\x1b", report)

    def test_tone_length_value_errors_kept(self):
        from candid import tailor as T
        prof, jd = _sample_profile(), _sample_jd()
        with self.assertRaises(ValueError):
            T.build_resume(prof, jd, tone="shouty")
        with self.assertRaises(ValueError):
            T.build_resume(prof, jd, length="pamphlet")
        with self.assertRaises(ValueError):
            T.build_cover_letter(prof, jd, "Acme", "Role", tone="shouty")


if __name__ == "__main__":
    unittest.main()
