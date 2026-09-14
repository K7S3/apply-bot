"""Browser automation: open a job posting and fill the application form.

Strategy (heuristic, works for many simple ATS forms):
  1. Load the job link, detect blockers (login wall, CAPTCHA) -> needs_manual.
  2. Fill text fields by matching labels/placeholders/names to profile keys.
  3. Upload the cleaned resume via <input type="file">.
  4. dry-run (default): screenshot the filled form, DO NOT submit.
     live (--live): click through Continue steps, then click Submit.

Limitations are real: Workday/Greenhouse/Lever custom flows, multi-page
wizards with validation, and anything behind a login will usually land in
`needs_manual`. The runner treats each row independently so one weird
site never kills the whole run.
"""

from __future__ import annotations

from pathlib import Path

from applybot import config as C

# Map profile.yaml keys -> keyword lists matched against each field's
# label / placeholder / name / id (lowercased, substring match).
FIELD_KEYWORDS: dict[str, list[str]] = {
    "first_name": ["first name", "firstname", "given name", "forename"],
    "last_name": ["last name", "lastname", "surname", "family name"],
    "full_name": ["full name", "your name", "applicant name"],
    "email": ["email", "e-mail"],
    "phone": ["phone", "mobile", "telephone", "tel "],
    "location": ["location", "city", "address", "where are you"],
    "linkedin": ["linkedin"],
    "website": ["website", "portfolio", "github", "personal site"],
    "years_experience": ["years of experience", "years experience"],
    "work_authorization": ["authorized to work", "work authorization", "legally authorized"],
    "requires_sponsorship": ["sponsorship", "require sponsorship", "visa sponsorship"],
}

LOGIN_MARKERS = ["log in to apply", "sign in to apply", "create an account to apply"]
CAPTCHA_MARKERS = ["recaptcha", "hcaptcha", "captcha"]


class ApplyError(Exception):
    """Raised for unexpected browser failures (row -> failed)."""


def _field_label_text(page, handle) -> str:
    """Best-effort label for a form control: aria-label, placeholder, <label>, name, id."""
    try:
        info = handle.evaluate(
            """(el) => {
                const label = document.querySelector(`label[for="${el.id}"]`);
                return {
                    aria: el.getAttribute('aria-label') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    labelText: label ? label.innerText : '',
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    type: el.type || el.tagName
                };
            }"""
        )
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(str(v) for v in info.values()).lower()


def detect_blockers(page) -> str | None:
    """Return a blocker reason string, or None if the page looks fillable."""
    try:
        text = (page.content() or "").lower()
    except Exception:  # noqa: BLE001
        return "could not read page content"

    if any(m in text for m in LOGIN_MARKERS):
        return "login wall: site requires sign-in before applying"
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if any(m in url for m in CAPTCHA_MARKERS):
                return "CAPTCHA detected on the application page"
    except Exception:  # noqa: BLE001
        pass
    if 'type="password"' in text and "apply" in text:
        return "login wall: password field on the application page"
    return None


def _match_profile_key(label: str) -> str | None:
    # Check specific keys before generic ones ("first name" before "name").
    for key in ("first_name", "last_name", "full_name"):
        if any(k in label for k in FIELD_KEYWORDS[key]):
            return key
    for key, keywords in FIELD_KEYWORDS.items():
        if key in ("first_name", "last_name", "full_name"):
            continue
        if any(k in label for k in keywords):
            return key
    return None


def fill_form(page, profile: dict) -> int:
    """Fill visible text inputs/textareas from the profile. Returns # filled."""
    filled = 0
    controls = page.locator("input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=submit]), textarea, select")
    for i in range(controls.count()):
        handle = controls.nth(i)
        try:
            if not handle.is_visible() or not handle.is_enabled():
                continue
            label = _field_label_text(page, handle)
            key = _match_profile_key(label)
            if not key or key not in profile or profile[key] in (None, ""):
                continue
            tag = handle.evaluate("(el) => el.tagName")
            if tag == "SELECT":
                try:
                    handle.select_option(label=str(profile[key]))
                    filled += 1
                except Exception:  # noqa: BLE001 — option text didn't match; skip
                    pass
            else:
                handle.fill(str(profile[key]))
                filled += 1
        except Exception:  # noqa: BLE001 — one stubborn field must not stop us
            continue
    return filled


def check_consent_boxes(page) -> int:
    """Check visible agreement/consent checkboxes. Returns # checked."""
    checked = 0
    boxes = page.locator('input[type="checkbox"]')
    for i in range(boxes.count()):
        handle = boxes.nth(i)
        try:
            if not handle.is_visible() or not handle.is_enabled() or handle.is_checked():
                continue
            label = _field_label_text(page, handle)
            if any(w in label for w in ("agree", "consent", "terms", "privacy", "acknowledge")):
                handle.check()
                checked += 1
        except Exception:  # noqa: BLE001
            continue
    return checked


def upload_resume(page, resume_path: Path) -> bool:
    """Attach the resume to the first file input found. Returns success."""
    inputs = page.locator('input[type="file"]')
    for i in range(inputs.count()):
        handle = inputs.nth(i)
        try:
            if handle.is_enabled():
                handle.set_input_files(str(resume_path))
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _click_if_present(page, locator_str: str, timeout: int = 4000) -> bool:
    try:
        loc = page.locator(locator_str).first
        if loc.is_visible():
            loc.click(timeout=timeout)
            page.wait_for_timeout(1500)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def apply_to_job(
    job_link: str,
    resume_path: Path,
    profile: dict,
    *,
    dry_run: bool,
    output_dir: Path,
    company: str,
    role: str,
) -> tuple[str, str]:
    """Run the browser apply flow. Returns (status, reason).

    Status is one of: "applied", "needs_manual", "failed".
    In dry-run mode the form is filled and screenshotted but never submitted.
    """
    try:
        from playwright.sync_api import sync_playwright  # lazy: applier optional for --help
    except ImportError as exc:
        raise ApplyError(
            "playwright is not installed. Run: pip install -r requirements.txt "
            "&& playwright install chromium"
        ) from exc

    from applybot.resume import safe_filename

    base = safe_filename(company, role, "").rstrip(".")
    shot_path = output_dir / f"{base}_form.png"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(C.PAGE_TIMEOUT_MS)
            try:
                page.goto(job_link, timeout=C.NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
            except Exception as exc:  # noqa: BLE001
                return C.STATUS_NEEDS_MANUAL, f"job page did not load: {exc}"

            page_text = (page.content() or "").lower()
            if "already applied" in page_text or "application submitted" in page_text:
                return C.STATUS_APPLIED, "site reports an application was already submitted"

            blocker = detect_blockers(page)
            if blocker:
                return C.STATUS_NEEDS_MANUAL, blocker

            n_filled = fill_form(page, profile)
            n_checked = check_consent_boxes(page)
            uploaded = upload_resume(page, resume_path)
            page.screenshot(path=str(shot_path), full_page=False)

            if dry_run:
                reason = (
                    f"dry-run: filled {n_filled} fields, checked {n_checked} boxes, "
                    f"resume {'uploaded' if uploaded else 'NOT uploaded (no file input found)'}, "
                    f"screenshot saved — NOT submitted"
                )
                return f"{C.STATUS_APPLIED} (dry-run)", reason

            # --- live mode: step through wizards, then submit ----------------
            # Safety guard: never submit a near-empty application. A real
            # submission needs the tailored resume attached and enough profile
            # fields matched that the application identifies the candidate.
            if not uploaded:
                return C.STATUS_NEEDS_MANUAL, (
                    f"live submit blocked: resume could not be attached "
                    f"({n_filled} fields filled) — finish manually"
                )
            if n_filled < 3:
                return C.STATUS_NEEDS_MANUAL, (
                    f"live submit blocked: only {n_filled} fields matched — "
                    "too few to submit safely, finish manually"
                )

            for _ in range(3):  # up to 3 "Continue/Next" wizard steps
                clicked = _click_if_present(
                    page,
                    "button:has-text('Continue'), button:has-text('Next'), "
                    "input[value='Continue'], input[value='Next']",
                )
                if not clicked:
                    break
                fill_form(page, profile)  # new page may have new fields

            submitted = _click_if_present(
                page,
                "button:has-text('Submit Application'), button:has-text('Submit'), "
                "button:has-text('Apply Now'), input[type='submit']",
                timeout=8000,
            )
            page.wait_for_timeout(3000)
            page.screenshot(path=str(shot_path), full_page=False)

            if submitted:
                after = (page.content() or "").lower()
                if any(w in after for w in ("thank you", "received", "submitted", "confirmation")):
                    return C.STATUS_APPLIED, "submitted; confirmation text detected"
                return C.STATUS_APPLIED, "submitted (clicked Submit; confirm on the site)"
            return C.STATUS_NEEDS_MANUAL, (
                f"no Submit button found after filling {n_filled} fields "
                "(custom application flow — finish manually)"
            )
    except ApplyError:
        raise
    except Exception as exc:  # noqa: BLE001 — unexpected browser crash -> failed
        return C.STATUS_FAILED, f"browser error: {exc}"
