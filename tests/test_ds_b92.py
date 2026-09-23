"""Tests for batch-92: ds-takehome simulator + `prep ds` pack.

Run: cd <repo> && python3 -m pytest tests/test_ds_b92.py -q
Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 - Present",
                    "bullets": ["Built churn models with XGBoost, lifting retention 3%."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
    "source_files": ["resume.pdf"],
}

EXPECTED_PROMPT_IDS = [
    "churn-risk", "pricing-elasticity", "anomaly-detection",
    "funnel-ab", "ltv-model", "metrics-review",
]


class DSBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-ds92-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp / "data"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.db"
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "proposals.json"
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))
        self.old_cwd = Path.cwd()
        import os
        os.chdir(str(self.tmp))

    def tearDown(self):
        import os
        os.chdir(str(self.old_cwd))
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(list(argv))
        return buf.getvalue()


class TakeHomeCatalogTest(DSBase):
    def test_six_prompts_with_unique_ids(self):
        from candid import ds_takehome as D
        prompts = D.list_prompts()
        self.assertEqual(len(prompts), 6)
        self.assertEqual([p["id"] for p in prompts], EXPECTED_PROMPT_IDS)
        self.assertEqual(len({p["id"] for p in prompts}), 6)

    def test_each_prompt_has_checklist_and_sections(self):
        from candid import ds_takehome as D
        for p in D.list_prompts():
            self.assertTrue(p["tasks"], p["id"])
            self.assertTrue(p["checklist"], p["id"])
            self.assertGreaterEqual(len(p["sections"]), 4, p["id"])
            for s in p["sections"]:
                self.assertIn("name", s)
                self.assertTrue(s["keywords"])

    def test_unknown_prompt_raises(self):
        from candid import ds_takehome as D
        with self.assertRaises(D.TakeHomeError):
            D.get_prompt("nope")

    def test_render_prompt_shows_checklist_and_sections(self):
        from candid import ds_takehome as D
        text = D.render_prompt(D.get_prompt("churn-risk"))
        self.assertIn("Subscriber Churn Analysis", text)
        self.assertIn("- [ ]", text)
        self.assertIn("Executive Summary", text)
        self.assertIn("drill", text.lower())

    def test_render_list_mentions_all_ids(self):
        from candid import ds_takehome as D
        text = D.render_list()
        for pid in EXPECTED_PROMPT_IDS:
            self.assertIn(pid, text)


class TakeHomeCSVTest(DSBase):
    def test_csv_generated_for_every_prompt(self):
        from candid import ds_takehome as D
        expected_columns = {
            "churn-risk": "customer_id",
            "pricing-elasticity": "market_id",
            "anomaly-detection": "timestamp",
            "funnel-ab": "user_id",
            "ltv-model": "cohort_month",
            "metrics-review": "week",
        }
        for pid, column in expected_columns.items():
            dest = D.write_sample_csv(pid, self.tmp / f"{pid}.csv")
            self.assertTrue(dest.exists(), pid)
            header = dest.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn(column, header.split(","), f"{pid}: {header}")
            self.assertGreater(len(dest.read_text().splitlines()), 10, pid)

    def test_csv_is_reproducible(self):
        from candid import ds_takehome as D
        a = D.write_sample_csv("churn-risk", self.tmp / "a.csv")
        b = D.write_sample_csv("churn-risk", self.tmp / "b.csv")
        self.assertEqual(a.read_text(), b.read_text())


class TakeHomeStartSubmitTest(DSBase):
    def test_start_records_state_and_deadline(self):
        from candid import ds_takehome as D
        before = datetime.now()
        out = D.start("churn-risk", hours=8)
        after = datetime.now()
        self.assertIn("Deadline", out)
        self.assertIn("Subscriber Churn Analysis", out)
        self.assertIn("- [ ]", out)  # checklist printed
        state = json.loads((C.DATA_DIR / "ds_takehome.json").read_text())
        e = state["churn-risk"]
        dl = datetime.fromisoformat(e["deadline"])
        # deadline stored at second precision; allow a small tolerance
        self.assertGreaterEqual(dl, before + timedelta(hours=8) - timedelta(seconds=5))
        self.assertLessEqual(dl, after + timedelta(hours=8))
        self.assertIsNone(e["submitted_at"])

    def test_start_defaults_to_prompt_timebox(self):
        from candid import ds_takehome as D
        D.start("metrics-review")
        state = json.loads((C.DATA_DIR / "ds_takehome.json").read_text())
        self.assertEqual(state["metrics-review"]["hours"], 3)

    def test_submit_full_report_is_complete(self):
        from candid import ds_takehome as D
        p = D.get_prompt("pricing-elasticity")
        report = self.tmp / "report.md"
        report.write_text("\n\n".join(
            f"## {s['name']}\n" + " ".join(s["keywords"]) for s in p["sections"]))
        out = D.submit("pricing-elasticity", report)
        self.assertIn("completeness check, not a grading", out)
        self.assertIn("5/5", out)
        state = json.loads((C.DATA_DIR / "ds_takehome.json").read_text())
        self.assertEqual(state["pricing-elasticity"]["completeness_pct"], 100)

    def test_submit_partial_report_lists_missing(self):
        from candid import ds_takehome as D
        report = self.tmp / "thin.md"
        report.write_text("# Summary\nWe found an anomaly and detected it on the timestamp.\n")
        res = D.check_completeness("anomaly-detection", report.read_text())
        self.assertLess(res["completeness_pct"], 100)
        self.assertTrue(res["sections_missing"])
        rendered = D.render_completeness(res)
        self.assertIn("completeness check, not a grading", rendered)
        for missing in res["sections_missing"]:
            self.assertIn(missing, rendered)

    def test_submit_missing_file_raises(self):
        from candid import ds_takehome as D
        with self.assertRaises(D.TakeHomeError):
            D.submit("churn-risk", self.tmp / "does-not-exist.md")

    def test_submit_empty_file_raises(self):
        from candid import ds_takehome as D
        empty = self.tmp / "empty.md"
        empty.write_text("   \n")
        with self.assertRaises(D.TakeHomeError):
            D.submit("churn-risk", empty)

    def test_status_reflects_started_drill(self):
        from candid import ds_takehome as D
        self.assertIn("No take-home drills started", D.status())
        D.start("funnel-ab", hours=5)
        self.assertIn("funnel-ab", D.status())
        self.assertIn("in progress", D.status())


class TakeHomeCLITest(DSBase):
    def test_cli_list_show_start_submit(self):
        out = self.run_cli("ds-takehome", "list")
        self.assertIn("churn-risk", out)
        out = self.run_cli("ds-takehome", "show", "churn-risk")
        self.assertIn("Subscriber Churn Analysis", out)
        out = self.run_cli("ds-takehome", "csv", "churn-risk", "-o",
                           str(self.tmp / "subs.csv"))
        self.assertTrue((self.tmp / "subs.csv").exists())
        out = self.run_cli("ds-takehome", "start", "metrics-review", "--hours", "2")
        self.assertIn("Deadline", out)
        rep = self.tmp / "rep.md"
        p = __import__("candid.ds_takehome", fromlist=["get_prompt"]).get_prompt("metrics-review")
        rep.write_text("\n\n".join(f"# {s['name']}\n{' '.join(s['keywords'])}"
                                   for s in p["sections"]))
        out = self.run_cli("ds-takehome", "submit", "metrics-review", str(rep))
        self.assertIn("completeness check, not a grading", out)
        out = self.run_cli("ds-takehome", "status")
        self.assertIn("metrics-review", out)

    def test_cli_unknown_id_is_friendly_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                self.run_cli("ds-takehome", "show", "bogus")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Unknown take-home", err.getvalue())


class PrepDSTest(DSBase):
    def test_build_ds_pack_sections(self):
        from candid import prep as P
        md, path = P.build_ds_pack(PROFILE, "Data Scientist", company="Acme")
        self.assertTrue(path.exists())
        self.assertIn("## 1. Statistics refresher", md)
        self.assertIn("## 2. ML case list", md)
        self.assertIn("## 3. SQL drills", md)
        self.assertIn("## 4.", md)
        self.assertIn("No verified company-specific questions found", md)
        self.assertIn("never fabricated", md)
        # stats topics come from the sibling ds_stats module when present
        self.assertIn("hypothesis_testing", md)
        self.assertIn("ds_stats", md)
        # ML cases and SQL drills present
        self.assertIn("Churn / retention prediction", md)
        self.assertIn("Window", md)

    def test_ds_stats_sibling_used_when_present(self):
        from candid import prep as P
        topics, source = P._ds_stats_topics()
        self.assertTrue(topics)
        self.assertIn("ds_stats", source)

    def test_ds_stats_failure_falls_back(self):
        import types
        import candid
        from candid import prep as P
        real_mod = sys.modules.get("candid.ds_stats")
        real_attr = getattr(candid, "ds_stats", None)
        fake = types.ModuleType("candid.ds_stats")

        def boom():
            raise RuntimeError("broken bank")

        fake.topics = boom
        sys.modules["candid.ds_stats"] = fake
        candid.ds_stats = fake
        try:
            topics, source = P._ds_stats_topics()
        finally:
            if real_mod is not None:
                sys.modules["candid.ds_stats"] = real_mod
            else:
                del sys.modules["candid.ds_stats"]
            if real_attr is not None:
                candid.ds_stats = real_attr
        self.assertIn("built-in", source)
        self.assertTrue(any("Hypothesis testing" in t for t in topics))

    def test_ds_sql_sibling_used_when_present(self):
        from candid import prep as P
        drills, source = P._ds_sql_drills()
        self.assertTrue(drills)
        self.assertIn("ds_sql", source)
        titles = [t for t, _ in drills]
        self.assertTrue(any("Window" in t for t in titles))

    def test_ds_pack_uses_sourced_company_questions(self):
        from candid import prep as P
        md, _ = P.build_ds_pack(PROFILE, "Data Scientist", company="Capital One")
        self.assertIn("Source:", md)
        self.assertNotIn("No verified company-specific questions found", md)

    def test_legacy_prep_pack_still_works(self):
        from candid import prep as P
        md, path = P.build_pack(PROFILE, "Acme", "Data Scientist")
        self.assertTrue(path.exists())
        self.assertIn("# Interview Prep", md)
        self.assertIn("## 1. Company-specific questions", md)

    def test_cli_prep_ds(self):
        out = self.run_cli("prep", "ds", "Data Scientist", "--company", "Acme")
        self.assertIn("DS prep pack saved to", out)
        packs = list(C.PREP_PACKS_DIR.glob("*.md"))
        self.assertEqual(len(packs), 1)
        text = packs[0].read_text()
        self.assertIn("Statistics refresher", text)
        self.assertIn("SQL drills", text)

    def test_cli_prep_ds_without_company(self):
        out = self.run_cli("prep", "ds", "Data Analyst")
        self.assertIn("DS prep pack saved to", out)

    def test_cli_legacy_prep_unchanged(self):
        out = self.run_cli("prep", "--company", "Acme", "--role", "Data Scientist")
        self.assertIn("Prep pack saved to", out)
        self.assertNotIn("DS prep pack", out)


if __name__ == "__main__":
    unittest.main()
