"""Tests for the batch-14 Dice and Authentic Jobs adapters in candid.jobs.

Hermetic: the RSS/HTTP layer is patched, no live network is made.
Run: python -m unittest tests.test_batch14_dice_authentic -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AJ_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:aj="https://authenticjobs.com">
  <channel>
    <title>Authentic Jobs</title>
    <item>
      <title>Senior Python Engineer</title>
      <link>https://authenticjobs.com/job/99999/acme-senior-python-engineer/</link>
      <dc:creator>acme</dc:creator>
      <pubDate>Tue, 04 Aug 2026 16:23:50 +0000</pubDate>
      <guid>https://authenticjobs.com/?post_type=job_listing&amp;p=99999</guid>
      <description>Acme needs a Python engineer. Apply today.</description>
      <content:encoded><![CDATA[
        <p>Acme needs a <strong>Python engineer</strong>.</p>
        <p>Build data pipelines. <a href="https://example.com">Details</a></p>
      ]]></content:encoded>
      <aj:location>Remote (US)</aj:location>
      <aj:job_type>Full-time</aj:job_type>
      <aj:job_category>Development</aj:job_category>
      <aj:company>Acme Corp</aj:company>
    </item>
    <item>
      <title>Product Designer</title>
      <link>https://authenticjobs.com/job/99998/acme-product-designer/</link>
      <dc:creator>acme</dc:creator>
      <pubDate>Wed, 05 Aug 2026 09:00:00 +0000</pubDate>
      <guid>https://authenticjobs.com/?post_type=job_listing&amp;p=99998</guid>
      <description>Design the future.</description>
      <aj:location>New York, NY</aj:location>
      <aj:job_type>Full-time</aj:job_type>
      <aj:job_category>Design</aj:job_category>
      <aj:company>Acme Corp</aj:company>
    </item>
  </channel>
</rss>"""


class AuthenticJobsAdapterTest(unittest.TestCase):
    def _run(self, payload):
        from candid import jobs as J
        with patch.object(J, "_get_text", return_value=payload):
            return J._adapt_authenticjobs()

    def test_registration(self):
        from candid import jobs as J
        self.assertIs(J.ADAPTERS["authenticjobs"], J._adapt_authenticjobs)

    def test_normalization(self):
        out = self._run(AJ_RSS)
        self.assertEqual(len(out), 2)
        j = out[0]
        self.assertEqual(j["source"], "authenticjobs")
        self.assertEqual(j["source_id"],
                         "authenticjobs:https://authenticjobs.com/?post_type=job_listing&p=99999")
        self.assertEqual(j["title"], "Senior Python Engineer")
        self.assertEqual(j["company"], "Acme Corp")
        self.assertEqual(j["location"], "Remote (US)")
        self.assertEqual(j["url"],
                         "https://authenticjobs.com/job/99999/acme-senior-python-engineer/")
        self.assertEqual(j["posted_at"], "2026-08-04")
        self.assertEqual(j["salary_text"], "")
        self.assertTrue(j["remote"])
        # content:encoded preferred over description, HTML stripped
        self.assertEqual(j["description"],
                         "Acme needs a Python engineer . Build data pipelines. Details")
        self.assertFalse(out[1]["remote"])

    def test_description_falls_back_when_no_encoded_content(self):
        out = self._run(AJ_RSS)
        self.assertEqual(out[1]["description"], "Design the future.")

    def test_source_id_stable_across_runs(self):
        first = [j["source_id"] for j in self._run(AJ_RSS)]
        second = [j["source_id"] for j in self._run(AJ_RSS)]
        self.assertEqual(first, second)

    def test_description_capped_at_4000(self):
        long_desc = "<p>" + "word " * 2000 + "</p>"
        rss = AJ_RSS.replace("Design the future.", long_desc)
        out = self._run(rss)
        self.assertLessEqual(len(out[1]["description"]), 4000)

    def test_malformed_feed_raises_jobs_error(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError):
            self._run("<rss><channel><item>not really xml")

    def test_non_xml_payload_raises_jobs_error(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError):
            self._run("<!doctype html><html>404 page</html>")

    def test_fetch_failure_raises_jobs_error(self):
        from candid import jobs as J
        with patch.object(J, "_get_text", side_effect=TimeoutError("boom")):
            with self.assertRaises(J.JobsError):
                J._adapt_authenticjobs()


class DiceAdapterTest(unittest.TestCase):
    def test_registration(self):
        from candid import jobs as J
        self.assertIs(J.ADAPTERS["dice"], J._adapt_dice)

    def test_returns_empty_gracefully(self):
        from candid import jobs as J
        self.assertEqual(J._adapt_dice(), [])


if __name__ == "__main__":
    unittest.main()
