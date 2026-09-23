"""Integration tests for batch 22 (worker C): warm-intro integrations + docs.

Covers:
- tracker <-> warm linkage: `warm link` round-trip, intro column on
  `track list`, and the guarantee that warm.set_status never auto-writes
  tracker entries;
- candid/warm_timing.py: last-contact lookup from a Gmail Takeout mbox,
  including defensive name matching and ambiguity handling;
- dashboard "Warm intros" section: data function, /api/warm route, HTML.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_dashboard.py).
"""
import email.message
import email.utils
import json
import mailbox
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import date, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import tracker as T  # noqa: E402
from candid import warm as W  # noqa: E402
from candid import warm_timing as WT  # noqa: E402


class TempData(unittest.TestCase):
    """Redirect config data paths into a temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-warmint-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "WARM_PATH", "DATA_DIR",
                     "GMAIL_PROPOSALS_PATH"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.WARM_PATH = self.tmp / "warm.json"
        C.DATA_DIR = self.tmp
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)


# ---------------------------------------------------------------------------
# tracker <-> warm linkage
# ---------------------------------------------------------------------------

class WarmLinkTest(TempData):
    def test_link_round_trip_preserves_outreach(self):
        T.add("Acme Corp", "Data Scientist", path=C.TRACKER_PATH)
        W.set_status("Acme Corp", "asked", contact="Jane Doe")
        rec = T.link_warm_app("Acme Corp", 1)
        self.assertEqual(rec["app_id"], 1)
        self.assertEqual(rec["status"], "asked")
        self.assertEqual(rec["contact"], "Jane Doe")
        self.assertEqual(rec["asked_on"], date.today().isoformat())
        # persisted in warm.json under the normalized company key
        state = W.load_warm()
        self.assertEqual(state["acme"]["app_id"], 1)

    def test_link_creates_record_when_no_outreach_yet(self):
        T.add("Initech", "Analyst", path=C.TRACKER_PATH)
        rec = T.link_warm_app("Initech", 1)
        self.assertEqual(rec["app_id"], 1)
        self.assertEqual(rec["status"], "none")

    def test_link_rejects_unknown_app_id(self):
        T.add("Initech", "Analyst", path=C.TRACKER_PATH)
        with self.assertRaises(T.TrackerError):
            T.link_warm_app("Initech", 999)

    def test_link_needs_company(self):
        T.add("Initech", "Analyst", path=C.TRACKER_PATH)
        with self.assertRaises(T.TrackerError):
            T.link_warm_app("   ", 1)

    def test_set_status_never_writes_tracker(self):
        T.add("Acme Corp", "Data Scientist", path=C.TRACKER_PATH)
        before = T.list_apps(path=C.TRACKER_PATH)
        W.set_status("Acme Corp", "applied", contact="Jane Doe")
        after = T.list_apps(path=C.TRACKER_PATH)
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[0]["status"], "saved")  # tracker untouched

    def test_intro_column_shows_warm_status(self):
        T.add("Acme Corp", "Data Scientist", path=C.TRACKER_PATH)
        T.add("Hooli", "ML Engineer", path=C.TRACKER_PATH)
        W.set_status("Acme Corp", "asked", contact="Jane Doe")
        out = T.render_list(T.list_apps(path=C.TRACKER_PATH))
        self.assertIn("Intro", out.splitlines()[0])
        acme_line = next(l for l in out.splitlines() if "Acme" in l)
        hooli_line = next(l for l in out.splitlines() if "Hooli" in l)
        self.assertIn("asked", acme_line)
        self.assertNotIn("asked", hooli_line)
        # "none" is not noisy: companies with no outreach show a blank intro
        self.assertNotIn("none", hooli_line)

    def test_cli_warm_link(self):
        T.add("Acme Corp", "Data Scientist", path=C.TRACKER_PATH)
        args = CLI.build_parser().parse_args(["warm", "link", "Acme", "--app", "1"])
        args.func(args)
        self.assertEqual(W.load_warm()["acme"]["app_id"], 1)


# ---------------------------------------------------------------------------
# warm_timing: last contact from a Gmail Takeout mbox
# ---------------------------------------------------------------------------

def _ts(y, m, d):
    return time.mktime(datetime(y, m, d, 12, 0, 0).timetuple())


def _msg(frm="", to="", cc="", ts=None, subject="hi"):
    m = email.message.Message()
    if frm:
        m["From"] = frm
    if to:
        m["To"] = to
    if cc:
        m["Cc"] = cc
    m["Date"] = email.utils.formatdate(ts, localtime=False)
    m["Subject"] = subject
    m.set_payload("hello")
    return m


class WarmTimingTest(unittest.TestCase):
    def _mbox(self, messages):
        tmp = Path(tempfile.mkdtemp(prefix="candid-timing-"))
        p = tmp / "takeout.mbox"
        box = mailbox.mbox(str(p))
        try:
            for m in messages:
                box.add(m)
            box.flush()
        finally:
            box.close()
        return p

    def test_recent_date_found_from_header(self):
        p = self._mbox([
            _msg(frm="Ann Lee <ann.lee@example.com>", ts=_ts(2026, 1, 5)),
            _msg(frm="Ann Lee <ann.lee@example.com>", ts=_ts(2026, 9, 20)),
        ])
        self.assertEqual(WT.get_last_contact("Ann Lee", p), date(2026, 9, 20))

    def test_to_and_cc_headers_match(self):
        p = self._mbox([
            _msg(frm="me@example.com", to="Bob Ray <bob@example.com>",
                 ts=_ts(2026, 3, 3)),
            _msg(frm="me@example.com", cc="Cara Poe <cara@example.com>",
                 ts=_ts(2026, 8, 8)),
        ])
        self.assertEqual(WT.get_last_contact("bob ray", p), date(2026, 3, 3))
        self.assertEqual(WT.get_last_contact("CARA POE", p), date(2026, 8, 8))

    def test_no_match_returns_none(self):
        p = self._mbox([
            _msg(frm="Someone Else <x@example.com>", ts=_ts(2026, 9, 1)),
        ])
        self.assertIsNone(WT.get_last_contact("Ann Lee", p))

    def test_ambiguous_names_return_none_never_guess(self):
        # Same full name, two distinct contact identities: ambiguous.
        p = self._mbox([
            _msg(frm="Ann Lee <ann.lee@example.com>", ts=_ts(2026, 9, 20)),
            _msg(frm="Ann Lee <ann.other@example.org>", ts=_ts(2026, 9, 21)),
        ])
        self.assertIsNone(WT.get_last_contact("Ann Lee", p))

    def test_blank_name_returns_none(self):
        p = self._mbox([
            _msg(frm="Ann Lee <ann.lee@example.com>", ts=_ts(2026, 9, 20)),
        ])
        self.assertIsNone(WT.get_last_contact("   ", p))

    def test_missing_mbox_raises(self):
        with self.assertRaises(WT.TimingError):
            WT.get_last_contact("Ann Lee", "/no/such/file.mbox")

    def test_directory_of_mboxes(self):
        tmp = Path(tempfile.mkdtemp(prefix="candid-timing-dir-"))
        box = mailbox.mbox(str(tmp / "a.mbox"))
        box.add(_msg(frm="Ann Lee <ann.lee@example.com>", ts=_ts(2026, 5, 5)))
        box.flush()
        box.close()
        self.assertEqual(WT.get_last_contact("Ann Lee", tmp), date(2026, 5, 5))


# ---------------------------------------------------------------------------
# dashboard "Warm intros" section
# ---------------------------------------------------------------------------

SNAPSHOT = [
    {"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe",
     "company": "Acme Inc", "position": "VP Engineering",
     "connected_on": "2026-06-01", "degree": 1},
    {"first_name": "Max", "last_name": "Roe", "full_name": "Max Roe",
     "company": "Hooli", "position": "Intern",
     "connected_on": "2020-01-01", "degree": 1},
]


class WarmDashboardTest(TempData):
    def _seed(self, snapshot=True):
        T.add("Acme Corp", "Data Scientist", path=C.TRACKER_PATH)
        W.set_status("Acme Corp", "asked", contact="Jane Doe")
        T.link_warm_app("Acme Corp", 1)
        W.set_status("Hooli", "introduced", contact="Max Roe")
        if snapshot:
            (self.tmp / "connections.json").write_text(
                json.dumps(SNAPSHOT), encoding="utf-8")

    def test_warm_intros_ranks_by_strength(self):
        self._seed()
        rows = D.warm_intros()
        self.assertEqual(len(rows), 2)
        # Acme's VP outranks Hooli's intern
        self.assertEqual(rows[0]["company"], "Acme Inc")
        self.assertGreater(rows[0]["strength"], rows[1]["strength"])
        self.assertEqual(rows[0]["top_connection"], "Jane Doe")
        self.assertEqual(rows[0]["status"], "asked")
        self.assertEqual(rows[0]["contact"], "Jane Doe")
        self.assertEqual(rows[0]["asked_on"], date.today().isoformat())
        self.assertEqual(rows[0]["app_id"], 1)

    def test_warm_intros_without_snapshot_still_shows_status(self):
        self._seed(snapshot=False)
        rows = D.warm_intros()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["strength"] == 0.0 for r in rows))
        by_company = {r["company"]: r for r in rows}
        self.assertEqual(by_company["acme"]["status"], "asked")
        self.assertEqual(by_company["hooli"]["status"], "introduced")

    def test_warm_intros_empty_when_no_outreach(self):
        self.assertEqual(D.warm_intros(), [])

    def test_api_warm_route(self):
        self._seed()
        server = ThreadingHTTPServer(("127.0.0.1", 0), D.DashboardHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/warm") as r:
                self.assertEqual(r.status, 200)
                rows = json.loads(r.read().decode())
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["top_connection"], "Jane Doe")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_html_has_warm_section(self):
        html = (ROOT / "candid" / "data" / "dashboard.html").read_text(
            encoding="utf-8")
        self.assertIn('id="sec-warm"', html)
        self.assertIn("/api/warm", html)
        self.assertIn("loadWarm", html)


if __name__ == "__main__":
    unittest.main()
