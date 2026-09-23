"""Tests for batch 55: skills radar (candid/skills_radar.py).

Covers the 10 features:
  1. AXES taxonomy + skill->axis mapping (every config lexicon skill mapped)
  2. skill_proficiency: evidence scoring, recency, 0..100 bounds
  3. axis_coverage: diminishing-returns aggregation, bounds
  4. ROLE_TARGETS catalog + load_target (builtin, unknown, custom JSON)
  5. gap_analysis: impact ordering, met/near/gap, readiness
  6. prioritize_gaps: benefit-per-hour order, prereqs first, empty when met
  7. render_ascii_radar: glyphs, labels, determinism
  8. evidence_for_axis: entry tracing, unknown axis error
  9. snapshots + trend: persistence, replace-on-same-date, deltas
 10. plan_report / report_markdown: sections, JSON-serializable

Run: CANDID_DATA_DIR=/tmp/candid-test-sr python3 -m pytest tests/test_skills_radar.py -q
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="candid-test-sr-")
os.environ["CANDID_DATA_DIR"] = _TMP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import skills_radar as SR  # noqa: E402


def _profile(**kw):
    """Fictional profile: senior backend/ML engineer."""
    base = {
        "name": "Test Person",
        "headline": "Senior Software Engineer, ML platform",
        "location": "New York, NY",
        "summary": "Backend engineer building ML ranking systems in Python.",
        "skills": ["python", "machine learning", "sql", "aws", "docker",
                   "system design", "leadership", "communication"],
        "experience": [
            {"title": "Senior Software Engineer", "company": "Acme",
             "dates": "2022 - Present",
             "bullets": [
                 "Designed Python microservices for ML ranking with pytorch models.",
                 "Led team of 4 engineers; mentored junior developers.",
                 "Deployed to AWS with docker and kubernetes; added monitoring.",
             ]},
            {"title": "Software Engineer", "company": "Beta",
             "dates": "2019 - 2022",
             "bullets": [
                 "Built SQL ETL pipelines in spark for analytics.",
                 "Shipped react dashboard for data visualization.",
             ]},
        ],
        "education": [{"school": "State U", "degree": "BS CS", "dates": "2015 - 2019"}],
        "years_experience": 7.0,
        "seniority": "senior",
        "source_files": [],
    }
    base.update(kw)
    return base


class TestTaxonomy(unittest.TestCase):
    def test_every_lexicon_skill_mapped_exactly_once(self):
        seen = {}
        for axis, skills in SR.AXES.items():
            for s in skills:
                self.assertNotIn(s, seen, f"{s} mapped twice")
                seen[s] = axis
        for skill in C.SKILL_LEXICON:
            self.assertIn(skill, seen,
                          f"lexicon skill '{skill}' has no radar axis")

    def test_axis_for_skill(self):
        self.assertEqual(SR.axis_for_skill("python"), "Languages")
        self.assertEqual(SR.axis_for_skill("pytorch"), "ML & AI")
        self.assertEqual(SR.axis_for_skill("react"), "Frontend & Mobile")
        self.assertIsNone(SR.axis_for_skill("not-a-skill"))

    def test_eight_axes(self):
        self.assertEqual(len(SR.AXES), 8)

    def test_skill_hit_aliases(self):
        self.assertTrue(SR.skill_hit("kubernetes", "we use k8s in prod"))
        self.assertTrue(SR.skill_hit("ci/cd", "set up CI/CD pipelines"))
        self.assertTrue(SR.skill_hit("python", "Python developer"))
        self.assertFalse(SR.skill_hit("python", "no relevant tech here"))
        # single-letter 'r' follows the lexicon convention (same as profile.py):
        # it matches via the 'r programming' alias, never inside other words
        self.assertFalse(SR.skill_hit("r", "our server fleet"))
        self.assertTrue(SR.skill_hit("r", "used r programming for stats"))


class TestProficiency(unittest.TestCase):
    def test_skills_section_gives_base(self):
        p = _profile()
        got = SR.skill_proficiency("python", p)
        self.assertGreaterEqual(got["score"], 45)
        self.assertIn("skills_section", got["breakdown"])

    def test_recency_matters(self):
        p = _profile()
        # pytorch: mentioned only in most recent role's bullets
        recent = SR.skill_proficiency("pytorch", p)
        self.assertGreater(recent["score"], 0)
        self.assertIn("experience_recency", recent["breakdown"])
        # spark: mentioned only in older role -> lower than a skill used recently
        old = SR.skill_proficiency("spark", p)
        self.assertGreater(recent["score"], old["score"])

    def test_unknown_skill_zero(self):
        p = _profile()
        got = SR.skill_proficiency("cobol", p)
        self.assertEqual(got["score"], 0)
        self.assertEqual(got["breakdown"], {})

    def test_bounds(self):
        p = _profile()
        for s in SR.all_canonical_skills():
            sc = SR.skill_proficiency(s, p)["score"]
            self.assertTrue(0 <= sc <= 100, f"{s} out of bounds: {sc}")

    def test_all_proficiencies_nonzero_only(self):
        profs = SR.all_proficiencies(_profile())
        self.assertIn("python", profs)
        self.assertNotIn("cobol", profs)
        self.assertTrue(all(v["score"] > 0 for v in profs.values()))


class TestAxisCoverage(unittest.TestCase):
    def test_bounds_and_keys(self):
        cov = SR.axis_coverage(_profile())
        self.assertEqual(set(cov), set(SR.AXES))
        for axis, info in cov.items():
            self.assertTrue(0 <= info["score"] <= 100)
            self.assertLessEqual(len(info["top_skills"]), 3)
            self.assertGreaterEqual(info["n_skills"], len(info["top_skills"]))

    def test_diminishing_returns(self):
        # one perfect skill vs three strong skills: breadth should not
        # triple the score (diminishing returns), but depth alone < breadth
        solo = _profile(skills=["python"], experience=[],
                        headline="", summary="")
        cov_solo = SR.axis_coverage(solo)["Languages"]["score"]
        broad = _profile(skills=["python", "java", "golang"], experience=[],
                         headline="", summary="")
        cov_broad = SR.axis_coverage(broad)["Languages"]["score"]
        self.assertGreater(cov_broad, cov_solo)
        self.assertLess(cov_broad, cov_solo * 2)

    def test_empty_profile_zero(self):
        cov = SR.axis_coverage(_profile(skills=[], experience=[],
                                        headline="", summary=""))
        self.assertTrue(all(v["score"] == 0 for v in cov.values()))

    def test_radar_scores_shape(self):
        rs = SR.radar_scores(_profile())
        self.assertEqual(set(rs), set(SR.AXES))
        self.assertTrue(all(isinstance(v, int) for v in rs.values()))


class TestRoleTargets(unittest.TestCase):
    def test_list_targets(self):
        targets = SR.list_targets()
        self.assertGreaterEqual(len(targets), 8)
        names = {t["name"] for t in targets}
        self.assertIn("senior-swe", names)
        self.assertIn("staff-ml", names)
        self.assertIn("eng-manager", names)

    def test_load_builtin(self):
        t = SR.load_target("senior-ml")
        self.assertEqual(t["name"], "senior-ml")
        self.assertIn("ML & AI", t["axes"])

    def test_load_unknown_raises(self):
        with self.assertRaises(SR.SkillsRadarError):
            SR.load_target("ceo-of-the-moon")

    def test_load_custom_json(self):
        custom = {"label": "Custom", "blurb": "x",
                  "axes": {"Languages": 90}, "skills": {"rust": 80},
                  "weights": {"Languages": 2.0}}
        p = Path(_TMP) / "custom-target.json"
        p.write_text(json.dumps(custom), encoding="utf-8")
        t = SR.load_target(str(p))
        self.assertEqual(t["label"], "Custom")
        self.assertEqual(SR.target_axes_required(t)["Languages"], 90)
        self.assertEqual(SR.target_axis_weight(t, "Languages"), 2.0)
        # missing axis defaults to 0 required / 1.0 weight
        self.assertEqual(SR.target_axes_required(t)["ML & AI"], 0)
        self.assertEqual(SR.target_axis_weight(t, "ML & AI"), 1.0)

    def test_load_bad_json_raises(self):
        p = Path(_TMP) / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(SR.SkillsRadarError):
            SR.load_target(str(p))


class TestGapAnalysis(unittest.TestCase):
    def test_impact_ordering(self):
        g = SR.gap_analysis(_profile(), SR.load_target("staff-ml"))
        impacts = [r["impact"] for r in g["axes"]]
        self.assertEqual(impacts, sorted(impacts, reverse=True))
        self.assertGreater(g["summary"]["n_axis_gaps"], 0)

    def test_statuses(self):
        g = SR.gap_analysis(_profile(), SR.load_target("senior-swe"))
        statuses = {r["status"] for r in g["axes"]}
        self.assertTrue(statuses <= {"met", "near", "gap"})

    def test_readiness_full_when_met(self):
        # target with no requirements: everything met -> readiness 100
        t = {"name": "none", "label": "None", "axes": {}, "skills": {},
             "weights": {}}
        g = SR.gap_analysis(_profile(), t)
        self.assertEqual(g["summary"]["readiness"], 100)
        self.assertEqual(g["summary"]["n_axis_gaps"], 0)

    def test_skill_gaps_reference_axes(self):
        g = SR.gap_analysis(_profile(), SR.load_target("senior-ml"))
        skills = {r["skill"]: r for r in g["skills"]}
        self.assertIn("pytorch", skills)
        self.assertEqual(skills["pytorch"]["axis"], "ML & AI")


class TestPrioritize(unittest.TestCase):
    def test_prereqs_come_first(self):
        # pytorch gapped while python weak: python must be planned first
        p = _profile(skills=["machine learning"], experience=[],
                     headline="", summary="")
        plan = SR.prioritize_gaps(p, SR.load_target("senior-ml"))
        skills = [s["skill"] for s in plan]
        self.assertIn("pytorch", skills)
        self.assertIn("python", skills)
        self.assertLess(skills.index("python"), skills.index("pytorch"))

    def test_empty_when_no_gaps(self):
        t = {"name": "none", "label": "None", "axes": {}, "skills": {},
             "weights": {}}
        self.assertEqual(SR.prioritize_gaps(_profile(), t), [])

    def test_plan_shape(self):
        plan = SR.prioritize_gaps(_profile(), SR.load_target("staff-ml"),
                                  max_items=5)
        self.assertLessEqual(len(plan), 5)
        for step in plan:
            for key in ("skill", "axis", "gap", "hours", "demand",
                        "ratio", "prereqs", "why"):
                self.assertIn(key, step)
            self.assertGreater(step["gap"], 0)
            self.assertGreater(step["hours"], 0)

    def test_max_items_respected(self):
        plan = SR.prioritize_gaps(_profile(), SR.load_target("staff-ml"),
                                  max_items=2)
        self.assertLessEqual(len(plan), 2)


class TestRadarChart(unittest.TestCase):
    def test_glyphs_and_labels(self):
        cur = SR.radar_scores(_profile())
        tgt = SR.target_axes_required(SR.load_target("senior-swe"))
        chart = SR.render_ascii_radar(cur, tgt)
        self.assertIn("●", chart)
        self.assertIn("◇", chart)
        for axis in ("Languages", "ML & AI", "Leadership"):
            self.assertIn(axis.replace(" & ", "&")[:8], chart)
        self.assertIn("skills radar", chart)

    def test_without_target(self):
        chart = SR.render_ascii_radar(SR.radar_scores(_profile()))
        self.assertIn("●", chart)
        self.assertNotIn("◇", chart)

    def test_deterministic(self):
        cur = SR.radar_scores(_profile())
        self.assertEqual(SR.render_ascii_radar(cur), SR.render_ascii_radar(cur))

    def test_table_shape(self):
        tbl = SR.render_radar_table(SR.radar_scores(_profile()),
                                    SR.target_axes_required(
                                        SR.load_target("senior-swe")))
        self.assertIn("| axis | you | target | gap |", tbl)
        self.assertEqual(tbl.count("\n"), 9)  # header + sep + 8 axes


class TestEvidence(unittest.TestCase):
    def test_traces_to_entries(self):
        rows = SR.evidence_for_axis(_profile(), "Cloud & DevOps")
        self.assertGreater(len(rows), 0)
        r0 = rows[0]
        self.assertEqual(r0["company"], "Acme")
        self.assertIn("aws", r0["matched_skills"])

    def test_unknown_axis_raises(self):
        with self.assertRaises(SR.SkillsRadarError):
            SR.evidence_for_axis(_profile(), "Astrology")

    def test_summary_covers_all_axes(self):
        summ = SR.evidence_summary(_profile())
        self.assertEqual(set(summ), set(SR.AXES))


class TestSnapshots(unittest.TestCase):
    def test_snapshot_roundtrip(self):
        snap = SR.take_snapshot(_profile(), when="2026-01-01")
        self.assertEqual(snap["date"], "2026-01-01")
        self.assertIn("Languages", snap["axes"])
        snaps = SR.load_snapshots()
        self.assertTrue(any(s["date"] == "2026-01-01" for s in snaps))

    def test_same_date_replaces(self):
        SR.take_snapshot(_profile(skills=["python"]), when="2026-02-01")
        SR.take_snapshot(_profile(skills=["python", "sql"]), when="2026-02-01")
        snaps = [s for s in SR.load_snapshots() if s["date"] == "2026-02-01"]
        self.assertEqual(len(snaps), 1)
        self.assertIn("sql", snaps[0]["skills"])

    def test_trend_deltas(self):
        data = [
            {"date": "2026-03-01",
             "axes": {a: 10 for a in SR.AXES},
             "skills": {"python": 40}, "seniority": "mid"},
            {"date": "2026-04-01",
             "axes": {a: 10 for a in SR.AXES} | {"ML & AI": 30},
             "skills": {"python": 55, "pytorch": 20}, "seniority": "mid"},
        ]
        t = SR.trend(data)
        self.assertEqual(t["from"], "2026-03-01")
        self.assertEqual(t["to"], "2026-04-01")
        ml = next(r for r in t["axes"] if r["axis"] == "ML & AI")
        self.assertEqual(ml["delta"], 20)
        py = next(r for r in t["skills"] if r["skill"] == "python")
        self.assertEqual(py["delta"], 15)

    def test_trend_needs_two(self):
        self.assertEqual(SR.trend([{"date": "2026-01-01"}]), {})


class TestReport(unittest.TestCase):
    def test_report_shape(self):
        rep = SR.plan_report(_profile(), SR.load_target("senior-swe"))
        for key in ("radar_ascii", "radar_table", "current", "required",
                    "gaps", "plan", "evidence", "trend"):
            self.assertIn(key, rep)
        json.dumps(rep)  # must be JSON-serializable

    def test_markdown_sections(self):
        rep = SR.plan_report(_profile(), SR.load_target("senior-swe"))
        md = SR.report_markdown(rep)
        for section in ("## Radar", "## Top axis gaps",
                        "## Learning plan (prioritized)",
                        "## Evidence highlights", "Readiness:"):
            self.assertIn(section, md)
        self.assertTrue(md.startswith("# Skills radar:"))


if __name__ == "__main__":
    unittest.main()
