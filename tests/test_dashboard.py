"""Tests for the candid local web dashboard + nudges.

The HTTP layer is exercised against a real local server bound to 127.0.0.1
on an ephemeral port; all data paths are redirected into a temp dir.
"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import nudges as N  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 – Present",
                    "bullets": ["Built churn models with XGBoost."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
    "source_files": ["resume.pdf"],
}


class DashBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-dash-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
            setattr(C, name, self.tmp / name.lower().replace("_path", "")
                    .replace("_dir", "").replace("_db", ".db"))
        # fix up filenames for dirs vs files
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        self._seed()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def _seed(self):
        from candid import tracker as T
        T.add("Acme", "Senior Data Scientist", status="selected_for_interview",
              path=C.TRACKER_PATH)
        T.add("Hooli", "ML Engineer", status="applied", path=C.TRACKER_PATH)
        T.add("Initech", "Data Analyst", status="saved", path=C.TRACKER_PATH)
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))


# ---------------------------------------------------------------------------
# data functions
# ---------------------------------------------------------------------------

class DataTest(DashBase):
    def test_overview(self):
        ov = D.overview()
        self.assertEqual(ov["funnel"]["selected_for_interview"], 1)
        self.assertEqual(ov["funnel"]["applied"], 1)
        self.assertEqual(ov["funnel"]["saved"], 1)
        self.assertEqual(ov["total"], 3)
        self.assertIn("response_rate", ov)

    def test_list_apps_filtered(self):
        self.assertEqual(len(D.list_apps_filtered(status="applied")), 1)
        self.assertEqual(len(D.list_apps_filtered(query="acme")), 1)
        self.assertEqual(len(D.list_apps_filtered()), 3)
        self.assertEqual(len(D.list_apps_filtered(status="nope")), 0)

    def test_update_status(self):
        rec = D.update_status(1, "offer")
        self.assertEqual(rec["status"], "offer")
        with self.assertRaises(D.DashboardError):
            D.update_status(1, "bogus_status")

    def test_curated_jobs_structure(self):
        jobs = D.curated_jobs()
        self.assertIsInstance(jobs, list)
        self.assertEqual(len(jobs), 1)  # the "saved" app
        self.assertEqual(jobs[0]["company"], "Initech")
        self.assertIn("score", jobs[0])

    def test_prep_status(self):
        st = D.prep_status()
        self.assertEqual(len(st), 1)  # interview-stage app
        self.assertFalse(st[0]["has_pack"])
        # after generating a pack, has_pack flips
        D.run_prep("Acme", "Senior Data Scientist", app_id=1)
        st2 = D.prep_status()
        self.assertTrue(st2[0]["has_pack"])

    def test_run_match(self):
        res = D.run_match(
            "We are hiring a Senior Data Scientist with Python, machine "
            "learning and statistics experience in New York.")
        self.assertIn("score", res)
        self.assertIn("verdict", res)
        self.assertGreaterEqual(res["score"], 40)

    def test_run_tailor_writes_files(self):
        res = D.run_tailor("resume", "Acme", "Senior Data Scientist",
                           "Python and machine learning required.")
        self.assertTrue(Path(res["path"]).exists())
        res2 = D.run_tailor("cover-letter", "Acme", "Senior Data Scientist",
                            "Python and machine learning required.")
        self.assertTrue(Path(res2["path"]).exists())

    def test_salary_lookup_empty_db(self):
        res = D.salary_lookup("Nope Corp", "Unicorn Wrangler")
        self.assertIn(res["n"], (0,))

    def test_proposals_empty(self):
        self.assertEqual(D.proposal_list(), [])


# ---------------------------------------------------------------------------
# nudges
# ---------------------------------------------------------------------------

class NudgeTest(unittest.TestCase):
    def test_interview_follow_up(self):
        apps = [{"id": 1, "company": "Acme", "role": "DS",
                 "status": "selected_for_interview",
                 "date_updated": "2026-09-01"}]
        ns = N.pending_nudges(apps, today=date(2026, 9, 22))
        self.assertTrue(any(n["kind"] == "follow_up_due" for n in ns))

    def test_quiet_application(self):
        apps = [{"id": 1, "company": "Acme", "role": "DS",
                 "status": "applied",
                 "date_updated": "2026-09-01"}]
        ns = N.pending_nudges(apps, today=date(2026, 9, 22))
        self.assertTrue(any(n["kind"] == "quiet_applied" for n in ns))

    def test_stale_saved(self):
        apps = [{"id": 1, "company": "Initech", "role": "DA",
                 "status": "saved",
                 "date_updated": "2026-09-01"}]
        ns = N.pending_nudges(apps, today=date(2026, 9, 22))
        self.assertTrue(any(n["kind"] == "stale_saved" for n in ns))

    def test_recent_is_quiet(self):
        apps = [{"id": 1, "company": "Acme", "role": "DS",
                 "status": "applied",
                 "date_updated": "2026-09-21"}]
        ns = N.pending_nudges(apps, today=date(2026, 9, 22))
        self.assertEqual(ns, [])


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------

class HTTPTest(DashBase):
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

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def _get_json(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.loads(r.read().decode())

    def _post(self, path, body=None):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())

    def test_root_serves_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"candid", body)
        self.assertIn(b"api/overview", body)

    def test_overview_api(self):
        status, res = self._get_json("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(res["total"], 3)
        self.assertIn("gmail", res)

    def test_apps_api_filter(self):
        status, res = self._get_json("/api/apps?status=applied")
        self.assertEqual(status, 200)
        self.assertEqual(len(res), 1)
        status, res = self._get_json("/api/apps?status=bogus")
        self.assertEqual(res, [])

    def test_update_status_api(self):
        status, res = self._post("/api/apps/1", {"status": "offer"})
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "offer")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/apps/999", {"status": "applied"})
        self.assertEqual(ctx.exception.code, 404)

    def test_nudges_and_prep_status(self):
        status, res = self._get_json("/api/nudges")
        self.assertEqual(status, 200)
        self.assertIsInstance(res, list)
        status, res = self._get_json("/api/prep-status")
        self.assertEqual(status, 200)
        self.assertEqual(len(res), 1)

    def test_proposals_roundtrip(self):
        from candid import gmail as G
        G._save_proposals([{"id": 1, "company": "Acme", "role": "DS",
                            "kind": "interview_invite", "confidence": 0.9,
                            "status": "pending", "subject": "s",
                            "from": "f", "date": "d",
                            "tracker_status": "selected_for_interview"}],
                          path=C.GMAIL_PROPOSALS_PATH)
        status, res = self._get_json("/api/proposals?status=pending")
        self.assertEqual(len(res), 1)
        status, res = self._post("/api/proposals/1/confirm")
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "selected_for_interview")

    def test_match_api(self):
        status, res = self._post("/api/match", {"jd": "Senior Data Scientist "
                                                        "with Python and SQL"})
        self.assertEqual(status, 200)
        self.assertIn("score", res)

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)


# ---------------------------------------------------------------------------
# /api/import (JSON path + multipart upload) and /api/import-guides
# ---------------------------------------------------------------------------

class ImportAPITest(DashBase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), D.DashboardHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        # tiny fixture mbox
        self.mbox = self.tmp / "mail.mbox"
        self.mbox.write_text(
            "From Acme Recruiting <recruiting@acme.com> Mon, 21 Sep 2026 10:00:00 -0400\n"
            "From: Acme Recruiting <recruiting@acme.com>\n"
            "Subject: Interview Invitation: Senior Data Scientist\n"
            "Message-ID: <dash-m1@example.com>\n"
            "Date: Mon, 21 Sep 2026 10:00:00 -0400\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\nWe'd like to schedule a phone screen.\n\n",
            encoding="utf-8")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def _post_json(self, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())

    def _post_upload(self, filename, data_bytes):
        boundary = "----candidtestboundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + data_bytes + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/import", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())

    def test_detect_source(self):
        self.assertEqual(D.detect_source("mail.mbox"), "gmail")
        self.assertEqual(D.detect_source("export.ZIP"), "linkedin")
        self.assertIsNone(D.detect_source("notes.txt"))

    def test_import_guides_endpoint(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/import-guides") as r:
            g = json.loads(r.read().decode())
        self.assertIn("takeout.google.com", "\n".join(g["gmail"]["steps"]))
        self.assertIn("Get a copy of your data", "\n".join(g["linkedin"]["steps"]))
        self.assertIn("pattern", g)

    def test_run_import_gmail(self):
        res = D.run_import("gmail", self.mbox)
        self.assertEqual(res["source"], "gmail")
        self.assertEqual(res["new_proposals"], 1)
        self.assertIn("summary", res)

    def test_run_import_bad_source(self):
        with self.assertRaises(D.DashboardError):
            D.run_import("twitter", self.mbox)

    def test_import_json_path(self):
        status, res = self._post_json(
            "/api/import", {"source": "gmail", "path": str(self.mbox)})
        self.assertEqual(status, 200)
        self.assertEqual(res["new_proposals"], 1)
        # re-import dedupes
        status, res = self._post_json(
            "/api/import", {"source": "gmail", "path": str(self.mbox)})
        self.assertEqual(res["new_proposals"], 0)

    def test_import_upload_mbox(self):
        status, res = self._post_upload("mail.mbox", self.mbox.read_bytes())
        self.assertEqual(status, 200)
        self.assertEqual(res["filename"], "mail.mbox")
        self.assertEqual(res["new_proposals"], 1)

    def test_import_upload_unknown_extension(self):
        try:
            self._post_upload("notes.txt", b"hello")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


if __name__ == "__main__":
    unittest.main()
