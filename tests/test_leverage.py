"""Tests for the competing-offer leverage playbook (batch 46).

Covers all ten features: register, ethical playbook, timeline, scripts,
BATNA, extension emails, deadline tracker, disclosure log, leverage score,
decision plan — plus the negotiation brief and CLI wiring.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import leverage as L  # noqa: E402
from candid import offer as O  # noqa: E402

TODAY = "2026-09-22"  # fixed "today" for deterministic tests

ACME = {"company": "Acme", "role": "Data Scientist", "base": 180000,
        "bonus_target_pct": 15, "sign_on": 20000, "equity_total": 200000,
        "vest_years": 4}
# normalized: 180000 + 27000 + 10000 + 50000 = 267000
BETA = {"company": "Beta", "role": "ML Engineer", "base": 200000,
        "bonus_target_pct": 10, "equity_total": 120000, "vest_years": 4}
# normalized: 200000 + 20000 + 0 + 30000 = 250000


class LeverageBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-leverage-"))
        self._saved = {}
        for name in ("DATA_DIR", "OFFERS_PATH", "PROFILE_PATH"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        self.acme = O.add(dict(ACME))
        self.beta = O.add(dict(BETA))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def _seed(self):
        L.register(self.acme["id"], status="written",
                   deadline="2026-10-04", contact="Jane")
        L.register(self.beta["id"], status="verbal",
                   deadline="2026-09-29", contact="Bob")
        return self.acme["id"], self.beta["id"]


class RegisterTest(LeverageBase):
    def test_register_and_list(self):
        aid, bid = self._seed()
        entries = L.list_registered(today=TODAY)
        self.assertEqual(len(entries), 2)
        # earliest deadline first: Beta (7d) before Acme (12d)
        self.assertEqual(entries[0]["offer_id"], bid)
        self.assertEqual(entries[0]["days_left"], 7)
        self.assertEqual(entries[1]["days_left"], 12)
        self.assertEqual(entries[1]["normalized_annual"], 267000)

    def test_register_rejects_bad_status(self):
        with self.assertRaises(L.LeverageError):
            L.register(self.acme["id"], status="maybe")

    def test_register_rejects_bad_deadline(self):
        with self.assertRaises(L.LeverageError):
            L.register(self.acme["id"], deadline="10/04/2026")

    def test_register_rejects_unknown_offer(self):
        with self.assertRaises(L.LeverageError):
            L.register(999, status="written")

    def test_register_updates_existing(self):
        self._seed()
        L.register(self.acme["id"], status="signed")
        entries = {e["offer_id"]: e for e in L.list_registered(today=TODAY)}
        self.assertEqual(entries[self.acme["id"]]["status"], "signed")

    def test_render_register_empty(self):
        self.assertIn("leverage add", L.render_register([]))

    def test_render_register_table(self):
        self._seed()
        out = L.render_register(L.list_registered(today=TODAY))
        self.assertIn("Acme", out)
        self.assertIn("267,000", out)


class PlaybookTest(unittest.TestCase):
    def test_playbook_has_ten_rules(self):
        text = L.ethical_playbook()
        self.assertIn("bluff", text)
        self.assertIn("Get everything in writing", text)
        for n in range(1, 11):
            self.assertIn(f"**{n}.", text)


class TimelineTest(LeverageBase):
    def test_sequenced_actions(self):
        self._seed()  # Beta 7d (soon), Acme 12d (on track), gap 5d -> overlap
        plan = L.build_timeline(today=TODAY)
        text = L.render_timeline(plan)
        self.assertIn("THIS WEEK", " ".join(plan["actions"]))
        self.assertTrue(any("OVERLAP" in a for a in plan["actions"]), text)
        self.assertIn("accelerate", text)

    def test_urgent_and_expired(self):
        L.register(self.acme["id"], status="written", deadline="2026-09-23")
        L.register(self.beta["id"], status="written", deadline="2026-09-20")
        plan = L.build_timeline(today=TODAY)
        joined = " ".join(plan["actions"])
        self.assertIn("DAY 0", joined)
        self.assertIn("EXPIRED", joined)

    def test_empty_register_guidance(self):
        plan = L.build_timeline(today=TODAY)
        self.assertTrue(any("leverage add" in a for a in plan["actions"]))

    def test_no_deadline_action(self):
        L.register(self.acme["id"], status="written")
        plan = L.build_timeline(today=TODAY)
        self.assertTrue(any("NO DEADLINE" in a for a in plan["actions"]))


class ScriptsTest(unittest.TestCase):
    ALL_FIELDS = {
        "recruiter": "R", "company": "Acme", "competing_company": "Beta",
        "competing_total": "$250k", "deadline": "Oct 1", "reason": "the team",
        "target": "$270k", "other_company": "Beta", "other_total": "$250k",
        "current_stage": "final round", "decision_date": "Oct 1", "days": "5",
        "current_deadline": "Sep 29", "new_date": "Oct 6", "redacted": "SSN",
        "breakdown": "$200k base + $50k equity",
        "competing_summary": "a $250k offer", "needed_date": "Oct 6",
        "accepted_company": "Beta", "genuine_positive": "the mission",
        "hiring_manager": "Lee",
    }

    def test_all_eight_scripts_render(self):
        self.assertEqual(len(L.LEVERAGE_SCRIPTS), 8)
        for key in L.LEVERAGE_SCRIPTS:
            out = L.get_script(key, **self.ALL_FIELDS)
            self.assertNotIn("{", out, f"unsubstituted field in {key}")
            self.assertNotIn("}", out, f"unsubstituted field in {key}")

    def test_unknown_script_raises(self):
        with self.assertRaises(L.LeverageError):
            L.get_script("bluff_hard")

    def test_script_index_lists_all(self):
        idx = L.render_script_index()
        for key in L.LEVERAGE_SCRIPTS:
            self.assertIn(key, idx)


class BatnaTest(LeverageBase):
    def test_best_written_is_batna(self):
        self._seed()
        r = L.batna_report(today=TODAY)
        self.assertEqual(r["batna"]["company"], "Acme")
        self.assertEqual(r["walk_away"], 267000)
        self.assertAlmostEqual(r["target"], 267000 * 1.07)
        self.assertFalse(r["weak"])
        self.assertIn("Walk-away", r["report"])

    def test_verbal_only_is_weak(self):
        L.register(self.acme["id"], status="verbal", deadline="2026-10-04")
        r = L.batna_report(today=TODAY)
        self.assertTrue(r["weak"])
        self.assertIn("verbal", r["basis"])

    def test_no_offers(self):
        r = L.batna_report(today=TODAY)
        self.assertIsNone(r["batna"])
        self.assertIsNone(r["walk_away"])
        self.assertIn("weak", r["report"])

    def test_expired_offer_excluded(self):
        L.register(self.acme["id"], status="written", deadline="2026-09-01")
        L.register(self.beta["id"], status="written", deadline="2026-10-04")
        r = L.batna_report(today=TODAY)
        self.assertEqual(r["batna"]["company"], "Beta")


class ExtensionTest(LeverageBase):
    def test_extension_email_contents(self):
        self._seed()
        email = L.extension_email_for(self.beta["id"], days=7,
                                      reason="final-rounds", name="Alex",
                                      today=TODAY)
        self.assertIn("2026-10-06", email)  # 2026-09-29 + 7 days
        self.assertIn("final-round", email)
        self.assertIn("Bob", email)
        self.assertIn("Alex", email)

    def test_extension_from_today_when_no_deadline(self):
        L.register(self.acme["id"], status="written")
        email = L.extension_email_for(self.acme["id"], days=5, today=TODAY)
        self.assertIn("2026-09-27", email)

    def test_extension_rejects_zero_days(self):
        self._seed()
        with self.assertRaises(L.LeverageError):
            L.extension_email_for(self.beta["id"], days=0, today=TODAY)

    def test_extension_rejects_unregistered(self):
        with self.assertRaises(L.LeverageError):
            L.extension_email_for(self.acme["id"], days=7, today=TODAY)

    def test_free_text_reason(self):
        out = L.extension_email("Alex", "Jane", "Acme", "DS",
                                "2026-09-29", "2026-10-06",
                                reason="waiting on my visa paperwork")
        self.assertIn("visa paperwork", out)


class DeadlinesTest(LeverageBase):
    def test_warnings(self):
        self._seed()  # Beta: verbal + 7d; Acme: written + 12d
        rep = L.deadline_report(today=TODAY)
        joined = " ".join(rep["warnings"])
        self.assertIn("verbal only", joined)  # Beta is verbal
        out = L.render_deadlines(rep)
        self.assertIn("Beta", out)
        self.assertIn("soon", out)

    def test_urgent_warning(self):
        L.register(self.beta["id"], status="written", deadline="2026-09-24")
        rep = L.deadline_report(today=TODAY)
        self.assertTrue(any("NOW" in w for w in rep["warnings"]))

    def test_no_warnings_when_calm(self):
        L.register(self.acme["id"], status="written", deadline="2026-12-01")
        rep = L.deadline_report(today=TODAY)
        self.assertEqual(rep["warnings"], [])
        self.assertIn("under control", L.render_deadlines(rep))


class DisclosureLogTest(LeverageBase):
    def test_log_and_list(self):
        rec = L.log_disclosure("Acme", "Jane", "call",
                               "told her about the $250k Beta offer")
        self.assertEqual(rec["company"], "Acme")
        self.assertTrue(rec["ts"].startswith("2026"))
        records = L.list_disclosures()
        self.assertEqual(len(records), 1)
        out = L.render_disclosures(records)
        self.assertIn("$250k Beta offer", out)
        self.assertIn("Consistency check", out)

    def test_log_rejects_bad_channel(self):
        with self.assertRaises(L.LeverageError):
            L.log_disclosure("Acme", "Jane", "smoke-signal", "hi")

    def test_log_rejects_empty(self):
        with self.assertRaises(L.LeverageError):
            L.log_disclosure("", "Jane", "call", "hi")
        with self.assertRaises(L.LeverageError):
            L.log_disclosure("Acme", "Jane", "call", "  ")

    def test_render_empty_log(self):
        self.assertIn("leverage log", L.render_disclosures([]))


class ScoreTest(LeverageBase):
    def test_moderate_score(self):
        self._seed()  # 1 written + 1 verbal, earliest 7d
        r = L.leverage_score(today=TODAY)
        self.assertEqual(r["score"], 55)  # 20 + 15 + 20
        self.assertIn("moderate", r["verdict"])
        out = L.render_score(r)
        self.assertIn("55/100", out)

    def test_weak_score_clamped(self):
        L.register(self.beta["id"], status="verbal", deadline="2026-09-24")
        r = L.leverage_score(today=TODAY)
        self.assertEqual(r["score"], 0)  # 0 + 3 + 10 - 10 - 10 -> clamp
        self.assertIn("weak", r["verdict"])
        self.assertTrue(r["levers"])

    def test_strong_score(self):
        L.register(self.acme["id"], status="written", deadline="2026-10-20")
        L.register(self.beta["id"], status="written", deadline="2026-10-25")
        gamma = O.add({"company": "Gamma", "role": "DS", "base": 170000,
                       "bonus_target_pct": 10, "equity_total": 100000,
                       "vest_years": 4})
        L.register(gamma["id"], status="written", deadline="2026-11-01")
        r = L.leverage_score(today=TODAY)
        self.assertGreaterEqual(r["score"], 70)
        self.assertIn("strong", r["verdict"])


class DecideTest(LeverageBase):
    def test_plan_recommends_top_offer(self):
        self._seed()
        plan = L.decision_plan(today=TODAY)
        recs = {r["company"]: r for r in plan["recommendations"]}
        self.assertEqual(recs["Acme"]["action"], "negotiate")
        self.assertEqual(recs["Beta"]["action"], "hold")
        self.assertTrue(any("If Acme reaches" in b for b in plan["branches"]))
        out = L.render_decision(plan)
        self.assertIn("NEGOTIATE", out)
        self.assertIn("Walk-away", out)

    def test_decide_action_when_deadline_near(self):
        L.register(self.acme["id"], status="written", deadline="2026-09-24")
        plan = L.decision_plan(today=TODAY)
        recs = {r["company"]: r for r in plan["recommendations"]}
        self.assertEqual(recs["Acme"]["action"], "decide")

    def test_empty_plan_is_pipeline(self):
        plan = L.decision_plan(today=TODAY)
        self.assertEqual(plan["recommendations"], [])
        self.assertTrue(any("pipeline" in b for b in plan["branches"]))


class BriefTest(LeverageBase):
    def test_brief_contents(self):
        self._seed()
        out = L.negotiation_brief(self.beta["id"], today=TODAY)
        self.assertIn("Beta", out)
        self.assertIn("Walk-away", out)
        self.assertIn("267,000", out)  # BATNA value from Acme
        self.assertIn("Suggested script", out)
        self.assertIn("disclosure log", out)

    def test_brief_unknown_offer(self):
        with self.assertRaises(L.LeverageError):
            L.negotiation_brief(999, today=TODAY)


class CLITest(LeverageBase):
    def setUp(self):
        super().setUp()
        import json
        C.PROFILE_PATH.write_text(json.dumps({"name": "Alex"}))

    def _run(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(["leverage", *argv])
        return buf.getvalue()

    def test_help_lists_leverage(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                CLI.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("leverage", buf.getvalue())

    def test_cli_add_list_score(self):
        out = self._run("add", "--offer-id", str(self.acme["id"]),
                        "--status", "written", "--deadline", "2026-10-04",
                        "--contact", "Jane")
        self.assertIn("Registered leverage", out)
        out = self._run("list")
        self.assertIn("Acme", out)
        out = self._run("score")
        self.assertIn("Leverage score", out)

    def test_cli_playbook_batna_timeline_deadlines_decide_brief(self):
        self._seed()
        for argv, needle in [
            (["playbook"], "ethical"),
            (["batna"], "BATNA"),
            (["timeline"], "Sequenced actions"),
            (["deadlines"], "deadlines"),
            (["decide"], "Decision plan"),
            (["brief", "--offer-id", str(self.acme["id"])], "Negotiation brief"),
            (["script", "--which", "index"], "first_disclosure"),
        ]:
            self.assertIn(needle, self._run(*argv), f"failed: {argv}")

    def test_cli_script_and_extend(self):
        self._seed()
        out = self._run("script", "--which", "match_ask",
                        "--set", "company=Acme", "--set", "other_company=Beta")
        self.assertIn("Acme", out)
        self.assertNotIn("{company}", out)
        out = self._run("extend", "--offer-id", str(self.beta["id"]),
                        "--days", "7")
        self.assertIn("2026-10-06", out)

    def test_cli_log(self):
        out = self._run("log", "--company", "Acme", "--person", "Jane",
                        "--channel", "call", "--said", "mentioned Beta offer")
        self.assertIn("Logged disclosure", out)
        out = self._run("log", "--list")
        self.assertIn("mentioned Beta offer", out)

    def test_cli_bad_script_is_friendly_error(self):
        with self.assertRaises(SystemExit) as cm:
            self._run("script", "--which", "bluff")
        self.assertEqual(cm.exception.code, 2)  # argparse invalid choice


if __name__ == "__main__":
    unittest.main()
