"""Tests for the batch-69 `search` CLI: advanced query routing, --explain,
--facet, --format csv/md, --out, saved searches, history, watches, and
clean (traceback-free) error handling.

Hermetic: config paths and candid.searchstore's module-level path
constants are redirected into a temp dir, so the real data dir is never
touched. Only the stdlib is used.
"""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import searchstore as SS  # noqa: E402
from candid import tracker as T  # noqa: E402


class SearchCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-searchcli-"))
        self._saved_config = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved_config[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

        # searchstore computes its paths at import time from the old
        # DATA_DIR; repoint the module constants at the temp dir.
        self._saved_store = (SS.SAVED_PATH, SS.HISTORY_PATH, SS.WATCH_PATH)
        SS.SAVED_PATH = self.tmp / "saved_searches.json"
        SS.HISTORY_PATH = self.tmp / "search_history.jsonl"
        SS.WATCH_PATH = self.tmp / "search_watch.json"

        # Seed a tiny fake tracker.
        T.add("Acme Corp", "Backend Engineer", status="applied",
              source="referral", notes="python services and queues")
        T.add("Globex", "Data Scientist", status="rejected",
              source="jobs-board", notes="machine learning models")
        T.add("Acme Corp", "Frontend Engineer", status="saved",
              source="referral", notes="react and typescript")

    def tearDown(self):
        for name, val in self._saved_config.items():
            setattr(C, name, val)
        (SS.SAVED_PATH, SS.HISTORY_PATH, SS.WATCH_PATH) = self._saved_store

    def run_cli(self, argv, stdin=""):
        """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin:
            sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    CLI.main(argv)
                except SystemExit as e:
                    code = e.code
                    return (code if isinstance(code, int) else 1,
                            out.getvalue(), err.getvalue())
                return 0, out.getvalue(), err.getvalue()
        finally:
            sys.stdin = old_stdin

    def history_queries(self):
        return [e["query"] for e in SS.get_history(100)]


# ---------------------------------------------------------------------------
# Bare query routing + flags
# ---------------------------------------------------------------------------

class BareQueryTest(SearchCLIBase):
    def test_bare_query_still_works(self):
        code, out, err = self.run_cli(["search", "python"])
        self.assertEqual(code, 0, err)
        self.assertIn("match(es)", out)
        self.assertIn("Acme Corp", out)

    def test_bare_query_multiword_joined(self):
        code, out, err = self.run_cli(["search", "machine", "learning"])
        self.assertEqual(code, 0, err)
        self.assertIn("Globex", out)

    def test_advanced_query_or_not(self):
        code, out, err = self.run_cli(
            ["search", "company:acme", "(backend", "OR", "frontend)"])
        self.assertEqual(code, 0, err)
        self.assertIn("Acme Corp", out)
        self.assertNotIn("Globex", out)

    def test_json_still_works(self):
        code, out, err = self.run_cli(["search", "python", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(isinstance(data, list) and len(data) >= 1)

    def test_explain_prints_breakdown(self):
        code, out, err = self.run_cli(
            ["search", "company:acme", "NOT", "intern", "--explain"])
        self.assertEqual(code, 0, err)
        self.assertIn("Advanced query", out)
        self.assertIn("[excluded]", out)

    def test_dash_negation_needs_double_dash(self):
        # "-term" starts with a dash so argparse reads it as a flag; the
        # documented workaround is a "--" separator.
        code, out, err = self.run_cli(
            ["search", "--explain", "--", "company:acme", "-intern"])
        self.assertEqual(code, 0, err)
        self.assertIn("[excluded]", out)

    def test_facet_kind_counts(self):
        code, out, err = self.run_cli(["search", "acme", "--facet", "kind"])
        self.assertEqual(code, 0, err)
        self.assertIn("By kind:", out)
        self.assertIn("application: 2", out)

    def test_facet_status_uses_tracker(self):
        code, out, err = self.run_cli(["search", "acme", "--facet", "status"])
        self.assertEqual(code, 0, err)
        self.assertIn("By status:", out)
        self.assertIn("applied: 1", out)
        self.assertIn("saved: 1", out)

    def test_facet_source(self):
        code, out, err = self.run_cli(["search", "engineer", "--facet", "source"])
        self.assertEqual(code, 0, err)
        self.assertIn("By source:", out)
        self.assertIn("referral: 2", out)

    def test_format_csv(self):
        code, out, err = self.run_cli(["search", "acme", "--format", "csv"])
        self.assertEqual(code, 0, err)
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[0], ["kind", "ref", "title", "score", "snippet"])
        self.assertTrue(any(r[0] == "application" for r in rows[1:]))

    def test_format_md(self):
        code, out, err = self.run_cli(["search", "acme", "--format", "md"])
        self.assertEqual(code, 0, err)
        self.assertIn("| kind | ref | title | score | snippet |", out)
        self.assertIn("Acme Corp", out)

    def test_out_writes_file_and_creates_parents(self):
        dest = self.tmp / "reports" / "nested" / "hits.md"
        code, out, err = self.run_cli(
            ["search", "acme", "--format", "md", "--out", str(dest)])
        self.assertEqual(code, 0, err)
        self.assertTrue(dest.exists())
        self.assertIn("| kind | ref | title | score | snippet |",
                      dest.read_text(encoding="utf-8"))
        self.assertIn("Wrote", out)

    def test_out_text_includes_explain_and_facet(self):
        dest = self.tmp / "hits.txt"
        code, out, err = self.run_cli(
            ["search", "acme", "--explain", "--facet", "kind",
             "--out", str(dest)])
        self.assertEqual(code, 0, err)
        text = dest.read_text(encoding="utf-8")
        self.assertIn("Advanced query", text)
        self.assertIn("By kind:", text)


# ---------------------------------------------------------------------------
# Saved searches / run / unsave
# ---------------------------------------------------------------------------

class SavedSearchTest(SearchCLIBase):
    def test_save_saved_run_unsave_roundtrip(self):
        code, out, err = self.run_cli(
            ["search", "save", "infra", "company:acme", "backend"])
        self.assertEqual(code, 0, err)
        self.assertIn("Saved search", out)

        code, out, err = self.run_cli(["search", "saved"])
        self.assertEqual(code, 0, err)
        self.assertIn("infra: company:acme backend", out)

        code, out, err = self.run_cli(["search", "run", "infra"])
        self.assertEqual(code, 0, err)
        self.assertIn("Acme Corp", out)
        self.assertNotIn("Globex", out)

        code, out, err = self.run_cli(["search", "unsave", "infra"])
        self.assertEqual(code, 0, err)
        self.assertIn("Deleted", out)

        code, out, err = self.run_cli(["search", "saved"])
        self.assertEqual(code, 0, err)
        self.assertIn("No saved searches.", out)

    def test_saved_empty_message(self):
        code, out, err = self.run_cli(["search", "saved"])
        self.assertEqual(code, 0, err)
        self.assertIn("No saved searches.", out)

    def test_save_needs_name_and_query(self):
        code, out, err = self.run_cli(["search", "save", "onlyname"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_run_honors_flags(self):
        self.run_cli(["search", "save", "ml", "machine"])
        code, out, err = self.run_cli(
            ["search", "run", "ml", "--format", "csv"])
        self.assertEqual(code, 0, err)
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[0], ["kind", "ref", "title", "score", "snippet"])


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class HistoryTest(SearchCLIBase):
    def test_bare_query_and_run_are_logged_newest_first(self):
        self.run_cli(["search", "python"])
        self.run_cli(["search", "machine"])
        self.run_cli(["search", "save", "acmeq", "acme"])
        self.run_cli(["search", "run", "acmeq"])
        code, out, err = self.run_cli(["search", "history"])
        self.assertEqual(code, 0, err)
        queries = self.history_queries()
        # run logs the resolved saved query; save/unsave/watch log nothing.
        self.assertEqual(queries, ["acme", "machine", "python"])
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 3)

    def test_history_limit_flag(self):
        self.run_cli(["search", "python"])
        self.run_cli(["search", "machine"])
        code, out, err = self.run_cli(["search", "history", "--limit", "1"])
        self.assertEqual(code, 0, err)
        self.assertIn("machine", out)
        self.assertNotIn("python", out)

    def test_clear_history(self):
        self.run_cli(["search", "python"])
        code, out, err = self.run_cli(["search", "clear-history"])
        self.assertEqual(code, 0, err)
        self.assertIn("cleared", out.lower())
        code, out, err = self.run_cli(["search", "history"])
        self.assertEqual(code, 0, err)
        self.assertIn("No search history.", out)

    def test_watch_logs_nothing(self):
        self.run_cli(["search", "save", "acme", "acme"])
        self.run_cli(["search", "watch", "acme"])
        self.assertEqual(self.history_queries(), [])


# ---------------------------------------------------------------------------
# Watch
# ---------------------------------------------------------------------------

class WatchTest(SearchCLIBase):
    def test_watch_first_run_all_new_second_run_empty(self):
        self.run_cli(["search", "save", "acme", "acme"])
        code, out, err = self.run_cli(["search", "watch", "acme"])
        self.assertEqual(code, 0, err)
        self.assertIn("2 new match(es) since last check.", out)
        self.assertIn("Acme Corp", out)

        code, out, err = self.run_cli(["search", "watch", "acme"])
        self.assertEqual(code, 0, err)
        self.assertIn("0 new match(es) since last check.", out)

    def test_watch_sees_new_app_added_later(self):
        self.run_cli(["search", "save", "acme", "acme"])
        self.run_cli(["search", "watch", "acme"])
        T.add("Acme Corp", "DevOps Engineer", status="applied",
              source="referral", notes="kubernetes")
        code, out, err = self.run_cli(["search", "watch", "acme"])
        self.assertEqual(code, 0, err)
        self.assertIn("1 new match(es) since last check.", out)
        self.assertIn("DevOps Engineer", out)


# ---------------------------------------------------------------------------
# Clean errors (exit code 2, no tracebacks)
# ---------------------------------------------------------------------------

class ErrorTest(SearchCLIBase):
    def assert_clean_error(self, argv):
        code, out, err = self.run_cli(argv)
        self.assertEqual(code, 2, f"{argv} exited {code}, stderr: {err}")
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)
        return err

    def test_bad_query_syntax(self):
        err = self.assert_clean_error(["search", "(unbalanced"])
        self.assertIn("error:", err)

    def test_bad_regex(self):
        self.assert_clean_error(["search", "/([/"])

    def test_run_unknown_name(self):
        err = self.assert_clean_error(["search", "run", "nope"])
        self.assertIn("nope", err)

    def test_unsave_unknown_name(self):
        err = self.assert_clean_error(["search", "unsave", "nope"])
        self.assertIn("nope", err)

    def test_watch_unknown_name(self):
        err = self.assert_clean_error(["search", "watch", "nope"])
        self.assertIn("nope", err)

    def test_save_bad_name(self):
        self.assert_clean_error(["search", "save", "bad name!", "python"])

    def test_run_missing_name(self):
        self.assert_clean_error(["search", "run"])


if __name__ == "__main__":
    unittest.main()
