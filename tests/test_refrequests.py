"""Tests for candid.refrequests (referral request workflow)."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class RefRequestTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "referral_requests.json"

    def tearDown(self):
        self.td.cleanup()

    def _add(self, **kw):
        from candid import refrequests as R
        kw.setdefault("contact", "Priya Nair")
        kw.setdefault("company", "Acme")
        kw.setdefault("role", "ML Engineer")
        return R.add(path=self.path, **kw)

    def test_add_and_list(self):
        from candid import refrequests as R
        rec = self._add()
        self.assertEqual(rec["id"], 1)
        self.assertEqual(rec["status"], "drafted")
        self.assertEqual(rec["date_created"], date.today().isoformat())
        self.assertEqual(len(R.list_requests(path=self.path)), 1)

    def test_add_duplicate_returns_existing(self):
        from candid import refrequests as R
        a = self._add()
        b = self._add()
        self.assertTrue(b.get("duplicate"))
        self.assertEqual(b["id"], a["id"])
        self.assertEqual(len(R.list_requests(path=self.path)), 1)

    def test_add_rejects_missing_fields(self):
        from candid import refrequests as R
        with self.assertRaises(R.RefRequestError):
            R.add("", "Acme", "ML Engineer", path=self.path)

    def test_add_rejects_bad_status(self):
        from candid import refrequests as R
        with self.assertRaises(R.RefRequestError):
            R.add("Priya", "Acme", "ML", status="bogus", path=self.path)

    def test_update_status_sets_dates(self):
        from candid import refrequests as R
        rec = self._add()
        r = R.update(rec["id"], status="sent", path=self.path)
        self.assertEqual(r["status"], "sent")
        self.assertEqual(r["date_sent"], date.today().isoformat())
        r = R.update(rec["id"], status="connected", path=self.path)
        self.assertEqual(r["date_closed"], date.today().isoformat())

    def test_update_note_appends(self):
        from candid import refrequests as R
        rec = self._add()
        r = R.update(rec["id"], note="sent via LinkedIn", path=self.path)
        self.assertIn("sent via LinkedIn", r["notes"])

    def test_update_rejects_unknown_id_and_status(self):
        from candid import refrequests as R
        with self.assertRaises(R.RefRequestError):
            R.update(999, status="sent", path=self.path)
        with self.assertRaises(R.RefRequestError):
            R.update(1, status="bogus", path=self.path)

    def test_list_filter_by_status(self):
        from candid import refrequests as R
        self._add(contact="A")
        self._add(contact="B", status="sent")
        self.assertEqual(len(R.list_requests(status="sent", path=self.path)), 1)
        self.assertEqual(len(R.list_requests(path=self.path)), 2)

    def test_draft_uses_referral_ask(self):
        from candid import refrequests as R
        rec = self._add(connection="your team builds the ranking stack")
        d = R.draft(rec["id"], name="Alex Rivera", path=self.path)
        self.assertIn("Subject: Quick favor", d)
        self.assertIn("Priya Nair", d)
        self.assertIn("ML Engineer", d)
        self.assertIn("Acme", d)
        self.assertIn("Alex Rivera", d)

    def test_draft_unknown_id(self):
        from candid import refrequests as R
        with self.assertRaises(R.RefRequestError):
            R.draft(999, path=self.path)

    def test_remind_finds_quiet_sent_requests(self):
        from candid import refrequests as R
        import json
        rec = self._add(status="sent")
        old = (date.today() - timedelta(days=10)).isoformat()
        data = json.loads(self.path.read_text())
        data[0]["date_sent"] = old
        self.path.write_text(json.dumps(data))
        rems = R.remind(days=7, name="Alex Rivera", path=self.path)
        self.assertEqual(len(rems), 1)
        self.assertEqual(rems[0]["request"]["id"], rec["id"])
        self.assertEqual(rems[0]["days_quiet"], 10)
        self.assertIn("Checking in", rems[0]["draft"])  # check_in tone
        self.assertIn(str(rec["id"]), rems[0]["command"])

    def test_remind_skips_recent(self):
        from candid import refrequests as R
        self._add(status="sent")  # sent today
        self.assertEqual(R.remind(days=7, path=self.path), [])

    def test_remind_skips_non_sent(self):
        from candid import refrequests as R
        self._add(status="drafted")
        self.assertEqual(R.remind(days=1, path=self.path), [])

    def test_render_list(self):
        from candid import refrequests as R
        self._add()
        out = R.render_list(R.list_requests(path=self.path))
        self.assertIn("#1", out)
        self.assertIn("Priya Nair", out)

    def test_env_data_dir_override(self):
        import os
        from candid import refrequests as R
        os.environ["CANDID_DATA_DIR"] = self.td.name
        try:
            rec = R.add("Kai Tan", "Beta", "Data Scientist")
            self.assertTrue((Path(self.td.name) / "referral_requests.json").exists())
            self.assertEqual(R.get(rec["id"])["contact"], "Kai Tan")
        finally:
            del os.environ["CANDID_DATA_DIR"]


if __name__ == "__main__":
    unittest.main()
