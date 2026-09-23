#!/bin/sh
# docker-smoke.sh — static smoke test for the candid Docker one-command run.
#
# Works on machines WITHOUT docker (this VM): checks file presence, shell
# syntax of the entrypoint, and Python syntax of the changed modules.
# When docker IS present it additionally builds the image and runs
# `python -m candid --version` inside the container.
#
# Usage: sh scripts/docker-smoke.sh   (from the repo root)

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

fail=0
ok()  { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }

echo "== docker smoke (static) =="

# 1. File presence.
for f in Dockerfile .dockerignore docker/entrypoint.sh \
         docker-compose.yml docker-compose.dev.yml Makefile; do
    if [ -f "$f" ]; then ok "$f present"; else bad "$f missing"; fi
done

# 2. Entrypoint: POSIX shell syntax check.
if sh -n docker/entrypoint.sh 2>/tmp/smoke-sh-err.txt; then
    ok "entrypoint.sh passes sh -n"
else
    bad "entrypoint.sh sh -n failed:"; cat /tmp/smoke-sh-err.txt
fi
if [ -x docker/entrypoint.sh ]; then ok "entrypoint.sh executable"; \
else bad "entrypoint.sh not executable"; fi

# 3. Python syntax compile of the batch's changed/new .py files.
#    (Use python3 when plain `python` is absent.)
PY="$(command -v python3 || command -v python || true)"
if [ -n "$PY" ]; then
    CHANGED="$("$PY" - <<'EOF'
import subprocess
try:
    out = subprocess.run(
        ["git", "diff", "--name-only", "origin/main", "--", "*.py"],
        capture_output=True, text=True, check=True).stdout
    files = [f for f in out.split() if f]
except Exception:
    files = []
print(" ".join(files))
EOF
)"
    if [ -z "$CHANGED" ]; then
        # Fallback: compile the whole package.
        if "$PY" -m compileall -q candid tests/test_docker.py 2>/tmp/smoke-py-err.txt; then
            ok "py_compile: candid package + tests/test_docker.py"
        else
            bad "py_compile failed:"; cat /tmp/smoke-py-err.txt
        fi
    else
        for f in $CHANGED; do
            if "$PY" -m py_compile "$f" 2>/tmp/smoke-py-err.txt; then
                ok "py_compile: $f"
            else
                bad "py_compile failed for $f:"; cat /tmp/smoke-py-err.txt
            fi
        done
    fi
else
    bad "no python found; skipping py_compile"
fi

# 4. Static Dockerfile sanity (no docker daemon needed).
grep -q '^FROM ' Dockerfile && ok "Dockerfile has FROM" || bad "Dockerfile missing FROM"
grep -q 'ENTRYPOINT' Dockerfile && ok "Dockerfile has ENTRYPOINT" || bad "Dockerfile missing ENTRYPOINT"

# 5. If docker exists, do the real thing: build + run --version.
if command -v docker >/dev/null 2>&1; then
    echo "== docker smoke (live) =="
    if docker build -q -t candid:smoke . >/tmp/smoke-build.log 2>&1; then
        ok "docker build"
    else
        bad "docker build failed (see /tmp/smoke-build.log)"
    fi
    if [ "$fail" -eq 0 ]; then
        if docker run --rm -e CANDID_SKIP_WIZARD=1 candid:smoke --version \
                >/tmp/smoke-version.log 2>&1; then
            ok "container runs: $(cat /tmp/smoke-version.log)"
        else
            bad "container --version failed (see /tmp/smoke-version.log)"
        fi
        docker rmi -f candid:smoke >/dev/null 2>&1 || true
    fi
else
    echo "note: docker not found; live build/run skipped (static checks only)"
fi

if [ "$fail" -eq 0 ]; then
    echo "SMOKE OK"
else
    echo "SMOKE FAILED"
    exit 1
fi
