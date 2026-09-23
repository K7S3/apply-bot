"""Tests for candid.em_tailor (EM resume reframe).

Covers: scope-signal extraction from profile text, missing-scope gap flags,
the never-invent guarantee (no fabricated team sizes / hiring numbers),
EM-relevant bullet promotion, and the `candid em reframe` CLI path.

Run: CANDID_DATA_DIR=/tmp/candid-test-em-tailor python3 -m pytest tests/test_em_tailor.py -q
"""
import json
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-em-tailor"

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import em_tailor as E  # noqa: E402
from candid import __main__ as CLI  # noqa: E402


def _em_profile(**kw):
    prof = {
        "name": "Jordan Lee",
        "headline": "Engineering Manager",
        "location": "New York, NY",
        "summary": "",
        "seniority": "lead",
        "years_experience": 8.0,
        "skills": ["python", "leadership"],
        "experience": [
            {"title": "Engineering Manager", "company": "Acme",
             "dates": "2022 - Present",
             "bullets": [
                 "Led a team of 8 engineers shipping the payments platform",
                 "Hired 6 engineers in 18 months",
                 "Partnered with 3 product teams to align the roadmap",
                 "Mentored 4 engineers; 2 promoted to senior",
                 "Wrote Python services for billing",
             ]},
            {"title": "Senior Software Engineer", "company": "Beta",
             "dates": "2018 - 2022",
             "bullets": [
                 "Built microservices in Python",
                 "Mentored 2 interns on testing",
             ]},
        ],
        "education": [],
        "source_files": [],
    }
    prof.update(kw)
    return prof


def _ic_profile():
    return _em_profile(experience=[
        {"title": "Software Engineer", "company": "Gamma",
         "dates": "2020 - Present",
         "bullets": ["Wrote backend code in Python", "Fixed production bugs"]},
    ])


def _signals_by_kind(signals, kind):
    return [s for s in signals if s["kind"] == kind]


class ScopeExtractionTest(unittest.TestCase):
    def test_team_size_extracted_with_source_quote(self):
        sigs = E.extract_scope_signals(_em_profile())
        team = _signals_by_kind(sigs, "team_size")
        self.assertEqual(len(team), 1)  # "team of 8" is one fact, not two
        self.assertEqual(team[0]["value"], 8)
        self.assertIn("team of 8", team[0]["text"])
        self.assertEqual(team[0]["role"], "Acme")

    def test_hiring_extracted(self):
        sigs = E.extract_scope_signals(_em_profile())
        hiring = _signals_by_kind(sigs, "hiring")
        self.assertEqual([s["value"] for s in hiring], [6])

    def test_mentoring_extracted_across_roles(self):
        sigs = E.extract_scope_signals(_em_profile())
        mentoring = sorted(s["value"] for s in _signals_by_kind(sigs, "mentoring"))
        self.assertEqual(mentoring, [2, 4])

    def test_cross_team_and_delivery_signals(self):
        sigs = E.extract_scope_signals(_em_profile())
        facts = E.scope_facts(sigs)
        self.assertTrue(facts["has_cross_team_signal"])
        self.assertTrue(facts["has_delivery_signal"])
        self.assertEqual(facts["max_team_size"], 8)

    def test_grew_team_from_to(self):
        prof = _em_profile(experience=[
            {"title": "Engineering Manager", "company": "Acme", "dates": "",
             "bullets": ["Grew the team from 3 to 10 engineers"]},
        ])
        sigs = E.extract_scope_signals(prof)
        hiring = _signals_by_kind(sigs, "hiring")
        self.assertEqual([s["value"] for s in hiring], [10])

    def test_every_signal_carries_its_source(self):
        for s in E.extract_scope_signals(_em_profile()):
            self.assertTrue(s["text"], "signal without source quote")
            self.assertTrue(s["role"], "signal without role attribution")


class MissingScopeFlagsTest(unittest.TestCase):
    def test_full_gap_list_for_scope_less_profile(self):
        prof = _ic_profile()
        gaps = E.missing_scope_flags(prof, E.extract_scope_signals(prof))
        joined = " ".join(gaps)
        self.assertIn("Team size: not stated", joined)
        self.assertIn("Hiring:", joined)
        self.assertIn("Mentoring:", joined)
        self.assertIn("Cross-team impact:", joined)
        self.assertIn("Delivery ownership:", joined)

    def test_no_gaps_when_scope_is_stated(self):
        prof = _em_profile()
        gaps = E.missing_scope_flags(prof, E.extract_scope_signals(prof))
        self.assertEqual(gaps, [])

    def test_ic_track_note_not_management_claim(self):
        gaps = E.missing_scope_flags(_ic_profile(),
                                     E.extract_scope_signals(_ic_profile()))
        track = [g for g in gaps if g.startswith("Track signal:")]
        self.assertEqual(len(track), 1)
        self.assertIn("individual-contributor track", track[0])
        self.assertIn("rather than claiming management", track[0])

    def test_no_track_note_for_manager_titles(self):
        prof = _em_profile()
        gaps = E.missing_scope_flags(prof, E.extract_scope_signals(prof))
        self.assertFalse(any(g.startswith("Track signal:") for g in gaps))


class NeverInventTest(unittest.TestCase):
    def test_summary_invents_nothing_for_thin_profile(self):
        result = E.build_reframe(_ic_profile())
        self.assertIn("No management-scope signals", result["summary"])
        self.assertIn("Nothing here is inferred", result["summary"])
        self.assertNotIn("led teams of up to", result["summary"])

    def test_summary_only_uses_stated_numbers(self):
        import re
        result = E.build_reframe(_em_profile())
        self.assertIn("up to 8", result["summary"])
        # the only headcounts in the summary are the ones stated in the
        # profile (8 = team size, 6 = hires, 2/4 = mentoring; 8.0 = years)
        nums = sorted({int(float(n)) for n in
                       re.findall(r"\d+(?:\.\d+)?", result["summary"])})
        self.assertEqual(nums, [2, 4, 6, 8])

    def test_gap_advice_never_supplies_a_number(self):
        import re
        for g in E.build_reframe(_ic_profile())["gaps"]:
            self.assertFalse(re.search(r"\d+", g),
                             f"gap flag contains a number: {g}")


class BulletPromotionTest(unittest.TestCase):
    def test_leadership_bullets_promoted(self):
        result = E.build_reframe(_em_profile())
        promoted = result["roles"][0]["promoted_bullets"]
        self.assertEqual(len(promoted), 3)
        # the three leadership bullets win; the pure-IC bullet sinks out
        self.assertIn("Led a team of 8 engineers shipping the payments platform",
                      promoted)
        self.assertIn("Hired 6 engineers in 18 months", promoted)
        self.assertIn("Partnered with 3 product teams to align the roadmap",
                      promoted)
        self.assertNotIn("Wrote Python services for billing", promoted)

    def test_per_role_gaps(self):
        result = E.build_reframe(_em_profile())
        beta = result["roles"][1]
        self.assertIn("team size not stated for this role", beta["gaps"])
        self.assertIn("hiring not evidenced for this role", beta["gaps"])
        acme = result["roles"][0]
        self.assertEqual(acme["gaps"], [])

    def test_result_is_json_serializable(self):
        json.dumps(E.build_reframe(_em_profile()))
        json.dumps(E.build_reframe(_ic_profile()))


class RenderTest(unittest.TestCase):
    def test_render_sections(self):
        text = E.render_reframe(E.build_reframe(_em_profile()))
        for section in ("SCOPE SIGNALS FOUND", "WHAT IS MISSING",
                        "ROLE-BY-ROLE REFRAME", "EM SUMMARY DRAFT"):
            self.assertIn(section, text)
        self.assertIn("team_size: 8", text)

    def test_render_honest_when_empty(self):
        text = E.render_reframe(E.build_reframe(_ic_profile()))
        self.assertIn("(none - every scope dimension below is a gap)", text)


class EmReframeCLITest(unittest.TestCase):
    def test_parser_accepts_em_reframe(self):
        args = CLI.build_parser().parse_args(["em", "reframe"])
        self.assertEqual(args.what, "reframe")
        self.assertFalse(args.json)
        args = CLI.build_parser().parse_args(["em", "reframe", "--json"])
        self.assertTrue(args.json)

    def test_cmd_em_reframe_end_to_end(self):
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(CLI, "_profile", return_value=_em_profile()):
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI.cmd_em(Namespace(what="reframe", json=False))
            out = buf.getvalue()
        self.assertIn("EM REFRAME", out)
        self.assertIn("team_size: 8", out)

    def test_cmd_em_reframe_json(self):
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(CLI, "_profile", return_value=_em_profile()):
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI.cmd_em(Namespace(what="reframe", json=True))
            result = json.loads(buf.getvalue())
        self.assertEqual(result["scope_facts"]["max_team_size"], 8)


if __name__ == "__main__":
    unittest.main()
