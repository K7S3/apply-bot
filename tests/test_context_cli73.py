"""batch-73-b: tests for the `context` CLI and the global --profile flag.

Runs the real CLI via subprocess (python -m candid) with CANDID_DATA_DIR /
CANDID_CONFIG_DIR pointed at temp dirs, so tests are isolated from the
user's real data. Requires candid/profiles.py (worker A's module); these
tests are written against the batch-73 contract.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ContextCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="candid73-")
        cls.root = Path(__file__).resolve().parent.parent
        cls.env = dict(os.environ)
        cls.env["CANDID_DATA_DIR"] = str(Path(cls.tmp.name) / "data")
        cls.env["CANDID_CONFIG_DIR"] = str(Path(cls.tmp.name) / "config")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_cli(self, *args, check=False):
        return subprocess.run(
            [sys.executable, "-m", "candid", *args],
            cwd=self.root, env=self.env,
            capture_output=True, text=True)

    def run_ok(self, *args):
        r = self.run_cli(*args)
        self.assertEqual(
            r.returncode, 0,
            f"{' '.join(args)} failed (rc={r.returncode})\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
        return r

    # --- context command lifecycle ----------------------------------------

    def test_context_create_list_use_current(self):
        self.run_ok("context", "create", "alpha")
        self.run_ok("context", "create", "beta", "--target-role", "ML Engineer")
        out = self.run_ok("context", "list").stdout
        self.assertIn("alpha", out)
        self.assertIn("beta", out)
        self.run_ok("context", "use", "beta")
        self.assertEqual(self.run_ok("context", "current").stdout.strip(), "beta")

    def test_context_create_with_clone(self):
        self.run_ok("context", "create", "gamma", "--from", "beta")
        self.assertIn("gamma", self.run_ok("context", "list").stdout)

    def test_context_rename(self):
        self.run_ok("context", "create", "rename_me")
        self.run_ok("context", "rename", "rename_me", "renamed")
        out = self.run_ok("context", "list").stdout
        self.assertIn("renamed", out)
        self.assertNotIn("rename_me", out)

    def test_context_show(self):
        self.run_ok("context", "create", "showme", "--target-role", "Data Scientist")
        out = self.run_ok("context", "show", "showme").stdout
        self.assertIn("showme", out)
        self.assertIn("Data Scientist", out)

    def test_context_delete(self):
        self.run_ok("context", "create", "todelete")
        self.run_ok("context", "delete", "todelete", "--force")
        self.assertNotIn("todelete", self.run_ok("context", "list").stdout)

    def test_context_export_import(self):
        self.run_ok("context", "create", "exp1")
        dest = Path(self.tmp.name) / "exp1.zip"
        self.run_ok("context", "export", "exp1", "--file", str(dest))
        self.assertTrue(dest.exists())
        r = self.run_ok("context", "import", "--file", str(dest), "--name", "exp2")
        self.assertIn("exp2", r.stdout)
        self.assertIn("exp2", self.run_ok("context", "list").stdout)

    # --- --profile scoping --------------------------------------------------

    def test_profile_flag_scopes_tracker(self):
        self.run_ok("context", "create", "scoped")
        self.run_ok("--profile", "scoped", "track", "add",
                    "--company", "Acme", "--role", "ML Engineer")
        scoped = self.run_ok("--profile", "scoped", "track", "list").stdout
        self.assertIn("Acme", scoped)
        default = self.run_ok("track", "list").stdout
        self.assertNotIn("Acme", default)

    def test_profile_flag_before_subcommand_position(self):
        # the flag must appear before the subcommand
        self.run_ok("context", "create", "poscheck")
        r = self.run_cli("--profile", "poscheck", "context", "current")
        self.assertEqual(r.returncode, 0)

    # --- onboard --context --------------------------------------------------

    def test_onboard_context(self):
        resume = Path(self.tmp.name) / "resume73.txt"
        resume.write_text(
            "Jane Smith\nML Engineer\nSkills: Python, SQL, PyTorch\n"
            "Experience: 5 years at Acme Corp\n")
        r = self.run_ok("onboard", "--context", "ctx1", "--resume", str(resume))
        self.assertIn("Profile saved", r.stdout)
        show = self.run_ok("context", "show", "ctx1").stdout
        self.assertIn("has_profile: True", show)
        # visible under the profile, not in the current one
        scoped = self.run_ok("--profile", "ctx1", "profile", "show").stdout
        self.assertIn("Jane Smith", scoped)

    # --- --all-profiles ------------------------------------------------------

    def test_track_list_all_profiles(self):
        self.run_ok("context", "create", "allp1")
        self.run_ok("context", "create", "allp2")
        self.run_ok("--profile", "allp1", "track", "add",
                    "--company", "AlphaCo", "--role", "MLE")
        self.run_ok("--profile", "allp2", "track", "add",
                    "--company", "BetaCo", "--role", "MLE")
        out = self.run_ok("track", "list", "--all-profiles").stdout
        self.assertIn("AlphaCo", out)
        self.assertIn("BetaCo", out)
        self.assertIn("allp1", out)
        self.assertIn("allp2", out)
        # JSON variant tags each row with its profile
        data = json.loads(self.run_ok(
            "track", "list", "--all-profiles", "--json").stdout)
        by_profile = {d["profile"] for d in data}
        self.assertIn("allp1", by_profile)
        self.assertIn("allp2", by_profile)

    def test_track_stats_all_profiles(self):
        out = self.run_ok("track", "stats", "--all-profiles").stdout
        self.assertIn("allp1", out)
        self.assertIn("allp2", out)

    def test_all_profiles_restores_scope(self):
        # after --all-profiles, a plain track list still reflects the
        # current/request profile (no cross-profile leak) in one process
        self.run_ok("context", "create", "rst1")
        self.run_ok("context", "create", "rst2")
        self.run_ok("--profile", "rst1", "track", "add",
                    "--company", "RestoreCo", "--role", "MLE")
        self.run_ok("--profile", "rst2", "track", "add",
                    "--company", "OtherCo", "--role", "MLE")
        code = (
            "import os, sys\n"
            f"os.environ['CANDID_DATA_DIR'] = {str(Path(self.tmp.name) / 'data')!r}\n"
            f"os.environ['CANDID_CONFIG_DIR'] = {str(Path(self.tmp.name) / 'config')!r}\n"
            "sys.path.insert(0, r'{}')\n".format(self.root)
            + "from candid.__main__ import main\n"
            + "main(['--profile', 'rst1', 'track', 'list', '--all-profiles'])\n"
            + "print('===RESTORED===')\n"
            + "main(['--profile', 'rst1', 'track', 'list'])\n"
        )
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        tail = r.stdout.split("===RESTORED===")[-1]
        self.assertIn("RestoreCo", tail)     # still scoped to rst1's data
        self.assertNotIn("OtherCo", tail)    # rst2's data leaked back in

    # --- invalid profiles: clean errors, no tracebacks -----------------------

    def test_invalid_profile_name_fails_cleanly(self):
        for args in (["--profile", "bad/name", "track", "list"],
                     ["context", "create", "bad/name"],
                     ["context", "show", "no-such-profile"],
                     ["context", "use", "no-such-profile"]):
            r = self.run_cli(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertNotIn("Traceback", r.stderr, args)
            self.assertNotIn("Traceback", r.stdout, args)
            self.assertIn("Error:", r.stderr, args)

    def test_existing_profile_command_untouched(self):
        r = self.run_cli("profile", "--help")
        self.assertEqual(r.returncode, 0)
        # the old `profile` command has no subcommands added
        self.assertNotIn("context", r.stdout)


if __name__ == "__main__":
    unittest.main()
