"""Tests for candid.templates (batch 106, worker A: pack format + validation).

Covers: PACK_KINDS, builtin/user-dir discovery, get_pack, the
{{variable}} renderer, manifest validation (schema, semver, kind, slug,
undeclared variables, empty templates), the questions-pack Source: rule,
load/save round-trips, and .candidpack zip support with zip-slip
protection.

Run: CANDID_DATA_DIR=/tmp/candid-test-tpl-a python -m unittest discover -s tests -p 'test_templates_a.py'
"""
import json
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-tpl-a"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-tpl-a-config"

import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C
from candid import templates as T

BUILTIN_NAMES = {
    "cover-letter-standard",
    "outreach-referral",
    "questions-ml-fundamentals",
}

_DEFAULT_VARIABLES = [
    {"name": "candidate_name", "description": "Your name.", "required": True},
    {"name": "company", "description": "Target company.", "required": True},
    {"name": "hook", "description": "Optional hook line.", "required": False},
]


def _write_pack(base, name="test-pack", kind="cover-letter",
                version="1.2.0", variables=_DEFAULT_VARIABLES,
                templates=None, manifest_extra=None):
    """Write a pack dir under base; returns the pack dir Path."""
    pack_dir = Path(base) / name
    templates = templates or {
        "hello.md": "Hi {{candidate_name}} at {{company}}. {{hook}}",
    }
    manifest = {
        "name": name,
        "title": "Test Pack",
        "version": version,
        "kind": kind,
        "author": "tester",
        "description": "A test pack.",
        "variables": variables,
        "min_candid_version": "0.2.0",
    }
    manifest.update(manifest_extra or {})
    tdir = pack_dir / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    for fname, text in templates.items():
        (tdir / fname).write_text(text, encoding="utf-8")
    return pack_dir


class ConstantsTest(unittest.TestCase):
    def test_pack_kinds(self):
        self.assertEqual(
            T.PACK_KINDS, ("cover-letter", "outreach", "questions"))

    def test_builtin_packs_dir_exists(self):
        self.assertTrue(T.BUILTIN_PACKS_DIR.is_dir())

    def test_template_error_is_exception(self):
        self.assertTrue(issubclass(T.TemplateError, Exception))

    def test_user_dir_under_config_dir(self):
        # TEMPLATES_USER_DIR is defined off CONFIG_DIR in config.py.
        self.assertEqual(C.TEMPLATES_USER_DIR, C.CONFIG_DIR / "packs")
        # templates._user_dir() resolves at call time so the
        # CANDID_CONFIG_DIR override always wins, regardless of import order.
        with unittest.mock.patch.dict(
                os.environ, {"CANDID_CONFIG_DIR": "/tmp/x-config"}):
            self.assertEqual(T._user_dir(), Path("/tmp/x-config") / "packs")
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CANDID_CONFIG_DIR", None)
            self.assertEqual(T._user_dir(), C.TEMPLATES_USER_DIR)


class ListPacksTest(unittest.TestCase):
    def setUp(self):
        self.user_base = T._user_dir()
        self.user_base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.user_base, ignore_errors=True)

    def test_builtin_packs_listed(self):
        names = {p["name"] for p in T.list_packs()}
        self.assertTrue(BUILTIN_NAMES <= names)

    def test_kind_filter(self):
        packs = T.list_packs(kind="cover-letter")
        self.assertTrue(packs)
        self.assertTrue(all(p["kind"] == "cover-letter" for p in packs))
        self.assertIn("cover-letter-standard",
                      {p["name"] for p in packs})

    def test_kind_filter_questions(self):
        packs = T.list_packs(kind="questions")
        self.assertTrue(packs)
        self.assertTrue(all(p["kind"] == "questions" for p in packs))
        self.assertIn("questions-ml-fundamentals",
                      {p["name"] for p in packs})

    def test_unknown_kind_raises(self):
        with self.assertRaises(T.TemplateError):
            T.list_packs(kind="nope")

    def test_user_dir_pack_listed(self):
        _write_pack(self.user_base, name="my-outreach", kind="outreach")
        names = {p["name"] for p in T.list_packs()}
        self.assertIn("my-outreach", names)
        self.assertIn("my-outreach",
                      {p["name"] for p in T.list_packs(kind="outreach")})


class GetPackTest(unittest.TestCase):
    def test_get_pack_structure(self):
        pack = T.get_pack("cover-letter-standard")
        self.assertEqual(pack["manifest"]["name"], "cover-letter-standard")
        self.assertEqual(pack["manifest"]["kind"], "cover-letter")
        names = {t["name"] for t in pack["templates"]}
        self.assertEqual(names, {"concise", "formal"})
        for tpl in pack["templates"]:
            self.assertTrue(tpl["filename"].endswith(".md"))
            self.assertTrue(tpl["text"].strip())

    def test_get_pack_unknown_raises(self):
        with self.assertRaises(T.TemplateError):
            T.get_pack("no-such-pack")


class RenderTest(unittest.TestCase):
    def test_render_happy_path(self):
        out = T.render_template(
            "cover-letter-standard", "concise",
            {"candidate_name": "Alex Rivera", "company": "Initech",
             "role": "Data Scientist", "seniority": "senior",
             "hook": "Your ads ranking work is exactly my thing.",
             "proof": "I cut model training cost 40%."})
        self.assertIn("Alex Rivera", out)
        self.assertIn("Initech", out)
        self.assertNotIn("{{", out)

    def test_render_by_filename(self):
        out = T.render_template(
            "cover-letter-standard", "formal.md",
            {"candidate_name": "Alex", "company": "Initech",
             "role": "Data Scientist", "proof": "Did things."})
        self.assertIn("Alex", out)

    def test_render_optional_missing_keeps_placeholder(self):
        out = T.render_template(
            "cover-letter-standard", "concise",
            {"candidate_name": "Alex", "company": "Initech",
             "role": "Data Scientist", "proof": "Did things."})
        self.assertIn("{{hook}}", out)
        self.assertIn("{{seniority}}", out)

    def test_render_missing_required_raises(self):
        with self.assertRaises(T.TemplateError) as ctx:
            T.render_template(
                "cover-letter-standard", "concise",
                {"candidate_name": "Alex", "company": "Initech"})
        self.assertIn("role", str(ctx.exception))

    def test_render_unknown_template_raises(self):
        with self.assertRaises(T.TemplateError):
            T.render_template(
                "cover-letter-standard", "nope",
                {"candidate_name": "Alex"})

    def test_render_unknown_pack_raises(self):
        with self.assertRaises(T.TemplateError):
            T.render_template("nope", "concise", {})

    def test_template_variables_helper(self):
        self.assertEqual(
            T.template_variables("Hi {{name}}, {{ name }} and {{other}}"),
            ["name", "other"])


class ValidateTest(unittest.TestCase):
    def test_builtin_packs_validate(self):
        for name in BUILTIN_NAMES:
            pack = T.get_pack(name)
            result = T.validate_pack(pack["path"])
            self.assertEqual(result["issues"], [], name)
            self.assertTrue(result["ok"], name)

    def test_valid_custom_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp)
            result = T.validate_pack(pack_dir)
            self.assertTrue(result["ok"], result["issues"])

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "templates").mkdir()
            result = T.validate_pack(tmp)
            self.assertFalse(result["ok"])
            self.assertTrue(any("manifest.json" in i
                                for i in result["issues"]))

    def test_invalid_manifest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manifest.json").write_text("{not json")
            result = T.validate_pack(tmp)
            self.assertFalse(result["ok"])

    def test_missing_manifest_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, manifest_extra={"author": None})
            manifest_path = pack_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            del manifest["author"]
            manifest_path.write_text(json.dumps(manifest))
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("author" in i for i in result["issues"]))

    def test_bad_semver(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp, version="1.2")
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("semver" in i for i in result["issues"]))

    def test_bad_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp, kind="resume")
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("kind" in i for i in result["issues"]))

    def test_bad_slug_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp, name="Bad Name!")
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("slug" in i for i in result["issues"]))

    def test_undeclared_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, templates={"hello.md": "Hi {{candidate_name}}, {{oops}}"})
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("undeclared" in i and "oops" in i
                                for i in result["issues"]))

    def test_empty_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp, templates={"empty.md": "   \n"})
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("empty" in i for i in result["issues"]))

    def test_questions_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, kind="questions",
                templates={"q.md": "1. What is overfitting?\n"})
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("Source" in i for i in result["issues"]))

    def test_questions_with_source_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, kind="questions",
                templates={"q.md": "1. What is overfitting?\n"
                                    "   Source: https://example.com\n"})
            result = T.validate_pack(pack_dir)
            self.assertTrue(result["ok"], result["issues"])

    def test_source_rule_only_applies_to_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, kind="outreach",
                templates={"m.md": "1. Do this thing?\n"})
            result = T.validate_pack(pack_dir)
            self.assertTrue(result["ok"], result["issues"])

    def test_future_min_candid_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(
                tmp, manifest_extra={"min_candid_version": "99.0.0"})
            result = T.validate_pack(pack_dir)
            self.assertFalse(result["ok"])
            self.assertTrue(any("99.0.0" in i for i in result["issues"]))

    def test_validate_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp)
            zpath = T.pack_to_zip(pack_dir, Path(tmp) / "pack.candidpack")
            result = T.validate_pack(zpath)
            self.assertTrue(result["ok"], result["issues"])


class LoadSaveTest(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp)
            pack = T.load_pack(pack_dir)
            dest = Path(tmp) / "copy"
            T.save_pack(pack, dest)
            reloaded = T.load_pack(dest)
            self.assertEqual(reloaded["manifest"]["name"], "test-pack")
            self.assertEqual(reloaded["manifest"]["version"], "1.2.0")
            texts = {t["name"]: t["text"] for t in reloaded["templates"]}
            self.assertEqual(texts["hello"],
                             "Hi {{candidate_name}} at {{company}}. {{hook}}")

    def test_load_pack_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(T.TemplateError):
                T.load_pack(tmp)

    def test_load_pack_from_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp)
            zpath = T.pack_to_zip(pack_dir, Path(tmp) / "pack.candidpack")
            pack = T.load_pack(zpath)
            self.assertEqual(pack["manifest"]["name"], "test-pack")
            self.assertEqual(len(pack["templates"]), 1)


class ZipTest(unittest.TestCase):
    def test_zip_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack_dir = _write_pack(tmp)
            zpath = T.pack_to_zip(pack_dir, Path(tmp) / "pack.candidpack")
            self.assertTrue(zpath.is_file())
            dest = Path(tmp) / "extracted"
            T.pack_from_zip(zpath, dest)
            result = T.validate_pack(dest)
            self.assertTrue(result["ok"], result["issues"])

    def test_pack_to_zip_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(T.TemplateError):
                T.pack_to_zip(tmp, Path(tmp) / "x.candidpack")

    def test_zip_slip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "evil.candidpack"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("manifest.json", "{}")
                zf.writestr("../evil.md", "pwned")
            with self.assertRaises(T.TemplateError):
                T.pack_from_zip(zpath, Path(tmp) / "dest")
            self.assertFalse((Path(tmp) / "evil.md").exists())

    def test_zip_slip_absolute_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "evil.candidpack"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("manifest.json", "{}")
                zf.writestr("/tmp/candid-abs-evil.md", "pwned")
            with self.assertRaises(T.TemplateError):
                T.pack_from_zip(zpath, Path(tmp) / "dest")

    def test_zip_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(T.TemplateError):
                T.pack_from_zip(Path(tmp) / "nope.candidpack",
                                Path(tmp) / "dest")


if __name__ == "__main__":
    unittest.main()
