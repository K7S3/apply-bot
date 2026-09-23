"""Tests for candid.polish_intel.

Run: CANDID_DATA_DIR=/tmp/candid-test-polish python3 -m unittest tests.test_polish_intel -v

The library JSON is seeded directly via json.dump into a temp DATA_DIR
(pointed at per-test, so this file is safe under unittest discover too).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-polish")

from candid import polish_intel as PI  # noqa: E402


ORIG_FILLERY = (
    "Um, so, like, basically, you know, I was working on this thing, "
    "and, uh, it was kind of slow, and stuff, and I, like, fixed it, "
    "and it was, you know, pretty good, honestly."
)

POLISHED_STAR = (
    "Situation: the checkout page loaded in 6 seconds. "
    "Task: cut load time under 2 seconds. "
    "Action: I profiled the bundle, removed 3 unused libraries, and lazy-loaded images. "
    "Result: load time dropped to 1.4 seconds, a 77% improvement, "
    "and reduced bounce rate by 18%."
)

LEAD_ENTRY = {
    "id": "e1",
    "name": "checkout latency story",
    "question": "Describe a time you led a team through a crisis.",
    "original": ORIG_FILLERY,
    "polished": (
        "Situation: our checkout API latency had spiked to 900ms and the team was stuck. "
        "Task: as the on-call lead, I needed to bring p99 under 300ms before the holiday launch. "
        "Action: I ran a blameless triage, split the team into two workstreams, "
        "and I built a caching layer over the hot path. "
        "Result: we cut p99 latency to 220ms, a 75% improvement, "
        "and checkout conversion increased 12% in Q4."
    ),
    "status": "approved",
}

CONFLICT_ENTRY = {
    "id": "e2",
    "name": "db design disagreement",
    "question": "Tell me about a disagreement with a coworker.",
    "original": "There was a disagreement with a coworker about the design. "
                "It was difficult. We talked and resolved it.",
    "polished": (
        "Situation: a senior engineer and I disagreed on the database design "
        "for the billing service. "
        "Task: pick an approach without stalling the sprint. "
        "Action: I proposed a prototype spike for each option and we measured "
        "query latency together. "
        "Result: we aligned on the indexed approach, shipped on time, "
        "and the design review passed with no follow-ups."
    ),
    "status": "approved",
}

DRAFT_ENTRY = {
    "id": "e3",
    "name": "draft story",
    "question": "Tell me about leading a team.",
    "original": "draft original",
    "polished": "draft polished about leading a team through a crisis",
    "status": "draft",
}


class _IntelTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self._orig_data_dir = C.DATA_DIR
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-polish-intel-"))
        C.DATA_DIR = self.tmp

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self._orig_data_dir

    def seed(self, entries):
        path = self.tmp / PI.POLISH_LIBRARY_FILENAME
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path


class TagCompetenciesTest(_IntelTest):
    def test_basic_tags(self):
        text = ("I led the team through a blameless triage, debugged the root "
                "cause, and increased checkout conversion by 12%.")
        tags = PI.tag_competencies(text)
        self.assertEqual(tags, sorted(tags))
        for expected in ("leadership", "problem_solving", "results"):
            self.assertIn(expected, tags)

    def test_case_insensitive(self):
        self.assertIn("leadership", PI.tag_competencies("I LED the migration."))

    def test_short_keyword_needs_word_boundary(self):
        # "led" must not fire inside "profiled" / "loaded".
        tags = PI.tag_competencies(
            "I profiled the bundle and the page loaded faster.")
        self.assertNotIn("leadership", tags)

    def test_empty_text(self):
        self.assertEqual(PI.tag_competencies(""), [])

    def test_no_match(self):
        self.assertEqual(PI.tag_competencies("The weather was nice that day."), [])

    def test_rejects_non_string(self):
        with self.assertRaises(PI.IntelError):
            PI.tag_competencies(None)

    def test_deterministic(self):
        text = "I mentored two engineers and shipped the feature."
        self.assertEqual(PI.tag_competencies(text), PI.tag_competencies(text))


class PairWithQuestionTest(_IntelTest):
    def setUp(self):
        super().setUp()
        self.seed([LEAD_ENTRY, CONFLICT_ENTRY, DRAFT_ENTRY])

    def test_ranks_best_first(self):
        ranked = PI.pair_with_question(
            "Tell me about a time you led a team and had a disagreement about the design")
        self.assertGreaterEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["id"], "e1")
        self.assertEqual(ranked[1]["id"], "e2")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_row_shape_and_explanation(self):
        ranked = PI.pair_with_question("a time you led a team through a crisis")
        self.assertTrue(ranked)
        row = ranked[0]
        for key in ("id", "name", "score", "matched_keywords", "explanation"):
            self.assertIn(key, row)
        self.assertTrue(row["matched_keywords"])
        self.assertIn("keyword", row["explanation"].lower())
        self.assertIn("led", row["matched_keywords"])

    def test_defaults_to_approved_only(self):
        ranked = PI.pair_with_question("leading a team")
        ids = [r["id"] for r in ranked]
        self.assertIn("e1", ids)
        self.assertNotIn("e3", ids)  # draft entries are excluded by default

    def test_explicit_entries_override_default(self):
        ranked = PI.pair_with_question("leading a team", entries=[DRAFT_ENTRY])
        self.assertEqual([r["id"] for r in ranked], ["e3"])

    def test_no_overlap_returns_empty(self):
        self.assertEqual(
            PI.pair_with_question("Explain quantum entanglement in detail"), [])

    def test_empty_question_raises(self):
        with self.assertRaises(PI.IntelError):
            PI.pair_with_question("   ")

    def test_deterministic(self):
        q = "Tell me about a time you led a team and had a disagreement about the design"
        self.assertEqual(PI.pair_with_question(q), PI.pair_with_question(q))


class RubricScoreTest(_IntelTest):
    def test_shape_and_ranges(self):
        result = PI.rubric_score(ORIG_FILLERY, POLISHED_STAR)
        for dim in ("clarity", "structure", "specificity", "impact"):
            self.assertIn(dim, result)
            self.assertIsInstance(result[dim], int)
            self.assertGreaterEqual(result[dim], 1)
            self.assertLessEqual(result[dim], 5)
        self.assertIn("overall", result)
        self.assertIn("notes", result)
        self.assertEqual(len(result["notes"]), 4)
        self.assertTrue(all(isinstance(n, str) and n for n in result["notes"]))

    def test_overall_is_mean(self):
        result = PI.rubric_score(ORIG_FILLERY, POLISHED_STAR)
        mean = (result["clarity"] + result["structure"]
                + result["specificity"] + result["impact"]) / 4
        self.assertAlmostEqual(result["overall"], round(mean, 2))

    def test_polished_beats_original(self):
        polished = PI.rubric_score(ORIG_FILLERY, POLISHED_STAR)
        original = PI.rubric_score(ORIG_FILLERY, ORIG_FILLERY)
        self.assertGreater(polished["overall"], original["overall"])
        self.assertEqual(polished["structure"], 5)  # full STAR coverage
        self.assertLessEqual(original["clarity"], 3)  # filler-heavy, run-on

    def test_notes_describe_improvement_and_next_step(self):
        result = PI.rubric_score(ORIG_FILLERY, POLISHED_STAR)
        joined = "\n".join(result["notes"])
        self.assertIn("was", joined)  # delta vs original mentioned
        for note in result["notes"]:
            self.assertIn("Next:", note)

    def test_rejects_empty_text(self):
        with self.assertRaises(PI.IntelError):
            PI.rubric_score("", POLISHED_STAR)
        with self.assertRaises(PI.IntelError):
            PI.rubric_score(ORIG_FILLERY, "  ")

    def test_single_text_scoring(self):
        result = PI.rubric_score(POLISHED_STAR, POLISHED_STAR)
        self.assertIn("unchanged", "\n".join(result["notes"]))

    def test_count_fillers(self):
        self.assertEqual(PI.count_fillers(ORIG_FILLERY), 10)
        self.assertEqual(PI.count_fillers(POLISHED_STAR), 0)

    def test_deterministic(self):
        self.assertEqual(PI.rubric_score(ORIG_FILLERY, POLISHED_STAR),
                         PI.rubric_score(ORIG_FILLERY, POLISHED_STAR))


class BeforeAfterReportTest(_IntelTest):
    def test_aggregates(self):
        self.seed([LEAD_ENTRY, CONFLICT_ENTRY])
        report = PI.before_after_report()
        self.assertEqual(report["n_entries"], 2)
        self.assertGreater(report["total_fillers_removed"], 0)
        self.assertGreater(report["avg_rubric_delta"], 0)
        self.assertTrue(report["competency_coverage"])
        self.assertEqual(len(report["entries"]), 2)
        for pe in report["entries"]:
            for key in ("id", "name", "word_reduction_pct",
                        "fillers_removed", "rubric_delta"):
                self.assertIn(key, pe)

    def test_skips_entries_missing_a_version(self):
        entries = [LEAD_ENTRY,
                   {"id": "e9", "name": "half", "original": "x",
                    "polished": "", "status": "approved"}]
        self.seed(entries)
        report = PI.before_after_report()
        self.assertEqual(report["n_entries"], 1)

    def test_empty_library(self):
        report = PI.before_after_report()
        self.assertEqual(report["n_entries"], 0)
        self.assertEqual(report["avg_word_reduction_pct"], 0.0)
        self.assertEqual(report["total_fillers_removed"], 0)
        self.assertEqual(report["avg_rubric_delta"], 0.0)
        self.assertEqual(report["competency_coverage"], {})

    def test_avg_reduction_matches_recomputation(self):
        self.seed([LEAD_ENTRY, CONFLICT_ENTRY])
        report = PI.before_after_report()
        mean = sum(p["word_reduction_pct"] for p in report["entries"]) / 2
        self.assertAlmostEqual(report["avg_word_reduction_pct"],
                               round(mean, 1))


class FormatReportTest(_IntelTest):
    def test_readable_output(self):
        self.seed([LEAD_ENTRY, CONFLICT_ENTRY])
        text = PI.format_report(PI.before_after_report())
        for needle in ("Polish before/after report", "Entries analyzed: 2",
                       "word-count reduction", "fillers removed",
                       "rubric delta", "Competency coverage", "Per entry:"):
            self.assertIn(needle, text)

    def test_empty_report_renders(self):
        text = PI.format_report(PI.before_after_report())
        self.assertIn("Entries analyzed: 0", text)


class LibraryAccessTest(_IntelTest):
    def test_missing_file_yields_empty(self):
        self.assertEqual(PI.load_entries(), [])

    def test_bad_json_raises(self):
        (self.tmp / PI.POLISH_LIBRARY_FILENAME).write_text("{nope", encoding="utf-8")
        with self.assertRaises(PI.IntelError):
            PI.load_entries()

    def test_dict_wrapper_schema(self):
        self.seed([])  # list schema
        self.assertEqual(PI.load_entries(), [])
        path = self.tmp / PI.POLISH_LIBRARY_FILENAME
        path.write_text(json.dumps({"entries": [LEAD_ENTRY]}), encoding="utf-8")
        self.assertEqual(len(PI.load_entries()), 1)

    def test_status_filter(self):
        self.seed([LEAD_ENTRY, DRAFT_ENTRY])
        self.assertEqual(len(PI.load_entries()), 2)
        self.assertEqual(len(PI.load_entries(status="approved")), 1)

    def test_get_entry(self):
        self.seed([LEAD_ENTRY])
        self.assertEqual(PI.get_entry("e1")["name"], "checkout latency story")
        with self.assertRaises(PI.IntelError):
            PI.get_entry("missing")


if __name__ == "__main__":
    unittest.main()
