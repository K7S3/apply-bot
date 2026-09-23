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


log = C.get_logger("dashboard")


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
    """Saved jobs with match scores and apply links — structured.

    Jobs dismissed via POST /api/jobs/dismiss are filtered out here.
    """
    from candid import tracker as T, jobs as J
    dismissed = dismissed_ids()
    out = []
    for a in T.list_apps(status="saved"):
        if a["id"] in dismissed["app_ids"]:
            continue
        meta = J.get_job_meta(a["id"])
        sid = _source_id_for_app(a["id"]) or meta.get("source_id") or ""
        if sid and sid in dismissed["source_ids"]:
            continue
        out.append({
            "app_id": a["id"],
            "company": a["company"],
            "role": a["role"],
            "score": meta.get("match_score"),
            "source": meta.get("source"),
            "source_id": sid,
            "url": meta.get("source_url") or a.get("jd_link") or "",
            "date_added": a.get("date_added", ""),
            "has_jd": bool(meta.get("jd_text")),
        })
    return out


def run_curate(role: str, location: str = "", remote: bool = False,
               level: str | None = None, limit: int = 15,
               sources: list | None = None) -> dict:
    """Run a job-curation pass from the dashboard.

    Returns the human-readable summary plus the structured result.
    """
    from candid import jobs as J, profile as Prof
    if not (role or "").strip():
        raise DashboardError("role is required (e.g. 'Data Scientist').")
    profile = Prof.load_profile()
    try:
        result = J.curate(profile, role=role, location=location or "",
                          remote=bool(remote), level=level or None,
                          limit=int(limit or 15), sources=sources or None)
    except J.JobsError as e:
        raise DashboardError(str(e)) from e
    return {
        "summary": J.render_curated(result),
        "fetched": result["fetched"],
        "candidates": result["candidates"],
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
    }


# ---------------------------------------------------------------------------
# dismissed curated jobs (sidecar state — jobs.py itself is untouched)
# ---------------------------------------------------------------------------

def _dismissed_path() -> Path:
    return C.DATA_DIR / "dismissed_jobs.json"


def _jobs_seen() -> dict:
    """Read jobs.py's own {source_id: app_id} map (read-only).

    This is how a curated tracker record is traced back to the job-board
    posting that produced it.
    """
    p = C.DATA_DIR / "jobs.json"
    if p.exists():
        try:
            seen = json.loads(p.read_text(encoding="utf-8")).get("seen", {})
            return seen if isinstance(seen, dict) else {}
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    return {}


def _source_id_for_app(app_id: int) -> str:
    for sid, aid in _jobs_seen().items():
        if aid == app_id:
            return str(sid)
    return ""


def dismissed_ids() -> dict:
    """{'source_ids': set[str], 'app_ids': set[int]} of dismissed jobs."""
    p = _dismissed_path()
    data: dict = {"source_ids": [], "app_ids": []}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data["source_ids"] = raw.get("source_ids", [])
                data["app_ids"] = raw.get("app_ids", [])
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    return {"source_ids": {str(s) for s in data["source_ids"]},
            "app_ids": {int(i) for i in data["app_ids"] if str(i).isdigit()}}


def _save_dismissed(d: dict) -> None:
    C.ensure_data_dirs()
    _dismissed_path().write_text(json.dumps({
        "source_ids": sorted(d["source_ids"]),
        "app_ids": sorted(d["app_ids"]),
    }, indent=2), encoding="utf-8")


def dismiss_job(source_id: str | None = None,
                app_id: int | None = None) -> dict:
    """Hide a curated job without tracking it.

    Accepts a curation ``source_id`` and/or a tracker ``app_id`` (resolved
    to its source_id via jobs.py's ``seen`` map). Dismissed jobs disappear
    from ``curated_jobs()`` and the dashboard's curated-jobs section.
    """
    if app_id is not None:
        try:
            app_id = int(app_id)
        except (TypeError, ValueError):
            raise DashboardError(f"Bad app_id: {app_id!r}")
        if not source_id:
            source_id = _source_id_for_app(app_id)
    if not source_id and app_id is None:
        raise DashboardError("Provide a source_id or an app_id to dismiss.")
    d = dismissed_ids()
    if source_id:
        d["source_ids"].add(str(source_id))
    if app_id is not None:
        d["app_ids"].add(app_id)
    _save_dismissed(d)
    log.debug("dismissed job source_id=%r app_id=%r", source_id, app_id)
    return {"dismissed": True, "source_id": str(source_id or ""),
            "app_id": app_id}


def run_tailor_diff(kind: str, company: str, role: str, jd: str,
                    tone: str = "confident", length: str = "one-page") -> dict:
    """Tailored text + keyword coverage vs the JD.

    Returns {text, coverage: {covered: [...], missing: [...]}, changes: []}.
    Coverage is computed from the same skill lexicon ``match`` uses, so the
    chips agree with the match breakdown.
    """
    from candid import tailor as T, profile as Prof, match as M
    if kind not in ("resume", "cover-letter"):
        raise DashboardError("kind must be 'resume' or 'cover-letter'.")
    if not (jd or "").strip():
        raise DashboardError("Paste a job description first.")
    profile = Prof.load_profile()
    if kind == "resume":
        text = T.build_resume(profile, jd, company=company, role=role,
                              tone=tone, length=length)
    else:
        text = T.build_cover_letter(profile, jd, company=company, role=role,
                                    tone=tone, hook="")
    must, nice = M._jd_skills(jd)
    pskills = set(profile.get("skills", []))
    wanted = must | nice
    return {
        "text": text,
        "coverage": {
            "covered": sorted(wanted & pskills),
            "missing": sorted(wanted - pskills),
        },
        "changes": [],
    }


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
# audit trail (read-only)
# ---------------------------------------------------------------------------

def audit_entries(limit: int | None = None, entity: str | None = None,
                  action: str | None = None, query: str = "") -> list[dict]:
    """Read-only audit trail: entries newest-first, with optional filters.

    ``query`` does a substring search (delegates to audit.search);
    otherwise audit.read applies the entity/action filters.
    """
    from candid import audit as A
    if query:
        entries = A.search(query)
    else:
        entries = A.read(entity=entity or None, action=action or None)
    if limit is not None:
        entries = entries[:limit]
    return entries


def audit_verify() -> dict:
    """Tamper check for the audit log. Returns {"ok", "problems"}."""
    from candid import audit as A
    problems = A.verify()
    return {"ok": not problems, "problems": problems}


def _qs_int(qs: dict, name: str) -> int | None:
    """Parse an integer query param; None when missing or invalid."""
    raw = (qs.get(name, [None])[0] or "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


_AUDIT_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>candid - Audit trail</title>
<style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;
padding:0 1rem;color:#1a1a1a;background:#fff}
h1{font-size:1.6rem;margin-bottom:0}
.sub{color:#555;margin-top:.3rem}
form#filters{display:flex;flex-wrap:wrap;gap:.6rem;align-items:flex-end;
margin:1.2rem 0}
label{font-size:.85rem;color:#333;display:flex;flex-direction:column;gap:.2rem}
input,button{font:inherit;padding:.35rem .5rem;border:1px solid #bbb;
border-radius:.3rem}
button{cursor:pointer;background:#f3f3f3}
button:hover{background:#e9e9e9}
#verifyResult{margin:.5rem 0;font-weight:600}
#verifyResult.ok{color:#0a6b2d}
#verifyResult.bad{color:#a31515}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{border:1px solid #ddd;padding:.4rem .5rem;text-align:left;
vertical-align:top}
th{background:#f6f6f6}
td.ts{white-space:nowrap}
details{font-size:.82rem}
pre{white-space:pre-wrap;word-break:break-word;margin:.3rem 0;max-height:
200px;overflow:auto;background:#fafafa;padding:.4rem;border:1px solid #eee}
.readonly{font-size:.85rem;color:#555;border:1px dashed #bbb;border-radius:
.3rem;padding:.6rem .8rem;margin:1rem 0;background:#fcfcfc}
</style>
</head>
<body>
<h1>Audit trail</h1>
<p class="sub">Every recorded change, newest first. <a href="/">Back to dashboard</a></p>
<div class="readonly">This view is read-only: the log can only grow (or be
pruned by age from the CLI). Undo happens through tracker snapshots, never by
editing the log.</div>
<form id="filters">
<label>entity<input name="entity" placeholder="tracker"></label>
<label>action<input name="action" placeholder="create / update / remove"></label>
<label>search<input name="q" placeholder="company, command, note..."></label>
<label>limit<input name="limit" value="200" size="6"></label>
<button type="submit">Filter</button>
<button type="button" id="verifyBtn">Verify integrity</button>
</form>
<div id="verifyResult"></div>
<table id="entries">
<thead><tr><th>when</th><th>actor</th><th>command</th><th>entity</th>
<th>entity id</th><th>action</th><th>changes</th></tr></thead>
<tbody></tbody>
</table>
<script>
const tbody = document.querySelector("#entries tbody");
const vres = document.querySelector("#verifyResult");
const esc = s => String(s == null ? "" : s)
  .replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",
  '"':"&quot;","'":"&#39;"}[c]));
function changeSummary(e){
  const ch = e.changes || [];
  if(!ch.length) return esc(e.note || "");
  const fields = ch.map(c => esc(c.field)).join(", ");
  const extra = ch.length > 6 ? " (+ " + (ch.length - 6) + " more)" : "";
  return "fields: " + ch.slice(0, 6).map(c => esc(c.field)).join(", ") + extra
    + '<details><summary>details</summary><pre>'
    + esc(JSON.stringify(ch, null, 1)) + "</pre></details>";
}
function render(entries){
  tbody.innerHTML = entries.map(e =>
    "<tr><td class=ts>" + esc(e.ts) + "</td><td>" + esc(e.actor) + "</td><td>" +
    esc(e.command) + "</td><td>" + esc(e.entity) + "</td><td>" +
    esc(e.entity_id) + "</td><td>" + esc(e.action) + "</td><td>" +
    changeSummary(e) + "</td></tr>").join("")
    || '<tr><td colspan="7">No entries match.</td></tr>';
}
async function load(){
  const q = new URLSearchParams(new FormData(document.querySelector("#filters")));
  const res = await fetch("/api/audit?" + q);
  render(await res.json());
}
document.querySelector("#filters").addEventListener("submit", ev => {
  ev.preventDefault(); load();
});
document.querySelector("#verifyBtn").addEventListener("click", async () => {
  const res = await fetch("/api/audit/verify");
  const v = await res.json();
  vres.className = v.ok ? "ok" : "bad";
  vres.textContent = v.ok ? "Integrity OK: hash chain verified."
    : "Problems: " + v.problems.join("; ");
});
load();
</script>
</body>
</html>"""


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
        log.debug("GET %s", self.path)
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
            elif path == "/audit":
                self._serve_audit_page()
            elif path == "/api/audit":
                _send_json(self, audit_entries(
                    limit=(_qs_int(qs, "limit")
                           if "limit" in qs else 200),
                    entity=qs.get("entity", [None])[0],
                    action=qs.get("action", [None])[0],
                    query=qs.get("q", [""])[0]))
            elif path == "/api/audit/verify":
                _send_json(self, audit_verify())
            else:
                _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            log.debug("GET %s -> 400: %s", self.path, e)
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 — never leak tracebacks to UI
            log.warning("GET %s -> 500: %s: %s", self.path,
                        type(e).__name__, e)
            _send_json(self, {"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ctype = self.headers.get("Content-Type", "")
        log.debug("POST %s", self.path)
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
                log.debug("POST %s (upload) -> 400: %s", self.path, e)
                _send_json(self, {"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name in ("GmailError", "LinkedInError", "ValueError"):
                    log.debug("POST %s (upload) -> 400: %s: %s",
                              self.path, name, e)
                    _send_json(self, {"error": str(e)}, 400)
                else:
                    log.warning("POST %s (upload) -> 500: %s: %s",
                                self.path, name, e)
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
            if path == "/api/curate":
                _send_json(self, run_curate(
                    role=body.get("role", ""),
                    location=body.get("location", ""),
                    remote=bool(body.get("remote", False)),
                    level=body.get("level") or None,
                    limit=body.get("limit", 15),
                    sources=body.get("sources") or None))
                return
            if path == "/api/jobs/dismiss":
                _send_json(self, dismiss_job(
                    source_id=body.get("source_id"),
                    app_id=body.get("app_id")))
                return
            if path == "/api/tailor-diff":
                _send_json(self, run_tailor_diff(
                    body.get("kind", "resume"), body.get("company", ""),
                    body.get("role", ""), body.get("jd", ""),
                    tone=body.get("tone", "confident"),
                    length=body.get("length", "one-page")))
                return
            _send_json(self, {"error": "not found"}, 404)
        except DashboardError as e:
            log.debug("POST %s -> 400: %s", self.path, e)
            _send_json(self, {"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            # map known domain errors to 400
            name = type(e).__name__
            if name in ("TrackerError", "PrepError", "GmailError", "OnboardError",
                        "MatchError", "JobsError", "ValueError"):
                log.debug("POST %s -> 400: %s: %s", self.path, name, e)
                _send_json(self, {"error": str(e)}, 400)
            else:
                log.warning("POST %s -> 500: %s: %s", self.path, name, e)
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

    def _serve_audit_page(self):
        """Serve the read-only Audit trail page (inline HTML)."""
        body = _AUDIT_PAGE_HTML.encode("utf-8")
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
