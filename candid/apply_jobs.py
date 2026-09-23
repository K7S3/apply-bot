"""Job specs for the apply pipeline.

Ports applybot/config.py's JobSpec to candid conventions: ``resume_pdf``
is optional (falls back to the tailored resume in ``candid.config.TAILOR_DIR``),
and errors are raised as ``ApplyJobsError``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from candid import config

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


class ApplyJobsError(Exception):
    """Raised when a job spec is invalid or a resume cannot be found."""


@dataclass
class JobSpec:
    id: str
    company: str
    role: str
    url: str
    resume_pdf: str = ""
    ats: str = "generic"  # adapter hint: generic | greenhouse | lever | ashby ...

    @classmethod
    def load(cls, path: str | Path) -> "JobSpec":
        """Load and validate a job spec from a YAML file."""
        if yaml is None:
            raise ApplyJobsError(
                "pyyaml is required to load job specs; "
                "install it with: pip install pyyaml"
            )
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for required in ("id", "company", "role", "url"):
            if not data.get(required):
                raise ApplyJobsError(
                    f"job spec {path} is missing required key: {required}"
                )
        url = str(data["url"])
        if not url.startswith(("http://", "https://")):
            raise ApplyJobsError(
                f"job spec {path} has an invalid url (must start with "
                f"http:// or https://): {url}"
            )
        return cls(
            id=str(data["id"]),
            company=str(data["company"]),
            role=str(data["role"]),
            url=url,
            resume_pdf=str(data.get("resume_pdf") or ""),
            ats=str(data.get("ats") or "generic"),
        )


def _slug(text: str) -> str:
    """Lowercase slug: runs of non-alphanumerics become a single "-".

    Mirrors how ``candid tailor`` names its outputs
    (<company>-<role>.pdf under TAILOR_DIR).
    """
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def tailored_resume_name(spec: JobSpec) -> str:
    """Filename candid tailor would produce for this spec: <company>-<role>.pdf."""
    return f"{_slug(spec.company)}-{_slug(spec.role)}.pdf"


def resolve_resume(spec: JobSpec) -> Path:
    """Resolve the resume PDF for a job spec.

    1. If ``spec.resume_pdf`` is set and the file exists, use it.
    2. Otherwise look for the tailored resume in ``candid.config.TAILOR_DIR``
       (``<sanitized-company>-<sanitized-role>.pdf``).
    3. Otherwise raise ``ApplyJobsError`` with guidance.
    """
    if spec.resume_pdf:
        p = Path(spec.resume_pdf).expanduser()
        if p.exists():
            return p.resolve()
    candidate = config.TAILOR_DIR / tailored_resume_name(spec)
    if candidate.exists():
        return candidate.resolve()
    raise ApplyJobsError(
        f"no resume found for job {spec.id!r}: set resume_pdf in the job spec, "
        f"or run `candid tailor resume --out {candidate}` and convert it to PDF"
    )
