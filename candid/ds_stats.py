"""DS statistics refreshers for data-science interviews.

A bank of ~25 stats/probability concept cards lives in
candid/data/ds_stats.json so anyone can extend it. Two commands:

    python -m candid ds-stats review [--topic bayes] [--shuffle]
    python -m candid ds-stats quiz [--n 10] [--topic distributions]

Free-text answers are graded by key-idea overlap (a self-check heuristic,
like the behavioral rubric in mock interviews, not a strict grader).
Numeric answers are checked against an expected value with a tolerance.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "ds_stats.json"


class DSStatsError(Exception):
    """Raised for ds-stats usage errors (unknown topic, bad --n, ...)."""


def load_cards() -> list[dict]:
    """Load the raw card list from candid/data/ds_stats.json."""
    with open(DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload["cards"])


def topics() -> list[str]:
    """Sorted topic names covered by the card bank."""
    return sorted({c["topic"] for c in load_cards()})


def get_cards(topic: str | None = None, shuffle: bool = False,
              seed: int | None = None) -> list[dict]:
    """Cards, optionally filtered by topic and/or shuffled."""
    cards = load_cards()
    if topic:
        if topic not in topics():
            raise DSStatsError(
                f"Unknown topic {topic!r}. Available topics: {', '.join(topics())}")
        cards = [c for c in cards if c["topic"] == topic]
    if shuffle or seed is not None:
        rng = random.Random(seed)
        cards = list(cards)
        rng.shuffle(cards)
    return cards


def render_card(card: dict, index: int | None = None,
                total: int | None = None) -> str:
    """Interview-ready rendering of one card (concept + explanation only)."""
    head = f"[{index}/{total}] " if index and total else ""
    return (f"{head}{card['concept']}  (topic: {card['topic']})\n"
            f"{'-' * 60}\n"
            f"{card['explanation']}")


def render_review(cards: list[dict]) -> str:
    """Printable study sheet for a list of cards."""
    return "\n\n".join(render_card(c, i + 1, len(cards))
                       for i, c in enumerate(cards))


_NUMERIC_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _first_number(text: str) -> float | None:
    m = _NUMERIC_RE.search(text)
    return float(m.group(0)) if m else None


def check_answer(card: dict, user_text: str) -> tuple[bool, str, int, int]:
    """Grade one free-text/numeric answer.

    Returns (ok, expected_summary, matched_key_ideas, total_key_ideas).
    Numeric answers pass when within tolerance. Free-text answers pass when
    at least the required number of key ideas appear (substring, case-free).
    """
    answer = card["answer"]
    numeric_items = [a for a in (answer if isinstance(answer, list) else [answer])
                     if isinstance(a, dict) and "numeric" in a]
    text_items = [str(a) for a in (answer if isinstance(answer, list) else [answer])
                  if not isinstance(a, dict)]

    num_ok, expected_parts = False, []
    val = _first_number(user_text or "")
    if numeric_items and val is not None:
        for item in numeric_items:
            tol = item.get("tol", 0.0)
            if abs(val - item["numeric"]) <= tol:
                num_ok = True
            expected_parts.append(f"{item['numeric']}")

    lowered = (user_text or "").lower()
    matched = [k for k in text_items if k.lower() in lowered]
    need = 1 if len(text_items) <= 3 else 2
    text_ok = len(matched) >= min(need, len(text_items)) if text_items else False

    if numeric_items and not text_items:
        ok = num_ok
    elif text_items and not numeric_items:
        ok = text_ok
    else:
        ok = num_ok or text_ok  # either route counts for mixed cards
    if not expected_parts and text_items:
        expected_parts = text_items
    summary = "; ".join(expected_parts) or "—"
    return ok, summary, len(matched), len(text_items)


def run_quiz(n: int = 10, topic: str | None = None, seed: int | None = None,
             input_fn=input, print_fn=print) -> dict:
    """Ask up to n questions from the bank; return a score report dict."""
    if n <= 0:
        raise DSStatsError("--n must be a positive integer.")
    cards = get_cards(topic=topic, shuffle=True, seed=seed)
    if not cards:
        raise DSStatsError(f"No cards found for topic {topic!r}.")
    picked = cards[:n]
    print_fn(f"DS stats quiz: {len(picked)} question(s)"
             + (f" on topic '{topic}'" if topic else "")
             + ". Type your answer and press Enter.\n")
    correct, details = 0, []
    for i, card in enumerate(picked, 1):
        print_fn(f"[{i}/{len(picked)}] {card['quiz']}")
        user = input_fn("> ")
        ok, expected, matched, total = check_answer(card, user)
        details.append({"id": card["id"], "ok": ok})
        if ok:
            correct += 1
            print_fn("  ✅ correct\n")
        else:
            print_fn(f"  ❌ expected: {expected}\n")
    pct = 100.0 * correct / len(picked)
    print_fn(f"Score: {correct}/{len(picked)} ({pct:.0f}%)")
    return {"score": correct, "total": len(picked), "pct": pct,
            "details": details}
