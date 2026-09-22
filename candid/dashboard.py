"""Local web dashboard for candid.

``python -m candid dashboard`` starts a server on 127.0.0.1 and opens it in
your browser. Everything is served from your machine; the server binds
localhost only, needs no accounts, no keys, no network.

The UI itself lives in ``candid/data/dashboard.html`` (single file, no CDN,
works fully offline). This module exposes the JSON API it talks to — the
data functions are importable and unit-tested independently of HTTP.
"""

from __future__ import annotations

import http.server
import json
import re
import tempfile
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from candid import config as C


class DashboardError(Exception):
    """Raised for dashboard operation problems."""


# ---------------------------------------------------------------------------
# data functions (pure logic — testable without HTTP)
# ---------------------------------------------------------------------------

def overview() -> dict:
    """Funnel stats, counts, nudges, integration status — one payload."""
    from candid import tracker as T, nudges as N, gmail
    from candid import profile as P
    stats = T.stats()
    try:
        prof = P.load_profile()
        profile_info = {"has_profile": True, "name": prof.get("name", ""),
                        "headline": prof.get("headline", "")}
    except Exception:
        profile_info = {"has_profile": False, "name": "", "headline": ""}
    return {
        "funnel": stats["counts"],
        "total": stats["total"],
        "response_rate": stats["response_rate"],
        "interview_rate": stats["interview_rate"],
        "offer_rate": stats["offer_rate"],
        "nudges": N.pending_nudges(),
        "nudge_count": len(N.pending_nudges()),
        # import model: candid never connects to accounts — the user exports
        # their own data and feeds it in. Only proposal counts are surfaced.
        "gmail": {"pending_proposals": len(gmail.list_proposals(status="pending"))},
        "gmail_pending_proposals": len(gmail.list_proposals(status="pending")),
        "profile": profile_info,
        "curated_count": len(curated_jobs()),
    }


IMPORT_PATTERN = """\
How to add a new source (the generic pattern):

1. The user exports their own data from the source (Takeout, data-export
   archive, CSV download, …) — candid never connects to accounts.
2. Add a module under candid/ that parses the export into plain dicts.
3. Wire it into `candid import` (candid/__main__.py), the dashboard's
   "Import your data" section (candid/dashboard.py + data/dashboard.html),
   and add fixture-based tests under tests/.
"""


def import_guides() -> dict:
    """Step-by-step export instructions per source, for the dashboard."""
    from candid import gmail, linkedin
    return {
        "gmail": {"title": "Gmail — Google Takeout mbox",
                  "steps": gmail.TAKEOUT_GUIDE.strip().splitlines(),
                  "accept": ".mbox",
                  "command": "python -m candid gmail import /path/to/your.mbox"},
        "linkedin": {"title": "LinkedIn — official data-export archive",
                     "steps": linkedin.EXPORT_GUIDE.strip().splitlines(),
                     "accept": ".zip",
                     "command": "python -m candid linkedin import --zip /path/to/LinkedIn-export.zip"},
        "pattern": {"title": "Any other source",
                    "steps": IMPORT_PATTERN.strip().splitlines()},
    }


def run_import(source: str, path: str | Path) -> dict:
    """Run an import from a user-supplied export file. Returns a summary."""
    source = (source or "").lower()
    if source == "gmail":
        from candid import gmail
        res = gmail.import_mbox(path)
        return {"source": "gmail",
                "files": res["files"],
                "messages": res["messages"],
                "new_proposals": len(res["new_proposals"]),
                "proposals": res["new_proposals"],
                "summary": gmail.render_import_summary(res)}
    if source == "linkedin":
        from candid import linkedin
        res = linkedin.import_zip(str(path))
        prof = res["profile"]
        return {"source": "linkedin",
                "mode": res["mode"],
                "positions": res["positions"],
                "skills": res["skills"],
                "education": res["education"],
                "summary": (f"LinkedIn import ({res['mode']}): {res['positions']} positions, "
                            f"{res['skills']} skills, {res['education']} education entries. "
                            f"Profile: {prof.get('name', '')} — {prof.get('headline', '')}.")}
    raise DashboardError(f"Unknown import source: {source!r} "
                         "(expected 'gmail' or 'linkedin').")


def detect_source(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".mbox"):
        return "gmail"
    if name.endswith(".zip"):
        return "linkedin"
    return None


def list_apps_filtered(status: str | None = None, query: str = "") -> list[dict]:
    from candid import config as C
    from candid import tracker as T
    if status and status not in C.STATUSES:
        return []  # unknown filter value → empty, not a 500
    apps = T.list_apps(status=status or None)
    if query:
        ql = query.lower()
        apps = [a for a in apps
                if ql in a.get("company", "").lower()
                or ql in a.get("role", "").lower()
                or ql in a.get("notes", "").lower()]
    return apps


def curated_jobs() -> list[dict]:
    """Saved jobs with match scores and apply links — structured."""
    from candid import tracker as T, jobs as J
    out = []
    for a in T.list_apps(status="saved"):
        meta = J.get_job_meta(a["id"])
        out.append({
            "app_id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "score": meta.get("match_score"),
            "source": meta.get("source"),
            "url": meta.get("source_url") or a.get("jd_link") or "",
            "date_added": a.get("date_added", ""),
            "has_jd": bool(meta.get("jd_text")),
        })
    return out


def prep_status() -> list[dict]:
    """Per-application interview-prep state (interview-stage apps only)."""
    from candid import tracker as T
    out = []
    for a in T.list_apps():
        if a.get("status") not in ("selected_for_interview", "offer"):
            continue
        pack = a.get("prep_pack", "")
        has_pack = bool(pack) and Path(pack).exists()
        out.append({
            "app_id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "status": a["status"],
            "has_pack": has_pack,
            "pack_path": pack if has_pack else "",
        })
    return out


def run_prep(company: str, role: str, app_id: int | None = None,
             jd: str = "", location: str = "") -> dict:
    from candid import prep as P, profile as Prof, tracker as T
    if not company or not role:
        raise DashboardError("company and role are required.")
    profile = Prof.load_profile()
    markdown, path = P.build_pack(profile, company, role, jd=jd,
                                  app_id=app_id, location=location)
    if app_id:
        T.update(app_id, prep_pack=str(path))
    return {"path": str(path), "chars": len(markdown)}


def run_match(jd: str, company: str = "", role: str = "",
              location: str = "") -> dict:
    from candid import match as M, profile as Prof
    if not jd.strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    result = M.score_match(profile, jd, title=role, company=company, location=location)
    result["report"] = M.render_report(result, company=company, title=role)
    return result


def update_status(app_id: int, status: str) -> dict:
    """Change an application's status from the dashboard."""
    from candid import config as C
    from candid import tracker as T
    if status not in C.STATUSES:
        raise DashboardError(f"Unknown status: {status!r}")
    try:
        return T.update(app_id, status=status)
    except T.TrackerError as e:
        raise DashboardError(str(e)) from e


def proposal_list(status: str = "pending") -> list[dict]:
    """Pending Gmail proposals awaiting confirmation."""
    from candid import gmail
    return gmail.list_proposals(status=status)


def confirm_proposal(proposal_id: int) -> dict:
    """Confirm a Gmail proposal → writes to the tracker."""
    from candid import gmail
    try:
        return gmail.confirm_proposal(proposal_id)
    except gmail.GmailError as e:
        raise DashboardError(str(e)) from e


def reject_proposal(proposal_id: int) -> None:
    """Dismiss a Gmail proposal."""
    from candid import gmail
    try:
        gmail.reject_proposal(proposal_id)
    except gmail.GmailError as e:
        raise DashboardError(str(e)) from e


def run_tailor(kind: str, company: str, role: str, jd: str,
               tone: str = "confident", length: str = "one-page") -> dict:
    from candid import tailor as T, profile as Prof
    if kind not in ("resume", "cover-letter"):
        raise DashboardError("kind must be 'resume' or 'cover-letter'.")
    if not jd.strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    if kind == "resume":
        text = T.build_resume(profile, jd, company=company, role=role,
                              tone=tone, length=length)
    else:
        text = T.build_cover_letter(profile, jd, company=company, role=role,
                                    tone=tone, hook="")
    C.ensure_data_dirs()
    safe = re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}-{kind}".lower()).strip("-")
    out = C.TAILOR_DIR / f"{safe}.md"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "text": text}


def salary_lookup(company: str, title: str, location: str = "") -> dict:
    from candid import salary as S
    return S.lookup(company=company, title=title, location=location)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

HTML_PATH = C.PACKAGE_ROOT / "data" / "dashboard.html"


def _send_json(handler: http.server.BaseHTTPRequestHandler, obj,
               status: int = 200) -> None:
    body = json.dumps(obj).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict, dict]:
    """Minimal multipart/form-data parser (stdlib only).

    Returns (fields, files) where files maps field name ->
    (filename, bytes). Good enough for a local dashboard file picker.
    """
    m = re.search(r"boundary=([^;]+)", content_type or "")
    if not m:
        raise DashboardError("multipart upload without a boundary.")
    boundary = ("--" + m.group(1).strip().strip('"')).encode()
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in body.split(boundary)[1:-1]:
        head, _, data = part.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = head.decode("latin-1", errors="replace")
        nm = re.search(r'name="([^"]+)"', headers)
        if not nm:
            continue
        fn = re.search(r'filename="([^"]*)"', headers)
        if fn and fn.group(1):
            files[nm.group(1)] = (fn.group(1), data)
        else:
            fields[nm.group(1)] = data.decode("utf-8", errors="replace")
    return fields, files


def _read_upload(handler: http.server.BaseHTTPRequestHandler) -> tuple[str, bytes]:
    """Read a multipart file upload. Returns (filename, bytes)."""
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if not length:
        raise DashboardError("Empty upload.")
    if length > 500 * 1024 * 1024:
        raise DashboardError("File too large (500 MB limit).")
    body = handler.rfile.read(length)
    _, files = _parse_multipart(body, handler.headers.get("Content-Type", ""))
    if "file" not in files:
        raise DashboardError("No file field in upload.")
    return files["file"]


def _read_json(handler: http.server.BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    server_version = "candid-dashboard/1.0"

    def log_message(self, *args):  # keep the CLI quiet
        pass

    # -- routing ---------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                self._serve_html()
            elif path == "/api/overview":
                _send_json(self, overview())
            elif path == "/api/apps":
                _send_json(self, list_apps_filtered(
                    status=qs.get("status", [None])[0],
                    query=qs.get("q", [""])[0]))
            elif path == "/api/jobs":
                _send_json(self, curated_jobs())
            elif path == "/api/prep-status":
                _send_json(self, prep_status())
            elif path == "/api/nudges":
                from candid import nudges as N
                _send_json(self, N.pending_nudges())
            elif path == "/api/salary":
                _send_json(self, salary_lookup(
                    qs.get("company", [""])[0], qs.get("title", [""])[0],
                    qs.get("location", [""])[0]))
            elif path == "/api/proposals":
                _send_json(self, proposal_list(
                    status=qs.get("status", [None])[0]))
            elif path == "/api/import-guides":
                _send_json(self, import_guides())
            else:
                _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 — never leak tracebacks to UI
            _send_json(self, {"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ctype = self.headers.get("Content-Type", "")
        # file uploads bypass the JSON reader (it would consume rfile)
        if path == "/api/import" and "multipart/form-data" in ctype:
            try:
                filename, data = _read_upload(self)
                source = detect_source(filename)
                if not source:
                    _send_json(self, {"error":
                        f"Can't detect source for {filename!r} — "
                        "use a .mbox (Gmail Takeout) or .zip (LinkedIn export)."}, 400)
                    return
                tmp = Path(tempfile.gettempdir()) / f"candid-import-{filename}"
                tmp.write_bytes(data)
                try:
                    _send_json(self, {**run_import(source, tmp),
                                      "filename": filename})
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            except DashboardError as e:
                _send_json(self, {"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name in ("GmailError", "LinkedInError", "ValueError"):
                    _send_json(self, {"error": str(e)}, 400)
                else:
                    _send_json(self, {"error": f"{name}: {e}"}, 500)
            return
        body = _read_json(self)
        try:
            m = re.fullmatch(r"/api/apps/(\d+)", path)
            if m:
                try:
                    rec = update_status(int(m.group(1)),
                                        body.get("status", ""))
                except DashboardError as e:
                    code = 404 if "No application" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                    return
                _send_json(self, rec)
                return
            if path == "/api/prep":
                _send_json(self, run_prep(
                    body.get("company", ""), body.get("role", ""),
                    app_id=body.get("app_id"), jd=body.get("jd", ""),
                    location=body.get("location", "")))
                return
            if path == "/api/match":
                _send_json(self, run_match(
                    body.get("jd", ""), company=body.get("company", ""),
                    role=body.get("role", ""),
                    location=body.get("location", "")))
                return
            if path == "/api/tailor":
                _send_json(self, run_tailor(
                    body.get("kind", "resume"), body.get("company", ""),
                    body.get("role", ""), body.get("jd", ""),
                    tone=body.get("tone", "confident"),
                    length=body.get("length", "one-page")))
                return
            m = re.fullmatch(r"/api/proposals/(\d+)/(confirm|reject)", path)
            if m:
                pid, action = int(m.group(1)), m.group(2)
                try:
                    if action == "confirm":
                        _send_json(self, confirm_proposal(pid))
                    else:
                        reject_proposal(pid)
                        _send_json(self, {"ok": True, "id": pid})
                except DashboardError as e:
                    code = 404 if "No proposal" in str(e) else 400
                    _send_json(self, {"error": str(e)}, code)
                return
            if path == "/api/import":
                src_name = (body.get("source") or "").lower()
                src_path = body.get("path", "")
                if not src_name or not src_path:
                    _send_json(self, {"error":
                        "Provide {\"source\": \"gmail\"|\"linkedin\", "
                        "\"path\": \"/path/to/export\"}."}, 400)
                    return
                _send_json(self, run_import(src_name, src_path))
                return
            _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            # map known domain errors to 400
            name = type(e).__name__
            if name in ("TrackerError", "PrepError", "GmailError", "OnboardError",
                        "MatchError", "ValueError"):
                _send_json(self, {"error": str(e)}, 400)
            else:
                _send_json(self, {"error": f"{name}: {e}"}, 500)

    def _serve_html(self):
        try:
            body = HTML_PATH.read_bytes()
        except OSError:
            _send_json(self, {"error": "dashboard.html missing"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8765, open_browser: bool = True,
          handler_class=DashboardHandler):
    """Start the dashboard server (blocking). Binds 127.0.0.1 only."""
    server = None
    last_err = None
    for p in range(port, port + 10):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", p),
                                                     handler_class)
            port = p
            break
        except OSError as e:
            last_err = e
    if server is None:
        raise DashboardError(f"Could not bind a port near {port}: {last_err}")
    url = f"http://127.0.0.1:{port}/"
    print(f"📊 candid dashboard: {url}")
    print("   Local only — nothing leaves your machine. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
