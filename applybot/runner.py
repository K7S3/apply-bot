"""Orchestrates the per-row pipeline.

For each application row:
  1. fetch tailored resume text (Google Docs export or resumes/*.txt)
  2. AI review/format with Gemini Flash -> output/<company>_<role>.txt
  3. (unless --check-only) apply via Playwright (dry-run or live)
  4. write status back to the Excel sheet + append to the run log

Every row is wrapped in try/except so one bad row never kills the run.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from applybot import config as C
from applybot import checker, excel_io, jobdesc, mailer, resume as resume_mod
from applybot import resume_pdf


def load_profile(path: str | Path) -> dict:
    """Load profile.yaml (candidate details + smtp config)."""
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("pyyaml is not installed. Run: pip install -r requirements.txt") from exc

    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"Profile not found: {path}\n"
            "Copy profile.yaml.example to profile.yaml and fill in your details."
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class RunLogger:
    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = output_dir / f"run_{stamp}.log"
        self._fh = open(self.path, "w", encoding="utf-8")

    def log(self, msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def process_row(row: dict, profile: dict, log: RunLogger, *, dry_run: bool, check_only: bool) -> dict:
    """Run the full pipeline for one row. Never raises — returns a result dict."""
    role = (row.get(C.COL_ROLE) or "").strip()
    company = (row.get(C.COL_COMPANY) or "").strip()
    job_link = (row.get(C.COL_JOB_LINK) or "").strip()
    resume_link = (row.get(C.COL_RESUME_LINK) or "").strip()
    result = {"role": role, "company": company, "status": C.STATUS_FAILED, "reason": ""}

    try:
        # --- 1. fetch resume text -------------------------------------------
        log.log(f"Fetching resume for {role} @ {company}...")
        resume_text = resume_mod.fetch_resume_text(resume_link, company, role)

        # --- 2. job description (best-effort) --------------------------------
        jd = jobdesc.fetch_job_description(job_link)
        if jd:
            log.log(f"  job description fetched ({len(jd)} chars)")
        else:
            log.log("  job description unavailable — reviewing against role title only")

        # --- 3. AI review/format ---------------------------------------------
        log.log(f"  reviewing resume with {C.MODEL}...")
        cleaned = checker.review_resume(resume_text, role, company, jd)
        out_name = resume_mod.safe_filename(company, role, "txt")
        out_path = C.OUTPUT_DIR / out_name
        out_path.write_text(cleaned, encoding="utf-8")
        log.log(f"  cleaned resume saved to output/{out_name}")

        # --- 3b. PDF for upload (portals expect doc/rtf/pdf, not .txt) --------
        pdf_name = resume_mod.safe_filename(company, role, "pdf")
        pdf_path = C.OUTPUT_DIR / pdf_name
        resume_pdf.text_to_pdf(cleaned, pdf_path)
        log.log(f"  upload-ready PDF saved to output/{pdf_name}")

        if check_only:
            result["status"] = "checked"
            result["reason"] = f"resume reviewed and saved to output/{out_name} (no browser step)"
            return result

        # --- 4. apply via browser ---------------------------------------------
        if not job_link:
            result["status"] = C.STATUS_NEEDS_MANUAL
            result["reason"] = "no job_link in the Excel row"
            return result

        # The applier is imported lazily so --check-only works without playwright.
        from applybot import applier

        log.log(f"  opening application page ({'dry-run' if dry_run else 'LIVE'})...")
        status, reason = applier.apply_to_job(
            job_link,
            pdf_path,
            profile,
            dry_run=dry_run,
            output_dir=C.OUTPUT_DIR,
            company=company,
            role=role,
        )
        result["status"] = status
        result["reason"] = reason
        return result

    except Exception as exc:  # noqa: BLE001 — per-row isolation
        result["status"] = C.STATUS_FAILED
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result


def run(excel_path: str | Path, profile_path: str | Path, *, dry_run: bool, check_only: bool) -> list[dict]:
    """Run the pipeline over every row in the workbook."""
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile = load_profile(profile_path)
    rows, ctx = excel_io.load_applications(excel_path)
    log = RunLogger(C.OUTPUT_DIR)

    mode = "check-only" if check_only else ("dry-run" if dry_run else "LIVE")
    log.log(f"Starting applybot ({mode}) — {len(rows)} application(s) from {excel_path}")

    results: list[dict] = []
    try:
        for i, row in enumerate(rows, 1):
            # Resume support: skip rows that already carry a terminal status
            # (applied / needs_manual / failed / skipped_*), so a re-run only
            # processes fresh rows.
            prior = (row.get(C.COL_STATUS) or "").strip()
            if prior:
                log.log(
                    f"--- [{i}/{len(rows)}] {row.get(C.COL_ROLE)} @ {row.get(C.COL_COMPANY)} "
                    f"--- skipped (status already '{prior}')"
                )
                results.append(
                    {
                        "role": row.get(C.COL_ROLE),
                        "company": row.get(C.COL_COMPANY),
                        "status": f"skipped ({prior})",
                        "reason": "",
                    }
                )
                continue
            log.log(f"--- [{i}/{len(rows)}] {row.get(C.COL_ROLE)} @ {row.get(C.COL_COMPANY)} ---")
            result = process_row(row, profile, log, dry_run=dry_run, check_only=check_only)
            results.append(result)
            log.log(f"  => {result['status']}: {result['reason']}")
            ctx.set_status(row["_excel_row"], result["status"])
            ctx.save(excel_path)  # persist after every row, not just at the end
        log.log(f"Done. Excel statuses updated in {excel_path}")
    finally:
        log.close()

    # --- 5. email summary ------------------------------------------------------
    try:
        mailer.send_summary(profile, results, dry_run=dry_run or check_only)
    except Exception as exc:  # noqa: BLE001 — email failure must not fail the run
        print(f"[mailer] Could not send summary: {exc}")

    return results
