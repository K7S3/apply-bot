"""candid.legacy — end-to-end job application automation.

Pipeline per application row:
  1. Fetch the tailored resume text (Google Docs export, or resumes/*.txt fallback)
  2. AI review/format with Gemini Flash (checker.py)
  3. Apply via Playwright (dry-run fills everything, live submits)
  4. Update the Excel status column + run log
  5. Email a summary when the run finishes
"""

__version__ = "0.1.0"
