# Dashboard: local web UI

Prefer clicking to typing? The dashboard is a local web UI over the same
data and commands: profile, tracker, curated jobs, prep packs, salary
lookups, and the "Import your data" section.

## The command

```bash
python -m candid dashboard
python -m candid dashboard --port 8888
python -m candid dashboard --no-browser
```

Flags:

- `--port` — preferred port (default 8765); tries the next 10 if busy.
- `--no-browser` — do not auto-open the browser tab.

## Safety

The dashboard binds to **127.0.0.1 only**: it is reachable from your own
machine and nothing else. Your profile and tracker never leave the laptop.

## What you can do there

- View and edit your profile card.
- Browse the tracker, update statuses, and see funnel stats.
- Review curated jobs from `jobs curate` and promote them.
- Generate prep packs and browse practice problems.
- Import your data: Gmail Takeout mbox and LinkedIn ZIP have guided
  upload flows (same parsers as the CLI `import` / `gmail` / `linkedin`
  commands — see the `imports` topic).

## CLI or dashboard?

Use whichever you reach for. They read and write the same `candid_data/`
store, so a `track add` on the CLI shows up in the dashboard instantly and
vice versa. The CLI is better for scripting and piping (`--json`,
`--out`); the dashboard is better for browsing and reviewing.
