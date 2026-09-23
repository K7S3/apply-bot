"""Accessibility tests for the candid dashboard stylesheet.

CSS layer only: parses the <style> block out of candid/data/dashboard.html
and re-checks the WCAG 2.1 AA contrast audit, the :focus-visible rules,
and the reduced-motion support. Pure Python, no dependencies.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "candid" / "data" / "dashboard.html"


# ---------------------------------------------------------------------------
# WCAG relative luminance / contrast helpers
# ---------------------------------------------------------------------------

def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast_ratio(fg, bg):
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------

def style_block():
    html = HTML.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "no <style> block found in dashboard.html"
    return m.group(1)


def root_vars(css):
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert m, "no :root block found"
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})", m.group(1)))


def resolve(color, vars_):
    m = re.fullmatch(r"var\(--([\w-]+)\)", color.strip())
    return "#" + vars_[m.group(1)] if m else color


def rule_colors(css, selector):
    """Return (color, background) for the rule at selector.

    Rules that declare no color inherit the body text color, so fall
    back to var(--text) in that case.
    """
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no CSS rule found for selector {selector}"
    body = m.group(1)
    color = re.search(r"(?<![\w-])color\s*:\s*(#[0-9a-fA-F]{3,6}|var\(--[\w-]+\))", body)
    bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6}|var\(--[\w-]+\))", body)
    assert bg, f"rule {selector} must declare a background"
    return (color.group(1) if color else "var(--text)"), bg.group(1)


class CSSTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = style_block()
        cls.vars = root_vars(cls.css)

    def assert_contrast(self, name, fg, bg, minimum):
        fg_hex, bg_hex = resolve(fg, self.vars), resolve(bg, self.vars)
        ratio = contrast_ratio(fg_hex, bg_hex)
        self.assertGreaterEqual(
            ratio, minimum,
            f"{name}: {fg_hex} on {bg_hex} = {ratio:.2f}:1, need >={minimum}:1")


# ---------------------------------------------------------------------------
# 1. contrast: normal text 4.5:1, large text / UI boundaries 3:1
# ---------------------------------------------------------------------------

class ContrastTest(CSSTestBase):
    # (name, foreground, background, minimum ratio)
    TEXT_PAIRS = [
        ("body text", "var(--text)", "var(--bg)", 4.5),
        ("muted on page bg", "var(--muted)", "var(--bg)", 4.5),
        ("muted on panel", "var(--muted)", "var(--panel)", 4.5),
        ("muted on panel2", "var(--muted)", "var(--panel2)", 4.5),
        ("accent link on page bg", "var(--accent)", "var(--bg)", 4.5),
        ("accent link on panel", "var(--accent)", "var(--panel)", 4.5),
        ("accent link on panel2", "var(--accent)", "var(--panel2)", 4.5),
        ("green on panel", "var(--green)", "var(--panel)", 4.5),
        ("green on panel2", "var(--green)", "var(--panel2)", 4.5),
        ("amber on panel", "var(--amber)", "var(--panel)", 4.5),
        ("amber on panel2", "var(--amber)", "var(--panel2)", 4.5),
        ("red on panel", "var(--red)", "var(--panel)", 4.5),
        ("red on panel2", "var(--red)", "var(--panel2)", 4.5),
        ("button text on accent", "#06101f", "var(--accent)", 4.5),
        ("chip.active text on accent", "#06101f", "var(--accent)", 4.5),
        ("placeholder on panel2", "var(--muted)", "var(--panel2)", 4.5),
    ]
    # pill / badge / score classes declare literal hex colors; read them
    # from the rules so the test tracks the stylesheet, not a copy of it.
    PILL_SELECTORS = [".saved", ".applied", ".selected_for_interview",
                      ".rejected", ".offer", ".withdrawn",
                      ".score-hi", ".score-mid", ".score-lo",
                      ".kwchip.covered", ".kwchip.missing"]
    # UI component boundaries need 3:1 against the adjacent surface.
    BOUNDARY_PAIRS = [
        ("--line on page bg", "var(--line)", "var(--bg)", 3.0),
        ("--line on panel", "var(--line)", "var(--panel)", 3.0),
    ]

    def test_text_pairs(self):
        for name, fg, bg, minimum in self.TEXT_PAIRS:
            with self.subTest(pair=name):
                self.assert_contrast(name, fg, bg, minimum)

    def test_pill_and_badge_pairs(self):
        for selector in self.PILL_SELECTORS:
            with self.subTest(selector=selector):
                fg, bg = rule_colors(self.css, selector)
                self.assert_contrast(selector, fg, bg, 4.5)

    def test_ui_boundary_pairs(self):
        for name, fg, bg, minimum in self.BOUNDARY_PAIRS:
            with self.subTest(pair=name):
                self.assert_contrast(name, fg, bg, minimum)

    def test_focus_outline_contrast(self):
        m = re.search(r":focus-visible\s*\{([^}]*)\}", self.css)
        assert m, "no :focus-visible rule found"
        body = m.group(1)
        color = re.search(r"outline(?:-color)?\s*:[^;}]*?(#[0-9a-fA-F]{3,6}|var\(--[\w-]+\))", body)
        assert color, ":focus-visible must set an outline color"
        for surface in ("var(--bg)", "var(--panel)", "var(--panel2)"):
            with self.subTest(surface=surface):
                # 3px outline with 2px offset sits on the surrounding surface
                self.assert_contrast("focus outline", color.group(1), surface, 3.0)


# ---------------------------------------------------------------------------
# 2. visible focus indicators
# ---------------------------------------------------------------------------

class FocusVisibleTest(CSSTestBase):
    def test_focus_visible_rule_exists(self):
        self.assertRegex(self.css, r":focus-visible\s*\{[^}]*outline\s*:",
                         "a :focus-visible rule with an outline is required")

    def test_outline_has_width_and_offset(self):
        m = re.search(r":focus-visible\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertRegex(body, r"outline\s*:\s*\d+px",
                         "focus outline needs an explicit width")
        self.assertRegex(body, r"outline-offset\s*:\s*\d+px",
                         "focus outline needs an offset so it never hugs text")

    def test_no_bare_outline_removal(self):
        for m in re.finditer(r"\{([^}]*)\}", self.css):
            body = m.group(1)
            if re.search(r"outline\s*:\s*(none|0)\b", body):
                self.fail("outline removed without a replacement: " + body.strip())


# ---------------------------------------------------------------------------
# 3. reduced motion: media query + manual data-motion hook
# ---------------------------------------------------------------------------

class ReducedMotionTest(CSSTestBase):
    def test_media_query_present(self):
        self.assertIn("@media (prefers-reduced-motion", self.css,
                      "prefers-reduced-motion media query is required")

    def test_manual_toggle_hook_present(self):
        self.assertRegex(self.css, r'html\[data-motion="reduced"\]',
                         'manual toggle hook html[data-motion="reduced"] is required')

    def _reduced_motion_bodies(self):
        # strip comments first: the contract comment itself mentions
        # html[data-motion="reduced"] and must not be parsed as a rule
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        bodies = []
        start = css.find("@media (prefers-reduced-motion")
        if start != -1:
            # walk balanced braces to capture the whole media block
            depth, i = 0, css.find("{", start)
            while i < len(css):
                depth += 1 if css[i] == "{" else -1 if css[i] == "}" else 0
                i += 1
                if depth == 0:
                    break
            bodies.append(css[start:i])
        bodies += re.findall(r'html\[data-motion="reduced"\][^{]*\{([^}]*)\}', css)
        return bodies

    def test_transitions_and_animations_disabled(self):
        bodies = self._reduced_motion_bodies()
        self.assertTrue(bodies, "no reduced-motion rules found")
        for body in bodies:
            self.assertIn("transition", body,
                          "reduced-motion rules must disable transitions")
            self.assertIn("animation", body,
                          "reduced-motion rules must disable animations")

    def test_reduced_motion_contract_documented(self):
        self.assertIn("candid-motion", self.css,
                      "the reduced-motion contract (localStorage key) must be "
                      "documented in a CSS comment for the JS worker")


if __name__ == "__main__":
    unittest.main()
