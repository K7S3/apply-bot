"""Master resume as the source of truth for all tailored variants.

The master resume is the canonical, complete record of the user's
experience. Every tailored variant (see versions.py) is *derived* from a
specific master version, and that derivation is recorded so any variant
can be traced back to the exact master text it came from.

Storage (under DATA_DIR/master_resume/, git-ignored, CANDID_DATA_DIR
overridable for tests):
    current.json      metadata of the current version
                      {version_id, content_hash, created_at, note, source}
    versions/vNNNN.md markdown of each master version (history kept)
    lineage.json      variant_id -> {kind, master_version, content_hash,
                                     recorded_at}

GOLDEN RULE: the master is the only place new facts enter the system.
Tailored variants and bullet rewrites must never invent experience,
metrics, percentages, tools, or achievements that are not in the master.
When information is missing, ask the user for it.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C
from candid import profile as profile_mod


class MasterResumeError(Exception):
    """Raised when the master resume store cannot be read or written."""


MASTER_DIR_NAME = "master_resume"


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """User data dir, read at call time so CANDID_DATA_DIR works in tests."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _store_dir() -> Path:
    return _data_dir() / MASTER_DIR_NAME


def _versions_dir() -> Path:
    return _store_dir() / "versions"


def _current_path() -> Path:
    return _store_dir() / "current.json"


def _lineage_path() -> Path:
    return _store_dir() / "lineage.json"


def _content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _version_id(n: int) -> str:
    return f"v{n:04d}"


_VERSION_RE = re.compile(r"^v(\d{4})\.md$")


def _existing_versions() -> list[str]:
    d = _versions_dir()
    if not d.exists():
        return []
    ids = [p.stem for p in d.glob("v*.md") if _VERSION_RE.match(p.name)]
    return sorted(ids)


def _next_version_id() -> str:
    existing = _existing_versions()
    n = max((int(_VERSION_RE.match(v + ".md").group(1)) for v in existing),
            default=0)
    return _version_id(n + 1)


def _version_path(version_id: str) -> Path:
    return _versions_dir() / f"{version_id}.md"


def _read_current() -> dict:
    p = _current_path()
    if not p.exists():
        raise MasterResumeError(
            "No master resume initialized. Run init_master() first."
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MasterResumeError(
            f"Master resume metadata at {p} is not valid JSON: {exc}"
        ) from exc


def _write_current(meta: dict) -> None:
    _store_dir().mkdir(parents=True, exist_ok=True)
    _current_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _read_lineage() -> dict:
    p = _lineage_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MasterResumeError(
            f"Lineage file at {p} is not valid JSON: {exc}"
        ) from exc
    return data if isinstance(data, dict) else {}


def _write_lineage(data: dict) -> None:
    _store_dir().mkdir(parents=True, exist_ok=True)
    _lineage_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# building the master markdown
# ---------------------------------------------------------------------------

def build_master_markdown(profile: dict) -> str:
    """Render a canonical master-resume markdown from an onboarded profile."""
    lines: list[str] = []
    name = (profile.get("name") or "").strip()
    lines.append(f"# {name}" if name else "# Master Resume")
    headline = (profile.get("headline") or "").strip()
    location = (profile.get("location") or "").strip()
    sub = " | ".join(p for p in (headline, location) if p)
    if sub:
        lines.append("")
        lines.append(sub)

    summary = (profile.get("summary") or "").strip()
    if summary:
        lines += ["", "## Summary", "", summary]

    skills = profile.get("skills") or []
    if skills:
        lines += ["", "## Skills", "", ", ".join(skills)]

    experience = profile.get("experience") or []
    if experience:
        lines += ["", "## Experience", ""]
        for e in experience:
            title = (e.get("title") or "").strip()
            company = (e.get("company") or "").strip()
            header = " — ".join(p for p in (title, company) if p) or "(role)"
            lines.append(f"### {header}")
            dates = (e.get("dates") or "").strip()
            if dates:
                lines.append(dates)
            for b in e.get("bullets") or []:
                b = b.strip()
                if b:
                    lines.append(f"- {b}")
            lines.append("")

    education = profile.get("education") or []
    if education:
        lines += ["## Education", ""]
        for ed in education:
            school = (ed.get("school") or "").strip()
            degree = (ed.get("degree") or "").strip()
            dates = (ed.get("dates") or "").strip()
            entry = ", ".join(p for p in (degree, school) if p)
            if dates:
                entry += f" ({dates})"
            if entry:
                lines.append(f"- {entry}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _store_version(markdown: str, note: str, source: str) -> dict:
    """Write a new version file + current.json; return the metadata."""
    version_id = _next_version_id()
    _versions_dir().mkdir(parents=True, exist_ok=True)
    _version_path(version_id).write_text(markdown, encoding="utf-8")
    meta = {
        "version_id": version_id,
        "content_hash": _content_hash(markdown),
        "created_at": _utcnow(),
        "note": note,
        "source": source,
    }
    _write_current(meta)
    return {**meta, "markdown": markdown}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def init_master(profile: dict | None = None,
                resume_path: str | Path | None = None,
                note: str = "") -> dict:
    """Build the canonical master resume and store it as the first version.

    Source, in order of preference:
      1. ``resume_path`` — a supplied resume markdown/text file is used
         verbatim as the master markdown.
      2. ``profile`` — a profile dict (as built by candid.profile) is
         rendered to markdown.
      3. neither — the onboarded profile is loaded from DATA_DIR.

    (Re-)initializing resets version history. Returns the stored version
    metadata plus the markdown.
    """
    if resume_path is not None:
        markdown = profile_mod.read_document(resume_path)
        source = f"resume_file:{resume_path}"
        profile_name = ""
    else:
        prof = profile if profile is not None else profile_mod.load_profile()
        markdown = build_master_markdown(prof)
        profile_name = (prof.get("name") or "").strip()
        source = "profile:" + (profile_name or "onboarded")

    # fresh init: reset history
    store = _store_dir()
    if store.exists():
        for p in _versions_dir().glob("v*.md"):
            p.unlink()
        if _lineage_path().exists():
            _lineage_path().unlink()

    meta = _store_version(markdown, note or "initial master resume", source)
    return meta


def get_master() -> dict:
    """Return the current master resume: markdown + metadata.

    Raises MasterResumeError if init_master() has not been run.
    """
    meta = _read_current()
    path = _version_path(meta["version_id"])
    if not path.exists():
        raise MasterResumeError(
            f"Master version {meta['version_id']} file is missing at {path}."
        )
    return {**meta, "markdown": path.read_text(encoding="utf-8")}


def get_version(version_id: str) -> dict:
    """Return a specific historical master version (markdown + metadata)."""
    path = _version_path(version_id)
    if not path.exists():
        raise MasterResumeError(f"Unknown master version: {version_id}")
    return {
        "version_id": version_id,
        "content_hash": _content_hash(path.read_text(encoding="utf-8")),
        "markdown": path.read_text(encoding="utf-8"),
    }


def update_master(new_markdown: str, note: str = "") -> dict:
    """Save a new master version, keeping history.

    If the content is identical to the current version, no new version is
    created and the current metadata is returned with ``unchanged=True``.
    """
    new_markdown = (new_markdown or "").strip() + "\n"
    if len(new_markdown.strip()) < 20:
        raise MasterResumeError("New master markdown is empty — not saved.")
    current = _read_current()
    if _content_hash(new_markdown) == current["content_hash"]:
        return {**current, "markdown": new_markdown, "unchanged": True}
    meta = _store_version(new_markdown, note, source="manual_update")
    return {**meta, "unchanged": False}


def record_variant(variant_id: str, kind: str) -> dict:
    """Link a tailored variant to the master version it was generated from.

    Idempotent: recording the same variant twice keeps the *original*
    master version it was derived from (lineage must not move), updating
    only the kind and timestamp. Returns the stored lineage record.
    """
    if not variant_id or not variant_id.strip():
        raise MasterResumeError("variant_id must be a non-empty string.")
    current = _read_current()
    data = _read_lineage()
    vid = variant_id.strip()
    if vid in data:
        record = data[vid]
        record["kind"] = kind
        record["recorded_at"] = _utcnow()
        record["duplicate"] = True
    else:
        record = {
            "variant_id": vid,
            "kind": kind,
            "master_version": current["version_id"],
            "content_hash": current["content_hash"],
            "recorded_at": _utcnow(),
        }
        data[vid] = record
    _write_lineage(data)
    return record


def lineage(variant_id: str) -> dict:
    """Show the variant -> master version chain for a recorded variant."""
    data = _read_lineage()
    record = data.get((variant_id or "").strip())
    if record is None:
        raise MasterResumeError(
            f"No lineage recorded for variant '{variant_id}'. "
            "Use record_variant() when a tailored variant is generated."
        )
    return dict(record)


def diff_versions(v1: str, v2: str) -> str:
    """Unified diff of two master versions' markdown (v1 -> v2)."""
    a = get_version(v1)["markdown"].splitlines(keepends=True)
    b = get_version(v2)["markdown"].splitlines(keepends=True)
    diff = difflib.unified_diff(a, b, fromfile=f"{v1}.md", tofile=f"{v2}.md")
    return "".join(diff)


_BULLET_MARK = re.compile(r"^\s*[•·▪◦\-\*\+–—>]\s+")
_HEADER_RE = re.compile(r"^\s*#{2,4}\s+(.*\S)\s*$")
# e.g. "Jan 2020 - Present" or "2020 - 2022"
_DATE_LINE_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|\b\d{4}\b",
    re.I,
)


def master_bullets() -> list[dict]:
    """Structured bullets from the current master, for tailor to consume.

    Each bullet carries its role context (title/company/dates) so tailored
    generation stays grounded in the master. Returns a list of
    {text, role, company, dates, bullet_hash}.
    """
    master = get_master()
    bullets: list[dict] = []
    role = ""
    company = ""
    dates = ""
    for raw in master["markdown"].splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HEADER_RE.match(raw)
        if m:
            header = m.group(1)
            if raw.lstrip().startswith("###"):
                # "Title — Company" shape
                parts = [p.strip() for p in re.split(r"\s+—\s+|\s+-\s+",
                                                     header) if p.strip()]
                role = parts[0] if parts else header
                company = parts[1] if len(parts) > 1 else ""
            else:
                role, company = header, ""
            dates = ""
            continue
        if _BULLET_MARK.match(raw):
            text = _BULLET_MARK.sub("", raw).strip()
            if text:
                bullets.append({
                    "text": text,
                    "role": role,
                    "company": company,
                    "dates": dates,
                    "bullet_hash": hashlib.sha256(
                        text.encode("utf-8")).hexdigest()[:12],
                })
            continue
        # a short date-ish line right under a role header is the dates line
        if role and not dates and len(line) < 80 and _DATE_LINE_RE.search(line):
            dates = line
    return bullets
