"""Tests for the candid data-quality engine (batch 76, worker A).

Covers: quality.run_all / quality_score / render_report, quality.fixes
(strip_whitespace, normalize_status, fill_date_updated, apply_fixes),
the `candid quality` CLI handler (in-process), and the CLI end to end
(subprocess, with CANDID_DATA_DIR / CANDID_CONFIG_DIR pointed at tmp dirs).

Check modules from the sibling workers don't exist in this worktree, so
run_all is exercised with injected fake check modules; the registry's
skip-if-missing behavior is what makes the subprocess CLI deterministic.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import tracker as T  # noqa: E402
from candid.quality import Issue, quality_score, render_report, run_all  # noqa: E402
from candid.quality import fixes as QF  # noqa: E402


def _rec(**kw):
    r = {"id": 1, "company": "Acme", "role": "Data Scientist",
         "jd_link": "", "status": "saved", "notes": "",
         "date_added": "2026-09-01", "date_updated": "2026-09-01",
         "prep_pack": ""}
    r.update(kw)
    return r


def _fake_check_module(name, issues):
    mod = types.ModuleType(name)

    def run(apps, ctx):
        return [i for i in issues]
    mod.run = run
    mod._ctx_seen = None
    orig_run = mod.run

    def wrapped(apps, ctx):
        mod._ctx_seen = ctx
        return orig_run(apps, ctx)
    mod.run = wrapped
    sys.modules[name] = mod
    return mod


class QualityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="candid-quality-")
        self.data = Path(self.tmp.name)
        # Patch config paths in-process (config was imported once; rebind attrs).
        self._saved = {n: getattr(C, n) for n in
                       ("DATA_DIR", "TRACKER_PATH", "PROFILE_PATH")}
        C.DATA_DIR = self.data
        C.TRACKER_PATH = self.data / "tracker.json"
        C.PROFILE_PATH = self.data / "profile.json"
        self.addCleanup(self.restore)

    def restore(self):
        for n, v in self._saved.items():
            setattr(C, n, v)
        self.tmp.cleanup()

    def seed_tracker(self, records):
        C.TRACKER_PATH.write_text(json.dumps(records), encoding="utf-8")


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------

class RunAllTest(QualityBase):
    def test_loads_tracker_and_empty_profile(self):
        apps = [_rec(), _rec(id=2, company="Globex")]
        self.seed_tracker(apps)
        mod = _fake_check_module("candid.quality.fake_a", [])
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_a"]):
            got_apps, got_issues = run_all()
        self.assertEqual(len(got_apps), 2)
        self.assertEqual(got_issues, [])
        ctx = mod._ctx_seen
        self.assertEqual(ctx["data_dir"], self.data)
        self.assertEqual(ctx["profile"], {})  # missing profile.json -> {}
        self.assertEqual(ctx["today"], date.today())

    def test_collects_issues_from_checks(self):
        self.seed_tracker([_rec()])
        issues = [Issue("fake_ws", "warning", 1, "trailing space",
                        "trim it", "strip_whitespace")]
        _fake_check_module("candid.quality.fake_b", issues)
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_b"]):
            _, got = run_all()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].check, "fake_ws")

    def test_missing_check_module_is_skipped(self):
        self.seed_tracker([_rec()])
        with mock.patch("candid.quality.CHECKS",
                        ["candid.quality.does_not_exist_yet"]):
            apps, issues = run_all()
        self.assertEqual(len(apps), 1)
        self.assertEqual(issues, [])

    def test_module_without_run_raises_quality_error(self):
        self.seed_tracker([_rec()])
        sys.modules["candid.quality.fake_broken"] = types.ModuleType(
            "candid.quality.fake_broken")
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_broken"]):
            with self.assertRaises(Exception) as cm:
                run_all()
        self.assertEqual(type(cm.exception).__name__, "QualityError")


# ---------------------------------------------------------------------------
# quality_score
# ---------------------------------------------------------------------------

class ScoreTest(unittest.TestCase):
    def test_math(self):
        issues = ([Issue("c", "error", 1, "m")] +
                  [Issue("c", "warning", 1, "m") for _ in range(2)] +
                  [Issue("c", "info", 1, "m") for _ in range(3)])
        self.assertEqual(quality_score(issues), 100 - 10 - 6 - 3)

    def test_perfect_and_floor(self):
        self.assertEqual(quality_score([]), 100)
        self.assertEqual(quality_score([Issue("c", "error", 1, "m")] * 25), 0)


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

class ReportTest(unittest.TestCase):
    def setUp(self):
        self.issues = [
            Issue("dup.check", "error", 7, "two rows look identical",
                  "remove one of them"),
            Issue("ws.check", "warning", 3, "leading space in company",
                  "trim it", "strip_whitespace"),
            Issue("stale.check", "info", None, "no applications in 30 days",
                  "run jobs curate"),
        ]

    def test_text_grouped_by_severity(self):
        out = render_report(self.issues)
        self.assertIn("ERRORS (1):", out)
        self.assertIn("WARNINGS (1):", out)
        self.assertIn("INFOS (1):", out)
        self.assertIn("[dup.check]", out)
        self.assertIn("#7", out)
        self.assertIn("two rows look identical", out)
        self.assertIn("Suggestion: remove one of them", out)
        self.assertIn("(global)", out)
        # error section comes before warning before info
        self.assertLess(out.index("ERRORS"), out.index("WARNINGS"))
        self.assertLess(out.index("WARNINGS"), out.index("INFOS"))

    def test_json_mode(self):
        data = json.loads(render_report(self.issues, json_mode=True))
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["check"], "dup.check")
        self.assertEqual(data[0]["severity"], "error")
        self.assertEqual(data[0]["record_id"], 7)
        self.assertEqual(data[1]["auto_fix"], "strip_whitespace")

    def test_empty(self):
        self.assertIn("No data-quality issues", render_report([]))
        self.assertEqual(json.loads(render_report([], json_mode=True)), [])


# ---------------------------------------------------------------------------
# fixes
# ---------------------------------------------------------------------------

class FixesTest(QualityBase):
    def test_strip_whitespace(self):
        apps = [_rec(company=" Acme ", notes=" hi\n")]
        issues = [Issue("ws", "warning", 1, "ws", auto_fix="strip_whitespace")]
        new_apps, log = QF.apply_fixes(apps, issues, dry_run=True)
        self.assertEqual(new_apps[0]["company"], "Acme")
        self.assertEqual(new_apps[0]["notes"], "hi")
        # input untouched (dry run works on copies)
        self.assertEqual(apps[0]["company"], " Acme ")
        self.assertTrue(any("trimmed company, notes" in l for l in log))

    def test_strip_whitespace_noop(self):
        apps = [_rec()]
        new_apps, log = QF.apply_fixes(
            apps, [Issue("ws", "warning", 1, "ws", auto_fix="strip_whitespace")])
        self.assertEqual(new_apps[0]["company"], "Acme")
        self.assertTrue(any("nothing to change" in l for l in log))

    def test_normalize_status(self):
        apps = [_rec(status="Applied"), _rec(id=2, status="INTERVIEW")]
        issues = [Issue("cs", "warning", 1, "m", auto_fix="normalize_status"),
                  Issue("cs", "warning", 2, "m", auto_fix="normalize_status")]
        new_apps, log = QF.apply_fixes(apps, issues, dry_run=False)
        self.assertEqual(new_apps[0]["status"], "applied")
        self.assertEqual(new_apps[1]["status"], "INTERVIEW")  # unknown -> kept
        self.assertTrue(any("Applied" in l and "applied" in l for l in log))

    def test_fill_date_updated(self):
        apps = [_rec(date_updated=""), _rec(id=2, date_added="", date_updated="")]
        issues = [Issue("du", "info", 1, "m", auto_fix="fill_date_updated"),
                  Issue("du", "info", 2, "m", auto_fix="fill_date_updated")]
        new_apps, _ = QF.apply_fixes(apps, issues, dry_run=False)
        self.assertEqual(new_apps[0]["date_updated"], "2026-09-01")
        self.assertEqual(new_apps[1]["date_updated"], "")  # no date_added -> skip

    def test_unknown_fix_and_missing_record_skipped(self):
        apps = [_rec()]
        issues = [Issue("x", "warning", 1, "m", auto_fix="merge_records"),
                  Issue("x", "warning", 999, "m", auto_fix="strip_whitespace")]
        new_apps, log = QF.apply_fixes(apps, issues)
        self.assertEqual(len(new_apps), 1)
        self.assertTrue(any("unknown auto-fix" in l for l in log))
        self.assertTrue(any("no record #999" in l for l in log))
        self.assertTrue(any("0 fix(es) applied" in l for l in log))

    def test_never_deletes_records(self):
        apps = [_rec(), _rec(id=2)]
        new_apps, _ = QF.apply_fixes(apps, [], dry_run=False)
        self.assertEqual([a["id"] for a in new_apps], [1, 2])


# ---------------------------------------------------------------------------
# CLI handler (in-process, with a fake check module)
# ---------------------------------------------------------------------------

class CLIHandlerTest(QualityBase):
    def test_fix_applies_and_saves(self):
        self.seed_tracker([_rec(company=" Acme ", status="Applied")])
        issues = [Issue("ws", "warning", 1, "ws", "trim", "strip_whitespace"),
                  Issue("cs", "warning", 1, "cs", "fix", "normalize_status")]
        _fake_check_module("candid.quality.fake_cli", issues)
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_cli"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                CLI.main(["quality", "--fix"])
        saved = json.loads(C.TRACKER_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["company"], "Acme")
        self.assertEqual(saved[0]["status"], "applied")
        text = out.getvalue()
        self.assertIn("saved", text)
        self.assertIn("Quality score:", text)

    def test_dry_run_does_not_save(self):
        self.seed_tracker([_rec(company=" Acme ")])
        issues = [Issue("ws", "warning", 1, "ws", "trim", "strip_whitespace")]
        _fake_check_module("candid.quality.fake_cli2", issues)
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_cli2"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                CLI.main(["quality", "--fix", "--dry-run"])
        saved = json.loads(C.TRACKER_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["company"], " Acme ")
        self.assertIn("Dry run", out.getvalue())
        self.assertIn("(dry run)", out.getvalue())

    def test_min_severity_filters(self):
        self.seed_tracker([_rec()])
        issues = [Issue("a", "error", 1, "e"), Issue("b", "info", 1, "i")]
        _fake_check_module("candid.quality.fake_cli3", issues)
        with mock.patch("candid.quality.CHECKS", ["candid.quality.fake_cli3"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                CLI.main(["quality", "--min-severity", "warning"])
        text = out.getvalue()
        self.assertIn("ERRORS (1):", text)
        self.assertNotIn("INFOS", text)


# ---------------------------------------------------------------------------
# CLI end to end (subprocess, env-isolated)
# ---------------------------------------------------------------------------

class CLISubprocessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="candid-qcli-")
        self.env = dict(os.environ,
                        CANDID_DATA_DIR=self.tmp.name,
                        CANDID_CONFIG_DIR=self.tmp.name)
        # seed a tracker directly; real check modules are absent here, so
        # the registry skips them and the CLI should still run cleanly.
        recs = [_rec(company=" Acme ", status="Applied"),
                _rec(id=2, company="Globex", status="saved",
                     date_updated="")]
        Path(self.tmp.name, "tracker.json").write_text(json.dumps(recs))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "candid", *args],
                              cwd=str(ROOT), capture_output=True, text=True,
                              timeout=120, env=self.env)

    def test_quality_report(self):
        r = self.run_cli("quality")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("Quality score:", r.stdout)

    def test_quality_json(self):
        r = self.run_cli("quality", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsInstance(json.loads(r.stdout), list)

    def test_quality_fix_dry_run_is_noop(self):
        r = self.run_cli("quality", "--fix", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Dry run", r.stdout)
        recs = json.loads(Path(self.tmp.name, "tracker.json").read_text())
        self.assertEqual(recs[0]["company"], " Acme ")  # untouched

    def test_quality_min_severity_flag(self):
        r = self.run_cli("quality", "--min-severity", "warning")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Quality score:", r.stdout)

    def test_quality_help(self):
        r = self.run_cli("quality", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--fix", r.stdout)


if __name__ == "__main__":
    unittest.main()
