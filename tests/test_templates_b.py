"""Tests for the `candid templates` CLI (batch 106, worker B).

The real engine (candid/templates.py, worker A) may not exist in this checkout,
so every test stubs it: a fake module is injected into sys.modules as
"candid.templates" implementing the agreed contract:

    TemplateError(Exception); PACK_KINDS
    list_packs(kind=None) -> [manifest dicts]
    get_pack(name) -> {"manifest": ..., "templates": [names]}
    render_template(pack_name, template_name, variables) -> str
    validate_pack(path) -> {"ok": bool, "issues": [str]}

Run targeted: CANDID_DATA_DIR=/tmp/candid-test-tpl-b python3 -m unittest tests.test_templates_b
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import candid  # noqa: E402
from candid import __main__ as CLI  # noqa: E402
from candid import templates_cli as TC  # noqa: E402

MANIFESTS = {
    "networking-pack": {
        "name": "networking-pack", "version": "1.0",
        "kind": "outreach", "title": "Networking outreach",
        "description": "Cold emails and referral requests.",
    },
    "cover-pack": {
        "name": "cover-pack", "version": "2.1",
        "kind": "cover-letter", "title": "Cover letters",
        "description": "Formal cover letter templates.",
    },
}

TEMPLATES = {
    "networking-pack": ["cold-email", "referral-ask"],
    "cover-pack": ["formal-cover"],
}

BODIES = {
    ("networking-pack", "cold-email"): "Hi {{name}},\nSaw {{company}} is hiring.\n",
    ("networking-pack", "referral-ask"): "Hi {{name}}, could you refer me to {{company}}?\n",
    ("cover-pack", "formal-cover"): "Dear {{hiring_manager}},\nI am {{name}}.\n",
}


def _make_stub(calls):
    stub = types.ModuleType("candid.templates")

    class TemplateError(Exception):
        pass

    stub.TemplateError = TemplateError
    stub.PACK_KINDS = ("cover-letter", "outreach", "questions")

    def list_packs(kind=None):
        calls.append(("list_packs", kind))
        packs = list(MANIFESTS.values())
        if kind:
            packs = [p for p in packs if p["kind"] == kind]
        return packs

    def get_pack(name):
        if name not in MANIFESTS:
            raise TemplateError(f"No pack '{name}'.")
        return {"manifest": MANIFESTS[name], "templates": TEMPLATES[name]}

    def render_template(pack_name, template_name, variables):
        body = BODIES.get((pack_name, template_name))
        if body is None:
            raise TemplateError(f"No template '{template_name}' in '{pack_name}'.")
        out = body
        for k, v in variables.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out

    def validate_pack(path):
        if str(path).endswith("good-pack"):
            return {"ok": True, "issues": []}
        return {"ok": False, "issues": ["manifest.json is missing",
                                       "template body is empty"]}

    stub.list_packs = list_packs
    stub.get_pack = get_pack
    stub.render_template = render_template
    stub.validate_pack = validate_pack
    return stub


class StubMixin:
    def setUp(self):
        self.calls = []
        self._stub = _make_stub(self.calls)
        self._saved_module = sys.modules.get("candid.templates")
        self._saved_attr = getattr(candid, "templates", None)
        self._had_attr = hasattr(candid, "templates")
        sys.modules["candid.templates"] = self._stub
        candid.templates = self._stub

    def tearDown(self):
        if self._saved_module is not None:
            sys.modules["candid.templates"] = self._saved_module
        else:
            sys.modules.pop("candid.templates", None)
        if self._had_attr:
            candid.templates = self._saved_attr
        elif hasattr(candid, "templates"):
            delattr(candid, "templates")


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


class ListTest(StubMixin, unittest.TestCase):
    def test_list_text(self):
        out = _capture(TC.list_packs)
        self.assertIn("networking-pack", out)
        self.assertIn("cover-pack", out)
        self.assertIn("outreach", out)
        self.assertIn("v1.0", out)

    def test_list_json_is_valid(self):
        out = _capture(TC.list_packs, as_json=True)
        data = json.loads(out)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "networking-pack")

    def test_list_kind_passthrough(self):
        out = _capture(TC.list_packs, kind="outreach")
        self.assertEqual(self.calls, [("list_packs", "outreach")])
        self.assertIn("networking-pack", out)
        self.assertNotIn("cover-pack", out)

    def test_list_empty(self):
        self._stub.list_packs = lambda kind=None: []
        out = _capture(TC.list_packs)
        self.assertIn("No template packs installed", out)


class ShowTest(StubMixin, unittest.TestCase):
    def test_show_pack(self):
        out = _capture(TC.show_pack, "networking-pack")
        self.assertIn("networking-pack", out)
        self.assertIn("cold-email", out)
        self.assertIn("referral-ask", out)
        self.assertIn("outreach", out)

    def test_show_template_highlights_vars(self):
        out = _capture(TC.show_pack, "networking-pack", template="cold-email")
        self.assertIn("\033[1m{{name}}\033[0m", out)
        self.assertIn("\033[1m{{company}}\033[0m", out)
        self.assertIn("Variables: name, company", out)

    def test_show_unknown_template(self):
        with self.assertRaises(self._stub.TemplateError):
            TC.show_pack("networking-pack", template="nope")

    def test_show_unknown_pack(self):
        with self.assertRaises(self._stub.TemplateError):
            TC.show_pack("nope-pack")


class UseTest(StubMixin, unittest.TestCase):
    def test_use_stdout(self):
        out = _capture(TC.use_template, "networking-pack", "cold-email",
                       ["name=Jane Doe"], None, None)
        self.assertIn("Hi Jane Doe,", out)
        self.assertIn("{{company}}", out)  # unfilled var stays visible

    def test_use_vars_json_and_out_file(self):
        with tempfile.TemporaryDirectory() as td:
            vars_file = Path(td) / "vars.json"
            vars_file.write_text(json.dumps({"name": "Sam", "company": "Acme"}))
            out_file = Path(td) / "email.txt"
            printed = _capture(TC.use_template, "networking-pack", "cold-email",
                               ["name=Override"], str(vars_file), str(out_file))
            self.assertIn("Saved to", printed)
            body = out_file.read_text()
            # --var wins over --vars-json; json fills the rest
            self.assertIn("Hi Override,", body)
            self.assertIn("Saw Acme is hiring.", body)

    def test_use_bad_var_format(self):
        with self.assertRaises(self._stub.TemplateError):
            TC.use_template("networking-pack", "cold-email", ["novalue"], None, None)

    def test_use_bad_vars_json_not_object(self):
        with tempfile.TemporaryDirectory() as td:
            vars_file = Path(td) / "vars.json"
            vars_file.write_text(json.dumps(["not", "an", "object"]))
            with self.assertRaises(self._stub.TemplateError):
                TC.use_template("networking-pack", "cold-email", [],
                                str(vars_file), None)


class SearchTest(StubMixin, unittest.TestCase):
    def test_search_matches_description(self):
        out = _capture(TC.search_packs, "referral")
        self.assertIn("networking-pack", out)

    def test_search_matches_template_name(self):
        out = _capture(TC.search_packs, "cold-email")
        self.assertIn("networking-pack", out)
        self.assertIn("cold-email", out)

    def test_search_json_is_valid(self):
        out = _capture(TC.search_packs, "cover", as_json=True)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["manifest"]["name"], "cover-pack")

    def test_search_no_match(self):
        out = _capture(TC.search_packs, "zzz-no-match")
        self.assertIn("No template packs match", out)


class ValidateTest(StubMixin, unittest.TestCase):
    def test_validate_ok(self):
        out = _capture(TC.validate_pack, "/tmp/good-pack")
        self.assertIn("valid", out)

    def test_validate_bad_raises(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(self._stub.TemplateError):
                TC.validate_pack("/tmp/bad-pack")
        self.assertIn("manifest.json is missing", buf.getvalue())


class GalleryTest(StubMixin, unittest.TestCase):
    def _pack_dir(self, td):
        packs = Path(td) / "packs"
        a = packs / "builtin-a"
        a.mkdir(parents=True)
        (a / "manifest.json").write_text(json.dumps(
            {"name": "builtin-a", "version": "0.3", "kind": "questions",
             "description": "Built-in interview questions."}))
        (packs / "builtin-b").mkdir(parents=True)  # no manifest: name-only
        return packs

    def test_gallery_empty(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["CANDID_PACKS_DIR"] = td  # empty dir
            try:
                out = _capture(TC.gallery)
            finally:
                del os.environ["CANDID_PACKS_DIR"]
        self.assertIn("gallery is empty", out)
        self.assertNotIn("Traceback", out)

    def test_gallery_missing_dir(self):
        os.environ["CANDID_PACKS_DIR"] = "/nonexistent/packs-dir-xyz"
        try:
            out = _capture(TC.gallery)
        finally:
            del os.environ["CANDID_PACKS_DIR"]
        self.assertIn("gallery is empty", out)

    def test_gallery_marks_installed(self):
        with tempfile.TemporaryDirectory() as td:
            packs = self._pack_dir(td)
            # pretend builtin-a is installed via the engine
            self._stub.list_packs = lambda kind=None: [
                {**MANIFESTS["networking-pack"], "name": "builtin-a"}]
            os.environ["CANDID_PACKS_DIR"] = str(packs)
            try:
                out = _capture(TC.gallery)
            finally:
                del os.environ["CANDID_PACKS_DIR"]
        self.assertIn("builtin-a [installed]", out)
        self.assertIn("builtin-b [not installed]", out)

    def test_gallery_kind_filter(self):
        with tempfile.TemporaryDirectory() as td:
            packs = self._pack_dir(td)
            os.environ["CANDID_PACKS_DIR"] = str(packs)
            try:
                out = _capture(TC.gallery, kind="questions")
            finally:
                del os.environ["CANDID_PACKS_DIR"]
        self.assertIn("builtin-a", out)
        self.assertNotIn("builtin-b", out)


class _BlockTemplatesImport:
    """Meta-path blocker so tests can simulate a missing gallery module."""

    def find_spec(self, name, path=None, target=None):
        if name == "candid.templates":
            raise ImportError("candid.templates blocked for test")
        return None

class EngineMissingTest(unittest.TestCase):
    def test_require_templates_raises_clear_error(self):
        saved_mod = sys.modules.pop("candid.templates", None)
        saved_attr = getattr(candid, "templates", None)
        if hasattr(candid, "templates"):
            delattr(candid, "templates")
        blocker = _BlockTemplatesImport()
        sys.meta_path.insert(0, blocker)
        try:
            with self.assertRaises(TC.TemplatesUnavailableError) as ctx:
                TC._require_templates()
            self.assertIn("candid/templates.py", str(ctx.exception))
        finally:
            sys.meta_path.remove(blocker)
            if saved_mod is not None:
                sys.modules["candid.templates"] = saved_mod
            if saved_attr is not None:
                candid.templates = saved_attr


class CLIWiringTest(StubMixin, unittest.TestCase):
    def test_command_registered(self):
        self.assertIn("templates", CLI.COMMANDS)
        # Other batch-106 workers add their own subcommands (questions, pack);
        # this worker's six must all be present.
        for sub in ["list", "show", "use", "gallery", "search", "validate"]:
            self.assertIn(sub, CLI.SUBCOMMANDS["templates"])
        self.assertIn("TemplateError", CLI._EXPECTED_ERRORS)

    def test_parser_routes_to_cmd_templates(self):
        args = CLI.build_parser().parse_args(["templates", "list", "--json"])
        self.assertIs(args.func, CLI.cmd_templates)
        self.assertEqual(args.what, "list")
        self.assertTrue(args.json)

    def test_parser_use_args(self):
        args = CLI.build_parser().parse_args(
            ["templates", "use", "p", "t", "--var", "a=1", "--var", "b=2"])
        self.assertEqual(args.var, ["a=1", "b=2"])
        self.assertIsNone(args.vars_json)
        self.assertIsNone(args.out)

    def test_end_to_end_list_json(self):
        args = CLI.build_parser().parse_args(["templates", "list", "--json"])
        out = _capture(args.func, args)
        data = json.loads(out)
        self.assertEqual(len(data), 2)


if __name__ == "__main__":
    unittest.main()
