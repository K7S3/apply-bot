"""Automated accessibility audit for the candid dashboard UI.

``python -m candid a11y [--json]`` runs a set of static checks against
``candid/data/dashboard.html`` and reports PASS/FAIL per check:

    1. contrast        WCAG 2.2 relative-luminance contrast ratios of the
                       CSS palette (:root custom properties + key selectors).
                       Flags text below 4.5:1 (normal) or 3.0:1 (large).
    2. structure       Skip link, banner/main/contentinfo landmarks, exactly
                       one h1, and no skipped heading levels.
    3. labels          Every input/select/textarea has an associated label
                       (``<label for>``, wrapping label, aria-label,
                       aria-labelledby, or title).
    4. buttons         Every <button> exposes accessible text or aria-label.
    5. images          Every <img> has an alt attribute.
    6. focus-motion    :focus-visible styles, a prefers-reduced-motion media
                       block, and html[data-motion="reduced"] support.
    7. live-region     At least one aria-live="polite" region.
    8. tables          Every <table> has a <caption> (or aria-label).

The checks are aligned with the dashboard's a11y contracts so they keep
passing as the UI evolves: skip link ``class="skip-link" href="#main-content"``,
``<main id="main-content">``, ``:focus-visible`` rules,
``@media (prefers-reduced-motion: reduce)``,
``html[data-motion="reduced"]`` support, and a polite aria-live region.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# color / contrast helpers (WCAG 2.x relative luminance)
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_VAR_RE = re.compile(r"^var\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,\s*(.+?))?\s*\)$")
_ROOT_BLOCK_RE = re.compile(r":root\s*\{(.*?)\}", re.DOTALL)
_DECL_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;{}]+?)\s*(?:;|(?=\})|$)")
_STYLE_TAG_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an ``#rgb`` / ``#rrggbb`` color (0..1)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"not a hex color: {hex_color!r}")
    channels = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255.0
        channels.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color1: str, color2: str) -> float:
    """WCAG contrast ratio of two hex colors, e.g. black/white = 21.0."""
    l1, l2 = relative_luminance(color1), relative_luminance(color2)
    light, dark = max(l1, l2), min(l1, l2)
    return (light + 0.05) / (dark + 0.05)


def resolve_color(value: str, variables: dict[str, str]) -> str | None:
    """Resolve a CSS color value to ``#rrggbb`` via :root vars; None if unknown."""
    value = value.strip().rstrip(";").strip()
    m = _VAR_RE.match(value)
    if m:
        var_name, fallback = m.group(1), m.group(2)
        if var_name in variables:
            return resolve_color(variables[var_name], variables)
        if fallback is not None:
            return resolve_color(fallback, variables)
        return None
    m = _HEX_RE.match(value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h.lower()
    return None


def parse_root_vars(style_text: str) -> dict[str, str]:
    """Extract ``--var: value`` pairs from the first ``:root{...}`` block."""
    m = _ROOT_BLOCK_RE.search(style_text)
    if not m:
        return {}
    return {name.strip(): val.strip() for name, val in _DECL_RE.findall(m.group(1))}


def css_from_html(html: str) -> str:
    """Concatenate all inline <style> blocks (the dashboard is single-file)."""
    return "\n".join(_STYLE_TAG_RE.findall(html))


# ---------------------------------------------------------------------------
# structural parse of the dashboard markup
# ---------------------------------------------------------------------------

_VOID = {"input", "img", "br", "hr", "meta", "link", "source", "wbr", "option"}


class _DashboardParser(HTMLParser):
    """Collects the elements the a11y checks need (skips <script>/<style>)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.headings: list[tuple[int, str, str]] = []   # (level, id, text)
        self.inputs: list[dict] = []                     # input/select/textarea attrs
        self.labels: list[dict] = []                     # label attrs + wrapped text
        self.buttons: list[dict] = []                    # button attrs + text
        self.images: list[dict] = []
        self.tables: list[dict] = []                     # attrs + has_caption
        self.landmarks: dict[str, list[str]] = {"banner": [], "main": [],
                                               "contentinfo": [], "navigation": []}
        self.skip_links: list[dict] = []
        self.live_regions: list[dict] = []
        self.body_children: list[str] = []               # direct child tags of <body>
        self.ids: set[str] = set()
        self.main_ids: list[str] = []
        self._stack: list[tuple[str, dict]] = []
        self._text: list[str] = []
        self._in_label: list[dict] = []
        self._in_table: list[dict] = []
        self._label_text: list[str] = []

    # -- tag handling ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "body":
            self._stack.append((tag, a))
            return
        if self._stack and self._stack[-1][0] == "body" and len(self._stack) == 1:
            self.body_children.append(tag)
        if tag in ("header", "main", "footer", "nav"):
            self._stack.append((tag, a))
            role = a.get("role", "")
            if tag == "header" or role == "banner":
                self.landmarks["banner"].append(self._describe(a))
            if tag == "main" or role == "main":
                self.landmarks["main"].append(self._describe(a))
                if a.get("id"):
                    self.main_ids.append(a["id"])
            if tag == "footer" or role == "contentinfo":
                self.landmarks["contentinfo"].append(self._describe(a))
            if tag == "nav" or role == "navigation":
                self.landmarks["navigation"].append(self._describe(a))
            return
        if tag == "a" and "skip-link" in a.get("class", "").split():
            self.skip_links.append(a)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append((int(tag[1]), a.get("id", ""), ""))
            self._text.append(tag)
        elif tag in ("input", "select", "textarea"):
            a["_tag"] = tag
            a["_wrapped"] = bool(self._in_label)
            self.inputs.append(a)
        elif tag == "label":
            entry = {"attrs": a, "text": ""}
            self.labels.append(entry)
            self._in_label.append(entry)
            self._label_text.append("")
        elif tag == "button":
            entry = {"attrs": a, "text": ""}
            self.buttons.append(entry)
            self._text.append(("button", entry))
        elif tag == "img":
            self.images.append(a)
        elif tag == "table":
            entry = {"attrs": a, "has_caption": False}
            self.tables.append(entry)
            self._in_table.append(entry)
        elif tag == "caption" and self._in_table:
            self._in_table[-1]["has_caption"] = True
        if a.get("aria-live"):
            self.live_regions.append(a)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in ("body", "header", "main", "footer", "nav") and self._stack \
                and self._stack[-1][0] == tag:
            self._stack.pop()
        if tag == "label" and self._in_label:
            entry = self._in_label.pop()
            entry["text"] = self._label_text.pop().strip()
        if tag == "table" and self._in_table:
            self._in_table.pop()
        if self._text and self._text[-1] == tag:
            self._text.pop()
        if self._text and isinstance(self._text[-1], tuple) and tag == "button":
            _, entry = self._text.pop()
            entry["text"] = entry.get("_buf", "").strip()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # void elements like <input .../>: treat as start only
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self.headings and self._text and self._text[-1] in (
                "h1", "h2", "h3", "h4", "h5", "h6"):
            level, hid, text = self.headings[-1]
            self.headings[-1] = (level, hid, (text + data).strip())
        if self._label_text:
            self._label_text[-1] += data
        if self._text and isinstance(self._text[-1], tuple):
            _, entry = self._text[-1]
            entry["_buf"] = entry.get("_buf", "") + data

    @staticmethod
    def _describe(a: dict) -> str:
        bits = []
        if a.get("id"):
            bits.append(f"id={a['id']}")
        if a.get("class"):
            bits.append(f"class={a['class']}")
        return " ".join(bits) or "(no id/class)"


# ---------------------------------------------------------------------------
# check results
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    id: str
    title: str
    passed: bool
    details: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title,
                "passed": self.passed, "details": self.details,
                "failures": self.failures}


# -- individual checks ------------------------------------------------------

def check_contrast(html: str) -> CheckResult:
    """WCAG relative-luminance contrast of the CSS palette pairs."""
    css = css_from_html(html)
    variables = parse_root_vars(css)
    details, failures = [], []
    if not variables:
        return CheckResult("contrast", "Color contrast (WCAG 2.2 AA)", False,
                           failures=["no :root custom properties found in <style>"])

    def note(desc: str, fg: str, bg: str, threshold: float, large: bool = False) -> None:
        fg_hex = resolve_color(fg, variables)
        bg_hex = resolve_color(bg, variables)
        if fg_hex is None or bg_hex is None:
            failures.append(f"{desc}: could not resolve color ({fg} on {bg})")
            return
        r = contrast_ratio(fg_hex, bg_hex)
        line = f"{desc}: {fg_hex} on {bg_hex} = {r:.2f}:1 (needs >={threshold})"
        if r + 1e-9 >= threshold:
            details.append("PASS " + line)
        else:
            failures.append("FAIL " + line + (" [large text]" if large else ""))

    surfaces = {"--bg": "--bg", "--panel": "--panel", "--panel2": "--panel2"}
    for fg_name in ("--text", "--muted", "--accent", "--green", "--amber", "--red"):
        for bg_name in surfaces.values():
            note(f"{fg_name} on {bg_name}", f"var({fg_name})", f"var({bg_name})", 4.5)
    # button chrome: dark text on accent background (from the `button` rule)
    note("button text on accent", "#06101f", "var(--accent)", 4.5)
    # large-text threshold applied to the h1/header accent usage as large text
    note("accent on bg (large text)", "var(--accent)", "var(--bg)", 3.0, large=True)
    passed = not failures
    return CheckResult("contrast", "Color contrast (WCAG 2.2 AA)", passed,
                       details=details, failures=failures)


def check_structure(html: str, parsed: _DashboardParser) -> CheckResult:
    """Skip link, landmarks, single h1, heading order."""
    details, failures = [], []

    good_skips = [a for a in parsed.skip_links if a.get("href") == "#main-content"]
    if good_skips:
        pos = parsed.body_children[:5]
        details.append(f'skip link class="skip-link" href="#main-content" present'
                       f" ({'first' if pos and pos[0] == 'a' else 'early'} in body)")
    else:
        failures.append('missing skip link: expected <a class="skip-link" '
                        'href="#main-content"> before main content')

    if parsed.landmarks["banner"]:
        details.append("banner landmark present (<header> or role=banner)")
    else:
        failures.append("missing banner landmark (<header> or role=banner)")
    if parsed.landmarks["main"]:
        details.append("main landmark present (<main> or role=main)")
    else:
        failures.append("missing main landmark (<main> or role=main)")
    if "main-content" in parsed.main_ids:
        details.append('<main id="main-content"> present (skip-link target)')
    else:
        failures.append('missing <main id="main-content"> (skip-link target)')
    if parsed.landmarks["contentinfo"]:
        details.append("contentinfo landmark present (<footer> or role=contentinfo)")
    else:
        failures.append("missing contentinfo landmark (<footer> or role=contentinfo)")

    h1s = [h for h in parsed.headings if h[0] == 1]
    if len(h1s) == 1:
        details.append(f"exactly one h1: {h1s[0][2][:60]!r}")
    else:
        failures.append(f"expected exactly one h1, found {len(h1s)}")

    prev = 0
    for level, _hid, text in parsed.headings:
        if prev and level > prev + 1:
            failures.append(f"skipped heading level: h{prev} -> h{level} "
                            f"({text[:50]!r})")
        prev = level
    if not any("skipped heading level" in f for f in failures):
        details.append("no skipped heading levels")

    return CheckResult("structure", "Landmarks, skip link, headings", not failures,
                       details=details, failures=failures)


def check_labels(parsed: _DashboardParser) -> CheckResult:
    """Every form control has an associated label."""
    details, failures = [], []
    labelled_for = set()
    for lab in parsed.labels:
        fid = lab["attrs"].get("for", "")
        if fid:
            labelled_for.add(fid)
    for ctrl in parsed.inputs:
        if ctrl.get("type", "").lower() == "hidden":
            continue
        cid = ctrl.get("id", "")
        ok = (
            (cid and cid in labelled_for)
            or ctrl.get("aria-label", "").strip()
            or ctrl.get("aria-labelledby", "").strip()
            or ctrl.get("title", "").strip()
            or ctrl.get("_wrapped", False)
        )
        name = cid or ctrl.get("name", "") or ctrl.get("type", "") or ctrl.get("_tag")
        if ok:
            details.append(f"<{ctrl.get('_tag', 'input')}> {name!r} labelled")
        else:
            failures.append(f"<{ctrl.get('_tag', 'input')}> {name!r} has no label, "
                            "aria-label, aria-labelledby, or title")
    return CheckResult("labels", "Form controls labelled", not failures,
                       details=details, failures=failures)


def check_buttons(html: str, parsed: _DashboardParser) -> CheckResult:
    """Every <button> (including JS-rendered ones) has accessible text."""
    details, failures = [], []
    seen = set()
    for b in parsed.buttons:
        key = (b["attrs"].get("id", ""), b["text"][:40])
        seen.add(key)
        label = b["text"] or b["attrs"].get("aria-label", "").strip() \
            or b["attrs"].get("aria-labelledby", "").strip()
        name = b["attrs"].get("id", "") or b["attrs"].get("class", "") or label[:20]
        if label:
            details.append(f"<button> {name!r} has text {label[:40]!r}")
        else:
            failures.append(f"<button> {name!r} has no text, aria-label, or "
                            "aria-labelledby")
    # buttons injected by the inline JS are invisible to the HTML parser, so
    # scan the raw source too (dashboard is single-file, script included)
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>",
                         html, re.DOTALL | re.IGNORECASE):
        attrs_text, inner = m.group(1), m.group(2)
        dynamic = "${" in inner                        # JS template: text at runtime
        inner = re.sub(r"\$\{.*?\}", "", inner)          # template interpolation
        inner = re.sub(r"<[^>]+>", "", inner).strip()    # nested markup
        attrs = dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', attrs_text))
        label = inner or attrs.get("aria-label", "").strip()
        key = (attrs.get("id", ""), label[:40])
        if key in seen:
            continue
        name = attrs.get("id", "") or attrs.get("class", "") or label[:20]
        if label:
            details.append(f"<button> {name!r} (JS) has text {label[:40]!r}")
        elif dynamic:
            details.append(f"<button> {name!r} (JS) renders dynamic text at runtime")
        else:
            failures.append(f"<button> {name!r} (JS) has no text, aria-label, or "
                            "aria-labelledby")
    return CheckResult("buttons", "Buttons have accessible text", not failures,
                       details=details, failures=failures)


def check_images(parsed: _DashboardParser) -> CheckResult:
    details, failures = [], []
    for img in parsed.images:
        src = img.get("src", "")[:40]
        if "alt" in img:
            details.append(f"<img> {src!r} has alt={img['alt'][:40]!r}")
        else:
            failures.append(f"<img> {src!r} missing alt attribute")
    if not parsed.images:
        details.append("no <img> elements (nothing to check)")
    return CheckResult("images", "Images have alt text", not failures,
                       details=details, failures=failures)


def check_focus_motion(html: str) -> CheckResult:
    """Keyboard focus styles + reduced-motion support in CSS."""
    details, failures = [], []
    css = css_from_html(html)
    if re.search(r":focus-visible", css):
        details.append(":focus-visible rules present")
    else:
        failures.append("no :focus-visible CSS rules found")
    if re.search(r"@media\s*\([^)]*prefers-reduced-motion\s*:\s*reduce", css):
        details.append("@media (prefers-reduced-motion: reduce) block present")
    else:
        failures.append("no @media (prefers-reduced-motion: reduce) block found")
    if re.search(r'html\s*\[\s*data-motion\s*=\s*["\']reduced["\']\s*\]', css):
        details.append('html[data-motion="reduced"] selector present')
    else:
        failures.append('no html[data-motion="reduced"] CSS selector found')
    return CheckResult("focus-motion", "Focus styles + reduced motion", not failures,
                       details=details, failures=failures)


def check_live_region(parsed: _DashboardParser) -> CheckResult:
    details, failures = [], []
    polite = [a for a in parsed.live_regions
              if a.get("aria-live", "").strip().lower() == "polite"]
    if polite:
        details.append(f"{len(polite)} aria-live=\"polite\" region(s) present")
    else:
        failures.append('no aria-live="polite" region found')
    return CheckResult("live-region", "Live region for dynamic updates", not failures,
                       details=details, failures=failures)


def check_tables(parsed: _DashboardParser) -> CheckResult:
    details, failures = [], []
    for t in parsed.tables:
        a = t["attrs"]
        name = a.get("id", "") or a.get("class", "") or "table"
        if t["has_caption"]:
            details.append(f"<table> {name!r} has a <caption>")
        elif a.get("aria-label", "").strip() or a.get("aria-labelledby", "").strip():
            details.append(f"<table> {name!r} labelled via aria-label")
        else:
            failures.append(f"<table> {name!r} has no <caption>")
    if not parsed.tables:
        details.append("no <table> elements (nothing to check)")
    return CheckResult("tables", "Tables have captions", not failures,
                       details=details, failures=failures)


# ---------------------------------------------------------------------------
# audit driver
# ---------------------------------------------------------------------------

def audit(html: str) -> list[CheckResult]:
    """Run every check against dashboard HTML; returns per-check results."""
    parsed = _DashboardParser()
    parsed.feed(html)
    # tag control dicts with their element name for clearer messages
    for ctrl in parsed.inputs:
        ctrl.setdefault("_tag", "input")
    results = [
        check_contrast(html),
        check_structure(html, parsed),
        check_labels(parsed),
        check_buttons(html, parsed),
        check_images(parsed),
        check_focus_motion(html),
        check_live_region(parsed),
        check_tables(parsed),
    ]
    return results


def audit_file(path: str | Path) -> list[CheckResult]:
    """Run the audit against a dashboard HTML file."""
    return audit(Path(path).read_text(encoding="utf-8"))


def all_passed(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)


def results_to_dict(results: list[CheckResult], source: str) -> dict:
    return {
        "source": str(source),
        "target": "WCAG 2.2 AA",
        "passed": all_passed(results),
        "checks": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
    }


def render_report(results: list[CheckResult], source: str) -> str:
    """Human-readable PASS/FAIL report."""
    lines = [f"candid a11y: accessibility audit of {source}",
             "target: WCAG 2.2 AA", ""]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"[{status}] {r.id}: {r.title}")
        for d in r.details:
            lines.append(f"        {d}")
        for f in r.failures:
            lines.append(f"        ! {f}")
        lines.append("")
    s = results_to_dict(results, source)["summary"]
    lines.append(f"{s['passed']}/{s['total']} checks passed"
                + (" (all clear)" if all_passed(results) else " (issues found)"))
    return "\n".join(lines)
