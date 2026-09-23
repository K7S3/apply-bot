"""Tests for contract-type detection + contract filtering in candid.jobs.

No live network: adapters are mocked. Run:
    python -m pytest tests/test_contract_filter.py -q
"""
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fake_fetch(payload):
    def _f():
        return payload
    return _f


PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql", "deep learning",
                      "pytorch", "statistics"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": [{"company": "Meridian Financial",
                           "title": "Senior Data Scientist"}]}

TYPE_JOBS = [
    {"source": "fake", "source_id": "fake:c1", "title": "Contract Data Scientist",
     "company": "StaffingCo", "location": "New York, NY", "remote": False,
     "url": "https://example.com/c1", "posted_at": "2026-09-20",
     "description": "6-month contract, W2. Python and machine learning, SQL.",
     "salary_text": ""},
    {"source": "fake", "source_id": "fake:c2", "title": "Freelance Data Scientist",
     "company": "GigHub", "location": "New York, NY", "remote": False,
     "url": "https://example.com/c2", "posted_at": "2026-09-20",
     "description": "Freelance gig, project-based work. Python, statistics.",
     "salary_text": ""},
    {"source": "fake", "source_id": "fake:c3", "title": "Senior Data Scientist",
     "company": "BigBank", "location": "New York, NY", "remote": False,
     "url": "https://example.com/c3", "posted_at": "2026-09-20",
     "description": "Full-time permanent role. Python, machine learning, SQL.",
     "salary_text": ""},
    {"source": "fake", "source_id": "fake:c4", "title": "Data Scientist",
     "company": "StartupZ", "location": "New York, NY", "remote": False,
     "url": "https://example.com/c4", "posted_at": "2026-09-20",
     "description": "Python and machine learning for our ML platform. SQL required.",
     "salary_text": ""},
]


class DetectContractTypeTest(unittest.TestCase):
    def setUp(self):
        from candid import jobs as J
        self.J = J

    def _d(self, title, description=""):
        return self.J.detect_contract_type(title, description)

    def test_contract_signals(self):
        cases = [
            ("Data Engineer", "1099 contractor, $95/hr"),
            ("ML Engineer", "C2C candidates only"),
            ("Backend Dev", "corp-to-corp or W2"),
            ("Data Scientist", "contract-to-hire opportunity"),
            ("Analyst", "contract to hire via staffing firm"),
            ("Engineer", "W2 contract, 12 months"),
            ("Data Scientist", "Hiring a contractor for our team"),
            ("Consultant", "contracting role with our client"),
            ("DevOps", "temporary position, 3 months"),
            ("QA Engineer", "temp-to-perm role"),
            ("Data Scientist", "This is a 6 month contract"),
            ("Data Scientist", "contract for 12 months, remote"),
            ("Data Scientist", "6-month contract assignment"),
            ("Data Engineer", "Contract position in NYC"),
            ("Data Scientist", "contract role, full-time hours"),
        ]
        for title, desc in cases:
            with self.subTest(title=title, desc=desc):
                self.assertEqual(self._d(title, desc), "contract", desc)

    def test_title_bare_contract_word(self):
        # bare "contract" in the title is explicit; in descriptions it's noisy
        self.assertEqual(self._d("Contract Data Engineer"), "contract")
        self.assertEqual(self._d("CONTRACT Recruiter", ""), "contract")
        # description-only "contract" without a contract-specific token is unknown
        self.assertEqual(self._d("Data Scientist",
                                 "sign the employment contract on day one"), "unknown")

    def test_smart_contract_not_flagged(self):
        # blockchain roles are not employment-type contracts
        self.assertEqual(self._d("Smart Contract Developer",
                                 "Solidity smart contracts on EVM"), "unknown")
        self.assertEqual(self._d("Senior Smart-Contract Engineer"), "unknown")

    def test_consultant_not_flagged(self):
        # consulting is a common full-time job family
        self.assertEqual(self._d("Solutions Consultant",
                                 "consulting with enterprise clients"), "unknown")
        self.assertEqual(self._d("Management Consultant",
                                 "strategy consulting practice"), "unknown")

    def test_freelance_signals(self):
        cases = [
            ("Freelancer - ML", ""),
            ("Data Scientist", "freelance data work"),
            ("Engineer", "gig work, flexible hours"),
            ("Designer", "project-based engagement"),
        ]
        for title, desc in cases:
            with self.subTest(title=title, desc=desc):
                self.assertEqual(self._d(title, desc), "freelance", desc)

    def test_fte_signals(self):
        self.assertEqual(self._d("Data Scientist", "Full-time role with benefits"), "fte")
        self.assertEqual(self._d("Data Scientist", "FULL-TIME, onsite"), "fte")
        self.assertEqual(self._d("Data Scientist", "permanent position"), "fte")

    def test_precedence_contract_over_fte(self):
        self.assertEqual(self._d("Data Scientist",
                                 "Full-time contract role, W2"), "contract")
        self.assertEqual(self._d("Data Scientist",
                                 "permanent hire, contract-to-hire"), "contract")

    def test_precedence_contract_over_freelance(self):
        self.assertEqual(self._d("Contractor", "freelance gig, 1099"), "contract")

    def test_precedence_freelance_over_fte(self):
        self.assertEqual(self._d("Freelance Data Scientist",
                                 "full-time freelance project"), "freelance")

    def test_permanent_resident_not_fte(self):
        # work authorization, not an engagement signal
        self.assertEqual(self._d("Data Scientist",
                                 "must be a US citizen or permanent resident"), "unknown")

    def test_unknown(self):
        self.assertEqual(self._d("Data Scientist",
                                 "Python, SQL, build dashboards"), "unknown")
        self.assertEqual(self._d("", ""), "unknown")

    def test_pure_function_and_case_insensitive(self):
        a = self._d("DATA SCIENTIST", "c2c ONLY")
        b = self._d("data scientist", "C2C only")
        self.assertEqual(a, b, "contract")
        before = ("Data Scientist", "Python, SQL")
        self._d(*before)
        self.assertEqual(before, ("Data Scientist", "Python, SQL"))


class CurateContractFilterTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_tracker = C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        self.td.cleanup()

    def _adapters(self):
        from candid import jobs as J
        return patch.dict(J.ADAPTERS, {"fake": _fake_fetch(TYPE_JOBS)}, clear=True)

    def _added_ids(self, res):
        return {j["source_id"] for j in res["added"]}

    def test_tags_every_listing(self):
        from candid import jobs as J
        with self._adapters():
            res = J.curate(PROFILE, "data scientist", "New York", sources=["fake"])
        self.assertEqual(res["fetched"], 4)
        self.assertEqual(len(res["added"]), 4)
        got = {j["source_id"]: j["contract_type"] for j in res["added"]}
        self.assertEqual(got, {"fake:c1": "contract", "fake:c2": "freelance",
                              "fake:c3": "fte", "fake:c4": "unknown"})

    def test_contract_type_persisted_in_jobs_json(self):
        from candid import jobs as J
        from candid import config as C
        with self._adapters():
            J.curate(PROFILE, "data scientist", "New York", sources=["fake"])
        state = json.loads((C.DATA_DIR / "jobs.json").read_text(encoding="utf-8"))
        self.assertEqual(state["contract_types"],
                         {"fake:c1": "contract", "fake:c2": "freelance",
                          "fake:c3": "fte", "fake:c4": "unknown"})

    def test_contract_only(self):
        from candid import jobs as J
        with self._adapters():
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"], contract_only=True)
        # unknown counts as neither -> dropped here
        self.assertEqual(self._added_ids(res), {"fake:c1", "fake:c2"})

    def test_exclude_contract(self):
        from candid import jobs as J
        with self._adapters():
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"], exclude_contract=True)
        # unknown counts as neither -> kept here
        self.assertEqual(self._added_ids(res), {"fake:c3", "fake:c4"})

    def test_contradictory_flags_raise(self):
        from candid import jobs as J
        with self._adapters():
            with self.assertRaises(J.JobsError):
                J.curate(PROFILE, "data scientist", "New York", sources=["fake"],
                         contract_only=True, exclude_contract=True)


class ListContractFilterTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_tracker = C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"
        from candid import jobs as J
        from candid import tracker as T
        self.J, self.T = J, T
        seed = [("StaffingCo", "Contract Data Scientist", "contract"),
                ("GigHub", "Freelance Data Scientist", "freelance"),
                ("BigBank", "Senior Data Scientist", "fte"),
                ("StartupZ", "Data Scientist", "unknown")]
        for company, role, ctype in seed:
            rec = T.add(company, role, status="saved", path=C.TRACKER_PATH)
            J._stash_job_meta(rec["id"], {
                "source": "fake", "source_url": f"https://example.com/{rec['id']}",
                "match_score": 80, "jd_text": "Python",
                "contract_type": ctype})

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        self.td.cleanup()

    def test_render_saved_filters(self):
        J = self.J
        self.assertIn("Contract Data Scientist", J.render_saved(contract="contract"))
        self.assertNotIn("Senior Data Scientist", J.render_saved(contract="contract"))
        self.assertIn("Freelance Data Scientist", J.render_saved(contract="freelance"))
        self.assertIn("Senior Data Scientist", J.render_saved(contract="fte"))
        self.assertIn("Data Scientist", J.render_saved(contract="any"))

    def test_render_saved_filter_matches_nothing(self):
        from candid import config as C
        from candid import tracker as T
        # fresh DB holding a single fte job: filtering for contract matches nothing
        td2 = tempfile.TemporaryDirectory()
        C.DATA_DIR = Path(td2.name)
        C.TRACKER_PATH = Path(td2.name) / "tracker.json"
        try:
            rec = T.add("BigBank", "Senior Data Scientist", status="saved",
                        path=C.TRACKER_PATH)
            self.J._stash_job_meta(rec["id"], {"source": "fake", "contract_type": "fte"})
            out = self.J.render_saved(contract="contract")
            self.assertIn("No saved jobs with engagement type 'contract'", out)
        finally:
            td2.cleanup()
            C.DATA_DIR = Path(self.td.name)
            C.TRACKER_PATH = Path(self.td.name) / "tracker.json"

    def test_cli_list_json_filter(self):
        from candid import __main__ as M
        args = SimpleNamespace(what="list", json=True, contract="contract")
        buf = StringIO()
        with redirect_stdout(buf):
            M.cmd_jobs(args)
        rows = json.loads(buf.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "Contract Data Scientist")
        self.assertEqual(rows[0]["contract_type"], "contract")

    def test_cli_list_text_filter(self):
        from candid import __main__ as M
        args = SimpleNamespace(what="list", json=False, contract="fte")
        buf = StringIO()
        with redirect_stdout(buf):
            M.cmd_jobs(args)
        out = buf.getvalue()
        self.assertIn("Senior Data Scientist", out)
        self.assertNotIn("Freelance Data Scientist", out)
        self.assertIn("fte", out)  # Type column shows the tag


class ParserContractFlagTest(unittest.TestCase):
    def test_flags_exist(self):
        from candid import __main__ as M
        p = M.build_parser()
        a = p.parse_args(["jobs", "curate", "--role", "x", "--contract-only"])
        self.assertTrue(a.contract_only)
        self.assertFalse(a.exclude_contract)
        a = p.parse_args(["jobs", "curate", "--role", "x", "--exclude-contract"])
        self.assertTrue(a.exclude_contract)
        a = p.parse_args(["jobs", "list", "--contract", "freelance"])
        self.assertEqual(a.contract, "freelance")
        a = p.parse_args(["jobs", "list"])
        self.assertEqual(a.contract, "any")


if __name__ == "__main__":
    unittest.main()
