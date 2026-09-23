"""Hermetic tests for the batch-14 niche-board adapters (fourdayweek, remoteco).

No live network: the fetch helpers are patched with fixture payloads.
Run: python -m unittest tests.test_batch14_fourdayweek_remoteco -v
"""
import sys
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.jobs import (  # noqa: E402
    ADAPTERS,
    JobsError,
    _adapt_fourdayweek,
    _adapt_remoteco,
)


# ---------------------------------------------------------------------------
# 4dayweek.io fixtures — shaped like the real public JSON feed
# (https://4dayweek.io/api/jobs), captured 2026-09-22
# ---------------------------------------------------------------------------

_FDW_JOB_REMOTE = {
    "id": "01a0ca09-f4bb-7a68-bf70-8533f5989d66",
    "title": "Staff AI Engineer",
    "slug": "staff-ai-engineer-at-acme-abc123",
    "company_name": "Acme Corp",
    "work_arrangement": "remote",
    "locations": [{"city": None, "country": "United States"}],
    "posted": 1758530400,  # 2025-09-22
    "schedule_type": "4_day_week_pro_rata",
    "category": "engineering",
    "is_expired": False,
    "work_life_score": 92,
}

_FDW_JOB_HYBRID = {
    "id": "01b1db1a-g5cc-8i79-cg81-d644g609a77",
    "title": "Regulatory Project Analyst",
    "slug": "regulatory-project-analyst-at-smartest-energy-def456",
    "company_name": "Smartest Energy",
    "work_arrangement": "hybrid",
    "locations": [{"city": "Ipswich", "country": "United Kingdom"}],
    "posted": 1758444000,  # 2025-09-21
    "schedule_type": "4_day_week",
    "category": "legal",
    "is_expired": False,
    "work_life_score": 88,
}

_FDW_JOB_EXPIRED = {
    "id": "dead-beef-0000",
    "title": "Old Role",
    "slug": "old-role-at-oldco-ghi789",
    "company_name": "OldCo",
    "work_arrangement": "onsite",
    "locations": [{"city": "Berlin", "country": "Germany"}],
    "posted": 1758000000,
    "schedule_type": "4_day_week",
    "category": "ops",
    "is_expired": True,
}

_FDW_PAGE1 = {
    "jobs": [_FDW_JOB_REMOTE, _FDW_JOB_HYBRID, _FDW_JOB_EXPIRED],
    "total": 3,
    "page": 1,
    "has_more": False,
}


# ---------------------------------------------------------------------------
# Remote.co fixtures — WordPress RSS shape
# ---------------------------------------------------------------------------

_RCO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>Remote.co Remote Jobs</title>
<item>
<title>Senior Python Developer</title>
<link>https://remote.co/remote-jobs/senior-python-developer/</link>
<guid>https://remote.co/remote-jobs/senior-python-developer/</guid>
<dc:creator>Acme Corp</dc:creator>
<pubDate>Tue, 22 Sep 2026 10:00:00 +0000</pubDate>
<description><![CDATA[<p>Build <b>cool</b> things with our team.</p><p>Salary: $150k-$180k.</p>]]></description>
</item>
<item>
<title>Customer Success Manager</title>
<link>https://remote.co/remote-jobs/customer-success-manager/</link>
<guid>https://remote.co/remote-jobs/customer-success-manager/</guid>
<pubDate>Mon, 21 Sep 2026 08:30:00 +0000</pubDate>
<description><![CDATA[<p>Help customers &amp; grow accounts.</p>]]></description>
</item>
</channel>
</rss>"""


def _fake_get_json(payload):
    def _f(url):
        return payload
    return _f


class FourDayWeekAdapterTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("fourdayweek", ADAPTERS)
        self.assertIs(ADAPTERS["fourdayweek"], _adapt_fourdayweek)

    def test_normalization(self):
        with patch("candid.jobs._get_json", _fake_get_json(_FDW_PAGE1)):
            jobs = _adapt_fourdayweek()
        # expired posting is skipped
        self.assertEqual(len(jobs), 2)

        remote_job, hybrid_job = jobs
        self.assertEqual(remote_job["source"], "fourdayweek")
        self.assertEqual(remote_job["source_id"],
                         "fourdayweek:01a0ca09-f4bb-7a68-bf70-8533f5989d66")
        self.assertEqual(remote_job["title"], "Staff AI Engineer")
        self.assertEqual(remote_job["company"], "Acme Corp")
        self.assertTrue(remote_job["remote"])
        self.assertEqual(remote_job["location"], "Remote (United States)")
        self.assertEqual(remote_job["url"],
                         "https://4dayweek.io/job/staff-ai-engineer-at-acme-abc123")
        self.assertEqual(remote_job["posted_at"], "2025-09-22")
        self.assertEqual(remote_job["salary_text"], "")
        self.assertIn("4-day week (pro rata)", remote_job["description"])
        self.assertLessEqual(len(remote_job["description"]), 4000)

        self.assertFalse(hybrid_job["remote"])
        self.assertEqual(hybrid_job["location"], "Ipswich, United Kingdom")
        self.assertEqual(hybrid_job["posted_at"], "2025-09-21")
        self.assertIn("4-day week", hybrid_job["description"])

    def test_source_id_stable_across_runs(self):
        with patch("candid.jobs._get_json", _fake_get_json(_FDW_PAGE1)):
            first = [j["source_id"] for j in _adapt_fourdayweek()]
            second = [j["source_id"] for j in _adapt_fourdayweek()]
        self.assertEqual(first, second)

    def test_pagination_respects_max_per_source(self):
        calls = []

        def page(url):
            calls.append(url)
            p = int(url.rsplit("page=", 1)[1])
            jobs = [dict(_FDW_JOB_REMOTE, id=f"p{p}-id-{i}") for i in range(25)]
            return {"jobs": jobs, "page": p, "has_more": True}
        with patch("candid.jobs._get_json", page):
            jobs = _adapt_fourdayweek()
        self.assertEqual(len(jobs), 100)
        self.assertEqual(len(calls), 4)  # 25/page x 4 = 100, then stop
        self.assertEqual(len({j["source_id"] for j in jobs}), 100)

    def test_stops_when_no_more_pages(self):
        calls = []

        def page(url):
            calls.append(url)
            return _FDW_PAGE1
        with patch("candid.jobs._get_json", page):
            _adapt_fourdayweek()
        self.assertEqual(calls, ["https://4dayweek.io/api/jobs?page=1"])

    def test_malformed_payload_raises(self):
        for bad in ({"nope": True}, [1, 2, 3], None):
            with patch("candid.jobs._get_json", _fake_get_json(bad)):
                with self.assertRaises(JobsError):
                    _adapt_fourdayweek()

    def test_unreachable_raises(self):
        def boom(url):
            raise ConnectionError("boom")
        with patch("candid.jobs._get_json", boom):
            with self.assertRaises(JobsError):
                _adapt_fourdayweek()

    def test_mojibake_fixed(self):
        job = dict(_FDW_JOB_REMOTE, title="DÃ©veloppeur")
        page = {"jobs": [job], "page": 1, "has_more": False}
        with patch("candid.jobs._get_json", _fake_get_json(page)):
            jobs = _adapt_fourdayweek()
        self.assertEqual(jobs[0]["title"], "Développeur")


class RemoteCoAdapterTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("remoteco", ADAPTERS)
        self.assertIs(ADAPTERS["remoteco"], _adapt_remoteco)

    def test_normalization_and_html_stripping(self):
        with patch("candid.jobs._get_text", lambda url: _RCO_RSS):
            jobs = _adapt_remoteco()
        self.assertEqual(len(jobs), 2)
        dev, csm = jobs
        self.assertEqual(dev["source"], "remoteco")
        self.assertEqual(dev["source_id"],
                         "remoteco:https://remote.co/remote-jobs/senior-python-developer/")
        self.assertEqual(dev["title"], "Senior Python Developer")
        self.assertEqual(dev["company"], "Acme Corp")
        self.assertEqual(dev["location"], "Remote")
        self.assertTrue(dev["remote"])
        self.assertEqual(dev["url"], "https://remote.co/remote-jobs/senior-python-developer/")
        self.assertEqual(dev["posted_at"], "2026-09-22")
        # HTML stripped, no tags left
        self.assertNotIn("<", dev["description"])
        self.assertNotIn(">", dev["description"])
        self.assertIn("Build cool things", dev["description"])
        self.assertLessEqual(len(dev["description"]), 4000)
        # item without dc:creator -> empty company, never invented
        self.assertEqual(csm["company"], "")
        self.assertEqual(csm["posted_at"], "2026-09-21")

    def test_source_id_stable_across_runs(self):
        with patch("candid.jobs._get_text", lambda url: _RCO_RSS):
            first = [j["source_id"] for j in _adapt_remoteco()]
            second = [j["source_id"] for j in _adapt_remoteco()]
        self.assertEqual(first, second)

    def test_malformed_feed_raises(self):
        with patch("candid.jobs._get_text", lambda url: "not xml < at all"):
            with self.assertRaises(JobsError):
                _adapt_remoteco()

    def test_http_error_raises(self):
        def fail(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with patch("candid.jobs._get_text", fail):
            with self.assertRaises(JobsError):
                _adapt_remoteco()

    def test_unreachable_feed_returns_empty(self):
        # remote.co silently drops automated requests (checked 2026-09-22):
        # documented as returning [] rather than failing the run.
        def fail(url):
            raise urllib.error.URLError("timed out")
        with patch("candid.jobs._get_text", fail):
            self.assertEqual(_adapt_remoteco(), [])


if __name__ == "__main__":
    unittest.main()
