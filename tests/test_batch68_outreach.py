"""Tests for candid.outreach (batch-68 feature W2): personalized outreach drafts.

Covers: all 3 templates produce grounded drafts (dossier keyword present,
no placeholder tokens, profile name used), the LinkedIn 300-char cap,
sparse-dossier honest degradation (no invented specifics), the 3-variant
bundle with labels, build_from_files, and OutreachError paths.

Fictional sample data only.

Run: CANDID_DATA_DIR=/tmp/candid-test-outreach python3 -m unittest tests.test_batch68_outreach -v
"""
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-outreach"

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROFILE = {
    "name": "Alex Rivera",
    "headline": "Software Engineer, Machine Learning",
    "location": "New York, NY",
    "summary": "ML engineer focused on ads ranking.",
    "skills": ["python", "machine learning", "pytorch"],
    "experience": [
        {
            "title": "Software Engineer, Machine Learning",
            "company": "Globex",
            "dates": "2023-2026",
            "bullets": [
                "Built ranking models that improved click-through rate by 4%",
                "Led migration of training pipelines to distributed setup",
            ],
        },
        {
            "title": "Data Analyst",
            "company": "Initech",
            "dates": "2021-2023",
            "bullets": ["Automated weekly reporting dashboards"],
        },
    ],
    "education": [{"school": "State University", "degree": "BS CS", "dates": "2017-2021"}],
    "years_experience": 4.5,
    "seniority": "mid",
    "source_files": [],
}

RICH_DOSSIER = {
    "id": "hm-1",
    "name": "Maya Chen",
    "title": "Engineering Manager",
    "company": "Acme Corp",
    "team": "Recommendations",
    "notes": "Spoke at RecSys 2025 about serendipity in recommendations. Cares about mentorship.",
    "sources": [
        {"label": "RecSys 2025 talk on serendipity", "url": "https://example.com/talk"},
        {"label": "Acme engineering blog post on ranking", "url": "https://example.com/blog"},
    ],
    "interests": ["recommender systems", "mentorship"],
    "contact_hint": "prefers email",
}

SPARSE_DOSSIER = {
    "id": "hm-2",
    "name": "Jordan Lee",
    "title": "Hiring Manager",
    "company": "Beta Inc",
    "team": "",
    "notes": "",
    "sources": [],
    "interests": [],
    "contact_hint": "",
}

BARE_DOSSIER = {"name": "Casey Kim", "title": "", "company": "", "team": "",
                "notes": "", "sources": [], "interests": []}


def _install_fake_hm(dossier_by_ref):
    """Stub candid.hm so build_from_files can resolve dossiers in tests.

    Patches both sys.modules and the candid package attribute, because
    `from candid import hm` prefers the package attribute. Returns a token
    for _restore_hm.
    """
    import candid
    saved = (sys.modules.get("candid.hm"), getattr(candid, "hm", None))
    mod = types.ModuleType("candid.hm")
    mod.get_dossier = lambda ref: dossier_by_ref.get(ref)
    sys.modules["candid.hm"] = mod
    candid.hm = mod
    return saved


def _restore_hm(saved):
    import candid
    saved_sys, saved_attr = saved
    if saved_sys is None:
        sys.modules.pop("candid.hm", None)
    else:
        sys.modules["candid.hm"] = saved_sys
    if saved_attr is None:
        try:
            delattr(candid, "hm")
        except AttributeError:
            pass
    else:
        candid.hm = saved_attr


class TestTemplatesGrounded(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O

    def test_specific_hook_references_dossier_and_profile(self):
        d = self.O.draft_outreach(PROFILE, RICH_DOSSIER, role="ML Engineer",
                                  channel="email", tone="warm",
                                  template="specific-hook")
        self.assertEqual(d["template_used"], "specific-hook")
        # dossier-derived specific present
        self.assertIn("RecSys", d["body"])
        # profile-derived specific present
        self.assertIn("Alex Rivera", d["body"])
        self.assertIn("Globex", d["body"])
        self.assertIn("subject", d)
        # references tracks dossier keys actually used
        self.assertIn("notes", d["references"])
        self.assertIn("company", d["references"])
        self._assert_clean(d)

    def test_mutual_connection_names_connection(self):
        d = self.O.draft_outreach(PROFILE, RICH_DOSSIER, role="ML Engineer",
                                  channel="email", tone="formal",
                                  template="mutual-connection",
                                  mutual_connection="Sam Ortiz")
        self.assertEqual(d["template_used"], "mutual-connection")
        self.assertIn("Sam Ortiz", d["body"])
        self.assertIn("Alex Rivera", d["body"])
        self.assertIn("Dear Maya Chen,", d["body"])
        self._assert_clean(d)

    def test_mutual_connection_requires_name(self):
        with self.assertRaises(self.O.OutreachError):
            self.O.draft_outreach(PROFILE, RICH_DOSSIER, channel="email",
                                  template="mutual-connection")

    def test_recent_news_opens_on_source(self):
        d = self.O.draft_outreach(PROFILE, RICH_DOSSIER, role="ML Engineer",
                                  channel="email", tone="concise",
                                  template="recent-news")
        self.assertEqual(d["template_used"], "recent-news")
        self.assertIn("RecSys 2025 talk on serendipity", d["body"])
        self.assertIn("Alex Rivera", d["body"])
        self.assertIn("sources", d["references"])
        self._assert_clean(d)

    def _assert_clean(self, draft):
        for token in ("[Your Name]", "[Name]", "[Company]", "[Role]",
                      "[Mutual]", "{{", "TODO", "XXX"):
            self.assertNotIn(token, draft["body"], f"placeholder {token!r} leaked")
            if "subject" in draft:
                self.assertNotIn(token, draft["subject"])


class TestLinkedInCap(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O

    def test_linkedin_capped_for_every_tone_and_template(self):
        for tone in ("warm", "concise", "formal"):
            for template in ("specific-hook", "mutual-connection", "recent-news"):
                kw = {} if template != "mutual-connection" else {"mutual_connection": "Sam Ortiz"}
                d = self.O.draft_outreach(PROFILE, RICH_DOSSIER, role="ML Engineer",
                                          channel="linkedin", tone=tone,
                                          template=template, **kw)
                self.assertLessEqual(len(d["body"]), 300,
                                     f"{tone}/{template} exceeded 300 chars")
                self.assertNotIn("subject", d)

    def test_linkedin_capped_on_sparse_dossier_too(self):
        d = self.O.draft_outreach(PROFILE, BARE_DOSSIER, role="ML Engineer",
                                  channel="linkedin", template="specific-hook")
        self.assertLessEqual(len(d["body"]), 300)


class TestSparseDossierDegradation(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O

    def test_sparse_dossier_degrades_honestly(self):
        d = self.O.draft_outreach(PROFILE, SPARSE_DOSSIER, role="ML Engineer",
                                  channel="email", template="specific-hook")
        self.assertEqual(d["template_used"], "degraded-honest")
        # says so plainly
        self.assertIn("could not find much public detail", d["body"])
        # still grounded in the profile
        self.assertIn("Alex Rivera", d["body"])
        self.assertIn("Globex", d["body"])
        # no invented specifics from the dossier
        self.assertNotIn("RecSys", d["body"])
        self.assertNotIn("serendipity", d["body"])

    def test_recent_news_without_sources_degrades(self):
        d = self.O.draft_outreach(PROFILE, SPARSE_DOSSIER, channel="email",
                                  template="recent-news")
        self.assertEqual(d["template_used"], "degraded-honest")
        self.assertIn("could not find much public detail", d["body"])


class TestVariants(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O

    def test_exactly_three_labeled_variants(self):
        vs = self.O.outreach_variants(PROFILE, RICH_DOSSIER, role="ML Engineer")
        self.assertEqual(len(vs), 3)
        labels = [v["label"] for v in vs]
        self.assertEqual(labels, ["linkedin connection request", "short DM", "full email"])
        for v in vs:
            self.assertTrue(v["when_to_use"], f"{v['label']} missing when_to_use")
            # grounded in the dossier (first name survives truncation)
            self.assertIn("Maya", v["body"])
            if v["channel"] != "linkedin":
                self.assertIn("Alex Rivera", v["body"])

    def test_connection_request_within_cap(self):
        vs = self.O.outreach_variants(PROFILE, RICH_DOSSIER, role="ML Engineer")
        self.assertLessEqual(len(vs[0]["body"]), 300)

    def test_email_variant_has_subject(self):
        vs = self.O.outreach_variants(PROFILE, RICH_DOSSIER, role="ML Engineer")
        self.assertIn("subject", vs[2])
        self.assertIn("ML Engineer", vs[2]["subject"])


class TestValidation(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O

    def test_bad_channel_tone_template_raise(self):
        with self.assertRaises(self.O.OutreachError):
            self.O.draft_outreach(PROFILE, RICH_DOSSIER, channel="sms")
        with self.assertRaises(self.O.OutreachError):
            self.O.draft_outreach(PROFILE, RICH_DOSSIER, tone="sassy")
        with self.assertRaises(self.O.OutreachError):
            self.O.draft_outreach(PROFILE, RICH_DOSSIER, template="cold-call")

    def test_missing_profile_name_raises(self):
        with self.assertRaises(self.O.OutreachError):
            self.O.draft_outreach({"name": ""}, RICH_DOSSIER)

    def test_subject_reflects_role_and_company(self):
        from candid import outreach as O
        d = O.draft_outreach(PROFILE, RICH_DOSSIER, role="ML Engineer", channel="email")
        self.assertIn("Acme Corp", d["subject"])
        d2 = O.draft_outreach(PROFILE, RICH_DOSSIER, channel="email")
        self.assertIn("Alex Rivera", d2["subject"])


class TestBuildFromFiles(unittest.TestCase):
    def setUp(self):
        from candid import outreach as O
        self.O = O
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name) / "profile.json").write_text(
            json.dumps(PROFILE), encoding="utf-8")
        self._saved_hm = None

    def tearDown(self):
        if self._saved_hm is not None:
            _restore_hm(self._saved_hm)

    def test_round_trip(self):
        self._saved_hm = _install_fake_hm({"maya": RICH_DOSSIER})
        profile, dossier = self.O.build_from_files(
            profile_path=str(Path(self.tmp.name) / "profile.json"),
            dossier_ref="maya")
        self.assertEqual(profile["name"], "Alex Rivera")
        self.assertEqual(dossier["name"], "Maya Chen")

    def test_missing_profile_raises_clear_error(self):
        self._saved_hm = _install_fake_hm({"maya": RICH_DOSSIER})
        with self.assertRaises(self.O.OutreachError) as ctx:
            self.O.build_from_files(
                profile_path=str(Path(self.tmp.name) / "nope.json"),
                dossier_ref="maya")
        self.assertIn("not found", str(ctx.exception))

    def test_missing_dossier_ref_raises(self):
        with self.assertRaises(self.O.OutreachError) as ctx:
            self.O.build_from_files(
                profile_path=str(Path(self.tmp.name) / "profile.json"),
                dossier_ref=None)
        self.assertIn("dossier_ref", str(ctx.exception))

    def test_unknown_dossier_ref_raises(self):
        self._saved_hm = _install_fake_hm({})
        with self.assertRaises(self.O.OutreachError) as ctx:
            self.O.build_from_files(
                profile_path=str(Path(self.tmp.name) / "profile.json"),
                dossier_ref="nobody")
        self.assertIn("nobody", str(ctx.exception))

    def test_hm_without_get_dossier_raises_clear_error(self):
        import candid
        self._saved_hm = (sys.modules.get("candid.hm"), getattr(candid, "hm", None))
        broken = types.ModuleType("candid.hm")  # no get_dossier attribute
        sys.modules["candid.hm"] = broken
        candid.hm = broken
        with self.assertRaises(self.O.OutreachError) as ctx:
            self.O.build_from_files(
                profile_path=str(Path(self.tmp.name) / "profile.json"),
                dossier_ref="maya")
        self.assertIn("get_dossier", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
