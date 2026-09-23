"""Tests for candid.usajobs — USAJOBS search adapter, sample announcements,
and the announcement detail parser.

All HTTP is mocked; no real network is made in these tests.
Run: python -m unittest tests.test_federal_usajobs -v
"""
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import usajobs as U  # noqa: E402
from candid.jobs import JobsError  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _descriptor(**kw):
    d = {
        "PositionID": "DE-12345678-26-ABC",
        "PositionTitle": "Computer Scientist",
        "OrganizationName": "Department of the Navy",
        "DepartmentName": "Department of Defense",
        "PositionURI": "https://www.usajobs.gov/GetJob/ViewDetails/12345",
        "ApplyURI": ["https://apply.usajobs.gov/12345"],
        "PositionLocationDisplay": "Washington, District of Columbia",
        "PositionLocation": [
            {"CityName": "Washington", "StateName": "District of Columbia",
             "CountryCode": "United States"},
            {"CityName": "Arlington", "StateName": "Virginia",
             "CountryCode": "United States"},
        ],
        "PositionStartDate": "09/15/2026 12:00:00 AM",
        "PositionEndDate": "10/15/2026 11:59:00 PM",
        "PublicationStartDate": "09/15/2026 12:00:00 AM",
        "QualificationSummary": "One year of specialized experience at the GS-12 level.",
        "PositionFormattedDescription": [
            {"Label": "Summary", "Content": "<p>Build <b>ML</b> models for the fleet.</p>"},
            {"Label": "Duties", "Content": "Design, train, deploy."},
        ],
        "PositionRemuneration": [
            {"MinimumRange": "104604", "MaximumRange": "135987",
             "RateIntervalCode": "PA", "Description": "$104,604 - $135,987 per year"}
        ],
        "JobGrade": [{"Code": "12", "Name": "GS-12"}, {"Code": "13", "Name": "GS-13"}],
        "LowGrade": "12", "HighGrade": "13",
        "PayPlan": "GS",
        "JobCategory": [{"Code": "1550", "Name": "Computer Science"}],
        "UserArea": {
            "Details": {
                "JobSummary": "Lead AI research.",
                "WhoMayApply": {"Name": "Open to the public", "Code": "public"},
                "HiringPaths": ["public", "vet"],
                "TeleworkEligible": True,
                "RemoteIndicator": False,
                "SecurityClearance": {"Code": "S", "Name": "Secret"},
                "CitizenshipRequired": True,
                "ApplyOnlineUrl": "https://apply.usajobs.gov/12345",
            }
        },
    }
    d.update(kw)
    return d


def _search_payload(*descriptors):
    return {
        "LanguageCode": "en",
        "SearchResult": {
            "SearchResultCount": len(descriptors),
            "SearchResultItems": [
                {"MatchedObjectDescriptor": d,
                 "MatchedObjectId": d.get("PositionID", ""),
                 "RelevanceRank": 1}
                for d in descriptors
            ],
        },
    }


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _mock_urlopen(payload=None, error=None):
    def _f(req, timeout=None):
        _f.captured = req  # remember the Request for URL/header assertions
        if error is not None:
            raise error
        body = json.dumps(payload).encode("utf-8")
        return _FakeResp(body)
    _f.captured = None
    return _f


def _no_key_env():
    """patch.dict removing CANDID_USAJOBS_KEY from the environment."""
    env = dict(os.environ)
    env.pop(U.ENV_KEY, None)
    return patch.dict(os.environ, env, clear=True)


# ---------------------------------------------------------------------------
# search() — key handling
# ---------------------------------------------------------------------------

class SearchKeyTest(unittest.TestCase):
    def test_no_key_raises_friendly_error(self):
        with _no_key_env():
            with self.assertRaises(U.UsajobsError) as cm:
                U.search("data scientist")
        msg = str(cm.exception)
        self.assertIn("developer.usajobs.gov", msg)
        self.assertIn(U.ENV_KEY, msg)
        self.assertIn("sample_announcements", msg)

    def test_usajobs_error_is_jobs_error(self):
        self.assertTrue(issubclass(U.UsajobsError, JobsError))

    def test_env_key_used(self):
        with patch.dict(os.environ, {U.ENV_KEY: "env-key-123"}):
            with patch.object(urllib.request, "urlopen",
                              _mock_urlopen(_search_payload())) as _:
                U.search("data scientist")
                # no exception -> env key accepted

    def test_explicit_key_beats_missing_env(self):
        with _no_key_env():
            with patch.object(urllib.request, "urlopen",
                              _mock_urlopen(_search_payload())):
                jobs = U.search("data scientist", api_key="explicit-key")
        self.assertEqual(jobs, [])


# ---------------------------------------------------------------------------
# search() — request building and normalization
# ---------------------------------------------------------------------------

class SearchRequestTest(unittest.TestCase):
    def _run(self, **kw):
        fake = _mock_urlopen(_search_payload(_descriptor()))
        with patch.object(urllib.request, "urlopen", fake):
            jobs = U.search("data scientist", api_key="k", **kw)
        return fake.captured, jobs

    def test_query_params(self):
        req, _ = self._run(location="New York", series="1550", grade="12-13",
                           results_per_page=50)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        self.assertEqual(q["Keyword"], "data scientist")
        self.assertEqual(q["LocationName"], "New York")
        self.assertEqual(q["JobCategoryCode"], "1550")
        self.assertEqual(q["PayGradeLow"], "12")
        self.assertEqual(q["PayGradeHigh"], "13")
        self.assertEqual(q["ResultsPerPage"], "50")

    def test_single_grade(self):
        req, _ = self._run(grade="13")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        self.assertEqual(q["PayGradeLow"], "13")
        self.assertEqual(q["PayGradeHigh"], "13")

    def test_auth_header_sent(self):
        req, _ = self._run()
        self.assertEqual(req.get_header("Authorization-key"), "k")

    def test_normalized_shape(self):
        _, jobs = self._run()
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["source"], "usajobs")
        self.assertEqual(j["source_id"], "usajobs:DE-12345678-26-ABC")
        self.assertEqual(j["title"], "Computer Scientist")
        self.assertEqual(j["company"], "Department of the Navy")
        self.assertEqual(j["location"], "Washington, District of Columbia")
        self.assertEqual(j["url"], "https://www.usajobs.gov/GetJob/ViewDetails/12345")
        self.assertEqual(j["salary_text"], "$104,604 - $135,987 per year")
        self.assertFalse(j["remote"])
        self.assertIn("ML", j["description"])      # HTML stripped
        self.assertNotIn("<p>", j["description"])
        self.assertEqual(j["posted_at"], "09/15/2026 12:00:00 AM")
        # normalized keys match the jobs.py contract
        self.assertEqual(set(j),
                         {"source", "source_id", "title", "company", "location",
                          "url", "description", "salary_text", "remote", "posted_at"})

    def test_remote_indicator_true(self):
        d = _descriptor()
        d["UserArea"]["Details"]["RemoteIndicator"] = True
        fake = _mock_urlopen(_search_payload(d))
        with patch.object(urllib.request, "urlopen", fake):
            jobs = U.search("x", api_key="k")
        self.assertTrue(jobs[0]["remote"])

    def test_multiple_items(self):
        d1, d2 = _descriptor(), _descriptor(PositionID="DE-999", PositionTitle="Clerk")
        fake = _mock_urlopen(_search_payload(d1, d2))
        with patch.object(urllib.request, "urlopen", fake):
            jobs = U.search("x", api_key="k")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[1]["title"], "Clerk")

    def test_results_per_page_clamped(self):
        req, _ = self._run(results_per_page=9999)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        self.assertEqual(q["ResultsPerPage"], str(U.MAX_RESULTS_PER_PAGE))


class SearchErrorsTest(unittest.TestCase):
    def test_401_gives_key_guidance(self):
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        with patch.object(urllib.request, "urlopen", _mock_urlopen(error=err)):
            with self.assertRaises(U.UsajobsError) as cm:
                U.search("x", api_key="bad")
        self.assertIn("401", str(cm.exception))
        self.assertIn(U.ENV_KEY, str(cm.exception))

    def test_500_gives_status(self):
        err = urllib.error.HTTPError("http://x", 500, "Server Error", {}, None)
        with patch.object(urllib.request, "urlopen", _mock_urlopen(error=err)):
            with self.assertRaises(U.UsajobsError) as cm:
                U.search("x", api_key="k")
        self.assertIn("500", str(cm.exception))

    def test_url_error(self):
        err = urllib.error.URLError("connection refused")
        with patch.object(urllib.request, "urlopen", _mock_urlopen(error=err)):
            with self.assertRaises(U.UsajobsError) as cm:
                U.search("x", api_key="k")
        self.assertIn("unreachable", str(cm.exception).lower())

    def test_timeout(self):
        with patch.object(urllib.request, "urlopen",
                          _mock_urlopen(error=TimeoutError("slow"))):
            with self.assertRaises(U.UsajobsError) as cm:
                U.search("x", api_key="k")
        self.assertIn("timed out", str(cm.exception).lower())

    def test_bad_json(self):
        def _f(req, timeout=None):
            return _FakeResp(b"<html>not json</html>")
        with patch.object(urllib.request, "urlopen", _f):
            with self.assertRaises(U.UsajobsError):
                U.search("x", api_key="k")


# ---------------------------------------------------------------------------
# adapt_search_results()
# ---------------------------------------------------------------------------

class AdaptTest(unittest.TestCase):
    def test_full_payload(self):
        jobs = U.adapt_search_results(_search_payload(_descriptor()))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "usajobs")

    def test_malformed_payloads_yield_empty(self):
        for bad in ({}, {"SearchResult": {}}, {"SearchResult": {"SearchResultItems": None}},
                    {"SearchResult": {"SearchResultItems": ["junk", 42, None]}},
                    None, [], "junk"):
            self.assertEqual(U.adapt_search_results(bad), [], f"payload: {bad!r}")

    def test_bad_item_skipped_not_fatal(self):
        good = {"MatchedObjectDescriptor": _descriptor()}
        bad = {"MatchedObjectDescriptor": None}
        payload = {"SearchResult": {"SearchResultItems": [bad, good, {"nope": 1}]}}
        jobs = U.adapt_search_results(payload)
        self.assertEqual(len(jobs), 1)

    def test_company_falls_back_to_department(self):
        d = _descriptor(OrganizationName="", DepartmentName="Dept of Widgets")
        jobs = U.adapt_search_results(_search_payload(d))
        self.assertEqual(jobs[0]["company"], "Dept of Widgets")

    def test_url_falls_back_to_apply_uri(self):
        d = _descriptor(PositionURI="", ApplyURI=["https://apply.example/9"])
        jobs = U.adapt_search_results(_search_payload(d))
        self.assertEqual(jobs[0]["url"], "https://apply.example/9")

    def test_opt_in_adapter_wiring(self):
        fake = _mock_urlopen(_search_payload(_descriptor()))
        with patch.object(urllib.request, "urlopen", fake):
            import candid.jobs as J
            with patch.dict(J.ADAPTERS, {"usajobs": U.opt_in_adapter("x", api_key="k")}):
                self.assertIn("usajobs", J.ADAPTERS)
                jobs = J.ADAPTERS["usajobs"]()
        self.assertEqual(jobs[0]["source"], "usajobs")


# ---------------------------------------------------------------------------
# sample_announcements()
# ---------------------------------------------------------------------------

class SamplesTest(unittest.TestCase):
    def test_samples_present_and_labeled(self):
        samples = U.sample_announcements()
        self.assertGreaterEqual(len(samples), 3)
        for s in samples:
            self.assertEqual(s["source"], "usajobs")
            label = (s["title"] + s["description"] + s["source_id"]).upper()
            self.assertIn("SAMPLE", label, f"unlabeled sample: {s['source_id']}")
            # normalized contract keys
            self.assertEqual(set(s),
                             {"source", "source_id", "title", "company", "location",
                              "url", "description", "salary_text", "remote", "posted_at"})

    def test_samples_are_copies(self):
        a = U.sample_announcements()
        b = U.sample_announcements()
        a[0]["title"] = "mutated"
        self.assertNotEqual(a[0]["title"], b[0]["title"])

    def test_samples_survive_pipeline_helpers(self):
        from candid import jobs as J
        samples = U.sample_announcements()
        out = J.filter_jobs(samples, "data scientist", "", True, None, 10)
        self.assertTrue(all(j["source"] == "usajobs" for j in out))


# ---------------------------------------------------------------------------
# parse_announcement()
# ---------------------------------------------------------------------------

class ParseTest(unittest.TestCase):
    def test_full_detail(self):
        p = U.parse_announcement(_search_payload(_descriptor()))
        self.assertEqual(p["title"], "Computer Scientist")
        self.assertEqual(p["agency"], "Department of the Navy")
        self.assertEqual(p["pay_plan"], "GS")
        self.assertEqual(p["grade_range"], "GS 12-13")
        self.assertEqual(p["occupation_series"], "1550")
        self.assertEqual(p["who_may_apply"], "Open to the public")
        self.assertEqual(p["hiring_paths"],
                         {"public": True, "federal_employee": False, "veteran": True})
        self.assertEqual(p["closing_date"], "10/15/2026 11:59:00 PM")
        self.assertEqual(p["duty_locations"],
                         ["Washington, District of Columbia", "Arlington, Virginia"])
        self.assertFalse(p["remote"])
        self.assertTrue(p["telework_eligible"])
        self.assertEqual(p["clearance_required"], "Secret")
        self.assertTrue(p["citizenship_required"])
        self.assertTrue(p["questionnaire_required"])

    def test_accepts_bare_descriptor(self):
        p = U.parse_announcement(_descriptor())
        self.assertEqual(p["title"], "Computer Scientist")
        self.assertEqual(p["grade_range"], "GS 12-13")

    def test_accepts_item_wrapper(self):
        p = U.parse_announcement({"MatchedObjectDescriptor": _descriptor()})
        self.assertEqual(p["occupation_series"], "1550")

    def test_missing_everything_never_crashes(self):
        for bad in ({}, {"SearchResult": {}}, {"SearchResult": {"SearchResultItems": []}},
                    {"MatchedObjectDescriptor": {}}, None, "junk", 42):
            p = U.parse_announcement(bad)
            self.assertIsNone(p["title"])
            self.assertIsNone(p["agency"])
            self.assertIsNone(p["pay_plan"])
            self.assertIsNone(p["grade_range"])
            self.assertIsNone(p["occupation_series"])
            self.assertIsNone(p["who_may_apply"])
            self.assertEqual(p["hiring_paths"],
                             {"public": False, "federal_employee": False, "veteran": False})
            self.assertIsNone(p["closing_date"])
            self.assertEqual(p["duty_locations"], [])
            self.assertFalse(p["remote"])
            self.assertFalse(p["telework_eligible"])
            self.assertIsNone(p["clearance_required"])
            self.assertIsNone(p["citizenship_required"])
            self.assertFalse(p["questionnaire_required"])

    def test_single_grade(self):
        d = _descriptor(JobGrade=[{"Code": "13", "Name": "GS-13"}],
                        LowGrade="13", HighGrade="13")
        p = U.parse_announcement(d)
        self.assertEqual(p["grade_range"], "GS 13")

    def test_grade_range_without_pay_plan(self):
        d = _descriptor(PayPlan="", JobGrade=[{"Code": "11"}, {"Code": "12"}],
                        LowGrade="11", HighGrade="12")
        p = U.parse_announcement(d)
        self.assertEqual(p["grade_range"], "11-12")

    def test_federal_employee_hiring_path(self):
        d = _descriptor()
        d["UserArea"]["Details"]["HiringPaths"] = ["fed-competitive", "fed-excepted"]
        d["UserArea"]["Details"]["WhoMayApply"] = {}
        p = U.parse_announcement(d)
        self.assertTrue(p["hiring_paths"]["federal_employee"])
        self.assertFalse(p["hiring_paths"]["public"])
        self.assertFalse(p["hiring_paths"]["veteran"])
        self.assertIn("Federal employees", p["who_may_apply"])

    def test_remote_indicator_in_details(self):
        d = _descriptor()
        d["UserArea"]["Details"]["RemoteIndicator"] = True
        p = U.parse_announcement(d)
        self.assertTrue(p["remote"])

    def test_duty_locations_fallback_to_display(self):
        d = _descriptor(PositionLocation=[], PositionLocationDisplay="Anywhere in the U.S.")
        p = U.parse_announcement(d)
        self.assertEqual(p["duty_locations"], ["Anywhere in the U.S."])

    def test_series_from_title_fallback(self):
        d = _descriptor(JobCategory=[])
        d["PositionTitle"] = "Mathematician (1520)"
        p = U.parse_announcement(d)
        self.assertEqual(p["occupation_series"], "1520")

    def test_string_clearance_and_citizenship(self):
        d = _descriptor()
        det = d["UserArea"]["Details"]
        det["SecurityClearance"] = "Top Secret"
        det["CitizenshipRequired"] = "Must be a U.S. citizen"
        p = U.parse_announcement(d)
        self.assertEqual(p["clearance_required"], "Top Secret")
        self.assertEqual(p["citizenship_required"], "Must be a U.S. citizen")


if __name__ == "__main__":
    unittest.main()
