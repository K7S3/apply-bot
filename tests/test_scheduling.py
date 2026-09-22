"""Tests for candid.scheduling (interview invite parsing + reply drafting)."""
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class ParseTest(unittest.TestCase):
    def test_full_invite(self):
        from candid import scheduling as S
        text = (
            "Hi Alex,\n\nYou are invited to a 45 minute interview with "
            "Jane Doe on September 24, 2026 at 2:30 PM ET.\n\n"
            "Join here: https://zoom.us/j/123456789\n\n"
            "Interviewer: Jane Doe, Engineering Manager"
        )
        p = S.parse_invite(text, today=date(2026, 9, 1))
        self.assertIn("2026-09-24", p["dates"])
        self.assertTrue(any("2:30" in t for t in p["times"]))
        self.assertIn("ET", p["timezones"])
        self.assertIn("Jane Doe", p["interviewers"])
        self.assertTrue(any("zoom.us" in u for u in p["video_links"]))
        self.assertEqual(p["duration_minutes"], 45)
        self.assertEqual(p["needs_confirm"], [])

    def test_yearless_date_gets_confirm_flag(self):
        from candid import scheduling as S
        p = S.parse_invite("Interview on Oct 5 at 11am PT",
                           today=date(2026, 9, 1))
        self.assertIn("2026-10-05", p["dates"])
        self.assertTrue(any("year" in f.lower() for f in p["needs_confirm"]),
                        p["needs_confirm"])

    def test_yearless_date_rolls_to_next_year(self):
        from candid import scheduling as S
        p = S.parse_invite("Interview on Jan 10 at 3pm ET",
                           today=date(2026, 9, 1))
        self.assertIn("2027-01-10", p["dates"])

    def test_ambiguous_invite_flags_everything(self):
        from candid import scheduling as S
        p = S.parse_invite("Looking forward to chatting next week!",
                           today=date(2026, 9, 1))
        self.assertEqual(p["dates"], [])
        self.assertTrue(len(p["needs_confirm"]) >= 4)

    def test_iso_date_and_24h_time(self):
        from candid import scheduling as S
        p = S.parse_invite("Call on 2026-10-02 at 14:30 CET with Sam Reed",
                           today=date(2026, 9, 1))
        self.assertIn("2026-10-02", p["dates"])
        self.assertIn("CET", p["timezones"])
        self.assertIn("Sam Reed", p["interviewers"])

    def test_meet_link_extracted(self):
        from candid import scheduling as S
        p = S.parse_invite("2026-10-05 10:00 AM PT https://meet.google.com/abc-defg-hij",
                           today=date(2026, 9, 1))
        self.assertTrue(any("meet.google.com" in u for u in p["video_links"]))

    def test_duration_hours(self):
        from candid import scheduling as S
        p = S.parse_invite("a 1 hour panel on 2026-10-05 at 9am ET",
                           today=date(2026, 9, 1))
        self.assertEqual(p["duration_minutes"], 60)

    def test_empty_text_raises(self):
        from candid import scheduling as S
        with self.assertRaises(S.SchedulingError) as cm:
            S.parse_invite("   ")
        self.assertIn("schedule parse --help", str(cm.exception))

    def test_render_parse_shows_confirm(self):
        from candid import scheduling as S
        p = S.parse_invite("chat sometime", today=date(2026, 9, 1))
        out = S.render_parse(p)
        self.assertIn("Please confirm", out)
        self.assertIn("(not found)", out)

    def test_never_crashes_on_garbage(self):
        from candid import scheduling as S
        p = S.parse_invite("!!! @@@ 999 2026-99-99 25:99pm", today=date(2026, 9, 1))
        self.assertIsInstance(p["needs_confirm"], list)


class ReplyTest(unittest.TestCase):
    def test_reply_proposes_slots(self):
        from candid import scheduling as S
        d = S.reply_draft("Alex Rivera", interviewer="Jane Doe", role="ML Engineer",
                          company="Acme",
                          slots=["Tue 2-4pm ET", "Wed 10am-12pm ET"])
        self.assertIn("Subject:", d)
        self.assertIn("Tue 2-4pm ET", d)
        self.assertIn("Wed 10am-12pm ET", d)
        self.assertIn("Alex Rivera", d)

    def test_reply_echoes_parsed_invite(self):
        from candid import scheduling as S
        parsed = {"dates": ["2026-09-24"], "times": ["2:30 PM"],
                  "timezones": ["ET"], "interviewers": [],
                  "video_links": [], "duration_minutes": None,
                  "needs_confirm": []}
        d = S.reply_draft("Alex", slots=["Fri 1pm ET"], parsed=parsed)
        self.assertIn("2026-09-24", d)

    def test_reply_rejects_no_slots(self):
        from candid import scheduling as S
        with self.assertRaises(S.SchedulingError):
            S.reply_draft("Alex", slots=[])

    def test_reply_rejects_too_many_slots(self):
        from candid import scheduling as S
        with self.assertRaises(S.SchedulingError):
            S.reply_draft("Alex", slots=["a", "b", "c", "d"])

    def test_read_source_file_and_stdin(self):
        import tempfile
        from candid import scheduling as S
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("interview invite")
            name = f.name
        self.assertEqual(S.read_source(name), "interview invite")
        self.assertEqual(S.read_source(file=name), "interview invite")
        self.assertEqual(S.read_source(stdin_text="pasted text"), "pasted text")
        self.assertEqual(S.read_source(source="literal text"), "literal text")
        with self.assertRaises(S.SchedulingError):
            S.read_source()


if __name__ == "__main__":
    unittest.main()
