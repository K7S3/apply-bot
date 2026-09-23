"""Tests for negotiate outreach additions: expectation scripts + counter simulator.

Run: cd ~/workspace/candid-batch-8 && python3 -m pytest tests/test_negotiate_outreach.py -q
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import negotiate as N  # noqa: E402

DATA_STATS = {
    "p25": 150000.0, "median": 175000.0, "p75": 200000.0, "n": 12,
    "sources": ["job_post:x", "dol_lca:y"], "matches": [],
}
NO_DATA_STATS = {
    "p25": None, "median": None, "p75": None, "n": 0,
    "sources": [], "matches": [],
}


def _patched_lookup(return_value=None, side_effect=None):
    return mock.patch("candid.salary.lookup",
                      return_value=return_value, side_effect=side_effect)


class ExpectationScriptTest(unittest.TestCase):
    def test_range_variant_with_data(self):
        with _patched_lookup(return_value=DATA_STATS):
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       title="Machine Learning Engineer",
                                       location="New York", variant="range")
        self.assertIn("Keshavan", out)
        self.assertIn("ML Engineer", out)
        self.assertIn("Acme", out)
        self.assertIn("$150,000", out)
        self.assertIn("$175,000", out)
        self.assertIn("$200,000", out)

    def test_deflect_variant(self):
        with _patched_lookup(return_value=DATA_STATS) as m:
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       variant="deflect")
        self.assertIn("Keshavan", out)
        self.assertIn("ML Engineer", out)
        self.assertIn("Acme", out)
        self.assertIn("budgeted band", out)
        m.assert_not_called()  # deflect needs no data

    def test_anchor_variant_with_data(self):
        with _patched_lookup(return_value=DATA_STATS):
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       variant="anchor")
        self.assertIn("Keshavan", out)
        self.assertIn("Acme", out)
        self.assertIn("$200,000", out)  # single anchor at p75 (>= median)
        self.assertIn("$175,000", out)  # justified against the median

    def test_range_no_data_invents_nothing(self):
        with _patched_lookup(return_value=NO_DATA_STATS):
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       variant="range")
        self.assertIn("No usable salary data was found", out)
        self.assertIn("budgeted", out)
        self.assertNotIn("$", out)  # no invented numbers anywhere

    def test_anchor_no_data_falls_back_to_deflect_language(self):
        with _patched_lookup(return_value=NO_DATA_STATS):
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       variant="anchor")
        self.assertIn("No usable salary data was found", out)
        self.assertIn("budgeted", out)
        self.assertNotIn("$", out)

    def test_salary_error_treated_as_no_data(self):
        from candid.salary import SalaryError
        with _patched_lookup(side_effect=SalaryError("db gone")):
            out = N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                       variant="range")
        self.assertIn("No usable salary data was found", out)
        self.assertNotIn("$", out)

    def test_invalid_variant_raises(self):
        with self.assertRaises(ValueError):
            N.expectation_script("Keshavan", "ML Engineer", "Acme",
                                 variant="mystery")

    def test_missing_fields_raise(self):
        for kwargs in ({"name": "", "role": "R", "company": "C"},
                       {"name": "N", "role": "", "company": "C"},
                       {"name": "N", "role": "R", "company": ""}):
            with self.assertRaises(ValueError):
                N.expectation_script(**kwargs)

    def test_get_script_registers_expectation_keys(self):
        with _patched_lookup(return_value=DATA_STATS):
            out = N.get_script("expectation_range", name="Keshavan",
                               role="ML Engineer", company="Acme")
        self.assertIn("$175,000", out)
        with self.assertRaises(ValueError):
            N.get_script("expectation_bogus", name="Keshavan",
                         role="ML Engineer", company="Acme")


class CounterSimulatorTest(unittest.TestCase):
    OFFER = {"base": 160000, "sign_on": 20000, "equity": 100000,
             "level": "L4", "target_level": "L5"}
    BATNA = {"description": "Stay at current role at $190k total",
             "value": 190000}

    def _session(self, scenario="lowball"):
        return N.start_counter_session(dict(self.OFFER), dict(self.BATNA),
                                       scenario=scenario)

    def test_invalid_scenario_raises(self):
        with self.assertRaises(ValueError):
            N.start_counter_session(self.OFFER, self.BATNA,
                                    scenario="not_a_scenario")
        with self.assertRaises(ValueError):
            N.start_counter_session("not-a-dict", self.BATNA)
        with self.assertRaises(ValueError):
            N.start_counter_session(self.OFFER, "not-a-dict")

    def test_alias_accepted(self):
        s = N.start_counter_session(self.OFFER, self.BATNA,
                                    scenario="lowball_anchor")
        self.assertEqual(s["scenario"], "lowball")

    def test_phases_progress_over_rounds(self):
        s = self._session()
        self.assertEqual(s["phase"], "probe")
        N.counter_recruiter_reply(s)  # round 0: opening probe
        self.assertEqual(s["phase"], "probe")
        N.counter_user_reply(s, "The base is below market for this level.")
        self.assertEqual(s["round"], 1)
        self.assertEqual(s["phase"], "probe")
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "Can you share the band for L4?")
        self.assertEqual(s["round"], 2)
        self.assertEqual(s["phase"], "pressure")
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "I am flexible on sign-on versus base.")
        self.assertEqual(s["phase"], "pressure")
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "What is the best you can do?")
        self.assertEqual(s["round"], 4)
        self.assertEqual(s["phase"], "concession")
        reply = N.counter_recruiter_reply(s)
        self.assertTrue(reply)  # concession line renders

    def test_recruiter_references_offer_numbers(self):
        s = self._session()
        for _ in range(4):
            N.counter_recruiter_reply(s)
            N.counter_user_reply(s, "Still too low.")
        last = N.counter_recruiter_reply(s)
        # 160000 * 1.06 rounded to nearest 1000 = 170000
        self.assertIn("$170,000", last)

    def test_keyword_reaction_competing_offer(self):
        s = self._session()
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "I have a competing offer at $210k.")
        self.assertIn("competing_offer", s["flags"])
        self.assertEqual(s["user_anchor"], "$210,000")
        reply = N.counter_recruiter_reply(s)
        self.assertIn("another offer", reply)

    def test_walkaway_flag_detected(self):
        s = self._session()
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "I cannot accept below $195k.")
        self.assertIn("walkaway", s["flags"])
        self.assertEqual(s["user_anchor"], "$195,000")

    def test_deterministic(self):
        def run():
            s = self._session(scenario="competing_offer")
            replies = [N.counter_recruiter_reply(s)]
            for msg in ("Where are they on timeline?",
                        "They are at $210k total.",
                        "Can you match that?"):
                N.counter_user_reply(s, msg)
                replies.append(N.counter_recruiter_reply(s))
            return replies
        self.assertEqual(run(), run())

    def test_transcript_contains_both_sides_and_debrief(self):
        s = self._session()
        N.counter_recruiter_reply(s)
        N.counter_user_reply(s, "The base is below market; I need $185k.")
        N.counter_recruiter_reply(s)
        t = N.counter_transcript(s)
        self.assertIn("Recruiter", t)
        self.assertIn("You", t)
        self.assertIn("Debrief", t)
        self.assertIn("What worked", t)
        self.assertIn("Try next", t)
        self.assertIn("$185,000", t)  # anchor shows up in debrief

    def test_all_scenarios_open(self):
        for scenario in ("lowball", "competing_offer", "exploding_deadline",
                         "level_pushback"):
            s = self._session(scenario=scenario)
            opening = N.counter_recruiter_reply(s)
            self.assertTrue(opening.strip(), scenario)

    def test_empty_user_reply_raises(self):
        s = self._session()
        with self.assertRaises(ValueError):
            N.counter_user_reply(s, "   ")

    def test_invalid_session_raises(self):
        with self.assertRaises(ValueError):
            N.counter_recruiter_reply({})
        with self.assertRaises(ValueError):
            N.counter_user_reply({"nope": 1}, "hi")
        with self.assertRaises(ValueError):
            N.counter_transcript(None)


if __name__ == "__main__":
    unittest.main()
