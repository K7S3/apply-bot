# ADR 0003: stdlib unittest Over pytest

- Status: accepted
- Date: 2026-09-22 (retrospective; true since the first test was written)

## Context

candid needed a test story from day one: every feature batch ships tests,
and contributors should be able to run them with nothing installed beyond
what the project itself needs. The two candidates were the standard-library
`unittest` framework and the third-party `pytest` runner.

The constraint that decided it is in `requirements.txt`: candid is
**stdlib-only by design**. The header comment reads "candid is stdlib-only
by design", and the single declared dependency, `pypdf>=3.0.0`, is optional
and needed only for `onboard --resume file.pdf` (PDF text extraction).
Everything else, matching, tailoring, tracker, dashboard, judge, runs on
the standard library alone.

## Decision

- All tests are written with stdlib `unittest`: `TestCase` subclasses,
  `test_*` methods, `self.assert*` assertions, runnable with
  `python -m unittest discover -s tests -v`.
- No pytest, no plugins, no test-only third-party packages. `requirements.txt`
  stays exactly as it is: one optional line for `pypdf`.
- The contributor setup stays a single step: clone, optionally
  `pip install -r requirements.txt`, run the discover command. This mirrors
  the local-first principle (ADR 0002): a contributor's machine needs no
  network to run the suite.

## Consequences

- Positive: zero test-dependency drift; the suite runs anywhere Python
  runs, offline, with no install step at all.
- Positive: one less thing to document, pin, and audit in the release
  checklist (`docs/releases.md`).
- Negative: no pytest conveniences (fixtures, parametrize, richer
  assertion introspection). Mitigated by convention: `setUp`/`tearDown`
  methods, `tempfile` isolation, and the per-area file layout in
  `docs/testing.md`. So far this has been enough for the whole suite,
  including the timeout-sensitive judge tests.
- Neutral: if the suite ever outgrows what `unittest` expresses cleanly,
  the decision can be revisited with a new ADR that supersedes this one.
