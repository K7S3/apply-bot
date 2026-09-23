# Skills radar

Map your profile's skills against next-level role requirements, visualize the
result as a radar chart, and get a prioritized learning plan. Everything is
deterministic and offline: no network, no LLM, no API keys.

## The 10 features

1. **8-axis taxonomy** (`candid/skills_radar.py: AXES`) — Languages, ML & AI,
   Data & Analytics, Systems & Backend, Cloud & DevOps, Frontend & Mobile,
   Leadership & People, Domain & Research. Every `config.SKILL_LEXICON` skill
   is mapped to exactly one axis, plus an extended alias lexicon
   (`EXTRA_SKILL_ALIASES`: pytorch, kubernetes, react, typescript, ...).
2. **Proficiency scoring** — each skill scores 0-100 from profile evidence:
   45 pts for being in the skills section, up to 30 for experience evidence
   weighted by recency (latest role counts most), 5 for headline/summary
   mention, up to 10 for bullet-mention frequency. The breakdown is returned
   with every score so the number is always explainable.
3. **Axis coverage** — per-axis 0-100 with diminishing returns: the top
   skill weighs 1.0, the next 0.6, then 0.4/0.25/0.15, plus a diversity
   multiplier (up to +25%) rewarding breadth.
4. **Role targets** — 8 built-in next-level archetypes (`senior-swe`,
   `staff-swe`, `senior-ml`, `staff-ml`, `senior-ds`, `senior-de`,
   `senior-fe`, `eng-manager`), each with per-axis requirements, per-skill
   requirements, and per-axis importance weights. Custom targets load from
   a JSON file: `{"label", "blurb", "axes": {axis: 0-100},
   "skills": {skill: 0-100}, "weights": {axis: float}}`.
5. **Gap analysis** — required-vs-current per axis and per skill, sorted by
   impact (gap x weight). Statuses: `met` / `near` (gap <= 10) / `gap`.
   Readiness 0-100 = mean requirement coverage.
6. **Prioritized learning plan** — gap skills ranked by benefit-per-hour
   (gap x axis weight x market demand, divided by estimated study hours),
   then greedily ordered so prerequisites come first (python before
   pytorch, statistics before causal inference).
7. **Radar-chart visualization** — ASCII radar (`●` you, `◇` target) plus
   `--format json|md` variants.
8. **Evidence mapping** — every axis score traces back to the resume
   experience entries that evidence it (`skills evidence --axis "ML & AI"`).
9. **Snapshots + trend** — `skills snapshot` stores dated radar snapshots
   in `candid_data/skills_snapshots.json`; `skills trend` shows per-axis
   and per-skill growth between the first and latest snapshot.
10. **Plan report** — `skills report` exports radar + gaps + plan +
    evidence (+ trend when snapshots exist) as Markdown or JSON.

## CLI

```bash
python -m candid skills targets                    # list role targets
python -m candid skills radar                      # ASCII radar vs default target
python -m candid skills radar --target staff-ml --format md
python -m candid skills gaps --target senior-swe
python -m candid skills plan --target staff-ml --n 8
python -m candid skills plan --target senior-ml --md plan.md
python -m candid skills evidence --axis "ML & AI"
python -m candid skills snapshot                   # store today's radar
python -m candid skills trend
python -m candid skills report --target staff-ml --md report.md
```

The default target is derived from your seniority (senior/lead/staff ->
`staff-swe`, otherwise `senior-swe`). A custom target JSON file can be
passed instead of a built-in name:

```bash
python -m candid skills gaps --target ./my-target.json
```

## How proficiency is scored (example)

`python` for a profile with Python in the skills section, used in the two
most recent roles and the headline:

- skills section: 45
- experience recency: 18 (latest role) + 10 (previous) = 28
- headline mention: 5
- bullet mentions: up to 10

Total capped at 100. A skill never mentioned anywhere scores 0.

## Files

- `candid/skills_radar.py` — all logic
- `tests/test_skills_radar.py` — 39 tests
- snapshots: `candid_data/skills_snapshots.json` (git-ignored, per-user)
