"""Tests for candid.appnotes: per-application notes and file attachments.

Run: CANDID_DATA_DIR is pointed at a throwaway dir before candid imports,
so nothing touches the real data dir.
"""
import os
import tempfile

DATA_DIR = tempfile.mkdtemp(prefix="candid-test-appnotes-")
os.environ["CANDID_DATA_DIR"] = DATA_DIR

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import appnotes as A
from candid import tracker as T


def _add_app(company="Acme", role="Data Scientist"):
    return T.add(company, role, status="applied")


def _fake_file(directory, name, size=1024):
    p = Path(directory) / name
    p.write_bytes(os.urandom(size))
    return p


class TestNotes(unittest.TestCase):
    def setUp(self):
        self.app = _add_app(company=f"NoteCo-{self._testMethodName}")

    def test_add_and_list_roundtrip(self):
        entry = A.add_note(self.app["id"], "Met hiring manager at meetup")
        self.assertIn("timestamp", entry)
        self.assertEqual(entry["text"], "Met hiring manager at meetup")
        notes = A.list_notes(self.app["id"])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["text"], "Met hiring manager at meetup")

    def test_notes_are_ordered_oldest_first(self):
        A.add_note(self.app["id"], "first")
        A.add_note(self.app["id"], "second")
        self.assertEqual([n["text"] for n in A.list_notes(self.app["id"])],
                         ["first", "second"])

    def test_notes_isolated_per_app(self):
        other = _add_app(company=f"OtherCo-{self._testMethodName}")
        A.add_note(self.app["id"], "only here")
        self.assertEqual(A.list_notes(other["id"]), [])

    def test_empty_note_rejected(self):
        with self.assertRaises(A.AppNotesError):
            A.add_note(self.app["id"], "   ")

    def test_unknown_app_rejected(self):
        with self.assertRaises(A.AppNotesError):
            A.add_note(999999, "hello")
        with self.assertRaises(A.AppNotesError):
            A.list_notes(999999)


class TestAttachments(unittest.TestCase):
    def setUp(self):
        self.app = _add_app(company=f"AttachCo-{self._testMethodName}")
        self.srcdir = tempfile.mkdtemp(prefix="candid-attach-src-")

    def test_attach_and_list_roundtrip(self):
        src = _fake_file(self.srcdir, "resume_tailored.pdf", size=2048)
        rec = A.attach(self.app["id"], src)
        self.assertEqual(rec["filename"], "resume_tailored.pdf")
        self.assertEqual(rec["size_bytes"], 2048)
        self.assertIn("added_at", rec)
        atts = A.list_attachments(self.app["id"])
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0]["filename"], "resume_tailored.pdf")

    def test_open_path_returns_stored_copy(self):
        src = _fake_file(self.srcdir, "cover.pdf", size=512)
        A.attach(self.app["id"], src)
        p = A.open_path(self.app["id"], "cover.pdf")
        self.assertTrue(p.is_file())
        self.assertEqual(p.read_bytes(), src.read_bytes())
        # attachments live under the data dir, never in the repo
        self.assertTrue(str(p).startswith(DATA_DIR))

    def test_filename_sanitized(self):
        src = _fake_file(self.srcdir, "weird name (final)!.pdf", size=100)
        rec = A.attach(self.app["id"], src)
        self.assertNotIn(" ", rec["filename"])
        self.assertNotIn("(", rec["filename"])
        dest = A.open_path(self.app["id"], rec["filename"])
        self.assertTrue(dest.is_file())

    def test_duplicate_filenames_do_not_overwrite(self):
        src1 = _fake_file(self.srcdir, "resume.pdf", size=100)
        sub = Path(self.srcdir) / "sub"
        sub.mkdir()
        src2 = _fake_file(sub, "resume.pdf", size=200)
        r1 = A.attach(self.app["id"], src1)
        r2 = A.attach(self.app["id"], src2)
        self.assertNotEqual(r1["filename"], r2["filename"])
        self.assertEqual(len(A.list_attachments(self.app["id"])), 2)

    def test_missing_source_rejected(self):
        with self.assertRaises(A.AppNotesError):
            A.attach(self.app["id"], Path(self.srcdir) / "nope.pdf")

    def test_unknown_app_rejected(self):
        src = _fake_file(self.srcdir, "x.pdf", size=10)
        with self.assertRaises(A.AppNotesError):
            A.attach(999999, src)

    def test_size_cap_enforced(self):
        old = A.MAX_ATTACHMENT_BYTES
        A.MAX_ATTACHMENT_BYTES = 1024
        try:
            src = _fake_file(self.srcdir, "big.pdf", size=2048)
            with self.assertRaises(A.AppNotesError) as ctx:
                A.attach(self.app["id"], src)
            self.assertIn("cap", str(ctx.exception))
        finally:
            A.MAX_ATTACHMENT_BYTES = old

    def test_open_path_unknown_file_rejected(self):
        with self.assertRaises(A.AppNotesError):
            A.open_path(self.app["id"], "missing.pdf")


if __name__ == "__main__":
    unittest.main()
