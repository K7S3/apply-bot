"""Tests for the culture decoder (interview-process transparency + prep hook).

Run: python -m pytest tests/test_culture_process.py -q
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import culture_process as cp


def _ctx(**kwargs):
    return kwargs


class ProcessProfileStagesTest(unittest.TestCase):
    def test_recruiter_screen_detected(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-01",
            "text": "Kicked off with a 30 minute recruiter screen. "
                    "She asked about my background and comp expectations.",
        }])
        profile = cp.process_profile("Acme", ctx)
        self.assertEqual(profile["company"], "Acme")
        stage_names = [s["stage"] for s in profile["stages"]]
        self.assertIn("recruiter screen", stage_names)

    def test_phone_screen_detected(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-02",
            "text": "Then a 45 minute technical phone screen with two "
                    "coding questions on arrays.",
        }])
        stages = {s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]}
        self.assertIn("technical phone screen", stages)

    def test_hiring_manager_detected(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme",
            "text": "After the screen I met the hiring manager for a "
                    "deep dive on my past projects.",
        }])
        stages = {s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]}
        self.assertIn("hiring manager", stages)

    def test_take_home_detected(self):
        ctx = _ctx(tracker=[{
            "company": "Acme", "status": "take-home sent",
            "notes": "They sent a take-home assignment, due in 48 hours.",
        }])
        stages = {s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]}
        self.assertIn("take-home", stages)

    def test_onsite_detected(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-10",
            "text": "Final round was a virtual onsite: four 45 minute "
                    "interviews back to back.",
        }])
        stages = {s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]}
        self.assertIn("onsite", stages)

    def test_multiple_stages_from_one_debrief(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-01",
            "text": "First a recruiter screen. Then a technical phone "
                    "screen with live coding. The onsite had four rounds.",
        }])
        stages = [s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]]
        self.assertEqual(
            stages, ["recruiter screen", "technical phone screen", "onsite"])

    def test_stages_in_canonical_order_regardless_of_evidence_order(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme",
            "text": "The onsite was intense. Before that, just a quick "
                    "recruiter screen to set it up.",
        }])
        stages = [s["stage"] for s in cp.process_profile("Acme", ctx)["stages"]]
        self.assertEqual(stages, ["recruiter screen", "onsite"])

    def test_matching_is_case_insensitive(self):
        ctx = _ctx(debriefs=[{
            "company": "ACME", "text": "RECRUITER SCREEN went well.",
        }])
        profile = cp.process_profile("acme", ctx)
        self.assertEqual([s["stage"] for s in profile["stages"]],
                         ["recruiter screen"])

    def test_no_stage_keywords_means_no_stages_but_no_crash(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme",
            "text": "Nice office, friendly people, free lunch.",
        }])
        profile = cp.process_profile("Acme", ctx)
        self.assertEqual(profile["stages"], [])
        self.assertEqual(profile["note"],
                         "no verified interview-process data for Acme")


class ProcessProfileEvidenceTest(unittest.TestCase):
    def test_quote_is_verbatim_substring(self):
        text = ("Started with a recruiter screen. She asked about salary. "
                "Then an onsite with system design.")
        ctx = _ctx(debriefs=[{"company": "Acme", "date": "2026-08-01",
                              "text": text}])
        profile = cp.process_profile("Acme", ctx)
        for stage in profile["stages"]:
            for item in stage["evidence"]:
                self.assertIn(item["quote"], text,
                              f"quote not verbatim: {item['quote']!r}")

    def test_debrief_source_labeled_with_date(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-01",
            "text": "Had a recruiter screen today.",
        }])
        profile = cp.process_profile("Acme", ctx)
        sources = {i["source"] for s in profile["stages"] for i in s["evidence"]}
        self.assertEqual(sources, {"interview debrief 2026-08-01"})

    def test_debrief_source_without_date(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "text": "Had a recruiter screen today.",
        }])
        profile = cp.process_profile("Acme", ctx)
        sources = {i["source"] for s in profile["stages"] for i in s["evidence"]}
        self.assertEqual(sources, {"interview debrief"})

    def test_prep_bank_source_label(self):
        ctx = _ctx(prep_bank=[{
            "company": "Acme",
            "question": "Onsite: design a URL shortener.",
        }])
        profile = cp.process_profile("Acme", ctx)
        sources = {i["source"] for s in profile["stages"] for i in s["evidence"]}
        self.assertEqual(sources, {"prep question bank"})

    def test_tracker_source_label(self):
        ctx = _ctx(tracker=[{
            "company": "Acme", "status": "screen",
            "notes": "Recruiter screen scheduled for Friday.",
        }])
        profile = cp.process_profile("Acme", ctx)
        sources = {i["source"] for s in profile["stages"] for i in s["evidence"]}
        self.assertEqual(sources, {"tracker note"})

    def test_coverage_counts_per_source(self):
        ctx = _ctx(
            debriefs=[
                {"company": "Acme", "date": "2026-08-01",
                 "text": "Recruiter screen done. Onsite next week."},
            ],
            tracker=[{"company": "Acme", "status": "screen",
                      "notes": "Phone screen passed."}],
        )
        profile = cp.process_profile("Acme", ctx)
        self.assertEqual(profile["coverage"],
                         {"interview debrief 2026-08-01": 2,
                          "tracker note": 1})

    def test_other_companies_ignored(self):
        ctx = _ctx(debriefs=[
            {"company": "Globex", "date": "2026-08-01",
             "text": "Recruiter screen at Globex."},
        ])
        profile = cp.process_profile("Acme", ctx)
        self.assertEqual(profile["stages"], [])
        self.assertEqual(profile["coverage"], {})
        self.assertEqual(profile["note"],
                         "no verified interview-process data for Acme")

    def test_missing_ctx_keys_treated_as_empty(self):
        self.assertEqual(cp.process_profile("Acme", {})["stages"], [])
        self.assertEqual(cp.process_profile("Acme")["stages"], [])
        self.assertEqual(cp.process_profile("Acme", None)["stages"], [])

    def test_evidence_shape(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-01",
            "text": "Recruiter screen went fine.",
        }])
        profile = cp.process_profile("Acme", ctx)
        stage = profile["stages"][0]
        self.assertEqual(set(stage.keys()), {"stage", "evidence"})
        item = stage["evidence"][0]
        self.assertEqual(set(item.keys()), {"quote", "source"})
        self.assertEqual(set(profile.keys()),
                         {"company", "stages", "coverage", "note"})

    def test_note_summarizes_when_evidence_exists(self):
        ctx = _ctx(debriefs=[{
            "company": "Acme", "date": "2026-08-01",
            "text": "Recruiter screen done. Onsite next week.",
        }])
        note = cp.process_profile("Acme", ctx)["note"]
        self.assertNotIn("no verified", note)
        self.assertIn("2", note)


class AttachCultureHookTest(unittest.TestCase):
    def _pack(self):
        return {
            "company": "Acme",
            "role": "Data Scientist",
            "ctx": _ctx(debriefs=[{
                "company": "Acme", "date": "2026-08-01",
                "text": "Recruiter screen went fine.",
            }]),
        }

    def test_hook_adds_culture_key(self):
        enriched = cp.attach_culture_to_prep("Acme", self._pack())
        self.assertIn("culture", enriched)
        self.assertEqual(set(enriched["culture"].keys()),
                         {"process", "values"})

    def test_hook_does_not_mutate_input(self):
        pack = self._pack()
        before = dict(pack)
        enriched = cp.attach_culture_to_prep("Acme", pack)
        self.assertNotIn("culture", pack)
        self.assertEqual(pack, before)
        self.assertIsNot(enriched, pack)

    def test_hook_returns_pack_plus_culture(self):
        pack = self._pack()
        enriched = cp.attach_culture_to_prep("Acme", pack)
        for key, value in pack.items():
            self.assertEqual(enriched[key], value)

    def test_hook_process_uses_pack_ctx(self):
        enriched = cp.attach_culture_to_prep("Acme", self._pack())
        process = enriched["culture"]["process"]
        self.assertEqual(process["company"], "Acme")
        self.assertEqual([s["stage"] for s in process["stages"]],
                         ["recruiter screen"])

    def test_hook_values_fallback_to_empty_list(self):
        # candid.culture_values does not exist in this tree.
        enriched = cp.attach_culture_to_prep("Acme", self._pack())
        self.assertEqual(enriched["culture"]["values"], [])

    def test_hook_pack_without_ctx(self):
        enriched = cp.attach_culture_to_prep("Acme", {"company": "Acme"})
        self.assertEqual(enriched["culture"]["process"]["stages"], [])
        self.assertEqual(enriched["culture"]["process"]["note"],
                         "no verified interview-process data for Acme")

    def test_hook_rejects_non_dict_pack(self):
        with self.assertRaises(TypeError):
            cp.attach_culture_to_prep("Acme", ["not", "a", "dict"])


if __name__ == "__main__":
    unittest.main()
