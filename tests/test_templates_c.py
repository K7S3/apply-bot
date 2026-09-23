"""Tests for candid.template_packs (batch-106 worker C): template pack
export/import, versioning (side-by-side installs), upgrade gating, diff,
and the `templates pack` CLI wiring.

Config paths are redirected into a temp dir by patching candid.config
attributes (same approach as the other CLI test modules).
"""
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import template_packs as TP  # noqa: E402


class PackBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-tpl-c-"))
        self._saved_config = C.CONFIG_DIR
        C.CONFIG_DIR = self.tmp / "config"
        self.src = self.tmp / "src"
        self.src.mkdir()
        self._pack_seq = 0

    def tearDown(self):
        C.CONFIG_DIR = self._saved_config
        sys.modules.pop("candid.templates", None)

    # -- helpers ---------------------------------------------------------
    def make_pack(self, name="demo", version="1.0.0", templates=None,
                  parent=None, **manifest_fields):
        """Create a pack source dir; returns the dir path."""
        templates = {"a.md": "hello A\n", "b.md": "hello B\n"} \
            if templates is None else templates
        self._pack_seq += 1
        d = (parent or self.src) / f"pack{self._pack_seq:02d}-{name}-{version}"
        tdir = d / "templates"
        tdir.mkdir(parents=True)
        entries = []
        for fname, text in templates.items():
            (tdir / fname).write_text(text, encoding="utf-8")
            entries.append({"file": f"templates/{fname}",
                            "name": Path(fname).stem})
        manifest = {"name": name, "title": f"{name} pack", "version": version,
                    "kind": "cover-letter", "author": "candid tests",
                    "description": f"{name} pack", "variables": [],
                    "min_candid_version": "0.2.0", **manifest_fields,
                    "templates": entries}
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                         encoding="utf-8")
        return d

    def run_cli(self, argv):
        """Run the CLI like `python -m candid ...`; returns (code, out, err)."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# semver
# ---------------------------------------------------------------------------

class SemverTest(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(TP.parse_semver("1.2.3")[:3], (1, 2, 3))
        self.assertEqual(TP.parse_semver("v2.0.0")[:3], (2, 0, 0))
        self.assertEqual(TP.parse_semver("1.0.0-alpha.1")[3], ("alpha", "1"))
        self.assertEqual(TP.parse_semver("1.0.0+build.5")[:3], (1, 0, 0))

    def test_parse_invalid(self):
        for bad in ("1.2", "abc", "", "1.2.3.4", "1.x.0"):
            with self.assertRaises(TP.TemplateError, msg=bad):
                TP.parse_semver(bad)

    def test_compare(self):
        self.assertEqual(TP.compare_semver("1.2.3", "1.2.4"), -1)
        self.assertEqual(TP.compare_semver("2.0.0", "1.9.9"), 1)
        self.assertEqual(TP.compare_semver("1.0.0", "1.0.0"), 0)
        # release beats prerelease of the same numbers
        self.assertEqual(TP.compare_semver("1.0.0-alpha", "1.0.0"), -1)
        self.assertEqual(TP.compare_semver("1.0.0-alpha", "1.0.0-beta"), -1)
        self.assertEqual(TP.compare_semver("1.0.0-alpha.1", "1.0.0-alpha.2"), -1)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

class ExportTest(PackBase):
    def test_export_creates_verified_zip(self):
        src = self.make_pack()
        out = self.tmp / "demo.candidpack"
        res = TP.export_pack(str(src), str(out))
        self.assertEqual(res["pack"], "demo")
        self.assertEqual(res["version"], "1.0.0")
        self.assertTrue(out.is_file())
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        self.assertIn("manifest.json", names)
        self.assertIn("templates/a.md", names)
        self.assertIn("checksums.sha256", names)
        # printed checksum matches the actual file digest
        import hashlib
        self.assertEqual(res["sha256"], hashlib.sha256(out.read_bytes()).hexdigest())
        # and the archive verifies on import
        inst = TP.import_pack(str(out))
        self.assertEqual(inst["pack"], "demo")

    def test_export_validates_pack(self):
        src = self.make_pack()
        (src / "templates" / "a.md").unlink()  # listed in manifest, missing
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.export_pack(str(src), str(self.tmp / "x.candidpack"))
        self.assertIn("validation failed", str(ctx.exception).lower())

    def test_export_unknown_pack(self):
        with self.assertRaises(TP.TemplateError):
            TP.export_pack("no-such-pack", str(self.tmp / "x.candidpack"))

    def test_export_picks_latest_installed_version(self):
        for v in ("1.0.0", "2.0.0"):
            TP.import_pack(self._exported(v))
        res = TP.export_pack("demo", str(self.tmp / "latest.candidpack"))
        self.assertEqual(res["version"], "2.0.0")

    def _exported(self, version):
        src = self.make_pack(version=version)
        out = self.tmp / f"demo-{version}.candidpack"
        TP.export_pack(str(src), str(out))
        return str(out)


# ---------------------------------------------------------------------------
# import / versions / upgrade
# ---------------------------------------------------------------------------

class ImportTest(PackBase):
    def _export(self, name="demo", version="1.0.0", templates=None, **kw):
        src = self.make_pack(name=name, version=version,
                             templates=templates, **kw)
        out = self.tmp / f"{name}-{version}.candidpack"
        TP.export_pack(str(src), str(out))
        return str(out)

    def test_import_installs_side_by_side(self):
        f1 = self._export(version="1.0.0")
        f2 = self._export(version="2.0.0")
        r1 = TP.import_pack(f1)
        r2 = TP.import_pack(f2)
        self.assertFalse(r1["replaced"])
        base = TP.user_packs_dir()
        self.assertTrue((base / "demo@1.0.0" / "manifest.json").is_file())
        self.assertTrue((base / "demo@2.0.0" / "manifest.json").is_file())
        self.assertEqual(r2["version"], "2.0.0")

    def test_import_same_version_refused_without_force(self):
        f = self._export()
        TP.import_pack(f)
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.import_pack(f)
        self.assertIn("already installed", str(ctx.exception))
        self.assertIn("--force", str(ctx.exception))

    def test_import_same_version_force_reinstalls(self):
        f = self._export()
        TP.import_pack(f)
        res = TP.import_pack(f, force=True)
        self.assertTrue(res["replaced"])
        self.assertEqual(res["version"], "1.0.0")

    def test_import_downgrade_refused_without_force(self):
        TP.import_pack(self._export(version="2.0.0"))
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.import_pack(self._export(version="1.0.0"))
        msg = str(ctx.exception)
        self.assertIn("newer version", msg)
        self.assertIn("--force", msg)

    def test_import_downgrade_allowed_with_force(self):
        TP.import_pack(self._export(version="2.0.0"))
        res = TP.import_pack(self._export(version="1.0.0"), force=True)
        self.assertEqual(res["version"], "1.0.0")

    def test_import_missing_file(self):
        with self.assertRaises(TP.TemplateError):
            TP.import_pack(str(self.tmp / "nope.candidpack"))

    def test_upgrade_to_newer(self):
        TP.import_pack(self._export(version="1.0.0"))
        res = TP.upgrade_pack(self._export(version="1.1.0"))
        self.assertEqual(res["version"], "1.1.0")
        self.assertEqual(res["previous"], "1.0.0")
        self.assertTrue((TP.user_packs_dir() / "demo@1.1.0").is_dir())

    def test_upgrade_same_version_refused(self):
        TP.import_pack(self._export(version="1.0.0"))
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.upgrade_pack(self._export(version="1.0.0"))
        self.assertIn("not newer", str(ctx.exception))

    def test_upgrade_older_refused(self):
        TP.import_pack(self._export(version="2.0.0"))
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.upgrade_pack(self._export(version="1.5.0"))
        self.assertIn("not newer", str(ctx.exception))

    def test_upgrade_fresh_install_allowed(self):
        res = TP.upgrade_pack(self._export(version="1.0.0"))
        self.assertEqual(res["version"], "1.0.0")
        self.assertIsNone(res["previous"])

    def test_versions_lists_side_by_side(self):
        TP.import_pack(self._export(version="1.0.0"))
        TP.import_pack(self._export(version="2.0.0"))
        res = TP.pack_versions("demo")
        self.assertEqual([v["version"] for v in res["versions"]],
                         ["1.0.0", "2.0.0"])
        self.assertEqual(res["versions"][0]["templates"], 2)

    def test_versions_empty(self):
        res = TP.pack_versions("demo")
        self.assertEqual(res["versions"], [])
        self.assertIn("No installed versions",
                      TP.render_versions_human(res))

    def test_name_with_path_traversal_rejected(self):
        with self.assertRaises(TP.TemplateError):
            TP.pack_versions("../evil")


# ---------------------------------------------------------------------------
# archive integrity
# ---------------------------------------------------------------------------

class IntegrityTest(PackBase):
    def _export(self, templates=None):
        src = self.make_pack(templates=templates)
        out = self.tmp / "demo.candidpack"
        TP.export_pack(str(src), str(out))
        return out

    def _rewrite_zip(self, src_zip, dest_zip, mutate):
        """Rebuild a zip from src_zip, applying mutate(name -> bytes|None)."""
        with zipfile.ZipFile(src_zip) as zin:
            items = [(i.filename, zin.read(i.filename))
                     for i in zin.infolist() if not i.filename.endswith("/")]
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in items:
                new = mutate(name, data)
                if new is not None:
                    zout.writestr(name, new)

    def test_zip_slip_rejected(self):
        evil = self.tmp / "evil.candidpack"
        manifest = {"name": "evil", "version": "1.0.0", "templates": []}
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../../evil.txt", "pwned")
            zf.writestr("checksums.sha256", "")
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.import_pack(str(evil))
        self.assertIn("traversal", str(ctx.exception).lower())
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_checksum_tamper_rejected(self):
        src = self._export()
        tampered = self.tmp / "tampered.candidpack"
        self._rewrite_zip(src, tampered,
                          lambda n, d: b"TAMPERED\n" if n == "templates/a.md" else d)
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.import_pack(str(tampered))
        self.assertIn("checksum mismatch", str(ctx.exception).lower())

    def test_missing_checksums_rejected(self):
        src = self._export()
        nocsum = self.tmp / "nocsum.candidpack"
        self._rewrite_zip(src, nocsum,
                          lambda n, d: None if n == "checksums.sha256" else d)
        with self.assertRaises(TP.TemplateError) as ctx:
            TP.import_pack(str(nocsum))
        self.assertIn("checksums.sha256", str(ctx.exception))

    def test_not_a_pack_archive(self):
        plain = self.tmp / "plain.zip"
        with zipfile.ZipFile(plain, "w") as zf:
            zf.writestr("hello.txt", "hi")
        with self.assertRaises(TP.TemplateError):
            TP.import_pack(str(plain))

    def test_validate_pack_ok_and_issues(self):
        src = self.make_pack()
        self.assertEqual(TP.validate_pack(str(src)),
                         {"ok": True, "issues": []})
        bad = self.tmp / "badpack"
        bad.mkdir()
        (bad / "manifest.json").write_text('{"name": "x"}')
        res = TP.validate_pack(str(bad))
        self.assertFalse(res["ok"])
        self.assertTrue(any("version" in i for i in res["issues"]))

    def test_worker_a_validator_merged_when_present(self):
        fake = types.ModuleType("candid.templates")
        fake.validate_pack = lambda path: {"ok": False,
                                            "issues": ["worker-a says no"]}
        sys.modules["candid.templates"] = fake
        src = self.make_pack()
        res = TP.validate_pack(str(src))
        self.assertFalse(res["ok"])
        self.assertIn("worker-a says no", res["issues"])

    def test_worker_a_absent_is_fine(self):
        # Simulate worker A's module being unavailable: validation works
        # on C's own checks alone.
        import candid as _candid_pkg

        saved_mod = sys.modules.pop("candid.templates", None)
        saved_attr = getattr(_candid_pkg, "templates", None)
        had_attr = hasattr(_candid_pkg, "templates")
        if had_attr:
            delattr(_candid_pkg, "templates")
        blocker = _BlockTemplatesImport()
        sys.meta_path.insert(0, blocker)
        try:
            src = self.make_pack()
            self.assertTrue(TP.validate_pack(str(src))["ok"])
        finally:
            sys.meta_path.remove(blocker)
            if saved_mod is not None:
                sys.modules["candid.templates"] = saved_mod
            if had_attr:
                _candid_pkg.templates = saved_attr


class _BlockTemplatesImport:
    """Meta-path blocker so tests can simulate a missing gallery module."""

    def find_spec(self, name, path=None, target=None):
        if name == "candid.templates":
            raise ImportError("candid.templates blocked for test")
        return None

# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

class DiffTest(PackBase):
    def test_diff_added_removed_changed(self):
        a = self.make_pack(name="demo", version="1.0.0",
                           templates={"a.md": "line1\nline2\n",
                                      "b.md": "same\n"},
                           parent=self.tmp / "pa")
        b = self.make_pack(name="demo", version="2.0.0",
                           templates={"a.md": "line1\nCHANGED\n",
                                      "c.md": "brand new\n"},
                           parent=self.tmp / "pb")
        res = TP.diff_packs(str(a), str(b))
        self.assertEqual(res["added"], ["c"])
        self.assertEqual(res["removed"], ["b"])
        self.assertEqual([c["name"] for c in res["changed"]], ["a"])
        snippet = res["changed"][0]["diff"]
        self.assertIn("-line2", snippet)
        self.assertIn("+CHANGED", snippet)
        self.assertIn("@@", snippet)
        fields = {c["field"] for c in res["manifest_changes"]}
        self.assertIn("version", fields)

    def test_diff_manifest_description_change(self):
        a = self.make_pack(description="old words")
        b = self.make_pack(description="new words")
        res = TP.diff_packs(str(a), str(b))
        change = next(c for c in res["manifest_changes"]
                      if c["field"] == "description")
        self.assertEqual((change["a"], change["b"]), ("old words", "new words"))

    def test_diff_identical(self):
        a = self.make_pack()
        res = TP.diff_packs(str(a), str(a))
        self.assertEqual(res["added"], [])
        self.assertEqual(res["removed"], [])
        self.assertEqual(res["changed"], [])
        self.assertEqual(res["manifest_changes"], [])

    def test_diff_zip_against_installed(self):
        src = self.make_pack(version="1.0.0")
        out = self.tmp / "demo.candidpack"
        TP.export_pack(str(src), str(out))
        TP.import_pack(str(out))
        res = TP.diff_packs("demo", str(out))
        self.assertEqual(res["added"], [])

    def test_render_human(self):
        a = self.make_pack(templates={"a.md": "one\n"})
        b = self.make_pack(templates={"a.md": "two\n", "z.md": "new\n"})
        text = TP.render_diff_human(TP.diff_packs(str(a), str(b)))
        self.assertIn("added templates (1)", text)
        self.assertIn("+ z", text)
        self.assertIn("changed templates (1)", text)
        self.assertIn("~ a", text)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

class CLIWireTest(PackBase):
    def _export(self, name="demo", version="1.0.0", templates=None):
        src = self.make_pack(name=name, version=version, templates=templates)
        out = self.tmp / f"{name}-{version}.candidpack"
        TP.export_pack(str(src), str(out))
        return str(out)

    def test_inventory(self):
        self.assertIn("templates", CLI.COMMANDS)
        self.assertIn("pack", CLI.SUBCOMMANDS["templates"])
        self.assertIn("TemplateError", CLI._EXPECTED_ERRORS)

    def test_parser_ops(self):
        for argv in (["templates", "pack", "export", "x", "--out", "x.cp"],
                     ["templates", "pack", "import", "x.cp"],
                     ["templates", "pack", "import", "x.cp", "--force"],
                     ["templates", "pack", "upgrade", "x.cp"],
                     ["templates", "pack", "versions", "x"],
                     ["templates", "pack", "diff", "a", "b"],
                     ["templates", "pack", "diff", "a", "b", "--json"]):
            a = CLI.build_parser().parse_args(argv)
            self.assertEqual(a.func, CLI.cmd_templates_pack)
            self.assertEqual(a.cmd, "templates")

    def test_cli_export_import_roundtrip_json(self):
        f = self._export()
        code, out, _ = self.run_cli(
            ["templates", "pack", "import", f, "--json"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["pack"], "demo")
        self.assertEqual(res["version"], "1.0.0")

        code, out, _ = self.run_cli(
            ["templates", "pack", "export", "demo", "--json"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(len(res["sha256"]), 64)

        code, out, _ = self.run_cli(
            ["templates", "pack", "versions", "demo", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["versions"]), 1)

    def test_cli_import_twice_is_friendly_error(self):
        f = self._export()
        self.assertEqual(self.run_cli(["templates", "pack", "import", f])[0], 0)
        code, _, err = self.run_cli(["templates", "pack", "import", f])
        self.assertEqual(code, 1)
        self.assertIn("already installed", err)
        self.assertIn("templates pack --help", err)

    def test_cli_downgrade_message(self):
        self.run_cli(["templates", "pack", "import", self._export(version="2.0.0")])
        code, _, err = self.run_cli(
            ["templates", "pack", "import", self._export(version="1.0.0")])
        self.assertEqual(code, 1)
        self.assertIn("newer version", err)

    def test_cli_upgrade_flow(self):
        self.run_cli(["templates", "pack", "import", self._export(version="1.0.0")])
        code, out, _ = self.run_cli(
            ["templates", "pack", "upgrade", self._export(version="1.1.0")])
        self.assertEqual(code, 0)
        self.assertIn("Upgraded pack 'demo' to v1.1.0", out)
        code, _, err = self.run_cli(
            ["templates", "pack", "upgrade", self._export(version="1.0.0")])
        self.assertEqual(code, 1)
        self.assertIn("not newer", err)

    def test_cli_diff_json(self):
        self._export(version="1.0.0", templates={"a.md": "one\n"})
        f2 = self._export(version="2.0.0",
                          templates={"a.md": "two\n", "z.md": "new\n"})
        self.run_cli(["templates", "pack", "import", self._export(version="1.0.0")])
        self.run_cli(["templates", "pack", "import", f2])
        code, out, _ = self.run_cli(
            ["templates", "pack", "diff", "demo@1.0.0", "demo@2.0.0", "--json"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["added"], ["z"])
        self.assertEqual([c["name"] for c in res["changed"]], ["a"])

    def test_cli_diff_human(self):
        self.run_cli(["templates", "pack", "import", self._export(version="1.0.0")])
        self.run_cli(["templates", "pack", "import", self._export(version="2.0.0")])
        code, out, _ = self.run_cli(
            ["templates", "pack", "diff", "demo@1.0.0", "demo@2.0.0"])
        self.assertEqual(code, 0)
        self.assertIn("diff demo@1.0.0 -> demo@2.0.0", out)

    def test_cli_unknown_pack_friendly(self):
        code, _, err = self.run_cli(["templates", "pack", "export", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)


if __name__ == "__main__":
    unittest.main()
