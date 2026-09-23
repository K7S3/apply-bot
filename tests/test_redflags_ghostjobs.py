"""Tests for candid.redflags.ghostjobs (posting-integrity detectors + reposts)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import ghostjobs  # noqa: E402


def _ids(flags):
    return [f.flag_id for f in flags]


class EvergreenTest(unittest.TestCase):
    def test_flags_talent_pool(self):
        text = (
            "Software Engineer\n\nWe are always looking for great engineers. "
            "Join our talent pool today and we will reach out when roles open."
        )
        flags = ghostjobs.detect_evergreen(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "ghost.evergreen")
        self.assertEqual(f.severity, "high")
        self.assertEqual(f.category, "posting-integrity")

    def test_flags_bench_language(self):
        text = "Consultant wanted. We keep strong candidates on our bench for pipeline roles."
        flags = ghostjobs.detect_evergreen(text)
        self.assertEqual(_ids(flags), ["ghost.evergreen"])

    def test_no_flag_for_active_requisition(self):
        text = (
            "Backend Engineer (Req #4821)\n\nWe have an immediate opening on "
            "the payments team starting next quarter."
        )
        self.assertEqual(ghostjobs.detect_evergreen(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(ghostjobs.detect_evergreen(""), [])
        self.assertEqual(ghostjobs.detect_evergreen(None), [])


class MlmTest(unittest.TestCase):
    def test_flags_mlm_language(self):
        text = (
            "Be your own boss! Unlimited earning potential and true financial "
            "freedom. Build your downline and earn residual income."
        )
        flags = ghostjobs.detect_mlm(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "ghost.mlm")
        self.assertEqual(f.severity, "critical")
        self.assertIn("do not pay", f.suggestion.lower())

    def test_flags_upfront_fee(self):
        text = "Sales opportunity. A $199 starter kit and registration fee apply."
        self.assertEqual(_ids(ghostjobs.detect_mlm(text)), ["ghost.mlm"])

    def test_no_flag_for_salaried_role(self):
        text = (
            "Account Executive\n\nBase salary $90k plus commission. "
            "Responsibilities: manage a book of business."
        )
        self.assertEqual(ghostjobs.detect_mlm(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(ghostjobs.detect_mlm(""), [])
        self.assertEqual(ghostjobs.detect_mlm(None), [])


class TooGoodTest(unittest.TestCase):
    def test_flags_no_experience_high_pay(self):
        text = (
            "No experience necessary! Earn $5,000 per week from home. "
            "Start today!"
        )
        flags = ghostjobs.detect_too_good(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "ghost.too_good")
        self.assertEqual(f.severity, "high")

    def test_flags_wfh_no_interview(self):
        text = (
            "Work from home data entry role. No interview required, start "
            "immediately after signup."
        )
        self.assertEqual(_ids(ghostjobs.detect_too_good(text)), ["ghost.too_good"])

    def test_no_flag_for_reasonable_pay(self):
        text = (
            "No experience necessary. Earn $18 per hour as a warehouse "
            "associate. Interview required."
        )
        self.assertEqual(ghostjobs.detect_too_good(text), [])

    def test_no_flag_for_normal_posting(self):
        text = "Senior Engineer. $160k-$200k base. Onsite interview process."
        self.assertEqual(ghostjobs.detect_too_good(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(ghostjobs.detect_too_good(""), [])
        self.assertEqual(ghostjobs.detect_too_good(None), [])


class GhostAnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_surfaces_ghost_flags(self):
        from candid.redflags.core import analyze

        text = (
            "Be your own boss! Join our talent pool. We are always looking for "
            "go-getters. Unlimited earning potential!"
        )
        result = analyze(text)
        ids = _ids(result["flags"])
        self.assertIn("ghost.mlm", ids)
        self.assertIn("ghost.evergreen", ids)

    def test_analyze_clean_for_good_posting(self):
        from candid.redflags.core import analyze

        text = (
            "Backend Engineer\n\nResponsibilities:\n- Build and ship APIs\n"
            "- Review code; debug prod\n\nYou will join our engineering team.\n\n"
            "Requirements: 3+ years Python."
        )
        result = analyze(text)
        ghost_ids = [i for i in _ids(result["flags"]) if i.startswith("ghost.")]
        self.assertEqual(ghost_ids, [])

    def test_mlm_drives_risky_verdict(self):
        from candid.redflags.core import analyze

        text = "Be your own boss! Unlimited earning potential, residual income, downline bonuses."
        result = analyze(text)
        self.assertIn(result["verdict"], ("caution", "risky"))


def _posting(company, title, text, date_posted):
    return {"company": company, "title": title, "text": text, "date_posted": date_posted}


class FindRepostsTest(unittest.TestCase):
    def test_groups_same_company_title_within_90_days(self):
        p1 = _posting("Acme Corp", "Data Scientist",
                      "We need a data scientist for the analytics team in NYC.",
                      "2026-06-01")
        p2 = _posting("ACME Corp.", "Data Scientist!",
                      "Completely different description about marketing work here.",
                      "2026-07-15")
        groups = ghostjobs.find_reposts([p1, p2])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_no_group_when_outside_90_day_window(self):
        p1 = _posting("Acme Corp", "Data Scientist",
                      "Analytics team role in NYC with Python and SQL required.",
                      "2026-01-01")
        p2 = _posting("Acme Corp", "Data Scientist",
                      "Totally different words about finance and reporting duties.",
                      "2026-06-01")  # 151 days later
        self.assertEqual(ghostjobs.find_reposts([p1, p2]), [])

    def test_groups_near_duplicate_text(self):
        body = (
            "Join our platform team to build scalable microservices in Go. "
            "You will own services end to end, review code, and mentor peers."
        )
        p1 = _posting("Globex", "Backend Engineer", body, "2026-08-01")
        p2 = _posting("Initech", "Software Developer", body + " Apply today!", "2026-08-02")
        groups = ghostjobs.find_reposts([p1, p2])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_distinct_postings_not_grouped(self):
        p1 = _posting("Acme", "Data Scientist", "Build ML models for fraud.", "2026-08-01")
        p2 = _posting("Globex", "Frontend Engineer", "Build React dashboards.", "2026-08-02")
        self.assertEqual(ghostjobs.find_reposts([p1, p2]), [])

    def test_transitive_grouping(self):
        body = "Identical posting body about building APIs and shipping features."
        posts = [
            _posting("A", "Eng", body, "2026-08-01"),
            _posting("B", "Eng", body, "2026-08-02"),
            _posting("C", "Eng", body, "2026-08-03"),
        ]
        groups = ghostjobs.find_reposts(posts)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)

    def test_empty_and_single_inputs(self):
        self.assertEqual(ghostjobs.find_reposts([]), [])
        self.assertEqual(ghostjobs.find_reposts([_posting("A", "B", "C", "2026-01-01")]), [])

    def test_missing_dates_still_group_on_duplicate_text(self):
        body = "Same exact posting text about the role and responsibilities listed."
        p1 = _posting("Acme", "Analyst", body, None)
        p2 = _posting("Acme", "Analyst", body, None)
        groups = ghostjobs.find_reposts([p1, p2])
        self.assertEqual(len(groups), 1)

    def test_helper_is_not_registered_detector(self):
        from candid.redflags.core import DETECTORS

        self.assertNotIn(ghostjobs.find_reposts, DETECTORS)


if __name__ == "__main__":
    unittest.main()
