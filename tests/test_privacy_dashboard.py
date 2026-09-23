"""Tests for candid.privacy_dashboard (privacy tab HTML fragment).

Test isolation: CANDID_DATA_DIR / CANDID_CONFIG_DIR are set before candid
is imported, and setUp/tearDown additionally redirect candid.config.DATA_DIR
(same approach as tests/test_dashboard.py), so these tests are independent
of import order.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privdash"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privdash-config"

from candid import config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_dashboard as pd  # noqa: E402


class PrivacyDashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-privdash-"))
        self._saved_data_dir = C.DATA_DIR
        C.DATA_DIR = self.tmp

    def tearDown(self):
        C.DATA_DIR = self._saved_data_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_string_containing_privacy(self):
        html = pd.privacy_tab_html()
        self.assertIsInstance(html, str)
        self.assertIn("Privacy", html)

    def test_lists_category_names(self):
        html = pd.privacy_tab_html()
        self.assertIn("profile", html)
        self.assertIn("tracker", html)
        self.assertIn("Application tracker", html)

    def test_shows_totals_and_table(self):
        (self.tmp / "tracker.json").write_text(
            '{"applications": [{"company": "Acme"}, {"company": "Beta"}]}',
            encoding="utf-8",
        )
        html = pd.privacy_tab_html()
        self.assertIn("data held", html)
        self.assertIn("files", html)
        self.assertIn("<table>", html)
        # two records counted for the tracker category
        self.assertIn(">2<", html)

    def test_escapes_html_in_labels(self):
        evil = {"label": '<script>alert("x") & y</script>',
                "paths": [], "kind": "dir"}
        saved = P.CATEGORIES.get("evil")
        P.CATEGORIES["evil"] = evil
        try:
            html = pd.privacy_tab_html()
        finally:
            if saved is None:
                del P.CATEGORIES["evil"]
            else:
                P.CATEGORIES["evil"] = saved
        self.assertNotIn('<script>alert("x") & y</script>', html)
        self.assertIn(
            "&lt;script&gt;alert(&quot;x&quot;) &amp; y&lt;/script&gt;", html
        )

    def test_includes_action_links(self):
        html = pd.privacy_tab_html()
        self.assertIn("/privacy?action=scan", html)
        self.assertIn("/privacy?action=export", html)
        self.assertIn("/privacy?action=nuke", html)
        # per-category links carry the category as a query param
        self.assertIn("action=export", html)
        self.assertIn("category=tracker", html)
        self.assertIn("action=purge", html)
        self.assertIn("category=profile", html)


if __name__ == "__main__":
    unittest.main()
