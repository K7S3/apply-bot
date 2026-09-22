"""Test suite for the candid package. Run: python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "samples" / "candid"


class ProfileTest(unittest.TestCase):
    def test_build_profile_from_sample_resume(self):
        from candid import profile as P
        text = (SAMPLES / "sample_resume.md").read_text()
        prof = P.build_profile([text], ["sample_resume.md"])
        self.assertEqual(prof["name"], "Alex Rivera")
        self.assertIn("python", prof["skills"])
        self.assertIn("machine learning", prof["skills"])
        self.assertGreaterEqual(len(prof["experience"]), 2)
        self.assertEqual(prof["experience"][0]["company"], "Meridian Financial")
        self.assertIn(prof["seniority"], ("mid", "senior"))
        self.assertGreater(prof["years_experience"], 2)

    def test_onboard_writes_json(self):
        from candid import profile as P
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "profile.json"
            prof = P.onboard(resume_path=SAMPLES / "sample_resume.md", out_path=out)
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text())
            self.assertEqual(loaded["name"], prof["name"])

    def test_onboard_rejects_missing_file(self):
        from candid import profile as P
        with self.assertRaises(P.OnboardError):
            P.onboard(resume_path="/nonexistent/resume.pdf")

    def test_load_profile_missing_gives_guidance(self):
        from candid import profile as P, config as C
        orig = C.PROFILE_PATH
        C.PROFILE_PATH = Path(tempfile.mkdtemp()) / "nope.json"
        try:
            with self.assertRaises(P.OnboardError) as cm:
                P.load_profile()
            self.assertIn("onboard", str(cm.exception))
        finally:
            C.PROFILE_PATH = orig


class MatchTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P
        text = (SAMPLES / "sample_resume.md").read_text()
        self.prof = P.build_profile([text])
        self.jd = (SAMPLES / "sample_jd.txt").read_text()

    def test_score_match(self):
        from candid import match as M
        r = M.score_match(self.prof, self.jd, title="Senior Data Scientist",
                          company="Acme Analytics", location="New York, NY")
        self.assertGreaterEqual(r["score"], 0)
        self.assertLessEqual(r["score"], 100)
        self.assertIn(r["verdict"], ("GO", "CONDITIONAL", "NO-GO"))
        self.assertIn("python", r["skills_matched"])
        self.assertEqual(r["breakdown"]["skills"] + r["breakdown"]["seniority"]
                         + r["breakdown"]["domain"] + r["breakdown"]["title_alignment"],
                         r["score"])

    def test_strong_sample_scores_well(self):
        from candid import match as M
        r = M.score_match(self.prof, self.jd, title="Senior Data Scientist")
        self.assertGreaterEqual(r["score"], 60, f"sample should be a good fit: {r}")

    def test_fetch_jd_rejects_garbage(self):
        from candid import match as M
        with self.assertRaises(M.MatchError):
            M.fetch_jd("hi")


class TailorTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        self.jd = (SAMPLES / "sample_jd.txt").read_text()

    def test_resume_never_invents_employers(self):
        from candid import tailor as T
        out = T.build_resume(self.prof, self.jd, company="Acme Analytics",
                             role="Senior Data Scientist")
        self.assertIn("ALEX RIVERA", out.upper())
        self.assertNotIn("Acme Analytics", out.split("Tailored for")[0])
        self.assertIn("Meridian Financial", out)

    def test_cover_letter_tones(self):
        from candid import tailor as T
        for tone in ("concise", "confident", "formal", "warm"):
            out = T.build_cover_letter(self.prof, self.jd, "Acme Analytics",
                                       "Senior Data Scientist", tone=tone)
            self.assertIn("Acme Analytics", out)
            self.assertIn("Alex Rivera", out)

    def test_cover_letter_needs_company_and_role(self):
        from candid import tailor as T
        with self.assertRaises(ValueError):
            T.build_cover_letter(self.prof, self.jd, "", "")


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "tracker.json"

    def tearDown(self):
        self.td.cleanup()

    def test_add_list_update_stats(self):
        from candid import tracker as T
        r1 = T.add("Acme", "Data Scientist", path=self.path)
        r2 = T.add("Globex", "ML Engineer", status="applied", path=self.path)
        self.assertEqual(r1["id"], 1)
        self.assertEqual(len(T.list_apps(path=self.path)), 2)
        self.assertEqual(len(T.list_apps(status="applied", path=self.path)), 1)
        T.update(1, status="selected_for_interview", path=self.path)
        s = T.stats(path=self.path)
        self.assertEqual(s["counts"]["selected_for_interview"], 1)
        self.assertEqual(s["counts"]["applied"], 1)

    def test_duplicate_rejected(self):
        from candid import tracker as T
        T.add("Acme", "Data Scientist", path=self.path)
        with self.assertRaises(T.TrackerError):
            T.add("acme", "data scientist", path=self.path)

    def test_bad_status_rejected(self):
        from candid import tracker as T
        with self.assertRaises(T.TrackerError):
            T.add("Acme", "DS", status="maybe", path=self.path)


class SalaryTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = Path(self.td.name) / "salary.db"

    def tearDown(self):
        self.td.cleanup()

    def test_parse_posted_range(self):
        from candid import salary as S
        jd = (SAMPLES / "sample_jd.txt").read_text()
        parsed = S.parse_posted_range(jd)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["low"], 150000)
        self.assertEqual(parsed["high"], 185000)

    def test_parse_hourly_annualizes(self):
        from candid import salary as S
        parsed = S.parse_posted_range("Pay: $60 - $80 per hour")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["low"], 60 * 2080)

    def test_import_lca_sample(self):
        from candid import salary as S
        res = S.import_lca(SAMPLES / "sample_lca.csv", path=self.db)
        self.assertEqual(res["imported"], 9)  # 10 rows, 1 withdrawn skipped
        self.assertEqual(res["skipped"], 1)

    def test_lookup_percentiles(self):
        from candid import salary as S
        S.import_lca(SAMPLES / "sample_lca.csv", path=self.db)
        r = S.lookup(company="Acme Analytics", title="Data Scientist",
                     location="New York", path=self.db)
        self.assertGreater(r["n"], 0)
        self.assertLessEqual(r["p25"], r["median"])
        self.assertLessEqual(r["median"], r["p75"])
        self.assertTrue(any("dol_lca" in s for s in r["sources"]))

    def test_lookup_empty(self):
        from candid import salary as S
        r = S.lookup(company="No Such Company", title="No Such Role", path=self.db)
        self.assertEqual(r["n"], 0)

    def test_invalid_range_rejected(self):
        from candid import salary as S
        with self.assertRaises(S.SalaryError):
            S.add_range("X", "Y", 200000, 100000, path=self.db)


class JudgeTest(unittest.TestCase):
    def _problem(self):
        from candid import mock as M
        return M.get_problem("two-sum")

    def test_accepted(self):
        from candid import mock_judge as J
        p = self._problem()
        r = J.judge(p, p["reference_solution"])
        self.assertEqual(r["verdict"], "accepted")

    def test_wrong_answer(self):
        from candid import mock_judge as J
        p = self._problem()
        r = J.judge(p, "def solve(nums, target):\n    return [0, 0]\n")
        self.assertEqual(r["verdict"], "wrong_answer")
        details = J.failing_details(r)
        self.assertTrue(any("Visible test" in d for d in details))

    def test_runtime_error(self):
        from candid import mock_judge as J
        p = self._problem()
        r = J.judge(p, "def solve(nums, target):\n    return 1 / 0\n")
        self.assertEqual(r["verdict"], "runtime_error")

    def test_syntax_error_is_runtime_error(self):
        from candid import mock_judge as J
        p = self._problem()
        r = J.judge(p, "def solve(nums, target)\n    return []\n")
        self.assertEqual(r["verdict"], "runtime_error")

    def test_time_limit(self):
        from candid import mock_judge as J
        p = self._problem()
        r = J.judge(p, "def solve(nums, target):\n    while True:\n        pass\n",
                    per_test_timeout=1.0)
        self.assertEqual(r["verdict"], "time_limit_exceeded")

    def test_empty_code_rejected(self):
        from candid import mock_judge as J
        p = self._problem()
        with self.assertRaises(J.JudgeError):
            J.judge(p, "   \n")


class MockBankTest(unittest.TestCase):
    def test_bank_loads(self):
        from candid import mock as M
        problems = M.list_problems()
        self.assertGreaterEqual(len(problems), 10)
        topics = {p["topic"] for p in problems}
        self.assertTrue({"arrays", "strings", "dp", "graphs"} <= topics)

    def test_all_references_pass(self):
        from candid import mock as M, mock_judge as J
        for meta in M.list_problems():
            p = M.get_problem(meta["id"])
            for field in ("statement", "function", "visible_tests", "hints",
                          "reference_solution", "complexity"):
                self.assertTrue(p.get(field), f"{p['id']} missing {field}")
            r = J.judge(p, p["reference_solution"], per_test_timeout=5.0)
            self.assertEqual(r["verdict"], "accepted", f"{p['id']}: {r['summary']}")

    def test_star_scoring(self):
        from candid import mock as M
        good = ("At Meridian I owned fraud modeling for the payments team. "
                "I decided to replace rules with XGBoost, built the pipeline, "
                "and convinced risk to trial it. Fraud losses decreased 22%, "
                "saving $3.1M per year. I learned to involve stakeholders earlier.")
        r = M.score_star(good)
        self.assertGreaterEqual(r["score"], r["max"] * 0.6)
        weak = M.score_star("It went fine.")
        self.assertLess(weak["score"], r["score"])


class PrepTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P, config as C
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        self.orig_packs = C.PREP_PACKS_DIR
        self.td = tempfile.TemporaryDirectory()
        C.PREP_PACKS_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def test_unknown_company_says_so_explicitly(self):
        from candid import prep as P
        md, path = P.build_pack(self.prof, "Fictional Corp", "Data Scientist")
        self.assertIn("No verified company-specific questions found", md)
        self.assertTrue(path.exists())

    def test_known_company_has_attributed_questions(self):
        from candid import prep as P
        md, _ = P.build_pack(self.prof, "Capital One", "Data Scientist")
        self.assertIn("Source:", md)
        self.assertNotIn("No verified company-specific questions found", md)

    def test_pack_has_all_sections(self):
        from candid import prep as P
        md, _ = P.build_pack(self.prof, "Fictional Corp", "Data Scientist")
        for section in ("Concept deep-dives", "Mock interview", "Compensation benchmark",
                        "Day-Before Checklist"):
            self.assertIn(section, md)

    def test_prep_questions_bank_integrity(self):
        from candid.prep_questions import QUESTIONS_DB
        total = 0
        for slug, questions in QUESTIONS_DB.items():
            for q in questions:
                total += 1
                self.assertTrue(q.get("q"), slug)
                self.assertTrue(q.get("source"), slug)
                self.assertTrue(q.get("url"), slug)
        self.assertGreaterEqual(total, 60)


class OfferNegotiateTest(unittest.TestCase):
    def test_normalize_math(self):
        from candid import offer as O
        r = O.normalize({"company": "Acme", "role": "DS", "base": 150000,
                         "bonus_target_pct": 10, "equity_total": 200000,
                         "vest_years": 4, "benefits_value": 15000})
        self.assertEqual(r["target_bonus"], 15000)
        self.assertEqual(r["annual_equity"], 50000)
        self.assertEqual(r["normalized_annual"], 150000 + 15000 + 50000 + 15000)

    def test_vest_schedule_year1(self):
        from candid import offer as O
        r = O.normalize({"company": "Acme", "role": "DS", "base": 150000,
                         "equity_total": 200000, "vest_years": 4,
                         "vest_schedule": "40/30/20/10"})
        self.assertEqual(r["year1_equity_vest"], 80000)

    def test_bad_vest_schedule_rejected(self):
        from candid import offer as O
        with self.assertRaises(O.OfferError):
            O.normalize({"company": "A", "role": "R", "vest_schedule": "50/20"})

    def test_negotiate_scripts(self):
        from candid import negotiate as N
        s = N.get_script("lowball_anchor", role="DS", location="NYC",
                         market_range="$150k-$185k", current_comp="$140k", target="$170k")
        self.assertIn("$170k", s)
        self.assertNotIn("{target}", s)
        with self.assertRaises(ValueError):
            N.get_script("nope")

    def test_counter_email(self):
        from candid import negotiate as N
        out = N.counter_email("Alex Rivera", "Sam", "DS", "Acme", "NYC",
                              base_ask_reason="market data supports it")
        self.assertIn("Alex Rivera", out)
        self.assertIn("Acme", out)


class FollowupTest(unittest.TestCase):
    def test_thank_you(self):
        from candid import followup as F
        out = F.thank_you("Alex Rivera", "Priya", "Data Scientist", "Acme",
                          topics="the ranking discussion", tone="concise")
        self.assertIn("Priya", out)
        self.assertIn("Alex Rivera", out)

    def test_check_in(self):
        from candid import followup as F
        out = F.check_in("Alex Rivera", "Sam", "Data Scientist", "Acme")
        self.assertIn("Sam", out)


if __name__ == "__main__":
    unittest.main()
