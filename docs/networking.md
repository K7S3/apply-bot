# Networking follow-up cadence manager

`python -m candid network ...` — a contact book plus the cadence around it.
Everything is stored as local JSON under `candid_data/network/` (git-ignored,
redirectable with `CANDID_DATA_DIR`). Nothing is ever sent automatically:
drafts print to stdout for you to copy, edit, and send yourself.

## The 10 features

| # | Module | CLI | What it does |
|---|--------|-----|--------------|
| 1 | `candid.network.contacts` | `add-contact`, `contacts`, `contact` | Contact book: name, role, company, where/when you met, notes, tags, and a 1-5 value rating. |
| 2 | `candid.network.sequences` | `start-sequence`, `templates`, `sequence`, `complete-step`, `skip-step` | Post-event follow-up sequences. Six templates (`conference`, `meetup`, `informational`, `recruiter_call`, `coffee_chat`, `referral_intro`), each a list of steps with day offsets, concrete due dates, and per-step guidance. |
| 3 | `candid.network.touchpoints` | `log-touch`, `touches` | Log every interaction (email, call, coffee, event, note, value_add, intro_made, congrats). |
| 4 | `candid.network.warmth` | `warmth [id]` | Relationship warmth 0-100: touchpoints add warmth weighted by kind, decaying exponentially with a configurable half-life (`CANDID_WARMTH_HALF_LIFE`, default 45 days). Tiers: warm / active / cooling / cold. |
| 5 | `candid.network.valueadd` | `value-add <id>` | Give-first touch ideas (article, intro, congrats, resource, event, ask_advice) picked deterministically from the contact's profile, plus a drafted message for the idea you choose. |
| 6 | `candid.network.reminders` | `due [--days N]` | Due follow-ups bucketed overdue / today / upcoming, plus re-engagement nudges for valuable contacts going quiet. |
| 7 | `candid.network.intros` | `intro ask|email`, `intro-checklist` | Double opt-in introduction builder: permission-ask draft, then the intro email (asker in To, you to BCC). |
| 8 | `candid.network.checkins` | `checkin-plan [-n N]` | Quarterly re-engagement planner: ranks cooling/cold high-value contacts and gives you this week's revival batch with a suggested action and idea each. |
| 9 | `candid.network.thanks` | `thank` | Thank-you drafts after a referral, intro, advice, or help, in warm/formal/concise tones with timing guidance. |
| 10 | `candid.network.report` | `report [--out FILE]` | Activity report: contact growth, touchpoint mix, warmth distribution, sequence completion, warmest relationships, coldest high-value contacts to revive. |

## Typical flow

```bash
# Meet someone at a conference
python -m candid network add-contact --name "Jane Doe" --role "Eng Manager" \
    --company Acme --event "DataConf 2026" --value 4

# Start the post-event sequence (schedules due dates)
python -m candid network start-sequence 1 --template conference

# Log interactions as they happen
python -m candid network log-touch 1 --kind coffee --notes "Talked about their new team"

# Each morning: what's due?
python -m candid network due

# Warmth check, value-add ideas, re-engagement plan, report
python -m candid network warmth
python -m candid network value-add 1
python -m candid network checkin-plan
python -m candid network report
```

## Warmth math

Each touchpoint contributes `kind_weight * 25 * 0.5^(days_ago / half_life)`,
capped at 100. Kind weights: `intro_made` 2.5, `coffee` 2.0, `value_add` 1.75,
`call`/`event` 1.5, `email` 1.0, `note` 0.75, `congrats` 0.5. Meeting someone
counts as a small initial touch (12 points, same decay). Set
`CANDID_WARMTH_HALF_LIFE` to change the decay speed.
