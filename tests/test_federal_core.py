"""Offline unit tests for candid.federal (USAJOBS helpers). No network."""

import unittest

from candid import federal


class TranslateToGsTest(unittest.TestCase):
    def test_output_shape(self):
        r = federal.translate_to_gs("Senior Software Engineer", 6)
        self.assertIn("grade_low", r)
        self.assertIn("grade_high", r)
        self.assertIn("rationale", r)
        self.assertIn("caveats", r)
        self.assertLessEqual(r["grade_low"], r["grade_high"])
        self.assertGreaterEqual(r["grade_low"], 5)
        self.assertLessEqual(r["grade_high"], 15)

    def test_caveat_always_present(self):
        for args in [("Engineer", 0), ("Staff Engineer", 10), ("Director", 15)]:
            r = federal.translate_to_gs(*args)
            joined = " ".join(r["caveats"]).lower()
            self.assertIn("rough estimate", joined)
            self.assertIn("not an official", joined)

    def test_experience_monotonic(self):
        low = federal.translate_to_gs("Engineer", 1)["grade_low"]
        mid = federal.translate_to_gs("Engineer", 4)["grade_low"]
        high = federal.translate_to_gs("Engineer", 9)["grade_low"]
        self.assertLessEqual(low, mid)
        self.assertLessEqual(mid, high)

    def test_senior_title_raises_band(self):
        junior = federal.translate_to_gs("Junior Analyst", 2)
        senior = federal.translate_to_gs("Senior Analyst", 2)
        self.assertLess(junior["grade_low"], senior["grade_low"])

    def test_phd_floors_at_gs11(self):
        r = federal.translate_to_gs("PhD Research Scientist", 0)
        self.assertGreaterEqual(r["grade_low"], 11)
        self.assertTrue(any("phd" in x.lower() or "doctorate" in x.lower()
                            for x in r["rationale"]))

    def test_staff_engineer_maps_high(self):
        r = federal.translate_to_gs("Staff Software Engineer", 8)
        self.assertGreaterEqual(r["grade_low"], 12)
        self.assertGreaterEqual(r["grade_high"], 14)

    def test_current_salary_adds_rationale_not_grade_change(self):
        a = federal.translate_to_gs("Senior Engineer", 6)
        b = federal.translate_to_gs("Senior Engineer", 6, current_salary=220000)
        self.assertEqual((a["grade_low"], a["grade_high"]),
                         (b["grade_low"], b["grade_high"]))
        self.assertGreater(len(b["rationale"]), len(a["rationale"]))

    def test_invalid_experience(self):
        with self.assertRaises(ValueError):
            federal.translate_to_gs("Engineer", -1)

    def test_grades_clamped(self):
        r = federal.translate_to_gs("VP of Engineering", 30)
        self.assertLessEqual(r["grade_high"], 15)
        r2 = federal.translate_to_gs("Intern", 0)
        self.assertGreaterEqual(r2["grade_low"], 5)


class TranslateFromGsTest(unittest.TestCase):
    def test_gs12_shape(self):
        r = federal.translate_from_gs("GS-12")
        self.assertEqual(r["grade"], "GS-12")
        self.assertIsNone(r["step"])
        band = r["base_pay_band"]
        self.assertLess(band["low"], band["high"])
        self.assertTrue(r["private_sector_titles"])
        self.assertIn("rough estimate", " ".join(r["caveats"]).lower())

    def test_step_interpolation(self):
        lo = federal.translate_from_gs(13, step=1)
        hi = federal.translate_from_gs(13, step=10)
        self.assertEqual(lo["base_pay_band"]["low"],
                         hi["base_pay_band"]["low"])
        self.assertIn("step 1", lo["base_pay_note"].lower())
        self.assertIn("step 10", hi["base_pay_note"].lower())

    def test_grade_formats(self):
        for g in ["gs-9", "GS9", "9", 11]:
            self.assertEqual(federal.translate_from_gs(g)["grade"], f"GS-{int(str(g).strip().upper().replace('GS', '').replace('-', ''))}")

    def test_invalid_grade(self):
        for bad in ["GS-3", "GS-16", "foo", 4]:
            with self.assertRaises(ValueError, msg=f"grade={bad}"):
                federal.translate_from_gs(bad)

    def test_invalid_step(self):
        for bad_step in [0, 11, -1]:
            with self.assertRaises(ValueError):
                federal.translate_from_gs(12, step=bad_step)

    def test_bands_increase_with_grade(self):
        prev_low = 0
        for g in range(5, 16):
            low = federal.translate_from_gs(g)["base_pay_band"]["low"]
            self.assertGreaterEqual(low, prev_low)
            prev_low = low

    def test_caveat_mentions_locality(self):
        r = federal.translate_from_gs(12)
        joined = " ".join(r["caveats"]).lower()
        self.assertIn("locality", joined)


class MatchSeriesTest(unittest.TestCase):
    def test_software_skills_top_2210_or_1550(self):
        skills = ["python", "software development", "aws", "docker",
                  "kubernetes", "machine learning"]
        top = federal.match_series(skills, top_n=3)
        codes = [m["code"] for m in top]
        self.assertTrue("2210" in codes or "1550" in codes)

    def test_stats_skills_match_1529(self):
        top = federal.match_series(
            ["statistics", "hypothesis testing", "regression", "bayesian",
             "experimental design"])
        self.assertEqual(top[0]["code"], "1529")

    def test_shape_and_ranking(self):
        matches = federal.match_series(["python", "contracts", "negotiation"])
        self.assertEqual(len(matches), 5)
        scores = [m["score"] for m in matches]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for m in matches:
            self.assertIn("code", m)
            self.assertIn("title", m)
            self.assertIn("why", m)
            self.assertIn("requirements", m)
            self.assertTrue(m["why"])

    def test_top_n_respected(self):
        self.assertEqual(len(federal.match_series(["python"], top_n=2)), 2)
        self.assertEqual(len(federal.match_series(["python"], top_n=10)), 10)

    def test_empty_skills_rejected(self):
        with self.assertRaises(ValueError):
            federal.match_series([])

    def test_engineering_skills_match_0801(self):
        top = federal.match_series(
            ["mechanical", "cad", "prototyping", "testing", "design"])
        codes = [m["code"] for m in top[:3]]
        self.assertIn("0801", codes)

    def test_render(self):
        matches = federal.match_series(["python", "sql"], top_n=2)
        text = federal.render_series_matches(matches)
        self.assertIn("2210", text)
        self.assertIn("rough estimate", text.lower())


class EligibilityChecklistTest(unittest.TestCase):
    def test_all_unknown_yields_action_items(self):
        result = federal.eligibility_checklist({})
        by_item = {i["item"]: i for i in result["items"]}
        for name in ["US citizenship", "Veterans' preference",
                     "Security clearance", "Hiring path"]:
            self.assertEqual(by_item[name]["status"], "action",
                             f"{name} should be action when unknown")

    def test_full_known_facts(self):
        result = federal.eligibility_checklist({
            "citizenship": "us_citizen",
            "veteran_status": "veteran",
            "clearance": "active",
            "federal_employee": True,
        })
        by_item = {i["item"]: i for i in result["items"]}
        self.assertEqual(by_item["US citizenship"]["status"], "ok")
        self.assertEqual(by_item["Security clearance"]["status"], "ok")
        self.assertEqual(by_item["Hiring path"]["status"], "ok")
        # veteran declared -> info, never assumed
        self.assertEqual(by_item["Veterans' preference"]["status"], "info")
        self.assertIn("DD-214", by_item["Veterans' preference"]["note"])

    def test_veteran_preference_never_assumed(self):
        result = federal.eligibility_checklist({"veteran_status": "unknown"})
        vet = next(i for i in result["items"] if i["item"] == "Veterans' preference")
        self.assertEqual(vet["status"], "action")
        result2 = federal.eligibility_checklist({})
        vet2 = next(i for i in result2["items"] if i["item"] == "Veterans' preference")
        self.assertEqual(vet2["status"], "action")

    def test_non_citizen_paths(self):
        pr = federal.eligibility_checklist({"citizenship": "permanent_resident"})
        item = next(i for i in pr["items"] if i["item"] == "US citizenship")
        self.assertEqual(item["status"], "info")

    def test_non_federal_employee_path(self):
        result = federal.eligibility_checklist({"federal_employee": False})
        item = next(i for i in result["items"] if i["item"] == "Hiring path")
        self.assertEqual(item["status"], "info")
        self.assertIn("open to the public", item["note"])

    def test_always_includes_heads_ups(self):
        result = federal.eligibility_checklist({})
        names = {i["item"] for i in result["items"]}
        for expected in ["Federal resume format", "Questionnaire / assessments",
                         "Selective factors"]:
            self.assertIn(expected, names)

    def test_status_values_valid(self):
        result = federal.eligibility_checklist({"citizenship": "us_citizen"})
        for i in result["items"]:
            self.assertIn(i["status"], {"ok", "info", "action"})
            self.assertTrue(i["note"])

    def test_bad_input_rejected(self):
        with self.assertRaises(ValueError):
            federal.eligibility_checklist("not a dict")

    def test_invalid_values_become_unknown(self):
        result = federal.eligibility_checklist({
            "citizenship": "martian",
            "veteran_status": None,
        })
        by_item = {i["item"]: i for i in result["items"]}
        self.assertEqual(by_item["US citizenship"]["status"], "action")
        self.assertEqual(by_item["Veterans' preference"]["status"], "action")

    def test_render(self):
        text = federal.render_eligibility(federal.eligibility_checklist({}))
        self.assertIn("[ACTION]", text)
        self.assertIn("US citizenship", text)


if __name__ == "__main__":
    unittest.main()
