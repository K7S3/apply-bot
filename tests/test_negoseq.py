"""Tests for the negotiation email sequence builder (candid/negoseq).

Run: CANDID_DATA_DIR=/tmp/candid-test-negoseq python -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        os.environ["CANDID_DATA_DIR"] = self.td.name
        from candid import negoseq as NQ
        self.NQ = NQ

    def tearDown(self):
        self.td.cleanup()
        os.environ.pop("CANDID_DATA_DIR", None)


class SequenceTest(_Base):
    def test_build_sequence_has_six_steps_in_order(self):
        steps = self.NQ.build_sequence()
        self.assertEqual([s["key"] for s in steps],
                         ["counter", "nudge", "call_request", "deadline_reply",
                          "accept", "decline"])

    def test_build_sequence_bad_deadline(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.build_sequence(deadline="not-a-date")


class DraftTest(_Base):
    def test_all_steps_draft(self):
        for step in ["counter", "nudge", "call_request", "deadline_reply",
                     "accept", "decline"]:
            d = self.NQ.draft_email(step, company="Acme", role="SWE",
                                    recruiter="Jane", name="K")
            self.assertIn("Acme", d["subject"] + d["body"])
            self.assertIn("SWE", d["subject"] + d["body"])
            self.assertTrue(d["subject"])

    def test_tone_changes_wording(self):
        bodies = {t: self.NQ.draft_email("counter", tone=t, company="Acme")["body"]
                  for t in ("warm", "professional", "assertive")}
        self.assertEqual(3, len(set(bodies.values())))

    def test_bad_step_and_tone(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.draft_email("bogus")
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.draft_email("counter", tone="rude")


class TimingTest(_Base):
    def test_add_business_days_skips_weekend(self):
        fri = date(2026, 9, 25)  # a Friday
        self.assertEqual(date(2026, 9, 28), self.NQ.add_business_days(fri, 1))
        self.assertEqual(date(2026, 9, 29), self.NQ.add_business_days(fri, 2))

    def test_timing_plan_counter_next_business_day(self):
        plan = self.NQ.timing_plan("2026-09-22")  # Tuesday
        self.assertEqual("2026-09-23", plan[0]["send_on"])
        self.assertEqual("counter", plan[0]["step"])
        steps = [p["step"] for p in plan]
        self.assertEqual(["counter", "nudge", "call_request"], steps)

    def test_timing_plan_deadline_anchored(self):
        plan = self.NQ.timing_plan("2026-09-22", deadline="2026-09-30")
        by_step = {p["step"]: p for p in plan}
        self.assertIn("deadline_reply", by_step)
        # 2026-09-30 is a Wednesday; reply goes out the business day before
        self.assertEqual("2026-09-29", by_step["deadline_reply"]["send_on"])
        self.assertEqual("2026-09-30", by_step["accept/decline"]["send_on"])

    def test_timing_plan_bad_inputs(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.timing_plan("nope")
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.timing_plan("2026-09-22", deadline="2026-09-01")


class BatnaTest(_Base):
    def test_all_kinds(self):
        for kind in ["competing_offer", "current_role", "other_finals",
                     "search_only", "none"]:
            r = self.NQ.batna_points(kind, detail="test")
            self.assertTrue(r["points"])
            self.assertTrue(r["cautions"])
            self.assertIn("test", r["points"][0])

    def test_strength_ordering(self):
        self.assertEqual("strong",
                         self.NQ.batna_points("competing_offer")["strength"])
        self.assertEqual("weakest",
                         self.NQ.batna_points("none")["strength"])

    def test_bad_kind(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.batna_points("bluff")


class AnchorTest(_Base):
    def test_anchor_above_target(self):
        r = self.NQ.anchor_ask(180000, 170000, 200000, 175000)
        self.assertGreater(r["ask"], 180000)
        self.assertLessEqual(r["ask"], 200000)
        self.assertEqual(r["ask"] - 180000, r["concession_room"])

    def test_anchor_capped_at_band_top(self):
        r = self.NQ.anchor_ask(198000, 170000, 200000, 190000)
        self.assertEqual(200000, r["ask"])
        self.assertTrue(any("capped" in n for n in r["notes"]))

    def test_target_below_walkaway_errors(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.anchor_ask(170000, 170000, 200000, 175000)

    def test_bad_band_errors(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.anchor_ask(180000, 200000, 170000, 175000)


class PushbackTest(_Base):
    def test_all_pushbacks(self):
        for kind in ["band_max", "need_approval", "firm_deadline",
                     "budget_freeze", "other_candidate", "verbal_only"]:
            r = self.NQ.pushback_reply(kind, deadline="Friday",
                                       later_date="Wednesday",
                                       review_months="6", reason="the scope",
                                       target_summary="$190k")
            self.assertTrue(r["reply"])
            self.assertTrue(r["tactic"])
            self.assertNotIn("{", r["reply"])

    def test_bad_pushback(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.pushback_reply("cry")


class TradeoffTest(_Base):
    def test_menu_default_order(self):
        menu = self.NQ.tradeoff_menu()
        self.assertEqual(8, len(menu))
        self.assertEqual("base", menu[0]["key"])

    def test_menu_priorities_first(self):
        menu = self.NQ.tradeoff_menu(["equity", "remote"])
        self.assertEqual(["equity", "remote"],
                         [m["key"] for m in menu[:2]])

    def test_menu_bad_lever(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.tradeoff_menu(["yacht"])

    def test_package_ask(self):
        text = self.NQ.package_ask({"base": "$190k", "sign_on": "$25k"})
        self.assertIn("$190k", text)
        self.assertIn("Sign-on bonus", text)
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.package_ask({})


class CallScriptTest(_Base):
    def test_call_and_voicemail(self):
        call = self.NQ.call_script(recruiter="Jane", company="Acme")
        self.assertIn("Jane", call)
        self.assertIn("Never accept on the call", call)
        vm = self.NQ.call_script(recruiter="Jane", voicemail=True)
        self.assertLess(len(vm), len(call))


class PlanRenderTest(_Base):
    def test_render_plan(self):
        md = self.NQ.render_plan("Acme", "SWE", "2026-09-22",
                                 deadline="2026-09-30", tone="warm",
                                 batna_kind="competing_offer",
                                 target_summary="$190k base")
        self.assertIn("# Negotiation plan: SWE @ Acme", md)
        self.assertIn("## Drafts", md)
        self.assertIn("## BATNA talking points", md)
        self.assertIn("strong", md)


class TrackerTest(_Base):
    def test_start_log_status_next(self):
        rec = self.NQ.start_sequence("Acme", "SWE", "2026-09-22",
                                     deadline="2026-09-30")
        self.assertEqual(1, rec["id"])
        self.assertEqual(5, len(rec["plan"]))
        nxt = self.NQ.next_action(1)
        self.assertIn("counter", nxt)
        self.NQ.log_email(1, "counter", "sent")
        nxt = self.NQ.next_action(1)
        self.assertIn("nudge", nxt)
        status = self.NQ.render_status(1)
        self.assertIn("Acme", status)
        self.assertIn("nudge", status)

    def test_list_and_get(self):
        self.NQ.start_sequence("Acme", "SWE", "2026-09-22")
        self.NQ.start_sequence("Beta", "DS", "2026-09-23")
        self.assertEqual(2, len(self.NQ.list_sequences()))
        self.assertEqual("Beta", self.NQ.get_sequence(2)["company"])

    def test_unknown_sequence_errors(self):
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.get_sequence(99)
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.log_email(99, "counter")

    def test_bad_log_inputs(self):
        self.NQ.start_sequence("Acme", "SWE", "2026-09-22")
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.log_email(1, "bogus_step")
        with self.assertRaises(self.NQ.NegoseqError):
            self.NQ.log_email(1, "counter", status="vibes")


class NegoseqCliTest(unittest.TestCase):
    """In-process CLI smoke tests; export must not require a profile."""

    def setUp(self):
        import contextlib
        import io
        import json
        self._ctxlib = contextlib
        self._io = io
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-negoseq-cli-"))
        from candid import __main__ as CLI
        from candid import config as C
        self.CLI = CLI
        self.C = C
        self._saved = {n: getattr(C, n) for n in
                       ("TRACKER_PATH", "PROFILE_PATH", "DATA_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.DATA_DIR = self.tmp
        os.environ["CANDID_DATA_DIR"] = str(self.tmp)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(self.C, name, val)
        os.environ.pop("CANDID_DATA_DIR", None)

    def run_cli(self, argv):
        out, err = self._io.StringIO(), self._io.StringIO()
        with self._ctxlib.redirect_stdout(out), self._ctxlib.redirect_stderr(err):
            try:
                self.CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    def test_export_works_without_profile(self):
        out_path = self.tmp / "plan.md"
        code, out, _ = self.run_cli(
            ["negoseq", "export", "--company", "Acme", "--role", "SWE",
             "--offer-date", "2026-09-22", "--out", str(out_path)])
        self.assertEqual(0, code, f"export failed without profile")
        text = out_path.read_text()
        self.assertIn("# Negotiation plan: SWE @ Acme", text)
        self.assertIn("## Drafts", text)

    def test_export_uses_profile_name_when_present(self):
        import json
        self.C.PROFILE_PATH.write_text(json.dumps({"name": "Alex Rivera"}))
        out_path = self.tmp / "plan2.md"
        code, _, _ = self.run_cli(
            ["negoseq", "export", "--company", "Acme", "--role", "SWE",
             "--offer-date", "2026-09-22", "--out", str(out_path)])
        self.assertEqual(0, code)
        self.assertIn("Alex Rivera", out_path.read_text())

    def test_draft_timing_anchor_track_smoke(self):
        for argv in (
            ["negoseq", "draft", "--step", "counter", "--tone", "warm",
             "--company", "Acme", "--role", "SWE"],
            ["negoseq", "timing", "--offer-date", "2026-09-22",
             "--deadline", "2026-09-30"],
            ["negoseq", "anchor", "--target", "180000", "--low", "170000",
             "--high", "200000", "--walkaway", "175000"],
            ["negoseq", "batna", "--kind", "competing_offer"],
            ["negoseq", "tradeoffs", "--priorities", "base,equity"],
            ["negoseq", "call", "--person", "Jane", "--company", "Acme"],
        ):
            code, out, _ = self.run_cli(argv)
            self.assertEqual(0, code, f"{argv} failed")
            self.assertTrue(out.strip(), f"{argv} printed nothing")
        code, _, _ = self.run_cli(
            ["negoseq", "track", "--op", "start", "--company", "Acme",
             "--role", "SWE", "--offer-date", "2026-09-22"])
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
