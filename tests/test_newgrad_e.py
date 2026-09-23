"""Tests for batch-88-e (new-grad track): new-grad referral outreach,
classmates search helper, and the first-job checklist.

Run: CANDID_DATA_DIR=/tmp/candid-test-newgrad python -m unittest tests.test_newgrad_e -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-newgrad")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import checklist as CL
from candid import followup as F
from candid import referrals as R


def _fake_profile():
    return {
        "name": "Keshavan",
        "education": [
            {"school": "Georgia Tech", "degree": "B.S. Computer Science",
             "dates": "2022 - 2026"},
        ],
    }


class NewGradDraftTest(unittest.TestCase):
    def test_cold_variant_references_school_alum(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="cold")
        self.assertIn("fellow Georgia Tech alum", d)

    def test_cold_variant_asks_for_chat_and_referral(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="cold")
        self.assertIn("15-min chat", d)
        self.assertIn("referral", d)

    def test_cold_variant_fits_connection_note(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="cold")
        body = d.split("\n\n*Timing:")[0]
        self.assertLessEqual(len(body), 300)

    def test_warm_variant_references_classmate_and_year(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="warm")
        self.assertIn("classmates at Georgia Tech", d)
        self.assertIn("class of 2026", d)

    def test_warm_variant_fits_connection_note(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="warm")
        body = d.split("\n\n*Timing:")[0]
        self.assertLessEqual(len(body), 300)

    def test_name_role_company_substituted(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="cold")
        self.assertIn("Keshavan", d)
        self.assertIn("New Grad SWE", d)
        self.assertIn("Acme", d)
        self.assertIn("Priya", d)

    def test_invalid_variant_raises(self):
        with self.assertRaises(ValueError):
            F.new_grad_referral_ask("K", "P", "R", "C", "S", "2026",
                                    variant="lukewarm")

    def test_missing_school_falls_back(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "", "", variant="cold")
        self.assertIn("fellow your school alum", d)

    def test_cold_has_peer_tone_not_formal_ask(self):
        d = F.new_grad_referral_ask("Keshavan", "Priya", "New Grad SWE", "Acme",
                                    "Georgia Tech", "2026", variant="cold")
        self.assertNotIn("Dear", d)
        self.assertIn("Thanks!", d)


class ClassmatesHelperTest(unittest.TestCase):
    def test_school_info_extracts_class_year(self):
        info = R.school_info(_fake_profile())
        self.assertEqual(info["school"], "Georgia Tech")
        self.assertEqual(info["class_year"], "2026")

    def test_school_info_picks_latest_entry(self):
        prof = {"education": [
            {"school": "Old School", "degree": "B.A.", "dates": "2018 - 2022"},
            {"school": "Georgia Tech", "degree": "B.S.", "dates": "2022 - 2026"},
        ]}
        self.assertEqual(R.school_info(prof)["school"], "Georgia Tech")

    def test_school_info_empty_profile(self):
        self.assertEqual(R.school_info({}), {"school": "", "class_year": ""})

    def test_search_terms_include_company_and_school(self):
        terms = R.classmates_search_terms(_fake_profile(), "Acme")
        blob = " ".join(terms["queries"] + terms["linkedin_filters"] + terms["steps"])
        self.assertIn("Acme", blob)
        self.assertIn("Georgia Tech", blob)

    def test_search_terms_no_school_still_works(self):
        terms = R.classmates_search_terms({}, "Acme")
        self.assertTrue(any("Acme" in q for q in terms["queries"]))
        self.assertTrue(terms["steps"])

    def test_render_classmates_includes_templates_and_checklist(self):
        out = R.render_classmates(_fake_profile(), "Acme")
        self.assertIn("Acme", out)
        self.assertIn("Georgia Tech", out)
        self.assertIn("fellow Georgia Tech alum", out)
        self.assertIn("classmates at Georgia Tech", out)
        self.assertIn("DRAFTS ONLY", out)


class ChecklistTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "checklist.json"

    def tearDown(self):
        self.td.cleanup()

    def test_timeline_dates_relative_to_graduation(self):
        items = {i["id"]: i for i in CL.build_timeline(date(2026, 5, 15))}
        self.assertEqual(items["start-applying"]["due"], "2025-08-15")
        self.assertEqual(items["fall-recruiting"]["due"], "2025-10-15")
        self.assertEqual(items["spring-recruiting"]["due"], "2026-01-15")
        self.assertEqual(items["offer-decisions"]["due"], "2026-04-15")
        self.assertEqual(items["background-check"]["due"], "2026-05-15")
        self.assertEqual(items["relocation"]["due"], "2026-06-15")
        self.assertEqual(items["first-day"]["due"], "2026-07-15")

    def test_shift_months_clamps_day(self):
        self.assertEqual(CL.shift_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(CL.shift_months(date(2026, 5, 31), -9), date(2025, 8, 31))

    def test_generate_and_load_persist(self):
        state = CL.generate("2026-05-15", path=self.path)
        self.assertEqual(len(state["items"]), 7)
        loaded = CL.load(self.path)
        self.assertEqual(loaded["graduation"], "2026-05-15")
        self.assertEqual([i["id"] for i in loaded["items"]],
                         [i["id"] for i in state["items"]])

    def test_check_persists_done(self):
        CL.generate("2026-05-15", path=self.path)
        CL.set_done("start-applying", path=self.path)
        loaded = CL.load(self.path)
        item = next(i for i in loaded["items"] if i["id"] == "start-applying")
        self.assertTrue(item["done"])

    def test_uncheck_persists(self):
        CL.generate("2026-05-15", path=self.path)
        CL.set_done("start-applying", path=self.path)
        CL.set_done("start-applying", done=False, path=self.path)
        loaded = CL.load(self.path)
        item = next(i for i in loaded["items"] if i["id"] == "start-applying")
        self.assertFalse(item["done"])

    def test_check_unknown_id_raises(self):
        CL.generate("2026-05-15", path=self.path)
        with self.assertRaises(CL.ChecklistError):
            CL.set_done("nope-not-real", path=self.path)

    def test_bad_graduation_date_raises(self):
        with self.assertRaises(CL.ChecklistError):
            CL.generate("15-05-2026", path=self.path)

    def test_render_shows_progress(self):
        CL.generate("2026-05-15", path=self.path)
        CL.set_done("start-applying", path=self.path)
        out = CL.render(CL.load(self.path), today=date(2025, 1, 1))
        self.assertIn("1/7", out)
        self.assertIn("[x] start-applying", out)
        self.assertIn("[ ] fall-recruiting", out)

    def test_nudges_flag_overdue_items(self):
        CL.generate("2026-05-15", path=self.path)
        nudges = CL.checklist_nudges(CL.load(self.path), today=date(2026, 8, 1))
        kinds = {n["kind"] for n in nudges}
        self.assertEqual(kinds, {"checklist_overdue"})
        self.assertTrue(any("start-applying" in n["command"] for n in nudges))

    def test_nudges_skip_done_items(self):
        CL.generate("2026-05-15", path=self.path)
        for i in CL.load(self.path)["items"]:
            CL.set_done(i["id"], path=self.path)
        self.assertEqual(CL.checklist_nudges(CL.load(self.path), today=date(2027, 1, 1)), [])


class CLIWiringTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.C = C
        self.orig_checklist = C.CHECKLIST_PATH
        self.orig_profile = C.PROFILE_PATH
        self.td = tempfile.TemporaryDirectory()
        C.CHECKLIST_PATH = Path(self.td.name) / "checklist.json"
        prof_path = Path(self.td.name) / "profile.json"
        prof_path.write_text(json.dumps(_fake_profile()), encoding="utf-8")
        C.PROFILE_PATH = prof_path

    def tearDown(self):
        self.C.CHECKLIST_PATH = self.orig_checklist
        self.C.PROFILE_PATH = self.orig_profile
        self.td.cleanup()

    def _parse(self, argv):
        from candid import __main__ as M
        return M.build_parser().parse_args(argv)

    def test_commands_registered(self):
        from candid import __main__ as M
        self.assertIn("checklist", M.COMMANDS)
        self.assertIn("referrals", M.COMMANDS)
        self.assertEqual(M.SUBCOMMANDS["checklist"], ["newgrad", "show", "check"])
        self.assertEqual(M.SUBCOMMANDS["referrals"], ["classmates"])

    def test_parser_checklist_newgrad(self):
        a = self._parse(["checklist", "newgrad", "--graduation", "2026-05-15"])
        self.assertEqual(a.graduation, "2026-05-15")

    def test_parser_checklist_check_undo(self):
        a = self._parse(["checklist", "check", "start-applying", "--undo"])
        self.assertEqual(a.item_id, "start-applying")
        self.assertTrue(a.undo)

    def test_parser_followup_referral_new_grad(self):
        a = self._parse(["followup", "referral", "--person", "Priya",
                         "--role", "New Grad SWE", "--company", "Acme",
                         "--new-grad", "--variant", "warm"])
        self.assertTrue(a.new_grad)
        self.assertEqual(a.variant, "warm")

    def test_parser_referrals_classmates(self):
        a = self._parse(["referrals", "classmates", "--company", "Acme"])
        self.assertEqual(a.company, "Acme")

    def test_end_to_end_checklist_cli(self):
        a = self._parse(["checklist", "newgrad", "--graduation", "2026-05-15"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        self.assertIn("2025-08-15", buf.getvalue())
        a = self._parse(["checklist", "check", "start-applying"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        self.assertIn("1/7", buf.getvalue())
        a = self._parse(["checklist", "show"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        self.assertIn("[x] start-applying", buf.getvalue())

    def test_end_to_end_followup_newgrad_cli(self):
        a = self._parse(["followup", "referral", "--person", "Priya",
                         "--role", "New Grad SWE", "--company", "Acme",
                         "--new-grad"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        out = buf.getvalue()
        self.assertIn("fellow Georgia Tech alum", out)
        self.assertIn("class of 2026", out)

    def test_end_to_end_referrals_classmates_cli(self):
        a = self._parse(["referrals", "classmates", "--company", "Acme"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        out = buf.getvalue()
        self.assertIn("Acme", out)
        self.assertIn("Georgia Tech", out)
        self.assertIn("DRAFTS ONLY", out)

    def test_nudge_hook_survives_checklist(self):
        from candid import nudges as N
        a = self._parse(["checklist", "newgrad", "--graduation", "2020-05-15"])
        with redirect_stdout(io.StringIO()):
            a.func(a)
        nudges = N.pending_nudges(apps=[], today=date(2026, 9, 22))
        self.assertTrue(any(n["kind"] == "checklist_overdue" for n in nudges))


if __name__ == "__main__":
    unittest.main()
