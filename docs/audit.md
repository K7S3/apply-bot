# Audit trail

Every change candid makes to your data is written to an append-only audit log.
It is your proof of what happened, when, and by whom: tracker adds/updates/
removes, imports confirmed from proposals, dismissals, undo operations, and
prunes. Nothing in the log is ever edited or deleted by normal operation.

The log lives at `audit.log` inside your candid data directory (see `candid
config` for the path), with a small `audit.meta.json` sidecar used for
retention bookkeeping.

## What gets logged

Each entry is one JSON line with these fields:

- `seq` - running sequence number (1, 2, 3, ...)
- `id` - short random id (e.g. `a1b2c3d4`) for pointing at one entry
- `ts` - ISO-8601 timestamp (UTC)
- `actor` - who made the change: `cli`, `dashboard`, or `api`
- `command` - the command run, e.g. `track update`
- `entity` - what kind of thing changed: `tracker`, `profile`, `prep`, ...
- `entity_id` - the record's id (a tracker application id, a proposal id, ...)
- `action` - `create`, `update`, `remove`, `undo`, `prune`, ...
- `before` / `after` - full snapshots of the record around the change
- `changes` - field-level diff: `[{field, old, new}, ...]`
- `note` - free-text note
- `prev_hash` / `hash` - hash-chain links (see Tamper-evidence below)

## Browsing and filtering

CLI:

```
candid audit log                                # newest first
candid audit log --entity tracker               # only tracker changes
candid audit log --action update --entity-id 12 # one record's history
candid audit log --since 2026-09-01 --until 2026-09-30 --limit 50
candid audit search "Acme"                      # full-text search
candid audit stats                               # totals by day, action, entity
candid audit export --csv audit.csv             # CSV export (oldest first)
candid audit export --md audit.md               # Markdown export
```

Dashboard: open the **Audit trail** page (the `/audit` route) for a read-only
browser view: filter by entity, action, and free-text search, paginate with
`limit`, and run the integrity check with one click. The dashboard view never
writes anything: it only calls the read endpoints `GET /api/audit` and
`GET /api/audit/verify`.

## Undo rules

`candid undo` (or `candid track undo`) rolls back the most recent tracker
change using the entry's `before` snapshot. Rules:

- **Tracker only.** Undo restores tracker records; it never touches other
  entities and it never edits the log.
- **The log is append-only.** An undo writes a *new* entry with
  `action: "undo"` and a note naming the entry it reverted. History is
  preserved; nothing is rewritten.
- **Only undoable when a snapshot exists.** Entries record `before` snapshots
  precisely so they can be reversed. If the original entry has no `before`
  (e.g. it was pruned, or the change predates audit logging), undo refuses
  rather than guessing.
- **Removals undo by re-adding.** Undoing a `remove` restores the record with
  its original field values and gets a new audit entry of its own.

Because undo itself is logged, you can undo an undo safely: the chain of
what happened stays visible.

## Retention and pruning

The log grows by one line per change, which is small but unbounded. Pruning
keeps it within an age window:

```
candid audit prune --older-than 180d        # dry run: reports only
candid audit prune --older-than 180d --apply  # actually drop old entries
```

- Dry-run is the default: without `--apply` you get a count of what *would*
  be pruned, and nothing changes.
- Pruning drops the oldest entries and records the cut point (last pruned
  `seq` and `hash`) in `audit.meta.json`, so `verify` still passes on the
  surviving chain: it treats the recorded pruned hash as the anchor for the
  first remaining entry.
- Pruning itself is logged as an entry with `action: "prune"`, noting how
  many entries were dropped.

## Tamper-evidence via hash chain

Each entry's `hash` is computed over its own fields plus the previous entry's
`hash`, forming a chain back to the first entry. That means any edit, delete,
or reorder of a line breaks the link for that line and everything after it.

Run the check any time:

```
candid audit verify
```

It reports problems (and nothing, i.e. OK, when the log is clean). It detects:

- corrupt lines (not valid JSON)
- missing or out-of-order sequence numbers
- `prev_hash` links that do not match the previous entry's `hash`
- entry hashes that do not match their content (tampering)

The check is read-only and safe to run on a schedule. If it reports a
problem, treat the log as suspect: candid will not auto-repair it, because
silently "fixing" a tamper-evident log would defeat its purpose. Restore from
a backup, and investigate what touched the file.
