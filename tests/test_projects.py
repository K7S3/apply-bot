"""Tests for the side-project ideator (candid.projects).

Run: CANDID_DATA_DIR=/tmp/candid-test-projects python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-projects")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "samples" / "candid"

TEST_DIR = Path("/tmp/candid-test-projects")

JD = """About the role: Senior ML Engineer.

Requirements:
- 5+ years of Python and machine learning in production
- Hands-on LLMs: RAG pipelines, prompt evaluation, fine-tuning
- MLOps: Docker, Kubernetes, CI/CD for model deployment
- AWS for training and serving infrastructure
- Strong SQL over large event datasets

Nice to have:
- Recommendation systems experience
"""


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


class LibraryIntegrityTest(unittest.TestCase):
    def test_unique_ids_and_required_fields(self):
        from candid import projects as PR
        from candid import config as C
        ids = [t["id"] for t in PR._IDEAS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate idea ids")
        self.assertGreaterEqual(len(ids), 15, "library should stay substantial")
        required = {"id", "title", "summary", "why", "skills", "roles",
                    "difficulty", "appeal", "stack_skills", "stack",
                    "weekends", "demo", "pitfalls"}
        for t in PR._IDEAS:
            self.assertTrue(required <= set(t), f"{t['id']} missing fields")
            self.assertTrue(1 <= t["difficulty"] <= 3)
            self.assertTrue(1 <= t["appeal"] <= 5)
            for w in t["weekends"]:
                self.assertTrue(w["tasks"], f"{t['id']} weekend has no tasks")
                self.assertTrue(w["done"], f"{t['id']} weekend has no done-criteria")
                self.assertGreater(w["hours"], 0)
            for s in t["skills"]:
                self.assertIn(s, C.SKILL_LEXICON,
                              f"{t['id']} skill '{s}' not in canonical lexicon")

    def test_browse_lists_everything(self):
        from candid import projects as PR
        self.assertEqual(len(PR.list_ideas()), len(PR._IDEAS))

    def test_unknown_idea_lists_valid_ids(self):
        from candid import projects as PR
        with self.assertRaises(PR.ProjectError) as cm:
            PR.get_idea("nope")
        self.assertIn("rag-support-bot", str(cm.exception))


class GapsTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P
        _clean()
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])

    def test_missing_skills_ranked(self):
        from candid import projects as PR
        a = PR.analyze_gaps(self.prof, JD)
        skills = [g["skill"] for g in a["gaps"]]
        self.assertIn("llm", skills)
        self.assertIn("cloud", skills)
        self.assertIn("recommendations", skills)
        # already on the resume -> not gaps
        for s in ("python", "sql", "machine learning", "mlops"):
            self.assertNotIn(s, skills)
        # must outranks nice
        weights = {g["skill"]: g["weight"] for g in a["gaps"]}
        self.assertGreaterEqual(weights["llm"], weights["recommendations"])

    def test_reframe_when_adjacent(self):
        from candid import projects as PR
        prof = {"skills": ["machine learning", "python"]}
        a = PR.analyze_gaps(prof, "Requirements: deep learning with PyTorch.")
        by_skill = {g["skill"]: g for g in a["gaps"]}
        self.assertEqual(by_skill["deep learning"]["fix"], "reframe")

    def test_freeform_tokens_excluded(self):
        from candid import projects as PR
        # "Acme AI" must not produce an "ai" gap: only canonical lexicon
        # skills are actionable for the ideator.
        a = PR.analyze_gaps(self.prof,
                            "Acme AI seeks Python engineers. Requirements: Python.")
        self.assertNotIn("ai", [g["skill"] for g in a["gaps"]])

    def test_ledger_covers_gaps(self):
        from candid import projects as PR, config as C
        td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        self.addCleanup(td.cleanup)
        orig = C.PROJECTS_PATH
        C.PROJECTS_PATH = Path(td.name) / "projects.json"
        self.addCleanup(setattr, C, "PROJECTS_PATH", orig)
        PR.add_project("RAG bot", ["llm", "python"], status="done")
        a = PR.analyze_gaps(self.prof, JD, existing=PR.list_projects())
        self.assertNotIn("llm", [g["skill"] for g in a["gaps"]])
        self.assertEqual(a["covered_by_projects"][0]["project"], "RAG bot")


class IdeasTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P, config as C
        _clean()
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        self.addCleanup(td.cleanup)
        self.orig = C.PROJECTS_PATH
        C.PROJECTS_PATH = Path(td.name) / "projects.json"
        self.addCleanup(setattr, C, "PROJECTS_PATH", self.orig)

    def test_generates_ranked_ideas(self):
        from candid import projects as PR
        ideas = PR.generate_ideas(self.prof, jd_text=JD, n=5)
        self.assertEqual(len(ideas), 5)
        scores = [i["score"] for i in ideas]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for i in ideas:
            self.assertTrue(i["matched_skills"])
            self.assertTrue(i["reasons"])

    def test_ledger_skills_excluded(self):
        from candid import projects as PR
        PR.add_project("RAG bot", ["llm"], status="done")
        ideas = PR.generate_ideas(self.prof, jd_text=JD, n=20)
        for i in ideas:
            self.assertNotIn("llm", i["matched_skills"])

    def test_no_jd_role_filter(self):
        from candid import projects as PR
        ideas = PR.generate_ideas(self.prof, role="frontend", n=20)
        self.assertTrue(ideas)
        for i in ideas:
            self.assertIn("frontend", i["roles"])

    def test_rank_reasons(self):
        from candid import projects as PR
        ranked = PR.rank_ideas([
            {"id": "b", "score": 1.0, "matched_skills": ["sql"],
             "appeal": 3, "difficulty": 2, "weekends": 2},
            {"id": "a", "score": 9.0, "matched_skills": ["llm"],
             "appeal": 5, "difficulty": 1, "weekends": 1},
        ])
        self.assertEqual([r["id"] for r in ranked], ["a", "b"])
        self.assertTrue(any("llm" in r for r in ranked[0]["reasons"]))


class ScopeStackEstimateTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])

    def test_scope_totals(self):
        from candid import projects as PR
        s = PR.weekend_scope("rag-support-bot")
        self.assertEqual(s["total_hours"],
                         sum(w["hours"] for w in s["weekends"]))
        self.assertTrue(all("done" in w and w["done"] for w in s["weekends"]))

    def test_stack_jd_overrides(self):
        from candid import projects as PR
        s = PR.suggest_stack("rag-support-bot",
                             jd_text="We use TypeScript, React, and AWS.")
        self.assertEqual(s["stack"]["language"], "TypeScript")
        self.assertEqual(s["stack"]["framework"], "React")
        self.assertIn("AWS", s["stack"]["deploy"])
        self.assertEqual(len(s["overrides"]), 3)
        self.assertTrue(all("default was" in o for o in s["overrides"]))

    def test_stack_no_jd_no_overrides(self):
        from candid import projects as PR
        s = PR.suggest_stack("dbt-marts")
        self.assertEqual(s["overrides"], [])
        self.assertIn("language", s["stack"])

    def test_estimate_discount_and_calendar(self):
        from candid import projects as PR
        e = PR.estimate("rag-support-bot", self.prof, hours_per_weekend=10,
                        start="2026-09-26")
        self.assertEqual(e["raw_hours"], 22)
        self.assertIn("python", e["known_stack"])  # profile knows python
        self.assertEqual(e["discount_pct"], 10)
        self.assertEqual(e["adjusted_hours"], 20)
        self.assertEqual(e["weekends_needed"], 2)
        self.assertEqual(e["start"], "2026-09-26")
        self.assertEqual(e["end"], "2026-10-03")
        self.assertEqual(len(e["plan"]), 2)

    def test_estimate_padding_when_slow_pace(self):
        from candid import projects as PR
        e = PR.estimate("rag-support-bot", self.prof, hours_per_weekend=5,
                        start="2026-09-26")
        self.assertEqual(e["weekends_needed"], 4)
        self.assertEqual(len(e["plan"]), 4)
        self.assertIn("Buffer", e["plan"][-1]["goal"])

    def test_estimate_bad_inputs(self):
        from candid import projects as PR
        with self.assertRaises(PR.ProjectError):
            PR.estimate("rag-support-bot", self.prof, hours_per_weekend=0)
        with self.assertRaises(PR.ProjectError):
            PR.estimate("rag-support-bot", self.prof, start="not-a-date")


class LearnTest(unittest.TestCase):
    def test_free_resources_per_stack_skill(self):
        from candid import projects as PR
        plan = PR.learning_plan("rag-support-bot")
        self.assertEqual([p["skill"] for p in plan], ["python", "llm"])
        for p in plan:
            self.assertTrue(p["resources"], f"no resources for {p['skill']}")
            for r in p["resources"]:
                self.assertTrue(r["url"].startswith("https://"))

    def test_every_idea_has_resources(self):
        from candid import projects as PR
        missing = []
        for t in PR._IDEAS:
            for p in PR.learning_plan(t["id"]):
                if not p["resources"]:
                    missing.append((t["id"], p["skill"]))
        self.assertEqual(missing, [], f"stack skills without resources: {missing}")


class LedgerTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        self.addCleanup(td.cleanup)
        self.orig = C.PROJECTS_PATH
        C.PROJECTS_PATH = Path(td.name) / "projects.json"
        self.addCleanup(setattr, C, "PROJECTS_PATH", self.orig)

    def test_add_list_update_remove(self):
        from candid import projects as PR
        rec = PR.add_project("Churn model", ["Python", "XGBoost"], status="done",
                             url="https://example.com", description="telco churn")
        self.assertEqual(rec["skills"], ["python", "xgboost"])  # normalized
        self.assertEqual(len(PR.list_projects()), 1)
        self.assertEqual(len(PR.list_projects(status="done")), 1)
        self.assertEqual(len(PR.list_projects(status="planned")), 0)
        PR.add_project("WIP", ["sql"], status="in_progress")
        updated = PR.update_project("WIP", status="done")
        self.assertEqual(updated["status"], "done")
        removed = PR.remove_project("Churn model")
        self.assertEqual(removed["name"], "Churn model")
        self.assertEqual(len(PR.list_projects()), 1)

    def test_duplicate_and_bad_status(self):
        from candid import projects as PR
        PR.add_project("Dup", ["python"])
        with self.assertRaises(PR.ProjectError):
            PR.add_project("dup", ["sql"])  # case-insensitive dup
        with self.assertRaises(PR.ProjectError):
            PR.add_project("Bad", ["sql"], status="shipped")
        with self.assertRaises(PR.ProjectError):
            PR.remove_project("ghost")
        with self.assertRaises(PR.ProjectError):
            PR.update_project("ghost", status="done")


class StoryTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        self.addCleanup(td.cleanup)
        self.orig = C.PROJECTS_PATH
        C.PROJECTS_PATH = Path(td.name) / "projects.json"
        self.addCleanup(setattr, C, "PROJECTS_PATH", self.orig)

    def test_story_from_idea(self):
        from candid import projects as PR
        s = PR.build_story("rag-support-bot")
        self.assertEqual(s["kind"], "idea")
        self.assertEqual(len(s["resume_bullets"]), 3)
        self.assertTrue(all("[" in b for b in s["resume_bullets"]),
                        "bullets must flag unmeasured numbers with [brackets]")
        self.assertIn("never invent metrics", s["note"])
        self.assertTrue(s["demo_checklist"] and s["talking_points"])

    def test_story_from_ledger(self):
        from candid import projects as PR
        PR.add_project("My Bot", ["llm"], status="done",
                       description="Support bot for docs")
        s = PR.build_story("my bot")  # case-insensitive
        self.assertEqual(s["kind"], "ledger")
        self.assertIn("Support bot", s["resume_bullets"][0])

    def test_story_unknown_ref(self):
        from candid import projects as PR
        with self.assertRaises(PR.ProjectError):
            PR.build_story("nothing-here")


class ScaffoldTest(unittest.TestCase):
    def test_python_scaffold(self):
        from candid import projects as PR
        with tempfile.TemporaryDirectory(dir=str(TEST_DIR)) as td:
            target = Path(td) / "bot"
            out = PR.scaffold("rag-support-bot", target)
            self.assertTrue((out / "README.md").exists())
            self.assertTrue((out / "src" / "main.py").exists())
            self.assertTrue((out / "tests" / "test_smoke.py").exists())
            self.assertTrue((out / ".gitignore").exists())
            readme = (out / "README.md").read_text()
            self.assertIn("RAG support bot", readme)
            self.assertIn("Weekend 1", readme)

    def test_node_scaffold(self):
        from candid import projects as PR
        with tempfile.TemporaryDirectory(dir=str(TEST_DIR)) as td:
            out = PR.scaffold("portfolio-site", Path(td) / "site")
            self.assertTrue((out / "package.json").exists())
            self.assertTrue((out / "src" / "index.js").exists())

    def test_refuses_nonempty(self):
        from candid import projects as PR
        with tempfile.TemporaryDirectory(dir=str(TEST_DIR)) as td:
            (Path(td) / "x.txt").write_text("occupied")
            with self.assertRaises(PR.ProjectError):
                PR.scaffold("rag-support-bot", td)


class RenderTest(unittest.TestCase):
    def setUp(self):
        from candid import profile as P, config as C
        _clean()
        self.prof = P.build_profile([(SAMPLES / "sample_resume.md").read_text()])
        td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        self.addCleanup(td.cleanup)
        self.orig = C.PROJECTS_PATH
        C.PROJECTS_PATH = Path(td.name) / "projects.json"
        self.addCleanup(setattr, C, "PROJECTS_PATH", self.orig)

    def test_renders(self):
        from candid import projects as PR
        a = PR.analyze_gaps(self.prof, JD, existing=[])
        self.assertIn("llm", PR.render_gaps(a))
        ideas = PR.generate_ideas(self.prof, jd_text=JD, n=2)
        self.assertIn(ideas[0]["id"], PR.render_ideas(ideas))
        self.assertIn("Weekend 1", PR.render_scope(PR.weekend_scope("dbt-marts")))
        self.assertIn("Recommended stack",
                      PR.render_stack(PR.suggest_stack("dbt-marts")))
        e = PR.estimate("dbt-marts", self.prof, start="2026-09-26")
        self.assertIn("2026-09-26", PR.render_estimate(e))
        t = PR.get_idea("dbt-marts")
        self.assertIn("dbt", PR.render_learn(PR.learning_plan("dbt-marts"), t["title"]).lower())
        PR.add_project("X", ["sql"], status="done")
        self.assertIn("X", PR.render_ledger(PR.list_projects()))
        self.assertIn("empty", PR.render_ledger([]).lower())
        self.assertIn("No ideas", PR.render_ideas([]))


if __name__ == "__main__":
    unittest.main()
