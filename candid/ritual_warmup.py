"""Pre-interview warm-up drill (ritual warmup).

A timed, low-pressure confidence routine to run shortly before an interview:
one easy coding problem, one behavioral question, one technical flashcard.

Framing is "warm-up, not an exam": per-section budgets are gentle guides,
never cutoffs. Everything runs locally: no network, no AI calls.

Public API (the CLI group wires these via lazy imports):
    run_warmup(minutes=15, seed=42, no_wait=False, input_fn=input,
               clock=None) -> dict

Manual use:
    python -m candid.ritual_warmup [--minutes 15] [--seed 42] [--no-wait]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

try:  # the mock problem bank is optional; builtins cover the fallback
    from candid import mock as _mock
    _HAS_MOCK = True
except Exception:  # defensive: warmup must work even if mock is broken
    _mock = None
    _HAS_MOCK = False


# ---------------------------------------------------------------------------
# data dir (resolved at call time so CANDID_DATA_DIR overrides always win)
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    from candid import config as _C
    return _C.DATA_DIR


def _warmups_dir() -> Path:
    d = _data_dir() / "rituals" / "warmups"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# built-in content (used when the mock bank is unavailable)
# ---------------------------------------------------------------------------

_BUILTIN_PROBLEMS: list[dict] = [
    {
        "id": "builtin-two-sum",
        "title": "Two Sum",
        "topic": "arrays",
        "difficulty": "easy",
        "function": "two_sum(nums, target)",
        "statement": (
            "Given a list of integers nums and an integer target, return the "
            "indices of the two numbers that add up to target. "
            "Assume exactly one solution exists."
        ),
        "visible_tests": [
            {"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"args": [[3, 2, 4], 6], "expected": [1, 2]},
        ],
        "sample_approach": (
            "One pass with a hash map: for each number, check whether "
            "target - number is already seen; if yes, return both indices, "
            "otherwise store the number. Time O(n), space O(n)."
        ),
    },
    {
        "id": "builtin-reverse-string",
        "title": "Reverse String",
        "topic": "strings",
        "difficulty": "easy",
        "function": "reverse_string(s)",
        "statement": (
            "Given a string s, return the string reversed. "
            "Skip reversed() and slicing if you want the full warm-up effect."
        ),
        "visible_tests": [
            {"args": ["hello"], "expected": "olleh"},
            {"args": ["candid"], "expected": "diddnac"},
        ],
        "sample_approach": (
            "Two pointers from both ends, swapping characters until they meet. "
            "Time O(n); for an immutable string, build the result in a list, "
            "so O(n) extra space."
        ),
    },
]

_BEHAVIORAL_QUESTIONS: list[str] = [
    "Tell me about a time you debugged a tricky production issue. What was your process?",
    "Describe a disagreement you had with a teammate. How did you resolve it?",
    "Tell me about a project you are proud of. What would you do differently next time?",
    "Describe a time you had to learn a new technology quickly. How did you get up to speed?",
    "Tell me about a mistake you made at work and what you learned from it.",
    "Describe a time you went above and beyond to hit a deadline.",
    "Tell me about a time you gave or received difficult feedback.",
    "Describe how you prioritize when everything feels urgent.",
]

_FLASHCARDS: list[tuple[str, str]] = [
    ("Big-O notation",
     "Describes how an algorithm's runtime or memory grows as the input grows "
     "(worst-case trend, e.g. O(n log n))."),
    ("Hash table",
     "Key-value store that hashes keys into buckets; average O(1) lookup, "
     "insert, and delete."),
    ("REST",
     "API style using HTTP verbs (GET, POST, PUT, DELETE) on resources; "
     "usually stateless with JSON payloads."),
    ("ACID",
     "Atomicity, Consistency, Isolation, Durability: the guarantees that make "
     "database transactions reliable."),
    ("Thread vs process",
     "A process owns its memory; threads share a process's memory, so they "
     "communicate fast but need locks."),
    ("Caching",
     "Storing hot results in fast storage to skip recomputation; the hard "
     "parts are invalidation and staleness."),
    ("Load balancer",
     "Spreads incoming traffic across servers so none is overwhelmed; "
     "enables scaling and failover."),
    ("Database index",
     "An auxiliary structure (often a B-tree) that speeds up lookups on a "
     "column, at the cost of slower writes."),
    ("Recursion",
     "A function solving smaller instances of the same problem until a base "
     "case; watch stack depth and repeated work."),
    ("Rate limiting",
     "Capping requests per client per time window to protect a service; "
     "commonly done with token buckets."),
]


# ---------------------------------------------------------------------------
# picking content
# ---------------------------------------------------------------------------

def _pick_easy_problem(rng: random.Random) -> tuple[dict, str]:
    """Return (problem_dict, source) where source is 'mock_bank' or 'builtin'."""
    if _HAS_MOCK:
        try:
            pool = _mock.list_problems(difficulty="easy")
            if pool:
                return _mock.get_problem(rng.choice(pool)["id"]), "mock_bank"
        except Exception:
            pass  # fall through to builtins
    return rng.choice(_BUILTIN_PROBLEMS), "builtin"


def _reveal_for(problem: dict, source: str) -> str:
    if source == "builtin":
        return problem.get("sample_approach", "")
    bits = []
    if problem.get("complexity"):
        bits.append(f"Complexity target: {problem['complexity']}.")
    hints = problem.get("hints") or []
    if hints:
        bits.append(f"Hint: {hints[0]}")
    if not bits:
        bits.append("Talk through a brute force first, then look for the pattern that removes the repeated work.")
    return " ".join(bits)


def _split_budgets(minutes: int) -> dict[str, int]:
    """Split minutes across stations; the parts always sum to minutes."""
    if minutes < 3:
        return {"coding": minutes, "behavioral": 0, "flashcard": 0}
    coding = minutes // 2
    behavioral = (minutes - coding) * 3 // 5
    flashcard = minutes - coding - behavioral
    return {"coding": coding, "behavioral": behavioral, "flashcard": flashcard}


# ---------------------------------------------------------------------------
# stations
# ---------------------------------------------------------------------------

def _breathe(no_wait: bool) -> None:
    if not no_wait:
        time.sleep(0.75)


def _station_done(name: str, budget: int, took_min: float) -> None:
    print(f"  [done] {name} took about {took_min:.1f} min "
          f"(budget was {budget} min). No rush either way.")


def _station_coding(rng, budget, input_fn, tick, no_wait) -> dict:
    print(f"\n-- Station 1 of 3: coding drill (about {budget} min, easy) --")
    problem, source = _pick_easy_problem(rng)
    print(f"\nProblem: {problem['title']} "
          f"[{problem.get('topic', '?')} - {problem.get('difficulty', 'easy')}]")
    print(problem["statement"])
    print(f"\nWrite: {problem['function']}")
    print("Examples:")
    for t in problem.get("visible_tests", []):
        print(f"  input {t['args']} -> {t['expected']}")
    start = tick()
    ans = input_fn("\nIn 1-2 sentences, how would you approach it? (or 'skip') ").strip()
    approach = None if (not ans or ans.lower() == "skip") else ans
    took = (tick() - start) / 60.0
    print("\nSample approach:")
    print(f"  {_reveal_for(problem, source)}")
    _station_done("coding", budget, took)
    _breathe(no_wait)
    return {
        "problem_id": problem["id"],
        "problem_title": problem["title"],
        "problem_source": source,
        "approach": approach,
        "elapsed_min": round(took, 2),
    }


def _ask_rating(input_fn) -> int | None:
    for _ in range(5):
        raw = input_fn("Self-rate that answer 1-5 (5 = nailed it; be kind, this is practice): ").strip().lower()
        if raw in ("", "skip", "s"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= 5:
            return int(raw)
        print("  Please enter a number from 1 to 5, or 'skip'.")
    return None


def _station_behavioral(rng, budget, input_fn, tick, no_wait) -> dict:
    print(f"\n-- Station 2 of 3: behavioral ({budget} min) --")
    question = rng.choice(_BEHAVIORAL_QUESTIONS)
    print(f"\nQuestion: {question}")
    start = tick()
    answer = input_fn("Your answer (2-3 sentences; one line is fine): ").strip()
    rating = _ask_rating(input_fn)
    took = (tick() - start) / 60.0
    if rating is not None:
        print(f"  Noted: {rating}/5. The habit of answering out loud is the real win.")
    else:
        print("  Noted. The habit of answering out loud is the real win.")
    _station_done("behavioral", budget, took)
    _breathe(no_wait)
    return {
        "question": question,
        "answer": answer or None,
        "self_rating": rating,
        "elapsed_min": round(took, 2),
    }


def _station_flashcard(rng, budget, input_fn, tick, no_wait) -> dict:
    print(f"\n-- Station 3 of 3: technical flashcard ({budget} min) --")
    term, definition = rng.choice(_FLASHCARDS)
    print(f"\nTerm: {term}")
    start = tick()
    input_fn("Say the definition out loud (or type it), then press Enter to reveal: ")
    print(f"Definition: {definition}")
    raw = input_fn("Did you recall it? (y/n): ").strip().lower()
    if raw.startswith("y"):
        recalled = True
    elif raw.startswith("n"):
        recalled = False
    else:
        recalled = None
    took = (tick() - start) / 60.0
    if recalled:
        print("  Nice, that one is warm.")
    elif recalled is False:
        print("  Good, now it is in short-term memory. That counts.")
    _station_done("flashcard", budget, took)
    return {
        "term": term,
        "definition": definition,
        "recalled": recalled,
        "elapsed_min": round(took, 2),
    }


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def run_warmup(minutes: int = 15, seed: int = 42, no_wait: bool = False,
               input_fn=input, clock=None) -> dict:
    """Run the warm-up drill and save a session summary.

    Args:
        minutes: total drill length; split across the three stations.
        seed: RNG seed so a drill is reproducible.
        no_wait: skip the short pacing pauses (used by tests).
        input_fn: callable used for all prompts (defaults to input).
        clock: monotonic clock callable (defaults to time.monotonic);
            inject a fake clock in tests.

    Returns:
        The session summary dict (also saved as JSON).
    """
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
        raise ValueError("minutes must be a positive integer")
    tick = clock or time.monotonic
    rng = random.Random(seed)
    budgets = _split_budgets(minutes)

    print("=" * 60)
    print(f"Interview warm-up: a gentle {minutes}-minute drill")
    print("Warm-up, not an exam. Budgets are guides, never cutoffs.")
    print("=" * 60)

    coding = _station_coding(rng, budgets["coding"], input_fn, tick, no_wait)
    behavioral = _station_behavioral(rng, budgets["behavioral"], input_fn, tick, no_wait)
    flashcard = _station_flashcard(rng, budgets["flashcard"], input_fn, tick, no_wait)

    print("\n" + "=" * 60)
    print("Warm-up complete. You showed up, and that is the win.")
    print("Good luck in there.")
    print("=" * 60)

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "minutes": minutes,
        "seed": seed,
        "budgets_min": budgets,
        "coding": coding,
        "behavioral": behavioral,
        "flashcard": flashcard,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = _warmups_dir() / f"{stamp}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["saved_to"] = str(path)
    print(f"\nSummary saved to {path}")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="candid ritual warmup",
        description="Timed pre-interview warm-up drill (warm-up, not an exam).")
    ap.add_argument("--minutes", type=int, default=15,
                    help="Total drill length in minutes (default: 15)")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for reproducible drills (default: 42)")
    ap.add_argument("--no-wait", action="store_true",
                    help="Skip the short pacing pauses between stations")
    a = ap.parse_args(argv)
    run_warmup(minutes=a.minutes, seed=a.seed, no_wait=a.no_wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
