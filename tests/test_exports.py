"""Tests for batch-3 exports: autofill kit + iCal export.

Covers: autofill.py (section rendering from a fixture profile, EEO safe
defaults are exact decline strings and nothing is ever invented),
ical.py (VEVENT structure, RFC 5545 escaping + line folding,
missing-date skip handling), and CLI smoke tests for
`profile autofill` and `track export-ics`.

Data paths are redirected into a temp dir by monkeypatching
candid.config attributes (same approach as tests/test_cli_ux.py).
All fixtures are fictional.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import autofill as A  # noqa: E402
from candid import config as C  # noqa: E402
from candid import ical as I  # noqa: E402
from candid import tracker as T  # noqa: E402

# Fictional fixture profile (nothing real here).
PROFILE = {
    "name": "Alex Rivera",
    "headline": "Senior Data Scientist",
    "location": "New York, NY",
    "summary": "ML & experimentation.",
    "skills": ["python", "machine learning", "sql"],
    "experience": [
        {"title": "Senior Data Scientist",
         "company": "Meridian Financial",
         "dates": "Jan 2021 - Present",
         "bullets": ["Built ranking models with XGBoost."]},
        {"title": "Data Analyst",
         "company": "Globex Corp",
         "dates": "Jun 2019 - Dec 2020",
         "bullets": []},
    ],
    "education": [{"school": "State University",
                   "degree": "B.S. Computer Science",
                   "dates": "2015 - 2019"}],
    "years_experience": 5.5,
    "seniority": "senior",
    "source_files": ["resume.pdf"],
}


def _unfold(text: str) -> list[str]:
    """Unfold an .ics file into logical content lines."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith(" ") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [l for l in lines if l]


class AutofillRenderTest(unittest.TestCase):
    def test_work_section_renders_entries(self):
        out = A.render_kit(PROFILE, section="work")
        self.assertIn("## Work history", out)
        self.assertIn("Meridian Financial", out)
        self.assertIn("Senior Data Scientist", out)
        self.assertIn("Jan 2021 - Present", out)
        self.assertIn("Globex Corp", out)
        self.assertIn("Data Analyst", out)

    def test_skills_section(self):
        out = A.render_kit(PROFILE, section="skills")
        self.assertIn("## Skills", out)
        self.assertIn("python, machine learning, sql", out)

    def test_education_section(self):
        out = A.render_kit(PROFILE, section="education")
        self.assertIn("## Education", out)
        self.assertIn("State University", out)
        self.assertIn("B.S. Computer Science", out)

    def test_all_includes_every_section(self):
        out = A.render_kit(PROFILE, section="all")
        for heading in ("## Work history", "## Skills",
                        "## Education", "## EEO / voluntary disclosure"):
            self.assertIn(heading, out)

    def test_fills_never_submits_label(self):
        out = A.render_kit(PROFILE)
        self.assertIn("FILLS", out)
        self.assertIn("never submits", out)

    def test_unknown_section_raises(self):
        with self.assertRaises(A.AutofillError):
            A.render_kit(PROFILE, section="nope")

    def test_empty_profile_degrades_gracefully(self):
        out = A.render_kit({})
        self.assertIn("Work history", out)
        self.assertIn("not detected", out)


class EEOSafeDefaultsTest(unittest.TestCase):
    """EEO answers must be decline-to-answer options — never invented data."""

    def test_exact_safe_default_strings(self):
        self.assertEqual(A.DECLINE, "I don't wish to answer")
        self.assertEqual(A.DECLINE_RACE, "Decline to self-identify")

    def test_eeo_section_uses_exact_strings(self):
        out = A.render_kit(PROFILE, section="eeo")
        self.assertIn("- **Gender:** I don't wish to answer", out)
        self.assertIn("- **Race / Ethnicity:** Decline to self-identify", out)
        self.assertIn("- **Disability status (Voluntary Self-Identification):** "
                      "I don't wish to answer", out)
        self.assertIn("- **Veteran status:** I don't wish to answer", out)

    def test_nothing_about_identity_is_invented(self):
        qa = A.eeo_answers()
        invented = {"Male", "Female", "Yes", "No", "White", "Black", "Asian",
                    "Hispanic", "Native Hawaiian", "Pacific Islander",
                    "American Indian", "Alaska Native", "Two or more races",
                    "protected veteran", "disabled veteran"}
        for q in qa:
            self.assertNotIn(q["answer"], invented)
            if "yourself" not in q["answer"]:
                self.assertIn(q["answer"],
                              ("I don't wish to answer",
                               "Decline to self-identify"))
        # the rendered EEO section answers are the same strings
        out = A.render_kit(PROFILE, section="eeo")
        for q in qa:
            self.assertIn(f"**{q['question']}:** {q['answer']}", out)

    def test_work_authorization_is_not_answered(self):
        out = A.render_kit(PROFILE, section="eeo")
        self.assertIn("Are you legally authorized", out)
        self.assertIn("answer yourself", out)


class IcsEscapingTest(unittest.TestCase):
    def test_escape_special_chars(self):
        self.assertEqual(
            I.escape_text("a;b,c\\d\ne"), "a\\;b\\,c\\\\d\\ne")
        self.assertEqual(I.escape_text("plain"), "plain")
        self.assertEqual(I.escape_text(""), "")

    def test_line_folding(self):
        long_line = "DESCRIPTION:" + "x" * 200
        folded = I.fold_line(long_line)
        for physical in folded.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)
        self.assertTrue(all(p.startswith(" ") or p.startswith("DESCRIPTION")
                            for p in folded.split("\r\n")[1:]))
        # unfold round-trips
        unfolded = I.fold_line("DESCRIPTION:" + "y" * 100).replace("\r\n ", "")
        self.assertEqual(unfolded, "DESCRIPTION:" + "y" * 100)

    def test_no_multibyte_char_split(self):
        line = "SUMMARY:" + "é" * 100
        for physical in I.fold_line(line).split("\r\n"):
            physical.encode("utf-8")  # raises if the split corrupted a char
            self.assertLessEqual(len(physical.encode("utf-8")), 75)


class IcsStructureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-exports-"))
        self._saved = {n: getattr(C, n) for n in
                       ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"

    def tearDown(self):
        for n, v in self._saved.items():
            setattr(C, n, v)

    def _future_date_note(self, days=2):
        d = date.today() + timedelta(days=days)
        return "Onsite interview scheduled for " + d.strftime("%b %d, %Y")

    def test_interview_event_structure(self):
        T.add("Acme", "Data Scientist", status="selected_for_interview",
              notes=self._future_date_note())
        events, skipped = I.collect_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(len(skipped), 0)
        ics = I.render_ics(events)
        lines = _unfold(ics)
        self.assertIn("BEGIN:VCALENDAR", lines)
        self.assertIn("VERSION:2.0", lines)
        self.assertIn("END:VCALENDAR", lines)
        starts = [l for l in lines if l.startswith("BEGIN:VEVENT")]
        self.assertEqual(len(starts), 1)
        vevent = lines[lines.index("BEGIN:VEVENT"):lines.index("END:VEVENT")]
        for prop in ("UID:", "DTSTAMP:", "DTSTART;VALUE=DATE:",
                     "SUMMARY:", "DESCRIPTION:"):
            self.assertTrue(any(l.startswith(prop) for l in vevent), prop)
        summary = next(l for l in vevent if l.startswith("SUMMARY:"))
        self.assertIn("Acme", summary)
        dtstart = next(l for l in vevent if l.startswith("DTSTART"))
        self.assertRegex(dtstart, r"DTSTART;VALUE=DATE:\d{8}")

    def test_missing_date_is_skipped_with_note(self):
        T.add("NoDate Inc", "ML Engineer", status="selected_for_interview",
              notes="talked to recruiter, waiting on scheduling")
        events, skipped = I.collect_events()
        self.assertEqual(len(events), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn("NoDate Inc", skipped[0])
        self.assertIn("no interview date", skipped[0].lower())
        # nothing fabricated: no VEVENTs at all
        self.assertNotIn("BEGIN:VEVENT", I.render_ics(events))

    def test_special_chars_escaped_in_output(self):
        T.add("Foo, Inc.; research", "Scientist \"A\"",
              status="selected_for_interview",
              notes=self._future_date_note() + " w/ hiring mgr")
        events, _ = I.collect_events()
        ics = I.render_ics(events)
        lines = _unfold(ics)
        summary = next(l for l in lines if l.startswith("SUMMARY:"))
        self.assertIn("Foo\\, Inc.\\; research", summary)

    def test_nudge_reminders_dated_today(self):
        T.add("QuietCo", "Analyst", status="applied",
              notes="applied ages ago " + (date.today() - timedelta(days=30)
                                           ).isoformat())
        rec = T.list_apps()[0]
        T.update(rec["id"], status="applied")  # date_updated stays today...
        # force an old date_updated so the quiet_applied nudge fires
        apps = T.list_apps()
        apps[0]["date_updated"] = (date.today() - timedelta(days=30)).isoformat()
        import json as _json
        C.TRACKER_PATH.write_text(_json.dumps(apps), encoding="utf-8")
        events, _ = I.collect_events()
        nudge_events = [e for e in events if e["kind"].startswith("nudge:")]
        self.assertTrue(nudge_events)
        for e in nudge_events:
            self.assertEqual(e["dtstart"], date.today())
            self.assertIn("due now", e["description"])

    def test_all_physical_lines_folded(self):
        T.add("Acme", "DS", status="selected_for_interview",
              notes=self._future_date_note() + " " + "detail " * 100)
        events, _ = I.collect_events()
        ics = I.render_ics(events)
        for physical in ics.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)


class CLIExportsSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-exports-cli-"))
        self._saved = {n: getattr(C, n) for n in
                       ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.PROFILE_PATH.write_text(json.dumps(PROFILE), encoding="utf-8")

    def tearDown(self):
        for n, v in self._saved.items():
            setattr(C, n, v)

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(argv)
        return buf.getvalue()

    def test_profile_autofill_all(self):
        out = self._run(["profile", "autofill"])
        self.assertIn("Meridian Financial", out)
        self.assertIn("I don't wish to answer", out)

    def test_profile_autofill_section(self):
        out = self._run(["profile", "autofill", "--section", "eeo"])
        self.assertIn("Decline to self-identify", out)
        self.assertNotIn("Meridian Financial", out)

    def test_track_export_ics(self):
        T.add("Acme", "Data Scientist", status="selected_for_interview",
              notes="Interview on " + (date.today() + timedelta(days=2)
                                       ).strftime("%b %d, %Y"))
        out = self._run(["track", "export-ics", "--out",
                         str(self.tmp / "calendar.ics")])
        self.assertIn("Exported 1 event(s)", out)
        self.assertTrue((self.tmp / "calendar.ics").exists())
        content = (self.tmp / "calendar.ics").read_text(encoding="utf-8")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("BEGIN:VEVENT", content)

    def test_track_export_ics_empty_tracker(self):
        out = self._run(["track", "export-ics", "--out",
                         str(self.tmp / "empty.ics")])
        self.assertIn("Exported 0 event(s)", out)
        content = (self.tmp / "empty.ics").read_text(encoding="utf-8")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertNotIn("BEGIN:VEVENT", content)


if __name__ == "__main__":
    unittest.main()
