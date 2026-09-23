"""Tests for the batch-14 niche-board adapters: builtin + wellfound.

Hermetic: _get_text is patched with fixture HTML, so no live network.
Run: python -m unittest tests.test_batch14_wellfound_builtin -v
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import jobs as J  # noqa: E402


def _card(job_id, title, slug, company, posted, chips, industry, desc,
          ld_url=True):
    """One realistic Built In job card, modeled on the live /jobs markup."""
    chip_html = "".join(
        f'<span class="font-barlow text-gray-04">{c}</span>' for c in chips)
    return f'''
<div id="job-card-{job_id}" data-id="job-card">
  <div><a href="/company/{company.lower()}" data-id="company-title">
    <span>{company}</span></a></div>
  <div><h2><a href="/job/{slug}/{job_id}" data-id="job-card-title"
    data-alias="/job/{slug}/{job_id}">{title}</a></h2></div>
  <div><span class="fs-xs fw-bold bg-gray-01">
    <i class="fa-regular fa-clock"></i>{posted}</span></div>
  <div class="chips">{chip_html}</div>
  <div id="drop-data-{job_id}">
    <div class="mb-md fs-xs fw-bold">{industry}</div>
    <div class="fs-sm fw-regular mb-md text-gray-04">{desc}</div>
  </div>
</div>'''


BUILTIN_JSONLD = '''
<script type="application/ld+json">{"@context": "https://schema.org",
"@graph": [{"@type": "CollectionPage", "name": "Built In Jobs"},
{"@type": "ItemList", "name": "jobs", "numberOfItems": 1,
"itemListElement": [{"@type": "ListItem", "position": 1,
"name": "Data Scientist Associate",
"url": "https://builtin.com/job/data-scientist-associate/11318198",
"description": "Build <b>models</b> &amp; dashboards for audit."}]}]}
</script>'''

BUILTIN_FIXTURE = "<html><head>" + BUILTIN_JSONLD + "</head><body>" + "".join([
    _card("11318198", "Data Scientist Associate",
          "data-scientist-associate", "JPMorganChase", "Yesterday",
          ["Hybrid", "New York, NY, USA", "110K-176K Annually",
           "Senior level"],
          "Financial Services",
          "Develop end-to-end data analytics solutions."),
    _card("555", "Remote ML Engineer", "remote-ml-engineer", "StartupXYZ",
          "3 days ago", ["Remote", "United States", "Junior"],
          "Artificial Intelligence",
          "Train <i>ranking</i> models at scale."),
    # malformed card: no title anchor -> skipped, must not fail the run
    '<div id="job-card-777" data-id="job-card"><p>broken</p></div>',
]) + "</body></html>"

WELLFOUND_SHELL = '''<html><head></head><body><div id="__next"></div>
<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">
{"props": {"pageProps": {"__APOLLO_SIG__": "x",
"apolloState": {"data": {"ROOT_QUERY": {"viewer": {"flashMessages": []}}}}}}}
</script></body></html>'''

WELLFOUND_WITH_JOBS = '''<html><head></head><body>
<script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {"search": {"results": [
{"title": "Founding Engineer", "company": {"name": "Acme AI"},
 "id": "abc123", "location": "New York, NY",
 "description": "<p>Build the <b>core</b> platform.</p>",
 "remote": false, "salary": "$150k-$200k", "posted_at": "2026-09-20"}]}}}}
</script></body></html>'''


class BuiltinAdapterTest(unittest.TestCase):
    def _run(self, html=BUILTIN_FIXTURE):
        with patch.object(J, "_get_text", return_value=html):
            return J._adapt_builtin()

    def test_normalization(self):
        jobs = self._run()
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual(j["source"], "builtin")
        self.assertEqual(j["source_id"], "builtin:11318198")
        self.assertEqual(j["title"], "Data Scientist Associate")
        self.assertEqual(j["company"], "JPMorganChase")
        self.assertEqual(j["location"], "New York, NY, USA")
        self.assertEqual(
            j["url"],
            "https://builtin.com/job/data-scientist-associate/11318198")
        self.assertEqual(j["salary_text"], "110K-176K Annually")
        self.assertFalse(j["remote"])
        self.assertEqual(j["posted_at"],
                         (date.today() - timedelta(days=1)).isoformat())

    def test_extras_captured(self):
        j = self._run()[0]
        self.assertEqual(j["work_mode"], "Hybrid")
        self.assertEqual(j["seniority"], "Senior level")
        self.assertEqual(j["industry"], "Financial Services")

    def test_remote_card(self):
        j = self._run()[1]
        self.assertEqual(j["source_id"], "builtin:555")
        self.assertTrue(j["remote"])
        self.assertEqual(j["salary_text"], "")
        self.assertEqual(j["posted_at"],
                         (date.today() - timedelta(days=3)).isoformat())

    def test_description_prefers_jsonld_and_strips_html(self):
        # card 1's description comes from JSON-LD, with tags stripped
        self.assertEqual(self._run()[0]["description"],
                         "Build models & dashboards for audit.")

    def test_description_falls_back_to_card(self):
        # card 2 has no JSON-LD entry -> card text, tags stripped
        self.assertEqual(self._run()[1]["description"],
                         "Train ranking models at scale.")

    def test_description_capped_at_4000(self):
        long_desc = "x" * 5000
        html = "<html><body>" + _card(
            "1", "T", "t", "C", "Yesterday", ["Hybrid"], "I", long_desc
        ) + "</body></html>"
        jobs = self._run(html)
        self.assertEqual(len(jobs[0]["description"]), 4000)

    def test_source_id_stable(self):
        self.assertEqual([j["source_id"] for j in self._run()],
                         [j["source_id"] for j in self._run()])

    def test_caps_at_max_per_source(self):
        html = "<html><body>" + "".join(
            _card(str(i), "T", "t", "C", "Yesterday",
                  ["Hybrid", "New York, NY, USA"], "I", "desc")
            for i in range(J.MAX_PER_SOURCE + 5)) + "</body></html>"
        self.assertEqual(len(self._run(html)), J.MAX_PER_SOURCE)

    def test_jobs_error_when_unreachable(self):
        with patch.object(J, "_get_text", side_effect=OSError("down")):
            with self.assertRaises(J.JobsError):
                J._adapt_builtin()

    def test_malformed_jsonld_does_not_fail(self):
        html = ('<html><head><script type="application/ld+json">'
                'not json{{{</script></head><body>'
                + _card("9", "T", "t", "C", "Yesterday",
                        ["Hybrid"], "I", "desc") + "</body></html>")
        jobs = self._run(html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["description"], "desc")

    def test_posted_at_labels(self):
        self.assertEqual(J._builtin_posted_at("Today"), date.today().isoformat())
        self.assertEqual(J._builtin_posted_at("2 weeks ago"),
                         (date.today() - timedelta(days=14)).isoformat())
        self.assertEqual(J._builtin_posted_at("1 month ago"),
                         (date.today() - timedelta(days=30)).isoformat())
        self.assertEqual(J._builtin_posted_at("6 Minutes Ago"),
                         date.today().isoformat())
        self.assertEqual(J._builtin_posted_at("3 hours ago"),
                         date.today().isoformat())
        self.assertEqual(J._builtin_posted_at("sometime"), "")

    def test_registered(self):
        self.assertIn("builtin", J.ADAPTERS)
        self.assertIs(J.ADAPTERS["builtin"], J._adapt_builtin)


class WellfoundAdapterTest(unittest.TestCase):
    def _run(self, html=WELLFOUND_SHELL):
        with patch.object(J, "_get_text", return_value=html):
            return J._adapt_wellfound()

    def test_empty_shell_returns_empty_gracefully(self):
        # No JobsError: the JS-only page is a known limitation, not a failure.
        self.assertEqual(self._run(), [])

    def test_embedded_payload_normalized_when_present(self):
        jobs = self._run(WELLFOUND_WITH_JOBS)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["source"], "wellfound")
        self.assertEqual(j["source_id"], "wellfound:abc123")
        self.assertEqual(j["title"], "Founding Engineer")
        self.assertEqual(j["company"], "Acme AI")
        self.assertEqual(j["location"], "New York, NY")
        self.assertEqual(j["url"], "https://wellfound.com/jobs/abc123")
        self.assertEqual(j["description"], "Build the core platform.")
        self.assertEqual(j["salary_text"], "$150k-$200k")
        self.assertFalse(j["remote"])
        self.assertEqual(j["posted_at"], "2026-09-20")

    def test_invalid_embedded_json_skipped(self):
        html = ('<html><body><script id="__NEXT_DATA__" '
                'type="application/json">nope{{{</script></body></html>')
        self.assertEqual(self._run(html), [])

    def test_jobs_error_when_unreachable(self):
        with patch.object(J, "_get_text", side_effect=OSError("down")):
            with self.assertRaises(J.JobsError):
                J._adapt_wellfound()

    def test_registered(self):
        self.assertIn("wellfound", J.ADAPTERS)
        self.assertIs(J.ADAPTERS["wellfound"], J._adapt_wellfound)


if __name__ == "__main__":
    unittest.main()
