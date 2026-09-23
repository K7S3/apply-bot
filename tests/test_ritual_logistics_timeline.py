"""Tests for ritual logistics checklists and day-of timelines.

Run: python -m unittest discover -s tests

CANDID_DATA_DIR is pointed at a temp dir BEFORE any candid import so
tests never touch real user data.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

_TEMP_DATA = tempfile.mkdtemp(prefix="candid_ritual_test_")
os.environ["CANDID_DATA_DIR"] = _TEMP_DATA

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import ritual_logistics as RL  # noqa: E402
from candid import ritual_timeline as RT  # noqa: E402


class _HermeticDataDir(unittest.TestCase):
    """Point CANDID_DATA_DIR at this module's temp dir for every test.

    Sibling test modules assign the same env var at import time; without a
    per-test reset, whichever module is imported last wins and the modules
    under test (which resolve the data dir at call time) write into the
    wrong temp dir.
    """

    def setUp(self):
        self._old_candid_data_dir = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = _TEMP_DATA

    def tearDown(self):
        old = getattr(self, "_old_candid_data_dir", None)
        if old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = old


def _no_em_dash(text: str) -> bool:
    return "\u2014" not in text and "\u2013" not in text


class BuildLogisticsTest(_HermeticDataDir):
    def test_virtual_checklist(self):
        d = RL.build_logistics("virtual", "Acme", "Data Scientist", "2026-09-25")
        self.assertEqual(len(d["items"]), 7)
        labels = [i["label"] for i in d["items"]]
        self.assertIn("Join link saved and easy to find", labels)
        self.assertIn("Camera and microphone tested", labels)
        self.assertIn("Join 10 minutes early", labels)
        self.assertTrue(all(not i["done"] for i in d["items"]))
        self.assertEqual([i["n"] for i in d["items"]], list(range(1, 8)))

    def test_onsite_checklist(self):
        d = RL.build_logistics("onsite", "Acme", "Data Scientist", "2026-09-25")
        self.assertEqual(len(d["items"]), 7)
        labels = " | ".join(i["label"] for i in d["items"])
        self.assertIn("resume copies", labels.lower())
        self.assertIn("30 min", labels)

    def test_phone_checklist(self):
        d = RL.build_logistics("phone", "Acme", "Data Scientist", "2026-09-25")
        self.assertEqual(len(d["items"]), 5)
        labels = " | ".join(i["label"] for i in d["items"])
        self.assertIn("charged", labels.lower())
        self.assertIn("number confirmed", labels.lower())

    def test_round_type_case_insensitive(self):
        d = RL.build_logistics("Virtual", "Acme", "DS", "2026-09-25")
        self.assertEqual(d["round_type"], "virtual")

    def test_bad_round_type(self):
        with self.assertRaises(RL.RitualError):
            RL.build_logistics("vr", "Acme", "DS", "2026-09-25")

    def test_bad_date(self):
        with self.assertRaises(RL.RitualError):
            RL.build_logistics("virtual", "Acme", "DS", "09/25/2026")
        with self.assertRaises(RL.RitualError):
            RL.build_logistics("virtual", "Acme", "DS", "")

    def test_missing_company_or_role(self):
        with self.assertRaises(RL.RitualError):
            RL.build_logistics("virtual", "", "DS", "2026-09-25")
        with self.assertRaises(RL.RitualError):
            RL.build_logistics("virtual", "Acme", "  ", "2026-09-25")

    def test_ritual_id_slug(self):
        d = RL.build_logistics("virtual", "Acme Corp", "Data Scientist",
                               "2026-09-25")
        self.assertEqual(d["ritual_id"],
                         "acme-corp-data-scientist-2026-09-25")

    def test_ritual_id_override(self):
        d = RL.build_logistics("virtual", "Acme", "DS", "2026-09-25",
                               ritual_id="my-custom-id")
        self.assertEqual(d["ritual_id"], "my-custom-id")

    def test_date_object_accepted(self):
        from datetime import date
        d = RL.build_logistics("phone", "Acme", "DS", date(2026, 9, 25))
        self.assertEqual(d["date"], "2026-09-25")


class PersistLogisticsTest(_HermeticDataDir):
    def setUp(self):
        super().setUp()
        self.data = RL.build_logistics("virtual", "Acme", "DS", "2026-09-25")

    def test_save_load_roundtrip(self):
        path = RL.save_logistics(self.data)
        self.assertTrue(path.exists())
        self.assertIn("rituals", path.parts)
        loaded = RL.load_logistics(self.data["ritual_id"])
        self.assertEqual(loaded, self.data)

    def test_save_writes_under_temp_data_dir(self):
        path = RL.save_logistics(self.data)
        self.assertTrue(str(path).startswith(_TEMP_DATA))
        self.assertNotIn("candid-batch86a", str(path))

    def test_load_missing_raises(self):
        with self.assertRaises(RL.RitualError):
            RL.load_logistics("no-such-ritual-xyz")

    def test_check_item_marks_done(self):
        RL.save_logistics(self.data)
        updated = RL.check_item(self.data["ritual_id"], 3)
        self.assertTrue(updated["items"][2]["done"])
        reloaded = RL.load_logistics(self.data["ritual_id"])
        self.assertTrue(reloaded["items"][2]["done"])

    def test_check_item_out_of_range(self):
        RL.save_logistics(self.data)
        with self.assertRaises(RL.RitualError):
            RL.check_item(self.data["ritual_id"], 99)
        with self.assertRaises(RL.RitualError):
            RL.check_item(self.data["ritual_id"], 0)

    def test_check_item_uncheck(self):
        RL.save_logistics(self.data)
        RL.check_item(self.data["ritual_id"], 1)
        updated = RL.check_item(self.data["ritual_id"], 1, done=False)
        self.assertFalse(updated["items"][0]["done"])


class RenderLogisticsTest(_HermeticDataDir):
    def test_render_has_boxes_and_progress(self):
        d = RL.build_logistics("phone", "Acme", "DS", "2026-09-25")
        d["items"][0]["done"] = True
        text = RL.render_logistics(d)
        self.assertIn("[x]", text)
        self.assertIn("[ ]", text)
        self.assertIn("1/5 checked", text)
        self.assertIn("Acme", text)
        self.assertTrue(_no_em_dash(text))
        self.assertTrue(text.isascii())


class BuildTimelineTest(_HermeticDataDir):
    def setUp(self):
        super().setUp()
        self.start = datetime(2026, 9, 25, 14, 0)

    def test_chronological_and_bookends(self):
        events = RT.build_timeline(self.start, "virtual")
        times = [t for t, _ in events]
        self.assertEqual(times, sorted(times))
        self.assertEqual(events[0][1], "Wake up")
        self.assertIn("Interview block", events[-2][1])
        self.assertIn("debrief", events[-1][1].lower())

    def test_default_wake_is_6h30_before(self):
        events = RT.build_timeline(self.start, "virtual")
        self.assertEqual(events[0][0], datetime(2026, 9, 25, 7, 30))

    def test_virtual_join_early(self):
        events = RT.build_timeline(self.start, "virtual")
        by_label = {label: t for t, label in events}
        self.assertEqual(by_label["Join the call 10 minutes early"],
                         datetime(2026, 9, 25, 13, 50))

    def test_onsite_depart_with_buffer(self):
        events = RT.build_timeline(self.start, "onsite")
        labels = [label for _, label in events]
        depart = [l for l in labels if l.startswith("Depart for the office")]
        self.assertEqual(len(depart), 1)
        by_label = {label: t for t, label in events}
        self.assertEqual(by_label[depart[0]], datetime(2026, 9, 25, 13, 0))

    def test_phone_follows_virtual_pattern(self):
        v = RT.build_timeline(self.start, "virtual")
        p = RT.build_timeline(self.start, "phone")
        self.assertEqual([l for _, l in v], [l for _, l in p])

    def test_wake_override(self):
        events = RT.build_timeline(self.start, "virtual", wake="08:00")
        self.assertEqual(events[0][0], datetime(2026, 9, 25, 8, 0))
        self.assertEqual(events[0][1], "Wake up")

    def test_wake_too_late_raises(self):
        with self.assertRaises(RT.RitualError):
            RT.build_timeline(self.start, "virtual", wake="13:00")

    def test_bad_wake_format_raises(self):
        with self.assertRaises(RT.RitualError):
            RT.build_timeline(self.start, "virtual", wake="morning")

    def test_bad_round_type_raises(self):
        with self.assertRaises(RT.RitualError):
            RT.build_timeline(self.start, "carrier-pigeon")

    def test_non_datetime_start_raises(self):
        with self.assertRaises(RT.RitualError):
            RT.build_timeline("2026-09-25 14:00", "virtual")

    def test_expected_slots_present(self):
        events = RT.build_timeline(self.start, "virtual")
        labels = " | ".join(l for _, l in events).lower()
        for slot in ("wake up", "breakfast", "shower", "materials review",
                     "warm-up", "tech check", "calm slot", "debrief"):
            self.assertIn(slot, labels)


class TimelineRenderTest(_HermeticDataDir):
    def test_render_text(self):
        events = RT.build_timeline(datetime(2026, 9, 25, 14, 0), "virtual",
                                   wake="07:30")
        text = RT.render_timeline(events)
        self.assertIn("07:30 - Wake up", text)
        self.assertIn("14:00 - Interview block", text)
        self.assertTrue(_no_em_dash(text))
        self.assertTrue(text.isascii())

    def test_json_roundtrip(self):
        events = RT.build_timeline(datetime(2026, 9, 25, 14, 0), "onsite")
        payload = json.loads(RT.timeline_json(events))
        self.assertEqual(len(payload), len(events))
        self.assertEqual(payload[0]["label"], "Wake up")
        self.assertTrue(payload[0]["time"].startswith("2026-09-25T07:30"))

    def test_parse_start_with_timezone(self):
        start = RT.parse_start("2026-09-25 14:00",
                               timezone="America/New_York")
        self.assertIsNotNone(start.tzinfo)
        events = RT.build_timeline(start, "virtual")
        self.assertEqual(events[0][0].tzinfo, start.tzinfo)
        self.assertIn("-04:00", events[0][0].isoformat())

    def test_parse_start_bad(self):
        with self.assertRaises(RT.RitualError):
            RT.parse_start("next friday-ish")
        with self.assertRaises(RT.RitualError):
            RT.parse_start("2026-09-25 14:00", timezone="Mars/Olympus")


if __name__ == "__main__":
    unittest.main()
