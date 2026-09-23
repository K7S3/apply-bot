"""Tests for the EM interview-prep module (candid/em_prep.py).

Run: CANDID_DATA_DIR=/tmp/candid-test-em python3 -m pytest tests/test_em_prep.py -v
(also honored when set in-process below).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-em")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-em")
EXPECTED_TOPICS = {
    "hiring", "performance_management", "org_design",
    "incident_leadership", "managing_up", "cross_functional",
}


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _sample_profile():
    return {
        "name": "Test Candidate",
        "experience": [
            {
                "title": "Senior Software Engineer",
                "company": "Acme Corp",
                "bullets": [
                    "Led a team of 5 engineers to rebuild the payments pipeline, cutting p99 latency 40%.",
                    "Mentored 3 junior engineers; two were promoted within a year.",
                ],
            }
        ],
    }


class EMQuestionBankTest(unittest.TestCase):
    def test_bank_loads(self):
        from candid import em_prep as E
        bank = E.load_bank()
        self.assertIn("questions", bank)
        self.assertIn("topics", bank)
        self.assertGreaterEqual(len(bank["questions"]), 20)

    def test_topics_metadata(self):
        from candid import em_prep as E
        slugs = {t["slug"] for t in E.topics()}
        self.assertEqual(slugs, EXPECTED_TOPICS)
        for t in E.topics():
            self.assertTrue(t["label"])
            self.assertGreaterEqual(t["count"], 1)

    def test_every_question_has_source_url(self):
        from candid import em_prep as E
        for q in E.load_bank()["questions"]:
            self.assertTrue(q["q"].strip(), "question text must not be empty")
            self.assertIn(q["topic"], EXPECTED_TOPICS)
            self.assertTrue(q["source"].strip(), f"missing source: {q['q'][:40]}")
            url = q.get("url", "")
            self.assertTrue(url.startswith("http"),
                            f"missing/invalid url: {q['q'][:40]}")

    def test_topics_filter(self):
        from candid import em_prep as E
        for slug in EXPECTED_TOPICS:
            qs = E.questions_by_topic(slug)
            self.assertGreater(len(qs), 0, f"no questions for {slug}")
            for q in qs:
                self.assertEqual(q["topic"], slug)
        # case-insensitive
        self.assertEqual(
            E.questions_by_topic("Hiring"),
            E.questions_by_topic("hiring"))

    def test_unknown_topic_honest_fallback(self):
        from candid import em_prep as E
        qs, note = E.list_questions("compensation_negotiation")
        self.assertEqual(qs, [])
        self.assertIsNotNone(note)
        self.assertIn("No verified questions", note)
        text = E.render_bank_text("compensation_negotiation")
        self.assertIn("No verified questions", text)
        payload = E.bank_as_json("compensation_negotiation")
        self.assertEqual(payload["questions"], [])
        self.assertIn("No verified questions", payload["note"])

    def test_list_all_and_render(self):
        from candid import em_prep as E
        qs, note = E.list_questions()
        self.assertIsNone(note)
        self.assertGreaterEqual(len(qs), 20)
        text = E.render_bank_text("hiring")
        self.assertIn("Hiring", text)
        self.assertIn("Source:", text)
        payload = E.bank_as_json()
        self.assertEqual(payload["count"], len(qs))
        json.dumps(payload)  # serializable


class EMPackTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        self.orig_packs = C.PREP_PACKS_DIR
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))
        C.PREP_PACKS_DIR = Path(self.td.name)

    def tearDown(self):
        from candid import config as C
        C.PREP_PACKS_DIR = self.orig_packs
        self.td.cleanup()

    def test_pack_builds_and_saves(self):
        from candid import em_prep as E
        md, path, sections = E.build_em_pack(_sample_profile(),
                                             role="Engineering Manager")
        self.assertTrue(Path(path).exists())
        self.assertIn("Engineering Manager", md)
        # leadership principles deep dive
        self.assertIn("Hire and Develop the Best", md)
        self.assertIn("Disagree and Commit", md)
        # verified org-design questions with sources
        self.assertIn("Org-design questions", md)
        self.assertIn("Source:", md)
        # EM-angle system design prompts, honestly labeled
        self.assertIn("system design prompts", md)
        self.assertIn("not verified as asked", md)
        # stakeholder scenarios
        self.assertIn("Stakeholder-management scenarios", md)
        # STAR prompts quote the real bullets, never invent
        self.assertIn("cutting p99 latency 40%", md)
        self.assertEqual(set(sections),
                         {"title", "leadership_principles",
                          "org_design_questions", "system_design_prompts",
                          "stakeholder_scenarios", "star_prompts",
                          "mock_interview"})

    def test_pack_without_profile_is_honest(self):
        from candid import em_prep as E
        md, _path, _sections = E.build_em_pack({}, role="Engineering Manager")
        self.assertIn("No resume bullets found", md)

    def test_pack_as_json_serializable(self):
        from candid import em_prep as E
        payload = E.pack_as_json(_sample_profile(), role="Engineering Manager")
        self.assertEqual(payload["role"], "Engineering Manager")
        self.assertTrue(Path(payload["path"]).exists())
        json.dumps(payload)

    def test_jd_hints_reorder(self):
        from candid import em_prep as E
        hints = E._jd_topic_hints("We need an EM to own hiring, grow the team, "
                                  "and run the interview loop.")
        self.assertIn("hiring", hints)
        self.assertEqual(hints[0], "hiring")


class EMCLITest(unittest.TestCase):
    def _run(self, *argv):
        env = dict(os.environ, CANDID_DATA_DIR=str(TEST_DIR))
        return subprocess.run(
            [sys.executable, "-m", "candid", *argv],
            cwd=str(ROOT), env=env, capture_output=True, text=True)

    def setUp(self):
        _clean()

    def test_em_questions_cli(self):
        r = self._run("prep", "em-questions", "--topic", "hiring")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Hiring", r.stdout)
        self.assertIn("Source:", r.stdout)

    def test_em_questions_cli_all(self):
        r = self._run("prep", "em-questions")
        self.assertEqual(r.returncode, 0, r.stderr)
        for label in ("Hiring", "Org design", "Managing up",
                      "Incident leadership"):
            self.assertIn(label, r.stdout)

    def test_em_questions_cli_json(self):
        r = self._run("prep", "em-questions", "--topic", "org_design", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertGreater(len(payload["questions"]), 0)
        for q in payload["questions"]:
            self.assertTrue(q["url"].startswith("http"))

    def test_em_questions_cli_unknown_topic(self):
        r = self._run("prep", "em-questions", "--topic", "foobar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No verified questions", r.stdout)

    def test_em_pack_cli(self):
        # seed a minimal profile so _profile() succeeds
        (TEST_DIR / "profile.json").write_text(
            json.dumps(_sample_profile()), encoding="utf-8")
        r = self._run("prep", "em", "--role", "Engineering Manager")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EM prep pack saved to", r.stdout)
        packs = list((TEST_DIR / "prep_packs").glob("*.md"))
        self.assertEqual(len(packs), 1)

    def test_em_pack_cli_json(self):
        (TEST_DIR / "profile.json").write_text(
            json.dumps(_sample_profile()), encoding="utf-8")
        r = self._run("prep", "em", "--role", "Engineering Manager", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["role"], "Engineering Manager")
        self.assertIn("Hire and Develop the Best", payload["markdown"])

    def test_em_pack_cli_no_profile_clean_error(self):
        r = self._run("prep", "em", "--role", "Engineering Manager")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_prep_still_requires_company_role(self):
        r = self._run("prep")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("prep needs --company and --role", r.stderr)


if __name__ == "__main__":
    unittest.main()
