"""Tests for candid.monitors — registry, fetchers, history/diff, health, reposts.

All HTTP is mocked; no real network is made in these tests.
Run: python -m unittest discover -s tests -p test_monitors.py -v
"""
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import monitors as M  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {"id": 101, "title": "Senior ML Engineer",
         "location": {"name": "New York, NY"},
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
         "departments": [{"name": "Engineering"}],
         "updated_at": "2026-09-20T10:00:00Z"},
        {"id": 102, "title": "Product Designer",
         "location": {"name": "Remote"},
         "absolute_url": "https://boards.greenhouse.io/acme/jobs/102",
         "departments": [{"name": "Design"}],
         "updated_at": "2026-09-21"},
    ]
}

LEVER_PAYLOAD = [
    {"id": "aaa-111", "text": "Backend Engineer",
     "categories": {"location": "San Francisco", "department": "Engineering",
                    "team": "Platform"},
     "hostedUrl": "https://jobs.lever.co/beta/aaa-111",
     "createdAt": 1789948800000},
    {"id": "bbb-222", "text": "Data Analyst",
     "categories": {"location": "Remote", "department": "Data"},
     "hostedUrl": "https://jobs.lever.co/beta/bbb-222",
     "createdAt": 1789862400},
]

RSS_PAYLOAD = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Acme Jobs</title>
<item><title>DevOps Engineer</title><link>https://acme.example/jobs/1</link>
<guid>job-1</guid><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Support Lead</title><link>https://acme.example/jobs/2</link>
<pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM_PAYLOAD = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Beta Jobs</title>
<entry><title>QA Engineer</title>
<link href="https://beta.example/jobs/9"/>
<id>tag:beta.example,2026:9</id>
<updated>2026-09-22T08:00:00Z</updated></entry>
</feed>"""


def _fake_http(payload):
    def _get(url):
        return payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return _get


def _raising_http(exc):
    def _get(url):
        raise exc
    return _get


# ---------------------------------------------------------------------------
# base: isolated data dir
# ---------------------------------------------------------------------------

class MonitorsBase(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        C.DATA_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        self.td.cleanup()


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class RegistryTest(MonitorsBase):
    def test_add_and_list_company(self):
        comp = M.add_company("Acme Corp")
        self.assertEqual(comp["key"], "acme-corp")
        names = [c["name"] for c in M.list_companies()]
        self.assertEqual(names, ["Acme Corp"])

    def test_duplicate_company_rejected_case_insensitive(self):
        M.add_company("Acme Corp")
        with self.assertRaises(M.MonitorError):
            M.add_company("acme corp")
        with self.assertRaises(M.MonitorError):
            M.add_company("")

    def test_remove_company(self):
        M.add_company("Acme")
        self.assertTrue(M.remove_company("acme"))
        self.assertEqual(M.list_companies(), [])
        with self.assertRaises(M.MonitorError):
            M.remove_company("acme")

    def test_add_greenhouse_source(self):
        M.add_company("Acme")
        src = M.add_source("acme", "greenhouse", board="acmetoken")
        self.assertEqual(src["type"], "greenhouse")
        self.assertIn("acmetoken", src["url"])
        self.assertEqual(len(M.list_sources("acme")), 1)

    def test_add_lever_source(self):
        M.add_company("Beta")
        src = M.add_source("beta", "lever", site="beta")
        self.assertIn("api.lever.co", src["url"])
        self.assertIn("beta", src["url"])

    def test_add_rss_source(self):
        M.add_company("Gamma")
        src = M.add_source("gamma", "rss", url="https://gamma.example/feed.xml")
        self.assertEqual(src["type"], "rss")
        self.assertEqual(src["url"], "https://gamma.example/feed.xml")

    def test_bad_source_type_rejected(self):
        M.add_company("Acme")
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "indeed", url="https://x.example")

    def test_bad_source_params_rejected(self):
        M.add_company("Acme")
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "greenhouse")  # no board
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "lever")  # no site
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "rss", url="not-a-url")
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "rss", url="ftp://x.example/f")

    def test_duplicate_source_rejected(self):
        M.add_company("Acme")
        M.add_source("acme", "greenhouse", board="acmetoken")
        with self.assertRaises(M.MonitorError):
            M.add_source("acme", "greenhouse", board="acmetoken")

    def test_remove_source(self):
        M.add_company("Acme")
        M.add_source("acme", "greenhouse", board="acmetoken")
        M.add_source("acme", "rss", url="https://acme.example/feed")
        removed = M.remove_source("acme", 0)
        self.assertEqual(removed["type"], "greenhouse")
        self.assertEqual(len(M.list_sources("acme")), 1)
        with self.assertRaises(M.MonitorError):
            M.remove_source("acme", 5)
        with self.assertRaises(M.MonitorError):
            M.add_source("nosuchco", "rss", url="https://x.example/f")

    def test_registry_persists_to_json(self):
        M.add_company("Acme")
        M.add_source("acme", "greenhouse", board="acmetoken")
        data = json.loads((Path(self.td.name) / "monitors.json").read_text())
        self.assertIn("acme", data["companies"])
        self.assertEqual(data["companies"]["acme"]["sources"][0]["type"], "greenhouse")

    def test_corrupt_registry_starts_empty(self):
        (Path(self.td.name) / "monitors.json").write_text("{not json")
        self.assertEqual(M.list_companies(), [])
        M.add_company("Acme")  # still usable afterwards
        self.assertEqual(len(M.list_companies()), 1)


# ---------------------------------------------------------------------------
# fetchers
# ---------------------------------------------------------------------------

class FetcherTest(MonitorsBase):
    def setUp(self):
        super().setUp()
        M.add_company("Acme")
        self.gh = M.add_source("acme", "greenhouse", board="acmetoken")
        self.lv = M.add_source("acme", "lever", site="acme")
        self.rss = M.add_source("acme", "rss", url="https://acme.example/feed")
        self.comp = M.get_company("acme")

    def test_greenhouse_adapter(self):
        postings, err = M.fetch_source(self.comp, self.gh,
                                       http_get=_fake_http(GREENHOUSE_PAYLOAD))
        self.assertIsNone(err)
        self.assertEqual(len(postings), 2)
        p = postings[0]
        self.assertEqual(p["id"], "greenhouse:acmetoken:101")
        self.assertEqual(p["title"], "Senior ML Engineer")
        self.assertEqual(p["location"], "New York, NY")
        self.assertEqual(p["url"], "https://boards.greenhouse.io/acme/jobs/101")
        self.assertEqual(p["department"], "Engineering")
        self.assertEqual(p["posted_date"], "2026-09-20")

    def test_lever_adapter(self):
        postings, err = M.fetch_source(self.comp, self.lv,
                                       http_get=_fake_http(LEVER_PAYLOAD))
        self.assertIsNone(err)
        self.assertEqual(len(postings), 2)
        self.assertEqual(postings[0]["id"], "lever:acme:aaa-111")
        self.assertEqual(postings[0]["title"], "Backend Engineer")
        self.assertEqual(postings[0]["location"], "San Francisco")
        self.assertEqual(postings[0]["department"], "Engineering")
        # epoch millis -> date; epoch seconds -> date
        self.assertEqual(postings[0]["posted_date"], "2026-09-21")
        self.assertEqual(postings[1]["posted_date"], "2026-09-20")

    def test_rss_adapter(self):
        postings, err = M.fetch_source(self.comp, self.rss,
                                       http_get=_fake_http(RSS_PAYLOAD))
        self.assertIsNone(err)
        self.assertEqual(len(postings), 2)
        self.assertEqual(postings[0]["title"], "DevOps Engineer")
        self.assertEqual(postings[0]["url"], "https://acme.example/jobs/1")
        self.assertEqual(postings[0]["posted_date"], "2026-09-21")
        self.assertTrue(postings[0]["id"].startswith("rss:acme:"))

    def test_atom_adapter(self):
        src = M.add_source("acme", "rss", url="https://beta.example/atom")
        postings, err = M.fetch_source(self.comp, src,
                                       http_get=_fake_http(ATOM_PAYLOAD))
        self.assertIsNone(err)
        self.assertEqual(len(postings), 1)
        self.assertEqual(postings[0]["title"], "QA Engineer")
        self.assertEqual(postings[0]["url"], "https://beta.example/jobs/9")

    def test_bad_json_recorded_not_raised(self):
        postings, err = M.fetch_source(self.comp, self.gh,
                                       http_get=_fake_http(b"<html>not json"))
        self.assertEqual(postings, [])
        self.assertIn("Bad JSON", err)

    def test_bad_xml_recorded_not_raised(self):
        postings, err = M.fetch_source(self.comp, self.rss,
                                       http_get=_fake_http(b"<rss><broken"))
        self.assertEqual(postings, [])
        self.assertIn("Bad XML", err)

    def test_http_error_recorded(self):
        exc = urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)
        postings, err = M.fetch_source(self.comp, self.gh,
                                       http_get=_raising_http(exc))
        self.assertEqual(postings, [])
        self.assertIn("404", err)

    def test_url_error_recorded(self):
        exc = urllib.error.URLError("name resolution failed")
        postings, err = M.fetch_source(self.comp, self.gh,
                                       http_get=_raising_http(exc))
        self.assertEqual(postings, [])
        self.assertIn("Unreachable", err)

    def test_timeout_recorded(self):
        postings, err = M.fetch_source(self.comp, self.gh,
                                       http_get=_raising_http(TimeoutError("timed out")))
        self.assertEqual(postings, [])
        self.assertIn("Timed out", err)


# ---------------------------------------------------------------------------
# history + diff
# ---------------------------------------------------------------------------

class DiffTest(MonitorsBase):
    def setUp(self):
        super().setUp()
        M.add_company("Acme")
        M.add_source("acme", "greenhouse", board="acmetoken")
        self.comp = M.get_company("acme")
        self.skey = M._source_key("acme", self.comp["sources"][0])

    def _run(self, payload, today="2026-09-22", closed_after=3):
        postings, err = M.fetch_source(self.comp, self.comp["sources"][0],
                                       http_get=_fake_http(payload))
        self.assertIsNone(err)
        return M.diff_fetch("acme", "Acme", postings, {self.skey},
                            closed_after=closed_after, today=today)

    def test_first_fetch_all_new(self):
        diff = self._run(GREENHOUSE_PAYLOAD)
        self.assertEqual(len(diff["new"]), 2)
        self.assertEqual(diff["closed"], [])
        ids = {p["id"] for p in diff["new"]}
        self.assertIn("greenhouse:acmetoken:101", ids)
        hist = M.get_history("acme")
        rec = hist["greenhouse:acmetoken:101"]
        self.assertEqual(rec["first_seen"], "2026-09-22")
        self.assertEqual(rec["last_seen"], "2026-09-22")
        self.assertEqual(rec["status"], "open")
        self.assertEqual(rec["miss_count"], 0)

    def test_stable_fetch_no_changes(self):
        self._run(GREENHOUSE_PAYLOAD)
        diff = self._run(GREENHOUSE_PAYLOAD, today="2026-09-23")
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["closed"], [])
        hist = M.get_history("acme")
        self.assertEqual(hist["greenhouse:acmetoken:101"]["last_seen"], "2026-09-23")

    def test_missing_posting_closes_after_n_misses(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        one_job = {"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]}
        diff = self._run(one_job, today="2026-09-23")
        self.assertEqual(diff["closed"], [])  # miss 1
        diff = self._run(one_job, today="2026-09-24")
        self.assertEqual(diff["closed"], [])  # miss 2
        diff = self._run(one_job, today="2026-09-25")
        self.assertEqual([p["id"] for p in diff["closed"]],
                         ["greenhouse:acmetoken:102"])  # miss 3 -> closed
        hist = M.get_history("acme")
        rec = hist["greenhouse:acmetoken:102"]
        self.assertEqual(rec["status"], "closed")
        self.assertEqual(rec["closed_at"], "2026-09-25")

    def test_custom_close_threshold(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        one_job = {"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]}
        diff = self._run(one_job, today="2026-09-23", closed_after=1)
        self.assertEqual([p["id"] for p in diff["closed"]],
                         ["greenhouse:acmetoken:102"])

    def test_reappearing_posting_resets_misses(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        one_job = {"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]}
        self._run(one_job, today="2026-09-23")  # miss 1
        diff = self._run(GREENHOUSE_PAYLOAD, today="2026-09-24")
        self.assertEqual(diff["new"], [])  # back — not new, not closed
        hist = M.get_history("acme")
        self.assertEqual(hist["greenhouse:acmetoken:102"]["miss_count"], 0)
        self.assertEqual(hist["greenhouse:acmetoken:102"]["status"], "open")

    def test_failed_source_does_not_accrue_misses(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        # source failed this run: its postings must not count as missing
        diff = M.diff_fetch("acme", "Acme", [], set(), today="2026-09-23")
        self.assertEqual(diff["closed"], [])
        hist = M.get_history("acme")
        self.assertEqual(hist["greenhouse:acmetoken:102"]["miss_count"], 0)

    def test_repost_flagged_within_window(self):
        # close posting 102 quickly
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        self._run({"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]},
                  today="2026-09-23", closed_after=1)
        # it reappears 10 days later under a new id, same title+location
        reopened = {"jobs": [{"id": 201, "title": "Product Designer",
                              "location": {"name": "Remote"},
                              "absolute_url": "https://boards.greenhouse.io/acme/jobs/201",
                              "departments": [{"name": "Design"}],
                              "updated_at": "2026-10-03"}]}
        diff = self._run(reopened, today="2026-10-03")
        self.assertEqual(len(diff["new"]), 1)
        self.assertEqual(len(diff["reposts"]), 1)
        rep = diff["reposts"][0]
        self.assertTrue(rep["repost"])
        self.assertEqual(rep["repost_of"], "greenhouse:acmetoken:102")

    def test_repost_not_flagged_outside_window(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-06-01")
        self._run({"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]},
                  today="2026-06-02", closed_after=1)
        reopened = {"jobs": [{"id": 201, "title": "Product Designer",
                              "location": {"name": "Remote"},
                              "absolute_url": "https://boards.greenhouse.io/acme/jobs/201",
                              "departments": [{"name": "Design"}],
                              "updated_at": "2026-10-03"}]}
        diff = self._run(reopened, today="2026-10-03")
        self.assertEqual(diff["reposts"], [])
        self.assertFalse(diff["new"][0]["repost"])

    def test_closed_posting_reappearing_by_same_id_is_repost(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        self._run({"jobs": GREENHOUSE_PAYLOAD["jobs"][:1]},
                  today="2026-09-23", closed_after=1)
        diff = self._run(GREENHOUSE_PAYLOAD, today="2026-09-30")
        by_id = {p["id"]: p for p in diff["new"]}
        self.assertTrue(by_id["greenhouse:acmetoken:102"]["repost"])
        self.assertEqual(by_id["greenhouse:acmetoken:102"]["status"], "open")

    def test_history_persists(self):
        self._run(GREENHOUSE_PAYLOAD, today="2026-09-22")
        data = json.loads((Path(self.td.name) / "monitor_history.json").read_text())
        postings = data["companies"]["acme"]["postings"]
        self.assertEqual(len(postings), 2)


# ---------------------------------------------------------------------------
# poll + health + backoff
# ---------------------------------------------------------------------------

class PollTest(MonitorsBase):
    def setUp(self):
        super().setUp()
        M.add_company("Acme")
        self.gh_src = M.add_source("acme", "greenhouse", board="acmetoken")
        self.rss_src = M.add_source("acme", "rss", url="https://acme.example/feed")

    def _poll(self, gh_payload, rss_payload=b"", today="2026-09-22"):
        def fake_get(url):
            if "greenhouse" in url:
                if isinstance(gh_payload, Exception):
                    raise gh_payload
                return json.dumps(gh_payload).encode()
            if isinstance(rss_payload, Exception):
                raise rss_payload
            return rss_payload or RSS_PAYLOAD
        return M.poll(http_get=fake_get, today=today)

    def test_poll_never_raises_and_reports(self):
        summary = self._poll(GREENHOUSE_PAYLOAD)
        self.assertEqual(summary["date"], "2026-09-22")
        comp = summary["companies"]["acme"]
        self.assertEqual(comp["fetched"], 4)  # 2 greenhouse + 2 rss
        self.assertEqual(len(comp["new"]), 4)
        self.assertEqual(comp["errors"], [])
        self.assertEqual(summary["totals"]["new"], 4)

    def test_poll_records_source_errors(self):
        exc = urllib.error.HTTPError("https://x", 500, "Server Error", {}, None)
        summary = self._poll(exc)
        comp = summary["companies"]["acme"]
        self.assertEqual(len(comp["errors"]), 1)
        self.assertIn("500", comp["errors"][0])
        self.assertEqual(comp["fetched"], 2)  # rss still worked

    def test_poll_single_company(self):
        M.add_company("Beta")
        M.add_source("beta", "lever", site="beta")
        summary = self._poll(GREENHOUSE_PAYLOAD, today="2026-09-22")
        # poll() with no company arg covers both; single-company poll covers one
        one = M.poll(company="acme", http_get=lambda u: json.dumps(GREENHOUSE_PAYLOAD).encode()
                     if "greenhouse" in u else RSS_PAYLOAD, today="2026-09-22")
        self.assertEqual(list(one["companies"]), ["acme"])

    def test_consecutive_failures_skip_source(self):
        exc = urllib.error.URLError("down")
        for i in range(6):
            summary = self._poll(exc, today=f"2026-09-{22 + i:02d}")
        # 6th failure: counter is 6 > 5, still fetched this time; 7th is skipped
        self.assertEqual(summary["companies"]["acme"]["errors"], ["Unreachable https://boards-api.greenhouse.io/v1/boards/acmetoken/jobs?content=false: down"])
        summary = self._poll(exc, today="2026-09-29")
        skipped = summary["companies"]["acme"]["skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("failing 6x", skipped[0])
        self.assertEqual(summary["totals"]["skipped"], 1)

    def test_success_resets_failure_counter(self):
        exc = urllib.error.URLError("down")
        self._poll(exc)
        self._poll(exc)
        self._poll(GREENHOUSE_PAYLOAD)  # ok again
        h = M.health()
        gh_key = next(k for k in h if "greenhouse" in k)
        self.assertEqual(h[gh_key]["consecutive_failures"], 0)
        self.assertEqual(h[gh_key]["status"], "ok")

    def test_health_statuses(self):
        exc = urllib.error.URLError("down")
        for i in range(7):
            self._poll(exc, today=f"2026-09-{10 + i:02d}")
        h = M.health()
        self.assertEqual(len(h), 2)
        statuses = {k: v["status"] for k, v in h.items()}
        gh_key = next(k for k in h if "greenhouse" in k)
        rss_key = next(k for k in h if "rss" in k)
        self.assertEqual(statuses[gh_key], "skipped")
        self.assertEqual(statuses[rss_key], "ok")
        self.assertIn("down", h[gh_key]["last_error"])
        self.assertEqual(h[gh_key]["company"], "Acme")
        self.assertEqual(h[gh_key]["consecutive_failures"], 6)

    def test_render_summary(self):
        summary = self._poll(GREENHOUSE_PAYLOAD)
        text = M.render_summary(summary)
        self.assertIn("Monitor poll", text)
        self.assertIn("Acme", text)
        self.assertIn("Senior ML Engineer", text)


if __name__ == "__main__":
    unittest.main()
