# Promotion path planner

Two commands, built for engineers already employed and thinking about the
next level: `leveling` (reference ladders) and `promo` (your personal
readiness plan).

## Leveling guides

Reference approximations of IC ladders at six companies, stored in
`candid/data/leveling.json`. They are planning aids, not official docs:
leveling is company-internal and changes over time, so verify against
official leveling docs and your manager before any promotion decision.

```bash
python -m candid leveling list                                   # supported companies
python -m candid leveling guide --company meta                   # full ladder
python -m candid leveling scope --company meta --level E5        # scope + promo criteria
python -m candid leveling ladder --company amazon                # ASCII ladder
python -m candid leveling map --from meta --level E5 --to google # cross-company translation
python -m candid leveling compare --company meta --from E4 --to E5  # what changes
```

Level input is forgiving: `E5`, `e5`, `5`, `senior`, `SDE III`, `62`,
`ICT4` all resolve. Company aliases work too (`facebook`, `aws`,
`msft`).

Translation aligns each level to a shared 0-5 "rung" scale (0 = early
career, 4 = principal/senior staff). It carries explicit caveats:
translations are approximate, down-leveling on hire is common, and
tenure plus interview performance shift the outcome.

## Promo planner

```bash
# 1. Bank evidence as it happens (wins, launches, scope stories)
python -m candid promo evidence add --text "Led X migration across 2 teams" \
    --company meta --criterion impact-team-plus-scope
python -m candid promo evidence list
python -m candid promo evidence remove 1

# 2. See where you stand
python -m candid promo checklist --company meta --current E4 --target E5
python -m candid promo gaps --company meta --target E5
python -m candid promo rubric --company meta --current E4 --target E5

# 3. Plan the path
python -m candid promo timeline --company meta --current E4 --target E5
python -m candid promo packet --company meta --current E4 --target E5
```

How it works:

- **checklist** scores each of the target level's promotion criteria as
  done / partial / todo. Evidence you banked counts as done; resume
  bullets that mention the criterion count as partial. Experience is
  compared against the level's typical years. Verdict: ready / close /
  building.
- **gaps** lists uncovered criteria with the exact `evidence add`
  command to close each one.
- **timeline** estimates months to readiness from the typical time in
  your current level, adjusted by promo-criteria coverage. A heuristic,
  not a promise; scope evidence moves it most.
- **packet** writes a markdown outline to
  `candid_data/promo_packets/`: snapshot, scope reference, your
  accomplishments mapped to each promotion criterion, growth areas, an
  endorser checklist, and pointers back to the checklist and timeline.
  It never invents accomplishments; unfilled sections stay as templates.
- Everything is deterministic and local. No profile yet? The commands
  still work, minus personalization - run `onboard` for the full
  version.

Data hygiene: evidence lives in `candid_data/promo_evidence.json`
(git-ignored, like the tracker). Leveling reference data is committed
under `candid/data/leveling.json`; extend it by adding a company entry
with the same schema (code, title, rung, typical_years, scope,
promo_criteria, typical_months_to_next, aka aliases).
