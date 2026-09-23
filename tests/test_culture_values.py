"""Tests for candid/culture_values.py: values extractor + values-to-questions.

Run: cd ~/workspace/candid-b79a && python -m pytest tests/test_culture_values.py -q
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-culture"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import culture_values as V  # noqa: E402

BULLETED = """Our values at Acme:

- Customer obsession: start with the customer and work backwards
- Ownership: act like an owner, never say "that's not my job"
- Invent and simplify
"""

NUMBERED = """Core principles

1. Bias for action
2. Have backbone; disagree and commit
3) Deliver results
"""

PLAIN_INLINE = (
    "Our company values are integrity, teamwork, and customer focus. "
    "We treat everyone with respect."
)

PLAIN_SENTENCE = (
    "We value transparency in everything we do. "
    "We champion bold ideas."
)


class ExtractBulletsTest(unittest.TestCase):
    def test_bulleted_list_extracted(self):
        entries = V.extract_values(BULLETED, "Acme")
        self.assertEqual(len(entries), 3)

    def test_bulleted_value_names(self):
        entries = V.extract_values(BULLETED, "Acme")
        names = [e["value"] for e in entries]
        self.assertEqual(names[0], "Customer obsession")
        self.assertEqual(names[1], "Ownership")
        self.assertEqual(names[2], "Invent and simplify")

    def test_bulleted_quotes_are_verbatim(self):
        entries = V.extract_values(BULLETED, "Acme")
        for entry in entries:
            self.assertIn(entry["quote"], BULLETED,
                          f"quote not verbatim: {entry['quote']!r}")

    def test_title_split_keeps_full_quote(self):
        entries = V.extract_values(BULLETED, "Acme")
        self.assertIn("start with the customer", entries[0]["quote"])


class ExtractNumberedTest(unittest.TestCase):
    def test_numbered_list_extracted(self):
        entries = V.extract_values(NUMBERED, "Acme")
        self.assertEqual(len(entries), 3)
        names = [e["value"] for e in entries]
        self.assertEqual(names[0], "Bias for action")
        self.assertEqual(names[1], "Have backbone; disagree and commit")
        self.assertEqual(names[2], "Deliver results")

    def test_numbered_paren_style(self):
        entries = V.extract_values("Our tenets\n1) Move fast\n2) Stay humble\n",
                                   "Acme")
        self.assertEqual([e["value"] for e in entries],
                         ["Move fast", "Stay humble"])


class ExtractPlainTextTest(unittest.TestCase):
    def test_inline_declaration(self):
        entries = V.extract_values(PLAIN_INLINE, "Acme")
        names = [e["value"] for e in entries]
        self.assertEqual(names, ["integrity", "teamwork", "customer focus"])

    def test_inline_quote_is_sentence_substring(self):
        entries = V.extract_values(PLAIN_INLINE, "Acme")
        for entry in entries:
            self.assertIn(entry["quote"], PLAIN_INLINE)

    def test_we_value_sentences(self):
        entries = V.extract_values(PLAIN_SENTENCE, "Acme")
        names = [e["value"] for e in entries]
        self.assertIn("transparency in everything we do", names)
        self.assertIn("bold ideas", names)
        for entry in entries:
            self.assertIn(entry["quote"], PLAIN_SENTENCE)


class ExtractInvariantsTest(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(V.extract_values("", "Acme"), [])
        self.assertEqual(V.extract_values("   \n  ", "Acme"), [])

    def test_origin_label_flows_to_source(self):
        entries = V.extract_values(BULLETED, "Acme", origin="acme handbook PDF")
        for entry in entries:
            self.assertEqual(entry["source"], "acme handbook PDF")

    def test_default_source_label(self):
        entries = V.extract_values(BULLETED, "Acme")
        for entry in entries:
            self.assertEqual(entry["source"], "user-provided text")

    def test_duplicates_removed(self):
        text = "- Move fast\n- move fast\n- Stay humble\n"
        entries = V.extract_values(text, "Acme")
        self.assertEqual(len(entries), 2)

    def test_entry_shape(self):
        entries = V.extract_values(BULLETED, "Acme")
        for entry in entries:
            self.assertEqual(set(entry.keys()), {"value", "quote", "source"})

    def test_no_list_no_declaration_returns_empty(self):
        text = "We make software for farmers. Our office is in Berlin."
        self.assertEqual(V.extract_values(text, "Acme"), [])

    def test_value_names_are_not_empty(self):
        text = "- \n- Move fast\n"
        entries = V.extract_values(text, "Acme")
        self.assertEqual([e["value"] for e in entries], ["Move fast"])


class SaveLoadTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        base = Path(td.name)
        patcher = patch.object(C, "DATA_DIR", base)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.values = V.extract_values(BULLETED, "Acme Corp")

    def test_roundtrip(self):
        path = V.save_values("Acme Corp", self.values)
        loaded = V.load_values("Acme Corp")
        self.assertEqual(loaded, self.values)
        self.assertTrue(path.name.startswith("values_"))
        self.assertTrue(path.name.endswith(".json"))

    def test_slug_sanitizes_company_name(self):
        path = V.save_values("Acme & Sons, Inc.", self.values)
        self.assertEqual(path.name, "values_acme_sons_inc.json")

    def test_load_missing_company_returns_empty(self):
        self.assertEqual(V.load_values("Never Seen Co"), [])

    def test_save_empty_list(self):
        V.save_values("Empty Co", [])
        self.assertEqual(V.load_values("Empty Co"), [])

    def test_save_does_not_clobber_other_companies(self):
        V.save_values("Acme Corp", self.values)
        V.save_values("Beta LLC", [{"value": "Speed", "quote": "Speed",
                                   "source": "x"}])
        self.assertEqual(len(V.load_values("Acme Corp")), 3)
        self.assertEqual(len(V.load_values("Beta LLC")), 1)


class QuestionsTest(unittest.TestCase):
    def setUp(self):
        self.values = V.extract_values(BULLETED, "Acme")

    def test_question_count_matches_values(self):
        questions = V.values_to_questions(self.values)
        self.assertEqual(len(questions), 3)

    def test_question_shape(self):
        questions = V.values_to_questions(self.values)
        for q in questions:
            self.assertEqual(set(q.keys()),
                             {"question", "targets_value", "source"})

    def test_targets_value_matches(self):
        questions = V.values_to_questions(self.values)
        self.assertEqual(questions[0]["targets_value"], "Customer obsession")

    def test_value_name_embedded_in_question(self):
        questions = V.values_to_questions(self.values)
        self.assertIn("Customer obsession", questions[0]["question"])

    def test_labeled_as_generated_not_real(self):
        questions = V.values_to_questions(self.values)
        for q in questions:
            self.assertIn("generated", q["source"].lower())
            self.assertNotIn("asked", q["source"].lower())

    def test_templates_rotate(self):
        many = [{"value": f"value {i}", "quote": f"value {i}",
                 "source": "x"} for i in range(7)]
        questions = V.values_to_questions(many)
        texts = [q["question"] for q in questions]
        self.assertGreater(len(set(texts)), 1)

    def test_accepts_plain_strings(self):
        questions = V.values_to_questions(["Integrity", "Speed"])
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["targets_value"], "Integrity")

    def test_empty_input_returns_empty(self):
        self.assertEqual(V.values_to_questions([]), [])

    def test_blank_values_skipped(self):
        questions = V.values_to_questions(["", "  ", "Integrity"])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["targets_value"], "Integrity")


class TestInlineNumberedExtraction(unittest.TestCase):
    def test_single_line_enumeration(self):
        text = ("Our values: 1. Customer obsession: we start with the customer. "
                "2. Ownership: we act like owners.")
        vals = V.extract_values(text, "Acme")
        self.assertEqual([v["value"] for v in vals],
                         ["Customer obsession", "Ownership"])
        for v in vals:
            self.assertIn(v["quote"], text)

    def test_paren_style_inline(self):
        text = "We live by (1) transparency (2) humility every day."
        vals = V.extract_values(text, "Acme")
        self.assertEqual([v["value"] for v in vals],
                         ["transparency", "humility every day"])

    def test_single_stray_marker_does_not_fire(self):
        self.assertEqual(V.extract_values("I joined in 2021. It was great.",
                                          "Acme"), [])

    def test_multiline_lists_still_take_priority(self):
        text = "- Ownership\n- Trust\nOur values: 1. Speed 2. Focus."
        vals = V.extract_values(text, "Acme")
        self.assertEqual([v["value"] for v in vals], ["Ownership", "Trust"])


if __name__ == "__main__":
    unittest.main()
