# Follow-up tone ladder + scheduler

`candid/drafting/ladder.py` and `candid/drafting/scheduler.py`.

Drafts only. Nothing in this package sends email, opens sockets, or makes
network calls. Drafts are rendered as text for the user to review, copy,
and send themselves.

## The ladder

The ladder escalates follow-up tone by days of silence since last contact
(read from the tracker record's `date_updated`, same as `candid/nudges.py`).

| Rung | Name | Days of silence | Tone | Guidance |
|------|------|-----------------|------|----------|
| 0 | Too early to follow up | < 3 | none | Wait until day 3. |
| 1 | Gentle nudge | 3-7 | gentle | Light, one or two sentences, assume good intent, no urgency. |
| 2 | Warm check-in | 8-14 | warm | Restate enthusiasm, add one small value item, one easy question. |
| 3 | Firmer nudge | 15-21 | firm | Be direct: name the silence, ask for a next step or an honest no. |
| 4 | Break-up / close the loop | 22+ | final | Graceful exit: assume a no, stop following up, leave the door open. |

### Stage adjustments

Stages shift the *effective* day count before rung mapping:

- `selected_for_interview`: **+2 effective days** (post-interview runs faster).
- `offer`: **-3 effective days** (offer stages need patience).
- Everything else (`applied`, `saved`, `rejected`, `withdrawn`): no offset.

Example: 6 days silent after an interview counts as 8 effective days, so it
lands on rung 2 (warm check-in), while the same silence after a plain
application is still rung 1. 9 days silent with an offer counts as 6
effective days, so rung 1, not rung 2.

## API

### `ladder_for(days_since_contact, stage) -> dict`

```python
from candid.drafting import ladder
ladder.ladder_for(16, "applied")
# {"rung": 3, "rung_name": "Firmer nudge", "tone": "firm",
#  "guidance": "...", "stage": "applied",
#  "days_since_contact": 16, "effective_days": 16}
```

### `render_ladder_draft(ladder, context) -> dict`

Deterministic template for the rung. Context keys used: `company`, `role`,
`contact_name`, `last_contact_date`, and optional `sender_name`. Missing or
blank values become placeholders (`[company]`, `there`, ...).

Returns `{"subject", "body", "rung"}`.

### `suggest_followups(tracker=None, config=None, today=None) -> list[dict]`

Scans tracker applications and returns per-app suggestions, most stale
first. `tracker` may be `None` (default tracker), a list of app dicts, or a
path to a tracker.json file. It is read only: never sent, never mutated.

- Skips apps with unparseable/missing dates, apps fresher than 3 days
  (configurable via `config["fresh_days"]`), and non-eligible statuses.
  Eligible statuses (configurable via `config["eligible_statuses"]`) are
  `applied`, `selected_for_interview`, and `offer`.

Each suggestion:

```python
{"app_id": 7,
 "company": "Acme",
 "role": "ML Engineer",
 "days_stale": 16,
 "ladder": {"rung": 3, "rung_name": "Firmer nudge", ...},
 "suggested_subject": "Next steps for ML Engineer at Acme?"}
```

## Tests

`tests/test_draft_ladder.py` (rung boundaries, stage adjustments, template
rendering) and `tests/test_draft_scheduler.py` (fresh-app skipping, stage
ladder in scheduler, output shape, no-mutation, config overrides).
