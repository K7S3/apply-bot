# staff_assess: ambiguity drill + leveling calibration

Staff/principal-track interview prep, in `candid/staff_assess.py`. Two tools:

1. **Ambiguity drill** - practice decomposing deliberately underspecified,
   staff-level problems (the classic staff+ interview signal).
2. **Leveling calibration** - generic L5/L6/L7 expectations across five
   dimensions, self-rating with gap analysis and next steps.

Local-first: no network, no paid APIs. Ratings stored are the user's own;
the module never invents experience or metrics.

## Ambiguity drill

Eight scenarios ship in `AMBIGUITY_SCENARIOS`, each with:

- `id`, `title`
- `brief` - deliberately underspecified, the way a real staff prompt is
- `decomposition_checklist` - four lists: `clarifying_questions`,
  `unknowns`, `milestones`, `risks`

| id | title |
|---|---|
| stalled-migration | The VP says the migration is stalled |
| build-vs-buy | Build or buy: the feature store question |
| p99-spike | p99 latency doubled and nobody owns serving |
| shadow-roadmaps | Three teams building the same thing |
| fuzzy-h2-goal | Turn 'improve ML quality' into an H2 plan |
| orphan-monolith | The monolith everyone depends on and nobody owns |
| exec-two-minutes | The CEO asks about model explainability at all-hands |
| staff-standoff | Two staff engineers, one storage layer, zero progress |

### Scoring (heuristic, clearly labeled)

`score_answer(scenario_id, answer_text)` returns per-dimension hits/misses
plus coaching tips. It is a **keyword-and-structure heuristic, not a human
grader**: for each checklist item it checks keyword overlap with the answer,
and it checks structural markers (question marks, unknown-naming language,
milestone/planning language, risk language). Dimension score =
0.7 * checklist coverage + 0.3 * structural probes. Overall bands: strong
(>= 0.7), solid (>= 0.4), developing (below). The result dict carries
`"heuristic": True` and a `heuristic_note` saying exactly this; the CLI and
`format_score()` print the caveat too.

Use it for practice reps, not verdicts. It rewards covering the checklist
topics with the right structure; it cannot judge correctness, depth, or
insight.

## Leveling calibration

`LEVEL_EXPECTATIONS` holds generic expectations for `L5`, `L6`, `L7` across
five dimensions: technical depth, scope, influence, mentorship, ambiguity.

> **Disclaimer (also printed by the CLI):** levels vary widely by company.
> These are GENERIC staff-track expectations for practice and
> self-reflection, not any employer's actual leveling rubric. Always
> calibrate against the specific company's leveling guide.

Each level defines a minimum self-rating (1-4 scale) per dimension:
L5 expects 2, L6 expects 3, L7 expects 4.

`self_rate(ratings, target="L6")`:

- Validates every dimension is present with an integer rating 1-4
  (raises `StaffError` otherwise).
- Persists `{"target", "ratings", "gap_dimensions", "updated_at"}` to
  `DATA_DIR/staff_level.json` (honors `CANDID_DATA_DIR`).
- Returns gaps: dimensions rated below the target's minimum, each with the
  level's expectation text and a concrete next-step suggestion.
- Offers gaps to the study-plan module via `_study_plan_hook()`: tries
  `candid.study.record_gaps` / `add_items` / `add_goals`, and degrades
  gracefully (returns `{"consumed": False, "reason": ..., "items": [...]}`)
  when `candid.study` is absent, which it currently is. Gap items are always
  included in the result so callers can consume them directly.

`load_ratings()` returns the persisted record, or `None` if never rated.

## CLI (for wiring into `python -m candid staff ...`)

`main(argv)` takes args after `staff` and returns an exit code:

```
staff ambiguity [--list] [--scenario ID] [--answer-file F]
staff level [--table] [--rate dim=1-4 ...] [--target L6|L7] [--json]
```

- `staff ambiguity --list` - list scenarios.
- `staff ambiguity --scenario ID` - show the brief + checklist. In an
  interactive terminal it then prompts for your answer on stdin and scores
  it; with piped stdin it scores the pipe directly.
- `staff ambiguity --scenario ID --answer-file F` - score a saved answer.
- `staff level --table` - print the generic leveling table + disclaimer.
- `staff level --rate technical_depth=3 --rate scope=2 ... [--target L6] [--json]`
  - self-rate; `--rate` is repeatable and also accepts space-separated
    pairs; dimension names accept hyphens (`technical-depth=3`).
- Bare `staff ambiguity` lists scenarios; bare `staff level` shows the table.
- Errors raise `StaffError`, printed cleanly with a non-zero exit code.

## API summary

- `list_scenarios()`, `get_scenario(id)`, `score_answer(scenario_id, answer_text) -> dict`, `format_score(score) -> str`
- `level_table() -> dict`, `self_rate(ratings, target="L6") -> dict`, `load_ratings()`
- `format_scenario_list()`, `format_scenario(s)`, `format_level_table()`, `format_self_rate(result)`
- `main(argv) -> int`, `StaffError(Exception)`
