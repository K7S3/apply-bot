"""Optional browser layer for the apply module.

Playwright is an OPTIONAL extra. Everything in this module except
``launch`` works without it. ``detect_blockers`` is pure duck-typed logic
over the page object.

Login walls and CAPTCHAs are reported as blockers and are NEVER solved.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE: bool = True
except ImportError:  # playwright is an optional extra
    sync_playwright = None  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE: bool = False

LOGIN_MARKERS = [
    "log in to apply",
    "sign in to apply",
    "create an account to apply",
    "login to apply",
]

CAPTCHA_MARKERS = ["recaptcha", "hcaptcha", "captcha", "turnstile"]


class ApplyBrowserError(Exception):
    """Raised when the browser layer cannot run (e.g. playwright missing)."""


def detect_blockers(page) -> str | None:
    """Return a blocker reason, or None if the page looks fillable.

    Login walls and CAPTCHAs are reported as blockers; they are NEVER
    solved or bypassed.
    """
    try:
        text = (page.content() or "").lower()
    except Exception:  # noqa: BLE001
        return "could not read page content"
    if any(m in text for m in LOGIN_MARKERS):
        return "login wall: site requires sign-in before applying"
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if any(m in url for m in CAPTCHA_MARKERS):
                return "CAPTCHA detected on the application page"
    except Exception:  # noqa: BLE001
        pass
    return None


@contextmanager
def launch(headless: bool = True) -> Iterator:
    """Yield a fresh application page; closes the browser on exit."""
    if not PLAYWRIGHT_AVAILABLE:
        raise ApplyBrowserError(
            "Playwright is not installed. The apply module needs it: "
            "pip install playwright && playwright install chromium. "
            "Core candid works without it."
        )

    with sync_playwright() as pw:
        # channel="chromium" runs the full Chromium build headless
        # (the separate headless-shell binary may not be downloaded).
        browser = pw.chromium.launch(headless=headless, channel="chromium")
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
