# Panel interview prep

Most interview loops are panels: 3-6 interviewers, each evaluating something
different. `python -m candid panel ...` prepares you **per interviewer**
instead of generically.

## The workflow

```bash
# 1. Define the loop: Name:archetype[:minutes]
python -m candid panel create --company "Acme" --role "Data Scientist" \
    --rounds "Priya Nair:hiring_manager:45, Sam Rao:data_scientist:60, Jo:bar_raiser:45"

# 2. Who's-who brief sheet (print it, or --export to save Markdown)
python -m candid panel brief --panel P1 --export

# 3. What each interviewer is likely to ask
python -m candid panel questions --panel P1 --round 2

# 4. Smart questions to ask each interviewer
python -m candid panel ask --panel P1

# 5. Interview-day timeline
python -m candid panel plan --panel P1 --start 10:00 --break-min 15

# 6. Mock each round in that interviewer's persona
python -m candid panel mock --panel P1 --round 2
python -m candid panel mock --panel P1 --round 2 --score 4 3 5 4

# 7. Record what each interviewer told you about themselves
python -m candid panel research --panel P1 --round 2 \
    --background "Staff DS, 6 yrs at Acme, owns the experimentation platform"

# 8. After each round, log what you told them (metrics, claims)
python -m candid panel log --panel P1 --round 2 --note "said 40% latency cut on ranking"

# 9. Check you stayed consistent across rounds
python -m candid panel consistency --panel P1

# 10. After the loop: consolidated debrief
python -m candid panel log --panel P1 --round 2 --signal strong --note "great deep dive on A/B testing"
python -m candid panel debrief --panel P1 --drafts

# 11. How ready are you?
python -m candid panel readiness --panel P1
```

Panels live in `panels.json` under your data dir (honors `CANDID_DATA_DIR`).

## Interviewer archetypes

`panel create` and `panel add-round` take an **archetype**: the interviewer's
role in the loop. Each archetype encodes what that interviewer evaluates, how
they ask, which question categories they draw from, sample questions, red
flags they watch for, questions *you* should ask them, and prep tips.

| Archetype | Who |
|---|---|
| `recruiter` | Recruiter screen |
| `hiring_manager` | Your would-be boss |
| `engineer` | Peer engineer (coding/technical) |
| `bar_raiser` | Hiring-bar guardian (deep behavioral drilling) |
| `system_design` | System design round |
| `data_scientist` | Data science technical |
| `product` | Product sense (usually a PM) |
| `behavioral` | Behavioral / culture |
| `skip_level` | Director+ two levels up |
| `cross_functional` | Partner team (PM, designer, ops) |

Run `python -m candid panel archetypes` to list them, or
`python -m candid panel archetypes --name bar_raiser` for one in detail.

## Honesty rules (strict)

1. **Expectations come from the archetype, not from leaks.** The brief sheet
   and question lists are labeled `archetype expectation` or `general bank`.
   They describe how that interviewer *role* tends to evaluate — never
   presented as that company's real questions.
2. **Interviewer backgrounds are yours.** `panel research --background`
   records what *you* found (recruiter emails, your LinkedIn data export).
   candid never scrapes profiles and never fabricates a background. Rounds
   without a recorded background say so explicitly in the brief.
3. **The consistency check is a flag, not a verdict.** It reports numbers
   that look contradictory across rounds so *you* can verify the context.
4. **Mocks are deterministic and offline.** Talking points come from your
   profile bullets; with no profile, the mock says so instead of inventing
   experience.

## Adding an archetype

Archetypes live in `candid/panel.py` in the `ARCHETYPES` dict. Copy a block
and keep the same keys:

```python
"solutions_architect": {
    "label": "Solutions architect",
    "description": "...",
    "evaluates": ["..."],       # what they score you on
    "styles": ["..."],          # how the round runs
    "categories": ["system_design"],  # must exist in prep_questions GENERIC_BANKS
    "sample_questions": ["..."],     # typical questions for this role
    "watch_for": ["..."],       # red flags they screen for
    "ask_them": ["..."],        # questions the candidate should ask
    "prep_tips": ["..."],
},
```

Then add a test in `tests/test_panel.py` (`ArchetypeCatalogTest` checks the
shape automatically). Categories must be ones used by
`candid/prep_questions.py` (`ml`, `stats`, `sql`, `python`, `case`,
`product`, `behavioral`, `system_design`, `quant`, `process`).
