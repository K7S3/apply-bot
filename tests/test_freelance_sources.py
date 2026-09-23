"""Tests for candid.freelance_sources — remotive, weworkremotely, workingnomads.

All fixture-based; no live network. The feed fetchers
(``_get_json`` / ``_get_xml``) are patched with canned payloads matching
the real shapes observed live on 2026-09-22. Run:
    python -m pytest tests/test_freelance_sources.py -q
"""

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import freelance_sources as fs


# ---------------------------------------------------------------------------
# fixtures — match the real shapes observed live on 2026-09-22
# ---------------------------------------------------------------------------

REMOTIVE_FIXTURE = {
    "0-legal-notice": "If you are reading this, you are fetching the API directly.",
    "job-count": 2,
    "jobs": [
        {
            "id": 2091141,
            "title": "Frontend Web Application Developer",
            "company_name": "KoboToolbox",
            "url": "https://remotive.com/remote-jobs/design/"
                   "frontend-web-application-developer-2091141",
            "description": "<p><strong>Location:</strong> Remote<br>"
                           "Build things with React.</p>",
            "salary": "$90k - $105k",
            "publication_date": "2026-09-18T16:43:22",
            "candidate_required_location": "USA, Canada, Argentina",
            "category": "Design",
            "job_type": "full_time",
            "tags": ["react", "python"],
        },
        {
            # sparse: missing salary, description, location, date
            "id": 2091142,
            "title": "  Backend Engineer  ",
            "company_name": "NoSalary Inc",
            "url": "https://remotive.com/remote-jobs/dev/backend-2091142",
            "description": "",
            "salary": "",
            "publication_date": "",
            "candidate_required_location": "",
            "category": "Dev",
            "job_type": "freelance",
            "tags": [],
        },
    ],
}

WWR_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>We Work Remotely: Remote jobs</title>
<item>
  <title>C4Media Inc.: Demand Generation Specialist</title>
  <region>Anywhere in the World</region>
  <category>Sales and Marketing</category>
  <type>Full-Time</type>
  <description><![CDATA[<img src="https://example.com/logo.gif" />
    <p>Own our demand generation engine.</p>]]></description>
  <pubDate>Tue, 22 Sep 2026 17:13:52 +0000</pubDate>
  <guid>https://weworkremotely.com/remote-jobs/c4media-inc-demand-generation-specialist</guid>
  <link>https://weworkremotely.com/remote-jobs/c4media-inc-demand-generation-specialist</link>
</item>
<item>
  <title>JustATitleWithoutCompany</title>
  <description></description>
  <pubDate>not-a-real-date</pubDate>
  <link>https://weworkremotely.com/remote-jobs/some-job</link>
</item>
</channel></rss>"""

# jobspresso (substitute for workingnomads): standard WordPress RSS item shape
JP_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>Jobspresso</title>
<item>
  <title>Senior Python Engineer</title>
  <link>https://jobspresso.co/job/senior-python-engineer-1/</link>
  <dc:creator>jobspresso</dc:creator>
  <pubDate>Sat, 29 Aug 2026 02:13:20 +0000</pubDate>
  <guid>https://jobspresso.co/job/senior-python-engineer-1/</guid>
  <description><![CDATA[<p>Remote Python role.</p>]]></description>
  <content:encoded><![CDATA[<p><strong>Remote Python role.</strong>
    Work on APIs and data pipelines.</p>]]></content:encoded>
</item>
<item>
  <title>Junior Designer</title>
  <link>https://jobspresso.co/job/junior-designer-2/</link>
  <pubDate></pubDate>
  <guid>https://jobspresso.co/?p=2</guid>
  <description></description>
</item>
</channel></rss>"""


class RemotiveTests(unittest.TestCase):
    @patch.object(fs, "_get_json", return_value=REMOTIVE_FIXTURE)
    def test_parses_jobs(self, _):
        jobs = fs._adapt_remotive()
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual(j["source"], "remotive")
        self.assertEqual(j["source_id"], "remotive:2091141")
        self.assertEqual(j["title"], "Frontend Web Application Developer")
        self.assertEqual(j["company"], "KoboToolbox")
        self.assertEqual(j["location"], "USA, Canada, Argentina")
        self.assertTrue(j["remote"])
        self.assertEqual(j["salary_text"], "$90k - $105k")
        self.assertEqual(j["url"],
                         "https://remotive.com/remote-jobs/design/"
                         "frontend-web-application-developer-2091141")
        # HTML stripped, no tags left
        self.assertNotIn("<p>", j["description"])
        self.assertIn("Build things with React.", j["description"])
        self.assertIn("Location: Remote", j["description"])

    @patch.object(fs, "_get_json", return_value=REMOTIVE_FIXTURE)
    def test_missing_fields_safe(self, _):
        j = fs._adapt_remotive()[1]
        self.assertEqual(j["source_id"], "remotive:2091142")
        self.assertEqual(j["title"], "Backend Engineer")  # whitespace trimmed
        self.assertEqual(j["salary_text"], "")
        self.assertEqual(j["description"], "")
        self.assertEqual(j["location"], "Remote")  # default when blank
        self.assertEqual(j["posted_at"], "")

    @patch.object(fs, "_get_json", return_value=REMOTIVE_FIXTURE)
    def test_posted_at_iso_parsed(self, _):
        j = fs._adapt_remotive()[0]
        self.assertTrue(j["posted_at"].startswith("2026-09-18T16:43:22"))

    @patch.object(fs, "_get_json",
                  return_value={"jobs": [{"id": 1, "title": "x"}] * 3})
    def test_source_ids_unique(self, _):
        # duplicate ids in payload -> still unique source_ids? no: same id
        # gives same source_id; assert set size matches distinct ids
        jobs = fs._adapt_remotive()
        ids = [j["source_id"] for j in jobs]
        self.assertEqual(len(set(ids)), 1)

    @patch.object(fs, "_get_json", side_effect=RuntimeError("boom"))
    def test_unreachable_raises_freelance_error(self, _):
        with self.assertRaises(fs.FreelanceError):
            fs._adapt_remotive()

    @patch.object(fs, "_get_json", return_value={"jobs": []})
    def test_empty_feed(self, _):
        self.assertEqual(fs._adapt_remotive(), [])

    @patch.object(fs, "_get_json", return_value={"jobs": [{"id": 7,
        "title": "T", "company_name": "C", "description": "y" * 6000}]})
    def test_description_truncated(self, _):
        j = fs._adapt_remotive()[0]
        self.assertEqual(len(j["description"]), 4000)


class WeWorkRemotelyTests(unittest.TestCase):
    @staticmethod
    def _xml():
        return ET.fromstring(WWR_RSS_FIXTURE)

    @patch.object(fs, "_get_xml")
    def test_parses_items(self, mock_xml):
        mock_xml.return_value = self._xml()
        jobs = fs._adapt_weworkremotely()
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual(j["source"], "weworkremotely")
        self.assertEqual(j["source_id"],
                         "weworkremotely:c4media-inc-demand-generation-specialist")
        self.assertEqual(j["company"], "C4Media Inc.")
        self.assertEqual(j["title"], "Demand Generation Specialist")
        self.assertEqual(j["location"], "Anywhere in the World")
        self.assertTrue(j["remote"])
        self.assertEqual(j["salary_text"], "")
        self.assertEqual(j["url"],
                         "https://weworkremotely.com/remote-jobs/"
                         "c4media-inc-demand-generation-specialist")
        self.assertNotIn("<p>", j["description"])
        self.assertIn("Own our demand generation engine.", j["description"])

    @patch.object(fs, "_get_xml")
    def test_posted_at_rfc2822_parsed(self, mock_xml):
        mock_xml.return_value = self._xml()
        j = fs._adapt_weworkremotely()[0]
        self.assertTrue(j["posted_at"].startswith("2026-09-22T17:13:52"))

    @patch.object(fs, "_get_xml")
    def test_title_without_company_and_bad_date(self, mock_xml):
        mock_xml.return_value = self._xml()
        j = fs._adapt_weworkremotely()[1]
        self.assertEqual(j["title"], "JustATitleWithoutCompany")
        self.assertEqual(j["company"], "")
        self.assertEqual(j["location"], "Remote")
        self.assertEqual(j["posted_at"], "not-a-real-date")  # pass-through

    @patch.object(fs, "_get_xml", side_effect=RuntimeError("boom"))
    def test_unreachable_raises_freelance_error(self, _):
        with self.assertRaises(fs.FreelanceError):
            fs._adapt_weworkremotely()


class WorkingNomadsTests(unittest.TestCase):
    @staticmethod
    def _xml():
        return ET.fromstring(JP_RSS_FIXTURE)

    @patch.object(fs, "_get_xml")
    def test_parses_jobspresso_items(self, mock_xml):
        mock_xml.return_value = self._xml()
        jobs = fs._adapt_workingnomads()
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual(j["source"], "workingnomads")
        self.assertEqual(j["source_id"],
                         "workingnomads:senior-python-engineer-1")
        self.assertEqual(j["title"], "Senior Python Engineer")
        self.assertEqual(j["url"],
                         "https://jobspresso.co/job/senior-python-engineer-1/")
        self.assertTrue(j["remote"])
        self.assertIn("Work on APIs and data pipelines.", j["description"])
        self.assertNotIn("<p>", j["description"])

    @patch.object(fs, "_get_xml")
    def test_prefers_content_encoded_over_description(self, mock_xml):
        mock_xml.return_value = self._xml()
        j = fs._adapt_workingnomads()[0]
        # content:encoded has the longer body
        self.assertIn("Work on APIs and data pipelines.", j["description"])

    @patch.object(fs, "_get_xml")
    def test_empty_channel_ok(self, mock_xml):
        mock_xml.return_value = ET.fromstring(
            '<?xml version="1.0"?><rss version="2.0">'
            "<channel><title>Jobspresso</title></channel></rss>")
        self.assertEqual(fs._adapt_workingnomads(), [])

    @patch.object(fs, "_get_xml", side_effect=RuntimeError("boom"))
    def test_unreachable_raises_freelance_error(self, _):
        with self.assertRaises(fs.FreelanceError):
            fs._adapt_workingnomads()


class ContractTests(unittest.TestCase):
    def test_contract_sources_keys_and_names(self):
        self.assertEqual(set(fs.CONTRACT_SOURCES.keys()),
                         {"remotive", "weworkremotely", "workingnomads"})
        self.assertEqual(fs.FREELANCE_SOURCE_NAMES,
                         ["remotive", "weworkremotely", "workingnomads"])
        for name, fn in fs.CONTRACT_SOURCES.items():
            self.assertTrue(callable(fn), name)

    def test_norm_posted_at_variants(self):
        self.assertEqual(fs._norm_posted_at(""), "")
        self.assertEqual(fs._norm_posted_at(None), "")
        iso = fs._norm_posted_at("2026-09-18T16:43:22")
        self.assertTrue(iso.startswith("2026-09-18T16:43:22"))
        rfc = fs._norm_posted_at("Tue, 22 Sep 2026 17:13:52 +0000")
        self.assertTrue(rfc.startswith("2026-09-22T17:13:52"))
        self.assertEqual(fs._norm_posted_at("garbage"), "garbage")

    def test_norm_job_keys(self):
        j = fs._norm_job("s", "s:1", "T", "C", "L", "u", "d", "$", True, "")
        self.assertEqual(set(j.keys()),
                         {"source", "source_id", "title", "company",
                          "location", "url", "description", "salary_text",
                          "remote", "posted_at"})


if __name__ == "__main__":
    unittest.main()
