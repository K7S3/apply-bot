"""Run apply-bot with resume review via local Ollama (deepseek-r1:8b).

- Reuses a cached cleaned resume (output/<Company>_<Role>.txt from a prior
  --check-only pass) so the live browser phase doesn't need the model in RAM
  at the same time as Chromium (RAM safety on this 8GB VM).
- Otherwise calls Ollama's local HTTP API. No API keys, no quotas, no cost.
- Local-only shim: never commit to the repo.
"""
import json
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/home/hatch/workspace/apply-bot")

from applybot import checker, config as C  # noqa: E402
from applybot import resume as resume_mod  # noqa: E402

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "deepseek-r1:8b"


def ollama_generate(system: str, prompt: str) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": 0.3, "num_predict": 1500},
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.load(resp)
    text = data.get("response", "")
    # strip <think>...</think> reasoning traces from deepseek-r1
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return text


def review_via_ollama(resume_text, role_title, company, job_description=""):
    # 1. reuse a cached review when present (lets the live run skip the model)
    out_name = resume_mod.safe_filename(company, role_title, "txt")
    cache = C.OUTPUT_DIR / out_name
    if cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        if len(cached) >= 200:
            print(f"  (using cached review output/{out_name})", flush=True)
            return cached
    # 2. fresh review via the local model
    prompt = checker.build_user_prompt(resume_text, role_title, company, job_description)
    last_err = ""
    for attempt in range(1, 4):
        try:
            cleaned = ollama_generate(checker.SYSTEM_PROMPT, prompt)
            if len(cleaned) >= 200:
                return cleaned
            last_err = f"short response ({len(cleaned)} chars)"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(10 * attempt)
    raise checker.ReviewError(f"Ollama review failed after 3 attempts: {last_err}")


checker.review_resume = review_via_ollama

from applybot.__main__ import main  # noqa: E402

raise SystemExit(main())
