# sre guides

SRE/DevOps interview prep under the `sre` command (module `candid/sre_guides.py`).
All content is offline, free, and dependency-free. No em dashes used anywhere
in user-facing text.

## sre stories: on-call STAR story builder

Turns pages, incidents, and war rooms into STAR stories tagged by competency.

```bash
python -m candid sre stories                 # interactive builder (default tag: on-call)
python -m candid sre stories --tag war-room  # custom tag for new stories
python -m candid sre stories --list          # list saved stories
```

The interactive flow walks through Situation, Task, Action, Result, plus
optional metrics, then scores the story (thin sections get flagged) and saves
it as JSON under `candid_data/sre_stories/` (git-ignored; override with
`CANDID_DATA_DIR`).

Competencies: incident-command, debugging, communication, prevention,
on-call-excellence, automation, reliability-engineering. Each competency ships
with interviewer-style prompts shown during the build.

Story JSON schema: `title`, `competencies`, `tags`, `situation`, `task`,
`action`, `result`, `metrics`, `created_at`.

Integration note: there is no central story-bank API in candid yet (no
`candid/stories.py`), so stories are saved standalone in the schema above.
When a story-bank API lands, repoint `save_story()` in `sre_guides.py` at it;
the schema fields are deliberately generic so migration is mechanical.

## sre cheatsheet: observability and tooling quick reference

```bash
python -m candid sre cheatsheet kubectl
python -m candid sre cheatsheet prometheus
python -m candid sre cheatsheet grafana
python -m candid sre cheatsheet linux
python -m candid sre cheatsheet terraform
```

Prints the essential commands or queries with one-line explanations. Content
was written from standard tool documentation and checked for accuracy
(kubectl flags, PromQL functions, LogQL operators, Terraform CLI behavior).

## sre quiz: practice questions

```bash
python -m candid sre quiz --tool kubectl
```

Five multiple-choice questions per tool, asked interactively. Answers accept
the option number or the answer text (case-insensitive). After the quiz you
get a score plus the correct answer and explanation for every miss.

Non-interactive grading is available in code via
`grade_quiz(tool, answers) -> {"tool", "score", "total", "details"}`,
which is how the test suite exercises it without touching stdin.

## sre ladder: SRE career ladder guide

```bash
python -m candid sre ladder            # all levels
python -m candid sre ladder --level L5 # one level
```

Covers L3 through L6. Each level documents scope, technical bar, leadership
expectations, on-call expectations, promotion criteria to the next level, and
what interviewers probe at that level.

This is general guidance grounded in publicly documented leveling norms;
every company levels differently, so treat it as calibration, not a promise
of any employer's ladder.

## For the coordinator

`register(subparsers)` adds the four subcommands (`stories`, `cheatsheet`,
`quiz`, `ladder`) to the `sre` subparsers object; each sets
`func=dispatch` and `sre_cmd=<name>`. `dispatch(args) -> int` routes on
`args.sre_cmd` and returns an exit code. All logic lives in pure functions
(`build_story_record`, `validate_story`, `save_story`, `list_stories`,
`render_cheatsheet`, `grade_quiz`, `render_ladder`); the CLI layer is thin.
