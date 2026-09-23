"""Accessibility structure tests for the candid dashboard HTML.

Parses candid/data/dashboard.html with stdlib html.parser (no browser, no
network) and asserts the document-skeleton accessibility contract:

* a "Skip to main content" link is the first element in <body> and targets
  #main-content
* exactly one h1 in the document, living in the header
* no skipped heading levels in document order
* header / main / footer landmarks are present, and main has id="main-content"
* every <section> has a heading, an aria-labelledby reference, and the
  referenced id belongs to a heading inside that section
"""
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "candid" / "data" / "dashboard.html"

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.parent = None

    def classes(self):
        return self.attrs.get("class", "").split()


class _TreeParser(HTMLParser):
    """Builds a minimal DOM tree from the dashboard markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", [])
        self._stack = [self.root]
        self.by_id = {}

    def _push(self, tag, attrs):
        node = _Node(tag, attrs)
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        if "id" in node.attrs:
            self.by_id[node.attrs["id"]] = node
        return node

    def handle_starttag(self, tag, attrs):
        node = self._push(tag, attrs)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._push(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break


def _walk(node, tag=None):
    """Yield node and descendants in document order (optionally filtered)."""
    if tag is None or node.tag == tag:
        yield node
    for child in node.children:
        yield from _walk(child, tag)


def _is_descendant(node, ancestor):
    cur = node.parent
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parent
    return False


class A11yStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = _TreeParser()
        parser.feed(DASHBOARD.read_text(encoding="utf-8"))
        cls.by_id = parser.by_id
        cls.body = next(_walk(parser.root, "body"))
        cls.header = next(_walk(parser.root, "header"))
        cls.main = next(_walk(parser.root, "main"))
        cls.footer = next(_walk(parser.root, "footer"))
        cls.sections = list(_walk(parser.root, "section"))

    # ------------------------------------------------------------------
    # skip link
    # ------------------------------------------------------------------
    def test_skip_link_is_first_element_in_body(self):
        first = self.body.children[0]
        self.assertEqual(first.tag, "a",
                         "first element in <body> should be the skip link")
        self.assertIn("skip-link", first.classes())
        self.assertEqual(first.attrs.get("href"), "#main-content")

    def test_skip_link_target_exists(self):
        self.assertIn("main-content", self.by_id)
        self.assertEqual(self.by_id["main-content"].tag, "main")

    # ------------------------------------------------------------------
    # landmarks
    # ------------------------------------------------------------------
    def test_landmarks_present(self):
        self.assertEqual(len(list(_walk(self.body, "header"))), 1)
        self.assertEqual(len(list(_walk(self.body, "main"))), 1)
        self.assertEqual(len(list(_walk(self.body, "footer"))), 1)

    def test_header_has_label(self):
        # native <header> already maps to role=banner; the aria-label names it
        self.assertTrue(self.header.attrs.get("aria-label"),
                        "header should carry an aria-label")

    def test_footer_is_contentinfo(self):
        role = self.footer.attrs.get("role")
        self.assertEqual(role, "contentinfo")

    # ------------------------------------------------------------------
    # heading hierarchy
    # ------------------------------------------------------------------
    def test_exactly_one_h1(self):
        h1s = list(_walk(self.body, "h1"))
        self.assertEqual(len(h1s), 1, "document must have exactly one h1")
        self.assertTrue(_is_descendant(h1s[0], self.header),
                        "the single h1 should live in the header")

    def test_no_skipped_heading_levels(self):
        prev = 0
        for node in _walk(self.body):
            if node.tag in HEADING_TAGS:
                level = int(node.tag[1])
                self.assertLessEqual(
                    level, prev + 1,
                    f"skipped heading level before <{node.tag}> in "
                    f"<{node.parent.tag}>")
                prev = level

    def test_each_section_has_exactly_one_h2(self):
        for sec in self.sections:
            h2s = [n for n in _walk(sec, "h2")]
            self.assertEqual(
                len(h2s), 1,
                f"section #{sec.attrs.get('id')} should have exactly one h2")

    # ------------------------------------------------------------------
    # labelled sections
    # ------------------------------------------------------------------
    def test_sections_have_headings_and_valid_labelling(self):
        self.assertGreater(len(self.sections), 0)
        for sec in self.sections:
            sid = sec.attrs.get("id")
            headings = [n for n in _walk(sec) if n.tag in HEADING_TAGS]
            self.assertGreater(
                len(headings), 0, f"section #{sid} has no heading")
            labelledby = sec.attrs.get("aria-labelledby")
            self.assertIsNotNone(
                labelledby, f"section #{sid} is missing aria-labelledby")
            target = self.by_id.get(labelledby)
            self.assertIsNotNone(
                target,
                f"section #{sid} aria-labelledby={labelledby!r} "
                "does not match any element id")
            self.assertIn(
                target.tag, HEADING_TAGS,
                f"section #{sid} aria-labelledby must point at a heading")
            self.assertTrue(
                _is_descendant(target, sec),
                f"section #{sid} aria-labelledby target is not inside "
                "the section")


if __name__ == "__main__":
    unittest.main()
