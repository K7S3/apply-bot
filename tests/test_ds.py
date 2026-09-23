"""Tests for candid ds-stats (stats refresher cards + quiz) and
candid ds-metrics (reference metric implementations + explanations).

Style follows tests/test_cli_ux.py: unittest classes, in-process CLI runs.
"""
import contextlib
import io
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import ds_metrics as M  # noqa: E402
from candid import ds_stats as S  # noqa: E402


def run_cli(argv, stdin=""):
    """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()
    finally:
        sys.stdin = old_stdin


def correct_answer(card):
    """A definitely-correct answer string for a card (numeric or key ideas)."""
    answer = card["answer"]
    items = answer if isinstance(answer, list) else [answer]
    numeric = [a["numeric"] for a in items if isinstance(a, dict)]
    texts = [a for a in items if not isinstance(a, dict)]
    parts = [str(numeric[0])] if numeric else []
    parts.extend(str(t) for t in texts)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# ds-stats: card bank
# ---------------------------------------------------------------------------

class CardBankTest(unittest.TestCase):
    def test_25_cards(self):
        self.assertEqual(len(S.load_cards()), 25)

    def test_card_schema(self):
        for card in S.load_cards():
            for key in ("id", "topic", "concept", "explanation", "quiz", "answer"):
                self.assertIn(key, card, f"card {card.get('id')} missing {key!r}")
            # concise, interview-ready explanations
            self.assertLess(len(card["explanation"]), 1200)
            self.assertGreater(len(card["explanation"]), 40)

    def test_card_ids_unique(self):
        ids = [c["id"] for c in S.load_cards()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_expected_topics_covered(self):
        tops = S.topics()
        self.assertEqual(tops, sorted(tops))
        for want in ("hypothesis_testing", "p_value", "bayes", "distributions",
                     "regression", "bias_variance"):
            self.assertIn(want, tops)

    def test_get_cards_topic_filter(self):
        cards = S.get_cards(topic="bayes")
        self.assertGreater(len(cards), 0)
        self.assertTrue(all(c["topic"] == "bayes" for c in cards))

    def test_get_cards_unknown_topic_raises(self):
        with self.assertRaises(S.DSStatsError):
            S.get_cards(topic="quantum")

    def test_shuffle_seed_deterministic(self):
        a = [c["id"] for c in S.get_cards(shuffle=True, seed=7)]
        b = [c["id"] for c in S.get_cards(shuffle=True, seed=7)]
        self.assertEqual(a, b)
        plain = [c["id"] for c in S.get_cards()]
        self.assertEqual(sorted(a), sorted(plain))  # same cards, reshuffled

    def test_render_card(self):
        card = S.load_cards()[0]
        text = S.render_card(card, 1, 25)
        self.assertIn(card["concept"], text)
        self.assertIn(card["explanation"], text)

    def test_render_review_counts(self):
        cards = S.get_cards(topic="bayes")
        text = S.render_review(cards)
        self.assertIn("[2/2]", text)


# ---------------------------------------------------------------------------
# ds-stats: answer checking
# ---------------------------------------------------------------------------

class CheckAnswerTest(unittest.TestCase):
    def _card(self, card_id):
        return next(c for c in S.load_cards() if c["id"] == card_id)

    def test_numeric_correct(self):
        card = self._card("bayes_theorem")
        ok, expected, matched, total = S.check_answer(card, "0.09")
        self.assertTrue(ok)
        self.assertIn("0.09", expected)

    def test_numeric_within_tolerance(self):
        card = self._card("normal_dist")  # 0.954 +/- 0.005
        ok, _, _, _ = S.check_answer(card, "0.95")
        self.assertTrue(ok)

    def test_numeric_outside_tolerance(self):
        card = self._card("bayes_theorem")
        ok, _, _, _ = S.check_answer(card, "0.5")
        self.assertFalse(ok)

    def test_numeric_embedded_in_sentence(self):
        card = self._card("type1_type2")  # expects 5
        ok, _, _, _ = S.check_answer(card, "I'd expect about 5 false positives")
        self.assertTrue(ok)

    def test_free_text_good_answer(self):
        card = self._card("p_value")
        ok, _, matched, total = S.check_answer(
            card, "It is the probability of data this extreme under the null; "
                  "it is NOT the probability the null is true.")
        self.assertTrue(ok)
        self.assertGreaterEqual(matched, 1)
        self.assertEqual(total, 3)

    def test_free_text_garbage_fails(self):
        card = self._card("p_value")
        ok, expected, matched, _ = S.check_answer(card, "asdf qwerty banana")
        self.assertFalse(ok)
        self.assertEqual(matched, 0)
        self.assertTrue(expected)

    def test_mixed_card_accepts_numeric(self):
        card = self._card("conditional_prob")
        ok, _, _, _ = S.check_answer(card, "0.5")
        self.assertTrue(ok)

    def test_mixed_card_accepts_text(self):
        card = self._card("conditional_prob")
        ok, _, _, _ = S.check_answer(card, "independent trials have no memory; gambler's fallacy")
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# ds-stats: quiz runner
# ---------------------------------------------------------------------------

class QuizTest(unittest.TestCase):
    def test_quiz_all_correct_scores_full(self):
        cards = S.get_cards(topic="bayes", shuffle=True, seed=1)
        answers = [correct_answer(c) for c in cards]
        out = io.StringIO()
        report = S.run_quiz(n=10, topic="bayes", seed=1,
                            input_fn=lambda _p: answers.pop(0),
                            print_fn=lambda *a: print(*a, file=out))
        self.assertEqual(report["score"], len(cards))
        self.assertEqual(report["total"], len(cards))
        self.assertIn(f"Score: {len(cards)}/{len(cards)}", out.getvalue())

    def test_quiz_all_wrong_scores_zero(self):
        out = io.StringIO()
        report = S.run_quiz(n=3, seed=2,
                            input_fn=lambda _p: "asdf qwerty",
                            print_fn=lambda *a: print(*a, file=out))
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["score"], 0)
        self.assertIn("Score: 0/3", out.getvalue())

    def test_quiz_caps_at_bank_size(self):
        report = S.run_quiz(n=1000, topic="estimation", seed=3,
                            input_fn=lambda _p: "x",
                            print_fn=lambda *a: None)
        self.assertEqual(report["total"], 1)  # only one estimation card

    def test_quiz_bad_n_raises(self):
        with self.assertRaises(S.DSStatsError):
            S.run_quiz(n=0, input_fn=lambda _p: "", print_fn=lambda *a: None)


# ---------------------------------------------------------------------------
# ds-metrics: pure functions
# ---------------------------------------------------------------------------

class BinaryMetricsTest(unittest.TestCase):
    def test_accuracy(self):
        self.assertAlmostEqual(M.accuracy([1, 0, 1, 1], [1, 0, 0, 1]), 0.75)

    def test_precision_recall_f1(self):
        yt, yp = [1, 1, 0, 0], [1, 0, 0, 1]
        self.assertAlmostEqual(M.precision(yt, yp), 0.5)
        self.assertAlmostEqual(M.recall(yt, yp), 0.5)
        self.assertAlmostEqual(M.f1(yt, yp), 0.5)

    def test_f1_perfect(self):
        self.assertAlmostEqual(M.f1([1, 0, 1], [1, 0, 1]), 1.0)

    def test_zero_division_returns_zero(self):
        self.assertEqual(M.precision([1, 1], [0, 0]), 0.0)
        self.assertEqual(M.recall([0, 0], [0, 0]), 0.0)
        self.assertEqual(M.f1([0, 0], [0, 0]), 0.0)

    def test_confusion_counts(self):
        c = M.confusion([1, 1, 0, 0], [1, 0, 1, 0])
        self.assertEqual(c, {"tp": 1, "tn": 1, "fp": 1, "fn": 1})

    def test_auc_perfect(self):
        self.assertAlmostEqual(M.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)

    def test_auc_worst(self):
        self.assertAlmostEqual(M.auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]), 0.0)

    def test_auc_ties_half(self):
        self.assertAlmostEqual(M.auc([0, 1], [0.5, 0.5]), 0.5)

    def test_auc_single_class_raises(self):
        with self.assertRaises(M.DSMetricsError):
            M.auc([1, 1, 1], [0.1, 0.2, 0.3])

    def test_auc_known_value(self):
        # positives ranked 1st and 3rd of 4: (3+1 ... ) -> 0.75
        self.assertAlmostEqual(M.auc([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]), 0.75)

    def test_log_loss(self):
        self.assertAlmostEqual(M.log_loss([1, 0], [0.9, 0.1]),
                               -math.log(0.9), places=6)

    def test_log_loss_clips_extremes(self):
        v = M.log_loss([1], [1.0])
        self.assertTrue(math.isfinite(v))
        self.assertGreater(v, 0)

    def test_thresholdize(self):
        self.assertEqual(M.thresholdize([0.9, 0.2, 0.5], 0.5), [1, 0, 1])


class RegressionMetricsTest(unittest.TestCase):
    def test_rmse(self):
        self.assertAlmostEqual(M.rmse([0, 0, 4], [0, 0, 0]),
                               math.sqrt(16 / 3))

    def test_mae(self):
        self.assertAlmostEqual(M.mae([1, 2, 3], [1, 3, 2]), 2 / 3)

    def test_rmse_perfect(self):
        self.assertEqual(M.rmse([1.5, 2.5], [1.5, 2.5]), 0.0)


class UpliftTest(unittest.TestCase):
    def test_uplift(self):
        self.assertAlmostEqual(M.uplift([1, 1, 0, 0], [1, 1, 0, 0]), 1.0)

    def test_uplift_continuous(self):
        self.assertAlmostEqual(M.uplift([10.0, 12.0, 5.0, 7.0],
                                        [1, 1, 0, 0]), 5.0)

    def test_uplift_missing_arm_raises(self):
        with self.assertRaises(M.DSMetricsError):
            M.uplift([1, 1], [1, 1])


class RankingMetricsTest(unittest.TestCase):
    def test_lift(self):
        yt = [1, 0, 0, 0, 1, 0, 0, 0, 0, 0]
        ys = [0.9, 0.1, 0.2, 0.3, 0.85, 0.05, 0.4, 0.15, 0.25, 0.35]
        self.assertAlmostEqual(M.lift_at_k(yt, ys, 2), 5.0)

    def test_gain(self):
        yt = [1, 0, 0, 0, 1, 0, 0, 0, 0, 0]
        ys = [0.9, 0.1, 0.2, 0.3, 0.85, 0.05, 0.4, 0.15, 0.25, 0.35]
        self.assertAlmostEqual(M.gain_at_k(yt, ys, 2), 1.0)
        self.assertAlmostEqual(M.gain_at_k(yt, ys, 10), 1.0)

    def test_ndcg_perfect(self):
        self.assertAlmostEqual(
            M.ndcg_at_k([3, 2, 1, 0], [0.9, 0.8, 0.7, 0.1], 4), 1.0)

    def test_ndcg_reversed_worse(self):
        v = M.ndcg_at_k([3, 2, 1, 0], [0.1, 0.7, 0.8, 0.9], 4)
        self.assertGreater(v, 0.0)
        self.assertLess(v, 1.0)

    def test_ndcg_no_relevance_zero(self):
        self.assertEqual(M.ndcg_at_k([0, 0, 0], [0.9, 0.8, 0.7], 3), 0.0)

    def test_map_known(self):
        # hits at ranks 1 (P@1=1) and 3 (P@3=2/3); 2 relevant total
        self.assertAlmostEqual(
            M.map_at_k([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.6], 3),
            (1.0 + 2 / 3) / 2)

    def test_map_no_relevant_zero(self):
        self.assertEqual(M.map_at_k([0, 0], [0.9, 0.1], 2), 0.0)

    def test_k_out_of_range_raises(self):
        with self.assertRaises(M.DSMetricsError):
            M.lift_at_k([1, 0], [0.9, 0.1], 3)


class CalibrationTest(unittest.TestCase):
    def test_perfect_calibration_zero_ece(self):
        res = M.calibration([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0], bins=2)
        self.assertAlmostEqual(res["ece"], 0.0)
        self.assertAlmostEqual(res["mce"], 0.0)
        self.assertEqual(len(res["bins"]), 2)

    def test_miscalibrated_positive_ece(self):
        res = M.calibration([1, 1, 1, 1], [0.5, 0.5, 0.5, 0.5], bins=10)
        self.assertGreater(res["ece"], 0.4)
        self.assertLessEqual(res["ece"], 1.0)


class RegistryTest(unittest.TestCase):
    def test_compute_metric_f1(self):
        v = M.compute_metric("f1", y_true=["1", "0", "1", "1"],
                             y_score=["0.9", "0.2", "0.8", "0.4"])
        self.assertAlmostEqual(v, 0.8)

    def test_compute_metric_auc(self):
        v = M.compute_metric("auc", y_true=[0, 0, 1, 1],
                             y_score=[0.1, 0.2, 0.8, 0.9])
        self.assertAlmostEqual(v, 1.0)

    def test_compute_metric_uplift_uses_treat(self):
        v = M.compute_metric("uplift", y_true=[1, 1, 0, 0],
                             y_treat=[1, 1, 0, 0])
        self.assertAlmostEqual(v, 1.0)

    def test_compute_metric_k_passthrough(self):
        v = M.compute_metric("ndcg", y_true=[3, 2, 1, 0],
                             y_score=[0.9, 0.8, 0.7, 0.1], k=4)
        self.assertAlmostEqual(v, 1.0)

    def test_compute_metric_missing_input_friendly(self):
        with self.assertRaises(M.DSMetricsError):
            M.compute_metric("f1", y_true=[1, 0], y_score=None)

    def test_compute_metric_length_mismatch(self):
        with self.assertRaises(M.DSMetricsError):
            M.compute_metric("rmse", y_true=[1, 2], y_score=[1.0])

    def test_compute_metric_unknown(self):
        with self.assertRaises(M.DSMetricsError):
            M.compute_metric("bogus", y_true=[1], y_score=[0.5])

    def test_explain_has_formula_and_when(self):
        text = M.explain("auc")
        self.assertIn("Formula:", text)
        self.assertIn("When to use it:", text)
        self.assertIn("0.5 = random", text)

    def test_explain_unknown_raises(self):
        with self.assertRaises(M.DSMetricsError):
            M.explain("bogus")

    def test_metric_list_covers_all(self):
        text = M.render_metric_list()
        for name in M.METRIC_NAMES:
            self.assertIn(name, text)
        self.assertEqual(len(M.METRIC_NAMES), 14)

    def test_render_result_float(self):
        self.assertEqual(M.render_result("f1", 0.8), "f1 = 0.8000")

    def test_render_result_calibration(self):
        res = M.calibration([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0], bins=2)
        text = M.render_result("calibration", res)
        self.assertIn("ECE=0.0000", text)
        self.assertIn("pred_mean", text)


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------

class DSStatsCLITest(unittest.TestCase):
    def test_review(self):
        code, out, _ = run_cli(["ds-stats", "review", "--topic", "bayes"])
        self.assertEqual(code, 0)
        self.assertIn("Bayes", out)
        self.assertIn("2 card(s)", out)

    def test_review_all(self):
        code, out, _ = run_cli(["ds-stats", "review"])
        self.assertEqual(code, 0)
        self.assertIn("25 card(s)", out)

    def test_review_bad_topic_friendly(self):
        code, out, err = run_cli(["ds-stats", "review", "--topic", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("ds-stats --help", err)

    def test_quiz_scores_with_stdin(self):
        cards = S.get_cards(shuffle=True, seed=3)[:2]
        stdin = "\n".join(correct_answer(c) for c in cards) + "\n"
        code, out, _ = run_cli(["ds-stats", "quiz", "--n", "2", "--seed", "3"],
                               stdin=stdin)
        self.assertEqual(code, 0)
        self.assertIn("Score: 2/2", out)

    def test_quiz_help_has_examples(self):
        code, out, _ = run_cli(["ds-stats", "quiz", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("examples:", out)

    def test_review_help_has_examples(self):
        code, out, _ = run_cli(["ds-stats", "review", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("examples:", out)


class DSMetricsCLITest(unittest.TestCase):
    def test_f1_cli(self):
        code, out, _ = run_cli(["ds-metrics", "f1",
                                "--y-true", "1", "0", "1", "1",
                                "--y-score", "0.9", "0.2", "0.8", "0.4"])
        self.assertEqual(code, 0)
        self.assertIn("f1 = 0.8000", out)

    def test_auc_cli(self):
        code, out, _ = run_cli(["ds-metrics", "auc",
                                "--y-true", "0", "0", "1", "1",
                                "--y-score", "0.1", "0.2", "0.8", "0.9"])
        self.assertEqual(code, 0)
        self.assertIn("auc = 1.0000", out)

    def test_uplift_cli(self):
        code, out, _ = run_cli(["ds-metrics", "uplift",
                                "--y-true", "1", "1", "0", "0",
                                "--y-treat", "1", "1", "0", "0"])
        self.assertEqual(code, 0)
        self.assertIn("uplift = 1.0000", out)

    def test_ndcg_cli_with_k(self):
        code, out, _ = run_cli(["ds-metrics", "ndcg",
                                "--y-true", "3", "2", "1", "0",
                                "--y-score", "0.9", "0.8", "0.7", "0.1",
                                "--k", "4"])
        self.assertEqual(code, 0)
        self.assertIn("ndcg = 1.0000", out)

    def test_calibration_cli(self):
        code, out, _ = run_cli(["ds-metrics", "calibration",
                                "--y-true", "1", "1", "0", "0",
                                "--y-score", "1", "1", "0", "0",
                                "--bins", "2"])
        self.assertEqual(code, 0)
        self.assertIn("ECE=0.0000", out)

    def test_explain_cli(self):
        code, out, _ = run_cli(["ds-metrics", "explain", "auc"])
        self.assertEqual(code, 0)
        self.assertIn("Formula:", out)
        self.assertIn("When to use it:", out)

    def test_list_cli(self):
        code, out, _ = run_cli(["ds-metrics", "list"])
        self.assertEqual(code, 0)
        for name in M.METRIC_NAMES:
            self.assertIn(name, out)

    def test_missing_inputs_friendly(self):
        code, out, err = run_cli(["ds-metrics", "f1",
                                  "--y-true", "1", "0"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("ds-metrics --help", err)

    def test_length_mismatch_friendly(self):
        code, out, err = run_cli(["ds-metrics", "rmse",
                                  "--y-true", "1", "2",
                                  "--y-score", "1"])
        self.assertEqual(code, 1)
        self.assertIn("Length mismatch", err)

    def test_metric_help_has_examples(self):
        code, out, _ = run_cli(["ds-metrics", "f1", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("examples:", out)

    def test_explain_help_has_examples(self):
        code, out, _ = run_cli(["ds-metrics", "explain", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("examples:", out)


class CommandInventoryTest(unittest.TestCase):
    def test_commands_registered(self):
        self.assertIn("ds-stats", CLI.COMMANDS)
        self.assertIn("ds-metrics", CLI.COMMANDS)
        self.assertIn("review", CLI.SUBCOMMANDS["ds-stats"])
        self.assertIn("quiz", CLI.SUBCOMMANDS["ds-stats"])
        for name in M.METRIC_NAMES:
            self.assertIn(name, CLI.SUBCOMMANDS["ds-metrics"])

    def test_top_level_help_lists_new_commands(self):
        code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("ds-stats", out)
        self.assertIn("ds-metrics", out)

    def test_error_classes_registered(self):
        self.assertIn("DSStatsError", CLI._EXPECTED_ERRORS)
        self.assertIn("DSMetricsError", CLI._EXPECTED_ERRORS)


if __name__ == "__main__":
    unittest.main()
