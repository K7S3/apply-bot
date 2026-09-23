"""Tests for candid.startup_lists: CSV import validation, add/remove/list,
stage and remote filters, duplicate handling, preferred stages.

DATA_DIR is isolated per test via the CANDID_DATA_DIR override pattern
(the config module is patched in setUp and restored in tearDown), so the
real user data is never touched.
Run: python3 -m pytest tests/test_batch21_lists.py -q
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOOD_CSV = """name,stage,funding_total_usd,employees,url,remote_policy,notes
Nova Robotics,seed,$2.5M,45,https://example.com/nova,remote-first,AI warehouse robots
Beacon Health,series-a,"1,250,000",30,https://example.com/beacon,hybrid,HIPAA focus
"""

BAD_ROWS_CSV = """name,stage,funding_total_usd,employees,url,remote_policy,notes
,seed,100000,10,,,missing name
Ghost Stage,hypergrowth,100000,10,,,bad stage
Bad Money,seed,not-a-number,10,,,bad funding
Bad Headcount,seed,100000,abc,,,bad employees
Fine Co,Series-A,500k,,https://example.com/fine,remote,ok
"""


class StartupListsTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        C.DATA_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        self.td.cleanup()

    def _csv(self, text, name="startups.csv"):
        p = Path(self.td.name) / name
        p.write_text(text, encoding="utf-8")
        return p

    # -- import ------------------------------------------------------------------
    def test_import_valid_csv(self):
        from candid import startup_lists as SL
        summary = SL.import_csv(self._csv(GOOD_CSV))
        self.assertEqual(summary["imported"], 2)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], [])
        recs = {r["name"]: r for r in SL.list_startups()}
        self.assertEqual(recs["Nova Robotics"]["funding_total_usd"], 2_500_000)
        self.assertEqual(recs["Beacon Health"]["employees"], 30)
        self.assertEqual(recs["Beacon Health"]["stage"], "series-a")

    def test_import_validation_reports_skipped_rows(self):
        from candid import startup_lists as SL
        summary = SL.import_csv(self._csv(BAD_ROWS_CSV))
        self.assertEqual(summary["imported"], 1)
        self.assertEqual(len(summary["skipped"]), 4)
        reasons = " | ".join(s["reason"] for s in summary["skipped"])
        self.assertIn("missing a company name", reasons)
        self.assertIn("Unknown stage", reasons)
        self.assertIn("funding amount", reasons)
        self.assertIn("employee count", reasons)
        # The good row still made it in; stage alias "Series-A" normalized.
        recs = {r["name"]: r for r in SL.list_startups()}
        self.assertIn("Fine Co", recs)
        self.assertEqual(recs["Fine Co"]["stage"], "series-a")
        self.assertEqual(recs["Fine Co"]["funding_total_usd"], 500_000)

    def test_import_missing_file_raises(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.import_csv(Path(self.td.name) / "nope.csv")

    def test_import_missing_name_column_raises(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.import_csv(self._csv("company,stage\nAcme,seed\n"))

    def test_import_duplicate_name_updates_instead(self):
        from candid import startup_lists as SL
        SL.import_csv(self._csv(GOOD_CSV))
        second = "name,stage,funding_total_usd,employees,url,remote_policy,notes\n" \
                 "Nova Robotics,seed,$3M,,,,raise follow-on\n"
        summary = SL.import_csv(self._csv(second, "more.csv"))
        self.assertEqual(summary["imported"], 0)
        self.assertEqual(summary["updated"], 1)
        recs = {r["name"]: r for r in SL.list_startups()}
        self.assertEqual(recs["Nova Robotics"]["funding_total_usd"], 3_000_000)
        self.assertEqual(recs["Nova Robotics"]["notes"], "raise follow-on")
        # Headcount from the first import is kept when the new row is blank.
        self.assertEqual(recs["Nova Robotics"]["employees"], 45)

    # -- add / remove / duplicates ---------------------------------------------------
    def test_add_returns_record_and_persists(self):
        from candid import startup_lists as SL
        rec = SL.add(name="Acme Labs", stage="seed", funding_usd="1.2M",
                     employees="25", url="https://example.com/acme",
                     remote_policy="remote", notes="watch")
        self.assertFalse(rec.get("duplicate"))
        self.assertEqual(rec["funding_total_usd"], 1_200_000)
        names = [r["name"] for r in SL.list_startups()]
        self.assertEqual(names, ["Acme Labs"])

    def test_add_duplicate_name_returns_existing_with_flag(self):
        from candid import startup_lists as SL
        SL.add(name="Acme Labs", stage="seed")
        dup = SL.add(name="acme labs", stage="series-a", notes="should not save")
        self.assertTrue(dup.get("duplicate"))
        recs = SL.list_startups()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["stage"], "seed")  # untouched

    def test_add_bad_stage_raises(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.add(name="Acme Labs", stage="mega-round")

    def test_add_blank_name_raises(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.add(name="   ")

    def test_remove(self):
        from candid import startup_lists as SL
        SL.add(name="Acme Labs", stage="seed")
        removed = SL.remove("ACME LABS")
        self.assertEqual(removed["name"], "Acme Labs")
        self.assertEqual(SL.list_startups(), [])

    def test_remove_unknown_raises(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.remove("Nobody Corp")

    # -- filters -----------------------------------------------------------------------
    def test_list_filters_stage_and_remote(self):
        from candid import startup_lists as SL
        SL.import_csv(self._csv(GOOD_CSV))
        seed = SL.list_startups(stage="seed")
        self.assertEqual([r["name"] for r in seed], ["Nova Robotics"])
        remote = SL.list_startups(remote_only=True)
        self.assertEqual([r["name"] for r in remote], ["Nova Robotics"])
        with self.assertRaises(SL.StartupListError):
            SL.list_startups(stage="bogus")

    def test_list_results_sorted_by_name(self):
        from candid import startup_lists as SL
        SL.add(name="Zulu Co", stage="seed")
        SL.add(name="Alpha Co", stage="seed")
        self.assertEqual([r["name"] for r in SL.list_startups()],
                         ["Alpha Co", "Zulu Co"])

    # -- preferred stages ----------------------------------------------------------------
    def test_preferred_stages_roundtrip_and_filter(self):
        from candid import startup_lists as SL
        SL.import_csv(self._csv(GOOD_CSV))
        stored = SL.set_preferred_stages("seed, series-a")
        self.assertEqual(stored, ["seed", "series-a"])
        self.assertEqual(SL.preferred_stages(), ["seed", "series-a"])
        fav = SL.list_startups(use_preferred=True)
        self.assertEqual(len(fav), 2)
        # Explicit --stage beats the preferred-stage filter.
        only = SL.list_startups(stage="seed", use_preferred=True)
        self.assertEqual([r["name"] for r in only], ["Nova Robotics"])

    def test_preferred_stages_reject_bad_stage(self):
        from candid import startup_lists as SL
        with self.assertRaises(SL.StartupListError):
            SL.set_preferred_stages(["seed", "moonshot"])

    def test_preferred_stages_dedup_and_alias(self):
        from candid import startup_lists as SL
        stored = SL.set_preferred_stages("Series-A, series-a, seed")
        self.assertEqual(stored, ["series-a", "seed"])

    # -- corrupt file ----------------------------------------------------------------------
    def test_corrupt_json_raises_expected_error(self):
        from candid import startup_lists as SL
        from candid import config as C
        (C.DATA_DIR / "startups.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(SL.StartupListError):
            SL.list_startups()


if __name__ == "__main__":
    unittest.main()
