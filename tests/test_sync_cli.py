"""Integration tests for the `candid sync` CLI surface.

Runs the CLI in-process with data/config dirs redirected into a temp dir
(per-test save/restore of candid.config attributes).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402


class SyncCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-synccli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR", "CONFIG_DIR"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp / "data"
        C.CONFIG_DIR = self.tmp / "config"
        C.TRACKER_PATH = C.DATA_DIR / "tracker.json"
        C.PROFILE_PATH = C.DATA_DIR / "profile.json"
        C.PREP_PACKS_DIR = C.DATA_DIR / "prep_packs"
        C.TAILOR_DIR = C.DATA_DIR / "tailored"
        C.SALARY_DB = C.DATA_DIR / "salary.sqlite"
        C.OFFERS_PATH = C.DATA_DIR / "offers.json"
        C.GMAIL_PROPOSALS_PATH = C.DATA_DIR / "gmail_proposals.json"
        C.ensure_data_dirs()
        C.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        C.PROFILE_PATH.write_text(json.dumps({"name": "CLI User"}))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()


class SyncCLIExportImportTest(SyncCLIBase):
    def _bundle(self):
        code, out, _ = self.run_cli(["sync", "export", str(self.tmp)])
        self.assertEqual(code, 0, out)
        zips = list(self.tmp.glob("candid-sync-*.zip"))
        self.assertEqual(len(zips), 1)
        return zips[0]

    def test_export_verify_import_round_trip(self):
        bundle = self._bundle()
        code, out, _ = self.run_cli(["sync", "verify", str(bundle)])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)
        code, out, _ = self.run_cli(["sync", "import", str(bundle),
                                    "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("unchanged", out)
        code, out, _ = self.run_cli(["sync", "import", str(bundle)])
        self.assertEqual(code, 0, out)
        self.assertIn("Imported", out)

    def test_export_dry_run_writes_nothing(self):
        before = set(self.tmp.glob("*.zip"))
        code, out, _ = self.run_cli(["sync", "export", "--dry-run",
                                    str(self.tmp)])
        self.assertEqual(code, 0)
        self.assertIn("preview", out.lower())
        self.assertEqual(set(self.tmp.glob("*.zip")), before)

    def test_export_include_filter(self):
        code, out, _ = self.run_cli(["sync", "export", str(self.tmp),
                                    "--include", "profile"])
        self.assertEqual(code, 0, out)
        zips = list(self.tmp.glob("candid-sync-*.zip"))
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        self.assertIn("profile.json", names)
        self.assertNotIn("tracker.json", names)

    def test_verify_tampered_bundle_fails_friendly(self):
        bundle = self._bundle()
        with zipfile.ZipFile(bundle, "a") as zf:
            zf.writestr("data/evil.txt", "tampered")
        code, _, err = self.run_cli(["sync", "verify", str(bundle)])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("sync --help", err)

    def test_import_bad_path_fails_friendly(self):
        code, _, err = self.run_cli(["sync", "import",
                                    str(self.tmp / "nope.zip")])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)


class SyncCLIStatusLogTest(SyncCLIBase):
    def test_status_before_and_after_sync(self):
        code, out, _ = self.run_cli(["sync", "status"])
        self.assertEqual(code, 0)
        self.assertIn("Machine id:", out)
        self.assertIn("none yet", out)
        code, out, _ = self.run_cli(["sync", "export", str(self.tmp)])
        self.assertEqual(code, 0)
        bundle = next(self.tmp.glob("candid-sync-*.zip"))
        code, _, _ = self.run_cli(["sync", "import", str(bundle)])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["sync", "status"])
        self.assertEqual(code, 0)
        self.assertIn("last_export:", out)
        self.assertIn("last_import:", out)
        code, out, _ = self.run_cli(["sync", "log", "--limit", "5"])
        self.assertEqual(code, 0)
        self.assertIn("export", out)
        self.assertIn("import", out)

    def test_status_json(self):
        code, out, _ = self.run_cli(["sync", "status", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("machine_id", data)


class SyncCLIPairRulesTest(SyncCLIBase):
    def test_pair_init_accept_list_remove(self):
        # init_pairing stamps THIS machine's id, so simulate the file coming
        # from a second machine by faking the id during init.
        from unittest import mock
        from candid.sync import pairing as SP

        pfile = self.tmp / "pair.json"
        with mock.patch.object(SP.machine, "get_machine_id",
                               return_value="m-fakepeer"):
            code, out, _ = self.run_cli(["sync", "pair", "init",
                                        "--name", "laptop",
                                        "--out", str(pfile)])
        self.assertEqual(code, 0, out)
        self.assertTrue(pfile.exists())
        code, out, _ = self.run_cli(["sync", "pair", "accept", str(pfile)])
        self.assertEqual(code, 0, out)
        self.assertIn("Paired", out)
        code, out, _ = self.run_cli(["sync", "pair", "list"])
        self.assertEqual(code, 0)
        self.assertIn("m-fakepeer", out)
        self.assertIn("laptop", out)
        code, out, _ = self.run_cli(["sync", "pair", "remove", "m-fakepeer"])
        self.assertEqual(code, 0)
        self.assertIn("Removed", out)

    def test_rules_set_show_clear(self):
        code, out, _ = self.run_cli(["sync", "rules", "set",
                                    "tracker", "newer-wins"])
        self.assertEqual(code, 0)
        self.assertIn("newer-wins", out)
        code, out, _ = self.run_cli(["sync", "rules", "show"])
        self.assertEqual(code, 0)
        self.assertIn("tracker", out)
        self.assertIn("newer-wins", out)
        code, out, _ = self.run_cli(["sync", "rules", "clear", "tracker"])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["sync", "rules", "show"])
        self.assertNotIn("newer-wins", out)


class SyncCLIConflictsTest(SyncCLIBase):
    def _make_conflict(self):
        from candid.sync import conflicts as SCon
        SCon.append_conflicts([{
            "kind": "record",
            "path": "tracker.json",
            "record_id": "app-1",
            "local": {"status": "applied"},
            "remote": {"status": "rejected"},
            "base": None,
            "bundle": "candid-sync-x.zip",
            "bundle_created_at": None,
        }])

    def test_conflicts_list_and_resolve(self):
        self._make_conflict()
        code, out, _ = self.run_cli(["sync", "conflicts", "list"])
        self.assertEqual(code, 0)
        self.assertIn("app-1", out)
        code, out, _ = self.run_cli(["sync", "conflicts", "resolve",
                                    "--ref", "0", "--choice", "remote"])
        self.assertEqual(code, 0, out)
        self.assertIn("remote", out)
        code, out, _ = self.run_cli(["sync", "conflicts", "list"])
        self.assertEqual(code, 0)
        self.assertIn("No pending", out)


class SyncCLIDeltaTest(SyncCLIBase):
    def test_since_last_exports_only_changes(self):
        from candid.sync import base as SB
        SB.update_last(SB.snapshot_current())
        C.PROFILE_PATH.write_text(json.dumps({"name": "changed"}))
        code, out, _ = self.run_cli(["sync", "export", "--since-last",
                                    "--dry-run", str(self.tmp)])
        self.assertEqual(code, 0, out)
        self.assertIn("1 changed", out)
        code, out, _ = self.run_cli(["sync", "export", "--since-last",
                                    str(self.tmp)])
        self.assertEqual(code, 0, out)
        zips = list(self.tmp.glob("candid-sync-delta-*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        self.assertIn("profile.json", names)
        code, out, _ = self.run_cli(["sync", "import", str(zips[0])])
        self.assertEqual(code, 0, out)
        self.assertIn("Applied delta", out)


if __name__ == "__main__":
    unittest.main()
