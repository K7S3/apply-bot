"""CLI-level tests for `python -m candid federal ...`.

No network is touched: live USAJOBS search is only exercised through the
no-key graceful path (and the bundled --samples), and one keyed search is
simulated by mocking candid.usajobs.search. Run:
python -m unittest discover -s tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics",
               "cloud security"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 - Present",
                    "bullets": ["Built churn models with XGBoost."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
}

SAMPLE_ANNOUNCE = Path(ROOT) / "samples" / "federal_sample.json"

PLAIN_JD = ("IT Specialist (INFOSEC), GS-13. Requires one year of specialized "
            "experience equivalent to GS-12, including cloud security "
            "architecture and incident response. Python automation experience "
            "preferred. US citizenship required.")


class FederalCliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-federal-cli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))
        # guarantee no live USAJOBS key leaks into these tests
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("CANDID_USAJOBS_KEY", None)

    def tearDown(self):
        self._env.stop()
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    def run_json(self, argv):
        code, out, err = self.run_cli(argv)
        self.assertEqual(code, 0, f"{argv} failed: {err}")
        return json.loads(out)


class SearchTest(FederalCliBase):
    def test_search_samples_prints_readable(self):
        code, out, err = self.run_cli(
            ["federal", "search", "--keyword", "data scientist", "--samples"])
        self.assertEqual(code, 0, err)
        self.assertIn("SAMPLE", out)
        self.assertIn("fictional", out.lower())

    def test_search_samples_json_valid(self):
        data = self.run_json(
            ["federal", "search", "--keyword", "x", "--samples", "--json"])
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertEqual(data[0]["source"], "usajobs")

    def test_search_no_key_graceful(self):
        # no key, no --samples: friendly error, no traceback, nonzero exit
        code, out, err = self.run_cli(
            ["federal", "search", "--keyword", "data scientist"])
        self.assertNotEqual(code, 0)
        combined = out + err
        self.assertIn("CANDID_USAJOBS_KEY", combined)
        self.assertNotIn("Traceback", combined)

    def test_search_with_key_mocked(self):
        fake = [{"source": "usajobs", "source_id": "usajobs:1",
                 "title": "Data Scientist", "company": "Dept of X",
                 "location": "Remote", "url": "https://example.com",
                 "description": "Analyze data.", "salary_text": "$100k",
                 "remote": True, "posted_at": ""}]
        with mock.patch("candid.usajobs.search", return_value=fake) as m:
            os.environ["CANDID_USAJOBS_KEY"] = "dummy"
            code, out, err = self.run_cli(
                ["federal", "search", "--keyword", "data scientist",
                 "--limit", "5"])
            self.assertEqual(code, 0, err)
            self.assertIn("Data Scientist", out)
            m.assert_called_once()
            self.assertEqual(m.call_args.kwargs.get("results_per_page"), 5)


class TranslateTest(FederalCliBase):
    def test_translate_prints_band(self):
        code, out, err = self.run_cli(
            ["federal", "translate", "--title", "Software Engineer",
             "--years", "5"])
        self.assertEqual(code, 0, err)
        self.assertIn("GS-", out)
        self.assertIn("12", out)

    def test_translate_json_valid(self):
        data = self.run_json(
            ["federal", "translate", "--title", "Data Scientist",
             "--years", "3", "--salary", "140000", "--json"])
        self.assertIn("grade_low", data)
        self.assertIn("grade_high", data)
        self.assertIn("rationale", data)
        self.assertIn("caveats", data)


class SeriesTest(FederalCliBase):
    def test_series_prints_matches(self):
        code, out, err = self.run_cli(["federal", "series"])
        self.assertEqual(code, 0, err)
        self.assertIn("1550", out)  # python/ML skills -> Computer Science

    def test_series_json_valid(self):
        data = self.run_json(["federal", "series", "--json"])
        self.assertIsInstance(data, list)
        self.assertIn("code", data[0])


class EligibilityTest(FederalCliBase):
    def test_eligibility_all_unknown_becomes_confirm(self):
        code, out, err = self.run_cli(["federal", "eligibility"])
        self.assertEqual(code, 0, err)
        self.assertIn("ACTION", out)

    def test_eligibility_with_facts(self):
        code, out, err = self.run_cli(
            ["federal", "eligibility", "--citizenship", "us_citizen",
             "--veteran", "no", "--federal-employee"])
        self.assertEqual(code, 0, err)
        self.assertIn("US citizenship", out)
        self.assertIn("Veterans' preference", out)

    def test_eligibility_bad_flag_rejected(self):
        code, out, err = self.run_cli(
            ["federal", "eligibility", "--veteran", "maybe"])
        self.assertNotEqual(code, 0)


class PayTest(FederalCliBase):
    def test_pay_prints_amount(self):
        code, out, err = self.run_cli(
            ["federal", "pay", "--grade", "13", "--step", "5"])
        self.assertEqual(code, 0, err)
        self.assertIn("GS-13", out)
        self.assertIn("$", out)

    def test_pay_with_locality(self):
        code, out, err = self.run_cli(
            ["federal", "pay", "--grade", "12",
             "--locality", "New York-Newark, NY-NJ-CT-PA"])
        self.assertEqual(code, 0, err)
        self.assertIn("New York", out)

    def test_pay_json_valid(self):
        data = self.run_json(["federal", "pay", "--grade", "13", "--json"])
        self.assertIn("pay", data)
        self.assertIn("band", data)
        self.assertIn("annual", data["pay"])

    def test_pay_bad_grade_friendly(self):
        code, out, err = self.run_cli(["federal", "pay", "--grade", "99"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out + err)


class ResumeNotesTest(FederalCliBase):
    def test_resume_notes_prints(self):
        code, out, err = self.run_cli(["federal", "resume-notes"])
        self.assertEqual(code, 0, err)
        self.assertIn("citizenship", out.lower())

    def test_resume_notes_json_valid(self):
        data = self.run_json(["federal", "resume-notes", "--json"])
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)


class ScoreTest(FederalCliBase):
    def _write(self, name, content):
        p = self.tmp / name
        p.write_text(content)
        return str(p)

    def test_score_plain_text(self):
        f = self._write("jd.txt", PLAIN_JD)
        code, out, err = self.run_cli(["federal", "score", "--file", f])
        self.assertEqual(code, 0, err)
        self.assertIn("Federal fit", out)

    def test_score_parsed_dict_json(self):
        payload = {"title": "IT Specialist", "grade_range": "GS-13",
                   "qualification_summary": PLAIN_JD,
                   "who_may_apply": "Open to the public"}
        f = self._write("ann.json", json.dumps(payload))
        data = self.run_json(["federal", "score", "--file", f, "--json"])
        self.assertIn("score", data)
        self.assertIn("verdict", data)

    def test_score_raw_usajobs_item(self):
        data = self.run_json(
            ["federal", "score", "--file", str(SAMPLE_ANNOUNCE), "--json"])
        self.assertIn("score", data)

    def test_score_missing_file_friendly(self):
        code, out, err = self.run_cli(
            ["federal", "score", "--file", str(self.tmp / "nope.json")])
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out + err)


class AnnounceTest(FederalCliBase):
    def test_announce_parses_sample(self):
        code, out, err = self.run_cli(
            ["federal", "announce", "--file", str(SAMPLE_ANNOUNCE)])
        self.assertEqual(code, 0, err)
        self.assertIn("IT Specialist", out)
        self.assertIn("Secret", out)

    def test_announce_json_valid(self):
        data = self.run_json(
            ["federal", "announce", "--file", str(SAMPLE_ANNOUNCE), "--json"])
        self.assertIn("title", data)
        self.assertIn("agency", data)

    def test_announce_rejects_plain_text(self):
        f = self.tmp / "plain.txt"
        f.write_text(PLAIN_JD)
        code, out, err = self.run_cli(
            ["federal", "announce", "--file", str(f)])
        self.assertNotEqual(code, 0)


class CurateAdapterTest(FederalCliBase):
    def test_usajobs_registered(self):
        from candid import jobs as J
        self.assertIn("usajobs", J.ADAPTERS)

    def test_curate_usajobs_no_key_never_crashes(self):
        from candid import jobs as J
        res = J.curate(PROFILE, role="data scientist",
                       sources=["usajobs"], limit=5)
        self.assertEqual(res["added"], [])
        self.assertTrue(any("CANDID_USAJOBS_KEY" in e or "API key" in e
                            for e in res["errors"]),
                        f"expected friendly key error, got: {res['errors']}")

    def test_curate_usajobs_keyed_mocked(self):
        from candid import jobs as J
        fake = [{"source": "usajobs", "source_id": "usajobs:mock-1",
                 "title": "Data Scientist", "company": "Dept of X",
                 "location": "Remote", "url": "https://example.com",
                 "description": "Python, machine learning, SQL, statistics.",
                 "salary_text": "", "remote": True, "posted_at": ""}]
        with mock.patch("candid.usajobs.search", return_value=fake):
            os.environ["CANDID_USAJOBS_KEY"] = "dummy"
            res = J.curate(PROFILE, role="data scientist",
                           sources=["usajobs"], limit=5)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["fetched"], 1)
        self.assertEqual(res["candidates"], 1)


if __name__ == "__main__":
    unittest.main()
