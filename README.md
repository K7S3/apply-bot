# applybot 🤖

End-to-end job application automation. For each row in your Excel sheet, the bot:

1. **Fetches** your tailored resume (from the Google Docs link, or a `.txt` in `resumes/`)
2. **Reviews & formats** it with AI (Gemini Flash) against the role
3. **Applies** on the job site automatically (Playwright browser)
4. **Updates** the Excel `status` column and **emails you a summary**

## Quick start (do this once)

**1. Install Python 3.10+**, then install the dependencies:

```bash
cd apply-bot
pip install -r requirements.txt
playwright install chromium
```

**2. Get a free Gemini API key** at <https://aistudio.google.com> ("Get API key"),
then set it in your terminal (the key is never stored in any file):

```bash
export GEMINI_API_KEY="paste-your-key-here"
```

**3. Create your profile** — copy the template and fill in your real details:

```bash
cp profile.yaml.example profile.yaml
# then open profile.yaml in any text editor and replace the PLACEHOLDERs
```

`profile.yaml` holds personal data and is git-ignored, so it never gets committed.

**4. Prepare your applications sheet.** Either edit `applications.xlsx` directly
or generate a fresh sample:

```bash
python -m applybot --make-sample --excel applications.xlsx
```

Columns: `role_title` | `company` | `job_link` | `resume_doc_link` | `status`
(the bot fills in `status` itself: `applied`, `needs_manual`, `failed: <reason>`).

> The Google Docs links must be shared as **"Anyone with the link can view"**,
> otherwise the bot can't download the resume text. If a doc is private, paste
> its text into `resumes/<Company>_<Role>.txt` instead.

## Running it

```bash
# Step 1 — ALWAYS run this first: fills every form, screenshots it, never submits
python -m applybot --excel applications.xlsx --dry-run

# Step 2 — only the AI review step, no browser (fast sanity check)
python -m applybot --excel applications.xlsx --check-only

# Step 3 — actually submit applications (asks for YES confirmation first)
python -m applybot --excel applications.xlsx --live
```

After each run you'll find in `output/`:
- `<Company>_<Role>.txt` — the AI-cleaned resume that was used
- `<Company>_<Role>_form.png` — screenshot of the filled application form
- `run_<timestamp>.log` — full log of what happened per row

And (if SMTP is configured in `profile.yaml` + `SMTP_PASSWORD` is set) a summary
email. For Gmail, create an **App Password** (Google Account → Security →
2-Step Verification → App passwords) and use that as `SMTP_PASSWORD` — never
your real Gmail password:

```bash
export SMTP_PASSWORD="your-app-password"
```

## What the bot can and can't do

**Can:**
- Review, fix typos/formatting, and lightly tailor each resume per role
- Fill standard application forms (name, email, phone, location, LinkedIn, work auth…)
- Upload the resume file and click through simple Continue/Submit flows

**Can't (these rows get `needs_manual` and the run continues):**
- Log in to a site for you — if the application is behind an account login,
  you'll need to apply manually (or log in once in a headed browser first)
- Solve CAPTCHAs (reCAPTCHA / hCaptcha) — those need a human by design
- Handle exotic multi-page ATS wizards (some Workday/Greenhouse custom flows)
- Guarantee submission — always spot-check the screenshots and confirmation emails

If a row fails unexpectedly, the reason is saved in the `status` column and the
run log, and the bot moves on to the next row.

## Files

| Path | What it is |
|---|---|
| `applybot/` | the bot's code |
| `applications.xlsx` | your job list (you edit this) |
| `profile.yaml` | your details (git-ignored; copy from `.example`) |
| `resumes/` | fallback `.txt` resumes |
| `output/` | cleaned resumes, screenshots, logs (git-ignored) |

## Switching the AI model

The model name lives in one place — `applybot/config.py`:

```python
MODEL = "gemini-3.7-flash"
```

Change that line to bump to a newer Flash model when one is released.
