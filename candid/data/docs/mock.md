# Mock: practice interviews

Practice is where interviews are won. candid ships four practice modes,
all offline except the conversational AI interviewer.

## Coding practice (offline, with a real judge)

```bash
python -m candid mock list
python -m candid mock list --topic arrays --difficulty easy
python -m candid mock coding
python -m candid mock coding --topic arrays --difficulty medium
python -m candid mock run --problem two-sum --file sol.py
python -m candid mock solution --problem two-sum
python -m candid mock hint --problem two-sum
```

- `list` — browse the bundled problem set, filterable by `--topic` and
  `--difficulty`.
- `coding` — interactive session: pick (or auto-pick) a problem, write your
  solution, get judged. `--problem` and `--file` target a specific one.
- `run` — judge a solution file non-interactively (exit code 0 = accepted).
- `solution` — reference solution plus complexity analysis, for after you
  attempt it.
- `hint` — graduated hints when you are stuck but do not want the answer.

## AI interviewer (uses Gemini)

```bash
python -m candid mock ai --track coding
python -m candid mock ai --track behavioral
python -m candid mock ai --track ml
```

`--track` is `coding` (default), `behavioral`, or `ml`. `--topic`,
`--difficulty`, and `--problem` focus the session. This is the one mock
mode that uses the network (the Gemini fast path); everything else is
fully offline.

## Behavioral practice

```bash
python -m candid mock behavioral
python -m candid mock behavioral --theme leadership --ai
```

STAR-format practice. `--theme` picks a theme (e.g. `leadership`);
`--ai` adds AI feedback on your answers.

## System design practice

```bash
python -m candid mock design
python -m candid mock design --level senior --ai
```

`--level` sets the expected depth; `--ai` adds AI feedback.

## How to structure practice

- **Coding**: 3-5 problems per week at your target difficulty; always attempt
  before reading `solution`; use `hint` at most twice per problem.
- **Behavioral**: prepare 6-8 STAR stories covering leadership, conflict,
  failure, and impact; rehearse them out loud.
- **Design**: one full session per week at the level you are interviewing
  for; draw the diagram, then defend the tradeoffs.
