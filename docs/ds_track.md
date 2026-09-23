# Data Scientist interview track

Local-first DS interview practice. Everything is stdlib-only; no network,
no keys, no paid APIs.

## Commands

| Command | What it does |
|---|---|
| `ds-stats review [--topic X] [--shuffle] [--seed N]` | 25 stats/probability concept cards (hypothesis testing, p-values, Bayes, regression, bias-variance, ...). |
| `ds-stats quiz [--n 10] [--topic X]` | Interactive quiz; numeric answers checked within tolerance, free-text by key-idea overlap. |
| `ds-metrics <metric> --y-true ... --y-score ...` | Compute accuracy/precision/recall/F1/AUC/log-loss/RMSE/MAE/uplift/lift/gain/NDCG/MAP/calibration. |
| `ds-metrics explain <metric>` | Interview-ready explanation: what it is, formula, when to use it. |
| `ds-case list|show <id>|drill <id>` | 8 ML case drills (churn, recommender, fraud, ETA, ad ranking, LTV, demand forecasting, moderation) with rubric feedback; sessions saved. |
| `ds-sysdesign list|show <id>|drill <id>` | 6 ML system-design drills (feature store, retraining pipeline, shadow deploy, experimentation platform, data quality, vector search). |
| `ds-sql list [--topic] [--difficulty]` | 15 SQL questions (aggregations, window functions, joins, CTEs, dates). |
| `ds-sql show <id>` / `ds-sql solve <id> [--file q.sql]` | Real judge: your query runs against an in-memory SQLite DB; row-set diff reported. |
| `ds-exp list|show <id>|drill <id>` | 10 experiment-design scenarios (randomization unit, guardrails, peeking, novelty, interference, SRM, ...). |
| `ds-exp calc --p 0.1 --mde 0.02 --alpha 0.05 --power 0.8` | Sample-size/power calculator for two-proportion z-tests (stdlib only). |
| `ds-takehome list|show <id>` | 6 timed take-home prompts with checklists and expected deliverable sections. |
| `ds-takehome csv <id> -o file.csv` | Generate the reproducible synthetic dataset for a prompt. |
| `ds-takehome start <id> [--hours N]` / `submit <id> <file>` | Deadline tracking + completeness check (explicitly labeled: completeness, not grading). |
| `ds-portfolio check <manifest.json|dir>` | Portfolio readiness score (0-100 across 8 dimensions) with concrete fix-next suggestions. |
| `ds-portfolio guide` | The DS portfolio playbook: 4 project archetypes, recruiter-scan tips, anti-patterns. |
| `prep ds <role-title>` | DS prep pack: stats refresher pointers, ML-case + SQL drill pointers, real reported company questions (with sources, or an explicit no-verified-questions note), STAR prompts from your profile. |
| `salary ds-bands <title>` | p25/median/p75 for DS title groups (`data-scientist`, `senior-data-scientist`, `ml-engineer`, `data-analyst`, `ds-manager`, `research-scientist`) from the same LCA wage sources. |

## Extending the banks

All content banks live as JSON under `candid/data/` and are validated by
schema tests (`tests/test_ds.py`, `tests/test_ds_drills.py`,
`tests/test_ds_track.py`):

- `ds_stats.json` — concept cards (`id, topic, concept, explanation, quiz, answer`)
- `ds_cases.json` — ML cases (`id, title, context, ml_question, probes[], rubric[]`)
- `ds_sysdesign.json` — system-design scenarios (same shape as cases)
- `ds_sql.json` — SQL questions (`id, prompt, setup_sql, solution, expected, order_matters, hint`)
- `ds_experiments.json` — A/B scenarios (`id, scenario, concepts, rubric, drill_questions[], model_answer`)

Drill scoring is a transparent keyword-heuristic self-check — it tells you
what dimensions your answer covered, not an AI grade.
