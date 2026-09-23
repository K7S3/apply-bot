# Draft store and voice profile (`candid/drafting`)

Context-aware email drafting helpers. Drafts only: nothing in this package
sends email, opens sockets, or makes network calls. Everything is local,
deterministic, and rule-based (no LLM).

## Storage layout (`candid/drafting/store.py`)

Drafts live under the user data dir from `candid/config.py`
(`CANDID_DATA_DIR` env override, default `candid_data/` in the project root,
which is git-ignored):

```
candid_data/drafts/<app_id>/v1.json
candid_data/drafts/<app_id>/v2.json
...
```

Each file is one JSON record:

```json
{
  "draft_id": "v2",
  "app_id": "acme-2026-swe",
  "kind": "followup",
  "created": "2026-09-22T20:14:00+00:00",
  "subject": "Re: Senior Engineer interview",
  "body": "Hi Maya,\n\nThanks for the chat...\n\nBest,\nKeshavan"
}
```

`kind` is a free-form label (e.g. `followup`, `thankyou`, `intro`) for
filtering later; `created` is an ISO-8601 UTC timestamp.

## Versioning

`save_draft` never overwrites. Every call computes the next sequence number
for that `app_id` and writes a fresh `vN.json` file, so the full edit history
is preserved. Version counters are per application: two different `app_id`s
each start at `v1`. `app_id` values are sanitized for safe directory names.

Available operations:

- `save_draft(app_id, draft, kind=None, data_dir=None) -> draft_id`
- `list_drafts(app_id, data_dir=None) -> [{draft_id, kind, created}]` (sorted)
- `get_draft(draft_id, data_dir=None) -> dict` (full record;
  `FileNotFoundError` for unknown ids)
- `diff_drafts(id_a, id_b, data_dir=None) -> str` (unified diff of
  subject+body, diffable across versions)
- `render_markdown(draft) -> str` (`# <subject>` heading followed by body)

`data_dir` defaults to the configured data dir and exists so tests can point
at a `tmp_path`.

## Voice profile (`candid/drafting/voice.py`)

Learns the user's writing style from approved samples (drafts they sent),
then nudges new drafts toward that style.

`learn_style(samples) -> dict` consumes a list of `{subject, body}` dicts and
returns deterministic stats:

- `avg_sentence_len` - mean words per sentence across all bodies
- `greeting` - most common first non-empty body line
- `signoff` - most common last non-empty body line
- `contraction_rate` - apostrophe forms (contractions and possessives like
  `week's`) per body word
- `avg_body_words` - mean body word count
- `sample_count` - number of samples consumed

An empty sample list returns neutral defaults (`""`, `0.0`, `0`) and never
crashes.

`apply_style(draft, profile) -> {subject, body, changed}` rewrites the draft's
first non-empty line to the learned `greeting` and its last non-empty line to
the learned `signoff`, but only when they differ. `changed` lists which parts
were rewritten (`"greeting"`, `"signoff"`). Already-matching drafts and
neutral profiles are no-ops, and a single-line body never gets both edits
forced onto the same line.

Example:

```python
from candid.drafting import voice

profile = voice.learn_style(approved_samples)   # user-approved sent drafts
out = voice.apply_style({"subject": "Re: chat", "body": "Hey,\n\nQuick note.\n\nCheers"},
                        profile)
# out["body"] -> "Hi Maya,\n\nQuick note.\n\nBest,\nKeshavan" (if learned)
```
