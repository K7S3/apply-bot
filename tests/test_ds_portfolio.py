"""Tests for batch-92: DS portfolio readiness (candid/ds_portfolio.py)
and DS salary bands (candid/salary.py additions).

Run: python -m pytest tests/test_ds_portfolio.py -q

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import ds_portfolio as D  # noqa: E402
from candid import salary as S  # noqa: E402

SAMPLE = ROOT / "candid" / "data" / "ds_portfolio_sample.json"

FULL = {
    "name": "churn",
    "description": ("Predicted telecom churn with XGBoost; beat a logistic "
                    "regression baseline by 6 F1 points on a held-out set."),
    "tech": ["python", "scikit-learn", "xgboost"],
    "data_source": "Public telecom churn dataset",
    "data_lineage": "Dropped duplicates; features computed as of snapshot date.",
    "metrics_reported": ["F1 0.71", "AUC 0.84"],
    "baseline": "logistic regression F1 0.65",
    "readme_present": True,
    "code_quality": {"tests": True, "lint": True, "docs": True},
}


def _tmpfile(suffix, text):
    td = tempfile.mkdtemp(prefix="candid-ds-")
    p = Path(td) / f"manifest{suffix}"
    p.write_text(text, encoding="utf-8")
    return p


class PortfolioScoringTest(unittest.TestCase):
    def test_full_project_scores_100(self):
        s = D.score_project(FULL)
        self.assertEqual(s["total"], 100)
        self.assertEqual(s["level"], "Portfolio-ready")
        self.assertEqual(s["suggestions"], [])

    def test_empty_project_scores_low_with_suggestions(self):
        s = D.score_project({"name": "blank"})
        self.assertLess(s["total"], 40)
        self.assertEqual(s["level"], "Needs work")
        joined = " ".join(s["suggestions"]).lower()
        for kw in ("readme", "metrics", "baseline"):
            self.assertIn(kw, joined)

    def test_missing_metrics_and_baseline_flagged(self):
        proj = dict(FULL, metrics_reported="", baseline="")
        s = D.score_project(proj)
        self.assertLess(s["total"], 100)
        joined = " ".join(s["suggestions"]).lower()
        self.assertIn("evaluation metrics", joined)
        self.assertIn("baseline", joined)
        self.assertEqual(s["dimensions"]["metrics"]["score"], 0)
        self.assertEqual(s["dimensions"]["baseline"]["score"], 0)

    def test_short_description_counts_as_missing(self):
        s = D.score_project(dict(FULL, description="too short"))
        self.assertFalse(s["dimensions"]["description"]["ok"])

    def test_partial_code_quality_proportional(self):
        proj = dict(FULL, code_quality={"tests": True, "lint": False, "docs": False})
        s = D.score_project(proj)
        dim = s["dimensions"]["code_quality"]
        self.assertAlmostEqual(dim["score"], 10 / 3, places=1)
        self.assertFalse(dim["ok"])

    def test_weakest_link_logic(self):
        results = D.check_projects([FULL, {"name": "blank"}])
        self.assertEqual(results["count"], 2)
        self.assertEqual(results["weakest"], "blank")
        self.assertEqual(results["portfolio_level"], "Work to do")
        out = D.render_check(results)
        self.assertIn("blank", out)
        self.assertIn("Weakest link", out)


class ManifestLoadingTest(unittest.TestCase):
    def test_sample_manifest_loads(self):
        projects = D.load_manifest(SAMPLE)
        self.assertEqual(len(projects), 3)
        self.assertEqual(projects[0]["name"], "Churn prediction pipeline")

    def test_sample_scores_sensibly(self):
        results = D.check_projects(D.load_manifest(SAMPLE))
        scores = {s["name"]: s["total"] for s in results["projects"]}
        self.assertGreater(scores["Churn prediction pipeline"], 90)
        self.assertLess(scores["Support ticket triage bot"], 40)

    def test_json_list_manifest(self):
        p = _tmpfile(".json", json.dumps([dict(FULL)]))
        self.assertEqual(len(D.load_manifest(p)), 1)

    def test_missing_file_raises(self):
        with self.assertRaises(D.DSPortfolioError):
            D.load_manifest("/tmp/does-not-exist-xyz.json")

    def test_bad_json_raises(self):
        p = _tmpfile(".json", "{not json")
        with self.assertRaises(D.DSPortfolioError):
            D.load_manifest(p)

    def test_empty_projects_raises(self):
        p = _tmpfile(".json", json.dumps({"projects": []}))
        with self.assertRaises(D.DSPortfolioError):
            D.load_manifest(p)

    def test_bad_suffix_raises(self):
        p = _tmpfile(".txt", "hello")
        with self.assertRaises(D.DSPortfolioError):
            D.load_manifest(p)

    @unittest.skipUnless(__import__("importlib").util.find_spec("yaml"),
                         "PyYAML not installed")
    def test_yaml_manifest_loads(self):
        import yaml
        p = _tmpfile(".yaml", yaml.safe_dump({"projects": [dict(FULL)]}))
        projects = D.load_manifest(p)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "churn")

    @unittest.skipUnless(__import__("importlib").util.find_spec("yaml") is None,
                         "PyYAML installed")
    def test_yaml_without_pyyaml_raises_helpfully(self):
        p = _tmpfile(".yaml", "projects: []")
        with self.assertRaises(D.DSPortfolioError) as ctx:
            D.load_manifest(p)
        self.assertIn("PyYAML", str(ctx.exception))


class DirectoryModeTest(unittest.TestCase):
    def _notes_dir(self):
        td = Path(tempfile.mkdtemp(prefix="candid-dsnotes-"))
        (td / "README.md").write_text("# My portfolio\n", encoding="utf-8")
        (td / "churn-prediction.md").write_text(
            "Predict customer churn for a telecom dataset using XGBoost.\n\n"
            "Data source: public telecom churn dataset. Used python, pandas "
            "and scikit-learn. Held-out accuracy 0.83, F1 0.71. Beat the "
            "logistic regression baseline (F1 0.65). Ran pytest and ruff.\n",
            encoding="utf-8")
        (td / "scratch.txt").write_text("todo: try a new dataset\n",
                                        encoding="utf-8")
        return td

    def test_directory_scan(self):
        projects = D.projects_from_directory(self._notes_dir())
        self.assertEqual(len(projects), 2)  # README is not a project
        churn = next(p for p in projects if "Churn" in p["name"])
        self.assertTrue(churn["metrics_reported"])
        self.assertTrue(churn["baseline"])
        self.assertTrue(churn["readme_present"])
        self.assertIn("python", churn["tech"])
        self.assertTrue(churn["code_quality"]["tests"])
        self.assertTrue(churn["code_quality"]["lint"])

    def test_no_notes_raises(self):
        td = Path(tempfile.mkdtemp(prefix="candid-dsnotes-empty-"))
        with self.assertRaises(D.DSPortfolioError):
            D.projects_from_directory(td)

    def test_not_a_directory_raises(self):
        p = _tmpfile(".md", "hello")
        with self.assertRaises(D.DSPortfolioError):
            D.projects_from_directory(p)


class GuideTest(unittest.TestCase):
    def test_guide_has_four_archetypes(self):
        g = D.render_guide()
        for head in ("END-TO-END ML PIPELINE",
                     "EXPERIMENTATION / CAUSAL INFERENCE STUDY",
                     "NLP / LLM PRODUCT",
                     "DATA STORYTELLING / ANALYTICS DEEP-DIVE",
                     "ANTI-PATTERNS"):
            self.assertIn(head, g)


class DSNormalizeTest(unittest.TestCase):
    def test_title_groups(self):
        cases = {
            "Data Scientist": "data-scientist",
            "Senior Data Scientist": "senior-data-scientist",
            "Sr. Data Scientist": "senior-data-scientist",
            "Staff Data Scientist": "senior-data-scientist",
            "Machine Learning Engineer": "ml-engineer",
            "ML Engineer": "ml-engineer",
            "Data Analyst II": "data-analyst",
            "DS Manager": "ds-manager",
            "Data Science Manager": "ds-manager",
            "Research Scientist": "research-scientist",
            "Janitor": "other",
            "": "other",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(S.normalize_ds_title(raw), want)


class DSBandsTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = Path(self.td.name) / "salary.db"
        for i, co in enumerate(["Acme", "Beta", "Gamma", "Delta", "Epsilon"]):
            S.add_range(co, "Data Scientist", 130000 + i * 10000,
                        170000 + i * 10000, location="New York",
                        source="job_post", path=self.db)
        for co in ["Acme", "Beta", "Gamma"]:
            S.add_range(co, "Machine Learning Engineer", 150000, 200000,
                        source="job_post", path=self.db)

    def tearDown(self):
        self.td.cleanup()

    def test_ds_bands_group_and_ordering(self):
        r = S.ds_bands("Data Scientist", path=self.db)
        self.assertEqual(r["group"], "data-scientist")
        self.assertGreaterEqual(r["n"], 3)
        self.assertLessEqual(r["p25"], r["median"])
        self.assertLessEqual(r["median"], r["p75"])

    def test_ds_bands_ml_engineer(self):
        r = S.ds_bands("ML Engineer", path=self.db)
        self.assertEqual(r["group"], "ml-engineer")
        self.assertGreater(r["n"], 0)

    def test_ds_bands_unknown_title_falls_back(self):
        r = S.ds_bands("Unicorn Wrangler", path=self.db)
        self.assertEqual(r["group"], "other")
        self.assertEqual(r["n"], 0)

    def test_ds_bands_uses_same_sources_as_lookup(self):
        # seeded rows are job_post-sourced; lookup should see them too
        lk = S.lookup(title="Data Scientist", path=self.db)
        bd = S.ds_bands("Data Scientist", path=self.db)
        self.assertGreater(lk["n"], 0)
        self.assertGreater(bd["n"], 0)

    def test_render_empty_bands(self):
        empty_db = Path(self.td.name) / "empty.db"
        out = S.render_ds_bands(S.ds_bands("Data Scientist", path=empty_db))
        self.assertIn("No salary data", out)
        self.assertIn("import-lca", out)

    def test_render_bands(self):
        S.add_range("Acme", "Data Analyst", 90000, 120000, source="job_post",
                    path=self.db)
        out = S.render_ds_bands(S.ds_bands("data analyst", path=self.db))
        self.assertIn("median", out)
        self.assertIn("data-analyst", out)


class DSCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-ds92-"))
        self._saved = C.SALARY_DB
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.ensure_data_dirs()

    def tearDown(self):
        C.SALARY_DB = self._saved

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()


class DSCLITest(DSCLIBase):
    def _seed(self):
        for co in ["Acme", "Beta", "Gamma"]:
            S.add_range(co, "Data Scientist", 130000, 180000,
                        location="New York", source="job_post")

    def test_ds_bands_cli(self):
        self._seed()
        code, out, _ = self.run_cli(["salary", "ds-bands", "Data Scientist"])
        self.assertEqual(code, 0)
        self.assertIn("median", out)
        self.assertIn("data-scientist", out)

    def test_ds_bands_cli_json(self):
        self._seed()
        code, out, _ = self.run_cli(
            ["salary", "ds-bands", "ML Engineer", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["group"], "ml-engineer")

    def test_ds_bands_cli_empty_db(self):
        code, out, _ = self.run_cli(["salary", "ds-bands", "Data Scientist"])
        self.assertEqual(code, 0)
        self.assertIn("No salary data", out)

    def test_ds_portfolio_guide_cli(self):
        code, out, _ = self.run_cli(["ds-portfolio", "guide"])
        self.assertEqual(code, 0)
        self.assertIn("DS PORTFOLIO PLAYBOOK", out)

    def test_ds_portfolio_check_manifest_cli(self):
        code, out, _ = self.run_cli(["ds-portfolio", "check", str(SAMPLE)])
        self.assertEqual(code, 0)
        self.assertIn("portfolio check", out)

    def test_ds_portfolio_check_dir_cli(self):
        td = Path(tempfile.mkdtemp(prefix="candid-dsnotes-cli-"))
        (td / "churn.md").write_text(
            "Churn prediction with XGBoost. Data source: telecom data. "
            "Held-out F1 0.71, beat baseline. python, pytest.\n",
            encoding="utf-8")
        code, out, _ = self.run_cli(["ds-portfolio", "check", str(td)])
        self.assertEqual(code, 0)
        self.assertIn("1 project", out)

    def test_ds_portfolio_check_missing_file_friendly_error(self):
        code, out, err = self.run_cli(
            ["ds-portfolio", "check", "/tmp/does-not-exist-xyz.json"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("ds-portfolio", err)

    def test_new_subcommands_in_inventory(self):
        self.assertIn("ds-portfolio", CLI.COMMANDS)
        self.assertIn("ds-bands", CLI.SUBCOMMANDS["salary"])
        self.assertEqual(sorted(CLI.SUBCOMMANDS["ds-portfolio"]),
                         ["check", "guide"])
        self.assertIn("DSPortfolioError", CLI._EXPECTED_ERRORS)


if __name__ == "__main__":
    unittest.main()
