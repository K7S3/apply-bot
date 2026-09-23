"""Side-project ideator: turn resume gaps into weekend-scoped projects.

Workflow
--------
1. ``analyze_gaps`` — compare your profile skills against a target JD and
   rank the missing skills by how much the JD cares about them.
2. ``generate_ideas`` / ``rank_ideas`` — pick concrete project ideas from a
   curated, deterministic library; each idea names the exact gap skills it
   demonstrates, so every weekend maps to a resume line.
3. ``weekend_scope`` — break an idea into weekend-sized milestones with
   done-criteria.
4. ``suggest_stack`` — recommend a tech stack for the idea, adjusted to the
   JD's keywords (TypeScript over JS when the JD says TypeScript, etc.).
5. ``estimate`` — hours per milestone, discounted for stack you already
   know, mapped onto a weekend calendar.
6. ``learning_plan`` — free resources for the stack, no scraping.
7. ``scaffold`` — starter repo (README, .gitignore, skeleton code).
8. Project ledger (``add_project``/``list_projects``/``remove_project``) —
   record what you've built; the ideator stops suggesting skills your
   finished projects already demonstrate.
9. ``build_story`` — turn a finished project into STAR resume bullets,
   interview talking points, and a demo checklist.

Everything is local and deterministic: the idea library is curated data,
not an LLM call, so suggestions are reproducible and explainable.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from candid import config as C


class ProjectError(Exception):
    """Expected failure: bad idea id, bad ledger op, scaffold collision."""


# --- curated idea library ----------------------------------------------------
# Each template: the exact gap skills it demonstrates, who it impresses,
# a default stack, and weekend-sized milestones with done-criteria.
# difficulty 1-3 (1 = one calm weekend), appeal 1-5 (recruiter eyebrow-raise).

_IDEA_TEMPLATES: list[dict] = [
    {
        "id": "rag-support-bot",
        "title": "RAG support bot over product docs",
        "summary": "Chatbot that answers questions from a docs corpus with citations.",
        "why": ("Every AI-adjacent JD asks for RAG/LLM experience; this is the "
                "cheapest credible proof: retrieval + rerank + cited generation, "
                "deployed behind an API with an eval set."),
        "skills": ["llm", "nlp", "python"],
        "roles": ["ml", "backend"],
        "difficulty": 2, "appeal": 5,
        "stack_skills": ["python", "llm"],
        "stack": {
            "language": "Python 3.11",
            "framework": "FastAPI",
            "retrieval": "pgvector (Postgres) or FAISS",
            "models": "open-source embeddings + an LLM API or local Ollama",
            "deploy": "Docker + a single VM",
        },
        "weekends": [
            {"goal": "Ingest + retrieve",
             "tasks": ["Crawl/chunk 200+ docs pages into clean passages",
                       "Embed and index in pgvector; build a /search endpoint",
                       "Measure recall@5 on 30 hand-written questions"],
             "done": "/search returns the right passage in the top 5 for 80%+ of test questions",
             "hours": 10},
            {"goal": "Generate + cite",
             "tasks": ["Add a /ask endpoint: retrieve, rerank, generate with citations",
                       "Add a 50-question golden eval set; score answer correctness",
                       "Ship a minimal chat UI and Dockerize the whole thing"],
             "done": "Deployed demo where every answer shows its source passages; eval score recorded in README",
             "hours": 12},
        ],
        "demo": ["Show a question the bot answers with citations",
                 "Show the eval set and how a prompt change moved the score",
                 "Explain chunking choices and why recall@5 was the metric"],
        "pitfalls": ["Don't skip the eval set - 'it feels good' is not a result",
                     "Keep the corpus small and clean; garbage docs = garbage answers"],
    },
    {
        "id": "llm-eval-harness",
        "title": "LLM prompt eval harness",
        "summary": "Framework to A/B test prompts with statistical rigor.",
        "why": ("Teams shipping LLM features desperately need eval discipline; "
                "this shows you think like an experimentalist, not a prompt "
                "tinkerer - a rare and hireable combination."),
        "skills": ["llm", "statistics", "python"],
        "roles": ["ml", "data"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "llm", "statistics"],
        "stack": {
            "language": "Python 3.11",
            "framework": "Plain Python package + Click CLI",
            "storage": "SQLite for runs, Parquet for results",
            "stats": "scipy for significance tests",
            "deploy": "GitHub repo + CI running the eval suite",
        },
        "weekends": [
            {"goal": "Runner + judges",
             "tasks": ["Define an eval-case schema (prompt, inputs, expected, judge)",
                       "Implement sync/async runners against 2+ model providers",
                       "Add LLM-as-judge and exact-match judges"],
             "done": "One command runs N cases across 2 prompts and prints a comparison table",
             "hours": 10},
            {"goal": "Statistics + report",
             "tasks": ["Add paired significance tests and confidence intervals on win rates",
                       "Generate a markdown report with per-case diffs",
                       "Evaluate 3 prompt variants on a real task (e.g. summarization) and write up the winner"],
             "done": "Report shows prompt B beats A with p<0.05 on 100 cases; repo documents the methodology",
             "hours": 10},
        ],
        "demo": ["Run the harness live on two prompts and show the diff report",
                 "Explain why paired tests, not raw averages",
                 "Show how a 'better sounding' prompt lost on the eval set"],
        "pitfalls": ["LLM judges have biases - note position/length bias in the README",
                     "Keep eval sets versioned; changing them mid-comparison invalidates results"],
    },
    {
        "id": "finetune-classifier",
        "title": "LoRA fine-tune of a small LLM for classification",
        "summary": "Fine-tune an open 1-8B model on a niche classification task.",
        "why": ("'Fine-tuning experience' on JDs usually means exactly this; a "
                "clean LoRA run with a proper train/eval split and a comparison "
                "against prompting is worth more than a certificate."),
        "skills": ["llm", "deep learning", "python"],
        "roles": ["ml"],
        "difficulty": 3, "appeal": 4,
        "stack_skills": ["python", "llm", "deep learning"],
        "stack": {
            "language": "Python 3.11",
            "framework": "Hugging Face transformers + PEFT (LoRA)",
            "compute": "A single rented GPU (or free Colab tier)",
            "tracking": "Weights & Biases free tier or plain CSV logs",
            "deploy": "Merge adapter + quantize; serve via Ollama",
        },
        "weekends": [
            {"goal": "Data + baseline",
             "tasks": ["Pick/build a 2-5k example labeled dataset for a niche task",
                       "Establish a prompting baseline with accuracy on a held-out split",
                       "Set up the training script with PEFT/LoRA"],
             "done": "Baseline accuracy recorded; training runs end-to-end on a GPU",
             "hours": 12},
            {"goal": "Tune + compare + serve",
             "tasks": ["Sweep LoRA rank/learning rate; pick by validation F1",
                       "Compare fine-tune vs prompting vs a linear baseline in a table",
                       "Quantize, serve locally, write up what worked in the README"],
             "done": "Fine-tuned model beats the prompting baseline by a documented margin; demo serves it locally",
             "hours": 12},
        ],
        "demo": ["Show the accuracy table: baseline vs fine-tuned",
                 "Show a failure case the fine-tune fixed",
                 "Explain LoRA in one minute (frozen weights + low-rank update)"],
        "pitfalls": ["Watch for train/test leakage - dedupe near-duplicates",
                     "Don't fine-tune on 200 examples and claim victory; say what the data limits are"],
    },
    {
        "id": "semantic-search",
        "title": "Semantic search over docs or code",
        "summary": "Natural-language search with embeddings, filters, and highlighting.",
        "why": ("Search is a evergreen backend/ML interview topic; this gives "
                "you a real artifact plus opinions on chunking, hybrid ranking, "
                "and latency tradeoffs."),
        "skills": ["llm", "nlp", "python"],
        "roles": ["ml", "backend"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "llm", "nlp"],
        "stack": {
            "language": "Python 3.11",
            "framework": "FastAPI",
            "retrieval": "FAISS or pgvector, BM25 hybrid via rank-bm25",
            "models": "Sentence-transformers (open, local)",
            "deploy": "Docker; UI as a single static page",
        },
        "weekends": [
            {"goal": "Index + hybrid rank",
             "tasks": ["Chunk and embed a corpus (docs or a code repo)",
                       "Implement hybrid BM25 + vector ranking with score fusion",
                       "Build a search UI with match highlighting"],
             "done": "Queries return highlighted results in <300ms; hybrid beats pure-vector on a 40-query test set",
             "hours": 10},
            {"goal": "Filters + quality pass",
             "tasks": ["Add metadata filters (date, type, repo path)",
                       "Tune chunk size/overlap; document the effect on recall",
                       "Add query analytics logging (what people search, zero-result rate)"],
             "done": "README shows the chunking experiment results; zero-result queries are logged and reviewable",
             "hours": 8},
        ],
        "demo": ["Search for something with synonyms the keywords miss",
                 "Show the hybrid-vs-pure ranking comparison",
                 "Explain one chunking tradeoff you measured"],
        "pitfalls": ["Embeddings go stale - note a reindex strategy",
                     "Latency matters; measure it, don't assume"],
    },
    {
        "id": "realtime-recs",
        "title": "Real-time recommendation microservice",
        "summary": "Low-latency recommender: candidate generation + ranking API.",
        "why": ("Recsys roles want the full loop - candidates, ranking, serving, "
                "measurement. A small but complete service beats a notebook with "
                "a good offline MAP score."),
        "skills": ["recommendations", "mlops", "python"],
        "roles": ["ml", "backend"],
        "difficulty": 3, "appeal": 5,
        "stack_skills": ["python", "recommendations", "mlops"],
        "stack": {
            "language": "Python 3.11",
            "framework": "FastAPI",
            "models": "Two-tower or ALS candidates + LightGBM ranker",
            "storage": "Redis for features/candidates, Postgres for events",
            "deploy": "Docker Compose; Prometheus metrics endpoint",
        },
        "weekends": [
            {"goal": "Offline pipeline",
             "tasks": ["Train candidate + ranker models on MovieLens or similar",
                       "Build an event logger that writes impressions/clicks",
                       "Offline eval: recall@K and a ranker AUC"],
             "done": "Models trained with documented offline metrics; event schema fixed",
             "hours": 12},
            {"goal": "Serve + measure",
             "tasks": ["Serve /recommend with p99 latency logging",
                       "Add a shadow A/B: random vs model, log both",
                       "Dashboard the click-through difference"],
             "done": "Live endpoint with p99 <100ms; README shows the A/B read with confidence intervals",
             "hours": 12},
            {"goal": "Harden (optional third weekend)",
             "tasks": ["Cold-start fallback for new users/items",
                       "Feature freshness job; retrain script on a schedule",
                       "Load test to 100 rps and document the bottleneck"],
             "done": "Cold-start path documented; load test results in README",
             "hours": 8},
        ],
        "demo": ["Hit the endpoint and show p99 latency",
                 "Show the A/B dashboard: model vs random CTR",
                 "Explain the cold-start fallback"],
        "pitfalls": ["Offline metrics lie - the A/B is the real result",
                     "Don't train on future data; time-split honestly"],
    },
    {
        "id": "churn-xgb",
        "title": "Churn prediction, end to end",
        "summary": "From raw events to a tuned churn model with explanations.",
        "why": ("The classic 'can you ship a model' project: feature engineering "
                "from messy data, proper validation, calibration, and SHAP "
                "explanations a PM could read."),
        "skills": ["machine learning", "scikit-learn", "xgboost", "sql"],
        "roles": ["ml", "data"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "scikit-learn", "xgboost", "sql"],
        "stack": {
            "language": "Python 3.11",
            "framework": "scikit-learn pipelines + XGBoost",
            "data": "SQLite/Postgres with SQL feature queries",
            "explain": "SHAP",
            "deploy": "Batch scoring script + a one-page report",
        },
        "weekends": [
            {"goal": "Features + validation",
             "tasks": ["Build SQL feature queries over an event table (telco churn or similar)",
                       "Time-based train/validation split; tune XGBoost",
                       "Calibrate probabilities and check the calibration curve"],
             "done": "Validated AUC + calibration plot; no time leakage (features only use past data)",
             "hours": 10},
            {"goal": "Explain + productize",
             "tasks": ["SHAP summary + per-customer explanation examples",
                       "Write the 'what would we do with this' section: thresholds, outreach cost model",
                       "Package scoring as a script with a README runbook"],
             "done": "One-command scoring; README has the business framing, not just the AUC",
             "hours": 8},
        ],
        "demo": ["Show the calibration curve and explain why it matters",
                 "Show a SHAP explanation for one customer",
                 "Walk through the leakage checks"],
        "pitfalls": ["Time leakage is the #1 silent killer - split by time, engineer from past only",
                     "AUC without calibration is a half-finished model"],
    },
    {
        "id": "mlops-pipeline",
        "title": "Full MLOps pipeline: train, registry, deploy, monitor",
        "summary": "CI/CD for ML with model registry, shadow deploy, drift alerts.",
        "why": ("MLOps is the most common 'missing skill' on ML JDs for people "
                "with modeling backgrounds; this is direct, legible proof you "
                "can operate a model, not just train one."),
        "skills": ["mlops", "cloud", "python"],
        "roles": ["ml", "platform"],
        "difficulty": 3, "appeal": 5,
        "stack_skills": ["python", "mlops", "cloud"],
        "stack": {
            "language": "Python 3.11",
            "orchestration": "GitHub Actions",
            "registry": "MLflow",
            "serving": "FastAPI in Docker",
            "deploy": "A cheap VM or free-tier cloud",
            "monitor": "Evidently or hand-rolled drift checks + alerts",
        },
        "weekends": [
            {"goal": "Train + registry + CI",
             "tasks": ["Train a simple model with MLflow tracking",
                       "CI pipeline: lint, test, train, register model version",
                       "Promotion rule: only register if eval beats the champion"],
             "done": "Merging to main retrains and registers a versioned model automatically",
             "hours": 12},
            {"goal": "Deploy + monitor",
             "tasks": ["Serve the champion model behind a versioned API",
                       "Shadow-deploy the challenger; log both predictions",
                       "Drift checks on inputs with a Slack/email alert on drift"],
             "done": "Deployed API serving the champion; drift alert fires on a synthetic data shift",
             "hours": 12},
        ],
        "demo": ["Show the MLflow registry with version lineage",
                 "Trigger the drift alert live",
                 "Explain the champion/challenger promotion rule"],
        "pitfalls": ["Don't monitor everything - pick 3 signals and alert on those",
                     "Pin dependencies; unpinned training envs are not reproducible"],
    },
    {
        "id": "k8s-gitops-lab",
        "title": "GitOps homelab on k3s",
        "summary": "A tiny Kubernetes cluster managed fully by git.",
        "why": ("For platform/MLOps roles, 'Kubernetes' on a resume with a "
                "GitOps repo to point at beats any amount of tutorial watching."),
        "skills": ["mlops", "cloud"],
        "roles": ["platform", "ml"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["mlops", "cloud"],
        "stack": {
            "language": "YAML + a little Python/Go for operators",
            "cluster": "k3s on a cheap VM or Raspberry Pi",
            "gitops": "ArgoCD or Flux",
            "apps": "A demo API + Postgres + monitoring",
            "secrets": "Sealed Secrets or External Secrets",
        },
        "weekends": [
            {"goal": "Cluster + GitOps bootstrap",
             "tasks": ["Stand up k3s; install ArgoCD; connect your repo",
                       "Deploy a sample API + Postgres via Helm/Kustomize from git",
                       "Verify: change in git -> rollout in cluster"],
             "done": "A git push visibly rolls out a new app version with zero manual kubectl",
             "hours": 10},
            {"goal": "Operate it like prod-lite",
             "tasks": ["Add Prometheus + Grafana dashboards for the cluster",
                       "Secret management without plaintext in git",
                       "Write the incident runbook: node down, disk pressure, bad deploy rollback"],
             "done": "Dashboards show cluster health; rollback demo: revert a commit, watch ArgoCD heal",
             "hours": 10},
        ],
        "demo": ["Push a commit and watch the rollout",
                 "Show the Grafana dashboard",
                 "Demo a rollback by reverting"],
        "pitfalls": ["Don't expose the cluster to the internet without auth",
                     "Document costs; a homelab that costs $200/mo is a red flag"],
    },
    {
        "id": "airflow-etl",
        "title": "Airflow batch ETL with data-quality gates",
        "summary": "Daily pipeline: ingest, transform, test, publish.",
        "why": ("Data-engineering JDs list Airflow + SQL + testing; a pipeline "
                "with real quality gates shows production instincts."),
        "skills": ["mlops", "sql", "python"],
        "roles": ["data", "platform"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "sql", "mlops"],
        "stack": {
            "language": "Python 3.11",
            "orchestration": "Airflow (Docker Compose)",
            "warehouse": "Postgres or DuckDB",
            "quality": "dbt tests or Great Expectations",
            "deploy": "Docker Compose on a VM",
        },
        "weekends": [
            {"goal": "Pipeline skeleton",
             "tasks": ["Ingest a public dataset daily (or simulate with a generator)",
                       "Transform into clean marts with SQL",
                       "Add freshness + row-count + uniqueness tests that fail the DAG"],
             "done": "DAG runs green end-to-end; a deliberately broken input fails loudly",
             "hours": 10},
            {"goal": "Backfills + observability",
             "tasks": ["Make the pipeline idempotent; demo a backfill over 7 days",
                       "Alert on failure (email/Slack); SLA miss dashboard",
                       "Document the data contract for downstream consumers"],
             "done": "Backfill reruns cleanly with no duplicates; failure alert demoed",
             "hours": 10},
        ],
        "demo": ["Show the DAG graph and a successful run",
                 "Break the input and show the quality gate failing",
                 "Show the backfill producing identical results twice"],
        "pitfalls": ["Idempotency first - reruns must not double-count",
                     "Test the alert path; an alert you've never seen fire is fiction"],
    },
    {
        "id": "streaming-spark",
        "title": "Streaming pipeline with Spark Structured Streaming",
        "summary": "Event stream in, aggregated features out, exactly-once.",
        "why": ("Streaming is a differentiator on data JDs; exactly-once "
                "semantics and late-data handling are the interview talking "
                "points this project hands you."),
        "skills": ["spark", "python", "sql"],
        "roles": ["data", "platform"],
        "difficulty": 3, "appeal": 4,
        "stack_skills": ["python", "spark", "sql"],
        "stack": {
            "language": "Python 3.11 (PySpark)",
            "streaming": "Kafka (Docker) or socket/file source to start",
            "processing": "Spark Structured Streaming",
            "sink": "Parquet files or Postgres",
            "deploy": "Docker Compose",
        },
        "weekends": [
            {"goal": "Stream in, aggregate out",
             "tasks": ["Stand up Kafka + a synthetic event generator",
                       "Structured Streaming job: windowed aggregations with watermarks",
                       "Exactly-once sink via checkpointing; kill and restart mid-stream"],
             "done": "Restart loses/duplicates zero events; watermark drops late data as designed",
             "hours": 12},
            {"goal": "Late data + joins",
             "tasks": ["Handle late arrivals: measure % dropped vs watermark choice",
                       "Stream-static join against a dimension table",
                       "Latency dashboard: event-time to output-time"],
             "done": "README documents the watermark tradeoff with measured numbers",
             "hours": 10},
        ],
        "demo": ["Kill the job mid-stream and show zero loss on restart",
                 "Show the latency dashboard",
                 "Explain watermarks in plain language"],
        "pitfalls": ["Start with a file/socket source if Kafka fights you - migrate later",
                     "Checkpoints must survive restarts; test the kill -9 case, not just ctrl-C"],
    },
]

_SECOND_WAVE: list[dict] = [
    {
        "id": "dbt-marts",
        "title": "dbt marts + executive dashboard",
        "summary": "Modeled warehouse marts feeding a KPI dashboard.",
        "why": ("Analytics-engineering JDs are dbt + SQL + a BI tool; a repo "
                "with tested models and documented lineage is the portfolio "
                "standard for these roles."),
        "skills": ["dbt", "sql", "data visualization"],
        "roles": ["data"],
        "difficulty": 1, "appeal": 4,
        "stack_skills": ["sql", "dbt", "data visualization"],
        "stack": {
            "language": "SQL + a little Python",
            "transform": "dbt Core",
            "warehouse": "DuckDB (local) or Postgres",
            "bi": "Evidence, Streamlit, or Metabase",
            "deploy": "GitHub repo + scheduled dbt run",
        },
        "weekends": [
            {"goal": "Models + tests",
             "tasks": ["Stage raw data; build staging -> intermediate -> mart layers",
                       "Add dbt tests (unique, not_null, relationships, accepted_values)",
                       "Document every model with descriptions in schema.yml"],
             "done": "`dbt build` green; docs site generated with full lineage graph",
             "hours": 8},
            {"goal": "Dashboard + metrics",
             "tasks": ["Define 5 core metrics with exact SQL definitions",
                       "Build the dashboard; every chart links to its model",
                       "Add one 'metric deep-dive' writeup explaining a surprising trend"],
             "done": "Dashboard live; README defines each metric in one sentence",
             "hours": 8},
        ],
        "demo": ["Show the dbt lineage graph",
                 "Click a dashboard number and trace it to SQL",
                 "Show a test catching a bad data load"],
        "pitfalls": ["Metrics need definitions - 'revenue' means nothing without one",
                     "Keep the layering honest; marts shouldn't query raw tables"],
    },
    {
        "id": "ab-simulator",
        "title": "A/B test design simulator",
        "summary": "Simulate experiments to teach power, peeking, and SRM checks.",
        "why": ("Experimentation roles screen for exactly this intuition; a "
                "simulator you built proves you understand power analysis and "
                "peeking bias, not just the vocabulary."),
        "skills": ["statistics", "product analytics", "python"],
        "roles": ["data", "ml"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "statistics", "product analytics"],
        "stack": {
            "language": "Python 3.11",
            "ui": "Streamlit",
            "stats": "numpy/scipy",
            "deploy": "Streamlit Community Cloud (free)",
        },
        "weekends": [
            {"goal": "Simulator core",
             "tasks": ["Simulate Bernoulli/metric outcomes under null and alternative",
                       "Power calculator: MDE vs sample size vs power curves",
                       "Peeking demo: show false-positive inflation when checking daily"],
             "done": "App shows power curves; peeking demo reproducibly inflates Type I error",
             "hours": 10},
            {"goal": "SRM + writeup",
             "tasks": ["Add a sample-ratio-mismatch detector with chi-square test",
                       "Simulate common pitfalls: novelty effect, carryover",
                       "Write the 'how to read an experiment' guide in the app"],
             "done": "SRM detector flags an injected imbalance; guide published in-app",
             "hours": 8},
        ],
        "demo": ["Drag the peeking slider and watch false positives climb",
                 "Inject SRM and show the detector firing",
                 "Explain MDE to a non-technical friend using the app"],
        "pitfalls": ["Simulations must be seeded and reproducible",
                     "Label assumptions; a simulator that hides them teaches the wrong lesson"],
    },
    {
        "id": "experiment-platform",
        "title": "Mini experimentation platform",
        "summary": "Feature flags + assignment + results for toy web apps.",
        "why": ("Full-stack experimentation platforms are rare on resumes and "
                "directly relevant to product-engineering and data roles at "
                "product companies."),
        "skills": ["statistics", "product analytics", "javascript", "python"],
        "roles": ["data", "backend", "frontend"],
        "difficulty": 3, "appeal": 4,
        "stack_skills": ["python", "javascript", "statistics"],
        "stack": {
            "language": "TypeScript frontend, Python backend",
            "backend": "FastAPI: assignment service + event ingestion",
            "frontend": "React demo app behind flag-gated UI",
            "storage": "Postgres",
            "analysis": "Nightly results job with sequential-safe stats",
        },
        "weekends": [
            {"goal": "Flags + assignment",
             "tasks": ["Flag service with sticky bucketing by user id",
                       "Demo app with two gated variants",
                       "Event pipeline: exposures and conversions into Postgres"],
             "done": "Same user always sees the same variant; exposures logged",
             "hours": 12},
            {"goal": "Results + guardrails",
             "tasks": ["Results page: conversion lift with confidence intervals",
                       "SRM check on every experiment automatically",
                       "Kill-switch: one click disables a flag everywhere"],
             "done": "Dashboard reads an experiment correctly; kill-switch demoed live",
             "hours": 12},
        ],
        "demo": ["Toggle a flag and watch the UI change",
                 "Show the results page with CIs and the SRM check",
                 "Hit the kill-switch"],
        "pitfalls": ["Sticky bucketing is load-bearing - hash, don't random()",
                     "Sequential testing matters if anyone peeks; say which method you used"],
    },
    {
        "id": "forecast-dashboard",
        "title": "Demand forecasting dashboard",
        "summary": "Forecast vs actual with error attribution.",
        "why": ("Forecasting JDs want the unglamorous parts: backtesting, "
                "hierarchical reconciliation, and honest error analysis - all "
                "of which this project forces you to do."),
        "skills": ["time series", "data visualization", "python"],
        "roles": ["data", "ml"],
        "difficulty": 2, "appeal": 3,
        "stack_skills": ["python", "time series", "data visualization"],
        "stack": {
            "language": "Python 3.11",
            "models": "StatsForecast (fast) or Darts",
            "ui": "Streamlit or Plotly Dash",
            "deploy": "Scheduled refresh + static hosting",
        },
        "weekends": [
            {"goal": "Backtest harness",
             "tasks": ["Pick a public demand/energy dataset",
                       "Rolling-origin backtest: naive vs seasonal-naive vs ETS/ARIMA",
                       "Error attribution: bias vs variance vs holiday effects"],
             "done": "Backtest table with MASE per model; winner chosen by backtest, not vibes",
             "hours": 10},
            {"goal": "Dashboard + reconciliation",
             "tasks": ["Forecast vs actual charts with prediction intervals",
                       "Hierarchical reconciliation (category totals match sum of parts)",
                       "Document where the model fails (promotions, holidays)"],
             "done": "Dashboard shows intervals, not just lines; failure modes written up",
             "hours": 8},
        ],
        "demo": ["Show the backtest table and defend the model choice",
                 "Point at a holiday the model missed and explain why",
                 "Show prediction intervals widening with horizon"],
        "pitfalls": ["Never evaluate on the training window - rolling origin only",
                     "Intervals are the product; point forecasts alone mislead"],
    },
    {
        "id": "realtime-kpi",
        "title": "Real-time KPI dashboard",
        "summary": "Streaming metrics with anomaly alerts.",
        "why": ("Product analytics roles love 'I built the dashboard the team "
                "actually watched'; anomaly detection on top shows judgment "
                "about signal vs noise."),
        "skills": ["data visualization", "product analytics", "sql"],
        "roles": ["data", "backend"],
        "difficulty": 2, "appeal": 3,
        "stack_skills": ["sql", "data visualization", "product analytics"],
        "stack": {
            "language": "Python 3.11 + SQL",
            "stream": "A generator or webhook into Postgres/TimescaleDB",
            "ui": "Streamlit or Grafana",
            "alerts": "Simple z-score/EWMA anomaly detector",
        },
        "weekends": [
            {"goal": "Pipeline + dashboard",
             "tasks": ["Event generator -> Postgres with 1-minute rollups",
                       "Dashboard: funnels, KPIs, timeseries with refresh",
                       "Define each metric once, in SQL, documented"],
             "done": "Dashboard refreshes live; every KPI has a one-sentence definition",
             "hours": 10},
            {"goal": "Anomaly alerts",
             "tasks": ["Baseline per metric (day-of-week aware)",
                       "Alert on sustained deviation, not single spikes",
                       "Alert log with acknowledge/resolve; measure false-positive rate"],
             "done": "Injected anomaly triggers exactly one alert; README notes the FP rate",
             "hours": 8},
        ],
        "demo": ["Inject a traffic spike and watch the alert fire",
                 "Show a single spike that correctly did NOT alert",
                 "Trace one KPI back to its SQL"],
        "pitfalls": ["Alert fatigue kills dashboards - tune for precision",
                     "Day-of-week seasonality will embarrass a naive baseline"],
    },
    {
        "id": "pricing-optimizer",
        "title": "Price optimization with linear programming",
        "summary": "Elasticity-informed pricing under inventory constraints.",
        "why": ("Optimization is a niche, high-signal skill; a clean LP with a "
                "readable business writeup stands out in ops/research-adjacent "
                "roles."),
        "skills": ["optimization", "python", "data visualization"],
        "roles": ["data", "ml"],
        "difficulty": 2, "appeal": 3,
        "stack_skills": ["python", "optimization"],
        "stack": {
            "language": "Python 3.11",
            "solver": "PuLP (CBC) or OR-Tools",
            "analysis": "pandas + matplotlib",
            "deploy": "Notebook-to-report repo",
        },
        "weekends": [
            {"goal": "Model + solve",
             "tasks": ["Estimate demand curves from a public retail dataset",
                       "Formulate the LP: maximize revenue subject to inventory/margin constraints",
                       "Solve and sanity-check against heuristics"],
             "done": "Optimal prices computed; LP beats naive heuristics by a documented margin",
             "hours": 10},
            {"goal": "Sensitivity + writeup",
             "tasks": ["Sensitivity analysis: which constraints bind, shadow prices",
                       "What-if UI: change inventory, see prices move",
                       "Write the business memo: recommendation + risks + what you'd need to deploy"],
             "done": "Memo-quality writeup with shadow-price interpretation",
             "hours": 8},
        ],
        "demo": ["Show the shadow prices and explain one in English",
                 "Change a constraint live and watch prices adapt",
                 "Defend the elasticity estimates"],
        "pitfalls": ["Elasticity estimates are the weak link - say so explicitly",
                     "An LP that ignores business constraints is a toy; add at least two real ones"],
    },
    {
        "id": "sentiment-api",
        "title": "Transformer sentiment API with drift watch",
        "summary": "Fine-tuned sentiment model served with input monitoring.",
        "why": ("A complete NLP micro-project: transfer learning, serving, and "
                "the monitoring everyone forgets - compact enough for two "
                "weekends."),
        "skills": ["nlp", "deep learning", "python", "mlops"],
        "roles": ["ml", "backend"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "nlp", "deep learning"],
        "stack": {
            "language": "Python 3.11",
            "models": "Hugging Face transformers (DistilBERT-class)",
            "serving": "FastAPI in Docker",
            "monitor": "Embedding-drift check on inputs",
        },
        "weekends": [
            {"goal": "Fine-tune + serve",
             "tasks": ["Fine-tune on a sentiment dataset; beat a TF-IDF baseline",
                       "Serve via FastAPI with batching; measure p99",
                       "Error analysis: 20 mistakes, categorized"],
             "done": "API live with p99 logged; error categories written up",
             "hours": 10},
            {"goal": "Drift watch",
             "tasks": ["Log input embeddings; alert when distribution shifts",
                       "Adversarial test set: sarcasm, negation, mixed sentiment",
                       "Document where the model is unreliable"],
             "done": "Drift alert demoed on a topic-shifted input batch",
             "hours": 8},
        ],
        "demo": ["Show the error analysis categories",
                 "Demo the drift alert on shifted inputs",
                 "Explain one sarcasm failure honestly"],
        "pitfalls": ["Sentiment datasets are full of artifacts - check them",
                     "Don't claim production-readiness; claim measured behavior"],
    },
    {
        "id": "portfolio-site",
        "title": "Portfolio site with a technical blog",
        "summary": "Fast personal site; each project gets a writeup.",
        "why": ("For frontend-leaning roles this IS the resume; for everyone "
                "else it's the landing page your projects link back to. "
                "Recruiters click links - give them somewhere good to land."),
        "skills": ["javascript"],
        "roles": ["frontend", "ml", "data", "backend"],
        "difficulty": 1, "appeal": 3,
        "stack_skills": ["javascript"],
        "stack": {
            "language": "TypeScript",
            "framework": "Next.js or Astro",
            "styling": "Tailwind",
            "deploy": "Vercel/Netlify (free)",
            "content": "Markdown blog posts",
        },
        "weekends": [
            {"goal": "Site live",
             "tasks": ["Scaffold with a clean template; make it yours, not the default theme",
                       "Projects page linking every repo with a one-line pitch",
                       "Lighthouse 95+ on performance/accessibility"],
             "done": "Deployed on your domain (or subdomain); loads fast on mobile",
             "hours": 8},
            {"goal": "Two deep writeups",
             "tasks": ["Write up your best project: problem, approach, results, what you'd change",
                       "Write one 'things I learned' post with real technical content",
                       "Add analytics; note what gets read"],
             "done": "Two posts published that a hiring manager would actually finish",
             "hours": 8},
        ],
        "demo": ["Show the Lighthouse scores",
                 "Read the first paragraph of your best writeup out loud - does it hook?",
                 "Show the projects page on a phone"],
        "pitfalls": ["Default templates are recognizable - customize visibly",
                     "A blog with zero posts is worse than no blog; ship with two"],
    },
    {
        "id": "serverless-etl",
        "title": "Serverless ETL on cloud functions",
        "summary": "Event-driven pipeline with zero servers to babysit.",
        "why": ("Cloud-native data work is increasingly serverless; this shows "
                "you can build event-driven systems and think about cost, "
                "retries, and idempotency."),
        "skills": ["cloud", "python", "sql"],
        "roles": ["data", "backend", "platform"],
        "difficulty": 2, "appeal": 4,
        "stack_skills": ["python", "cloud", "sql"],
        "stack": {
            "language": "Python 3.11",
            "compute": "AWS Lambda / GCP Cloud Functions",
            "infra": "Terraform or Pulumi",
            "storage": "S3/GCS + a warehouse (BigQuery/Snowflake free tier)",
            "deploy": "CI deploys the IaC",
        },
        "weekends": [
            {"goal": "Pipeline on functions",
             "tasks": ["File-drop triggers function: validate, transform, load",
                       "IaC for the whole stack; destroy and recreate from scratch",
                       "Dead-letter queue for bad records with a replay path"],
             "done": "Drop a file, watch it flow; bad file lands in DLQ with an alert",
             "hours": 12},
            {"goal": "Cost + reliability",
             "tasks": ["Idempotent loads (rerun-safe); test by double-firing",
                       "Cost dashboard: per-run cost tracked and budgeted",
                       "Backfill story: replay 30 days through the same path"],
             "done": "README shows per-1k-records cost; double-fire produces no duplicates",
             "hours": 8},
        ],
        "demo": ["Drop a file and trace it through logs",
                 "Show the DLQ replay",
                 "Show the cost per run"],
        "pitfalls": ["Cold starts and timeouts will bite - set them deliberately",
                     "IaC from day one; click-ops doesn't count as cloud skill"],
    },
    {
        "id": "dq-monitor",
        "title": "Data-quality monitor for a warehouse",
        "summary": "Scheduled checks with an incident workflow.",
        "why": ("Data quality is everyone's problem and nobody's resume line; "
                "owning it visibly signals seniority beyond your years."),
        "skills": ["sql", "python", "data visualization"],
        "roles": ["data", "platform"],
        "difficulty": 1, "appeal": 3,
        "stack_skills": ["python", "sql"],
        "stack": {
            "language": "Python 3.11 + SQL",
            "checks": "Hand-rolled YAML check definitions",
            "schedule": "Cron or Airflow",
            "ui": "Status page (Streamlit) + Slack alerts",
        },
        "weekends": [
            {"goal": "Checks + alerts",
             "tasks": ["YAML-defined checks: freshness, volume, nulls, distributions",
                       "Runner executes checks and writes results history",
                       "Slack alert on failure with the offending query attached"],
             "done": "5+ checks green on a real dataset; injected fault alerts correctly",
             "hours": 8},
            {"goal": "Incident workflow",
             "tasks": ["Status page with check history and uptime",
                       "Acknowledge/silence workflow for known issues",
                       "Postmortem template: fill one out for your injected fault"],
             "done": "Status page live; one completed example postmortem in the repo",
             "hours": 8},
        ],
        "demo": ["Inject a fault and watch the alert + status page",
                 "Show the results history trending",
                 "Walk through the example postmortem"],
        "pitfalls": ["Checks need owners and thresholds - defaults alert on noise",
                     "History matters more than the current status; keep it"],
    },
]

_IDEAS: list[dict] = _IDEA_TEMPLATES + _SECOND_WAVE
_IDEA_INDEX: dict[str, dict] = {t["id"]: t for t in _IDEAS}


def list_ideas() -> list[dict]:
    """All curated idea templates (lightweight summaries)."""
    return [{"id": t["id"], "title": t["title"], "summary": t["summary"],
             "skills": t["skills"], "difficulty": t["difficulty"],
             "weekends": len(t["weekends"])} for t in _IDEAS]


def get_idea(idea_id: str) -> dict:
    """Full template for an idea id; raises ProjectError listing valid ids."""
    try:
        return _IDEA_INDEX[idea_id]
    except KeyError:
        valid = ", ".join(sorted(_IDEA_INDEX))
        raise ProjectError(f"Unknown idea '{idea_id}'. Valid ids: {valid}")


def _profile_skills(profile: dict) -> set[str]:
    return {s.strip().lower() for s in profile.get("skills", []) if s}


def _jd_gap_skills(jd_text: str) -> dict[str, float]:
    """JD skill -> importance weight.

    Uses the full match extraction (must/nice/context tiers) so short or
    loosely formatted JDs still yield gaps: must=2.0, nice=1.0, context=0.5.
    """
    from candid import match as M
    ex = M._extract_jd(jd_text)
    weights: dict[str, float] = {}
    for name, info in ex["items"].items():
        tier = info["tier"]
        if tier not in ("must", "nice", "context"):
            continue
        if name not in C.SKILL_LEXICON:
            # Free-form tokens (company names, quoted phrases) can't map to
            # ideas - the library only covers canonical skills. Skip them so
            # the gaps view stays actionable.
            continue
        weights[name] = {"must": 2.0, "nice": 1.0, "context": 0.5}[tier]
    return weights


# --- gap analysis ------------------------------------------------------------

def _fix_pointer(skill: str, profile_skills: set[str]) -> tuple[str, str]:
    """Classify how to close a skill gap: reframe, project, or course.

    Returns (fix, pointer). 'reframe' when the skill overlaps something the
    profile already names (just say it louder); 'project' for hands-on
    technical skills (the ideator's home turf); 'course' for theory-heavy
    skills where structured learning beats building first.
    """
    toks = set(skill.split())
    for ps in sorted(profile_skills):
        if toks & set(ps.split()):
            return ("reframe",
                    f"Adjacent to '{ps}' on your resume - name '{skill}' explicitly "
                    f"wherever it applies before building anything new.")
    theory = {"statistics", "finance", "optimization"}
    if skill in theory and not (toks & {"python", "sql"}):
        return ("course",
                f"'{skill}' rewards structured study first; pair a short course "
                f"with one applied project below.")
    return ("project",
            f"'{skill}' is best proven by building - the ideas below each "
            f"demonstrate it directly.")


def analyze_gaps(profile: dict, jd_text: str,
                 existing: list[dict] | None = None) -> dict:
    """Rank missing JD skills by importance; note what projects already cover.

    Returns {"gaps": [...], "covered_by_projects": [...],
             "profile_skills": [...]}. Each gap has skill, tier
    ("must"/"nice"/"context"), weight, fix ("reframe"/"project"/"course"),
    and pointer.
    """
    prof_skills = _profile_skills(profile)
    jd_weights = _jd_gap_skills(jd_text)
    covered: dict[str, str] = {}
    for p in existing or []:
        for s in p.get("skills", []):
            covered.setdefault(s.strip().lower(), p.get("name", ""))
    gaps = []
    for skill in sorted(jd_weights):
        if skill in prof_skills or skill in covered:
            continue
        weight = jd_weights[skill]
        tier = "must" if weight >= 2.0 else "nice" if weight >= 1.0 else "context"
        fix, pointer = _fix_pointer(skill, prof_skills)
        gaps.append({"skill": skill, "tier": tier, "weight": weight,
                     "fix": fix, "pointer": pointer})
    gaps.sort(key=lambda g: (-g["weight"], g["skill"]))
    jd_skill_set = set(jd_weights)
    covered_hits = sorted({s for s in covered if s in jd_skill_set})
    return {"gaps": gaps,
            "covered_by_projects": [{"skill": s, "project": covered[s]}
                                    for s in covered_hits],
            "profile_skills": sorted(prof_skills)}


# --- idea generation + ranking -----------------------------------------------

def generate_ideas(profile: dict, jd_text: str = "", role: str = "",
                   n: int = 8, existing: list[dict] | None = None) -> list[dict]:
    """Pick project ideas that fill the profile's gaps against the JD.

    Without a JD, ideas are chosen to broaden the profile toward the given
    role family. Skills already demonstrated by ledger projects are excluded
    from matching so you never get told to build what you've built.
    """
    existing = existing if existing is not None else list_projects(silent=True)
    gaps = analyze_gaps(profile, jd_text, existing) if jd_text else None
    missing = {g["skill"] for g in gaps["gaps"]} if gaps else set()
    prof_skills = _profile_skills(profile)
    weights = {g["skill"]: g["weight"] for g in gaps["gaps"]} if gaps else {}

    role = role.strip().lower()
    ideas = []
    for t in _IDEAS:
        if missing:
            matched = sorted(set(t["skills"]) & missing)
            if not matched:
                continue
        else:
            # No JD: suggest ideas that add skills the profile lacks,
            # optionally biased to the requested role family.
            matched = sorted(set(t["skills"]) - prof_skills)
            if not matched:
                continue
            if role and role not in [r.lower() for r in t["roles"]]:
                continue
        gap_value = sum(weights.get(s, 1.0) for s in matched)
        score = round(gap_value * t["appeal"] / t["difficulty"], 2)
        ideas.append({
            "id": t["id"], "title": t["title"], "summary": t["summary"],
            "why": t["why"], "matched_skills": matched,
            "roles": t["roles"], "difficulty": t["difficulty"],
            "appeal": t["appeal"], "weekends": len(t["weekends"]),
            "score": score,
        })
    ideas = rank_ideas(ideas, gaps)
    return ideas[:max(n, 0)]


def rank_ideas(ideas: list[dict], gaps: dict | None = None) -> list[dict]:
    """Order ideas by score desc; attach human-readable reasons."""
    ranked = sorted(ideas, key=lambda i: (-i.get("score", 0),
                                          i.get("weekends", 99), i["id"]))
    for i in ranked:
        reasons = []
        musts = [s for s in i.get("matched_skills", [])]
        if musts:
            reasons.append(f"covers gap skill(s): {', '.join(musts)}")
        if i.get("appeal", 0) >= 4:
            reasons.append("high recruiter signal for its effort")
        if i.get("difficulty", 3) <= 1:
            reasons.append("shippable in a single weekend")
        elif i.get("weekends", 0) >= 3:
            reasons.append("deeper build - strongest portfolio piece of the set")
        i["reasons"] = reasons
    return ranked


# --- weekend scoping ---------------------------------------------------------

def weekend_scope(idea_id: str) -> dict:
    """Break an idea into weekend milestones with done-criteria."""
    t = get_idea(idea_id)
    total = sum(w["hours"] for w in t["weekends"])
    return {"id": t["id"], "title": t["title"],
            "total_hours": total,
            "weekends": [{"n": n + 1, **w}
                         for n, w in enumerate(t["weekends"])]}


# --- tech-stack suggestions --------------------------------------------------

_STACK_OVERRIDES: list[tuple[list[str], str, str, str]] = [
    # (jd keywords, stack component, replacement, note)
    (["typescript"], "language", "TypeScript",
     "JD mentions TypeScript - use it over plain JavaScript"),
    (["react"], "framework", "React",
     "JD mentions React - build the UI in it"),
    (["next.js", "nextjs"], "framework", "Next.js",
     "JD mentions Next.js - use it for the frontend"),
    (["vue"], "framework", "Vue",
     "JD mentions Vue - build the UI in it"),
    (["aws"], "deploy", "AWS (ECS/Lambda + S3)",
     "JD mentions AWS - deploy there, not a generic VM"),
    (["gcp", "google cloud"], "deploy", "GCP (Cloud Run + GCS)",
     "JD mentions GCP - deploy there, not a generic VM"),
    (["azure"], "deploy", "Azure (Container Apps + Blob)",
     "JD mentions Azure - deploy there, not a generic VM"),
    (["kubernetes", "k8s", "eks", "gke"], "deploy", "Kubernetes",
     "JD mentions Kubernetes - containerize and deploy on k8s"),
    (["postgres"], "data", "PostgreSQL",
     "JD mentions Postgres - use it as the datastore"),
    (["mysql"], "data", "MySQL",
     "JD mentions MySQL - use it as the datastore"),
    (["snowflake"], "data", "Snowflake",
     "JD mentions Snowflake - warehouse on it"),
    (["bigquery"], "data", "BigQuery",
     "JD mentions BigQuery - warehouse on it"),
    (["pytorch"], "framework", "PyTorch",
     "JD mentions PyTorch - train in it"),
    (["tensorflow"], "framework", "TensorFlow/Keras",
     "JD mentions TensorFlow - train in it"),
    (["go", "golang"], "language", "Go",
     "JD mentions Go - write the service in it"),
    (["rust"], "language", "Rust",
     "JD mentions Rust - write the performance-critical parts in it"),
]


def suggest_stack(idea_id: str, jd_text: str = "") -> dict:
    """Recommend a stack for the idea, adjusted to JD keywords.

    Returns {"stack": {...}, "overrides": [notes], "why": ...}.
    Overrides replace a stack component only when the JD names a concrete
    alternative; anything else becomes an advisory note.
    """
    t = get_idea(idea_id)
    stack = dict(t["stack"])
    original = dict(t["stack"])
    jd_low = jd_text.lower()
    overrides: list[str] = []

    def _hit(keywords: list[str]) -> bool:
        for kw in keywords:
            if kw[:1].isalnum():
                if re.search(r"\b" + re.escape(kw) + r"\b", jd_low):
                    return True
            elif kw in jd_low:
                return True
        return False

    for keywords, component, replacement, note in _STACK_OVERRIDES:
        if not _hit(keywords):
            continue
        if component in stack and stack[component] != replacement:
            overrides.append(f"{note} (default was: {original[component]})")
            stack[component] = replacement
        elif component not in stack:
            overrides.append(f"{note} - consider adding it to the {component} layer")
    return {"id": t["id"], "title": t["title"], "stack": stack,
            "overrides": overrides,
            "why": ("Defaults are boring-on-purpose (hireable, well-documented). "
                    "Overrides align the repo with the exact words recruiters "
                    "search for in the target JD.")}


# --- effort estimation -------------------------------------------------------

def estimate(idea_id: str, profile: dict, hours_per_weekend: float = 10,
             start: str = "") -> dict:
    """Estimate calendar time: milestone hours discounted by known stack.

    Each stack skill already on the profile discounts total hours by 10%
    (cap 30%): you move faster in tools you know. Weekends are mapped from
    `start` (YYYY-MM-DD, default today), one per 7 days.
    """
    t = get_idea(idea_id)
    if hours_per_weekend <= 0:
        raise ProjectError("hours-per-weekend must be positive")
    prof_skills = _profile_skills(profile)
    known = sorted(set(t["stack_skills"]) & prof_skills)
    raw_total = sum(w["hours"] for w in t["weekends"])
    discount = min(0.30, 0.10 * len(known))
    adjusted = round(raw_total * (1 - discount))
    weekends_needed = max(1, math.ceil(adjusted / hours_per_weekend))
    try:
        start_d = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise ProjectError(f"Bad start date '{start}': use YYYY-MM-DD")
    plan = []
    for n, w in enumerate(t["weekends"]):
        wk = start_d + timedelta(days=7 * n)
        plan.append({"weekend": n + 1, "date": wk.isoformat(),
                     "goal": w["goal"], "hours": w["hours"]})
    end_d = start_d + timedelta(days=7 * (weekends_needed - 1))
    return {"id": t["id"], "title": t["title"],
            "raw_hours": raw_total, "known_stack": known,
            "discount_pct": int(round(discount * 100)),
            "adjusted_hours": adjusted,
            "hours_per_weekend": hours_per_weekend,
            "weekends_needed": weekends_needed,
            "start": start_d.isoformat(), "end": end_d.isoformat(),
            "plan": plan[:weekends_needed] if weekends_needed <= len(plan)
                    else plan + [{"weekend": n + 1,
                                  "date": (start_d + timedelta(days=7 * n)).isoformat(),
                                  "goal": "Buffer / polish / writeup",
                                  "hours": hours_per_weekend}
                                 for n in range(len(plan), weekends_needed)]}


# --- project ledger ------------------------------------------------------------

def _projects_path() -> Path:
    return C.PROJECTS_PATH


def _load_projects() -> list[dict]:
    p = _projects_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ProjectError(f"Could not read project ledger: {e}")
    if not isinstance(data, list):
        raise ProjectError("Project ledger is corrupt (expected a list).")
    return data


def _save_projects(projects: list[dict]) -> None:
    p = _projects_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(projects, indent=2))


STATUSES = ["planned", "in_progress", "done", "archived"]


def add_project(name: str, skills: list[str], status: str = "planned",
                url: str = "", description: str = "") -> dict:
    """Record a side project in the ledger. Names are unique (case-insensitive)."""
    name = name.strip()
    if not name:
        raise ProjectError("Project name is required.")
    if status not in STATUSES:
        raise ProjectError(f"Bad status '{status}'. Choose from: {', '.join(STATUSES)}")
    projects = _load_projects()
    if any(p["name"].lower() == name.lower() for p in projects):
        raise ProjectError(f"Project '{name}' is already in the ledger. "
                           "Use 'project rm' first, or pick another name.")
    rec = {"name": name,
           "skills": sorted({s.strip().lower() for s in skills if s.strip()}),
           "status": status, "url": url.strip(),
           "description": description.strip(),
           "added": date.today().isoformat()}
    projects.append(rec)
    _save_projects(projects)
    return rec


def list_projects(status: str | None = None, silent: bool = False) -> list[dict]:
    """All ledger projects, optionally filtered by status."""
    projects = _load_projects()
    if status:
        if status not in STATUSES:
            raise ProjectError(f"Bad status '{status}'. Choose from: {', '.join(STATUSES)}")
        projects = [p for p in projects if p["status"] == status]
    return projects


def remove_project(name: str) -> dict:
    """Delete a project from the ledger by name."""
    projects = _load_projects()
    for i, p in enumerate(projects):
        if p["name"].lower() == name.strip().lower():
            rec = projects.pop(i)
            _save_projects(projects)
            return rec
    raise ProjectError(f"No project named '{name}' in the ledger.")


def update_project(name: str, status: str | None = None, url: str | None = None,
                   description: str | None = None,
                   skills: list[str] | None = None) -> dict:
    """Update fields of a ledger project (e.g. mark done when you ship)."""
    projects = _load_projects()
    for p in projects:
        if p["name"].lower() == name.strip().lower():
            if status:
                if status not in STATUSES:
                    raise ProjectError(f"Bad status '{status}'. "
                                       f"Choose from: {', '.join(STATUSES)}")
                p["status"] = status
            if url is not None:
                p["url"] = url.strip()
            if description is not None:
                p["description"] = description.strip()
            if skills is not None:
                p["skills"] = sorted({s.strip().lower() for s in skills if s.strip()})
            _save_projects(projects)
            return p
    raise ProjectError(f"No project named '{name}' in the ledger.")


# --- portfolio story builder -------------------------------------------------

def _resolve_ref(ref: str) -> tuple[str, dict, str]:
    """Resolve a story/estimate ref to (kind, data, display_name).

    kind is 'ledger' (user's project) or 'idea' (library template).
    """
    for p in _load_projects():
        if p["name"].lower() == ref.strip().lower():
            return ("ledger", p, p["name"])
    try:
        t = get_idea(ref.strip())
    except ProjectError:
        names = [p["name"] for p in _load_projects()]
        raise ProjectError(
            f"Unknown project or idea '{ref}'. "
            f"Ledger projects: {', '.join(names) or '(none)'}; "
            f"use 'project list' and 'project ideas' to browse.")
    return ("idea", t, t["title"])


def build_story(ref: str) -> dict:
    """Turn a project into STAR resume bullets + talking points + demo checklist.

    `ref` is a ledger project name or an idea id. Bullets are concrete about
    scope and honest about metrics: anything you haven't measured is marked
    [measure this] so you never ship a fabricated number on your resume.
    """
    kind, data, name = _resolve_ref(ref)
    if kind == "ledger":
        title = data["name"]
        summary = data.get("description") or "Side project demonstrating " + \
            ", ".join(data.get("skills", []))
        skills = data.get("skills", [])
        url = data.get("url", "")
        demo = [f"Show the repo live ({url})" if url else "Show the repo live",
                "Walk through the hardest technical decision and the alternative you rejected",
                "Name one thing that broke and how you fixed it"]
        pitfalls = ["Be ready to explain every line you claim - interviewers will ask"]
    else:
        title = data["title"]
        summary = data["summary"]
        skills = data["skills"]
        url = ""
        demo = list(data["demo"])
        pitfalls = list(data["pitfalls"])

    first_skill = skills[0] if skills else "the target stack"
    bullets = [
        f"Designed and shipped {title}: {summary.rstrip('.')} "
        f"[add scale: users, requests, data volume]",
        f"Built with {first_skill}"
        + (f", {skills[1]}" if len(skills) > 1 else "")
        + "; implemented end-to-end from data ingestion to deployed demo "
          "[name the 2-3 hardest components]",
        f"Measured results and wrote them up: [add the one number that proves "
        f"it works - latency, accuracy, cost, uptime]",
    ]
    talking = [
        f"One-minute pitch: the problem {title} solves and who has it",
        f"Architecture: draw the data flow on a whiteboard in 3 minutes",
        f"Tradeoff: one decision where you chose boring technology on purpose, and why",
        f"Failure: something that broke, what you learned, what you'd do differently",
    ]
    return {"name": name, "kind": kind, "title": title,
            "skills": skills, "url": url,
            "resume_bullets": bullets,
            "talking_points": talking,
            "demo_checklist": demo,
            "interview_pitfalls": pitfalls,
            "note": ("Brackets [like this] are yours to fill with real numbers - "
                     "never invent metrics for a resume.")}


# --- learning plan (curated free resources, no scraping) ----------------------

_RESOURCES: dict[str, list[dict]] = {
    "python": [
        {"title": "Official Python tutorial", "url": "https://docs.python.org/3/tutorial/", "kind": "docs"},
        {"title": "Automate the Boring Stuff (free online book)", "url": "https://automatetheboringstuff.com/", "kind": "book"},
    ],
    "sql": [
        {"title": "SQLBolt interactive tutorial", "url": "https://sqlbolt.com/", "kind": "tutorial"},
        {"title": "PGExercises", "url": "https://pgexercises.com/", "kind": "practice"},
    ],
    "llm": [
        {"title": "Hugging Face LLM course (free)", "url": "https://huggingface.co/learn/llm-course", "kind": "course"},
        {"title": "LangChain docs", "url": "https://python.langchain.com/", "kind": "docs"},
    ],
    "nlp": [
        {"title": "Hugging Face NLP course (free)", "url": "https://huggingface.co/learn/nlp-course", "kind": "course"},
        {"title": "spaCy 101", "url": "https://spacy.io/usage/spacy-101", "kind": "docs"},
    ],
    "deep learning": [
        {"title": "fast.ai Practical Deep Learning (free)", "url": "https://www.fast.ai/", "kind": "course"},
        {"title": "PyTorch tutorials", "url": "https://pytorch.org/tutorials/", "kind": "docs"},
    ],
    "machine learning": [
        {"title": "scikit-learn user guide", "url": "https://scikit-learn.org/stable/user_guide.html", "kind": "docs"},
        {"title": "Google Machine Learning Crash Course (free)", "url": "https://developers.google.com/machine-learning/crash-course", "kind": "course"},
    ],
    "scikit-learn": [
        {"title": "scikit-learn user guide", "url": "https://scikit-learn.org/stable/user_guide.html", "kind": "docs"},
    ],
    "xgboost": [
        {"title": "XGBoost Python intro", "url": "https://xgboost.readthedocs.io/en/stable/python/python_intro.html", "kind": "docs"},
    ],
    "statistics": [
        {"title": "OpenIntro Statistics (free textbook)", "url": "https://www.openintro.org/book/os/", "kind": "book"},
        {"title": "StatQuest (free videos)", "url": "https://www.youtube.com/c/joshstarmer", "kind": "video"},
    ],
    "product analytics": [
        {"title": "Lenny's Newsletter: experimentation essays (free tier)", "url": "https://www.lennysnewsletter.com/", "kind": "essays"},
    ],
    "data visualization": [
        {"title": "Storytelling with Data (blog)", "url": "https://www.storytellingwithdata.com/blog", "kind": "essays"},
        {"title": "Plotly Python docs", "url": "https://plotly.com/python/", "kind": "docs"},
    ],
    "mlops": [
        {"title": "Made With ML (free MLOps course)", "url": "https://madewithml.com/", "kind": "course"},
        {"title": "MLflow docs", "url": "https://mlflow.org/docs/latest/", "kind": "docs"},
    ],
    "cloud": [
        {"title": "AWS free-tier docs", "url": "https://aws.amazon.com/free/", "kind": "docs"},
        {"title": "Google Cloud free tier", "url": "https://cloud.google.com/free", "kind": "docs"},
    ],
    "spark": [
        {"title": "Spark quick-start", "url": "https://spark.apache.org/docs/latest/quick-start.html", "kind": "docs"},
    ],
    "dbt": [
        {"title": "dbt Learn: Fundamentals (free)", "url": "https://learn.getdbt.com/", "kind": "course"},
        {"title": "dbt docs", "url": "https://docs.getdbt.com/", "kind": "docs"},
    ],
    "javascript": [
        {"title": "MDN JavaScript guide", "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", "kind": "docs"},
        {"title": "freeCodeCamp JavaScript (free)", "url": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures/", "kind": "course"},
    ],
    "time series": [
        {"title": "Forecasting: Principles and Practice (free book)", "url": "https://otexts.com/fpp3/", "kind": "book"},
    ],
    "recommendations": [
        {"title": "Google Developers: Recommendation systems (free)", "url": "https://developers.google.com/machine-learning/recommendation", "kind": "course"},
    ],
    "optimization": [
        {"title": "PuLP docs + case studies", "url": "https://coin-or.github.io/pulp/", "kind": "docs"},
    ],
}


def learning_plan(idea_id: str) -> list[dict]:
    """Free learning resources for each skill in the idea's stack.

    Returns [{"skill": ..., "resources": [{"title","url","kind"}]}].
    Skills with no curated entry are listed with an empty resource list and
    a pointer to official docs instead of a dead link.
    """
    t = get_idea(idea_id)
    plan = []
    for skill in t["stack_skills"]:
        res = _RESOURCES.get(skill, [])
        plan.append({"skill": skill, "resources": res,
                     "note": "" if res else
                     "No curated link - start from the official docs for this tool."})
    return plan


# --- repo scaffolder -----------------------------------------------------------

_PYTHON_GITIGNORE = """__pycache__/
*.py[cod]
.venv/
venv/
.env
*.egg-info/
.pytest_cache/
"""

_NODE_GITIGNORE = """node_modules/
dist/
.env
*.log
"""

_GENERIC_GITIGNORE = """.env
*.log
.DS_Store
"""


def _scaffold_readme(t: dict, stack: dict) -> str:
    lines = [f"# {t['title']}", "",
             f"> {t['summary']}", "",
             "## Why this project", "", t["why"], "",
             "## Stack", ""]
    for k, v in stack.items():
        lines.append(f"- **{k.capitalize()}**: {v}")
    lines += ["", "## Milestones", ""]
    for n, w in enumerate(t["weekends"], 1):
        lines.append(f"### Weekend {n}: {w['goal']} (~{w['hours']}h)")
        for task in w["tasks"]:
            lines.append(f"- [ ] {task}")
        lines.append(f"- **Done when:** {w['done']}")
        lines.append("")
    lines += ["## Demo script", ""]
    for d in t["demo"]:
        lines.append(f"- {d}")
    lines += ["", "## Watch out", ""]
    for p in t["pitfalls"]:
        lines.append(f"- {p}")
    lines += ["", "## Skills demonstrated", "",
              ", ".join(f"`{s}`" for s in t["skills"]), ""]
    return "\n".join(lines)


def scaffold(idea_id: str, target_dir: str | Path,
             stack: dict | None = None) -> Path:
    """Generate a starter repo for an idea: README, .gitignore, skeleton code.

    Refuses to write into a non-empty directory. Returns the created path.
    """
    t = get_idea(idea_id)
    stack = stack or t["stack"]
    target = Path(target_dir).expanduser()
    if target.exists() and any(target.iterdir()):
        raise ProjectError(f"Refusing to scaffold into non-empty directory: {target}")
    lang = str(stack.get("language", "")).lower()

    target.mkdir(parents=True, exist_ok=True)
    (target / "README.md").write_text(_scaffold_readme(t, stack))

    if "python" in lang:
        (target / ".gitignore").write_text(_PYTHON_GITIGNORE)
        (target / "requirements.txt").write_text(
            "# add deps as you go; pin versions before you call it done\n")
        src = target / "src"
        src.mkdir(exist_ok=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text(
            '"""Entry point. Start here; keep functions small and tested."""\n\n\n'
            'def main() -> None:\n'
            f'    print("TODO: implement {t["id"]}")\n\n\n'
            'if __name__ == "__main__":\n    main()\n')
        tests = target / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_smoke.py").write_text(
            "def test_placeholder():\n"
            "    assert True  # replace with a real test in weekend 1\n")
        (target / "data").mkdir(exist_ok=True)
        (target / "data" / ".gitkeep").write_text("")
    elif "typescript" in lang or "javascript" in lang or "node" in lang:
        (target / ".gitignore").write_text(_NODE_GITIGNORE)
        (target / "package.json").write_text(json.dumps(
            {"name": t["id"], "version": "0.1.0", "private": True,
             "scripts": {"dev": "node src/index.js", "test": "node --test tests/"},
             "type": "module"}, indent=2))
        src = target / "src"
        src.mkdir(exist_ok=True)
        (src / "index.js").write_text(
            f"// Entry point for {t['id']}\nconsole.log('TODO: implement');\n")
        (target / "tests").mkdir(exist_ok=True)
    else:
        (target / ".gitignore").write_text(_GENERIC_GITIGNORE)
        (target / "src").mkdir(exist_ok=True)
        (target / "src" / "README.md").write_text(
            f"# src\n\nImplementation for {t['title']} goes here.\n")
    return target


# --- text rendering (CLI) ------------------------------------------------------

def _bar(score: float, width: int = 20) -> str:
    fill = min(width, max(0, int(round(score / 10 * width))))
    return "#" * fill + "-" * (width - fill)


def render_gaps(analysis: dict) -> str:
    lines = ["Resume gaps vs this JD (project-ideator view)", ""]
    if not analysis["gaps"]:
        lines.append("No gaps found: your profile already covers every JD skill detected,")
        lines.append("or your project ledger covers the rest. Nice.")
    for g in analysis["gaps"]:
        lines.append(f"- {g['skill']} [{g['tier']}] -> {g['fix']}")
        lines.append(f"    {g['pointer']}")
    if analysis["covered_by_projects"]:
        lines.append("")
        lines.append("Already covered by your projects:")
        for c in analysis["covered_by_projects"]:
            lines.append(f"- {c['skill']} (via '{c['project']}')")
    return "\n".join(lines)


def render_ideas(ideas: list[dict]) -> str:
    if not ideas:
        return ("No ideas matched. Try without --jd (broader suggestions), or add "
                "a different target role.")
    lines = [f"{len(ideas)} project idea(s), ranked by gap-fill x appeal / effort", ""]
    for i, idea in enumerate(ideas, 1):
        lines.append(f"{i}. [{idea['id']}] {idea['title']}  "
                     f"(score {idea['score']:.1f} {_bar(idea['score'])})")
        lines.append(f"   {idea['summary']}")
        lines.append(f"   Fills: {', '.join(idea['matched_skills'])} | "
                     f"~{idea['weekends']} weekend(s) | difficulty {idea['difficulty']}/3")
        for r in idea.get("reasons", []):
            lines.append(f"   - {r}")
        lines.append("")
    lines.append("Next: `project scope <id>` for the weekend plan, "
                 "`project stack <id> --jd jd.txt` for the stack.")
    return "\n".join(lines).rstrip()


def render_scope(scope: dict) -> str:
    lines = [f"Weekend plan: {scope['title']} (~{scope['total_hours']}h total)", ""]
    for w in scope["weekends"]:
        lines.append(f"Weekend {w['n']}: {w['goal']} (~{w['hours']}h)")
        for task in w["tasks"]:
            lines.append(f"  - {task}")
        lines.append(f"  Done when: {w['done']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_stack(s: dict) -> str:
    lines = [f"Recommended stack: {s['title']}", ""]
    for k, v in s["stack"].items():
        lines.append(f"  {k.capitalize():<12} {v}")
    if s["overrides"]:
        lines.append("")
        lines.append("JD-driven overrides:")
        for o in s["overrides"]:
            lines.append(f"  * {o}")
    lines.append("")
    lines.append(s["why"])
    return "\n".join(lines)


def render_story(story: dict) -> str:
    lines = [f"Portfolio story: {story['title']}", ""]
    lines.append("Resume bullets (STAR, fill the [brackets] with real numbers):")
    for b in story["resume_bullets"]:
        lines.append(f"  - {b}")
    lines.append("")
    lines.append("Interview talking points:")
    for t in story["talking_points"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("Demo checklist:")
    for d in story["demo_checklist"]:
        lines.append(f"  [ ] {d}")
    lines.append("")
    lines.append("Be ready for:")
    for p in story["interview_pitfalls"]:
        lines.append(f"  - {p}")
    lines.append("")
    lines.append(story["note"])
    return "\n".join(lines)


def render_estimate(e: dict) -> str:
    lines = [f"Estimate: {e['title']}", "",
             f"  Raw effort:      {e['raw_hours']}h"]
    if e["known_stack"]:
        lines.append(f"  Known stack:     {', '.join(e['known_stack'])} "
                     f"(-{e['discount_pct']}%)")
    lines += [f"  Adjusted effort: {e['adjusted_hours']}h",
              f"  Pace:            {e['hours_per_weekend']:g}h/weekend -> "
              f"{e['weekends_needed']} weekend(s)",
              f"  Calendar:        {e['start']} .. {e['end']}", "",
              "Weekend plan:"]
    for w in e["plan"]:
        lines.append(f"  {w['date']}  W{w['weekend']}: {w['goal']} (~{w['hours']}h)")
    return "\n".join(lines)


def render_learn(plan: list[dict], title: str) -> str:
    lines = [f"Learning plan: {title}", ""]
    for item in plan:
        lines.append(f"{item['skill']}:")
        if item["resources"]:
            for r in item["resources"]:
                lines.append(f"  - [{r['kind']}] {r['title']}: {r['url']}")
        else:
            lines.append(f"  - {item['note']}")
    lines.append("")
    lines.append("All resources above are free; work through them alongside "
                 "weekend 1, not before it.")
    return "\n".join(lines)


def render_ledger(projects: list[dict]) -> str:
    if not projects:
        return ("Ledger is empty. Add finished or planned projects with "
                "`project add --name ... --skills ...` so the ideator stops "
                "suggesting skills you've already proven.")
    lines = [f"{len(projects)} project(s) in the ledger", ""]
    for p in projects:
        skills = ", ".join(p.get("skills", [])) or "(no skills listed)"
        url = f"  {p['url']}" if p.get("url") else ""
        lines.append(f"- {p['name']} [{p['status']}]")
        lines.append(f"    skills: {skills}{url}")
        if p.get("description"):
            lines.append(f"    {p['description']}")
    return "\n".join(lines)
