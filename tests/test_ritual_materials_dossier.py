"""Tests for the pre-interview ritual modules (ritual_materials, ritual_dossier).

Run: cd <worktree> && python -m unittest discover -s tests

CANDID_DATA_DIR is pointed at a fresh temp dir BEFORE any candid import.
The ritual modules resolve the data dir dynamically from the env on every
call, so per-test dirs work even under full-suite discovery.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

_TD = tempfile.mkdtemp(prefix="candid-ritual-test-")
os.environ["CANDID_DATA_DIR"] = _TD

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import ritual_materials as RM  # noqa: E402
from candid import ritual_dossier as RD  # noqa: E402

COMPANY = "Acme Corp"
ROLE = "Data Scientist"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


PROFILE = {
    "name": "Alex Rivera",
    "headline": "ML engineer shipping ranking systems",
    "seniority": "senior",
    "years_experience": 6,
    "summary": "Senior ML engineer focused on ads ranking and experimentation.",
    "skills": ["python", "machine learning", "sql", "llm", "statistics"],
    "experience": [
        {
            "title": "Senior ML Engineer",
            "company": "Meridian Financial",
            "dates": "2022 - present",
            "bullets": [
                "Improved ranking model AUC by 8% across 40M daily users.",
                "Led migration of training pipelines to Kubeflow.",
                "Mentored 3 junior engineers.",
            ],
        },
        {
            "title": "Data Scientist",
            "company": "Northwind",
            "dates": "2020 - 2022",
            "bullets": [
                "Built churn model that cut attrition by 12%.",
                "Automated weekly reporting dashboards.",
            ],
        },
    ],
    "education": [{"school": "State University", "degree": "MS Statistics",
                   "dates": "2018 - 2020"}],
}


class MaterialsTest(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("CANDID_DATA_DIR")
        self.td = Path(tempfile.mkdtemp(prefix="candid-ritual-"))
        os.environ["CANDID_DATA_DIR"] = str(self.td)
        self._seed()

    def tearDown(self):
        os.environ["CANDID_DATA_DIR"] = self._old

    def _seed(self):
        dd = self.td
        _write(dd / "profile.json", json.dumps(PROFILE))
        _write(dd / "tailored" / "acme-corp-data-scientist-resume-v1.md",
               "# Resume v1 (older)")
        _write(dd / "tailored" / "acme-corp-data-scientist-resume-v2.md",
               "# Resume v2 (newer)")
        _write(dd / "tailored" / "acme-corp-data-scientist-cover-letter.md",
               "Dear hiring manager...")
        _write(dd / "prep_packs" / "2026-09-20_acme_corp_data_scientist.md",
               "# Prep pack")
        r1 = dd / "debriefs" / "acme-corp-data-scientist-round1.md"
        r2 = dd / "debriefs" / "acme-corp-data-scientist-round2.md"
        _write(r1, "# Round 1 debrief")
        _write(r2, "# Round 2 debrief")
        os.utime(r1, (1000000000, 1000000000))
        os.utime(r2, (1000000001, 1000000001))
        _write(dd / "company_briefs" / "acme-corp-data-scientist.md",
               "# Acme Corp brief")
        _write(dd / "tracker.json", json.dumps([{
            "id": 1, "company": COMPANY, "role": ROLE,
            "status": "selected_for_interview",
            "notes": "Recruiter call went well. Ask about team size.",
        }]))

    def test_order_and_minutes(self):
        m = RM.build_materials(COMPANY, ROLE, ritual_id="r1")
        kinds = [i["kind"] for i in m["items"]]
        self.assertEqual(
            kinds,
            ["resume", "cover_letter", "prep_pack", "debrief", "debrief",
             "company_brief", "tracker_notes"])
        self.assertEqual([i["n"] for i in m["items"]],
                         [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(m["items"][0]["minutes"], 10)
        self.assertEqual(m["items"][2]["minutes"], 20)
        self.assertEqual(m["total_minutes"], 70)
        # newest resume variant wins
        self.assertTrue(m["items"][0]["path"].endswith("resume-v2.md"))
        # debriefs oldest round first
        self.assertIn("round1", m["items"][3]["path"])
        self.assertIn("round2", m["items"][4]["path"])

    def test_persists_and_loads(self):
        RM.build_materials(COMPANY, ROLE, ritual_id="r2")
        p = self.td / "rituals" / "r2" / "materials.json"
        self.assertTrue(p.is_file())
        loaded = RM.load_materials("r2")
        self.assertEqual(loaded["ritual_id"], "r2")
        self.assertEqual(loaded["company"], COMPANY)
        self.assertIsNone(RM.load_materials("nope"))

    def test_check_and_uncheck(self):
        RM.build_materials(COMPANY, ROLE, ritual_id="r3")
        item = RM.check_item("r3", 2)
        self.assertTrue(item["reviewed"])
        self.assertTrue(RM.load_materials("r3")["items"][1]["reviewed"])
        item = RM.uncheck_item("r3", 2)
        self.assertFalse(item["reviewed"])
        with self.assertRaises(RM.RitualError):
            RM.check_item("r3", 99)
        with self.assertRaises(RM.RitualError):
            RM.check_item("missing", 1)

    def test_render_shows_progress_and_total(self):
        m = RM.build_materials(COMPANY, ROLE, ritual_id="r4")
        RM.check_item("r4", 1)
        out = RM.render_materials(RM.load_materials("r4"))
        self.assertIn("1/7 reviewed", out)
        self.assertIn("[x] 1.", out)
        self.assertIn("[ ] 2.", out)
        self.assertIn("~70 minutes", out)
        self.assertIn("~10 min", out)
        self.assertIn("ritual-id r4", out)
        self.assertNotIn("\N{EM DASH}", out)

    def test_missing_everything_is_defensive(self):
        empty = Path(tempfile.mkdtemp(prefix="candid-ritual-empty-"))
        os.environ["CANDID_DATA_DIR"] = str(empty)
        m = RM.build_materials(COMPANY, ROLE, ritual_id="r5")
        self.assertEqual(m["items"], [])
        self.assertEqual(m["total_minutes"], 0)
        self.assertGreater(len(m["notes"]), 0)
        out = RM.render_materials(m)
        self.assertIn("0/0 reviewed", out)

    def test_requires_company_and_role(self):
        with self.assertRaises(RM.RitualError):
            RM.build_materials("", ROLE)
        with self.assertRaises(RM.RitualError):
            RM.build_materials(COMPANY, "")

    def test_notes_only_included_when_present(self):
        td = Path(tempfile.mkdtemp(prefix="candid-ritual-nonotes-"))
        os.environ["CANDID_DATA_DIR"] = str(td)
        _write(td / "tailored" / "acme-corp-data-scientist-resume.md",
               "# Resume")
        _write(td / "tracker.json", json.dumps([{
            "id": 1, "company": COMPANY, "role": ROLE, "status": "saved",
            "notes": "",
        }]))
        m = RM.build_materials(COMPANY, ROLE, ritual_id="r6")
        kinds = [i["kind"] for i in m["items"]]
        self.assertEqual(kinds, ["resume"])
        self.assertTrue(any("tracker notes" in n for n in m["notes"]))


class DossierTest(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("CANDID_DATA_DIR")
        self.td = Path(tempfile.mkdtemp(prefix="candid-dossier-"))
        os.environ["CANDID_DATA_DIR"] = str(self.td)

    def tearDown(self):
        os.environ["CANDID_DATA_DIR"] = self._old

    def test_dossier_grounded_in_profile(self):
        _write(self.td / "profile.json", json.dumps(PROFILE))
        out = RD.build_dossier(COMPANY, ROLE)
        self.assertIn("Alex Rivera", out)
        self.assertIn("senior", out)
        self.assertIn("python", out)
        self.assertIn("Meridian Financial", out)
        self.assertIn("Improved ranking model AUC by 8%", out)
        self.assertNotIn("\N{EM DASH}", out)

    def test_top_bullets_prefer_metrics(self):
        _write(self.td / "profile.json", json.dumps(PROFILE))
        bullets = RD.top_resume_bullets(PROFILE, limit=3)
        self.assertEqual(len(bullets), 3)
        texts = [b for _, b in bullets]
        self.assertTrue(any("8%" in b for b in texts))
        self.assertTrue(any("12%" in b for b in texts))
        # unquantified bullets fall out of the top 3
        self.assertFalse(any("Automated weekly" in b for b in texts))

    def test_no_profile_suggests_onboard(self):
        out = RD.build_dossier(COMPANY, ROLE)
        self.assertIn("No profile found", out)
        self.assertIn("onboard", out)
        self.assertNotIn("Alex Rivera", out)

    def test_match_highlights_use_real_stored_data(self):
        _write(self.td / "profile.json", json.dumps(PROFILE))
        _write(self.td / "matches.json", json.dumps([{
            "company": COMPANY, "role": ROLE, "score": 82,
            "date": "2026-09-21",
            "strengths": ["Deep ranking systems experience",
                          "Strong experimentation background"],
        }]))
        out = RD.build_dossier(COMPANY, ROLE)
        self.assertIn("82/100", out)
        self.assertIn("Deep ranking systems experience", out)

    def test_no_match_run_no_crash_no_invention(self):
        _write(self.td / "profile.json", json.dumps(PROFILE))
        out = RD.build_dossier(COMPANY, ROLE)
        self.assertIn("No stored match run", out)
        self.assertNotIn("/100", out)

    def test_other_company_match_not_used(self):
        _write(self.td / "profile.json", json.dumps(PROFILE))
        _write(self.td / "matches.json", json.dumps([{
            "company": "Other Corp", "role": ROLE, "score": 95,
            "strengths": ["Unrelated strength"],
        }]))
        out = RD.build_dossier(COMPANY, ROLE)
        self.assertNotIn("95/100", out)
        self.assertNotIn("Unrelated strength", out)


if __name__ == "__main__":
    unittest.main()
