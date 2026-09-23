"""Tests for candid.apply_browser. No playwright is imported or required."""

from __future__ import annotations

import pytest

import candid.apply_browser as ab
from candid.apply_browser import (
    ApplyBrowserError,
    detect_blockers,
    launch,
)


class FakeFrame:
    def __init__(self, url):
        self.url = url


class FakePage:
    def __init__(self, text="", frames=None, fail_content=False):
        self._text = text
        self.frames = frames or []
        self._fail_content = fail_content

    def content(self):
        if self._fail_content:
            raise RuntimeError("nope")
        return self._text


def test_detect_blockers_login_wall():
    page = FakePage(text="<html>Please log in to apply to continue</html>")
    assert detect_blockers(page) == "login wall: site requires sign-in before applying"


def test_detect_blockers_captcha_frame():
    page = FakePage(
        text="<html>Job application</html>",
        frames=[FakeFrame("https://www.google.com/recaptcha/api.js")],
    )
    assert detect_blockers(page) == "CAPTCHA detected on the application page"


def test_detect_blockers_clean_page():
    page = FakePage(text="<html>Job Application Form</html>", frames=[])
    assert detect_blockers(page) is None


def test_detect_blockers_unreadable_page():
    page = FakePage(fail_content=True)
    assert detect_blockers(page) == "could not read page content"


def test_launch_raises_when_playwright_missing(monkeypatch):
    monkeypatch.setattr(ab, "PLAYWRIGHT_AVAILABLE", False)
    with pytest.raises(ApplyBrowserError) as excinfo:
        with launch():
            pass  # pragma: no cover
    assert "pip install playwright" in str(excinfo.value)


def test_apply_browser_error_is_exception():
    assert issubclass(ApplyBrowserError, Exception)
