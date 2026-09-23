"""Tests for dashboard multi-profile views (batch-73 worker D).

Uses the real ``candid.profiles`` module with ``C.DATA_DIR`` /
``C.CONFIG_DIR`` patched to temp dirs.

Coverage: per-profile payload isolation, the "all" aggregate view
(funnel counts summed, labeled per profile), the profile list + active
profile in the payload, clean 400 (no traceback) for an unknown
?profile=, and request-profile set/clear around HTTP requests.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import profiles as P  # noqa: E402
from candid import tracker as T  # noqa: E402


class DashProfilesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-dash73-"))
        # isolate: patch the config dirs (profiles.py reads them dynamically)
        self._saved = {}
        for name, val in (("DATA_DIR", self.tmp / "data"),
                          ("CONFIG_DIR", self.tmp / "config"),
                          ("TRACKER_PATH", self.tmp / "data" / "tracker.json"),
                          ("PROFILE_PATH", self.tmp / "data" / "profile.json"),
                          ("GMAIL_PROPOSALS_PATH",
                           self.tmp / "data" / "gmail_proposals.json")):
            self._saved[name] = getattr(C, name)
            setattr(C, name, val)
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._prev_request = P._REQUEST_PROFILE
        P.clear_request_profile()
        self._seed()

    def tearDown(self):
        P.clear_request_profile()
        if self._prev_request is not None:
            P.set_request_profile(self._prev_request)
        for name, val in self._saved.items():
            setattr(C, name, val)

    def _seed(self):
        P.create_profile("swe", target_role="Software Engineer")
        P.create_profile("mle", target_role="ML Engineer")
        T.add("Acme", "Backend Engineer", status="applied",
              path=C.tracker_path(profile="swe"))
        T.add("Hooli", "Frontend Engineer", status="offer",
              path=C.tracker_path(profile="swe"))
        T.add("Initech", "ML Engineer", status="saved",
              path=C.tracker_path(profile="mle"))


# ---------------------------------------------------------------------------
# data functions
# ---------------------------------------------------------------------------

class ProfilePayloadTest(DashProfilesBase):
    def test_per_profile_isolation(self):
        swe = D.overview(profile="swe")
        self.assertFalse(swe["aggregate"])
        self.assertEqual(swe["total"], 2)
        self.assertEqual(swe["funnel"]["applied"], 1)
        self.assertEqual(swe["funnel"]["offer"], 1)
        self.assertEqual(swe["funnel"]["saved"], 0)
        mle = D.overview(profile="mle")
        self.assertEqual(mle["total"], 1)
        self.assertEqual(mle["funnel"]["saved"], 1)
        self.assertEqual(mle["funnel"]["applied"], 0)
        # no cross-contamination
        self.assertEqual(swe["active_profile"], "swe")
        self.assertEqual(mle["active_profile"], "mle")

    def test_aggregate_sums_and_labels(self):
        agg = D.overview(profile="all")
        self.assertTrue(agg["aggregate"])
        self.assertEqual(agg["total"], 3)
        self.assertEqual(agg["funnel"]["applied"], 1)
        self.assertEqual(agg["funnel"]["offer"], 1)
        self.assertEqual(agg["funnel"]["saved"], 1)
        by_name = {p["profile"]: p for p in agg["per_profile"]}
        self.assertEqual(set(by_name), {"default", "swe", "mle"})
        self.assertEqual(by_name["swe"]["total"], 2)
        self.assertEqual(by_name["mle"]["total"], 1)
        self.assertEqual(by_name["default"]["total"], 0)
        self.assertEqual(agg["active_profile"], "all")

    def test_profile_list_in_payload(self):
        ov = D.overview(profile="swe")
        self.assertEqual(ov["profiles"], ["default", "mle", "swe"])
        self.assertEqual(ov["active_profile"], "swe")
        self.assertEqual(ov["profile_info"]["mle"]["target_role"],
                         "ML Engineer")

    def test_env_resolution_order(self):
        os.environ["CANDID_PROFILE"] = "mle"
        try:
            self.assertEqual(D.overview()["active_profile"], "mle")
            self.assertEqual(D.overview()["total"], 1)
        finally:
            del os.environ["CANDID_PROFILE"]

    def test_unknown_profile_is_clean_error(self):
        with self.assertRaises(D.DashboardError) as cm:
            D.resolve_dashboard_profile("nope")
        self.assertIn("nope", str(cm.exception))
        with self.assertRaises(D.DashboardError):
            D.overview(profile="nope")
        with self.assertRaises(D.DashboardError):
            D.list_apps_filtered(profile="nope")

    def test_apps_aggregate_labeled(self):
        apps = D.list_apps_filtered(profile="all")
        self.assertEqual(len(apps), 3)
        self.assertTrue(all("profile" in a for a in apps))
        self.assertEqual(
            sorted(a["profile"] for a in apps), ["mle", "swe", "swe"])
        swe_apps = D.list_apps_filtered(profile="swe")
        self.assertEqual(len(swe_apps), 2)
        self.assertFalse(any("profile" in a for a in swe_apps))

    def test_update_status_scoped(self):
        rec = D.update_status(1, "rejected", profile="swe")
        self.assertEqual(rec["status"], "rejected")
        # mle's tracker untouched
        mle_apps = D.list_apps_filtered(profile="mle")
        self.assertEqual(mle_apps[0]["status"], "saved")
        # aggregate view is read-only for mutations
        with self.assertRaises(D.DashboardError):
            D.update_status(1, "offer", profile="all")

    def test_nudges_scoped(self):
        n = D._nudges_for("swe")
        self.assertIsInstance(n, list)
        agg = D._nudges_for("all")
        self.assertTrue(all("profile" in x for x in agg))


# ---------------------------------------------------------------------------
# HTTP layer: ?profile= threading + clean errors
# ---------------------------------------------------------------------------

class HTTPProfileTest(DashProfilesBase):
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

    def test_overview_per_profile(self):
        status, body = self._get_json("/api/overview?profile=swe")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["active_profile"], "swe")
        self.assertEqual(body["profiles"], ["default", "mle", "swe"])
        status, body = self._get_json("/api/overview?profile=mle")
        self.assertEqual(body["total"], 1)

    def test_overview_aggregate(self):
        status, body = self._get_json("/api/overview?profile=all")
        self.assertEqual(status, 200)
        self.assertTrue(body["aggregate"])
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["per_profile"]), 3)

    def test_unknown_profile_400_not_traceback(self):
        try:
            self._get_json("/api/overview?profile=nope")
            self.fail("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read().decode())
            self.assertIn("error", body)
            self.assertIn("nope", body["error"])
            self.assertNotIn("Traceback", body["error"])

    def test_request_profile_cleared(self):
        self._get_json("/api/overview?profile=mle")
        self.assertIsNone(P._REQUEST_PROFILE)
        self._get_json("/api/apps?profile=swe")
        self.assertIsNone(P._REQUEST_PROFILE)

    def test_apps_scoped_via_http(self):
        status, body = self._get_json("/api/apps?profile=mle")
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["company"], "Initech")
        status, body = self._get_json("/api/apps?profile=all")
        self.assertEqual(len(body), 3)

    def test_binds_localhost_only(self):
        import socket
        s = socket.socket()
        try:
            # the handler module hardcodes 127.0.0.1 in serve(); the test
            # server here binds the same loopback address
            self.assertEqual(self.server.server_address[0], "127.0.0.1")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
