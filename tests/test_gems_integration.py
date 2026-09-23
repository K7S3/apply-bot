"""Integration tests for the hidden-gem detector wiring (batch 23, worker C).

Covers the additive jobs.py changes (exclude_megacorps threading through
filter_jobs/curate/refresh, gem payload stashed via _stash_job_meta), the
dashboard top_gems() data function + /api/gems route + HTML panel, and
graceful behavior when candid.gems is absent.

A fake gems module is injected via patch.object on jobs._gems_module so the
wiring is tested deterministically without coupling to candid/gems.py's
internals. A small RealGemsContractTest at the end checks the real module
honors the agreed contract shape.

Network adapters are mocked; no real HTTP is made in these tests.
Run: python -m unittest tests.test_gems_integration -v
"""
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _FakeGems:
    """Deterministic stand-in for candid.gems (contract-compatible)."""
    MEGA = {"megacorp inc"}

    @staticmethod
    def is_megacorp(company, jobs, top_n=10):
        return (company or "").strip().lower() in _FakeGems.MEGA

    @staticmethod
    def gem_score(job, profile=None, all_jobs=None):
        return {"gem_score": 75.0, "fit_score": 80.0, "signals": {},
                "reasons": ["test reason"], "sleeper": False,
                "megacorp": _FakeGems.is_megacorp(job.get("company", ""), [])}

    @staticmethod
    def top_gems(jobs, profile=None, limit=15, exclude_megacorps=False,
                 min_fit=0.0):
        return []


def _patch_gems(fake):
    """Patch the lazy gems lookup in candid.jobs to return ``fake``."""
    from candid import jobs as J
    return patch.object(J, "_gems_module", return_value=fake)


FAKE_JOBS = [
    {"source": "fake", "source_id": "fake:1", "title": "Data Scientist",
     "company": "Acme Corp", "location": "New York, NY", "remote": False,
     "url": "https://example.com/1", "posted_at": "2026-09-21",
     "description": "Python machine learning data science. SQL required.",
     "salary_text": "$150k-$180k"},
    {"source": "fake", "source_id": "fake:2", "title": "Senior Data Scientist",
     "company": "MegaCorp Inc", "location": "New York, NY", "remote": False,
     "url": "https://example.com/2", "posted_at": "2026-09-21",
     "description": "Python machine learning data science at scale.",
     "salary_text": "$200k-$240k"},
    {"source": "fake", "source_id": "fake:3", "title": "Data Scientist",
     "company": "Tiny Labs", "location": "New York, NY", "remote": False,
     "url": "https://example.com/3", "posted_at": "2026-09-21",
     "description": "Python data analysis and statistics.",
     "salary_text": ""},
]

PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql", "statistics"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": [{"company": "Meridian Financial",
                           "title": "Senior Data Scientist"}]}


class ExcludeMegacorpsFilterTest(unittest.TestCase):
    def test_default_keeps_megacorps(self):
        from candid import jobs as J
        with _patch_gems(_FakeGems()):
            out = J.filter_jobs(FAKE_JOBS, "data scientist", "New York")
        companies = [j["company"] for j in out]
        self.assertIn("MegaCorp Inc", companies)

    def test_exclude_drops_megacorps(self):
        from candid import jobs as J
        with _patch_gems(_FakeGems()):
            out = J.filter_jobs(FAKE_JOBS, "data scientist", "New York",
                                exclude_megacorps=True)
        companies = [j["company"] for j in out]
        self.assertNotIn("MegaCorp Inc", companies)
        self.assertIn("Acme Corp", companies)
        self.assertIn("Tiny Labs", companies)

    def test_exclude_without_gems_module_is_noop(self):
        from candid import jobs as J
        with _patch_gems(None):
            out = J.filter_jobs(FAKE_JOBS, "data scientist", "New York",
                                exclude_megacorps=True)
        self.assertEqual({j["company"] for j in out},
                         {"Acme Corp", "MegaCorp Inc", "Tiny Labs"})

    def test_exclude_empty_batch(self):
        from candid import jobs as J
        with _patch_gems(_FakeGems()):
            self.assertEqual(J.filter_jobs([], "data scientist", "",
                                           exclude_megacorps=True), [])

    def test_exclude_flag_positional_backward_compat(self):
        # old positional call style still works — new arg is keyword-only
        # in practice (appended last), and the default preserves behavior
        from candid import jobs as J
        with _patch_gems(_FakeGems()):
            out = J.filter_jobs(FAKE_JOBS, "data scientist", "New York",
                                False, None, 25)
        self.assertEqual(len(out), 3)


class _TempData(unittest.TestCase):
    """Isolate DATA_DIR + tracker per test (same pattern as test_jobs.py)."""
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

    def _adapters(self, payload=FAKE_JOBS):
        from candid import jobs as J
        def _f():
            return payload
        return patch.dict(J.ADAPTERS, {"fake": _f}, clear=True)


class CurateGemsTest(_TempData):
    def test_curate_stashes_gem_meta(self):
        from candid import jobs as J
        with self._adapters(), _patch_gems(_FakeGems()):
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"])
        self.assertEqual(len(res["added"]), 3)
        for job in res["added"]:
            meta = J.get_job_meta(job["app_id"])
            self.assertIn("gem", meta)
            self.assertEqual(meta["gem"]["gem_score"], 75.0)
            self.assertEqual(meta["gem"]["reasons"], ["test reason"])
            # existing meta keys still stashed alongside
            self.assertEqual(meta["source"], "fake")
            self.assertIn("match_score", meta)

    def test_curate_no_gem_key_when_gems_absent(self):
        from candid import jobs as J
        with self._adapters(), _patch_gems(None):
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"])
        self.assertEqual(len(res["added"]), 3)
        meta = J.get_job_meta(res["added"][0]["app_id"])
        self.assertNotIn("gem", meta)
        self.assertEqual(meta["source"], "fake")

    def test_curate_exclude_megacorps(self):
        from candid import jobs as J
        with self._adapters(), _patch_gems(_FakeGems()):
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"], exclude_megacorps=True)
        companies = [j["company"] for j in res["added"]]
        self.assertNotIn("MegaCorp Inc", companies)
        self.assertEqual(len(res["added"]), 2)

    def test_curate_default_includes_megacorps(self):
        from candid import jobs as J
        with self._adapters(), _patch_gems(_FakeGems()):
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"])
        self.assertIn("MegaCorp Inc", [j["company"] for j in res["added"]])

    def test_refresh_threads_exclude_megacorps(self):
        from candid import jobs as J
        with self._adapters(), _patch_gems(_FakeGems()):
            res = J.refresh(PROFILE, "data scientist", "New York",
                            sources=["fake"], exclude_megacorps=True)
        self.assertNotIn("MegaCorp Inc", [j["company"] for j in res["added"]])
        self.assertEqual(len(res["added"]), 2)

    def test_backward_compat_defaults(self):
        from candid import jobs as J
        for fn in (J.filter_jobs, J.curate, J.refresh):
            param = inspect.signature(fn).parameters["exclude_megacorps"]
            self.assertFalse(param.default,
                             f"{fn.__name__} default must stay False")

    def test_stash_job_meta_without_gem_unchanged(self):
        from candid import jobs as J
        J._stash_job_meta(7, {"source": "x", "source_url": "u",
                              "match_score": 55, "jd_text": "text"})
        self.assertEqual(J.get_job_meta(7),
                         {"source": "x", "source_url": "u",
                          "match_score": 55, "jd_text": "text"})


class DashboardGemsTest(_TempData):
    def _stash(self, app_id, gem_score, reasons, sleeper=False,
               fit_score=80.0):
        from candid import jobs as J
        J._stash_job_meta(app_id, {
            "source": "fake", "source_url": f"https://example.com/{app_id}",
            "match_score": 70, "jd_text": "jd",
            "gem": {"gem_score": gem_score, "fit_score": fit_score,
                    "signals": {}, "reasons": reasons, "sleeper": sleeper,
                    "megacorp": False}})

    def _add_saved(self, company, role):
        from candid import tracker as T
        return T.add(company, role)["id"]

    def test_top_gems_empty_without_state(self):
        from candid import dashboard as D
        self.assertEqual(D.top_gems(), [])

    def test_top_gems_sorted_limited_to_five(self):
        from candid import dashboard as D
        ids = [self._add_saved(f"Co{i}", "Data Scientist") for i in range(6)]
        scores = [61, 95, 70, 88, 66, 74]
        for app_id, s in zip(ids, scores):
            self._stash(app_id, s, [f"reason {s}"])
        gems = D.top_gems()
        self.assertEqual(len(gems), 5)
        self.assertEqual([g["gem_score"] for g in gems],
                         [95, 88, 74, 70, 66])
        self.assertEqual(gems[0]["reason"], "reason 95")
        self.assertEqual(gems[0]["company"], "Co1")

    def test_top_gems_limit_param(self):
        from candid import dashboard as D
        ids = [self._add_saved(f"Co{i}", "Data Scientist") for i in range(4)]
        for app_id in ids:
            self._stash(app_id, 70.0, ["r"])
        self.assertEqual(len(D.top_gems(limit=2)), 2)

    def test_top_gems_skips_apps_without_gem(self):
        from candid import dashboard as D
        from candid import jobs as J
        plain = self._add_saved("Plain Co", "Data Scientist")
        J._stash_job_meta(plain, {"source": "fake", "match_score": 70})
        gem_id = self._add_saved("Gem Co", "Data Scientist")
        self._stash(gem_id, 80.0, ["shiny"])
        gems = D.top_gems()
        self.assertEqual([g["company"] for g in gems], ["Gem Co"])

    def test_top_gems_surfaces_sleeper_and_url(self):
        from candid import dashboard as D
        app_id = self._add_saved("Sleeper Co", "Data Scientist")
        self._stash(app_id, 82.0, ["old but gold"], sleeper=True)
        (gem,) = D.top_gems()
        self.assertTrue(gem["sleeper"])
        self.assertEqual(gem["url"], f"https://example.com/{app_id}")
        self.assertEqual(gem["fit_score"], 80.0)

    def test_api_gems_route_registered(self):
        from candid import dashboard as D
        src = inspect.getsource(D)
        self.assertIn('"/api/gems"', src)

    def test_html_panel_wired(self):
        html = (ROOT / "candid" / "data" / "dashboard.html").read_text()
        self.assertIn('id="sec-gems"', html)
        self.assertIn('id="gemsCards"', html)
        self.assertIn("loadGems()", html)
        self.assertIn("/api/gems", html)


class GemsAbsentResilienceTest(_TempData):
    """Everything keeps working when candid.gems cannot be imported."""

    def _block_gems_import(self):
        import contextlib

        @contextlib.contextmanager
        def _cm():
            saved = sys.modules.get("candid.gems", None)
            had = "candid.gems" in sys.modules
            sys.modules["candid.gems"] = None  # -> ImportError on import
            try:
                yield
            finally:
                if had:
                    sys.modules["candid.gems"] = saved
                else:
                    sys.modules.pop("candid.gems", None)
        return _cm()

    def test_gems_module_returns_none_when_absent(self):
        from candid import jobs as J
        with self._block_gems_import():
            self.assertIsNone(J._gems_module())

    def test_filter_jobs_noop_when_gems_absent(self):
        from candid import jobs as J
        with self._block_gems_import():
            out = J.filter_jobs(FAKE_JOBS, "data scientist", "New York",
                                exclude_megacorps=True)
        self.assertEqual(len(out), 3)

    def test_curate_no_gem_meta_when_gems_absent(self):
        from candid import jobs as J
        with self._adapters(), self._block_gems_import():
            res = J.curate(PROFILE, "data scientist", "New York",
                           sources=["fake"])
        self.assertEqual(len(res["added"]), 3)
        for job in res["added"]:
            self.assertNotIn("gem", J.get_job_meta(job["app_id"]))


class RealGemsContractTest(unittest.TestCase):
    """The real candid.gems honors the agreed contract (worker A)."""

    def test_gem_score_shape(self):
        from candid import gems as G
        job = dict(FAKE_JOBS[0])
        g = G.gem_score(job, None, [job])
        for key in ("gem_score", "fit_score", "signals", "reasons",
                    "sleeper", "megacorp"):
            self.assertIn(key, g)
        self.assertGreaterEqual(g["gem_score"], 0)
        self.assertLessEqual(g["gem_score"], 100)
        self.assertIsInstance(g["reasons"], list)

    def test_is_megacorp_known_brand(self):
        from candid import gems as G
        self.assertTrue(G.is_megacorp("Google", []))
        self.assertFalse(G.is_megacorp("Tiny Obscure Labs", []))

    def test_top_gems_exclude_megacorps_contract(self):
        from candid import gems as G
        batch = [dict(FAKE_JOBS[0]),
                 dict(FAKE_JOBS[1]) | {"company": "Google"}]
        out = G.top_gems(batch, profile=None, limit=15,
                         exclude_megacorps=True, min_fit=0.0)
        self.assertNotIn("Google", [j["company"] for j in out])


if __name__ == "__main__":
    unittest.main()
