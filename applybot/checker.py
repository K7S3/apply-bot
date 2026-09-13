"""AI resume review/formatting step, powered by Gemini Flash.

Takes the tailored resume text plus role context and asks the model to:
  - fix typos, grammar, and formatting inconsistencies
  - tighten bullet points and tailor them to the role
  - keep everything truthful (no invented experience)

Returns the cleaned resume as plain text. Raises if GEMINI_API_KEY is unset.
"""

from __future__ import annotations

from applybot import config as C


class ReviewError(Exception):
    """Raised when the AI review step fails."""


SYSTEM_PROMPT = """\
You are an expert resume editor helping a data scientist apply for jobs.
You will receive a resume and the role they are applying for.

Your job:
1. Fix typos, grammar mistakes, and inconsistent formatting (dates, bullets, casing).
2. Tighten bullet points: start with strong action verbs, quantify impact where the
   original text already implies numbers, keep each bullet to one or two lines.
3. Lightly tailor wording toward the target role using the job description,
   but NEVER invent employers, degrees, skills, or achievements that are not
   already in the resume. If the job asks for something the resume lacks,
   do not add it.
4. Keep the plain-text structure: NAME on the first line, then clearly separated
   sections (SUMMARY, EXPERIENCE, EDUCATION, SKILLS, etc.).

Output ONLY the cleaned resume text — no commentary, no preamble, no markdown
code fences.
"""


def build_user_prompt(
    resume_text: str, role_title: str, company: str, job_description: str
) -> str:
    parts = [
        f"ROLE: {role_title} at {company}",
    ]
    if job_description:
        parts.append(f"JOB DESCRIPTION (may be truncated):\n{job_description}")
    else:
        parts.append(
            "JOB DESCRIPTION: not available (posting could not be fetched); "
            "tailor using the role title only."
        )
    parts.append(f"RESUME TO REVIEW:\n{resume_text[: C.RESUME_MAX_CHARS]}")
    return "\n\n".join(parts)


def review_resume(
    resume_text: str,
    role_title: str,
    company: str,
    job_description: str = "",
) -> str:
    """Call Gemini Flash and return the cleaned resume text."""
    api_key = C.gemini_api_key()
    if not api_key:
        raise ReviewError(
            f"Environment variable {C.GEMINI_API_KEY_ENV} is not set. "
            "Get a free key at https://aistudio.google.com and export it, e.g.\n"
            '  export GEMINI_API_KEY="your-key-here"'
        )

    try:
        from google import genai  # lazy import: checker unused in --help
    except ImportError as exc:
        raise ReviewError(
            "The google-genai package is not installed. "
            "Run: pip install -r requirements.txt"
        ) from exc

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=C.MODEL,
            contents=build_user_prompt(resume_text, role_title, company, job_description),
            config={"system_instruction": SYSTEM_PROMPT},
        )
    except Exception as exc:  # noqa: BLE001 — surface API errors with context
        raise ReviewError(f"Gemini API call failed ({C.MODEL}): {exc}") from exc

    cleaned = (response.text or "").strip()
    if len(cleaned) < 50:
        raise ReviewError("Gemini returned an empty or trivial response.")
    return cleaned
