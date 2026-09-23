"""Bulk JD import: score many job descriptions at once, ranked by fit.

    python -m candid bulk --jd-dir ./jds/
    python -m candid bulk --jd-files a.txt b.txt --top 10 --min-score 60
    python -m candid bulk --jd-dir ./jds/ --manifest meta.csv --json

All scoring goes through ``candid.match.score_match`` -- this module only
collects files, resolves company/role metadata, ranks, and renders. Filenames
may encode metadata as ``Company__Role.txt``; a ``--manifest`` CSV with
``file,company,role`` columns overrides the filename guess. Unreadable files
are skipped with a clean warning on stderr, never a traceback.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from candid import config as C
from candid import match as M


class BulkError(Exception):
    """Raised for expected bulk-import failures (empty dir, bad manifest, ...)."""


#: File extensions picked up when scanning --jd-dir (explicit --jd-files
#: accept any extension).
JD_EXTENSIONS = (".txt", ".md", ".markdown")

#: How many missing must-haves to show per row of the ranked table.
_TOP_MISSING = 3


def company_role_from_filename(path: str | Path) -> tuple[str, str]:
    """Guess (company, role) from a filename like ``AcmeCorp__Data-Scientist.txt``.

    Returns ("", "") parts when nothing can be guessed; never raises.
    """
    stem = Path(path).stem
    if "__" in stem:
        company, role = stem.split("__", 1)
    else:
        company, role = stem, ""
    company = company.strip()
    role = re.sub(r"[-_]+", " ", role).strip()
    # bare stems like "senior-data-scientist" with no company marker are a
    # role guess, not a company guess.
    if not role and company and re.search(r"[-_]", stem):
        return "", re.sub(r"[-_]+", " ", stem).strip()
    return company, role


def parse_manifest(path: str | Path) -> dict[str, tuple[str, str]]:
    """Parse a ``--manifest`` CSV into {basename -> (company, role)}.

    Headers accepted: ``file``/``filename``, ``company``, ``role``/``title``.
    ``file`` may be a bare name or a relative path -- matching is by basename.
    """
    p = Path(path)
    if not p.is_file():
        raise BulkError(
            f"Manifest {p} not found. Create a CSV with "
            "`file,company,role` columns, then run "
            f"`python -m candid bulk --manifest {p}`."
        )
    try:
        rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    except Exception as exc:
        raise BulkError(
            f"Could not read manifest {p}: {exc}. It should be a CSV with "
            "`file,company,role` columns."
        ) from exc
    if not rows:
        raise BulkError(
            f"Manifest {p} has no data rows. Add `file,company,role` rows, then run "
            f"`python -m candid bulk --manifest {p}`."
        )
    headers = {h.strip().lower() for h in (rows[0].keys() or [])}
    file_key = next((k for k in ("file", "filename") if k in headers), None)
    role_key = next((k for k in ("role", "title") if k in headers), None)
    if file_key is None or "company" not in headers or role_key is None:
        raise BulkError(
            f"Manifest {p} needs `file,company,role` header columns "
            f"(found: {sorted(headers)}). Fix the header row, then run "
            f"`python -m candid bulk --manifest {p}`."
        )
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        name = (r.get(file_key) or "").strip()
        if not name:
            continue
        out[Path(name).name] = (
            (r.get("company") or "").strip(),
            (r.get(role_key) or "").strip(),
        )
    return out


def collect_jd_files(jd_dir: str | Path | None = None,
                     jd_files: list[str | Path] | None = None) -> list[Path]:
    """Collect JD file paths from a directory and/or an explicit list.

    Directory scans are non-recursive and sorted. Raises BulkError when
    nothing was given or nothing was found.
    """
    files: list[Path] = []
    if jd_dir:
        d = Path(jd_dir)
        if not d.is_dir():
            raise BulkError(
                f"{d} is not a directory. Pass a folder of JD text files, "
                f"e.g. `python -m candid bulk --jd-dir {d}` after creating it, "
                "or list files explicitly with --jd-files."
            )
        files.extend(
            sorted(p for p in d.iterdir()
                   if p.is_file() and p.suffix.lower() in JD_EXTENSIONS)
        )
    for f in jd_files or []:
        p = Path(f)
        if p not in files:
            files.append(p)
    files.sort()
    if not files:
        where = f" in {jd_dir}" if jd_dir else ""
        raise BulkError(
            f"No JD files found{where}. Put .txt/.md JDs in the folder or pass "
            f"explicit paths, then run `python -m candid bulk --jd-dir DIR` "
            f"(or `python -m candid bulk --jd-files a.txt b.txt`)."
        )
    return files


def read_jd_file(path: Path) -> str:
    """Read JD text; raises BulkError for unreadable/too-short files."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BulkError(f"Could not read {path.name}: {exc}") from exc
    if len(text.strip()) < 50:
        raise BulkError(f"{path.name} looks empty (< 50 chars of text)")
    return text[:20000]


def score_all(profile: dict,
              jd_dir: str | Path | None = None,
              jd_files: list[str | Path] | None = None,
              manifest: str | Path | None = None,
              min_score: float = 0.0) -> dict:
    """Score every JD file; return {"results": [...], "warnings": [...]}.

    ``results`` are sorted by score, descending, filtered to
    ``score >= min_score``. Each result: file, company, role, score,
    verdict, missing_must_haves (top missing must-have skills). Bad files
    are skipped with a warning, never an exception.
    """
    meta = parse_manifest(manifest) if manifest else {}
    files = collect_jd_files(jd_dir=jd_dir, jd_files=jd_files)
    results: list[dict] = []
    warnings: list[str] = []
    for f in files:
        try:
            text = read_jd_file(f)
        except BulkError as exc:
            warnings.append(f"skipped {f.name}: {exc}")
            continue
        company, role = meta.get(f.name) or company_role_from_filename(f)
        result = M.score_match(profile, text, title=role, company=company)
        results.append({
            "file": f.name,
            "company": company,
            "role": role,
            "score": result["score"],
            "verdict": result["verdict"],
            "missing_must_haves": sorted(result.get("missing_skill_pointers", {}))[:_TOP_MISSING],
        })
    results = [r for r in results if r["score"] >= min_score]
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"results": results, "warnings": warnings}


def render_table(results: list[dict], top: int | None = None) -> str:
    """Render the ranked table: score, verdict, company, role, missing must-haves."""
    if top is not None and top < 1:
        raise BulkError(
            f"--top {top} makes no sense. Pass a positive number, "
            "e.g. `python -m candid bulk --jd-dir DIR --top 10`."
        )
    rows = results[:top] if top else list(results)
    if not rows:
        return "No JDs matched the filter. Lower --min-score and run again:\n  python -m candid bulk --jd-dir DIR"
    cols = ["score", "verdict", "company", "role", "missing must-haves"]
    body = [[
        f"{r['score']:.1f}",
        r["verdict"],
        r["company"] or "-",
        r["role"] or "-",
        ", ".join(r["missing_must_haves"]) or "-",
    ] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in body)) for i, c in enumerate(cols)]
    header = "  ".join(c.upper().ljust(w) for c, w in zip(cols, widths))
    sep = "  ".join("-" * w for w in widths)
    lines = [header, sep]
    for row in body:
        lines.append("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
    lines.append(f"\n{len(rows)} JD(s) ranked" +
                 (f" (top {top})" if top else "") +
                 f"; highest score {rows[0]['score']:.1f}.")
    return "\n".join(lines)
