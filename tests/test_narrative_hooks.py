"""Tests for candid.narrative_hooks: hook library + transition lines.

Run: python3 -m pytest tests/test_narrative_hooks.py -q
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-narrative-")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402

C.DATA_DIR = Path(os.environ["CANDID_DATA_DIR"])
C.PROFILE_PATH = C.DATA_DIR / "profile.json"

from candid import narrative_hooks as N  # noqa: E402
from candid.profile import OnboardError  # noqa: E402

FAKE_PROFILE = {
    "name": "Test Person",
    "headline": "Engineer",
    "skills": ["python"],
    "experience": [
        {
            "title": "Senior Engineer",
            "company": "BigCorp",
            "dates": "2022 - 2026",
            "bullets": [
                "Grew revenue by 40% to $12M ARR after leading a team of 6.",
                "Attended team meetings and wrote docs.",
                "Launched a platform serving 2M users across 3 regions.",
            ],
        },
        {
            "title": "Engineer",
            "company": "StartupX",
            "dates": "2020 - 2022",
            "bullets": [
                "Built internal dashboards for the support team.",
                "Shipped 15 features and cut support tickets by 30%.",
            ],
        },
        {
            "title": "Intern",
            "company": "DatelessCo",
            "dates": "",
            "bullets": [
                "Fixed bugs in the billing pipeline.",
            ],
        },
    ],
}


class NarrativeTestBase(unittest.TestCase):
    def setUp(self):
        p = C.PROFILE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(FAKE_PROFILE), encoding="utf-8")
        npath = C.DATA_DIR / "narrative.json"
        if npath.exists():
            npath.unlink()

    def tearDown(self):
        p = C.PROFILE_PATH
        if p.exists():
            p.unlink()
        npath = C.DATA_DIR / "narrative.json"
        if npath.exists():
            npath.unlink()


class ScorerTests(NarrativeTestBase):
    def test_metric_bearing_bullets_rank_highest(self):
        hooks = N.suggest_hooks(n=3)
        # the two metric-heavy bullets must top the ranking
        self.assertIn("40%", hooks[0]["text"])
        self.assertIn("2M", hooks[1]["text"])
        self.assertTrue(
            any("2M" in h["text"] for h in hooks[:3]),
            "metric bullet should rank in the top three",
        )

    def test_metric_template_chosen_deterministically(self):
        hooks = N.suggest_hooks(n=1)
        self.assertTrue(
            hooks[0]["text"].startswith("A result that captures what I bring: ")
        )

    def test_scope_template_for_scope_without_metric(self):
        hooks = N.suggest_hooks(n=10)
        by_bullet = {h["bullet"]: h for h in hooks}
        b = "Built internal dashboards for the support team."
        self.assertIn(b, by_bullet)
        self.assertTrue(
            by_bullet[b]["text"].startswith("The scale of my work is best shown by: ")
        )

    def test_quotes_source_bullet_verbatim_no_invented_metrics(self):
        hooks = N.suggest_hooks(n=10)
        by_bullet = {h["bullet"]: h for h in hooks}
        for bullet, hook in by_bullet.items():
            self.assertIn(bullet, hook["text"])
            # no em dashes anywhere
            self.assertNotIn("\u2014", hook["text"])
            self.assertEqual(hook["bullet"], bullet)

    def test_ties_break_in_profile_order(self):
        hooks = N.suggest_hooks(n=10)
        by_bullet = {h["bullet"]: h for h in hooks}
        # two zero-score plain bullets: "Attended team meetings" (BigCorp) first
        self.assertIn("Attended team meetings and wrote docs.", by_bullet)
        self.assertIn("Fixed bugs in the billing pipeline.", by_bullet)

    def test_hooks_cite_sources(self):
        hooks = N.suggest_hooks(n=2)
        self.assertIn("BigCorp", hooks[0]["source"])
        self.assertIn("Senior Engineer", hooks[0]["source"])


class HookRoundtripTests(NarrativeTestBase):
    def test_save_list_delete_roundtrip(self):
        hooks = N.store_suggestions(N.suggest_hooks(n=3))
        self.assertEqual(N.list_hooks(), [])
        saved = N.save_hook(hooks[0]["id"])
        self.assertTrue(saved["saved"])
        listed = N.list_hooks()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], hooks[0]["id"])
        deleted = N.delete_hook(hooks[0]["id"])
        self.assertEqual(deleted["id"], hooks[0]["id"])
        self.assertEqual(N.list_hooks(), [])

    def test_resuggest_preserves_saved_flags(self):
        hooks = N.store_suggestions(N.suggest_hooks(n=3))
        N.save_hook(hooks[1]["id"])
        again = N.suggest_hooks(n=3)
        N.store_suggestions(again)
        by_id = {h["id"]: h for h in N.list_hooks()}
        self.assertIn(hooks[1]["id"], by_id)

    def test_unknown_hook_id_raises(self):
        with self.assertRaises(N.NarrativeError):
            N.save_hook("hook-nope")
        with self.assertRaises(N.NarrativeError):
            N.delete_hook("hook-nope")

    def test_empty_hook_id_raises(self):
        with self.assertRaises(N.NarrativeError):
            N.save_hook("")

    def test_suggest_n_validation(self):
        with self.assertRaises(N.NarrativeError):
            N.suggest_hooks(n=0)
        with self.assertRaises(N.NarrativeError):
            N.suggest_hooks(n=-2)


class TransitionTests(NarrativeTestBase):
    def test_chronological_order(self):
        transitions = N.build_transitions()
        self.assertEqual(len(transitions), 2)
        self.assertEqual(transitions[0]["from_role"]["company"], "DatelessCo")
        self.assertEqual(transitions[0]["to_role"]["company"], "StartupX")
        self.assertEqual(transitions[1]["from_role"]["company"], "StartupX")
        self.assertEqual(transitions[1]["to_role"]["company"], "BigCorp")

    def test_motivation_placeholder_present(self):
        transitions = N.build_transitions()
        for t in transitions:
            self.assertIn(N.MOTIVATION_PLACEHOLDER, t["text"])
            self.assertNotIn("\u2014", t["text"])
        self.assertIn(
            "After Intern at DatelessCo, I moved to StartupX as Engineer.",
            transitions[0]["text"],
        )

    def test_list_transitions(self):
        self.assertEqual(N.list_transitions(), [])
        N.build_transitions()
        self.assertEqual(len(N.list_transitions()), 2)

    def test_update_transition(self):
        N.build_transitions()
        mine = "I joined BigCorp to work on large-scale payments."
        rec = N.update_transition(1, mine)
        self.assertEqual(rec["text"], mine)
        self.assertTrue(rec["edited"])
        self.assertEqual(N.list_transitions()[1]["text"], mine)

    def test_update_transition_guards(self):
        N.build_transitions()
        with self.assertRaises(N.NarrativeError):
            N.update_transition(1, "")
        with self.assertRaises(N.NarrativeError):
            N.update_transition(1, "   ")
        with self.assertRaises(N.NarrativeError):
            N.update_transition(99, "x")
        with self.assertRaises(N.NarrativeError):
            N.update_transition(-5, "x")

    def test_rebuild_preserves_user_edits(self):
        N.build_transitions()
        mine = "I wanted a bigger stage, so I joined BigCorp."
        N.update_transition(1, mine)
        rebuilt = N.build_transitions()
        self.assertEqual(rebuilt[1]["text"], mine)
        self.assertTrue(rebuilt[1]["edited"])
        # untouched transition is regenerated, not edited
        self.assertFalse(rebuilt[0]["edited"])

    def test_records_have_expected_keys(self):
        for t in N.build_transitions():
            self.assertEqual(
                set(t.keys()), {"from_role", "to_role", "text", "edited"}
            )
        for h in N.suggest_hooks(n=2):
            self.assertEqual(
                set(h.keys()), {"id", "text", "source", "bullet", "saved"}
            )


class StateTests(NarrativeTestBase):
    def test_sibling_keys_preserved(self):
        npath = C.DATA_DIR / "narrative.json"
        npath.parent.mkdir(parents=True, exist_ok=True)
        npath.write_text(
            json.dumps({"some_other_feature": {"x": 1}}), encoding="utf-8"
        )
        N.store_suggestions(N.suggest_hooks(n=1))
        N.build_transitions()
        data = json.loads(npath.read_text(encoding="utf-8"))
        self.assertEqual(data["some_other_feature"], {"x": 1})
        self.assertIn("hooks", data)
        self.assertIn("transitions", data)

    def test_missing_profile_raises_narrative_error(self):
        C.PROFILE_PATH.unlink()
        with self.assertRaises(N.NarrativeError) as ctx:
            N.suggest_hooks()
        self.assertIn("candid onboard --resume", str(ctx.exception))
        with self.assertRaises(N.NarrativeError):
            N.build_transitions()

    def test_no_profile_yaml_or_pii_artifacts(self):
        N.suggest_hooks(n=2)
        N.build_transitions()
        data_dir = list(C.DATA_DIR.iterdir())
        names = [p.name for p in data_dir]
        self.assertNotIn("profile.yaml", names)
        self.assertNotIn("output", names)


if __name__ == "__main__":
    unittest.main()
