# Product Manager Interview Track

The PM track is a set of `candid pm ...` commands built for product-manager
interviews: question banks, concept deep-dives, timed drills, mock
interviews, STAR story practice, practice scoring, interview prep packs, and
product teardown templates.

```bash
python -m candid pm <command> --help   # every command documents itself
```

All PM-track data (prep packs, teardowns, stories, drill history) lives in
your local data dir (`candid_data/`, overridable with `CANDID_DATA_DIR`).
Nothing is sent anywhere; nothing is invented about your background or the
company's products — prompts and templates stay blank for you to fill from
your own experience.

## Command overview

| Command | What it does |
|---|---|
| `pm questions` | Browse the PM question bank: company-reported questions with sources, filterable by category and company. Reported questions carry source attribution; general ones are labeled as such. |
| `pm concepts` | Concept deep-dives for PM interviews: metrics, experimentation, prioritization frameworks, estimation, and product strategy — study notes you can review before a loop. |
| `pm drills` | Timed practice drills (estimation, metrics debugging, prioritization) with a timer and self-scoring, so you build speed under pressure. |
| `pm mock` | Mock PM interviews: product-sense, metrics, and execution questions with talking points, plus an AI-interviewer mode for a realistic loop. |
| `pm stories` | STAR story bank: write and rehearse your behavioral stories (product sense, execution, influence, failure, customer obsession) and get reminders before interview day. |
| `pm scores` | Score your drill and mock practice over time: per-category trends so you can see which PM muscle is weakest before the real loop. |
| `pm prep` | Build a PM interview prep pack: company questions, metrics to know, a teardown assignment, STAR reminders, and a day-before checklist. Saved as Markdown. |
| `pm teardown` | Create structured product teardown templates with RICE scoring — do the teardown, bring it to the interview. |

## `pm prep` — interview prep packs

```bash
python -m candid pm prep --company "Figma" --role "Growth PM"
python -m candid pm prep --company "Figma" --role "Growth PM" --json   # machine-readable
```

`build_pm_prep(company, role)` returns a dict with:

- **company_pm_questions** — company-specific PM questions from the
  `candid.pm_questions` bank (`list_questions(category=None,
  company=None)`), each with its category. The bank module is imported
  *lazily*: if it is not present, the pack says so and falls back to a
  generic PM checklist, clearly labeled as generic prep rather than verified
  company questions.
- **metrics_to_know** — metric families interviewers usually probe for this
  PM type, matched by role keyword: Growth PMs get acquisition/activation/
  retention/referral/funnel metrics; monetization roles get ARPU, CTR,
  CPC/CPM, fill rate; search/recommendation roles get long-CTR, dwell time,
  abandonment; marketplace roles get GMV, take rate, liquidity; B2B/SaaS
  roles get NRR/GRR, churn, expansion; anything else gets the default set
  (north star, input metrics, AARRR, guardrails). These are suggestions,
  never presented as the company's actual metrics.
- **teardown_prompt** — a company-specific teardown assignment: pick one of
  the company's products you use weekly, map the onboarding funnel, find
  three friction points, name the metric you would move and the experiment
  you would run.
- **star_story_reminders** — the six PM behavioral angles to have ready:
  product sense, execution under constraint, influence without authority,
  moving a metric that mattered, a launch that flopped, customer obsession.
- **day_before_checklist** — say your stories out loud, rehearse metrics
  answers, prepare sharp questions for interviewers, lock in your "why this
  company, why PM" answer, handle logistics.

The pack is rendered as Markdown and saved to
`candid_data/pm_prep_<company>.md` so you can review it on your phone the
morning of the loop.

## `pm teardown` — product teardown templates

```bash
python -m candid pm teardown new --company "Figma" --product "FigJam"
python -m candid pm teardown list
python -m candid pm teardown show figma_figjam
python -m candid pm teardown new --company "Figma" --product "FigJam" --json
```

`new_teardown(company, product)` creates a blank Markdown template in
`candid_data/teardowns/` with six sections:

1. **Product overview** — what it is, who pays, how it makes money.
2. **Target users** — 2-3 personas and the job each hires the product for.
3. **Strengths** — what it genuinely does well, from your own use.
4. **Gaps and pain points** — where you got stuck; recurring complaints from
   reviews.
5. **Opportunities with RICE scoring** — three concrete opportunities plus a
   scoring table: Reach (1-10) x Impact (1-10) x Confidence (%) / Effort
   (person-weeks). The template explains the formula; you fill in the
   numbers.
6. **Interview talking points** — the 2-minute spoken version: the product
   and its north star, the one gap you would fix first, the experiment you
   would run.

Every section starts as a `[TODO]` prompt. The generator never fabricates
product facts — it is a scaffold for *your* opinion, built from your own
hands-on use. Do the teardown before the interview; interviewers would
rather debate a real opinion than a framework recital.

## Tips

- Run `pm prep` a week out, then `pm teardown new` and spend an hour in the
  product. Re-run `pm prep` the day before for the checklist.
- Use `pm drills` for estimation and metrics-debugging speed; watch `pm
  scores` for your weakest category and aim `pm mock` sessions at it.
- Keep your `pm stories` bank current: after every real project, add one
  STAR story while the details are fresh — `pm prep` will remind you to
  rehearse them.
