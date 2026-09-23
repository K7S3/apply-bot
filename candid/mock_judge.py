"""Sandboxed code judge for the mock-interview coding track.

Safety model:
  - User code runs in a *separate* subprocess, never in this process.
  - Each test case runs in its OWN subprocess with a hard wall-clock
    timeout (default 2s per test, enforced by subprocess; plus a CPU rlimit
    as a backstop). An infinite loop fails that test fast instead of hanging
    the whole run.
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
    t = spec["test"]
    args = copy.deepcopy(t["args"])
    try:
        got = fn(*args)
        ok = compare(got, t["expected"], spec["compare"])
        print(json.dumps({"verdict": "accepted" if ok else "wrong_answer",
                          "got": safe(got), "expected": safe(t["expected"])}))
    except Exception as e:  # noqa: BLE001 - report any user-code error
        print(json.dumps({"verdict": "runtime_error",
                          "error": f"{type(e).__name__}: {e}"}))

main()
"""


class JudgeError(Exception):
    """Raised when the judge itself fails (not the user's code)."""


def _run_single_test(workdir: Path, fn_name: str, compare_mode: str,
                     args, expected, per_test_timeout: float) -> dict:
    """Run one test case in its own sandboxed subprocess."""
    (workdir / "spec.json").write_text(json.dumps({
        "fn": fn_name,
        "compare": compare_mode,
        "test": {"args": args, "expected": expected},
    }), encoding="utf-8")

    # wall-clock timeout with headroom for interpreter startup; the CPU
    # rlimit is the backstop for spin-loops that dodge signals.
    wall_timeout = per_test_timeout + max(1.0, per_test_timeout * 0.5)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONNOUSERSITE": "1",
           "COPILOT_CPU_LIMIT": str(int(per_test_timeout) + 5)}
    # Sandboxing model: bubblewrap/firejail-style namespace isolation is
    # POSIX-only, so on Windows the judge runs the code directly in a
    # subprocess with only the wall-clock timeout as the guard. This is an
    # honest fallback, not a sandbox: do not run untrusted third-party code.
    # CREATE_NO_WINDOW keeps the interpreter from popping up a console
    # window on Windows; it does not exist on POSIX, hence the getattr.
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "runner.py"],
            shell=False,
            cwd=str(workdir.resolve()),
            env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=wall_timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            preexec_fn=_child_limits if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return {"verdict": "time_limit_exceeded",
                "error": f"Hit the {per_test_timeout:g}s per-test time limit - "
                         "likely an infinite loop or far too slow."}

    if proc.returncode is not None and proc.returncode < 0:
        # killed by a signal (SIGXCPU/SIGKILL from rlimits, incl. OOM) -
        # for practice purposes this is a time/memory blowup, not a bug report
        return {"verdict": "time_limit_exceeded",
                "error": "Your solution was killed for exceeding CPU time or "
                         "memory (infinite loop, far too slow, or too much memory)."}
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        err_tail = "\n".join(err[-8:]) if err else "unknown error"
        if "ModuleNotFoundError" in err_tail or "ImportError" in err_tail:
            detail = "Your code imports a module that isn't available in the sandbox."
        elif "SyntaxError" in err_tail:
            detail = "Syntax error in your solution."
        elif "MemoryError" in err_tail:
            detail = ("Your solution ran out of memory "
                      f"(sandbox limit: {MEMORY_LIMIT_BYTES // (1024*1024)} MB).")
        else:
            detail = "Your solution crashed before running the test."
        return {"verdict": "runtime_error", "error": f"{detail}\n{err_tail}"}

    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"verdict": "runtime_error",
                "error": "Judge runner produced no parseable output."}
    return raw


def judge(problem: dict, code: str, per_test_timeout: float = DEFAULT_PER_TEST_TIMEOUT) -> dict:
    """Run `code` against a problem's visible + hidden tests.

    Each test runs in its own sandboxed subprocess with a per-test timeout,
    so an infinite loop fails fast instead of hanging the suite.

    Returns:
        {"verdict": "accepted"|"wrong_answer"|"time_limit_exceeded"|"runtime_error",
         "tests": [{"i", "verdict", "got", "expected", "error", "hidden", "args"}...],
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

        results: list[dict] = []
        skip_rest = False
        for i, t in enumerate(tests):
            if skip_rest:
                # an earlier test already blew the time budget - don't burn
                # another full timeout per remaining test
                results.append({
                    "i": i, "verdict": "time_limit_exceeded", "hidden": t["hidden"],
                    "args": t["args"],
                    "error": "Skipped: an earlier test exceeded the time limit.",
                })
                continue
            r = _run_single_test(workdir, fn_name, problem.get("compare", "exact"),
                                 t["args"], t["expected"], per_test_timeout)
            r.update({"i": i, "hidden": t["hidden"], "args": t["args"]})
            if r["verdict"] == "time_limit_exceeded":
                skip_rest = True
            results.append(r)

        if all(r["verdict"] == "accepted" for r in results):
            verdict = "accepted"
        elif any(r["verdict"] == "time_limit_exceeded" for r in results):
            verdict = "time_limit_exceeded"
        elif all(r["verdict"] == "runtime_error" for r in results):
            verdict = "runtime_error"
        else:
            verdict = "wrong_answer"
        return {"verdict": verdict, "tests": results,
                "summary": _summarize(verdict, results)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
