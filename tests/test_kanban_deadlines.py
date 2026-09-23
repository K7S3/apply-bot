"""Tests for dashboard kanban view + application deadline countdowns.

Uses a temp data dir (CANDID_DATA_DIR-style overrides on the config module),
never the real candid_data/. Both the pure data functions and the HTTP
routes are exercised.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import dashboard as D  # noqa: E402
from candid import tracker as T  # noqa: E402


def iso(d: date) -> str:
    return d.isoformat()


class KanbanBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-kanban-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def seed(self, **kw):
        """Add an app; returns the record."""
        return T.add(kw.pop("company", "Acme"), kw.pop("role", "Engineer"), **kw)

    def _set_updated(self, app_id: int, day: date):
        apps = T._load()
        for a in apps:
            if a["id"] == app_id:
                a["date_updated"] = iso(day)
        T._save(apps)


# ---------------------------------------------------------------------------
# tracker.update(deadline=...)
# ---------------------------------------------------------------------------

class DeadlineUpdateTest(KanbanBase):
    def test_update_deadline_valid(self):
        rec = self.seed()
        out = T.update(rec["id"], deadline="2026-10-01")
        self.assertEqual(out["deadline"], "2026-10-01")
        # persisted
        self.assertEqual(T._load()[0]["deadline"], "2026-10-01")

    def test_update_deadline_strict_format(self):
        # Not zero-padded → rejected: the format is strictly YYYY-MM-DD.
        rec = self.seed()
        with self.assertRaises(T.TrackerError):
            T.update(rec["id"], deadline="2026-1-5")

    def test_update_deadline_invalid(self):
        rec = self.seed()
        for bad in ("10/01/2026", "tomorrow", "2026-13-01", "2026-02-30",
                    "2026-10-01 12:00", "abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(T.TrackerError):
                    T.update(rec["id"], deadline=bad)
        self.assertNotIn("deadline", T._load()[0])

    def test_update_deadline_clear(self):
        rec = self.seed()
        T.update(rec["id"], deadline="2026-10-01")
        out = T.update(rec["id"], deadline="")
        self.assertEqual(out["deadline"], "")

    def test_update_deadline_omitted_leaves_untouched(self):
        rec = self.seed()
        T.update(rec["id"], deadline="2026-10-01")
        out = T.update(rec["id"], status="applied")
        self.assertEqual(out["deadline"], "2026-10-01")

    def test_update_deadline_unknown_id(self):
        with self.assertRaises(T.TrackerError):
            T.update(999, deadline="2026-10-01")


# ---------------------------------------------------------------------------
# deadline_alerts() urgency buckets
# ---------------------------------------------------------------------------

class DeadlineAlertsTest(KanbanBase):
    TODAY = date(2026, 9, 22)

    def test_buckets_and_sort(self):
        def add_with(company, offset_days):
            r = self.seed(company=company)
            T.update(r["id"], deadline=iso(self.TODAY + timedelta(days=offset_days)))
            return r
        add_with("OverdueCo", -2)      # overdue
        add_with("ThreeCo", 3)         # due_3d
        add_with("ZeroCo", 0)          # due_3d (due today)
        add_with("SevenCo", 7)         # due_7d
        add_with("LaterCo", 30)        # later
        self.seed(company="NoDeadlineCo")  # skipped

        rows = D.deadline_alerts(today=self.TODAY)
        self.assertEqual([r["company"] for r in rows],
                         ["OverdueCo", "ZeroCo", "ThreeCo", "SevenCo", "LaterCo"])
        self.assertEqual([r["bucket"] for r in rows],
                         ["overdue", "due_3d", "due_3d", "due_7d", "later"])
        self.assertEqual([r["days_remaining"] for r in rows],
                         [-2, 0, 3, 7, 30])
        # entry fields
        first = rows[0]
        for key in ("app_id", "company", "role", "status", "deadline",
                    "days_remaining", "bucket"):
            self.assertIn(key, first)

    def test_empty_when_no_deadlines(self):
        self.seed()
        self.assertEqual(D.deadline_alerts(today=self.TODAY), [])

    def test_boundary_days(self):
        r1 = self.seed(company="D3"); T.update(r1["id"], deadline=iso(self.TODAY + timedelta(days=3)))
        r2 = self.seed(company="D4"); T.update(r2["id"], deadline=iso(self.TODAY + timedelta(days=4)))
        r3 = self.seed(company="D7"); T.update(r3["id"], deadline=iso(self.TODAY + timedelta(days=7)))
        r4 = self.seed(company="D8"); T.update(r4["id"], deadline=iso(self.TODAY + timedelta(days=8)))
        rows = D.deadline_alerts(today=self.TODAY)
        by_co = {r["company"]: r["bucket"] for r in rows}
        self.assertEqual(by_co, {"D3": "due_3d", "D4": "due_7d",
                                "D7": "due_7d", "D8": "later"})


# ---------------------------------------------------------------------------
# kanban_board() shaping
# ---------------------------------------------------------------------------

class KanbanBoardTest(KanbanBase):
    TODAY = date(2026, 9, 22)

    def test_columns_match_statuses(self):
        self.seed(company="A", status="saved")
        self.seed(company="B", status="offer")
        board = D.kanban_board(today=self.TODAY)
        self.assertEqual(list(board.keys()), list(C.STATUSES))
        self.assertEqual([c["company"] for c in board["saved"]["cards"]], ["A"])
        self.assertEqual([c["company"] for c in board["offer"]["cards"]], ["B"])
        self.assertEqual(board["applied"]["cards"], [])

    def test_card_fields(self):
        r = self.seed(company="Acme", role="Data Scientist", status="applied")
        T.update(r["id"], deadline=iso(self.TODAY + timedelta(days=2)))
        self._set_updated(r["id"], self.TODAY - timedelta(days=5))  # after update()
        card = D.kanban_board(today=self.TODAY)["applied"]["cards"][0]
        self.assertEqual(card["id"], r["id"])
        self.assertEqual(card["company"], "Acme")
        self.assertEqual(card["role"], "Data Scientist")
        self.assertEqual(card["status"], "applied")
        self.assertEqual(card["days_in_stage"], 5)
        self.assertEqual(card["next_action"], T.NEXT_ACTIONS["applied"])
        self.assertEqual(card["deadline"], iso(self.TODAY + timedelta(days=2)))
        self.assertEqual(card["days_remaining"], 2)

    def test_days_in_stage_floor_zero(self):
        r = self.seed()
        self._set_updated(r["id"], self.TODAY + timedelta(days=3))  # future
        card = D.kanban_board(today=self.TODAY)["saved"]["cards"][0]
        self.assertEqual(card["days_in_stage"], 0)

    def test_unknown_status_skipped_not_500(self):
        apps = T._load()
        r = self.seed()
        for a in apps:
            if a["id"] == r["id"]:
                a["status"] = "not_a_real_status"
        T._save(apps)
        board = D.kanban_board(today=self.TODAY)  # must not raise
        self.assertNotIn("not_a_real_status", board)


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

class KanbanHTTPTest(KanbanBase):
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
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.loads(r.read().decode())

    def _post_json(self, path, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())

    def test_get_kanban(self):
        self.seed(company="A", status="applied")
        status, res = self._get_json("/api/kanban")
        self.assertEqual(status, 200)
        self.assertEqual(set(res.keys()), set(C.STATUSES))
        self.assertEqual(res["applied"]["cards"][0]["company"], "A")

    def test_get_deadlines(self):
        r = self.seed(company="B")
        T.update(r["id"], deadline=iso(date.today() + timedelta(days=1)))
        status, res = self._get_json("/api/deadlines")
        self.assertEqual(status, 200)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["bucket"], "due_3d")
        self.assertEqual(res[0]["days_remaining"], 1)

    def test_post_deadline(self):
        r = self.seed()
        status, res = self._post_json(f"/api/apps/{r['id']}/deadline",
                                     {"deadline": "2026-12-31"})
        self.assertEqual(status, 200)
        self.assertEqual(res["deadline"], "2026-12-31")
        # and the kanban view reflects it
        _, board = self._get_json("/api/kanban")
        self.assertEqual(board["saved"]["cards"][0]["deadline"], "2026-12-31")

    def test_post_deadline_invalid(self):
        r = self.seed()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post_json(f"/api/apps/{r['id']}/deadline",
                            {"deadline": "not-a-date"})
        self.assertEqual(ctx.exception.code, 400)

    def test_post_deadline_unknown_app(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post_json("/api/apps/4242/deadline",
                            {"deadline": "2026-12-31"})
        self.assertEqual(ctx.exception.code, 404)

    def test_move_card_via_existing_status_route(self):
        r = self.seed(status="saved")
        status, res = self._post_json(f"/api/apps/{r['id']}",
                                     {"status": "applied"})
        self.assertEqual(status, 200)
        _, board = self._get_json("/api/kanban")
        self.assertEqual(board["saved"]["cards"], [])
        self.assertEqual(board["applied"]["cards"][0]["company"], r["company"])


# ---------------------------------------------------------------------------
# HTML smoke checks
# ---------------------------------------------------------------------------

class DashboardHTMLTest(unittest.TestCase):
    HTML = ROOT / "candid" / "data" / "dashboard.html"

    def test_parses(self):
        class P(HTMLParser):
            def error(self, message):
                raise AssertionError(message)
        P().feed(self.HTML.read_text(encoding="utf-8"))

    def test_sections_present(self):
        text = self.HTML.read_text(encoding="utf-8")
        for sid in ("sec-deadlines", "sec-kanban", "kanbanBoard",
                    "deadlineAlerts"):
            self.assertIn(f'id="{sid}"', text)
        for token in ("/api/kanban", "/api/deadlines", "/deadline"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
