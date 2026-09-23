"""Tests for the USAJOBS/federal integration (batch 17, worker C).

Covers candid.fedpay (2026 OPM GS pay tables) and candid.fedresume
(federal resume notes, KSA hints, announcement scoring). All offline.
"""

import unittest

from candid import fedpay, fedresume


def _sample_profile() -> dict:
    return {
        "name": "Alex Rivera",
        "headline": "Machine Learning Engineer",
        "location": "New York, NY",
        "summary": "ML engineer building ranking models.",
        "skills": ["python", "machine learning", "sql", "deep learning",
                   "statistics", "cloud"],
        "experience": [
            {"title": "Machine Learning Engineer", "company": "Acme Ads",
             "dates": "2021 - Present",
             "bullets": [
                 "Built learning-to-rank models serving 50M requests/day.",
                 "Cut training cost 30% with distributed data pipelines.",
                 "Ran A/B tests and analyzed results with Python and SQL.",
             ]},
            {"title": "Data Analyst", "company": "Beta Corp",
             "dates": "June 2019 - May 2021",
             "bullets": [
                 "Built dashboards tracking funnel metrics.",
                 "Automated weekly reporting with Python.",
             ]},
        ],
        "education": [{"school": "State University", "degree": "B.S. Computer Science",
                       "dates": "2015 - 2019"}],
        "years_experience": 5.0,
        "seniority": "mid",
        "domains": ["data science", "ads / monetization"],
        "source_files": [],
    }


_GOOD_ANNOUNCEMENT = {
    "text": (
        "Computer Scientist, GS-1550-12/13\n"
        "Location: New York, NY\n"
        "Specialized Experience: One year of specialized experience equivalent "
        "to the GS-11 level. Specialized experience includes developing machine "
        "learning models in Python, statistical analysis of large datasets, "
        "and deploying models to cloud production environments.\n"
        "Requirements: Skill in statistical analysis. Ability to communicate "
        "technical findings to non-technical stakeholders. Knowledge of "
        "experimental design."
    ),
    "series": "1550",
    "grade": "GS-12/13",
    "location": "New York, NY",
    "remote": False,
}

_BAD_ANNOUNCEMENT = {
    "text": (
        "Contract Specialist, GS-1102-15\n"
        "Location: Anchorage, AK\n"
        "Specialized Experience: One year of specialized experience in federal "
        "procurement, contract negotiation, and acquisition regulations.\n"
        "Requirements: Skill in cost analysis of procurement contracts. "
        "Knowledge of the Federal Acquisition Regulation."
    ),
    "series": "1102",
    "grade": "GS-15",
    "location": "Anchorage, AK",
    "remote": False,
}


class TestFedPay(unittest.TestCase):
    def test_base_table_spot_rates(self):
        # 2026 OPM base rates (annual), spot-checked against OPM + federalpay.
        self.assertEqual(fedpay.gs_pay(5, 1)["annual"], 34799)
        self.assertEqual(fedpay.gs_pay(13, 10)["annual"], 118204)
        self.assertEqual(fedpay.gs_pay(1, 9)["annual"], 27550)
        self.assertEqual(fedpay.gs_pay(15, 1)["annual"], 126384)
        self.assertEqual(fedpay.gs_pay(15, 10)["annual"], 164301)

    def test_table_shape_monotonic(self):
        for grade in range(1, 16):
            steps = [fedpay.gs_pay(grade, s)["annual"] for s in range(1, 11)]
            self.assertEqual(len(steps), 10)
            self.assertTrue(all(b >= a for a, b in zip(steps, steps[1:])),
                            f"grade {grade} steps not non-decreasing")

    def test_invalid_grade_step(self):
        with self.assertRaises(ValueError):
            fedpay.gs_pay(0, 1)
        with self.assertRaises(ValueError):
            fedpay.gs_pay(16, 1)
        with self.assertRaises(ValueError):
            fedpay.gs_pay(5, 0)
        with self.assertRaises(ValueError):
            fedpay.gs_pay(5, 11)

    def test_locality_adjustment_values(self):
        # Verified 2026 locality percentages.
        self.assertAlmostEqual(
            fedpay.locality_adjustment("Washington-Baltimore-Arlington"), 33.94)
        self.assertAlmostEqual(
            fedpay.locality_adjustment("New York-Newark"), 37.95)
        self.assertAlmostEqual(
            fedpay.locality_adjustment("San Francisco"), 46.34)
        self.assertAlmostEqual(
            fedpay.locality_adjustment("Los Angeles-Long Beach"), 36.47)
        self.assertAlmostEqual(fedpay.locality_adjustment("Rest of U.S."), 17.06)
        self.assertIsNone(fedpay.locality_adjustment("Atlantis"))
        self.assertIsNone(fedpay.locality_adjustment(""))

    def test_locality_pay_matches_opm_published(self):
        # GS-5 step 1, DC locality: OPM publishes $46,610.
        self.assertEqual(
            fedpay.gs_pay(5, 1, locality="Washington, DC")["annual"], 46610)
        # GS-9 step 1, NY locality: OPM publishes $72,737.
        self.assertEqual(
            fedpay.gs_pay(9, 1, locality="New York-Newark")["annual"], 72737)
        # GS-15 step 1, SF locality: OPM publishes $184,950.
        self.assertEqual(
            fedpay.gs_pay(15, 1, locality="San Francisco")["annual"], 184950)

    def test_locality_pay_cap(self):
        # GS-15 step 5 SF exceeds the 2026 Level IV cap -> capped at $197,200.
        r = fedpay.gs_pay(15, 5, locality="San Francisco")
        self.assertEqual(r["annual"], 197200)
        self.assertTrue(r["capped"])
        self.assertEqual(r["locality_pct"], 46.34)

    def test_unknown_locality_raises(self):
        with self.assertRaises(ValueError):
            fedpay.gs_pay(5, 1, locality="Moon Base")

    def test_grade_salary_range(self):
        r = fedpay.grade_salary_range(12)
        self.assertEqual(r["step1"], 76463)
        self.assertEqual(r["step10"], 99404)
        self.assertEqual(r["year"], 2026)
        self.assertIn("2026", r["caveat"])
        self.assertIn("2026", r["source"])
        rl = fedpay.grade_salary_range(12, locality="New York-Newark")
        self.assertEqual(rl["step1"], 105481)  # OPM NY table
        self.assertEqual(rl["step10"], 137128)

    def test_table_info_provenance(self):
        info = fedpay.table_info()
        self.assertEqual(info["year"], 2026)
        self.assertIn("2026", info["source"])
        self.assertIn("2026", info["caveat"])


class TestFederalResumeNotes(unittest.TestCase):
    def test_notes_structure(self):
        notes = fedresume.federal_resume_notes(_sample_profile())
        for key in ("required_blocks", "per_role", "formatting_rules",
                    "veterans", "groundedness"):
            self.assertIn(key, notes)
        self.assertEqual(len(notes["per_role"]), 2)
        self.assertTrue(any("MM/YYYY" in b["note"]
                            for b in notes["required_blocks"]))

    def test_per_role_prompts_grounded(self):
        notes = fedresume.federal_resume_notes(_sample_profile())
        first = notes["per_role"][0]  # "2021 - Present" -> year_only dates
        joined = " ".join(first["prompts"])
        self.assertIn("MM/YYYY", joined)
        self.assertIn("hours per week", joined.lower())
        self.assertIn("supervisor", joined.lower())
        # Second role already has month/year dates -> no MM/YYYY prompt.
        second = " ".join(notes["per_role"][1]["prompts"])
        self.assertNotIn("MM/YYYY", second)
        # Prompts must not invent experience: no fabricated employers.
        for r in notes["per_role"]:
            for p in r["prompts"]:
                self.assertNotIn("NASA", p)
                self.assertNotIn("PhD", p)

    def test_render_notes(self):
        out = fedresume.render_notes(fedresume.federal_resume_notes(_sample_profile()))
        self.assertIn("FEDERAL RESUME CHECKLIST", out)
        self.assertIn("hours per week", out.lower())
        self.assertIn("Veterans", out)

    def test_empty_profile(self):
        notes = fedresume.federal_resume_notes({})
        self.assertEqual(notes["per_role"], [])
        self.assertTrue(notes["required_blocks"])  # checklist still emitted
        self.assertIn("never infers veteran status",
                      notes["veterans"]["guidance"])


class TestKsaHints(unittest.TestCase):
    def test_extracts_ksa_themes(self):
        text = ("Requirements: Skill in statistical analysis. Ability to "
                "communicate technical findings. Knowledge of experimental "
                "design. Experience with cloud platforms.")
        hints = fedresume.ksa_hints(text)
        kinds = {h["kind"] for h in hints}
        self.assertTrue({"skill", "ability", "knowledge", "experience"} <= kinds)
        for h in hints:
            self.assertIn("phrase", h)
            self.assertIn("prep_pointer", h)
            self.assertTrue(len(h["phrase"]) >= 4)

    def test_empty_and_dedup(self):
        self.assertEqual(fedresume.ksa_hints(""), [])
        self.assertEqual(fedresume.ksa_hints("No requirements listed here."), [])
        text = "Skill in Python. Skill in python."
        hints = fedresume.ksa_hints(text)
        self.assertEqual(len(hints), 1)

    def test_specialized_experience_hint(self):
        text = ("Specialized Experience: one year of experience developing "
                "machine learning models for production use.")
        hints = fedresume.ksa_hints(text)
        self.assertTrue(any(h["kind"] == "specialized" for h in hints))


class TestScoreFederal(unittest.TestCase):
    def test_good_fit(self):
        r = fedresume.score_federal(_sample_profile(), _GOOD_ANNOUNCEMENT)
        self.assertGreaterEqual(r["score"], 50)
        self.assertIn(r["verdict"], ("GO", "CONDITIONAL"))
        self.assertEqual(set(r["breakdown"]),
                         {"specialized_experience", "series_fit",
                          "grade_band_fit", "location"})
        self.assertIsInstance(r["gaps"], list)
        self.assertTrue(r["ksa_hints"])

    def test_bad_fit(self):
        r = fedresume.score_federal(_sample_profile(), _BAD_ANNOUNCEMENT)
        self.assertLess(r["score"], 50)
        self.assertEqual(r["verdict"], "NO-GO")
        self.assertTrue(r["gaps"])

    def test_string_announcement_accepted(self):
        r = fedresume.score_federal(_sample_profile(),
                                    "Data Scientist GS-1550-13, remote. "
                                    "Specialized experience in machine learning "
                                    "with Python.")
        self.assertGreaterEqual(r["score"], 0)
        self.assertLessEqual(r["score"], 100)

    def test_remote_gets_full_location(self):
        r = fedresume.score_federal(_sample_profile(),
                                    {"text": "Remote role. Specialized "
                                             "experience in machine learning.",
                                     "remote": True})
        self.assertEqual(r["breakdown"]["location"], 15.0)

    def test_grade_band_parsing_and_estimation(self):
        self.assertEqual(
            fedresume._parse_grade_band("", {"grade": "GS-12/13"}), (12, 13))
        self.assertEqual(fedresume._parse_grade_band("GS-9 position", {}), (9, 9))
        self.assertIsNone(fedresume._parse_grade_band("no grade here", {}))
        from candid import federal as fed
        r = fed.translate_to_gs("Machine Learning Engineer", 5.0)
        self.assertEqual(fedresume._estimate_gs_band(_sample_profile()),
                         (r["grade_low"], r["grade_high"]))

    def test_series_uses_federal_module(self):
        # candid.federal exists in this tree; its SERIES table should be used.
        kws = fedresume._keywords_for_series("1550")
        self.assertIsNotNone(kws)
        self.assertIn("machine learning", kws)

    def test_series_defensive_fallback(self):
        # If the federal module cannot be imported (_keywords_for_series
        # returns None), the bundled keyword fallback still scores.
        from unittest import mock
        with mock.patch.object(fedresume, "_keywords_for_series",
                               return_value=None):
            score, detail = fedresume._series_fit_score(
                _sample_profile(), "series 1550 computer scientist", {})
            self.assertGreater(score, 0)
            self.assertEqual(detail["series"], "1550")
            self.assertIn("machine learning", detail["series_keywords"])

    def test_render_report(self):
        r = fedresume.score_federal(_sample_profile(), _GOOD_ANNOUNCEMENT)
        out = fedresume.render_federal_report(r)
        self.assertIn("Federal match score", out)
        self.assertIn(r["verdict"], out)

    def test_empty_announcement_neutral(self):
        r = fedresume.score_federal(_sample_profile(), "")
        self.assertGreaterEqual(r["score"], 0)
        self.assertLessEqual(r["score"], 100)


if __name__ == "__main__":
    unittest.main()
