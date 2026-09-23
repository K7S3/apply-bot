"""Tests for the 30-60-90 day plan generator (batch 53).

Run: CANDID_DATA_DIR=/tmp/candid-test-b53 python -m unittest discover -s tests
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-b53")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-b53")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _tmp_path(name="plans.json") -> Path:
    d = Path(tempfile.mkdtemp(dir=str(TEST_DIR)))
    return d / name


class FamilyDetectionTest(unittest.TestCase):
    def test_each_family_detected(self):
        from candid import plan_templates as PT
        cases = {
            "Backend Engineer": "backend",
            "Senior Server Engineer": "backend",
            "Frontend Developer": "frontend",
            "iOS Engineer": "mobile",
            "Android Engineer": "mobile",
            "Machine Learning Engineer": "ml",
            "Applied Scientist, GenAI": "ml",
            "Data Engineer": "data",
            "Data Scientist": "data",
            "Site Reliability Engineer": "devops",
            "DevOps Engineer": "devops",
            "Engineering Manager": "em",
            "Product Manager": "pm",
            "Product Designer": "design",
            "UX Designer": "design",
        }
        for role, expected in cases.items():
            with self.subTest(role=role):
                self.assertEqual(PT.detect_family(role), expected)

    def test_unknown_role_falls_back_to_general(self):
        from candid import plan_templates as PT
        self.assertEqual(PT.detect_family("Chief Happiness Officer"), "general")
        self.assertEqual(PT.detect_family(""), "general")

    def test_tier_detection(self):
        from candid import plan_templates as PT
        self.assertEqual(PT.detect_tier("Junior Engineer"), "junior")
        self.assertEqual(PT.detect_tier("Sr. Software Engineer"), "senior")
        self.assertEqual(PT.detect_tier("Staff Engineer"), "staff")
        self.assertEqual(PT.detect_tier("Software Engineer"), "mid")
        self.assertEqual(PT.detect_tier(""), "mid")

    def test_list_families_covers_ten(self):
        from candid import plan_templates as PT
        fams = PT.list_families()
        self.assertEqual(len(fams), 10)
        self.assertIn("general", [f["key"] for f in fams])


class TemplateIntegrityTest(unittest.TestCase):
    def test_all_templates_well_formed(self):
        from candid import plan_templates as PT
        for key, tmpl in PT.ROLE_TEMPLATES.items():
            with self.subTest(family=key):
                self.assertEqual(len(tmpl["phases"]), 3)
                for phase in tmpl["phases"]:
                    self.assertIn(phase["key"], ("p30", "p60", "p90"))
                    self.assertTrue(phase["goals"], "phase has no goals")
                    for g in phase["goals"]:
                        self.assertIn("text", g)
                        lo, hi = PT.WEEK_RANGES[phase["key"]]
                        self.assertTrue(lo <= g["week"] <= hi,
                                        f"week {g['week']} out of range")
                        self.assertIn(g["kind"], ("learning", "relationship",
                                                 "delivery", "process"))
                self.assertTrue(tmpl["learning"])
                for item in tmpl["learning"]:
                    self.assertTrue(item["resources"])
                    self.assertIn(item["priority"], ("high", "medium", "low"))
                self.assertTrue(tmpl["stakeholders"])
                for s in tmpl["stakeholders"]:
                    self.assertTrue(s["first_meeting"])
                    self.assertTrue(s["cadence"])
                self.assertTrue(tmpl["metrics"])
                for m in tmpl["metrics"]:
                    self.assertIn(m["phase"], ("30", "60", "90"))

    def test_level_modifiers_reference_valid_phases(self):
        from candid import plan_templates as PT
        for tier, mod in PT.LEVEL_MODIFIERS.items():
            for pkey in mod["add_goals"]:
                self.assertIn(pkey, ("p30", "p60", "p90"))


class BuildPlanTest(unittest.TestCase):
    def test_plan_structure(self):
        from candid import plan as P
        plan = P.build_plan("Acme", "Backend Engineer", level="mid",
                            start_date="2026-10-05", name="Pat")
        self.assertEqual(plan["role_family"], "backend")
        self.assertEqual(plan["level_tier"], "mid")
        self.assertEqual(plan["start_date"], "2026-10-05")
        self.assertEqual(plan["name"], "Pat")
        self.assertEqual(len(plan["phases"]), 3)
        ids = [g["id"] for ph in plan["phases"] for g in ph["goals"]]
        self.assertEqual(len(ids), len(set(ids)), "goal ids must be unique")
        self.assertTrue(all(i.startswith("g") for i in ids))
        self.assertTrue(all(l["id"].startswith("l") for l in plan["learning"]))
        self.assertTrue(all(m["id"].startswith("m") for m in plan["metrics"]))
        self.assertFalse(any(g["done"] for ph in plan["phases"]
                             for g in ph["goals"]))

    def test_level_modifiers_change_scope(self):
        from candid import plan as P
        junior = P.build_plan("Acme", "Backend Engineer", level="junior")
        senior = P.build_plan("Acme", "Backend Engineer", level="senior")
        staff = P.build_plan("Acme", "Backend Engineer", level="staff")
        nj = sum(len(ph["goals"]) for ph in junior["phases"])
        ns = sum(len(ph["goals"]) for ph in senior["phases"])
        nt = sum(len(ph["goals"]) for ph in staff["phases"])
        self.assertGreater(ns, nj)
        self.assertGreaterEqual(nt, ns)
        self.assertTrue(any(g.get("level_added")
                            for ph in staff["phases"] for g in ph["goals"]))
        # staff scope shows in stakeholder breadth instead of raw goal count
        self.assertGreater(len(staff["stakeholders"]),
                           len(senior["stakeholders"]))
        self.assertIn("Staff", staff["level_note"])

    def test_focus_areas_become_custom_goals(self):
        from candid import plan as P
        plan = P.build_plan("Acme", "Data Scientist",
                            focus_areas=["churn model", "dashboard cleanup"])
        p60 = next(ph for ph in plan["phases"] if ph["key"] == "p60")
        customs = [g for g in p60["goals"] if g.get("custom")]
        self.assertEqual(len(customs), 2)
        self.assertIn("churn model", customs[0]["text"])

    def test_family_override(self):
        from candid import plan as P
        plan = P.build_plan("Acme", "Backend Engineer", family="pm")
        self.assertEqual(plan["role_family"], "pm")

    def test_invalid_inputs_raise(self):
        from candid import plan as P
        from candid.plan import PlanError
        with self.assertRaises(PlanError):
            P.build_plan("", "Backend Engineer")
        with self.assertRaises(PlanError):
            P.build_plan("Acme", "Backend Engineer",
                         start_date="not-a-date")
        with self.assertRaises(PlanError):
            P.build_plan("Acme", "Backend Engineer", family="nope")

    def test_default_start_date_is_today(self):
        from candid import plan as P
        from datetime import date
        plan = P.build_plan("Acme", "Backend Engineer")
        self.assertEqual(plan["start_date"], date.today().isoformat())


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.path = _tmp_path()

    def test_create_list_get_remove_roundtrip(self):
        from candid import plan as P
        p1 = P.create("Acme", "Backend Engineer", path=self.path)
        p2 = P.create("Globex", "Product Manager", path=self.path)
        self.assertEqual(p1["id"], 1)
        self.assertEqual(p2["id"], 2)
        plans = P.list_plans(path=self.path)
        self.assertEqual([p["id"] for p in plans], [2, 1])  # newest first
        self.assertEqual(P.get_plan(1, path=self.path)["company"], "Acme")
        P.remove(1, path=self.path)
        self.assertEqual(len(P.list_plans(path=self.path)), 1)
        with self.assertRaises(P.PlanError):
            P.get_plan(1, path=self.path)
        with self.assertRaises(P.PlanError):
            P.remove(99, path=self.path)


class ProgressTest(unittest.TestCase):
    def setUp(self):
        _clean()
        from candid import plan as P
        self.P = P
        self.path = _tmp_path()
        self.plan = P.create("Acme", "Backend Engineer", path=self.path)

    def test_check_uncheck_flow(self):
        P = self.P
        goal_id = self.plan["phases"][0]["goals"][0]["id"]
        P.check(self.plan["id"], goal_id, path=self.path)
        got = P.get_plan(self.plan["id"], path=self.path)
        g = next(g for ph in got["phases"] for g in ph["goals"]
                 if g["id"] == goal_id)
        self.assertTrue(g["done"])
        self.assertIsNotNone(g["done_on"])
        P.uncheck(self.plan["id"], goal_id, path=self.path)
        got = P.get_plan(self.plan["id"], path=self.path)
        g = next(g for ph in got["phases"] for g in ph["goals"]
                 if g["id"] == goal_id)
        self.assertFalse(g["done"])

    def test_check_unknown_goal_raises(self):
        with self.assertRaises(self.P.PlanError):
            self.P.check(self.plan["id"], "g999", path=self.path)

    def test_progress_math(self):
        P = self.P
        pr = P.progress(self.plan["id"], path=self.path)
        self.assertEqual(pr["done"], 0)
        self.assertEqual(pr["pct"], 0)
        g1 = self.plan["phases"][0]["goals"][0]["id"]
        g2 = self.plan["phases"][0]["goals"][1]["id"]
        P.check(self.plan["id"], g1, path=self.path)
        P.check(self.plan["id"], g2, path=self.path)
        pr = P.progress(self.plan["id"], path=self.path)
        self.assertEqual(pr["done"], 2)
        self.assertEqual(pr["pct"], round(100 * 2 / pr["total"]))
        self.assertIn("p30", pr["by_phase"])
        rendered = P.render_progress(pr)
        self.assertIn("2/", rendered)

    def test_check_learning(self):
        P = self.P
        lid = self.plan["learning"][0]["id"]
        P.check_learning(self.plan["id"], lid, path=self.path)
        got = P.get_plan(self.plan["id"], path=self.path)
        self.assertTrue(got["learning"][0]["done"])
        pr = P.progress(self.plan["id"], path=self.path)
        self.assertEqual(pr["learning_done"], 1)
        with self.assertRaises(P.PlanError):
            P.check_learning(self.plan["id"], "l999", path=self.path)


class WeekViewTest(unittest.TestCase):
    def setUp(self):
        _clean()
        from candid import plan as P
        self.P = P
        self.path = _tmp_path()
        self.plan = P.create("Acme", "Backend Engineer", path=self.path)

    def test_week_view_contents(self):
        w = self.P.week_view(self.plan["id"], 2, path=self.path)
        self.assertEqual(w["week"], 2)
        self.assertIn("30", w["phase"])
        self.assertTrue(all(g["week"] == 2 for g in w["goals"]))
        self.assertTrue(w["prompts"])
        text = self.P.render_week(w)
        self.assertIn("Week 2", text)
        self.assertIn("reflection", text)

    def test_week_maps_to_right_phase(self):
        self.assertIn("60", self.P.week_view(self.plan["id"], 6,
                                             path=self.path)["phase"])
        self.assertIn("90", self.P.week_view(self.plan["id"], 11,
                                             path=self.path)["phase"])

    def test_invalid_week_raises(self):
        with self.assertRaises(self.P.PlanError):
            self.P.week_view(self.plan["id"], 0, path=self.path)
        with self.assertRaises(self.P.PlanError):
            self.P.week_view(self.plan["id"], 13, path=self.path)


class ViewsTest(unittest.TestCase):
    def setUp(self):
        _clean()
        from candid import plan as P
        self.P = P
        self.path = _tmp_path()
        self.plan = P.create("Acme", "Backend Engineer", name="Pat",
                             path=self.path)

    def test_summarize(self):
        text = self.P.summarize(self.plan)
        self.assertIn("Pat", text)
        self.assertIn("Backend Engineer @ Acme", text)
        self.assertIn("Days 1-30", text)
        self.assertIn("Days 61-90", text)

    def test_render_list(self):
        text = self.P.render_list(self.P.list_plans(path=self.path),
                                  path=self.path)
        self.assertIn("#1", text)
        self.assertIn("Acme", text)

    def test_render_list_empty(self):
        text = self.P.render_list([], path=self.path)
        self.assertIn("plan new", text)

    def test_stakeholders_view(self):
        text = self.P.render_stakeholders(self.plan)
        self.assertIn("Engineering manager", text)
        self.assertIn("cadence", text)
        self.assertIn("What does success look like", text)

    def test_learning_view(self):
        text = self.P.render_learning(self.plan)
        self.assertIn("priority", text)
        self.assertIn("Why:", text)

    def test_metrics_view(self):
        text = self.P.render_metrics(self.plan)
        self.assertIn("By day 30:", text)
        self.assertIn("By day 90:", text)
        self.assertIn("Measured by:", text)


class AgendaTest(unittest.TestCase):
    def setUp(self):
        from candid import plan as P
        self.plan = P.build_plan("Acme", "Backend Engineer", name="Pat")

    def test_three_kinds_differ(self):
        from candid import plan as P
        first = P.agenda(self.plan, "first")
        weekly = P.agenda(self.plan, "weekly")
        monthly = P.agenda(self.plan, "monthly")
        self.assertIn("First 1:1", first)
        self.assertIn("Pat", first)
        self.assertIn("Weekly 1:1", weekly)
        self.assertIn("skip-level", monthly)
        self.assertNotEqual(first, weekly)

    def test_unknown_kind_raises(self):
        from candid import plan as P
        with self.assertRaises(P.PlanError):
            P.agenda(self.plan, "yearly")


class ReviewDraftTest(unittest.TestCase):
    def test_review_reflects_completed_work(self):
        from candid import plan as P
        path = _tmp_path()
        plan = P.create("Acme", "Backend Engineer", name="Pat", path=path)
        goal = next(g for ph in plan["phases"] for g in ph["goals"]
                    if g["kind"] == "delivery")
        P.check(plan["id"], goal["id"], path=path)
        text = P.review_draft(P.get_plan(plan["id"], path=path))
        self.assertIn("self-review", text)
        self.assertIn("Pat", text)
        self.assertIn(goal["text"], text)
        self.assertIn("Next 90 days", text)

    def test_empty_plan_has_placeholders(self):
        from candid import plan as P
        plan = P.build_plan("Acme", "Backend Engineer")
        text = P.review_draft(plan)
        self.assertIn("plan check", text)


class ExportTest(unittest.TestCase):
    def setUp(self):
        _clean()
        from candid import config as C, plan as P
        self.C, self.P = C, P
        self.path = _tmp_path()
        self.plan = P.create("Acme", "Backend Engineer", name="Pat",
                             path=self.path)
        self.orig_exports = C.PLAN_EXPORTS_DIR
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        C.PLAN_EXPORTS_DIR = Path(self.td.name)

    def tearDown(self):
        self.C.PLAN_EXPORTS_DIR = self.orig_exports
        self.td.cleanup()

    def test_export_markdown(self):
        dest = self.P.export(self.plan["id"], "md", path=self.path)
        self.assertTrue(dest.exists())
        text = dest.read_text()
        self.assertIn("# 30-60-90 Day Plan", text)
        self.assertIn("Stakeholder map", text)
        self.assertIn("Success metrics", text)
        self.assertIn("Learning goals", text)

    def test_export_html(self):
        dest = self.P.export(self.plan["id"], "html", path=self.path)
        self.assertTrue(dest.exists())
        text = dest.read_text()
        self.assertIn("<html", text)
        self.assertIn("30-60-90 Day Plan", text)
        self.assertIn("</ul>", text)

    def test_unknown_format_raises(self):
        with self.assertRaises(self.P.PlanError):
            self.P.export(self.plan["id"], "pdf", path=self.path)


class PersonalizationTest(unittest.TestCase):
    def test_matching_skills_deprioritize_learning(self):
        from candid import plan as P
        profile = {"skills": ["CI/CD", "incident response", "Terraform"]}
        plan = P.build_plan("Acme", "DevOps Engineer", profile=profile)
        lows = [l for l in plan["learning"] if l["priority"] == "low"]
        self.assertTrue(lows, "expected skill-matched topics deprioritized")
        self.assertTrue(any("background" in l["why"] for l in lows))

    def test_no_profile_keeps_defaults(self):
        from candid import plan as P
        plan = P.build_plan("Acme", "Backend Engineer")
        self.assertTrue(all(l["priority"] in ("high", "medium")
                            for l in plan["learning"]))


class CliWiringTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        # CLI tests use the default (env-resolved) plans path, which _clean()
        # may not cover when CANDID_DATA_DIR is set externally.
        if C.PLANS_PATH.exists():
            C.PLANS_PATH.unlink()

    def _run(self, argv):
        from candid.__main__ import main
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                main(argv)
        except SystemExit:
            pass  # --help and expected-error paths exit; output captured
        return buf.getvalue()

    def test_plan_new_list_show_week_progress(self):
        out = self._run(["plan", "new", "--company", "Acme",
                         "--role", "Backend Engineer", "--level", "senior"])
        self.assertIn("Created 90-day plan #1", out)
        out = self._run(["plan", "list"])
        self.assertIn("#1", out)
        self.assertIn("Acme", out)
        out = self._run(["plan", "show", "1"])
        self.assertIn("Backend Engineer @ Acme", out)
        out = self._run(["plan", "week", "1", "2"])
        self.assertIn("Week 2", out)
        out = self._run(["plan", "progress", "1"])
        self.assertIn("0/", out)

    def test_plan_check_flow_via_cli(self):
        self._run(["plan", "new", "--company", "Acme",
                   "--role", "Backend Engineer"])
        from candid import plan as P
        plan = P.get_plan(1)
        gid = plan["phases"][0]["goals"][0]["id"]
        out = self._run(["plan", "check", "1", gid])
        self.assertIn("done", out.lower())
        out = self._run(["plan", "progress", "1"])
        self.assertIn("1/", out)

    def test_plan_subcommand_views_via_cli(self):
        self._run(["plan", "new", "--company", "Acme",
                   "--role", "Product Manager"])
        for sub in ["stakeholders", "metrics", "learning", "review"]:
            out = self._run(["plan", sub, "1"])
            self.assertTrue(len(out) > 50, sub)
        out = self._run(["plan", "agenda", "1", "--kind", "weekly"])
        self.assertIn("Weekly 1:1", out)
        out = self._run(["plan", "export", "1", "--format", "html"])
        self.assertIn("plan-1.html", out)

    def test_plan_new_with_focus_and_start(self):
        out = self._run(["plan", "new", "--company", "Acme",
                         "--role", "Data Scientist",
                         "--start-date", "2026-10-05",
                         "--focus", "churn model;dashboard cleanup"])
        self.assertIn("2026-10-05", out)

    def test_plan_remove_via_cli(self):
        self._run(["plan", "new", "--company", "Acme",
                   "--role", "Backend Engineer"])
        out = self._run(["plan", "remove", "1"])
        self.assertIn("Removed", out)

    def test_plan_help_lists_subcommands(self):
        out = self._run(["plan", "--help"])
        self.assertIn("new", out)
        self.assertIn("stakeholders", out)


if __name__ == "__main__":
    unittest.main()
