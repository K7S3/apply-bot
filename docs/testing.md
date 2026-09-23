# candid testing guide

candid uses Python's standard-library `unittest` only. No pytest, no
third-party test plugins (see `docs/adr/0003-unittest-over-pytest.md` for why).
All suites run with one command from the repo root:

```bash
python -m unittest discover -s tests -v
```

The literal command the test suite checks for is `python -m unittest discover`
(`docs/testing.md` must contain it verbatim).

## Running tests

Full suite (verbose), from the repo root:

```bash
python -m unittest discover -s tests -v
```

A single test file:

```bash
python -m unittest tests.test_core -v
```

A single test class or method:

```bash
python -m unittest tests.test_core.ProfileTest -v
python -m unittest tests.test_core.ProfileTest.test_onboard_writes_json -v
```

One file's tests with the discover command:

```bash
python -m unittest discover -s tests -p "test_core.py" -v
```

## Conventions

1. **unittest only.** Test classes subclass `unittest.TestCase`, methods are
   named `test_*`, assertions use `self.assertEqual` and friends.
2. **Tempfile isolation.** Tests never touch a real `candid_data/`
   directory. Point the data dir at a throwaway location before importing
   candid modules:

   ```python
   import os, tempfile
   os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp()  # or a fixed /tmp path
   ```

   `candid/config.py` reads `CANDID_DATA_DIR` at import time, so set the env
   var before the first `from candid import ...`. Several existing test
   files set it at module top level; follow the same pattern.
3. **samples/ fixtures.** Fictional fixtures live in `samples/candid/`:
   `sample_resume.md` (Alex Rivera), `sample_jd.txt`, `sample_lca.csv`.
   Reuse them; do not invent PII or real company data in tests. If you need
   a new fixture shape, build it inline with `tempfile`.
4. **Never touch real user data.** No test may read `~/candid_data`,
   `./candid_data` from a real checkout, `profile.yaml`, `output/`, or any
   secrets. If a test needs to exercise import parsing, hand it a fixture
   file from `samples/` or a temp file.
5. **Hermetic.** No network calls. The judge tests (`mock_judge`) spawn local
   subprocesses only, with the same timeouts as production code.
6. **One file per area.** Name it `tests/test_<module-or-area>.py`
   (e.g. `tests/test_match_tailor.py`, `tests/test_ingest_track.py`).
   The discover pattern picks up `test_*.py` automatically.
7. **Docstring at the top of each test file** stating what area it covers,
   mirroring the existing files.

## Skeleton for a new module test file

Save as `tests/test_<module>.py`:

```python
"""Tests for candid.<module>: <one-line description of the area covered>."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp()

SAMPLES = ROOT / "samples" / "candid"


class TestMyModule(unittest.TestCase):
    def setUp(self):
        from candid import mymodule as M
        self.M = M

    def test_basic_behavior(self):
        result = self.M.some_function("input fixture")
        self.assertEqual(result["status"], "ok")

    def test_failure_is_clean(self):
        # expected failures raise the module's own Error class, no tracebacks
        from candid import mymodule as M
        with self.assertRaises(M.MyModuleError):
            M.some_function("bad input")

    def test_never_touches_real_data_dir(self):
        from candid import config as C
        self.assertNotEqual(str(C.DATA_DIR),
                            str(ROOT / "candid_data"))


if __name__ == "__main__":
    unittest.main()
```

Notes on the skeleton:

- Set `CANDID_DATA_DIR` before any `from candid import ...` so
  `config.py` picks up the temp dir.
- `setUp` (re)imports the module under test so each test gets a clean
  reference; add `tearDown` to remove temp files you created outside
  `TemporaryDirectory` contexts.
- Cover both the happy path and the module's expected-error path (every
  feature module defines its own `*Error`, listed in
  `candid/__main__.py` `_EXPECTED_ERRORS`).

## Coverage guidance

- Every new feature batch ships tests in the same batch. A batch with zero
  new tests is incomplete.
- Aim for: every public function exercised on the happy path, every
  `*Error` raised at least once, and CLI smoke coverage for new commands
  (parse args, run the dispatch, assert the output mentions the expected
  result). `tests/test_cli_ux.py` is the model for CLI-level tests.
- Dashboard data functions (in `candid/dashboard.py`) are tested without
  HTTP: import them and call them directly. Only `serve()` needs a live
  socket; bind it to port 0 or a high temp port in tests.
- The judge (`candid/mock_judge.py`) already has timeout-sensitive tests;
  keep them fast (small problems, short inputs) so the suite stays green on
  slow machines.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Tests read your real `candid_data/` | `CANDID_DATA_DIR` set after importing candid | Set the env var at module top, before any `from candid import ...` |
| `ModuleNotFoundError: candid` | Wrong working directory | Run from the repo root so `candid/` is importable, or keep the `sys.path.insert` block |
| A test passes alone but fails in the suite | Shared state: module-level caches or env leakage | Reset in `setUp`/`tearDown`; use `tempfile.TemporaryDirectory` per test |
| Judge tests hang | Subprocess timeout changed or problem file missing | Keep timeouts small; load problems from `candid/data/problems/` only |
| `discover` finds zero tests | File name does not match `test_*.py` | Rename to `tests/test_<area>.py` |

If the full suite is green locally but a CI run fails, check for
platform-specific assumptions first (path separators, locale, `/tmp`
availability) before changing production code.
