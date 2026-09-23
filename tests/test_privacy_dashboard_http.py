"""HTTP tests for the dashboard privacy integration (/privacy routes + tab)."""

import json
import os
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("CANDID_CONFIG_DIR", "/tmp/candid-test-privdashhttp-config")

from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import privacy as P  # noqa: E402


class PrivacyHTTPBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-privhttp-"))
        self._saved = {}
        for name in ("DATA_DIR",):
            self._saved[name] = getattr(C, name)
        for name in ("AUDIT_LOG_PATH", "PRIVACY_EXPORT_DIR"):
            self._saved[f"P.{name}"] = getattr(P, name)
        C.DATA_DIR = self.tmp
        P.AUDIT_LOG_PATH = self.tmp / "privacy_audit.jsonl"
        P.PRIVACY_EXPORT_DIR = self.tmp / "privacy_exports"
        (self.tmp / "profile.json").write_text(
            json.dumps({"name": "T", "email": "t@example.com",
                        "phone": "+1-555-010-1234"}), encoding="utf-8")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), D.DashboardHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for name, val in self._saved.items():
            if name.startswith("P."):
                setattr(P, name[2:], val)
            else:
                setattr(C, name, val)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def _post_form(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(self._url(path), data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")


class PrivacyOverviewTest(PrivacyHTTPBase):
    def test_overview_data(self):
        data = D.privacy_overview_data()
        self.assertGreater(data["total_bytes"], 0)
        self.assertEqual(data["with_data"], 1)
        names = [r["name"] for r in data["categories"]]
        self.assertIn("profile", names)

    def test_index_contains_privacy_tab(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn('id="privacy"', body)

    def test_privacy_overview_page(self):
        status, body = self._get("/privacy")
        self.assertEqual(status, 200)
        self.assertIn("Privacy overview", body)
        self.assertIn("profile", body)


class PrivacyActionsTest(PrivacyHTTPBase):
    def test_scan_page_masks_pii(self):
        status, body = self._get("/privacy?action=scan")
        self.assertEqual(status, 200)
        self.assertIn("PII scan", body)
        self.assertNotIn("t@example.com", body)
        self.assertIn("t***@example.com", body)

    def test_egress_page(self):
        status, body = self._get("/privacy?action=egress")
        self.assertEqual(status, 200)
        self.assertIn("127.0.0.1", body)

    def test_audit_page_empty_then_logged(self):
        status, body = self._get("/privacy?action=audit")
        self.assertEqual(status, 200)
        self.assertIn("No privacy actions recorded yet", body)
        P.audit("test.action", "hello")
        status, body = self._get("/privacy?action=audit")
        self.assertIn("test.action", body)

    def test_retention_page(self):
        status, body = self._get("/privacy?action=retention")
        self.assertEqual(status, 200)
        self.assertIn("Retention policies", body)

    def test_export_action(self):
        status, body = self._get("/privacy?action=export&category=profile")
        self.assertEqual(status, 200)
        self.assertIn("Export complete", body)
        self.assertTrue(list((self.tmp / "privacy_exports").glob("profile-*.zip")))
        self.assertTrue((self.tmp / "profile.json").exists())

    def test_export_bad_category(self):
        status, body = self._get("/privacy?action=export&category=bogus")
        self.assertEqual(status, 400)

    def test_purge_get_shows_confirmation_only(self):
        status, body = self._get("/privacy?action=purge&category=profile")
        self.assertEqual(status, 200)
        self.assertIn("Confirm purge", body)
        self.assertIn("Delete permanently", body)
        self.assertTrue((self.tmp / "profile.json").exists())

    def test_purge_post_confirmed(self):
        status, body = self._post_form("/privacy", {
            "action": "purge", "category": "profile", "confirmed": "yes"})
        self.assertEqual(status, 200)
        self.assertIn("Purge complete", body)
        self.assertFalse((self.tmp / "profile.json").exists())
        entries = P.read_audit_log()
        self.assertTrue(any(e["action"] == "dashboard.purge" for e in entries))

    def test_purge_post_unconfirmed_does_nothing(self):
        status, body = self._post_form("/privacy", {
            "action": "purge", "category": "profile"})
        self.assertEqual(status, 400)
        self.assertTrue((self.tmp / "profile.json").exists())

    def test_nuke_get_shows_delete_form(self):
        status, body = self._get("/privacy?action=nuke")
        self.assertEqual(status, 200)
        self.assertIn("Confirm nuke", body)
        self.assertIn("DELETE", body)

    def test_nuke_post_wrong_text_does_nothing(self):
        status, body = self._post_form("/privacy", {
            "action": "nuke", "confirm_text": "delete"})
        self.assertEqual(status, 400)
        self.assertTrue((self.tmp / "profile.json").exists())

    def test_nuke_post_delete_wipes(self):
        (self.tmp / "privacy_exports").mkdir(exist_ok=True)
        (self.tmp / "privacy_exports" / "keep.zip").write_bytes(b"x")
        status, body = self._post_form("/privacy", {
            "action": "nuke", "confirm_text": "DELETE"})
        self.assertEqual(status, 200)
        self.assertIn("Nuke complete", body)
        self.assertFalse((self.tmp / "profile.json").exists())
        self.assertTrue((self.tmp / "privacy_exports" / "keep.zip").exists())
        entries = P.read_audit_log()
        self.assertTrue(any(e["action"] == "nuke" for e in entries))
