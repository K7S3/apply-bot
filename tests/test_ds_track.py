"""Tests for the Data Scientist track: SQL drills (ds-sql) and
experiment-design drills + power calculator (ds-exp).

Run: python -m pytest tests/test_ds_track.py -q
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402


class CLIRunner:
    def run_cli(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin is not None:
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


# ---------------------------------------------------------------------------
# SQL question bank
# ---------------------------------------------------------------------------

class SQLBankTest(unittest.TestCase):
    def test_15_questions_with_required_fields(self):
        from candid import ds_sql as S
        qs = S.load_questions()
        self.assertEqual(len(qs), 15)
        ids = [q["id"] for q in qs]
        self.assertEqual(len(set(ids)), 15, "question ids must be unique")
        for q in qs:
            for field in ("id", "title", "topic", "difficulty", "prompt",
                          "setup_sql", "solution", "expected", "hint"):
                self.assertIn(field, q, f"{q['id']} missing {field}")
            self.assertIn(q["topic"],
                          {"aggregations", "window", "joins", "cte", "dates"})
            self.assertIn(q["difficulty"], {"easy", "medium", "hard"})
            self.assertTrue(q["expected"], f"{q['id']} has empty expected")

    def test_topics_cover_all_five_areas(self):
        from candid import ds_sql as S
        topics = {q["topic"] for q in S.load_questions()}
        self.assertEqual(topics, {"aggregations", "window", "joins", "cte", "dates"})

    def test_reference_solutions_all_pass(self):
        from candid import ds_sql as S
        for q in S.load_questions():
            r = S.judge(q["id"], q["solution"])
            self.assertTrue(r["passed"], f"{q['id']} reference failed: {r}")
            self.assertEqual(r["got_rows"], len(q["expected"]))

    def test_wrong_query_fails_with_diff(self):
        from candid import ds_sql as S
        r = S.judge("ds-sql-01", "SELECT region, COUNT(*) FROM orders GROUP BY region")
        self.assertFalse(r["passed"])
        self.assertTrue(r["missing"] or r["extra"])
        out = S.render_verdict(r, show_hint=False)
        self.assertIn("FAIL", out)
        self.assertIn("Missing rows", out)

    def test_trivially_wrong_query_fails(self):
        from candid import ds_sql as S
        for qid in ("ds-sql-01", "ds-sql-06", "ds-sql-10", "ds-sql-14"):
            r = S.judge(qid, "SELECT 1")
            self.assertFalse(r["passed"], qid)

    def test_order_insensitive_by_default(self):
        from candid import ds_sql as S
        q = S.get_question("ds-sql-01")
        # same rows, deliberately scrambled order, no ORDER BY
        alt = ("SELECT region, SUM(amount) AS revenue FROM orders "
               "GROUP BY region ORDER BY revenue DESC, region")
        r = S.judge(q["id"], alt)
        self.assertTrue(r["passed"], S.render_verdict(r))

    def test_order_matters_enforced(self):
        from candid import ds_sql as S
        # ds-sql-04 requires revenue DESC; ascending must fail
        r = S.judge("ds-sql-04",
                    "SELECT product, revenue FROM products ORDER BY revenue ASC LIMIT 3")
        self.assertFalse(r["passed"])
        out = S.render_verdict(r, show_hint=False)
        self.assertIn("FAIL", out)

    def test_column_count_mismatch_flagged(self):
        from candid import ds_sql as S
        r = S.judge("ds-sql-01", "SELECT region FROM orders GROUP BY region")
        self.assertFalse(r["passed"])
        self.assertTrue(r["column_mismatch"])
        self.assertIn("Column count", S.render_verdict(r, show_hint=False))

    def test_non_select_rejected(self):
        from candid import ds_sql as S
        with self.assertRaises(S.SQLDrillError):
            S.judge("ds-sql-01", "DROP TABLE orders")
        with self.assertRaises(S.SQLDrillError):
            S.judge("ds-sql-01", "")
        with self.assertRaises(S.SQLDrillError):
            S.judge("ds-sql-01", "INSERT INTO orders VALUES (9,'x',1)")

    def test_unknown_question_id(self):
        from candid import ds_sql as S
        with self.assertRaises(S.SQLDrillError):
            S.get_question("nope-99")

    def test_null_and_float_handling(self):
        from candid import ds_sql as S
        # ds-sql-08 has a NULL mom_growth and rounded floats
        r = S.judge("ds-sql-08", S.get_question("ds-sql-08")["solution"])
        self.assertTrue(r["passed"])

    def test_dedup_and_funnel_edge_cases(self):
        from candid import ds_sql as S
        # user 3 purchased BEFORE signup -> must be excluded (funnel)
        r = S.judge("ds-sql-14", S.get_question("ds-sql-14")["solution"])
        self.assertTrue(r["passed"])
        got = [tuple(x) for x in S.get_question("ds-sql-14")["expected"]]
        self.assertEqual(got, [(1,), (4,)])

    def test_hint_shown_on_failure(self):
        from candid import ds_sql as S
        r = S.judge("ds-sql-02", "SELECT name FROM customers")
        out = S.render_verdict(r, show_hint=True)
        self.assertIn("Hint:", out)
        self.assertIn("LEFT JOIN", out)


# ---------------------------------------------------------------------------
# ds-sql CLI
# ---------------------------------------------------------------------------

class DSSQLCLITest(CLIRunner, unittest.TestCase):
    def test_list(self):
        code, out, err = self.run_cli(["ds-sql", "list"])
        self.assertEqual(code, 0, err)
        self.assertIn("ds-sql-01", out)
        self.assertIn("ds-sql-15", out)

    def test_list_topic_filter(self):
        code, out, err = self.run_cli(["ds-sql", "list", "--topic", "window"])
        self.assertEqual(code, 0, err)
        self.assertIn("ds-sql-06", out)
        self.assertNotIn("ds-sql-01", out)

    def test_list_difficulty_filter(self):
        code, out, err = self.run_cli(["ds-sql", "list", "--difficulty", "easy"])
        self.assertEqual(code, 0, err)
        self.assertIn("ds-sql-01", out)
        self.assertNotIn("ds-sql-10", out)

    def test_show(self):
        code, out, err = self.run_cli(["ds-sql", "show", "ds-sql-09"])
        self.assertEqual(code, 0, err)
        self.assertIn("Customers above average spend", out)
        self.assertIn("CREATE TABLE", out)

    def test_show_unknown_id_is_friendly(self):
        code, out, err = self.run_cli(["ds-sql", "show", "bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Next:", err)
        self.assertNotIn("Traceback", err)

    def test_solve_pass_via_stdin(self):
        from candid import ds_sql as S
        sol = S.get_question("ds-sql-02")["solution"]
        code, out, err = self.run_cli(["ds-sql", "solve", "ds-sql-02"], stdin=sol)
        self.assertEqual(code, 0, err)
        self.assertIn("PASS", out)

    def test_solve_fail_exit_code(self):
        code, out, err = self.run_cli(["ds-sql", "solve", "ds-sql-02"],
                                      stdin="SELECT name FROM customers")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("Hint:", out)

    def test_solve_via_file(self):
        from candid import ds_sql as S
        import tempfile
        sol = S.get_question("ds-sql-13")["solution"]
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
            f.write(sol)
            path = f.name
        code, out, err = self.run_cli(["ds-sql", "solve", "ds-sql-13",
                                       "--file", path])
        self.assertEqual(code, 0, err)
        self.assertIn("PASS", out)

    def test_solve_broken_sql_is_friendly(self):
        code, out, err = self.run_cli(["ds-sql", "solve", "ds-sql-01"],
                                      stdin="SELECT FROM WHERE")
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Next:", err)
        self.assertNotIn("Traceback", err)


# ---------------------------------------------------------------------------
# experiment scenario bank
# ---------------------------------------------------------------------------

class ExperimentBankTest(unittest.TestCase):
    def test_10_scenarios_with_required_fields(self):
        from candid import ds_experiment as E
        ss = E.load_scenarios()
        self.assertEqual(len(ss), 10)
        ids = [s["id"] for s in ss]
        self.assertEqual(len(set(ids)), 10)
        for s in ss:
            for field in ("id", "title", "topic", "scenario", "key_concepts",
                          "rubric", "drill_questions", "sample_answer"):
                self.assertIn(field, s, f"{s['id']} missing {field}")
            self.assertTrue(s["drill_questions"], s["id"])
            for dq in s["drill_questions"]:
                self.assertIn("question", dq)
                self.assertTrue(dq["key_points"], s["id"])
                for kp in dq["key_points"]:
                    self.assertIn("point", kp)
                    self.assertTrue(kp["keywords"], s["id"])
            self.assertTrue(s["rubric"], s["id"])
            for r in s["rubric"]:
                self.assertIn("dimension", r)
                self.assertIn("check", r)

    def test_unknown_scenario(self):
        from candid import ds_experiment as E
        with self.assertRaises(E.ExperimentError):
            E.get_scenario("exp-99")

    def test_topic_filter(self):
        from candid import ds_experiment as E
        peeking = E.list_scenarios(topic="peeking")
        self.assertEqual({s["id"] for s in peeking}, {"exp-03", "exp-09"})
        self.assertEqual(len(E.list_scenarios()), 10)


# ---------------------------------------------------------------------------
# power calculator
# ---------------------------------------------------------------------------

class PowerCalcTest(unittest.TestCase):
    def test_ndtri_accuracy(self):
        from candid import ds_experiment as E
        self.assertAlmostEqual(E._ndtri(0.975), 1.959963985, places=5)
        self.assertAlmostEqual(E._ndtri(0.8), 0.841621234, places=5)
        self.assertAlmostEqual(E._ndtri(0.5), 0.0, places=9)

    def test_required_n_canonical(self):
        from candid import ds_experiment as E
        # hand-checkable two-proportion example
        self.assertEqual(E.required_n(0.1, 0.02, 0.05, 0.8), 3841)

    def test_required_n_monotonic(self):
        from candid import ds_experiment as E
        # smaller MDE -> larger n; higher power -> larger n
        self.assertGreater(E.required_n(0.1, 0.01), E.required_n(0.1, 0.02))
        self.assertGreater(E.required_n(0.1, 0.02, power=0.9),
                           E.required_n(0.1, 0.02, power=0.8))

    def test_detectable_effect_roundtrip(self):
        from candid import ds_experiment as E
        eff = E.detectable_effect(0.1, 3841, 0.05, 0.8)
        self.assertAlmostEqual(eff, 0.02, places=4)

    def test_detectable_effect_shrinks_with_n(self):
        from candid import ds_experiment as E
        small = E.detectable_effect(0.1, 1000)
        large = E.detectable_effect(0.1, 20000)
        self.assertGreater(small, large)
        self.assertLess(large, 0.02)

    def test_invalid_inputs_raise(self):
        from candid import ds_experiment as E
        for kwargs in ({"p": 0, "mde": 0.02},
                       {"p": 1.5, "mde": 0.02},
                       {"p": 0.1, "mde": -0.01},
                       {"p": 0.99, "mde": 0.02},   # p + mde >= 1
                       {"p": 0.1, "mde": 0.02, "alpha": 1.5},
                       {"p": 0.1, "mde": 0.02, "power": 0}):
            with self.assertRaises(E.ExperimentError, msg=str(kwargs)):
                E.required_n(**kwargs)
        with self.assertRaises(E.ExperimentError):
            E.detectable_effect(0.1, 0)


# ---------------------------------------------------------------------------
# drill scoring
# ---------------------------------------------------------------------------

class DrillScoreTest(unittest.TestCase):
    def test_keyword_matching(self):
        from candid import ds_experiment as E
        kps = [{"point": "Use sticky bucketing.", "keywords": ["sticky", "bucket"]},
               {"point": "Name the bias.", "keywords": ["carryover"]}]
        good = E.score_answer("Randomize by user with sticky bucketing.", kps)
        self.assertEqual((good["covered"], good["total"]), (1, 2))
        self.assertTrue(good["hits"][0]["covered"])
        self.assertFalse(good["hits"][1]["covered"])
        bad = E.score_answer("I would just ship it.", kps)
        self.assertEqual(bad["covered"], 0)

    def test_case_insensitive(self):
        from candid import ds_experiment as E
        kps = [{"point": "p", "keywords": ["SUTVA"]}]
        self.assertEqual(E.score_answer("this violates sutva", kps)["covered"], 1)

    def test_drill_with_canned_answers(self):
        from candid import ds_experiment as E
        s = E.get_scenario("exp-01")
        answers = []
        for dq in s["drill_questions"]:
            # an answer containing every keyword -> full coverage
            words = {kw for kp in dq["key_points"] for kw in kp["keywords"]}
            answers.append(" ".join(sorted(words)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report = E.drill("exp-01", answers=answers)
        self.assertEqual(report["covered"], report["total"])
        self.assertGreater(report["total"], 0)
        self.assertIn("Drill score", buf.getvalue())

    def test_drill_partial_answers(self):
        from candid import ds_experiment as E
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report = E.drill("exp-03", answers=["I would ship it immediately."])
        self.assertEqual(report["covered"], 0)
        self.assertIn("Model answer", buf.getvalue())


# ---------------------------------------------------------------------------
# ds-exp CLI
# ---------------------------------------------------------------------------

class DSExpCLITest(CLIRunner, unittest.TestCase):
    def test_list(self):
        code, out, err = self.run_cli(["ds-exp", "list"])
        self.assertEqual(code, 0, err)
        self.assertIn("exp-01", out)
        self.assertIn("exp-10", out)

    def test_list_topic_filter(self):
        code, out, err = self.run_cli(["ds-exp", "list", "--topic", "peeking"])
        self.assertEqual(code, 0, err)
        self.assertIn("exp-03", out)
        self.assertNotIn("exp-01", out)

    def test_show(self):
        code, out, err = self.run_cli(["ds-exp", "show", "exp-05"])
        self.assertEqual(code, 0, err)
        self.assertIn("Network interference", out)
        self.assertIn("Rubric", out)

    def test_show_unknown_id_is_friendly(self):
        code, out, err = self.run_cli(["ds-exp", "show", "bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Next:", err)
        self.assertNotIn("Traceback", err)

    def test_calc_absolute_mde(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "0.1", "--mde", "0.02",
             "--alpha", "0.05", "--power", "0.8"])
        self.assertEqual(code, 0, err)
        self.assertIn("3,841", out)
        self.assertIn("per variant", out)

    def test_calc_relative_mde(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "0.1", "--rel", "0.2"])
        self.assertEqual(code, 0, err)
        self.assertIn("3,841", out)

    def test_calc_detectable_effect(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "0.1", "--n", "5000"])
        self.assertEqual(code, 0, err)
        self.assertIn("detectable", out.lower())
        self.assertIn("0.0174", out)

    def test_calc_conflicting_flags_friendly(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "0.1", "--mde", "0.02", "--rel", "0.2"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Next:", err)
        self.assertNotIn("Traceback", err)

    def test_calc_n_with_mde_friendly(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "0.1", "--n", "5000", "--mde", "0.02"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertNotIn("Traceback", err)

    def test_calc_bad_baseline_friendly(self):
        code, out, err = self.run_cli(
            ["ds-exp", "calc", "--p", "1.5", "--mde", "0.02"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertNotIn("Traceback", err)

    def test_drill_empty_stdin_exits_nonzero(self):
        # empty stdin -> EOF immediately -> zero coverage -> exit 1, no hang
        code, out, err = self.run_cli(["ds-exp", "drill", "exp-01"], stdin="")
        self.assertEqual(code, 1)
        self.assertIn("Drill score", out)


if __name__ == "__main__":
    unittest.main()
