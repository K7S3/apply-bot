# Behavioral prep beyond STAR

STAR is a format, not a strategy. Most big-tech loops score your stories
against an explicit values framework (Amazon's 16 Leadership Principles,
Meta's values, Netflix's culture memo, ...). `candid behavioral` prepares
you for the framework, not just the format.

## The frameworks

`python -m candid behavioral frameworks` lists all ten:

| Key | Framework | Principles |
|---|---|---|
| `amazon` | Amazon Leadership Principles | 16 |
| `meta` | Meta Values | 6 |
| `google` | Google Hiring Attributes (incl. Googleyness) | 4 |
| `netflix` | Netflix Culture Values | 8 |
| `microsoft` | Microsoft Culture | 5 |
| `apple` | Apple Interview Themes | 5 |
| `startup` | Startup Behavioral Themes | 5 |
| `finance` | Finance / Banking Themes | 5 |
| `consulting` | Consulting Themes | 5 |
| `default` | General Behavioral Themes | 6 |

`candid behavioral <subcommand> --company "Amazon"` auto-selects the
framework; `--framework amazon` overrides it. Banks and consulting firms
map to `finance` / `consulting`; anything unrecognized gets `default`.

Principle text is paraphrased from each company's public values material.
Each principle carries `listens_for` — what the interviewer is actually
scoring — and `signals`, the keywords used by the story-mapping heuristic.

## Commands

```bash
# principle-tagged question bank (every question has interviewer follow-up probes)
python -m candid behavioral lp-bank --company Amazon
python -m candid behavioral lp-bank --framework meta --principle move_fast

# values-alignment / "why us" prompts with answer scaffolds
python -m candid behavioral values --company Netflix

# map YOUR resume stories to the principles; see what's covered / thin / missing
python -m candid behavioral story-map --company Amazon

# full markdown coverage report with a 30-minute drill plan
python -m candid behavioral coverage --company Meta --role "ML Engineer"

# one drill: a principle-tagged question + the probes interviewers actually use
python -m candid behavioral drill --company Amazon --principle bias_action

# red-flag questions (salary, gaps, leaving, weaknesses) with framing guidance
python -m candid behavioral traps

# 90-second "tell me about yourself" mapped to the company's values
python -m candid behavioral pitch --company Google

# render a story bullet as STAR / STAR-V / PAR / SOAR
python -m candid behavioral scaffold --story "Cut churn 12% by ..." --variant star_v
```

## Story mapping: how the scoring works

`map_stories()` scores each resume bullet against each principle's signal
keywords, with a +1 bonus for concrete detail (numbers in the bullet).
Status thresholds:

- **covered** (score ≥ 2): the bullet signals the principle
- **thin** (score = 1): a passing mention — add a metric
- **missing** (score = 0): no bullet signals it

This is an honest keyword heuristic, documented as such wherever it is
shown — not an LLM judgment of your experience. A "missing" principle
usually means the story isn't *on the page* yet, not that you lack it.
Close gaps by drafting the story in STAR-V and adding the metric to the
resume bullet; the mapping re-scores automatically.

## Mock integration

`candid mock behavioral --theme <principle>` accepts any principle slug
(e.g. `--theme bias_action`, `--theme move_fast`) and drills you on a
principle-tagged question with the standard STAR self-check. The classic
`behavioral.json` themes still work; unknown themes still error.

## Prep-pack integration

`candid prep` packs now include a **Leadership principles & values
alignment** section: the framework's principles with what interviewers
listen for, your coverage score, values prompts to rehearse, and one drill
to run today.

## Adding questions

The bank lives in `candid/behavioral.py` (`LP_QUESTIONS`, built with the
`_q()` helper). Questions here are canonical, widely-documented behavioral
prompts — never present them as "recently asked at company X". Sourced,
company-specific reports belong in `candid/prep_questions.py` instead (see
docs/adding_questions.md). When adding: tag the right framework +
principle id, and always include 2-3 follow-up probes — the probes are
where loops are won.
