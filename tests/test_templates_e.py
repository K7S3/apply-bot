"""Tests for question-pack import (batch 106, worker E).

Run: CANDID_DATA_DIR=/tmp/candid-test-tpl-e python3 -m unittest tests.test_templates_e -v
(also honored when set in-process below).
"""
import io
import json
import os
import shutil
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-tpl-e")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-tpl-e")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Stub for candid.templates (worker A's gallery module) implementing the
# documented contract: TemplateError, list_packs(kind), get_pack(name).
# ---------------------------------------------------------------------------

PACKS = {}


class TemplateError(Exception):
    pass


def _list_packs(kind=None):
    return [n for n, p in PACKS.items()
            if kind is None or p["manifest"].get("kind") == kind]


def _get_pack(name):
    if name not in PACKS:
        raise TemplateError(f"unknown pack '{name}'")
    return PACKS[name]


_SAVED_TEMPLATES_MODULE = sys.modules.get("candid.templates")
_SAVED_TEMPLATES_ATTR = getattr(__import__("candid"), "templates", None)
_HAD_TEMPLATES_ATTR = hasattr(__import__("candid"), "templates")


def _install_stub():
    mod = types.ModuleType("candid.templates")
    mod.TemplateError = TemplateError
    mod.list_packs = _list_packs
    mod.get_pack = _get_pack
    sys.modules["candid.templates"] = mod
    __import__("candid").templates = mod


def _remove_stub():
    if _SAVED_TEMPLATES_MODULE is not None:
        sys.modules["candid.templates"] = _SAVED_TEMPLATES_MODULE
    else:
        sys.modules.pop("candid.templates", None)
    if _HAD_TEMPLATES_ATTR:
        __import__("candid").templates = _SAVED_TEMPLATES_ATTR
    elif hasattr(__import__("candid"), "templates"):
        delattr(__import__("candid"), "templates")


class _BlockTemplatesImport:
    """Meta-path blocker so tests can simulate a missing gallery module."""

    def find_spec(self, name, path=None, target=None):
        if name == "candid.templates":
            raise ImportError("candid.templates blocked for test")
        return None

def _md(blocks):
    """Build a templates/*.md doc from (heading, category, question, source)."""
    parts = ["# Question pack", ""]
    for heading, category, question, source in blocks:
        parts += [f"## {heading}", "", f"Category: {category}", "",
                  question, "", f"Source: {source}", ""]
    return "\n".join(parts)


def _fixture_packs():
    return {
        "acme-ds": {
            "manifest": {"name": "acme-ds", "version": "1.0.0",
                         "kind": "questions", "company": "Acme"},
            "templates": {
                "behavioral.md": _md([
                    ("Conflict", "behavioral",
                     "Tell me about a time you disagreed with a teammate.",
                     "https://example.com/acme-guide"),
                    ("Failure", "behavioral",
                     "Describe a project that failed and what you changed.",
                     "Example Guide - https://example.com/acme-failure"),
                ]),
            },
        },
        # One question duplicates a real QUESTIONS_DB entry verbatim.
        "dup-pack": {
            "manifest": {"name": "dup-pack", "version": "2.0.0",
                         "kind": "questions", "company": "Meta"},
            "templates": {
                "misc.md": _md([
                    ("Ambiguity", "behavioral",
                     "How do you embrace ambiguity and work comfortably "
                     "with minimal guidelines or information?",
                     "https://example.com/meta-guide"),
                    ("Fresh", "ml",
                     "What regularization would you try first on a small "
                     "tabular dataset?",
                     "https://example.com/meta-ml"),
                ]),
            },
        },
        "resume-pack": {
            "manifest": {"name": "resume-pack", "version": "1.0.0",
                         "kind": "resume"},
            "templates": {"resume.md": "# Resume\n\n## Summary\n\nText.\n"},
        },
    }


class QuestionPacksTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        _clean()
        self._orig_data_dir = C.DATA_DIR
        C.DATA_DIR = TEST_DIR
        _install_stub()
        PACKS.clear()
        PACKS.update(_fixture_packs())

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self._orig_data_dir
        _remove_stub()

    # -- happy path ------------------------------------------------------
    def test_import_adds_questions_with_pack_tags(self):
        from candid import question_packs as QP
        res = QP.import_pack("acme-ds", company="Acme")
        self.assertEqual(res["status"], "imported")
        self.assertEqual(res["added"], 2)
        self.assertEqual(res["skipped_duplicates"], 0)
        self.assertEqual(res["slug"], "acme")
        overlay = json.loads((TEST_DIR / QP.OVERLAY_FILENAME).read_text())
        entries = overlay["companies"]["acme"]
        self.assertEqual(len(entries), 2)
        for e in entries:
            self.assertEqual(e["pack"], "acme-ds")
            self.assertEqual(e["pack_version"], "1.0.0")
            self.assertTrue(e["url"].startswith("https://"))
        # entry shape matches the QUESTIONS_DB format
        for key in ("q", "category", "source", "url", "reported"):
            self.assertIn(key, entries[0])

    def test_merged_db_includes_overlay_without_mutating_constant(self):
        from candid import question_packs as QP
        from candid.prep_questions import QUESTIONS_DB
        QP.import_pack("acme-ds", company="Acme")
        merged = QP.merged_questions_db()
        self.assertEqual(len(merged["acme"]), 2)
        self.assertNotIn("acme", QUESTIONS_DB)  # module constant untouched

    def test_manifest_company_used_when_flag_absent(self):
        from candid import question_packs as QP
        res = QP.import_pack("acme-ds")  # manifest names Acme
        self.assertEqual(res["slug"], "acme")

    def test_dry_run_writes_nothing(self):
        from candid import question_packs as QP
        res = QP.import_pack("acme-ds", company="Acme", dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertEqual(res["would_add"], 2)
        self.assertFalse((TEST_DIR / QP.OVERLAY_FILENAME).exists())
        self.assertFalse((TEST_DIR / QP.REGISTRY_FILENAME).exists())

    # -- dedupe + registry ------------------------------------------------
    def test_dedupes_against_existing_bank_text(self):
        from candid import question_packs as QP
        res = QP.import_pack("dup-pack", company="Meta")
        self.assertEqual(res["status"], "imported")
        self.assertEqual(res["added"], 1)  # the verbatim meta question skipped
        self.assertEqual(res["skipped_duplicates"], 1)
        self.assertNotIn("embrace ambiguity",
                         " ".join(e["q"] for e in res["questions"]))

    def test_reimport_same_version_is_noop(self):
        from candid import question_packs as QP
        first = QP.import_pack("acme-ds", company="Acme")
        self.assertEqual(first["status"], "imported")
        second = QP.import_pack("acme-ds", company="Acme")
        self.assertEqual(second["status"], "no-op")
        overlay = json.loads((TEST_DIR / QP.OVERLAY_FILENAME).read_text())
        self.assertEqual(len(overlay["companies"]["acme"]), 2)

    def test_newer_version_imports_only_new_questions(self):
        from candid import question_packs as QP
        QP.import_pack("acme-ds", company="Acme")
        PACKS["acme-ds"]["manifest"]["version"] = "1.1.0"
        # v1.1.0 appends one new question block to the existing template file
        PACKS["acme-ds"]["templates"]["behavioral.md"] += (
            "\n## New\n\nCategory: stats\n\n"
            "How would you design an experiment for a new ranking model?\n\n"
            "Source: https://example.com/acme-v11\n"
        )
        res = QP.import_pack("acme-ds", company="Acme")
        self.assertEqual(res["status"], "imported")
        self.assertEqual(res["added"], 1)
        self.assertEqual(res["skipped_duplicates"], 2)
        reg = json.loads((TEST_DIR / QP.REGISTRY_FILENAME).read_text())
        self.assertEqual(reg["acme-ds"]["version"], "1.1.0")
        overlay = json.loads((TEST_DIR / QP.OVERLAY_FILENAME).read_text())
        self.assertEqual(len(overlay["companies"]["acme"]), 3)

    # -- validation: verified-only rule -----------------------------------
    def test_wrong_kind_rejected(self):
        from candid import question_packs as QP
        with self.assertRaises(TemplateError) as cm:
            QP.import_pack("resume-pack", company="Acme")
        self.assertIn("not a 'questions' pack", str(cm.exception))

    def test_missing_source_rejected_naming_template_and_line(self):
        from candid import question_packs as QP
        PACKS["bad-pack"] = {
            "manifest": {"name": "bad-pack", "version": "1.0.0",
                         "kind": "questions"},
            "templates": {"q.md": "## Mystery question\n\n"
                                  "What is your favorite color?\n"},
        }
        with self.assertRaises(TemplateError) as cm:
            QP.import_pack("bad-pack", company="Acme")
        msg = str(cm.exception)
        self.assertIn("q.md", msg)
        self.assertIn("line", msg)
        self.assertIn("Source", msg)

    def test_source_without_link_rejected(self):
        from candid import question_packs as QP
        PACKS["nolink-pack"] = {
            "manifest": {"name": "nolink-pack", "version": "1.0.0",
                         "kind": "questions"},
            "templates": {"q.md": "## Q\n\nSome question?\n\n"
                                  "Source: a guide with no url\n"},
        }
        with self.assertRaises(TemplateError) as cm:
            QP.import_pack("nolink-pack", company="Acme")
        self.assertIn("no link", str(cm.exception))

    def test_missing_company_rejected(self):
        from candid import question_packs as QP
        PACKS["nocompany"] = {
            "manifest": {"name": "nocompany", "version": "1.0.0",
                         "kind": "questions"},
            "templates": {"q.md": _md([("Q", "ml", "Some question?",
                                              "https://example.com/x")])},
        }
        with self.assertRaises(TemplateError) as cm:
            QP.import_pack("nocompany")
        self.assertIn("--company", str(cm.exception))

    def test_empty_pack_rejected(self):
        from candid import question_packs as QP
        PACKS["empty"] = {
            "manifest": {"name": "empty", "version": "1.0.0",
                         "kind": "questions"},
            "templates": {"q.md": "# Nothing here\n\nJust prose.\n"},
        }
        with self.assertRaises(TemplateError) as cm:
            QP.import_pack("empty", company="Acme")
        self.assertIn("no question blocks", str(cm.exception))

    def test_unknown_pack_propagates_template_error(self):
        from candid import question_packs as QP
        with self.assertRaises(TemplateError):
            QP.import_pack("no-such-pack", company="Acme")

    def test_missing_gallery_module_graceful(self):
        from candid import question_packs as QP
        import candid as _candid_pkg
        saved_mod = sys.modules.pop("candid.templates", None)
        saved_attr = getattr(_candid_pkg, "templates", None)
        had_attr = hasattr(_candid_pkg, "templates")
        if had_attr:
            delattr(_candid_pkg, "templates")
        blocker = _BlockTemplatesImport()
        sys.meta_path.insert(0, blocker)
        try:
            with self.assertRaises(QP.QuestionPackError) as cm:
                QP.import_pack("acme-ds", company="Acme")
            self.assertIn("candid/templates.py", str(cm.exception))
        finally:
            sys.meta_path.remove(blocker)
            if saved_mod is not None:
                sys.modules["candid.templates"] = saved_mod
            if had_attr:
                _candid_pkg.templates = saved_attr
            _install_stub()

    # -- list --------------------------------------------------------------
    def test_list_tags_pack_name_and_version(self):
        from candid import question_packs as QP
        QP.import_pack("acme-ds", company="Acme")
        QP.import_pack("dup-pack", company="Meta")
        qs = QP.list_pack_questions()
        self.assertEqual(len(qs), 3)
        by_pack = {}
        for q in qs:
            by_pack.setdefault(q["pack"], set()).add(q["pack_version"])
        self.assertEqual(by_pack, {"acme-ds": {"1.0.0"}, "dup-pack": {"2.0.0"}})

    def test_list_company_filter(self):
        from candid import question_packs as QP
        QP.import_pack("acme-ds", company="Acme")
        QP.import_pack("dup-pack", company="Meta")
        qs = QP.list_pack_questions(company="Acme")
        self.assertEqual(len(qs), 2)
        acme_only = [q for q in qs if q["company_slug"] == "acme"]
        self.assertEqual(len(acme_only), 2)
        meta_qs = QP.list_pack_questions(company="Meta")
        self.assertEqual(len(meta_qs), 1)

    def test_list_empty(self):
        from candid import question_packs as QP
        self.assertEqual(QP.list_pack_questions(), [])
        self.assertIn("No pack-contributed",
                      QP.render_pack_questions([], company="Acme"))


class TemplatesCliTest(unittest.TestCase):
    """CLI wiring for `templates questions ...` (no gallery module needed
    for parsing; the stub backs execution)."""

    def setUp(self):
        from candid import config as C
        _clean()
        self._orig_data_dir = C.DATA_DIR
        C.DATA_DIR = TEST_DIR
        _install_stub()
        PACKS.clear()
        PACKS.update(_fixture_packs())

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self._orig_data_dir
        _remove_stub()

    def _parse(self, argv):
        from candid import __main__ as M
        return M.build_parser().parse_args(argv)

    def test_import_parses(self):
        a = self._parse(["templates", "questions", "import", "acme-ds",
                         "--company", "Acme", "--dry-run"])
        self.assertEqual(a.qwhat, "import")
        self.assertEqual(a.pack, "acme-ds")
        self.assertEqual(a.company, "Acme")
        self.assertTrue(a.dry_run)
        self.assertTrue(callable(a.func))

    def test_list_parses(self):
        a = self._parse(["templates", "questions", "list",
                         "--company", "Acme", "--json"])
        self.assertEqual(a.qwhat, "list")
        self.assertEqual(a.company, "Acme")
        self.assertTrue(a.json)

    def test_list_json_end_to_end(self):
        from candid import question_packs as QP
        QP.import_pack("acme-ds", company="Acme")
        a = self._parse(["templates", "questions", "list", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["pack"], "acme-ds")

    def test_import_dry_run_end_to_end(self):
        a = self._parse(["templates", "questions", "import", "acme-ds",
                         "--company", "Acme", "--dry-run"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            a.func(a)
        out = buf.getvalue()
        self.assertIn("Dry run", out)
        self.assertIn("acme-ds", out)

    def test_expected_errors_registered(self):
        from candid import __main__ as M
        self.assertIn("TemplateError", M._EXPECTED_ERRORS)
        self.assertIn("QuestionPackError", M._EXPECTED_ERRORS)

    def test_template_error_is_friendly_not_traceback(self):
        # unknown pack -> TemplateError -> main() reports cleanly, exit 1
        from candid import __main__ as M
        with self.assertRaises(SystemExit) as cm:
            M.main(["templates", "questions", "import", "nope",
                    "--company", "Acme"])
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
