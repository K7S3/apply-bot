# Drafting context: context packets and thread summaries

The `candid.drafting` package builds **drafts only**. Nothing in it sends
email, opens sockets, or makes network calls. These two modules assemble the
facts a drafter (or a later template/LLM step) needs, straight from the
application tracker.

## Modules

### `candid.drafting.context`

`build_context(company, tracker=None, app_id=None) -> dict`

Assembles one context packet for drafting an email about a company.

- `company`: company name (substring match, case-insensitive; exact match
  preferred).
- `tracker`: a path to a `tracker.json` file, a ready-made list of
  application records, or `None` to read the default tracker via
  `candid.tracker.list_apps`.
- `app_id`: when several records match, select one by id.

Packet fields:

| field | source |
|---|---|
| `company` | record's company, or the query |
| `found` | whether a record matched |
| `application_id`, `role`, `status`, `stage`, `jd_link`, `notes` | tracker record (`stage` mirrors `status`) |
| `applied_date` | record `date_added`, ISO or `""` |
| `last_contact` | latest of `date_updated`, `date_added`, `status_history` dates |
| `days_since_applied`, `days_since_last_contact` | whole days vs today, `None` when unknown |
| `interviewers` | record `interviewers` (list; string coerced) |
| `company_notes` | `company_notes.json` next to the tracker file (or under the data dir), keyed case-insensitively |
| `open_questions` | record `open_questions` |

Missing data yields empty fields (`""`, `[]`, `None`), never exceptions.
A malformed tracker file is treated as empty.

### `candid.drafting.threads`

`summarize_thread(company, tracker=None) -> dict`

Deterministic, template-based summary of the thread history with a company.
`tracker` accepts the same forms as `build_context`.

Returns:

- `company`: name.
- `bullets`: short timeline strings, oldest first; built from
  `status_history` entries (dicts with `date`/`from`/`to`/`note`, or plain
  strings), `date_added`, `interviewers`, `notes`, and `prep_pack`.
  Undated entries go last, in insertion order.
- `last_contact`: latest known contact date, ISO or `""`.
- `open_questions`: from the record, plus a template-based nudge when the
  status is `applied` and there has been no contact in 14+ days.

## Data sources

Both modules import (never duplicate) the data-path conventions from
`candid.config` (`DATA_DIR`, `TRACKER_PATH`, `STATUSES`) and read records
through `candid.tracker`. Optional extra record fields used when present:

- `interviewers`: list of names.
- `status_history`: list of `{"date": ..., "from": ..., "to": ..., "note": ...}`
  or plain strings.
- `open_questions`: list of strings.
- `company_notes.json`: optional JSON object `{company: notes}` beside the
  tracker file.

## Guarantees

- Drafts only: no `smtplib`, `requests`, `urllib`, or `socket` anywhere.
- Import-safe: module top-level imports are stdlib plus
  `candid.config` / `candid.tracker`.
- Deterministic: no LLMs, no randomness; bullet order is fully defined.
