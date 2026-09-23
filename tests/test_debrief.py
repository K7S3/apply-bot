"""Tests for the interview-debrief store (candid/debrief.py).

Run: python -m unittest discover -s tests
(Uses an explicit store path so the suite is immune to CANDID_DATA_DIR
import-order races with other test modules.)
"""

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-debrief")
STORE = TEST_DIR / "debriefs.json"


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


from candid import debrief  # noqa: E402


_SUMMARY_A = {
    "key_questions": ["Tell me about yourself.", "Explain gradient boosting."],
    "key_answers": ["I am a data scientist.", "Trees fit on residuals."],
    "weak_spots": ["On 'Explain gradient boosting.': got shaky on the loss function [not confident]"],
    "action_items": ["Review gradient boosting math."],
    "one_paragraph_summary": "Covered 2 questions.",
    "enhanced": False,
}
_SUMMARY_B = {
    "key_questions": ["Design a feature store."],
    "key_answers": ["Talked about Feast."],
    "weak_spots": ["On 'Explain gradient boosting.': got shaky on the loss function [not confident]",
                   "On 'Design a feature store.': stumbled on offline vs online stores [stumbled]"],
    "action_items": ["Read the Feast docs."],
    "one_paragraph_summary": "System design round.",
    "enhanced": False,
}


def _record(app_id, company, role, summary):
    return debrief.record_debrief(app_id, company, role, "/tmp/t.json",
                                  summary, path=STORE)


class DebriefStoreTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_record_and_get(self):
        rec = _record(7, "Acme", "Data Scientist", _SUMMARY_A)
        self.assertEqual(rec["id"], 1)
        self.assertEqual(rec["app_id"], 7)
        self.assertEqual(rec["company"], "Acme")
        self.assertIn("recorded_at", rec)
        got = debrief.get(1, path=STORE)
        self.assertEqual(got["role"], "Data Scientist")
        self.assertEqual(got["summary"]["key_questions"][0],
                         "Tell me about yourself.")

    def test_record_assigns_incrementing_ids(self):
        a = _record(1, "A", "R", _SUMMARY_A)
        b = _record(1, "A", "R", _SUMMARY_A)
        self.assertEqual(a["id"] + 1, b["id"])

    def test_get_missing_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief.get(999, path=STORE)

    def test_record_bad_summary_raises(self):
        with self.assertRaises(debrief.DebriefError):
            debrief.record_debrief(1, "A", "R", "t", "not a dict", path=STORE)

    def test_list_debriefs_newest_first_and_filter(self):
        _record(7, "Acme", "DS", _SUMMARY_A)
        _record(9, "Beta", "MLE", _SUMMARY_B)
        all_ds = debrief.list_debriefs(path=STORE)
        self.assertEqual(len(all_ds), 2)
        self.assertEqual(all_ds[0]["app_id"], 9)  # newest first
        only_7 = debrief.list_debriefs(app_id=7, path=STORE)
        self.assertEqual(len(only_7), 1)
        self.assertEqual(only_7[0]["company"], "Acme")

    def test_has_debrief(self):
        self.assertFalse(debrief.has_debrief(7, path=STORE))
        _record(7, "Acme", "DS", _SUMMARY_A)
        self.assertTrue(debrief.has_debrief(7, path=STORE))
        self.assertFalse(debrief.has_debrief(8, path=STORE))

    def test_weak_spots_aggregate_newest_first_deduped(self):
        _record(7, "Acme", "DS", _SUMMARY_A)
        _record(7, "Acme", "DS", _SUMMARY_B)
        spots = debrief.weak_spots(app_id=7, path=STORE)
        # shared spot deduped to a single entry
        self.assertEqual(len(spots), 2)
        self.assertEqual(len({s.lower() for s in spots}), 2)
        self.assertTrue(any("gradient boosting" in s for s in spots))
        self.assertTrue(any("feature store" in s for s in spots))

    def test_weak_spots_filter_app(self):
        _record(7, "Acme", "DS", _SUMMARY_A)
        _record(9, "Beta", "MLE", _SUMMARY_B)
        spots_7 = debrief.weak_spots(app_id=7, path=STORE)
        self.assertEqual(len(spots_7), 1)
        spots_all = debrief.weak_spots(path=STORE)
        self.assertEqual(len(spots_all), 2)

    def test_render_summary_sections(self):
        rec = _record(7, "Acme", "Data Scientist", _SUMMARY_A)
        out = debrief.render_summary(rec)
        for section in ("SUMMARY", "KEY QUESTIONS & ANSWERS", "WEAK SPOTS",
                        "ACTION ITEMS", "Acme", "Data Scientist"):
            self.assertIn(section, out)
        self.assertIn("Tell me about yourself.", out)
        self.assertIn("Review gradient boosting math.", out)


if __name__ == "__main__":
    unittest.main()
