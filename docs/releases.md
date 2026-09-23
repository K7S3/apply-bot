# candid release checklist

## Checklist (run in order)

1. **Full suite green.** From a clean checkout on the release branch:

   ```bash
   python -m unittest discover -s tests -v
   ```

   Zero failures, zero errors. If anything is red, stop and fix it before
   continuing.

2. **README feature table update.** The README lists every command and
   feature. If the release adds, renames, or removes anything user-visible,
   update the README sections (command examples, feature list, dashboard
   notes) so they match `candid/__main__.py` `COMMANDS` exactly.

3. **Version bump.** The single source of truth is `__version__` in
   `candid/__init__.py`. Bump it per the semver policy below and confirm no
   other file hardcodes the old version:

   ```bash
   grep -rn "0\.2\.0" --include="*.py" --include="*.md" . | grep -v tests
   ```

4. **Pre-release secrets/PII check.** Before tagging, verify the tree is
   clean of anything that must never be public:

   ```bash
   git status --porcelain            # nothing unexpected staged
   git ls-files | grep -E 'profile\.yaml$|^output/|run_ollama_shim\.py$' \
     && echo "BLOCKED: secrets/PII-adjacent file tracked" || echo OK
   grep -rniE "api[_-]?key|secret|token|password" --include="*.py" candid/ \
     | grep -vi "no .* key" || echo OK
   ```

   Rules: `profile.yaml` (real user profile) is never committed, `output/`
   is never committed, and `run_ollama_shim.py` (local dev helper) is never
   committed. The committed `profile.yaml.example` is the only profile file
   allowed in the tree. If the check finds a real credential, rotate it
   before proceeding; the release waits.

5. **Tag.** Create an annotated tag on the release commit:

   ```bash
   git tag -a vX.Y.Z -m "candid vX.Y.Z: <one-line summary>"
   git log -1 --format=%H vX.Y.Z     # confirm the tag points at the release commit
   ```

6. **Push.**

   ```bash
   git push origin batch-<n>   # or main, per the release plan
   git push origin vX.Y.Z
   ```

7. **Verify.** After pushing:
   - `git ls-remote --tags origin` shows `vX.Y.Z`.
   - A fresh clone of the tag passes `python -m unittest discover -s tests -v`.
   - `python -m candid --version` prints the new version.

## Semver policy

candid ships **feature batches**, and the version tracks them:

- **Minor (`0.Y.0`)** for every feature batch: new commands, new modules,
  new dashboard sections, new data sources. This is the normal release.
  Example: batch-112 ships as `0.3.0`.
- **Patch (`0.Y.Z`)** for bug fixes and doc-only fixes with no behavior
  change.
- **Major (`1.0.0`)** is reserved for a future stable CLI contract. Until
  then, `0.x` signals the CLI surface may still change between batches.

Rules of thumb:

- One batch, one minor bump. Never bump twice for the same batch.
- `__version__` in `candid/__init__.py` is the only place the version
  lives; tags (`vX.Y.Z`) mirror it exactly.
- The README "what's new" note (if any) references the batch number and
  the version together, e.g. "batch-112 (v0.3.0)".

## Rollback

If a pushed release is broken: do not force-push or delete the tag. Cut a
patch release (`0.Y.Z+1`) with the fix and note the superseded version in
the release notes. Tags are append-only history.
