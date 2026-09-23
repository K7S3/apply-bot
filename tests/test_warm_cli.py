"""Tests for `candid warm` (warm-intro job ranking CLI).

Runs the CLI in-process via candid.__main__.main (same approach as
tests/test_cli_ux.py), with all data paths redirected into a temp dir.
Seeds: a LinkedIn export zip fixture, tracker saved jobs with stashed
match scores, and a minimal profile.
"""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402

EXPORT_ROWS = [
    # first, last, company, position, connected_on
    ("Ada", "Lovelace", "Acme Corp", "Senior Software Engineer", "15 Jan 2022"),
    ("Grace", "Hopper", "Acme Corp", "Engineering Manager", "03 Mar 2021"),
    ("Alan", "Turing", "Beta Inc", "Technical Recruiter", "20 Jun 2023"),
    ("No", "Company", "", "Student", "01 Feb 2024"),  # no company: skipped by queue
]


def _make_export_zip(path: Path) -> Path:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["First Name", "Last Name", "URL", "Email Address",
                "Company", "Position", "Connected On"])
    for first, last, co, pos, on in EXPORT_ROWS:
        w.writerow([first, last, f"https://www.linkedin.com/in/{first.lower()}",
                    "", co, pos, on])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Connections.csv", buf.getvalue())
    return path


class WarmCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-warm-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "DATA_DIR", "WARM_PATH"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.DATA_DIR = self.tmp
        C.WARM_PATH = self.tmp / "warm.json"
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps({"name": "Alex Rivera"}))

        from candid import tracker as T
        self.app_acme = T.add("Acme Corp", "Senior ML Engineer", status="saved")
        self.app_beta = T.add("Beta Inc", "Data Scientist", status="saved")
        self.app_gamma = T.add("Gamma LLC", "Backend Engineer", status="saved")
        # stashed curation match scores (what jobs.get_job_meta returns)
        (self.tmp / "job_meta.json").write_text(json.dumps({
            str(self.app_acme["id"]): {"match_score": 90,
                                       "source_url": "https://example.com/acme"},
            str(self.app_beta["id"]): {"match_score": 60,
                                       "source_url": "https://example.com/beta"},
            str(self.app_gamma["id"]): {"match_score": 95,
                                        "source_url": "https://example.com/gamma"},
        }))

        self.export_zip = _make_export_zip(self.tmp / "connections.zip")

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
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
            pass


class WarmRankTest(WarmCLIBase):
    def test_rank_ordering(self):
        code, out, err = self.run_cli(
            ["warm", "rank", "--export", str(self.export_zip)])
        self.assertEqual(code, 0, err)
        # Acme: strongest network (eng manager + senior eng, match 90)
        # Beta: one recruiter, match 60. Gamma: match 95 but no connections.
        ia, ib, ig = out.index("Acme Corp"), out.index("Beta Inc"), out.index("Gamma LLC")
        self.assertLess(ia, ib)
        self.assertLess(ib, ig)

    def test_rank_top_connection_is_warmest(self):
        code, out, _ = self.run_cli(
            ["warm", "rank", "--export", str(self.export_zip)])
        self.assertEqual(code, 0)
        acme_line = next(l for l in out.splitlines() if "Acme Corp" in l)
        self.assertIn("Grace Hopper", acme_line)  # manager outranks senior eng

    def test_rank_limit(self):
        code, out, _ = self.run_cli(
            ["warm", "rank", "--export", str(self.export_zip), "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Acme Corp", out)
        self.assertNotIn("Beta Inc", out)

    def test_rank_json(self):
        code, out, err = self.run_cli(
            ["warm", "rank", "--export", str(self.export_zip), "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(len(data), 3)
        scores = [r["warm_score"] for r in data]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for r in data:
            for key in ("job", "company", "connections", "strength",
                        "paths", "match", "warm_score"):
                self.assertIn(key, r)
        self.assertEqual(data[0]["company"], "Acme Corp")
        self.assertEqual(data[0]["match"], 90)

    def test_rank_csv_and_md(self):
        csv_path = self.tmp / "ranking.csv"
        md_path = self.tmp / "ranking.md"
        code, out, err = self.run_cli(
            ["warm", "rank", "--export", str(self.export_zip),
             "--csv", str(csv_path), "--md", str(md_path)])
        self.assertEqual(code, 0, err)
        rows = list(csv.reader(csv_path.read_text().splitlines()))
        self.assertEqual(rows[0], ["rank", "company", "title", "warm_score",
                                   "strength", "match", "top_connection",
                                   "n_connections", "url"])
        self.assertEqual(len(rows), 4)  # header + 3 jobs
        self.assertEqual(rows[1][1], "Acme Corp")
        md = md_path.read_text()
        self.assertIn("| Rank | Company | Title | Warm |", md)
        self.assertIn("Acme Corp", md)

    def test_rank_no_saved_jobs(self):
        C.TRACKER_PATH.write_text("[]")
        (self.tmp / "job_meta.json").write_text("{}")
        code, out, err = self.run_cli(["warm", "rank"])
        self.assertNotEqual(code, 0)
        self.assertIn("No saved jobs", err)

    def test_rank_bad_export_is_friendly_error(self):
        code, out, err = self.run_cli(
            ["warm", "rank", "--export", "/nonexistent/export.zip"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("python -m candid warm --help", err)

    def test_rank_without_export_still_works(self):
        code, out, err = self.run_cli(["warm", "rank"])
        self.assertEqual(code, 0, err)
        # Gamma (match 95, no connections) now outranks Acme (match 90, no conns)
        self.assertLess(out.index("Gamma LLC"), out.index("Acme Corp"))


class WarmQueueTest(WarmCLIBase):
    def test_queue_dedup_per_company_and_strength_order(self):
        code, out, err = self.run_cli(
            ["warm", "queue", "--export", str(self.export_zip)])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("Acme Corp"), 1)  # one row, not two
        self.assertIn("Beta Inc", out)
        self.assertNotIn("No Company", out)  # blank-company connection skipped
        self.assertLess(out.index("Acme Corp"), out.index("Beta Inc"))

    def test_queue_shows_contact_role_connected_status_action(self):
        code, out, _ = self.run_cli(
            ["warm", "queue", "--export", str(self.export_zip)])
        acme_line = next(l for l in out.splitlines() if "Acme Corp" in l)
        self.assertIn("Grace Hopper", acme_line)      # best contact
        self.assertIn("Engineering Manager", acme_line)
        self.assertIn("2021-03-03", acme_line)        # connected-on
        self.assertIn("none", acme_line)              # intro status
        self.assertIn("Ask Grace for an intro", acme_line)

    def test_queue_reflects_recorded_status(self):
        self.run_cli(["warm", "status", "Acme Corp", "asked",
                      "--contact", "Grace Hopper"])
        code, out, _ = self.run_cli(
            ["warm", "queue", "--export", str(self.export_zip)])
        self.assertEqual(code, 0)
        acme_line = next(l for l in out.splitlines() if "Acme Corp" in l)
        self.assertIn("asked", acme_line)
        self.assertIn("Follow up with Grace on the intro request", acme_line)

    def test_queue_needs_export(self):
        code, out, err = self.run_cli(["warm", "queue"])
        self.assertNotEqual(code, 0)
        self.assertIn("--export", err)


class WarmMapTest(WarmCLIBase):
    def test_map_grouping(self):
        code, out, err = self.run_cli(
            ["warm", "map", "Acme Corp", "--export", str(self.export_zip)])
        self.assertEqual(code, 0, err)
        hiring = out[out.index("Hiring"):out.index("Recruiting")]
        self.assertIn("Grace Hopper", hiring)
        eng = out[out.index("Engineering"):out.index("Other")]
        self.assertIn("Ada Lovelace", eng)
        self.assertIn("Recruiting (0)", out)

    def test_map_recruiter_bucket(self):
        code, out, _ = self.run_cli(
            ["warm", "map", "Beta Inc", "--export", str(self.export_zip)])
        self.assertEqual(code, 0)
        rec = out[out.index("Recruiting"):]
        self.assertIn("Alan Turing", rec)

    def test_map_unknown_company_is_friendly_error(self):
        code, out, err = self.run_cli(
            ["warm", "map", "Nonexistent Co", "--export", str(self.export_zip)])
        self.assertEqual(code, 1)
        self.assertIn("No connections found", err)
        self.assertIn("python -m candid warm --help", err)


class WarmDraftTest(WarmCLIBase):
    def test_draft_defaults_to_warmest_connection_and_best_job(self):
        code, out, err = self.run_cli(
            ["warm", "draft", "Acme Corp", "--export", str(self.export_zip)])
        self.assertEqual(code, 0, err)
        self.assertIn("Hi Grace,", out)
        self.assertIn("Senior ML Engineer", out)
        self.assertIn("Acme Corp", out)
        self.assertIn("Alex Rivera", out)

    def test_draft_connection_flag(self):
        code, out, _ = self.run_cli(
            ["warm", "draft", "Acme Corp", "--export", str(self.export_zip),
             "--connection", "Ada Lovelace"])
        self.assertEqual(code, 0)
        self.assertIn("Hi Ada,", out)

    def test_draft_job_flag(self):
        code, out, _ = self.run_cli(
            ["warm", "draft", "Beta Inc", "--export", str(self.export_zip),
             "--job", "Data Scientist"])
        self.assertEqual(code, 0)
        self.assertIn("Data Scientist", out)
        self.assertIn("Hi Alan,", out)

    def test_draft_unknown_connection_is_friendly_error(self):
        code, out, err = self.run_cli(
            ["warm", "draft", "Acme Corp", "--export", str(self.export_zip),
             "--connection", "Nobody Here"])
        self.assertEqual(code, 1)
        self.assertIn("No connection named", err)


class WarmStatusTest(WarmCLIBase):
    def test_status_round_trip(self):
        from candid import warm as W
        code, out, err = self.run_cli(
            ["warm", "status", "Acme Corp", "asked", "--contact", "Grace Hopper"])
        self.assertEqual(code, 0, err)
        self.assertIn("asked", out)
        rec = W.get_status("Acme Corp")
        self.assertEqual(rec["status"], "asked")
        self.assertEqual(rec["contact"], "Grace Hopper")
        self.assertTrue(rec["asked_on"])

        # company name matching is case/whitespace-insensitive
        rec2 = W.get_status("  acme corp ")
        self.assertEqual(rec2["status"], "asked")

        # applied keeps the contact
        self.run_cli(["warm", "status", "Acme Corp", "applied"])
        self.assertEqual(W.get_status("Acme Corp")["contact"], "Grace Hopper")

        # none resets the outreach state; the contact is kept for reference
        self.run_cli(["warm", "status", "Acme Corp", "none"])
        rec3 = W.get_status("Acme Corp")
        self.assertEqual(rec3["status"], "none")
        self.assertFalse(rec3["asked_on"])
        self.assertEqual(rec3["contact"], "Grace Hopper")

    def test_status_default_is_none(self):
        from candid import warm as W
        self.assertEqual(W.get_status("Unknown Co")["status"], "none")

    def test_status_bad_choice_rejected_by_argparse(self):
        code, out, err = self.run_cli(["warm", "status", "Acme", "maybe"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)


class WarmEngineContractTest(unittest.TestCase):
    """Direct contract checks against candid.warm (engine owned by worker A)."""

    def test_norm_company(self):
        from candid import warm as W
        self.assertEqual(W._norm_company("Acme Inc."), W._norm_company("ACME LLC"))
        self.assertEqual(W._norm_company("  Beta  "), "beta")

    def test_rank_jobs_without_match_scores(self):
        from candid import warm as W
        conns = [
            {"first_name": "A", "last_name": "B", "full_name": "A B",
             "company": "Acme Inc", "position": "Engineer",
             "connected_on": None, "degree": 1},
        ]
        jobs = [{"title": "Eng", "company": "ACME"},
                {"title": "Other", "company": "Elsewhere"}]
        ranked = W.rank_jobs(jobs, conns)
        self.assertEqual(ranked[0]["company"], "ACME")
        self.assertIsNone(ranked[0]["match"])
        self.assertEqual(ranked[0]["warm_score"], ranked[0]["strength"])
        self.assertEqual(len(ranked[0]["paths"]), 1)


if __name__ == "__main__":
    unittest.main()
