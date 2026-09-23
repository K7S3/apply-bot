"""A/B-test experiment-design practice for Data Science interviews.

A seeded bank of ~10 design scenarios (randomization unit, guardrail
metrics, peeking, novelty effects, network interference, SRM, metrics,
duration, multiple comparisons, null results). Each scenario has drill
questions with keyword rubrics plus a model answer.

Also ships a pure-stdlib sample-size / power calculator (normal
approximation for two proportions): required n per variant given
baseline rate, MDE, alpha and power — or the detectable effect given n.

Usage:
    python -m candid ds-exp list [--topic peeking]
    python -m candid ds-exp show exp-03
    python -m candid ds-exp drill exp-03
    python -m candid ds-exp calc --p 0.1 --mde 0.02 --alpha 0.05 --power 0.8
    python -m candid ds-exp calc --p 0.1 --n 5000   # detectable effect

Everything runs locally with the standard library only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

DATA = Path(__file__).parent / "data"
SCENARIOS_FILE = DATA / "ds_experiments.json"


class ExperimentError(Exception):
    """Raised for experiment-drill usage errors."""


# ---------------------------------------------------------------------------
# scenario bank
# ---------------------------------------------------------------------------

def load_scenarios() -> list[dict]:
    if not SCENARIOS_FILE.exists():
        raise ExperimentError(f"Experiment bank not found at {SCENARIOS_FILE}.")
    return json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))["scenarios"]


def list_scenarios(topic: str | None = None) -> list[dict]:
    return [s for s in load_scenarios() if not topic or s.get("topic") == topic]


def get_scenario(sid: str) -> dict:
    for s in load_scenarios():
        if s["id"] == sid:
            return s
    known = ", ".join(s["id"] for s in load_scenarios())
    raise ExperimentError(f"Unknown scenario '{sid}'. Known: {known}")


def render_scenario(s: dict) -> str:
    lines = [
        f"### {s['title']}  [{s['topic']}]  ({s['id']})",
        "",
        s["scenario"],
        "",
        "**Key concepts:** " + ", ".join(s["key_concepts"]),
        "",
        "**Rubric (what a strong answer covers):**",
    ]
    for r in s["rubric"]:
        lines.append(f"  • {r['dimension']}: {r['check']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sample-size / power calculator (pure stdlib, normal approximation)
# ---------------------------------------------------------------------------

def _ndtri(p: float) -> float:
    """Inverse standard normal CDF, via bisection on erfc. Stdlib only."""
    if not 0.0 < p < 1.0:
        raise ExperimentError(f"probability must be in (0, 1), got {p}.")
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(-mid / math.sqrt(2)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _check_calc_args(p: float, mde: float, alpha: float, power: float) -> None:
    if not 0.0 < p < 1.0:
        raise ExperimentError(f"Baseline rate --p must be in (0, 1), got {p}.")
    if mde <= 0:
        raise ExperimentError(f"MDE must be positive, got {mde}.")
    if p + mde >= 1.0:
        raise ExperimentError(f"p + MDE must be < 1 (got p={p}, mde={mde}).")
    if not 0.0 < alpha < 1.0:
        raise ExperimentError(f"--alpha must be in (0, 1), got {alpha}.")
    if not 0.0 < power < 1.0:
        raise ExperimentError(f"--power must be in (0, 1), got {power}.")


def required_n(p: float, mde: float, alpha: float = 0.05,
               power: float = 0.8) -> int:
    """Sample size per variant for a two-sided two-proportion z-test.

    n = (z_{1-a/2}·√(2·p̄(1-p̄)) + z_{power}·√(p₀(1-p₀)+p₁(1-p₁)))² / mde²
    """
    _check_calc_args(p, mde, alpha, power)
    z_alpha = _ndtri(1 - alpha / 2)
    z_beta = _ndtri(power)
    p1 = p + mde
    pbar = (p + p1) / 2
    n = ((z_alpha * math.sqrt(2 * pbar * (1 - pbar))
          + z_beta * math.sqrt(p * (1 - p) + p1 * (1 - p1))) ** 2) / (mde ** 2)
    return math.ceil(n)


def detectable_effect(p: float, n: int, alpha: float = 0.05,
                      power: float = 0.8) -> float:
    """Smallest absolute MDE detectable with n samples per variant.

    Inverts required_n by bisection (required_n decreases in MDE).
    """
    if n < 1:
        raise ExperimentError(f"--n must be >= 1, got {n}.")
    _check_calc_args(p, 1e-9, alpha, power)
    lo, hi = 1e-9, min(p, 1 - p) - 1e-9
    if hi <= lo:
        raise ExperimentError(f"Baseline rate {p} leaves no room for an effect.")
    if required_n(p, hi, alpha, power) > n:
        # even the largest feasible effect needs more samples
        return hi
    for _ in range(80):
        mid = (lo + hi) / 2
        if required_n(p, mid, alpha, power) <= n:
            hi = mid
        else:
            lo = mid
    return hi


def render_calc(p: float, mde: float | None, alpha: float, power: float,
                n: int | None) -> str:
    if n is not None:
        eff = detectable_effect(p, n, alpha, power)
        return "\n".join([
            f"Detectable effect (absolute MDE) with n={n}/variant:",
            f"  baseline rate p = {p}",
            f"  alpha = {alpha}, power = {power}",
            f"  detectable MDE = {eff:.4f}  ({eff / p * 100:.1f}% relative lift)",
        ])
    assert mde is not None
    per = required_n(p, mde, alpha, power)
    return "\n".join([
        "Required sample size (two-sided two-proportion z-test):",
        f"  baseline rate p = {p}, MDE = {mde} ({mde / p * 100:.1f}% relative)",
        f"  alpha = {alpha}, power = {power}",
        f"  n per variant = {per:,}",
        f"  total n       = {per * 2:,}",
    ])


# ---------------------------------------------------------------------------
# interactive drill with keyword-rubric feedback
# ---------------------------------------------------------------------------

def score_answer(answer: str, key_points: list[dict]) -> dict:
    """Keyword self-check. Honest about being a heuristic, not an AI grade.

    A key point counts as covered when any of its keywords appears in the
    answer (case-insensitive).
    """
    low = answer.lower()
    hits = []
    for kp in key_points:
        matched = [kw for kw in kp["keywords"] if kw.lower() in low]
        hits.append({"point": kp["point"], "covered": bool(matched),
                     "matched": matched})
    covered = sum(1 for h in hits if h["covered"])
    return {"covered": covered, "total": len(hits), "hits": hits}


def read_answer_interactive() -> str:
    print("Type your answer (end with a line containing only EOF, or Ctrl-D):")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def drill(sid: str, answers: list[str] | None = None) -> dict:
    """Run an interactive drill. `answers` (for tests) bypasses stdin.

    Returns a report dict with per-question scores.
    """
    s = get_scenario(sid)
    print(f"### Drill: {s['title']}\n\n{s['scenario']}\n")
    questions = s["drill_questions"]
    results = []
    total_covered = total_points = 0
    for i, dq in enumerate(questions, 1):
        print(f"**Q{i}:** {dq['question']}\n")
        answer = answers[i - 1] if answers is not None else read_answer_interactive()
        if answers is None and len(answer.strip()) < 20:
            print("(Very short answer — a strong answer is usually 2-4 sentences.)\n")
        scored = score_answer(answer, dq["key_points"])
        total_covered += scored["covered"]
        total_points += scored["total"]
        results.append({"question": dq["question"], "answer": answer,
                        "covered": scored["covered"], "total": scored["total"],
                        "hits": scored["hits"]})
        print(f"Key-point coverage: {scored['covered']}/{scored['total']}")
        for h in scored["hits"]:
            mark = "✅" if h["covered"] else "❌"
            print(f"  {mark} {h['point']}")
        print()
    print("--- Rubric reminder ---")
    for r in s["rubric"]:
        print(f"  • {r['dimension']}: {r['check']}")
    print("\n--- Model answer ---")
    print(s["sample_answer"])
    print(f"\nDrill score: {total_covered}/{total_points} key points covered.")
    return {"id": sid, "title": s["title"], "covered": total_covered,
            "total": total_points, "questions": results}


# ---------------------------------------------------------------------------
# CLI entry points (wired in candid/__main__.py)
# ---------------------------------------------------------------------------

def cmd_list(args) -> None:
    ss = list_scenarios(topic=args.topic)
    if not ss:
        print("No scenarios match. Try without --topic.")
        return
    print(f"{'ID':<10}{'Title':<44}Topic")
    for s in ss:
        print(f"{s['id']:<10}{s['title'][:43]:<44}{s['topic']}")


def cmd_show(args) -> None:
    print(render_scenario(get_scenario(args.id)))


def cmd_drill(args) -> int:
    report = drill(args.id)
    return 0 if report["covered"] == report["total"] else 1


def cmd_calc(args) -> None:
    if args.mde is not None and args.rel is not None:
        raise ExperimentError("Pass either --mde or --rel, not both.")
    if args.n is not None:
        if args.mde is not None or args.rel is not None:
            raise ExperimentError("--n computes the detectable effect; "
                                  "drop --mde/--rel.")
        print(render_calc(args.p, None, args.alpha, args.power, args.n))
        return
    if args.rel is not None:
        if args.rel <= 0:
            raise ExperimentError(f"--rel must be positive, got {args.rel}.")
        mde = args.p * args.rel
    elif args.mde is not None:
        mde = args.mde
    else:
        raise ExperimentError("Provide --mde (absolute) or --rel (relative), "
                              "or --n to compute the detectable effect.")
    print(render_calc(args.p, mde, args.alpha, args.power, None))
