"""Tests for the offer decision journal (batch-52).

Run: CANDID_DATA_DIR=/tmp/candid-test-decision python -m unittest discover -s tests
"""
import os
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-decision")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path(os.environ["CANDID_DATA_DIR"])


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _make_offers():
    from candid import offer as OFF
    o1 = OFF.add({"company": "Acme", "role": "Data Scientist",
                  "base": 180000, "equity_total": 200000})
    o2 = OFF.add({"company": "Globex", "role": "MLE",
                  "base": 190000, "equity_total": 120000})
    return str(o1["id"]), str(o2["id"])


class ProsConsTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_weighted_totals_and_net(self):
        from candid import decision as D
        D.add_point(self.k1, "pro", "Great team", weight=3)
        D.add_point(self.k1, "pro", "Good comp", weight=1)
        D.add_point(self.k1, "con", "Long commute", weight=2)
        t = D.pro_con_totals(self.k1)
        self.assertEqual(t["pro_total"], 4)
        self.assertEqual(t["con_total"], 2)
        self.assertEqual(t["net"], 2)

    def test_weight_must_be_1_to_3(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.add_point(self.k1, "pro", "x", weight=5)
        with self.assertRaises(DecisionError):
            D.add_point(self.k1, "pro", "x", weight=0)

    def test_empty_text_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.add_point(self.k1, "con", "   ")

    def test_remove_by_index(self):
        from candid import decision as D
        D.add_point(self.k1, "pro", "Team", weight=2)
        D.add_point(self.k1, "pro", "Comp", weight=1)
        rec = D.remove_point(self.k1, "pro", 1)
        self.assertEqual(rec["text"], "Team")
        t = D.pro_con_totals(self.k1)
        self.assertEqual(len(t["pros"]), 1)
        self.assertEqual(t["pros"][0]["text"], "Comp")

    def test_remove_bad_index(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.remove_point(self.k1, "con", 3)

    def test_render_includes_weights(self):
        from candid import decision as D
        D.add_point(self.k1, "pro", "Team", weight=3)
        out = D.render_pros_cons(self.k1)
        self.assertIn("[3] Team", out)
        self.assertIn("net +3", out)

    def test_points_are_per_offer(self):
        from candid import decision as D
        D.add_point(self.k1, "pro", "Team", weight=3)
        t2 = D.pro_con_totals(self.k2)
        self.assertEqual(t2["net"], 0)


class CriteriaTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_rank_orders_by_weighted_score(self):
        from candid import decision as D
        D.set_criteria_weights({"comp": 50, "growth": 50})
        D.score_offer(self.k1, {"comp": 8, "growth": 6})   # weighted 7.0
        D.score_offer(self.k2, {"comp": 6, "growth": 9})   # weighted 7.5
        rows = D.criteria_rank()
        self.assertEqual(rows[0]["offer_key"], self.k2)
        self.assertAlmostEqual(rows[0]["weighted"], 7.5)
        self.assertEqual(rows[1]["offer_key"], self.k1)
        self.assertAlmostEqual(rows[1]["weighted"], 7.0)

    def test_score_range_validated(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.score_offer(self.k1, {"comp": 11})
        with self.assertRaises(DecisionError):
            D.score_offer(self.k1, {"comp": 0})

    def test_weights_must_be_positive(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.set_criteria_weights({"comp": 0})

    def test_rank_requires_weights(self):
        from candid import decision as D
        from candid.decision import DecisionError
        D.score_offer(self.k1, {"comp": 8})
        with self.assertRaises(DecisionError):
            D.criteria_rank()

    def test_unscored_offers_skipped(self):
        from candid import decision as D
        D.set_criteria_weights({"comp": 100})
        D.score_offer(self.k1, {"comp": 8})
        rows = D.criteria_rank()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["offer_key"], self.k1)

    def test_custom_criteria_allowed(self):
        from candid import decision as D
        D.set_criteria_weights({"comp": 60, "dog_policy": 40})
        D.score_offer(self.k1, {"comp": 8, "dog_policy": 10})
        rows = D.criteria_rank()
        self.assertAlmostEqual(rows[0]["weighted"], 8.8)

    def test_render_rank_shows_leader(self):
        from candid import decision as D
        D.set_criteria_weights({"comp": 100})
        D.score_offer(self.k1, {"comp": 9})
        out = D.render_criteria_rank(D.criteria_rank(), D.get_criteria_weights())
        self.assertIn("Leader: Acme", out)


class GutCheckTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_prompt_rotates_and_is_stable_same_day(self):
        from candid import decision as D
        d = date(2026, 9, 22)
        self.assertEqual(D.gut_prompt(d), D.gut_prompt(d))
        self.assertIn(D.gut_prompt(d), D.GUT_PROMPTS)

    def test_prompt_varies_across_days(self):
        from candid import decision as D
        prompts = {D.gut_prompt(date(2026, 9, d)) for d in range(1, 15)}
        self.assertGreater(len(prompts), 1)

    def test_answer_journaled(self):
        from candid import decision as D
        rec = D.gut_answer(self.k1, "I would be crushed")
        self.assertIn("prompt", rec)
        self.assertEqual(len(D.list_gut_answers(self.k1)), 1)
        self.assertEqual(len(D.list_gut_answers(self.k2)), 0)

    def test_empty_answer_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.gut_answer(self.k1, "  ")


class DeadlineTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()
        self.today = date(2026, 9, 22)

    def test_countdown_and_urgency(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-09-24", exploding=True)
        st = D.deadline_status(
            D._entry(D._load(), self.k1)["deadline"], self.today)
        self.assertEqual(st["days_left"], 2)
        self.assertEqual(st["urgency"], "urgent")
        self.assertTrue(st["exploding"])

    def test_overdue(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-09-20")
        st = D.deadline_status(
            D._entry(D._load(), self.k1)["deadline"], self.today)
        self.assertEqual(st["urgency"], "overdue")

    def test_scheduled_far_out(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-12-01")
        st = D.deadline_status(
            D._entry(D._load(), self.k1)["deadline"], self.today)
        self.assertEqual(st["urgency"], "scheduled")

    def test_bad_date_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.set_deadline(self.k1, "10/05/2026")

    def test_list_sorted_most_urgent_first(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-10-20")
        D.set_deadline(self.k2, "2026-09-25")
        rows = D.list_deadlines(self.today)
        self.assertEqual(rows[0]["offer_key"], self.k2)
        self.assertEqual(rows[1]["offer_key"], self.k1)

    def test_clear(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-10-05")
        D.clear_deadline(self.k1)
        self.assertEqual(D.list_deadlines(self.today), [])

    def test_render_flags_urgent(self):
        from candid import decision as D
        D.set_deadline(self.k1, "2026-09-23")
        out = D.render_deadlines(D.list_deadlines(self.today))
        self.assertIn("URGENT", out)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_state_transitions_logged(self):
        from candid import decision as D
        D.set_state(self.k1, "leaning")
        D.set_state(self.k1, "accepted")
        e = D._entry(D._load(), self.k1)
        self.assertEqual(e["state"], "accepted")
        kinds = [r["kind"] for r in e["journal"]]
        self.assertIn("state", kinds)

    def test_bad_state_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.set_state(self.k1, "maybe")

    def test_notes_and_timeline_order(self):
        from candid import decision as D
        D.add_note(self.k1, "First thought")
        D.set_state(self.k1, "leaning")
        D.add_note(self.k1, "Second thought")
        tl = D.timeline(self.k1)
        self.assertEqual([r["kind"] for r in tl],
                         ["note", "state", "note"])
        out = D.render_timeline(self.k1)
        self.assertIn("Second thought", out)


class RegretTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_both_sides_required(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.set_regret(self.k1, take="x", decline="")
        r = D.set_regret(self.k1, take="Golden handcuffs",
                         decline="Missing the rocketship",
                         ten_year="Rocketship wins")
        self.assertEqual(r["ten_year"], "Rocketship wins")

    def test_render_asks_the_question(self):
        from candid import decision as D
        D.set_regret(self.k1, take="a", decline="b")
        out = D.render_regret(self.k1)
        self.assertIn("harder to live with", out)


class SnapshotRevisitTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_snapshot_and_revisit(self):
        from candid import decision as D
        D.set_state(self.k1, "leaning")
        snap = D.take_snapshot(self.k1, "team I trust; comp; growth")
        self.assertEqual(len(snap["reasons"]), 3)
        self.assertEqual(snap["state"], "leaning")
        rv = D.revisit(self.k1, still_true="team I trust; comp",
                       changed="growth unclear", note="Still leaning yes")
        self.assertEqual(rv["still_true"], ["team I trust", "comp"])
        self.assertEqual(rv["changed"], ["growth unclear"])
        out = D.render_revisit(self.k1)
        self.assertIn("growth unclear", out)

    def test_revisit_without_snapshot_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.revisit(self.k1, still_true="x")

    def test_empty_reasons_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.take_snapshot(self.k1, " ; ")


class AdviceTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_consensus_counts(self):
        from candid import decision as D
        D.add_advice(self.k1, "Priya", "for", note="Great growth")
        D.add_advice(self.k1, "Sam", "against", note="Burnout risk")
        D.add_advice(self.k1, "Jo", "for")
        c = D.advice_consensus(self.k1)
        self.assertEqual(c["counts"], {"for": 2, "against": 1, "neutral": 0})

    def test_bad_stance_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.add_advice(self.k1, "Priya", "maybe")

    def test_render_shows_consensus(self):
        from candid import decision as D
        D.add_advice(self.k1, "Priya", "for")
        out = D.render_advice(self.k1)
        self.assertIn("for=1", out)
        self.assertIn("Priya", out)


class ConfidenceTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_history_and_trend(self):
        from candid import decision as D
        D.set_confidence(self.k1, 5, note="Early days")
        D.set_confidence(self.k1, 8, note="After onsite")
        hist = D.confidence_history(self.k1)
        self.assertEqual([r["level"] for r in hist], [5, 8])
        out = D.render_confidence(self.k1)
        self.assertIn("rising", out)

    def test_range_validated(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.set_confidence(self.k1, 11)
        with self.assertRaises(DecisionError):
            D.set_confidence(self.k1, 0)


class SummaryExportTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def _fill(self):
        from candid import decision as D
        D.add_point(self.k1, "pro", "Team", weight=3)
        D.set_criteria_weights({"comp": 100})
        D.score_offer(self.k1, {"comp": 9})
        D.set_state(self.k1, "leaning")
        D.set_deadline(self.k1, "2026-10-05")
        D.gut_answer(self.k1, "Crushed")
        D.add_advice(self.k1, "Priya", "for")
        D.set_confidence(self.k1, 7)
        D.set_regret(self.k1, take="a", decline="b")
        D.take_snapshot(self.k1, "team; comp")

    def test_summary_covers_everything(self):
        from candid import decision as D
        self._fill()
        out = D.render_summary(self.k1, today=date(2026, 9, 22))
        for token in ["leaning", "2026-10-05", "net +3", "7/10",
                      "1 for", "done", "taken", "Journal entries"]:
            self.assertIn(token, out)

    def test_export_writes_markdown(self):
        from candid import decision as D
        self._fill()
        out_path = TEST_DIR / "journal.md"
        p = D.export_journal(offer_key=self.k1, out=out_path,
                             today=date(2026, 9, 22))
        self.assertTrue(p.exists())
        md = p.read_text()
        for token in ["# Decision Journal", "## Acme (#1)", "Pros / cons",
                      "Criteria scores", "Gut checks", "Regret minimization",
                      "Reasons snapshot", "Advice", "Confidence", "Timeline"]:
            self.assertIn(token, md)

    def test_export_all_offers(self):
        from candid import decision as D
        self._fill()
        p = D.export_journal(out=TEST_DIR / "all.md",
                             today=date(2026, 9, 22))
        md = p.read_text()
        self.assertIn("## Acme (#1)", md)

    def test_export_empty_journal(self):
        from candid import decision as D
        p = D.export_journal(out=TEST_DIR / "empty.md")
        self.assertIn("No journal entries yet", p.read_text())


class ResolveOfferTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def test_by_id(self):
        from candid import decision as D
        key, offer = D.resolve_offer(self.k1)
        self.assertEqual(offer["company"], "Acme")

    def test_by_company_substring(self):
        from candid import decision as D
        key, offer = D.resolve_offer("glob")
        self.assertEqual(offer["company"], "Globex")

    def test_no_match_rejected(self):
        from candid import decision as D
        from candid.decision import DecisionError
        with self.assertRaises(DecisionError):
            D.resolve_offer("nonexistent-corp")

    def test_ambiguous_rejected(self):
        from candid import offer as OFF
        from candid import decision as D
        from candid.decision import DecisionError
        OFF.add({"company": "Acme Labs", "role": "SWE", "base": 1})
        with self.assertRaises(DecisionError):
            D.resolve_offer("acme")


class DecisionCLITest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.k1, self.k2 = _make_offers()

    def _run(self, *argv):
        import io
        from contextlib import redirect_stdout
        from candid.__main__ import build_parser
        buf = io.StringIO()
        with redirect_stdout(buf):
            build_parser().parse_args(list(argv)).func(
                build_parser().parse_args(list(argv)))
        return buf.getvalue()

    def test_cli_pros_roundtrip(self):
        out = self._run("decision", "pros-add", "--offer", "1",
                        "--pro", "Team", "--weight", "3")
        self.assertIn("Added pro", out)
        out = self._run("decision", "pros-list", "--offer", "1")
        self.assertIn("net +3", out)

    def test_cli_pros_add_needs_side(self):
        from candid.decision import DecisionError
        from candid.__main__ import build_parser
        a = build_parser().parse_args(
            ["decision", "pros-add", "--offer", "1"])
        with self.assertRaises(DecisionError):
            a.func(a)

    def test_cli_deadlines_and_summary(self):
        self._run("decision", "deadline-set", "--offer", "1",
                  "--date", "2026-10-05")
        out = self._run("decision", "deadlines")
        self.assertIn("Acme", out)
        out = self._run("decision", "summary", "--offer", "1")
        self.assertIn("Decision journal", out)

    def test_cli_export(self):
        out = self._run("decision", "export", "--offer", "1",
                        "--out", str(TEST_DIR / "cli.md"))
        self.assertIn("exported to", out)
        self.assertTrue((TEST_DIR / "cli.md").exists())


if __name__ == "__main__":
    unittest.main()
