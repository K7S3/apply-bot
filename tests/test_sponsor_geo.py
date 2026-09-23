"""Tests for the sponsor-geo workstream: H-1B sponsorship signal + location arbitrage.

Network adapters are mocked; no real HTTP is made in these tests.
Run: python3 -m unittest discover -s tests -v
"""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import geo as GEO  # noqa: E402
from candid import jobs as J  # noqa: E402
from candid import salary as S  # noqa: E402
from candid import sponsor as SP  # noqa: E402

LCA_HEADERS = ["CASE_NUMBER", "CASE_STATUS", "EMPLOYER_NAME", "JOB_TITLE",
               "WORKSITE_CITY", "WORKSITE_STATE",
               "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO",
               "WAGE_UNIT_OF_PAY"]

PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": []}


def _lca_row(case_no, status, company, year=2026):
    return [case_no, status, company, "Data Scientist", "New York", "NY",
            "150000", "180000", "Year"]


def _write_lca(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LCA_HEADERS)
        w.writerows(rows)


class _IsolatedDB(unittest.TestCase):
    """Redirect all candid data paths at a temp dir per test."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name)
        self.orig = (C.DATA_DIR, C.TRACKER_PATH, C.SALARY_DB)
        C.DATA_DIR = base
        C.TRACKER_PATH = base / "tracker.json"
        C.SALARY_DB = base / "salary.db"
        self.csv_path = base / "lca.csv"

    def tearDown(self):
        C.DATA_DIR, C.TRACKER_PATH, C.SALARY_DB = self.orig
        self.td.cleanup()


# ---------------------------------------------------------------------------
# sponsorship scoring
# ---------------------------------------------------------------------------

class SponsorScoreTest(_IsolatedDB):
    def test_score_math(self):
        # 18 certified + 2 denied, all FY2026: hand-computed expectation
        rows = ([_lca_row(f"A-{i}", "CERTIFIED", "Acme Inc") for i in range(18)]
                + [_lca_row(f"D-{i}", "DENIED", "Acme Inc") for i in range(2)])
        _write_lca(self.csv_path, rows)
        res = S.import_lca(self.csv_path, fiscal_year=2026)
        self.assertEqual(res["imported"], 18)  # only certified hit the ranges table
        got = SP.score_company("Acme")
        self.assertFalse(got["insufficient"])
        self.assertEqual(got["n"], 20)  # denied rows still count for sponsorship
        self.assertEqual(got["certified"], 18)
        self.assertEqual(got["denied"], 2)
        self.assertEqual(got["approval_rate"], 0.9)
        self.assertEqual(got["recency_score"], 0.9)
        self.assertEqual(got["years"], [2026])
        # 0.45*0.9 + 0.30*0.9 + 0.25*(log10(21)/log10(101)) -> 84
        import math
        vol = math.log10(21) / math.log10(101)
        self.assertAlmostEqual(got["volume_score"], vol, places=3)
        self.assertEqual(got["score"], 84)
        out = SP.render_score(got, "Acme")
        self.assertIn("84/100", out)
        self.assertIn("20 total", out)

    def test_withdrawn_counted_separately(self):
        rows = [_lca_row("A-1", "CERTIFIED", "Acme Inc"),
                _lca_row("A-2", "DENIED", "Acme Inc"),
                _lca_row("A-3", "CERTIFIED-WITHDRAWN", "Acme Inc")]
        _write_lca(self.csv_path, rows)
        S.import_lca(self.csv_path)
        got = SP.score_company("Acme")
        self.assertEqual(got["n"], 3)
        self.assertEqual(got["certified"], 1)
        self.assertEqual(got["denied"], 1)
        self.assertEqual(got["withdrawn"], 1)
        self.assertTrue(got["small_sample"])
        self.assertIn("Small sample", SP.render_score(got, "Acme"))

    def test_reimport_dedupes(self):
        rows = [_lca_row("A-1", "CERTIFIED", "Acme Inc", year=2024)]
        _write_lca(self.csv_path, rows)
        S.import_lca(self.csv_path, fiscal_year=2024)
        S.import_lca(self.csv_path, fiscal_year=2024)  # same file again
        got = SP.score_company("Acme")
        self.assertEqual(got["n"], 1)

    def test_recency_weighting(self):
        # A: certified recently, denied long ago. B: the reverse.
        # Same approval rate; recency must separate them.
        rows_a = ([_lca_row(f"A-C{i}", "CERTIFIED", "Recent Corp") for i in range(10)]
                  + [_lca_row(f"A-D{i}", "DENIED", "Recent Corp") for i in range(10)])
        rows_b = ([_lca_row(f"B-C{i}", "CERTIFIED", "Stale Corp") for i in range(10)]
                  + [_lca_row(f"B-D{i}", "DENIED", "Stale Corp") for i in range(10)])
        _write_lca(self.csv_path, rows_a[:10])
        S.import_lca(self.csv_path, fiscal_year=2026)
        _write_lca(self.csv_path, rows_a[10:])
        S.import_lca(self.csv_path, fiscal_year=2020)
        _write_lca(self.csv_path, rows_b[:10])
        S.import_lca(self.csv_path, fiscal_year=2020)
        _write_lca(self.csv_path, rows_b[10:])
        S.import_lca(self.csv_path, fiscal_year=2026)
        a = SP.score_company("Recent Corp")
        b = SP.score_company("Stale Corp")
        self.assertEqual(a["approval_rate"], b["approval_rate"])
        self.assertAlmostEqual(a["recency_score"], 10 / 12, places=2)
        self.assertAlmostEqual(b["recency_score"], 2 / 12, places=2)
        self.assertGreater(a["score"], b["score"])

    def test_fuzzy_company_match(self):
        _write_lca(self.csv_path, [_lca_row("A-1", "CERTIFIED", "GOOGLE LLC")])
        S.import_lca(self.csv_path)
        self.assertEqual(SP.score_company("Google")["n"], 1)
        self.assertEqual(SP.score_company("google llc")["n"], 1)
        self.assertEqual(SP.score_company("Google")["matched_name"], "GOOGLE LLC")

    def test_insufficient_data_never_fabricates(self):
        self.assertFalse(SP.lca_loaded())
        got = SP.score_company("No Such Company")
        self.assertTrue(got["insufficient"])
        self.assertIsNone(got["score"])
        out = SP.render_score(got, "No Such Company")
        self.assertIn("Insufficient", out)
        self.assertIn("salary import-lca", out)
        # empty query is also insufficient, never an error
        self.assertTrue(SP.score_company("")["insufficient"])

    def test_fiscal_year_detection(self):
        self.assertEqual(SP.fiscal_year_from_name("H-1B_Disclosure_Data_FY2024.csv"), 2024)
        self.assertEqual(SP.fiscal_year_from_name("dol_h1b.csv"), 0)

    def test_sponsor_line(self):
        self.assertIsNone(SP.sponsor_line("Acme"))  # no data loaded: quiet
        _write_lca(self.csv_path,
                   [_lca_row(f"A-{i}", "CERTIFIED", "Acme Inc") for i in range(20)])
        S.import_lca(self.csv_path)
        line = SP.sponsor_line("Acme")
        self.assertIsNotNone(line)
        self.assertIn("/100", line)
        self.assertIn("n=20", line)
        self.assertIn("DOL LCA", line)
        # company with no filings: explicit note, not a score
        line2 = SP.sponsor_line("Nobody")
        self.assertIn("no LCA filings", line2)


# ---------------------------------------------------------------------------
# curate --min-sponsor
# ---------------------------------------------------------------------------

FAKE_JOBS = [
    {"source": "fake", "source_id": "fake:1", "title": "Senior Data Scientist",
     "company": "SponsorCorp", "location": "Remote", "remote": True,
     "url": "https://example.com/1", "posted_at": "2026-09-20",
     "description": "Python and machine learning for our ML platform. SQL required.",
     "salary_text": "$150k-$180k"},
    {"source": "fake", "source_id": "fake:2", "title": "Senior Data Scientist",
     "company": "NoData Inc", "location": "Remote", "remote": True,
     "url": "https://example.com/2", "posted_at": "2026-09-20",
     "description": "Python and machine learning for our ML platform. SQL required.",
     "salary_text": "$150k-$180k"},
]


def _fake_fetch(payload):
    def _f():
        return payload
    return _f


class CurateSponsorFilterTest(_IsolatedDB):
    def _adapters(self, payload=FAKE_JOBS):
        return patch.dict(J.ADAPTERS, {"fake": _fake_fetch(payload)}, clear=True)

    def test_min_sponsor_keeps_only_sponsors(self):
        rows = [_lca_row(f"S-{i}", "CERTIFIED", "SponsorCorp LLC") for i in range(30)]
        _write_lca(self.csv_path, rows)
        S.import_lca(self.csv_path)
        self.assertGreaterEqual(SP.score_company("SponsorCorp")["score"], 50)
        with self._adapters():
            res = J.curate(PROFILE, "data scientist", sources=["fake"],
                           min_sponsor=50)
        added = [j["company"] for j in res["added"]]
        self.assertEqual(added, ["SponsorCorp"])
        self.assertEqual(res["skipped_no_sponsor"], 1)
        out = J.render_curated(res)
        self.assertIn("sponsorship gate", out)

    def test_min_sponsor_without_lca_data_errors(self):
        with self._adapters():
            with self.assertRaises(J.JobsError) as ctx:
                J.curate(PROFILE, "data scientist", sources=["fake"],
                         min_sponsor=50)
        self.assertIn("salary import-lca", str(ctx.exception))

    def test_no_sponsor_gate_by_default(self):
        with self._adapters():
            res = J.curate(PROFILE, "data scientist", sources=["fake"])
        self.assertEqual(len(res["added"]), 2)
        self.assertEqual(res["skipped_no_sponsor"], 0)


# ---------------------------------------------------------------------------
# location arbitrage
# ---------------------------------------------------------------------------

class GeoTest(_IsolatedDB):
    def test_effective_pay_math(self):
        # $150k nominal in NYC (index 132.6) -> national-average dollars
        self.assertAlmostEqual(GEO.effective_pay(150000, 132.6),
                               150000 * 100 / 132.6, places=2)
        self.assertGreater(GEO.effective_pay(100000, 90.8),
                           GEO.effective_pay(100000, 132.6))

    def test_bundled_table_loads(self):
        table = GEO.load_col_index()
        self.assertIn("new york, ny", table["metros"])
        self.assertEqual(table["metros"]["new york, ny"]["index"], 132.6)
        self.assertIn("source", table["_meta"])
        self.assertIn("MERIC", table["_meta"]["source"])

    def test_find_metro(self):
        key, entry = GEO.find_metro("New York, NY")
        self.assertEqual(key, "new york, ny")
        self.assertEqual(entry["index"], 132.6)
        key2, _ = GEO.find_metro("nyc")
        self.assertEqual(key2, "new york, ny")
        key3, entry3 = GEO.find_metro("Austin, TX")
        self.assertEqual(entry3["index"], 90.8)
        self.assertIsNone(GEO.find_metro("Nowhere, ZZ"))
        self.assertIsNone(GEO.find_metro(""))

    def test_col_user_override(self):
        cfg = Path(self.td.name) / "cfg"
        cfg.mkdir()
        override = {"_meta": {"source": "test"}, "aliases": {},
                    "metros": {"testville, tx": {"label": "Testville, TX",
                                                 "index": 80.0}}}
        (cfg / "col_index.json").write_text(json.dumps(override))
        with patch.dict(os.environ, {"CANDID_CONFIG_DIR": str(cfg)}):
            table = GEO.load_col_index()
            self.assertEqual(table["metros"]["testville, tx"]["index"], 80.0)
            key, _ = GEO.find_metro("Testville, TX")
            self.assertEqual(key, "testville, tx")

    def test_rank_remote_math(self):
        jobs = [
            {"title": "Role A", "company": "C1", "location": "Remote",
             "url": "", "salary_text": "$100k - $120k", "description": ""},
            {"title": "Role B", "company": "C2", "location": "Remote",
             "url": "", "salary_text": "$200k-$220k", "description": ""},
            {"title": "Role C", "company": "C3", "location": "Remote",
             "url": "", "salary_text": "", "description": "no pay mentioned"},
        ]
        ranked = GEO.rank_remote_jobs(jobs, "austin, tx", 90.8)
        self.assertEqual(ranked["skipped_no_pay"], 1)
        rows = ranked["rows"]
        self.assertEqual([r["title"] for r in rows], ["Role B", "Role A"])
        self.assertAlmostEqual(rows[0]["nominal_mid"], 210000.0)
        self.assertAlmostEqual(rows[0]["effective"], 210000 * 100 / 90.8, places=2)

    def test_render_ranking_labels_estimates(self):
        ranked = GEO.rank_remote_jobs(
            [{"title": "Role B", "company": "C2", "location": "Remote", "url": "",
              "salary_text": "$200k-$220k", "description": ""}],
            "austin, tx", 90.8)
        out = GEO.render_ranking(ranked, "Austin, TX", 90.8, limit=5)
        self.assertIn("(est", out)
        self.assertIn("Estimates:", out)
        self.assertIn("Role B", out)


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

class CliSmokeTest(_IsolatedDB):
    def test_salary_sponsor_cli(self):
        import subprocess
        _write_lca(self.csv_path,
                   [_lca_row(f"A-{i}", "CERTIFIED", "Acme Inc") for i in range(12)])
        env = dict(os.environ, CANDID_DATA_DIR=str(Path(self.td.name)))
        r = subprocess.run(
            [sys.executable, "-m", "candid", "salary", "import-lca",
             str(self.csv_path)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(
            [sys.executable, "-m", "candid", "salary", "sponsor",
             "--company", "Acme"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/100", r.stdout)
        r = subprocess.run(
            [sys.executable, "-m", "candid", "salary", "sponsor",
             "--company", "Nobody"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Insufficient", r.stdout)

    def test_rank_remote_cli_inprocess(self):
        from candid import __main__ as CLI
        fake = [
            {"source": "remoteok", "source_id": "remoteok:1",
             "title": "Remote Data Scientist", "company": "C1",
             "location": "Remote", "url": "https://example.com/1",
             "description": "Python, ML.", "salary_text": "$150k - $180k",
             "remote": True, "posted_at": "2026-09-20"},
            {"source": "remoteok", "source_id": "remoteok:2",
             "title": "Remote ML Engineer", "company": "C2",
             "location": "Remote", "url": "https://example.com/2",
             "description": "Python, ML.", "salary_text": "$200k - $240k",
             "remote": True, "posted_at": "2026-09-20"},
        ]
        args = CLI.build_parser().parse_args(
            ["jobs", "rank-remote", "--location", "Austin, TX"])
        buf = io.StringIO()
        with patch.object(J, "_adapt_remoteok", _fake_fetch(fake)):
            with redirect_stdout(buf):
                args.func(args)
        out = buf.getvalue()
        self.assertIn("Effective", out)
        self.assertIn("(est", out)
        # higher nominal pay ranks first
        self.assertLess(out.index("Remote ML Engineer"), out.index("Remote Data Scientist"))

    def test_rank_remote_unknown_location_errors_cleanly(self):
        from candid import __main__ as CLI
        args = CLI.build_parser().parse_args(
            ["jobs", "rank-remote", "--location", "Nowhere, ZZ"])
        with self.assertRaises(J.JobsError):
            args.func(args)


if __name__ == "__main__":
    unittest.main()
