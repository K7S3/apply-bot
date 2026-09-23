"""Tests for candid.packet: application packet PDF export + references.

PDF output is verified to start with %PDF and to parse back with pypdf
(strict mode). If pypdf is unavailable the byte-level checks still run.
"""
import os
import tempfile

DATA_DIR = tempfile.mkdtemp(prefix="candid-test-packet-")
os.environ["CANDID_DATA_DIR"] = DATA_DIR

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C
from candid import packet as P
from candid import tracker as T

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


PROFILE = {
    "name": "Test User",
    "location": "New York, NY",
    "headline": "Data Scientist",
    "seniority": "mid",
    "years_experience": 4.0,
    "skills": ["python", "sql", "machine learning"],
    "experience": [
        {"title": "Data Scientist", "company": "Initech", "dates": "2023 - Present",
         "bullets": [
             "Built churn model with python that cut attrition 12%",
             "Wrote SQL reports for product analytics",
         ]},
    ],
    "education": [{"school": "State University", "degree": "BS Statistics",
                   "dates": "2018 - 2022"}],
}

JD = ("We are hiring a Data Scientist. Requirements: python, sql, "
      "machine learning, product analytics. Nice to have: deep learning.")


def _add_app(company="PacketCo", role="Data Scientist"):
    return T.add(company, role, status="applied")


class PacketTestBase(unittest.TestCase):
    def setUp(self):
        C.PROFILE_PATH.write_text(json.dumps(PROFILE), encoding="utf-8")
        self.app = _add_app(company=f"PacketCo-{self._testMethodName}")


class TestPdfWriter(PacketTestBase):
    def test_pdf_starts_with_magic_and_parses(self):
        pdf = P._write_pdf([("Title", "hello world")])
        self.assertTrue(pdf.startswith(b"%PDF"))
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        self.assertEqual(len(reader.pages), 1)
        self.assertIn("hello world", reader.pages[0].extract_text())

    def test_long_text_flows_across_pages(self):
        pdf = P._write_pdf([("Big", "line\n" * 500)])
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        self.assertGreater(len(reader.pages), 1)
        last = reader.pages[-1].extract_text()
        self.assertIn(f"Page {len(reader.pages)} of {len(reader.pages)}", last)

    def test_non_latin1_glyphs_do_not_break_pdf(self):
        body = "bullet \u2022 em dash \u2014 ellipsis \u2026 caf\u00e9"
        pdf = P._write_pdf([("Glyphs", body)])
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        text = PdfReader(io.BytesIO(pdf), strict=True).pages[0].extract_text()
        self.assertIn("bullet - em dash -", text)
        self.assertIn("caf", text)  # latin-1 char survives


class TestPacketBuild(PacketTestBase):
    def _build(self, **kw):
        return P.build_packet(self.app["id"], jd=JD, **kw)

    def test_packet_has_resume_and_cover_letter(self):
        pdf = self._build()
        self.assertTrue(pdf.startswith(b"%PDF"))
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        self.assertGreaterEqual(len(reader.pages), 2)
        all_text = "\n".join(p.extract_text() for p in reader.pages)
        self.assertIn("TEST USER", all_text)
        self.assertIn("Cover Letter", all_text)
        self.assertNotIn("REFERENCES", all_text)

    def test_packet_reuses_tailor_output(self):
        from candid import tailor as TL
        resume = TL.build_resume(PROFILE, JD, company=self.app["company"],
                                 role=self.app["role"])
        pdf = self._build()
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        all_text = "\n".join(
            p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        # a distinctive tailor-produced line appears in the packet
        self.assertIn("ATS KEYWORD CHECK", all_text)
        self.assertIn(resume.splitlines()[0], all_text)

    def test_references_page_only_with_consent(self):
        P.add_reference("Sam Rivera", "former manager", "sam@example.com")
        pdf = self._build(include_references=True)
        if not HAS_PYPDF:
            self.skipTest("pypdf not installed")
        pages = PdfReader(io.BytesIO(pdf), strict=True).pages
        self.assertIn("REFERENCES", pages[-1].extract_text())
        self.assertIn("Sam Rivera", pages[-1].extract_text())

    def test_references_flag_with_no_references_errors(self):
        with self.assertRaises(P.PacketError) as ctx:
            self._build(include_references=True)
        self.assertIn("references add", str(ctx.exception))

    def test_unknown_app_errors(self):
        with self.assertRaises(P.PacketError):
            P.build_packet(999999, jd=JD)

    def test_missing_jd_errors_with_next_command(self):
        with self.assertRaises(P.PacketError) as ctx:
            P.build_packet(self.app["id"])
        self.assertIn("--jd", str(ctx.exception))

    def test_save_packet_writes_file(self):
        dest = Path(DATA_DIR) / "packet.pdf"
        out = P.save_packet(self.app["id"], dest, jd=JD)
        self.assertEqual(out, dest)
        self.assertTrue(dest.read_bytes().startswith(b"%PDF"))


class TestReferences(PacketTestBase):
    def test_add_and_list(self):
        rec = P.add_reference("Sam Rivera", "former manager", "sam@example.com")
        self.assertEqual(rec["name"], "Sam Rivera")
        refs = P.list_references()
        self.assertTrue(any(r["name"] == "Sam Rivera" for r in refs))

    def test_add_requires_name_and_relationship(self):
        with self.assertRaises(P.PacketError):
            P.add_reference("", "former manager")
        with self.assertRaises(P.PacketError):
            P.add_reference("Sam Rivera", "")


if __name__ == "__main__":
    unittest.main()
