"""Accessibility tests for dashboard components and forms (features 8-9).

Feature 8: status is never conveyed by color alone - pills, score badges and
keyword chips all carry a text label and a non-color cue.
Feature 9: accessible tables, charts, and forms - caption/scope/aria-sort on
tables, a text alternative for the funnel chart, labels on every form control,
role="alert" on error outputs.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "candid" / "data" / "dashboard.html"


def read_html():
    return HTML.read_text(encoding="utf-8")


def templates_with(src, needle):
    """Return source lines that render the given component (static or JS)."""
    return [ln for ln in src.splitlines() if needle in ln]


class TestColorIndependentStatus(unittest.TestCase):
    def test_pill_templates_have_text_label(self):
        src = read_html()
        pills = templates_with(src, 'class="pill')
        self.assertTrue(pills, "no pill template found in dashboard.html")
        for ln in pills:
            self.assertIn("pretty(", ln,
                          "pill template must render a text status label, not color alone")
            self.assertIn("aria-label", ln,
                          "pill template should expose an accessible status name")

    def test_pill_has_noncolor_glyph(self):
        src = read_html()
        self.assertRegex(src, r'class="pill[^>]*aria-label[^>]*>.*aria-hidden="true"',
                         "pill template should include a non-color shape cue")

    def test_scorebadge_templates_have_text_label(self):
        src = read_html()
        badges = templates_with(src, 'class="scorebadge')
        self.assertTrue(badges, "no scorebadge template found")
        for ln in badges:
            self.assertIn("/100", ln, "score badge must show the numeric score text")
            self.assertIn("aria-label", ln,
                          "score badge must name its tier (high/medium/low) in text")

    def test_kwchip_templates_have_text_and_cue(self):
        src = read_html()
        chips = templates_with(src, 'class="kwchip')
        self.assertTrue(chips, "no kwchip template found")
        for ln in chips:
            self.assertIn("aria-label", ln,
                          "kwchip must name covered/missing status for screen readers")
            self.assertTrue("\u2713" in ln or "\u2717" in ln,
                            "kwchip must use a non-color glyph cue in addition to color")

    def test_no_icon_only_status(self):
        src = read_html()
        # icon-only check/cross without any text alternative would fail
        for ln in templates_with(src, 'class="kwchip'):
            self.assertIn("aria-label", ln)


class TestAccessibleTables(unittest.TestCase):
    def test_every_table_has_caption(self):
        src = read_html()
        for m in re.finditer(r"<table[^>]*>", src):
            after = src[m.end():]
            cap = after.find("<caption")
            end = after.find("</table>")
            self.assertNotEqual(cap, -1, "table is missing a <caption>")
            if end != -1:
                self.assertLess(cap, end, "<caption> must be inside the table")

    def test_th_have_scope(self):
        src = read_html()
        ths = re.findall(r"<th(?![a-z])[^>]*>", src)
        self.assertTrue(ths, "no th elements found")
        for th in ths:
            self.assertIn('scope="', th, f"th missing scope: {th}")

    def test_sortable_th_expose_aria_sort(self):
        src = read_html()
        self.assertIn("aria-sort", src,
                      "sortable table headers must expose aria-sort")


class TestFunnelTextAlternative(unittest.TestCase):
    def test_funnel_has_text_alternative(self):
        src = read_html()
        funnel_region = src[src.find("funnelBars"):src.find("loadNudges")]
        has_table = "<table" in funnel_region and "<caption" in funnel_region
        has_describedby = "aria-describedby" in funnel_region
        self.assertTrue(has_table or has_describedby,
                        "funnel chart needs a text alternative (hidden data table "
                        "or aria-describedby summary)")
        if has_table:
            self.assertIn('scope="row"', funnel_region,
                          "hidden funnel table should label each stage row")


class TestFormLabels(unittest.TestCase):
    def test_every_static_control_has_label(self):
        src = read_html()
        # strip the <script> block so JS template strings do not confuse matching
        static = re.sub(r"<script>.*</script>", "", src, flags=re.S)
        ids = re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', static)
        self.assertTrue(ids, "no form controls found")
        for cid in ids:
            labelled = (f'<label for="{cid}"' in static or
                        f"<label for='{cid}'" in static)
            wrapped = re.search(
                r"<label[^>]*>(?:(?!</label>).)*<"
                r"(?:input|select|textarea)[^>]*id=\"" + re.escape(cid) + r"\"",
                static, flags=re.S)
            self.assertTrue(labelled or wrapped,
                            f"form control #{cid} has no associated <label>")

    def test_dynamic_status_select_has_accessible_name(self):
        src = read_html()
        self.assertRegex(src, r'class="stSel"[^>]*aria-label=',
                         "per-row status <select> is rendered from a JS template "
                         "and must carry an aria-label")

    def test_required_fields_marked(self):
        src = read_html()
        self.assertIn('aria-required="true"', src,
                      "required inputs must set aria-required")
        self.assertIn("(required)", src,
                      "required inputs must show visible '(required)' text, "
                      "not color alone")

    def test_error_outputs_have_role_alert(self):
        src = read_html()
        errs = templates_with(src, 'class="err"')
        self.assertTrue(errs, "no .err error outputs found")
        for ln in errs:
            self.assertIn('role="alert"', ln,
                          "error outputs must have role=\"alert\"")


if __name__ == "__main__":
    unittest.main()
