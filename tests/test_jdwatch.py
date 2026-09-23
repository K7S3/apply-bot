"""Tests for candid jdwatch (batch 30): JD change detection.

Covers: normalization + hashing, requirement extraction/diff, field
extraction (salary/location/employment type), change detection + severity
classification, snapshot store, alert rules + dedupe + thresholds, repost
detection, timeline, digest, watch list, and the `jdwatch` CLI wiring.

Run: CANDID_DATA_DIR=/tmp/candid-test-jdwatch python3 -m pytest tests/test_jdwatch.py -q
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import jdwatch as W  # noqa: E402
from candid import __main__ as CLI  # noqa: E402


JD_V1 = """Software Engineer, Backend — Acme Corp
Location: New York, NY (Hybrid)
Salary: $150,000 - $180,000 per year
Employment: Full-time position

About the role:
We are a great team building cool distributed systems.

Requirements:
- 5+ years of Python experience
- Strong distributed systems background
- Experience with PostgreSQL
"""

JD_V2_SALARY = JD_V1.replace("$150,000 - $180,000 per year",
                              "$170,000 - $200,000 per year")

JD_V2_LOCATION = JD_V1.replace("Location: New York, NY (Hybrid)",
                               "Location: Boston, MA (On-site)")

JD_V2_REQ_ADDED = JD_V1.replace("- Experience with PostgreSQL",
                                "- Experience with PostgreSQL\n- Experience with Kubernetes")

JD_V2_REQ_REMOVED = JD_V1.replace("- Experience with PostgreSQL\n", "")

JD_V2_REQ_REWORDED = JD_V1.replace("Strong distributed systems background",
                                   "Solid background in distributed systems")

JD_V2_BODY_EDIT = JD_V1.replace("We are a great team building cool distributed systems.",
                                 "We are a fantastic team building neat distributed systems.")

JD_V2_EMPTYPE = JD_V1.replace("Full-time position", "Contract position")

JD_V2_COSMETIC = JD_V1.replace("About the role:", "About the role!!!")


class JDWatchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old
        self.tmp.cleanup()

    # -- normalization / hashing -------------------------------------------
    def test_normalize_strips_html(self):
        self.assertNotIn("<b>", W.normalize_jd("<b>hello</b>"))
        self.assertIn("hello", W.normalize_jd("<b>hello</b>"))

    def test_normalize_collapses_whitespace(self):
        self.assertEqual(W.normalize_jd("a\n\n  b\tc"), "a b c")

    def test_snapshot_hash_stable(self):
        self.assertEqual(W.snapshot_hash(JD_V1), W.snapshot_hash(JD_V1))

    def test_snapshot_hash_case_insensitive(self):
        self.assertEqual(W.snapshot_hash(JD_V1), W.snapshot_hash(JD_V1.upper()))

    def test_snapshot_hash_differs_on_content_change(self):
        self.assertNotEqual(W.snapshot_hash(JD_V1), W.snapshot_hash(JD_V2_SALARY))

    # -- requirements -------------------------------------------------------
    def test_extract_bullets(self):
        text = "Intro\n- alpha\n* beta\n• gamma\n1. delta\n2) epsilon\n"
        reqs = W.extract_requirements(text)
        self.assertEqual(reqs, ["alpha", "beta", "gamma", "delta", "epsilon"])

    def test_extract_under_heading(self):
        text = "Qualifications:\nDeep Python knowledge\nStrong SQL skills\n\nBenefits:\nFree lunch\n"
        reqs = W.extract_requirements(text)
        self.assertIn("Deep Python knowledge", reqs)
        self.assertIn("Strong SQL skills", reqs)
        self.assertNotIn("Free lunch", reqs)

    def test_extract_dedupes(self):
        text = "- alpha\n- Alpha\n"
        self.assertEqual(W.extract_requirements(text), ["alpha"])

    def test_diff_added_removed(self):
        d = W.diff_requirements(["a", "b"], ["a", "c"])
        self.assertEqual(d["added"], ["c"])
        self.assertEqual(d["removed"], ["b"])
        self.assertEqual(d["modified"], [])

    def test_diff_reworded_pairs_as_modified(self):
        d = W.diff_requirements(["Strong distributed systems background"],
                                ["Solid background in distributed systems"])
        self.assertEqual(d["added"], [])
        self.assertEqual(d["removed"], [])
        self.assertEqual(len(d["modified"]), 1)

    def test_diff_dissimilar_replace_becomes_add_remove(self):
        d = W.diff_requirements(["Python wizardry"], ["Expert underwater basket weaving"])
        self.assertEqual(len(d["modified"]), 0)
        self.assertEqual(d["added"], ["Expert underwater basket weaving"])
        self.assertEqual(d["removed"], ["Python wizardry"])

    # -- field extraction ----------------------------------------------------
    def test_salary_band_extracted(self):
        band = W.extract_salary_band(JD_V1)
        self.assertIsNotNone(band)
        self.assertEqual(band["low"], 150000.0)
        self.assertEqual(band["high"], 180000.0)

    def test_salary_band_absent(self):
        self.assertIsNone(W.extract_salary_band("No pay mentioned here."))

    def test_location_hint_line(self):
        self.assertEqual(W.extract_location_hint(JD_V1), "new york, ny (hybrid)")

    def test_location_hint_work_model(self):
        self.assertEqual(W.extract_location_hint("This is a remote role."), "remote")
        self.assertEqual(W.extract_location_hint("Hybrid schedule."), "hybrid")
        self.assertEqual(W.extract_location_hint("On-site five days."), "onsite")

    def test_employment_type(self):
        self.assertEqual(W.extract_employment_type(JD_V1), "full-time")
        self.assertEqual(W.extract_employment_type(JD_V2_EMPTYPE), "contract")
        self.assertEqual(W.extract_employment_type("no mention"), "")

    # -- change detection / severity ------------------------------------------
    def test_identical_is_unchanged(self):
        ch = W.detect_changes(JD_V1, JD_V1)
        self.assertFalse(ch["changed"])
        self.assertEqual(ch["severity"], "cosmetic")
        self.assertEqual(ch["summary"], "no changes")

    def test_formatting_only_is_cosmetic(self):
        ch = W.detect_changes(JD_V1, JD_V2_COSMETIC)
        self.assertTrue(ch["changed"])
        self.assertEqual(ch["severity"], "cosmetic")
        self.assertEqual(ch["reasons"], ["formatting_only"])
        self.assertIn("formatting only", ch["summary"])

    def test_salary_change_is_material(self):
        ch = W.detect_changes(JD_V1, JD_V2_SALARY)
        self.assertEqual(ch["severity"], "material")
        self.assertIn("salary_changed", ch["reasons"])
        self.assertIn("salary", ch["fields"])
        self.assertIn("summary", ch)
        self.assertIn("$150,000-$180,000/yr", ch["summary"])

    def test_salary_added_and_removed_are_material(self):
        no_pay = JD_V1.replace("Salary: $150,000 - $180,000 per year\n", "")
        ch = W.detect_changes(no_pay, JD_V1)
        self.assertIn("salary_added", ch["reasons"])
        self.assertEqual(ch["severity"], "material")
        ch2 = W.detect_changes(JD_V1, no_pay)
        self.assertIn("salary_removed", ch2["reasons"])
        self.assertEqual(ch2["severity"], "material")

    def test_location_change_is_material(self):
        ch = W.detect_changes(JD_V1, JD_V2_LOCATION)
        self.assertIn("location_changed", ch["reasons"])
        self.assertEqual(ch["severity"], "material")

    def test_employment_type_change_is_material(self):
        ch = W.detect_changes(JD_V1, JD_V2_EMPTYPE)
        self.assertIn("employment_type_changed", ch["reasons"])
        self.assertEqual(ch["severity"], "material")

    def test_requirement_added_is_material(self):
        ch = W.detect_changes(JD_V1, JD_V2_REQ_ADDED)
        self.assertIn("requirements_added", ch["reasons"])
        self.assertEqual(ch["severity"], "material")
        self.assertTrue(any("Kubernetes" in r for r in ch["fields"]["requirements_added"]))

    def test_requirement_removed_is_material(self):
        ch = W.detect_changes(JD_V1, JD_V2_REQ_REMOVED)
        self.assertIn("requirements_removed", ch["reasons"])
        self.assertEqual(ch["severity"], "material")

    def test_reword_only_is_minor(self):
        ch = W.detect_changes(JD_V1, JD_V2_REQ_REWORDED)
        self.assertIn("requirements_reworded", ch["reasons"])
        self.assertNotIn("requirements_added", ch["reasons"])
        self.assertNotIn("requirements_removed", ch["reasons"])
        self.assertEqual(ch["severity"], "minor")

    def test_body_edit_is_minor(self):
        ch = W.detect_changes(JD_V1, JD_V2_BODY_EDIT)
        self.assertIn("body_edited", ch["reasons"])
        self.assertEqual(ch["severity"], "minor")

    def test_material_wins_over_minor(self):
        both = JD_V2_SALARY.replace(
            "We are a great team building cool distributed systems.",
            "We are a fantastic team building neat distributed systems.")
        ch = W.detect_changes(JD_V1, both)
        self.assertEqual(ch["severity"], "material")
        self.assertIn("salary_changed", ch["reasons"])

    def test_classify_severity_direct(self):
        self.assertEqual(W.classify_severity(["body_edited"]), "minor")
        self.assertEqual(W.classify_severity(["location_changed"]), "material")
        self.assertEqual(W.classify_severity(["formatting_only"]), "cosmetic")
        self.assertEqual(W.classify_severity([]), "cosmetic")

    def test_render_diff_output(self):
        out = W.render_diff(JD_V1, JD_V2_REQ_ADDED, old_label="v1", new_label="v2")
        self.assertIn("severity: material", out)
        self.assertIn("Kubernetes", out)
        self.assertIn("--- v1", out)
        self.assertIn("+++ v2", out)

    def test_render_diff_no_changes(self):
        self.assertIn("no changes", W.render_diff(JD_V1, JD_V1))

    # -- snapshot store -------------------------------------------------------
    def test_first_snapshot_is_new(self):
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        self.assertEqual(res["status"], "new")
        self.assertIsNone(res["change"])
        self.assertIsNone(res["alert"])
        self.assertEqual(len(res["sha256"]), 64)

    def test_duplicate_snapshot_is_unchanged(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        self.assertEqual(res["status"], "unchanged")
        self.assertEqual(len(W.get_snapshots("Acme", "Backend Engineer")), 1)

    def test_whitespace_only_edit_is_unchanged(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V1 + "\n\n   \n")
        self.assertEqual(res["status"], "unchanged")

    def test_changed_snapshot_emits_alert(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V2_SALARY)
        self.assertEqual(res["status"], "changed")
        self.assertEqual(res["change"]["severity"], "material")
        self.assertIsNotNone(res["alert"])
        self.assertEqual(res["alert"]["severity"], "material")
        self.assertEqual(len(W.list_alerts(unread_only=True)), 1)

    def test_cosmetic_change_records_no_alert(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V2_COSMETIC)
        self.assertEqual(res["status"], "changed")
        self.assertEqual(res["change"]["severity"], "cosmetic")
        self.assertIsNone(res["alert"])
        self.assertEqual(W.list_alerts(), [])

    def test_threshold_material_suppresses_minor_alert(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        res = W.snapshot_jd("Acme", "Backend Engineer", JD_V2_BODY_EDIT,
                            threshold="material")
        self.assertEqual(res["status"], "changed")
        self.assertEqual(res["change"]["severity"], "minor")
        self.assertIsNone(res["alert"])

    def test_threshold_env_var(self):
        os.environ["CANDID_JDWATCH_THRESHOLD"] = "material"
        try:
            self.assertEqual(W.default_threshold(), "material")
            self.assertTrue(W.meets_threshold("material"))
            self.assertFalse(W.meets_threshold("minor"))
        finally:
            del os.environ["CANDID_JDWATCH_THRESHOLD"]
        self.assertEqual(W.default_threshold(), "minor")

    def test_meets_threshold_ordering(self):
        self.assertTrue(W.meets_threshold("material", "minor"))
        self.assertTrue(W.meets_threshold("minor", "minor"))
        self.assertFalse(W.meets_threshold("cosmetic", "minor"))
        self.assertTrue(W.meets_threshold("cosmetic", "cosmetic"))

    def test_alert_dedupe(self):
        a1 = W.record_alert(company="Acme", role="Backend Engineer", key="k",
                            severity="material", reasons=["salary_changed"],
                            summary="s", old_sha="o", new_sha="n")
        a2 = W.record_alert(company="Acme", role="Backend Engineer", key="k",
                            severity="material", reasons=["salary_changed"],
                            summary="s", old_sha="o", new_sha="n")
        self.assertEqual(a1["id"], a2["id"])
        self.assertEqual(len(W.list_alerts()), 1)

    def test_empty_jd_raises(self):
        with self.assertRaises(W.JDWatchError):
            W.snapshot_jd("Acme", "Backend Engineer", "   ")

    def test_missing_company_role_raises(self):
        with self.assertRaises(W.JDWatchError):
            W.snapshot_jd("", "Backend Engineer", JD_V1)
        with self.assertRaises(W.JDWatchError):
            W.snapshot_jd("Acme", "  ", JD_V1)

    def test_snapshot_key_case_insensitive(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        self.assertEqual(len(W.get_snapshots("ACME", "backend engineer")), 1)

    def test_list_snapshot_keys(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Frontend Engineer", JD_V1)
        keys = W.list_snapshot_keys()
        self.assertEqual(len(keys), 2)
        roles = {k["role"] for k in keys}
        self.assertEqual(roles, {"Backend Engineer", "Frontend Engineer"})

    # -- reposts --------------------------------------------------------------
    def test_repost_detected_with_altered_requirements(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Senior Backend Engineer", JD_V2_REQ_ADDED)
        rows = W.find_reposts("Acme")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertFalse(r["identical"])
        self.assertGreaterEqual(r["similarity"], 0.75)
        self.assertTrue(any("Kubernetes" in x for x in r["requirements_added_in_b"]))

    def test_identical_repost_flagged(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Backend Engineer II", JD_V1)
        rows = W.find_reposts("Acme")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["identical"])

    def test_dissimilar_postings_not_reposts(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        other = "Chef wanted. Must know French cuisine. Paris location."
        W.snapshot_jd("Acme", "Executive Chef", other)
        self.assertEqual(W.find_reposts("Acme"), [])

    def test_repost_company_filter(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Globex", "Backend Engineer", JD_V1)
        self.assertEqual(len(W.find_reposts("Acme")), 0)
        self.assertEqual(len(W.find_reposts()), 1)

    def test_repost_min_similarity(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Senior Backend Engineer", JD_V2_REQ_ADDED)
        self.assertEqual(W.find_reposts("Acme", min_similarity=0.999), [])

    # -- timeline / digest / alerts --------------------------------------------
    def test_timeline_chronological(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Backend Engineer", JD_V2_SALARY)
        W.snapshot_jd("Acme", "Backend Engineer", JD_V2_REQ_ADDED)
        events = W.timeline("Acme", "Backend Engineer")
        self.assertEqual([e["event"] for e in events],
                         ["first_seen", "changed", "changed"])
        self.assertIsNone(events[0]["severity"])
        self.assertEqual(events[1]["severity"], "material")
        # chronological order
        times = [e["captured_at"] for e in events]
        self.assertEqual(times, sorted(times))

    def test_timeline_empty(self):
        self.assertEqual(W.timeline("Nobody", "No Role"), [])

    def test_digest_contains_changes(self):
        W.snapshot_jd("Acme", "Backend", JD_V1)
        W.snapshot_jd("Acme", "Backend", JD_V2_SALARY)
        out = W.digest(7)
        self.assertIn("# JD change digest", out)
        self.assertIn("Acme — Backend", out)
        self.assertIn("MATERIAL", out)
        self.assertIn("salary band", out)

    def test_digest_empty_window(self):
        out = W.digest(7)
        self.assertIn("No JD snapshots captured", out)

    def test_alerts_unread_and_mark_read(self):
        W.snapshot_jd("Acme", "Backend Engineer", JD_V1)
        W.snapshot_jd("Acme", "Backend Engineer", JD_V2_SALARY)
        self.assertEqual(len(W.list_alerts(unread_only=True)), 1)
        self.assertEqual(W.mark_alerts_read(), 1)
        self.assertEqual(W.list_alerts(unread_only=True), [])
        self.assertEqual(len(W.list_alerts()), 1)
        self.assertEqual(W.mark_alerts_read(), 0)

    # -- watch list -------------------------------------------------------------
    def test_watch_unwatch_list(self):
        r = W.watch("Acme", "Backend Engineer")
        self.assertTrue(r["watched"])
        r2 = W.watch("Acme", "Backend Engineer")
        self.assertFalse(r2["watched"])
        self.assertEqual(len(W.list_watched()), 1)
        self.assertTrue(W.unwatch("Acme", "Backend Engineer")["unwatched"])
        self.assertFalse(W.unwatch("Acme", "Backend Engineer")["unwatched"])
        self.assertEqual(W.list_watched(), [])

    # -- CLI ---------------------------------------------------------------------
    def _run_cli(self, argv, stdin_text=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        try:
            if stdin_text is not None:
                sys.stdin = io.StringIO(stdin_text)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    CLI.main(argv)
                except SystemExit as e:
                    return out.getvalue(), err.getvalue(), e.code
            return out.getvalue(), err.getvalue(), 0
        finally:
            sys.stdin = old_stdin

    def _jd_file(self, text):
        p = Path(self.tmp.name) / "jd.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_cli_snapshot_changed_with_alert(self):
        jd = self._jd_file(JD_V1)
        out, _, code = self._run_cli(
            ["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend", "--jd", jd])
        self.assertEqual(code, 0)
        self.assertIn("Snapshot captured", out)
        out, _, code = self._run_cli(
            ["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
             "--jd", self._jd_file(JD_V2_SALARY)])
        self.assertEqual(code, 0)
        self.assertIn("CHANGED (material)", out)
        self.assertIn("ALERT", out)

    def test_cli_snapshot_json(self):
        out, _, code = self._run_cli(
            ["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
             "--jd", self._jd_file(JD_V1), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["status"], "new")

    def test_cli_snapshot_stdin(self):
        out, _, code = self._run_cli(
            ["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend", "--jd", "-"],
            stdin_text=JD_V1)
        self.assertEqual(code, 0)
        self.assertIn("Snapshot captured", out)

    def test_cli_diff(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V2_REQ_ADDED)])
        out, _, code = self._run_cli(
            ["jdwatch", "diff", "--company", "Acme", "--role", "Backend"])
        self.assertEqual(code, 0)
        self.assertIn("severity: material", out)
        self.assertIn("Kubernetes", out)

    def test_cli_diff_needs_two_snapshots(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        _, err, code = self._run_cli(
            ["jdwatch", "diff", "--company", "Acme", "--role", "Backend"])
        self.assertEqual(code, 1)
        self.assertIn("Need at least 2 snapshots", err)

    def test_cli_reposts_json(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Senior Backend",
                       "--jd", self._jd_file(JD_V2_REQ_ADDED)])
        out, _, code = self._run_cli(["jdwatch", "reposts", "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["identical"])

    def test_cli_timeline(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        out, _, code = self._run_cli(
            ["jdwatch", "timeline", "--company", "Acme", "--role", "Backend"])
        self.assertEqual(code, 0)
        self.assertIn("first_seen", out)

    def test_cli_alerts_and_mark_read(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V2_SALARY)])
        out, _, code = self._run_cli(["jdwatch", "alerts", "--unread"])
        self.assertEqual(code, 0)
        self.assertIn("[material]", out)
        out, _, code = self._run_cli(["jdwatch", "alerts", "--mark-read"])
        self.assertIn("Marked 1 alert(s) read", out)

    def test_cli_digest(self):
        self._run_cli(["jdwatch", "snapshot", "--company", "Acme", "--role", "Backend",
                       "--jd", self._jd_file(JD_V1)])
        out, _, code = self._run_cli(["jdwatch", "digest", "--days", "7"])
        self.assertEqual(code, 0)
        self.assertIn("JD change digest", out)

    def test_cli_watch_list(self):
        out, _, code = self._run_cli(
            ["jdwatch", "watch", "--company", "Acme", "--role", "Backend"])
        self.assertEqual(code, 0)
        self.assertIn("Watching Acme", out)
        out, _, code = self._run_cli(["jdwatch", "list"])
        self.assertIn("Watched roles (1)", out)

    def test_cli_missing_role_friendly_error(self):
        _, err, code = self._run_cli(
            ["jdwatch", "snapshot", "--company", "Acme", "--jd", self._jd_file(JD_V1)])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("jdwatch --help", err)
        self.assertNotIn("Traceback", err)

    def test_cli_typo_suggests_jdwatch(self):
        _, err, code = self._run_cli(["jdwtch"])
        self.assertEqual(code, 2)
        self.assertIn("jdwatch", err)

    def test_cli_jdwatch_in_help(self):
        out, _, code = self._run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("jdwatch", out)

    def test_fetch_jd_long_piped_text(self):
        # Regression: long stdin/pasted JD text must not be probed as a file
        # path (used to raise OSError: File name too long).
        from candid import match as M
        long_jd = (JD_V1 + "\nExtra context. ") * 20
        self.assertGreater(len(long_jd), 2000)
        self.assertIn("Software Engineer", M.fetch_jd(long_jd))


if __name__ == "__main__":
    unittest.main()
