"""Tests for candid.thankyou (post-interview thank-you sequencer)."""
import sys
import unittest
from datetime import date
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _interviewers():
    return [
        {"name": "Jane Doe", "round": "phone screen",
         "topics": "the ranking stack", "standout": "my latency win"},
        {"name": "Sam Reed", "round": "onsite"},
    ]


class ThankYouTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "thankyou_sequences.json"

    def tearDown(self):
        self.td.cleanup()

    def _plan(self, app_id=3, **kw):
        from candid import thankyou as TK
        kw.setdefault("role", "ML Engineer")
        kw.setdefault("company", "Acme")
        kw.setdefault("interviewers", _interviewers())
        return TK.plan(app_id, path=self.path, **kw)

    def test_plan_creates_steps(self):
        from candid import thankyou as TK
        seq = self._plan()
        self.assertEqual(seq["app_id"], 3)
        self.assertEqual(len(seq["steps"]), 2)
        self.assertEqual(seq["steps"][0]["interviewer"], "Jane Doe")
        self.assertEqual(seq["steps"][0]["status"], "pending")
        self.assertIn("same evening", seq["steps"][0]["timing"])
        self.assertEqual(seq["status"], "pending")

    def test_plan_replaces_existing(self):
        from candid import thankyou as TK
        self._plan()
        seq = TK.plan(3, role="ML Engineer", company="Acme",
                      interviewers=[{"name": "Only One", "round": "final"}],
                      path=self.path)
        self.assertEqual(len(seq["steps"]), 1)
        self.assertEqual(len(TK.list_sequences(path=self.path)), 1)

    def test_plan_validates(self):
        from candid import thankyou as TK
        with self.assertRaises(TK.ThankYouError):
            TK.plan(1, role="", company="Acme",
                    interviewers=_interviewers(), path=self.path)
        with self.assertRaises(TK.ThankYouError):
            TK.plan(1, role="ML", company="Acme", interviewers=[],
                    path=self.path)
        with self.assertRaises(TK.ThankYouError):
            TK.plan(1, role="ML", company="Acme",
                    interviewers=[{"name": ""}], path=self.path)

    def test_get_sequence_missing(self):
        from candid import thankyou as TK
        with self.assertRaises(TK.ThankYouError) as cm:
            TK.get_sequence(99, path=self.path)
        self.assertIn("thanks plan", str(cm.exception))

    def test_draft_uses_thank_you(self):
        from candid import thankyou as TK
        self._plan()
        d = TK.draft(3, 1, name="Alex Rivera", path=self.path)
        self.assertIn("Subject:", d)
        self.assertIn("Jane Doe", d)
        self.assertIn("ML Engineer", d)
        self.assertIn("Acme", d)
        self.assertIn("ranking stack", d)
        self.assertIn("Alex Rivera", d)

    def test_mark_sent(self):
        from candid import thankyou as TK
        self._plan()
        seq = TK.mark_sent(3, 1, path=self.path)
        self.assertEqual(seq["steps"][0]["status"], "sent")
        self.assertEqual(seq["steps"][0]["date_sent"], date.today().isoformat())
        self.assertEqual(seq["status"], "pending")  # step 2 still pending
        seq = TK.mark_sent(3, 2, path=self.path)
        self.assertEqual(seq["status"], "sent")

    def test_mark_sent_rejects_bad_step_and_double_send(self):
        from candid import thankyou as TK
        self._plan()
        with self.assertRaises(TK.ThankYouError):
            TK.mark_sent(3, 9, path=self.path)
        TK.mark_sent(3, 1, path=self.path)
        with self.assertRaises(TK.ThankYouError):
            TK.mark_sent(3, 1, path=self.path)

    def test_mark_sent_unknown_app(self):
        from candid import thankyou as TK
        with self.assertRaises(TK.ThankYouError):
            TK.mark_sent(77, 1, path=self.path)

    def test_pending_steps(self):
        from candid import thankyou as TK
        self._plan(app_id=3)
        self._plan(app_id=4, interviewers=[{"name": "Zoe Park"}])
        TK.mark_sent(3, 1, path=self.path)
        pend = TK.pending_steps(path=self.path)
        self.assertEqual(len(pend), 2)
        names = {p["interviewer"] for p in pend}
        self.assertEqual(names, {"Sam Reed", "Zoe Park"})

    def test_list_sequences_filter(self):
        from candid import thankyou as TK
        self._plan(app_id=3)
        self._plan(app_id=4, interviewers=[{"name": "Zoe Park"}])
        TK.mark_sent(4, 1, path=self.path)
        self.assertEqual(len(TK.list_sequences(status="sent", path=self.path)), 1)
        self.assertEqual(len(TK.list_sequences(status="pending", path=self.path)), 1)
        self.assertEqual(len(TK.list_sequences(path=self.path)), 2)

    def test_render_sequence(self):
        from candid import thankyou as TK
        seq = self._plan()
        out = TK.render_sequence(seq)
        self.assertIn("App #3", out)
        self.assertIn("Jane Doe", out)
        self.assertIn("step 1", out)

    def test_render_pending_empty(self):
        from candid import thankyou as TK
        self.assertIn("All thank-you notes are sent", TK.render_pending([]))


if __name__ == "__main__":
    unittest.main()
