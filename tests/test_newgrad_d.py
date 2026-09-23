"""Tests for worker D (batch 88, new-grad track): new-grad salary benchmarks
and internship bulk mode.

Run: CANDID_DATA_DIR=/tmp/candid-test-newgrad-d python3 -m unittest tests.test_newgrad_d -v
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-newgrad-d")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _tmp_json():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    return Path(f.name)


def _seed_lca(db, floors, title="Software Engineer", location="New York, NY",
              company="Fictional Corp"):
    """Mock LCA rows: floors list of annual wage-range floors."""
    from candid import salary as S
    for i, floor in enumerate(floors):
        S.add_range(company, title, floor, floor + 20000, location=location,
                    source="dol_lca", source_detail=f"LCA I-200-0000{i:03d}",
                    path=db)


def _seed_posts(db, pairs, title="Software Engineer", location="New York, NY",
                company="Fictional Corp"):
    from candid import salary as S
    for low, high in pairs:
        S.add_range(company, title, low, high, location=location,
                    source="job_post", source_detail="https://example.com/jd",
                    path=db)


class NewgradLcaTest(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()

    def tearDown(self):
        self.db.unlink(missing_ok=True)

    def test_newgrad_labels_lca_source(self):
        from candid import salary as S
        _seed_lca(self.db, [80000, 85000, 90000, 95000, 100000])
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertIn("dol_lca", r["sources"])
        self.assertTrue(r["lca_data_imported"])
        self.assertIn("PROXY", r["sources"]["dol_lca"]["label"])
        # entry band derives from inserted floors: p10 and p50
        floors = sorted([80000, 85000, 90000, 95000, 100000])
        self.assertEqual(r["sources"]["dol_lca"]["low"], S._percentile(floors, 10))
        self.assertEqual(r["sources"]["dol_lca"]["high"], S._percentile(floors, 50))

    def test_newgrad_combines_job_post_source(self):
        from candid import salary as S
        _seed_lca(self.db, [80000, 90000, 100000])
        _seed_posts(self.db, [(110000, 150000), (115000, 155000), (120000, 160000)])
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertIn("dol_lca", r["sources"])
        self.assertIn("job_post", r["sources"])
        self.assertEqual(r["combined"]["low"], r["sources"]["dol_lca"]["low"])
        self.assertEqual(r["combined"]["high"], r["sources"]["job_post"]["high"])

    def test_newgrad_location_filtering(self):
        from candid import salary as S
        _seed_lca(self.db, [200000], location="San Francisco, CA")
        _seed_lca(self.db, [80000, 85000, 90000, 95000, 100000],
                  location="New York, NY")
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertEqual(r["sources"]["dol_lca"]["n"], 5)

    def test_newgrad_company_filtering(self):
        from candid import salary as S
        _seed_lca(self.db, [80000, 90000, 100000], company="Fictional Corp")
        _seed_lca(self.db, [250000], company="OtherCo")
        r = S.newgrad("Software Engineer", company="Fictional", path=self.db)
        self.assertEqual(r["sources"]["dol_lca"]["n"], 3)

    def test_newgrad_graceful_no_data_imported(self):
        from candid import salary as S
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertFalse(r["lca_data_imported"])
        self.assertEqual(r["sources"], {})
        self.assertIsNone(r["combined"])
        text = S.render_newgrad(r)
        self.assertIn("import-lca", text)
        self.assertIn("No salary data imported yet", text)

    def test_newgrad_graceful_no_matching_rows(self):
        from candid import salary as S
        _seed_lca(self.db, [80000], title="Accountant", location="Chicago, IL")
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertTrue(r["lca_data_imported"])
        self.assertEqual(r["sources"], {})
        text = S.render_newgrad(r)
        self.assertIn("No LCA or posted-range rows match", text)

    def test_newgrad_bls_explicitly_unavailable(self):
        from candid import salary as S
        _seed_lca(self.db, [80000, 90000, 100000])
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        self.assertIsNone(r["bls"])
        self.assertIn("no BLS OES import", r["bls_note"])
        self.assertIn("no BLS OES import", S.render_newgrad(r))

    def test_newgrad_disclaimer_rendered(self):
        from candid import salary as S
        _seed_lca(self.db, [80000, 90000, 100000])
        r = S.newgrad("Software Engineer", "New York", path=self.db)
        text = S.render_newgrad(r)
        self.assertIn("vary widely by company tier", text)
        self.assertIn("Estimated entry-level range", text)
        self.assertIn("[dol_lca]", text)

    def test_newgrad_requires_title(self):
        from candid import salary as S
        with self.assertRaises(S.SalaryError):
            S.newgrad("", path=self.db)


class InternshipCrudTest(unittest.TestCase):
    def setUp(self):
        self.p = _tmp_json()

    def tearDown(self):
        self.p.unlink(missing_ok=True)

    def test_add_defaults_stage_applied(self):
        from candid import internships as I
        rec = I.add("Acme", "SWE Intern", path=self.p)
        self.assertEqual(rec["id"], 1)
        self.assertEqual(rec["stage"], "applied")
        self.assertEqual(rec["deadline"], "")
        self.assertTrue(date.fromisoformat(rec["date_added"]))

    def test_add_full_fields(self):
        from candid import internships as I
        rec = I.add("Acme", "SWE Intern", location="NYC",
                    deadline="2026-10-15", url="https://example.com/apply",
                    notes="referral", path=self.p)
        self.assertEqual(rec["location"], "NYC")
        self.assertEqual(rec["deadline"], "2026-10-15")
        self.assertEqual(rec["url"], "https://example.com/apply")

    def test_add_rejects_bad_stage(self):
        from candid import internships as I
        with self.assertRaises(I.InternshipsError):
            I.add("Acme", "SWE Intern", stage="interviewing", path=self.p)

    def test_add_rejects_bad_deadline(self):
        from candid import internships as I
        with self.assertRaises(I.InternshipsError):
            I.add("Acme", "SWE Intern", deadline="10/15/2026", path=self.p)

    def test_add_rejects_missing_company_role(self):
        from candid import internships as I
        with self.assertRaises(I.InternshipsError):
            I.add("", "SWE Intern", path=self.p)

    def test_add_duplicate_returns_existing(self):
        from candid import internships as I
        I.add("Acme", "SWE Intern", path=self.p)
        dup = I.add("Acme", "SWE Intern", path=self.p)
        self.assertTrue(dup.get("duplicate"))
        self.assertEqual(len(I.list_internships(path=self.p)), 1)

    def test_list_filters_stage_and_company(self):
        from candid import internships as I
        I.add("Acme", "SWE Intern", path=self.p)
        I.add("BetaCo", "ML Intern", path=self.p)
        I.update(1, stage="oa", path=self.p)
        self.assertEqual([a["id"] for a in I.list_internships(stage="oa", path=self.p)], [1])
        self.assertEqual([a["company"] for a in I.list_internships(company="beta", path=self.p)],
                         ["BetaCo"])

    def test_update_stage_walk(self):
        from candid import internships as I
        from candid import config as C
        I.add("Acme", "SWE Intern", path=self.p)
        for stage in ["oa", "phone", "onsite", "offer", "accepted"]:
            rec = I.update(1, stage=stage, path=self.p)
            self.assertEqual(rec["stage"], stage)
        self.assertIn("oa", C.INTERN_STATUSES)

    def test_update_rejects_unknown_id(self):
        from candid import internships as I
        with self.assertRaises(I.InternshipsError):
            I.update(99, stage="oa", path=self.p)

    def test_update_rejects_bad_stage(self):
        from candid import internships as I
        I.add("Acme", "SWE Intern", path=self.p)
        with self.assertRaises(I.InternshipsError):
            I.update(1, stage="final-round", path=self.p)

    def test_remove(self):
        from candid import internships as I
        I.add("Acme", "SWE Intern", path=self.p)
        I.remove(1, path=self.p)
        self.assertEqual(I.list_internships(path=self.p), [])
        with self.assertRaises(I.InternshipsError):
            I.remove(1, path=self.p)


class InternshipCsvTest(unittest.TestCase):
    def setUp(self):
        self.p = _tmp_json()
        self.csv = Path(tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name)

    def tearDown(self):
        self.p.unlink(missing_ok=True)
        self.csv.unlink(missing_ok=True)

    def test_import_csv_bulk_adds(self):
        from candid import internships as I
        dl = (date.today() + timedelta(days=10)).isoformat()
        self.csv.write_text(
            "company,role,location,deadline,url\n"
            f"Acme,SWE Intern,NYC,{dl},https://example.com/a\n"
            "BetaCo,ML Intern,,,\n")
        res = I.import_csv(self.csv, path=self.p)
        self.assertEqual(res["added"], 2)
        self.assertEqual(res["skipped_duplicates"], 0)
        self.assertEqual(res["skipped_bad"], 0)
        items = I.list_internships(path=self.p)
        self.assertEqual(items[0]["deadline"], dl)
        self.assertEqual(items[1]["deadline"], "")

    def test_import_csv_skips_duplicates(self):
        from candid import internships as I
        self.csv.write_text("company,role\nAcme,SWE Intern\nAcme,SWE Intern\n")
        res = I.import_csv(self.csv, path=self.p)
        self.assertEqual(res["added"], 1)
        self.assertEqual(res["skipped_duplicates"], 1)

    def test_import_csv_skips_bad_rows(self):
        from candid import internships as I
        self.csv.write_text(
            "company,role,deadline\n"
            "Acme,SWE Intern,not-a-date\n"
            ",Missing Role,\n"
            "BetaCo,ML Intern,2026-12-01\n")
        res = I.import_csv(self.csv, path=self.p)
        self.assertEqual(res["added"], 1)
        self.assertEqual(res["skipped_bad"], 2)
        self.assertEqual(len(res["errors"]), 2)

    def test_import_csv_requires_company_and_role_columns(self):
        from candid import internships as I
        self.csv.write_text("employer,position\nAcme,SWE Intern\n")
        with self.assertRaises(I.InternshipsError):
            I.import_csv(self.csv, path=self.p)

    def test_import_csv_missing_file(self):
        from candid import internships as I
        with self.assertRaises(I.InternshipsError):
            I.import_csv("/tmp/does-not-exist-88.csv", path=self.p)


class InternshipDeadlinesTest(unittest.TestCase):
    def setUp(self):
        self.p = _tmp_json()

    def tearDown(self):
        self.p.unlink(missing_ok=True)

    def _add(self, company, days_out, stage="applied"):
        from candid import internships as I
        dl = (date.today() + timedelta(days=days_out)).isoformat()
        return I.add(company, "SWE Intern", deadline=dl, stage=stage, path=self.p)

    def test_deadlines_sorted_soonest_first(self):
        from candid import internships as I
        self._add("Slow", 20)
        self._add("Fast", 3)
        self._add("Mid", 10)
        items = I.deadlines(days=30, path=self.p)
        self.assertEqual([a["company"] for a in items], ["Fast", "Mid", "Slow"])
        self.assertEqual([a["days_left"] for a in items], [3, 10, 20])

    def test_deadlines_excludes_past_and_terminal_stages(self):
        from candid import internships as I
        self._add("Past", -5)
        self._add("AcceptedOne", 5, stage="accepted")
        self._add("RejectedOne", 5, stage="rejected")
        I.add("NoDate", "SWE Intern", path=self.p)
        items = I.deadlines(days=30, path=self.p)
        self.assertEqual(items, [])

    def test_deadlines_window_respected(self):
        from candid import internships as I
        self._add("Near", 10)
        self._add("Far", 40)
        self.assertEqual(len(I.deadlines(days=30, path=self.p)), 1)
        self.assertEqual(len(I.deadlines(days=60, path=self.p)), 2)

    def test_deadlines_render_mentions_soonest_first(self):
        from candid import internships as I
        self._add("SoonCo", 2)
        text = I.render_deadlines(I.deadlines(days=30, path=self.p))
        self.assertIn("soonest first", text)
        self.assertIn("SoonCo", text)
        self.assertEqual(I.render_deadlines([]), "No upcoming internship deadlines in this window.")

    def test_stats_counts_pipeline(self):
        from candid import internships as I
        self._add("A", 10)
        self._add("B", 10, stage="oa")
        s = I.stats(path=self.p)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["counts"]["applied"], 1)
        self.assertEqual(s["counts"]["oa"], 1)


if __name__ == "__main__":
    unittest.main()
