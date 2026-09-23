"""End-to-end test for the bullet metric helper (Worker C, batch-81).

Flow: build a profile from the sample resume -> scan for metric
opportunities -> check coverage < 100 -> validate a sane metric ->
simulate the user answering via bank entries with status "supplied" ->
suggest_phrasings returns variants built only from supplied numbers ->
apply_rewrite updates the bullet (pure, original untouched) ->
coverage improves -> metric_debt shrinks -> audit_no_invention is clean,
and flags an invented number -> export_story_metrics returns the
JSON-serializable contract.

The bank round-trips through save_bank/load_bank on disk (CANDID_DATA_DIR
points at a tempdir). If candid.metrics (Worker A) is missing or its API
does not match the contract, the metrics tests skip with an exact
explanation. No stubs are written into candid/ by this test.
"""

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Must be set before candid.config is first imported (it reads this at import).
os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid_metrics_e2e_")

REQUIRED_API = [
    "scan_bullets",
    "metric_coverage",
    "validate_metric",
    "suggest_phrasings",
    "load_bank",
    "save_bank",
    "record_answer",
    "apply_rewrite",
    "metric_debt",
    "audit_no_invention",
    "export_story_metrics",
    "bank_key",
    "OPP_TYPES",
]

SAMPLE_RESUME = os.path.join(REPO_ROOT, "samples", "candid", "sample_resume.md")


def load_metrics(testcase):
    """Import candid.metrics and check the full contract API.

    Returns the module, or skips the test with the exact missing pieces.
    """
    try:
        import candid.metrics as metrics
    except ImportError as exc:
        testcase.skipTest(
            "candid.metrics is not importable yet (Worker A module not "
            f"landed): {exc}"
        )
    missing = [name for name in REQUIRED_API if not hasattr(metrics, name)]
    if missing:
        testcase.skipTest(
            "candid.metrics exists but is missing contract API "
            f"(Worker A in progress): {', '.join(missing)}"
        )
    return metrics


class ProfileFixtureTest(unittest.TestCase):
    """The profile half of the fixture; independent of Worker A's module."""

    def test_sample_resume_yields_experience_bullets(self):
        from candid.profile import build_profile

        with open(SAMPLE_RESUME, encoding="utf-8") as fh:
            text = fh.read()
        profile = build_profile([text], source_files=[SAMPLE_RESUME])
        bullets = [
            b
            for job in profile.get("experience", [])
            for b in job.get("bullets", [])
        ]
        self.assertGreaterEqual(
            len(bullets), 4, "sample resume should yield several bullets"
        )


class MetricsFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_metrics(cls)
        from candid.profile import build_profile

        with open(SAMPLE_RESUME, encoding="utf-8") as fh:
            text = fh.read()
        cls.profile = build_profile([text], source_files=[SAMPLE_RESUME])
        bullets = [
            b
            for job in cls.profile.get("experience", [])
            for b in job.get("bullets", [])
        ]
        assert bullets, "sample resume fixture must yield bullets"

    # -- the flow ---------------------------------------------------------

    def test_scan_finds_opportunities(self):
        opps = self.m.scan_bullets(self.profile)
        self.assertGreater(len(opps), 0, "scan should find opportunities")
        declared = set(self.m.OPP_TYPES)
        self.assertTrue(declared, "OPP_TYPES should be non-empty")
        for opp in opps:
            self.assertIn(
                opp["opp_type"],
                declared,
                f"opportunity type {opp['opp_type']!r} not in OPP_TYPES",
            )
            self.assertIn("questions", opp)
            self.assertTrue(opp["questions"], "each opp should ask follow-ups")
        self.__class__.opps = opps

    def test_coverage_starts_below_100(self):
        cov = self.m.metric_coverage(self.profile)
        for key in ("total", "with_metrics", "pct", "per_role"):
            self.assertIn(key, cov)
        self.assertLess(cov["pct"], 100.0, "coverage should start below 100%")

    def test_validate_metric(self):
        # Sane metric: no warnings.
        self.assertEqual(
            self.m.validate_metric("team", 2, "people"),
            [],
            "a sane metric should validate clean",
        )
        # Absurd percent: warnings, not silence.
        warnings = self.m.validate_metric("performance", 99999, "%")
        self.assertGreater(len(warnings), 0, "absurd percent must warn")
        # Negative latency: warnings.
        self.assertGreater(
            len(self.m.validate_metric("time", -5, "hours")), 0
        )

    def test_full_metric_flow(self):
        m = self.m
        profile = self.profile

        # 1. Scan finds an opportunity.
        opps = m.scan_bullets(profile)
        self.assertGreater(len(opps), 0)
        opp = opps[0]
        role_idx, bullet_idx = opp["role_idx"], opp["bullet_idx"]
        bullet = opp["bullet"]
        opp_type = opp["opp_type"]

        cov_before = m.metric_coverage(profile)["pct"]
        self.assertLess(cov_before, 100.0)

        # 2. Debt lists the opportunity while the bank is empty.
        self.assertGreater(
            len(m.metric_debt(profile, {})), 0, "fresh debt should be open"
        )

        # 3. Simulate the user answering: supplied numbers go in the bank.
        # Answers use the template keys for this opp type, and units that
        # candid's metric detector recognizes so the rewrite registers.
        if opp_type in ("cost", "revenue", "team", "adoption"):
            answers = {"value": "2", "unit": "people"}
            supplied_digits = {"2"}
        else:  # performance/scale/time/quality use before/after/unit
            answers = {"before": "10", "after": "2", "unit": "hours"}
            supplied_digits = {"10", "2"}

        bank = {}
        m.record_answer(
            bank, role_idx, bullet_idx, bullet, answers, status="supplied"
        )
        key = m.bank_key(role_idx, bullet_idx)
        self.assertEqual(key, f"{role_idx}:{bullet_idx}")
        self.assertEqual(bank[key]["status"], "supplied")

        # 4. Bank round-trips through disk.
        m.save_bank(bank)
        loaded = m.load_bank()
        self.assertEqual(loaded, bank, "bank should round-trip via disk")

        # 5. Suggested phrasings use only supplied numbers...
        suggestions = m.suggest_phrasings(bullet, opp_type, answers)
        self.assertGreater(
            len(suggestions), 0, "suggest_phrasings should offer variants"
        )
        for variant in suggestions:
            for digit_run in __import__("re").findall(r"\d[\d.,]*", variant):
                self.assertIn(
                    digit_run,
                    supplied_digits,
                    f"variant {variant!r} uses a number the user never "
                    "supplied",
                )
        # ...and nothing is suggested when a required number is missing
        # (the never-invent guarantee, at the unit level).
        self.assertEqual(
            m.suggest_phrasings(bullet, opp_type, {}),
            [],
            "missing answers must yield no phrasings, not a guess",
        )

        # 6. Apply the chosen rewrite. Pure: the original profile is untouched.
        chosen = suggestions[0]
        original_text = profile["experience"][role_idx]["bullets"][bullet_idx]
        new_profile = m.apply_rewrite(profile, role_idx, bullet_idx, chosen)
        self.assertEqual(
            profile["experience"][role_idx]["bullets"][bullet_idx],
            original_text,
            "apply_rewrite must not mutate the input profile",
        )
        self.assertEqual(
            new_profile["experience"][role_idx]["bullets"][bullet_idx], chosen
        )

        # 7. Coverage improves after the rewrite is adopted.
        cov_after = m.metric_coverage(new_profile)["pct"]
        self.assertGreater(
            cov_after,
            cov_before,
            f"coverage should improve ({cov_before:.1f} -> {cov_after:.1f})",
        )

        # 8. Debt shrinks once the bullet is supplied...
        self.assertEqual(
            m.metric_debt(new_profile, bank), [],
            "supplied bullets should leave the debt list",
        )
        # ...and declined bullets leave it too (never auto-filled).
        declined_bank = {}
        m.record_answer(
            declined_bank, role_idx, bullet_idx, bullet, {}, status="declined"
        )
        self.assertEqual(m.metric_debt(profile, declined_bank), [])

        # 9. Audit: clean when every metric-bearing bullet is backed...
        full_bank = dict(bank)
        for r_idx, exp in enumerate(new_profile.get("experience", [])):
            for b_idx, b in enumerate(exp.get("bullets", [])):
                if m._has_metric(b) and m.bank_key(r_idx, b_idx) not in full_bank:
                    m.record_answer(
                        full_bank, r_idx, b_idx, b, {}, status="supplied"
                    )
        result = m.audit_no_invention(new_profile, full_bank)
        self.assertTrue(
            result["ok"], f"audit should be clean: {result['violations']}"
        )
        self.assertEqual(result["violations"], [])

        # 10. ...and flags a number the user never supplied.
        tampered = m.apply_rewrite(
            new_profile, 1, 1, "Grew revenue 9000% overnight"
        )
        bad = m.audit_no_invention(tampered, full_bank)
        self.assertFalse(bad["ok"])
        self.assertGreater(len(bad["violations"]), 0)

        # 11. Export: the JSON contract for downstream tools (e.g. stories).
        exported = m.export_story_metrics(full_bank)
        json.dumps(exported)  # must be JSON-serializable
        self.assertGreater(len(exported), 0)
        ours = [e for e in exported if e["bullet"] == bullet]
        self.assertEqual(len(ours), 1)
        self.assertIn("2", ours[0]["metric_summary"])
        # Declined entries are excluded from the export.
        declined_only = {}
        m.record_answer(
            declined_only, role_idx, bullet_idx, bullet, {}, status="declined"
        )
        self.assertEqual(m.export_story_metrics(declined_only), [])


if __name__ == "__main__":
    unittest.main()
