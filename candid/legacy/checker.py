"""AI resume review/formatting step, powered by the local Ollama model.

Default model: deepseek-r1:8b served at http://localhost:11434 (no API keys,
no quotas, no cost). The model is only invoked when no cached review exists:
`output/<Company>_<Role>.txt` from a prior --check-only pass is reused, so a
--live browser run never needs the model in RAM at the same time as Chromium.

Takes the tailored resume text plus role context and asks the model to:
  - fix typos, grammar, and formatting inconsistencies
  - tighten bullet points and tailor them to the role
  - keep everything truthful (no invented experience)

Returns the cleaned resume as plain text.
"""

from __future__ import annotations

import json
import re
import urllib.request

from candid.legacy import config as C
from candid.legacy import resume as resume_mod


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
code fences, no thinking trace.
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


def _ollama_generate(system: str, prompt: str, timeout: int = 600) -> str:
    """One non-streaming generation via the local Ollama HTTP API."""
    body = json.dumps(
        {
            "model": C.OLLAMA_MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0.3,
                "num_predict": C.OLLAMA_NUM_PREDICT,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{C.OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:  # noqa: BLE001 — server down, refused, timeout...
        raise ReviewError(
            f"Could not reach Ollama at {C.OLLAMA_URL} ({exc}). "
            "Start it with ~/workspace/ollama-start.sh and make sure "
            f"'{C.OLLAMA_MODEL}' is pulled."
        ) from exc
    text = data.get("response", "") or ""
    # Strip deepseek-r1 <think>...</think> reasoning traces if present.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return text


def review_resume(
    resume_text: str,
    role_title: str,
    company: str,
    job_description: str = "",
) -> str:
    """Review the resume with the local model and return the cleaned text.

    Reuses output/<Company>_<Role>.txt when a prior --check-only pass already
    produced it, so --live runs don't need the model loaded.
    """
    out_name = resume_mod.safe_filename(company, role_title, "txt")
    cache = C.OUTPUT_DIR / out_name
    if cache.exists():
        cached = cache.read_text(encoding="utf-8", errors="replace").strip()
        if len(cached) >= 200:
            return cached

    prompt = build_user_prompt(resume_text, role_title, company, job_description)
    last_err = ""
    for attempt in range(1, 4):
        try:
            cleaned = _ollama_generate(SYSTEM_PROMPT, prompt)
            if len(cleaned) >= 200:
                return cleaned
            last_err = f"short response ({len(cleaned)} chars)"
        except ReviewError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:200]
        import time

        time.sleep(10 * attempt)
    raise ReviewError(f"Local-model review failed after 3 attempts: {last_err}")
