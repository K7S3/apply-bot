"""Tests for the take-home assignment planner (candid.assign).

Run: CANDID_DATA_DIR=/tmp/candid-test-assign python -m pytest tests/test_assign.py -q
"""
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-assign")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import assign as A  # noqa: E402


def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _clean():
    p = Path(os.environ["CANDID_DATA_DIR"])
    if p.exists():
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)


def _plan(**kw):
    args = dict(template="rest-api", company="Acme", role="Backend Engineer",
                deadline=_future(7), hours_per_day=3.0)
    args.update(kw)
    return A.create_plan(**args)


class TemplateTest(unittest.TestCase):
    def test_list_templates(self):
        ts = A.list_templates()
        self.assertEqual(len(ts), 6)
        names = {t["name"] for t in ts}
        self.assertEqual(names, {"data-pipeline", "rest-api", "web-app",
                                 "ml-model", "algorithm-pack", "generic"})
        for t in ts:
            self.assertGreater(t["typical_hours"], 0)

    def test_phase_shares_sum_to_one(self):
        for name in A.TEMPLATES:
            shares = sum(s for _, s, _ in A.TEMPLATES[name]["phases"])
            self.assertAlmostEqual(shares, 1.0, msg=name)

    def test_get_template_unknown(self):
        with self.assertRaises(A.AssignError):
            A.get_template("nope")

    def test_suggest_template(self):
        sug = A.suggest_template("Build a REST API with endpoints for CRUD")
        self.assertEqual(sug["template"], "rest-api")
        self.assertGreater(sug["score"], 0)
        sug = A.suggest_template("Train a classifier and report accuracy")
        self.assertEqual(sug["template"], "ml-model")

    def test_suggest_template_fallback(self):
        sug = A.suggest_template("do something vague with sparkles")
        self.assertEqual(sug["template"], "generic")

    def test_file_map_and_readme_skeleton_have_no_code(self):
        for name in A.TEMPLATES:
            for f in A.file_map(name):
                self.assertNotIn("\n", f)
                self.assertLess(len(f), 60)
            self.assertGreater(len(A.readme_skeleton(name)), 2)


class PlanTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_create_plan(self):
        plan = _plan()
        self.assertEqual(plan["id"], 1)
        self.assertEqual(plan["company"], "Acme")
        self.assertEqual(len(plan["milestones"]), 6)
        dues = [m["due"] for m in plan["milestones"]]
        self.assertEqual(dues, sorted(dues))
        self.assertEqual(dues[-1], plan["deadline"])
        total = round(sum(m["est_hours"] for m in plan["milestones"]), 1)
        self.assertEqual(total, plan["typical_hours"])
        mids = [m["id"] for m in plan["milestones"]]
        self.assertEqual(len(set(mids)), len(mids))

    def test_create_plan_ids_increment(self):
        _plan()
        p2 = _plan(company="Beta")
        self.assertEqual(p2["id"], 2)

    def test_create_plan_bad_deadline(self):
        with self.assertRaises(A.AssignError):
            _plan(deadline="not-a-date")
        with self.assertRaises(A.AssignError):
            _plan(deadline="2026-13-99")

    def test_create_plan_past_deadline(self):
        with self.assertRaises(A.AssignError):
            _plan(deadline=date.today().isoformat())
        with self.assertRaises(A.AssignError):
            _plan(deadline="2020-01-01")

    def test_create_plan_bad_hours(self):
        for bad in (0, -2, 25, "lots"):
            with self.assertRaises(A.AssignError, msg=str(bad)):
                _plan(hours_per_day=bad)

    def test_create_plan_unknown_template(self):
        with self.assertRaises(A.AssignError):
            _plan(template="nope")

    def test_create_plan_requires_company_role(self):
        with self.assertRaises(A.AssignError):
            _plan(company="  ")
        with self.assertRaises(A.AssignError):
            _plan(role="")

    def test_get_plan_unknown(self):
        with self.assertRaises(A.AssignError):
            A.get_plan(999)

    def test_delete_plan(self):
        _plan()
        A.delete_plan(1)
        self.assertEqual(A.list_plans(), [])
        with self.assertRaises(A.AssignError):
            A.delete_plan(1)


class FitTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_fit_ok(self):
        plan = _plan(hours_per_day=8, deadline=_future(7))
        self.assertEqual(plan["fit"]["verdict"], "ok")

    def test_fit_over(self):
        plan = _plan(hours_per_day=0.5, deadline=_future(2))
        self.assertEqual(plan["fit"]["verdict"], "over")
        self.assertGreater(len(plan["fit"]["suggestions"]), 0)

    def test_fit_tight(self):
        # rest-api needs ~10h; 2 days * 3h = 6h, buffer 0.6 -> 5.4 work hrs
        plan = _plan(hours_per_day=3, deadline=_future(2))
        self.assertEqual(plan["fit"]["verdict"], "over")
        plan2 = _plan(hours_per_day=4, deadline=_future(3), company="B")
        # 12h avail, 1.2 buffer -> 10.8 work vs 10 needed -> ok
        self.assertIn(plan2["fit"]["verdict"], ("ok", "tight"))


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_schedule_covers_window(self):
        plan = _plan(deadline=_future(5), hours_per_day=2.0)
        blocks = A.timebox_schedule(plan["id"])
        self.assertTrue(blocks)
        dates = [b["date"] for b in blocks]
        self.assertEqual(dates[0], (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(dates[-1], plan["deadline"])
        kinds = {b["kind"] for b in blocks}
        self.assertIn("buffer", kinds)
        self.assertIn("work", kinds)

    def test_schedule_work_within_budget(self):
        plan = _plan(deadline=_future(7), hours_per_day=3.0)
        blocks = A.timebox_schedule(plan["id"])
        work = round(sum(b["hours"] for b in blocks if b["kind"] == "work"), 1)
        self.assertLessEqual(work, plan["fit"]["work_hours"] + 0.05)

    def test_schedule_single_day(self):
        plan = _plan(deadline=_future(1), hours_per_day=4.0)
        blocks = A.timebox_schedule(plan["id"])
        self.assertTrue(blocks)
        self.assertEqual({b["date"] for b in blocks},
                         {plan["deadline"]})


class ProgressTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_complete_milestone(self):
        plan = _plan()
        m = A.complete_milestone(plan["id"], "m1")
        self.assertTrue(m["done"])
        st = A.plan_status(plan["id"])
        self.assertEqual(st["milestones_done"], 1)
        self.assertEqual(st["next_up"][:2], "m2")

    def test_complete_milestone_unknown(self):
        plan = _plan()
        with self.assertRaises(A.AssignError):
            A.complete_milestone(plan["id"], "m99")

    def test_check_item(self):
        plan = _plan()
        item = A.check_item(plan["id"], "prompt-reread")
        self.assertTrue(item["done"])
        st = A.plan_status(plan["id"])
        self.assertEqual(st["review_done"], 1)

    def test_check_item_unknown(self):
        plan = _plan()
        with self.assertRaises(A.AssignError):
            A.check_item(plan["id"], "nope")

    def test_status_complete(self):
        plan = _plan()
        for m in plan["milestones"]:
            A.complete_milestone(plan["id"], m["id"])
        for r in plan["review"]:
            A.check_item(plan["id"], r["id"])
        st = A.plan_status(plan["id"])
        self.assertTrue(st["complete"])


class ReplanTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_replan_moves_dates_keeps_done(self):
        plan = _plan(deadline=_future(7))
        A.complete_milestone(plan["id"], "m1")
        new_dl = _future(14)
        plan2 = A.replan(plan["id"], new_dl)
        self.assertEqual(plan2["deadline"], new_dl)
        dues = [m["due"] for m in plan2["milestones"]]
        self.assertEqual(dues[-1], new_dl)
        self.assertTrue(plan2["milestones"][0]["done"])
        self.assertFalse(plan2["milestones"][1]["done"])

    def test_replan_bad_deadline(self):
        plan = _plan()
        with self.assertRaises(A.AssignError):
            A.replan(plan["id"], "yesterday")


class ExportTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_export_markdown(self):
        plan = _plan()
        md = A.export_markdown(plan["id"])
        for section in ("## Fit check", "## Milestones",
                        "## Time-boxed schedule", "## Suggested project layout",
                        "## README skeleton", "## Self-review checklist"):
            self.assertIn(section, md)
        self.assertIn(plan["company"], md)
        self.assertIn("candid plans the work", md)


class RenderTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_renders(self):
        self.assertIn("rest-api", A.render_templates())
        self.assertIn("Phases:", A.render_template_detail("ml-model"))
        sug = A.suggest_template("build a rest api")
        self.assertIn("rest-api", A.render_suggestion(sug))
        plan = _plan()
        for out in (A.render_plan(plan), A.render_schedule(A.timebox_schedule(1)),
                    A.render_status(A.plan_status(1)), A.render_review(plan),
                    A.render_plans([plan]), A.render_fit(plan["fit"])):
            self.assertTrue(out.strip())
        self.assertIn("No take-home plans", A.render_plans([]))


class GuardrailTest(unittest.TestCase):
    def test_refusal_text(self):
        self.assertIn("does not do them", A.SOLVE_REFUSAL)
        self.assertIn("assign plan", A.SOLVE_REFUSAL)
        self.assertNotIn("def ", A.SOLVE_REFUSAL)

    def test_no_template_contains_code(self):
        for name, t in A.TEMPLATES.items():
            for phase, _, guidance in t["phases"]:
                self.assertNotIn("```", guidance, msg=f"{name}/{phase}")
            for rid, label, hint in t["review"]:
                self.assertNotIn("```", hint, msg=f"{name}/{rid}")


if __name__ == "__main__":
    unittest.main()
