#!/usr/bin/env bash
# release.sh - one-command release helper for candid.
#
# Steps (all read-only / local, nothing is ever uploaded automatically):
#   1. Run the test suite
#   2. Build sdist + wheel into dist/
#   3. Run `twine check` on the built artifacts
#   4. Write SHA256 checksums to dist/SHA256SUMS
#   5. Print a manual upload checklist (tag, twine upload, GitHub release)
#
# Idempotent: dist/ and build/ are removed and rebuilt from scratch each run.
#
# Environment overrides:
#   RELEASE_SKIP_TESTS=1   skip the pytest step (faster re-runs / CI that tests separately)
#   RELEASE_REPO_ROOT      override the repo root (used by tests)
#
# Requires: pyproject.toml in the repo root, `python -m build` installed.
# `twine` is optional: if it is missing, twine check is skipped with a warning.
#
# Exit codes:
#   0 - everything done (or skipped twine) successfully
#   1 - a step failed (tests, build, twine check, checksum)
#   2 - configuration error (pyproject.toml missing, build module missing)

set -euo pipefail

REPO_ROOT="${RELEASE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT"

step() { printf '\n=== %s ===\n' "$1"; }

# --- Fail fast: is this tree releasable? ---
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  cat >&2 <<'EOF'
ERROR: pyproject.toml not found in repo root.

release.sh needs packaging metadata (pyproject.toml) to build sdist/wheel.
This tree may predate the W-pkg packaging work. Options:
  1. Pull the packaging batch's work (adds pyproject.toml) and re-run.
  2. Create a minimal pyproject.toml by hand and re-run.

Nothing was built, tested, or uploaded.
EOF
  exit 2
fi

if ! python3 -c "import build" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: the `build` package is not installed (needed for sdist/wheel).

Install it with: python3 -m pip install build
Then re-run scripts/release.sh. Nothing was built, tested, or uploaded.
EOF
  exit 2
fi

# --- Step 1: tests ---
if [[ "${RELEASE_SKIP_TESTS:-0}" == "1" ]]; then
  echo "SKIP: test suite (RELEASE_SKIP_TESTS=1)"
else
  step "1. Test suite"
  python3 -m pytest tests/ -q
fi

# --- Step 2: build (clean first, so re-runs are identical) ---
step "2. Build sdist + wheel"
rm -rf dist/ build/
python3 -m build --sdist --wheel --outdir dist/

# --- Step 3: twine check (optional) ---
step "3. twine check"
if ! command -v twine >/dev/null 2>&1; then
  cat <<'EOF'
WARNING: `twine` is not installed, skipping twine check.
Run `twine check dist/*` yourself before uploading, or install it with:
  python3 -m pip install twine
EOF
else
  twine check dist/*
fi

# --- Step 4: checksums ---
step "4. SHA256 checksums"
( cd dist && sha256sum -- ./*.tar.gz ./*.whl > SHA256SUMS )
echo "Wrote dist/SHA256SUMS:"
cat dist/SHA256SUMS

# --- Step 5: manual checklist ---
step "5. Manual release checklist (nothing below runs automatically)"
VERSION="$(python3 -c 'import candid; print(candid.__version__)' 2>/dev/null || \
  python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || \
  echo 'x.y.z')"
cat <<EOF
[ ] git add CHANGELOG.md and commit any release notes
[ ] git tag -a v${VERSION} -m "candid ${VERSION}"
[ ] git push origin batch-101-release  (merge first, then push the tag)
[ ] git push origin v${VERSION}
[ ] twine upload dist/*                 (needs ~/.pypirc or a PyPI API token)
[ ] Verify the release on PyPI: https://pypi.org/project/candid/${VERSION}/
[ ] Create the GitHub release: https://github.com/K7S3/candid/releases/new?tag=v${VERSION}
      attach dist/* and dist/SHA256SUMS, paste the CHANGELOG.md entry as notes
[ ] Homebrew: see docs/release.md "Homebrew formula bump" for the next steps

Artifacts are in dist/ (git-ignored, never committed).
EOF
