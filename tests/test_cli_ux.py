"""Tests for candid CLI UX (help, typo tolerance, --json, friendly errors)
and the new dashboard endpoints (curate, dismiss, tailor-diff) + HTML/API
cross-check.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_dashboard.py).
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 - Present",
                    "bullets": ["Built churn models with XGBoost."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
    "source_files": ["resume.pdf"],
}

JD = ("About the role: Senior Data Scientist in New York.\n"
      "\n"
      "Must have:\n"
      "- Python, machine learning, SQL and statistics experience.\n"
      "\n"
      "Nice to have:\n"
      "- deep learning and experimentation with large datasets.\n")


class CLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-cliux-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv, stdin=""):
        """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin:
            sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    CLI.main(argv)
                except SystemExit as e:
                    code = e.code
                    return (code if isinstance(code, int) else 1,
                            out.getvalue(), err.getvalue())
                return 0, out.getvalue(), err.getvalue()
        finally:
            sys.stdin = old_stdin


# ---------------------------------------------------------------------------
# CLI UX
# ---------------------------------------------------------------------------

class HelpTest(CLIBase):
    def test_top_level_help_lists_commands(self):
        code, out, _ = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        for cmd in CLI.COMMANDS:
            self.assertIn(cmd, out, f"command {cmd!r} missing from top-level help")

    def test_every_command_has_examples_epilog(self):
        for cmd in CLI.COMMANDS:
            code, out, _ = self.run_cli([cmd, "--help"])
            self.assertEqual(code, 0)
            self.assertIn("examples:", out,
                          f"`{cmd} --help` has no examples epilog")

    def test_every_subcommand_has_examples_epilog(self):
        for cmd, subs in CLI.SUBCOMMANDS.items():
            for s in subs:
                code, out, _ = self.run_cli([cmd, s, "--help"])
                self.assertEqual(code, 0, f"{cmd} {s} --help failed")
                self.assertIn("examples:", out,
                              f"`{cmd} {s} --help` has no examples epilog")

    def test_version(self):
        from candid import __version__
        code, out, _ = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)


class TypoTest(CLIBase):
    def test_unknown_command_suggests(self):
        with self.assertRaises(SystemExit) as ctx:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                CLI.main(["macth"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("did you mean", err.getvalue().lower())
        self.assertIn("match", err.getvalue())

    def test_unknown_subcommand_suggests(self):
        with self.assertRaises(SystemExit):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                CLI.main(["track", "lsit"])
        self.assertIn("list", err.getvalue())

    def test_no_traceback_on_parse_error(self):
        with self.assertRaises(SystemExit):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                CLI.main(["boguscmd"])
        self.assertNotIn("Traceback", err.getvalue())


class FriendlyErrorTest(CLIBase):
    def test_missing_jd_error_has_next_command(self):
        code, out, err = self.run_cli(["match"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("--jd -", err)  # points at the stdin escape hatch
        self.assertIn("Next:", err)

    def test_tracker_error_has_next_command(self):
        code, out, err = self.run_cli(["track", "update", "999",
                                       "--status", "applied"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Next:", err)
        self.assertIn("python -m candid track list", err)

    def test_jobs_error_mapped_not_traceback(self):
        # unknown curation source → JobsError → friendly, no traceback
        code, out, err = self.run_cli(
            ["jobs", "curate", "--role", "Data Scientist",
             "--sources", "nosuchsource"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("Next:", err)


class JsonFlagTest(CLIBase):
    def test_match_json(self):
        code, out, err = self.run_cli(
            ["match", "--jd", JD, "--company", "Acme", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIn("score", data)
        self.assertIn("breakdown", data)
        self.assertIn("verdict", data)

    def test_match_stdin_json(self):
        code, out, err = self.run_cli(
            ["match", "--jd", "-", "--json"], stdin=JD)
        self.assertEqual(code, 0, err)
        self.assertIn("score", json.loads(out))

    def test_track_list_json(self):
        from candid import tracker as T
        T.add("Acme", "Data Scientist", status="applied")
        code, out, err = self.run_cli(["track", "list", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["company"], "Acme")

    def test_track_list_default_view(self):
        from candid import tracker as T
        T.add("Acme", "Data Scientist")
        code, out, err = self.run_cli(["track", "list"])
        self.assertEqual(code, 0, err)
        self.assertIn("1 application(s) tracked", out)

    def test_jobs_list_json(self):
        from candid import tracker as T, jobs as J
        rec = T.add("Initech", "Data Analyst", status="saved")
        J._stash_job_meta(rec["id"], {"source_id": "src-1", "match_score": 82,
                                      "source": "arbeitnow",
                                      "source_url": "https://example.com/j/1"})
        code, out, err = self.run_cli(["jobs", "list", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["score"], 82)
        self.assertEqual(data[0]["url"], "https://example.com/j/1")

    def test_salary_lookup_json(self):
        from candid import salary as S
        parsed = S.ingest_posted_range(
            "Acme", "Data Scientist",
            "Pay range $150,000 - $200,000 per year. Python required.",
            location="New York")
        self.assertIsNotNone(parsed)
        code, out, err = self.run_cli(
            ["salary", "lookup", "--company", "Acme",
             "--title", "Data Scientist", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertGreaterEqual(data["n"], 1)
        self.assertIn("median", data)


# ---------------------------------------------------------------------------
# new dashboard endpoints
# ---------------------------------------------------------------------------

FAKE_CURATE_RESULT = {
    "fetched": 10, "candidates": 3,
    "added": [{"source_id": "src-9", "company": "Globex",
               "title": "Data Scientist", "location": "Remote",
               "url": "https://example.com/j/9", "source": "remoteok",
               "description": "Python and SQL.", "score": 78,
               "why": "test", "salary": None, "app_id": 99}],
    "skipped": 1, "errors": [],
}


class NewEndpointTest(CLIBase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), D.DashboardHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def _post(self, path, body=None):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())

    def _get_json(self, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.loads(r.read().decode())

    # -- /api/curate ----------------------------------------------------
    def test_run_curate_data_function(self):
        from candid import jobs as J
        with mock.patch.object(J, "curate",
                               return_value=FAKE_CURATE_RESULT) as m:
            res = D.run_curate("Data Scientist", location="Remote",
                               remote=True, limit=5)
        m.assert_called_once()
        self.assertIn("summary", res)
        self.assertEqual(len(res["added"]), 1)
        self.assertEqual(res["added"][0]["company"], "Globex")
        json.dumps(res)  # must be JSON-serializable

    def test_run_curate_requires_role(self):
        with self.assertRaises(D.DashboardError):
            D.run_curate("")

    def test_run_curate_maps_jobs_error(self):
        from candid import jobs as J
        with mock.patch.object(J, "curate",
                               side_effect=J.JobsError("Arbeitnow unreachable")):
            with self.assertRaises(D.DashboardError):
                D.run_curate("Data Scientist")

    def test_curate_endpoint_http(self):
        from candid import jobs as J
        with mock.patch.object(J, "curate", return_value=FAKE_CURATE_RESULT):
            status, res = self._post("/api/curate", {"role": "Data Scientist"})
        self.assertEqual(status, 200)
        self.assertIn("summary", res)
        self.assertEqual(len(res["added"]), 1)

    def test_curate_endpoint_jobs_error_is_400(self):
        from candid import jobs as J
        with mock.patch.object(J, "curate",
                               side_effect=J.JobsError("boom")):
            try:
                self._post("/api/curate", {"role": "Data Scientist"})
                self.fail("expected HTTPError")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 400)

    # -- /api/jobs/dismiss ----------------------------------------------
    def _seed_saved_job(self, source_id="src-1", company="Initech"):
        """A saved tracker record linked to a curated source_id."""
        from candid import tracker as T
        rec = T.add(company, "Data Analyst", status="saved")
        jobs_state = self.tmp / "jobs.json"
        seen = {}
        if jobs_state.exists():
            seen = json.loads(jobs_state.read_text()).get("seen", {})
        seen[source_id] = rec["id"]
        jobs_state.write_text(json.dumps({"seen": seen}))
        return rec

    def test_dismiss_flow(self):
        rec = self._seed_saved_job("src-1")
        self.assertEqual(len(D.curated_jobs()), 1)

        res = D.dismiss_job(source_id="src-1")
        self.assertTrue(res["dismissed"])
        self.assertEqual(len(D.curated_jobs()), 0)

        # sidecar persists across reads
        self.assertEqual(D.dismissed_ids()["source_ids"], {"src-1"})
        self.assertTrue((self.tmp / "dismissed_jobs.json").exists())

    def test_dismiss_by_app_id(self):
        rec = self._seed_saved_job("src-2")
        res = D.dismiss_job(app_id=rec["id"])
        self.assertTrue(res["dismissed"])
        self.assertEqual(res["source_id"], "src-2")
        self.assertEqual(len(D.curated_jobs()), 0)

    def test_dismiss_requires_identifier(self):
        with self.assertRaises(D.DashboardError):
            D.dismiss_job()

    def test_dismiss_endpoint_http(self):
        self._seed_saved_job("src-3")
        status, res = self._post("/api/jobs/dismiss", {"source_id": "src-3"})
        self.assertEqual(status, 200)
        self.assertTrue(res["dismissed"])
        status, jobs = self._get_json("/api/jobs")
        self.assertEqual(jobs, [])

    # -- /api/tailor-diff ------------------------------------------------
    def test_tailor_diff_shape(self):
        res = D.run_tailor_diff("resume", "Acme", "Data Scientist", JD)
        self.assertIn("text", res)
        self.assertIn("coverage", res)
        self.assertIn("changes", res)
        self.assertIsInstance(res["changes"], list)
        cov = res["coverage"]
        self.assertIn("covered", cov)
        self.assertIn("missing", cov)
        # profile has python/sql → covered; deep learning → missing
        self.assertIn("python", cov["covered"])
        self.assertIn("deep learning", cov["missing"])
        self.assertTrue(len(res["text"]) > 100)
        json.dumps(res)

    def test_tailor_diff_cover_letter(self):
        res = D.run_tailor_diff("cover-letter", "Acme", "Data Scientist", JD)
        self.assertIn("Acme", res["text"])

    def test_tailor_diff_bad_kind(self):
        with self.assertRaises(D.DashboardError):
            D.run_tailor_diff("haiku", "Acme", "DS", JD)

    def test_tailor_diff_endpoint_http(self):
        status, res = self._post("/api/tailor-diff",
                                 {"kind": "resume", "company": "Acme",
                                  "role": "Data Scientist", "jd": JD})
        self.assertEqual(status, 200)
        self.assertIn("coverage", res)
        self.assertIn("text", res)


# ---------------------------------------------------------------------------
# HTML ↔ API cross-check
# ---------------------------------------------------------------------------

# every /api/... route the dashboard serves (mirrors dashboard.py)
ROUTES = [
    "/api/overview", "/api/apps", "/api/jobs", "/api/prep-status",
    "/api/nudges", "/api/salary", "/api/proposals", "/api/import-guides",
    "/api/warm",
    "/api/apps/<id>", "/api/prep", "/api/match", "/api/tailor",
    "/api/proposals/<id>/confirm", "/api/proposals/<id>/reject",
    "/api/import", "/api/curate", "/api/jobs/dismiss", "/api/tailor-diff",
]


def _route_regex(route: str) -> str:
    return "^" + re.escape(route).replace(r"\<id\>", r"\d+") + "$"


class HtmlApiTest(unittest.TestCase):
    def test_html_exists(self):
        html = ROOT / "candid" / "data" / "dashboard.html"
        self.assertTrue(html.exists())
        self.assertGreater(html.stat().st_size, 5000)

    def test_every_api_call_has_a_handler(self):
        html = (ROOT / "candid" / "data" / "dashboard.html").read_text()
        tokens = re.findall(r'["\'](/api/[^"\']*)', html)
        self.assertTrue(tokens, "no /api/ references found in the HTML")
        patterns = [_route_regex(r) for r in ROUTES]
        for tok in sorted(set(tokens)):
            norm = tok.split("?")[0]  # drop query strings
            norm = re.sub(r"\$\{[^}]*\}", "1", norm)  # template vars → id
            matched = any(re.fullmatch(p, norm) for p in patterns)
            self.assertTrue(matched,
                            f"{tok!r} called from dashboard.html has no "
                            f"handler route in dashboard.py")

    def test_html_has_no_cdn(self):
        html = (ROOT / "candid" / "data" / "dashboard.html").read_text()
        self.assertNotIn("https://cdn", html)
        self.assertNotIn("http://cdn", html)
        self.assertNotIn('src="http', html)

    def test_html_wires_new_endpoints(self):
        html = (ROOT / "candid" / "data" / "dashboard.html").read_text()
        for ep in ("/api/curate", "/api/jobs/dismiss", "/api/tailor-diff"):
            self.assertIn(ep, html, f"{ep} not wired in the HTML")


if __name__ == "__main__":
    unittest.main()
