"""Tests for candid.jobs_remote_sources (batch 20, worker A).

The network is NEVER touched: urllib.request.urlopen is patched with an
in-memory router serving realistic RSS/JSON fixtures, malformed payloads,
and simulated network failures.

Run: python -m pytest tests/test_remote_sources.py -q
"""
from __future__ import annotations

import json
import sys
import urllib.error
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import jobs_remote_sources as rs  # noqa: E402
from candid.jobs import JobsError  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures — realistic samples of each feed
# ---------------------------------------------------------------------------

WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>We Work Remotely: Remote jobs in programming</title>
<link>https://weworkremotely.com/categories/remote-programming-jobs</link>
<item>
<title>Lemon.io: Senior .NET Full-stack Developer</title>
<link>https://weworkremotely.com/remote-jobs/lemon-io-senior-net-full-stack-developer-1</link>
<guid>https://weworkremotely.com/remote-jobs/lemon-io-senior-net-full-stack-developer-1</guid>
<description><![CDATA[<img src="https://example.com/logo.gif" /><p><strong>Headquarters:</strong> New York, NY</p><p>Are you a <em>talented</em> Senior Developer &amp; ready?</p><ul><li>4+ years of experience</li></ul>]]></description>
<pubDate>Tue, 08 Sep 2026 13:49:13 +0000</pubDate>
</item>
<item>
<title>Junior QA Tester</title>
<link>https://weworkremotely.com/remote-jobs/acme-junior-qa-tester</link>
<description><![CDATA[<p>Test things &lt;3 and ship.</p>]]></description>
<pubDate>Mon, 07 Sep 2026 10:00:00 +0000</pubDate>
</item>
<item>
<title>No link here: Ghost Job</title>
<description><![CDATA[<p>no link, must be skipped</p>]]></description>
</item>
</channel>
</rss>"""

HIMALAYAS_JSON = json.dumps({
    "jobs": [
        {
            "id": "abc123",
            "title": "Senior Backend Engineer",
            "companyName": "HimalayaTest",
            "applicationLink": "https://himalayas.app/jobs/abc123",
            "locationRestrictions": "Worldwide",
            "description": "<p>Build <strong>cool</strong> stuff &amp; ship it.</p>",
            "salary": "$120k - $160k",
            "pubDate": "2026-09-20",
        },
        {
            "id": "def456",
            "title": "Product Designer",
            "company_name": "DesignCo",
            "url": "https://himalayas.app/jobs/def456",
            "minSalary": 90000,
            "maxSalary": 120000,
            "description": "Design things.",
            "publicationDate": "2026-09-19T00:00:00Z",
        },
        {"title": "No URL job", "companyName": "Nowhere Inc"},
        "not a dict",
    ]
})

HIMALAYAS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Himalayas Jobs</title>
<item>
<title>RemoteCo: Data Analyst</title>
<link>https://himalayas.app/jobs/xyz789</link>
<description><![CDATA[<p>Analyze <b>data</b> remotely.</p>]]></description>
<pubDate>2026-09-18</pubDate>
</item>
<item>
<title></title>
<link>https://himalayas.app/jobs/empty-title</link>
<description><![CDATA[<p>empty title, must be skipped</p>]]></description>
</item>
</channel>
</rss>"""

JOBSPRESSO_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>Jobspresso</title>
<link>https://jobspresso.co</link>
<item>
<title>Senior Backend Engineer at Acme Corp</title>
<link>https://jobspresso.co/job/senior-backend-engineer-acme/</link>
<description><![CDATA[<p>Company: Acme Corp</p><p>Location: Anywhere</p><p>We need a <b>great</b> engineer &amp; friend.</p>]]></description>
<pubDate>Sat, 29 Aug 2026 02:13:20 +0000</pubDate>
<dc:creator>jobspresso</dc:creator>
</item>
<item>
<title>DevOps Engineer</title>
<link>https://jobspresso.co/job/devops-engineer/</link>
<description><![CDATA[<p>Run the infra.</p>]]></description>
<pubDate>Sat, 29 Aug 2026 01:00:00 +0000</pubDate>
</item>
</channel>
</rss>"""

REMOTIVE_JSON = json.dumps({
    "job-count": 3,
    "jobs": [
        {
            "id": 2091141,
            "url": "https://remotive.com/remote-jobs/design/frontend-dev-2091141",
            "title": "Frontend Web Application Developer",
            "company_name": "KoboToolbox",
            "category": "Design",
            "job_type": "full_time",
            "publication_date": "2026-09-18T16:43:22",
            "candidate_required_location": "USA, Canada",
            "salary": "$90k - $105k",
            "description": "<p><strong>Location:</strong> Remote</p><p>Write <em>great</em> code &amp; docs.</p>",
        },
        {
            "id": 2091140,
            "url": "https://remotive.com/remote-jobs/dev/senior-shopify-2091140",
            "title": "Senior Shopify Developer",
            "company_name": "Sanctuary Computer Inc",
            "publication_date": "2026-09-18T15:10:28",
            "description": "Contract role.",
        },
        {
            "title": "Missing id job",
            "url": "https://remotive.com/remote-jobs/x",
            "company_name": "Ghost",
        },
    ],
})

EXPECTED_KEYS = {"source", "source_id", "title", "company", "location", "url",
                 "description", "salary_text", "remote", "posted_at"}


# ---------------------------------------------------------------------------
# fake network layer
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, data):
        self._data = data if isinstance(data, bytes) else data.encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NetTest(unittest.TestCase):
    """urlopen is patched; _ROUTES maps URL substrings to responses."""

    _ROUTES: dict = {}

    def setUp(self):
        type(self)._ROUTES = {}

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            for key, val in type(self)._ROUTES.items():
                if key in url:
                    if isinstance(val, Exception):
                        raise val
                    return _FakeResp(val)
            raise AssertionError(f"test did not expect a fetch of {url}")

        patcher = mock.patch("urllib.request.urlopen", fake_urlopen)
        self.addCleanup(patcher.stop)
        patcher.start()

    def route(self, substr, payload):
        type(self)._ROUTES[substr] = payload

    def route_wwr(self, payload=WWR_RSS):
        for cat in ("remote-programming-jobs", "remote-devops-sysadmin-jobs",
                    "remote-design-jobs"):
            self.route(cat, payload)


# ---------------------------------------------------------------------------
# We Work Remotely
# ---------------------------------------------------------------------------

class TestWeWorkRemotely(NetTest):
    def test_parses_items(self):
        self.route_wwr()
        jobs = rs.fetch_weworkremotely()
        self.assertEqual(len(jobs), 2)  # linkless item skipped
        first = jobs[0]
        self.assertEqual(first["title"], "Senior .NET Full-stack Developer")
        self.assertEqual(first["company"], "Lemon.io")
        self.assertEqual(first["url"],
                         "https://weworkremotely.com/remote-jobs/lemon-io-senior-net-full-stack-developer-1")
        self.assertEqual(first["posted_at"], "Tue, 08 Sep 2026 13:49:13 +0000")
        self.assertEqual(first["location"], "Remote")
        self.assertTrue(first["remote"])
        self.assertNotIn("<", first["description"])
        self.assertIn("talented Senior Developer & ready?", first["description"])

    def test_title_without_colon(self):
        self.route_wwr()
        jobs = rs.fetch_weworkremotely()
        second = jobs[1]
        self.assertEqual(second["title"], "Junior QA Tester")
        self.assertEqual(second["company"], "")
        self.assertIn("Test things <3 and ship.", second["description"])

    def test_source_ids_unique_and_prefixed(self):
        self.route_wwr()
        jobs = rs.fetch_weworkremotely()
        ids = [j["source_id"] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        for j in jobs:
            self.assertTrue(j["source_id"].startswith("weworkremotely:"))

    def test_malformed_xml_raises(self):
        self.route_wwr(payload="<rss><channel><item><title>oops")
        with self.assertRaises(JobsError) as ctx:
            rs.fetch_weworkremotely()
        self.assertIn("weworkremotely", str(ctx.exception))

    def test_network_error_raises(self):
        self.route_wwr(payload=urllib.error.URLError("boom"))
        with self.assertRaises(JobsError):
            rs.fetch_weworkremotely()

    def test_one_dead_category_does_not_kill_others(self):
        self.route("remote-programming-jobs", WWR_RSS)
        self.route("remote-devops-sysadmin-jobs",
                   urllib.error.HTTPError("http://x", 404, "nf", {}, None))
        self.route("remote-design-jobs", WWR_RSS)
        jobs = rs.fetch_weworkremotely()
        # same fixture in two categories -> cross-category dedupe by slug
        self.assertEqual(len(jobs), 2)

    def test_all_categories_dead_raises(self):
        self.route_wwr(payload=urllib.error.URLError("down"))
        with self.assertRaises(JobsError):
            rs.fetch_weworkremotely()


# ---------------------------------------------------------------------------
# Himalayas
# ---------------------------------------------------------------------------

class TestHimalayas(NetTest):
    def route_api(self, payload=HIMALAYAS_JSON):
        self.route("himalayas.app/api/jobs", payload)

    def route_rss(self, payload=HIMALAYAS_RSS):
        self.route("himalayas.app/rss", payload)

    def test_json_success(self):
        self.route_api()
        self.route_rss()
        jobs = rs.fetch_himalayas()
        self.assertEqual(len(jobs), 2)  # bad items skipped
        first, second = jobs
        self.assertEqual(first["title"], "Senior Backend Engineer")
        self.assertEqual(first["company"], "HimalayaTest")
        self.assertEqual(first["location"], "Worldwide")
        self.assertEqual(first["salary_text"], "$120k - $160k")
        self.assertEqual(first["posted_at"], "2026-09-20")
        self.assertIn("Build cool stuff & ship it.", first["description"])
        self.assertTrue(first["remote"])
        # min/max salary composed, missing location defaults to Remote
        self.assertEqual(second["salary_text"], "90000 - 120000")
        self.assertEqual(second["company"], "DesignCo")
        self.assertEqual(second["location"], "Remote")

    def test_json_404_falls_back_to_rss(self):
        self.route_api(payload=urllib.error.HTTPError(
            "http://x", 404, "Not Found", {}, None))
        self.route_rss()
        jobs = rs.fetch_himalayas()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Data Analyst")
        self.assertEqual(jobs[0]["company"], "RemoteCo")
        self.assertEqual(jobs[0]["source"], "himalayas")
        self.assertIn("Analyze data remotely.", jobs[0]["description"])

    def test_json_unknown_shape_falls_back_to_rss(self):
        self.route_api(payload=json.dumps({"ok": True, "message": "v2 moved"}))
        self.route_rss()
        jobs = rs.fetch_himalayas()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_id"], "himalayas:xyz789")

    def test_invalid_json_falls_back_to_rss(self):
        self.route_api(payload="this is not json {{{")
        self.route_rss()
        jobs = rs.fetch_himalayas()
        self.assertEqual(len(jobs), 1)

    def test_both_fail_raises(self):
        self.route_api(payload=urllib.error.URLError("down"))
        self.route_rss(payload=urllib.error.URLError("also down"))
        with self.assertRaises(JobsError) as ctx:
            rs.fetch_himalayas()
        self.assertIn("himalayas", str(ctx.exception))


# ---------------------------------------------------------------------------
# Jobspresso
# ---------------------------------------------------------------------------

class TestJobspresso(NetTest):
    def test_parses_items(self):
        self.route("jobspresso.co/feed", JOBSPRESSO_RSS)
        jobs = rs.fetch_jobspresso()
        self.assertEqual(len(jobs), 2)
        first = jobs[0]
        self.assertEqual(first["title"], "Senior Backend Engineer")
        self.assertEqual(first["company"], "Acme Corp")
        self.assertEqual(first["location"], "Anywhere")
        self.assertEqual(first["url"],
                         "https://jobspresso.co/job/senior-backend-engineer-acme/")
        self.assertEqual(first["posted_at"],
                         "Sat, 29 Aug 2026 02:13:20 +0000")
        self.assertTrue(first["remote"])
        self.assertNotIn("<", first["description"])
        self.assertIn("great engineer & friend.", first["description"])

    def test_plain_title_no_company(self):
        self.route("jobspresso.co/feed", JOBSPRESSO_RSS)
        jobs = rs.fetch_jobspresso()
        self.assertEqual(jobs[1]["title"], "DevOps Engineer")
        self.assertEqual(jobs[1]["company"], "")
        self.assertEqual(jobs[1]["location"], "Remote")

    def test_skips_items_missing_title_or_link(self):
        rss = ('<?xml version="1.0"?><rss><channel>'
               '<item><title></title><link>https://jobspresso.co/job/x/</link></item>'
               '<item><title>Real Job</title><link></link></item>'
               '</channel></rss>')
        self.route("jobspresso.co/feed", rss)
        self.assertEqual(rs.fetch_jobspresso(), [])

    def test_malformed_xml_raises(self):
        self.route("jobspresso.co/feed", "<rss><channel><oops")
        with self.assertRaises(JobsError):
            rs.fetch_jobspresso()

    def test_network_error_raises(self):
        self.route("jobspresso.co/feed", urllib.error.URLError("boom"))
        with self.assertRaises(JobsError):
            rs.fetch_jobspresso()


# ---------------------------------------------------------------------------
# Remotive
# ---------------------------------------------------------------------------

class TestRemotive(NetTest):
    def route_api(self, payload=REMOTIVE_JSON):
        self.route("remotive.com/api/remote-jobs", payload)

    def test_parses_items(self):
        self.route_api()
        jobs = rs.fetch_remotive()
        self.assertEqual(len(jobs), 2)  # id-less item skipped
        first = jobs[0]
        self.assertEqual(first["title"], "Frontend Web Application Developer")
        self.assertEqual(first["company"], "KoboToolbox")
        self.assertEqual(first["location"], "USA, Canada")
        self.assertEqual(first["salary_text"], "$90k - $105k")
        self.assertEqual(first["posted_at"], "2026-09-18T16:43:22")
        self.assertEqual(first["source_id"], "remotive:2091141")
        self.assertTrue(first["remote"])
        self.assertNotIn("<", first["description"])
        self.assertIn("Write great code & docs.", first["description"])

    def test_missing_optional_fields_default(self):
        self.route_api()
        jobs = rs.fetch_remotive()
        second = jobs[1]
        self.assertEqual(second["salary_text"], "")
        self.assertEqual(second["location"], "Remote")

    def test_unexpected_shape_raises(self):
        self.route_api(payload=json.dumps("just a string"))
        with self.assertRaises(JobsError):
            rs.fetch_remotive()

    def test_invalid_json_raises(self):
        self.route_api(payload="{nope")
        with self.assertRaises(JobsError):
            rs.fetch_remotive()

    def test_network_error_raises(self):
        self.route_api(payload=urllib.error.URLError("boom"))
        with self.assertRaises(JobsError) as ctx:
            rs.fetch_remotive()
        self.assertIn("remotive", str(ctx.exception))

    def test_empty_jobs_list(self):
        self.route_api(payload=json.dumps({"jobs": []}))
        self.assertEqual(rs.fetch_remotive(), [])


# ---------------------------------------------------------------------------
# cross-adapter guarantees
# ---------------------------------------------------------------------------

class TestAdapterContract(NetTest):
    def setUp(self):
        super().setUp()
        self.route_wwr()
        self.route("himalayas.app/api/jobs", HIMALAYAS_JSON)
        self.route("jobspresso.co/feed", JOBSPRESSO_RSS)
        self.route("remotive.com/api/remote-jobs", REMOTIVE_JSON)

    def route_wwr(self, payload=WWR_RSS):
        for cat in ("remote-programming-jobs", "remote-devops-sysadmin-jobs",
                    "remote-design-jobs"):
            self.route(cat, payload)

    def test_registry(self):
        self.assertEqual(set(rs.REMOTE_ADAPTERS),
                         {"weworkremotely", "himalayas", "jobspresso", "remotive"})
        self.assertIs(rs.REMOTE_ADAPTERS["weworkremotely"], rs.fetch_weworkremotely)
        self.assertIs(rs.REMOTE_ADAPTERS["himalayas"], rs.fetch_himalayas)
        self.assertIs(rs.REMOTE_ADAPTERS["jobspresso"], rs.fetch_jobspresso)
        self.assertIs(rs.REMOTE_ADAPTERS["remotive"], rs.fetch_remotive)

    def test_normalized_shape_and_remote_true(self):
        for name, fetch in rs.REMOTE_ADAPTERS.items():
            for job in fetch():
                self.assertEqual(set(job.keys()), EXPECTED_KEYS, name)
                self.assertEqual(job["source"], name)
                self.assertIs(job["remote"], True)
                self.assertTrue(job["title"], name)
                self.assertTrue(job["url"], name)
                self.assertTrue(job["source_id"].startswith(f"{name}:"), name)
                self.assertLessEqual(len(job["description"]), 4000)

    def test_source_ids_unique_within_adapter(self):
        for name, fetch in rs.REMOTE_ADAPTERS.items():
            ids = [j["source_id"] for j in fetch()]
            self.assertEqual(len(ids), len(set(ids)), name)

    def test_description_truncated_to_4000(self):
        long_desc = "<p>" + "x" * 9000 + "</p>"
        jobs = {"jobs": [{"id": 1, "title": "T", "company_name": "C",
                          "url": "https://remotive.com/j/1",
                          "description": long_desc}]}
        self.route("remotive.com/api/remote-jobs", json.dumps(jobs))
        (job,) = rs.fetch_remotive()
        self.assertEqual(len(job["description"]), 4000)

    def test_max_per_source_cap(self):
        jobs = {"jobs": [
            {"id": i, "title": f"Job {i}", "company_name": "C",
             "url": f"https://remotive.com/j/{i}", "description": "d"}
            for i in range(10)]}
        self.route("remotive.com/api/remote-jobs", json.dumps(jobs))
        with mock.patch.object(rs, "MAX_PER_SOURCE", 3):
            got = rs.fetch_remotive()
        self.assertEqual(len(got), 3)


if __name__ == "__main__":
    unittest.main()
