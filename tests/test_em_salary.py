"""Tests for candid.em_salary (EM salary bands).

Covers: management-title filtering (engineering manager / EM / director in,
IC titles out), p25/median/p75 band computation, title/location narrowing,
and honest sparse/empty-data reporting (no invented bands).

Run: CANDID_DATA_DIR=/tmp/candid-test-em-salary python3 -m pytest tests/test_em_salary.py -q
"""
import json
import os
import tempfile

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-em-salary"

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import em_salary as ES  # noqa: E402
from candid import salary as S  # noqa: E402
from candid import __main__ as CLI  # noqa: E402


def _seed(db):
    rows = [
        # (company, title, low, high, location)
        ("Acme", "Engineering Manager", 180000, 230000, "New York, NY"),
        ("Beta", "Engineering Manager", 190000, 240000, "New York, NY"),
        ("Gamma", "Senior Engineering Manager", 220000, 270000, "San Francisco, CA"),
        ("Acme", "EM", 175000, 210000, "New York, NY"),
        ("Delta", "Director of Engineering", 240000, 300000, "New York, NY"),
        ("Epsilon", "Director", 200000, 250000, "Austin, TX"),
        ("Zeta", "Senior Software Engineer", 150000, 180000, "New York, NY"),
        ("Eta", "Product Manager", 140000, 170000, "New York, NY"),
    ]
    for company, title, low, high, loc in rows:
        S.add_range(company, title, low, high, location=loc,
                    source="job_post", path=db)


class TitleClassificationTest(unittest.TestCase):
    def test_engineering_manager_variants(self):
        for t in ("Engineering Manager", "Senior Engineering Manager",
                  "Software Engineering Manager", "Engineering Mgr",
                  "Sr. Engineering Manager"):
            cls = ES.classify_mgmt_title(t)
            self.assertIsNotNone(cls, t)
            self.assertEqual(cls["label"], "Engineering Manager")

    def test_em_token(self):
        for t in ("EM", "EM, Platform", "Engineering Manager (EM)"):
            # "(EM)" hits the Engineering Manager rule first - still management
            self.assertIsNotNone(ES.classify_mgmt_title(t), t)
        self.assertEqual(ES.classify_mgmt_title("EM")["label"], "EM")

    def test_em_token_does_not_match_inside_words(self):
        self.assertIsNone(ES.classify_mgmt_title("Systems Engineer"))
        self.assertIsNone(ES.classify_mgmt_title("EMEA Sales Lead"))

    def test_director_variants(self):
        for t in ("Director of Engineering", "Engineering Director",
                  "Senior Director, Engineering"):
            cls = ES.classify_mgmt_title(t)
            self.assertIsNotNone(cls, t)
            self.assertEqual(cls["label"], "Director")

    def test_bare_director_included_but_flagged(self):
        cls = ES.classify_mgmt_title("Director")
        self.assertIsNotNone(cls)
        self.assertEqual(cls["label"], "Director")
        self.assertTrue(cls["bare_director"])
        self.assertFalse(ES.classify_mgmt_title(
            "Director of Engineering")["bare_director"])

    def test_ic_titles_excluded(self):
        for t in ("Senior Software Engineer", "Staff Engineer",
                  "Product Manager", "Data Scientist", "Engineering",
                  "Manager, Support"):
            self.assertIsNone(ES.classify_mgmt_title(t), t)


class BandComputationTest(unittest.TestCase):
    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp(prefix="candid-emsal-")) / "s.db")
        _seed(self.db)

    def test_ic_rows_excluded_from_bands(self):
        result = ES.mgmt_bands(path=self.db)
        self.assertEqual(result["overall"]["n"], 6)  # 8 rows minus 2 IC
        labels = [b["label"] for b in result["bands"]]
        self.assertEqual(labels, ["Engineering Manager", "EM", "Director"])

    def test_band_math_matches_salary_percentiles(self):
        result = ES.mgmt_bands(path=self.db)
        em = next(b for b in result["bands"]
                  if b["label"] == "Engineering Manager")
        mids = sorted([205000.0, 215000.0, 245000.0])
        self.assertEqual(em["n"], 3)
        self.assertEqual(em["median"], S._percentile(mids, 50))
        self.assertEqual(em["p25"], S._percentile(mids, 25))
        self.assertEqual(em["p75"], S._percentile(mids, 75))
        self.assertEqual(em["n_companies"], 3)

    def test_title_filter(self):
        result = ES.mgmt_bands(title="director", path=self.db)
        labels = [b["label"] for b in result["bands"]]
        self.assertEqual(labels, ["Director"])
        self.assertEqual(result["overall"]["n"], 2)

    def test_location_filter(self):
        result = ES.mgmt_bands(location="san francisco", path=self.db)
        self.assertEqual(result["overall"]["n"], 1)
        self.assertEqual(result["bands"][0]["label"], "Engineering Manager")

    def test_sparse_note_below_threshold(self):
        result = ES.mgmt_bands(path=self.db)
        sparse = [n for n in result["notes"] if n.startswith("Sparse:")]
        # EM (n=1) and Director (n=2) are sparse; EM-mgr (n=3) is sparse too
        self.assertEqual(len(sparse), 3)
        self.assertTrue(all("indicative, not authoritative" in n
                            for n in sparse))

    def test_no_sparse_note_with_enough_data(self):
        db2 = str(Path(tempfile.mkdtemp(prefix="candid-emsal2-")) / "s.db")
        for i in range(6):
            S.add_range(f"Co{i}", "Engineering Manager",
                        180000 + i * 5000, 220000 + i * 5000, path=db2)
        result = ES.mgmt_bands(path=db2)
        band = next(b for b in result["bands"]
                    if b["label"] == "Engineering Manager")
        self.assertEqual(band["n"], 6)
        self.assertFalse(any(n.startswith("Sparse:") and "'Engineering Manager'" in n
                             for n in result["notes"]))

    def test_bare_director_caution_note(self):
        result = ES.mgmt_bands(path=self.db)
        self.assertTrue(any("just 'Director'" in n for n in result["notes"]))

    def test_empty_db_is_honest(self):
        db3 = str(Path(tempfile.mkdtemp(prefix="candid-emsal3-")) / "s.db")
        S.connect(db3).close()  # create schema, no rows
        result = ES.mgmt_bands(path=db3)
        self.assertEqual(result["bands"], [])
        self.assertEqual(result["overall"]["n"], 0)
        self.assertTrue(any("No management-title rows" in n
                            for n in result["notes"]))

    def test_result_is_json_serializable(self):
        json.dumps(ES.mgmt_bands(path=self.db))


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp(prefix="candid-emsalr-")) / "s.db")
        _seed(self.db)

    def test_render_bands(self):
        text = ES.render_bands(ES.mgmt_bands(path=self.db))
        self.assertIn("EM SALARY BANDS", text)
        self.assertIn("Engineering Manager", text)
        self.assertIn("median $", text)
        self.assertIn("Notes:", text)

    def test_render_empty(self):
        db3 = str(Path(tempfile.mkdtemp(prefix="candid-emsalre-")) / "s.db")
        S.connect(db3).close()
        text = ES.render_bands(ES.mgmt_bands(path=db3))
        self.assertIn("No management-title rows", text)
        self.assertNotIn("median $", text)


class EmSalaryCLITest(unittest.TestCase):
    def test_parser_accepts_em_salary(self):
        args = CLI.build_parser().parse_args(["em", "salary"])
        self.assertEqual(args.what, "salary")
        self.assertEqual(args.title, "")
        args = CLI.build_parser().parse_args(
            ["em", "salary", "--title", "Engineering Manager",
             "--location", "New York", "--json"])
        self.assertEqual(args.title, "Engineering Manager")
        self.assertEqual(args.location, "New York")
        self.assertTrue(args.json)

    def test_cmd_em_salary_end_to_end(self):
        import io
        from contextlib import redirect_stdout
        db = str(Path(tempfile.mkdtemp(prefix="candid-emsalc-")) / "s.db")
        _seed(db)
        with mock.patch("candid.config.SALARY_DB", db):
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI.cmd_em(Namespace(what="salary", title="", location="",
                                     json=False))
            out = buf.getvalue()
        self.assertIn("EM SALARY BANDS", out)
        self.assertIn("Engineering Manager", out)

    def test_cmd_em_salary_json(self):
        import io
        from contextlib import redirect_stdout
        db = str(Path(tempfile.mkdtemp(prefix="candid-emsalcj-")) / "s.db")
        _seed(db)
        with mock.patch("candid.config.SALARY_DB", db):
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI.cmd_em(Namespace(what="salary", title="", location="",
                                     json=True))
            result = json.loads(buf.getvalue())
        self.assertEqual(result["overall"]["n"], 6)


if __name__ == "__main__":
    unittest.main()
