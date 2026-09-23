"""Tests for candid.docs_export (offline docs export).

Everything here runs against fixture topics or monkeypatched data; the real
docs bundle is never required. The packaging test uses
``pytest.importorskip("candid.docs_bundle")`` because the bundle module is
owned by a sibling worker and may not exist yet on this branch.
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SAMPLE_TOPICS = [
    (
        "Getting Started",
        "# Getting Started\n\n"
        "Welcome to **candid**.\n\n"
        "- Install it\n"
        "- Run `python -m candid --help`\n\n"
        "See [the website](https://example.com/docs) for more.\n",
    ),
    (
        "FAQ",
        "# FAQ\n\n"
        "## Is it free?\n\n"
        "Yes. Everything runs locally.\n\n"
        "```bash\npython -m candid match --help\n```\n\n"
        "![diagram](https://example.com/diagram.png)\n",
    ),
]

SRC_HREF_RE = re.compile(r'''(?:src|href)\s*=\s*["']([^"']*)["']''', re.IGNORECASE)


class DeferredImportTest(unittest.TestCase):
    def test_module_imports_without_docs_bundle(self):
        sys.modules.pop("candid.docs_bundle", None)
        import importlib

        import candid.docs_export as DX

        importlib.reload(DX)
        self.assertNotIn("candid.docs_bundle", sys.modules)


class ExportTxtTest(unittest.TestCase):
    def test_export_txt_contains_all_topics(self):
        from candid import docs_export as DX

        with tempfile.TemporaryDirectory() as td:
            out = DX.export_txt(Path(td) / "docs.txt", topics=SAMPLE_TOPICS,
                                generated_at="2026-09-22")
            self.assertTrue(out.is_file())
            text = out.read_text(encoding="utf-8")
        # title page
        self.assertIn("candid", text)
        self.assertIn("Docs version", text)
        self.assertIn("2026-09-22", text)
        # table of contents lists every topic
        for title, _md in SAMPLE_TOPICS:
            self.assertIn(title, text)
        # every topic's content is rendered as plain text (no markdown)
        self.assertIn("Welcome to candid.", text)
        self.assertIn("Is it free?", text)
        self.assertNotIn("**", text)
        self.assertNotIn("# Getting Started", text)
        # absolute links degrade to text + url
        self.assertIn("the website (https://example.com/docs)", text)
        # code blocks survive without fences
        self.assertIn("python -m candid match --help", text)
        self.assertNotIn("```", text)

    def test_export_txt_returns_path_and_creates_parents(self):
        from candid import docs_export as DX

        with tempfile.TemporaryDirectory() as td:
            out = DX.export_txt(Path(td) / "sub" / "docs.txt", topics=SAMPLE_TOPICS)
            self.assertTrue(out.is_file())
            self.assertEqual(out, Path(td) / "sub" / "docs.txt")

    def test_markdown_to_text_minimal(self):
        from candid import docs_export as DX

        self.assertEqual(DX.markdown_to_text("# Hello\n\nWorld"), "Hello\n=====\n\nWorld")
        self.assertEqual(DX.markdown_to_text("- a\n- b"), "  - a\n  - b")


class ExportHtmlTest(unittest.TestCase):
    def test_export_html_no_external_references(self):
        from candid import docs_export as DX

        with tempfile.TemporaryDirectory() as td:
            out = DX.export_html(Path(td) / "docs.html", topics=SAMPLE_TOPICS,
                                 generated_at="2026-09-22")
            self.assertTrue(out.is_file())
            page = out.read_text(encoding="utf-8")
        # no external resources: no src/href with http(s)
        for attr in SRC_HREF_RE.findall(page):
            self.assertFalse(
                attr.startswith(("http://", "https://")),
                f"external reference leaked into src/href: {attr}",
            )
        # no external stylesheets / scripts / images / fonts at all
        self.assertNotIn("<link", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("url(http", page)
        # still self-contained: embedded style block present
        self.assertIn("<style>", page)
        # TOC with anchor links to every topic
        self.assertIn('class="toc"', page)
        for i, (title, _md) in enumerate(SAMPLE_TOPICS):
            slug = DX._slugify(title)
            self.assertIn(f'id="{slug}"', page)
            self.assertIn(f'href="#{slug}"', page)
        # markdown rendered: headings, lists, code, links
        self.assertIn("<h2>Getting Started</h2>", page)
        self.assertIn("<ul>", page)
        self.assertIn("<li>", page)
        self.assertIn("<pre><code", page)
        self.assertIn("<strong>candid</strong>", page)
        # absolute link does not become an external anchor
        self.assertNotIn('href="https://example.com', page)
        self.assertIn("the website (https://example.com/docs)", page)
        # image degrades to alt text, no <img>
        self.assertIn("diagram", page)

    def test_export_html_returns_path(self):
        from candid import docs_export as DX

        with tempfile.TemporaryDirectory() as td:
            out = DX.export_html(Path(td) / "docs.html", topics=SAMPLE_TOPICS)
            self.assertTrue(out.is_file())

    def test_unique_slugs_for_duplicate_titles(self):
        from candid import docs_export as DX

        slugs = DX._unique_slugs(["Intro", "Intro", "Intro"])
        self.assertEqual(len(set(slugs)), 3)


class LoadTopicsTest(unittest.TestCase):
    def test_load_topics_uses_monkeypatched_bundle(self):
        # docs_bundle is sibling-owned; simulate it with fixture data.
        import types

        import candid
        from candid import docs_export as DX

        fake = types.SimpleNamespace(DOCS_DIR=Path("/nonexistent"))
        old_mod = sys.modules.get("candid.docs_bundle")
        had_attr = hasattr(candid, "docs_bundle")
        old_attr = getattr(candid, "docs_bundle", None)
        sys.modules["candid.docs_bundle"] = fake
        candid.docs_bundle = fake
        try:
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / "b.md").write_text("# Bee\n\nbody b", encoding="utf-8")
                (Path(td) / "a.md").write_text("# Aye\n\nbody a", encoding="utf-8")
                fake.DOCS_DIR = Path(td)
                topics = DX.load_topics()
            self.assertEqual([t for t, _m in topics], ["Aye", "Bee"])
            self.assertIn("body a", topics[0][1])
        finally:
            if old_mod is not None:
                sys.modules["candid.docs_bundle"] = old_mod
            else:
                sys.modules.pop("candid.docs_bundle", None)
            if had_attr:
                candid.docs_bundle = old_attr


class ManifestTest(unittest.TestCase):
    def test_manifest_includes_docs(self):
        manifest = ROOT / "MANIFEST.in"
        self.assertTrue(manifest.is_file(), "MANIFEST.in missing")
        text = manifest.read_text(encoding="utf-8")
        self.assertIn("candid/data/docs", text)
        self.assertIn("docs/", text)


class PackagingTest(unittest.TestCase):
    def test_docs_bundle_ships_inside_package(self):
        # Every file under candid/data/docs/ must live inside the installed
        # package directory, reachable offline via candid.docs_bundle.DOCS_DIR.
        import pytest

        docs_bundle = pytest.importorskip("candid.docs_bundle")
        import candid

        pkg_dir = Path(candid.__file__).resolve().parent
        docs_dir = Path(docs_bundle.DOCS_DIR).resolve()
        self.assertFalse(
            str(docs_dir).startswith(("http://", "https://")),
            "DOCS_DIR must be a local path, not a network path",
        )
        self.assertTrue(docs_dir.is_dir(), f"DOCS_DIR missing: {docs_dir}")
        self.assertTrue(
            docs_dir == pkg_dir / "data" / "docs"
            or docs_dir.is_relative_to(pkg_dir),
            f"docs live outside the installed package: {docs_dir}",
        )
        files = [p for p in docs_dir.rglob("*") if p.is_file()]
        self.assertTrue(files, "no doc files shipped in DOCS_DIR")


if __name__ == "__main__":
    unittest.main()
