"""New-grad track tests (worker C, batch 88).

Covers:
  - new-grad question selection + fundamentals weighting (prep --new-grad)
  - new-grad behavioral set, deep-dives, system-design note (prep --new-grad)
  - thin-experience detection (tailor --new-grad)
  - projects-first ordering, coursework opt-in (tailor --new-grad)
  - no-fabrication guardrails (never invent experience, metrics, or facts)
  - CLI flag wiring (flags only, no new top-level commands)

Run: CANDID_DATA_DIR=/tmp/candid-test-newgrad-c python -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-newgrad-c")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-newgrad-c")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _new_grad_profile(**over):
    prof = {
        "name": "New Grad",
        "headline": "CS senior",
        "location": "New York, NY",
        "skills": ["python", "sql", "git"],
        "experience": [
            {"title": "SWE Intern", "company": "Acme Corp", "dates": "2025",
             "bullets": [
                 "Helped with data pipelines",
                 "Built a dashboard used by 40 people",
             ]},
        ],
        "education": [
            {"school": "State University", "degree": "BS Computer Science",
             "dates": "2026", "coursework": ["Algorithms", "Databases"],
             "gpa": "3.8"},
        ],
        "years_experience": 0.3,
        "seniority": "entry",
        "projects": [
            {"name": "TrailFinder", "tech": "React, Flask",
             "bullets": [
                 "Worked on a hiking trail app",
                 "Cut API latency by 60% with response caching",
             ]},
        ],
    }
    prof.update(over)
    return prof


class NewGradQuestionSelectionTest(unittest.TestCase):
    def test_questions_weighted_fundamentals(self):
        from candid import prep as P
        qs = P.select_new_grad_questions()
        cats = [q["category"] for q in qs]
        # fundamentals areas appear, and DSA (weight 4) outranks each advanced area
        self.assertEqual(cats.count("dsa_fundamentals"), P.NEW_GRAD_WEIGHTS["dsa"])
        self.assertEqual(cats.count("sql_basics"), P.NEW_GRAD_WEIGHTS["sql_basics"])
        self.assertEqual(cats.count("oop"), P.NEW_GRAD_WEIGHTS["oop"])
        self.assertEqual(cats.count("os_networking"), P.NEW_GRAD_WEIGHTS["os_networking"])
        # fundamentals come before behavioral in the ordered pack
        first_behav = cats.index("new_grad_behavioral")
        self.assertTrue(all(c != "new_grad_behavioral" for c in cats[:first_behav]))
        self.assertEqual(len(qs), sum(P.NEW_GRAD_WEIGHTS.values()))

    def test_behavioral_set_covers_named_topics(self):
        from candid import prep as P
        qs = [q["q"] for q in P.select_new_grad_questions()
              if q["category"] == "new_grad_behavioral"]
        joined = " ".join(qs).lower()
        self.assertIn("team project", joined)
        self.assertIn("learn", joined)
        self.assertIn("feedback", joined)
        self.assertIn("ambiguous", joined)
        self.assertIn("first", joined)  # why this company as a first job

    def test_new_grad_sections_pure(self):
        from candid import prep as P
        prof = _new_grad_profile()
        qs, dds, note = P.new_grad_sections(prof)
        self.assertIsInstance(qs, list)
        self.assertTrue(all("q" in q for q in qs))
        self.assertIsInstance(dds, list)
        self.assertTrue(all(isinstance(d, str) for d in dds))
        self.assertIn("lighter", note.lower())


class NewGradPrepPackTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        self.prof = _new_grad_profile()
        self.orig_packs = C.PREP_PACKS_DIR
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        C.PREP_PACKS_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def _pack(self, **kw):
        from candid import prep as P
        md, _ = P.build_pack(self.prof, "Fictional Corp", "Software Engineer", **kw)
        return md

    def test_pack_has_fundamentals_questions(self):
        md = self._pack(new_grad=True)
        self.assertIn("Big-O", md)
        self.assertIn("Entry-level mode", md)

    def test_pack_has_entry_level_deepdives(self):
        md = self._pack(new_grad=True)
        self.assertIn("Entry-level concept deep-dives", md)
        self.assertIn("Fundamentals First", md)
        # fundamentals deep-dives come before the advanced fallback section
        self.assertLess(md.index("Entry-level concept deep-dives"),
                        md.index("Advanced deep-dives"))

    def test_pack_has_system_design_note(self):
        md = self._pack(new_grad=True)
        self.assertIn("system design expectations are much lighter", md.lower())

    def test_pack_behavioral_set_included(self):
        md = self._pack(new_grad=True)
        self.assertIn("critical feedback", md.lower())

    def test_star_prompts_use_new_grad_rotation_and_projects(self):
        md = self._pack(new_grad=True)
        self.assertIn("team project", md.lower())
        self.assertIn("TrailFinder", md)  # project bullet usable as STAR source

    def test_default_pack_unaffected(self):
        md = self._pack()
        self.assertNotIn("Entry-level concept deep-dives", md)
        self.assertNotIn("system design expectations are much lighter", md.lower())
        self.assertNotIn("Entry-level mode", md)


class ThinExperienceDetectionTest(unittest.TestCase):
    def test_zero_roles_is_thin(self):
        from candid import tailor as T
        self.assertTrue(T.is_thin_experience(_new_grad_profile(experience=[])))

    def test_one_role_is_thin(self):
        from candid import tailor as T
        prof = _new_grad_profile()
        prof["years_experience"] = 5.0  # years alone do not save a single role
        self.assertTrue(T.is_thin_experience(prof))

    def test_under_one_year_is_thin(self):
        from candid import tailor as T
        prof = _new_grad_profile(experience=[
            {"title": "A", "company": "X", "dates": "2026", "bullets": []},
            {"title": "B", "company": "Y", "dates": "2026", "bullets": []},
        ], years_experience=0.5)
        self.assertTrue(T.is_thin_experience(prof))

    def test_two_roles_two_years_not_thin(self):
        from candid import tailor as T
        prof = _new_grad_profile(experience=[
            {"title": "A", "company": "X", "dates": "2024", "bullets": []},
            {"title": "B", "company": "Y", "dates": "2025", "bullets": []},
        ], years_experience=2.0)
        self.assertFalse(T.is_thin_experience(prof))


class ProjectsFirstResumeTest(unittest.TestCase):
    def test_projects_lead_when_thin(self):
        from candid import tailor as T
        r = T.build_resume(_new_grad_profile(), "python sql",
                           company="Acme", role="SWE", new_grad=True)
        self.assertLess(r.index("PROJECTS"), r.index("EXPERIENCE"))
        self.assertLess(r.index("SKILLS"), r.index("EXPERIENCE"))
        self.assertIn("New-grad layout: projects first", r)

    def test_standard_order_when_not_thin(self):
        from candid import tailor as T
        prof = _new_grad_profile(experience=[
            {"title": "A", "company": "X", "dates": "2024", "bullets": ["Did X"]},
            {"title": "B", "company": "Y", "dates": "2025", "bullets": ["Did Y"]},
        ], years_experience=3.0)
        r = T.build_resume(prof, "python", new_grad=True)
        self.assertLess(r.index("EXPERIENCE"), r.index("SKILLS"))
        self.assertNotIn("New-grad layout", r)

    def test_projects_section_uses_profile_data_only(self):
        from candid import tailor as T
        r = T.build_resume(_new_grad_profile(), "python",
                           company="Acme", role="SWE", new_grad=True)
        self.assertIn("TrailFinder", r)
        self.assertIn("React, Flask", r)

    def test_no_projects_gives_honest_note(self):
        from candid import tailor as T
        prof = _new_grad_profile(projects=[])
        r = T.build_resume(prof, "python", company="Acme", role="SWE",
                           new_grad=True)
        self.assertIn("no projects in profile", r.lower())

    def test_coursework_only_when_opted_in(self):
        from candid import tailor as T
        prof = _new_grad_profile()
        with_opt = T.build_resume(prof, "python", new_grad=True,
                                  include_coursework=True)
        self.assertIn("Relevant coursework: Algorithms, Databases", with_opt)
        self.assertIn("GPA: 3.8", with_opt)
        without = T.build_resume(prof, "python", new_grad=True)
        self.assertNotIn("Relevant coursework", without)
        self.assertNotIn("GPA: 3.8", without)

    def test_coursework_missing_data_says_so(self):
        from candid import tailor as T
        prof = _new_grad_profile(education=[
            {"school": "State University", "degree": "BS CS", "dates": "2026"}])
        r = T.build_resume(prof, "python", new_grad=True,
                           include_coursework=True)
        self.assertIn("no coursework/gpa in profile", r.lower())

    def test_weak_bullet_feedback_suggests_not_invents(self):
        from candid import tailor as T
        notes = T.weak_bullet_feedback([
            "Helped with data pipelines",
            "Cut API latency by 60% with response caching",
        ])
        self.assertEqual(len(notes), 1)  # only the weak one flagged
        self.assertIn("Helped with data pipelines", notes[0])
        self.assertIn("scope number", notes[0])
        # the suggestion never fills in a number itself
        import re
        suggestion_part = notes[0].split("->", 1)[1]
        self.assertFalse(re.search(r"\b\d+\b", suggestion_part))

    def test_bullet_feedback_section_in_resume(self):
        from candid import tailor as T
        r = T.build_resume(_new_grad_profile(), "python",
                           company="Acme", role="SWE", new_grad=True)
        self.assertIn("BULLET FEEDBACK", r)
        self.assertIn("nothing auto-filled", r)

    def test_no_fabrication(self):
        from candid import tailor as T
        prof = _new_grad_profile()
        r = T.build_resume(prof, "python sql", company="Acme", role="SWE",
                           new_grad=True, include_coursework=True)
        # every employer/project named must come from the profile
        for invented in ["Google", "Meta", "Stanford", "HackathonX",
                         "10x", "million users"]:
            self.assertNotIn(invented, r)
        self.assertIn("Acme Corp", r)      # real experience employer
        self.assertIn("TrailFinder", r)    # real project
        self.assertIn("State University", r)  # real school


class NewGradCoverLetterTest(unittest.TestCase):
    def test_new_grad_paragraph(self):
        from candid import tailor as T
        prof = _new_grad_profile()
        with_ng = T.build_cover_letter(prof, "python", "Acme", "SWE",
                                       new_grad=True)
        self.assertIn("entry-level", with_ng)
        self.assertIn("first", with_ng)
        without = T.build_cover_letter(prof, "python", "Acme", "SWE")
        self.assertNotIn("entry-level candidate", without)


class NewGradCLIFlagsTest(unittest.TestCase):
    def _run_help(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "candid", *args, "--help"],
            capture_output=True, text=True, cwd=str(ROOT))

    def test_prep_new_grad_flag(self):
        r = self._run_help("prep")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--new-grad", r.stdout)

    def test_tailor_new_grad_and_coursework_flags(self):
        r = self._run_help("tailor", "resume")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--new-grad", r.stdout)
        self.assertIn("--include-coursework", r.stdout)


if __name__ == "__main__":
    unittest.main()
