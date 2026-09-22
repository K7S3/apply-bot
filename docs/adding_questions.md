# Adding interview questions to the prep bank

Company-specific questions live in `candid/prep_questions.py`, in the
`COMPANY_BANKS` dict keyed by company slug.

## Rules (strict)

1. **Only add questions that were publicly reported** — from candidate
   write-ups, Glassdoor/Prepfully/Interview Query reports, or published
   interview guides. Every entry needs a `source` (human-readable name) and
   a `url`.
2. **Never fabricate "recently asked" questions.** If you can't find a real
   report, don't add the company — the prep pack will say so explicitly and
   fall back to general questions.
3. Each entry: `{"question": ..., "category": ..., "source": ..., "url": ...}`.
   Categories: `ml`, `stats`, `sql`, `python`, `case`, `product`, `behavioral`,
   `system_design`, `quant`, `process`.

## Adding a company

```python
"stripe": {
    "name": "Stripe",
    "questions": [
        {"question": "Design an experiment to measure ...",
         "category": "stats",
         "source": "Candidate write-up, Apr 2026",
         "url": "https://..."},
    ],
},
```

Then verify: `python3 -c "
from candid.prep_questions import QUESTIONS_DB
qs = QUESTIONS_DB['stripe']
assert all(q.get('q') and q.get('source') and q.get('url') for q in qs)
print(len(qs), 'questions ok')"`

## Adding general questions

`GENERIC_BANKS` (keyed by role family: `data_scientist`, `ml_engineer`,
`data_analyst`, `quant`, `behavioral`) holds non-company-specific prep.
These are always labeled as general preparation in prep packs — never as
"asked at company X".
