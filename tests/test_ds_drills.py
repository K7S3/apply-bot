"""Tests for the DS-track interview drills: ds-case and ds-sysdesign.

Covers the seeded banks (ids, schema), rubric coverage scoring, the
interactive drill engine (via canned answers and via mocked stdin), and
the CLI wiring (list / show / drill registration, friendly errors).

Run: CANDID_DATA_DIR=/tmp/candid-test-ds python3 -m pytest tests/test_ds_drills.py -q
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-ds")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import ds_case as DC  # noqa: E402
from candid import ds_sysdesign as DS  # noqa: E402

CASE_IDS = ["churn-prediction", "recommender", "fraud-detection",
            "eta-prediction", "ad-ranking", "customer-ltv",
            "demand-forecasting", "content-moderation"]
CASE_DIMS = ["Problem framing", "Metrics choice", "Data & baseline",
             "Modeling", "Evaluation", "Deployment & monitoring"]

SCENARIO_IDS = ["feature-store", "batch-retraining", "model-serving-shadow",
                "experimentation-platform", "data-quality-monitoring",
                "vector-search-retrieval"]
SCENARIO_DIMS = ["Data flow", "Feature engineering", "Training/serving skew",
                 "Latency", "Monitoring", "Feedback loops"]


class CaseBankTest(unittest.TestCase):
    def test_case_ids(self):
        ids = [c["id"] for c in DC.list_cases()]
        self.assertEqual(ids, CASE_IDS)

    def test_case_schema(self):
        for cid in CASE_IDS:
            c = DC.get_case(cid)
            self.assertTrue(c["business_context"], cid)
            self.assertTrue(c["core_question"], cid)
            self.assertGreaterEqual(len(c["probes"]), 5, cid)
            for p in c["probes"]:
                self.assertTrue(p["question"], cid)
                self.assertTrue(p["why"], cid)
                self.assertTrue(p["strong"], cid)
            self.assertEqual([r["dimension"] for r in c["rubric"]],
                             CASE_DIMS, cid)
            for r in c["rubric"]:
                self.assertTrue(r["check"], cid)
                self.assertGreaterEqual(len(r["signals"]), 5, (cid, r["dimension"]))

    def test_get_case_unknown(self):
        with self.assertRaises(DC.DSCaseError):
            DC.get_case("nope-not-a-case")


class ScenarioBankTest(unittest.TestCase):
    def test_scenario_ids(self):
        ids = [s["id"] for s in DS.list_scenarios()]
        self.assertEqual(ids, SCENARIO_IDS)

    def test_scenario_schema(self):
        for sid in SCENARIO_IDS:
            s = DS.get_scenario(sid)
            self.assertTrue(s["context"], sid)
            self.assertTrue(s["goal"], sid)
            self.assertGreaterEqual(len(s["questions"]), 5, sid)
            for q in s["questions"]:
                self.assertTrue(q["question"], sid)
                self.assertTrue(q["why"], sid)
                self.assertTrue(q["strong"], sid)
            self.assertEqual([r["dimension"] for r in s["rubric"]],
                             SCENARIO_DIMS, sid)
            for r in s["rubric"]:
                self.assertTrue(r["check"], sid)
                self.assertGreaterEqual(len(r["signals"]), 4, (sid, r["dimension"]))

    def test_get_scenario_unknown(self):
        with self.assertRaises(DS.DSSysDesignError):
            DS.get_scenario("nope-not-a-scenario")


class ScoreCoverageTest(unittest.TestCase):
    def test_covered_dimension(self):
        case = DC.get_case("churn-prediction")
        text = ("I define the label as cancelled within a 30-day churn window, "
                "with a fixed prediction window and cohort, an as-of cutoff, "
                "so the CSM outreach decision and intervention action are clear.")
        cov = DC.score_coverage(text, case["rubric"])
        framing = next(d for d in cov["dims"] if d["dimension"] == "Problem framing")
        self.assertTrue(framing["covered"])
        self.assertGreaterEqual(len(framing["matched"]), 2)

    def test_empty_text_covers_nothing(self):
        case = DC.get_case("churn-prediction")
        cov = DC.score_coverage("", case["rubric"])
        self.assertEqual(cov["pct"], 0)
        self.assertEqual(cov["earned"], 0)
        self.assertTrue(all(not d["covered"] for d in cov["dims"]))
        self.assertIn("Needs work", cov["level"])

    def test_case_insensitive(self):
        case = DC.get_case("churn-prediction")
        cov = DC.score_coverage("LABEL and CHURN WINDOW defined.", case["rubric"])
        framing = next(d for d in cov["dims"] if d["dimension"] == "Problem framing")
        self.assertTrue(framing["covered"])

    def test_level_bands(self):
        self.assertIn("Strong", DC._level(85))
        self.assertIn("Solid", DC._level(65))
        self.assertIn("Developing", DC._level(45))
        self.assertIn("Needs work", DC._level(10))


# Canned answers that collectively cover every churn rubric dimension.
CHURN_ANSWERS = [
    "I define the label as cancelled within a 30-day churn window, with a "
    "fixed prediction window and cohort, an as-of cutoff for features, so "
    "the CSM outreach decision and intervention action are well defined.",
    "I optimize AUC-PR and report lift and recall@k at the CSM capacity, "
    "translating to retained revenue as the business metric. Accuracy is "
    "meaningless at this base rate.",
    "Data: usage telemetry, billing events, support tickets, firmographic "
    "attributes. Baseline: a recency heuristic (no login in 14 days) and "
    "logistic regression before any ML.",
    "The imbalance is handled with class weight and threshold tuning "
    "instead of SMOTE. I prevent leakage with a strict as-of cutoff on "
    "every feature.",
    "Offline I use time-based splits and a backtest with a holdout scored "
    "at capacity. Then a randomized pilot with a holdout measures "
    "incremental retention and uplift, not just scores.",
    "In production I monitor drift in the score distribution and feature "
    "freshness, alert on shifts, and retrain on cadence with a "
    "champion/challenger setup to avoid intervention fatigue.",
]

# Canned answers that collectively cover every feature-store rubric dimension.
STORE_ANSWERS = [
    "Events flow through ingestion into an immutable event-time log; "
    "materialization jobs sync the online store and offline store.",
    "The online store is a key-value store with TTLs for p99 latency; the "
    "offline store is columnar. Precomputed aggregates are cached with a "
    "fallback to batch values.",
    "Training uses point-in-time as-of joins so there is no "
    "training/serving skew; I run parity checks between online and "
    "offline values.",
    "Features are versioned in a registry; backfill recomputes from event "
    "time without leaking the future.",
    "I monitor freshness SLAs, null rates, and drift per feature, and "
    "page on parity breaches with an alert.",
    "Serving decisions feed back into training data, so I watch for "
    "selection bias and feedback loop effects in the logging, and keep "
    "exploration traffic.",
]


class DrillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-dsdrill-"))
        self._orig = DC.SESSIONS_DIR
        DC.SESSIONS_DIR = self.tmp

    def tearDown(self):
        DC.SESSIONS_DIR = self._orig

    def _run_quiet(self, fn, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args, **kwargs)

    def test_drill_full_coverage(self):
        report = self._run_quiet(DC.drill, "churn-prediction",
                                 answers=CHURN_ANSWERS)
        self.assertEqual(report["kind"], "ds_case")
        self.assertEqual(report["item"], "churn-prediction")
        self.assertEqual(len(report["answers"]), 6)
        cov = report["coverage"]
        self.assertEqual(cov["pct"], 100)
        self.assertTrue(all(d["covered"] for d in cov["dims"]))
        saved = list(self.tmp.glob("*_ds_case_churn-prediction.json"))
        self.assertEqual(len(saved), 1)
        on_disk = json.loads(saved[0].read_text(encoding="utf-8"))
        self.assertEqual(on_disk["item"], "churn-prediction")

    def test_drill_empty_answers(self):
        report = self._run_quiet(DC.drill, "churn-prediction",
                                 answers=[""] * 6)
        self.assertEqual(report["coverage"]["pct"], 0)

    def test_drill_short_answers_list(self):
        # Fewer answers than probes: missing ones are treated as skipped.
        report = self._run_quiet(DC.drill, "churn-prediction",
                                 answers=CHURN_ANSWERS[:2])
        self.assertEqual(len(report["answers"]), 6)
        self.assertEqual(report["answers"][2], "")

    def test_drill_interactive_eof(self):
        # Ctrl-D on every probe: drill completes with zero coverage.
        with mock.patch("builtins.input", side_effect=EOFError):
            report = self._run_quiet(DC.drill, "recommender")
        self.assertEqual(report["item"], "recommender")
        self.assertEqual(report["coverage"]["pct"], 0)

    def test_drill_unknown_case(self):
        with self.assertRaises(DC.DSCaseError):
            self._run_quiet(DC.drill, "nope", answers=[])

    def test_sysdesign_drill_full_coverage(self):
        report = self._run_quiet(DS.drill, "feature-store",
                                 answers=STORE_ANSWERS)
        self.assertEqual(report["kind"], "ds_sysdesign")
        self.assertEqual(report["item"], "feature-store")
        cov = report["coverage"]
        self.assertEqual(cov["pct"], 100)
        self.assertTrue(all(d["covered"] for d in cov["dims"]))
        saved = list(self.tmp.glob("*_ds_sysdesign_feature-store.json"))
        self.assertEqual(len(saved), 1)

    def test_sysdesign_drill_unknown(self):
        with self.assertRaises(DS.DSSysDesignError):
            self._run_quiet(DS.drill, "nope", answers=[])


class RenderTest(unittest.TestCase):
    def test_render_case(self):
        text = DC.render_case(DC.get_case("fraud-detection"))
        self.assertIn("Fraud Detection", text)
        self.assertIn("Scoring rubric", text)
        for dim in CASE_DIMS:
            self.assertIn(dim, text)

    def test_render_scenario(self):
        text = DS.render_scenario(DS.get_scenario("vector-search-retrieval"))
        self.assertIn("Vector Search for Retrieval", text)
        self.assertIn("Critique rubric", text)
        for dim in SCENARIO_DIMS:
            self.assertIn(dim, text)

    def test_render_feedback_marks_misses(self):
        case = DC.get_case("eta-prediction")
        cov = DC.score_coverage("mae and p95 tail metrics", case["rubric"])
        text = DC.render_feedback("ETA Prediction", cov)
        self.assertIn("MISS", text)
        self.assertIn("Study next", text)


class CLITest(unittest.TestCase):
    def _main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(argv)
        return buf.getvalue()

    def test_ds_case_list(self):
        out = self._main(["ds-case", "list"])
        for cid in CASE_IDS:
            self.assertIn(cid, out)

    def test_ds_case_list_json(self):
        out = self._main(["ds-case", "list", "--json"])
        rows = json.loads(out)
        self.assertEqual([r["id"] for r in rows], CASE_IDS)

    def test_ds_case_show(self):
        out = self._main(["ds-case", "show", "ad-ranking"])
        self.assertIn("Ad Ranking", out)
        self.assertIn("Core question", out)

    def test_ds_case_show_unknown(self):
        with self.assertRaises(SystemExit) as cm:
            self._main(["ds-case", "show", "nope"])
        self.assertEqual(cm.exception.code, 1)

    def test_ds_sysdesign_list(self):
        out = self._main(["ds-sysdesign", "list"])
        for sid in SCENARIO_IDS:
            self.assertIn(sid, out)

    def test_ds_sysdesign_list_json(self):
        out = self._main(["ds-sysdesign", "list", "--json"])
        rows = json.loads(out)
        self.assertEqual([r["id"] for r in rows], SCENARIO_IDS)

    def test_ds_sysdesign_show(self):
        out = self._main(["ds-sysdesign", "show", "experimentation-platform"])
        self.assertIn("Experimentation Platform", out)
        self.assertIn("Goal:", out)

    def test_ds_sysdesign_show_unknown(self):
        with self.assertRaises(SystemExit) as cm:
            self._main(["ds-sysdesign", "show", "nope"])
        self.assertEqual(cm.exception.code, 1)

    def test_commands_registered(self):
        self.assertIn("ds-case", CLI.COMMANDS)
        self.assertIn("ds-sysdesign", CLI.COMMANDS)
        self.assertEqual(CLI.SUBCOMMANDS["ds-case"], ["list", "show", "drill"])
        self.assertEqual(CLI.SUBCOMMANDS["ds-sysdesign"], ["list", "show", "drill"])


if __name__ == "__main__":
    unittest.main()
