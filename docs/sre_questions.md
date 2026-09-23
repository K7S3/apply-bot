# SRE interview prep (`candid sre`)

Two subcommands for DevOps/SRE interview preparation.

## `candid sre questions [--category X] [--list-categories]`

Prints the SRE interview question bank. Categories: `linux`,
`networking`, `kubernetes`, `cicd`, `observability`, `reliability`.

```bash
candid sre questions --list-categories
candid sre questions --category kubernetes
candid sre questions            # all categories
```

Every question carries a source label and key talking points for a
strong answer. Sources are honest by design: entries drawn from
Google's SRE books are labeled as such, the rest are labeled
"Reported SRE loop question". Nothing is presented as asked at a
specific company on a specific date.

### Adding or editing questions

Questions live in `candid/data/sre_questions.json`, keyed by category.
Each entry:

```json
{
  "q": "Question text?",
  "source": "Google SRE book (Site Reliability Engineering, O'Reilly)",
  "difficulty": "medium",
  "talking_points": ["point one", "point two"]
}
```

Rules:
1. Only add questions you can verify: genuinely covered in a
   published SRE book, or widely reported from real interview loops.
   Label the source accordingly.
2. Never invent "recently asked at company X" claims.
3. If a category has no verified questions, leave it empty; the CLI
   says so honestly instead of inventing entries.
4. No em dashes in question text (use commas or hyphens).

After editing, run `python3 -m pytest tests/test_sre_questions.py -q`.

## `candid sre deepdive <topic> [--save]`

Prints a markdown deep-dive on a reliability concept. Topics: `slos`,
`error-budgets`, `redundancy`, `backpressure`, `circuit-breakers`,
`chaos-engineering`, `incident-management`.

```bash
candid sre deepdive error-budgets
candid sre deepdive slos --save   # also writes candid_data/sre/slos.md
```

Deep-dive content lives in `candid/sre_questions.py` (`DEEPDIVES`
dict). Keep it technically accurate and citation-free: no fabricated
links or invented statistics. Content conventions: start with "The
short version", explain the core idea, name the traps, and close with
"How this shows up in interviews".

## Module contract (for the CLI coordinator)

- `candid/sre_questions.py` exposes `register(subparsers)` (adds
  `questions` and `deepdive`, each with `func=dispatch`) and
  `dispatch(args) -> int` (reads `args.sre_cmd`).
- Logic is in pure functions (`questions_output`, `deepdive_output`,
  `get_questions`, `get_deepdive`, `save_deepdive`); parsing is thin.
