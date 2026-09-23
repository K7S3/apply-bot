"""Tests for the `design` CLI command group (designer track).

Covers all 11 subcommands via candid.__main__.main(). Data paths are
redirected into a temp dir; interactive drills get mocked stdin and a
no-op countdown so no real sleeping happens.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import design as D  # noqa: E402
from candid import design_drills as DD  # noqa: E402
from candid import design_studio as DS  # noqa: E402

PROFILE = {
    "name": "Alex Rivera",
    "headline": "Product Designer",
    "location": "New York, NY",
    "summary": "Product designer focused on design systems.",
    "skills": ["figma", "prototyping", "user research", "design systems"],
    "experience": [{"title": "Product Designer", "company": "Meridian",
                    "dates": "2022 - Present",
                    "bullets": ["Redesigned onboarding flow."]}],
    "projects": [
        {"title": "Onboarding Redesign", "role": "Lead designer",
         "summary": "Cut signup drop-off with a 3-step flow.",
         "outcomes": ["Signup completion up 18%."]},
        {"title": "Design System v2", "role": "Contributor",
         "summary": "Tokenized component library.",
         "outcomes": ["Adopted by 4 teams."]},
    ],
    "education": [], "years_experience": 4, "seniority": "senior",
}

JD = ("Product Designer role. Must have: motion design, "
      "prototyping, and design systems experience. Nice to have: "
      "illustration.")


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        CLI.main(argv)
    return buf.getvalue()


class DesignCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-design-cli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "TAILOR_DIR", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.DATA_DIR = self.tmp
        C.PROFILE_PATH.write_text(json.dumps(PROFILE))
        self._saved_packs = D.DESIGN_PACKS_DIR
        D.DESIGN_PACKS_DIR = self.tmp / "design_packs"
        # design_studio / design_drills resolve the data dir at call time
        # via C._data_dir(), which honors the CANDID_DATA_DIR env var.
        self._saved_env = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = str(self.tmp)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)
        D.DESIGN_PACKS_DIR = self._saved_packs
        if self._saved_env is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._saved_env


class TestDesignCLI(DesignCLIBase):
    def test_prep(self):
        out = run_cli(["design", "prep", "--company", "Acme",
                       "--role", "Product Designer"])
        self.assertIn("Acme", out)
        self.assertIn("No company-verified", out)
        packs = list(D.DESIGN_PACKS_DIR.glob("*.md"))
        self.assertTrue(packs, "prep pack file should be written")

    def test_gaps(self):
        out = run_cli(["design", "gaps", "--jd", JD])
        self.assertIn("motion design", out.lower())
        self.assertIn("missing", out.lower())

    def test_concepts_list(self):
        out = run_cli(["design", "concepts"])
        self.assertIn("usability_heuristics", out)

    def test_concepts_show(self):
        out = run_cli(["design", "concepts", "usability_heuristics"])
        self.assertIn("heuristic", out.lower())

    def test_checklist(self):
        out = run_cli(["design", "checklist",
                       "--project", "redesigned onboarding flow"])
        self.assertIn("Accessibility", out)

    def test_site(self):
        out = run_cli(["design", "site"])
        self.assertIn("DRAFT", out)
        self.assertTrue((self.tmp / "design_packs" / "site_draft.md").exists())

    def test_walkthrough(self):
        out = run_cli(["design", "walkthrough", "--minutes", "5"])
        self.assertIn("Opener", out)
        self.assertIn("Onboarding Redesign", out)

    def test_casestudy_json(self):
        pj = self.tmp / "project.json"
        aj = self.tmp / "answers.json"
        pj.write_text(json.dumps({"title": "Onboarding Redesign"}))
        aj.write_text(json.dumps({
            "context": "Signup drop-off was 60%.",
            "role": "Lead designer",
            "research": "5 user interviews",
            "ideation": "3 concepts",
            "iteration": "2 usability rounds",
            "outcome": "Completion up 18%",
            "learnings": "Test earlier",
        }))
        out = run_cli(["design", "casestudy", "--project-json", str(pj),
                       "--answers-json", str(aj), "--export", "md"])
        self.assertIn("Onboarding Redesign", out)
        self.assertIn("Context", out)
        exported = list((self.tmp / "design_packs").glob("case-study-*.md"))
        self.assertTrue(exported, "case study export should be written")

    def test_present(self):
        out = run_cli(["design", "present", "--minutes", "10"])
        self.assertIn("saved", out.lower())
        plans = list((self.tmp / "design_packs").glob("presentation-plan-*.md"))
        self.assertTrue(plans, "presentation plan should be written")

    def test_critique(self):
        sc_id = DD.SCENARIOS[0]["id"]
        inputs = ["First observation.", "Second line.", "",
                  "2", "2", "2", "2"]
        with mock.patch("builtins.input", side_effect=inputs):
            out = run_cli(["design", "critique", "--scenario", sc_id])
        self.assertIn("Score:", out)
        self.assertIn("8/12", out)

    def test_whiteboard(self):
        ex_id = DD.EXERCISES[0]["id"]
        inputs = [""] + ["y"] * 8
        with mock.patch("builtins.input", side_effect=inputs), \
             mock.patch.object(DD, "countdown", lambda *a, **k: None):
            out = run_cli(["design", "whiteboard", "--exercise", ex_id,
                           "--minutes", "30"])
        self.assertIn("Self-review:", out)
        self.assertIn("8/8", out)

    def test_rapid_fire(self):
        inputs = ["my answer", "", "another answer"]
        with mock.patch("builtins.input", side_effect=inputs):
            out = run_cli(["design", "rapid-fire", "--n", "2"])
        self.assertIn("Answered 2 rapid-fire questions.", out)

    def test_design_in_command_inventory(self):
        self.assertIn("design", CLI.COMMANDS)
        self.assertIn("prep", CLI.SUBCOMMANDS["design"])


if __name__ == "__main__":
    unittest.main()
