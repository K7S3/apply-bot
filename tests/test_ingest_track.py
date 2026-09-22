"""Tests for candid ingestion + tracking + discovery + salary.

Covers: profile.py (LinkedIn-style text, experience dedupe/merge,
validate_profile), jobs.py (recency filter, min-score gate, cross-source
dedupe, exclude_ids), tracker.py (duplicate-add warning, CSV export,
search), nudges.py (interview_soon), gmail.py (classification kinds,
multipart, proposal dedupe), linkedin.py (position bullets, endorsements),
salary.py (LCA variant hardening, aggregate_by_title).

Run: CANDID_DATA_DIR=/tmp/candid-test-ingest python3 -m unittest discover -s tests -v
"""
import csv
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-ingest"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import gmail as G  # noqa: E402
from candid import jobs as J  # noqa: E402
from candid import linkedin as L  # noqa: E402
from candid import nudges as N  # noqa: E402
from candid import profile as P  # noqa: E402
from candid import salary as S  # noqa: E402
from candid import tracker as T  # noqa: E402


def _temp_paths():
    td = tempfile.TemporaryDirectory()
    base = Path(td.name)
    return td, {
        "tracker": base / "tracker.json",
        "proposals": base / "gmail_proposals.json",
        "db": base / "salary.db",
        "csv": base / "export.csv",
        "mbox": base / "takeout.mbox",
        "zip": base / "linkedin.zip",
    }


# ---------------------------------------------------------------------------
# profile: LinkedIn-style plain text onboarding
# ---------------------------------------------------------------------------

LINKEDIN_STYLE_TEXT = """\
Alex Rivera
Senior Data Scientist | Python, Machine Learning, SQL
New York, NY

Experience
Senior Data Scientist
Meridian Financial · Full-time
Jan 2021 - Present · 5 yrs 9 mos
New York, New York
- Built ranking models with Python and TensorFlow
- Cut serving latency 30% with Spark pipelines

Data Analyst
Globex Corp · Contract
Jun 2019 - Dec 2020 · 1 yr 7 mos
- Dashboards in Tableau and SQL

Lead Data Scientist at Initech, Mar 2018 - May 2019
- Led a team of four analysts
"""


class LinkedInStyleOnboardingTest(unittest.TestCase):
    def test_multiline_headers(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])
        self.assertEqual(prof["name"], "Alex Rivera")
        self.assertEqual(prof["location"], "New York, NY")
        exp = prof["experience"]
        self.assertEqual(len(exp), 3)
        self.assertEqual(exp[0]["title"], "Senior Data Scientist")
        self.assertEqual(exp[0]["company"], "Meridian Financial")
        self.assertIn("Jan 2021", exp[0]["dates"])
        self.assertEqual(len(exp[0]["bullets"]), 2)
        self.assertNotIn("New York", " ".join(exp[0]["bullets"]))

    def test_title_at_company_single_line(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])
        third = prof["experience"][2]
        self.assertEqual(third["title"], "Lead Data Scientist")
        self.assertEqual(third["company"], "Initech")

    def test_employment_type_stripped(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])
        self.assertEqual(prof["experience"][1]["company"], "Globex Corp")

    def test_skills_from_bullets_when_no_skills_section(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])  # no Skills section
        self.assertIn("python", prof["skills"])
        self.assertIn("sql", prof["skills"])

    def test_domains_inferred(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])
        self.assertIn("data science", prof["domains"])


class ExperienceDedupeTest(unittest.TestCase):
    RESUME = """\
Alex Rivera
Senior Data Scientist
Experience
Senior Data Scientist — Meridian Financial, Jan 2021 - Present
- Built ranking models with Python
"""
    LINKEDIN = """\
Alex Rivera
Experience
Senior Data Scientist
Meridian Financial · Full-time
Jan 2021 - Present
- Cut serving latency 30%
"""

    def test_resume_linkedin_overlap_merges(self):
        prof = P.build_profile([self.RESUME, self.LINKEDIN])
        self.assertEqual(len(prof["experience"]), 1)
        entry = prof["experience"][0]
        self.assertEqual(entry["title"], "Senior Data Scientist")
        self.assertEqual(entry["company"], "Meridian Financial")
        bullets = " ".join(entry["bullets"]).lower()
        self.assertIn("ranking models", bullets)
        self.assertIn("latency", bullets)

    def test_distinct_roles_not_merged(self):
        prof = P.build_profile([self.RESUME,
                                "Alex Rivera\nExperience\nData Analyst — Globex, 2019 - 2020\n- SQL\n"])
        self.assertEqual(len(prof["experience"]), 2)


class ValidateProfileTest(unittest.TestCase):
    def test_empty_profile_reports_errors(self):
        problems = P.validate_profile({"name": "", "skills": [],
                                       "experience": []})
        fields = {p["field"] for p in problems if p["severity"] == "error"}
        self.assertEqual(fields, {"name", "skills", "experience"})

    def test_good_profile_has_no_errors(self):
        prof = P.build_profile([LINKEDIN_STYLE_TEXT])
        errors = [p for p in P.validate_profile(prof) if p["severity"] == "error"]
        self.assertEqual(errors, [])

    def test_problems_have_shape(self):
        for p in P.validate_profile({}):
            self.assertIn("field", p)
            self.assertIn("severity", p)
            self.assertIn("message", p)
            self.assertIn(p["severity"], ("error", "warning"))


# ---------------------------------------------------------------------------
# jobs: recency, exclude_ids, phrase relevance, min-score gate, x-source dedupe
# ---------------------------------------------------------------------------

def _job(sid, title, company, posted_at, desc="data scientist python"):
    return {"source": "t", "source_id": sid, "title": title, "company": company,
            "location": "New York, NY", "remote": False, "url": "",
            "description": desc, "salary_text": "", "posted_at": posted_at}


class RecencyFilterTest(unittest.TestCase):
    def test_days_filters_old_postings(self):
        recent = (date.today() - timedelta(days=2)).isoformat()
        old = (date.today() - timedelta(days=60)).isoformat()
        jobs = [_job("t:new", "Data Scientist", "Acme", recent),
                _job("t:old", "Data Scientist", "Acme", old)]
        out = J.filter_jobs(jobs, "data scientist", "New York", days=7)
        self.assertEqual([j["source_id"] for j in out], ["t:new"])

    def test_unparseable_dates_are_kept(self):
        jobs = [_job("t:x", "Data Scientist", "Acme", "sometime last week")]
        out = J.filter_jobs(jobs, "data scientist", "New York", days=7)
        self.assertEqual(len(out), 1)

    def test_no_days_keeps_everything(self):
        old = (date.today() - timedelta(days=300)).isoformat()
        jobs = [_job("t:old", "Data Scientist", "Acme", old)]
        out = J.filter_jobs(jobs, "data scientist", "New York")
        self.assertEqual(len(out), 1)

    def test_epoch_posted_at(self):
        import time
        recent_epoch = str(int(time.time()) - 86400)
        jobs = [_job("t:e", "Data Scientist", "Acme", recent_epoch)]
        out = J.filter_jobs(jobs, "data scientist", "New York", days=7)
        self.assertEqual(len(out), 1)


class ExcludeIdsTest(unittest.TestCase):
    def test_exclude_ids_skips_source_ids(self):
        recent = date.today().isoformat()
        jobs = [_job("t:1", "Data Scientist", "Acme", recent),
                _job("t:2", "Data Scientist", "Globex", recent)]
        out = J.filter_jobs(jobs, "data scientist", "New York",
                            exclude_ids={"t:1"})
        self.assertEqual([j["source_id"] for j in out], ["t:2"])

    def test_exclude_ids_defaults_empty(self):
        recent = date.today().isoformat()
        jobs = [_job("t:1", "Data Scientist", "Acme", recent)]
        out = J.filter_jobs(jobs, "data scientist", "New York")
        self.assertEqual(len(out), 1)


class PhraseRelevanceTest(unittest.TestCase):
    def test_exact_phrase_title_ranks_first(self):
        jobs = [_job("t:phrase", "Data Scientist", "Acme", ""),
                _job("t:tokens", "Scientist, Data Platform", "Acme", "")]
        out = J.filter_jobs(jobs, "data scientist", "New York")
        self.assertEqual(out[0]["source_id"], "t:phrase")


PROFILE_MINI = {"name": "Alex Rivera",
                "skills": ["python", "machine learning", "sql"],
                "seniority": "senior", "years_experience": 6.5,
                "experience": [{"company": "Meridian", "title": "Senior Data Scientist"}]}


class CurateGateTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _temp_paths()
        self.orig_data, self.orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = self.p["tracker"]

    def tearDown(self):
        C.DATA_DIR, C.TRACKER_PATH = self.orig_data, self.orig_tracker
        self.td.cleanup()

    def _adapters(self, payloads):
        return patch.dict(J.ADAPTERS,
                          {k: (lambda pl: (lambda: pl))(pl)
                           for k, pl in payloads.items()}, clear=True)

    def _curate_job(self, sid, company="Acme Corp", title="Senior Data Scientist"):
        return _job(sid, title, company, date.today().isoformat(),
                    desc="Python and machine learning for our ML platform. SQL required.")

    def test_min_score_gate_stashes_below_threshold(self):
        with self._adapters({"fake": [self._curate_job("fake:1")]}):
            res = J.curate(PROFILE_MINI, "data scientist", "New York",
                           sources=["fake"], min_score=101)
        self.assertEqual(len(res["added"]), 0)
        self.assertEqual(res["skipped_low_score"], 1)
        self.assertEqual(len(T.list_apps(path=self.p["tracker"])), 0)
        import json
        state = json.loads((C.DATA_DIR / "jobs.json").read_text())
        self.assertEqual(len(state["skipped_low_score"]), 1)
        self.assertEqual(state["skipped_low_score"][0]["source_id"], "fake:1")

    def test_min_score_zero_adds_as_before(self):
        with self._adapters({"fake": [self._curate_job("fake:1")]}):
            res = J.curate(PROFILE_MINI, "data scientist", "New York",
                           sources=["fake"])
        self.assertEqual(len(res["added"]), 1)
        self.assertEqual(res.get("skipped_low_score", 0), 0)

    def test_cross_source_dedupe_by_normalized_key(self):
        with self._adapters({"a": [self._curate_job("a:1", company="Acme Corp")],
                             "b": [self._curate_job("b:2", company="acme corp. ")]}):
            res = J.curate(PROFILE_MINI, "data scientist", "New York",
                           sources=["a", "b"])
        self.assertEqual(len(res["added"]), 1)
        self.assertEqual(len(T.list_apps(path=self.p["tracker"])), 1)

    def test_norm_key_dedupe_against_existing_tracker_entry(self):
        T.add("Acme Corp.", "Senior Data Scientist", path=self.p["tracker"])
        with self._adapters({"a": [self._curate_job("a:1", company="ACME CORP")]}):
            res = J.curate(PROFILE_MINI, "data scientist", "New York",
                           sources=["a"])
        self.assertEqual(len(res["added"]), 0)
        self.assertEqual(res["skipped"], 1)


# ---------------------------------------------------------------------------
# tracker: duplicate-add warning, CSV export, search, next-action hints
# ---------------------------------------------------------------------------

class TrackerDuplicateTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _temp_paths()

    def tearDown(self):
        self.td.cleanup()

    def test_duplicate_add_returns_existing_with_flag(self):
        first = T.add("Acme", "Data Scientist", path=self.p["tracker"])
        second = T.add("acme", "data scientist", path=self.p["tracker"])
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(T.list_apps(path=self.p["tracker"])), 1)

    def test_first_add_has_no_duplicate_flag(self):
        rec = T.add("Acme", "Data Scientist", path=self.p["tracker"])
        self.assertNotIn("duplicate", rec)

    def test_csv_export_round_trip(self):
        T.add("Acme", "Data Scientist", notes="great, \"quoted\" fit",
              path=self.p["tracker"])
        T.add("Globex", "ML Engineer", status="applied", path=self.p["tracker"])
        dest = T.export_csv(self.p["csv"], path=self.p["tracker"])
        self.assertTrue(dest.exists())
        with open(dest, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        by_company = {r["company"]: r for r in rows}
        self.assertEqual(by_company["Acme"]["role"], "Data Scientist")
        self.assertIn("quoted", by_company["Acme"]["notes"])
        self.assertEqual(by_company["Globex"]["status"], "applied")

    def test_search(self):
        T.add("Acme Corp", "Data Scientist", notes="referral from Priya",
              path=self.p["tracker"])
        T.add("Globex", "ML Engineer", path=self.p["tracker"])
        self.assertEqual(len(T.search("acme", path=self.p["tracker"])), 1)
        self.assertEqual(len(T.search("priya", path=self.p["tracker"])), 1)
        self.assertEqual(len(T.search("ENGINEER", path=self.p["tracker"])), 1)
        self.assertEqual(T.search("nope-xyz", path=self.p["tracker"]), [])
        self.assertEqual(T.search("", path=self.p["tracker"]), [])

    def test_render_list_has_next_actions(self):
        T.add("Acme", "Data Scientist", path=self.p["tracker"])
        T.add("Globex", "ML Engineer", status="applied", path=self.p["tracker"])
        out = T.render_list(T.list_apps(path=self.p["tracker"]))
        self.assertIn("tailor resume + apply", out)
        self.assertIn("follow up", out)


# ---------------------------------------------------------------------------
# nudges: interview_soon
# ---------------------------------------------------------------------------

class InterviewSoonNudgeTest(unittest.TestCase):
    TODAY = date(2026, 9, 21)

    def _app(self, notes, status="selected_for_interview", prep_pack=""):
        return {"id": 7, "company": "Acme", "role": "Data Scientist",
                "status": status, "date_updated": "2026-09-21",
                "notes": notes, "prep_pack": prep_pack}

    def test_interview_in_two_days(self):
        ns = N.pending_nudges(
            [self._app("Onsite interview scheduled 2026-09-23 at 2pm")],
            today=self.TODAY)
        kinds = [n["kind"] for n in ns]
        self.assertIn("interview_soon", kinds)
        n = next(n for n in ns if n["kind"] == "interview_soon")
        self.assertEqual(n["app_id"], 7)
        self.assertIn("prep", n["command"])

    def test_far_future_date_no_nudge(self):
        ns = N.pending_nudges(
            [self._app("Interview on 2026-12-01")], today=self.TODAY)
        self.assertNotIn("interview_soon", [n["kind"] for n in ns])

    def test_garbage_notes_never_crash(self):
        ns = N.pending_nudges(
            [self._app("interview on 9999-99-99 ??? \x00\x01")],
            today=self.TODAY)
        self.assertIsInstance(ns, list)

    def test_no_date_no_nudge(self):
        ns = N.pending_nudges([self._app("waiting to hear back")],
                              today=self.TODAY)
        self.assertNotIn("interview_soon", [n["kind"] for n in ns])

    def test_saved_status_not_nudged(self):
        ns = N.pending_nudges(
            [self._app("Interview 2026-09-22", status="saved")], today=self.TODAY)
        self.assertNotIn("interview_soon", [n["kind"] for n in ns])

    def test_month_name_date(self):
        ns = N.pending_nudges(
            [self._app("Phone screen Sep 22, 2026 at 10am")], today=self.TODAY)
        self.assertIn("interview_soon", [n["kind"] for n in ns])


# ---------------------------------------------------------------------------
# gmail: classification kinds, multipart, proposal dedupe
# ---------------------------------------------------------------------------

class GmailClassificationTest(unittest.TestCase):
    def test_offer(self):
        kind, conf = G.classify_message(
            "Your offer letter from Globex", "hr@globex.com",
            "Congratulations! Your offer package is attached.")
        self.assertEqual(kind, "offer")

    def test_rejection(self):
        kind, _ = G.classify_message(
            "Update on your application", "n@initech.com",
            "Unfortunately we will not be moving forward at this time.")
        self.assertEqual(kind, "rejection")

    def test_interview_invite(self):
        kind, _ = G.classify_message(
            "Interview Invitation: Senior Data Scientist", "a@acme.com",
            "We'd like to schedule a phone screen next week.")
        self.assertEqual(kind, "interview_invite")

    def test_recruiter_outreach(self):
        kind, _ = G.classify_message(
            "Exciting ML opportunity at Hooli", "jane@hoolistaffing.com",
            "I came across your profile and wanted to reach out.")
        self.assertEqual(kind, "recruiter_outreach")

    def test_recruiter_spam(self):
        kind, conf = G.classify_message(
            "URGENT HIRING!!! Immediate openings", "blast@massstaffing.com",
            "Dear candidate, multiple openings available. Act fast, "
            "click here to apply!!! No experience required.")
        self.assertEqual(kind, "recruiter_spam")
        self.assertLess(conf, 0.6)

    def test_single_urgent_not_spam(self):
        kind, _ = G.classify_message(
            "Urgent: interview feedback", "recruiter@acme.com",
            "The hiring manager gave urgent feedback on your interview.")
        self.assertNotEqual(kind, "recruiter_spam")

    def test_other(self):
        kind, conf = G.classify_message(
            "Your receipt", "receipts@wholefoods.com", "Thanks for shopping.")
        self.assertEqual(kind, "other")


class GmailMultipartTest(unittest.TestCase):
    def _msg(self, payload: str, ctype: str, charset="utf-8",
             encoding: str | None = None):
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"] = "a@example.com"
        m["Subject"] = "test"
        m.set_content(payload, subtype="plain", charset=charset,
                      cte=encoding or "7bit")
        return m

    def test_base64_text_plain(self):
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"] = "recruiter@acme.com"
        m["Subject"] = "Interview Invitation"
        m.set_content("We invite you to interview.", cte="base64")
        self.assertIn("interview", G._message_text(m).lower())

    def test_nested_multipart_alternative(self):
        from email.message import EmailMessage
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        outer = MIMEMultipart("mixed")
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText("<b>Interview</b> invite", "html", "utf-8"))
        alt.attach(MIMEText("Interview invite", "plain", "utf-8"))
        outer.attach(alt)
        self.assertIn("interview", G._message_text(outer).lower())

    def test_html_only_falls_back_to_text(self):
        from email.message import EmailMessage
        m = EmailMessage()
        m["Subject"] = "x"
        m.set_content("<html><body><p>Your <b>offer</b> letter</p></body></html>",
                      subtype="html")
        text = G._message_text(m)
        self.assertIn("offer", text.lower())
        self.assertNotIn("<b>", text)

    def test_unknown_charset_does_not_crash(self):
        from email.message import EmailMessage
        m = EmailMessage()
        m["Subject"] = "x"
        m.set_content("plain body", charset="utf-8")
        # corrupt the declared charset
        m.replace_header("Content-Type", 'text/plain; charset="bogus-xyz"')
        self.assertIn("plain body", G._message_text(m))

    def test_mbox_import_end_to_end_with_encoded_part(self):
        import base64
        body = base64.b64encode(
            "We'd like to schedule a phone screen.".encode()).decode()
        raw = (
            "From recruiter@acme.com Mon Sep 21 10:00:00 2026\n"
            "From: Acme Recruiting <recruiting@acme.com>\n"
            "Subject: Interview Invitation: Senior Data Scientist\n"
            "Message-ID: <enc1@example.com>\n"
            "Date: Mon, 21 Sep 2026 10:00:00 -0400\n"
            "Content-Type: multipart/mixed; boundary=BOUND\n"
            "\n--BOUND\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "Content-Transfer-Encoding: base64\n"
            f"\n{body}\n--BOUND--\n"
        )
        td, p = _temp_paths()
        try:
            p["mbox"].write_text(raw, encoding="utf-8")
            res = G.import_mbox(p["mbox"], proposals_path=p["proposals"])
            self.assertEqual(len(res["new_proposals"]), 1)
            self.assertIn("phone screen",
                          res["new_proposals"][0]["snippet"].lower())
        finally:
            td.cleanup()


def _mbox_two_dupes(path: Path):
    """Two different messages, same company/role/kind -> one proposal."""
    msgs = []
    for i, mid in enumerate(("<dup1@example.com>", "<dup2@example.com>")):
        msgs.append(
            f"From recruiting@acme.com Mon Sep 2{i} 10:00:00 2026\n"
            f"From: Acme Recruiting <recruiting@acme.com>\n"
            "Subject: Interview Invitation: Senior Data Scientist\n"
            f"Message-ID: {mid}\n"
            f"Date: Mon, 2{i} Sep 2026 10:00:00 -0400\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\nPhone screen next week.\n\n")
    path.write_text("".join(msgs), encoding="utf-8")


class GmailProposalDedupeTest(unittest.TestCase):
    def test_reimport_dedupes_on_message_id(self):
        td, p = _temp_paths()
        try:
            _mbox_two_dupes(p["mbox"])
            first = G.import_mbox(p["mbox"], proposals_path=p["proposals"])
            second = G.import_mbox(p["mbox"], proposals_path=p["proposals"])
            self.assertEqual(len(first["new_proposals"]), 1)
            self.assertEqual(len(second["new_proposals"]), 0)
        finally:
            td.cleanup()

    def test_same_company_role_kind_deduped(self):
        td, p = _temp_paths()
        try:
            _mbox_two_dupes(p["mbox"])
            res = G.import_mbox(p["mbox"], proposals_path=p["proposals"])
            self.assertEqual(len(res["new_proposals"]), 1)
            self.assertEqual(res["skipped_duplicates"], 1)
        finally:
            td.cleanup()

    def test_different_kinds_not_deduped(self):
        td, p = _temp_paths()
        try:
            raw = (
                "From a@acme.com Mon Sep 21 10:00:00 2026\n"
                "From: Acme <a@acme.com>\n"
                "Subject: Interview Invitation: Senior Data Scientist\n"
                "Message-ID: <k1@example.com>\n"
                "Date: Mon, 21 Sep 2026 10:00:00 -0400\n"
                "Content-Type: text/plain; charset=utf-8\n"
                "\nPhone screen next week.\n\n"
                "From a@acme.com Tue Sep 22 10:00:00 2026\n"
                "From: Acme <a@acme.com>\n"
                "Subject: Your offer letter from Acme\n"
                "Message-ID: <k2@example.com>\n"
                "Date: Tue, 22 Sep 2026 10:00:00 -0400\n"
                "Content-Type: text/plain; charset=utf-8\n"
                "\nCongratulations, your offer package is attached.\n\n"
            )
            p["mbox"].write_text(raw, encoding="utf-8")
            res = G.import_mbox(p["mbox"], proposals_path=p["proposals"])
            self.assertEqual(len(res["new_proposals"]), 2)
        finally:
            td.cleanup()


# ---------------------------------------------------------------------------
# linkedin: position bullets, endorsements, education
# ---------------------------------------------------------------------------

def _linkedin_zip(path: Path, skills_header="Name", endorsement=None):
    prof = io.StringIO()
    w = csv.writer(prof)
    w.writerow(["First Name", "Last Name", "Headline", "Location", "Summary"])
    w.writerow(["Alex", "Rivera", "Senior Data Scientist", "New York, NY",
                "ML engineer with 6 years"])
    prof.seek(0)

    pos = io.StringIO()
    w = csv.writer(pos)
    w.writerow(["Title", "Company Name", "Started On", "Finished On",
                "Description", "Location"])
    w.writerow(["Senior Data Scientist", "Meridian Financial", "Jan 2021",
                "Present",
                "• Built ranking models\n• Cut latency 30%\n- Mentored interns",
                "New York, NY"])
    w.writerow(["Data Analyst", "Globex", "Jun 2019", "Dec 2020",
                "Led dashboard development for the finance team. "
                "This involved building self-serve Tableau dashboards that "
                "reduced ad-hoc requests by half. Also automated weekly "
                "reporting with Python and SQL pipelines.",
                "New York, NY"])
    pos.seek(0)

    skills = io.StringIO()
    w = csv.writer(skills)
    if endorsement:
        w.writerow([skills_header, endorsement])
        w.writerow(["Python", "42"])
        w.writerow(["SQL", "17"])
        w.writerow(["Tableau", ""])
    else:
        w.writerow([skills_header])
        w.writerow(["Python"])
        w.writerow(["SQL"])
    skills.seek(0)

    edu = io.StringIO()
    w = csv.writer(edu)
    w.writerow(["School Name", "Degree Name", "Field of Study",
                "Start Date", "End Date"])
    w.writerow(["State University", "B.S.", "Computer Science", "2015", "2019"])
    edu.seek(0)

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Profile.csv", prof.read())
        zf.writestr("Positions.csv", pos.read())
        zf.writestr("Skills.csv", skills.read())
        zf.writestr("Education.csv", edu.read())


class LinkedInParseTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _temp_paths()
        _linkedin_zip(self.p["zip"])

    def tearDown(self):
        self.td.cleanup()

    def test_position_bullets_parsed(self):
        parsed = L.parse_export(self.p["zip"])
        exp = parsed["experience"]
        self.assertEqual(len(exp), 2)
        self.assertEqual(len(exp[0]["bullets"]), 3)
        self.assertTrue(all(not b.startswith("•") for b in exp[0]["bullets"]))
        self.assertIn("ranking models", exp[0]["bullets"][0].lower())

    def test_paragraph_description_split_into_sentences(self):
        parsed = L.parse_export(self.p["zip"])
        bullets = parsed["experience"][1]["bullets"]
        self.assertGreaterEqual(len(bullets), 2)

    def test_education_parsed(self):
        parsed = L.parse_export(self.p["zip"])
        edu = parsed["education"]
        self.assertEqual(len(edu), 1)
        self.assertEqual(edu[0]["school"], "State University")
        self.assertIn("Computer Science", edu[0]["degree"])

    def test_skills_without_endorsement_column(self):
        parsed = L.parse_export(self.p["zip"])
        self.assertEqual(parsed["skills_raw"], ["Python", "SQL"])
        self.assertEqual(parsed["skills_with_endorsements"], [])

    def test_skills_with_endorsement_counts(self):
        _linkedin_zip(self.p["zip"], endorsement="Endorsements")
        parsed = L.parse_export(self.p["zip"])
        endorsed = {e["name"]: e["endorsements"]
                    for e in parsed["skills_with_endorsements"]}
        self.assertEqual(endorsed, {"Python": 42, "SQL": 17})

    def test_to_profile_and_merge_modes(self):
        prof = L.to_profile(L.parse_export(self.p["zip"]))
        self.assertEqual(prof["name"], "Alex Rivera")
        self.assertIn("python", prof["skills"])
        merged = L._merge_profiles(
            {"experience": [{"title": "Senior Data Scientist",
                             "company": "Meridian Financial",
                             "dates": "", "bullets": []}],
             "education": [], "skills": [], "source_files": []}, prof)
        # base's dupe entry merged; only the distinct Data Analyst entry added
        self.assertEqual(len(merged["experience"]), 2)
        titles = [(e["title"], e["company"]) for e in merged["experience"]]
        self.assertEqual(len(set(titles)), 2)
        replaced = L.import_zip(self.p["zip"], mode="replace",
                                out_path=self.td.name + "/profile.json")
        self.assertEqual(replaced["mode"], "replace")
        self.assertEqual(replaced["positions"], 2)


# ---------------------------------------------------------------------------
# salary: LCA variant hardening + aggregate_by_title
# ---------------------------------------------------------------------------

class SalaryVariantTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _temp_paths()

    def tearDown(self):
        self.td.cleanup()

    def _write_csv(self, header, rows, bom=False):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        data = buf.getvalue()
        if bom:
            data = "\ufeff" + data
        p = Path(self.td.name) / "lca.csv"
        p.write_text(data, encoding="utf-8")
        return p

    def test_lowercase_space_variant_headers(self):
        p = self._write_csv(
            ["case number", "case status", "employer name", "job title",
             "worksite city", "worksite state",
             "wage rate of pay from", "wage rate of pay to", "wage unit of pay"],
            [["A-1", "CERTIFIED", "Acme Inc", "Data Scientist",
              "New York", "NY", "150000", "180000", "Year"]])
        res = S.import_lca(p, path=self.p["db"])
        self.assertEqual(res["imported"], 1)

    def test_bom_and_whitespace_headers(self):
        p = self._write_csv(
            [" CASE_NUMBER ", " CASE_STATUS", "EMPLOYER_NAME", "JOB_TITLE",
             "WORKSITE_CITY", "WORKSITE_STATE",
             "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO", "WAGE_UNIT_OF_PAY"],
            [["A-2", "CERTIFIED", "Acme Inc", "Data Scientist",
              "New York", "NY", "150000", "180000", "Year"]], bom=True)
        res = S.import_lca(p, path=self.p["db"])
        self.assertEqual(res["imported"], 1)

    def test_certified_withdrawn_excluded(self):
        p = self._write_csv(
            ["CASE_NUMBER", "CASE_STATUS", "EMPLOYER_NAME", "JOB_TITLE",
             "WORKSITE_CITY", "WORKSITE_STATE",
             "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO", "WAGE_UNIT_OF_PAY"],
            [["A-3", "CERTIFIED-WITHDRAWN", "Acme Inc", "Data Scientist",
              "New York", "NY", "150000", "180000", "Year"]])
        res = S.import_lca(p, path=self.p["db"])
        self.assertEqual(res["imported"], 0)
        self.assertEqual(res["skipped"], 1)

    def test_aggregate_by_title(self):
        S.add_range("Acme", "Data Scientist", 150000, 190000,
                    source="dol_lca", path=self.p["db"])
        S.add_range("Acme", "Data Scientist", 160000, 200000,
                    source="dol_lca", path=self.p["db"])
        S.add_range("Globex", "Data Scientist", 130000, 160000,
                    source="job_post", path=self.p["db"])
        agg = S.aggregate_by_title("Data Scientist", path=self.p["db"])
        self.assertEqual(agg["n"], 2)
        self.assertLessEqual(agg["p25"], agg["median"])
        self.assertLessEqual(agg["median"], agg["p75"])
        self.assertEqual(len(agg["companies"]), 2)

    def test_aggregate_by_title_empty(self):
        agg = S.aggregate_by_title("No Such Role", path=self.p["db"])
        self.assertEqual(agg["n"], 0)
        self.assertIsNone(agg["median"])

    def test_render_lookup_has_attribution(self):
        S.add_range("Acme", "Data Scientist", 150000, 190000,
                    source="job_post", source_detail="https://example.com/jd",
                    path=self.p["db"])
        res = S.lookup(company="Acme", title="Data Scientist", path=self.p["db"])
        out = S.render_lookup(res, company="Acme", title="Data Scientist")
        self.assertIn("median", out)
        self.assertIn("job_post", out)
        self.assertIn("Acme", out)


if __name__ == "__main__":
    unittest.main()
