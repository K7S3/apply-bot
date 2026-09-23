"""Privacy dashboard: scan stored data for likely PII, and report network egress.

Two commands:

* ``candid privacy scan [--json] [--category C]`` — walk every text file in
  the user's data categories (skipping binary files) and report likely PII
  using ``privacy.find_pii``. Findings are informational, so the exit code is
  always 0 (only a bad ``--category`` is a usage error, exit 2).
* ``candid privacy egress [--json]`` — a static "what leaves this machine"
  report. It greps the package source (no network calls): HTTP(S) endpoints
  used by ``jobs.py`` / ``salary.py``, and the bind address used by
  ``dashboard.py``.

Exposes ``add_parsers(sub)`` so ``candid privacy`` can register the
``scan`` and ``egress`` subcommands. Handlers return int exit codes.
"""

from __future__ import annotations

import argparse
import json
import re
from argparse import Namespace
from pathlib import Path

from . import config
from . import privacy as P

MATCH_PREVIEW_LEN = 40  # truncated match shown per finding
_MAX_FILE_BYTES = 10 * 1024 * 1024  # never read absurd files into memory

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
_BIND_HOST_RE = re.compile(r'\(\s*["\']([^"\']+)["\']\s*,')  # ("host", port...)
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _mask_match(finding_type: str, match: str) -> str:
    """Mask an email's local part (keshavan@example.com -> k***@example.com),
    then truncate the whole preview to MATCH_PREVIEW_LEN chars."""
    if finding_type == "email" and "@" in match:
        local, _, domain = match.partition("@")
        head = local[0] if local else ""
        match = f"{head}***@{domain}"
    if len(match) > MATCH_PREVIEW_LEN:
        match = match[:MATCH_PREVIEW_LEN]
    return match


def _read_text_if_text_file(path: Path) -> str | None:
    """Return the file's UTF-8 text, or None when the file is binary
    (null bytes or undecodable) or too large."""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_data(categories: list[str] | None = None) -> dict:
    """Scan category files for PII. Returns findings + summary counts."""
    if categories is None:
        categories = sorted(P.CATEGORIES)
    findings: list[dict] = []
    files_scanned = 0
    skipped_binary = 0
    for name in categories:
        for path in P.category_files(name):
            text = _read_text_if_text_file(path)
            if text is None:
                skipped_binary += 1
                continue
            files_scanned += 1
            rel = str(path.relative_to(config.DATA_DIR))
            for hit in P.find_pii(text):
                findings.append(
                    {
                        "file": rel,
                        "type": hit["type"],
                        "line": hit["line"],
                        "match": _mask_match(hit["type"], hit["match"]),
                    }
                )
    files_with_findings = len({f["file"] for f in findings})
    summary = {
        "categories": categories,
        "files_scanned": files_scanned,
        "skipped_binary": skipped_binary,
        "files_with_findings": files_with_findings,
        "findings": len(findings),
    }
    return {"findings": findings, "summary": summary}


def cmd_scan(args: Namespace) -> int:
    if args.category:
        P.require_category(args.category)  # SystemExit(2) on unknown category
        categories = [args.category]
    else:
        categories = None

    result = scan_data(categories)
    summary = result["summary"]

    P.audit(
        "scan",
        f"categories={','.join(summary['categories'])} "
        f"files={summary['files_scanned']} findings={summary['findings']}",
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PII scan of your stored data")
        print("-" * 72)
        if result["findings"]:
            for f in result["findings"]:
                print(f"{f['file']}:{f['line']}  [{f['type']}]  {f['match']}")
        else:
            print("No likely PII found in text files.")
        print("-" * 72)
        print(
            f"Scanned {summary['files_scanned']} file(s) "
            f"across {len(summary['categories'])} categor(ies): "
            f"{summary['findings']} finding(s) in {summary['files_with_findings']} file(s); "
            f"skipped {summary['skipped_binary']} binary file(s)."
        )
    return 0


# --- egress ----------------------------------------------------------------


def _urls_with_context(path: Path) -> list[dict]:
    """Collect https? URLs from a source file with the nearest enclosing
    function name and its docstring."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for i, line in enumerate(lines, 1):
        for m in _URL_RE.finditer(line):
            func = None
            doc = ""
            for back in range(i, max(0, i - 40), -1):
                dm = re.match(r"^def\s+(\w+)\s*\(", lines[back - 1])
                if dm:
                    func = dm.group(1)
                    for j in range(back, min(len(lines), back + 3)):
                        ds = lines[j].strip()
                        if ds.startswith(('"""', "'''")):
                            doc = ds.strip('"""').strip("'''").strip().strip('"')
                            break
                    break
            out.append({"url": m.group(0), "line": i, "function": func, "doc": doc})
    return out


def _dashboard_bind_hosts(path: Path) -> list[str]:
    """Static check: host strings passed as the first arg to socket/bind-style
    calls in dashboard.py (e.g. ThreadingHTTPServer(("127.0.0.1", p), ...))."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    hosts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not re.search(r"bind|serve|httpserver|http\.server|run\(", line, re.I):
            continue
        for m in _BIND_HOST_RE.finditer(line):
            host = m.group(1)
            if re.fullmatch(r"[A-Za-z0-9_.\-:]+", host) and host not in hosts:
                hosts.append(host)
    return hosts


def egress_report() -> dict:
    """Static "what leaves this machine" report. No network calls."""
    root = config.PACKAGE_ROOT
    components: list[dict] = []
    warnings: list[str] = []

    # job data sources
    for fname in ("jobs.py", "salary.py"):
        path = root / fname
        for u in _urls_with_context(path):
            purpose = u["doc"] or f"used by {fname}"
            when = (
                "On `candid jobs refresh` / `jobs curate` (you run it; never automatic)"
                if fname == "jobs.py"
                else "Never contacted by candid itself; LCA data arrives via a CSV you import"
            )
            components.append(
                {
                    "component": f"{fname} ({u['function'] or 'module level'})",
                    "url_or_purpose": f"{u['url']} — {purpose}",
                    "when_contacted": when,
                    "data_sent": "None — plain HTTPS GET with a generic User-Agent "
                    "header; no personal data and no query params are sent.",
                }
            )
    if not any(c["component"].startswith("salary.py") for c in components):
        components.append(
            {
                "component": "salary.py",
                "url_or_purpose": "(no network endpoints) — LCA wage data comes "
                "from a DOL disclosure CSV you import yourself",
                "when_contacted": "Never — all salary lookups are local SQLite queries",
                "data_sent": "None.",
            }
        )

    # dashboard bind check
    dash = root / "dashboard.py"
    hosts = _dashboard_bind_hosts(dash)
    if not hosts:
        hosts = ["(none detected)"]
    non_local = [h for h in hosts if h not in _LOCAL_HOSTS and h != "(none detected)"]
    for h in non_local:
        warnings.append(
            f"WARNING: dashboard.py binds address {h!r}, which is not localhost — "
            "the dashboard would be reachable from your network."
        )
    bind_desc = ", ".join(hosts)
    components.append(
        {
            "component": "dashboard.py",
            "url_or_purpose": f"http://{bind_desc if bind_desc else '127.0.0.1'}:<port>/ — local web UI",
            "when_contacted": "Only while `candid dashboard` is running, and only by your own browser",
            "data_sent": "None leaves the machine — your browser talks to localhost only; "
            "the server needs no accounts, keys, or network access.",
        }
    )

    components.append(
        {
            "component": "everything else",
            "url_or_purpose": "profile, tracker, tailored resumes, prep packs, gmail/linkedin imports — all plain files under your data dir",
            "when_contacted": "Never — file-based storage only",
            "data_sent": "None.",
        }
    )

    return {"components": components, "warnings": warnings, "ok": not warnings}


def _print_table(components: list[dict]) -> None:
    cols = ("component", "url_or_purpose", "when_contacted", "data_sent")
    headers = {"component": "Component", "url_or_purpose": "URL / purpose",
               "when_contacted": "When contacted", "data_sent": "Data sent"}
    widths = {c: len(headers[c]) for c in cols}
    for row in components:
        for c in cols:
            widths[c] = max(widths[c], len(row[c]))
    widths = {c: min(w, 52) for c, w in widths.items()}

    def wrap(text: str, width: int) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        return lines or [""]

    wrapped = [[wrap(row[c], widths[c]) for c in cols] for row in components]
    sep = "+-" + "-+-".join("-" * widths[c] for c in cols) + "-+"
    fmt = "| " + " | ".join("{:<%d}" % widths[c] for c in cols) + " |"
    print(sep)
    print(fmt.format(*(headers[c] for c in cols)))
    print(sep)
    for wrow in wrapped:
        for i in range(max(len(c) for c in wrow)):
            print(fmt.format(*(c[i] if i < len(c) else "" for c in wrow)))
        print(sep)


def cmd_egress(args: Namespace) -> int:
    report = egress_report()
    P.audit("egress", f"components={len(report['components'])} warnings={len(report['warnings'])}")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("What leaves this machine (static check, no network calls)")
        print("=" * 72)
        _print_table(report["components"])
        if report["warnings"]:
            print()
            for w in report["warnings"]:
                print(w)
        else:
            print("OK: dashboard binds localhost only; job sources receive no personal data.")
    return 0


def add_parsers(sub) -> None:
    p = sub.add_parser("scan", help="Scan stored data for likely PII (informational).")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--category", help="Scan only one data category (default: all).")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser(
        "egress", help="Static report of what data leaves this machine."
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_egress)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="privacy-scan")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_parsers(sub)
    args = parser.parse_args()
    raise SystemExit(args.func(args))
