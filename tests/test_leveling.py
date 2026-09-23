"""Tests for candid.leveling: guides, scope, ladder, translation, comparison.

Run: CANDID_DATA_DIR=/tmp/candid-test-leveling python3 -m unittest tests.test_leveling -v
"""
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-leveling"

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import leveling as L


class ListCompaniesTest(unittest.TestCase):
    def test_six_companies(self):
        cos = L.list_companies()
        keys = {c["key"] for c in cos}
        self.assertEqual(keys, {"meta", "google", "amazon", "microsoft", "apple", "startup"})

    def test_each_has_levels(self):
        for co in L.list_companies():
            self.assertTrue(co["levels"], co["key"])

    def test_meta_has_e3_to_e7(self):
        meta = next(c for c in L.list_companies() if c["key"] == "meta")
        self.assertEqual(meta["levels"], ["E3", "E4", "E5", "E6", "E7"])


class NormalizeTest(unittest.TestCase):
    def test_alias_facebook(self):
        self.assertEqual(L.normalize_company("facebook"), "meta")

    def test_alias_aws(self):
        self.assertEqual(L.normalize_company("aws"), "amazon")

    def test_case_insensitive(self):
        self.assertEqual(L.normalize_company("GOOGLE"), "google")

    def test_unknown_company_raises(self):
        with self.assertRaises(L.LevelingError):
            L.normalize_company("initech")

    def test_level_by_code_case_insensitive(self):
        lv = L.normalize_level("meta", "e5")
        self.assertEqual(lv["code"], "E5")

    def test_level_by_alias(self):
        lv = L.normalize_level("meta", "senior")
        self.assertEqual(lv["code"], "E5")

    def test_level_by_number(self):
        lv = L.normalize_level("google", "5")
        self.assertEqual(lv["code"], "L5")

    def test_level_amazon_named(self):
        lv = L.normalize_level("amazon", "SDE III")
        self.assertEqual(lv["code"], "SDE III")

    def test_unknown_level_raises(self):
        with self.assertRaises(L.LevelingError):
            L.normalize_level("meta", "E99")


class GuideScopeTest(unittest.TestCase):
    def test_guide_returns_company(self):
        co = L.get_guide("meta")
        self.assertEqual(co["name"], "Meta")

    def test_scope_expectations(self):
        lv, co = L.scope_expectations("meta", "E5")
        self.assertEqual(lv["code"], "E5")
        self.assertTrue(lv["scope"])
        self.assertTrue(lv["promo_criteria"])
        self.assertEqual(co["name"], "Meta")

    def test_levels_ascending_rung(self):
        for key in ("meta", "google", "amazon", "microsoft", "apple", "startup"):
            rungs = [lv["rung"] for lv in L.get_guide(key)["levels"]]
            self.assertEqual(rungs, sorted(rungs), key)

    def test_next_level(self):
        nxt = L.next_level("meta", "E4")
        self.assertEqual(nxt["code"], "E5")

    def test_next_level_at_top_is_none(self):
        self.assertIsNone(L.next_level("meta", "E7"))

    def test_disclaimer_present(self):
        self.assertIn("approximation", L.disclaimer().lower())


class TranslateTest(unittest.TestCase):
    def test_e5_to_google_l5(self):
        t = L.translate_level("meta", "E5", "google")
        self.assertEqual(t["to"]["code"], "L5")

    def test_e5_to_amazon_sde3(self):
        t = L.translate_level("meta", "E5", "amazon")
        self.assertEqual(t["to"]["code"], "SDE III")

    def test_e6_to_google_l6(self):
        t = L.translate_level("meta", "E6", "google")
        self.assertEqual(t["to"]["code"], "L6")

    def test_msft_64_to_meta_e6(self):
        t = L.translate_level("microsoft", "64", "meta")
        self.assertEqual(t["to"]["code"], "E6")

    def test_caveats_present(self):
        t = L.translate_level("meta", "E5", "google")
        self.assertTrue(t["caveats"])
        self.assertIn("rung", t)


class CompareTest(unittest.TestCase):
    def test_compare_e4_e5(self):
        c = L.compare_levels("meta", "E4", "E5")
        self.assertEqual(c["from"]["code"], "E4")
        self.assertEqual(c["to"]["code"], "E5")
        self.assertTrue(c["new_scope"])
        self.assertTrue(c["promo_criteria"])

    def test_new_scope_not_in_source(self):
        c = L.compare_levels("meta", "E4", "E5")
        src = set(c["from"]["scope"])
        for b in c["new_scope"]:
            self.assertNotIn(b, src)


class RenderTest(unittest.TestCase):
    def test_render_guide(self):
        out = L.render_guide("google")
        self.assertIn("L5", out)
        self.assertIn("Senior Software Engineer", out)

    def test_render_ladder(self):
        out = L.render_ladder("meta")
        self.assertIn("E7", out)
        self.assertIn("E3", out)
        # top of ladder first
        self.assertLess(out.index("E7"), out.index("E3"))

    def test_render_scope(self):
        out = L.render_scope("amazon", "SDE II")
        self.assertIn("Scope expectations", out)
        self.assertIn("Promotion criteria", out)

    def test_render_translation(self):
        out = L.render_translation("meta", "E5", "google")
        self.assertIn("L5", out)
        self.assertIn("Caveats", out)

    def test_render_compare(self):
        out = L.render_compare("meta", "E4", "E5")
        self.assertIn("E4 -> E5", out)

    def test_render_company_list(self):
        out = L.render_company_list()
        self.assertIn("meta", out)
        self.assertIn("startup", out)


if __name__ == "__main__":
    unittest.main()
