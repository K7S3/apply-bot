"""Tests for candid.security_loop (security interview loop descriptions).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_loop
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import security_loop as SL


class LoopsTest(unittest.TestCase):
    def test_expected_slugs(self):
        for slug in ("startup", "bigtech", "fintech", "consulting"):
            self.assertIn(slug, SL.LOOPS)

    def test_loop_shape(self):
        for slug, loop in SL.LOOPS.items():
            for key in ("label", "rounds", "notes"):
                self.assertIn(key, loop, f"{slug} missing {key}")
            self.assertIsInstance(loop["rounds"], list)

    def test_round_count_range(self):
        for slug, loop in SL.LOOPS.items():
            self.assertTrue(4 <= len(loop["rounds"]) <= 6,
                            f"{slug} has {len(loop['rounds'])} rounds, expected 4-6")

    def test_round_shape(self):
        for slug, loop in SL.LOOPS.items():
            for rnd in loop["rounds"]:
                for key in ("name", "focus", "tips"):
                    self.assertIn(key, rnd, f"{slug}/{rnd.get('name')} missing {key}")
                self.assertTrue(rnd["name"].strip())
                self.assertTrue(rnd["focus"].strip())
                self.assertIsInstance(rnd["tips"], list)
                self.assertTrue(1 <= len(rnd["tips"]) <= 2,
                                f"{slug}/{rnd['name']} should have 1-2 tips")
                for tip in rnd["tips"]:
                    self.assertTrue(tip.strip())

    def test_each_loop_has_core_round_types(self):
        for slug, loop in SL.LOOPS.items():
            names = " ".join(r["name"].lower() for r in loop["rounds"])
            self.assertIn("recruiter", names, f"{slug} missing recruiter screen")
            self.assertTrue("behavioral" in names or "manager" in names,
                            f"{slug} missing a behavioral/manager round")

    def test_bigtech_has_threat_model_round(self):
        names = " ".join(r["name"].lower() for r in SL.LOOPS["bigtech"]["rounds"])
        self.assertIn("threat", names)

    def test_consulting_has_presentation_round(self):
        names = " ".join(r["name"].lower() for r in SL.LOOPS["consulting"]["rounds"])
        self.assertTrue("report" in names or "presentation" in names)

    def test_notes_nonempty(self):
        for slug, loop in SL.LOOPS.items():
            self.assertTrue(loop["notes"].strip())

    def test_get_loop_ok(self):
        loop = SL.get_loop("fintech")
        self.assertIn("Fintech", loop["label"])

    def test_get_loop_unknown_raises(self):
        with self.assertRaises(ValueError):
            SL.get_loop("government")

    def test_loop_names(self):
        names = SL.loop_names()
        self.assertEqual(sorted(names), ["bigtech", "consulting", "fintech", "startup"])


if __name__ == "__main__":
    unittest.main()
