"""Tests for worker D template packs (candid batch 106, template gallery).

Packs covered: cover-letter-tones, outreach-starter, interview-questions-starter.

Verifies: every pack dir has a valid manifest.json (required keys, name
matches dir, semver versions, valid kind, well-formed variables), every
{{variable}} placeholder used in templates is declared in its manifest and
every required variable is used, every question block in the questions pack
carries a Source: https link, and all files are non-empty UTF-8 with no
em dashes.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = ROOT / "candid" / "data" / "packs"

# Packs owned by worker D (slug -> expected kind).
PACKS = {
    "cover-letter-tones": "cover-letter",
    "outreach-starter": "outreach",
    "interview-questions-starter": "questions",
}

REQUIRED_MANIFEST_KEYS = {
    "name", "title", "version", "kind", "author",
    "description", "variables", "min_candid_version",
}
VALID_KINDS = {"cover-letter", "outreach", "questions"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
QUESTION_HEADING_RE = re.compile(r"^##\s+\d+\.", re.MULTILINE)
HTTPS_URL_RE = re.compile(r"^https://\S+$")
EM_DASH = "\u2014"


def _load_manifest(slug):
    with open(PACKS_DIR / slug / "manifest.json", encoding="utf-8") as f:
        return json.load(f)


def _templates(slug):
    return sorted((PACKS_DIR / slug / "templates").glob("*.md"))


def _pack_files(slug):
    return [PACKS_DIR / slug / "manifest.json"] + _templates(slug)


class TestPackManifests(unittest.TestCase):
    def test_pack_dirs_and_templates_exist(self):
        for slug in PACKS:
            d = PACKS_DIR / slug
            self.assertTrue(d.is_dir(), f"missing pack dir {d}")
            self.assertTrue((d / "manifest.json").is_file(),
                            f"{slug} missing manifest.json")
            self.assertGreater(len(_templates(slug)), 0,
                               f"{slug} has no templates")

    def test_template_counts(self):
        self.assertEqual(len(_templates("cover-letter-tones")), 4)
        self.assertEqual(len(_templates("outreach-starter")), 5)
        self.assertEqual(len(_templates("interview-questions-starter")), 2)

    def test_manifest_required_keys(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                missing = REQUIRED_MANIFEST_KEYS - set(_load_manifest(slug))
                self.assertFalse(missing, f"{slug} missing keys: {missing}")

    def test_manifest_name_matches_dir(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                self.assertEqual(_load_manifest(slug)["name"], slug)

    def test_manifest_versions_are_semver(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                m = _load_manifest(slug)
                self.assertRegex(m["version"], SEMVER_RE)
                self.assertRegex(m["min_candid_version"], SEMVER_RE)

    def test_manifest_kind_valid_and_expected(self):
        for slug, expected in PACKS.items():
            with self.subTest(pack=slug):
                kind = _load_manifest(slug)["kind"]
                self.assertIn(kind, VALID_KINDS)
                self.assertEqual(kind, expected)

    def test_manifest_text_fields_nonempty(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                m = _load_manifest(slug)
                for key in ("title", "author", "description"):
                    self.assertTrue(str(m[key]).strip(), f"{slug}.{key} empty")

    def test_manifest_variables_well_formed(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                variables = _load_manifest(slug)["variables"]
                self.assertIsInstance(variables, list)
                self.assertGreater(len(variables), 0)
                names = []
                for v in variables:
                    self.assertIn("name", v)
                    self.assertIn("description", v)
                    self.assertIn("required", v)
                    self.assertIsInstance(v["required"], bool)
                    self.assertTrue(str(v["description"]).strip())
                    names.append(v["name"])
                self.assertEqual(len(names), len(set(names)),
                                 f"{slug} has duplicate variable names")


class TestPlaceholders(unittest.TestCase):
    def test_no_undeclared_placeholders(self):
        for slug in PACKS:
            declared = {v["name"] for v in _load_manifest(slug)["variables"]}
            for tpl in _templates(slug):
                with self.subTest(pack=slug, template=tpl.name):
                    used = set(PLACEHOLDER_RE.findall(
                        tpl.read_text(encoding="utf-8")))
                    undeclared = used - declared
                    self.assertFalse(
                        undeclared,
                        f"{slug}/{tpl.name} uses undeclared vars: "
                        f"{sorted(undeclared)}")

    def test_required_variables_are_used(self):
        for slug in PACKS:
            with self.subTest(pack=slug):
                manifest = _load_manifest(slug)
                required = {v["name"] for v in manifest["variables"]
                            if v["required"]}
                used = set()
                for tpl in _templates(slug):
                    used |= set(PLACEHOLDER_RE.findall(
                        tpl.read_text(encoding="utf-8")))
                self.assertFalse(required - used,
                                 f"{slug} required vars never used: "
                                 f"{sorted(required - used)}")


class TestQuestionsPack(unittest.TestCase):
    def test_every_question_has_source_line(self):
        slug = "interview-questions-starter"
        self.assertEqual(_load_manifest(slug)["kind"], "questions")
        for tpl in _templates(slug):
            text = tpl.read_text(encoding="utf-8")
            blocks = QUESTION_HEADING_RE.split(text)
            # blocks[0] is the intro; the rest are question blocks.
            self.assertGreaterEqual(len(blocks) - 1, 8,
                                    f"{tpl.name} should have ~8 questions")
            for i, block in enumerate(blocks[1:], start=1):
                with self.subTest(template=tpl.name, question=i):
                    sources = [ln for ln in block.splitlines()
                               if ln.strip().startswith("Source:")]
                    self.assertGreater(len(sources), 0,
                                       f"{tpl.name} question {i} missing "
                                       "Source: line")
                    for src in sources:
                        url = src.split("Source:", 1)[1].strip()
                        self.assertRegex(
                            url, HTTPS_URL_RE,
                            f"{tpl.name} question {i} bad Source URL: {url}")


class TestFileHygiene(unittest.TestCase):
    def test_files_nonempty_utf8(self):
        for slug in PACKS:
            for path in _pack_files(slug):
                with self.subTest(file=str(path.relative_to(ROOT))):
                    raw = path.read_bytes()
                    self.assertGreater(len(raw), 0, "empty file")
                    raw.decode("utf-8")  # raises on invalid UTF-8

    def test_no_em_dashes(self):
        for slug in PACKS:
            for path in _pack_files(slug):
                with self.subTest(file=str(path.relative_to(ROOT))):
                    self.assertNotIn(EM_DASH,
                                     path.read_text(encoding="utf-8"),
                                     "em dash found; use hyphens or commas")


if __name__ == "__main__":
    unittest.main()
