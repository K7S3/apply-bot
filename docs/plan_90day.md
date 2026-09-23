# 30-60-90 day plan generator

`python -m candid plan` builds a personalized first-90-day onboarding plan
from a role-specific template: concrete milestones per phase, learning goals
with resources, a stakeholder map with first-meeting questions, and draft
success metrics you align on with your manager in week 1.

Everything is local and deterministic. Plans live in
`candid_data/plans.json` (git-ignored); exports go to
`candid_data/plan_exports/`.

## Quick start

```bash
# Create a plan (role family is auto-detected from the title)
python -m candid plan new --company Acme --role "Backend Engineer" --level senior

# With a start date, your name, and custom focus areas
python -m candid plan new --company Acme --role "Data Scientist" \
    --start-date 2026-10-05 --name "Pat" --focus "churn model;dashboard cleanup"

# See the plan, then work it week by week
python -m candid plan show 1
python -m candid plan week 1 2        # focus sheet + reflection prompts for week 2
python -m candid plan check 1 g3      # mark milestone g3 done
python -m candid plan progress 1      # completion stats per phase
```

## The workflow

1. **Create** — `plan new` picks one of 10 role-family templates (backend,
   frontend, mobile, ML, data, devops, EM, PM, design, general) and layers
   level expectations on top (junior / mid / senior / staff). If you have
   onboarded (`candid onboard`), your profile skills deprioritize learning
   goals you already cover. `--family` overrides auto-detection.
2. **Align (week 1)** — `plan metrics 1` drafts measurable success criteria
   per phase; `plan stakeholders 1` gives you who to meet and what to ask
   them. Export the plan (`plan export 1`) and walk through it with your
   manager. Adjust the drafts together; they are starting points, not edicts.
3. **Execute** — each Monday run `plan week <id> <n>` for the week's
   milestones plus a 5-minute reflection. Check things off with
   `plan check` / `plan check-learning` as you go.
4. **Check in** — `plan agenda 1 --kind weekly` drafts your 1:1 agenda;
   `--kind first` for the very first 1:1, `--kind monthly` for skip-levels.
5. **Review (day 90)** — `plan review 1` drafts your self-review from the
   milestones you actually completed, with open items framed as growth areas.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `new` | Create a plan (`--company`, `--role` required; `--level`, `--start-date`, `--name`, `--focus`, `--family` optional) |
| `list` / `show` | List plans / show one plan's milestones (`--json` for scripting) |
| `week <id> <n>` | Weekly focus sheet for week 1–12 with reflection prompts |
| `check` / `uncheck` | Mark a milestone done / reopen it (goal ids from `plan show`) |
| `check-learning` | Mark a learning objective complete |
| `progress` | Completion stats overall and per phase |
| `stakeholders` | Stakeholder map: who, meeting cadence, first-meeting questions |
| `metrics` | Draft success metrics per phase (align with manager in week 1) |
| `learning` | Learning objectives with resources and priorities |
| `agenda` | 1:1 agenda draft (`--kind first` / `weekly` / `monthly`) |
| `review` | 90-day self-review draft from completed milestones |
| `export` | Export to Markdown (default) or HTML (`--format html`) |
| `remove` | Delete a plan |

## Templates

Templates live in `candid/plan_templates.py` as plain data. Each family
defines three phases (Days 1–30: Learn, 31–60: Contribute, 61–90: Own) with
week-tagged goals in four kinds (`learning`, `relationship`, `delivery`,
`process`), 4–6 learning objectives with resources, 4–6 stakeholder
archetypes with first-meeting questions, and draft success metrics.

Level modifiers in the same file add expectations per tier: juniors get
pairing and fundamentals goals; seniors get a published expectations doc,
mentorship, and cross-team initiatives; staff/principal gets org-level
strategy and sponsorship expectations.

To add or tune a template, edit the data structures and run the template
integrity tests:

```bash
python -m unittest tests.test_b53_plan.TemplateIntegrityTest
```

## Design notes

- Plans are snapshots: editing a template later does not rewrite plans you
  already created.
- Goal ids (`g1…`), learning ids (`l1…`), and metric ids (`m1…`) are stable
  within a plan; use them with `check` / `check-learning`.
- `plan new` never requires a profile; without one you get the full template
  and a nudge to run `candid onboard` for personalization.
