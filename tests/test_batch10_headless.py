"""Batch 10, workstream D: --json everywhere + headless/CI mode.

Covers:
  - --json on every command/subcommand emits valid JSON on stdout (exit 0)
  - headless mode (--headless flag and CANDID_HEADLESS=1): expected failures
    print one JSON {"error", "next"} object on stderr and exit 3
  - interactive mode keeps typo suggestions, friendly errors, and next steps
  - interactive-only sessions (mock ai/coding/behavioral/design, dashboard)
    refuse cleanly in headless mode

Run: python3 -m unittest tests.test_batch10_headless -v
(uses a fresh temp CANDID_DATA_DIR per run; no profile leaks between runs)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples" / "candid"

TWO_SUM_SOLUTION = """\
def solve(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
"""


class HeadlessCLITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="candid-batch10-headless-")
        cls._run(["onboard", "--resume", str(SAMPLES / "sample_resume.md")])
        cls._run(["track", "add", "--company", "Acme",
                  "--role", "Data Scientist", "--status", "applied"])

    @classmethod
    def _run(cls, args, env_extra=None):
        env = dict(os.environ)
        env["CANDID_DATA_DIR"] = cls.tmp
        env.pop("CANDID_HEADLESS", None)  # isolation; tests opt in explicitly
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "candid", *args],
            capture_output=True, text=True, cwd=str(ROOT), env=env,
            timeout=180)

    def _assert_json_stdout(self, args, env_extra=None):
        p = self._run(args, env_extra=env_extra)
        self.assertEqual(p.returncode, 0, f"{args} failed: {p.stderr[:500]}")
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"{args} did not emit valid JSON on stdout:\n{p.stdout[:500]}")

    # --json everywhere: valid JSON on stdout, exit 0 -----------------------
    def test_onboard_json(self):
        d = self._assert_json_stdout(
            ["onboard", "--resume", str(SAMPLES / "sample_resume.md"), "--json"])
        self.assertIn("profile", d)
        self.assertTrue(d["profile"].get("name"))

    def test_profile_show_json(self):
        d = self._assert_json_stdout(["profile", "show", "--json"])
        self.assertTrue(d.get("name"))

    def test_match_json(self):
        d = self._assert_json_stdout(
            ["match", "--jd", str(SAMPLES / "sample_jd.txt"),
             "--company", "Acme", "--role", "Data Scientist", "--json"])
        self.assertIn("score", d)

    def test_tailor_resume_json(self):
        d = self._assert_json_stdout(
            ["tailor", "resume", "--jd", str(SAMPLES / "sample_jd.txt"),
             "--company", "Acme", "--role", "Data Scientist", "--json"])
        self.assertTrue(d.get("text"))

    def test_track_add_list_json(self):
        d = self._assert_json_stdout(
            ["track", "add", "--company", "Initech", "--role", "ML Engineer",
             "--json"])
        self.assertEqual(d["company"], "Initech")
        apps = self._assert_json_stdout(["track", "list", "--json"])
        self.assertIsInstance(apps, list)
        self.assertGreaterEqual(len(apps), 2)

    def test_track_stats_search_json(self):
        stats = self._assert_json_stdout(["track", "stats", "--json"])
        self.assertIsInstance(stats, dict)
        hits = self._assert_json_stdout(["track", "search", "acme", "--json"])
        self.assertIsInstance(hits, list)

    def test_prep_json(self):
        d = self._assert_json_stdout(
            ["prep", "--company", "Acme", "--role", "Data Scientist", "--json"])
        self.assertTrue(d.get("markdown"))
        self.assertTrue(d.get("path"))

    def test_followup_json(self):
        for what, extra in (("thank-you", []), ("check-in", []), ("referral", [])):
            d = self._assert_json_stdout(
                ["followup", what, "--person", "Jane", "--role", "DS",
                 "--company", "Acme", "--json"] + extra)
            self.assertTrue(d.get("text"), what)

    def test_offer_json(self):
        d = self._assert_json_stdout(
            ["offer", "add", "--company", "Acme", "--role", "DS",
             "--base", "180000", "--json"])
        self.assertEqual(d["company"], "Acme")
        offers = self._assert_json_stdout(["offer", "list", "--json"])
        self.assertIsInstance(offers, list)
        offers = self._assert_json_stdout(["offer", "compare", "--json"])
        self.assertIsInstance(offers, list)
        d = self._assert_json_stdout(["offer", "export", "--json"])
        self.assertTrue(d.get("path"))

    def test_negotiate_json(self):
        d = self._assert_json_stdout(["negotiate", "playbook", "--json"])
        self.assertTrue(d.get("text"))
        d = self._assert_json_stdout(
            ["negotiate", "script", "--which", "lowball_anchor", "--json"])
        self.assertTrue(d.get("text"))
        d = self._assert_json_stdout(
            ["negotiate", "counter", "--person", "Jane", "--role", "DS",
             "--company", "Acme", "--base-ask", "190k base", "--json"])
        self.assertTrue(d.get("text"))

    def test_salary_json(self):
        d = self._assert_json_stdout(
            ["salary", "lookup", "--company", "Acme", "--title", "DS", "--json"])
        self.assertIsInstance(d, dict)
        d = self._assert_json_stdout(
            ["salary", "parse-range", "--company", "Acme", "--role", "DS",
             "--text", "Pay range $120k-$150k", "--json"])
        self.assertEqual(d["parsed"]["low"], 120000.0)

    def test_mock_json(self):
        problems = self._assert_json_stdout(["mock", "list", "--json"])
        self.assertIsInstance(problems, list)
        self.assertGreater(len(problems), 0)
        d = self._assert_json_stdout(
            ["mock", "hint", "--problem", "two-sum", "--json"])
        self.assertTrue(d.get("hints"))
        d = self._assert_json_stdout(
            ["mock", "solution", "--problem", "two-sum", "--json"])
        self.assertTrue(d.get("solution"))

    def test_mock_run_json(self):
        sol = Path(self.tmp) / "two_sum.py"
        sol.write_text(TWO_SUM_SOLUTION)
        p = self._run(["mock", "run", "--problem", "two-sum",
                       "--file", str(sol), "--json"])
        self.assertEqual(p.returncode, 0, p.stderr[:500])
        d = json.loads(p.stdout)
        self.assertEqual(d["verdict"], "accepted")

    def test_jobs_list_json(self):
        jobs = self._assert_json_stdout(["jobs", "list", "--json"])
        self.assertIsInstance(jobs, list)

    def test_gmail_linkedin_json(self):
        d = self._assert_json_stdout(["gmail", "guide", "--json"])
        self.assertTrue(d.get("guide"))
        proposals = self._assert_json_stdout(["gmail", "proposals", "--json"])
        self.assertIsInstance(proposals, list)
        d = self._assert_json_stdout(["linkedin", "guide", "--json"])
        self.assertTrue(d.get("guide"))

    # headless mode: JSON errors on stderr, exit 3 ---------------------------
    def _assert_headless_error(self, p):
        self.assertEqual(p.returncode, 3, f"stderr: {p.stderr[:300]}")
        try:
            err = json.loads(p.stderr)
        except json.JSONDecodeError:
            self.fail(f"headless error was not a single JSON object:\n{p.stderr[:500]}")
        self.assertIn("error", err)
        self.assertIn("next", err)
        self.assertEqual(p.stdout, "")
        return err

    def test_headless_expected_failure_exit3(self):
        p = self._run(["--headless", "track", "update", "999",
                       "--status", "applied"])
        err = self._assert_headless_error(p)
        self.assertIn("999", err["error"])

    def test_headless_env_var_works_without_flag(self):
        p = self._run(["mock", "solution", "--problem", "bogus-problem"],
                      env_extra={"CANDID_HEADLESS": "1"})
        err = self._assert_headless_error(p)
        self.assertIn("bogus-problem", err["error"])
        self.assertEqual(err["next"], "python -m candid mock --help")

    def test_headless_success_exit0(self):
        p = self._run(["--headless", "track", "list", "--json"])
        self.assertEqual(p.returncode, 0, p.stderr[:300])
        self.assertIsInstance(json.loads(p.stdout), list)

    def test_headless_no_typo_suggestions(self):
        p = self._run(["--headless", "matc"])
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Did you mean", p.stderr)

    def test_mock_ai_refused_in_headless(self):
        p = self._run(["--headless", "mock", "ai"])
        err = self._assert_headless_error(p)
        self.assertIn("interactive", err["error"].lower())

    def test_mock_coding_refused_in_headless(self):
        p = self._run(["--headless", "mock", "coding"],
                      env_extra={"CANDID_HEADLESS": "true"})
        self._assert_headless_error(p)

    def test_dashboard_refused_in_headless(self):
        p = self._run(["--headless", "dashboard"])
        self._assert_headless_error(p)

    # interactive mode keeps its UX ------------------------------------------
    def test_typo_suggestion_interactive(self):
        p = self._run(["matc"])
        self.assertEqual(p.returncode, 2)
        self.assertIn("Did you mean", p.stderr)
        self.assertIn("match", p.stderr)

    def test_interactive_expected_failure_exit1(self):
        p = self._run(["track", "update", "999", "--status", "applied"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("Error:", p.stderr)
        self.assertIn("Next:", p.stderr)


if __name__ == "__main__":
    unittest.main()
