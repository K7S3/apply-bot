"""Tests for the secure system-design drills (security track).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_design
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class DrillStructureTest(unittest.TestCase):
    def test_eight_drills_present(self):
        from candid import security_design as SD
        self.assertGreaterEqual(len(SD.DRILLS), 8)

    def test_drill_ids_unique(self):
        from candid import security_design as SD
        ids = [d["id"] for d in SD.DRILLS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_drill_has_content(self):
        from candid import security_design as SD
        for drill in SD.DRILLS:
            with self.subTest(drill=drill["id"]):
                self.assertTrue(drill["id"])
                self.assertTrue(drill["title"])
                self.assertTrue(drill["prompt"].strip(), "prompt non-empty")
                self.assertGreaterEqual(len(drill["checklist"]), 6)
                for item in drill["checklist"]:
                    self.assertTrue(item.strip())
                self.assertGreaterEqual(len(drill["followups"]), 2)
                for q in drill["followups"]:
                    self.assertTrue(q.strip())

    def test_get_drill_roundtrip(self):
        from candid import security_design as SD
        for drill in SD.DRILLS:
            self.assertIs(SD.get_drill(drill["id"]), drill)

    def test_get_drill_unknown_raises(self):
        from candid import security_design as SD
        with self.assertRaises(ValueError):
            SD.get_drill("no-such-drill")


class ScoreChecklistTest(unittest.TestCase):
    def setUp(self):
        from candid import security_design as SD
        self.SD = SD
        self.did = SD.DRILLS[0]["id"]
        self.total = len(SD.get_drill(self.did)["checklist"])

    def test_full_marks(self):
        r = self.SD.score_checklist(self.did, list(range(self.total)))
        self.assertEqual(r["covered"], self.total)
        self.assertEqual(r["total"], self.total)
        self.assertEqual(r["pct"], 100.0)
        self.assertEqual(r["missed"], [])
        self.assertEqual(r["verdict"], "strong")

    def test_empty(self):
        r = self.SD.score_checklist(self.did, [])
        self.assertEqual(r["covered"], 0)
        self.assertEqual(r["pct"], 0.0)
        self.assertEqual(len(r["missed"]), self.total)
        self.assertEqual(r["verdict"], "needs work")

    def test_boundary_strong_at_80(self):
        # 8/10 = 80 -> strong; 7/10 = 70 -> developing; 4/10 = 40 -> needs work
        from candid import security_design as SD
        drill = SD.get_drill("secure-webhook-receiver")  # 8 checklist items
        total = len(drill["checklist"])
        self.assertEqual(total, 8)
        r = self.SD.score_checklist(drill["id"], list(range(total)))
        self.assertEqual(r["verdict"], "strong")

    def test_boundary_verdicts(self):
        # first drill has 9 checklist items:
        # 8/9 ~= 88.9 -> strong; 5/9 ~= 55.6 -> developing; 4/9 ~= 44.4 -> needs work
        self.assertEqual(self.total, 9)
        r = self.SD.score_checklist(self.did, list(range(8)))
        self.assertAlmostEqual(r["pct"], 8 / 9 * 100)
        self.assertEqual(r["verdict"], "strong")
        r = self.SD.score_checklist(self.did, list(range(5)))
        self.assertGreaterEqual(r["pct"], 50)
        self.assertLess(r["pct"], 80)
        self.assertEqual(r["verdict"], "developing")
        r = self.SD.score_checklist(self.did, list(range(4)))
        self.assertLess(r["pct"], 50)
        self.assertEqual(r["verdict"], "needs work")

    def test_out_of_range_indices_ignored(self):
        r = self.SD.score_checklist(self.did, [0, 1, -1, self.total,
                                               999, self.total + 5])
        self.assertEqual(r["covered"], 2)
        self.assertEqual(len(r["missed"]), self.total - 2)

    def test_duplicate_indices_count_once(self):
        r = self.SD.score_checklist(self.did, [0, 0, 0])
        self.assertEqual(r["covered"], 1)

    def test_missed_lists_unchecked_items(self):
        drill = self.SD.get_drill(self.did)
        r = self.SD.score_checklist(self.did, [0])
        self.assertEqual(r["missed"], drill["checklist"][1:])

    def test_unknown_drill_raises(self):
        with self.assertRaises(ValueError):
            self.SD.score_checklist("nope", [0])


class RunDrillTest(unittest.TestCase):
    def test_run_drill_all_yes(self):
        from candid import security_design as SD
        drill = SD.DRILLS[0]
        total = len(drill["checklist"])
        with patch("builtins.input", side_effect=["y"] * total):
            with patch("builtins.print") as mock_print:
                SD.run_drill(drill["id"])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list
                           if c.args)
        self.assertIn("strong", printed)
        self.assertIn(drill["title"], printed)
        self.assertIn(drill["followups"][0][:20], printed)

    def test_run_drill_all_no(self):
        from candid import security_design as SD
        drill = SD.DRILLS[0]
        total = len(drill["checklist"])
        with patch("builtins.input", side_effect=["n"] * total):
            with patch("builtins.print") as mock_print:
                SD.run_drill(drill["id"])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list
                           if c.args)
        self.assertIn("needs work", printed)

    def test_run_drill_lists_then_selects_by_number(self):
        from candid import security_design as SD
        drill = SD.DRILLS[1]
        total = len(drill["checklist"])
        with patch("builtins.input",
                   side_effect=["2"] + ["y"] * total):
            with patch("builtins.print") as mock_print:
                SD.run_drill()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list
                           if c.args)
        self.assertIn(drill["title"], printed)

    def test_run_drill_unknown_id_raises(self):
        from candid import security_design as SD
        with self.assertRaises(ValueError):
            SD.run_drill("no-such-drill")


if __name__ == "__main__":
    unittest.main()
