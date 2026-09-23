"""Integration tests for the batch-67 recruiter modules working together.

Covers the storage-contract seams between recruiter_contacts (list of
profiles), recruiter_threads (list of touches), recruiter_scoring (read-only
analytics), and recruiter_pipeline. All fixture data is fictional.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path


def _isolated():
    d = tempfile.mkdtemp(prefix="candid-rec67-")
    os.environ["CANDID_DATA_DIR"] = d
    # Modules resolve CANDID_DATA_DIR per call (scoring) or via C.DATA_DIR
    # captured at import; force a fresh import of candid.config so DATA_DIR
    # picks up the override.
    import importlib
    import candid.config as C
    importlib.reload(C)
    for mod in ("candid.recruiter_contacts", "candid.recruiter_threads",
                "candid.recruiter_scoring", "candid.recruiter_pipeline"):
        importlib.reload(importlib.import_module(mod))
    from candid import recruiter_contacts as RC
    from candid import recruiter_threads as RT
    from candid import recruiter_scoring as RS
    from candid import recruiter_pipeline as RP
    return d, RC, RT, RS, RP


class RecruiterIntegrationTest(unittest.TestCase):
    def setUp(self):
        import importlib
        self._old_env = os.environ.get("CANDID_DATA_DIR")
        self.d, self.RC, self.RT, self.RS, self.RP = _isolated()

    def tearDown(self):
        # Restore the environment so other test modules in the same pytest
        # process are unaffected by the reload in _isolated().
        import importlib
        import candid.config as C
        if self._old_env is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old_env
        importlib.reload(C)

    def _seed(self):
        self.RC.add("Priya Shah", "Acme", kind="inhouse")
        self.RC.add("Bob Lee", "Acme", kind="agency", agency="TechTalent")

    def test_scoring_reads_contacts_list_format(self):
        # contacts stores a LIST of profiles; scoring must see the kind.
        self._seed()
        self.RT.log_touch("Priya Shah", "email", "intro sent")
        card = self.RS.scorecard("Priya Shah")
        self.assertEqual(card["kind"], "inhouse")
        self.assertEqual(card["total_touches"], 1)
        # in-house bonus of 15 should be reflected in the score
        self.assertGreaterEqual(card["worth_replying"], 15)

    def test_replied_flag_flows_to_response_rate(self):
        self._seed()
        t1 = self.RT.log_touch("Priya Shah", "email", "intro sent")
        self.RT.log_touch("Priya Shah", "linkedin", "follow-up", replied=True)
        self.assertEqual(self.RS.response_rate("Priya Shah"), 0.5)
        # mark_replied updates an existing touch
        self.RT.mark_replied(t1["id"])
        self.assertEqual(self.RS.response_rate("Priya Shah"), 1.0)

    def test_mark_replied_unknown_id(self):
        self._seed()
        with self.assertRaises(self.RT.RecruiterError):
            self.RT.mark_replied(999)

    def test_rank_and_agency_split_use_real_data(self):
        self._seed()
        self.RT.log_touch("Priya Shah", "email", "intro", replied=True)
        self.RT.log_touch("Bob Lee", "email", "cold pitch")
        ranked = self.RS.rank_recruiters()
        self.assertEqual(ranked[0]["recruiter"], "Priya Shah")
        comp = self.RS.agency_vs_inhouse()
        self.assertEqual(comp["inhouse"]["count"], 1)
        self.assertEqual(comp["agency"]["count"], 1)
        self.assertEqual(comp["inhouse"]["avg_response_rate"], 1.0)

    def test_pipeline_stale_uses_thread_last_touch(self):
        self._seed()
        self.RT.log_touch("Bob Lee", "email", "cold pitch", date="2020-01-01")
        stale = self.RP.stale_threads(days=14)
        names = [s["recruiter"] for s in stale]
        self.assertIn("Bob Lee", names)
        # Priya has no touches at all: also stale (missing last_touch counts)
        self.assertIn("Priya Shah", names)

    def test_link_requires_real_tracker_app(self):
        self._seed()
        from candid import tracker as T
        app = T.add("Acme", "ML Engineer", status="applied")
        self.RP.link("Priya Shah", app["id"])
        self.assertEqual(self.RP.for_application(app["id"]), ["Priya Shah"])
        funnel = self.RP.recruiter_funnel("Priya Shah")
        self.assertEqual(funnel["counts"]["applied"], 1)
        self.assertEqual(funnel["total"], 1)


if __name__ == "__main__":
    unittest.main()
