# Demo tour

`python -m candid demo` runs a narrated, non-interactive, 60-second tour of
the core loop - **onboard -> match -> tailor -> track -> prep** - against
the fictional sample data in `samples/candid/` (Alex Rivera's sample resume
and a sample JD at the fictional Acme Analytics). Nothing is real; the tour
says so up front.

It prints each step with the equivalent real command (so you can copy what
you like), shows the key outputs (profile card, match score and verdict,
tailored resume excerpt, tracker row, prep-pack preview), and exits 0.

## Your data is untouched

The tour redirects candid's data directory to a fresh temporary directory
in-process (`candid/demo.py` rebinds the `candid.config` paths and sets
`CANDID_DATA_DIR`), runs everything there, then removes the temp dir and
restores your configuration. Your real profile, tracker, and other data are
never read or written.

## Inspect the demo data

```bash
python -m candid demo --keep /tmp/candid-demo
```

With `--keep DIR`, the demo data is persisted in `DIR` instead of a temp
dir: `profile.json`, `tracker.json`, `tailored/`, `prep_packs/`. Poke
around, then delete it whenever.

## Notes for contributors

- The tour calls the same library functions as the CLI commands
  (`profile.onboard`, `match.score_match`, `tailor.build_resume`,
  `tracker.add`, `prep.build_pack`) - it is an integration smoke test of
  the happy path as well as a tour.
- Keep it fast (seconds, not minutes) and non-interactive: no prompts, no
  network, no browser.
- The `demo` command is registered via `candid/demo.py::register`
  (wired into the CLI by the coordinator); it takes no dependency on
  `candid.__main__` at import time.
