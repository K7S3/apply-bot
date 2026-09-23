"""Tests for candid.startup_signals and candid.startup_rank (candid batch 21).

Signals math runs on a synthetic jobs.json + tracker.json pair inside a
tmp DATA_DIR (same isolation pattern as tests/test_jobs.py). Rank tests use
the pure rank_startups() function with injected inputs, plus a few
registry round-trips through startup_lists.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def _tracker_rec(app_id, company, role, days_ago_n, status="saved"):
    return {
        "id": app_id, "company": company, "role": role, "jd_link": "",
        "status": status, "notes": "", "date_added": _days_ago(days_ago_n),
        "date_updated": _days_ago(days_ago_n), "prep_pack": "",
    }


# Acme AI: 4 recent + 1 prior -> growing, 4.0/30d
# Beta Corp: 1 recent + 2 prior -> shrinking, 1.0/30d
# Gamma LLC: 2 recent + 2 prior (same title) -> flat, 2.0/30d
# Delta Inc: 1 posting only -> below default min_postings=2
_FIXTURE_APPS = [
    _tracker_rec(1, "Acme AI", "ML Engineer", 5),
    _tracker_rec(2, "Acme AI", "ML Engineer", 10),
    _tracker_rec(3, "Acme AI", "Data Scientist", 15),
    _tracker_rec(4, "Acme AI", "Backend Engineer", 20),
    _tracker_rec(5, "Acme AI", "ML Engineer", 40),
    _tracker_rec(6, "Beta Corp", "ML Engineer", 10),
    _tracker_rec(7, "Beta Corp", "ML Engineer", 35),
    _tracker_rec(8, "Beta Corp", "Data Scientist", 50),
    _tracker_rec(9, "Gamma LLC", "ML Engineer", 10),
    _tracker_rec(10, "Gamma LLC", "ML Engineer", 20),
    _tracker_rec(11, "Gamma LLC", "ML Engineer", 35),
    _tracker_rec(12, "Gamma LLC", "ML Engineer", 45),
    _tracker_rec(13, "Delta Inc", "ML Engineer", 3),
    # curated nowhere: must never appear in signals
    _tracker_rec(14, "Epsilon Co", "ML Engineer", 2),
]

_FIXTURE_SEEN = {
    "fake:1": 1, "fake:2": 2, "fake:3": 3, "fake:4": 4, "fake:5": 5,
    "fake:6": 6, "fake:7": 7, "fake:8": 8,
    "fake:9": 9, "fake:10": 10, "fake:11": 11, "fake:12": 12,
    "fake:13": 13,
    # id 14 (Epsilon Co) deliberately absent
}


class _TmpData(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_tracker = C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"
        _write_json(C.TRACKER_PATH, _FIXTURE_APPS)
        _write_json(C.DATA_DIR / "jobs.json",
                    {"last_run": _days_ago(0), "seen": dict(_FIXTURE_SEEN)})

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        self.td.cleanup()

    def _by_company(self, rows):
        return {r["company"]: r for r in rows}


# ---------------------------------------------------------------------------
# startup_signals
# ---------------------------------------------------------------------------

class SignalsMathTest(_TmpData):
    def test_velocity_and_trend(self):
        from candid import startup_signals as SIG
        by = self._by_company(SIG.compute_signals())
        self.assertEqual(by["Acme AI"]["postings_per_30d"], 4.0)
        self.assertEqual(by["Acme AI"]["trend"], "growing")
        self.assertEqual(by["Beta Corp"]["postings_per_30d"], 1.0)
        self.assertEqual(by["Beta Corp"]["trend"], "shrinking")
        self.assertEqual(by["Gamma LLC"]["postings_per_30d"], 2.0)
        self.assertEqual(by["Gamma LLC"]["trend"], "flat")

    def test_new_vs_repeat(self):
        from candid import startup_signals as SIG
        by = self._by_company(SIG.compute_signals())
        acme = by["Acme AI"]
        self.assertEqual(acme["postings_total"], 5)
        self.assertEqual(acme["new"], 3)      # ml engineer, data scientist, backend
        self.assertEqual(acme["repeat"], 2)
        self.assertAlmostEqual(acme["new_vs_repeat_ratio"], 1.5)
        gamma = by["Gamma LLC"]
        self.assertEqual((gamma["new"], gamma["repeat"]), (1, 3))
        self.assertAlmostEqual(gamma["new_vs_repeat_ratio"], 0.33, places=2)

    def test_sort_order_and_min_postings(self):
        from candid import startup_signals as SIG
        rows = SIG.compute_signals()
        self.assertEqual([r["company"] for r in rows],
                         ["Acme AI", "Gamma LLC", "Beta Corp"])
        # Delta Inc (1 posting) filtered by default min_postings=2
        by = self._by_company(rows)
        self.assertNotIn("Delta Inc", by)
        rows1 = SIG.compute_signals(min_postings=1)
        self.assertIn("Delta Inc", self._by_company(rows1))
        # tracker entries that were never curated are excluded
        for rows_ in (rows, rows1):
            self.assertNotIn("Epsilon Co", self._by_company(rows_))

    def test_min_postings_rejected(self):
        from candid import startup_signals as SIG
        with self.assertRaises(SIG.StartupSignalError):
            SIG.compute_signals(min_postings=0)

    def test_signals_by_company(self):
        from candid import startup_signals as SIG
        d = SIG.signals_by_company()
        self.assertIn("acme ai", d)
        self.assertEqual(d["acme ai"]["trend"], "growing")

    def test_render_signals(self):
        from candid import startup_signals as SIG
        text = SIG.render_signals(SIG.compute_signals())
        self.assertIn("Acme AI", text)
        self.assertIn("growing", text)
        self.assertNotIn("\u2014", text)  # no em dashes in user-facing strings

    def test_render_signals_empty(self):
        from candid import startup_signals as SIG
        text = SIG.render_signals([])
        self.assertIn("No hiring signals yet", text)


class SignalsEmptyInputTest(unittest.TestCase):
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

    def test_missing_jobs_json(self):
        from candid import startup_signals as SIG
        self.assertEqual(SIG.compute_signals(), [])

    def test_empty_jobs_json(self):
        from candid import startup_signals as SIG
        _write_json(Path(self.td.name) / "jobs.json", {})
        self.assertEqual(SIG.compute_signals(), [])
        _write_json(Path(self.td.name) / "jobs.json", {"seen": {}})
        self.assertEqual(SIG.compute_signals(), [])

    def test_malformed_jobs_json(self):
        from candid import startup_signals as SIG
        (Path(self.td.name) / "jobs.json").write_text("not json{{{",
                                                      encoding="utf-8")
        self.assertEqual(SIG.compute_signals(), [])

    def test_seen_pointing_at_missing_tracker_entry(self):
        from candid import startup_signals as SIG
        _write_json(Path(self.td.name) / "tracker.json", [])
        _write_json(Path(self.td.name) / "jobs.json",
                    {"seen": {"fake:1": 999}})
        self.assertEqual(SIG.compute_signals(), [])


# ---------------------------------------------------------------------------
# startup_rank
# ---------------------------------------------------------------------------

def _reg_startups():
    return [
        {"name": "Acme AI", "stage": "seed",
         "notes": "ml infrastructure platform for llm serving"},
        {"name": "Beta Corp", "stage": "series-b",
         "notes": "ml ops tooling for data teams"},
        {"name": "Gamma LLC", "stage": "series-a",
         "notes": "ml ranking models for advertising"},
    ]


def _sig_dict():
    from candid import startup_signals as SIG
    base = {
        "company": "", "postings_total": 0, "postings_per_30d": 0.0,
        "trend": "flat", "trend_detail": "", "new": 0, "repeat": 0,
        "new_vs_repeat_ratio": None, "recent_titles": [],
    }
    def mk(company, per30, trend):
        return {**base, "company": company, "postings_per_30d": per30,
                "trend": trend}
    return {
        "acme ai": mk("Acme AI", 4.0, "growing"),
        "gamma llc": mk("Gamma LLC", 2.0, "flat"),
        # Beta Corp: no curated data -> neutral signal factor
    }


class RankOrderingTest(unittest.TestCase):
    ROLE = "ML Engineer"  # "engineer" is a stopword; match keyword is "ml"

    def test_score_is_product_of_three_factors(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=["seed"],
                                signals=_sig_dict())
        by = {r["name"]: r for r in rows}
        acme = by["Acme AI"]
        # fit 1.0 (ml) x 1.25 (seed preferred) x 1.2*(1+4/10) (growing)
        self.assertAlmostEqual(acme["score"], 1.0 * 1.25 * 1.68, places=3)
        self.assertEqual(acme["stage_factor"], 1.25)
        self.assertAlmostEqual(acme["signal_factor"], 1.68, places=3)
        gamma = by["Gamma LLC"]
        # fit 1.0 x 0.75 (series-a not preferred) x 1.0*(1+2/10) (flat)
        self.assertAlmostEqual(gamma["score"], 1.0 * 0.75 * 1.2, places=3)
        beta = by["Beta Corp"]
        # fit 1.0 x 0.75 x 1.0 (no signal data -> neutral)
        self.assertAlmostEqual(beta["score"], 0.75, places=3)
        self.assertEqual(beta["trend"], "no data")

    def test_ordering_prefers_preferred_stage_and_signal(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=["seed"],
                                signals=_sig_dict())
        self.assertEqual([r["name"] for r in rows],
                         ["Acme AI", "Gamma LLC", "Beta Corp"])

    def test_no_prefs_means_all_stages_equal(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=[],
                                signals=_sig_dict())
        self.assertTrue(all(r["stage_factor"] == 1.0 for r in rows))
        # order then comes from fit x signal alone
        self.assertEqual([r["name"] for r in rows],
                         ["Acme AI", "Gamma LLC", "Beta Corp"])

    def test_shrinking_signal_penalizes(self):
        from candid import startup_rank as SR
        sigs = _sig_dict()
        sigs["beta corp"] = {**sigs["acme ai"], "company": "Beta Corp",
                             "postings_per_30d": 3.0, "trend": "shrinking"}
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=[],
                                signals=sigs)
        by = {r["name"]: r for r in rows}
        # 1.0 x 1.0 x 0.75*(1+3/10) = 0.975 < gamma's 1.2
        self.assertAlmostEqual(by["Beta Corp"]["signal_factor"], 0.975,
                               places=3)
        self.assertLess(by["Beta Corp"]["score"], by["Gamma LLC"]["score"])

    def test_why_is_single_line(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=["seed"],
                                signals=_sig_dict())
        for r in rows:
            self.assertIn("why", r)
            self.assertTrue(r["why"].strip())
            self.assertNotIn("\n", r["why"])
            self.assertNotIn("\u2014", r["why"])  # no em dashes

    def test_matched_terms(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=[], signals={})
        self.assertEqual(rows[0]["matched_terms"], ["ml"])

    def test_blank_role_raises(self):
        from candid import startup_rank as SR
        with self.assertRaises(SR.StartupRankError):
            rank_startups_blank = SR.rank_startups("   ")

    def test_render_rank_empty(self):
        from candid import startup_rank as SR
        text = SR.render_rank([], "ML Engineer")
        self.assertIn("No startup registry found", text)

    def test_render_rank_table(self):
        from candid import startup_rank as SR
        rows = SR.rank_startups(self.ROLE, startups=_reg_startups(),
                                preferred_stages=["seed"],
                                signals=_sig_dict())
        text = SR.render_rank(rows, self.ROLE)
        self.assertIn("1. Acme AI (seed)", text)
        self.assertIn("why:", text)


class RankRegistryTest(unittest.TestCase):
    """Registry-driven tests: prefs flow through set-stages storage."""

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

    def test_missing_registry_returns_empty(self):
        from candid import startup_rank as SR
        self.assertEqual(SR.load_registry(), ([], []))
        self.assertEqual(SR.rank_startups("ML Engineer"), [])

    def test_prefs_from_set_stages_boost_ranking(self):
        from candid import startup_rank as SR
        from candid import startup_lists as L
        for rec in _reg_startups():
            L.add(name=rec["name"], stage=rec["stage"], notes=rec["notes"])
        L.set_preferred_stages(["seed"])
        rows = SR.rank_startups("ML Engineer", signals=_sig_dict())
        self.assertEqual([r["name"] for r in rows],
                         ["Acme AI", "Gamma LLC", "Beta Corp"])
        self.assertEqual(rows[0]["stage_factor"], 1.25)

    def test_malformed_registry_is_defensive(self):
        from candid import startup_rank as SR
        _write_json(Path(self.td.name) / "startups.json", {"nope": True})
        records, prefs = SR.load_registry()
        self.assertEqual((records, prefs), ([], []))
        self.assertEqual(SR.rank_startups("ML Engineer"), [])

    def test_plain_list_registry_shape(self):
        from candid import startup_rank as SR
        _write_json(Path(self.td.name) / "startups.json", _reg_startups())
        records, prefs = SR.load_registry()
        # plain list shape: startups load, no prefs -> all stages equal
        self.assertEqual(len(records), 3)
        self.assertEqual(prefs, [])


class StartupsCLITest(unittest.TestCase):
    """The startups group exposes signals and rank with the right shape."""

    def test_parser_routes(self):
        from candid.__main__ import build_parser, cmd_startups
        a = build_parser().parse_args(
            ["startups", "signals", "--min-postings", "3"])
        self.assertIs(a.func, cmd_startups)
        self.assertEqual(a.what, "signals")
        self.assertEqual(a.min_postings, 3)
        a = build_parser().parse_args(
            ["startups", "rank", "--role", "ML Engineer"])
        self.assertEqual(a.what, "rank")
        self.assertEqual(a.role, "ML Engineer")

    def test_cli_signals_empty_data(self):
        from candid import config as C
        from candid.__main__ import main
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["startups", "signals"])
            self.assertIn("No hiring signals yet", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["startups", "rank", "--role", "ML Engineer"])
            self.assertIn("No startup registry found", buf.getvalue())
        finally:
            C.DATA_DIR = orig_data
            C.TRACKER_PATH = orig_tracker
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
