# Release process

How to cut a candid release. Releases are manual by design: `scripts/release.sh`
builds and verifies everything locally, and a human does the tag, the PyPI
upload, and the GitHub release.

## 1. Version bump

The single source of truth is `candid/__init__.py`:

```python
__version__ = "0.3.0"
```

Bump it in its own commit before anything else (semver: patch for fixes,
minor for features, major for breaking changes).

## 2. Changelog

Generate a draft entry from the git history since the last tag:

```bash
python scripts/changelog.py v0.2.0 HEAD --output CHANGELOG.md
```

Review the entry (the grouping is heuristic, edit it into final shape),
commit it:

```bash
git add CHANGELOG.md candid/__init__.py
git commit -m "chore: release 0.3.0"
```

## 3. Tag

Annotated tags only, named `v<version>`:

```bash
git tag -a v0.3.0 -m "candid 0.3.0"
git push origin main          # or your feature branch, then merge
git push origin v0.3.0
```

## 4. Build and verify

One command runs the test suite, builds sdist+wheel, runs `twine check`,
writes `dist/SHA256SUMS`, and prints the manual upload checklist:

```bash
bash scripts/release.sh
```

Notes:

- The script is idempotent (dist/ and build/ are rebuilt from scratch) and
  never uploads anything. It fails cleanly with exit code 2 and a clear
  message if `pyproject.toml` is missing (packaging lives with the W-pkg
  batch) or the `build` package is not installed.
- `twine` is optional: if it is not installed, the script skips
  `twine check` with a warning instead of failing.
- `RELEASE_SKIP_TESTS=1` skips the pytest step when the suite already ran
  (for example, in CI). Never ship a release that skipped tests without
  running them separately.
- `dist/`, `build/`, and `dist/SHA256SUMS` are git-ignored and must never
  be committed. The same goes for `profile.yaml`, `output/`,
  `run_ollama_shim.py`, and anything with secrets or PII.

## 5. Upload to PyPI

Needs a PyPI account with the `candid` project. Copy `.pypirc.example`
to `~/.pypirc`, fill in an API token (never commit it), then:

```bash
twine upload dist/*
```

Verify the release renders correctly at
`https://pypi.org/project/candid/<version>/`.

## 6. GitHub release

Create the release at `https://github.com/K7S3/candid/releases/new`,
choosing the `v<version>` tag. Attach `dist/*` and `dist/SHA256SUMS`,
and paste the matching CHANGELOG.md entry as the release notes.

## 7. Homebrew formula bump

There is no Homebrew tap yet. When one exists (for example,
`homebrew-candid` with a `candid.rb` formula), a release bumps it:

1. Download the sdist and get its SHA256: `sha256sum dist/candid-<version>.tar.gz`
2. Update `url` and `sha256` in `candid.rb` in a `bump <version>` commit
3. Push to the tap repo; verify with `brew install --build-from-source candid.rb`

Until a tap exists, this step is intentionally a no-op.

## Quick checklist

1. Bump `__version__` in `candid/__init__.py`
2. `python scripts/changelog.py <last-tag> HEAD --output CHANGELOG.md`, review, commit
3. `git tag -a v<version> -m "candid <version>"` and push tag
4. `bash scripts/release.sh` and fix anything it flags
5. `twine upload dist/*`, verify on PyPI
6. GitHub release with attached artifacts and SHA256SUMS
7. Homebrew formula bump (once a tap exists)
