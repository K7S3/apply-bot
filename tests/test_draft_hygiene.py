"""Tests for candid.drafting.hygiene (quality checks + send time)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import hygiene as H


CLEAN_DRAFT = {
    "subject": "Quick intro",
    "body": ("Hi Jane,\n\nI saw the senior ML engineer posting and would love "
             "to discuss my background.\n\nBest,\nKeshavan"),
}


def checks_of(draft):
    return {f["check"]: f for f in H.check(draft)}


class HygieneCheckTest(unittest.TestCase):
    def test_clean_draft_passes(self):
        self.assertEqual(H.check(CLEAN_DRAFT), [])

    def test_missing_subject_is_error(self):
        f = checks_of({"subject": "", "body": CLEAN_DRAFT["body"]})
        self.assertIn("subject_present", f)
        self.assertEqual(f["subject_present"]["severity"], "error")

    def test_long_subject_warns(self):
        f = checks_of({"subject": "x" * 61, "body": CLEAN_DRAFT["body"]})
        self.assertIn("subject_length", f)
        self.assertEqual(f["subject_length"]["severity"], "warn")

    def test_subject_at_boundary_ok(self):
        f = checks_of({"subject": "x" * 60, "body": CLEAN_DRAFT["body"]})
        self.assertNotIn("subject_length", f)

    def test_long_body_warns(self):
        f = checks_of({"subject": "s", "body": "word " * 250})
        self.assertIn("body_length", f)
        self.assertEqual(f["body_length"]["severity"], "warn")

    def test_body_at_boundary_ok(self):
        body = "Hi Jane,\n\n" + "word " * 196 + "\n\nBest,\nKeshavan"
        f = checks_of({"subject": "s", "body": body})
        self.assertNotIn("body_length", f)

    def test_spam_words_fire(self):
        f = checks_of({"subject": "s",
                       "body": "Hi Jane,\n\nThis is a free offer, I guarantee it. "
                               "Act now!\n\nBest,\nKeshavan"})
        self.assertIn("spam_words", f)
        self.assertEqual(f["spam_words"]["severity"], "warn")
        self.assertTrue(any(w in f["spam_words"]["message"]
                            for w in ("free", "guarantee", "act now")))

    def test_exclamation_marks_fire(self):
        f = checks_of({"subject": "s",
                       "body": "Hi Jane,\n\nGreat news!!! Let's talk!!!\n\nBest,\nKeshavan"})
        self.assertIn("exclamation_marks", f)
        self.assertEqual(f["exclamation_marks"]["severity"], "warn")

    def test_two_exclamations_ok(self):
        f = checks_of({"subject": "s",
                       "body": "Hi Jane,\n\nGreat news! Let's talk!\n\nBest,\nKeshavan"})
        self.assertNotIn("exclamation_marks", f)

    def test_excessive_caps_fires(self):
        f = checks_of({"subject": "s",
                       "body": "HI JANE THIS IS VERY IMPORTANT PLEASE READ IT NOW"})
        self.assertIn("excessive_caps", f)

    def test_missing_greeting_is_info(self):
        f = checks_of({"subject": "s",
                       "body": "Wanted to reach out about the role.\n\nBest,\nKeshavan"})
        self.assertIn("greeting_present", f)
        self.assertEqual(f["greeting_present"]["severity"], "info")

    def test_missing_signoff_is_info(self):
        f = checks_of({"subject": "s",
                       "body": "Hi Jane,\n\nWanted to reach out about the role."})
        self.assertIn("signoff_present", f)
        self.assertEqual(f["signoff_present"]["severity"], "info")

    def test_findings_have_required_keys(self):
        findings = H.check({"subject": "", "body": ""})
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(set(finding.keys()), {"check", "severity", "message"})


class BestSendTimeTest(unittest.TestCase):
    def test_best_send_time_shape_and_content(self):
        t = H.best_send_time()
        self.assertEqual(set(t.keys()), {"weekday", "window", "rationale"})
        self.assertEqual(t["weekday"], "Tuesday-Thursday")
        self.assertEqual(t["window"], "9:00-11:00 AM")
        self.assertIn("local timezone", t["rationale"])


if __name__ == "__main__":
    unittest.main()
