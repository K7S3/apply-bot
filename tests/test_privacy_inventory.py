"""Tests for candid.privacy_inventory (`candid privacy inventory|show`).

Test isolation: CANDID_DATA_DIR / CANDID_CONFIG_DIR point at unique temp
dirs, set before candid is imported. setUp seeds data files, tearDown
removes them.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privinv"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privinv-config"

import candid.config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_inventory as PI  # noqa: E402

DATA_DIR = Path(os.environ["CANDID_DATA_DIR"])
CONFIG_DIR = Path(os.environ["CANDID_CONFIG_DIR"])


def _ns(**kwargs):
    base = {"json": False, "index": 0, "category": "tracker"}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _run(func, args):
    """Run a handler, capturing stdout/stderr. Returns (exit_code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = func(args)
    return code, out.getvalue(), err.getvalue()


class PrivacyInventoryTest(unittest.TestCase):
    def setUp(self):
        # Point candid.config at this test's temp dir regardless of which test
        # module imported candid first (config.DATA_DIR is bound at import).
        self._saved_data_dir = C.DATA_DIR
        self._saved_audit_log = P.AUDIT_LOG_PATH
        C.DATA_DIR = DATA_DIR
        P.AUDIT_LOG_PATH = DATA_DIR / "privacy_audit.jsonl"
        for d in (DATA_DIR, CONFIG_DIR):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        # json category: tracker with two records
        (DATA_DIR / "tracker.json").write_text(
            json.dumps(
                [
                    {"id": 1, "company": "Acme", "role": "Data Scientist"},
                    {"id": 2, "company": "Globex", "role": "ML Engineer"},
                ]
            ),
            encoding="utf-8",
        )
        # json category: profile as a single object (not a list)
        (DATA_DIR / "profile.json").write_text(
            json.dumps({"name": "Test User", "skills": ["python"]}),
            encoding="utf-8",
        )
        # dir category: tailored with two text files
        tailored = DATA_DIR / "tailored"
        tailored.mkdir(parents=True, exist_ok=True)
        (tailored / "acme_resume.md").write_text("# Resume for Acme\n", encoding="utf-8")
        (tailored / "globex_resume.md").write_text("# Resume for Globex\n", encoding="utf-8")

    def tearDown(self):
        C.DATA_DIR = self._saved_data_dir
        P.AUDIT_LOG_PATH = self._saved_audit_log
        for d in (DATA_DIR, CONFIG_DIR):
            shutil.rmtree(d, ignore_errors=True)

    # --- inventory -----------------------------------------------------

    def test_inventory_lists_all_categories(self):
        code, out, _ = _run(PI.cmd_inventory, _ns())
        self.assertEqual(code, 0)
        for name in P.CATEGORIES:
            self.assertIn(name, out, f"category {name!r} missing from inventory table")

    def test_inventory_rows_match_iter_inventory(self):
        rows = P.iter_inventory()
        self.assertEqual({r["name"] for r in rows}, set(P.CATEGORIES))
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["tracker"]["records"], 2)
        self.assertEqual(by_name["profile"]["records"], 2)  # dict: key count
        self.assertEqual(by_name["tailored"]["records"], 2)  # two files
        self.assertTrue(by_name["tracker"]["exists"])
        self.assertFalse(by_name["salary"]["exists"])  # no salary.db seeded
        self.assertGreater(by_name["tracker"]["bytes"], 0)
        self.assertIn("B", by_name["tracker"]["size"])

    def test_inventory_json(self):
        code, out, _ = _run(PI.cmd_inventory, _ns(json=True))
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertIsInstance(rows, list)
        self.assertEqual({r["name"] for r in rows}, set(P.CATEGORIES))
        row = next(r for r in rows if r["name"] == "tracker")
        self.assertEqual(row["records"], 2)
        self.assertTrue(row["exists"])

    # --- show: json categories -----------------------------------------

    def test_show_displays_a_record(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="tracker"))
        self.assertEqual(code, 0)
        self.assertIn("Acme", out)
        self.assertIn("Data Scientist", out)

    def test_show_index_selects_record(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="tracker", index=1))
        self.assertEqual(code, 0)
        self.assertIn("Globex", out)
        self.assertIn("ML Engineer", out)

    def test_show_single_object_json(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="profile"))
        self.assertEqual(code, 0)
        self.assertIn("Test User", out)

    def test_show_json_flag_emits_json(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="tracker", json=True))
        self.assertEqual(code, 0)
        record = json.loads(out)
        self.assertEqual(record["company"], "Acme")

    def test_show_bad_category_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            PI.cmd_show(_ns(category="nope"))
        self.assertEqual(ctx.exception.code, 2)

    def test_show_out_of_range_index_exits_nonzero(self):
        code, out, err = _run(PI.cmd_show, _ns(category="tracker", index=99))
        self.assertNotEqual(code, 0)
        self.assertIn("out of range", err)

    def test_show_negative_index_exits_nonzero(self):
        code, _, err = _run(PI.cmd_show, _ns(category="tracker", index=-1))
        self.assertNotEqual(code, 0)
        self.assertIn(">= 0", err)

    # --- show: dir categories ------------------------------------------

    def test_show_dir_lists_files_and_content(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="tailored"))
        self.assertEqual(code, 0)
        self.assertIn("acme_resume.md", out)
        self.assertIn("globex_resume.md", out)
        self.assertIn("# Resume for Acme", out)

    def test_show_dir_index_selects_file(self):
        code, out, _ = _run(PI.cmd_show, _ns(category="tailored", index=1))
        self.assertEqual(code, 0)
        self.assertIn("# Resume for Globex", out)

    def test_show_dir_out_of_range_exits_nonzero(self):
        code, _, err = _run(PI.cmd_show, _ns(category="tailored", index=5))
        self.assertNotEqual(code, 0)
        self.assertIn("out of range", err)

    def test_show_empty_category_exits_nonzero(self):
        # 'study' dir exists in CATEGORIES but has no files seeded
        code, _, err = _run(PI.cmd_show, _ns(category="study"))
        self.assertNotEqual(code, 0)
        self.assertIn("No stored", err)

    # --- show: db category ---------------------------------------------

    def test_show_db_metadata(self):
        db_path = DATA_DIR / "salary.db"
        con = sqlite3.connect(db_path)
        con.execute("CREATE TABLE wages (company TEXT, wage REAL)")
        con.execute("INSERT INTO wages VALUES ('Acme', 150000)")
        con.commit()
        con.close()
        code, out, _ = _run(PI.cmd_show, _ns(category="salary"))
        self.assertEqual(code, 0)
        self.assertIn("wages", out)
        self.assertIn("1 rows", out)


if __name__ == "__main__":
    unittest.main()
