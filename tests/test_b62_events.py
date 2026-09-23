"""Tests for batch 62: candid.events — conference/meetup finder.

Covers the dataset, listing/filtering, relevance ranking, the networking
planner, tracker integration, watchlist, debrief drafts, ICS export,
budget planning, and topic taxonomy. No network, no real user data:
DATA_DIR is redirected to a temp dir.
Run: python3 -m pytest tests/test_b62_events.py -q
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C
from candid import events as E

PROFILE = {
    "name": "Alex Rivera",
    "headline": "Senior Data Scientist",
    "location": "New York, NY",
    "seniority": "senior",
    "years_experience": 6,
    "skills": ["python", "machine learning", "sql", "deep learning",
               "pandas", "mlops", "statistics"],
    "domains": ["fintech", "data"],
    "target_roles": ["Data Scientist", "ML Engineer"],
    "experience": [{"title": "Senior Data Scientist",
                    "bullets": ["Built XGBoost fraud models", "A/B testing framework"]}],
}

TODAY = date(2026, 9, 22)


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_tracker = C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"
        E._TODAY = TODAY

    def tearDown(self):
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        E._TODAY = None
        self.td.cleanup()


# ---------------------------------------------------------------- dataset

class TestDataset(_Base):
    def test_loads_and_validates(self):
        evs = E.load_events()
        self.assertGreaterEqual(len(evs), 20)
        ids = [e["id"] for e in evs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_confidence_values_known(self):
        for ev in E.load_events():
            self.assertIn(ev.get("date_confidence"), E.CONFIDENCE_LABEL)

    def test_verified_dates_are_real(self):
        by_id = {e["id"]: e for e in E.load_events()}
        self.assertEqual(by_id["reinvent-2026"]["start"], "2026-11-30")
        self.assertEqual(by_id["reinvent-2026"]["end"], "2026-12-04")
        self.assertEqual(by_id["pycon-us-2026"]["start"], "2026-05-13")
        self.assertEqual(by_id["kubecon-eu-2026"]["start"], "2026-03-23")

    def test_get_event_unknown_raises(self):
        with self.assertRaises(E.EventsError):
            E.get_event("nope-not-real")

    def test_upcoming_and_days_until(self):
        ev = E.get_event("reinvent-2026")
        self.assertTrue(E.is_upcoming(ev))
        self.assertEqual(E.days_until(ev), 69)  # 2026-09-22 -> 2026-11-30
        past = E.get_event("pycon-us-2026")
        self.assertFalse(E.is_upcoming(past))
        self.assertLess(E.days_until(past), 0)


# ---------------------------------------------------------------- listing

class TestListing(_Base):
    def test_default_is_upcoming_only(self):
        evs = E.list_events(limit=500)
        self.assertTrue(all(E.is_upcoming(e) for e in evs))
        self.assertLess(len(evs), len(E.load_events()))  # past ones excluded

    def test_include_past(self):
        evs = E.list_events(limit=500, include_past=True)
        self.assertEqual(len(evs), len(E.load_events()))

    def test_city_filter(self):
        evs = E.list_events(city="New York", limit=500)
        self.assertTrue(evs)
        self.assertTrue(all("new york" in e["city"].lower() for e in evs))

    def test_free_filter(self):
        evs = E.list_events(free_only=True, limit=500)
        self.assertTrue(evs)
        self.assertTrue(all((e.get("cost_usd") or 0) == 0 for e in evs))

    def test_virtual_filter(self):
        evs = E.list_events(virtual_only=True, limit=500)
        self.assertTrue(evs)
        self.assertTrue(all(e["format"] in ("virtual", "hybrid") for e in evs))

    def test_topic_filter(self):
        evs = E.list_events(topic="python", limit=500)
        self.assertTrue(evs)
        self.assertTrue(all("python" in [t.lower() for t in e["topics"]] for e in evs))

    def test_days_filter(self):
        evs = E.list_events(days=30, limit=500)
        self.assertTrue(all(E.days_until(e) <= 30 for e in evs))

    def test_sorted_by_start(self):
        evs = E.list_events(limit=500)
        starts = [e["start"] for e in evs]
        self.assertEqual(starts, sorted(starts))

    def test_render_list_empty(self):
        self.assertIn("No events match", E.render_list([]))

    def test_render_list_marks_unverified(self):
        evs = E.list_events(limit=500)
        text = E.render_list(evs)
        self.assertIn("NOT verified", text)

    def test_render_show(self):
        ev = E.get_event("reinvent-2026")
        text = E.render_show(ev)
        self.assertIn("AWS re:Invent", text)
        self.assertIn("Las Vegas", text)
        self.assertIn("$2,499", text)
        self.assertIn("Networking angles", text)


# ---------------------------------------------------------------- ranking

class TestRanking(_Base):
    def test_rank_sorted_desc_and_bounded(self):
        ranked = E.rank_events(PROFILE, limit=500)
        self.assertTrue(ranked)
        scores = [r["score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= s <= 100 for s in scores))

    def test_deterministic(self):
        a = E.rank_events(PROFILE, limit=10)
        b = E.rank_events(PROFILE, limit=10)
        self.assertEqual(a, b)

    def test_data_scientist_prefers_data_events(self):
        ranked = E.rank_events(PROFILE, limit=10)
        top_ids = [r["id"] for r in ranked[:3]]
        self.assertIn("odsc-west-2026", top_ids)

    def test_verdict_thresholds(self):
        ranked = E.rank_events(PROFILE, limit=500)
        for r in ranked:
            if r["score"] >= 65:
                self.assertEqual(r["verdict"], "GO")
            elif r["score"] >= 40:
                self.assertEqual(r["verdict"], "CONDITIONAL")
            else:
                self.assertEqual(r["verdict"], "SKIP")

    def test_score_has_why_and_components(self):
        r = E.score_event(PROFILE, E.get_event("reinvent-2026"))
        self.assertTrue(r["why"])
        self.assertEqual(set(r["components"]), {"role", "skills", "seniority", "logistics"})

    def test_frontend_profile_ranks_react_high(self):
        fe = dict(PROFILE, headline="Frontend Engineer",
                  skills=["react", "javascript", "typescript"],
                  target_roles=["Frontend Engineer"])
        ranked = E.rank_events(fe, limit=500)
        by_id = {r["id"]: r for r in ranked}
        self.assertGreater(by_id["react-summit-us-2026"]["score"],
                           by_id["neurips-2026"]["score"])

    def test_render_ranked(self):
        text = E.render_ranked(E.rank_events(PROFILE, limit=3))
        self.assertIn("Ranked by fit", text)
        self.assertIn("events plan", text)


# ---------------------------------------------------------------- planner

class TestPlanner(_Base):
    def test_plan_structure_and_files(self):
        plan = E.plan_event(PROFILE, "nyc-python-meetup", target_contacts=8)
        for key in ("goals", "who_to_meet", "conversation_starters",
                    "elevator_pitch", "session_strategy",
                    "pre_event_checklist", "follow_up_targets"):
            self.assertTrue(plan[key], key)
        self.assertIn("Alex Rivera", plan["elevator_pitch"])
        d = C.DATA_DIR / "event_plans"
        self.assertTrue((d / "nyc-python-meetup.json").exists())
        self.assertTrue((d / "nyc-python-meetup.md").exists())

    def test_plan_custom_goals(self):
        plan = E.plan_event(PROFILE, "odsc-west-2026", goals=["find a mentor"])
        self.assertEqual(plan["goals"], ["find a mentor"])

    def test_plan_unknown_event(self):
        with self.assertRaises(E.EventsError):
            E.plan_event(PROFILE, "nope")

    def test_load_plan_roundtrip(self):
        E.plan_event(PROFILE, "odsc-west-2026")
        loaded = E.load_plan("odsc-west-2026")
        self.assertEqual(loaded["event_id"], "odsc-west-2026")

    def test_load_plan_missing(self):
        with self.assertRaises(E.EventsError):
            E.load_plan("never-planned")

    def test_render_plan(self):
        plan = E.plan_event(PROFILE, "odsc-west-2026")
        text = E.render_plan(plan)
        self.assertIn("# Networking plan: ODSC West", text)
        self.assertIn("events debrief odsc-west-2026", text)


# ---------------------------------------------------------------- tracker + watchlist

class TestTrackerWatch(_Base):
    def test_save_to_tracker(self):
        rec = E.save_to_tracker("odsc-west-2026")
        self.assertEqual(rec["status"], "saved")
        self.assertIn("ODSC West", rec["company"])
        self.assertIn("odsc.com", rec["jd_link"])

    def test_save_duplicate_returns_existing(self):
        first = E.save_to_tracker("odsc-west-2026")
        second = E.save_to_tracker("odsc-west-2026")
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["id"], second["id"])

    def test_watch_roundtrip(self):
        self.assertEqual(E.watch_list(), [])
        E.watch_add("reinvent-2026")
        E.watch_add("odsc-west-2026")
        E.watch_add("reinvent-2026")  # idempotent
        ids = [e["id"] for e in E.watch_list()]
        self.assertEqual(sorted(ids), ["odsc-west-2026", "reinvent-2026"])
        E.watch_remove("reinvent-2026")
        self.assertEqual([e["id"] for e in E.watch_list()], ["odsc-west-2026"])

    def test_watch_add_unknown(self):
        with self.assertRaises(E.EventsError):
            E.watch_add("nope")

    def test_upcoming_digest(self):
        evs = E.upcoming_digest(days=40)
        self.assertTrue(evs)
        self.assertTrue(all(E.days_until(e) <= 40 for e in evs))

    def test_upcoming_digest_watched_only(self):
        E.watch_add("reinvent-2026")
        evs = E.upcoming_digest(days=400, watched_only=True)
        self.assertEqual([e["id"] for e in evs], ["reinvent-2026"])


# ---------------------------------------------------------------- debrief

class TestDebrief(_Base):
    def test_parse_contacts(self):
        cs = E.parse_contacts("Jane Doe, Engineer, Acme, great talk on Airflow; Sam Lee")
        self.assertEqual(len(cs), 2)
        self.assertEqual(cs[0]["name"], "Jane Doe")
        self.assertEqual(cs[0]["company"], "Acme")
        self.assertEqual(cs[1], {"name": "Sam Lee", "role": "", "company": "", "note": ""})

    def test_parse_contacts_empty(self):
        self.assertEqual(E.parse_contacts(""), [])
        self.assertEqual(E.parse_contacts(";;;"), [])

    def test_debrief_drafts_and_file(self):
        contacts = E.parse_contacts("Jane Doe, Engineer, Acme, loved her Airflow talk; Sam Lee")
        result = E.debrief(PROFILE, "nyc-python-meetup", contacts)
        self.assertEqual(len(result["drafts"]), 2)
        d0 = result["drafts"][0]
        self.assertIn("NYC Python Meetup", d0["subject"])
        self.assertIn("Jane", d0["body"])
        self.assertIn("Alex Rivera", d0["body"])
        self.assertIn("Airflow", d0["body"])
        p = C.DATA_DIR / "event_plans" / "nyc-python-meetup_debrief.md"
        self.assertTrue(p.exists())

    def test_render_debrief(self):
        contacts = E.parse_contacts("Jane Doe, Engineer, Acme")
        text = E.render_debrief(E.debrief(PROFILE, "odsc-west-2026", contacts))
        self.assertIn("To: Jane Doe", text)
        self.assertIn("Subject:", text)


# ---------------------------------------------------------------- ics + budget + topics

class TestIcsBudgetTopics(_Base):
    def test_export_ics_valid(self):
        evs = E.list_events(limit=3)
        dest = Path(self.td.name) / "out.ics"
        E.export_ics(evs, dest)
        text = dest.read_text(encoding="utf-8")
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("END:VCALENDAR", text)
        self.assertEqual(text.count("BEGIN:VEVENT"), 3)
        for ev in evs:
            self.assertIn(f"UID:{ev['id']}@candid.local", text)
            self.assertIn("DTSTART;VALUE=DATE:" + ev["start"].replace("-", ""), text)

    def test_budget_math(self):
        b = E.budget_plan("reinvent-2026", travel_usd=400, nights=4,
                          hotel_per_night=180, per_diem=75, budget=3000)
        # 5 event days: 2499 + 400 + 720 + 375 = 3994
        self.assertEqual(b["total"], 3994.0)
        self.assertEqual(b["verdict"], "OVER budget")
        self.assertEqual(b["breakdown"]["ticket"], 2499.0)

    def test_budget_within(self):
        b = E.budget_plan("nyc-python-meetup", budget=100)
        self.assertEqual(b["verdict"], "within budget")
        self.assertEqual(b["total"], 75.0)  # 1 day * $75 per diem

    def test_budget_no_budget_arg(self):
        b = E.budget_plan("odsc-west-2026", travel_usd=200)
        self.assertIsNone(b["budget"])
        self.assertEqual(b["verdict"], "within budget")

    def test_render_budget_over(self):
        b = E.budget_plan("reinvent-2026", budget=100)
        text = E.render_budget(b)
        self.assertIn("OVER budget", text)
        self.assertIn("consider:", text)

    def test_topics_sorted(self):
        pairs = E.topics()
        self.assertTrue(pairs)
        counts = [n for _, n in pairs]
        self.assertEqual(counts, sorted(counts, reverse=True))
        by_name = dict(pairs)
        self.assertGreater(by_name.get("ai-ml", 0), 3)

    def test_render_topics(self):
        text = E.render_topics(E.topics())
        self.assertIn("ai-ml", text)
        self.assertIn("events list --topic", text)


# ---------------------------------------------------------------- CLI

class TestCLI(_Base):
    def _run(self, *argv):
        from candid.__main__ import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["events", *argv])
        return buf.getvalue()

    def test_cli_list_json(self):
        out = self._run("list", "--topic", "python", "--json")
        data = json.loads(out)
        self.assertTrue(data)
        self.assertTrue(all("python" in e["topics"] for e in data))

    def test_cli_rank(self):
        with patch("candid.__main__._profile", return_value=PROFILE):
            out = self._run("rank", "--limit", "2")
        self.assertIn("Ranked by fit", out)

    def test_cli_show(self):
        out = self._run("show", "reinvent-2026")
        self.assertIn("AWS re:Invent", out)

    def test_cli_show_unknown_exits_1(self):
        from candid.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                main(["events", "show", "nope"])
        self.assertEqual(cm.exception.code, 1)

    def test_cli_plan_saves(self):
        with patch("candid.__main__._profile", return_value=PROFILE):
            out = self._run("plan", "odsc-west-2026")
        self.assertIn("Plan saved", out)

    def test_cli_watch_add_list_remove(self):
        self._run("watch", "add", "odsc-west-2026")
        out = self._run("watch", "list")
        self.assertIn("odsc-west-2026", out)
        self._run("watch", "remove", "odsc-west-2026")
        out = self._run("watch", "list")
        self.assertIn("empty", out)

    def test_cli_debrief_needs_contacts(self):
        from candid.__main__ import main
        with patch("candid.__main__._profile", return_value=PROFILE):
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    main(["events", "debrief", "odsc-west-2026"])

    def test_cli_calendar(self):
        dest = str(Path(self.td.name) / "cal.ics")
        out = self._run("calendar", "--out", dest, "--days", "60")
        self.assertIn("Wrote", out)
        self.assertTrue(Path(dest).exists())

    def test_cli_budget(self):
        out = self._run("budget", "reinvent-2026", "--budget", "5000")
        self.assertIn("within budget", out)

    def test_cli_topics(self):
        out = self._run("topics")
        self.assertIn("ai-ml", out)

    def test_cli_save(self):
        out = self._run("save", "odsc-west-2026")
        self.assertIn("Saved to tracker", out)

    def test_cli_upcoming(self):
        out = self._run("upcoming", "--days", "40")
        self.assertIn("Events in the next 40 days", out)


if __name__ == "__main__":
    unittest.main()
