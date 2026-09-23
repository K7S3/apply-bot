# Sync: your data on two machines, no cloud

`python -m candid sync` moves your candid data between your own machines as
portable bundle files. There is no server, no account, no login, no key, and
no network call. You export a zip, carry it over a channel you trust (USB
stick, your own cable, your own encrypted drive), and import it on the other
machine.

## Security model (read this first)

- **Integrity, not secrecy.** Every bundle carries a manifest with SHA-256
  checksums for each file; `sync verify` and every import check them before
  anything is written. A tampered bundle is refused.
- **Bundles are NOT encrypted.** Anyone holding the zip can read your data.
  Treat the bundle like the data itself: use a channel you trust, and delete
  it from the transport medium after importing.
- **Pairing is identity, not encryption.** Pairing pins the machine ids you
  sync with; once paired, this machine refuses bundles from unknown machines.
  It does not hide bundle contents.

## Quick start

On machine A:

```bash
python -m candid sync pair init --name laptop --out /media/usb/pair.json
```

Carry the pairing file to machine B, run there:

```bash
python -m candid sync pair accept /media/usb/pair.json
```

Now export on machine A, carry the zip to machine B, import:

```bash
# machine A
python -m candid sync export /media/usb/

# machine B
python -m candid sync verify /media/usb/candid-sync-*.zip
python -m candid sync import /media/usb/candid-sync-*.zip
```

`export` names the bundle `candid-sync-<machine>-<timestamp>.zip` when you
point it at a directory. `--dry-run` previews without writing.

## Full vs delta bundles

- **Full** (`sync export DEST`) snapshots every synced category.
- **Delta** (`sync export --since-last DEST`) includes only files changed
  since the last sync, plus a record of deleted paths. Deltas are smaller and
  are applied with `sync import` automatically (the manifest says which).
- If the other machine never synced with this one, a delta import fails with
  a base-mismatch error and tells you to send a full bundle first.

## Selective sync

```bash
python -m candid sync export ~/usb --include tracker,prep
python -m candid sync export ~/usb --exclude gmail,salary
```

Categories: profile, tracker, offers, salary, prep, tailored, gmail. Excludes
win over includes. Missing data is skipped silently.

## Import modes

- **replace** (default): overwrite local files with the bundle's. Overwritten
  files are backed up under `candid_data/sync/backups/` first.
- **merge** (`--mode merge`): three-way merge against the last sync base.
  - Unchanged, local-only, and remote-only changes apply automatically.
  - Tracker JSON merges at the record level by application id; disjoint
    edits to different records merge cleanly.
  - Same-record edits on both sides (or file conflicts) are recorded as
    pending conflicts instead of guessing.

Preview any import with `--dry-run` first; it reports new/changed/unchanged
without writing anything.

## Conflicts

```bash
python -m candid sync conflicts list
python -m candid sync conflicts resolve --ref 0 --choice remote
```

Choices: `local`, `remote`, `newer`, `older` (by embedded timestamps; exact
ties keep local). Record-level conflicts apply the winner to that one record;
file conflicts swap the whole file (remote bytes are stashed until resolved).

## Merge rules

Set a per-category strategy used during merges:

```bash
python -m candid sync rules set tracker newer-wins
python -m candid sync rules show
python -m candid sync rules clear tracker
```

Strategies: `auto` (default), `local-wins`, `remote-wins`, `newer-wins`,
`manual` (always record a conflict). `local-wins`/`remote-wins` decide whole
files; `newer-wins` decides per tracker record.

## Pairing

```bash
python -m candid sync pair init --name laptop --out /tmp/pair.json
python -m candid sync pair accept /tmp/pair.json
python -m candid sync pair list
python -m candid sync pair remove m-xxxx
```

The pairing file is one-time: it carries a random token and must travel over
your trusted channel. Only the token's SHA-256 is stored after acceptance.
Self-pairing is refused. Once at least one peer is registered, bundles from
unknown machines are refused at import.

## History, status, bookkeeping

```bash
python -m candid sync status     # machine id, last import/export, conflicts, peers
python -m candid sync log        # append-only history of syncs (--limit N)
python -m candid sync log --json
```

Sync state lives under `candid_data/sync/`: base snapshots (hashes of what
was last synced), backups of overwritten files, the conflict list, the
pairing registry, merge rules, and the history log. Your machine identity
lives under your config dir (`sync/machine.json`).

## Backup and recovery

- Every replace-import backs up overwritten files with timestamps; restore by
  copying them back.
- Merge failures leave local data untouched (nothing is applied when a merge
  cannot complete).
- `sync verify FILE` checks any bundle without importing it.

## Limitations

- Bundles are integrity-checked but not encrypted; the transport channel must
  be trusted.
- Base snapshots store hashes, not old record bodies, so same-record
  conflicts are resolved conservatively (no automatic three-way content
  merge for the differing record).
- Record deletions are not tracked as deletions; a deleted record can
  reappear when a bundle from a machine that still has it is merged in.
- Export and import are manual steps; nothing runs in the background.
