"""Tests for the red-flag report layer and CLI. Run: python -m unittest discover -s tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _flag(flag_id, severity, category="compensation", title=None,
          explanation=None, evidence=(), suggestion=""):
    from candid.redflags.core import Flag
    return Flag(
        flag_id=flag_id,
        title=title or flag_id,
        severity=severity,
        category=category,
        explanation=explanation or f"Why {flag_id} matters. Plain language here.",
        evidence=list(evidence),
        suggestion=suggestion,
    )


def _analysis(flags, risk_score=0, verdict="clean"):
    return {
        "flags": list(flags),
        "flags_json": [f.to_dict() for f in flags],
        "risk_score": risk_score,
        "verdict": verdict,
    }


class ReportTest(unittest.TestCase):
    def setUp(self):
        from candid.redflags import report as R
        self.R = R

    def test_format_report_verdict_and_score(self):
        out = self.R.format_report(_analysis([], 0, "clean"))
        self.assertIn("Verdict: CLEAN", out)
        self.assertIn("Risk score: 0/100", out)

    def test_format_report_groups_by_severity(self):
        flags = [
            _flag("x.low", "low", evidence=["low snippet"], suggestion="Ask."),
            _flag("x.high", "high", explanation="High flag here. Second sentence."),
            _flag("x.critical", "critical"),
        ]
        out = self.R.format_report(_analysis(flags, 55, "caution"))
        self.assertIn("Verdict: CAUTION", out)
        self.assertIn("== CRITICAL ==", out)
        self.assertIn("== HIGH ==", out)
        self.assertIn("== LOW ==", out)
        # worst first
        self.assertLess(out.index("== CRITICAL =="), out.index("== HIGH =="))
        self.assertLess(out.index("== HIGH =="), out.index("== LOW =="))
        self.assertIn("High flag here.", out)
        self.assertIn('Evidence: "low snippet"', out)
        self.assertIn("Suggestion: Ask.", out)

    def test_format_report_lists_greens_last(self):
        flags = [
            _flag("x.high", "high"),
            _flag("green.salary_range", "info", category="green",
                  title="Salary range listed"),
        ]
        out = self.R.format_report(_analysis(flags, 15, "clean"))
        self.assertIn("Green flags (positive signals):", out)
        self.assertIn("+ Salary range listed", out)
        self.assertLess(out.index("== HIGH =="),
                        out.index("Green flags (positive signals):"))

    def test_format_report_green_adjustment(self):
        flags = [
            _flag("x.high", "high"),
            _flag("green.salary_range", "info", category="green",
                  title="Salary range listed"),
            _flag("green.equal_opportunity", "info", category="green",
                  title="Equal opportunity statement"),
        ]
        out = self.R.format_report(_analysis(flags, 44, "caution"))
        # -3 per green flag -> 44 - 6 = 38
        self.assertIn("Risk score: 38/100", out)
        self.assertIn("reduced from 44 by 2 green flag(s)", out)

    def test_format_report_no_flags(self):
        out = self.R.format_report(_analysis([], 0, "clean"))
        self.assertIn("No flags found", out)

    def test_check_file_missing(self):
        with self.assertRaises(self.R.RedFlagError):
            self.R.check_file("/nonexistent/jd.txt")
        with self.assertRaises(ValueError):  # RedFlagError subclasses ValueError
            self.R.check_file("/nonexistent/jd.txt")

    def test_check_file_reads_and_analyzes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "jd.md"
            p.write_text("Salary: $120k-$150k. We are an equal opportunity employer.")
            out = self.R.check_file(p)
            self.assertIn("Verdict: CLEAN", out)
            self.assertIn("+ Salary range listed", out)
            self.assertIn("+ Equal opportunity statement", out)

    def test_analyze_file_returns_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "jd.txt"
            p.write_text("Salary: $120k-$150k.")
            a = self.R.analyze_file(p)
            self.assertEqual("clean", a["verdict"])
            self.assertTrue(any(f.flag_id == "green.salary_range"
                                for f in a["flags"]))

    def test_scan_directory(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.txt").write_text(
                "Salary: $120k-$150k.\n"
                "Responsibilities: Build features in Python. "
                "You will join the platform team, "
                "reporting to the engineering manager.")
            (d / "b.md").write_text("Just a plain posting.")
            (d / "ignore.pdf").write_text("not a jd")
            results = self.R.scan_directory(d)
            self.assertEqual(["a.txt", "b.md"], [r["filename"] for r in results])
            by_name = {r["filename"]: r for r in results}
            self.assertEqual("clean", by_name["a.txt"]["verdict"])
            self.assertEqual(0, by_name["a.txt"]["risk_score"])
            self.assertEqual(0, by_name["a.txt"]["flag_count"])
            self.assertEqual(1, by_name["a.txt"]["green_count"])
            self.assertEqual(0, by_name["a.txt"]["adjusted_score"])
            self.assertEqual("clean", by_name["b.md"]["verdict"])

    def test_scan_directory_missing(self):
        with self.assertRaises(self.R.RedFlagError):
            self.R.scan_directory("/nonexistent/dir")

    def test_summary_for_match_clean(self):
        out = self.R.summary_for_match(
            "Salary: $120k-$150k. Equal opportunity employer. "
            "Responsibilities: build features. "
            "You will join the platform team, "
            "reporting to the engineering manager.")
        self.assertEqual("red flags: 0 — clean (score 0)", out)

    def test_summary_for_match_empty(self):
        self.assertEqual("red flags: 0 — clean (score 0)",
                         self.R.summary_for_match(""))
        self.assertEqual("red flags: 0 — clean (score 0)",
                         self.R.summary_for_match(None))

    def test_summary_for_match_with_red_flag(self):
        from candid.redflags.core import DETECTORS, Flag, register

        def fake_detect(text):
            if "FAKETRIGGER" in text:
                return [Flag("fake.x", "Fake", "high", "fake",
                             "Why. Plain.", [], "Ask.")]
            return []

        register(fake_detect)
        try:
            # Include pay + responsibilities + team info so only the fake
            # detector fires among the real registered detectors.
            out = self.R.summary_for_match(
                "Salary: $120k-$150k. Responsibilities: build features. "
                "You will join the platform team, reporting to the "
                "engineering manager. FAKETRIGGER inside")
        finally:
            DETECTORS.remove(fake_detect)
        self.assertEqual("red flags: 1 (1 high) — clean (score 15)", out)


class RedflagsCliTest(unittest.TestCase):
    def _run(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "candid", *argv],
            cwd=ROOT, capture_output=True, text=True, timeout=120)

    def test_cli_check(self):
        with tempfile.TemporaryDirectory() as td:
            jd = Path(td) / "jd.txt"
            jd.write_text("Salary: $120k-$150k. Equal opportunity employer.")
            r = self._run("redflags", "check", str(jd))
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("Verdict: CLEAN", r.stdout)
            self.assertIn("Salary range listed", r.stdout)

    def test_cli_check_json(self):
        with tempfile.TemporaryDirectory() as td:
            jd = Path(td) / "jd.txt"
            jd.write_text("Salary: $120k-$150k.")
            r = self._run("redflags", "check", str(jd), "--json")
            self.assertEqual(0, r.returncode, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual("clean", payload["verdict"])
            self.assertTrue(any(f["id"] == "green.salary_range"
                                for f in payload["flags"]))

    def test_cli_check_missing_file(self):
        r = self._run("redflags", "check", "/nonexistent/jd.txt")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("Error:", r.stderr)
        self.assertIn("redflags --help", r.stderr)

    def test_cli_scan(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.txt").write_text("Salary: $120k-$150k.")
            (d / "b.txt").write_text("Plain posting.")
            r = self._run("redflags", "scan", str(d))
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("a.txt", r.stdout)
            self.assertIn("b.txt", r.stdout)
            self.assertIn("clean", r.stdout)


if __name__ == "__main__":
    unittest.main()
