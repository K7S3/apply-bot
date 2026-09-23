# Crash log, bug reports, and diagnostics

candid keeps a **local crash log** so that when something goes wrong you can
inspect it, and — only if you choose — turn it into a redacted bug report to
share. Nothing ever leaves your machine automatically.

## What is logged

When an uncaught exception escapes a candid command, the crash hook (installed
at CLI startup by `candid.crashlog.install_crash_hook()`) writes **one
record** to the log. Each record contains:

- `id` — a random 12-hex-char crash id
- `ts` — timestamp (local timezone, ISO)
- the command that crashed (e.g. `match`) plus the redacted argv
- `exc_type` and `exc_msg` — exception type and message
- the traceback as structured **frames** (file basename only, module, function,
  line — no user paths), **redacted before anything is written**
- `traceback_hash` — a dedupe hash of the redacted frames (crashes with the
  same signature group together in `crashlog stats`)
- candid / Python / platform version info

The hook also drops a **last-crash marker** (`candid_data/.last_crash`) holding
the crash id. The next time you run any candid command, the CLI prints a
one-line pointer to stderr:

```
Note: candid crashed during the previous run (ValueError in 'match').
Run 'candid crashlog show 3fa1b2c4d5e6' or 'candid bug-report' to inspect.
```

The marker is cleared right after the note is shown, so you see it once.

## Where it lives

Everything is under your data dir (`CANDID_DATA_DIR`, default
`./candid_data/`):

| Path | Contents |
|---|---|
| `candid_data/crash.log` | Crash records, one JSON object per line |
| `candid_data/crash.log.1` … | Rotated files (see retention below) |
| `candid_data/.last_crash` | Marker for the most recent crash (one JSON object) |
| `candid_data/bug_reports/` | Bug reports you generated locally |

## Rotation and retention

The log is bounded so it can never grow without limit:

- **Size:** when `crash.log` exceeds `CRASH_LOG_MAX_BYTES` (1 MB), it rotates;
  the last `CRASH_LOG_KEEP` (5) rotated files are kept.
- **Age:** records older than `CRASH_LOG_MAX_AGE_DAYS` (90 days) are pruned.
- `crashlog clear` wipes the log files and the last-crash marker.

(See `candid/config.py` for the constants.)

## What redaction covers

Redaction (`candid/redact.py`) is applied **before** a crash record is
written, and again when a bug report is built. The covered PII kinds are
`token`, `email`, `mac`, `ip`, `sid`, `home`, `username`, and `phone`:

- your home directory and username (`/home/you/...` becomes `<HOME>`/`[USER]`)
- email addresses (`[EMAIL]`), phone numbers (`[PHONE]`)
- things that look like API keys / tokens / session ids (`[TOKEN]`, `[SID]`)
- IP and MAC addresses (`[IP]`, `[MAC]`)
- hostnames in platform strings (`[HOST]`)
- absolute file paths outside the project (frames store basenames only;
  argv paths get `<HOME>`)

Every generated report embeds a **Redaction audit** section listing exactly
which patterns were detected and replaced. Inspect it before you share
anything.

## The opt-in model

Local-first, always:

1. The crash log is local. candid has no telemetry and phones nothing home.
2. `candid bug-report` builds a **redacted Markdown report on your machine**
   and prints a preview. Nothing is uploaded, emailed, or sent anywhere.
3. `--opt-in` only *unlocks generating the shareable file*
   (`bugreport.prepare_shareable()`, which returns the report path plus
   manual-sharing instructions). Sharing itself is a manual paste by
   you — candid never sends the report.
4. `bug-report --status` shows the current consent state (`--opt-in` /
   `--opt-out` change it; undecided is the default). Consent lives in
   your config dir (`~/.config/candid/consent.json`,
   overridable via `CANDID_CONFIG_DIR`).

## Command reference

```bash
python -m candid crashlog list                  # recent crashes: time, command, type, hash
python -m candid crashlog list --limit 5 --json # JSON for scripting
python -m candid crashlog show 3                 # full detail of one crash
python -m candid crashlog show a1b2c3d4         # ...or by hash prefix
python -m candid crashlog stats                 # totals, groups by signature, top exceptions
python -m candid crashlog clear                 # asks for confirmation first
python -m candid crashlog clear --yes           # skip the prompt

python -m candid bug-report                     # report for the latest crash: preview + saved file
python -m candid bug-report --id 3 --out /tmp/r.md
python -m candid bug-report --show-redactions   # where to find the report's redaction audit
python -m candid bug-report --status            # show consent state
python -m candid bug-report --opt-in            # allow shareable-file generation
python -m candid bug-report --opt-out           # disallow it again

python -m candid diagnostics                    # redacted diagnostics bundle
python -m candid diagnostics --json             # JSON for scripting
```

See the [README](../README.md) for the rest of the CLI.
