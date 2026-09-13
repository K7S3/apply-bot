"""Best-effort job-description scraper.

Fetches the job posting page and extracts visible text so the resume
reviewer has context about the role. If the page can't be fetched
(JS-heavy site, blocked, login wall), returns "" and the pipeline
continues with just the role title.
"""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser

from applybot import config as C


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping scripts/styles."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def fetch_job_description(job_link: str | None, timeout: int = 25) -> str:
    """Return cleaned visible text from the job posting, or "" on failure."""
    if not job_link or not job_link.startswith(("http://", "https://")):
        return ""
    try:
        req = urllib.request.Request(
            job_link, headers={"User-Agent": "applybot/0.1 (+job-description)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return ""
            html = resp.read().decode("utf-8", errors="replace")
        parser = _TextExtractor()
        parser.feed(html)
        text = parser.text()
        return text[: C.JOB_DESC_MAX_CHARS]
    except Exception:  # noqa: BLE001 — scraping is best-effort by design
        return ""
