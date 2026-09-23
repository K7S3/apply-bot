# Contributing to candid

Thanks for considering a contribution. candid is a small, local-first project:
every contribution that keeps it honest, private, and easy to run is welcome,
from a typo fix to a whole new command.

## Project principles

Keep these in mind before you write any code:

1. **Local-first, no accounts, no keys, no scraping.** candid never asks for
   API keys or OAuth tokens, never phones home, and never scrapes sites.
   Features must work fully offline with bundled or user-supplied data.
2. **Groundedness: never invent user data.** Every number, claim, or score
   shown to a user must come from their profile or from bundled public data
   (e.g. DOL salary figures). If data is missing, say so instead of guessing.
3. **Errors teach.** A failure should end with the exact next command to run,
   never a bare traceback. See the `_next_command` pattern in
   `candid/__main__.py`.
4. **Small surface area.** Prefer one clear command over three clever ones.

## Quickstart

```bash
git clone https://github.com/K7S3/candid.git
cd candid
./scripts/dev-setup.sh        # or run the steps below by hand
```

Manual steps:

- Python 3.10 or newer (`python3 --version` to check).
- Create a virtualenv: `python3 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt` (stdlib only; nothing to compile)
- Sanity check: `python -m candid --help`
- Run the tests: `python -m unittest discover -s tests -v`

## How to add a feature

Most features follow the same shape:

1. **New module** under `candid/`, e.g. `candid/mentor.py`. One module per
   command area; keep shared helpers small and reusable.
2. **Wire it into the CLI** in `candid/__main__.py`: register a subparser via
   the `_sub(...)` helper, add the command to the command inventory near the
   top of the file, and route it in `main()`. Use argparse; keep help text
   concrete with an example in the epilog.
3. **Add tests** in `tests/test_<name>.py` (see below).
4. **Document it**: add a row to the README feature table and a short page
   under `docs/` (a single Markdown file, e.g. `docs/mentor.md`). The docs
   page should cover: what it does, the command, an example run, and what the
   output means.

## Coding standards

- **stdlib + stdlib-first deps.** Do not add third-party dependencies without
  discussion in the issue/PR first. `requirements.txt` is intentionally
  minimal.
- **Type hints encouraged.** Annotate public function signatures; strict
  mypy is not required.
- **No em dashes in user-facing text.** Use hyphens or commas instead, in
  help text, docs, and error messages.
- Match the existing style: argparse CLI, small functions, early returns,
  no silent failures.

## Test requirements

- Every feature needs tests in `tests/test_<name>.py`, mirroring the module
  name.
- Tests run with `python -m unittest discover -s tests -v`. The full suite
  must be green before a PR is merged.
- Prefer deterministic, fixture-based tests. Do not depend on network access,
  wall-clock time, or files outside the repo (use `tests/fixtures/` or
  tempfile).

## Docs requirements

- Any user-visible change needs a row in the README feature table and a page
  under `docs/`, or an update to an existing page.
- Keep examples copy-pasteable and verified: run the command before writing
  it down.

## PR process

- Keep PRs small and focused: one feature or fix per PR.
- Describe the change, how you tested it, and the commands you ran.
- If the repo has a PR template, fill it out. CI runs the full test suite;
  fix failures before requesting review.
- A maintainer review is required before merge.

## Reporting bugs

- Open an issue using the bug template. Include: the exact command you ran,
  what you expected, what happened (copy the output, not a screenshot),
  your Python version (`python3 --version`), and your OS.
- candid never sends data anywhere, so you can paste full command output
  without worrying about leaking credentials. Still, redact any personal
  data in resumes or JDs before posting.

## Getting help

- Start with `python -m candid --help` and the `docs/` pages.
- Look for issues tagged `good first issue`; they are scoped to be doable in
  one sitting.
- Not sure where something lives? Open an issue and ask; questions become
  docs.
