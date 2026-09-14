"""Shared configuration constants for applybot.

Bump MODEL here when a newer Gemini Flash model is released.
Secrets (GEMINI_API_KEY, SMTP_PASSWORD) are NEVER stored here —
they come from environment variables only.
"""

import os
from pathlib import Path

# --- AI model ---------------------------------------------------------------
# Local Ollama model (no API keys, no quotas, no cost). The server must be
# running (~/workspace/ollama-start.sh) with the model pulled.
# Change these two lines to switch models everywhere in the pipeline.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-r1:8b")
OLLAMA_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "1500"))
# Kept for display / backwards compatibility with the old Gemini path.
MODEL = f"{OLLAMA_MODEL} (local Ollama)"

# --- Input / output paths ---------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESUMES_DIR = PROJECT_ROOT / "resumes"
OUTPUT_DIR = PROJECT_ROOT / "output"

# --- Excel schema -----------------------------------------------------------
# applications.xlsx must have these columns (order does not matter).
# The bot adds/updates the `status` column itself.
COL_ROLE = "role_title"
COL_COMPANY = "company"
COL_JOB_LINK = "job_link"
COL_RESUME_LINK = "resume_doc_link"
COL_STATUS = "status"

REQUIRED_COLUMNS = [COL_ROLE, COL_COMPANY, COL_JOB_LINK, COL_RESUME_LINK]

# --- Status values written back to the Excel sheet --------------------------
STATUS_PENDING = ""            # not attempted yet
STATUS_APPLIED = "applied"     # submitted (live) or fully filled (dry-run)
STATUS_NEEDS_MANUAL = "needs_manual"  # login wall / CAPTCHA / other blocker
STATUS_FAILED = "failed"       # unexpected error (reason appended)

# --- Browser / network tuning -----------------------------------------------
PAGE_TIMEOUT_MS = 30_000
NAVIGATION_TIMEOUT_MS = 45_000
JOB_DESC_MAX_CHARS = 6_000     # cap on scraped job-description text
RESUME_MAX_CHARS = 12_000      # cap on resume text sent to the model

# --- Environment variables --------------------------------------------------
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
SMTP_PASSWORD_ENV = "SMTP_PASSWORD"


def gemini_api_key() -> str | None:
    """Return the Gemini API key from the environment (None if unset)."""
    return os.environ.get(GEMINI_API_KEY_ENV)


def smtp_password() -> str | None:
    """Return the SMTP password from the environment (None if unset)."""
    return os.environ.get(SMTP_PASSWORD_ENV)
