"""Tests for the dashboard watchlist panels (company career-page monitors).

Most tests inject fake monitor/alert modules into sys.modules — no network,
no real state. A final integration class exercises the real
candid/monitors.py + candid/alerts.py against a temp data dir.
"""

import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402


# ---------------------------------------------------------------------------
# fake modules
# ---------------------------------------------------------------------------

NATIVE_COMPANIES = [
    {"key": "acme", "name": "Acme", "sources": [
        {"type": "greenhouse",
         "url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
         "label": "acme"},
        {"type": "rss", "url": "https://acme.example/jobs.xml",
         "label": "https://acme.example/jobs.xml"}]},
    {"key": "initech", "name": "Initech", "sources": []},
]

NATIVE_HEALTH = {
    "acme:greenhouse:acme": {
        "company": "Acme", "type": "greenhouse", "label": "acme",
        "url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        "consecutive_failures": 0, "last_error": "",
        "last_ok": "2026-09-22", "status": "ok"},
    "acme:rss:https://acme.example/jobs.xml": {
        "company": "Acme", "type": "rss",
        "label": "https://acme.example/jobs.xml",
        "url": "https://acme.example/jobs.xml",
        "consecutive_failures": 6, "last_error": "timeout",
        "last_ok": "", "status": "failing"},
}

NATIVE_RUNS = {
    "companies": {
        "Acme": {"last_run": "2026-09-22T09:00:00", "new": 2,
                 "closed": 1, "open": 5},
    },
    "last_run": "2026-09-22T09:00:00",
}

NATIVE_HISTORY = {
    "gh-1": {"id": "gh-1", "title": "Senior Data Scientist",
             "location": "New York, NY", "url": "https://x/1",
             "first_seen": "2026-09-20", "last_seen": "2026-09-22",
             "status": "open", "closed_at": "", "repost": False},
    "gh-2": {"id": "gh-2", "title": "Data Analyst",
             "location": "Remote", "url": "https://x/2",
             "first_seen": "2026-09-18", "last_seen": "2026-09-22",
             "status": "open", "closed_at": "", "repost": True},
    "gh-3": {"id": "gh-3", "title": "Backend Engineer",
             "location": "NYC", "url": "https://x/3",
             "first_seen": "2026-09-10", "last_seen": "2026-09-15",
             "status": "closed", "closed_at": "2026-09-19",
             "repost": False},
}

NATIVE_PENDING = [
    {"id": 1, "kind": "new", "company": "Acme",
     "title": "Senior Data Scientist", "score": 88.0, "verdict": "GO",
     "url": "https://x/1",
     "message": "New posting: Senior Data Scientist @ Acme — match 88/100 (GO).",
     "created_at": "2026-09-22T10:00:00"},
    {"id": 2, "kind": "repost", "company": "Acme",
     "title": "Data Analyst", "score": 72.0, "verdict": "CONDITIONAL",
     "url": "https://x/2",
     "message": "Reposted: Data Analyst @ Acme is back on the board — match 72/100 (CONDITIONAL).",
     "created_at": "2026-09-22T10:05:00"},
]


def make_native_monitors():
    mod = types.ModuleType("candid.monitors")
    mod.list_companies = lambda: [dict(c) for c in NATIVE_COMPANIES]
    mod.health = lambda: {k: dict(v) for k, v in NATIVE_HEALTH.items()}

    def get_history(name):
        if name != "Acme":
            raise Exception(f"Unknown company {name!r}. Known: acme")
        return {k: dict(v) for k, v in NATIVE_HISTORY.items()}

    mod.get_history = get_history
    return mod


def make_native_alerts(pending=None, threshold=65.0):
    mod = types.ModuleType("candid.alerts")
    mod._pending = [dict(a) for a in (NATIVE_PENDING if pending is None else pending)]
    mod._marked = []

    def get_pending_alerts():
        return [dict(a) for a in mod._pending]

    def mark_read(alert_id):
        ids = [a["id"] for a in mod._pending]
        if alert_id not in ids:
            raise Exception(f"No alert with id {alert_id}.")
        mod._marked.append(alert_id)

    mod.get_pending_alerts = get_pending_alerts
    mod.mark_read = mark_read
    mod.get_threshold = lambda: threshold
    mod.load_runs = lambda: {k: (dict(v) if isinstance(v, dict) else v)
                             for k, v in NATIVE_RUNS.items()}
    return mod


def make_alias_monitors():
    """Old-style aliases only — the dashboard must probe and find these."""
    mod = types.ModuleType("candid.monitors")
    mod.companies = lambda: [
        {"company": "Acme", "source_type": "greenhouse", "source_key": "acme",
         "enabled": True, "last_run": "2026-09-22T09:00:00", "open_count": 5,
         "new_since_last": 2, "feed_health": "ok", "last_error": ""},
    ]
    mod.postings = lambda name: {
        "open": [{"title": "Senior Data Scientist", "url": "https://x/1",
                  "first_seen": "2026-09-20", "reposted": False}],
        "recently_closed": [{"title": "Old Role", "closed_at": "2026-09-19"}],
    }
    return mod


def make_alias_alerts():
    mod = types.ModuleType("candid.alerts")
    mod._marked = []
    mod.pending = lambda: [
        {"id": 7, "company": "Acme", "title": "ML Engineer",
         "url": "https://x/7", "first_seen": "2026-09-22", "read": False},
        {"id": 8, "company": "Acme", "title": "Read Already",
         "url": "https://x/8", "read": True},
    ]
    mod.ack = mod._marked.append
    return mod


class WatchBase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: sys.modules.get(k)
                       for k in ("candid.monitors", "candid.alerts")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def _absent(self):
        """Simulate missing modules even though the files exist on disk."""
        sys.modules["candid.monitors"] = None  # known-absent marker
        sys.modules["candid.alerts"] = None

    def _install(self, monitors=None, alerts=None):
        monitors = make_native_monitors() if monitors is None else monitors
        alerts = make_native_alerts() if alerts is None else alerts
        sys.modules["candid.monitors"] = monitors
        sys.modules["candid.alerts"] = alerts
        return monitors, alerts


# ---------------------------------------------------------------------------
# data functions — native API
# ---------------------------------------------------------------------------

class WatchDataTest(WatchBase):
    def test_absent_modules_degrade(self):
        self._absent()
        self.assertEqual(D.watch_status(), {"enabled": False, "companies": []})
        self.assertEqual(D.watch_alerts(), {"enabled": False, "alerts": []})
        self.assertFalse(D.watch_available())
        with self.assertRaises(D.DashboardError):
            D.watch_mark_read(1)
        with self.assertRaises(D.DashboardError):
            D.company_timeline("Acme")

    def test_native_watch_cards(self):
        self._install()
        st = D.watch_status()
        self.assertTrue(st["enabled"])
        self.assertTrue(D.watch_available())
        self.assertEqual(len(st["companies"]), 2)
        acme = st["companies"][0]
        self.assertEqual(acme["company"], "Acme")
        self.assertEqual(acme["source_type"], "greenhouse, rss")
        self.assertEqual(acme["source_key"], "acme")
        self.assertTrue(acme["enabled"])
        self.assertEqual(acme["open_count"], 5)       # from runs state
        self.assertEqual(acme["new_since_last"], 2)   # from runs state
        self.assertEqual(acme["last_run"], "2026-09-22T09:00:00")
        self.assertEqual(acme["feed_health"], "error")  # rss source failing
        self.assertEqual(acme["last_error"], "timeout")
        initech = st["companies"][1]
        self.assertEqual(initech["feed_health"], "not configured")
        self.assertEqual(initech["open_count"], 0)

    def test_native_open_count_falls_back_to_history(self):
        mon, _ = self._install()
        al = sys.modules["candid.alerts"]
        al.load_runs = lambda: {}  # no runs state
        st = D.watch_status()
        acme = st["companies"][0]
        self.assertEqual(acme["open_count"], 2)  # two open records in history
        self.assertEqual(al.load_runs(), {})

    def test_native_alerts_and_threshold(self):
        self._install()
        res = D.watch_alerts()
        self.assertTrue(res["enabled"])
        self.assertEqual(res["threshold"], 65.0)
        self.assertEqual(len(res["alerts"]), 2)
        a = res["alerts"][0]
        self.assertEqual(a["id"], 1)
        self.assertEqual(a["kind"], "new")
        self.assertEqual(a["title"], "Senior Data Scientist")
        self.assertEqual(a["url"], "https://x/1")
        self.assertEqual(a["score"], 88.0)
        self.assertEqual(a["verdict"], "GO")
        self.assertIn("match 88/100", a["message"])
        rep = res["alerts"][1]
        self.assertEqual(rep["kind"], "repost")

    def test_native_mark_read(self):
        _, al = self._install()
        res = D.watch_mark_read(1)
        self.assertEqual(res, {"ok": True, "id": 1})
        self.assertEqual(al._marked, [1])

    def test_native_mark_read_unknown_id_raises(self):
        self._install()
        with self.assertRaises(D.DashboardError) as ctx:
            D.watch_mark_read(99)
        self.assertIn("No alert", str(ctx.exception))

    def test_native_timeline(self):
        self._install()
        t = D.company_timeline("Acme")
        self.assertEqual(t["company"], "Acme")
        self.assertEqual(len(t["open"]), 2)
        # sorted by first_seen desc
        self.assertEqual(t["open"][0]["title"], "Senior Data Scientist")
        self.assertEqual(t["open"][0]["first_seen"], "2026-09-20")
        self.assertFalse(t["open"][0]["reposted"])
        self.assertTrue(t["open"][1]["reposted"])
        self.assertEqual(len(t["recently_closed"]), 1)
        self.assertEqual(t["recently_closed"][0]["title"], "Backend Engineer")
        self.assertEqual(t["recently_closed"][0]["closed_at"], "2026-09-19")

    def test_native_timeline_unknown_company(self):
        self._install()
        with self.assertRaises(D.DashboardError) as ctx:
            D.company_timeline("Nope")
        self.assertIn("Unknown company", str(ctx.exception))

    def test_timeline_missing_name(self):
        self._install()
        with self.assertRaises(D.DashboardError):
            D.company_timeline("")

    def test_broken_native_module_degrades(self):
        mod = types.ModuleType("candid.monitors")

        def _boom():
            raise RuntimeError("boom")

        mod.list_companies = _boom
        sys.modules["candid.monitors"] = mod
        st = D.watch_status()
        self.assertTrue(st["enabled"])  # module exists; read failed
        self.assertEqual(st["companies"], [])
        self.assertIn("error", st)


# ---------------------------------------------------------------------------
# data functions — alias fallbacks
# ---------------------------------------------------------------------------

class WatchAliasTest(WatchBase):
    def test_alias_watch_cards(self):
        self._install(monitors=make_alias_monitors(), alerts=make_alias_alerts())
        st = D.watch_status()
        self.assertTrue(st["enabled"])
        self.assertEqual(len(st["companies"]), 1)
        c = st["companies"][0]
        self.assertEqual(c["company"], "Acme")
        self.assertEqual(c["source_type"], "greenhouse")
        self.assertEqual(c["open_count"], 5)
        self.assertEqual(c["new_since_last"], 2)
        self.assertEqual(c["feed_health"], "ok")

    def test_alias_alerts_filter_unread(self):
        self._install(monitors=make_alias_monitors(), alerts=make_alias_alerts())
        res = D.watch_alerts()
        self.assertTrue(res["enabled"])
        self.assertEqual(len(res["alerts"]), 1)  # read one filtered out
        self.assertEqual(res["alerts"][0]["id"], 7)
        self.assertEqual(res["alerts"][0]["url"], "https://x/7")

    def test_alias_mark_read(self):
        _, al = self._install(monitors=make_alias_monitors(),
                              alerts=make_alias_alerts())
        self.assertEqual(D.watch_mark_read(7), {"ok": True, "id": 7})
        self.assertEqual(al._marked, [7])

    def test_alias_timeline_open_closed(self):
        self._install(monitors=make_alias_monitors(), alerts=make_alias_alerts())
        t = D.company_timeline("Acme")
        self.assertEqual(len(t["open"]), 1)
        self.assertEqual(t["open"][0]["title"], "Senior Data Scientist")
        self.assertEqual(t["open"][0]["first_seen"], "2026-09-20")
        self.assertEqual(len(t["recently_closed"]), 1)


# ---------------------------------------------------------------------------
# HTTP endpoints (real local server, 127.0.0.1)
# ---------------------------------------------------------------------------

class WatchHTTPTest(WatchBase):
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

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get_json(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def _post(self, path, body=None):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(self._url(path), data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_watch_api(self):
        self._install()
        status, res = self._get_json("/api/watch")
        self.assertEqual(status, 200)
        self.assertTrue(res["enabled"])
        self.assertEqual(len(res["companies"]), 2)
        acme = res["companies"][0]
        self.assertEqual(acme["company"], "Acme")
        self.assertEqual(acme["new_since_last"], 2)
        self.assertEqual(acme["feed_health"], "error")

    def test_watch_api_absent(self):
        self._absent()
        status, res = self._get_json("/api/watch")
        self.assertEqual(status, 200)
        self.assertFalse(res["enabled"])
        self.assertEqual(res["companies"], [])

    def test_alerts_api(self):
        self._install()
        status, res = self._get_json("/api/watch/alerts")
        self.assertEqual(status, 200)
        self.assertTrue(res["enabled"])
        self.assertEqual(res["threshold"], 65.0)
        self.assertEqual(len(res["alerts"]), 2)
        self.assertEqual(res["alerts"][0]["url"], "https://x/1")
        self.assertEqual(res["alerts"][1]["kind"], "repost")

    def test_mark_read_api(self):
        self._install()
        status, res = self._post("/api/watch/alerts/1/read")
        self.assertEqual(status, 200)
        self.assertEqual(res, {"ok": True, "id": 1})
        self.assertEqual(sys.modules["candid.alerts"]._marked, [1])

    def test_mark_read_api_unknown_id_404(self):
        self._install()
        status, res = self._post("/api/watch/alerts/99/read")
        self.assertEqual(status, 404)
        self.assertIn("error", res)

    def test_mark_read_api_absent_400(self):
        self._absent()
        status, res = self._post("/api/watch/alerts/1/read")
        self.assertEqual(status, 400)
        self.assertIn("error", res)

    def test_timeline_api(self):
        self._install()
        status, res = self._get_json("/api/watch/company?name=Acme")
        self.assertEqual(status, 200)
        self.assertEqual(res["company"], "Acme")
        self.assertEqual(len(res["open"]), 2)
        self.assertEqual(len(res["recently_closed"]), 1)
        self.assertTrue(res["open"][1]["reposted"])

    def test_timeline_api_unknown_company_404(self):
        self._install()
        status, res = self._get_json("/api/watch/company?name=Nope")
        self.assertEqual(status, 404)
        self.assertIn("error", res)

    def test_timeline_api_missing_name_400(self):
        self._install()
        status, res = self._get_json("/api/watch/company?name=")
        self.assertEqual(status, 400)
        self.assertIn("error", res)

    def test_root_serves_watch_panels(self):
        with urllib.request.urlopen(self._url("/")) as r:
            body = r.read()
        self.assertEqual(r.status, 200)
        self.assertIn(b'id="sec-watch"', body)
        self.assertIn(b"/api/watch", body)
        self.assertIn(b"loadWatch()", body)
        self.assertIn(b"loadAlerts()", body)
        self.assertIn(b"timelineWrap", body)


# ---------------------------------------------------------------------------
# integration against the real modules (temp data dir, no network)
# ---------------------------------------------------------------------------

class RealWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-watch-"))
        self._saved_data_dir = C.DATA_DIR
        self._saved_mods = {k: sys.modules.get(k)
                            for k in ("candid.monitors", "candid.alerts")}
        sys.modules.pop("candid.monitors", None)
        sys.modules.pop("candid.alerts", None)
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

    def tearDown(self):
        C.DATA_DIR = self._saved_data_dir
        for k, v in self._saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def test_real_modules_end_to_end(self):
        from candid import monitors as MON
        from candid import alerts as AL

        MON.add_company("Acme")
        MON.add_source("Acme", "greenhouse", board="acme")

        st = D.watch_status()
        self.assertTrue(st["enabled"])
        self.assertEqual(len(st["companies"]), 1)
        card = st["companies"][0]
        self.assertEqual(card["company"], "Acme")
        self.assertEqual(card["source_type"], "greenhouse")
        self.assertEqual(card["source_key"], "acme")
        self.assertEqual(card["feed_health"], "ok")  # no failures recorded
        self.assertEqual(card["open_count"], 0)

        alert = AL.create_alert(
            {"company": "Acme", "title": "Data Scientist",
             "url": "https://x/1"},
            90.0, "GO")
        res = D.watch_alerts()
        self.assertTrue(res["enabled"])
        self.assertEqual(res["threshold"], 60.0)  # default
        self.assertEqual(len(res["alerts"]), 1)
        self.assertEqual(res["alerts"][0]["id"], alert["id"])
        self.assertEqual(res["alerts"][0]["score"], 90.0)
        self.assertEqual(res["alerts"][0]["url"], "https://x/1")

        self.assertEqual(D.watch_mark_read(alert["id"]),
                         {"ok": True, "id": alert["id"]})
        self.assertEqual(D.watch_alerts()["alerts"], [])

        t = D.company_timeline("Acme")
        self.assertEqual(t["company"], "Acme")
        self.assertEqual(t["open"], [])
        self.assertEqual(t["recently_closed"], [])
        # the real get_history returns {} for unknown companies —
        # an empty timeline, not an error
        t2 = D.company_timeline("Nope")
        self.assertEqual(t2["open"], [])
        self.assertEqual(t2["recently_closed"], [])


if __name__ == "__main__":
    unittest.main()
