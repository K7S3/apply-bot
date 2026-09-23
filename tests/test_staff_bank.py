"""Tests for candid.staff_bank (staff/principal question bank + rubrics).

Run: CANDID_DATA_DIR=/tmp/candid-test-staff python -m pytest tests/test_staff_bank.py -q
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = os.environ.get(
    "CANDID_DATA_DIR", str(Path(tempfile.gettempdir()) / "candid-test-staff")
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class StaffBankDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from candid import staff_bank as sb
        cls.sb = sb

    def test_dimensions(self):
        self.assertEqual(
            self.sb.list_dimensions(),
            ["scope", "influence", "ambiguity", "org-design", "mentorship"],
        )

    def test_question_count_and_coverage(self):
        qs = self.sb.get_questions()
        self.assertGreaterEqual(len(qs), 40)
        for d in self.sb.list_dimensions():
            self.assertGreaterEqual(
                len(self.sb.get_questions(dimension=d)), 6,
                f"dimension {d} too thin",
            )

    def test_entry_schema(self):
        for q in self.sb.get_questions():
            self.assertIn("q", q)
            self.assertIn("dimension", q)
            self.assertIn("level", q)
            self.assertIn("good_signals", q)
            self.assertIn("follow_ups", q)
            self.assertIn("source", q)
            self.assertEqual(q["source"], "candid practice prompt")
            self.assertTrue(q["q"].strip())
            self.assertTrue(q["good_signals"])
            self.assertTrue(q["follow_ups"])
            self.assertTrue(set(q["level"]) <= {6, 7})
            # no em dashes, per user style rule
            for text in [q["q"]] + q["good_signals"] + q["follow_ups"]:
                self.assertNotIn("\u2014", text)
                self.assertNotIn("\u2013", text)

    def test_level_filter(self):
        six = self.sb.get_questions(level=6)
        seven = self.sb.get_questions(level=7)
        self.assertTrue(all(6 in q["level"] for q in six))
        self.assertTrue(all(7 in q["level"] for q in seven))
        self.assertTrue(six and seven)

    def test_limit(self):
        self.assertEqual(len(self.sb.get_questions(limit=3)), 3)
        self.assertEqual(len(self.sb.get_questions(limit=0)), 0)

    def test_dimension_filter_preserves_dimension(self):
        for q in self.sb.get_questions(dimension="ambiguity"):
            self.assertEqual(q["dimension"], "ambiguity")

    def test_bad_inputs_raise(self):
        with self.assertRaises(self.sb.StaffError):
            self.sb.get_questions(dimension="nope")
        with self.assertRaises(self.sb.StaffError):
            self.sb.get_questions(level=5)
        with self.assertRaises(self.sb.StaffError):
            self.sb.get_questions(limit=-1)
        with self.assertRaises(self.sb.StaffError):
            self.sb.get_rubric("nope")


class RubricTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from candid import staff_bank as sb
        cls.sb = sb

    def test_rubric_dimensions(self):
        for d in [
            "technical-judgment",
            "org-influence",
            "mentorship",
            "delivery-through-others",
            "ambiguity-handling",
        ]:
            r = self.sb.get_rubric(d)
            self.assertEqual(r["dimension"], d)
            self.assertEqual(sorted(r["levels"].keys()), [1, 2, 3, 4])
            for lv, signals in r["levels"].items():
                self.assertGreaterEqual(len(signals), 2)
                for s in signals:
                    self.assertNotIn("\u2014", s)

    def test_format_rubric(self):
        out = self.sb.format_rubric(self.sb.get_rubric("mentorship"))
        self.assertIn("Level 1:", out)
        self.assertIn("Level 4:", out)

    def test_format_question(self):
        q = self.sb.get_questions(dimension="scope", limit=1)[0]
        out = self.sb.format_question(q)
        self.assertIn(q["q"], out)
        self.assertIn("candid practice prompt", out)
        self.assertIn("Good signals:", out)
        self.assertIn("Follow-ups:", out)


class StaffCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from candid import staff_bank as sb
        cls.sb = sb

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.sb.main(argv)
        return rc, buf.getvalue()

    def test_questions_cli(self):
        rc, out = self._run(["questions", "--dimension", "scope", "--limit", "2"])
        self.assertEqual(rc, 0)
        self.assertIn("[scope", out)
        # exactly 2 question headers
        self.assertEqual(out.count("Source: candid practice prompt"), 2)

    def test_questions_json(self):
        import json
        rc, out = self._run(["questions", "--limit", "1", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["source"], "candid practice prompt")

    def test_rubric_list(self):
        rc, out = self._run(["rubric", "list"])
        self.assertEqual(rc, 0)
        self.assertIn("technical-judgment", out)

    def test_rubric_dimension(self):
        rc, out = self._run(["rubric", "--dimension", "org-influence"])
        self.assertEqual(rc, 0)
        self.assertIn("org-influence", out)
        self.assertIn("Level 4:", out)

    def test_rubric_missing_dimension_errors(self):
        rc, _ = self._run(["rubric"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
