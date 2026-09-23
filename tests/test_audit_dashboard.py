"""Tests for the dashboard's read-only audit-trail endpoints.

The real ``candid.audit`` log is exercised; all data paths are redirected
via CANDID_DATA_DIR so the user's real log is never touched.
"""
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-audit-dash"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import audit as A  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import tracker as T  # noqa: E402


class AuditDashBase(unittest.TestCase):
    def setUp(self):
        # Fresh data dir per test: drop the audit log, its meta sidecar,
        # and the tracker so seeds never leak between tests.
        d = Path(C.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        for name in ("audit.log", "audit.meta.json", "tracker.json"):
            p = d / name
            if p.exists():
                p.unlink()
        self._seed()

    def _seed(self):
        # Real tracker ops (default path) write real audit entries.
        T.add("Acme", "Senior Data Scientist", status="applied")
        T.update(1, status="selected_for_interview")
        T.add("Hooli", "ML Engineer", status="saved")
        A.record(actor="cli", command="track remove", entity="tracker",
                 entity_id="99", action="remove",
                 before={"id": 99, "company": "Initech"},
                 after=None, note="manual removal")


# ---------------------------------------------------------------------------
# data functions (no HTTP)
# ---------------------------------------------------------------------------

class AuditDataTest(AuditDashBase):
    def test_entries_newest_first(self):
        entries = D.audit_entries()
        self.assertGreaterEqual(len(entries), 4)
        seqs = [e["seq"] for e in entries]
        self.assertEqual(seqs, sorted(seqs, reverse=True))

    def test_entry_shape(self):
        entry = D.audit_entries(limit=1)[0]
        for key in ("seq", "id", "ts", "actor", "command", "entity",
                    "entity_id", "action", "prev_hash", "hash"):
            self.assertIn(key, entry)

    def test_limit_param(self):
        self.assertEqual(len(D.audit_entries(limit=2)), 2)
        self.assertEqual(D.audit_entries(limit=1000),
                         D.audit_entries())

    def test_entity_filter(self):
        entries = D.audit_entries(entity="tracker")
        self.assertTrue(entries)
        self.assertTrue(all(e["entity"] == "tracker" for e in entries))
        self.assertEqual(D.audit_entries(entity="nonexistent"), [])

    def test_action_filter(self):
        entries = D.audit_entries(action="create")
        self.assertTrue(entries)
        self.assertTrue(all(e["action"] == "create" for e in entries))
        # tracker.update recorded an "update" entry
        upd = D.audit_entries(action="update")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["command"], "track update")

    def test_search_query(self):
        res = D.audit_entries(query="Acme")
        self.assertTrue(res)
        blob = json.dumps(res).lower()
        self.assertIn("acme", blob)
        self.assertEqual(D.audit_entries(query="zz-no-such-string"), [])

    def test_verify_ok(self):
        res = D.audit_verify()
        self.assertEqual(res, {"ok": True, "problems": []})

    def test_verify_detects_tampering(self):
        with open(C.AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write("this is not valid json\n")
        res = D.audit_verify()
        self.assertFalse(res["ok"])
        self.assertTrue(res["problems"])
        self.assertTrue(any("corrupt" in p for p in res["problems"]))


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------

class AuditHTTPTest(AuditDashBase):
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

    def _get_json(self, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.loads(r.read().decode())

    def _get(self, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def test_api_audit_http(self):
        status, res = self._get_json("/api/audit")
        self.assertEqual(status, 200)
        self.assertIsInstance(res, list)
        self.assertGreaterEqual(len(res), 4)

    def test_api_audit_http_filters(self):
        status, res = self._get_json("/api/audit?limit=2")
        self.assertEqual(status, 200)
        self.assertEqual(len(res), 2)
        status, res = self._get_json("/api/audit?action=update")
        self.assertEqual(status, 200)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["action"], "update")
        status, res = self._get_json("/api/audit?q=hooli")
        self.assertEqual(status, 200)
        self.assertTrue(res)
        self.assertIn("hooli", json.dumps(res).lower())

    def test_api_audit_verify_http(self):
        status, res = self._get_json("/api/audit/verify")
        self.assertEqual(status, 200)
        self.assertEqual(res, {"ok": True, "problems": []})

    def test_audit_page_served(self):
        status, body = self._get("/audit")
        self.assertEqual(status, 200)
        self.assertIn(b"Audit trail", body)
        self.assertIn(b"/api/audit", body)


if __name__ == "__main__":
    unittest.main()
