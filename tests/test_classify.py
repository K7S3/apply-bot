"""Tests for the recruiter message classifier (candid/classify.py).

Covers: the three buckets (direct outreach, agency outreach, interview
invites), ambiguous mail landing in "unsure" (never forced into a wrong
bucket), reason output, invite-to-proposal routing through the existing
confirm/reject flow, proposal dedupe, and a CLI smoke test.

Every name, company, domain, and address in the fixtures is fictional.

Run: CANDID_DATA_DIR=/tmp/candid-test-classify python3 -m unittest discover -s tests
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-classify"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import classify as CL  # noqa: E402
from candid import config as C  # noqa: E402
from candid import gmail as G  # noqa: E402
from candid import tracker as T  # noqa: E402


# ---------------------------------------------------------------------------
# fictional fixtures
# ---------------------------------------------------------------------------

DIRECT = (
    "Jane Park <jane.park@novacorp.com>",
    "Opportunity on my team at NovaCorp",
    "direct1@example.com",
    "Hi Alex,\n\n"
    "I'm the hiring manager for the Data Science team at NovaCorp, and I'd "
    "love to chat about an open role on my team. Your background in ML looks "
    "like a great fit.\n\n"
    "Best,\nJane",
)

AGENCY = (
    "Mike Torres <mike@brightstaffing.com>",
    "Hot Requirement: Senior Data Scientist - Contract (NYC)",
    "agency1@example.com",
    "Hi,\n\n"
    "My client in New York has an urgent contract opening for a Senior Data "
    "Scientist. This is a 12-month contract, C2C or W2, at $95/hr. If you're "
    "interested, please send your resume.\n\n"
    "Thanks,\nMike",
)

INVITE = (
    "Acme Recruiting <recruiting@acme.com>",
    "Interview Invitation: Senior Data Scientist",
    "invite1@example.com",
    "Hi Alex,\n\n"
    "We'd like to invite you to a phone screen for the Senior Data "
    "Scientist role. Please share your availability next week - you can "
    "also grab a time directly here: https://calendly.com/acme-recruiting/chat\n\n"
    "Best,\nAcme Recruiting",
)

DIGEST = (
    "JobDigest <jobs@jobdigest.example>",
    "Your weekly job digest: 12 new Data Scientist roles",
    "digest1@example.com",
    "Hi Alex,\n\n"
    "Here are this week's top picks for Data Scientist roles in New York:\n"
    "1. Senior Data Scientist at Globex\n"
    "2. ML Engineer at Initech\n\n"
    "Happy job hunting!",
)

# Single weak scheduling mention from a company-side sender: an intro call,
# not an interview invite.
INTRO_CALL = (
    "Jane Park <jane.park@novacorp.com>",
    "Quick intro",
    "intro1@example.com",
    "Hi Alex,\n\n"
    "I'm a data science manager at NovaCorp. Would love to schedule a brief "
    "call to discuss an opening on my team.\n\n"
    "Best,\nJane",
)

# Conflicting signals: agency domain + "my client", but also "hiring manager".
CONFLICT = (
    "Sara Kim <sara@peakstaffing.com>",
    "Data Scientist opening",
    "conflict1@example.com",
    "Hi,\n\n"
    "I'm the hiring manager working with my client on a data scientist "
    "opening. Let me know if you'd like details.\n\n"
    "Thanks,\nSara",
)


def _mbox(*messages) -> str:
    parts = []
    for i, (sender, subject, mid, body) in enumerate(messages):
        parts.append(
            f"From sender{i}@example.com Mon Sep 21 1{i}:00:00 2026\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Message-ID: <{mid}>\n"
            f"Date: Mon, 21 Sep 2026 1{i}:00:00 -0400\n"
            f"\n{body}\n"
        )
    return "".join(parts)


class ClassifyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-classify-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_mbox(self, *messages) -> Path:
        p = self.tmp / "in.mbox"
        p.write_text(_mbox(*messages), encoding="utf-8")
        return p

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# bucket classification
# ---------------------------------------------------------------------------

class BucketTest(unittest.TestCase):
    def _classify(self, fixture):
        sender, subject, _, body = fixture
        return CL.classify_recruiter(sender, subject, body)

    def test_direct_outreach(self):
        bucket, reasons = self._classify(DIRECT)
        self.assertEqual(bucket, "direct_outreach")
        self.assertTrue(reasons)
        self.assertTrue(any("hiring manager" in r for r in reasons))

    def test_agency_outreach(self):
        bucket, reasons = self._classify(AGENCY)
        self.assertEqual(bucket, "agency_outreach")
        self.assertTrue(reasons)
        self.assertTrue(any("staffing/recruiting firm" in r for r in reasons))
        self.assertTrue(any("client" in r for r in reasons))

    def test_interview_invite(self):
        bucket, reasons = self._classify(INVITE)
        self.assertEqual(bucket, "interview_invite")
        self.assertTrue(reasons)
        joined = " ".join(reasons)
        self.assertIn("scheduling link", joined)
        self.assertIn("availability", joined)

    def test_ambiguous_newsletter_is_unsure(self):
        bucket, reasons = self._classify(DIGEST)
        self.assertEqual(bucket, "unsure")
        self.assertTrue(reasons)

    def test_single_weak_scheduling_is_not_an_invite(self):
        # One "schedule a call" in first-touch outreach is an intro chat.
        bucket, reasons = self._classify(INTRO_CALL)
        self.assertEqual(bucket, "direct_outreach")
        self.assertTrue(any("single weak" in r or "my team" in r
                            for r in reasons))

    def test_conflicting_signals_are_unsure(self):
        bucket, reasons = self._classify(CONFLICT)
        self.assertEqual(bucket, "unsure")
        self.assertTrue(any("conflicting" in r for r in reasons))

    def test_every_bucket_has_reasons(self):
        for fixture in (DIRECT, AGENCY, INVITE, DIGEST, INTRO_CALL, CONFLICT):
            bucket, reasons = self._classify(fixture)
            self.assertIn(bucket, CL.BUCKETS)
            self.assertTrue(reasons, f"no reasons for {bucket}")

    def test_interview_beats_sender_type(self):
        # An interview invite from an agency recruiter is still an
        # interview invite (scheduling intent wins).
        sender = "Mike Torres <mike@brightstaffing.com>"
        subject = "Interview Invitation: Senior Data Scientist"
        body = ("Hi, my client would like to schedule a phone screen. "
                "Please share your availability: calendly.com/brightstaffing/x")
        bucket, reasons = CL.classify_recruiter(sender, subject, body)
        self.assertEqual(bucket, "interview_invite")
        self.assertTrue(any("agency" in r for r in reasons))


# ---------------------------------------------------------------------------
# mbox driver + proposal routing
# ---------------------------------------------------------------------------

class ClassifyMboxTest(ClassifyBase):
    def test_classify_mbox_buckets_and_proposals(self):
        mbox = self.write_mbox(DIRECT, AGENCY, INVITE, DIGEST)
        res = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        self.assertEqual(res["messages"], 4)
        self.assertEqual(len(res["buckets"]["direct_outreach"]), 1)
        self.assertEqual(len(res["buckets"]["agency_outreach"]), 1)
        self.assertEqual(len(res["buckets"]["interview_invite"]), 1)
        self.assertEqual(len(res["buckets"]["unsure"]), 1)
        # only the interview invite becomes a proposal
        self.assertEqual(len(res["new_proposals"]), 1)
        p = res["new_proposals"][0]
        self.assertEqual(p["kind"], "interview_invite")
        self.assertEqual(p["status"], "pending")
        self.assertEqual(p["company"], "Acme")
        self.assertEqual(p["role"], "Senior Data Scientist")
        self.assertTrue(p["classify_reasons"])

    def test_proposals_go_through_confirm_flow(self):
        mbox = self.write_mbox(INVITE)
        res = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        pid = res["new_proposals"][0]["id"]
        # nothing touches the tracker before confirm
        self.assertEqual(T.list_apps(path=C.TRACKER_PATH), [])
        rec = G.confirm_proposal(pid, proposals_path=C.GMAIL_PROPOSALS_PATH,
                                 tracker_path=C.TRACKER_PATH)
        self.assertEqual(rec["status"], "selected_for_interview")
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(T.list_apps(path=C.TRACKER_PATH)[0]["id"], rec["id"])

    def test_rerun_dedupes_invites(self):
        mbox = self.write_mbox(INVITE)
        first = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        second = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        self.assertEqual(len(first["new_proposals"]), 1)
        self.assertEqual(len(second["new_proposals"]), 0)
        self.assertEqual(second["skipped_duplicates"], 1)
        self.assertEqual(len(G.list_proposals(path=C.GMAIL_PROPOSALS_PATH)), 1)

    def test_dedupes_against_import_mbox_proposals(self):
        mbox = self.write_mbox(INVITE)
        G.import_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        res = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        self.assertEqual(len(res["new_proposals"]), 0)
        self.assertEqual(res["skipped_duplicates"], 1)

    def test_missing_mbox_raises(self):
        with self.assertRaises(G.GmailError):
            CL.classify_mbox(self.tmp / "nope.mbox",
                             proposals_path=C.GMAIL_PROPOSALS_PATH)

    def test_render_lists_buckets_with_reasons(self):
        mbox = self.write_mbox(DIRECT, INVITE, DIGEST)
        res = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        out = CL.render_classify_summary(res)
        self.assertIn("Direct outreach", out)
        self.assertIn("Interview invites", out)
        self.assertIn("Unsure", out)
        self.assertIn("why:", out)
        self.assertIn("pending proposal", out)


# ---------------------------------------------------------------------------
# draft_proposals (gmail.py helper)
# ---------------------------------------------------------------------------

class DraftProposalsTest(ClassifyBase):
    def test_unknown_kind_rejected(self):
        with self.assertRaises(G.GmailError):
            G.draft_proposals([], kind="bogus",
                              proposals_path=C.GMAIL_PROPOSALS_PATH)

    def test_reject_proposal_flow_still_works(self):
        mbox = self.write_mbox(INVITE)
        res = CL.classify_mbox(mbox, proposals_path=C.GMAIL_PROPOSALS_PATH)
        pid = res["new_proposals"][0]["id"]
        G.reject_proposal(pid, path=C.GMAIL_PROPOSALS_PATH)
        self.assertEqual(G.list_proposals(status="pending",
                                          path=C.GMAIL_PROPOSALS_PATH), [])
        self.assertEqual(T.list_apps(path=C.TRACKER_PATH), [])


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class ClassifyCLITest(ClassifyBase):
    def test_classify_command(self):
        mbox = self.write_mbox(DIRECT, AGENCY, INVITE, DIGEST)
        code, out, err = self.run_cli(
            ["gmail", "classify", "--mbox", str(mbox)])
        self.assertEqual(code, 0, err)
        for label in ("Direct outreach", "Agency / third-party recruiter",
                      "Interview invites / scheduling", "Unsure"):
            self.assertIn(label, out)
        self.assertIn("pending proposal", out)
        # the invite is confirmable through the normal flow
        code, out, err = self.run_cli(["gmail", "confirm", "1"])
        self.assertEqual(code, 0, err)
        apps = T.list_apps(path=C.TRACKER_PATH)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["status"], "selected_for_interview")

    def test_classify_requires_mbox(self):
        code, out, err = self.run_cli(["gmail", "classify"])
        self.assertEqual(code, 1)
        self.assertIn("classify --mbox", err)
        self.assertIn("Next:", err)

    def test_classify_help(self):
        code, out, err = self.run_cli(["gmail", "classify", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--mbox", out)


if __name__ == "__main__":
    unittest.main()
