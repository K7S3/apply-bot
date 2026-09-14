# apply-bot

End-to-end job-application automation. For each row in your Excel sheet, the bot:

1. **Fetches** your tailored resume — from the Google Docs link, or from a `.txt` file in `resumes/` as fallback
2. **Reviews & formats** it with AI (Gemini Flash) against the role and job description, then converts the cleaned resume to an upload-ready **PDF** (portals expect doc/rtf/pdf, not .txt)
3. **Applies** on the job site automatically with a real browser (Playwright) — live mode only submits when the resume attached and at least 3 profile fields matched, otherwise the row is flagged for manual finish
4. **Updates** the Excel `status` column after every row
5. **Emails you a summary** of what was applied, what needs a human, and what failed

## Quick start

**1. Install** (Python 3.10+, one time):

```bash
cd apply-bot
pip install -r requirements.txt
playwright install chromium
```

**2. Get a free Gemini API key** at <https://aistudio.google.com> ("Get API key") and set it in your terminal. The key is never stored in any file:

```bash
export GEMINI_API_KEY="paste-your-key-here"
```

**3. Create your profile** — copy the template and replace the placeholders with your real details:

```bash
cp profile.yaml.example profile.yaml
```

`profile.yaml` is git-ignored, so your personal data never gets committed.

**4. Prepare your applications sheet.** Edit `applications.xlsx` (or generate a fresh one with `python -m applybot --make-sample --excel applications.xlsx`):

| Column | What to put |
|---|---|
| `role_title` | e.g. `Data Scientist` |
| `company` | e.g. `Acme Corp` |
| `job_link` | URL of the application page |
| `resume_doc_link` | Google Docs link to the tailored resume (**"Anyone with the link can view"**) |
| `status` | left blank — the bot fills this in |

If a doc is private, paste its text into `resumes/<Company>_<Role>.txt` instead and leave `resume_doc_link` empty.

## CLI modes

| Mode | Command | What it does |
|---|---|---|
| `--dry-run` (default) | `python -m applybot --excel applications.xlsx --dry-run` | Fills every form and screenshots it, but **never submits**. Always run this first. |
| `--check-only` | `python -m applybot --excel applications.xlsx --check-only` | Only the AI resume-review step; no browser. Fast sanity check of resumes. |
| `--live` | `python -m applybot --excel applications.xlsx --live` | Actually submits applications. Asks you to type `YES` first. |

Each run writes to `output/` (git-ignored):

- `<Company>_<Role>.txt` — the AI-cleaned resume text
- `<Company>_<Role>.pdf` — the same resume as a PDF (this is what gets uploaded to the application form)
- `<Company>_<Role>_form.png` — screenshot of the filled application form
- `run_<timestamp>.log` — full per-row log

Status values written back to the Excel sheet: `applied`, `applied (dry-run)`, `needs_manual`, `checked`, `failed: <reason>`.

### Email summaries (optional)

Add an `smtp:` section to `profile.yaml` (see the template) and set the password via environment variable — never in the file:

```bash
export SMTP_PASSWORD="your-app-password"
```

For Gmail, create an **App Password** (Google Account → Security → 2-Step Verification → App passwords). Without SMTP configured, the bot simply skips the email and the run log still has everything.

## Honest limitations

The bot handles standard application forms well, but some rows will need you:

- **Login walls** — if applying requires an account, the row is marked `needs_manual`
- **CAPTCHAs** (reCAPTCHA / hCaptcha) — need a human by design → `needs_manual`
- **Exotic ATS wizards** — some Workday/Greenhouse custom multi-page flows can't be completed automatically → `needs_manual`
- **No guarantees** — always spot-check the screenshots in `output/` before trusting a submission

One bad row never kills a run: every row is isolated, its status is saved immediately, and the bot moves on.

## Files

| Path | What it is |
|---|---|
| `applybot/` | the bot's code |
| `applications.xlsx` | your job list (you edit this) |
| `profile.yaml` | your details (git-ignored; copy from `.example`) |
| `resumes/` | fallback `.txt` resumes |
| `samples/` | test fixtures: fake job pages + a test workbook |
| `output/` | cleaned resumes, screenshots, logs (git-ignored) |

## Switching the AI model

The model name lives in one place — `applybot/config.py`:

```python
MODEL = "gemini-3.7-flash"
```

Change that line when a newer Flash model is released. To try the fixtures in `samples/`, see the test notes in the repo history.
