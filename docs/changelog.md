# Changelog generator

`candid changelog` builds a changelog straight from your git history. No
external dependencies, stdlib only: it parses `git log` with an
unambiguous unit-separator format and renders Keep-a-Changelog style
Markdown, plain text, a GitHub release body, or JSON.

## Subcommands

### generate

Build the changelog and print it, or write it to a file.

```bash
python -m candid changelog generate
python -m candid changelog generate --since v0.1.0 --format github
python -m candid changelog generate --output CHANGELOG.md --no-stats
```

- `--since REF`: git ref or tag to start from. Default: the most recent
  tag (so releases only cover changes since the last release). Repos with
  no tags cover the full history.
- `--format`: `markdown` (default), `plain`, `json`, or `github`.
- `--output FILE`: write the rendered changelog to FILE (parent dirs are
  created).
- `--repo PATH`: point at another repo (default: current directory).
- `--stats` / `--no-stats`: include the stats section in Markdown output
  (on by default).

### check

Verify an existing CHANGELOG.md actually covers the git history since the
reference. Useful as a pre-release gate (see CI recipe below).

```bash
python -m candid changelog check
python -m candid changelog check --file CHANGELOG.md --since v0.1.0
```

`check` reads the first `## ` section of the file and fails with a list of
the commit subjects missing from it. Regenerate with `changelog generate
--output <file>` to fix.

### suggest-bump

Print a semver bump suggestion based on the commits in range.

```bash
python -m candid changelog suggest-bump
python -m candid changelog suggest-bump --since v0.1.0
```

Output looks like:

```
bump: minor
version: 0.2.0 -> 0.3.0
```

## Categorization rules

Each commit is sorted into one of `breaking, feat, fix, perf, docs,
refactor, test, chore, other`, which map to section titles like
"Breaking Changes" and "Features". Breaking commits appear only under
Breaking Changes.

1. **Conventional commits first.** `type(scope)!: subject` is parsed for
   the type (`feat`, `fix`, `docs`, ...). Known types map to categories,
   unknown types fall into Other.
2. **Keyword fallback.** Commits without a prefix are matched against an
   ordered keyword list: feat (`add`, `new`, `feature`, ...) is tried first,
   then fix, docs, perf, test, refactor, chore, in that order; the first
   match wins. No match means Other.
3. **Breaking detection.** A commit counts as breaking if the subject ends
   with `!` after the type (`feat(api)!: ...`), the body contains a
   `BREAKING CHANGE` / `BREAKING-CHANGE` trailer (case-insensitive), or the
   subject starts with `BREAKING`.

## Version-bump semantics

`suggest-bump` applies the highest-impact rule first:

- any breaking change: **major**
- any `feat`: **minor**
- any `fix`, `perf`, `docs`, `refactor`, or `test`: **patch**
- otherwise (only `chore` / `other`, or no commits): **none**

## Formats

- `markdown`: Keep-a-Changelog style with `## [version] - date` header,
  per-category `### ` sections (empty ones skipped), commit subject, short
  SHA, author per entry, and a Stats section (commit count, per-category
  counts, authors, date range).
- `plain`: same content without Markdown syntax.
- `github`: starts with `## What's Changed` for pasting into a release,
  and adds a `**Full Changelog**: <repo>/compare/<since>...<version>`
  compare link when version and since are both known.
- `json`: structured payload with version, since, per-category entry
  lists, and stats, for scripting.

## CI recipe: pre-release gate

Fail the release job if CHANGELOG.md does not cover the git history:

```yaml
- name: Check changelog coverage
  run: python -m candid changelog generate --output CHANGELOG.md
- name: Gate
  run: python -m candid changelog check --file CHANGELOG.md
```

Tag-based flow: keep a generated CHANGELOG.md current, tag your release,
then `changelog generate` automatically scopes the next release's changes
to `since` the new tag.
