"""Fetch the tailored resume text for one application row.

Primary path: download the Google Doc as plain text via the Docs export URL.
This works for docs shared as "Anyone with the link can view".

Fallback path: a .txt file in the `resumes/` folder, e.g.
    resumes/ExampleCorp_Data_Scientist.txt
Useful when the doc is private or the export fails.
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from candid.legacy import config as C


class ResumeFetchError(Exception):
    """Raised when the resume text cannot be obtained."""


def _doc_id_from_link(link: str) -> str | None:
    """Extract the Google Docs document id from a share link."""
    if not link:
        return None
    m = re.search(r"/document/d/([a-zA-Z0-9-_]+)", link)
    return m.group(1) if m else None


def _download_doc_as_txt(doc_id: str, timeout: int = 30) -> str:
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    req = urllib.request.Request(url, headers={"User-Agent": "candid.legacy/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    text = raw.strip()
    if len(text) < 50:
        raise ResumeFetchError(
            "Google Docs export returned almost no text "
            "(the doc may be private or the link may be wrong)."
        )
    return text


def _fallback_txt(company: str, role: str) -> Path | None:
    """Find a matching .txt resume in the resumes/ folder, if any."""
    safe_company = re.sub(r"[^\w\-]+", "_", (company or "unknown").strip())
    safe_role = re.sub(r"[^\w\-]+", "_", (role or "role").strip())
    preferred = C.RESUMES_DIR / f"{safe_company}_{safe_role}.txt"
    if preferred.exists():
        return preferred
    # Otherwise accept any .txt whose name contains the company name.
    if C.RESUMES_DIR.exists():
        for p in sorted(C.RESUMES_DIR.glob("*.txt")):
            if safe_company.lower() in p.stem.lower():
                return p
    return None


def fetch_resume_text(resume_doc_link: str | None, company: str, role: str) -> str:
    """Return the tailored resume as plain text.

    Tries the Google Docs export first; falls back to resumes/*.txt.
    """
    doc_id = _doc_id_from_link(resume_doc_link or "")
    if doc_id:
        try:
            return _download_doc_as_txt(doc_id)
        except Exception as exc:  # noqa: BLE001 — fall through to .txt backup
            fallback_exc = exc
    else:
        fallback_exc = ResumeFetchError(
            f"Could not parse a Google Doc id from: {resume_doc_link!r}"
        )

    txt_path = _fallback_txt(company, role)
    if txt_path:
        return txt_path.read_text(encoding="utf-8", errors="replace").strip()

    raise ResumeFetchError(
        f"Could not fetch resume for {company} / {role}: {fallback_exc}. "
        f"Tip: paste the resume text into resumes/ as a .txt file."
    )


def safe_filename(company: str, role: str, ext: str) -> str:
    """Build a filesystem-safe output filename like ExampleCorp_Data_Scientist.txt."""
    safe_company = re.sub(r"[^\w\-]+", "_", (company or "unknown").strip())
    safe_role = re.sub(r"[^\w\-]+", "_", (role or "role").strip())
    return f"{safe_company}_{safe_role}.{ext}"
