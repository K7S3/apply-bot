"""Concept deep-dive library for interview prep packs.

Each concept is a self-contained markdown explainer: the idea in 60 seconds,
a worked example, how to answer it in an interview, and follow-ups to expect.
Keyed by concept tag; candid.prep maps question categories to concepts.
"""

from __future__ import annotations

CONCEPTS: dict[str, str] = {
    "ab_testing": """### A/B Testing & Experimentation

**The idea in 60 seconds.** Randomize users into control/treatment, measure the
difference in a primary metric, and only ship if the lift is statistically
significant *and* practically meaningful. The three things interviewers probe:
power (sample size), peeking (don't stop early), and guardrails (don't break
something else while improving one metric).

**Worked example.** New checkout button: 100k users/day, baseline conversion
5%. To detect a +0.3pp lift at 80% power, α=0.05, you need ~140k users per arm
(≈3 days). Pre-register the primary metric, set a fixed runtime, and watch
guardrails (latency, error rate). If you peek daily and stop at the first
significant day, your false-positive rate is far above 5%.

**How to answer.** State the metric hierarchy first (primary / guardrails /
diagnostics), then randomization unit, then runtime math, then the launch
rule. Always mention what you'd do if guardrails trip.

**Follow-ups to expect.** "What if users interfere with each other?"
→ switchback or cluster randomization. "What if the metric is rare?"
→ longer runtime or proxy metrics.""",
    "guardrails": """### Guardrail Metrics & Launch Decisions

**The idea in 60 seconds.** A launch decision is never about one metric. You
need: a primary metric (what you're trying to move), guardrails (what must
not regress — latency, error rate, revenue, fairness), and diagnostics (to
explain *why* something moved).

**Worked example.** A ranking change lifts engagement +2% but increases p99
latency by 400ms. Guardrail breached → no launch, even though the primary
metric is green. The right answer names the tradeoff explicitly and proposes
the next experiment (e.g., a cheaper model variant).

**How to answer.** "I'd define three guardrails up front: ___, ___, ___.
If any regress beyond the pre-set threshold, it's a no-go regardless of the
primary metric — and here's what I'd test next."

**Follow-ups to expect.** "Who sets the thresholds?" → you propose them with
product, based on historical variance and business cost.""",
    "causal_inference": """### Causal Inference Beyond A/B Tests

**The idea in 60 seconds.** When you can't randomize, you borrow causality:
difference-in-differences (compare treated vs control *before and after*),
regression discontinuity (cutoff-based assignment), instrumental variables,
and propensity-score matching. Every method trades an untestable assumption
for an answer.

**Worked example.** Did a price change cause churn? You can't A/B price
easily. DiD: compare churn in the region where price changed vs a similar
region where it didn't, before and after. Key assumption: parallel trends —
both regions would have moved together without the change.

**How to answer.** Name the method, state its identifying assumption in one
sentence, and say how you'd sanity-check it (placebo tests, pre-trend plots).

**Follow-ups to expect.** "When does DiD fail?" → when the parallel-trends
assumption breaks (e.g., a competitor launched in one region).""",
    "sql_window": """### SQL Window Functions for Analytics

**The idea in 60 seconds.** Window functions compute across rows without
collapsing them: `ROW_NUMBER()`, `RANK()`, `LAG()/LEAD()`, and running
aggregates with `OVER (PARTITION BY ... ORDER BY ...)`. They're the core of
sessionization, retention, and time-between-events questions.

**Worked example — sessionize events within 30 minutes:**
```sql
WITH ordered AS (
  SELECT user_id, ts,
         LAG(ts) OVER (PARTITION BY user_id ORDER BY ts) AS prev_ts
  FROM events
),
flagged AS (
  SELECT *, CASE WHEN prev_ts IS NULL
                  OR ts - prev_ts > INTERVAL '30 minutes'
             THEN 1 ELSE 0 END AS new_session
  FROM ordered
)
SELECT user_id, ts,
       SUM(new_session) OVER (PARTITION BY user_id ORDER BY ts) AS session_id
FROM flagged;
```

**How to answer.** Narrate the query top-down: "first I order events per user,
then I flag gaps, then I cumulative-sum the flags into session ids."

**Follow-ups to expect.** "How does this perform on billions of rows?" →
partition pruning, clustering by (user_id, ts), and avoiding the self-join.""",
    "xgboost_vs_rf": """### XGBoost vs Random Forests

**The idea in 60 seconds.** Both are tree ensembles. Random Forests bag
independent deep trees (variance reduction, hard to overfit, few knobs).
XGBoost *boosts* shallow trees sequentially, each correcting the last, with
explicit regularization (L1/L2 on leaf weights, min child weight, gamma).
XGBoost usually wins on tabular data *if* you tune it; RF wins on
"just work" robustness.

**Worked example.** Fraud detection with 50 features, heavy class imbalance:
XGBoost with `scale_pos_weight`, early stopping on a time-split validation
set, and tuned `max_depth`/`lambda` beats RF by several points of PR-AUC —
but only after tuning. An untuned XGBoost often loses to a default RF.

**How to answer.** "I'd start with a tuned RF baseline, then try XGBoost
with early stopping. The regularization knobs (lambda, alpha, gamma) are
what let boosting beat bagging on noisy tabular data."

**Follow-ups to expect.** "When would you NOT use XGBoost?" → tiny data,
need for calibrated probabilities out of the box, or strict latency
budgets (a single shallow tree or linear model can be 100x faster).""",
    "transformers": """### Transformers vs CNNs vs RNNs: Context & Memory

**The idea in 60 seconds.** RNNs process tokens sequentially, carrying a
compressed hidden state — memory fades over long sequences (vanishing
gradients) and nothing parallelizes. CNNs see fixed local windows, stacked
into wider receptive fields — great for local patterns, weak at long-range
dependencies. Transformers attend to *all* positions at once: every token
directly reads every other token (O(n²) attention), so long-range context
is first-class and training parallelizes — at the cost of quadratic memory.

**Worked example.** Document Q&A over 10k tokens: an RNN forgets the
beginning, a CNN never connects paragraph 1 to paragraph 40, a Transformer
answers — but needs ~GBs of KV-cache, which is why we chunk, retrieve
(RAG), or use sparse attention.

**How to answer.** Compare on three axes: how context flows, what
parallelizes, and what it costs. Then tie it to the use case.

**Follow-ups to expect.** "Why is attention O(n²)?" → each of n queries
dots each of n keys. "How do you fix it?" → sliding-window/sparse
attention, KV-cache, or retrieval.""",
    "llm_eval": """### LLM Evaluation & Guardrails

**The idea in 60 seconds.** LLMs fail in ways accuracy doesn't catch:
hallucinations, prompt-injection, inconsistent formatting, and confident
wrongness. Evaluate on three layers: (1) task metrics (exact match / F1 /
human preference on a golden set), (2) behavioral tests (adversarial prompts,
edge cases, PII handling), (3) production monitoring (thumbs-down rate,
escalation rate, latency, cost per query).

**Worked example.** A SQL-generating assistant: golden set of 200
natural-language → SQL pairs with a sandbox DB to *execute* both and compare
results (execution accuracy, not string match). Guardrails: schema-aware
prompting, read-only DB role, result-set size caps, and a "low confidence →
ask a clarifying question" path.

**How to answer.** "I'd build a golden eval set first, measure execution
accuracy rather than BLEU, and add guardrails at the prompt, tool, and
monitoring layers."

**Follow-ups to expect.** "How do you know the eval set is good?" →
coverage of failure modes, refreshed from production failures, human-labeled
disagreements adjudicated.""",
    "rag_design": """### RAG Pipeline Design

**The idea in 60 seconds.** Retrieve-then-generate: chunk documents, embed,
store in a vector index, retrieve top-k for the query, and stuff them into
the prompt. Quality lives in the boring parts: chunking strategy, embedding
choice, hybrid (dense + BM25) retrieval, reranking, and citations.

**Worked example.** Enterprise knowledge assistant over 50k docs: 512-token
chunks with 64-token overlap, hybrid retrieval (vector + BM25), cross-encoder
rerank of top-50 → top-5, prompt with "answer only from the sources; cite
them; say you don't know otherwise." Eval: faithfulness (is every claim
supported?) and answer relevance on a golden set.

**How to answer.** Walk the pipeline stage by stage and name one failure
mode per stage (bad chunks → split answers; weak retrieval → hallucinations;
no citations → untrustworthy).

**Follow-ups to expect.** "How do you keep it fresh?" → incremental
indexing, versioned embeddings, and a feedback loop from thumbs-downs.""",
    "ml_system_design": """### ML System Design: From Notebook to Production

**The idea in 60 seconds.** Interviewers want the *loop*, not the model:
how data gets in, how the model trains, how it serves, and — critically —
how you know it's still working. Hit: feature pipeline (training/serving
consistency), validation strategy (time splits for time data), rollout
(shadow → canary → full), and monitoring (input drift, prediction drift,
business metric).

**Worked example.** Fraud model: features from a streaming pipeline with a
feature store guaranteeing train/serve parity; time-based validation (never
random splits on time data); shadow deployment for two weeks comparing
decisions; dashboards on feature distributions + approval rate; automatic
rollback if drift exceeds threshold.

**How to answer.** Draw the boxes in order and spend most time on the
feedback loops: retraining triggers, rollback, and label delay ("ground
truth arrives weeks later — so I monitor proxies first").

**Follow-ups to expect.** "Offline metrics improved but online didn't move."
→ training/serving skew, label leakage, or the offline metric not matching
the business objective.""",
    "metrics_trees": """### Metrics Trees & Product Sense

**The idea in 60 seconds.** A metrics tree decomposes a north-star metric
into its drivers (e.g., revenue = users × conversion × AOV), so you can
reason about *which* lever a change pulls and what could break. Interviews
test whether you think in systems or in single numbers.

**Worked example.** "Application drop-off is up 5%": decompose into
traffic (fewer qualified applicants?) vs funnel (which step broke?) vs
external (competitor launch, site outage). For each branch, name the data
you'd pull and the fastest check first.

**How to answer.** Draw the tree out loud, prioritize branches by expected
impact × ease of checking, and always name a confounder you'd rule out.

**Follow-ups to expect.** "How do you pick the north star?" → it must be a
leading indicator of long-term value, hard to game, and movable by the team.""",
    "star_schema": """### Star Schema vs Snowflake Schema

**The idea in 60 seconds.** Star: one central fact table, denormalized
dimension tables (one join hop each). Snowflake: dimensions normalized into
sub-dimensions (storage-efficient, more joins). Analytical databases prefer
star because queries are simpler, optimizers handle fewer joins better, and
storage is cheap relative to analyst time.

**Worked example.** E-commerce: `fact_orders` joins directly to
`dim_customer`, `dim_product`, `dim_date`. In a snowflake, `dim_product`
would join to `dim_category` → `dim_department` — three hops for "revenue by
department."

**How to answer.** "Star optimizes for query simplicity and speed; snowflake
optimizes for storage and write-consistency. In analytics, reads dominate,
so star wins."

**Follow-ups to expect.** "When would you snowflake?" → very large,
slowly-changing dimensions where update anomalies matter, or strict storage
constraints.""",
    "pvalues": """### P-values, Multiple Testing & Practical Significance

**The idea in 60 seconds.** A p-value is P(data this extreme | null true) —
*not* P(null is true). With many comparisons, some will look significant by
chance: correct with Bonferroni (conservative), Benjamini-Hochberg (FDR
control), or hierarchical testing. And statistical significance ≠ practical
significance: a +0.01% lift on 100M users is "significant" but worthless.

**Worked example.** Testing 20 email subject lines at α=0.05: expect ~1
false positive. Bonferroni → test each at 0.0025. Better: pre-register one
primary comparison and treat the rest as exploratory.

**How to answer.** Define the p-value correctly (interviewers love this
trap), name the correction, and always ask "but is the effect *big enough
to matter*?"

**Follow-ups to expect.** "Your p-value is 0.06 — ship it?" → no; the
threshold was pre-registered. Discuss power for the next run instead.""",
    "gpu_training": """### GPU-Aware Training: Precision, Memory & Scale

**The idea in 60 seconds.** At scale, the bottleneck is usually memory
bandwidth, not FLOPs. The big levers: mixed precision (FP16 compute, FP32
master weights + loss scaling), gradient accumulation / checkpointing to fit
bigger batches, and distributed strategies (data-parallel with
gradient all-reduce; model-parallel when a model doesn't fit on one GPU).

**Worked example.** Training a 7B model on 8×A100s: bf16 mixed precision,
FSDP sharding, gradient accumulation to reach the target global batch size,
and profiling first — because the bottleneck is often the dataloader, not
the matmuls.

**How to answer.** "I'd profile before optimizing, then attack the actual
bottleneck: precision for memory-bandwidth limits, accumulation for batch
size, and data-parallel with overlap of communication and compute."

**Follow-ups to expect.** "Why loss scaling?" → FP16's narrow range
underflows small gradients; scaling keeps them representable.""",
}

# question category -> concept tags
CATEGORY_CONCEPTS: dict[str, list[str]] = {
    "stats": ["ab_testing", "pvalues", "causal_inference"],
    "case": ["metrics_trees", "ab_testing"],
    "product": ["metrics_trees", "guardrails"],
    "sql": ["sql_window", "star_schema"],
    "python": ["sql_window"],
    "ml": ["xgboost_vs_rf", "transformers", "llm_eval"],
    "system_design": ["ml_system_design", "rag_design", "gpu_training"],
    "behavioral": [],
    "quant": ["pvalues"],
    "process": [],
}

ROLE_FAMILY_CONCEPTS: dict[str, list[str]] = {
    "data_scientist": ["ab_testing", "metrics_trees", "xgboost_vs_rf"],
    "ml_engineer": ["ml_system_design", "llm_eval", "rag_design", "gpu_training"],
    "data_analyst": ["sql_window", "metrics_trees", "ab_testing"],
    "data_engineer": ["sql_window", "star_schema"],
    "quant": ["pvalues", "causal_inference"],
    "software_engineer": ["ml_system_design"],
}

DAY_BEFORE_CHECKLIST = """### Day-Before Checklist

**Logistics**
- [ ] Confirm time, timezone, video link, and interviewer names (LinkedIn-stalk politely)
- [ ] Test camera/mic/screen-share; have a phone hotspot as backup
- [ ] Quiet room, water, notebook; phone on Do Not Disturb

**What to review (90 minutes max — don't cram)**
- [ ] Your 2-minute background pitch out loud, once
- [ ] One STAR story per theme: impact, conflict, failure, leadership
- [ ] The 3 concept deep-dives most related to the reported questions above
- [ ] The company's last 2 product launches or earnings highlights (one talking point each)

**Questions to ask them** (pick 3)
- What does success look like in the first 90 days?
- What's the hardest technical problem the team is working on right now?
- How do modeling decisions get reviewed and shipped here?
- What happened to the last person in this role / why is it open?
- What's something you wish you'd known before joining the team?

**Mindset**
- Interviews are a two-way evaluation — you're choosing them too.
- "I don't know, but here's how I'd figure it out" beats a bluff every time.
- Sleep > one more LeetCode problem.
"""
