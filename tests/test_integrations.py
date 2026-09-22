"""Tests for candid Gmail + LinkedIn integrations.

No real network calls: the Gmail API layer is exercised through the
message_fetcher test hook and by patching candid.gmail._http_json.
"""
import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import gmail as G  # noqa: E402
from candid import linkedin as L  # noqa: E402


@contextmanager
def temp_config(**overrides):
    """Point config paths at a temp dir for hermetic tests."""
    saved = {k: getattr(C, k) for k in overrides}
    tmp = Path(tempfile.mkdtemp(prefix="candid-test-"))
    mapping = {k: (tmp / v if isinstance(v, str) else v)
               for k, v in overrides.items()}
    for k, v in mapping.items():
        setattr(C, k, v)
    try:
        yield tmp
    finally:
        for k, v in saved.items():
            setattr(C, k, v)


# ---------------------------------------------------------------------------
# Gmail classification / extraction (pure functions)
# ---------------------------------------------------------------------------

class ClassifyTest(unittest.TestCase):
    def test_interview_invite(self):
        kind, conf = G.classify_message(
            "Interview Invitation: Senior Data Scientist @ Acme",
            "Acme Careers <careers@acme.com>",
            "We'd like to invite you to a phone screen next week.")
        self.assertEqual(kind, "interview_invite")
        self.assertGreater(conf, 0.5)

    def test_offer(self):
        kind, conf = G.classify_message(
            "Your offer letter from Globex",
            "HR <hr@globex.com>",
            "Congratulations! Please find your offer package attached.")
        self.assertEqual(kind, "offer")

    def test_rejection(self):
        kind, conf = G.classify_message(
            "Update on your application",
            "noreply@initech.com",
            "Unfortunately we will not be moving forward at this time.")
        self.assertEqual(kind, "rejection")

    def test_recruiter_outreach(self):
        kind, conf = G.classify_message(
            "Exciting ML opportunity at Hooli",
            "Jane Recruiter <jane@hoolistaffing.com>",
            "I came across your profile and wanted to reach out about a role.")
        self.assertEqual(kind, "recruiter_outreach")

    def test_other_ignored(self):
        kind, conf = G.classify_message(
            "Your receipt from Whole Foods", "receipts@wholefoods.com",
            "Thanks for shopping with us.")
        self.assertEqual(kind, "other")
        self.assertEqual(conf, 0.0)

    def test_extract_company_role(self):
        company, role, conf = G.extract_company_role(
            "Interview for Senior Data Scientist — next steps",
            "Acme Recruiting <recruiting@acme.com>", "")
        self.assertEqual(company, "Acme")
        self.assertIn("Senior Data Scientist", role)

    def test_extract_strips_via_linkedin(self):
        company, _, _ = G.extract_company_role(
            "Opportunity", "Jane Doe (Hooli Talent) via LinkedIn <invites@linkedin.com>", "")
        self.assertEqual(company, "Hooli Talent")


# ---------------------------------------------------------------------------
# Gmail Takeout mbox import (fixture mbox — no network, no OAuth)
# ---------------------------------------------------------------------------

def _fixture_mbox(path: Path) -> Path:
    """Write a small Takeout-style mbox with 3 messages."""
    msgs = [
        ("Acme Recruiting <recruiting@acme.com>",
         "Interview Invitation: Senior Data Scientist",
         "<m1@example.com>",
         "Mon, 21 Sep 2026 10:00:00 -0400",
         "We'd like to schedule a phone screen for the Senior Data Scientist role."),
        ("jane@hoolistaffing.com",
         "ML Engineer opportunity at Hooli",
         "<m2@example.com>",
         "Tue, 22 Sep 2026 11:00:00 -0400",
         "Reaching out because your background looks like a great fit for Hooli."),
        ("receipts@wholefoods.com",
         "Your receipt",
         "<m3@example.com>",
         "Wed, 23 Sep 2026 12:00:00 -0400",
         "Thanks for shopping with us."),
    ]
    parts = []
    for sender, subject, mid, date, body in msgs:
        parts.append(
            f"From {sender} {date}\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Message-ID: {mid}\n"
            f"Date: {date}\n"
            f"Content-Type: text/plain; charset=utf-8\n"
            f"\n{body}\n\n")
    path.write_text("".join(parts), encoding="utf-8")
    return path


class MboxParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-mbox-"))
        self.mbox = _fixture_mbox(self.tmp / "takeout.mbox")

    def test_parse_mbox_fields(self):
        msgs = G.parse_mbox(self.mbox)
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["id"], "<m1@example.com>")
        self.assertEqual(msgs[0]["subject"],
                         "Interview Invitation: Senior Data Scientist")
        self.assertIn("phone screen", msgs[0]["body"])
        self.assertTrue(msgs[0]["snippet"])

    def test_iter_mbox_files(self):
        self.assertEqual(G.iter_mbox_files(self.mbox), [self.mbox])
        sub = self.tmp / "takeout-dir"
        sub.mkdir()
        (self.tmp / "takeout.mbox").rename(sub / "a.mbox")
        _fixture_mbox(sub / "b.mbox")
        self.assertEqual(len(G.iter_mbox_files(sub)), 2)
        with self.assertRaises(G.GmailError):
            G.iter_mbox_files(self.tmp / "nope.mbox")
        txt = self.tmp / "note.txt"
        txt.write_text("hi")
        with self.assertRaises(G.GmailError):
            G.iter_mbox_files(txt)

    def test_takeout_guide_exists(self):
        self.assertIn("takeout.google.com", G.TAKEOUT_GUIDE)
        self.assertIn(".mbox", G.TAKEOUT_GUIDE)
        self.assertNotIn("OAuth", G.TAKEOUT_GUIDE)


class MboxImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-gmail-"))
        self.mbox = _fixture_mbox(self.tmp / "takeout.mbox")
        self.props = self.tmp / "proposals.json"
        self.tracker = self.tmp / "tracker.json"

    def test_import_creates_proposals_for_job_mail_only(self):
        res = G.import_mbox(self.mbox, proposals_path=self.props)
        self.assertEqual(res["messages"], 3)
        self.assertEqual(len(res["new_proposals"]), 2)  # receipt is "other"
        kinds = {pr["kind"] for pr in res["new_proposals"]}
        self.assertIn("interview_invite", kinds)
        self.assertIn("recruiter_outreach", kinds)
        for pr in res["new_proposals"]:
            self.assertEqual(pr["status"], "pending")

    def test_import_dedupes_on_second_run(self):
        G.import_mbox(self.mbox, proposals_path=self.props)
        res2 = G.import_mbox(self.mbox, proposals_path=self.props)
        self.assertEqual(res2["new_proposals"], [])
        self.assertEqual(res2["messages"], 3)

    def test_import_max_messages(self):
        res = G.import_mbox(self.mbox, max_messages=1, proposals_path=self.props)
        self.assertEqual(res["messages"], 1)

    def test_confirm_writes_tracker(self):
        G.import_mbox(self.mbox, proposals_path=self.props)
        pending = G.list_proposals(status="pending", path=self.props)
        interview = next(pr for pr in pending if pr["kind"] == "interview_invite")
        rec = G.confirm_proposal(interview["id"], proposals_path=self.props,
                                 tracker_path=self.tracker)
        self.assertEqual(rec["status"], "selected_for_interview")
        self.assertIn("Acme", rec["company"])
        apps = json.loads(self.tracker.read_text())
        self.assertEqual(len(apps), 1)
        with self.assertRaises(G.GmailError):
            G.confirm_proposal(interview["id"], proposals_path=self.props,
                               tracker_path=self.tracker)

    def test_confirm_updates_existing_app(self):
        from candid import tracker as T
        T.add("Acme", "Senior Data Scientist", status="applied", path=self.tracker)
        G.import_mbox(self.mbox, proposals_path=self.props)
        interview = next(pr for pr in G.list_proposals(status="pending", path=self.props)
                         if pr["kind"] == "interview_invite")
        rec = G.confirm_proposal(interview["id"], proposals_path=self.props,
                                 tracker_path=self.tracker)
        self.assertEqual(rec["status"], "selected_for_interview")
        self.assertEqual(len(json.loads(self.tracker.read_text())), 1)

    def test_reject(self):
        G.import_mbox(self.mbox, proposals_path=self.props)
        pid = G.list_proposals(status="pending", path=self.props)[0]["id"]
        G.reject_proposal(pid, path=self.props)
        remaining = G.list_proposals(status="pending", path=self.props)
        self.assertTrue(all(pr["id"] != pid for pr in remaining))

    def test_render_import_summary(self):
        res = G.import_mbox(self.mbox, proposals_path=self.props)
        out = G.render_import_summary(res)
        self.assertIn("3 message", out)
        self.assertIn("confirm", out)


# ---------------------------------------------------------------------------
# LinkedIn export import (fixture ZIP)
# ---------------------------------------------------------------------------

def _fixture_zip(path: Path):
    def w(name, rows, fields):
        buf = io.StringIO()
        wr = csv.DictWriter(buf, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
        return buf.getvalue()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Profile.csv", w("Profile.csv", [{
            "First Name": "Alex", "Last Name": "Rivera",
            "Headline": "Senior Data Scientist | ML & Experimentation",
            "Summary": "Data scientist with 6 years of experience.",
            "Location": "New York, New York, United States",
        }], ["First Name", "Last Name", "Headline", "Summary", "Location"]))
        zf.writestr("Positions.csv", w("Positions.csv", [
            {"Company Name": "Meridian Financial", "Title": "Senior Data Scientist",
             "Description": "Built churn models.\nLed experimentation.",
             "Location": "New York, NY", "Started On": "Jan 2022", "Finished On": "Present"},
            {"Company Name": "Northwind Labs", "Title": "Data Analyst",
             "Description": "Dashboards and KPI reporting.",
             "Location": "Boston, MA", "Started On": "Jun 2019", "Finished On": "Dec 2021"},
        ], ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"]))
        zf.writestr("Skills.csv", w("Skills.csv", [
            {"Name": "Python"}, {"Name": "Machine Learning"}, {"Name": "SQL"},
        ], ["Name"]))
        zf.writestr("Education.csv", w("Education.csv", [{
            "School Name": "State University", "Degree Name": "B.S. Statistics",
            "Start Date": "2015", "End Date": "2019",
        }], ["School Name", "Degree Name", "Start Date", "End Date"]))
        zf.writestr("Email Addresses.csv", w("Email Addresses.csv", [
            {"Email Address": "alex@example.com"},
        ], ["Email Address"]))
    return path


class LinkedInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-li-"))
        self.zip = _fixture_zip(self.tmp / "linkedin-export.zip")
        self.profile_path = self.tmp / "profile.json"

    def test_parse_export(self):
        parsed = L.parse_export(self.zip)
        self.assertEqual(parsed["name"], "Alex Rivera")
        self.assertIn("Senior Data Scientist", parsed["headline"])
        self.assertEqual(len(parsed["experience"]), 2)
        self.assertEqual(parsed["experience"][0]["company"], "Meridian Financial")
        self.assertEqual(len(parsed["skills_raw"]), 3)
        self.assertEqual(parsed["education"][0]["school"], "State University")

    def test_to_profile_schema(self):
        prof = L.to_profile(L.parse_export(self.zip))
        self.assertIn("python", prof["skills"])
        self.assertIn(prof["seniority"], ("mid", "senior"))
        self.assertGreater(prof["years_experience"], 2)

    def test_import_replace(self):
        res = L.import_zip(self.zip, mode="replace", out_path=self.profile_path)
        self.assertEqual(res["mode"], "replace")
        self.assertEqual(res["positions"], 2)
        saved = json.loads(self.profile_path.read_text())
        self.assertEqual(saved["name"], "Alex Rivera")

    def test_import_merge_dedupes(self):
        # seed a profile at the (patched) PROFILE_PATH, then merge the same
        # export → no duplicate entries
        with temp_config(PROFILE_PATH="profile.json") as tmp:
            base = {"name": "Alex Rivera", "headline": "", "location": "",
                    "summary": "", "skills": ["python"], "experience": [
                        {"title": "Senior Data Scientist",
                         "company": "Meridian Financial",
                         "dates": "Jan 2022 – Present", "bullets": []}],
                    "education": [], "years_experience": 4.5,
                    "seniority": "senior", "source_files": ["resume.pdf"]}
            (tmp / "profile.json").write_text(json.dumps(base))
            res = L.import_zip(self.zip, mode="merge",
                               out_path=self.tmp / "merged.json")
            self.assertEqual(res["mode"], "merge")
            saved = json.loads((self.tmp / "merged.json").read_text())
            meridian = [e for e in saved["experience"]
                        if e["company"] == "Meridian Financial"]
            self.assertEqual(len(meridian), 1)  # deduped, not doubled
            self.assertIn("linkedin_export", saved["source_files"])
            self.assertIn("python", saved["skills"])

    def test_rejects_non_zip(self):
        bad = self.tmp / "notazip.txt"
        bad.write_text("hello")
        with self.assertRaises(L.LinkedInError):
            L.parse_export(bad)

    def test_rejects_missing_file(self):
        with self.assertRaises(L.LinkedInError):
            L.parse_export(self.tmp / "missing.zip")

    def test_guide_mentions_no_scraping(self):
        self.assertIn("Terms of Service", L.EXPORT_GUIDE)
        self.assertIn("Get a copy of your data", L.EXPORT_GUIDE)


if __name__ == "__main__":
    unittest.main()
