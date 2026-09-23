#!/usr/bin/env bash
# Dev setup for candid.
# Usage: ./scripts/dev-setup.sh [--skip-tests]
#
# Creates a local .venv, installs requirements into it only (no sudo, nothing
# system-wide), verifies the CLI starts, and runs the test suite.
set -euo pipefail

SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."

echo "==> Checking python3 (need >= 3.10)..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found on PATH." >&2
  exit 1
fi
PY_VER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')"
if [ "$PY_OK" != "1" ]; then
  echo "ERROR: python3 >= 3.10 required, found $PY_VER." >&2
  exit 1
fi
echo "    found python3 $PY_VER"

echo "==> Creating .venv (if missing)..."
if [ ! -d .venv ]; then
  python3 -m venv .venv
  echo "    created .venv"
else
  echo "    .venv already exists, reusing"
fi
VENV_PY=".venv/bin/python"

echo "==> Installing requirements into the venv only..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt
echo "    requirements installed"

echo "==> Verifying the CLI starts..."
"$VENV_PY" -m candid --help >/dev/null
echo "    python -m candid --help OK"

if [ "$SKIP_TESTS" -eq 1 ]; then
  echo "==> Skipping test suite (--skip-tests)"
else
  echo "==> Running test suite..."
  "$VENV_PY" -m unittest discover -s tests
  echo "    tests passed"
fi

echo ""
echo "Done. Next steps:"
echo "  1. Activate the venv:  source .venv/bin/activate"
echo "  2. Copy profile.yaml.example to profile.yaml and fill it in (never commit profile.yaml)"
echo "  3. Try:                 python -m candid --help"
echo "  4. Run tests again:     python -m unittest discover -s tests"
