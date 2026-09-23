"""Tests for the `candid watch` commands + candid.alerts (alert store,
matching gate, threshold config, run state, digest hook).

Monitor-engine calls are fully mocked: a fake `candid.monitors` module with
worker 1's real API surface (add_company / add_source / remove_company /
list_companies / poll / MonitorError) is injected into sys.modules, and
match scoring is stubbed. No network.

Data paths are redirected into a temp dir by reassigning candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import alerts as AL  # noqa: E402
from candid import config as C  # noqa: E402

PROFILE = {
    "name": "Alex Rivera", "headline": "Senior Data Scientist",
    "location": "New York, NY", "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql", "statistics"],
    "experience": [{"title": "Senior Data Scientist",
                    "company": "Meridian Financial",
                    "dates": "Jan 2022 - Present",
                    "bullets": ["Built churn models with XGBoost."]}],
    "education": [], "years_experience": 4.5, "seniority": "senior",
    "source_files": ["resume.pdf"],
}

# shaped like real worker-1 posting records (id, no jd body)
POSTING_GO = {"id": "greenhouse:acme:1", "company": "Acme",
              "title": "Senior Data Scientist",
              "url": "https://boards.example/acme/1",
              "jd": "Must have: Python, machine learning, SQL, statistics. "
                    "Senior data scientist, New York.",
              "location": "New York", "department": "Data",
              "repost": False}
POSTING_WEAK = {"id": "greenhouse:acme:2", "company": "Acme",
                "title": "Junior Accountant",
                "url": "https://boards.example/acme/2",
                "jd": "Must have: Excel, bookkeeping. Junior accountant.",
                "location": "New York", "department": "Finance",
                "repost": False}
POSTING_REPOST = {"id": "lever:beta:7", "company": "Beta",
                  "title": "ML Engineer",
                  "url": "https://boards.example/beta/7",
                  "jd": "Must have: Python, machine learning. ML engineer.",
                  "location": "New York", "department": "ML",
                  "repost": True}


def _fake_score(profile, jd, title="", company="", location=""):
    """Deterministic stand-in for match.score_match."""
    if "Accountant" in title:
        return {"score": 12.0, "verdict": "NO-GO"}
    if "ML Engineer" in title:
        return {"score": 66.0, "verdict": "CONDITIONAL"}
    return {"score": 85.0, "verdict": "GO"}


def _no_fetch():
    """Patch scoring_text so tests never touch the network."""
    return mock.patch.object(AL, "scoring_text",
                             lambda p: p.get("jd") or p.get("title") or "")


class AlertBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-watch-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)


# ---------------------------------------------------------------------------
# alert store
# ---------------------------------------------------------------------------

class AlertStoreTest(AlertBase):
    def test_load_empty_when_no_file(self):
        self.assertEqual(AL.load_alerts(), [])

    def test_create_and_load(self):
        a = AL.create_alert(POSTING_GO, 85.0, "GO")
        self.assertEqual(a["id"], 1)
        self.assertEqual(a["kind"], "new")
        self.assertFalse(a["read"])
        self.assertIn("New posting", a["message"])
        loaded = AL.load_alerts()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["posting_id"], "greenhouse:acme:1")
        self.assertEqual(loaded[0]["score"], 85.0)

    def test_dedupe_no_two_unread_for_same_posting(self):
        first = AL.create_alert(POSTING_GO, 85.0, "GO")
        second = AL.create_alert(POSTING_GO, 90.0, "GO")
        self.assertIsNotNone(first)
        self.assertIsNone(second)  # deduped
        self.assertEqual(len(AL.load_alerts()), 1)

    def test_dedupe_falls_back_to_url_when_no_id(self):
        p1 = {"company": "Acme", "title": "X", "url": "https://x/1"}
        p2 = {"company": "acme", "title": "Y", "url": "https://x/1"}
        AL.create_alert(p1, 80.0, "GO")
        self.assertIsNone(AL.create_alert(p2, 80.0, "GO"))

    def test_new_alert_allowed_after_old_one_read(self):
        AL.create_alert(POSTING_GO, 85.0, "GO")
        AL.mark_read(1)
        again = AL.create_alert(POSTING_GO, 88.0, "GO")
        self.assertIsNotNone(again)
        self.assertEqual(again["id"], 2)

    def test_mark_read(self):
        AL.create_alert(POSTING_GO, 85.0, "GO")
        a = AL.mark_read(1)
        self.assertTrue(a["read"])
        self.assertEqual(AL.unread_count(), 0)

    def test_mark_read_missing_raises(self):
        with self.assertRaises(AL.AlertError):
            AL.mark_read(999)

    def test_ids_increment(self):
        AL.create_alert(POSTING_GO, 85.0, "GO")
        AL.mark_read(1)
        b = AL.create_alert(POSTING_WEAK, 90.0, "GO")
        self.assertEqual(b["id"], 2)


# ---------------------------------------------------------------------------
# threshold config
# ---------------------------------------------------------------------------

class ThresholdTest(AlertBase):
    def test_default_threshold(self):
        self.assertEqual(AL.get_threshold(), 60.0)

    def test_set_and_get(self):
        self.assertEqual(AL.set_threshold(70), 70.0)
        self.assertEqual(AL.get_threshold(), 70.0)

    def test_set_rejects_out_of_range(self):
        for bad in (-1, 101, 1000):
            with self.assertRaises(AL.AlertError):
                AL.set_threshold(bad)

    def test_set_rejects_non_numeric(self):
        with self.assertRaises(AL.AlertError):
            AL.set_threshold("high")

    def test_passes_gate(self):
        self.assertTrue(AL.passes_gate({"score": 85, "verdict": "GO"}, 60))
        self.assertTrue(AL.passes_gate({"score": 55, "verdict": "CONDITIONAL"}, 60))
        self.assertTrue(AL.passes_gate({"score": 72, "verdict": "NO-GO"}, 60))
        self.assertFalse(AL.passes_gate({"score": 59, "verdict": "NO-GO"}, 60))


# ---------------------------------------------------------------------------
# scoring text
# ---------------------------------------------------------------------------

class ScoringTextTest(AlertBase):
    def test_uses_jd_when_present(self):
        jd = "x" * 700
        with mock.patch("candid.match.fetch_jd") as fj:
            self.assertEqual(AL.scoring_text({"jd": jd, "url": "https://x"}), jd)
            fj.assert_not_called()

    def test_fetches_url_when_text_thin(self):
        with mock.patch("candid.match.fetch_jd",
                        return_value="fetched full jd " * 50) as fj:
            text = AL.scoring_text({"title": "Data Scientist",
                                    "url": "https://x/1"})
        fj.assert_called_once_with("https://x/1")
        self.assertIn("fetched full jd", text)

    def test_falls_back_to_board_text_on_fetch_failure(self):
        from candid.match import MatchError
        with mock.patch("candid.match.fetch_jd",
                        side_effect=MatchError("nope")):
            text = AL.scoring_text({"title": "Data Scientist",
                                    "url": "https://x/1"})
        self.assertIn("Data Scientist", text)


# ---------------------------------------------------------------------------
# matching / evaluation
# ---------------------------------------------------------------------------

class EvaluateTest(AlertBase):
    def test_evaluate_creates_alerts_for_passing_gate(self):
        with _no_fetch(), \
                mock.patch("candid.match.score_match", side_effect=_fake_score):
            res = AL.evaluate_postings([POSTING_GO, POSTING_WEAK], PROFILE)
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["created"]), 1)
        self.assertEqual(res["created"][0]["posting_id"], "greenhouse:acme:1")
        self.assertEqual(len(res["below_threshold"]), 1)
        self.assertEqual(res["below_threshold"][0]["posting_id"],
                         "greenhouse:acme:2")
        self.assertEqual(res["duplicates"], [])

    def test_evaluate_respects_custom_threshold(self):
        posting = dict(POSTING_WEAK, id="w-1")

        def scorer(profile, jd, title="", company="", location=""):
            return {"score": 59.0, "verdict": "NO-GO"}

        with _no_fetch(), mock.patch("candid.match.score_match",
                                     side_effect=scorer):
            self.assertEqual(len(AL.evaluate_postings([posting], PROFILE,
                                                      threshold=60)["created"]), 0)
            self.assertEqual(len(AL.evaluate_postings([posting], PROFILE,
                                                      threshold=50)["created"]), 1)

    def test_evaluate_dedupes_unread(self):
        with _no_fetch(), \
                mock.patch("candid.match.score_match", side_effect=_fake_score):
            AL.evaluate_postings([POSTING_GO], PROFILE)
            res = AL.evaluate_postings([POSTING_GO], PROFILE)
        self.assertEqual(res["created"], [])
        self.assertEqual(len(res["duplicates"]), 1)

    def test_repost_gets_own_kind_and_message(self):
        with _no_fetch(), \
                mock.patch("candid.match.score_match", side_effect=_fake_score):
            res = AL.evaluate_postings([POSTING_REPOST], PROFILE)
        self.assertEqual(len(res["created"]), 1)
        a = res["created"][0]
        self.assertEqual(a["kind"], "repost")
        self.assertIn("back on the board", a["message"])
        self.assertIn("Reposted", a["message"])

    def test_repost_alerts_even_after_read_new_alert(self):
        # a read "new" alert must not block a later "repost" alert
        old = dict(POSTING_REPOST, repost=False)
        with _no_fetch(), \
                mock.patch("candid.match.score_match", side_effect=_fake_score):
            AL.evaluate_postings([old], PROFILE)
        AL.mark_read(1)
        with _no_fetch(), \
                mock.patch("candid.match.score_match", side_effect=_fake_score):
            res = AL.evaluate_postings([POSTING_REPOST], PROFILE)
        self.assertEqual(len(res["created"]), 1)
        self.assertEqual(res["created"][0]["kind"], "repost")


# ---------------------------------------------------------------------------
# run state
# ---------------------------------------------------------------------------

class RunStateTest(AlertBase):
    def test_record_run_counts(self):
        state = AL.record_run([POSTING_GO, POSTING_WEAK],
                              [{"company": "Acme", "id": "old-1"}])
        co = state["companies"]["Acme"]
        self.assertEqual(co["new"], 2)
        self.assertEqual(co["closed"], 1)
        self.assertEqual(co["open"], 1)  # 0 + 2 - 1
        self.assertIn("last_run", co)

    def test_record_run_open_floors_at_zero(self):
        state = AL.record_run([], [{"company": "Acme", "id": "x"}])
        self.assertEqual(state["companies"]["Acme"]["open"], 0)

    def test_record_run_tracks_polled_companies_without_activity(self):
        state = AL.record_run([], [], companies=["Acme", "Beta"])
        for co in ("Acme", "Beta"):
            self.assertIn("last_run", state["companies"][co])
            self.assertEqual(state["companies"][co]["new"], 0)
            self.assertEqual(state["companies"][co]["open"], 0)

    def test_load_runs_empty(self):
        self.assertEqual(AL.load_runs(), {})


# ---------------------------------------------------------------------------
# digest hook
# ---------------------------------------------------------------------------

class DigestHookTest(AlertBase):
    def test_get_pending_alerts_format(self):
        AL.create_alert(POSTING_GO, 85.0, "GO")
        AL.create_alert(POSTING_WEAK, 90.0, "GO")
        AL.mark_read(2)
        pending = AL.get_pending_alerts()
        self.assertEqual(len(pending), 1)
        p = pending[0]
        for key in ("id", "kind", "company", "title", "score", "verdict",
                    "url", "message", "created_at"):
            self.assertIn(key, p)
        self.assertEqual(p["company"], "Acme")

    def test_get_pending_alerts_import_safe(self):
        # corrupt store must not crash the digest hook
        (self.tmp / "alerts.json").write_text("{not json")
        self.assertEqual(AL.get_pending_alerts(), [])

    def test_get_pending_alerts_empty(self):
        self.assertEqual(AL.get_pending_alerts(), [])


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

class RenderTest(AlertBase):
    def test_render_alerts_empty(self):
        self.assertEqual(AL.render_alerts([]), "No alerts.")

    def test_render_run_summary(self):
        res = {"total": 3, "created": [
            {"message": "New posting: X @ Acme — match 85/100 (GO)."}],
            "below_threshold": [{"title": "y"}], "duplicates": []}
        out = AL.render_run_summary(res, 60.0, n_closed=1)
        self.assertIn("3 new posting(s)", out)
        self.assertIn("1 new alert(s)", out)
        self.assertIn("1 closed", out)

    def test_render_status_with_engine_entries(self):
        companies = [{"key": "acme", "name": "Acme",
                      "sources": [{"type": "greenhouse", "label": "acme"}]}]
        runs = {"companies": {"Acme": {"last_run": "2026-09-22T10:00:00",
                                       "new": 1, "closed": 0, "open": 1}}}
        alerts = [{"id": 1, "company": "Acme", "read": False}]
        out = AL.render_status(companies, runs, alerts)
        self.assertIn("Acme", out)
        self.assertIn("2026-09-22T10:00:00", out)
        self.assertIn("1 unread alert(s)", out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class MonitorError(Exception):
    """Fake worker-1 error type."""


class FakeMonitors:
    """Stand-in for the worker-1 monitor engine (real API surface)."""
    def __init__(self):
        self.companies: dict[str, dict] = {}
        self.poll_result = {"date": "2026-09-22", "companies": {},
                            "totals": {"new": 0, "closed": 0, "reposts": 0,
                                       "errors": 0, "skipped": 0}}

    def add_company(self, name):
        name = (name or "").strip()
        if not name:
            raise MonitorError("Company name cannot be empty.")
        if name.lower() in self.companies:
            raise MonitorError(f"Company {name!r} is already monitored.")
        comp = {"key": name.lower(), "name": name, "sources": []}
        self.companies[name.lower()] = comp
        return comp

    def add_source(self, company, source_type, url=None, board=None, site=None):
        comp = self.companies.get(company.lower())
        if comp is None:
            raise MonitorError(f"Unknown company {company!r}.")
        label = board or site or url
        src = {"type": source_type, "url": url or f"{source_type}:{label}",
               "label": label}
        if any(s["url"] == src["url"] for s in comp["sources"]):
            raise MonitorError(f"Source {src['url']} is already registered.")
        comp["sources"].append(src)
        return src

    def remove_company(self, name):
        if name.lower() not in self.companies:
            raise MonitorError(f"Unknown company {name!r}.")
        del self.companies[name.lower()]
        return True

    def list_companies(self):
        return [dict(c) for c in self.companies.values()]

    def poll(self, company=None, **kwargs):
        return self.poll_result


class WatchCLIBase(AlertBase):
    def setUp(self):
        super().setUp()
        self.fake = FakeMonitors()
        mod = types.ModuleType("candid.monitors")
        mod.MonitorError = MonitorError
        mod.add_company = self.fake.add_company
        mod.add_source = self.fake.add_source
        mod.remove_company = self.fake.remove_company
        mod.list_companies = self.fake.list_companies
        mod.poll = self.fake.poll
        sys.modules["candid.monitors"] = mod

    def tearDown(self):
        sys.modules.pop("candid.monitors", None)
        super().tearDown()

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

    def score(self):
        """Context manager stubbing both scoring steps (no network)."""
        stack = contextlib.ExitStack()
        stack.enter_context(_no_fetch())
        stack.enter_context(mock.patch("candid.match.score_match",
                                       side_effect=_fake_score))
        return stack


class WatchAddRemoveListTest(WatchCLIBase):
    def test_add_greenhouse(self):
        code, out, _ = self.run_cli(
            ["watch", "add", "Acme", "--greenhouse", "acme"])
        self.assertEqual(code, 0)
        self.assertIn("acme", out)
        comp = self.fake.companies["acme"]
        self.assertEqual(comp["sources"][0]["type"], "greenhouse")

    def test_add_second_source_to_existing_company(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, out, _ = self.run_cli(
            ["watch", "add", "Acme", "--rss", "https://acme.example/jobs.xml"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.fake.companies["acme"]["sources"]), 2)

    def test_add_duplicate_source_is_friendly_error(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, _, err = self.run_cli(
            ["watch", "add", "Acme", "--greenhouse", "acme"])
        self.assertEqual(code, 1)
        self.assertIn("already registered", err)

    def test_add_requires_exactly_one_source(self):
        code, _, _ = self.run_cli(["watch", "add", "Acme"])
        self.assertEqual(code, 2)  # argparse error
        code, _, _ = self.run_cli(
            ["watch", "add", "Acme", "--greenhouse", "a", "--lever", "b"])
        self.assertEqual(code, 2)

    def test_remove(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, out, _ = self.run_cli(["watch", "remove", "Acme"])
        self.assertEqual(code, 0)
        self.assertIn("Stopped watching", out)
        self.assertEqual(self.fake.companies, {})

    def test_remove_not_watched(self):
        code, out, _ = self.run_cli(["watch", "remove", "Nobody"])
        self.assertEqual(code, 0)
        self.assertIn("not being watched", out)

    def test_list_json(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, out, _ = self.run_cli(["watch", "list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data[0]["name"], "Acme")

    def test_list_human(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, out, _ = self.run_cli(["watch", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Acme", out)
        self.assertIn("greenhouse:acme", out)

    def test_list_empty(self):
        code, out, _ = self.run_cli(["watch", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Not watching", out)


class WatchRunTest(WatchCLIBase):
    def _prime(self):
        self.fake.add_company("Acme")
        self.fake.poll_result = {
            "date": "2026-09-22",
            "companies": {"acme": {
                "name": "Acme", "fetched": 2,
                "new": [dict(POSTING_GO), dict(POSTING_WEAK)],
                "closed": [{"company": "Acme", "id": "old-9"}],
                "reposts": [], "errors": [], "skipped": []}},
            "totals": {"new": 2, "closed": 1, "reposts": 0,
                       "errors": 0, "skipped": 0},
        }

    def test_run_creates_alerts_and_reports(self):
        self._prime()
        with self.score():
            code, out, _ = self.run_cli(["watch", "run"])
        self.assertEqual(code, 0)
        self.assertIn("1 new alert(s)", out)
        self.assertIn("Senior Data Scientist", out)
        self.assertEqual(AL.unread_count(), 1)

    def test_run_json(self):
        self._prime()
        with self.score():
            code, out, _ = self.run_cli(["watch", "run", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["new_postings"], 2)
        self.assertEqual(data["closed_postings"], 1)
        self.assertEqual(len(data["alerts_created"]), 1)
        self.assertEqual(data["threshold"], 60.0)

    def test_run_dedupes_across_runs(self):
        self._prime()
        with self.score():
            self.run_cli(["watch", "run"])
            code, out, _ = self.run_cli(["watch", "run"])
        self.assertEqual(code, 0)
        self.assertIn("0 new alert(s)", out)
        self.assertEqual(AL.unread_count(), 1)

    def test_run_attaches_company_to_postings(self):
        self._prime()
        with self.score():
            self.run_cli(["watch", "run"])
        alerts = AL.load_alerts()
        self.assertEqual(alerts[0]["company"], "Acme")

    def test_run_requires_profile(self):
        C.PROFILE_PATH.unlink()
        self._prime()
        with self.score():
            code, _, err = self.run_cli(["watch", "run"])
        self.assertEqual(code, 1)
        self.assertIn("onboard", err)

    def test_run_records_polled_companies_with_no_activity(self):
        self.fake.add_company("Quiet")
        self.fake.poll_result = {
            "date": "2026-09-22",
            "companies": {"quiet": {
                "name": "Quiet", "fetched": 0, "new": [], "closed": [],
                "reposts": [], "errors": [], "skipped": []}},
            "totals": {"new": 0, "closed": 0, "reposts": 0,
                       "errors": 0, "skipped": 0},
        }
        with self.score():
            code, _, _ = self.run_cli(["watch", "run"])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["watch", "status"])
        self.assertEqual(code, 0)
        self.assertIn("Quiet", out)
        self.assertNotIn("never", out)


class WatchStatusAlertsTest(WatchCLIBase):
    def _prime_run(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        self.fake.poll_result = {
            "date": "2026-09-22",
            "companies": {"acme": {
                "name": "Acme", "fetched": 1,
                "new": [dict(POSTING_GO)], "closed": [],
                "reposts": [], "errors": [], "skipped": []}},
            "totals": {"new": 1, "closed": 0, "reposts": 0,
                       "errors": 0, "skipped": 0},
        }
        with self.score():
            self.run_cli(["watch", "run"])

    def test_status_before_any_run(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        code, out, _ = self.run_cli(["watch", "status"])
        self.assertEqual(code, 0)
        self.assertIn("Acme", out)
        self.assertIn("never", out)

    def test_status_after_run(self):
        self._prime_run()
        code, out, _ = self.run_cli(["watch", "status"])
        self.assertEqual(code, 0)
        self.assertIn("open 1", out)
        self.assertIn("1 unread alert(s)", out)

    def test_alerts_list_and_unread_filter(self):
        self.run_cli(["watch", "add", "Acme", "--greenhouse", "acme"])
        self.run_cli(["watch", "add", "Beta", "--lever", "beta"])
        self.fake.poll_result = {
            "date": "2026-09-22",
            "companies": {
                "acme": {"name": "Acme", "fetched": 1,
                         "new": [dict(POSTING_GO)], "closed": [],
                         "reposts": [], "errors": [], "skipped": []},
                "beta": {"name": "Beta", "fetched": 1,
                         "new": [dict(POSTING_REPOST)], "closed": [],
                         "reposts": [dict(POSTING_REPOST)],
                         "errors": [], "skipped": []}},
            "totals": {"new": 2, "closed": 0, "reposts": 1,
                       "errors": 0, "skipped": 0},
        }
        with self.score():
            self.run_cli(["watch", "run"])
        code, out, _ = self.run_cli(["watch", "alerts"])
        self.assertEqual(code, 0)
        self.assertIn("[new]", out)
        self.assertIn("[repost]", out)
        code, out, _ = self.run_cli(["watch", "alerts-read", "1"])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["watch", "alerts", "--unread"])
        self.assertEqual(code, 0)
        self.assertNotIn("#1 ", out)
        self.assertIn("#2 ", out)

    def test_alerts_json(self):
        self._prime_run()
        code, out, _ = self.run_cli(["watch", "alerts", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data[0]["company"], "Acme")
        self.assertFalse(data[0]["read"])

    def test_alerts_read_missing_id(self):
        code, _, err = self.run_cli(["watch", "alerts-read", "99"])
        self.assertEqual(code, 1)
        self.assertIn("No alert with id 99", err)

    def test_threshold_command(self):
        code, out, _ = self.run_cli(["watch", "threshold", "70"])
        self.assertEqual(code, 0)
        self.assertIn("70", out)
        self.assertEqual(AL.get_threshold(), 70.0)

    def test_threshold_invalid(self):
        code, _, err = self.run_cli(["watch", "threshold", "150"])
        self.assertEqual(code, 1)
        self.assertIn("between 0 and 100", err)


if __name__ == "__main__":
    unittest.main()
