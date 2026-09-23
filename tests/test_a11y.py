"""Tests for the `candid a11y` accessibility audit (candid/a11y.py)."""

import json
from pathlib import Path

import pytest

from candid import a11y as A
from candid import dashboard as D

DASHBOARD = D.HTML_PATH.read_text(encoding="utf-8")

# A minimal but fully accessible page used as the positive control: it
# embodies the same contracts as the dashboard (skip link, landmarks, labels,
# focus-visible, reduced-motion, live region, captioned table).
GOOD_HTML = """<!DOCTYPE html><html lang="en"><head><style>
:root{--bg:#0f1420;--text:#e8edf7;--muted:#9aa7c4;--accent:#5aa2ff;
      --green:#3ecf8e;--amber:#f5b544;--red:#f26d6d;--panel:#182034;--panel2:#1f2a44}
button{color:#06101f;background:var(--accent)}
:focus-visible{outline:3px solid #fff}
@media (prefers-reduced-motion: reduce){*{transition:none}}
html[data-motion="reduced"] *{transition:none}
</style></head><body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<header><h1>Title</h1></header>
<main id="main-content">
<section><h2>Form</h2>
<label for="q">Search</label><input id="q">
<label>Wrap me <input type="checkbox" id="c"></label>
<select id="s" aria-label="Level"><option>a</option></select>
<textarea id="t" title="Notes"></textarea>
<button>Go</button><button aria-label="Close dialog"></button>
<img src="x.png" alt="decorative">
<div role="status" aria-live="polite"></div>
<table><caption>Apps</caption><tr><td>x</td></tr></table>
</section></main><footer></footer>
</body></html>"""


def results_by_id(results):
    return {r.id: r for r in results}


# ---------------------------------------------------------------------------
# contrast math
# ---------------------------------------------------------------------------

def test_contrast_black_white_is_21_to_1():
    assert A.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert A.contrast_ratio("#fff", "#000") == pytest.approx(21.0, abs=0.01)


def test_contrast_known_mid_value():
    # #777777 on white is ~4.48:1 (just under AA for normal text)
    r = A.contrast_ratio("#777777", "#ffffff")
    assert r == pytest.approx(4.48, abs=0.02)
    assert r < 4.5


def test_relative_luminance_bounds():
    assert A.relative_luminance("#000000") == pytest.approx(0.0)
    assert A.relative_luminance("#ffffff") == pytest.approx(1.0)


def test_resolve_color_var_and_fallback():
    vars_ = {"--a": "#112233"}
    assert A.resolve_color("var(--a)", vars_) == "#112233"
    assert A.resolve_color("var(--missing, #445566)", vars_) == "#445566"
    assert A.resolve_color("#abc", vars_) == "#aabbcc"
    assert A.resolve_color("var(--missing)", vars_) is None


# ---------------------------------------------------------------------------
# positive control: every check passes on a contract-conformant page
# ---------------------------------------------------------------------------

def test_all_checks_pass_on_good_html():
    results = A.audit(GOOD_HTML)
    assert len(results) == 8
    failures = {r.id: r.failures for r in results if not r.passed}
    assert not failures, f"checks failed on good HTML: {failures}"
    assert A.all_passed(results)


def test_all_checks_pass_on_current_dashboard():
    results = A.audit(DASHBOARD)
    failures = {r.id: r.failures for r in results if not r.passed}
    assert not failures, f"checks failed on dashboard.html: {failures}"


# ---------------------------------------------------------------------------
# negative tests: crafted bad snippets fail the right check
# ---------------------------------------------------------------------------

def _with(**kwargs):
    html = GOOD_HTML
    for old, new in kwargs.items():
        html = html.replace(old, new)
    return html


def test_low_contrast_fails_contrast_check():
    html = GOOD_HTML.replace("--text:#e8edf7", "--text:#555b66")
    r = results_by_id(A.audit(html))["contrast"]
    assert not r.passed
    assert any("--text on --bg" in f for f in r.failures)


def test_missing_skip_link_fails_structure():
    html = GOOD_HTML.replace('<a class="skip-link" href="#main-content">Skip to main content</a>', "")
    r = results_by_id(A.audit(html))["structure"]
    assert not r.passed
    assert any("skip link" in f for f in r.failures)


def test_two_h1_fails_structure():
    html = GOOD_HTML.replace("<h1>Title</h1>", "<h1>One</h1><h1>Two</h1>")
    r = results_by_id(A.audit(html))["structure"]
    assert not r.passed
    assert any("exactly one h1" in f for f in r.failures)


def test_skipped_heading_level_fails_structure():
    html = GOOD_HTML.replace("<h2>Form</h2>", "<h3>Form</h3>")
    r = results_by_id(A.audit(html))["structure"]
    assert not r.passed
    assert any("skipped heading level" in f for f in r.failures)


def test_unlabelled_input_fails_labels():
    html = GOOD_HTML.replace('<label for="q">Search</label>', "")
    r = results_by_id(A.audit(html))["labels"]
    assert not r.passed
    assert any("'q'" in f for f in r.failures)


def test_empty_button_fails_buttons():
    html = GOOD_HTML.replace("<button>Go</button>", "<button></button>")
    r = results_by_id(A.audit(html))["buttons"]
    assert not r.passed
    assert r.failures


def test_img_without_alt_fails_images():
    html = GOOD_HTML.replace('alt="decorative"', "")
    r = results_by_id(A.audit(html))["images"]
    assert not r.passed
    assert any("alt" in f for f in r.failures)


def test_missing_focus_visible_fails_focus_motion():
    html = GOOD_HTML.replace(":focus-visible{outline:3px solid #fff}", "")
    r = results_by_id(A.audit(html))["focus-motion"]
    assert not r.passed
    assert any("focus-visible" in f for f in r.failures)


def test_missing_reduced_motion_fails_focus_motion():
    html = GOOD_HTML.replace("@media (prefers-reduced-motion: reduce){*{transition:none}}", "")
    html = html.replace('html[data-motion="reduced"] *{transition:none}', "")
    r = results_by_id(A.audit(html))["focus-motion"]
    assert not r.passed
    assert any("reduced-motion" in f for f in r.failures)


def test_missing_live_region_fails_live_region():
    html = GOOD_HTML.replace('<div role="status" aria-live="polite"></div>', "")
    r = results_by_id(A.audit(html))["live-region"]
    assert not r.passed
    assert any("aria-live" in f for f in r.failures)


def test_table_without_caption_fails_tables():
    html = GOOD_HTML.replace("<table><caption>Apps</caption>", "<table>")
    r = results_by_id(A.audit(html))["tables"]
    assert not r.passed
    assert any("caption" in f for f in r.failures)


# ---------------------------------------------------------------------------
# report rendering + CLI behavior
# ---------------------------------------------------------------------------

def test_json_report_is_machine_readable():
    results = A.audit(GOOD_HTML)
    data = A.results_to_dict(results, "good.html")
    assert data["passed"] is True
    assert data["target"] == "WCAG 2.2 AA"
    assert data["summary"] == {"total": 8, "passed": 8, "failed": 0}
    json.dumps(data)  # must serialize cleanly


def test_human_report_marks_pass_fail():
    results = A.audit(GOOD_HTML)
    text = A.render_report(results, "good.html")
    assert "[PASS]" in text and "[FAIL]" not in text
    bad = A.audit(GOOD_HTML.replace('<a class="skip-link" href="#main-content">Skip to main content</a>', ""))
    assert "[FAIL]" in A.render_report(bad, "bad.html")


def test_cli_exit_zero_on_pass(tmp_path):
    from candid.__main__ import main
    good = tmp_path / "good.html"
    good.write_text(GOOD_HTML, encoding="utf-8")
    main(["a11y", "--file", str(good)])  # no exception means exit 0


def test_cli_exit_one_on_failure(tmp_path, capsys):
    from candid.__main__ import main
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body><input id='q'></body></html>", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["a11y", "--file", str(bad)])
    assert e.value.code == 1


def test_cli_json_flag(tmp_path, capsys):
    from candid.__main__ import main
    good = tmp_path / "good.html"
    good.write_text(GOOD_HTML, encoding="utf-8")
    main(["a11y", "--file", str(good), "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is True
    assert len(data["checks"]) == 8
