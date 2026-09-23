"""Tests for candid.behavioral (batch-37): leadership-principle frameworks,
values-alignment prompts, story-to-principle mapping, drills, scaffolds,
trap questions, pitch builder, prep-pack integration, and CLI.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import behavioral as B  # noqa: E402
from candid import config as C  # noqa: E402

PROFILE = {
    "name": "Alex Rivera",
    "headline": "Senior Data Scientist",
    "years_experience": 4.5,
    "experience": [
        {"title": "Senior Data Scientist", "company": "Meridian Financial",
         "dates": "Jan 2022 - Present",
         "bullets": [
             "Led a team of 4 to rebuild the churn model, cutting customer churn by 12% and saving $1.2M annually.",
             "Disagreed with the VP's launch plan, presented customer feedback data, and convinced leadership to delay; the revised launch beat targets by 30%.",
             "Automated the reporting pipeline, simplifying 6 manual steps into one scheduled job and saving 10 hours weekly.",
         ]},
        {"title": "Data Analyst", "company": "ShopCo",
         "dates": "Jun 2020 - Dec 2021",
         "bullets": [
             "Built dashboards used by 50+ stakeholders across the company.",
         ]},
    ],
}


class FrameworkTest(unittest.TestCase):
    def test_all_frameworks_listed(self):
        fw = B.list_frameworks()
        keys = {f["key"] for f in fw}
        self.assertTrue({"amazon", "meta", "google", "netflix", "microsoft",
                         "apple", "startup", "finance", "consulting", "default"} <= keys)
        for f in fw:
            self.assertGreater(f["principles"], 0)

    def test_amazon_has_16_principles(self):
        self.assertEqual(len(B.get_framework("amazon")["principles"]), 16)

    def test_each_principle_has_required_fields(self):
        for key, fw in B.FRAMEWORKS.items():
            ids = set()
            for p in fw["principles"]:
                for field in ("id", "name", "desc", "listens_for", "signals"):
                    self.assertIn(field, p, f"{key}.{p.get('id')}: missing {field}")
                self.assertNotIn(p["id"], ids, f"{key}: duplicate principle id {p['id']}")
                ids.add(p["id"])
                self.assertTrue(p["signals"], f"{key}.{p['id']}: empty signals")

    def test_unknown_framework_raises(self):
        with self.assertRaises(KeyError):
            B.get_framework("nonexistent")

    def test_principle_lookup(self):
        p = B.principle_lookup("amazon", "bias_action")
        self.assertEqual(p["name"], "Bias for Action")
        with self.assertRaises(KeyError):
            B.principle_lookup("amazon", "nope")
        with self.assertRaises(KeyError):
            B.principle_lookup("nope", "ownership")


class CompanyMappingTest(unittest.TestCase):
    def test_company_to_framework(self):
        cases = {
            "Amazon": "amazon", "AWS": "amazon", "Meta": "meta",
            "Facebook": "meta", "Google": "google", "DeepMind": "google",
            "Netflix": "netflix", "Microsoft": "microsoft", "GitHub": "microsoft",
            "Apple": "apple", "McKinsey": "consulting", "BCG": "consulting",
            "Bank of America": "finance", "Goldman Sachs": "finance",
            "Capital One": "finance",
        }
        for company, expected in cases.items():
            self.assertEqual(B.framework_for_company(company), expected, company)

    def test_unknown_company_gets_default(self):
        self.assertEqual(B.framework_for_company("Fictional Corp"), "default")
        self.assertEqual(B.framework_for_company(""), "default")


class QuestionBankTest(unittest.TestCase):
    def test_amazon_bank_covers_all_16(self):
        qs = B.lp_questions(framework="amazon")
        self.assertEqual(len(qs), 32)
        covered = {q["principle"] for q in qs}
        self.assertEqual(covered, set(B.principle_slugs("amazon")))

    def test_every_framework_has_questions(self):
        for key in B.FRAMEWORKS:
            qs = B.lp_questions(framework=key)
            self.assertTrue(qs, f"{key} has no questions")
            for q in qs:
                self.assertTrue(q["q"])
                self.assertGreaterEqual(len(q["followups"]), 2)
                # principle tag must exist in the framework
                B.principle_lookup(key, q["principle"])

    def test_filter_by_principle(self):
        qs = B.lp_questions(framework="amazon", principle="ownership")
        self.assertEqual(len(qs), 2)
        self.assertTrue(all(q["principle"] == "ownership" for q in qs))

    def test_company_routing(self):
        qs = B.lp_questions(company="Amazon")
        self.assertTrue(qs)
        self.assertTrue(all(q["framework"] == "amazon" for q in qs))

    def test_invalid_inputs_raise(self):
        with self.assertRaises(KeyError):
            B.lp_questions(framework="nope")
        with self.assertRaises(KeyError):
            B.lp_questions(framework="amazon", principle="nope")


class ValuesAndTrapsTest(unittest.TestCase):
    def test_values_prompts_per_company(self):
        for company in ("Amazon", "Meta", "Google", "Netflix", "Fictional Corp"):
            prompts = B.values_prompts(company=company)
            self.assertGreaterEqual(len(prompts), 3, company)
            for vp in prompts:
                self.assertIn("q", vp)
                self.assertIn("scaffold", vp)

    def test_trap_bank(self):
        traps = B.trap_questions()
        self.assertGreaterEqual(len(traps), 8)
        for t in traps:
            self.assertIn("q", t)
            self.assertIn("why_asked", t)
            self.assertIn("frame", t)
        qs = [t["q"].lower() for t in traps]
        self.assertTrue(any("salary" in q for q in qs))
        self.assertTrue(any("weakness" in q for q in qs))


class StoryMappingTest(unittest.TestCase):
    def test_stories_extracted(self):
        stories = B.stories_from_profile(PROFILE)
        self.assertEqual(len(stories), 4)
        self.assertEqual(stories[0]["company"], "Meridian Financial")

    def test_stories_tolerate_junk(self):
        self.assertEqual(B.stories_from_profile({}), [])
        self.assertEqual(B.stories_from_profile({"experience": None}), [])
        self.assertEqual(B.stories_from_profile({"experience": ["junk", {"bullets": ["short"]}]}), [])

    def test_scoring_finds_hits_and_metrics(self):
        p = B.principle_lookup("amazon", "backbone")
        r = B.score_story_against_principle(PROFILE["experience"][0]["bullets"][1], p)
        self.assertGreater(r["score"], 0)
        self.assertTrue(r["hits"])
        self.assertTrue(r["has_metric"])  # "30%" in the bullet

    def test_map_stories_statuses(self):
        m = B.map_stories(PROFILE, company="Amazon")
        self.assertEqual(m["framework"], "amazon")
        self.assertEqual(len(m["mapping"]), 16)
        statuses = {e["status"] for e in m["mapping"].values()}
        self.assertTrue(statuses <= {"covered", "thin", "missing"})
        # churn story should cover customer obsession / deliver results
        self.assertIn(m["mapping"]["customer_obsession"]["status"], ("covered", "thin"))
        # backbone story: disagreed with VP
        self.assertNotEqual(m["mapping"]["backbone"]["status"], "missing")

    def test_map_stories_empty_profile_all_missing(self):
        m = B.map_stories({}, company="Amazon")
        self.assertTrue(all(e["status"] == "missing" for e in m["mapping"].values()))
        self.assertIsNone(m["mapping"]["ownership"]["best"])

    def test_coverage_report_renders(self):
        md = B.coverage_report(PROFILE, company="Amazon", role="Data Scientist")
        self.assertIn("Amazon Leadership Principles", md)
        self.assertIn("Principle coverage", md)
        self.assertIn("Gaps to close", md)
        self.assertIn("drill plan", md)

    def test_coverage_report_empty_profile(self):
        md = B.coverage_report({}, company="Meta")
        self.assertIn("Meta Values", md)


class DrillTest(unittest.TestCase):
    def test_drill_deterministic_with_seed(self):
        d1 = B.drill(company="Amazon", seed=42)
        d2 = B.drill(company="Amazon", seed=42)
        self.assertEqual(d1["q"], d2["q"])
        self.assertIn("q", d1)
        self.assertGreaterEqual(len(d1["followups"]), 2)
        self.assertIn("name", d1["principle"])

    def test_drill_principle_filter(self):
        d = B.drill(company="Amazon", principle="frugality", seed=1)
        self.assertEqual(d["principle"]["id"], "frugality")

    def test_drill_invalid_principle_raises(self):
        with self.assertRaises(KeyError):
            B.drill(company="Amazon", principle="nope")

    def test_render_drill(self):
        d = B.drill(company="Meta", seed=3)
        out = B.render_drill(d)
        self.assertIn(d["q"], out)
        self.assertIn("Probe 1", out)
        self.assertIn("listening for", out)


class ScaffoldTest(unittest.TestCase):
    def test_all_variants(self):
        for variant in ("star", "star_v", "par", "soar"):
            out = B.scaffold_story("Cut churn 12% by rebuilding the model.", variant=variant)
            self.assertIn("Your bullet", out)
            self.assertIn("150+", out)

    def test_star_v_values_tie(self):
        p = B.principle_lookup("amazon", "bias_action")
        out = B.scaffold_story("Shipped the MVP in 3 weeks.", variant="star_v", principle=p)
        self.assertIn("Bias for Action", out)

    def test_invalid_variant_raises(self):
        with self.assertRaises(KeyError):
            B.scaffold_story("x", variant="nope")


class PitchTest(unittest.TestCase):
    def test_pitch_structure(self):
        out = B.pitch(PROFILE, company="Google")
        self.assertIn("90-Second Pitch", out)
        self.assertIn("Present", out)
        self.assertIn("Past", out)
        self.assertIn("Future", out)
        self.assertIn("Alex Rivera", out)

    def test_pitch_empty_profile(self):
        out = B.pitch({}, company="Netflix")
        self.assertIn("90-Second Pitch", out)
        self.assertIn("No resume bullets found", out)


class PackSectionTest(unittest.TestCase):
    def test_pack_section(self):
        md = B.pack_section(PROFILE, "Amazon", "Data Scientist")
        self.assertIn("Leadership principles & values alignment", md)
        self.assertIn("Amazon Leadership Principles", md)
        self.assertIn("Your coverage:", md)
        self.assertIn("drill", md)

    def test_prep_pack_includes_behavioral_section(self):
        from candid import prep as P
        tmp = Path(tempfile.mkdtemp(prefix="candid-behav-"))
        saved = C.PREP_PACKS_DIR
        C.PREP_PACKS_DIR = tmp
        try:
            md, _ = P.build_pack(PROFILE, "Amazon", "Data Scientist")
        finally:
            C.PREP_PACKS_DIR = saved
        self.assertIn("Leadership principles & values alignment", md)
        self.assertIn("Bias for Action", md)
        # old sections still present (renumbered, not removed)
        self.assertIn("STAR story prompts", md)
        self.assertIn("Company-research checklist", md)
        self.assertIn("Compensation benchmark", md)


class MockIntegrationTest(unittest.TestCase):
    def test_mock_question_adapter(self):
        q = B.mock_question("bias_action", seed=5)
        self.assertIsNotNone(q)
        self.assertIn("question", q)
        self.assertIn("theme", q)
        self.assertIn("id", q)
        self.assertTrue(q["id"].startswith("lp-amazon-bias_action"))

    def test_mock_question_unknown_returns_none(self):
        self.assertIsNone(B.mock_question("not_a_principle"))

    def test_pick_behavioral_falls_back_to_principle(self):
        from candid import mock as M
        q = M._pick_behavioral("bias_action")
        self.assertIn("Bias for Action", q["theme"])

    def test_pick_behavioral_still_rejects_garbage(self):
        from candid import mock as M
        with self.assertRaises(M.MockError):
            M._pick_behavioral("definitely_not_a_theme")


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-behav-cli-"))
        self._saved = {}
        for name in ("PROFILE_PATH", "PREP_PACKS_DIR", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.DATA_DIR = self.tmp
        C.PROFILE_PATH.write_text(json.dumps(PROFILE), encoding="utf-8")

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def _run(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            CLI.main(["behavioral", *args])
        return buf.getvalue()

    def test_frameworks(self):
        out = self._run("frameworks")
        self.assertIn("amazon", out)
        self.assertIn("Amazon Leadership Principles", out)

    def test_lp_bank(self):
        out = self._run("lp-bank", "--company", "Amazon")
        self.assertIn("Customer Obsession", out)

    def test_lp_bank_principle_filter(self):
        out = self._run("lp-bank", "--framework", "amazon", "--principle", "ownership")
        self.assertIn("Ownership", out)

    def test_values(self):
        out = self._run("values", "--company", "Netflix")
        self.assertIn("culture memo", out)

    def test_story_map(self):
        out = self._run("story-map", "--company", "Amazon")
        self.assertIn("Story map", out)
        self.assertIn("Bias for Action", out)

    def test_drill(self):
        out = self._run("drill", "--company", "Amazon", "--principle", "bias_action",
                        "--seed", "11")
        self.assertIn("Drill", out)
        self.assertIn("Probe 1", out)

    def test_coverage(self):
        out = self._run("coverage", "--company", "Meta", "--role", "ML Engineer")
        self.assertIn("Behavioral Coverage", out)

    def test_traps(self):
        out = self._run("traps")
        self.assertIn("salary", out.lower())

    def test_pitch(self):
        out = self._run("pitch", "--company", "Google")
        self.assertIn("90-Second Pitch", out)

    def test_scaffold(self):
        out = self._run("scaffold", "--story", "Cut churn 12%.", "--variant", "par")
        self.assertIn("PAR", out)


if __name__ == "__main__":
    unittest.main()
