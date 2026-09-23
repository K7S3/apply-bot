"""Tests for candid.profiles (multi-profile support, batch-73).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate before importing candid modules (config reads these at import).
_TMP = tempfile.TemporaryDirectory()
os.environ["CANDID_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["CANDID_CONFIG_DIR"] = str(Path(_TMP.name) / "config")

from candid import config, profiles  # noqa: E402
from candid.profiles import ContextError  # noqa: E402


def _reset_state():
    """Wipe registry + profile data so tests don't leak into each other."""
    reg = profiles.registry_path()
    if reg.exists():
        reg.unlink()
    pdir = Path(os.environ["CANDID_DATA_DIR"]) / "profiles"
    shutil.rmtree(pdir, ignore_errors=True)
    profiles.clear_request_profile()
    os.environ.pop("CANDID_PROFILE", None)


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        _reset_state()

    def tearDown(self):
        _reset_state()

    # --- create / list / validation --------------------------------------
    def test_create_and_list(self):
        info = profiles.create_profile("work", target_role="Data Scientist")
        self.assertEqual(info["name"], "work")
        self.assertEqual(info["target_role"], "Data Scientist")
        self.assertIn("created", info)
        self.assertIn("work", profiles.list_profiles())
        self.assertIn("default", profiles.list_profiles())

    def test_create_duplicate_raises(self):
        profiles.create_profile("work")
        with self.assertRaises(ContextError):
            profiles.create_profile("work")

    def test_name_validation(self):
        for bad in ["", "-lead", "_lead", "has space", "a/b", "a" * 65, None, 123]:
            with self.assertRaises(ContextError, msg=f"name={bad!r}"):
                profiles.create_profile(bad)
        # valid shapes
        for good in ["a", "work", "Work2", "my-profile_1", "a" * 64]:
            profiles.create_profile(good)

    def test_profile_info_unknown_raises(self):
        with self.assertRaises(ContextError):
            profiles.profile_info("nope")

    def test_profile_info_contents(self):
        profiles.create_profile("work", target_role="MLE")
        info = profiles.profile_info("work")
        self.assertEqual(info["name"], "work")
        self.assertEqual(info["target_role"], "MLE")
        self.assertTrue(info["created"])
        info0 = profiles.profile_info("default")
        self.assertEqual(info0["name"], "default")
        self.assertIsNone(info0["target_role"])

    # --- default maps to legacy paths -------------------------------------
    def test_default_profile_dir_is_legacy_data_dir(self):
        self.assertEqual(profiles.profile_dir("default"), config.DATA_DIR)
        self.assertEqual(
            profiles.profile_dir("work"),
            config.DATA_DIR / "profiles" / "work",
        )

    def test_config_helpers_default_return_module_constants(self):
        self.assertEqual(config.profile_json_path(), config.PROFILE_PATH)
        self.assertEqual(config.tracker_path(), config.TRACKER_PATH)
        self.assertEqual(config.offers_path(), config.OFFERS_PATH)
        self.assertEqual(config.prep_packs_dir(), config.PREP_PACKS_DIR)
        self.assertEqual(config.tailored_dir(), config.TAILOR_DIR)
        self.assertEqual(config.salary_db_path(), config.SALARY_DB)
        self.assertEqual(config.gmail_proposals_path(), config.GMAIL_PROPOSALS_PATH)

    def test_config_helpers_non_default_namespaced(self):
        profiles.create_profile("work")
        self.assertEqual(
            config.tracker_path(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "tracker.json",
        )
        self.assertEqual(
            config.profile_json_path(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "profile.json",
        )
        self.assertEqual(
            config.offers_path(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "offers.json",
        )
        self.assertEqual(
            config.prep_packs_dir(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "prep_packs",
        )
        self.assertEqual(
            config.tailored_dir(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "tailored",
        )
        self.assertEqual(
            config.salary_db_path(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "salary.db",
        )
        self.assertEqual(
            config.gmail_proposals_path(profile="work"),
            config.DATA_DIR / "profiles" / "work" / "gmail_proposals.json",
        )

    # --- isolation ---------------------------------------------------------
    def test_tracker_isolation_between_profiles(self):
        profiles.create_profile("p1")
        profiles.create_profile("p2")
        t1 = config.tracker_path(profile="p1")
        t2 = config.tracker_path(profile="p2")
        self.assertNotEqual(t1, t2)
        entries = [{"company": "Acme", "status": "applied"}]
        t1.write_text(json.dumps(entries))
        self.assertTrue(t2.parent.is_dir())
        self.assertFalse(t2.exists())
        self.assertEqual(json.loads(t1.read_text()), entries)

    # --- rename / delete ---------------------------------------------------
    def test_rename_moves_data_dir(self):
        profiles.create_profile("old", target_role="SE")
        config.tracker_path(profile="old").write_text(json.dumps([{"a": 1}]))
        profiles.rename_profile("old", "new")
        self.assertIn("new", profiles.list_profiles())
        self.assertNotIn("old", profiles.list_profiles())
        data = json.loads(config.tracker_path(profile="new").read_text())
        self.assertEqual(data, [{"a": 1}])
        self.assertEqual(profiles.profile_info("new")["target_role"], "SE")

    def test_rename_default_refused(self):
        config.TRACKER_PATH.write_text(json.dumps([{"a": 1}]))
        with self.assertRaises(ContextError):
            profiles.rename_profile("default", "renamed")
        # legacy data untouched
        self.assertEqual(json.loads(config.TRACKER_PATH.read_text()), [{"a": 1}])
        self.assertEqual(profiles.get_current(), "default")

    def test_rename_collision_raises(self):
        profiles.create_profile("a")
        profiles.create_profile("b")
        with self.assertRaises(ContextError):
            profiles.rename_profile("a", "b")

    def test_delete_refuses_default(self):
        with self.assertRaises(ContextError):
            profiles.delete_profile("default")

    def test_delete_refuses_profile_with_tracker_entries(self):
        profiles.create_profile("work")
        config.tracker_path(profile="work").write_text(json.dumps([{"a": 1}]))
        with self.assertRaises(ContextError):
            profiles.delete_profile("work")
        # force works
        profiles.delete_profile("work", force=True)
        self.assertNotIn("work", profiles.list_profiles())
        self.assertFalse((config.DATA_DIR / "profiles" / "work").exists())

    def test_delete_empty_profile_no_force(self):
        profiles.create_profile("empty")
        profiles.delete_profile("empty")
        self.assertNotIn("empty", profiles.list_profiles())

    def test_delete_current_resets_to_default(self):
        profiles.create_profile("work")
        profiles.set_current("work")
        profiles.delete_profile("work", force=True)
        self.assertEqual(profiles.get_current(), "default")

    # --- current ------------------------------------------------------------
    def test_get_set_current(self):
        self.assertEqual(profiles.get_current(), "default")
        profiles.create_profile("work")
        profiles.set_current("work")
        self.assertEqual(profiles.get_current(), "work")
        with self.assertRaises(ContextError):
            profiles.set_current("nope")

    # --- resolution ---------------------------------------------------------
    def test_resolve_explicit(self):
        profiles.create_profile("work")
        self.assertEqual(profiles.resolve("work"), "work")

    def test_resolve_unknown_raises(self):
        with self.assertRaises(ContextError):
            profiles.resolve("nope")
        with self.assertRaises(ContextError):
            profiles.resolve("-bad")

    def test_resolve_env_var(self):
        profiles.create_profile("work")
        os.environ["CANDID_PROFILE"] = "work"
        try:
            self.assertEqual(profiles.resolve(), "work")
        finally:
            del os.environ["CANDID_PROFILE"]

    def test_resolve_falls_back_to_current_then_default(self):
        profiles.create_profile("work")
        profiles.set_current("work")
        self.assertEqual(profiles.resolve(), "work")
        _reset_state()
        self.assertEqual(profiles.resolve(), "default")

    # --- request scoping ----------------------------------------------------
    def test_request_profile_scoping(self):
        profiles.create_profile("work")
        profiles.set_request_profile("work")
        try:
            self.assertEqual(profiles.active_profile(), "work")
            # CLI usage: thread active_profile() through the helpers
            self.assertEqual(
                config.tracker_path(profile=profiles.active_profile()),
                config.tracker_path(profile="work"),
            )
        finally:
            profiles.clear_request_profile()
        self.assertEqual(profiles.active_profile(), "default")

    def test_set_request_profile_unknown_raises(self):
        with self.assertRaises(ContextError):
            profiles.set_request_profile("nope")

    def test_set_request_profile_none_clears(self):
        profiles.create_profile("work")
        profiles.set_request_profile("work")
        profiles.set_request_profile(None)
        self.assertEqual(profiles.active_profile(), "default")

    # --- export / import -----------------------------------------------------
    def test_export_import_roundtrip(self):
        profiles.create_profile("work", target_role="Data Scientist")
        entries = [{"company": "Acme", "status": "applied"}]
        config.tracker_path(profile="work").write_text(json.dumps(entries))
        zf = Path(_TMP.name) / "work.zip"
        profiles.export_profile("work", zf)
        self.assertTrue(zf.is_file())

        # meta.json contents
        with zipfile.ZipFile(zf) as z:
            meta = json.loads(z.read("meta.json").decode("utf-8"))
        self.assertEqual(meta["name"], "work")
        self.assertEqual(meta["target_role"], "Data Scientist")
        self.assertIn("candid_version", meta)
        self.assertIn("tracker.json", z.namelist())

        # delete, then re-import under the same name
        profiles.delete_profile("work", force=True)
        info = profiles.import_profile(zf)
        self.assertEqual(info["name"], "work")
        self.assertEqual(info["target_role"], "Data Scientist")
        back = json.loads(config.tracker_path(profile="work").read_text())
        self.assertEqual(back, entries)

    def test_export_default_excludes_profiles_subtree(self):
        profiles.create_profile("other")
        config.tracker_path(profile="other").write_text(json.dumps([{"a": 1}]))
        config.TRACKER_PATH.write_text(json.dumps([{"b": 2}]))
        zf = Path(_TMP.name) / "default.zip"
        profiles.export_profile("default", zf)
        with zipfile.ZipFile(zf) as z:
            names = z.namelist()
        self.assertIn("tracker.json", names)
        self.assertTrue(all(not n.startswith("profiles/") for n in names))

    def test_import_collision_raises(self):
        profiles.create_profile("work", target_role="SE")
        zf = Path(_TMP.name) / "work.zip"
        profiles.export_profile("work", zf)
        with self.assertRaises(ContextError):
            profiles.import_profile(zf)
        # explicit free name works
        info = profiles.import_profile(zf, name="work2")
        self.assertEqual(info["name"], "work2")

    def test_import_missing_file_raises(self):
        with self.assertRaises(ContextError):
            profiles.import_profile(Path(_TMP.name) / "nope.zip")

    # --- clone ---------------------------------------------------------------
    def test_clone_copies_data(self):
        profiles.create_profile("src", target_role="MLE")
        entries = [{"company": "Acme", "status": "applied"}]
        config.tracker_path(profile="src").write_text(json.dumps(entries))
        info = profiles.clone_profile("src", "dst")
        self.assertEqual(info["target_role"], "MLE")
        back = json.loads(config.tracker_path(profile="dst").read_text())
        self.assertEqual(back, entries)

    def test_clone_unknown_source_raises(self):
        with self.assertRaises(ContextError):
            profiles.clone_profile("nope", "dst")

    def test_create_with_clone_from(self):
        profiles.create_profile("src")
        config.tracker_path(profile="src").write_text(json.dumps([{"a": 1}]))
        info = profiles.create_profile("dst", clone_from="src", target_role="SE")
        self.assertEqual(info["target_role"], "SE")
        back = json.loads(config.tracker_path(profile="dst").read_text())
        self.assertEqual(back, [{"a": 1}])

    # --- ensure_data_dirs ------------------------------------------------------
    def test_ensure_data_dirs_profile(self):
        profiles.create_profile("work")
        config.ensure_data_dirs(profile="work")
        d = config.DATA_DIR / "profiles" / "work"
        self.assertTrue(d.is_dir())
        self.assertTrue((d / "prep_packs").is_dir())
        self.assertTrue((d / "tailored").is_dir())

    def test_ensure_data_dirs_default_legacy(self):
        config.ensure_data_dirs()
        self.assertTrue(config.DATA_DIR.is_dir())
        self.assertTrue(config.PREP_PACKS_DIR.is_dir())
        self.assertTrue(config.TAILOR_DIR.is_dir())


if __name__ == "__main__":
    unittest.main()
