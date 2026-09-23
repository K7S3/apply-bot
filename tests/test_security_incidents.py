"""Tests for candid.security_incidents (security-engineer interview track).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_incidents
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_KEYS = ("id", "title", "year", "summary", "root_cause", "lessons",
                 "interview_framing", "sources")


class SecurityIncidentsStructureTest(unittest.TestCase):
    def test_incident_count(self):
        from candid import security_incidents as S
        self.assertEqual(len(S.INCIDENTS), 8)

    def test_expected_ids_present(self):
        from candid import security_incidents as S
        ids = {i["id"] for i in S.INCIDENTS}
        for slug in ("capital-one-2019", "solarwinds-sunburst-2020",
                     "log4shell-2021", "equifax-2017", "target-2013",
                     "uber-2016", "lastpass-2022", "moveit-2023"):
            self.assertIn(slug, ids)

    def test_every_incident_has_required_keys(self):
        from candid import security_incidents as S
        for incident in S.INCIDENTS:
            for key in REQUIRED_KEYS:
                self.assertIn(key, incident, f"{incident.get('id')} missing {key}")
                self.assertTrue(incident[key], f"{incident.get('id')}.{key} is empty")

    def test_year_is_int(self):
        from candid import security_incidents as S
        for incident in S.INCIDENTS:
            self.assertIsInstance(incident["year"], int, incident["id"])

    def test_sources_nonempty_with_http_urls(self):
        from candid import security_incidents as S
        for incident in S.INCIDENTS:
            sources = incident["sources"]
            self.assertIsInstance(sources, list, incident["id"])
            self.assertGreaterEqual(len(sources), 1, incident["id"])
            for source in sources:
                self.assertIn("label", source, incident["id"])
                self.assertIn("url", source, incident["id"])
                self.assertTrue(source["url"].startswith(("http://", "https://")),
                                f"{incident['id']}: bad url {source['url']}")

    def test_lessons_are_nonempty_lists(self):
        from candid import security_incidents as S
        for incident in S.INCIDENTS:
            lessons = incident["lessons"]
            self.assertIsInstance(lessons, list, incident["id"])
            self.assertTrue(lessons, f"{incident['id']} lessons empty")
            for lesson in lessons:
                self.assertIsInstance(lesson, str)
                self.assertTrue(lesson.strip(), f"{incident['id']} empty lesson")

    def test_no_em_dashes(self):
        from candid import security_incidents as S
        for incident in S.INCIDENTS:
            for key in ("title", "summary", "root_cause", "interview_framing"):
                self.assertNotIn("\u2014", incident[key],
                                 f"{incident['id']}.{key} has em dash")
            for lesson in incident["lessons"]:
                self.assertNotIn("\u2014", lesson,
                                 f"{incident['id']} lesson has em dash")


class SecurityIncidentsApiTest(unittest.TestCase):
    def test_get_returns_incident(self):
        from candid import security_incidents as S
        inc = S.get("equifax-2017")
        self.assertEqual(inc["id"], "equifax-2017")
        self.assertEqual(inc["year"], 2017)

    def test_get_raises_on_unknown(self):
        from candid import security_incidents as S
        with self.assertRaises(KeyError):
            S.get("nonexistent-breach-2099")

    def test_list_incidents_shape(self):
        from candid import security_incidents as S
        listed = S.list_incidents()
        self.assertEqual(len(listed), len(S.INCIDENTS))
        for item in listed:
            self.assertEqual(set(item.keys()), {"id", "title", "year"})
            self.assertIsInstance(item["year"], int)

    def test_search_finds_ssrf(self):
        from candid import security_incidents as S
        results = S.search("SSRF")
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("capital-one-2019", [r["id"] for r in results])

    def test_search_case_insensitive(self):
        from candid import security_incidents as S
        self.assertEqual([r["id"] for r in S.search("ssrf")],
                         [r["id"] for r in S.search("SSRF")])

    def test_search_finds_ransomware(self):
        from candid import security_incidents as S
        results = S.search("ransomware")
        self.assertGreaterEqual(len(results), 1)

    def test_search_gibberish_returns_empty(self):
        from candid import security_incidents as S
        self.assertEqual(S.search("zxqvkwjbr"), [])


if __name__ == "__main__":
    unittest.main()
