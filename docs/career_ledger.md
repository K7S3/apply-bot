# Career-capital ledger

Log wins and impact **as they happen**, so performance reviews, interviews,
and resume updates write themselves. The ledger is the raw material; three
modules turn it into artifacts:

| Module | What it does |
|---|---|
| `candid.wins` | CRUD ledger: wins tagged by competency, with STAR fields, impacts, quotes |
| `candid.impact` | Typed impact metrics (before/after), rollup, timeline |
| `candid.star` | STAR stories, behavioral answer kit, grounded resume bullets |
| `candid.brag` | Markdown brag sheet, competency coverage, JD gap analysis |

## Quickstart

```bash
# log a win (competencies: see candid.wins.COMPETENCIES)
python -m candid wins add --title "Cut p99 latency 8x" \
  --competency system-design --competency ownership --tag promo

# attach a quantified impact
python -m candid wins impact-add w-0001 --metric "p99 latency" \
  --before 800 --after 120 --unit ms --category performance

# see the story so far
python -m candid wins timeline
python -m candid wins rollup

# performance review: brag sheet
python -m candid brag sheet --since 2026-01-01 --out brag-h1.md

# interview prep: behavioral answer kit
python -m candid star kit --competency leadership

# resume: grounded bullets (numbers come ONLY from logged impacts)
python -m candid star bullets w-0001

# where are you thin vs a target JD?
python -m candid wins gap --jd jd.txt
```

## Win record

```json
{
  "id": "w-0001",
  "title": "Cut p99 latency 8x on ranking service",
  "date": "2026-06-12",
  "role": "Software Engineer, ML",
  "description": "Reworked the batching path...",
  "star": {"situation": "...", "task": "...", "action": "...", "result": "..."},
  "competencies": ["system-design", "ownership"],
  "impacts": [{"metric": "p99 latency", "before": 800, "after": 120,
               "unit": "ms", "category": "performance"}],
  "quotes": [{"text": "Crisp execution.", "author": "Teammate",
              "source": "peer review"}],
  "tags": ["promo-packet"]
}
```

Impact categories: `revenue`, `cost`, `performance`, `quality`, `scale`, `time`.

## Competencies

18 seeded tags (leadership, ownership, communication, system-design, coding,
debugging, data-analysis, experimentation, ml-modeling, product-sense,
stakeholder-management, mentoring, project-management, incident-response,
technical-writing, collaboration, strategic-thinking, customer-focus).
Add your own with `candid.wins.register_competency("public-speaking", "...")`.

## Grounding rule

`star bullets` only quantifies what you logged in `impacts`. A win with no
impacts gets unquantified bullets. The ledger never invents numbers.

## Nudges

`candid.nudges.win_nudges()` suggests logging a win if none was logged in
the last 7 days (`WIN_LOG_AFTER_DAYS`). The dashboard's Career capital
section surfaces the ledger at a glance.
