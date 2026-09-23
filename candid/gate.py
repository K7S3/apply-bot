"""Pre-submit quality gate: a checklist that runs before you apply.

``run_gate`` evaluates a tracked application against the checks that
matter before hitting "submit": is a tailored resume recorded, was the
variant explicitly chosen, is the JD unchanged since tailoring, is it
ATS-clean, is the deadline sane, is contact info complete, is the match
score above the floor, does the resume cover the JD's skill keywords,
and is a cover letter ready.

Each check returns one of three severities:

- ``block``  - do not submit until this is fixed (exit code 2)
- ``warn``   - submittable, but worth a look (exit code 1)
- ``ok``     - passing (exit code 0 when everything passes)

``--strict`` promotes warnings to blocks.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

from candid import config as C

GATE_VERSION = 2

#: Statuses that mean the application was already submitted.
SUBMITTED_STATUSES = {"applied", "selected_for_interview", "offer"}

#: Standard resume section headers the gate looks for.
EXPECTED_SECTIONS = ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}"
)


class GateError(Exception):
    """Raised for invalid gate usage (unknown app, bad flags)."""


def jd_sha(jd_text: str) -> str:
    """Short stable hash of a JD, used to detect JD drift since tailoring."""
    return hashlib.sha256((jd_text or "").encode("utf-8")).hexdigest()[:12]


def _check(check_id: str, title: str, severity: str, message: str,
           fix: str = "") -> dict:
    assert severity in ("ok", "warn", "block"), severity
    return {"id": check_id, "title": title, "severity": severity,
            "message": message, "fix": fix}


# ---------------------------------------------------------------------------
# individual checks (each returns a single check dict)
# ---------------------------------------------------------------------------

def _check_not_submitted(app: dict) -> dict:
    status = app.get("status", "saved")
    if status in SUBMITTED_STATUSES:
        return _check(
            "already_submitted", "Not already submitted", "block",
            f"This application is already '{status}' - submitting again "
            "risks a duplicate application.",
            "If this is a re-application, update the status first, e.g. "
            f"`python -m candid track update {app.get('id')} --status saved`.")
    return _check("already_submitted", "Not already submitted", "ok",
                  f"Status is '{status}' - nothing submitted yet.")


def _check_variant_recorded(app: dict) -> dict:
    variant = app.get("resume_variant") or {}
    if not variant.get("tone"):
        return _check(
            "tailored_resume", "Tailored resume recorded", "block",
            "No tailored resume is recorded for this application.",
            f"Tailor one: `python -m candid tailor resume --app-id {app.get('id')} "
            "--jd jd.txt`")
    return _check(
        "tailored_resume", "Tailored resume recorded", "ok",
        f"Variant recorded: {variant.get('tone')}/{variant.get('length')} "
        f"(tailored {variant.get('created_at', 'unknown date')}).")


def _check_variant_chosen(app: dict) -> dict:
    variant = app.get("resume_variant") or {}
    if not variant.get("tone"):
        return _check("variant_chosen", "Variant explicitly chosen", "ok",
                      "Skipped - no variant recorded yet.")
    if not variant.get("chosen"):
        return _check(
            "variant_chosen", "Variant explicitly chosen", "block",
            f"A {variant.get('tone')}/{variant.get('length')} variant was "
            "generated but never chosen for this application.",
            f"Choose it: `python -m candid track update {app.get('id')} "
            "--variant-chosen` (or re-run tailor with --choose).")
    return _check("variant_chosen", "Variant explicitly chosen", "ok",
                  f"Chosen variant: {variant.get('tone')}/{variant.get('length')}.")


def _check_jd_freshness(app: dict, jd_text: str) -> dict:
    variant = app.get("resume_variant") or {}
    if not jd_text:
        return _check("jd_freshness", "JD unchanged since tailoring", "ok",
                      "Skipped - no JD supplied (pass --jd to verify).")
    if not variant.get("jd_sha"):
        return _check("jd_freshness", "JD unchanged since tailoring", "ok",
                      "Skipped - variant has no recorded JD hash.")
    if jd_sha(jd_text) != variant["jd_sha"]:
        return _check(
            "jd_freshness", "JD unchanged since tailoring", "warn",
            "The JD looks different from the one this resume was tailored "
            "against - bullets may target stale keywords.",
            f"Re-tailor: `python -m candid tailor resume --app-id {app.get('id')} "
            "--jd <new-jd> --choose`.")
    return _check("jd_freshness", "JD unchanged since tailoring", "ok",
                  "JD matches the one the variant was tailored against.")


def _ats_findings(resume_text: str) -> list[dict]:
    """Lightweight ATS parseability checks over the tailored resume text."""
    text = resume_text or ""
    lines = [ln for ln in text.splitlines()]
    findings: list[dict] = []

    if EMAIL_RE.search(text):
        findings.append(_check("ats_email", "ATS: contact email", "ok",
                               "Email address is parseable."))
    else:
        findings.append(_check(
            "ats_email", "ATS: contact email", "block",
            "No email address found in the resume text - the ATS cannot "
            "contact you.",
            "Add a plain-text email near the top, e.g. "
            "`python -m candid profile set --email you@example.com` then re-tailor."))

    if PHONE_RE.search(text):
        findings.append(_check("ats_phone", "ATS: phone number", "ok",
                               "Phone number is parseable."))
    else:
        findings.append(_check(
            "ats_phone", "ATS: phone number", "warn",
            "No phone number found in the resume text.",
            "Add one: `python -m candid profile set --phone \"+1 555-010-1234\"` "
            "then re-tailor."))

    first = next((ln.strip() for ln in lines if ln.strip()), "")
    first_clean = re.sub(r"^#+\s*", "", first)
    if (first_clean and re.search(r"[A-Za-z]{2,}", first_clean)
            and len(first_clean) <= 60 and "@" not in first_clean):
        findings.append(_check("ats_name", "ATS: name on first line", "ok",
                               f"Name parsed from first line: {first_clean}."))
    else:
        findings.append(_check(
            "ats_name", "ATS: name on first line", "warn",
            "Could not parse a name from the first line.",
            "Put your full name alone on the first line of the resume."))

    upper = text.upper()
    missing = [s for s in EXPECTED_SECTIONS if s not in upper]
    if not missing:
        findings.append(_check("ats_sections", "ATS: standard sections", "ok",
                               "Standard section headers found."))
    else:
        findings.append(_check(
            "ats_sections", "ATS: standard sections", "warn",
            f"Missing section headers: {', '.join(missing)}.",
            "Use plain headers like SUMMARY, EXPERIENCE, EDUCATION, SKILLS."))

    table_lines = [ln for ln in lines
                   if ln.count("|") >= 2 and (ln.strip().startswith("|")
                                              or ln.strip().endswith("|"))]
    if table_lines:
        findings.append(_check(
            "ats_tables", "ATS: no pipe tables", "block",
            f"{len(table_lines)} pipe-table row(s) detected - most ATS "
            "parsers scramble tables.",
            "Replace tables with plain bullet lines and re-tailor."))
    else:
        findings.append(_check("ats_tables", "ATS: no pipe tables", "ok",
                               "No pipe tables detected."))

    if len(text) > 8000:
        findings.append(_check(
            "ats_length", "ATS: reasonable length", "warn",
            f"Resume text is {len(text)} characters - likely over two pages.",
            "Prefer the one-page variant: `--length one-page`."))
    else:
        findings.append(_check("ats_length", "ATS: reasonable length", "ok",
                               "Length looks reasonable."))
    return findings


def _check_ats_clean(app: dict) -> list[dict]:
    variant = app.get("resume_variant") or {}
    text = variant.get("resume_text", "")
    if not text:
        return [_check(
            "ats_clean", "ATS-clean resume", "block",
            "No tailored resume text is stored, so ATS parseability cannot "
            "be verified.",
            f"Re-run: `python -m candid tailor resume --app-id {app.get('id')} "
            "--jd jd.txt` (records the text).")]
    return _ats_findings(text)


def _check_deadline(app: dict, today: date,
                    warn_days: int) -> dict:
    raw = (app.get("deadline") or "").strip()
    if not raw:
        return _check(
            "deadline", "Deadline sane", "warn",
            "No deadline recorded for this application.",
            f"Set one: `python -m candid track update {app.get('id')} "
            "--deadline YYYY-MM-DD`.")
    try:
        dl = date.fromisoformat(raw)
    except ValueError:
        return _check(
            "deadline", "Deadline sane", "block",
            f"Recorded deadline {raw!r} is not a valid YYYY-MM-DD date.",
            f"Fix it: `python -m candid track update {app.get('id')} "
            "--deadline YYYY-MM-DD`.")
    delta = (dl - today).days
    if delta < 0:
        return _check(
            "deadline", "Deadline sane", "block",
            f"Deadline {dl.isoformat()} passed {-delta} day(s) ago - this "
            "posting is likely closed.",
            "Verify the posting is still live before applying.")
    if delta <= warn_days:
        return _check(
            "deadline", "Deadline sane", "warn",
            f"Deadline {dl.isoformat()} is in {delta} day(s) - apply soon.",
            "Submit today if the rest of the gate passes.")
    return _check("deadline", "Deadline sane", "ok",
                  f"Deadline {dl.isoformat()} is in {delta} days.")


def _check_contact(profile: dict) -> list[dict]:
    out = []
    if (profile.get("email") or "").strip():
        out.append(_check("contact_email", "Contact: email on file", "ok",
                          f"Email on file: {profile['email'].strip()}."))
    else:
        out.append(_check(
            "contact_email", "Contact: email on file", "block",
            "No email in your profile - applications need one.",
            "Add it: `python -m candid profile set --email you@example.com`."))
    if (profile.get("phone") or "").strip():
        out.append(_check("contact_phone", "Contact: phone on file", "ok",
                          "Phone number on file."))
    else:
        out.append(_check(
            "contact_phone", "Contact: phone on file", "warn",
            "No phone number in your profile.",
            "Add it: `python -m candid profile set --phone \"+1 555-010-1234\"`."))
    if (profile.get("location") or "").strip():
        out.append(_check("contact_location", "Contact: location on file",
                          "ok", f"Location on file: {profile['location'].strip()}."))
    else:
        out.append(_check(
            "contact_location", "Contact: location on file", "warn",
            "No location in your profile - many applications require it.",
            "Add it: `python -m candid profile set --location \"New York, NY\"`."))
    return out


def _check_match_floor(app: dict, profile: dict, jd_text: str,
                       floor: float) -> dict:
    score = None
    source = ""
    if jd_text:
        from candid import match as M
        score = M.score_match(profile, jd_text,
                              title=app.get("role", ""),
                              company=app.get("company", ""))["score"]
        source = "scored just now"
    elif app.get("match_score") is not None:
        score = app["match_score"]
        source = "stored on the application"
    if score is None:
        return _check("match_floor", "Match score above floor", "ok",
                      "Skipped - no JD to score (pass --jd, or store one with "
                      f"`track update {app.get('id')} --match-score N`).")
    if score < floor:
        return _check(
            "match_floor", "Match score above floor", "warn",
            f"Match score {score}/100 is below the floor of {floor} ({source}).",
            "Consider whether this role is worth the application effort - "
            "or strengthen the tailored bullets first.")
    return _check("match_floor", "Match score above floor", "ok",
                  f"Match score {score}/100 clears the floor of {floor} ({source}).")


def _check_cover_letter(app: dict) -> dict:
    cl = app.get("cover_letter") or {}
    if not cl.get("text"):
        return _check(
            "cover_letter", "Cover letter ready", "warn",
            "No cover letter recorded for this application.",
            f"Draft one: `python -m candid tailor cover-letter --app-id {app.get('id')}`.")
    return _check("cover_letter", "Cover letter ready", "ok",
                  f"Cover letter recorded ({cl.get('created_at', 'unknown date')}).")


def _check_keyword_coverage(app: dict, jd_text: str, warn_below: float) -> dict:
    """Re-verify the tailored resume covers the JD's skill keywords."""
    variant = app.get("resume_variant") or {}
    resume_text = variant.get("resume_text", "")
    if not jd_text:
        return _check("keyword_coverage", "JD keyword coverage", "ok",
                      "Skipped - no JD supplied (pass --jd to verify).")
    if not resume_text:
        return _check("keyword_coverage", "JD keyword coverage", "ok",
                      "Skipped - no tailored resume text recorded.")
    from candid import tailor as TL
    cov = TL.keyword_coverage(resume_text, jd_text)
    total = cov["total"]
    if not total:
        return _check("keyword_coverage", "JD keyword coverage", "ok",
                      "No skill keywords extracted from the JD.")
    pct = cov["coverage"]
    if pct < warn_below:
        missing = ", ".join(cov["missing"][:6])
        more = f" (+{len(cov['missing']) - 6} more)" if len(cov["missing"]) > 6 else ""
        return _check(
            "keyword_coverage", "JD keyword coverage", "warn",
            f"Resume covers {len(cov['covered'])}/{total} JD skill keywords "
            f"({pct:.0%}) - below the {warn_below:.0%} bar. "
            f"Missing: {missing}{more}.",
            f"Strengthen the tailored bullets or re-tailor: "
            f"`python -m candid tailor resume --app-id {app.get('id')} "
            "--jd <jd> --choose`.")
    return _check("keyword_coverage", "JD keyword coverage", "ok",
                  f"Resume covers {len(cov['covered'])}/{total} JD skill "
                  f"keywords ({pct:.0%}).")


# ---------------------------------------------------------------------------
# gate runner
# ---------------------------------------------------------------------------

def run_gate(app: dict, profile: dict, *, jd_text: str = "",
             strict: bool = False,
             match_floor: float | None = None,
             deadline_warn_days: int | None = None,
             keyword_coverage_warn_below: float | None = None,
             today: date | None = None) -> dict:
    """Run every pre-submit check. Returns a structured gate result."""
    if match_floor is None:
        match_floor = C.GATE_MATCH_FLOOR
    if deadline_warn_days is None:
        deadline_warn_days = C.GATE_DEADLINE_WARN_DAYS
    if keyword_coverage_warn_below is None:
        keyword_coverage_warn_below = C.GATE_KEYWORD_COVERAGE_WARN
    if today is None:
        today = date.today()

    checks: list[dict] = []
    checks.append(_check_not_submitted(app))
    checks.append(_check_variant_recorded(app))
    checks.append(_check_variant_chosen(app))
    checks.append(_check_jd_freshness(app, jd_text))
    checks.extend(_check_ats_clean(app))
    checks.append(_check_deadline(app, today, deadline_warn_days))
    checks.extend(_check_contact(profile))
    checks.append(_check_match_floor(app, profile, jd_text, match_floor))
    checks.append(_check_keyword_coverage(app, jd_text,
                                          keyword_coverage_warn_below))
    checks.append(_check_cover_letter(app))

    blocks = [c for c in checks if c["severity"] == "block"]
    warns = [c for c in checks if c["severity"] == "warn"]
    oks = [c for c in checks if c["severity"] == "ok"]
    verdict = "BLOCK" if blocks else ("WARN" if warns else "PASS")
    if strict and verdict == "WARN":
        verdict = "BLOCK"
        blocks = blocks + warns
        warns = []

    return {
        "gate_version": GATE_VERSION,
        "verdict": verdict,
        "strict": strict,
        "checks": checks,
        "blocks": [c["id"] for c in blocks],
        "warnings": [c["id"] for c in warns],
        "passed": len(oks),
        "total": len(checks),
    }


def verdict_exit_code(verdict: str) -> int:
    """0 = ready to submit, 1 = warnings only, 2 = blocked."""
    return {"PASS": 0, "WARN": 1, "BLOCK": 2}[verdict]


def summarize(result: dict) -> str:
    n_block = len(result["blocks"])
    n_warn = len(result["warnings"])
    return (f"{result['verdict']}: {result['passed']}/{result['total']} checks passed, "
            f"{n_block} blocking, {n_warn} warnings")


_ICON = {"ok": "[ok]", "warn": "[WARN]", "block": "[BLOCK]"}


def render_report(result: dict, company: str = "", role: str = "") -> str:
    """Human-readable gate report."""
    head = "Pre-submit gate"
    if company or role:
        head += f": {role} @ {company}" if company else f": {role}"
    lines = [head, "=" * len(head), summarize(result), ""]
    for c in result["checks"]:
        lines.append(f"{_ICON[c['severity']]} {c['title']}: {c['message']}")
        if c["fix"] and c["severity"] != "ok":
            lines.append(f"         fix: {c['fix']}")
    lines.append("")
    if result["verdict"] == "PASS":
        lines.append("Ready to submit.")
    elif result["verdict"] == "WARN":
        lines.append("Submittable, but review the warnings above first.")
    else:
        lines.append("BLOCKED - fix the [BLOCK] items above before applying.")
        lines.append("Override (not recommended): re-run with --force where supported,")
        lines.append("or `track update <id> --status applied --gate --force`.")
    return "\n".join(lines)
