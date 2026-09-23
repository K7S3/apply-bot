"""PM product-sense mock interviewer (scripted by default, optional local LLM).

A product-sense interview round: pick a prompt, ask it, then ask follow-up
questions in a deterministic depth order:

    clarification -> tradeoffs -> metrics -> prioritization

Two modes:
  scripted (default) — deterministic, depth-based follow-ups. This is what
      tests and demos use; it never touches the network.
  llm — uses a local Ollama endpoint ONLY if explicitly requested AND
      localhost:11434 answers (lazy import, short timeout). Any failure
      falls back to the scripted sequence.

Session transcripts are saved to DATA_DIR/pm_mock_sessions.json.

This module is wired into the CLI by the coordinator via register_pm();
it never touches candid.__main__ itself.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "PmMockError",
    "PROMPTS",
    "DEPTH_ORDER",
    "FOLLOWUPS",
    "list_prompts",
    "pick_prompt",
    "scripted_followups",
    "script_session",
    "interactive_session",
    "save_session",
    "load_sessions",
    "ollama_available",
    "llm_followup",
    "register_pm",
]


class PmMockError(Exception):
    """Raised for PM-mock usage errors."""


# ---------------------------------------------------------------------------
# prompt bank + scripted follow-ups
# ---------------------------------------------------------------------------

PROMPTS: list[str] = [
    "Design a product to improve airport security wait times.",
    "How would you improve the checkout flow of an e-commerce app?",
    "Design a feature to help remote teams build trust.",
    "You are the PM for a food-delivery app. Orders are declining - what do you do?",
    "Design a product for elderly users to stay connected with family.",
    "How would you improve onboarding for a fitness tracking app?",
    "Should we add a social feed to our banking app? Walk me through your decision.",
    "Design a marketplace feature for buying and selling used textbooks.",
]

#: Depth stages asked in strict order.
DEPTH_ORDER: list[str] = ["clarification", "tradeoffs", "metrics", "prioritization"]

#: stage -> follow-up question bank. Scripted mode cycles through each list.
FOLLOWUPS: dict[str, list[str]] = {
    "clarification": [
        "Before we go further - who exactly is the user here, and what are "
        "their top two goals?",
        "What constraints should we assume - platform, budget, timeline?",
        "Are we optimizing for new users, existing users, or both? Why?",
    ],
    "tradeoffs": [
        "What is the biggest tradeoff in your proposal, and why did you pick "
        "this side of it?",
        "What would you explicitly NOT build in v1, and why?",
        "How does your approach change if we have half the engineering capacity?",
    ],
    "metrics": [
        "What is the single success metric for this, and what would move it?",
        "Name two guardrail metrics - what must NOT regress while we optimize?",
        "How would you run an experiment to validate this before full launch?",
    ],
    "prioritization": [
        "You have three competing asks - this feature, a bug fix for churn, "
        "and a partner integration. How do you prioritize?",
        "How do you decide what ships in v1 versus v2?",
        "How would you get stakeholder buy-in for this roadmap call?",
    ],
}

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:8b"


def _data_dir() -> Path:
    """User data dir, overridable via CANDID_DATA_DIR (used by tests)."""
    override = os.environ.get("CANDID_DATA_DIR")
    return Path(override).expanduser() if override else Path.cwd() / "candid_data"


def _sessions_path() -> Path:
    return _data_dir() / "pm_mock_sessions.json"


def list_prompts() -> list[str]:
    """All product-sense prompts in the bank."""
    return list(PROMPTS)


def pick_prompt(seed: int | None = None) -> str:
    """Pick one prompt; deterministic when seed is given."""
    rng = random.Random(seed)
    return rng.choice(PROMPTS)


def scripted_followups(rounds: int, seed: int | None = None) -> list[tuple[str, str]]:
    """Deterministic follow-up sequence.

    Stage cycles clarification -> tradeoffs -> metrics -> prioritization;
    within a stage, questions cycle through that stage's bank. `seed`
    rotates the starting offset so different seeds vary the questions.
    """
    if rounds < 0:
        raise PmMockError(f"rounds must be >= 0, got {rounds}")
    rng = random.Random(seed)
    offset = rng.randrange(64) if seed is not None else 0
    out: list[tuple[str, str]] = []
    for i in range(rounds):
        stage = DEPTH_ORDER[i % len(DEPTH_ORDER)]
        bank = FOLLOWUPS[stage]
        question = bank[(offset + i) % len(bank)]
        out.append((stage, question))
    return out


def script_session(prompt: str, rounds: int, seed: int | None = None) -> dict:
    """Build a full (non-interactive) session transcript.

    Returns a dict with prompt metadata plus the ordered turn list; used by
    --script and by tests. No user answers are collected in script mode -
    answers are left as null placeholders to fill in during practice.
    """
    turns = [{"role": "question", "stage": "prompt", "text": prompt, "answer": None}]
    for stage, question in scripted_followups(rounds, seed=seed):
        turns.append({"role": "question", "stage": stage, "text": question, "answer": None})
    return {
        "kind": "pm_mock",
        "mode": "script",
        "prompt": prompt,
        "rounds": rounds,
        "seed": seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# optional local-LLM mode (strictly opt-in, graceful fallback)
# ---------------------------------------------------------------------------

def ollama_available(url: str = OLLAMA_URL, timeout: float = 2.0) -> bool:
    """True if a local Ollama endpoint answers. Never raises.

    Only called when the user explicitly requests --mode llm. The check is
    lazy (urllib imported here, not at module top) with a short timeout.
    """
    import urllib.request  # lazy: only needed for local-LLM mode

    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": "ping", "stream": False}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def llm_followup(prompt: str, history: list[dict], stage: str,
                 url: str = OLLAMA_URL, timeout: float = 30.0) -> str:
    """Ask local Ollama for one follow-up question.

    Falls back to the scripted question for `stage` if anything goes wrong,
    so LLM mode degrades gracefully instead of erroring out.
    """
    import urllib.request  # lazy: only needed for local-LLM mode

    convo = "\n".join(f"{t['role']} [{t.get('stage', '')}]: {t['text']}"
                      for t in history if t["role"] == "question")
    llm_prompt = (
        f"You are a product-management interviewer. The prompt was: {prompt}\n"
        f"Conversation so far:\n{convo}\n"
        f"Ask ONE sharp follow-up question focused on: {stage}. "
        f"Reply with only the question."
    )
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": llm_prompt,
                          "stream": False}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = (data.get("response") or "").strip()
        if not text:
            raise PmMockError("empty LLM response")
        return text.split("\n")[0].strip()
    except Exception:
        bank = FOLLOWUPS[stage]
        return bank[abs(hash(prompt)) % len(bank)]


# ---------------------------------------------------------------------------
# interactive session
# ---------------------------------------------------------------------------

def _ask(text: str) -> str:
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        raise PmMockError("Session interrupted.")


def interactive_session(prompt: str, mode: str = "script", rounds: int = 4,
                        seed: int | None = None, input_fn=None) -> dict:
    """Run an interactive PM mock: ask the prompt, collect answers, follow up.

    `input_fn` is injectable for tests (defaults to input()). Returns the
    session dict; the caller decides whether to save it.
    """
    ask = input_fn or (lambda t: _ask(t))
    turns: list[dict] = [{"role": "question", "stage": "prompt",
                          "text": prompt, "answer": None}]
    print("=== PM Mock Interview: product sense ===")
    print(f"\nPrompt: {prompt}\n")
    try:
        answer = ask("Your answer (blank line to skip): ")
    except PmMockError:
        raise
    turns[0]["answer"] = answer.strip() or None

    use_llm = mode == "llm" and ollama_available()
    if mode == "llm" and not use_llm:
        print("(Local LLM unavailable - falling back to scripted follow-ups.)")
    stages = scripted_followups(rounds, seed=seed) if not use_llm else []
    history = [t for t in turns]
    for i in range(rounds):
        stage = DEPTH_ORDER[i % len(DEPTH_ORDER)]
        if use_llm:
            question = llm_followup(prompt, history, stage)
        else:
            _, question = stages[i]
        print(f"\nFollow-up [{stage}]: {question}")
        try:
            answer = ask("Your answer (blank line to skip): ")
        except PmMockError:
            break
        turn = {"role": "question", "stage": stage, "text": question,
                "answer": answer.strip() or None}
        turns.append(turn)
        history.append(turn)

    return {
        "kind": "pm_mock",
        "mode": "llm" if use_llm else "script",
        "prompt": prompt,
        "rounds": rounds,
        "seed": seed,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def load_sessions() -> list[dict]:
    """All saved PM mock sessions (oldest first)."""
    path = _sessions_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PmMockError(f"Session file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PmMockError(f"Session file {path} is corrupted (expected a list).")
    return data


def save_session(session: dict) -> Path:
    """Append one session transcript to DATA_DIR/pm_mock_sessions.json."""
    path = _sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions = load_sessions()
    sessions.append(session)
    path.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI (register_pm is called by the coordinator; see module docstring)
# ---------------------------------------------------------------------------

def register_pm(subparsers) -> None:
    """Register the 'mock' PM-mock subcommand on an argparse subparsers object.

    Flags: --mode script|llm, --rounds N, --script (non-interactive full
    follow-up sequence, for tests/demo), --json (machine output), --prompt-index.
    """
    p = subparsers.add_parser(
        "mock", help="PM product-sense mock interview (scripted follow-ups).",
        epilog="examples:\n"
               "  python -m candid pm mock --script\n"
               "  python -m candid pm mock --rounds 3 --seed 42\n")
    p.add_argument("--mode", default="script", choices=["script", "llm"],
                   help="Follow-up source: scripted (default) or local LLM.")
    p.add_argument("--rounds", type=int, default=4,
                   help="Number of follow-up questions (default 4).")
    p.add_argument("--script", action="store_true",
                   help="Non-interactive: print the full follow-up sequence.")
    p.add_argument("--json", action="store_true",
                   help="Print machine-readable JSON instead of text.")
    p.add_argument("--prompt-index", type=int, default=None,
                   help="Pick a prompt by index (0-based). Default: random.")
    p.add_argument("--seed", type=int, default=None,
                   help="Seed for deterministic prompt/follow-up selection.")
    p.set_defaults(func=cmd_pm_mock)


def cmd_pm_mock(args: argparse.Namespace) -> None:
    """Dispatch for the registered 'mock' subcommand."""
    if args.rounds < 0:
        raise PmMockError(f"--rounds must be >= 0, got {args.rounds}")
    if args.prompt_index is None:
        prompt = pick_prompt(seed=args.seed)
    else:
        prompts = list_prompts()
        if not 0 <= args.prompt_index < len(prompts):
            raise PmMockError(
                f"--prompt-index {args.prompt_index} out of range "
                f"(0-{len(prompts) - 1}).")
        prompt = prompts[args.prompt_index]

    if args.script:
        session = script_session(prompt, args.rounds, seed=args.seed)
        if args.json:
            print(json.dumps(session, indent=2))
        else:
            lines = [f"Prompt: {prompt}", ""]
            for turn in session["turns"][1:]:
                lines.append(f"[{turn['stage']}] {turn['text']}")
            print("\n".join(lines))
        return

    session = interactive_session(prompt, mode=args.mode, rounds=args.rounds,
                                  seed=args.seed)
    path = save_session(session)
    answered = sum(1 for t in session["turns"] if t.get("answer"))
    if args.json:
        print(json.dumps({"saved_to": str(path), "turns": len(session["turns"]),
                          "answered": answered}, indent=2))
    else:
        print(f"\nSession saved to {path} "
              f"({answered}/{len(session['turns'])} turns answered).")
    return None
