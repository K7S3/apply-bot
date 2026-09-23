"""Tests for candid.polish_library. Run:
CANDID_DATA_DIR=$(mktemp -d) python3 -m pytest tests/test_polish_library.py -q
"""
import json
import os
import tempfile

# Point the candid data dir at a scratch dir before importing candid, so the
# tests work even without the CANDID_DATA_DIR env var from the runner.
os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-pl-"))

import unittest

from candid import polish_library as PL


ORIG = "I work with data. I built models. It went well."
POLISHED = "I partner with stakeholders on data products. I built production ML models. The rollout lifted conversion 12%."
QUESTION = "Tell me about yourself"


def _write_last(original=ORIG, polished=POLISHED, question=QUESTION):
    path = PL.LAST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"question": question, "original": original,
                    "polished": polished}),
        encoding="utf-8",
    )


class ReadLastTest(unittest.TestCase):
    def setUp(self):
        if PL.LAST_PATH.exists():
            PL.LAST_PATH.unlink()

    def test_missing_raises(self):
        with self.assertRaises(PL.LibraryError):
            PL.read_last()

    def test_reads_file(self):
        _write_last()
        last = PL.read_last()
        self.assertEqual(last["original"], ORIG)
        self.assertEqual(last["polished"], POLISHED)

    def test_corrupt_raises(self):
        PL.LAST_PATH.write_text("{not json", encoding="utf-8")
        with self.assertRaises(PL.LibraryError):
            PL.read_last()


class SaveEntryTest(unittest.TestCase):
    def setUp(self):
        if PL.LIBRARY_PATH.exists():
            PL.LIBRARY_PATH.unlink()
        if PL.LAST_PATH.exists():
            PL.LAST_PATH.unlink()

    def test_save_from_last(self):
        _write_last()
        entry_id = PL.save_entry("self-intro")
        entry = PL.get_entry(entry_id)
        self.assertEqual(entry["status"], "pending")
        self.assertEqual(entry["original"], ORIG)
        self.assertEqual(entry["polished"], POLISHED)
        self.assertEqual(entry["question"], QUESTION)
        self.assertTrue(entry_id.startswith("pl-"))
        self.assertIn("created_at", entry)

    def test_save_from_last_without_question(self):
        path = PL.LAST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"original": ORIG, "polished": POLISHED}),
                        encoding="utf-8")
        entry_id = PL.save_entry("no-q", question="custom q?")
        self.assertEqual(PL.get_entry(entry_id)["question"], "custom q?")

    def test_save_explicit(self):
        entry_id = PL.save_entry("explicit", question="q?",
                                 original="a b c", polished="a b")
        entry = PL.get_entry(entry_id)
        self.assertEqual(entry["original"], "a b c")
        self.assertEqual(entry["polished"], "a b")

    def test_save_without_last_raises(self):
        with self.assertRaises(PL.LibraryError):
            PL.save_entry("boom")

    def test_save_empty_name_raises(self):
        with self.assertRaises(PL.LibraryError):
            PL.save_entry("   ", original="x", polished="y")

    def test_save_star(self):
        star = {"situation": "s", "task": "t", "action": "a", "result": "r"}
        entry_id = PL.save_entry("star", original="o", polished="p", star=star)
        self.assertEqual(PL.get_entry(entry_id)["star"], star)


class ListGetTest(unittest.TestCase):
    def setUp(self):
        if PL.LIBRARY_PATH.exists():
            PL.LIBRARY_PATH.unlink()
        self.id1 = PL.save_entry("system design story", question="scale QPS",
                                 original="aaa", polished="bbb")
        self.id2 = PL.save_entry("conflict story", question="disagree",
                                 original="ccc", polished="ddd")
        PL.approve(self.id1)

    def test_list_all(self):
        self.assertEqual(len(PL.list_entries()), 2)

    def test_filter_status(self):
        approved = PL.list_entries(status="approved")
        self.assertEqual([e["id"] for e in approved], [self.id1])
        pending = PL.list_entries(status="pending")
        self.assertEqual([e["id"] for e in pending], [self.id2])

    def test_filter_bad_status(self):
        with self.assertRaises(PL.LibraryError):
            PL.list_entries(status="bogus")

    def test_query(self):
        hits = PL.list_entries(query="conflict")
        self.assertEqual([e["id"] for e in hits], [self.id2])
        hits = PL.list_entries(query="QPS")
        self.assertEqual([e["id"] for e in hits], [self.id1])
        self.assertEqual(PL.list_entries(query="zzz"), [])

    def test_get_unknown(self):
        with self.assertRaises(PL.LibraryError):
            PL.get_entry("pl-deadbeef")


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        if PL.LIBRARY_PATH.exists():
            PL.LIBRARY_PATH.unlink()
        self.entry_id = PL.save_entry("intro", question=QUESTION,
                                      original=ORIG, polished=POLISHED)

    def test_render_approval_diff(self):
        text = PL.render_approval(self.entry_id)
        self.assertIn("--- original", text)
        self.assertIn("+++ polished", text)
        self.assertIn("Answer: intro", text)
        self.assertIn("Status: pending", text)
        self.assertIn("words:", text)
        self.assertIn("saved)", text)
        # diff markers for changed lines
        self.assertIn("-I work with data.", text)
        self.assertIn("+I partner with stakeholders on data products.", text)

    def test_render_unknown(self):
        with self.assertRaises(PL.LibraryError):
            PL.render_approval("pl-deadbeef")

    def test_approve_sets_status_and_returns_diff(self):
        diff = PL.approve(self.entry_id)
        self.assertEqual(PL.get_entry(self.entry_id)["status"], "approved")
        self.assertIn("+++ polished", diff)
        self.assertIn("Status: approved", diff)

    def test_reject(self):
        diff = PL.reject(self.entry_id)
        self.assertEqual(PL.get_entry(self.entry_id)["status"], "rejected")
        self.assertIn("Status: rejected", diff)

    def test_approve_unknown(self):
        with self.assertRaises(PL.LibraryError):
            PL.approve("pl-deadbeef")


class DeleteLinkTest(unittest.TestCase):
    def setUp(self):
        if PL.LIBRARY_PATH.exists():
            PL.LIBRARY_PATH.unlink()
        self.entry_id = PL.save_entry("to-delete", original="x", polished="y")

    def test_delete(self):
        PL.delete(self.entry_id)
        with self.assertRaises(PL.LibraryError):
            PL.get_entry(self.entry_id)

    def test_delete_unknown(self):
        with self.assertRaises(PL.LibraryError):
            PL.delete("pl-deadbeef")

    def test_link_story(self):
        entry = PL.link_story(self.entry_id, "story-42")
        self.assertEqual(entry["story_id"], "story-42")
        self.assertEqual(PL.get_entry(self.entry_id)["story_id"], "story-42")
        self.assertIn("story-42", PL.render_approval(self.entry_id))

    def test_link_story_unknown(self):
        with self.assertRaises(PL.LibraryError):
            PL.link_story("pl-deadbeef", "story-1")

    def test_link_story_empty(self):
        with self.assertRaises(PL.LibraryError):
            PL.link_story(self.entry_id, "  ")


class StatsTest(unittest.TestCase):
    def setUp(self):
        if PL.LIBRARY_PATH.exists():
            PL.LIBRARY_PATH.unlink()

    def test_stats_empty(self):
        s = PL.stats()
        self.assertEqual(s, {"total": 0, "pending": 0, "approved": 0,
                             "rejected": 0, "words_saved": 0})

    def test_stats_counts_and_words(self):
        id1 = PL.save_entry("a", original="one two three four", polished="one two")
        id2 = PL.save_entry("b", original="hello world", polished="hello")
        id3 = PL.save_entry("c", original="x y", polished="x y z")
        PL.approve(id1)
        PL.reject(id2)
        s = PL.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["approved"], 1)
        self.assertEqual(s["rejected"], 1)
        # (4-2) + (2-1) + (2-3) = 2
        self.assertEqual(s["words_saved"], 2)


if __name__ == "__main__":
    unittest.main()
