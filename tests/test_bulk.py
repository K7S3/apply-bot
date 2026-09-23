"""Tests for candid.bulk (bulk JD import / ranking).

Covers: scoring reuse via candid.match.score_match, ranking order, manifest
parsing, filename company/role guessing, bad-file handling (warnings, no
tracebacks), --min-score filtering, --top limiting, and the ranked table.
All fixtures live in tmp dirs; the real user data dir is never touched.
"""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-bulk-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import bulk as B  # noqa: E402

SAMPLES = ROOT / "samples" / "candid"


def _profile(**kw):
    prof = {
        "name": "Test User",
        "location": "New York, NY",
        "headline": "Senior Data Scientist",
        "seniority": "senior",
        "years_experience": 5.0,
        "skills": ["python", "sql", "machine learning", "statistics",
                   "xgboost", "scikit-learn", "pandas", "llm", "cloud"],
        "experience": [{"title": "Senior Data Scientist", "company": "Acme"}],
    }
    prof.update(kw)
    return prof


JD_A = """Senior Data Scientist - Risk Modeling
Requirements:
- 5+ years of experience in data science
- Strong SQL and Python skills, pandas for analysis
- Machine learning: XGBoost, scikit-learn, model evaluation
- Statistics: A/B testing and experimental design
Nice to have:
- Airflow experience
Compensation: $160,000 - $200,000 per year.
"""

JD_B = """Junior Frontend Developer
Requirements:
- 1+ year of experience with JavaScript and React
- HTML and CSS fundamentals
- Familiarity with Figma
Compensation: $90,000 - $110,000 per year.
"""


def _write_jds(tmp: Path) -> Path:
    d = tmp / "jds"
    d.mkdir()
    (d / "AcmeCorp__Senior-Data-Scientist.txt").write_text(JD_A, encoding="utf-8")
    (d / "OtherCo__Frontend-Developer.txt").write_text(JD_B, encoding="utf-8")
    return d


class TestFilenameParsing(unittest.TestCase):
    def test_double_underscore_split(self):
        self.assertEqual(
            B.company_role_from_filename("AcmeCorp__Data-Scientist.txt"),
            ("AcmeCorp", "Data Scientist"),
        )

    def test_plain_role_stem(self):
        company, role = B.company_role_from_filename("data-scientist.txt")
        self.assertEqual(company, "")
        self.assertEqual(role, "data scientist")

    def test_never_raises(self):
        self.assertEqual(B.company_role_from_filename("x"), ("x", ""))


class TestManifest(unittest.TestCase):
    def _manifest(self, tmp: Path, rows) -> Path:
        p = tmp / "meta.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "company", "role"])
            w.writerows(rows)
        return p

    def test_parse_ok(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p = self._manifest(tmp, [("a.txt", "Acme", "Data Scientist")])
            self.assertEqual(B.parse_manifest(p), {"a.txt": ("Acme", "Data Scientist")})

    def test_filename_alias(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p = tmp / "m.csv"
            p.write_text("filename,company,title\nb.txt,Beta,ML Engineer\n",
                         encoding="utf-8")
            self.assertEqual(B.parse_manifest(p), {"b.txt": ("Beta", "ML Engineer")})

    def test_missing_file(self):
        with self.assertRaises(B.BulkError) as cm:
            B.parse_manifest("/tmp/candid-nope-manifest.csv")
        self.assertIn("python -m candid bulk", str(cm.exception))

    def test_bad_headers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p = tmp / "m.csv"
            p.write_text("name,org\nx.txt,Y\n", encoding="utf-8")
            with self.assertRaises(B.BulkError) as cm:
                B.parse_manifest(p)
            self.assertIn("file,company,role", str(cm.exception))


class TestCollect(unittest.TestCase):
    def test_dir_scan(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_jds(Path(td))
            (d / "notes.pdf").write_text("not a jd", encoding="utf-8")
            files = B.collect_jd_files(jd_dir=d)
            self.assertEqual([f.name for f in files],
                             ["AcmeCorp__Senior-Data-Scientist.txt",
                              "OtherCo__Frontend-Developer.txt"])

    def test_missing_dir(self):
        with self.assertRaises(B.BulkError) as cm:
            B.collect_jd_files(jd_dir="/tmp/candid-nope-dir")
        self.assertIn("python -m candid bulk", str(cm.exception))

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(B.BulkError):
                B.collect_jd_files(jd_dir=td)

    def test_nothing_given(self):
        with self.assertRaises(B.BulkError):
            B.collect_jd_files()


class TestScoreAll(unittest.TestCase):
    def test_scoring_reuses_match_and_ranks_desc(self):
        # score_all delegates to candid.match.score_match for real JDs and
        # ranks highest score first.
        with tempfile.TemporaryDirectory() as td:
            d = _write_jds(Path(td))
            out = B.score_all(_profile(), jd_dir=d)
            self.assertEqual(out["warnings"], [])
            self.assertEqual(len(out["results"]), 2)
            scores = [r["score"] for r in out["results"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
            # the senior DS JD should beat the frontend one for a DS profile
            self.assertGreater(scores[0], scores[1])
            top = out["results"][0]
            self.assertEqual(top["company"], "AcmeCorp")
            self.assertEqual(top["role"], "Senior Data Scientist")
            self.assertIn("verdict", top)
            self.assertIsInstance(top["missing_must_haves"], list)
            # sample JDs give the verdict/missing fields real match.py output
            self.assertIn(top["verdict"], ("GO", "CONDITIONAL", "NO-GO"))

    def test_mocked_scoring_order_and_payload(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_jds(Path(td))
            fake = {
                "AcmeCorp__Senior-Data-Scientist.txt": {
                    "score": 42.0, "verdict": "NO-GO",
                    "missing_skill_pointers": {"dbt": "x", "spark": "y"},
                },
                "OtherCo__Frontend-Developer.txt": {
                    "score": 88.0, "verdict": "GO",
                    "missing_skill_pointers": {},
                },
            }

            def _fake_score(profile, jd, title="", company="", location=""):
                # figure out which file by matching company back
                key = next(k for k in fake if company in k)
                return fake[key]

            with mock.patch("candid.bulk.M.score_match", side_effect=_fake_score):
                out = B.score_all(_profile(), jd_dir=d)
            self.assertEqual([r["score"] for r in out["results"]], [88.0, 42.0])
            self.assertEqual(out["results"][0]["verdict"], "GO")
            self.assertEqual(out["results"][1]["missing_must_haves"], ["dbt", "spark"])

    def test_explicit_jd_files(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f1 = tmp / "one.txt"
            f1.write_text(JD_A, encoding="utf-8")
            out = B.score_all(_profile(), jd_files=[f1])
            self.assertEqual(len(out["results"]), 1)
            self.assertEqual(out["results"][0]["file"], "one.txt")

    def test_bad_files_warn_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            good = tmp / "good.txt"
            good.write_text(JD_A, encoding="utf-8")
            empty = tmp / "empty.txt"
            empty.write_text("too short", encoding="utf-8")
            missing = tmp / "ghost.txt"  # listed explicitly but absent
            out = B.score_all(_profile(), jd_files=[good, empty, missing])
            self.assertEqual(len(out["results"]), 1)
            self.assertEqual(len(out["warnings"]), 2)
            self.assertTrue(all("skipped" in w for w in out["warnings"]))

    def test_min_score_filter(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_jds(Path(td))
            out = B.score_all(_profile(), jd_dir=d, min_score=1000.0)
            self.assertEqual(out["results"], [])
            lo = B.score_all(_profile(), jd_dir=d, min_score=0.0)
            self.assertEqual(len(lo["results"]), 2)

    def test_manifest_overrides_filename(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = _write_jds(tmp)
            p = tmp / "meta.csv"
            p.write_text("file,company,role\n"
                         "AcmeCorp__Senior-Data-Scientist.txt,Initech,Principal DS\n",
                         encoding="utf-8")
            out = B.score_all(_profile(), jd_dir=d, manifest=p)
            row = next(r for r in out["results"]
                       if r["file"] == "AcmeCorp__Senior-Data-Scientist.txt")
            self.assertEqual(row["company"], "Initech")
            self.assertEqual(row["role"], "Principal DS")

    def test_results_json_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_jds(Path(td))
            out = B.score_all(_profile(), jd_dir=d)
            json.dumps(out)  # must not raise

    def test_sample_jd_from_samples_dir(self):
        if not (SAMPLES / "sample_jd.txt").exists():
            self.skipTest("samples/candid/sample_jd.txt not present")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f1 = tmp / "sample.txt"
            f1.write_text((SAMPLES / "sample_jd.txt").read_text(encoding="utf-8"),
                          encoding="utf-8")
            out = B.score_all(_profile(), jd_files=[f1])
            self.assertEqual(len(out["results"]), 1)
            self.assertGreater(out["results"][0]["score"], 0)


class TestRenderTable(unittest.TestCase):
    def _rows(self):
        return [
            {"file": "a.txt", "company": "Acme", "role": "Data Scientist",
             "score": 82.5, "verdict": "GO", "missing_must_haves": ["dbt"]},
            {"file": "b.txt", "company": "Beta", "role": "ML Engineer",
             "score": 45.0, "verdict": "NO-GO",
             "missing_must_haves": ["kubernetes", "spark", "dbt", "airflow"]},
        ]

    def test_table_columns(self):
        t = B.render_table(self._rows())
        self.assertIn("SCORE", t)
        self.assertIn("VERDICT", t)
        self.assertIn("COMPANY", t)
        self.assertIn("MISSING MUST-HAVES", t)
        self.assertIn("82.5", t)
        self.assertIn("Acme", t)
        self.assertIn("dbt", t)
        # rank order preserved: 82.5 line before 45.0 line
        self.assertLess(t.index("82.5"), t.index("45.0"))

    def test_top_limit(self):
        t = B.render_table(self._rows(), top=1)
        self.assertIn("Acme", t)
        self.assertNotIn("Beta", t)
        self.assertIn("top 1", t)

    def test_bad_top(self):
        with self.assertRaises(B.BulkError) as cm:
            B.render_table(self._rows(), top=0)
        self.assertIn("python -m candid bulk", str(cm.exception))

    def test_empty(self):
        t = B.render_table([])
        self.assertIn("--min-score", t)


class TestCliSurface(unittest.TestCase):
    """The dispatcher contract: cmd_bulk exists in CLI_REGISTRATION.txt."""
    def test_registration_doc_present(self):
        doc = ROOT / "CLI_REGISTRATION.txt"
        self.assertTrue(doc.exists(), "CLI_REGISTRATION.txt must ship with bulk.py")
        text = doc.read_text(encoding="utf-8")
        for token in ("cmd_bulk", '"bulk"', "--jd-dir", "--min-score",
                      "_NEXT_COMMAND", "BulkError"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
