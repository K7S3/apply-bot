"""Tests for the `metrics` CLI subcommand (batch-81: bullet metric helper).

The CLI talks to candid.metrics only through its public contract:
scan_bullets, metric_coverage, validate_metric, suggest_phrasings,
load_bank, save_bank, record_answer, bank_key, apply_rewrite,
metric_debt, audit_no_invention.

CANDID_DATA_DIR is set to a temp dir before importing candid.config, and
the metrics bank path (candid.config.METRICS_BANK_PATH) is reset per test.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Redirect user data into a temp dir BEFORE importing candid.config.
TMP_DATA = tempfile.mkdtemp(prefix="candid-metrics-cli-")
os.environ["CANDID_DATA_DIR"] = TMP_DATA

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import metrics as METRICS  # noqa: E402
from candid.profile import OnboardError  # noqa: E402

REQUIRED_METRICS_API = [
    "scan_bullets", "metric_coverage", "validate_metric",
    "suggest_phrasings", "load_bank", "save_bank", "record_answer",
    "bank_key", "apply_rewrite", "metric_debt", "audit_no_invention",
]
for _name in REQUIRED_METRICS_API:
    assert callable(getattr(METRICS, _name, None)), f"candid.metrics.{_name} missing"

# None of these seed bullets carry a digit+unit metric per the module's
# detector, so scan flags all three.
PROFILE = {
    "name": "Test User",
    "headline": "ML Engineer",
    "experience": [
        {"title": "ML Engineer", "company": "Acme",
         "dates": "2023 - Present",
         "bullets": [
             "Built churn prediction models for the marketing team.",
             "Cut inference latency substantially for the ranking service.",
         ]},
        {"title": "Data Analyst", "company": "Beta",
         "dates": "2021 - 2023",
         "bullets": ["Automated weekly reporting dashboards."]},
    ],
}

BULLET_00 = "Built churn prediction models for the marketing team."


def _ns(**kwargs):
    base = {"action": None, "json": False, "keys": [],
            "bank_action": None, "key": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


class MetricsCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-metrics-"))
        self._saved_profile = C.PROFILE_PATH
        C.PROFILE_PATH = self.tmp / "profile.json"
        self.bank_path = C.METRICS_BANK_PATH
        if self.bank_path.exists():
            self.bank_path.unlink()
        self._seed_profile()

    def tearDown(self):
        C.PROFILE_PATH = self._saved_profile
        if self.bank_path.exists():
            self.bank_path.unlink()

    def _seed_profile(self, profile=None):
        C.PROFILE_PATH.write_text(
            json.dumps(profile if profile is not None else PROFILE,
                       indent=2), encoding="utf-8")

    def _run(self, namespace):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.cmd_metrics(namespace)
        return buf.getvalue()

    def _bank(self):
        return METRICS.load_bank()

    def _seed_bank_entry(self, role_idx=0, bullet_idx=0, bullet=BULLET_00,
                         answers=None, chosen=None, status="supplied"):
        bank = self._bank()
        METRICS.record_answer(bank, role_idx, bullet_idx, bullet,
                              answers if answers is not None
                              else {"value": 25, "unit": "engineers"},
                              status=status)
        entry = bank[METRICS.bank_key(role_idx, bullet_idx)]
        entry.update({
            "role": "ML Engineer", "company": "Acme", "opp_type": "team",
            "phrasings": METRICS.suggest_phrasings(
                bullet, "team", entry["answers"]),
            "chosen": chosen,
        })
        METRICS.save_bank(bank)
        return bank


class TestScanCoverageDebtAudit(MetricsCLIBase):
    def test_scan_human_lists_opportunities(self):
        out = self._run(_ns(action="scan"))
        self.assertIn("Built churn prediction models", out)
        self.assertIn("Automated weekly reporting dashboards", out)
        self.assertIn("?", out)  # questions are shown

    def test_scan_json_shape(self):
        out = self._run(_ns(action="scan", json=True))
        data = json.loads(out)
        self.assertEqual(len(data), 3)
        for item in data:
            for field in ("role_idx", "bullet_idx", "role", "company",
                          "bullet", "cues", "opp_type", "questions"):
                self.assertIn(field, item)

    def test_scan_no_profile_errors_clearly(self):
        C.PROFILE_PATH = self.tmp / "missing.json"
        with self.assertRaises(OnboardError):
            self._run(_ns(action="scan"))

    def test_coverage_json(self):
        out = self._run(_ns(action="coverage", json=True))
        cov = json.loads(out)
        self.assertEqual(cov["total"], 3)
        self.assertEqual(cov["with_metrics"], 0)
        self.assertEqual(len(cov["per_role"]), 2)
        self.assertIn("pct", cov)

    def test_coverage_human(self):
        out = self._run(_ns(action="coverage"))
        self.assertIn("0/3", out)
        self.assertIn("ML Engineer", out)

    def test_debt_json_lists_unresolved(self):
        out = self._run(_ns(action="debt", json=True))
        debt = json.loads(out)
        self.assertEqual(len(debt), 3)

    def test_debt_human_empty_after_decline(self):
        bank = self._bank()
        for item in METRICS.scan_bullets(PROFILE):
            METRICS.record_answer(bank, item["role_idx"], item["bullet_idx"],
                                  item["bullet"], {}, status="declined")
        METRICS.save_bank(bank)
        out = self._run(_ns(action="debt"))
        self.assertIn("No metric debt", out)

    def test_audit_clean(self):
        out = self._run(_ns(action="audit"))
        self.assertIn("clean", out.lower())

    def test_audit_violation_exits_nonzero(self):
        prof = dict(PROFILE)
        prof["experience"] = [dict(PROFILE["experience"][0])]
        prof["experience"][0] = dict(prof["experience"][0])
        prof["experience"][0]["bullets"] = ["Saved $50K in annual spend."]
        self._seed_profile(prof)
        with self.assertRaises(SystemExit) as ctx:
            out = self._run(_ns(action="audit"))
        self.assertNotEqual(ctx.exception.code, 0)

    def test_audit_violation_prints_offending_bullet(self):
        prof = dict(PROFILE)
        prof["experience"] = [dict(PROFILE["experience"][0])]
        prof["experience"][0] = dict(prof["experience"][0])
        prof["experience"][0]["bullets"] = ["Saved $50K in annual spend."]
        self._seed_profile(prof)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                CLI.cmd_metrics(_ns(action="audit"))
        self.assertIn("Saved $50K", buf.getvalue())

    def test_audit_passes_with_supplied_bank_entry(self):
        prof = dict(PROFILE)
        prof["experience"] = [dict(PROFILE["experience"][0])]
        prof["experience"][0] = dict(prof["experience"][0])
        prof["experience"][0]["bullets"] = ["Saved $50K in annual spend."]
        self._seed_profile(prof)
        bank = self._bank()
        METRICS.record_answer(bank, 0, 0, "Saved $50K in annual spend.",
                              {"value": 50, "unit": "$K"}, status="supplied")
        METRICS.save_bank(bank)
        out = self._run(_ns(action="audit"))
        self.assertIn("clean", out.lower())


class TestPrompt(MetricsCLIBase):
    def test_prompt_answer_skip_decline(self):
        # (0,0) is team-type: needs value + unit. "25 percent" fills both.
        # (0,1) and (1,0) are performance-type: skipped / declined.
        with mock.patch("builtins.input",
                         side_effect=["25 percent", "s", "d"]):
            out = self._run(_ns(action="prompt"))
        bank = self._bank()
        entry = bank["0:0"]
        self.assertEqual(entry["status"], "supplied")
        self.assertEqual(entry["answers"], {"value": 25.0, "unit": "percent"})
        self.assertTrue(entry["phrasings"])
        self.assertIsNone(entry["chosen"])
        self.assertEqual(bank["0:1"]["status"], "skipped")
        self.assertEqual(bank["1:0"]["status"], "declined")
        self.assertEqual(bank["1:0"]["phrasings"], [])
        self.assertIn("Bank updated", out)
        # supplied + declined leave debt; skipped stays
        debt = METRICS.metric_debt(PROFILE, bank)
        self.assertEqual(len(debt), 1)
        self.assertEqual((debt[0]["role_idx"], debt[0]["bullet_idx"]), (0, 1))

    def test_prompt_validation_warning_asks_confirm(self):
        # 20000 percent trips the absurd-percent warning; "n" rejects it.
        with mock.patch("builtins.input", side_effect=[
                "20000 percent", "n", "50 users", "y", "s", "d"]):
            out = self._run(_ns(action="prompt"))
        self.assertIn("Heads up", out)
        entry = self._bank()["0:0"]
        self.assertEqual(entry["answers"], {"value": 50.0, "unit": "users"})

    def test_prompt_bad_number_reprompts(self):
        with mock.patch("builtins.input",
                         side_effect=["lots", "10 reports", "s", "d"]):
            out = self._run(_ns(action="prompt"))
        self.assertIn("Could not read a number", out)
        entry = self._bank()["0:0"]
        self.assertEqual(entry["answers"], {"value": 10.0, "unit": "reports"})

    def test_prompt_blank_answers_stay_in_debt(self):
        with mock.patch("builtins.input", side_effect=["", "", "s", "d"]):
            self._run(_ns(action="prompt"))
        bank = self._bank()
        self.assertEqual(bank["0:0"]["status"], "skipped")
        debt = METRICS.metric_debt(PROFILE, bank)
        self.assertEqual(len(debt), 2)  # skipped bullets stay in debt


class TestPreviewApplyBank(MetricsCLIBase):
    def test_preview_accept_stores_chosen(self):
        self._seed_bank_entry()
        with mock.patch("builtins.input", side_effect=["y"]):
            out = self._run(_ns(action="preview"))
        self.assertIn("---", out)  # unified diff markers present
        entry = self._bank()["0:0"]
        self.assertEqual(entry["chosen"], 0)
        self.assertEqual(entry["status"], "accepted")

    def test_preview_decline_leaves_chosen_unset(self):
        self._seed_bank_entry()
        with mock.patch("builtins.input", side_effect=["n"]):
            self._run(_ns(action="preview"))
        entry = self._bank()["0:0"]
        self.assertIsNone(entry["chosen"])

    def test_preview_explicit_keys(self):
        self._seed_bank_entry()
        with mock.patch("builtins.input", side_effect=["y"]):
            self._run(_ns(action="preview", keys=["0:0"]))
        self.assertEqual(self._bank()["0:0"]["chosen"], 0)

    def test_preview_nothing_to_preview(self):
        out = self._run(_ns(action="preview"))
        self.assertIn("Nothing to preview", out)

    def test_apply_writes_profile_and_backup(self):
        old_text = C.PROFILE_PATH.read_text(encoding="utf-8")
        self._seed_bank_entry(chosen=0)
        out = self._run(_ns(action="apply"))
        backups = list(self.tmp.glob("profile.json.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), old_text)
        new_profile = json.loads(C.PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(new_profile["experience"][0]["bullets"][0],
                         "Led a team of 25 engineers")
        # untouched bullets survive
        self.assertEqual(new_profile["experience"][0]["bullets"][1],
                         "Cut inference latency substantially for the ranking service.")
        self.assertEqual(self._bank()["0:0"]["status"], "applied")
        self.assertIn("Backup", out)

    def test_apply_nothing_accepted(self):
        self._seed_bank_entry(chosen=None)
        out = self._run(_ns(action="apply"))
        self.assertIn("Nothing to apply", out)
        self.assertEqual(list(self.tmp.glob("profile.json.bak.*")), [])

    def test_bank_list_and_remove(self):
        self._seed_bank_entry()
        out = self._run(_ns(action="bank", bank_action="list"))
        self.assertIn("0:0", out)
        self.assertIn("ML Engineer", out)
        self.assertIn("value: 25", out)
        out = self._run(_ns(action="bank", bank_action="list", json=True))
        self.assertIn("0:0", json.loads(out))
        out = self._run(_ns(action="bank", bank_action="remove", key="0:0"))
        self.assertIn("Removed", out)
        self.assertEqual(self._bank(), {})

    def test_bank_remove_unknown_key(self):
        with self.assertRaises(SystemExit):
            self._run(_ns(action="bank", bank_action="remove", key="9:9"))


class TestParserWiring(unittest.TestCase):
    def test_metrics_registered_in_parser(self):
        parser = CLI.build_parser()
        args = parser.parse_args(["metrics", "scan", "--json"])
        self.assertEqual(args.cmd, "metrics")
        self.assertEqual(args.action, "scan")
        self.assertTrue(args.json)
        self.assertIs(args.func, CLI.cmd_metrics)
        args = parser.parse_args(["metrics", "bank", "remove", "0:1"])
        self.assertEqual(args.bank_action, "remove")
        self.assertEqual(args.key, "0:1")
        args = parser.parse_args(["metrics", "preview", "0:0"])
        self.assertEqual(args.keys, ["0:0"])

    def test_metrics_in_command_inventory(self):
        self.assertIn("metrics", CLI.COMMANDS)
        self.assertIn("scan", CLI.SUBCOMMANDS["metrics"])


if __name__ == "__main__":
    unittest.main()
