"""Tests for candid.recruiter_threads. Fictional fixture data only."""

import json
import unittest
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import recruiter_threads as RT


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.threads = Path(self.td.name) / "recruiter_threads.json"
        self.recruiters = Path(self.td.name) / "recruiters.json"
        # Fictional recruiter profiles (worker A owns this file; we only read it).
        self.recruiters.write_text(json.dumps([
            {"name": "Jane Quill", "agency": "Quill Talent"},
            {"name": "Marcus Bell", "agency": "Bell Search"},
        ]), encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def kw(self, **over):
        base = {"path": self.threads, "recruiters_path": self.recruiters}
        base.update(over)
        return base


class TouchLogTest(_Base):
    def test_log_touch_defaults_to_today(self):
        t = RT.log_touch("Jane Quill", "email", "Intro call about ML role",
                         **self.kw())
        self.assertEqual(t["recruiter"], "Jane Quill")
        self.assertEqual(t["channel"], "email")
        self.assertEqual(t["summary"], "Intro call about ML role")
        self.assertRegex(t["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(self.threads.exists())

    def test_log_touch_explicit_date_and_role_company(self):
        t = RT.log_touch("Jane Quill", "phone", "Screening call",
                         date="2026-09-10", role="ML Engineer",
                         company="Acme Corp", **self.kw())
        self.assertEqual(t["date"], "2026-09-10")
        self.assertEqual(t["role"], "ML Engineer")
        self.assertEqual(t["company"], "Acme Corp")

    def test_thread_chronological_order(self):
        RT.log_touch("Jane Quill", "email", "Second", date="2026-09-12", **self.kw())
        RT.log_touch("Jane Quill", "email", "First", date="2026-09-01", **self.kw())
        RT.log_touch("Marcus Bell", "email", "Other recruiter", date="2026-09-05",
                     **self.kw())
        hist = RT.thread("Jane Quill", **self.kw())
        self.assertEqual([t["summary"] for t in hist], ["First", "Second"])

    def test_last_touch_returns_most_recent(self):
        RT.log_touch("Jane Quill", "email", "Older", date="2026-09-01", **self.kw())
        RT.log_touch("Jane Quill", "linkedin", "Newer", date="2026-09-20", **self.kw())
        last = RT.last_touch("Jane Quill", **self.kw())
        self.assertEqual(last["summary"], "Newer")
        self.assertEqual(last["channel"], "linkedin")

    def test_last_touch_none_when_empty(self):
        self.assertIsNone(RT.last_touch("Jane Quill", **self.kw()))

    def test_invalid_channel_rejected(self):
        for bad in ("sms", "carrier-pigeon", ""):
            with self.assertRaises(RT.RecruiterError):
                RT.log_touch("Jane Quill", bad, "x", **self.kw())

    def test_channel_case_insensitive(self):
        t = RT.log_touch("Jane Quill", "EMAIL", "x", **self.kw())
        self.assertEqual(t["channel"], "email")

    def test_valid_channels_accepted(self):
        for ch in RT.CHANNELS:
            t = RT.log_touch("Jane Quill", ch, f"via {ch}", **self.kw())
            self.assertEqual(t["channel"], ch)

    def test_unknown_recruiter_rejected(self):
        with self.assertRaises(RT.RecruiterError):
            RT.log_touch("Nobody Real", "email", "x", **self.kw())
        with self.assertRaises(RT.RecruiterError):
            RT.thread("Nobody Real", **self.kw())

    def test_missing_recruiters_file_allows_any_name(self):
        kw = {"path": self.threads,
              "recruiters_path": Path(self.td.name) / "nope.json"}
        t = RT.log_touch("New Person", "phone", "Cold call", **kw)
        self.assertEqual(t["recruiter"], "New Person")

    def test_blank_summary_rejected(self):
        with self.assertRaises(RT.RecruiterError):
            RT.log_touch("Jane Quill", "email", "   ", **self.kw())

    def test_ids_increment(self):
        a = RT.log_touch("Jane Quill", "email", "one", **self.kw())
        b = RT.log_touch("Jane Quill", "email", "two", **self.kw())
        self.assertEqual(b["id"], a["id"] + 1)


class DuplicateOutreachTest(_Base):
    def test_two_recruiters_same_role_flagged(self):
        RT.log_touch("Jane Quill", "email", "Pitched ML role",
                     role="ML Engineer", company="Acme Corp", **self.kw())
        RT.log_touch("Marcus Bell", "linkedin", "Pitched ML role",
                     role="ML Engineer", company="Acme Corp", **self.kw())
        groups = RT.same_role_pitches("ML Engineer", "Acme Corp", **self.kw())
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(sorted(g["recruiters"]), ["Jane Quill", "Marcus Bell"])
        self.assertEqual(len(g["pitches"]), 2)
        self.assertTrue(all(isinstance(p, tuple) and len(p) == 2
                            for p in g["pitches"]))

    def test_single_recruiter_not_flagged(self):
        RT.log_touch("Jane Quill", "email", "Pitched ML role",
                     role="ML Engineer", company="Acme Corp", **self.kw())
        RT.log_touch("Jane Quill", "email", "Follow-up",
                     role="ML Engineer", company="Acme Corp", **self.kw())
        groups = RT.same_role_pitches("ML Engineer", "Acme Corp", **self.kw())
        self.assertEqual(groups, [])

    def test_no_matches_empty(self):
        self.assertEqual(RT.same_role_pitches("ML Engineer", "Acme", **self.kw()),
                         [])

    def test_normalization_ignores_case_punctuation_whitespace(self):
        RT.log_touch("Jane Quill", "email", "Pitched",
                     role="Machine-Learning  Engineer!", company="Acme-Corp",
                     **self.kw())
        RT.log_touch("Marcus Bell", "email", "Pitched",
                     role="machine learning engineer", company="acme corp",
                     **self.kw())
        groups = RT.same_role_pitches("MACHINE LEARNING ENGINEER", "ACME CORP",
                                      **self.kw())
        self.assertEqual(len(groups), 1)

    def test_different_company_not_grouped(self):
        RT.log_touch("Jane Quill", "email", "Pitched",
                     role="ML Engineer", company="Acme Corp", **self.kw())
        RT.log_touch("Marcus Bell", "email", "Pitched",
                     role="ML Engineer", company="Beta Inc", **self.kw())
        self.assertEqual(RT.same_role_pitches("ML Engineer", "Acme Corp",
                                              **self.kw()), [])

    def test_summary_fallback_when_role_company_unset(self):
        RT.log_touch("Jane Quill", "email",
                     "Pitched the Senior ML Engineer role at Acme Corp",
                     **self.kw())
        RT.log_touch("Marcus Bell", "email",
                     "Also pitching Senior ML Engineer at Acme Corp", **self.kw())
        groups = RT.same_role_pitches("Senior ML Engineer", "Acme Corp",
                                      **self.kw())
        self.assertEqual(len(groups), 1)


class GmailProposalTest(unittest.TestCase):
    def test_company_from_subject_at_pattern(self):
        msgs = [{"from_name": "Jane Quill", "from_email": "jane@quilltalent.com",
                 "subject": "Exciting Senior ML Engineer role at Acme Corp",
                 "snippet": "Hi, I came across your profile", "date": "2026-09-01"}]
        out = RT.propose_from_gmail(msgs)
        self.assertEqual(out[0]["company"], "Acme Corp")
        self.assertTrue(out[0]["company_guess"])
        self.assertEqual(out[0]["company_source"], "subject")
        self.assertEqual(out[0]["channel"], "email")

    def test_company_from_email_domain_fallback(self):
        msgs = [{"from_name": "Marcus Bell", "from_email": "marcus@bellsearch.io",
                 "subject": "Quick intro", "snippet": "reaching out",
                 "date": "2026-09-02"}]
        out = RT.propose_from_gmail(msgs)
        self.assertEqual(out[0]["company"], "Bellsearch")
        self.assertTrue(out[0]["company_guess"])
        self.assertEqual(out[0]["company_source"], "email_domain")

    def test_generic_domain_yields_no_guess(self):
        msgs = [{"from_name": "Jane Quill", "from_email": "jane.quill@gmail.com",
                 "subject": "Hello", "snippet": "just saying hi",
                 "date": "2026-09-03"}]
        out = RT.propose_from_gmail(msgs)
        self.assertEqual(out[0]["company"], "")
        self.assertFalse(out[0]["company_guess"])

    def test_name_falls_back_to_email(self):
        msgs = [{"from_name": "", "from_email": "jane@quilltalent.com",
                 "subject": "Hi", "snippet": "hi", "date": ""}]
        out = RT.propose_from_gmail(msgs)
        self.assertEqual(out[0]["name"], "jane@quilltalent.com")

    def test_empty_input(self):
        self.assertEqual(RT.propose_from_gmail([]), [])
        self.assertEqual(RT.propose_from_gmail(None), [])

    def test_propose_writes_nothing(self):
        # propose_from_gmail must be pure: no new files, no touched files.
        with tempfile.TemporaryDirectory() as td:
            before = {str(p) for p in Path(td).rglob("*")}
            msgs = [{"from_name": "Jane Quill",
                     "from_email": "jane@quilltalent.com",
                     "subject": "Role at Acme Corp", "snippet": "hello",
                     "date": "2026-09-01"}]
            RT.propose_from_gmail(msgs)
            after = {str(p) for p in Path(td).rglob("*")}
            self.assertEqual(before, after)
        # and it must not write into the real data dir either
        from candid import config as C
        data_dir = Path(C.DATA_DIR)
        files = set()
        if data_dir.exists():
            files = {p.name for p in data_dir.iterdir()}
        RT.propose_from_gmail(msgs)
        after2 = {p.name for p in data_dir.iterdir()} if data_dir.exists() else set()
        self.assertEqual(files, after2)


if __name__ == "__main__":
    unittest.main()
