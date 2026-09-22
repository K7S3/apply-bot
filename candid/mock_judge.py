"""Sandboxed code judge for the mock-interview coding track.

Safety model:
  - User code runs in a *separate* subprocess, never in this process.
  - Hard wall-clock timeout per run (default 2s per test, enforced by
    subprocess; plus a CPU rlimit as a backstop).
  - Resource limits via setrlimit in the child: CPU seconds, address-space
    memory, file size, open files, no core dumps.
  - Runs with `python -I` (isolated: no user site-packages, no PYTHONPATH,
    no inherited env) in a fresh temp dir that is always cleaned up.
  - Stdin/stdout only — the runner never imports anything from the network.
  - IMPORTANT: problems are loaded from local data files only
    (candid/data/problems/). Never execute code fetched from the network.

Known limitation: network access inside the sandbox is not blocked at the
OS level (no namespaces without root). Do not run untrusted third-party
code here; this judge is for *your own* practice solutions.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PER_TEST_TIMEOUT = 2.0
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


def _child_limits() -> None:
    """Applied in the child via preexec_fn (POSIX only)."""
    try:
        import resource
        cpu = int(os.environ.get("COPILOT_CPU_LIMIT", "10"))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass  # non-POSIX: timeouts still apply


_RUNNER = r"""
import copy, json, sys

def safe(o):
    try:
        json.dumps(o)
        return o
    except Exception:
        return repr(o)

def compare(got, expected, mode):
    try:
        if mode == "sorted":
            return sorted(safe(got)) == sorted(safe(expected))
        if mode == "sorted_nested":
            norm = lambda x: sorted([sorted(g) for g in x])
            return norm(safe(got)) == norm(safe(expected))
        return safe(got) == safe(expected)
    except Exception:
        return False

def main():
    spec = json.loads(open("spec.json").read())
    sys.path.insert(0, ".")
    import solution
    fn = getattr(solution, spec["fn"])
    results = []
    for i, t in enumerate(spec["tests"]):
        args = copy.deepcopy(t["args"])
        try:
            got = fn(*args)
            ok = compare(got, t["expected"], spec["compare"])
            results.append({"i": i, "verdict": "accepted" if ok else "wrong_answer",
                            "got": safe(got), "expected": safe(t["expected"])})
        except Exception as e:  # noqa: BLE001 - report any user-code error
            results.append({"i": i, "verdict": "runtime_error",
                            "error": f"{type(e).__name__}: {e}"})
    print(json.dumps(results))

main()
"""


class JudgeError(Exception):
    """Raised when the judge itself fails (not the user's code)."""


def judge(problem: dict, code: str, per_test_timeout: float = DEFAULT_PER_TEST_TIMEOUT) -> dict:
    """Run `code` against a problem's visible + hidden tests.

    Returns:
        {"verdict": "accepted"|"wrong_answer"|"time_limit_exceeded"|"runtime_error",
         "tests": [{"i", "verdict", "got", "expected", "error", "hidden"}...],
         "summary": str}
    """
    fn_name = problem["function"].split("(")[0].strip()
    tests = (
        [{"hidden": False, **t} for t in problem.get("visible_tests", [])]
        + [{"hidden": True, **t} for t in problem.get("hidden_tests", [])]
    )
    if not tests:
        raise JudgeError(f"Problem '{problem.get('id')}' has no test cases.")
    if not code.strip():
        raise JudgeError("Empty solution — nothing to run.")

    workdir = Path(tempfile.mkdtemp(prefix="candid_judge_"))
    try:
        (workdir / "solution.py").write_text(code, encoding="utf-8")
        (workdir / "runner.py").write_text(_RUNNER, encoding="utf-8")
        (workdir / "spec.json").write_text(json.dumps({
            "fn": fn_name,
            "compare": problem.get("compare", "exact"),
            "tests": [{"args": t["args"], "expected": t["expected"]} for t in tests],
        }), encoding="utf-8")

        total_timeout = per_test_timeout * len(tests) + 5
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONNOUSERSITE": "1",
               "COPILOT_CPU_LIMIT": str(int(total_timeout) + 5)}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "runner.py"],
                cwd=str(workdir), env=env, capture_output=True, text=True,
                timeout=total_timeout,
                preexec_fn=_child_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return _verdict("time_limit_exceeded", tests,
                            f"Exceeded {total_timeout:.0f}s total — likely an infinite loop "
                            "or far too slow.")

        if proc.returncode is not None and proc.returncode < 0:
            # killed by a signal (SIGXCPU/SIGKILL from rlimits, incl. OOM) —
            # for practice purposes this is a time/memory blowup, not a bug report
            return _verdict("time_limit_exceeded", tests,
                            "Your solution was killed for exceeding CPU time or memory "
                            "(infinite loop or far too slow / too much memory).")
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            err_tail = "\n".join(err[-8:]) if err else "unknown error"
            if "ModuleNotFoundError" in err_tail or "ImportError" in err_tail:
                detail = "Your code imports a module that isn't available in the sandbox."
            elif "SyntaxError" in err_tail:
                detail = "Syntax error in your solution."
            else:
                detail = "Your solution crashed before running any test."
            return _verdict("runtime_error", tests, f"{detail}\n{err_tail}")

        try:
            raw = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return _verdict("runtime_error", tests,
                            "Judge runner produced no parseable output.")

        enriched = []
        for t, r in zip(tests, raw):
            enriched.append({**r, "hidden": t["hidden"], "args": t["args"]})
        verdict = "accepted" if all(r["verdict"] == "accepted" for r in enriched) else "wrong_answer"
        # surface a crash as runtime_error if every test crashed identically
        if verdict != "accepted" and all(r["verdict"] == "runtime_error" for r in enriched):
            verdict = "runtime_error"
        return {"verdict": verdict, "tests": enriched,
                "summary": _summarize(verdict, enriched)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _verdict(verdict: str, tests: list[dict], summary: str) -> dict:
    return {
        "verdict": verdict,
        "tests": [{"i": i, "verdict": verdict, "hidden": t["hidden"],
                   "args": t.get("args"), "error": summary} for i, t in enumerate(tests)],
        "summary": summary,
    }


def _summarize(verdict: str, tests: list[dict]) -> str:
    n = len(tests)
    passed = sum(1 for t in tests if t["verdict"] == "accepted")
    vis = [t for t in tests if not t["hidden"]]
    vis_passed = sum(1 for t in vis if t["verdict"] == "accepted")
    if verdict == "accepted":
        return f"Accepted — all {n} tests passed ({len(vis)} visible + {n - len(vis)} hidden)."
    return (f"{verdict.replace('_', ' ').title()} — {passed}/{n} tests passed "
            f"({vis_passed}/{len(vis)} visible).")


def failing_details(result: dict) -> list[str]:
    """Human-readable details for failed *visible* tests (hidden stay hidden)."""
    lines = []
    for t in result["tests"]:
        if t["verdict"] == "accepted" or t.get("hidden"):
            continue
        if t["verdict"] == "wrong_answer":
            lines.append(
                f"  Visible test #{t['i'] + 1} FAILED:\n"
                f"    input:    {t['args']}\n"
                f"    expected: {t.get('expected')}\n"
                f"    got:      {t.get('got')}"
            )
        else:
            lines.append(
                f"  Visible test #{t['i'] + 1} {t['verdict'].upper()}: {t.get('error', '')}"
            )
    hidden_failed = sum(1 for t in result["tests"]
                        if t.get("hidden") and t["verdict"] != "accepted")
    if hidden_failed:
        lines.append(
            f"  ({hidden_failed} hidden test(s) also failed — inputs withheld so you "
            "can keep practicing.)"
        )
    return lines
