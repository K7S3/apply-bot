"""Static interaction/accessibility checks for the dashboard (batch-104, features 6-7).

Features 6 (keyboard operability) and 7 (live regions) are implemented in the
dashboard's inline <script>; these tests assert the script and markup contain
the required pieces via static string checks.
"""
import re
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "candid" / "data" / "dashboard.html"


def _parts():
    text = HTML.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", text, re.S)
    assert m, "no <script> block found in dashboard.html"
    return text, m.group(1)


def test_focus_trap_implementation():
    _, js = _parts()
    assert "function trapFocus" in js, "missing trapFocus(container) implementation"
    assert '"Tab"' in js or "'Tab'" in js, "trap does not handle the Tab key"
    assert "openModal" in js and "closeModal" in js, "modal open/close helpers missing"
    assert "showModal" in js, "dialog should open with showModal()"


def test_escape_handling():
    _, js = _parts()
    assert '"Escape"' in js or "'Escape'" in js, "no Escape key handling"
    assert "<dialog" in js, "no <dialog> element created in the script"


def test_dismiss_dialog_wires_trap_escape_return_focus():
    _, js = _parts()
    assert "dismissDialog" in js, "dismiss job confirmation dialog missing"
    assert "trapFocus" in js
    assert "_returnFocusTo" in js, "return-focus after modal close missing"


def test_aria_sort_updates():
    _, js = _parts()
    assert "aria-sort" in js, "headers do not set aria-sort"
    assert "ascending" in js and "descending" in js, "aria-sort values not updated"
    assert "<button" in js and "data-sort" in js, "headers need real <button> elements"


def test_announce_helper_wired_into_status_sites():
    _, js = _parts()
    assert re.search(r"function announce\s*\(", js), "announce() helper missing"
    calls = len(re.findall(r"(?<![\w$.])announce\(", js)) - 1  # minus the definition
    assert calls >= 3, f"announce() wired into only {calls} status-update sites, need >= 3"


def test_assertive_errors_are_announced():
    _, js = _parts()
    assert "announceErr" in js, "no assertive error announcer"
    assert js.count("announceErr(") >= 2, "assertive announcements should cover several error paths"


def test_live_regions():
    html, js = _parts()
    assert 'aria-live="polite"' in html, "polite live region missing from markup"
    assert 'role="status"' in html, "role=status missing from markup"
    assert 'id="a11yStatus"' in html, "polite region needs a stable id"
    assert 'aria-live="assertive"' in js or 'role="alert"' in js, \
        "no assertive region for real errors"


def test_shortcut_help():
    _, js = _parts()
    assert '"?"' in js or "'?'" in js, "no ? shortcut for help"
    assert '"/"' in js or "'/'" in js, "no / shortcut for search"
    assert "helpDialog" in js, "shortcut help dialog missing"
