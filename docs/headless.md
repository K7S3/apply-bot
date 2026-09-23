# Headless / CI mode

candid is a terminal CLI, but every command also works from scripts and CI:
add `--json` for machine-readable output, and add `--headless` (or set
`CANDID_HEADLESS=1`) for non-interactive runs.

## --json

Every command and subcommand accepts `--json`. It prints a single JSON
document to stdout (exit 0), e.g.:

```bash
python -m candid match --jd jd.txt --company Acme --role "Data Scientist" --json
python -m candid track list --json
python -m candid prep --company Acme --role "Data Scientist" --json
```

Text-producing commands (tailor, followup, negotiate, mock solution) wrap
their output as `{"text": "..."}`. The one exception is `dashboard`, which
is a local web server and has no meaningful machine output.

## --headless

Place `--headless` **before** the command, or export `CANDID_HEADLESS=1`
(the env var works without the flag):

```bash
python -m candid --headless track list --json
CANDID_HEADLESS=1 python -m candid match --jd jd.txt --json
```

In headless mode candid guarantees:

- **No interactive prompts.** Commands that are inherently interactive
  (`mock coding`, `mock ai`, `mock behavioral`, `mock design`, and the
  `dashboard` web server) refuse immediately instead of blocking on stdin.
- **No decorative output.** Typo suggestions, emoji hints, and warning
  banners are suppressed.
- **Stable, parseable failures.** Any expected failure (bad id, missing
  profile, unknown problem, ...) prints exactly one JSON object to stderr
  and exits 3:

```json
{"error": "No application with id 999. Use `track list` to see ids.",
 "next": "python -m candid track list"}
```

`"next"` is the exact command to run to recover, or a help command.
On success stdout carries the result (JSON when `--json` is given) and the
exit code is 0. Unexpected bugs still raise a traceback (exit 1) so CI
logs show the real failure.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (judge `accepted` for `mock run` too) |
| 1 | Expected failure in interactive mode (friendly error + next step on stderr); unexpected exception (traceback) |
| 2 | Command-line usage error (argparse; typo suggestions shown unless headless) |
| 3 | Expected failure in headless/CI mode (single JSON `{"error", "next"}` on stderr) |

`mock run` exits 1 when the verdict is anything other than `accepted`
(both modes). Interactive typo suggestions and the `Error:`/`Next:` hints
are unchanged when `--headless` is off.
