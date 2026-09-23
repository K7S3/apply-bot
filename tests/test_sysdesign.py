"""Tests for the system design fundamentals library (batch-36).

Covers: topic library, deep-dives, trade-off cards, practice drills,
back-of-envelope estimator, checklist, flashcards, study plans,
gap-to-topic mapping, prep-pack integration, and the sysdesign CLI.

Run: CANDID_DATA_DIR=/tmp/candid-test-sysdesign python -m unittest discover -s tests
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-sysdesign")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import sysdesign as S  # noqa: E402


def _run_cli(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        CLI.main(list(argv))
    return buf.getvalue()


class TopicLibraryTest(unittest.TestCase):
    def test_ten_topics_core_first(self):
        topics = S.list_topics()
        self.assertEqual(len(topics), 10)
        self.assertEqual([t["id"] for t in topics[:5]], S.CORE_TOPICS)

    def test_topic_fields(self):
        for t in S.list_topics():
            full = S.get_topic(t["id"])
            for field in ("title", "overview", "patterns", "numbers", "one_liner"):
                self.assertIn(field, full, f"{t['id']} missing {field}")
            self.assertGreaterEqual(len(full["patterns"]), 3)
            self.assertGreaterEqual(len(full["numbers"]), 2)

    def test_topic_id_normalization(self):
        self.assertEqual(S.get_topic("Load-Balancing")["title"], "Load Balancing")

    def test_unknown_topic(self):
        with self.assertRaises(S.SysdesignError):
            S.get_topic("blockchain")


class DeepDiveTest(unittest.TestCase):
    def test_five_deep_dives_with_structure(self):
        for tid in S.CORE_TOPICS:
            md = S.deep_dive(tid)
            for section in ("60 seconds", "Worked example", "How to answer",
                            "Follow-ups to expect"):
                self.assertIn(section, md, f"{tid} missing '{section}'")
            # each deep-dive points at its drills
            self.assertIn(f"sysdesign drill --topic {tid}", md)

    def test_unknown_deep_dive(self):
        with self.assertRaises(S.SysdesignError):
            S.deep_dive("rate_limiting")


class TradeoffCardTest(unittest.TestCase):
    def test_card_structure_every_topic(self):
        for t in S.list_topics():
            cards = S.tradeoff_cards(t["id"])
            self.assertGreaterEqual(len(cards), 2, t["id"])
            for card in cards:
                self.assertIn("decision", card)
                self.assertIn("rule", card)
                self.assertGreaterEqual(len(card["options"]), 2)
                for opt in card["options"]:
                    for field in ("name", "when", "pros", "cons"):
                        self.assertIn(field, opt)
                    self.assertGreaterEqual(len(opt["pros"]), 1)
                    self.assertGreaterEqual(len(opt["cons"]), 1)

    def test_render_contains_decisions(self):
        out = S.render_tradeoffs("caching")
        self.assertIn("How do writes reach the cache?", out)
        self.assertIn("Rule of thumb", out)

    def test_unknown_cards(self):
        with self.assertRaises(S.SysdesignError):
            S.tradeoff_cards("nope")


class DrillTest(unittest.TestCase):
    def test_drill_structure_every_topic(self):
        for t in S.list_topics():
            drills = S.practice_prompts(t["id"])
            self.assertGreaterEqual(len(drills), 2, t["id"])
            for d in drills:
                for field in ("prompt", "level", "self_check", "followups"):
                    self.assertIn(field, d)
                self.assertIn(d["level"], ("easy", "medium", "hard"))
                self.assertGreaterEqual(len(d["self_check"]), 3)

    def test_level_filter(self):
        hard = S.practice_prompts("consistency", level="hard")
        self.assertTrue(hard)
        self.assertTrue(all(d["level"] == "hard" for d in hard))
        easy = S.practice_prompts("caching", level="easy")
        self.assertTrue(all(d["level"] == "easy" for d in easy))

    def test_bad_level(self):
        with self.assertRaises(S.SysdesignError):
            S.practice_prompts("caching", level="brutal")

    def test_render_drill(self):
        out = S.render_drill("queues", "easy")
        self.assertIn("Self-check", out)
        self.assertIn("Follow-ups to expect", out)


class EstimatorTest(unittest.TestCase):
    def test_exact_math(self):
        # 100 writes/sec * 86400 s * 30 d * 1 KB * 3 replicas * 1.0 overhead
        res = S.estimate(qps=1000, read_ratio=0.9, payload_kb=1.0,
                         retention_days=30, replication=3, overhead=1.0)
        self.assertAlmostEqual(res["write_qps"], 100.0, delta=1e-6)
        self.assertAlmostEqual(res["requests_per_day"], 86_400_000.0, delta=1.0)
        self.assertAlmostEqual(res["storage_bytes"], 100 * 86400 * 30 * 1024 * 3,
                               delta=1.0)
        self.assertAlmostEqual(res["read_bandwidth_bps"], 900 * 1024, delta=1.0)
        self.assertAlmostEqual(res["write_bandwidth_bps"], 100 * 1024, delta=1.0)
        self.assertTrue(any("741.6 GB" in line for line in res["lines"]))

    def test_dau_path(self):
        res = S.estimate(daily_active_users=86400, requests_per_user_per_day=10)
        self.assertAlmostEqual(res["qps"], 10.0)

    def test_bad_inputs(self):
        with self.assertRaises(S.SysdesignError):
            S.estimate()
        with self.assertRaises(S.SysdesignError):
            S.estimate(qps=-5)
        with self.assertRaises(S.SysdesignError):
            S.estimate(qps=10, read_ratio=1.5)
        with self.assertRaises(S.SysdesignError):
            S.estimate(qps=10, replication=0)

    def test_jsonable(self):
        res = S.estimate(qps=10)
        json.dumps(S.to_jsonable(res))  # must not raise


class ChecklistFlashcardPlanTest(unittest.TestCase):
    def test_checklist_phases(self):
        md = S.checklist()
        for phase in ("Clarify requirements", "Back-of-envelope", "API design",
                      "Data model", "High-level design", "Deep dive",
                      "Bottlenecks"):
            self.assertIn(phase, md)

    def test_flashcards_count_and_determinism(self):
        a = S.flashcards("sharding", n=4, seed=7)
        b = S.flashcards("sharding", n=4, seed=7)
        c = S.flashcards("sharding", n=4, seed=8)
        self.assertEqual(len(a), 4)
        self.assertEqual(a, b)
        self.assertNotEqual([x["q"] for x in a], [x["q"] for x in c])
        for card in a:
            self.assertIn("q", card)
            self.assertIn("a", card)

    def test_flashcards_bad_n(self):
        with self.assertRaises(S.SysdesignError):
            S.flashcards("caching", n=0)

    def test_study_plan_order(self):
        steps = S.study_plan("caching")
        text = "\n".join(steps)
        self.assertLess(text.index("deep-dive"), text.index("tradeoffs"))
        self.assertLess(text.index("tradeoffs"), text.index("drill --topic"))
        self.assertLess(text.index("flashcards"), text.index("mock design"))
        # non-core topic skips the deep-dive step
        plan = S.render_study_plan("rate_limiting")
        self.assertNotIn("deep-dive", plan)
        self.assertIn("mock design", plan)


class GapMappingTest(unittest.TestCase):
    def test_keyword_mapping(self):
        topics = S.topics_for_gaps(["Missing must-have skill: caching with Redis",
                                    "Need Kafka experience"])
        self.assertIn("caching", topics)
        self.assertIn("queues", topics)

    def test_dedup_and_empty(self):
        topics = S.topics_for_gaps(["caching", "more caching"])
        self.assertEqual(topics, ["caching"])
        self.assertEqual(S.topics_for_gaps([]), [])
        self.assertEqual(S.topics_for_gaps(None), [])


class PrepIntegrationTest(unittest.TestCase):
    def test_pack_includes_fundamentals_on_sysdesign_gap(self):
        import tempfile
        from candid import config as C
        from candid import prep as P
        prof = {"name": "T", "skills": [], "experience": [], "education": []}
        with tempfile.TemporaryDirectory() as td:
            orig = C.PREP_PACKS_DIR
            C.PREP_PACKS_DIR = Path(td)
            try:
                md, _ = P.build_pack(prof, "Acme", "Backend Engineer",
                                    gaps=["Missing must-have skill: distributed caching"])
            finally:
                C.PREP_PACKS_DIR = orig
        self.assertIn("### System design fundamentals", md)
        self.assertIn("**Caching**", md)
        self.assertIn("sysdesign deep-dive", md)

    def test_pack_omits_fundamentals_without_sysdesign(self):
        import tempfile
        from candid import config as C
        from candid import prep as P
        prof = {"name": "T", "skills": [], "experience": [], "education": []}
        with tempfile.TemporaryDirectory() as td:
            orig = C.PREP_PACKS_DIR
            C.PREP_PACKS_DIR = Path(td)
            try:
                md, _ = P.build_pack(prof, "Acme", "Data Analyst",
                                    gaps=["Missing must-have skill: sql"])
            finally:
                C.PREP_PACKS_DIR = orig
        self.assertNotIn("### System design fundamentals", md)


class SysdesignCLITest(unittest.TestCase):
    def test_list(self):
        out = _run_cli("sysdesign", "list")
        self.assertIn("caching", out)
        self.assertIn("load_balancing", out)

    def test_list_json(self):
        out = _run_cli("sysdesign", "list", "--json")
        data = json.loads(out)
        self.assertEqual(len(data), 10)

    def test_show(self):
        out = _run_cli("sysdesign", "show", "--topic", "queues")
        self.assertIn("Message Queues", out)
        self.assertIn("Interview one-liner", out)

    def test_deep_dive(self):
        out = _run_cli("sysdesign", "deep-dive", "--topic", "sharding")
        self.assertIn("Shard", out)
        self.assertIn("How to answer", out)

    def test_tradeoffs(self):
        out = _run_cli("sysdesign", "tradeoffs", "--topic", "consistency")
        self.assertIn("Rule of thumb", out)
        data = json.loads(_run_cli("sysdesign", "tradeoffs", "--topic",
                                   "consistency", "--json"))
        self.assertTrue(data)

    def test_drill(self):
        out = _run_cli("sysdesign", "drill", "--topic", "caching", "--level", "hard")
        self.assertIn("[hard]", out)
        self.assertIn("Self-check", out)

    def test_estimate(self):
        out = _run_cli("sysdesign", "estimate", "--qps", "1000",
                       "--payload-kb", "1", "--retention-days", "30",
                       "--replication", "3", "--overhead", "1.0")
        self.assertIn("Requests/day: 86,400,000", out)
        data = json.loads(_run_cli("sysdesign", "estimate", "--qps", "1000", "--json"))
        self.assertAlmostEqual(data["qps"], 1000.0)

    def test_checklist(self):
        out = _run_cli("sysdesign", "checklist")
        self.assertIn("45 minutes", out)

    def test_flashcards(self):
        out = _run_cli("sysdesign", "flashcards", "--topic", "cdn", "--n", "2")
        self.assertIn("Q1.", out)
        self.assertIn("A1.", out)

    def test_plan(self):
        out = _run_cli("sysdesign", "plan", "--topic", "queues")
        self.assertIn("Study plan", out)
        self.assertIn("mock design", out)

    def test_unknown_topic_is_friendly_error(self):
        with self.assertRaises(SystemExit) as cm:
            _run_cli("sysdesign", "show", "--topic", "nope")
        self.assertEqual(cm.exception.code, 1)

    def test_registered_in_inventory(self):
        self.assertIn("sysdesign", CLI.COMMANDS)
        self.assertIn("deep-dive", CLI.SUBCOMMANDS["sysdesign"])
        self.assertIn("SysdesignError", CLI._EXPECTED_ERRORS)


if __name__ == "__main__":
    unittest.main()
