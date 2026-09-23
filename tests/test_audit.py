"""Tests for candid/audit.py: append-only tamper-evident audit log.

Covers: record/read roundtrip, filters, hash-chain verify (clean and
tampered), corrupt-line tolerance, search, stats, CSV/Markdown export,
prune (dry-run vs real), and undo-friendly before/after capture.

Run: python3 -m pytest tests/test_audit.py -q
"""
import csv
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-audit"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import audit as A  # noqa: E402
from candid import config as C  # noqa: E402


class AuditTestBase(unittest.TestCase):
    """Each test gets a fresh, isolated audit log via a temp CANDID_DATA_DIR."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._orig_audit_path = C.AUDIT_PATH
        # audit.py reads config.AUDIT_PATH lazily, so patching the
        # constant per-test isolates the log file (and its meta sidecar).
        C.AUDIT_PATH = Path(self.td.name) / "audit.log"

    def tearDown(self):
        C.AUDIT_PATH = self._orig_audit_path
        self.td.cleanup()

    def _raw_lines(self):
        return C.AUDIT_PATH.read_text(encoding="utf-8").splitlines()

    def _rewrite_lines(self, lines):
        C.AUDIT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _old_ts(self, days=40):
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# record / read
# ---------------------------------------------------------------------------

class TestRecordRead(AuditTestBase):
    def test_record_entry_schema(self):
        e = A.record("cli", "track update", "tracker", "42", "update",
                     before={"status": "applied"}, after={"status": "offer"},
                     note="moved to offer")
        for key in ("seq", "id", "ts", "actor", "command", "entity",
                    "entity_id", "action", "before", "after", "changes",
                    "note", "prev_hash", "hash"):
            self.assertIn(key, e)
        self.assertEqual(e["seq"], 1)
        self.assertRegex(e["id"], r"^[0-9a-f]{8}$")
        self.assertRegex(e["hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(e["prev_hash"], A.GENESIS_HASH)
        self.assertEqual(e["entity_id"], "42")
        # ISO-8601 UTC timestamp parses
        datetime.fromisoformat(e["ts"])

    def test_entity_id_coerced_to_str(self):
        e = A.record("api", "offer add", "offer", 7, "create", after={"x": 1})
        self.assertEqual(e["entity_id"], "7")

    def test_read_roundtrip_newest_first(self):
        for i in range(3):
            A.record("cli", f"cmd {i}", "tracker", str(i), "update",
                     after={"n": i})
        entries = A.read()
        self.assertEqual(len(entries), 3)
        self.assertEqual([e["seq"] for e in entries], [3, 2, 1])

    def test_read_missing_file_returns_empty(self):
        self.assertEqual(A.read(), [])

    def test_read_limit(self):
        for i in range(5):
            A.record("cli", "cmd", "tracker", str(i), "update", after={"n": i})
        got = A.read(limit=2)
        self.assertEqual([e["seq"] for e in got], [5, 4])

    def test_read_filters(self):
        A.record("cli", "track add", "tracker", "1", "create", after={"a": 1})
        A.record("cli", "track update", "tracker", "1", "update",
                 before={"a": 1}, after={"a": 2})
        A.record("dashboard", "offer add", "offer", "9", "create", after={"b": 1})
        self.assertEqual(len(A.read(entity="tracker")), 2)
        self.assertEqual(len(A.read(entity="offer")), 1)
        self.assertEqual(len(A.read(action="create")), 2)
        self.assertEqual(len(A.read(entity="tracker", entity_id="1")), 2)
        self.assertEqual(len(A.read(entity="tracker", entity_id=1)), 2)
        self.assertEqual(A.read(entity="goal"), [])

    def test_read_since_until(self):
        old = A._record("cli", "track add", "tracker", "1", "create",
                        after={"a": 1}, ts="2020-05-01T00:00:00+00:00")
        new = A._record("cli", "track update", "tracker", "1", "update",
                        before={"a": 1}, after={"a": 2},
                        ts="2026-01-02T00:00:00+00:00")
        self.assertEqual([e["id"] for e in A.read(since="2026-01-01T00:00:00+00:00")],
                         [new["id"]])
        self.assertEqual([e["id"] for e in A.read(until="2020-06-01T00:00:00+00:00")],
                         [old["id"]])
        self.assertEqual(len(A.read(since=old["ts"], until=new["ts"])), 2)

    def test_seq_increments_across_calls(self):
        a = A.record("cli", "c1", "tracker", "1", "create", after={"x": 1})
        b = A.record("cli", "c2", "tracker", "1", "update",
                     before={"x": 1}, after={"x": 2})
        self.assertEqual(b["seq"], a["seq"] + 1)
        self.assertEqual(b["prev_hash"], a["hash"])
        self.assertNotEqual(a["id"], b["id"])

    def test_invalid_actor_raises(self):
        with self.assertRaises(ValueError):
            A.record("web", "cmd", "tracker", "1", "create")


# ---------------------------------------------------------------------------
# hash chain / verify
# ---------------------------------------------------------------------------

class TestHashChain(AuditTestBase):
    def test_verify_clean_log(self):
        for i in range(4):
            A.record("cli", f"cmd {i}", "tracker", str(i), "update",
                     after={"n": i})
        self.assertEqual(A.verify(), [])

    def test_verify_empty_log(self):
        self.assertEqual(A.verify(), [])

    def test_tamper_flip_line_detected(self):
        A.record("cli", "track update", "tracker", "1", "update",
                 before={"s": "applied"}, after={"s": "offer"}, note="clean")
        A.record("cli", "track update", "tracker", "2", "update",
                 before={"s": "saved"}, after={"s": "applied"})
        lines = self._raw_lines()
        tampered = json.loads(lines[0])
        tampered["note"] = "forged note"  # edit content, leave hash stale
        lines[0] = json.dumps(tampered)
        self._rewrite_lines(lines)
        problems = A.verify()
        self.assertTrue(problems, "expected tampering to be detected")
        self.assertTrue(any("bad hash" in p for p in problems), problems)
        # the edited content is still readable
        self.assertEqual(A.read()[-1]["note"], "forged note")

    def test_tamper_delete_line_detected(self):
        for i in range(3):
            A.record("cli", f"cmd {i}", "tracker", str(i), "update",
                     after={"n": i})
        lines = self._raw_lines()
        del lines[1]  # remove the middle entry
        self._rewrite_lines(lines)
        problems = A.verify()
        self.assertTrue(problems)
        self.assertTrue(any("out of order" in p or "prev_hash" in p for p in problems),
                        problems)

    def test_out_of_order_seq_detected(self):
        for i in range(2):
            A.record("cli", f"cmd {i}", "tracker", str(i), "update",
                     after={"n": i})
        lines = self._raw_lines()
        e0, e1 = json.loads(lines[0]), json.loads(lines[1])
        e0["seq"], e1["seq"] = e1["seq"], e0["seq"]  # swap seqs, hashes go stale
        self._rewrite_lines([json.dumps(e0), json.dumps(e1)])
        problems = A.verify()
        self.assertTrue(problems)
        self.assertTrue(any("out of order" in p or "bad hash" in p for p in problems),
                        problems)

    def test_corrupt_line_skipped_in_read_reported_in_verify(self):
        A.record("cli", "cmd", "tracker", "1", "create", after={"a": 1})
        with open(C.AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write("this is not json\n")
            f.write('["also", "not", "an", "object"]\n')
        A.record("cli", "cmd", "tracker", "2", "create", after={"b": 2})
        entries = A.read()
        self.assertEqual(len(entries), 2)  # corrupt lines skipped
        self.assertEqual([e["seq"] for e in entries], [2, 1])
        problems = A.verify()
        self.assertEqual(len([p for p in problems if "corrupt" in p]), 2)


# ---------------------------------------------------------------------------
# search / stats / get
# ---------------------------------------------------------------------------

class TestSearchStatsGet(AuditTestBase):
    def test_search_case_insensitive(self):
        A.record("cli", "track update", "tracker", "1", "update",
                 before={"s": "applied"}, after={"s": "offer"},
                 note="Phone screen with Acme went well")
        self.assertEqual(len(A.search("acme")), 1)
        self.assertEqual(len(A.search("PHONE SCREEN")), 1)
        self.assertEqual(len(A.search("offer")), 1)  # matches after-value too

    def test_search_no_match(self):
        A.record("cli", "cmd", "tracker", "1", "create", after={"a": 1})
        self.assertEqual(A.search("zzz-no-such-thing"), [])

    def test_stats(self):
        A.record("cli", "track add", "tracker", "1", "create", after={"a": 1})
        A.record("cli", "track update", "tracker", "1", "update",
                 before={"a": 1}, after={"a": 2})
        A.record("dashboard", "offer add", "offer", "9", "create", after={"b": 1})
        s = A.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_action"], {"create": 2, "update": 1})
        self.assertEqual(s["by_entity"], {"tracker": 2, "offer": 1})
        self.assertEqual(sum(s["by_day"].values()), 3)

    def test_get_by_id(self):
        e = A.record("cli", "cmd", "tracker", "1", "create", after={"a": 1})
        got = A.get(e["id"])
        self.assertIsNotNone(got)
        self.assertEqual(got["seq"], e["seq"])

    def test_get_missing_returns_none(self):
        A.record("cli", "cmd", "tracker", "1", "create", after={"a": 1})
        self.assertIsNone(A.get("deadbeef"))


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

class TestExport(AuditTestBase):
    def test_export_csv(self):
        A.record("cli", "track add", "tracker", "1", "create",
                 after={"status": "applied"}, note="first")
        A.record("api", "track update", "tracker", "1", "update",
                 before={"status": "applied"}, after={"status": "offer"})
        out = Path(self.td.name) / "audit.csv"
        returned = A.export_csv(out)
        self.assertEqual(returned, out)
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["seq"], "1")  # chronological
        self.assertEqual(rows[1]["action"], "update")
        self.assertIn("status", rows[1]["changes"])
        self.assertEqual(rows[0]["note"], "first")

    def test_export_markdown(self):
        A.record("cli", "track add", "tracker", "1", "create",
                 after={"status": "applied"}, note="hello")
        out = Path(self.td.name) / "audit.md"
        A.export_markdown(out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# Audit log", text)
        self.assertIn("track add", text)
        self.assertIn("status", text)  # changes summary mentions the field
        self.assertIn("hello", text)


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------

class TestPrune(AuditTestBase):
    def _seed_old_and_new(self):
        old = A._record("cli", "track add", "tracker", "old", "create",
                        after={"a": 1}, ts=self._old_ts(40))
        new = A.record("cli", "track add", "tracker", "new", "create",
                       after={"a": 2})
        return old, new

    def test_prune_dry_run_changes_nothing(self):
        self._seed_old_and_new()
        result = A.prune(older_than_days=30, dry_run=True)
        self.assertEqual(result, {"total": 2, "kept": 1, "pruned": 1,
                                  "dry_run": True})
        self.assertEqual(len(A.read()), 2)  # file untouched
        self.assertEqual(A.verify(), [])

    def test_prune_real_removes_old_and_chain_still_verifies(self):
        old, new = self._seed_old_and_new()
        result = A.prune(older_than_days=30, dry_run=False)
        self.assertEqual(result["pruned"], 1)
        self.assertFalse(result["dry_run"])
        remaining = A.read()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], new["id"])
        # chain still verifies: meta sidecar anchors the pruned prefix
        self.assertEqual(A.verify(), [])

    def test_prune_nothing_old_is_noop(self):
        A.record("cli", "cmd", "tracker", "1", "create", after={"a": 1})
        result = A.prune(older_than_days=30, dry_run=False)
        self.assertEqual(result["pruned"], 0)
        self.assertEqual(len(A.read()), 1)
        self.assertEqual(A.verify(), [])


# ---------------------------------------------------------------------------
# diff + undo-friendly capture
# ---------------------------------------------------------------------------

class TestDiff(AuditTestBase):
    def test_diff_changed_added_removed(self):
        changes = A._diff({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "d": 4})
        by_field = {c["field"]: c for c in changes}
        self.assertEqual(set(by_field), {"b", "c", "d"})
        self.assertEqual(by_field["b"], {"field": "b", "old": 2, "new": 5})
        self.assertEqual(by_field["c"], {"field": "c", "old": 3, "new": None})
        self.assertEqual(by_field["d"], {"field": "d", "old": None, "new": 4})

    def test_diff_nested_dict_dotted_paths(self):
        changes = A._diff({"a": {"x": 1, "y": 2}}, {"a": {"x": 9, "y": 2}})
        self.assertEqual(changes, [{"field": "a.x", "old": 1, "new": 9}])

    def test_diff_no_changes_empty(self):
        self.assertEqual(A._diff({"a": 1}, {"a": 1}), [])
        self.assertEqual(A._diff(None, None), [])

    def test_create_captures_after_as_changes(self):
        e = A.record("cli", "track add", "tracker", "1", "create",
                     after={"status": "applied", "company": "Acme"})
        self.assertIsNone(e["before"])
        self.assertEqual(e["changes"], [
            {"field": "company", "old": None, "new": "Acme"},
            {"field": "status", "old": None, "new": "applied"},
        ])

    def test_update_captures_before_after_for_undo(self):
        before = {"status": "applied", "notes": "waiting"}
        after = {"status": "offer", "notes": "waiting"}
        e = A.record("cli", "track update", "tracker", "1", "update",
                     before=before, after=after)
        self.assertEqual(e["before"], before)  # verbatim snapshots
        self.assertEqual(e["after"], after)
        self.assertEqual(e["changes"],
                         [{"field": "status", "old": "applied", "new": "offer"}])

    def test_values_kept_as_is_no_redaction(self):
        e = A.record("cli", "cmd", "tracker", "1", "update",
                     before={"salary": 150000}, after={"salary": 165000})
        self.assertEqual(e["changes"][0]["new"], 165000)


if __name__ == "__main__":
    unittest.main()
