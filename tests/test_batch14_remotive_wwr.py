"""Hermetic tests for the Remotive and We Work Remotely adapters.

No live network: HTTP layers are patched with fixture payloads.
Run: python -m unittest tests.test_batch14_remotive_wwr -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


REMOTIVE_PAYLOAD = {
    "job-count": 2,
    "jobs": [
        {
            "id": 2091141,
            "title": "Frontend Web Application Developer",
            "company_name": "KoboToolbox",
            "category": "Design",
            "job_type": "full_time",
            "salary": "$90k - $105k",
            "candidate_required_location": "USA, Canada",
            "publication_date": "2026-09-18T16:43:22",
            "url": "https://remotive.com/remote-jobs/design/frontend-2091141",
            "description": "<p>Build <strong>React</strong> apps &amp; dashboards.</p>",
        },
        {
            "id": 2091150,
            "title": "Backend Engineer",
            "company_name": "",
            "category": "",
            "job_type": "",
            "salary": None,
            "candidate_required_location": "",
            "publication_date": "",
            "url": "",
            "description": "x" * 5000,
        },
    ],
}

WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WWR programming</title>
    <item>
      <title>Lemon.io: Senior .NET Full-stack Developer</title>
      <region>Anywhere in the World</region>
      <category>Full-Stack Programming</category>
      <description>&lt;p&gt;Remote job for &lt;strong&gt;senior&lt;/strong&gt; devs.&lt;/p&gt;</description>
      <pubDate>Tue, 08 Sep 2026 13:49:13 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/lemon-io-senior-net</link>
      <guid>https://weworkremotely.com/remote-jobs/lemon-io-senior-net</guid>
    </item>
    <item>
      <title>Staff DevOps Engineer</title>
      <region>Remote</region>
      <category>DevOps / Sysadmin</category>
      <description>Plain text, no HTML.</description>
      <pubDate>Mon, 07 Sep 2026 10:00:00 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/staff-devops</link>
      <guid>https://weworkremotely.com/remote-jobs/staff-devops</guid>
    </item>
  </channel>
</rss>"""

REQUIRED_KEYS = {"source", "source_id", "title", "company", "location", "url",
                 "description", "salary_text", "remote", "posted_at"}


class RemotiveTest(unittest.TestCase):
    def setUp(self):
        from candid import jobs as J
        self.J = J

    def _adapt(self, payload, **kwargs):
        with patch.object(self.J, "_get_json", return_value=payload) as m:
            out = self.J._adapt_remotive(**kwargs)
        return out, m

    def test_normalization(self):
        out, _ = self._adapt(REMOTIVE_PAYLOAD)
        self.assertEqual(len(out), 2)
        j = out[0]
        self.assertEqual(REQUIRED_KEYS, set(j.keys()))
        self.assertEqual(j["source"], "remotive")
        self.assertEqual(j["source_id"], "remotive:2091141")
        self.assertEqual(j["title"], "Frontend Web Application Developer")
        self.assertEqual(j["company"], "KoboToolbox")
        self.assertEqual(j["location"], "USA, Canada")
        self.assertEqual(j["url"],
                         "https://remotive.com/remote-jobs/design/frontend-2091141")
        self.assertEqual(j["salary_text"], "$90k - $105k")
        self.assertTrue(j["remote"])
        self.assertEqual(j["posted_at"], "2026-09-18T16:43:22")

    def test_html_stripped_and_capped(self):
        out, _ = self._adapt(REMOTIVE_PAYLOAD)
        desc = out[0]["description"]
        self.assertNotIn("<", desc)
        self.assertNotIn(">", desc)
        self.assertIn("React", desc)
        self.assertEqual(len(out[1]["description"]), 4000)

    def test_job_type_and_category_captured(self):
        out, _ = self._adapt(REMOTIVE_PAYLOAD)
        self.assertIn("full time", out[0]["description"])
        self.assertIn("Design", out[0]["description"])
        # sparse job: missing fields degrade gracefully
        j = out[1]
        self.assertEqual(j["company"], "")
        self.assertEqual(j["location"], "Remote")
        self.assertEqual(j["salary_text"], "")
        self.assertEqual(j["source_id"], "remotive:2091150")

    def test_source_id_stability(self):
        out1, _ = self._adapt(REMOTIVE_PAYLOAD)
        out2, _ = self._adapt(REMOTIVE_PAYLOAD)
        self.assertEqual([j["source_id"] for j in out1],
                         [j["source_id"] for j in out2])

    def test_search_param_hits_api(self):
        out, mock_get = self._adapt(REMOTIVE_PAYLOAD, search="backend engineer")
        called_url = mock_get.call_args[0][0]
        self.assertIn("search=", called_url)
        self.assertIn("backend+engineer", called_url)
        self.assertEqual(len(out), 2)

    def test_max_per_source(self):
        big = {"jobs": [dict(REMOTIVE_PAYLOAD["jobs"][0], id=i) for i in range(150)]}
        out, _ = self._adapt(big)
        self.assertEqual(len(out), 100)

    def test_malformed_payload_raises(self):
        for bad in ({"jobs": "nope"}, {"no-jobs": []}, [1, 2], "garbage"):
            with patch.object(self.J, "_get_json", return_value=bad):
                with self.assertRaises(self.J.JobsError):
                    self.J._adapt_remotive()

    def test_unreachable_raises(self):
        with patch.object(self.J, "_get_json", side_effect=OSError("down")):
            with self.assertRaises(self.J.JobsError):
                self.J._adapt_remotive()


class WeWorkRemotelyTest(unittest.TestCase):
    def setUp(self):
        from candid import jobs as J
        self.J = J

    def _adapt(self, rss_text, **kwargs):
        with patch.object(self.J, "_get_text", return_value=rss_text) as m:
            out = self.J._adapt_weworkremotely(**kwargs)
        return out, m

    def test_company_parsing_from_title(self):
        out, _ = self._adapt(WWR_RSS, categories=["https://example.com/one.rss"])
        self.assertEqual(len(out), 2)
        j = out[0]
        self.assertEqual(REQUIRED_KEYS, set(j.keys()))
        self.assertEqual(j["source"], "weworkremotely")
        self.assertEqual(j["company"], "Lemon.io")
        self.assertEqual(j["title"], "Senior .NET Full-stack Developer")
        self.assertEqual(j["source_id"],
                         "weworkremotely:https://weworkremotely.com/remote-jobs/lemon-io-senior-net")
        self.assertTrue(j["remote"])
        self.assertEqual(j["location"], "Anywhere in the World")
        self.assertEqual(j["posted_at"], "Tue, 08 Sep 2026 13:49:13 +0000")

    def test_title_without_colon(self):
        out, _ = self._adapt(WWR_RSS)
        j = out[1]
        self.assertEqual(j["company"], "")
        self.assertEqual(j["title"], "Staff DevOps Engineer")

    def test_html_stripped_and_entities_decoded(self):
        out, _ = self._adapt(WWR_RSS)
        desc = out[0]["description"]
        self.assertNotIn("<", desc)
        self.assertIn("senior devs", desc)
        self.assertIn("Full-Stack Programming", desc)  # category captured
        self.assertLessEqual(len(desc), 4000)

    def test_source_id_stability(self):
        out1, _ = self._adapt(WWR_RSS)
        out2, _ = self._adapt(WWR_RSS)
        self.assertEqual([j["source_id"] for j in out1],
                         [j["source_id"] for j in out2])

    def test_custom_categories(self):
        custom = ["https://example.com/custom.rss", "https://example.com/other.rss"]
        with patch.object(self.J, "_get_text", return_value=WWR_RSS) as m:
            out = self.J._adapt_weworkremotely(categories=custom)
        self.assertEqual([c[0][0] for c in m.call_args_list], custom)
        self.assertEqual(len(out), 4)  # 2 items x 2 feeds

    def test_default_fetches_three_feeds(self):
        with patch.object(self.J, "_get_text", return_value=WWR_RSS) as m:
            self.J._adapt_weworkremotely()
        urls = [c[0][0] for c in m.call_args_list]
        self.assertEqual(len(urls), 3)
        self.assertTrue(all(u.endswith(".rss") for u in urls))
        self.assertTrue(any("programming" in u for u in urls))
        self.assertTrue(any("devops" in u for u in urls))
        self.assertTrue(any("product" in u for u in urls))

    def test_malformed_xml_raises(self):
        with patch.object(self.J, "_get_text", return_value="not <xml>"):
            with self.assertRaises(self.J.JobsError):
                self.J._adapt_weworkremotely()

    def test_unreachable_raises(self):
        with patch.object(self.J, "_get_text", side_effect=OSError("down")):
            with self.assertRaises(self.J.JobsError):
                self.J._adapt_weworkremotely()


class AdapterRegistrationTest(unittest.TestCase):
    def test_both_registered(self):
        from candid import jobs as J
        self.assertIs(J.ADAPTERS["remotive"], J._adapt_remotive)
        self.assertIs(J.ADAPTERS["weworkremotely"], J._adapt_weworkremotely)
        # every adapter returns lists of fully-normalized dicts or JobsError
        with patch.object(J, "_get_json", return_value=REMOTIVE_PAYLOAD):
            for j in J._adapt_remotive():
                self.assertEqual(REQUIRED_KEYS, set(j.keys()))
                self.assertTrue(j["source_id"].startswith("remotive:"))
        with patch.object(J, "_get_text", return_value=WWR_RSS):
            for j in J._adapt_weworkremotely(categories=["https://example.com/x.rss"]):
                self.assertEqual(REQUIRED_KEYS, set(j.keys()))
                self.assertTrue(j["source_id"].startswith("weworkremotely:"))


if __name__ == "__main__":
    unittest.main()
