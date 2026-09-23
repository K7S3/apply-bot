"""Tests for candid.security_concepts (security-engineer interview track).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_concepts
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_KEYS = ("title", "summary", "key_points", "interview_angles",
                 "related_categories")


class SecurityConceptsStructureTest(unittest.TestCase):
    def test_concept_count(self):
        from candid import security_concepts as S
        self.assertEqual(len(S.SECURITY_CONCEPTS), 14)

    def test_expected_slugs_present(self):
        from candid import security_concepts as S
        for slug in ("owasp-top-10", "authentication", "oauth2-oidc", "tls",
                     "crypto-primitives", "password-hashing", "zero-trust",
                     "supply-chain-security", "detection-soc", "cloud-iam",
                     "network-security", "web-security-headers",
                     "secrets-management", "secure-sdlc"):
            self.assertIn(slug, S.SECURITY_CONCEPTS)

    def test_every_concept_has_required_keys(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            for key in REQUIRED_KEYS:
                self.assertIn(key, concept, f"{slug} missing {key}")
                self.assertTrue(concept[key], f"{slug}.{key} is empty")

    def test_title_and_summary_are_nonempty_strings(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            self.assertIsInstance(concept["title"], str)
            self.assertTrue(concept["title"].strip(), slug)
            self.assertIsInstance(concept["summary"], str)
            self.assertTrue(concept["summary"].strip(), slug)

    def test_key_points_and_angles_are_nonempty_lists(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            for key in ("key_points", "interview_angles"):
                val = concept[key]
                self.assertIsInstance(val, list, f"{slug}.{key}")
                self.assertTrue(len(val) >= 2, f"{slug}.{key} too short")
                for item in val:
                    self.assertIsInstance(item, str)
                    self.assertTrue(item.strip(), f"{slug}.{key} blank item")

    def test_key_point_count_in_range(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            n = len(concept["key_points"])
            self.assertTrue(4 <= n <= 8, f"{slug}: {n} key_points")

    def test_interview_angle_count_in_range(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            n = len(concept["interview_angles"])
            self.assertTrue(2 <= n <= 4, f"{slug}: {n} interview_angles")

    def test_related_categories_valid(self):
        from candid import security_concepts as S
        valid = {"appsec", "cloudsec", "threat-modeling", "crypto",
                 "incident-response", "iam-network", "detection",
                 "behavioral"}
        for slug, concept in S.SECURITY_CONCEPTS.items():
            cats = concept["related_categories"]
            self.assertIsInstance(cats, list, slug)
            self.assertTrue(cats, f"{slug} has no categories")
            for cat in cats:
                self.assertIn(cat, valid, f"{slug}: bad category {cat!r}")

    def test_no_em_dashes_anywhere(self):
        from candid import security_concepts as S
        for slug, concept in S.SECURITY_CONCEPTS.items():
            blobs = [concept["title"], concept["summary"]]
            blobs += concept["key_points"] + concept["interview_angles"]
            for blob in blobs:
                self.assertNotIn("\u2014", blob, f"{slug} has em dash")


class SecurityConceptsApiTest(unittest.TestCase):
    def test_get_returns_right_concept(self):
        from candid import security_concepts as S
        concept = S.get("tls")
        self.assertIs(S.SECURITY_CONCEPTS["tls"], concept)
        self.assertEqual(concept["title"],
                         "TLS: How Encrypted Transport Actually Works")

    def test_get_raises_on_unknown(self):
        from candid import security_concepts as S
        with self.assertRaises((KeyError, ValueError)):
            S.get("not-a-real-concept")

    def test_names_matches_dict_keys(self):
        from candid import security_concepts as S
        self.assertEqual(S.names(), list(S.SECURITY_CONCEPTS.keys()))
        self.assertEqual(len(S.names()), 14)


if __name__ == "__main__":
    unittest.main()
