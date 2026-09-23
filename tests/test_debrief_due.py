"""Tests for worker D: debrief reminders, nudge integration, prep integration,
markdown export.

Run: CANDID_DATA_DIR=/tmp/candid-test-debrief-due python3 -m unittest discover -s tests

Isolation: tracker/debrief stores are exercised through their `path=`
overrides or via rebound config paths, never the real user data dir.
"""
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-debrief-due")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import debrief_due as DD  # noqa: E402
from candid import nudges as N  # noqa: E402
from candid import prep as P  # noqa: E402

TODAY = date(2026, 9, 22)


@contextmanager
def _no_debrief_store():
    """Simulate candid.debrief being truly absent.

    patch.dict(sys.modules, ...) alone is not enough: the import system
    falls back to the already-set `candid.debrief` package attribute, so
    we must remove that too for the ImportError path to trigger.
    """
    import candid
    saved = getattr(candid, "debrief", None)
    had = hasattr(candid, "debrief")
    if had:
        delattr(candid, "debrief")
    with unittest.mock.patch.dict(sys.modules, {"candid.debrief": None}):
        try:
            yield
        finally:
            if had:
                setattr(candid, "debrief", saved)


def _app(app_id, company="Acme", role="Data Scientist", status="offer",
         updated=None, notes=""):
    return {
        "id": app_id,
        "company": company,
        "role": role,
        "status": status,
        "notes": notes,
        "date_added": "2026-09-01",
        "date_updated": (updated or TODAY).isoformat(),
        "prep_pack": "",
    }


_SUMMARY = {
    "key_questions": ["Walk me through a churn model"],
    "key_answers": ["Described the XGBoost pipeline"],
    "weak_spots": ["fumbled the SQL window function question"],
    "action_items": ["drill SQL window functions"],
    "one_paragraph_summary": "Solid round, weak on SQL.",
    "enhanced": False,
}


class DueListingTest(unittest.TestCase):
    def test_offer_status_is_due_when_recent(self):
        apps = [_app(1, status="offer")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        self.assertEqual([d["app"]["id"] for d in due], [1])

    def test_offer_status_outside_window_not_due(self):
        apps = [_app(1, status="offer", updated=TODAY - timedelta(days=30))]
        due = DD.interviews_due(apps=apps, today=TODAY, days=7,
                                has_debrief=lambda i: False)
        self.assertEqual(due, [])

    def test_selected_for_interview_with_past_date_is_due(self):
        apps = [_app(2, status="selected_for_interview",
                     notes="onsite Sept 20, 2026")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        self.assertEqual([d["app"]["id"] for d in due], [2])
        self.assertEqual(due[0]["interview_date"], "2026-09-20")

    def test_selected_for_interview_no_past_date_not_due(self):
        apps = [_app(2, status="selected_for_interview",
                     notes="onsite next week")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        self.assertEqual(due, [])

    def test_non_interview_statuses_never_due(self):
        apps = [_app(1, status=s) for s in
                ("saved", "applied", "rejected", "withdrawn")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        self.assertEqual(due, [])

    def test_forward_compatible_interview_statuses(self):
        apps = [_app(1, status="interviewed"), _app(2, status="onsite")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        self.assertEqual({d["app"]["id"] for d in due}, {1, 2})

    def test_debriefed_app_stops_being_due(self):
        from candid import debrief as D
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "debriefs.json"
            apps = [_app(7, status="offer")]
            store_fn = lambda i: D.has_debrief(i, path=store)
            self.assertEqual(
                len(DD.interviews_due(apps=apps, today=TODAY, has_debrief=store_fn)), 1)
            D.record_debrief(7, "Acme", "Data Scientist",
                             transcript_path="", summary=dict(_SUMMARY), path=store)
            self.assertEqual(
                DD.interviews_due(apps=apps, today=TODAY, has_debrief=store_fn), [])

    def test_missing_store_means_everything_due(self):
        # candid.debrief absent -> treated as "no debriefs recorded", never raises
        apps = [_app(1, status="offer")]
        with _no_debrief_store():
            due = DD.interviews_due(apps=apps, today=TODAY)
        self.assertEqual([d["app"]["id"] for d in due], [1])

    def test_render_due(self):
        apps = [_app(1, status="offer")]
        due = DD.interviews_due(apps=apps, today=TODAY, has_debrief=lambda i: False)
        text = DD.render_due(due, days=7)
        self.assertIn("Acme", text)
        self.assertIn("debrief", text.lower())
        self.assertIn("No interviews", DD.render_due([], days=7))


class NudgeIntegrationTest(unittest.TestCase):
    def setUp(self):
        # hermetic: never consult the real/shared debrief store here
        self.td = tempfile.TemporaryDirectory()
        self.orig_debriefs = C.DEBRIEFS_PATH
        C.DEBRIEFS_PATH = Path(self.td.name) / "debriefs.json"

    def tearDown(self):
        C.DEBRIEFS_PATH = self.orig_debriefs
        self.td.cleanup()

    def test_debrief_nudges_shape(self):
        apps = [_app(1, company="Acme", role="Data Scientist", status="offer")]
        nudges = DD.debrief_nudges(apps=apps, today=TODAY)
        self.assertEqual(len(nudges), 1)
        n = nudges[0]
        self.assertEqual(n["kind"], "debrief_due")
        self.assertEqual(n["app_id"], 1)
        self.assertIn("Debrief your", n["message"])
        self.assertIn("Acme", n["message"])
        self.assertIn("command", n)

    def test_pending_nudges_includes_debrief_due(self):
        apps = [_app(1, status="offer")]
        nudges = N.pending_nudges(apps=apps, today=TODAY)
        kinds = [n["kind"] for n in nudges]
        self.assertIn("debrief_due", kinds)

    def test_pending_nudges_no_crash_without_store(self):
        apps = [_app(1, status="offer")]
        with _no_debrief_store():
            nudges = N.pending_nudges(apps=apps, today=TODAY)
        self.assertTrue(any(n["kind"] == "debrief_due" for n in nudges))


class PrepIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.orig_debriefs = C.DEBRIEFS_PATH
        self.orig_packs = C.PREP_PACKS_DIR
        C.DEBRIEFS_PATH = Path(self.td.name) / "debriefs.json"
        C.PREP_PACKS_DIR = Path(self.td.name) / "packs"

    def tearDown(self):
        C.DEBRIEFS_PATH = self.orig_debriefs
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def _record(self, app_id=3):
        from candid import debrief as D
        return D.record_debrief(app_id, "Acme", "Data Scientist",
                                transcript_path="", summary=dict(_SUMMARY))

    def test_weak_spots_for_prep(self):
        self._record()
        spots = P.weak_spots_for_prep(3)
        self.assertIn("fumbled the SQL window function question", spots)

    def test_weak_spots_for_prep_empty_without_debriefs(self):
        self.assertEqual(P.weak_spots_for_prep(3), [])
        self.assertEqual(P.weak_spots_for_prep(None), [])

    def test_weak_spots_for_prep_empty_without_store(self):
        self._record()
        with _no_debrief_store():
            self.assertEqual(P.weak_spots_for_prep(3), [])

    def test_get_debrief_context_section(self):
        self._record()
        ctx = P.get_debrief_context(3)
        self.assertIn("Based on your past debriefs, drill these:", ctx)
        self.assertIn("fumbled the SQL window function question", ctx)

    def test_get_debrief_context_empty(self):
        self.assertEqual(P.get_debrief_context(3), "")

    def test_build_pack_includes_debrief_section(self):
        self._record(app_id=3)
        prof = {"name": "Test", "experience": []}
        md, _ = P.build_pack(prof, "Acme", "Data Scientist", app_id=3)
        self.assertIn("Based on your past debriefs, drill these:", md)
        self.assertIn("fumbled the SQL window function question", md)

    def test_build_pack_without_store_still_works(self):
        prof = {"name": "Test", "experience": []}
        with _no_debrief_store():
            md, _ = P.build_pack(prof, "Acme", "Data Scientist", app_id=3)
        self.assertNotIn("Based on your past debriefs", md)
        self.assertIn("Interview Prep", md)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_debriefs = C.DEBRIEFS_PATH
        C.DATA_DIR = Path(self.td.name) / "data"
        C.DEBRIEFS_PATH = Path(self.td.name) / "debriefs.json"

    def tearDown(self):
        C.DATA_DIR = self.orig_data
        C.DEBRIEFS_PATH = self.orig_debriefs
        self.td.cleanup()

    def _record(self, transcript_path=""):
        from candid import debrief as D
        return D.record_debrief(5, "Acme", "Data Scientist",
                                transcript_path=transcript_path,
                                summary=dict(_SUMMARY))

    def test_export_markdown_contents(self):
        rec = self._record()
        out = DD.export_debrief_markdown(rec["id"], fmt="md")
        self.assertTrue(out.exists())
        self.assertEqual(out.parent.parent, C.DATA_DIR)  # under the data dir
        text = out.read_text(encoding="utf-8")
        self.assertIn("Acme", text)
        self.assertIn("Data Scientist", text)
        self.assertIn("Solid round, weak on SQL.", text)
        self.assertIn("fumbled the SQL window function question", text)
        self.assertIn("Walk me through a churn model", text)
        self.assertIn("drill SQL window functions", text)

    def test_export_includes_transcript_turns(self):
        tpath = Path(self.td.name) / "session.json"
        tpath.write_text(
            '[{"prompt": "Tell me about yourself", "answer": "I am a data scientist"}]',
            encoding="utf-8")
        rec = self._record(transcript_path=str(tpath))
        out = DD.export_debrief_markdown(rec["id"], fmt="md")
        text = out.read_text(encoding="utf-8")
        self.assertIn("Tell me about yourself", text)
        self.assertIn("I am a data scientist", text)

    def test_export_unknown_id_raises(self):
        self._record()
        with self.assertRaises(DD.DebriefDueError):
            DD.export_debrief_markdown(999, fmt="md")

    def test_export_bad_format_raises(self):
        rec = self._record()
        with self.assertRaises(DD.DebriefDueError):
            DD.export_debrief_markdown(rec["id"], fmt="pdf")

    def test_export_via_app_id_fallback(self):
        rec = self._record()
        out = DD.export_debrief_markdown(5, fmt="md")  # tracker app id, not debrief id
        self.assertTrue(out.exists())
        self.assertIn(f"debrief_{rec['id']}_", out.name)


if __name__ == "__main__":
    unittest.main()
