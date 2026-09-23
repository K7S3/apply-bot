# Per-application notes and file attachments

`candid/appnotes.py` keeps unstructured material next to each tracked
application — timestamped notes and copied files. `candid/tracker.py` is
untouched; notes and attachments reference the tracker only to validate
that an `app_id` exists (`tracker.list_apps`).

## Storage (all under the git-ignored data dir)

- Notes: `candid_data/app_notes.json` — `{ "<app_id>": [{timestamp, text}] }`
- Attachments: `candid_data/attachments/<app_id>/<sanitized-name>`; metadata in
  `candid_data/attachments.json`

Attachments are **copied**, never moved, so the user's originals are safe.
Filenames are sanitized (path components stripped, unsafe chars replaced),
and name collisions get a `_2`, `_3` suffix. The total stored size per
application is capped at 25 MiB (`MAX_ATTACHMENT_BYTES`); exceeding it raises
`AppNotesError` with a clean message instead of silently dropping the file.

## API

```python
from candid import appnotes as A

A.add_note(3, "met hiring manager at meetup")   # -> {"timestamp": ..., "text": ...}
A.list_notes(3)                                  # oldest first
A.render_notes(3, A.list_notes(3))               # human-readable text

A.attach(3, "offer_letter.pdf")                  # -> metadata dict
A.list_attachments(3)                            # oldest first
A.open_path(3, "offer_letter.pdf")               # -> Path under the data dir
A.render_attachments(3, A.list_attachments(3))
```

All public functions take an optional `path` (notes-file path or data-dir
override); tests point it at throwaway dirs. Errors raise `AppNotesError`
with the next command embedded (e.g. `python -m candid track list`).

## CLI (registration in CLI_REGISTRATION.txt)

```
python -m candid note add --app-id 3 "referral from Sam"
python -m candid note list --app-id 3
python -m candid attach add --app-id 3 resume_tailored.pdf
python -m candid attach list --app-id 3
```
