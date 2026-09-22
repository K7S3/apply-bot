"""Tests for the offer letter PDF parser (candid/offer_parse.py).

Run: python3 -m pytest tests/test_offer_parse.py -q
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import offer as O  # noqa: E402
from candid import offer_parse as OP  # noqa: E402


FULL_LETTER = """Dear Alex Rivera,

We are pleased to offer you the position of Senior Data Scientist at Acme Corp.

Your annual base salary will be $190,000, paid semi-monthly.

You will be eligible for an annual discretionary bonus with a target of 15% of your base salary.

You will also receive a one-time sign-on bonus of $25,000, payable with your first paycheck.

Subject to board approval, you will be granted 1,200 restricted stock units (RSUs) with a grant value of approximately $180,000. The RSUs will vest over 4 years, with 25% vesting annually on each anniversary of your start date.

Your anticipated start date is October 5, 2026.

Benefits include comprehensive health insurance, dental and vision coverage, 15 days of PTO, and a 401(k) plan with company match.

Sincerely,
Jane Smith, VP People
"""

PARTIAL_LETTER = """Dear Alex Rivera,

We are pleased to offer you the position of Data Scientist at Beta Inc.

Your annual base salary will be $150,000.

Sincerely,
HR
"""


def make_pdf(path: Path, text: str) -> None:
    """Write a minimal one-page PDF (stdlib only) so pypdf can extract text."""
    lines = text.splitlines()
    content = []
    y = 740
    for ln in lines:
        esc = (ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))
        content.append(f"BT /F1 11 Tf 50 {y} Td ({esc}) Tj ET")
        y -= 16
    stream = "\n".join(content).encode("latin-1")
    parts = [b"%PDF-1.4\n"]
    offsets = {}

    def obj(n: int, data: bytes) -> None:
        offsets[n] = sum(len(p) for p in parts)
        parts.append(f"{n} 0 obj\n".encode("latin-1") + data + b"\nendobj\n")

    obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
           b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    obj(5, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    xref = sum(len(p) for p in parts)
    n = max(offsets) + 1
    parts.append(f"xref\n0 {n}\n".encode("latin-1"))
    parts.append(b"0000000000 65535 f \n")
    for i in range(1, n):
        parts.append(f"{offsets[i]:010d} 00000 n \n".encode("latin-1"))
    parts.append(
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
        .encode("latin-1"))
    path.write_bytes(b"".join(parts))


class OfferParseTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = Path(self.td.name)
        self._orig_data = C.DATA_DIR
        self._orig_offers = C.OFFERS_PATH
        C.DATA_DIR = self.tmp
        C.OFFERS_PATH = self.tmp / "offers.json"

    def tearDown(self):
        C.DATA_DIR = self._orig_data
        C.OFFERS_PATH = self._orig_offers
        self.td.cleanup()

    def _letter_pdf(self, text: str, name: str = "letter.pdf") -> Path:
        p = self.tmp / name
        make_pdf(p, text)
        return p

    # -- extraction ------------------------------------------------------
    def test_full_extraction_from_pdf(self):
        p = self._letter_pdf(FULL_LETTER)
        result = OP.parse_letter_text(OP.read_letter_text(p))
        f = result["fields"]
        self.assertEqual(f["base"], 190000)
        self.assertEqual(f["bonus_target_pct"], 15)
        self.assertEqual(f["sign_on"], 25000)
        self.assertEqual(f["equity_total"], 180000)
        self.assertEqual(f["equity_type"], "rsu")
        self.assertEqual(f["vest_years"], 4)
        self.assertEqual(f["vest_schedule"], "25/25/25/25")
        self.assertEqual(f["start_date"], "October 5, 2026")
        self.assertEqual(result["equity_shares"], 1200)
        for b in ("401(k)", "health insurance", "dental", "vision", "PTO"):
            self.assertIn(b, result["benefit_mentions"])
        self.assertEqual(result["pto_days"], 15)
        # only benefits_value is genuinely absent
        self.assertEqual(result["missing"], ["benefits_value"])
        # every extracted field carries its source snippet
        for field in ("base", "bonus_target_pct", "sign_on", "equity_total"):
            self.assertIn(field, result["evidence"])
            self.assertTrue(result["evidence"][field].strip())

    def test_partial_extraction_lists_missing(self):
        p = self._letter_pdf(PARTIAL_LETTER)
        result = OP.parse_letter_text(OP.read_letter_text(p))
        f = result["fields"]
        self.assertEqual(f["base"], 150000)
        # nothing invented: only base found
        self.assertNotIn("sign_on", f)
        self.assertNotIn("equity_total", f)
        self.assertNotIn("benefits_value", f)
        self.assertIn("bonus_target_pct", result["missing"])
        self.assertIn("sign_on", result["missing"])
        self.assertIn("equity_total", result["missing"])
        self.assertIn("benefits_value", result["missing"])

    def test_k_suffix_and_no_comma_amounts(self):
        text = ("Your base salary will be $190K. You will receive a sign-on "
                "bonus of $25k.")
        result = OP.parse_letter_text(text)
        self.assertEqual(result["fields"]["base"], 190000)
        self.assertEqual(result["fields"]["sign_on"], 25000)

    def test_bonus_phrasing_variants(self):
        for letter in (
            "Annual target bonus of 20% of base salary.",
            "You are eligible for a 20% target bonus.",
            "Discretionary annual bonus with a target payout of 20%.",
        ):
            result = OP.parse_letter_text(letter + " Base salary $100,000.")
            self.assertEqual(result["fields"]["bonus_target_pct"], 20,
                             f"failed on: {letter}")

    def test_vest_percentages_are_not_bonus(self):
        # vesting 25% must not be read as a 25% bonus target
        result = OP.parse_letter_text(
            "RSUs vest over 4 years, 25% annually. Base salary $100,000.")
        self.assertNotIn("bonus_target_pct", result["fields"])
        self.assertEqual(result["fields"]["vest_schedule"], "25/25/25/25")

    def test_missing_file_raises_offer_error(self):
        with self.assertRaises(O.OfferError):
            OP.read_letter_text(self.tmp / "nope.pdf")

    def test_txt_letter_also_readable(self):
        p = self.tmp / "letter.txt"
        p.write_text(FULL_LETTER, encoding="utf-8")
        result = OP.parse_letter_text(OP.read_letter_text(p))
        self.assertEqual(result["fields"]["base"], 190000)

    # -- confirmation flow ------------------------------------------------
    def test_confirm_yes_saves_record(self):
        p = self._letter_pdf(FULL_LETTER)
        result = OP.parse_letter_text(OP.read_letter_text(p))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rec = OP.confirm_and_add(result, "Acme", "Senior Data Scientist",
                                     yes=True, source=str(p))
        out = buf.getvalue()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(rec["base"], 190000)
        # extraction printed with evidence snippets
        self.assertIn("$190,000", out)
        self.assertIn("...", out)
        # missing fields listed, not invented
        self.assertIn("benefits_value", out)
        # persisted
        self.assertEqual(len(O.list_offers()), 1)
        self.assertIn("1,200 RSUs", O.list_offers()[0]["notes"])

    def test_confirm_prompt_accepts_y(self):
        result = OP.parse_letter_text("Base salary $100,000.")
        with mock.patch("builtins.input", return_value="y"):
            rec = OP.confirm_and_add(result, "Acme", "DS")
        self.assertIsNotNone(rec)
        self.assertEqual(len(O.list_offers()), 1)

    def test_confirm_prompt_decline_saves_nothing(self):
        result = OP.parse_letter_text("Base salary $100,000.")
        buf = io.StringIO()
        with mock.patch("builtins.input", return_value="n"), \
                redirect_stdout(buf):
            rec = OP.confirm_and_add(result, "Acme", "DS")
        self.assertIsNone(rec)
        self.assertEqual(O.list_offers(), [])
        self.assertIn("offer add --help", buf.getvalue())

    def test_confirm_empty_letter_still_asks(self):
        result = OP.parse_letter_text("Dear candidate, welcome aboard.")
        self.assertEqual(result["fields"], {})
        with mock.patch("builtins.input", return_value="n"):
            rec = OP.confirm_and_add(result, "Acme", "DS")
        self.assertIsNone(rec)

    # -- CLI ---------------------------------------------------------------
    def test_cli_parse_smoke(self):
        p = self._letter_pdf(FULL_LETTER)
        env = dict(os.environ, CANDID_DATA_DIR=str(self.tmp))
        proc = subprocess.run(
            [sys.executable, "-m", "candid", "offer", "parse", str(p),
             "--company", "Acme", "--role", "Senior Data Scientist", "--yes"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
            timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Added offer #1", proc.stdout)
        self.assertIn("$190,000", proc.stdout)
        offers = O.list_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["normalized_annual"], 190000 + 28500
                         + 12500 + 45000)

    def test_cli_missing_file_friendly_error(self):
        env = dict(os.environ, CANDID_DATA_DIR=str(self.tmp))
        proc = subprocess.run(
            [sys.executable, "-m", "candid", "offer", "parse",
             str(self.tmp / "missing.pdf"),
             "--company", "Acme", "--role", "DS", "--yes"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
            timeout=120)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("Next: run `python -m candid offer --help`", proc.stderr)


if __name__ == "__main__":
    unittest.main()
