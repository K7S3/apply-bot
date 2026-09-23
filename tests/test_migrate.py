"""Tests for the config migration framework (candid migrate) and candid doctor.

Run: CANDID_DATA_DIR=/tmp/candid-test-migrate python3 -m unittest tests.test_migrate -v
"""
import glob
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _PatchedTree(unittest.TestCase):
    """Redirect config + data paths into a temp dir for each test."""

    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self._orig = (C.CONFIG_DIR, C.CONFIG_PATH, C.DATA_DIR)
        C.CONFIG_DIR = self.root / "config"
        C.CONFIG_PATH = C.CONFIG_DIR / "config.yaml"
        C.DATA_DIR = self.root / "data"
        self.C = C

    def tearDown(self):
        C = self.C
        C.CONFIG_DIR, C.CONFIG_PATH, C.DATA_DIR = self._orig
        self.td.cleanup()

    def write_v0(self, extra: dict | None = None) -> Path:
        """Write a pre-versioning (v0) config.yaml: no config_version key."""
        import yaml
        cfg = {"log_level": "DEBUG"}
        cfg.update(extra or {})
        self.C.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.C.CONFIG_PATH.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        return self.C.CONFIG_PATH

    def backups(self) -> list[str]:
        return sorted(glob.glob(str(self.C.CONFIG_PATH) + ".bak.*"))


class MigrationUnitTest(_PatchedTree):
    def test_v0_to_v1_stamps_and_backfills(self):
        from candid import migrations as M
        out, notes = M._migrate_v0_to_v1({"log_level": "DEBUG", "custom_key": 7})
        self.assertEqual(out["config_version"], 1)
        self.assertEqual(out["log_level"], "DEBUG")   # existing values kept
        self.assertEqual(out["custom_key"], 7)        # unknown keys preserved
        self.assertEqual(out["dashboard_port"], 8765)  # missing default backfilled
        self.assertTrue(any("dashboard_port" in n for n in notes))

    def test_migrations_from_current_is_empty(self):
        from candid import migrations as M, config as C
        self.assertEqual(M.migrations_from(C.CONFIG_VERSION), [])

    def test_migrations_from_v0_is_the_single_step(self):
        from candid import migrations as M
        steps = M.migrations_from(0)
        self.assertEqual(len(steps), 1)
        self.assertEqual((steps[0].from_version, steps[0].to_version), (0, 1))

    def test_migrations_from_newer_version_refuses(self):
        from candid import migrations as M, config as C
        with self.assertRaises(C.ConfigError):
            M.migrations_from(C.CONFIG_VERSION + 1)


class MigrateCommandTest(_PatchedTree):
    def test_v0_config_gets_migrated_with_backup(self):
        import yaml
        from candid import migrate as MIG
        before = self.write_v0()
        before_bytes = before.read_bytes()
        report = MIG.migrate_config()
        self.assertFalse(report["noop"])
        self.assertFalse(report["created"])
        self.assertEqual((report["from_version"], report["to_version"]), (0, 1))
        self.assertEqual(len(report["applied"]), 1)
        # backup exists, matches the timestamped naming, holds the original
        baks = self.backups()
        self.assertEqual(len(baks), 1)
        self.assertRegex(Path(baks[0]).name, r"config\.yaml\.bak\.\d{14}$")
        self.assertEqual(Path(baks[0]).read_bytes(), before_bytes)
        # config now stamped v1, original values kept
        cfg = yaml.safe_load(self.C.CONFIG_PATH.read_text())
        self.assertEqual(cfg["config_version"], 1)
        self.assertEqual(cfg["log_level"], "DEBUG")

    def test_idempotent_second_run_is_noop(self):
        from candid import migrate as MIG
        self.write_v0()
        first = MIG.migrate_config()
        self.assertFalse(first["noop"])
        second = MIG.migrate_config()
        self.assertTrue(second["noop"])
        self.assertIsNone(second["backup_path"])
        self.assertEqual(len(self.backups()), 1)  # no second backup written

    def test_missing_config_is_created_not_backed_up(self):
        from candid import migrate as MIG, config as C
        report = MIG.migrate_config()
        self.assertTrue(report["created"])
        self.assertTrue(self.C.CONFIG_PATH.exists())
        self.assertEqual(self.backups(), [])
        self.assertEqual(C.load_config()["config_version"], C.CONFIG_VERSION)

    def test_newer_config_is_refused_not_rewritten(self):
        import yaml
        from candid import migrate as MIG, config as C
        self.C.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.C.CONFIG_PATH.write_text(
            yaml.safe_dump({"config_version": C.CONFIG_VERSION + 5}), encoding="utf-8")
        with self.assertRaises(C.ConfigError):
            MIG.migrate_config()
        self.assertEqual(self.backups(), [])  # nothing touched

    def test_cli_migrate_reports_each_step(self):
        from candid import __main__ as MAIN
        self.write_v0()
        buf = io.StringIO()
        with redirect_stdout(buf):
            MAIN.main(["migrate"])
        out = buf.getvalue()
        self.assertIn("backup written", out)
        self.assertIn("v0 -> v1", out)
        self.assertIn("Done: config migrated v0 -> v1", out)


class DoctorTest(_PatchedTree):
    def test_healthy_tree_passes(self):
        from candid import doctor as D
        results = D.check_health()
        self.assertTrue(D.all_ok(results))
        self.assertEqual(len(results), 4)
        names = [r["name"] for r in results]
        self.assertIn("config loads", names)
        self.assertIn("config_version current", names)
        self.assertIn("data dir writable", names)
        self.assertIn("python >= 3.9", names)

    def test_outdated_config_flagged_with_migrate_hint(self):
        from candid import doctor as D
        self.write_v0()
        results = D.check_health()
        by_name = {r["name"]: r for r in results}
        self.assertFalse(D.all_ok(results))
        check = by_name["config_version current"]
        self.assertFalse(check["ok"])
        self.assertIn("candid migrate", check["detail"])

    def test_unreadable_config_flagged(self):
        from candid import doctor as D
        self.C.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.C.CONFIG_PATH.write_text("not: [valid, yaml\n", encoding="utf-8")
        results = D.check_health()
        self.assertFalse(D.all_ok(results))
        by_name = {r["name"]: r for r in results}
        self.assertFalse(by_name["config loads"]["ok"])

    def test_cli_doctor_healthy_exits_zero(self):
        from candid import __main__ as MAIN
        buf = io.StringIO()
        with redirect_stdout(buf):
            MAIN.main(["doctor"])
        self.assertIn("All checks passed", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
