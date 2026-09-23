# Decision journal

The `decision` command is a structured thinking companion for hard offer
choices. Comp math lives in `offer`; this is where you record *why* you
would take an offer, and revisit those reasons later. Everything is stored
in `candid_data/decisions.json` (git-ignored), keyed by offer id, and
everything is user-entered - nothing is inferred.

## The ten features

### 1. Weighted pros/cons

```bash
python -m candid decision pros-add --offer 1 --pro "Great team" --weight 3
python -m candid decision pros-add --offer 1 --con "Long commute" --weight 2
python -m candid decision pros-list --offer 1
python -m candid decision pros-remove --offer 1 --side pro --index 2
```

Weights are 1-3 (default 2). The scoreboard shows weighted totals and a
net score. `--offer` accepts an offer id or a company-name substring.

### 2. Criteria scorecard

Set your own criteria and weights once, then score each offer 1-10:

```bash
python -m candid decision criteria-set --set comp=30 --set growth=25 --set wlb=20 --set manager=15 --set mission=10
python -m candid decision criteria-score --offer 1 --set comp=8 --set growth=7
python -m candid decision criteria-rank
```

`criteria-rank` prints a decision matrix sorted by weighted score, with the
leader named. Weights are normalized at rank time, so any positive numbers
work. Custom criteria (anything beyond the six defaults) are allowed.

### 3. Gut-check prompts

A rotating bank of reflective questions - one per day:

```bash
python -m candid decision gut
python -m candid decision gut --offer 1          # also shows past answers
python -m candid decision gut-answer --offer 1 --answer "I would be crushed"
python -m candid decision gut-list --offer 1
```

### 4. Decision deadlines

```bash
python -m candid decision deadline-set --offer 1 --date 2026-10-05
python -m candid decision deadline-set --offer 1 --date 2026-10-05 --exploding --note "Recruiter says firm"
python -m candid decision deadlines                 # most urgent first
python -m candid decision deadline-clear --offer 1
```

Urgency levels: overdue, due-today, urgent (<=3 days, or <=7 for
exploding offers), upcoming (<=14 days), scheduled.

### 5. Decision lifecycle, notes, timeline

```bash
python -m candid decision state-set --offer 1 --state leaning
python -m candid decision note-add --offer 1 --text "Loved the hiring-manager call"
python -m candid decision timeline --offer 1
```

States: `considering`, `leaning`, `negotiating`, `accepted`, `declined`,
`withdrawn`. Every action in the journal (pros, scores, gut answers,
deadlines, state changes, advice, ...) is also appended to the timestamped
timeline, so you can see how your thinking evolved.

### 6. Regret-minimization exercise

```bash
python -m candid decision regret-set --offer 1 \
  --take "Golden handcuffs for two years" \
  --decline "Missing the rocketship" \
  --ten-year "The rocketship story wins"
python -m candid decision regret-show --offer 1
```

### 7. Reasons snapshot + revisit

Freeze your top reasons at decision time, then come back later and mark
what still holds:

```bash
python -m candid decision snapshot --offer 1 --reasons "team I trust; comp; growth"
python -m candid decision revisit --offer 1 --still-true "team I trust; comp" --changed "growth unclear" --note "Still leaning yes"
python -m candid decision revisit --offer 1   # view snapshot + past revisits
```

### 8. Advice log

```bash
python -m candid decision advice-add --offer 1 --advisor "Priya (mentor)" --stance for --note "Great growth"
python -m candid decision advice-list --offer 1
```

Shows a for/against/neutral consensus count plus each advisor's note.

### 9. Confidence tracking

```bash
python -m candid decision confidence-set --offer 1 --level 7 --note "After the team call"
python -m candid decision confidence-history --offer 1
```

Levels are 1-10; the history view draws a bar per entry and names the trend
(rising / falling / flat) when there are two or more.

### 10. Summary + journal export

```bash
python -m candid decision summary --offer 1
python -m candid decision export --offer 1 --out journal.md
python -m candid decision export                      # all offers
```

The summary is a one-screen view of the whole journal for an offer. The
export is a shareable markdown document (criteria, pros/cons, scores, gut
answers, regret exercise, snapshot + revisits, advice, confidence,
timeline) - useful for talking it through with a partner or mentor.

## Data model

`decisions.json` holds `criteria_weights` plus one entry per offer id with
`pros`, `cons`, `criteria_scores`, `gut_answers`, `deadline`, `state`,
`journal`, `regret`, `snapshot`, `revisits`, `advice`, and `confidence`.
Delete the file to start over; it is never committed.
