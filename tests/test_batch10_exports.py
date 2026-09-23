"""Tests for the batch-10 export formats workstream (Obsidian, .eml, vCard).

Run: CANDID_DATA_DIR=/tmp/candid-test-exports python -m unittest discover -s tests -p "test_batch10_exports.py"
(also honored when set in-process below).
"""
import argparse
import os
import shutil
import sys
import tempfile
import unittest
from email.parser import Parser
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-exports")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import exports as E  # noqa: E402
from candid import prep as P  # noqa: E402

TEST_DIR = Path("/tmp/candid-test-exports")

PROFILE = {
    "name": "Test Candidate",
    "experience": [
        {
            "title": "Software Engineer",
            "company": "OldCo",
            "bullets": [
                "Cut p99 latency by 40% across the ads ranking pipeline serving 10M QPS.",
                "Led migration of 12 services to Kubernetes with zero downtime.",
            ],
        }
    ],
}


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


class PrepObsidianTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _clean()
        # Build a REAL prep pack via the actual generator (no invented shape).
        cls.pack_md, cls.pack_path = P.build_pack(
            PROFILE, "Acme Corp", "Data Scientist", jd="python sql machine learning"
        )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-obs-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_all_expected_files(self):
        folder = E.export_prep_obsidian("Acme Corp", "Data Scientist", self.tmp)
        names = sorted(p.name for p in folder.iterdir())
        self.assertIn("Questions.md", names)
        self.assertIn("Concepts.md", names)
        self.assertIn("STAR stories.md", names)
        self.assertIn("Checklist.md", names)
        index = [n for n in names if n.startswith("Prep - Acme Corp - Data Scientist")]
        self.assertEqual(len(index), 1)

    def test_index_frontmatter_and_wikilinks(self):
        folder = E.export_prep_obsidian("Acme Corp", "Data Scientist", self.tmp)
        index = next(folder.glob("Prep - *.md"))
        text = index.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("company: Acme Corp", text)
        self.assertIn("role: Data Scientist", text)
        self.assertIn("date:", text)
        self.assertIn("tags:", text)
        for note in ("Questions", "Concepts", "STAR stories", "Checklist"):
            self.assertIn(f"[[{note}]]", text)

    def test_sections_land_in_child_notes(self):
        folder = E.export_prep_obsidian("Acme Corp", "Data Scientist", self.tmp)
        q = (folder / "Questions.md").read_text(encoding="utf-8")
        self.assertIn("Company-specific questions", q)
        c = (folder / "Concepts.md").read_text(encoding="utf-8")
        self.assertIn("Concept deep-dives", c)
        s = (folder / "STAR stories.md").read_text(encoding="utf-8")
        self.assertIn("STAR story prompts", s)
        cl = (folder / "Checklist.md").read_text(encoding="utf-8")
        self.assertIn("Company-research checklist", cl)
        self.assertIn("Day-Before Checklist", cl)

    def test_missing_pack_raises(self):
        with self.assertRaises(E.ExportError):
            E.export_prep_obsidian("Nonexistent Co", "Wizard", self.tmp)

    def test_graceful_when_section_missing(self):
        # A hand-written minimal pack: parser must not blow up and must
        # still produce all four child notes.
        odd = C.PREP_PACKS_DIR / "2099-01-01_Odd_Co-Janitor.md"
        odd.write_text("# Interview Prep — Janitor @ Odd Co\n\nJust a line.\n",
                       encoding="utf-8")
        folder = E.export_prep_obsidian("Odd Co", "Janitor", self.tmp)
        for n in ("Questions.md", "Concepts.md", "STAR stories.md", "Checklist.md"):
            self.assertTrue((folder / n).exists())


class FollowupEmlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-eml-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _roundtrip(self, path):
        raw = Path(path).read_text(encoding="utf-8")
        return Parser().parsestr(raw)

    def test_thank_you_roundtrip(self):
        out = self.tmp / "ty.eml"
        E.export_followup_eml(
            kind="thank-you", company="Acme Corp", role="Data Scientist",
            to="recruiter@acme.com", out=out, counterparty="Priya",
            sender_name="Test Candidate", sender_email="test@example.com")
        msg = self._roundtrip(out)
        self.assertTrue(msg["Subject"])  # warm-tone subject is generic
        self.assertEqual(msg["To"], "recruiter@acme.com")
        self.assertEqual(msg["From"], "test@example.com")
        self.assertTrue(msg["Date"])
        body = msg.get_payload(decode=True).decode("utf-8")
        self.assertIn("Priya", body)
        self.assertIn("Timing:", body)

    def test_check_in_and_referral(self):
        for kind in ("check-in", "referral"):
            out = self.tmp / f"{kind}.eml"
            E.export_followup_eml(
                kind=kind, company="Beta Inc", role="ML Engineer",
                out=out, sender_name="Test Candidate")
            msg = self._roundtrip(out)
            self.assertTrue(msg["Subject"])
            # To: left blank but present and valid.
            self.assertIsNotNone(msg["To"])
            self.assertEqual(msg["To"], "")
            self.assertIn("Beta Inc", msg.get_payload(decode=True).decode("utf-8"))

    def test_unknown_kind_raises(self):
        with self.assertRaises(E.ExportError):
            E.export_followup_eml(kind="nudge", company="X", out=self.tmp / "x.eml")


class ContactVcardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-vcf-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vcard_shape(self):
        out = self.tmp / "jane.vcf"
        E.export_contact_vcard(
            name="Jane Doe", email="jane@example.com", phone="+1 555-0100",
            org="Acme Corp", title="Recruiter", out=out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("BEGIN:VCARD", text)
        self.assertIn("VERSION:3.0", text)
        self.assertIn("FN:Jane Doe", text)
        self.assertIn("N:Doe;Jane;;;", text)
        self.assertIn("EMAIL;TYPE=INTERNET:jane@example.com", text)
        self.assertIn("TEL;TYPE=WORK,VOICE:+1 555-0100", text)
        self.assertIn("ORG:Acme Corp", text)
        self.assertIn("TITLE:Recruiter", text)
        self.assertIn("END:VCARD", text)

    def test_escaping(self):
        out = self.tmp / "esc.vcf"
        E.export_contact_vcard(name="Doe, John", email="j@d.com", out=out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("FN:Doe\\, John", text)

    def test_empty_name_raises(self):
        with self.assertRaises(E.ExportError):
            E.export_contact_vcard(name="  ", email="x@y.com",
                                   out=self.tmp / "bad.vcf")


class RegisterTest(unittest.TestCase):
    def test_register_adds_export_with_subcommands(self):
        parser = argparse.ArgumentParser(prog="python -m candid")
        sub = parser.add_subparsers(dest="cmd", required=True)
        E.register(sub)
        for argv in (
            ["export", "prep-obsidian", "--company", "A", "--role", "B", "--out", "/tmp/x"],
            ["export", "followup-eml", "--kind", "thank-you", "--company", "A", "--out", "f.eml"],
            ["export", "contact-vcard", "--name", "Jane", "--email", "j@x.com"],
        ):
            args = parser.parse_args(argv)
            self.assertEqual(args.cmd, "export")
            self.assertTrue(callable(args.func))


if __name__ == "__main__":
    unittest.main()
