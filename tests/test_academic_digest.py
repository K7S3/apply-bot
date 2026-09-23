"""Tests for batch-19 worker 5: NRSA stipends + academic digest.

Run: CANDID_DATA_DIR=/tmp/candid-test-academic-digest python -m pytest tests/test_academic_digest.py -q
(also honored when set in-process below; must be set before candid is imported).

Zero network: all sibling modules are exercised locally; the fellowships
sibling module is faked via sys.modules injection (it may not exist yet).
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CANDID_DATA_DIR",
                      tempfile.mkdtemp(prefix="candid-test-academic-digest-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import salary as S  # noqa: E402
from candid import academic_digest as AD  # noqa: E402

DATA_DIR = C.DATA_DIR
PACKAGE_DATA = ROOT / "candid" / "data" / "nrsa_stipends.json"

EXPECTED_ANNUAL = {
    "0": 63480, "1": 63900, "2": 64380, "3": 66948,
    "4": 69180, "5": 71748, "6": 74424, "7+": 77076,
}
EXPECTED_MONTHLY = {
    "0": 5290, "1": 5325, "2": 5365, "3": 5579,
    "4": 5765, "5": 5979, "6": 6202, "7+": 6423,
}


def _clean_data_dir():
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def blocked_import(name):
    """Make importlib.import_module(name) raise ImportError for the block.

    Works even if the module file exists or was already imported: stashes
    sys.modules[name] (set to None, which halts the import) and the parent
    package attribute, then restores both.
    """
    saved_mod = sys.modules.get(name)
    parent_name, _, child = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    had_attr = bool(parent) and hasattr(parent, child)
    saved_attr = getattr(parent, child, None) if had_attr else None
    sys.modules[name] = None
    if had_attr:
        delattr(parent, child)
    try:
        yield
    finally:
        if saved_mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved_mod
        if parent is not None:
            if had_attr:
                setattr(parent, child, saved_attr)
            elif hasattr(parent, child):
                delattr(parent, child)


@contextlib.contextmanager
def fake_fellowships(items):
    """Inject a fake candid.fellowships module exposing upcoming_deadlines()."""
    name = "candid.fellowships"
    saved_mod = sys.modules.get(name)
    parent = sys.modules.get("candid")
    had_attr = hasattr(parent, "fellowships")
    saved_attr = getattr(parent, "fellowships", None)
    fake = types.ModuleType(name)
    fake.upcoming_deadlines = lambda: items  # noqa: E731
    sys.modules[name] = fake
    setattr(parent, "fellowships", fake)
    try:
        yield fake
    finally:
        if saved_mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved_mod
        if had_attr:
            setattr(parent, "fellowships", saved_attr)
        elif hasattr(parent, "fellowships"):
            delattr(parent, "fellowships")


def _seed_labs_and_jobs():
    """Seed a watchlist entry and one curated job that mentions it."""
    from candid import labs as L
    L.add_lab("Ada Lovelace", "Analytical Engines Lab")
    jobs = [{
        "title": "Postdoctoral Fellow, Computational Mathematics",
        "company": "Analytical Engines Lab",
        "location": "London, UK",
        "url": "https://example.org/jobs/postdoc-1",
        "description": ("The Analytical Engines Lab seeks a postdoc. "
                        "The group builds on Ada Lovelace's notes on the "
                        "Analytical Engine. Start date flexible."),
    }, {
        "title": "Software Engineer",
        "company": "Unrelated Corp",
        "location": "Remote",
        "url": "https://example.org/jobs/se-9",
        "description": "Backend role, no lab affiliation.",
    }]
    (DATA_DIR / "jobs.json").write_text(json.dumps({"jobs": jobs}),
                                        encoding="utf-8")


class NrsaDatasetTest(unittest.TestCase):
    def test_json_is_valid(self):
        data = json.loads(PACKAGE_DATA.read_text(encoding="utf-8"))
        self.assertEqual(data["fiscal_year"], "FY2026")
        self.assertEqual(data["source"], "NIH")
        self.assertEqual(data["notice"], "NOT-OD-26-044")
        self.assertTrue(data["verified"])
        self.assertEqual(len(data["levels"]), 8)

    def test_levels_match_verified_nih_table(self):
        data = json.loads(PACKAGE_DATA.read_text(encoding="utf-8"))
        got_annual = {lv["years"]: lv["annual"] for lv in data["levels"]}
        got_monthly = {lv["years"]: lv["monthly"] for lv in data["levels"]}
        self.assertEqual(got_annual, EXPECTED_ANNUAL)
        self.assertEqual(got_monthly, EXPECTED_MONTHLY)
        for lv in data["levels"]:
            self.assertEqual(lv["monthly"] * 12, lv["annual"])

    def test_lookup_every_level(self):
        for years in range(8):
            res = S.nrsa_lookup(years)
            label = "7+" if years == 7 else str(years)
            self.assertEqual(res["years_label"], label)
            self.assertEqual(res["stipend_annual"], EXPECTED_ANNUAL[label])
            self.assertEqual(res["stipend_monthly"], EXPECTED_MONTHLY[label])
            self.assertEqual(res["fiscal_year"], "FY2026")
            self.assertEqual(res["source"], "NIH")
            self.assertIn("not a market", res["note"].lower().replace("pay rate", "market"))

    def test_lookup_out_of_range_high_maps_to_top_level(self):
        for years in (8, 10, 25):
            res = S.nrsa_lookup(years)
            self.assertEqual(res["years_label"], "7+")
            self.assertEqual(res["stipend_annual"], 77076)

    def test_lookup_negative_raises(self):
        with self.assertRaises(S.SalaryError):
            S.nrsa_lookup(-1)

    def test_lookup_non_integer_raises(self):
        with self.assertRaises(S.SalaryError):
            S.nrsa_lookup("two")

    def test_render_nrsa_marks_scale_not_market(self):
        out = S.render_nrsa(S.nrsa_lookup(2))
        self.assertIn("$64,380", out)
        self.assertIn("NOT-OD-26-044", out)
        self.assertIn("not a market", out)

    def test_render_table_covers_all_levels(self):
        out = S.render_nrsa_table()
        for annual in EXPECTED_ANNUAL.values():
            self.assertIn(f"${annual:,}", out)


class SalaryRegressionTest(unittest.TestCase):
    """The salary.py additions must not break existing behavior."""

    def setUp(self):
        _clean_data_dir()

    def tearDown(self):
        _clean_data_dir()

    def test_add_and_lookup_roundtrip(self):
        S.add_range("Acme", "Data Scientist", 120000, 150000,
                    location="New York", source="manual")
        res = S.lookup(company="Acme", title="Data Scientist")
        self.assertGreaterEqual(res["n"], 1)
        self.assertEqual(res["median"], 135000)

    def test_parse_posted_range_unchanged(self):
        parsed = S.parse_posted_range("Pay range $120k-$150k per year")
        self.assertEqual(parsed["low"], 120000)
        self.assertEqual(parsed["high"], 150000)

    def test_lookup_empty_db(self):
        res = S.lookup(company="Nobody", title="Nothing")
        self.assertEqual(res["n"], 0)
        self.assertIsNone(res["median"])

    def test_import_lca_missing_file_still_raises(self):
        with self.assertRaises(S.SalaryError):
            S.import_lca("/tmp/does-not-exist-lca.csv")


class SalaryCliSurfaceTest(unittest.TestCase):
    def _salary_parser(self):
        p = argparse.ArgumentParser(prog="python -m candid")
        sub = p.add_subparsers(dest="cmd")
        sp = sub.add_parser("salary")
        ss = sp.add_subparsers(dest="what")
        lookup_p = ss.add_parser("lookup")
        lookup_p.add_argument("--company", default="")
        lookup_p.add_argument("--title", default="")
        return p, ss

    def test_add_parsers_extends_lookup(self):
        p, ss = self._salary_parser()
        S.add_parsers(ss)  # must not raise; additive only
        a = p.parse_args(["salary", "lookup", "--postdoc", "--years", "2"])
        self.assertTrue(a.postdoc)
        self.assertEqual(a.years, 2)
        self.assertEqual(a.company, "")

    def test_add_parsers_plain_lookup_still_works(self):
        p, ss = self._salary_parser()
        S.add_parsers(ss)
        a = p.parse_args(["salary", "lookup", "--company", "Acme"])
        self.assertFalse(a.postdoc)
        self.assertIsNone(a.years)

    def test_handle_postdoc_lookup_true(self):
        a = SimpleNamespace(postdoc=True, years=2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handled = S.handle_postdoc_lookup(a)
        self.assertTrue(handled)
        out = buf.getvalue()
        self.assertIn("$64,380", out)
        self.assertIn("not a market", out)

    def test_handle_postdoc_lookup_table_without_years(self):
        a = SimpleNamespace(postdoc=True, years=None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handled = S.handle_postdoc_lookup(a)
        self.assertTrue(handled)
        self.assertIn("77,076", buf.getvalue())

    def test_handle_postdoc_lookup_false_when_flag_absent(self):
        a = SimpleNamespace(postdoc=False, years=None, company="Acme")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handled = S.handle_postdoc_lookup(a)
        self.assertFalse(handled)
        self.assertEqual(buf.getvalue(), "")


class AcademicDigestTest(unittest.TestCase):
    def setUp(self):
        _clean_data_dir()

    def tearDown(self):
        _clean_data_dir()

    def test_all_sources_present(self):
        items = [
            {"name": "Hertz Fellowship", "deadline": "2026-10-23",
             "url": "https://example.org/hertz"},
            {"name": "NSF GRFP", "deadline": "2026-10-19",
             "url": "https://example.org/grfp"},
        ]
        with fake_fellowships(items):
            _seed_labs_and_jobs()
            d = AD.build_digest(now=date(2026, 9, 22))
        self.assertEqual(d["as_of"], "2026-09-22")
        secs = d["sections"]
        self.assertEqual(set(secs), {"fellowships", "labs", "milestones"})

        f = secs["fellowships"]
        self.assertEqual(f["status"], "ok")
        self.assertEqual([i["name"] for i in f["items"]],
                         ["NSF GRFP", "Hertz Fellowship"])  # sorted by deadline

        labs_sec = secs["labs"]
        self.assertEqual(labs_sec["status"], "ok")
        self.assertTrue(labs_sec["items"])
        self.assertTrue(any(h["lab"] == "Ada Lovelace"
                            for h in labs_sec["items"]))

        ms = secs["milestones"]
        self.assertEqual(ms["status"], "ok")
        self.assertIn("September", ms["items"][0]["headline"])

    def test_fellowships_missing_degrades(self):
        with blocked_import("candid.fellowships"):
            d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["fellowships"]
        self.assertEqual(sec["status"], "unavailable")
        self.assertEqual(sec["items"], [])
        self.assertIn("not configured", sec["note"])
        # other sections still fine
        self.assertEqual(d["sections"]["milestones"]["status"], "ok")

    def test_labs_missing_degrades(self):
        with blocked_import("candid.labs"):
            d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["labs"]
        self.assertEqual(sec["status"], "unavailable")
        self.assertIn("not configured", sec["note"])
        self.assertEqual(d["sections"]["milestones"]["status"], "ok")

    def test_calendar_missing_degrades(self):
        with blocked_import("candid.academic_calendar"):
            d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["milestones"]
        self.assertEqual(sec["status"], "unavailable")
        self.assertIn("not configured", sec["note"])

    def test_all_sources_missing_still_builds(self):
        with blocked_import("candid.fellowships"), \
             blocked_import("candid.labs"), \
             blocked_import("candid.academic_calendar"):
            d = AD.build_digest(now=date(2026, 9, 22))
        for sec in d["sections"].values():
            self.assertEqual(sec["status"], "unavailable")
        text = AD.render_digest(d)
        self.assertIn("not configured", text)

    def test_labs_present_but_no_data(self):
        # real labs module, empty watchlist and no jobs.json
        d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["labs"]
        self.assertEqual(sec["status"], "ok")
        self.assertEqual(sec["items"], [])
        self.assertIn("no data", sec["note"].lower())

    def test_labs_watchlist_but_no_hits(self):
        from candid import labs as L
        L.add_lab("Nobody Matches This Name XYZ")
        (DATA_DIR / "jobs.json").write_text(
            json.dumps({"jobs": [{"title": "Barista", "company": "Cafe",
                                  "description": "coffee"}]}), encoding="utf-8")
        d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["labs"]
        self.assertEqual(sec["items"], [])
        self.assertIn("no watchlist hits", sec["note"])

    def test_real_fellowships_module_shape(self):
        # The sibling's real module: items are {fellowship: {...}, deadline,
        # days_until, approx, rolling}. The digest must unwrap the nested
        # record, never str() it into the name.
        d = AD.build_digest(now=date(2026, 9, 22))
        sec = d["sections"]["fellowships"]
        self.assertEqual(sec["status"], "ok")
        self.assertTrue(sec["items"])
        for it in sec["items"]:
            self.assertNotIn("{", it["name"])
            self.assertIsInstance(it["deadline"], str)
        text = AD.render_digest(d)
        self.assertIn("Miller Institute Postdoctoral Fellowship", text)
        self.assertNotIn("deadline_months", text)

    def test_real_fellowships_json_serializable(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            AD.cmd_academic_digest(SimpleNamespace(json=True))
        parsed = json.loads(buf.getvalue())  # must not raise
        self.assertIn("sections", parsed)
        self.assertIn("fellowships", parsed["sections"])

    def test_render_markdown_structure(self):
        items = [{"name": "Hertz Fellowship", "deadline": "2026-10-23"}]
        with fake_fellowships(items):
            _seed_labs_and_jobs()
            d = AD.build_digest(now=date(2026, 9, 22))
        text = AD.render_digest(d)
        self.assertIn("# Academic digest - September 22, 2026", text)
        self.assertIn("## 1. Upcoming fellowship deadlines", text)
        self.assertIn("## 2. Watched-lab hits in latest curated jobs", text)
        self.assertIn("## 3. This month's hiring-season milestones (September)", text)
        self.assertIn("Hertz Fellowship", text)
        self.assertIn("Ada Lovelace", text)
        self.assertIn("_Generated", text)

    def test_add_parsers_wires_command(self):
        p = argparse.ArgumentParser(prog="python -m candid")
        sub = p.add_subparsers(dest="cmd")
        AD.add_parsers(sub)  # must not raise
        a = p.parse_args(["academic-digest"])
        self.assertTrue(callable(a.func))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            a.func(SimpleNamespace(json=False))
        self.assertIn("# Academic digest", buf.getvalue())

    def test_cmd_json_output(self):
        with fake_fellowships([]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                AD.cmd_academic_digest(SimpleNamespace(json=True))
        parsed = json.loads(buf.getvalue())
        self.assertIn("sections", parsed)


if __name__ == "__main__":
    unittest.main()
