# Staff/principal interview questions: how to use this bank

`candid/staff_bank.py` is the question bank and behavioral rubric module for
staff-and-above loops.

## What is in the bank

- **40 practice questions** across 5 dimensions: `scope`, `influence`,
  `ambiguity`, `org-design`, `mentorship` (8 questions each).
- **5 behavioral rubrics** (1-4 scale, observable signals per level):
  `technical-judgment`, `org-influence`, `mentorship`,
  `delivery-through-others`, `ambiguity-handling`.

Every question is a **candid practice prompt**: written for preparation, not
reported as asked at any specific company. Each entry carries
`source: "candid practice prompt"` so generated packs never fabricate
"asked at company X" claims. This is the same provenance discipline as
`candid/prep_questions.py` (real reported questions there carry real
sources; the staff bank carries none because none are claimed).

## Levels 6/7: generic labels, not company levels

Each question is tagged with level `[6]` and/or `[7]` as generic
staff/principal-caliber labels. **Level numbering varies by company**
(L6/L7, E6/E7, IC6/IC7, or different ladders entirely). Map to the target
company's ladder before using `--level`. The CLI prints this disclaimer on
every non-JSON run.

## Question entry fields

- `q`: the question text
- `dimension`: one of the 5 bank dimensions
- `level`: subset of `[6, 7]`
- `good_signals`: observable behaviors that indicate a strong answer
- `follow_ups`: drill-down questions an interviewer (or practice partner)
  would ask next
- `source`: always `"candid practice prompt"`

## CLI (module-level; wired into the top-level CLI by the coordinator)

```
staff questions [--dimension D] [--level 6|7] [--limit N] [--json]
staff rubric list | --dimension D [--json]
```

Examples:

```
python -m candid staff questions --dimension ambiguity --level 6
python -m candid staff questions --limit 5 --json
python -m candid staff rubric list
python -m candid staff rubric --dimension org-influence
```

## Programmatic API

```python
from candid import staff_bank as sb

sb.list_dimensions()            # question-bank dimensions
sb.get_questions(dimension="scope", level=6, limit=5)
sb.get_rubric("mentorship")     # 1-4 scale with signals
sb.format_question(q)           # readable text for one question
sb.format_rubric(r)             # readable text for one rubric
```

Errors raise `sb.StaffError` (unknown dimension, bad level, negative limit).

## Practice guidance

- Answer in **STAR with a staff lens**: the Situation should show scope
  (teams, systems, users affected), the Action should show influence
  (how you moved people without authority), and the Result should show
  durable outcomes (not just shipped, but adopted, sustained, or learned).
- Use the rubric to self-score mock answers: level 3 is the staff bar in
  most orgs (proactive, cross-team, measurable); level 4 is principal+
  (org-wide, durable, develops others).
- Pair a question with its `follow_ups` in mock interviews: the first
  answer is the pitch, the follow-ups are where the real signal is.
