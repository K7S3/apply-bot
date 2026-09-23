"""Tests for candid.academic_feeds — RSS/Atom parsing, registry, adapters, CLI.

All network is mocked (urllib / _http_get patched); zero real HTTP here.
Run: python -m pytest tests/test_academic_feeds.py -q
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import academic_feeds as AF  # noqa: E402
from candid import config as C  # noqa: E402

RSS_FIXTURE = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Job Search RSS</title>
<link>https://example.com/jobs</link>
<item>
<title>City University: Chair Professor of Computer Science</title>
<link>https://example.com/job/1</link>
<guid>https://example.com/job/1</guid>
<pubDate>Tue, 22 Sep 2026 09:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>Lead our <b>AI</b> lab. $150k-$180k per year.</p>]]></content:encoded>
</item>
<item>
<title>Remote Data Scientist (New York, NY)</title>
<link>https://example.com/job/2</link>
<guid>job-2</guid>
<pubDate>2026-09-20</pubDate>
<description>Join us &amp; build models.</description>
</item>
</channel>
</rss>"""

ATOM_FIXTURE = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Uni Jobs</title>
<entry>
<title>Postdoc in ML</title>
<link href="https://example.com/job/9" rel="alternate"/>
<id>urn:job:9</id>
<updated>2026-09-21T10:00:00Z</updated>
<author><name>Example University</name></author>
<summary>Two-year <i>postdoc</i> position.</summary>
</entry>
</feed>"""

RDF_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<RDF xmlns="http://purl.org/rss/1.0/">
<channel><title>RDF Jobs</title><link>https://example.com/</link></channel>
<item><title>RDF Item</title><link>https://example.com/r1</link></item>
</RDF>"""

EMPTY_FIXTURE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""


class _FakeResp:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AcademicFeedsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-feeds-test-")
        self._old_data_dir = C.DATA_DIR
        C.DATA_DIR = Path(self.tmp)
        os.environ["CANDID_DATA_DIR"] = self.tmp

    def tearDown(self):
        C.DATA_DIR = self._old_data_dir
        os.environ.pop("CANDID_DATA_DIR", None)

    # -- parsing ------------------------------------------------------

    def test_parse_rss(self):
        feed = AF.parse_feed(RSS_FIXTURE)
        self.assertEqual(feed["title"], "Job Search RSS")
        self.assertEqual(len(feed["entries"]), 2)
        first = feed["entries"][0]
        self.assertEqual(first["title"],
                         "City University: Chair Professor of Computer Science")
        self.assertEqual(first["url"], "https://example.com/job/1")
        self.assertIn("Lead our", first["description"])  # content:encoded wins
        self.assertEqual(first["posted_at"], "Tue, 22 Sep 2026 09:00:00 +0000")

    def test_parse_atom(self):
        feed = AF.parse_feed(ATOM_FIXTURE)
        self.assertEqual(len(feed["entries"]), 1)
        e = feed["entries"][0]
        self.assertEqual(e["title"], "Postdoc in ML")
        self.assertEqual(e["url"], "https://example.com/job/9")
        self.assertEqual(e["author"], "Example University")
        self.assertIn("postdoc", e["description"])

    def test_parse_rdf_case_insensitive(self):
        feed = AF.parse_feed(RDF_FIXTURE)
        self.assertEqual(feed["title"], "RDF Jobs")
        self.assertEqual(len(feed["entries"]), 1)

    def test_parse_malformed_raises(self):
        with self.assertRaises(AF.FeedsError):
            AF.parse_feed(b"<rss><channel><item>oops")

    def test_parse_unknown_root_raises(self):
        with self.assertRaises(AF.FeedsError):
            AF.parse_feed(b"<html><body>not a feed</body></html>")

    # -- fetching ------------------------------------------------------

    def test_fetch_entries_ok(self):
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            entries = AF.fetch_entries("https://example.com/rss")
        self.assertEqual(len(entries), 2)

    def test_fetch_entries_empty_raises(self):
        with patch.object(AF, "_http_get", return_value=EMPTY_FIXTURE):
            with self.assertRaises(AF.FeedsError):
                AF.fetch_entries("https://example.com/rss")

    def test_fetch_entries_http_error(self):
        err = urllib.error.HTTPError("https://example.com/rss", 404, "NF",
                                     {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(AF.FeedsError) as cm:
                AF.fetch_entries("https://example.com/rss")
        self.assertIn("404", str(cm.exception))

    def test_fetch_entries_unreachable(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("nope")):
            with self.assertRaises(AF.FeedsError):
                AF.fetch_entries("https://example.com/rss")

    def test_fetch_entries_oversize_rejected(self):
        with patch.object(AF, "_http_get", return_value=b"x" * 6_000_000):
            with self.assertRaises(AF.FeedsError):
                AF.fetch_entries("https://example.com/rss")

    def test_verify_feed_never_raises(self):
        with patch.object(AF, "_http_get",
                           side_effect=AF.FeedsError("boom")):
            r = AF.verify_feed("https://example.com/rss")
        self.assertFalse(r["ok"])
        self.assertIn("boom", r["message"])

    def test_verify_feed_ok(self):
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            r = AF.verify_feed("https://example.com/rss")
        self.assertTrue(r["ok"])
        self.assertEqual(r["entries"], 2)
        self.assertEqual(r["title"], "Job Search RSS")

    # -- normalization -------------------------------------------------

    def test_normalize_job_schema(self):
        entry = {"title": "Remote Data Scientist (New York, NY)",
                 "url": "https://example.com/job/2", "guid": "job-2",
                 "description": "Join us &amp; build models.",
                 "posted_at": "Tue, 22 Sep 2026 09:00:00 +0000",
                 "author": "", "location": ""}
        job = AF.normalize_job("academic", "Test Board", entry)
        self.assertEqual(job["source"], "academic")
        self.assertTrue(job["source_id"].startswith("academic:"))
        self.assertEqual(job["title"], "Remote Data Scientist")
        self.assertEqual(job["location"], "New York, NY")
        self.assertTrue(job["remote"])
        self.assertEqual(job["posted_at"], "2026-09-22")
        self.assertEqual(job["description"], "Join us & build models.")
        # stable id across runs
        again = AF.normalize_job("academic", "Test Board", entry)
        self.assertEqual(job["source_id"], again["source_id"])

    def test_normalize_employer_sep(self):
        entry = {"title": "City University: Chair Professor",
                 "url": "https://example.com/1", "guid": "g1",
                 "description": "", "posted_at": "", "author": "",
                 "location": ""}
        job = AF.normalize_job("naturecareers", "Nature Careers", entry,
                               employer_sep=": ")
        self.assertEqual(job["company"], "City University")
        self.assertEqual(job["title"], "Chair Professor")

    def test_normalize_desc_employer(self):
        entry = {"title": "Research Fellow", "url": "https://example.com/1",
                 "guid": "g1",
                 "description": "University of Chicago (Chicago, IL)",
                 "posted_at": "", "author": "", "location": ""}
        job = AF.normalize_job("academic", "HigherEdJobs", entry,
                               desc_employer=True)
        self.assertEqual(job["company"], "University of Chicago")
        self.assertEqual(job["location"], "Chicago, IL")

    def test_normalize_salary_extraction(self):
        entry = {"title": "Engineer $150k-$180k", "url": "https://e.com/1",
                 "guid": "g1", "description": "", "posted_at": "",
                 "author": "", "location": ""}
        job = AF.normalize_job("academic", "Board", entry)
        self.assertEqual(job["salary_text"], "$150k-$180k")

    def test_normalize_title_paren_without_comma_kept(self):
        entry = {"title": "Researcher (AI)", "url": "https://e.com/1",
                 "guid": "g1", "description": "", "posted_at": "",
                 "author": "", "location": ""}
        job = AF.normalize_job("academic", "Board", entry)
        self.assertEqual(job["title"], "Researcher (AI)")
        self.assertEqual(job["location"], "")

    # -- registry --------------------------------------------------------

    def test_registry_seeds_listed(self):
        feeds = AF.registry_list()
        names = [f["name"] for f in feeds]
        self.assertIn("Nature Careers", names)
        self.assertTrue(all(f["seed"] for f in feeds))

    def test_registry_add_list_remove_roundtrip(self):
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            rec = AF.registry_add("Test Uni", "https://example.com/rss")
        self.assertTrue(rec["verified"])
        self.assertEqual(rec["entries_checked"], 2)
        names = [f["name"] for f in AF.registry_list()]
        self.assertIn("Test Uni", names)
        # persisted to disk
        data = json.loads((Path(self.tmp) / AF.REGISTRY_FILENAME)
                          .read_text(encoding="utf-8"))
        self.assertTrue(any(f["url"] == "https://example.com/rss"
                            for f in data["feeds"]))
        gone = AF.registry_remove("Test Uni")
        self.assertEqual(gone["name"], "Test Uni")
        self.assertNotIn("Test Uni",
                         [f["name"] for f in AF.registry_list()])

    def test_registry_add_duplicate_rejected(self):
        with self.assertRaises(AF.FeedsError):
            AF.registry_add("Dupe", "https://www.nature.com/naturecareers/jobsrss/",
                            verify=False)

    def test_registry_add_bad_url_rejected(self):
        with self.assertRaises(AF.FeedsError):
            AF.registry_add("Bad", "not-a-url", verify=False)

    def test_registry_add_verify_failure_not_saved(self):
        with patch.object(AF, "_http_get",
                           side_effect=AF.FeedsError("down")):
            with self.assertRaises(AF.FeedsError):
                AF.registry_add("Down", "https://example.com/down")
        self.assertNotIn("Down", [f["name"] for f in AF.registry_list()])

    def test_registry_remove_seed_and_readd(self):
        url = "https://www.nature.com/naturecareers/jobsrss/"
        gone = AF.registry_remove("Nature Careers")
        self.assertTrue(gone["seed"])
        self.assertNotIn("Nature Careers",
                         [f["name"] for f in AF.registry_list()])
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            AF.registry_add("Nature Careers", url)
        self.assertIn("Nature Careers",
                      [f["name"] for f in AF.registry_list()])

    def test_registry_remove_unknown_raises(self):
        with self.assertRaises(AF.FeedsError):
            AF.registry_remove("No Such Feed")

    # -- adapters --------------------------------------------------------

    def test_adapt_research_feed(self):
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            jobs = AF.adapt_research_feed("naturecareers")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["source"], "naturecareers")
        self.assertEqual(jobs[0]["company"], "City University")
        self.assertEqual(jobs[0]["title"],
                         "Chair Professor of Computer Science")

    def test_adapt_research_feed_unknown_key(self):
        with self.assertRaises(AF.FeedsError):
            AF.adapt_research_feed("nope")

    def test_adapt_research_feed_failure(self):
        with patch.object(AF, "_http_get",
                           side_effect=AF.FeedsError("down")):
            with self.assertRaises(AF.FeedsError):
                AF.adapt_research_feed("naturecareers")

    def test_fetch_registry_partial_failure(self):
        def fake_get(url):
            if "bad" in url:
                raise AF.FeedsError("kaput")
            return RSS_FIXTURE

        with patch.object(AF, "DEFAULT_FEEDS", [
                {"name": "Good", "url": "https://example.com/good",
                 "verified": True},
                {"name": "Bad", "url": "https://example.com/bad",
                 "verified": True}]):
            with patch.object(AF, "_http_get", side_effect=fake_get):
                with contextlib.redirect_stderr(io.StringIO()):
                    jobs, errors = AF.fetch_registry()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(errors), 1)
        self.assertIn("Bad", errors[0])

    def test_adapt_academic_registry_empty(self):
        with patch.object(AF, "DEFAULT_FEEDS", []):
            with self.assertRaises(AF.FeedsError):
                AF.adapt_academic_registry()

    # -- jobs.py wiring ---------------------------------------------------

    def test_jobs_extra_adapters_registered(self):
        from candid import jobs as J
        self.assertIn("naturecareers", J.EXTRA_ADAPTERS)
        self.assertIn("academic", J.EXTRA_ADAPTERS)
        self.assertNotIn("naturecareers", J.ADAPTERS)  # opt-in only
        self.assertNotIn("academic", J.ADAPTERS)

    def test_jobs_adapter_converts_errors(self):
        from candid import jobs as J
        with patch.object(AF, "adapt_research_feed",
                           side_effect=AF.FeedsError("down")):
            with self.assertRaises(J.JobsError):
                J.EXTRA_ADAPTERS["naturecareers"]()

    def test_curate_unknown_source_lists_extras(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError) as cm:
            J.curate({}, role="Postdoc", sources=["nope"])
        self.assertIn("naturecareers", str(cm.exception))

    # -- CLI ---------------------------------------------------------------

    def _parser(self):
        p = argparse.ArgumentParser(prog="candid")
        sub = p.add_subparsers(dest="cmd", required=True)
        AF.add_parsers(sub)
        return p

    def test_cli_list_json(self):
        args = self._parser().parse_args(["feeds", "list", "--json"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = AF.cmd_feeds(args)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(any(f["name"] == "Nature Careers" for f in data))

    def test_cli_add_and_remove(self):
        with patch.object(AF, "_http_get", return_value=RSS_FIXTURE):
            args = self._parser().parse_args(
                ["feeds", "add", "Test Uni", "https://example.com/rss"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = AF.cmd_feeds(args)
        self.assertEqual(rc, 0)
        self.assertIn("Added", buf.getvalue())

        args = self._parser().parse_args(["feeds", "remove", "Test Uni"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = AF.cmd_feeds(args)
        self.assertEqual(rc, 0)
        self.assertIn("Removed", buf.getvalue())

    def test_cli_add_bad_url_fails(self):
        args = self._parser().parse_args(
            ["feeds", "add", "Bad", "notaurl", "--no-verify"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = AF.cmd_feeds(args)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
