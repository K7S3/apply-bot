"""Tests for candid.metrics (bullet metric helper). Run: python -m pytest tests/test_metrics.py -q"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# CANDID_DATA_DIR must be set BEFORE candid.config is imported, since paths
# are computed at import time.
TMPDIR = tempfile.mkdtemp(prefix="candid_metrics_test_")
os.environ["CANDID_DATA_DIR"] = TMPDIR

from candid import config as C  # noqa: E402
from candid import metrics as M  # noqa: E402


def make_profile():
    return {
        "experience": [
            {
                "title": "Backend Engineer",
                "company": "Acme",
                "dates": "2023-2025",
                "bullets": [
                    "Improved API performance significantly across several services",
                    "Reduced p99 latency by 50% after the rewrite",
                    "Wrote API documentation",
                    "Cut cloud costs by $2M annually",
                ],
            },
            {
                "title": "Team Lead",
                "company": "Beta",
                "dates": "2021-2023",
                "bullets": [
                    "Mentored a team of engineers and streamlined onboarding",
                    "Grew request throughput to 10x previous capacity",
                ],
            },
        ]
    }


class OppTypesTest(unittest.TestCase):
    def test_all_eight_types_present(self):
        for t in ["performance", "scale", "cost", "time", "revenue", "quality", "team", "adoption"]:
            self.assertIn(t, M.OPP_TYPES)

    def test_each_type_has_label_questions_units(self):
        for name, spec in M.OPP_TYPES.items():
            self.assertIsInstance(spec["label"], str, name)
            self.assertGreaterEqual(len(spec["questions"]), 1, name)
            self.assertGreaterEqual(len(spec["units"]), 1, name)


class ScanTest(unittest.TestCase):
    def test_finds_vague_bullet(self):
        results = M.scan_bullets(make_profile())
        bullets = [r["bullet"] for r in results]
        self.assertIn("Improved API performance significantly across several services", bullets)

    def test_result_shape(self):
        r = M.scan_bullets(make_profile())[0]
        for key in ["role_idx", "bullet_idx", "role", "company", "bullet", "cues", "opp_type", "questions"]:
            self.assertIn(key, r)
        self.assertEqual(r["role"], "Backend Engineer")
        self.assertEqual(r["company"], "Acme")
        self.assertGreater(len(r["cues"]), 0)

    def test_skips_bullets_with_metrics(self):
        results = M.scan_bullets(make_profile())
        bullets = [r["bullet"] for r in results]
        self.assertNotIn("Reduced p99 latency by 50% after the rewrite", bullets)
        self.assertNotIn("Cut cloud costs by $2M annually", bullets)
        self.assertNotIn("Grew request throughput to 10x previous capacity", bullets)

    def test_skips_bullets_with_spelled_out_percent(self):
        prof = {"experience": [{
            "title": "Engineer", "company": "Acme", "dates": "2024",
            "bullets": ["Cut error rate by 40 percent after the migration"],
        }]}
        results = M.scan_bullets(prof)
        self.assertEqual(results, [])

    def test_skips_bullets_without_cues(self):
        results = M.scan_bullets(make_profile())
        bullets = [r["bullet"] for r in results]
        self.assertNotIn("Wrote API documentation", bullets)

    def test_cues_detected(self):
        results = M.scan_bullets(make_profile())
        r = [x for x in results if "significantly" in x["bullet"]][0]
        self.assertIn("significantly", r["cues"])
        self.assertIn("improved", r["cues"])


class ClassifierTest(unittest.TestCase):
    def _opp(self, bullet):
        prof = {"experience": [{"title": "X", "company": "Y", "dates": "", "bullets": [bullet]}]}
        res = M.scan_bullets(prof)
        self.assertEqual(len(res), 1, bullet)
        return res[0]["opp_type"]

    def test_cost(self):
        self.assertEqual(self._opp("Reduced cloud spend and saved budget"), "cost")

    def test_team(self):
        self.assertEqual(self._opp("Mentored a team of engineers"), "team")

    def test_revenue(self):
        self.assertEqual(self._opp("Increased revenue through upsell deals"), "revenue")

    def test_time(self):
        self.assertEqual(self._opp("Automated the manual deployment process to save hours"), "time")

    def test_quality(self):
        self.assertEqual(self._opp("Reduced production errors and improved uptime"), "quality")

    def test_adoption(self):
        self.assertEqual(self._opp("Launched the feature and drove customer adoption"), "adoption")

    def test_scale(self):
        self.assertEqual(self._opp("Scaled the system to handle growing traffic"), "scale")


class CoverageTest(unittest.TestCase):
    def test_coverage_counts(self):
        cov = M.metric_coverage(make_profile())
        self.assertEqual(cov["total"], 6)
        self.assertEqual(cov["with_metrics"], 3)
        self.assertAlmostEqual(cov["pct"], 50.0)

    def test_coverage_per_role(self):
        cov = M.metric_coverage(make_profile())
        self.assertEqual(len(cov["per_role"]), 2)
        self.assertEqual(cov["per_role"][0]["role"], "Backend Engineer")
        self.assertEqual(cov["per_role"][0]["total"], 4)
        self.assertEqual(cov["per_role"][0]["with_metrics"], 2)
        self.assertEqual(cov["per_role"][1]["with_metrics"], 1)


class ValidateTest(unittest.TestCase):
    def test_absurd_percent_flagged(self):
        self.assertGreater(len(M.validate_metric("performance", 50000, "%")), 0)

    def test_negative_latency_flagged(self):
        self.assertGreater(len(M.validate_metric("performance", -5, "ms")), 0)

    def test_negative_time_flagged(self):
        self.assertGreater(len(M.validate_metric("time", -2, "hours")), 0)

    def test_zero_ratio_flagged(self):
        self.assertGreater(len(M.validate_metric("scale", 0, "x")), 0)

    def test_sane_values_pass(self):
        self.assertEqual(M.validate_metric("cost", 20, "%"), [])
        self.assertEqual(M.validate_metric("performance", 400, "ms"), [])
        self.assertEqual(M.validate_metric("scale", 10, "x"), [])


class PhrasingTest(unittest.TestCase):
    def test_performance_uses_only_supplied_numbers(self):
        answers = {"before": 2000, "after": 400, "unit": "ms", "pct": 80}
        variants = M.suggest_phrasings("Improved latency", "performance", answers)
        self.assertEqual(len(variants), 3)
        for v in variants:
            self.assertIn("2000", v)
            self.assertIn("400", v)
            self.assertIn("80", v)
            self.assertIn("ms", v)

    def test_missing_required_number_returns_empty(self):
        answers = {"before": 2000, "after": 400, "unit": "ms"}  # pct missing
        self.assertEqual(M.suggest_phrasings("Improved latency", "performance", answers), [])

    def test_cost_phrasing(self):
        variants = M.suggest_phrasings("Cut costs", "cost", {"value": 2, "unit": "M"})
        self.assertEqual(len(variants), 3)
        self.assertIn("2M", variants[0])

    def test_extra_answers_ignored(self):
        variants = M.suggest_phrasings(
            "Cut costs", "cost", {"value": 2, "unit": "M", "unrelated": "zzz"})
        self.assertEqual(len(variants), 3)
        for v in variants:
            self.assertNotIn("zzz", v)


class BankTest(unittest.TestCase):
    def _isolated_bank(self):
        """Point METRICS_BANK_PATH at a temp file, independent of import order.

        candid.config computes DATA_DIR at import time, so relying on the
        CANDID_DATA_DIR env var is fragile when another test module imports
        the config first. Patching the attribute is hermetic and reverted.
        """
        td = tempfile.TemporaryDirectory(prefix="candid_bank_")
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "metrics_bank.json"
        patcher = unittest.mock.patch.object(C, "METRICS_BANK_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def test_roundtrip(self):
        self._isolated_bank()
        bank = {}
        M.record_answer(bank, 0, 1, "Improved latency", {"pct": 80}, "supplied")
        M.save_bank(bank)
        loaded = M.load_bank()
        self.assertEqual(loaded["0:1"]["answers"]["pct"], 80)
        self.assertEqual(loaded["0:1"]["status"], "supplied")
        self.assertIn("updated", loaded["0:1"])

    def test_load_missing_returns_empty(self):
        self._isolated_bank()
        self.assertEqual(M.load_bank(), {})

    def test_load_corrupt_returns_empty(self):
        path = self._isolated_bank()
        path.write_text("{not valid json")
        self.assertEqual(M.load_bank(), {})

    def test_bank_path_under_data_dir(self):
        # Order-independent: the bank file is named metrics_bank.json and
        # lives directly under the configured DATA_DIR, whatever it is.
        self.assertEqual(C.METRICS_BANK_PATH.name, "metrics_bank.json")
        self.assertEqual(C.METRICS_BANK_PATH.parent, C.DATA_DIR)


class RewriteTest(unittest.TestCase):
    def test_apply_rewrite_is_pure(self):
        prof = make_profile()
        before = json.dumps(prof, sort_keys=True)
        new = M.apply_rewrite(prof, 0, 0, "Cut p99 latency from 2000ms to 400ms (80% reduction)")
        self.assertEqual(json.dumps(prof, sort_keys=True), before)
        self.assertEqual(new["experience"][0]["bullets"][0],
                         "Cut p99 latency from 2000ms to 400ms (80% reduction)")
        self.assertIsNot(prof, new)


class DebtTest(unittest.TestCase):
    def test_debt_includes_unanswered(self):
        debt = M.metric_debt(make_profile(), {})
        self.assertGreater(len(debt), 0)

    def test_debt_excludes_supplied_and_declined(self):
        prof = make_profile()
        bank = {}
        M.record_answer(bank, 0, 0, prof["experience"][0]["bullets"][0], {"pct": 30}, "supplied")
        M.record_answer(bank, 1, 0, prof["experience"][1]["bullets"][0], {}, "declined")
        debt = M.metric_debt(prof, bank)
        keys = {(d["role_idx"], d["bullet_idx"]) for d in debt}
        self.assertNotIn((0, 0), keys)
        self.assertNotIn((1, 0), keys)

    def test_debt_keeps_skipped(self):
        prof = make_profile()
        bank = {}
        M.record_answer(bank, 0, 0, prof["experience"][0]["bullets"][0], {}, "skipped")
        debt = M.metric_debt(prof, bank)
        keys = {(d["role_idx"], d["bullet_idx"]) for d in debt}
        self.assertIn((0, 0), keys)


class AuditTest(unittest.TestCase):
    def test_audit_ok_when_backed(self):
        prof = make_profile()
        bank = {}
        M.record_answer(bank, 0, 1, prof["experience"][0]["bullets"][1], {"pct": 50}, "supplied")
        M.record_answer(bank, 0, 3, prof["experience"][0]["bullets"][3], {"value": 2, "unit": "M"}, "supplied")
        M.record_answer(bank, 1, 1, prof["experience"][1]["bullets"][1], {"value": 10, "unit": "x"}, "supplied")
        result = M.audit_no_invention(prof, bank)
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])

    def test_audit_flags_unbacked_metrics(self):
        result = M.audit_no_invention(make_profile(), {})
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["violations"]), 3)
        self.assertTrue(any("50%" in v for v in result["violations"]))

    def test_audit_ignores_nonmetric_bullets(self):
        prof = {"experience": [{"title": "X", "company": "Y", "dates": "",
                                "bullets": ["Improved things a lot"]}]}
        result = M.audit_no_invention(prof, {})
        self.assertTrue(result["ok"])

    def test_audit_accepts_accepted_and_applied(self):
        # The CLI moves entries supplied -> accepted -> applied; all are
        # user-backed, so the never-invent guarantee still holds.
        prof = {"experience": [{"title": "X", "company": "Y", "dates": "",
                                "bullets": ["Cut costs by $2M annually"]}]}
        for status in ("supplied", "accepted", "applied"):
            bank = {}
            M.record_answer(bank, 0, 0, prof["experience"][0]["bullets"][0],
                            {"value": 2, "unit": "M"}, status)
            result = M.audit_no_invention(prof, bank)
            self.assertTrue(result["ok"], f"status {status} should be backed")


class ExportTest(unittest.TestCase):
    def test_export_only_supplied(self):
        bank = {}
        M.record_answer(bank, 0, 0, "Improved latency", {"pct": 80, "unit": "ms"}, "supplied")
        M.record_answer(bank, 0, 1, "Cut costs", {"value": 2}, "declined")
        out = M.export_story_metrics(bank)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bullet"], "Improved latency")
        self.assertIn("80", out[0]["metric_summary"])
        self.assertEqual(out[0]["answers"], {"pct": 80, "unit": "ms"})
        json.dumps(out)  # serializable


if __name__ == "__main__":
    unittest.main()
