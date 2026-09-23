"""Tests for the interview-prep + offers + mock-interview improvements.

Run: CANDID_DATA_DIR=<system-temp-dir>/candid-test-prep python -m unittest discover -s tests
(also honored when set in-process below).
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

_CANDID_TEST_PREP = str(Path(tempfile.gettempdir()) / "candid-test-prep")
os.environ.setdefault("CANDID_DATA_DIR", _CANDID_TEST_PREP)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "samples" / "candid"

TEST_DIR = Path(_CANDID_TEST_PREP)


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


class PrepGapsTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P, config as C
        _clean()
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        self.orig_packs = C.PREP_PACKS_DIR
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        C.PREP_PACKS_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def test_gap_prioritizes_deepdives(self):
        from candid import prep as P
        md, _ = P.build_pack(self.prof, "Fictional Corp", "Data Scientist",
                             gaps=["Missing must-have skill: sql"])
        self.assertIn("SQL Window Functions", md)
        # gap-driven deep-dive comes before unrelated ones
        self.assertLess(md.index("SQL Window Functions"), md.index("A/B Testing"))

    def test_gap_section_lists_gaps(self):
        from candid import prep as P
        md, _ = P.build_pack(self.prof, "Fictional Corp", "Data Scientist",
                             gaps=["Missing must-have skill: machine learning",
                                   "Seniority gap: role wants senior level"])
        self.assertIn("Priority focus", md)
        self.assertIn("Missing must-have skill: machine learning", md)

    def test_no_gaps_still_works(self):
        from candid import prep as P
        md, path = P.build_pack(self.prof, "Fictional Corp", "Data Scientist")
        self.assertNotIn("Priority focus", md)
        self.assertTrue(path.exists())

    def test_gap_categories_mapping(self):
        from candid import prep as P
        cats = P._gap_categories(["Missing must-have skill: sql",
                                  "No overlap on JD domain keywords: ['pricing']"])
        self.assertIn("sql", cats)


class PrepStarTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        self.orig_packs = C.PREP_PACKS_DIR
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        C.PREP_PACKS_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def test_star_prompts_use_real_bullets(self):
        from candid import prep as P
        profile = {"name": "Test Person", "experience": [
            {"title": "Data Scientist", "company": "Acme",
             "bullets": ["Cut p99 latency 40% by rewriting the ranking pipeline in Rust"]},
        ]}
        md, _ = P.build_pack(profile, "Fictional Corp", "Data Scientist")
        self.assertIn("STAR story prompts", md)
        # the actual bullet text shows up, mapped to a tell-me-about-a-time prompt
        self.assertIn("Cut p99 latency 40%", md)
        self.assertIn("Tell me about a time", md)

    def test_star_section_handles_empty_profile(self):
        from candid import prep as P
        md, _ = P.build_pack({}, "Fictional Corp", "Data Scientist")
        self.assertIn("STAR story prompts", md)

    def test_pack_has_new_sections(self):
        from candid import profile as Prof, prep as P
        prof = Prof.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        md, _ = P.build_pack(prof, "Fictional Corp", "Data Scientist")
        for section in ("STAR story prompts", "Company-research checklist",
                        "Concept deep-dives", "Mock interview",
                        "Compensation benchmark", "Day-Before Checklist"):
            self.assertIn(section, md)


class FollowupDraftTest(unittest.TestCase):
    def test_subject_lines_present(self):
        from candid import followup as F
        self.assertIn("Subject:", F.thank_you("Alex", "Priya", "DS", "Acme"))
        self.assertIn("Subject:", F.check_in("Alex", "Sam", "DS", "Acme"))
        self.assertIn("Subject:", F.referral_ask("Alex", "Jo", "DS", "Acme"))

    def test_timing_advice_present(self):
        from candid import followup as F
        for draft in (F.thank_you("Alex", "Priya", "DS", "Acme"),
                      F.check_in("Alex", "Sam", "DS", "Acme"),
                      F.referral_ask("Alex", "Jo", "DS", "Acme")):
            self.assertIn("Timing:", draft)

    def test_new_enthusiastic_tone(self):
        from candid import followup as F
        out = F.thank_you("Alex", "Priya", "DS", "Acme", tone="enthusiastic")
        self.assertIn("Priya", out)
        self.assertIn("Subject:", out)
        with self.assertRaises(ValueError):
            F.thank_you("Alex", "Priya", "DS", "Acme", tone="nope")


class OfferMathTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.path = TEST_DIR / "offers.json"

    def test_annualized_equity(self):
        from candid import offer as O
        r = O.normalize({"company": "Acme", "role": "DS", "base": 150000,
                         "equity_total": 400000, "vest_years": 4})
        self.assertEqual(r["annual_equity"], 100000)

    def test_signon_amortized_over_two_years(self):
        from candid import offer as O
        r = O.normalize({"company": "Acme", "role": "DS", "base": 100000,
                         "bonus_target_pct": 10, "sign_on": 50000,
                         "equity_total": 200000, "vest_years": 4,
                         "benefits_value": 5000})
        self.assertEqual(r["signon_amortized_2yr"], 25000)
        self.assertEqual(r["normalized_annual"],
                         100000 + 10000 + 25000 + 50000 + 5000)
        # year-1 total still counts the full sign-on
        self.assertEqual(r["year1_total"], 100000 + 10000 + 50000 + 50000 + 5000)

    def test_no_signon_unchanged(self):
        from candid import offer as O
        r = O.normalize({"company": "Acme", "role": "DS", "base": 150000,
                         "bonus_target_pct": 10, "equity_total": 200000,
                         "vest_years": 4, "benefits_value": 15000})
        self.assertEqual(r["signon_amortized_2yr"], 0)
        self.assertEqual(r["normalized_annual"], 150000 + 15000 + 50000 + 15000)

    def test_comparison_table_and_export(self):
        from candid import offer as O
        O.add({"company": "Acme", "role": "DS", "base": 150000, "sign_on": 40000,
               "equity_total": 200000, "vest_years": 4}, path=self.path)
        O.add({"company": "Beta", "role": "DS", "base": 160000,
               "equity_total": 120000, "vest_years": 4}, path=self.path)
        offers = O.list_offers(path=self.path)
        table = O.render_comparison(offers)
        self.assertIn("Normalized $/yr", table)
        self.assertIn("Acme", table)
        self.assertIn("Beta", table)
        self.assertIn("Rough tax note", table)
        out = O.export_comparison(offers, path=TEST_DIR / "comparison.md")
        self.assertTrue(out.exists())
        md = out.read_text(encoding="utf-8")
        self.assertIn("| Company |", md)
        self.assertIn("Normalized $/yr", md)


class NegotiateTest(unittest.TestCase):
    def test_leveling_up_push_renders(self):
        from candid import negotiate as N
        s = N.get_script("leveling_up_push", scope="ads ranking",
                         target_level="E5", offered_level="E4",
                         review_months="12")
        self.assertIn("E5", s)
        self.assertNotIn("{target_level}", s)
        self.assertNotIn("{scope}", s)

    def test_remote_flexibility_renders(self):
        from candid import negotiate as N
        s = N.get_script("remote_flexibility", remote_ask="2 remote days a week",
                         example_schedule="Tue/Thu from home",
                         onsite_commitment="team onsites and planning weeks")
        self.assertIn("2 remote days a week", s)
        self.assertNotIn("{remote_ask}", s)

    def test_playbook_has_precall_checklist(self):
        from candid import negotiate as N
        playbook = N.render_playbook()
        self.assertIn("Pre-call checklist", playbook)
        self.assertIn("leveling_up_push", playbook)
        self.assertIn("remote_flexibility", playbook)


class JudgeHardeningTest(unittest.TestCase):
    def test_infinite_loop_fails_fast(self):
        from candid import mock as M, mock_judge as J
        p = M.get_problem("two-sum")
        t0 = time.monotonic()
        r = J.judge(p, "def solve(nums, target):\n    while True:\n        pass\n",
                    per_test_timeout=0.3)
        elapsed = time.monotonic() - t0
        self.assertEqual(r["verdict"], "time_limit_exceeded")
        self.assertLess(elapsed, 15, f"judge took {elapsed:.1f}s on infinite loop")
        self.assertTrue(any("infinite loop" in (t.get("error") or "").lower()
                            for t in r["tests"] if not t.get("hidden")))

    def test_memory_limit_enforced(self):
        from candid import mock as M, mock_judge as J
        p = M.get_problem("two-sum")
        r = J.judge(p, "def solve(nums, target):\n"
                       "    x = bytearray(700 * 1024 * 1024)\n"
                       "    return [0, 1]\n",
                    per_test_timeout=2.0)
        self.assertEqual(r["verdict"], "runtime_error")
        self.assertTrue(any("MemoryError" in (t.get("error") or "")
                            for t in r["tests"]))

    def test_new_problems_reference_solutions_pass(self):
        from candid import mock as M, mock_judge as J
        for pid in ("merge-intervals", "kth-largest", "word-break",
                    "valid-parentheses"):
            p = M.get_problem(pid)
            self.assertTrue(p.get("visible_tests"), pid)
            self.assertTrue(p.get("hidden_tests"), pid)
            self.assertTrue(p.get("hints"), pid)
            r = J.judge(p, p["reference_solution"], per_test_timeout=5.0)
            self.assertEqual(r["verdict"], "accepted",
                             f"{pid}: {r['summary']}")

    def test_render_verdict_readable(self):
        from candid import mock as M, mock_judge as J
        p = M.get_problem("two-sum")
        r = J.judge(p, "def solve(nums, target):\n    return [0, 0]\n")
        out = M.render_verdict("two-sum", r)
        self.assertIn("two-sum", out)
        self.assertIn("tests passed", out)
        self.assertIn("Visible test", out)


if __name__ == "__main__":
    unittest.main()
