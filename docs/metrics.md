# Bullet metric helper (`metrics`)

Résumé bullets land harder with numbers. The metric helper finds the bullets
in your profile that lack concrete metrics, asks *you* for the numbers,
suggests tighter phrasings built from those numbers, applies the phrasing
you pick, and tracks your metric coverage over time.

It works on the bullets from `candid onboard` / `profile`; it never touches
your raw résumé text.

## What it does

1. **Scan** your profile bullets for metric opportunities (bullets with no
   numbers, vague scope, unquantified impact, and similar).
2. **Prompt** you for each missing number, one bullet at a time. You can
   also decline a bullet; declined bullets are left alone, never auto-filled.
3. **Suggest** phrasings that use only the numbers you supplied, and show
   them side by side for a **preview**.
4. **Apply** the phrasing you choose to a rewritten copy of your bullets.
   Your original bullets are never overwritten in place; the rewrite is
   stored alongside them and reported back to you.
5. **Track** progress: `coverage` (share of bullets carrying at least one
   validated metric) and `debt` (the opportunities still open, biggest
   impact first).
6. **Audit** every rewritten bullet to prove each number traces back to a
   number you supplied.

## The never-invent guarantee

This is the hard rule the helper is built around:

- **Numbers only ever come from you.** The helper has no way to invent a
  metric. Suggested phrasings are assembled from bank entries you marked
  `supplied`; if a bullet has no supplied number, no phrasing is offered
  for it.
- **Declined bullets are never auto-filled.** Marking a bank entry
  `declined` removes the bullet from prompting and from rewrite candidacy.
  It can still show up in `debt` as intentionally unquantified, so the
  coverage math stays honest.
- **`metrics audit` verifies.** The audit pass checks every number in every
  rewritten bullet against the story bank. Any number without a matching
  user-backed entry (status `supplied`, `accepted`, or `applied`) is reported
  as a violation, and the command exits
  non-zero so scripts can gate on it.

The same guarantee holds in code: `candid.metrics.audit_no_invention`
takes your profile and the bank and returns `{"ok": ..., "violations":
[...]}`. Every bullet containing a digit-based metric must have a bank
entry with a user-backed status; anything unattributed lands in `violations`.
`ok` is true exactly when the list is empty.

## Command reference

All commands run as `python -m candid metrics <subcommand>`.

| Subcommand | What it does | Example |
|---|---|---|
| `scan` | Find bullets without metrics and print an opportunity report with types and suggested fixes. | `python -m candid metrics scan` |
| `prompt` | Interactive loop: for each opportunity, type the number (with unit and context) or `d` to decline. Saves answers to the story bank. | `python -m candid metrics prompt` |
| `preview` | Show suggested phrasings for bullets that have supplied numbers. Nothing is written. | `python -m candid metrics preview --bullet 3` |
| `apply` | Rewrite bullets using the phrasing you picked in `preview`. Prints a before/after diff. | `python -m candid metrics apply --bullet 3 --choice 1` |
| `coverage` | Print the share of bullets carrying at least one validated metric, plus the trend if you have history. | `python -m candid metrics coverage` |
| `debt` | List open metric opportunities ("metric debt"), biggest impact first. | `python -m candid metrics debt` |
| `bank` | View or edit the story bank (bullet, numbers, units, context, status). | `python -m candid metrics bank --list` |
| `audit` | Verify every number in rewritten bullets traces to a user-backed bank entry (`supplied`, `accepted`, `applied`). Exits non-zero on any violation. | `python -m candid metrics audit` |

A typical session:

```bash
# 1. See what is missing
python -m candid metrics scan

# 2. Supply your numbers (or decline with 'd')
python -m candid metrics prompt

# 3. Look at the suggested rewrites, then apply the ones you like
python -m candid metrics preview --bullet 2
python -m candid metrics apply --bullet 2 --choice 0

# 4. Check progress and prove nothing was invented
python -m candid metrics coverage
python -m candid metrics audit
```

## Opportunity types

`candid.metrics.OPP_TYPES` names the categories `scan` can report. Each
type carries a human label, the follow-up questions `metrics prompt` asks to
pull real numbers out of you, and the units those answers usually come in:

| Type | Label | Example follow-up question | Typical units |
|---|---|---|---|
| `performance` | Performance | What was the latency before the change? After? | ms, seconds, %, x |
| `scale` | Scale | How many users or requests did it handle before? After? | users, requests/sec, transactions, x |
| `cost` | Cost | How much did it cost before? How much did you save? | $, USD, % |
| `time` | Time saved | How long did the process take before? After? | hours, days, minutes, % |
| `revenue` | Revenue | How much revenue was influenced or generated? | $, USD, % |
| `quality` | Quality / reliability | What was the error rate before? After? | %, count, x |
| `team` | Team / leadership | How many people did you lead, mentor, or hire? | count |
| `adoption` | Adoption | How many users or teams adopted it? | users, teams |

`scan` only reports bullets that have no digit-based metric yet *and* show
an opportunity cue (a vague quantifier like "several", an impact verb like
"improved", or a scope word like "team"). Bullets already carrying numbers
are skipped, not re-flagged.

## Suggested phrasings

`suggest_phrasings` builds 2-3 deterministic bullet variants from the
answers you supplied for one opportunity. Templates declare the answer keys
they need (for example, the `performance` templates need `before`, `after`,
`unit`, and `pct`); if any required key is missing, the helper returns an
empty list rather than fabricate a number. Every variant uses only the
values you typed.

## The story bank

The story bank is the single source of truth for your numbers. It is a JSON
file (`metrics_bank.json` in your candid data dir) keyed by
`"<role_idx>:<bullet_idx>"`. Each entry records the bullet, the answers you
supplied (a dict of named values like `{"value": "2", "unit": "junior data
scientists"}`), a status, and a timestamp:

- `supplied`: you gave the numbers; phrasings may use them, and `audit`
  treats the bullet as backed.
- `accepted`: you accepted a suggested phrasing in `preview`; still backed.
- `applied`: the phrasing was written into your profile; still backed.
- `declined`: you chose not to quantify this bullet. It leaves the debt
  list and is never auto-filled.
- `skipped`: you skipped it for now; it stays in the debt list.
- `pending`: an opportunity was found and you have not answered yet.

`metrics prompt` writes to the bank via `record_answer`;
`metrics bank --list` reads it back; `load_bank` / `save_bank` are the
programmatic equivalents in `candid.metrics`.

## Story-bank integration point

`candid.metrics.export_story_metrics` turns the bank into a
JSON-serializable list, one record per `supplied` entry:

```json
[
  {
    "bullet": "Mentored 2 junior data scientists on experiment design",
    "metric_summary": "unit: junior data scientists; value: 2",
    "answers": {"value": "2", "unit": "junior data scientists"}
  }
]
```

Only `supplied` entries are exported; `declined`, `skipped`, and `pending`
entries are excluded. If `candid/stories.py` exists in a given checkout, it
can consume this list to seed interview-story drafts. Otherwise the export
itself is the contract: any downstream tool (a prep-pack builder, the
dashboard, or your own script) reads it and gets bullet text plus
user-supplied numbers with provenance, and nothing else.
