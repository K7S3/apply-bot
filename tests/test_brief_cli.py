"""CLI integration tests for `brief` (batch-84 interviewer brief).

Covers the argparse wiring in candid/__main__.py, the prep-pack hook, and the
dashboard prep_status extension. Data paths are redirected into a temp dir.
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
from candid import interviewers as I  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 - Present",
                    "bullets": ["Built churn models with XGBoost, lifting retention 4%."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
    "source_files": ["resume.pdf"],
}


class BriefCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-briefcli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        self._saved_iv = I.DEFAULT_PATH
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        I.DEFAULT_PATH = self.tmp / "interviewers.json"
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)
        I.DEFAULT_PATH = self._saved_iv

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


class BriefAddListTest(BriefCLIBase):
    def test_add_and_list(self):
        code, out, _ = self.run_cli(
            ["brief", "add", "--name", "Jane Doe", "--role", "hiring_manager",
             "--round", "Round 2"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        code, out, _ = self.run_cli(["brief", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        self.assertIn("hiring_manager", out)

    def test_list_json(self):
        self.run_cli(["brief", "add", "--name", "Sam Lee", "--role", "peer_engineer"])
        code, out, _ = self.run_cli(["brief", "list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Sam Lee")

    def test_list_empty_hint(self):
        code, out, _ = self.run_cli(["brief", "list"])
        self.assertEqual(code, 0)
        self.assertIn("brief add", out)

    def test_remove(self):
        self.run_cli(["brief", "add", "--name", "Jane Doe"])
        code, out, _ = self.run_cli(["brief", "remove", "--id", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Removed", out)
        code, out, _ = self.run_cli(["brief", "list"])
        self.assertIn("No interviewers recorded yet", out)

    def test_remove_missing_id_friendly(self):
        code, _, err = self.run_cli(["brief", "remove", "--id", "99"])
        self.assertEqual(code, 1)
        self.assertIn("Error", err)


class BriefBackgroundDebriefTest(BriefCLIBase):
    def test_background(self):
        self.run_cli(["brief", "add", "--name", "Jane Doe"])
        code, out, _ = self.run_cli(
            ["brief", "background", "--id", "1", "--title", "Eng Manager",
             "--focus", "ranking, experimentation"])
        self.assertEqual(code, 0)
        iv = I.get_interviewer(1)
        self.assertEqual(iv["background"]["title"], "Eng Manager")
        self.assertEqual(iv["background"]["focus_areas"],
                         ["ranking", "experimentation"])

    def test_background_nothing_to_update(self):
        self.run_cli(["brief", "add", "--name", "Jane Doe"])
        code, out, _ = self.run_cli(["brief", "background", "--id", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing to update", out)

    def test_debrief(self):
        self.run_cli(["brief", "add", "--name", "Jane Doe"])
        code, out, _ = self.run_cli(
            ["brief", "debrief", "--id", "1",
             "--asked", "churn case; SQL window",
             "--signals", "dug deep on metrics"])
        self.assertEqual(code, 0)
        iv = I.get_interviewer(1)
        self.assertEqual(iv["debrief"]["asked"],
                         ["churn case", "SQL window"])
        self.assertEqual(iv["debrief"]["signals"], ["dug deep on metrics"])


class BriefRolesTest(BriefCLIBase):
    def test_roles_lists_all(self):
        code, out, _ = self.run_cli(["brief", "roles"])
        self.assertEqual(code, 0)
        for role in ("hiring_manager", "peer_engineer", "bar_raiser",
                     "recruiter", "skip_level", "domain_specialist"):
            self.assertIn(role, out)

    def test_roles_json(self):
        code, out, _ = self.run_cli(["brief", "roles", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("bar_raiser", data)
        self.assertIn("likely_angles", data["bar_raiser"])


class BriefShowTest(BriefCLIBase):
    def test_show_no_interviewers_hint(self):
        code, out, _ = self.run_cli(["brief", "show", "--company", "Acme"])
        self.assertEqual(code, 0)
        self.assertIn("brief add", out)

    def test_show_builds_and_saves(self):
        self.run_cli(["track", "add", "--company", "Acme",
                      "--role", "Data Scientist",
                      "--status", "selected_for_interview"])
        self.run_cli(["brief", "add", "--name", "Jane Doe",
                      "--role", "hiring_manager", "--app-id", "1"])
        code, out, _ = self.run_cli(
            ["brief", "show", "--company", "Acme",
             "--role-title", "Data Scientist"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        self.assertIn("Questions to ask", out)
        briefs = list((self.tmp / "briefs").glob("*.md"))
        self.assertEqual(len(briefs), 1)


class BriefPrepIntegrationTest(BriefCLIBase):
    def test_prep_pack_appends_brief_section(self):
        self.run_cli(["track", "add", "--company", "Acme",
                      "--role", "Data Scientist",
                      "--status", "selected_for_interview"])
        self.run_cli(["brief", "add", "--name", "Jane Doe",
                      "--role", "hiring_manager", "--app-id", "1"])
        code, out, _ = self.run_cli(
            ["prep", "--company", "Acme", "--role", "Data Scientist",
             "--app-id", "1"])
        self.assertEqual(code, 0)
        packs = list((self.tmp / "prep_packs").glob("*.md"))
        self.assertEqual(len(packs), 1)
        text = packs[0].read_text(encoding="utf-8")
        self.assertIn("## Interview brief", text)
        self.assertIn("Jane Doe", text)

    def test_prep_pack_without_interviewers_has_no_brief(self):
        self.run_cli(["track", "add", "--company", "Globex",
                      "--role", "Data Scientist",
                      "--status", "selected_for_interview"])
        code, _, _ = self.run_cli(
            ["prep", "--company", "Globex", "--role", "Data Scientist",
             "--app-id", "1"])
        self.assertEqual(code, 0)
        packs = list((self.tmp / "prep_packs").glob("*.md"))
        text = packs[0].read_text(encoding="utf-8")
        self.assertNotIn("## Interview brief", text)


class BriefDashboardTest(BriefCLIBase):
    def test_prep_status_includes_interviewer_count(self):
        from candid import dashboard as D
        self.run_cli(["track", "add", "--company", "Acme",
                      "--role", "Data Scientist",
                      "--status", "selected_for_interview"])
        self.run_cli(["brief", "add", "--name", "Jane Doe",
                      "--role", "hiring_manager", "--app-id", "1"])
        self.run_cli(["brief", "add", "--name", "Sam Lee",
                      "--role", "peer_engineer", "--app-id", "1"])
        status = D.prep_status()
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["n_interviewers"], 2)


if __name__ == "__main__":
    unittest.main()
