"""Tests for candid.security_gaps (self-assessment to study plan).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_gaps
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import security_gaps as SG


def _all_ids(ratings):
    return {d["id"] for d in SG.DOMAINS}


class DomainsTest(unittest.TestCase):
    def test_ten_domains(self):
        self.assertEqual(len(SG.DOMAINS), 10)

    def test_domain_shape(self):
        for d in SG.DOMAINS:
            for key in ("id", "name", "description", "concept_refs", "question_category"):
                self.assertIn(key, d)
            self.assertIsInstance(d["concept_refs"], list)
            self.assertTrue(d["concept_refs"])

    def test_expected_ids(self):
        ids = {d["id"] for d in SG.DOMAINS}
        for expected in ("appsec", "cloudsec", "threat-modeling", "crypto",
                         "incident-response", "iam", "detection",
                         "network-security", "supply-chain", "governance"):
            self.assertIn(expected, ids)

    def test_unique_ids(self):
        ids = [d["id"] for d in SG.DOMAINS]
        self.assertEqual(len(ids), len(set(ids)))


class AssessTest(unittest.TestCase):
    def _ratings(self, **over):
        base = {d["id"]: 3 for d in SG.DOMAINS}
        base.update(over)
        return base

    def test_priority_logic(self):
        result = SG.assess(self._ratings(appsec=1, cloudsec=2, crypto=3, iam=4, detection=5))
        by_id = {e["domain"]: e for e in result["plan"]}
        self.assertEqual(by_id["appsec"]["priority"], "high")
        self.assertEqual(by_id["cloudsec"]["priority"], "high")
        self.assertEqual(by_id["crypto"]["priority"], "medium")
        self.assertEqual(by_id["iam"]["priority"], "low")
        self.assertEqual(by_id["detection"]["priority"], "low")

    def test_weakest_lists_rating_2_and_below(self):
        result = SG.assess(self._ratings(appsec=1, cloudsec=2, crypto=3, iam=4))
        self.assertEqual(sorted(result["weakest"]), ["appsec", "cloudsec"])

    def test_high_priority_sorted_first(self):
        result = SG.assess(self._ratings(appsec=4, cloudsec=5, crypto=3, iam=1))
        priorities = [e["priority"] for e in result["plan"]]
        self.assertEqual(priorities[0], "high")
        self.assertIn("iam", result["plan"][0]["domain"])

    def test_actions_reference_concepts_and_practice(self):
        result = SG.assess(self._ratings(appsec=2))
        entry = next(e for e in result["plan"] if e["domain"] == "appsec")
        self.assertGreaterEqual(len(entry["actions"]), 2)
        blob = " ".join(entry["actions"])
        self.assertIn("owasp_top_10", blob)
        self.assertIn("practice", blob.lower())

    def test_rating_out_of_range_raises(self):
        for bad in (0, 6, -1):
            with self.assertRaises(ValueError):
                SG.assess(self._ratings(appsec=bad))

    def test_non_int_rating_raises(self):
        with self.assertRaises(ValueError):
            SG.assess(self._ratings(appsec="3"))
        with self.assertRaises(ValueError):
            SG.assess(self._ratings(appsec=2.5))
        with self.assertRaises(ValueError):
            SG.assess(self._ratings(appsec=True))

    def test_unknown_domain_raises(self):
        with self.assertRaises(ValueError):
            SG.assess({"appsec": 3, "rocket-science": 4})

    def test_partial_ratings_ok(self):
        result = SG.assess({"appsec": 2, "iam": 5})
        self.assertEqual(len(result["plan"]), 2)
        self.assertEqual(result["weakest"], ["appsec"])

    def test_empty_ratings(self):
        result = SG.assess({})
        self.assertEqual(result["plan"], [])
        self.assertEqual(result["weakest"], [])


if __name__ == "__main__":
    unittest.main()
