"""Curated role-family prep tracks for interview preparation.

A *prep track* is a self-contained study guide for one role family
(``mle``, ``backend``, ``frontend``, ``data-science``, ``pm``, ``em``).
Each track bundles:

  * ``loop``      — the rounds a typical interview loop for this family has,
                    with per-round time budgets and what each round probes;
  * ``concepts``  — concept deep-dive tags (see ``candid.prep_concepts``),
                    each with a "why this matters for this track" note;
  * ``questions`` — a curated general question bank: every entry has the
                    question text, a category, a difficulty, and the round
                    it belongs to. These are *general preparation* questions,
                    not questions reported at any specific company;
  * ``drills``    — timed practice exercises with instructions and a
                    self-check checklist;
  * ``mock``      — suggested ``python -m candid mock ...`` commands that
                    line up with the track's rounds.

Everything is deterministic and offline. Progress (completed concepts,
questions, drills) persists under ``candid_data/track_progress.json``
(respecting ``CANDID_DATA_DIR``).

Usage:
    python -m candid tracks list
    python -m candid tracks show mle
    python -m candid tracks questions --track backend --difficulty medium
    python -m candid tracks plan --track frontend --days 14
"""

from __future__ import annotations

import json
import os
import random
from datetime import date
from pathlib import Path

from candid import config as C
from candid import prep_concepts as PC

TRACK_IDS = ("mle", "backend", "frontend", "data-science", "pm", "em")

_DIFFICULTIES = ("easy", "medium", "hard")
_ITEM_KINDS = ("concept", "question", "drill")


class TrackError(Exception):
    """Raised for unknown tracks, bad filters, or invalid progress ops."""


def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _progress_file() -> Path:
    return _data_dir() / "track_progress.json"


# ---------------------------------------------------------------------------
# Track registry
# ---------------------------------------------------------------------------

TRACKS: dict[str, dict] = {
    "mle": {
        "title": "Machine Learning Engineer",
        "tagline": "ML systems end to end: modeling, training, serving, and LLMs.",
        "loop": [
            {"round": "ML coding", "minutes": 45,
             "what": "Implement an ML-flavored coding task (e.g. vectorized numpy, data pipeline, loss function)."},
            {"round": "ML system design", "minutes": 45,
             "what": "Design an ML system end to end: data, features, training, serving, monitoring, retraining."},
            {"round": "ML fundamentals", "minutes": 30,
             "what": "Modeling choices, metrics, debugging training, LLM/RAG internals."},
            {"round": "Behavioral", "minutes": 30,
             "what": "Impact, ambiguity, cross-functional collaboration, on-call ownership."},
        ],
        "concepts": [
            {"tag": "ml_system_design", "why": "The centerpiece of the MLE loop - every design round walks this arc."},
            {"tag": "bias_variance", "why": "Interviewers probe whether you can diagnose under/overfitting with the right fix."},
            {"tag": "data_leakage", "why": "Classic failure mode; asked to test whether you validate like a professional."},
            {"tag": "class_imbalance", "why": "Metric choice and sampling strategy come up in nearly every modeling discussion."},
            {"tag": "transformers", "why": "Attention mechanics and scaling are the default LLM-system foundation."},
            {"tag": "llm_eval", "why": "Knowing how to evaluate LLM output separates production MLEs from demo builders."},
            {"tag": "rag_design", "why": "RAG is the most commonly assigned applied-ML design exercise right now."},
            {"tag": "gpu_training", "why": "Distributed training tradeoffs (data vs model parallel) appear in senior loops."},
        ],
        "questions": [
            {"q": "Explain bias-variance tradeoff and how you would diagnose which one a model suffers from.",
             "category": "ml", "difficulty": "medium", "round": "ML fundamentals"},
            {"q": "Your model's offline AUC improved but the online metric did not move. Walk me through your debugging.",
             "category": "ml", "difficulty": "hard", "round": "ML fundamentals"},
            {"q": "Design a fraud-detection ML system from raw events to a production decision.",
             "category": "ml", "difficulty": "hard", "round": "ML system design"},
            {"q": "Design a recommendation system for a feed with 100M daily users.",
             "category": "ml", "difficulty": "hard", "round": "ML system design"},
            {"q": "How does multi-head attention work, and why is it more expressive than a single head?",
             "category": "ml", "difficulty": "medium", "round": "ML fundamentals"},
            {"q": "Compare fine-tuning vs RAG for keeping an LLM current on company docs. When would you pick each?",
             "category": "ml", "difficulty": "medium", "round": "ML system design"},
            {"q": "How would you evaluate a summarization feature built on an LLM before launch?",
             "category": "ml", "difficulty": "medium", "round": "ML fundamentals"},
            {"q": "Implement softmax with numerical stability in numpy, and explain each line.",
             "category": "coding", "difficulty": "easy", "round": "ML coding"},
            {"q": "Write a data loader that yields balanced mini-batches from an imbalanced dataset.",
             "category": "coding", "difficulty": "medium", "round": "ML coding"},
            {"q": "What is data leakage? Give two concrete ways it sneaks into a training pipeline.",
             "category": "ml", "difficulty": "easy", "round": "ML fundamentals"},
            {"q": "How would you set up monitoring and retraining for a model whose input distribution drifts seasonally?",
             "category": "ml", "difficulty": "medium", "round": "ML system design"},
            {"q": "Tell me about a model you shipped that behaved badly in production. What did you change?",
             "category": "behavioral", "difficulty": "medium", "round": "Behavioral"},
        ],
        "drills": [
            {"id": "mle-design-45", "name": "45-minute ML design whiteboard", "minutes": 45,
             "kind": "design",
             "instructions": "Pick one prompt (fraud detection, recommendations, RAG search). Draw the full "
                             "system: data sources, feature pipeline, training, serving, monitoring, rollback. "
                             "Talk out loud for the full 45 minutes.",
             "checklist": ["Data sources and labels named explicitly", "Training/serving skew addressed",
                           "Monitoring metrics and alert thresholds stated", "Rollback/retraining plan included"]},
            {"id": "mle-metrics-20", "name": "Metric-choice lightning round", "minutes": 20,
             "kind": "qna",
             "instructions": "For each: imbalanced classifier, ranking, LLM summary, churn model - name the "
                             "primary metric, one guardrail, and why. 2 minutes per scenario, no pausing.",
             "checklist": ["Primary metric justified per scenario", "Guardrail named for each",
                           "Could explain why accuracy is the wrong choice"]},
            {"id": "mle-numpy-30", "name": "Numpy-from-scratch sprint", "minutes": 30,
             "kind": "coding",
             "instructions": "Implement without ML libraries: softmax, cross-entropy, one gradient-descent step on "
                             "logistic regression. Verify shapes and numerics by hand.",
             "checklist": ["Numerically stable softmax", "Gradient shapes verified",
                           "Loss decreases on a toy dataset"]},
            {"id": "mle-debug-25", "name": "Training-debugging drill", "minutes": 25,
             "kind": "qna",
             "instructions": "Given symptoms (loss NaN, train up/val flat, slow convergence), state the most "
                             "likely cause and the single experiment you would run first. 5 scenarios.",
             "checklist": ["Cause named before fix proposed", "Experiment isolates one variable",
                           "Learning-rate and data checks come first"]},
        ],
        "mock": [
            {"round": "ML system design", "command": "python -m candid mock design --level senior",
             "note": "Use an ML-flavored prompt (recommendations, fraud, RAG) instead of a generic web service."},
            {"round": "ML coding", "command": "python -m candid mock coding --difficulty medium",
             "note": "Pick numpy/pandas-flavored problems; narrate shapes and complexity."},
            {"round": "Behavioral", "command": "python -m candid mock behavioral --theme ownership",
             "note": "Prepare one shipped-model story and one production-incident story in STAR form."},
        ],
    },
    "backend": {
        "title": "Backend / Systems Engineer",
        "tagline": "Distributed systems, APIs, data stores, and the coding bar.",
        "loop": [
            {"round": "Coding", "minutes": 45,
             "what": "Two data-structure/algorithm problems; clean code and complexity analysis."},
            {"round": "System design", "minutes": 45,
             "what": "Design a large-scale backend: API, storage, caching, queues, consistency tradeoffs."},
            {"round": "Systems deep-dive", "minutes": 30,
             "what": "Concurrency, databases, networking - how things work under the hood."},
            {"round": "Behavioral", "minutes": 30,
             "what": "Ownership, incidents, technical disagreements."},
        ],
        "concepts": [
            {"tag": "load_balancing", "why": "Every backend design round starts with 'how do requests get to your servers?'"},
            {"tag": "caching", "why": "Cache strategy and invalidation are the fastest way to show systems judgment."},
            {"tag": "message_queues", "why": "Async processing and backpressure separate junior from senior answers."},
            {"tag": "sql_window", "why": "Analytics-adjacent SQL shows up in backend loops more than people expect."},
            {"tag": "star_schema", "why": "Warehouse modeling questions test whether you can reason about data at rest."},
        ],
        "questions": [
            {"q": "Design a URL shortener serving 100M URLs a day.",
             "category": "system_design", "difficulty": "medium", "round": "System design"},
            {"q": "Design a rate limiter that works across 50 API servers.",
             "category": "system_design", "difficulty": "medium", "round": "System design"},
            {"q": "Design a notification service delivering 1B push notifications a day.",
             "category": "system_design", "difficulty": "hard", "round": "System design"},
            {"q": "What happens when you type a URL and press enter? Go as deep as you can.",
             "category": "systems", "difficulty": "medium", "round": "Systems deep-dive"},
            {"q": "Explain the difference between optimistic and pessimistic locking, with an example where each fits.",
             "category": "systems", "difficulty": "medium", "round": "Systems deep-dive"},
            {"q": "Your p99 latency doubled overnight with no deploy. How do you investigate?",
             "category": "systems", "difficulty": "hard", "round": "Systems deep-dive"},
            {"q": "How would you design idempotency for a payments API?",
             "category": "system_design", "difficulty": "medium", "round": "System design"},
            {"q": "Compare SQL vs NoSQL for a social graph workload. What breaks first at scale?",
             "category": "systems", "difficulty": "medium", "round": "Systems deep-dive"},
            {"q": "Implement an LRU cache with O(1) get and put.",
             "category": "coding", "difficulty": "medium", "round": "Coding"},
            {"q": "Given a stream of events, find the top-k frequent items in one pass with limited memory.",
             "category": "coding", "difficulty": "hard", "round": "Coding"},
            {"q": "Tell me about the worst production incident you owned. What changed afterwards?",
             "category": "behavioral", "difficulty": "medium", "round": "Behavioral"},
            {"q": "Describe a time you disagreed with a teammate on a technical approach.",
             "category": "behavioral", "difficulty": "easy", "round": "Behavioral"},
        ],
        "drills": [
            {"id": "be-design-45", "name": "45-minute system design whiteboard", "minutes": 45,
             "kind": "design",
             "instructions": "Pick rate limiter, URL shortener, or notification service. Drive the full arc: "
                             "requirements, back-of-envelope math, API, data model, scaling, failure modes. Talk continuously.",
             "checklist": ["Back-of-envelope numbers stated up front", "Bottleneck identified and addressed",
                           "Consistency/availability tradeoff named", "Failure mode + mitigation covered"]},
            {"id": "be-coding-45", "name": "Two-problem coding sprint", "minutes": 45,
             "kind": "coding",
             "instructions": "Solve two medium problems (e.g. LRU cache, top-k stream) in 45 minutes total, "
                             "narrating complexity as you go. Use `python -m candid mock coding` for prompts.",
             "checklist": ["Both solutions compile and pass", "Time/space complexity stated",
                           "Edge cases enumerated before coding"]},
            {"id": "be-debug-20", "name": "Latency-debugging lightning round", "minutes": 20,
             "kind": "qna",
             "instructions": "Five scenarios (p99 spike, memory leak, connection-pool exhaustion, cache stampede, "
                             "slow query). For each: first dashboard you open, first hypothesis, first mitigation.",
             "checklist": ["Metrics named before guesses", "Mitigation is reversible",
                           "Root-cause vs symptom distinguished"]},
            {"id": "be-tradeoff-15", "name": "Tradeoff rapid-fire", "minutes": 15,
             "kind": "qna",
             "instructions": "Ten pairs (SQL vs NoSQL, sync vs async, monolith vs microservices, ...). "
                             "For each: one-line verdict for a startup vs a bank, in under 60 seconds.",
             "checklist": ["Context-dependent answer, not dogma", "One concrete failure mode cited",
                           "Stays under the time box"]},
        ],
        "mock": [
            {"round": "System design", "command": "python -m candid mock design",
             "note": "Practice the rate-limiter or URL-shortener prompt; time yourself at 45 minutes."},
            {"round": "Coding", "command": "python -m candid mock coding --difficulty medium",
             "note": "Two problems back to back, narrating tradeoffs out loud."},
            {"round": "Behavioral", "command": "python -m candid mock behavioral --theme incidents",
             "note": "One incident story with the postmortem and what changed."},
        ],
    },
    "frontend": {
        "title": "Frontend Engineer",
        "tagline": "UI architecture, rendering performance, and JavaScript depth.",
        "loop": [
            {"round": "Coding (JS/DOM)", "minutes": 45,
             "what": "JavaScript problems plus a DOM/component build: debounced search, virtualized list, autocomplete."},
            {"round": "Frontend system design", "minutes": 45,
             "what": "Design a client-side system: news feed, collaborative editor, video player UI."},
            {"round": "Web fundamentals", "minutes": 30,
             "what": "Rendering pipeline, performance, accessibility, browser internals."},
            {"round": "Behavioral", "minutes": 30,
             "what": "Cross-functional work with design/product, craft and quality bar."},
        ],
        "concepts": [
            {"tag": "caching", "why": "Browser/HTTP caching and memoization are core frontend performance levers."},
            {"tag": "load_balancing", "why": "CDN and edge delivery shape how frontend assets reach users globally."},
            {"tag": "message_queues", "why": "Event-driven UI updates (websockets, workers) mirror queue thinking."},
        ],
        "questions": [
            {"q": "Build a debounced autocomplete search box. Handle race conditions between requests.",
             "category": "coding", "difficulty": "medium", "round": "Coding (JS/DOM)"},
            {"q": "Implement a virtualized list rendering 100k rows smoothly.",
             "category": "coding", "difficulty": "hard", "round": "Coding (JS/DOM)"},
            {"q": "Design the frontend architecture for a collaborative document editor.",
             "category": "system_design", "difficulty": "hard", "round": "Frontend system design"},
            {"q": "Design a news feed that stays fast on a 3G connection.",
             "category": "system_design", "difficulty": "medium", "round": "Frontend system design"},
            {"q": "Walk through what happens from HTML/CSS/JS to pixels on screen.",
             "category": "web", "difficulty": "medium", "round": "Web fundamentals"},
            {"q": "How does React reconciliation work, and when do keys actually matter?",
             "category": "web", "difficulty": "medium", "round": "Web fundamentals"},
            {"q": "A page's interaction feels janky. How do you diagnose and fix it?",
             "category": "web", "difficulty": "medium", "round": "Web fundamentals"},
            {"q": "Explain event delegation and give a case where it is the wrong choice.",
             "category": "web", "difficulty": "easy", "round": "Web fundamentals"},
            {"q": "How would you make a complex dashboard accessible to screen-reader users?",
             "category": "web", "difficulty": "medium", "round": "Web fundamentals"},
            {"q": "Implement a tiny pub/sub (event emitter) with once() and off().",
             "category": "coding", "difficulty": "easy", "round": "Coding (JS/DOM)"},
            {"q": "Tell me about a time you pushed back on a design to protect performance or accessibility.",
             "category": "behavioral", "difficulty": "medium", "round": "Behavioral"},
            {"q": "How do you keep UI quality high when product wants to ship fast?",
             "category": "behavioral", "difficulty": "easy", "round": "Behavioral"},
        ],
        "drills": [
            {"id": "fe-build-45", "name": "Component build sprint", "minutes": 45,
             "kind": "coding",
             "instructions": "Build one widget from scratch (autocomplete, virtualized list, or tab component): "
                             "working, keyboard-accessible, no UI library. Narrate decisions.",
             "checklist": ["Works without a framework", "Keyboard navigable",
                           "Race conditions / stale state handled", "Edge cases (empty, error, loading) covered"]},
            {"id": "fe-perf-20", "name": "Performance audit drill", "minutes": 20,
             "kind": "qna",
             "instructions": "Given a slow page scenario, list the measurements you take (in order) and the top "
                             "three fixes you expect. Do five scenarios.",
             "checklist": ["Measure before guessing", "Rendering pipeline terms used correctly",
                           "Fixes ranked by expected impact"]},
            {"id": "fe-js-25", "name": "JavaScript internals rapid-fire", "minutes": 25,
             "kind": "qna",
             "instructions": "Explain, each in under 2 minutes: closures, event loop, promises vs async/await, "
                             "prototypes, this-binding, debouncing vs throttling.",
             "checklist": ["No hand-waving on the event loop", "One code example per concept",
                           "Stays inside the time box"]},
            {"id": "fe-design-45", "name": "Frontend design whiteboard", "minutes": 45,
             "kind": "design",
             "instructions": "Design the client architecture for a news feed or collaborative editor: component "
                             "tree, state management, data fetching, offline, performance budget.",
             "checklist": ["State ownership explicit", "Data-fetching strategy named",
                           "Performance budget stated", "Failure/offline states covered"]},
        ],
        "mock": [
            {"round": "Coding (JS/DOM)", "command": "python -m candid mock coding --difficulty medium",
             "note": "Supplement with a hand-built component drill; the judge covers algorithms only."},
            {"round": "Frontend system design", "command": "python -m candid mock design",
             "note": "Steer the prompt to a client-side system (feed, editor, player)."},
            {"round": "Behavioral", "command": "python -m candid mock behavioral --theme craft",
             "note": "Prepare a story about defending quality under schedule pressure."},
        ],
    },
    "data-science": {
        "title": "Data Scientist",
        "tagline": "Experimentation, inference, SQL, and product sense with data.",
        "loop": [
            {"round": "Statistics & experimentation", "minutes": 45,
             "what": "A/B testing, p-values, causal inference, metric design - whiteboard math."},
            {"round": "SQL / data case", "minutes": 45,
             "what": "Live SQL on event tables plus a product case ('metric dropped, why?')."},
            {"round": "ML modeling", "minutes": 30,
             "what": "Modeling choices, leakage, evaluation - lighter than the MLE loop."},
            {"round": "Behavioral", "minutes": 30,
             "what": "Stakeholder influence, communicating uncertainty, business impact."},
        ],
        "concepts": [
            {"tag": "ab_testing", "why": "The single most-tested DS topic; power, peeking, and guardrails."},
            {"tag": "pvalues", "why": "Interviewers check whether you truly understand what a p-value is not."},
            {"tag": "causal_inference", "why": "DiD and quasi-experiments separate senior DS candidates."},
            {"tag": "exp_pitfalls", "why": "Real-world experiment failure modes are favorite follow-ups."},
            {"tag": "guardrails", "why": "Launch decisions are never about one metric."},
            {"tag": "metrics_trees", "why": "Decomposing a metric drop is the canonical DS case."},
            {"tag": "sql_window", "why": "Window functions are the SQL interview workhorse."},
            {"tag": "sql_joins_groupby", "why": "Join/group-by semantics underpin every take-home and live SQL round."},
            {"tag": "xgboost_vs_rf", "why": "Tabular modeling defaults and when to deviate."},
            {"tag": "data_leakage", "why": "Validation hygiene is tested in every modeling conversation."},
            {"tag": "bias_variance", "why": "Diagnosing model error is a modeling-round staple."},
        ],
        "questions": [
            {"q": "Design an A/B test for a new onboarding flow. How long do you run it?",
             "category": "stats", "difficulty": "medium", "round": "Statistics & experimentation"},
            {"q": "What is a p-value, precisely? What does p=0.04 let you claim?",
             "category": "stats", "difficulty": "easy", "round": "Statistics & experimentation"},
            {"q": "You peeked at results daily and shipped at the first significant day. What is wrong?",
             "category": "stats", "difficulty": "medium", "round": "Statistics & experimentation"},
            {"q": "How would you estimate the causal effect of a price change you cannot A/B test?",
             "category": "stats", "difficulty": "hard", "round": "Statistics & experimentation"},
            {"q": "Signup conversion dropped 8% week over week. Walk me through your investigation.",
             "category": "case", "difficulty": "medium", "round": "SQL / data case"},
            {"q": "Write SQL for 7-day rolling retention from a raw events table.",
             "category": "sql", "difficulty": "medium", "round": "SQL / data case"},
            {"q": "Find the second purchase per user and the days between first and second purchase, in SQL.",
             "category": "sql", "difficulty": "hard", "round": "SQL / data case"},
            {"q": "When would you choose a random forest over gradient boosting, and why?",
             "category": "ml", "difficulty": "medium", "round": "ML modeling"},
            {"q": "Your churn model's precision is 90% but the business sees no lift. What happened?",
             "category": "ml", "difficulty": "hard", "round": "ML modeling"},
            {"q": "How do you detect and fix data leakage in a time-series model?",
             "category": "ml", "difficulty": "medium", "round": "ML modeling"},
            {"q": "Tell me about a time your analysis changed a decision. How did you persuade skeptics?",
             "category": "behavioral", "difficulty": "medium", "round": "Behavioral"},
            {"q": "How do you communicate uncertainty in your results to non-technical stakeholders?",
             "category": "behavioral", "difficulty": "easy", "round": "Behavioral"},
        ],
        "drills": [
            {"id": "ds-ab-30", "name": "Experiment design sprint", "minutes": 30,
             "kind": "qna",
             "instructions": "Three scenarios (onboarding, pricing, ranking). For each: metric hierarchy, "
                             "randomization unit, runtime estimate, guardrails, launch rule. 10 minutes each.",
             "checklist": ["Primary metric pre-registered", "Runtime justified with power math",
                           "Guardrails named", "Peeking policy stated"]},
            {"id": "ds-sql-30", "name": "SQL whiteboard set", "minutes": 30,
             "kind": "coding",
             "instructions": "Five queries on a users/events schema: rolling retention, funnel conversion, "
                             "second purchase, sessionization, cohort LTV. Write by hand, no running.",
             "checklist": ["Window functions used where apt", "Edge cases (nulls, dupes) handled",
                           "Query reads correctly on re-read"]},
            {"id": "ds-metric-20", "name": "Metric-drop teardown", "minutes": 20,
             "kind": "qna",
             "instructions": "Pick two 'metric dropped X%' scenarios. Decompose via metrics tree, list the top 5 "
                             "hypotheses ranked by likelihood, and the one query/chart that tests each.",
             "checklist": ["Decomposition before hypotheses", "Hypotheses ranked, not listed",
                           "Each hypothesis has a falsifying check"]},
            {"id": "ds-causal-20", "name": "Causal inference rapid-fire", "minutes": 20,
             "kind": "qna",
             "instructions": "For DiD, regression discontinuity, IV, and propensity matching: the setup, the key "
                             "assumption, and one way the assumption fails. 5 minutes each.",
             "checklist": ["Assumption named precisely", "Failure mode is concrete",
                           "Knows when to prefer a real experiment"]},
        ],
        "mock": [
            {"round": "Statistics & experimentation", "command": "python -m candid mock ai --track stats --difficulty medium",
             "note": "Have the AI interviewer probe power, peeking, and guardrails."},
            {"round": "SQL / data case", "command": "python -m candid mock coding --difficulty medium",
             "note": "Pair with the handwritten SQL drill; the judge covers algorithms only."},
            {"round": "Behavioral", "command": "python -m candid mock behavioral --theme influence",
             "note": "One story where analysis moved a skeptical stakeholder."},
        ],
    },
    "pm": {
        "title": "Product Manager",
        "tagline": "Product sense, metrics, execution, and leadership without authority.",
        "loop": [
            {"round": "Product sense", "minutes": 45,
             "what": "Design or improve a product: users, pain points, solutions, tradeoffs, success metrics."},
            {"round": "Metrics / analytical", "minutes": 45,
             "what": "'Metric moved, why?' plus experiment design and metric hierarchies."},
            {"round": "Execution / behavioral", "minutes": 30,
             "what": "Shipping under constraints, prioritization, conflict, influence."},
            {"round": "Technical fluency", "minutes": 30,
             "what": "How the product is built: APIs, data, ML basics at a PM level of depth."},
        ],
        "concepts": [
            {"tag": "metrics_trees", "why": "Decomposing metrics is the analytical round's core skill."},
            {"tag": "guardrails", "why": "Launch decisions and tradeoff judgment hinge on guardrails."},
            {"tag": "ab_testing", "why": "PMs are expected to design and interpret experiments fluently."},
            {"tag": "exp_pitfalls", "why": "Knowing how experiments fail shows product maturity."},
        ],
        "questions": [
            {"q": "Design a product to help remote teams build trust. Walk through users, problem, solution, metrics.",
             "category": "product", "difficulty": "hard", "round": "Product sense"},
            {"q": "How would you improve the onboarding of a product you use daily?",
             "category": "product", "difficulty": "medium", "round": "Product sense"},
            {"q": "Should a ride-share app add a subscription tier? Structure your answer.",
             "category": "product", "difficulty": "medium", "round": "Product sense"},
            {"q": "Daily active users dropped 5% after a release. What do you do in the first 24 hours?",
             "category": "product", "difficulty": "medium", "round": "Metrics / analytical"},
            {"q": "Design an A/B test for a new feed ranking algorithm. What is the primary metric?",
             "category": "stats", "difficulty": "medium", "round": "Metrics / analytical"},
            {"q": "How do you decide what NOT to build when everything feels urgent?",
             "category": "execution", "difficulty": "medium", "round": "Execution / behavioral"},
            {"q": "Tell me about a product decision you got wrong. What did you learn?",
             "category": "behavioral", "difficulty": "medium", "round": "Execution / behavioral"},
            {"q": "How would you explain how a recommendation system works to a non-technical stakeholder?",
             "category": "technical", "difficulty": "easy", "round": "Technical fluency"},
            {"q": "Your engineers say a feature will take 3x your estimate. How do you handle it?",
             "category": "execution", "difficulty": "medium", "round": "Execution / behavioral"},
            {"q": "Estimate the number of ride-share trips per day in New York City.",
             "category": "estimation", "difficulty": "medium", "round": "Metrics / analytical"},
            {"q": "How do you measure the success of a feature with no direct revenue impact?",
             "category": "product", "difficulty": "medium", "round": "Metrics / analytical"},
            {"q": "Describe a time you aligned disagreeing stakeholders behind one roadmap.",
             "category": "behavioral", "difficulty": "medium", "round": "Execution / behavioral"},
        ],
        "drills": [
            {"id": "pm-sense-45", "name": "Product sense whiteboard", "minutes": 45,
             "kind": "design",
             "instructions": "Pick a prompt (improve X, design Y). Run the full structure: clarify, users, pain "
                             "points, solutions, prioritize, metrics, tradeoffs - out loud, no notes.",
             "checklist": ["Scoped before solving", "Users and pain points explicit",
                           "Solutions compared, not just listed", "Success metric defined"]},
            {"id": "pm-metric-25", "name": "Metric teardown sprint", "minutes": 25,
             "kind": "qna",
             "instructions": "Three 'metric moved' scenarios. Decompose each into a metrics tree, rank hypotheses, "
                             "name the analysis that falsifies each. 8 minutes per scenario.",
             "checklist": ["Tree before theories", "Segmentation ideas included",
                           "Distinguishes correlation from cause"]},
            {"id": "pm-estimate-15", "name": "Estimation rapid-fire", "minutes": 15,
             "kind": "qna",
             "instructions": "Three Fermi estimates. State assumptions first, sanity-check the final number "
                             "against a known anchor, in 5 minutes each.",
             "checklist": ["Assumptions stated up front", "Anchor check at the end",
                           "Math kept simple and round"]},
            {"id": "pm-story-20", "name": "Execution story polish", "minutes": 20,
             "kind": "qna",
             "instructions": "Deliver two STAR stories (a launch, a conflict) in under 3 minutes each, recorded. "
                             "Listen back and cut every sentence that does not add signal.",
             "checklist": ["Under 3 minutes each", "Your actions are the subject",
                           "Ends with the lesson, not just the win"]},
        ],
        "mock": [
            {"round": "Product sense", "command": "python -m candid mock ai --track product --difficulty medium",
             "note": "Ask the AI interviewer to play the product-sense interviewer and push on tradeoffs."},
            {"round": "Metrics / analytical", "command": "python -m candid mock ai --track stats --difficulty medium",
             "note": "Focus on metric decomposition and experiment design."},
            {"round": "Execution / behavioral", "command": "python -m candid mock behavioral --theme leadership",
             "note": "Prioritization and influence-without-authority stories."},
        ],
    },
    "em": {
        "title": "Engineering Manager",
        "tagline": "People leadership, delivery, technical judgment, and org design.",
        "loop": [
            {"round": "People management", "minutes": 45,
             "what": "Hiring, performance, conflict, coaching - all through real stories."},
            {"round": "Execution & delivery", "minutes": 45,
             "what": "Planning, prioritization, incident leadership, cross-team delivery."},
            {"round": "System design (leadership lens)", "minutes": 45,
             "what": "Technical direction: architecture reviews, build-vs-buy, scaling the org's systems."},
            {"round": "Behavioral / values", "minutes": 30,
             "what": "Culture, managing up, handling ambiguity and reorgs."},
        ],
        "concepts": [
            {"tag": "load_balancing", "why": "Enough systems fluency to review designs and ask the right questions."},
            {"tag": "message_queues", "why": "Async architecture judgment for the technical-direction round."},
            {"tag": "caching", "why": "Performance tradeoff literacy for architecture reviews."},
            {"tag": "star_framework", "why": "Every EM answer is a story; STAR keeps them tight."},
        ],
        "questions": [
            {"q": "Tell me about someone you managed who was underperforming. What did you do?",
             "category": "behavioral", "difficulty": "hard", "round": "People management"},
            {"q": "How do you run performance reviews and calibrations fairly?",
             "category": "behavioral", "difficulty": "medium", "round": "People management"},
            {"q": "Describe your hiring bar and a time you made a hard no-hire call.",
             "category": "behavioral", "difficulty": "medium", "round": "People management"},
            {"q": "Two senior engineers disagree on architecture and it is getting personal. What do you do?",
             "category": "behavioral", "difficulty": "hard", "round": "People management"},
            {"q": "How do you coach a strong engineer who wants to become a tech lead?",
             "category": "behavioral", "difficulty": "medium", "round": "People management"},
            {"q": "Walk me through how you plan a quarter for a team of eight.",
             "category": "execution", "difficulty": "medium", "round": "Execution & delivery"},
            {"q": "Your team's top priority slips two weeks before launch. Walk me through your response.",
             "category": "execution", "difficulty": "hard", "round": "Execution & delivery"},
            {"q": "Tell me about a SEV you led. What did the team change afterwards?",
             "category": "execution", "difficulty": "medium", "round": "Execution & delivery"},
            {"q": "Design a notification service - but answer as the EM: what decisions do you own vs delegate?",
             "category": "system_design", "difficulty": "medium", "round": "System design (leadership lens)"},
            {"q": "How do you evaluate build-vs-buy for a core infrastructure component?",
             "category": "system_design", "difficulty": "medium", "round": "System design (leadership lens)"},
            {"q": "How do you manage up when your org's priorities keep shifting?",
             "category": "behavioral", "difficulty": "medium", "round": "Behavioral / values"},
            {"q": "What kind of team culture do you deliberately build, and how?",
             "category": "behavioral", "difficulty": "easy", "round": "Behavioral / values"},
        ],
        "drills": [
            {"id": "em-story-45", "name": "Story bank polish", "minutes": 45,
             "kind": "qna",
             "instructions": "Prepare 8 stories covering: underperformance, conflict, hiring, incident, missed "
                             "deadline, reorg, coaching win, managing up. Deliver each in 3 minutes, recorded.",
             "checklist": ["8 stories banked", "Each under 3 minutes", "Your decisions are explicit",
                           "Ends with what you would repeat or change"]},
            {"id": "em-scenario-30", "name": "Scenario rapid-fire", "minutes": 30,
             "kind": "qna",
             "instructions": "Ten scenarios (engineer wants a raise, two teams blocked on each other, key person "
                             "quitting, ...). First 60 seconds: your read of the situation and first action.",
             "checklist": ["Diagnoses before prescribing", "People-first framing",
                           "Concrete first step, not philosophy"]},
            {"id": "em-plan-30", "name": "Quarter-planning whiteboard", "minutes": 30,
             "kind": "design",
             "instructions": "Plan a quarter for a fictional 8-person team: capacity math, prioritization "
                             "framework, milestones, risks, comms plan. Present in 10 minutes.",
             "checklist": ["Capacity math shown", "Explicit tradeoffs made",
                           "Risks with mitigations", "Stakeholder comms named"]},
            {"id": "em-tech-20", "name": "Technical-direction drill", "minutes": 20,
             "kind": "qna",
             "instructions": "For three architecture proposals: the questions you would ask in review, the "
                             "decision you would own, and what you would delegate to the tech lead.",
             "checklist": ["Review questions are specific", "Own-vs-delegate line is clear",
                           "Business context tied to technical choice"]},
        ],
        "mock": [
            {"round": "People management", "command": "python -m candid mock behavioral --theme management",
             "note": "Underperformance and conflict stories, in STAR form, under 3 minutes each."},
            {"round": "Execution & delivery", "command": "python -m candid mock ai --track execution --difficulty medium",
             "note": "Have the AI interviewer probe planning and incident leadership."},
            {"round": "System design", "command": "python -m candid mock design",
             "note": "Answer with the EM lens: decisions owned, questions asked, delegation."},
        ],
    },
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def list_tracks() -> list[dict]:
    """Summaries of every track: id, title, tagline, counts."""
    return [
        {
            "id": tid,
            "title": t["title"],
            "tagline": t["tagline"],
            "rounds": len(t["loop"]),
            "concepts": len(t["concepts"]),
            "questions": len(t["questions"]),
            "drills": len(t["drills"]),
        }
        for tid, t in TRACKS.items()
    ]


def get_track(track_id: str) -> dict:
    """Full track dict, or raise TrackError for an unknown id."""
    tid = (track_id or "").strip().lower().replace("_", "-")
    if tid not in TRACKS:
        raise TrackError(
            f"Unknown track '{track_id}'. Available: {', '.join(TRACKS)}."
        )
    return TRACKS[tid]


def normalize_track_id(track_id: str) -> str:
    """Canonical track id (accepts 'data_science' as well as 'data-science')."""
    return get_track(track_id) and (track_id or "").strip().lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Questions: filtering + deterministic sampling
# ---------------------------------------------------------------------------

def track_questions(track_id: str, category: str | None = None,
                    difficulty: str | None = None,
                    round_name: str | None = None) -> list[dict]:
    """Questions for a track, optionally filtered by category/difficulty/round."""
    track = get_track(track_id)
    if difficulty and difficulty not in _DIFFICULTIES:
        raise TrackError(
            f"Bad difficulty '{difficulty}'. Choose from: {', '.join(_DIFFICULTIES)}."
        )
    out = []
    for i, q in enumerate(track["questions"]):
        if category and q["category"] != category.lower():
            continue
        if difficulty and q["difficulty"] != difficulty:
            continue
        if round_name and round_name.lower() not in q["round"].lower():
            continue
        out.append({"n": i + 1, **q})
    return out


def sample_questions(track_id: str, n: int = 5, seed: int = 0,
                     difficulty: str | None = None) -> list[dict]:
    """Deterministic sample of n questions (seeded shuffle; same seed, same set)."""
    if n <= 0:
        raise TrackError("n must be a positive integer.")
    pool = track_questions(track_id, difficulty=difficulty)
    if not pool:
        raise TrackError(f"No questions match for track '{track_id}'.")
    rng = random.Random(f"{normalize_track_id(track_id)}:{seed}:{difficulty or 'all'}")
    idx = list(range(len(pool)))
    rng.shuffle(idx)
    return [pool[i] for i in idx[: min(n, len(pool))]]


def question_categories(track_id: str) -> list[str]:
    """Distinct question categories in a track, in first-seen order."""
    seen: list[str] = []
    for q in get_track(track_id)["questions"]:
        if q["category"] not in seen:
            seen.append(q["category"])
    return seen


# ---------------------------------------------------------------------------
# Concepts: resolve deep-dive text from candid.prep_concepts
# ---------------------------------------------------------------------------

def track_concepts(track_id: str) -> list[dict]:
    """Concepts for a track with full deep-dive markdown resolved.

    Every concept tag must exist in ``prep_concepts.CONCEPTS`` (enforced by
    tests); the returned dicts carry ``tag``, ``why`` and ``deep_dive``.
    """
    track = get_track(track_id)
    out = []
    for c in track["concepts"]:
        tag = c["tag"]
        if tag not in PC.CONCEPTS:
            raise TrackError(
                f"Track '{track_id}' references unknown concept tag '{tag}'."
            )
        out.append({"tag": tag, "why": c["why"], "deep_dive": PC.CONCEPTS[tag]})
    return out


# ---------------------------------------------------------------------------
# Drills
# ---------------------------------------------------------------------------

def track_drills(track_id: str, kind: str | None = None) -> list[dict]:
    """Drills for a track, optionally filtered by kind (design/coding/qna)."""
    track = get_track(track_id)
    if kind:
        kinds = {d["kind"] for d in track["drills"]}
        if kind not in kinds:
            raise TrackError(
                f"Bad drill kind '{kind}'. Choose from: {', '.join(sorted(kinds))}."
            )
        return [d for d in track["drills"] if d["kind"] == kind]
    return list(track["drills"])


def get_drill(track_id: str, drill_id: str) -> dict:
    """One drill by id, or raise TrackError."""
    for d in get_track(track_id)["drills"]:
        if d["id"] == drill_id:
            return d
    raise TrackError(
        f"Unknown drill '{drill_id}' for track '{track_id}'. "
        f"Available: {', '.join(d['id'] for d in get_track(track_id)['drills'])}."
    )


def total_drill_minutes(track_id: str) -> int:
    """Sum of drill time budgets for a track."""
    return sum(d["minutes"] for d in get_track(track_id)["drills"])


# ---------------------------------------------------------------------------
# Study plan: spread a track across N days
# ---------------------------------------------------------------------------

def build_plan(track_id: str, days: int = 14, hours_per_day: float = 1.0) -> dict:
    """Spread a track's concepts, questions, and drills across ``days`` days.

    Returns a dict with per-day items (type, ref, minutes) fitting inside the
    daily budget; drills are scheduled whole, concepts/questions fill the rest.
    """
    if days <= 0:
        raise TrackError("days must be a positive integer.")
    if hours_per_day <= 0:
        raise TrackError("hours_per_day must be positive.")
    tid = normalize_track_id(track_id)
    track = get_track(tid)
    budget = hours_per_day * 60

    concepts = [{"type": "concept", "ref": c["tag"], "minutes": 25,
                 "label": f"Deep-dive: {c['tag'].replace('_', ' ')} — {c['why']}"}
                for c in track["concepts"]]
    questions = [{"type": "question", "ref": f"q{i + 1}", "minutes": 10,
                  "label": q["q"][:90] + ("…" if len(q["q"]) > 90 else "")}
                 for i, q in enumerate(track["questions"])]
    drills = [{"type": "drill", "ref": d["id"], "minutes": d["minutes"],
               "label": f"Drill: {d['name']}"}
              for d in track["drills"]]

    # Interleave so each day mixes concepts, questions, and (whole) drills.
    items: list[dict] = []
    for trio in zip(concepts, questions):
        items.extend(trio)
    items.extend(concepts[len(questions):] or [])
    items.extend(questions[len(concepts):] or [])
    drill_queue = list(drills)

    plan_days: list[dict] = [{"day": d + 1, "items": [], "minutes": 0}
                             for d in range(days)]
    # Round-robin whole drills first so each lands on exactly one day.
    di = 0
    for drill in drill_queue:
        if drill["minutes"] > budget:
            raise TrackError(
                f"Drill '{drill['ref']}' needs {drill['minutes']}m but the daily "
                f"budget is {budget:.0f}m. Raise --hours."
            )
        placed = False
        for _ in range(days):
            day = plan_days[di % days]
            if day["minutes"] + drill["minutes"] <= budget:
                day["items"].append(drill)
                day["minutes"] += drill["minutes"]
                placed = True
                break
            di += 1
        if not placed:  # every day full: append to the least-loaded day
            day = min(plan_days, key=lambda d: d["minutes"])
            day["items"].append(drill)
            day["minutes"] += drill["minutes"]
        di += 1
    # Then fill remaining budget with concepts/questions round-robin.
    di = 0
    for item in items:
        for _ in range(days):
            day = plan_days[di % days]
            if day["minutes"] + item["minutes"] <= budget:
                day["items"].append(item)
                day["minutes"] += item["minutes"]
                break
            di += 1
        di += 1

    total = sum(d["minutes"] for d in plan_days)
    return {
        "track": tid,
        "title": track["title"],
        "days": days,
        "hours_per_day": hours_per_day,
        "daily_budget_minutes": budget,
        "total_minutes": total,
        "schedule": plan_days,
    }


def render_plan(plan: dict) -> str:
    """Human-readable rendering of a build_plan() result."""
    lines = [
        f"# {plan['days']}-day prep plan — {plan['title']}",
        f"_{plan['hours_per_day']}h/day · {plan['total_minutes']} minutes total_",
        "",
    ]
    for day in plan["schedule"]:
        lines.append(f"## Day {day['day']} ({day['minutes']} min)")
        lines.append("")
        if not day["items"]:
            lines.append("- Rest / review day.")
        for it in day["items"]:
            lines.append(f"- [{it['type']}] {it['label']} ({it['minutes']}m)")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress tracking (persisted)
# ---------------------------------------------------------------------------

def _load_progress() -> dict:
    f = _progress_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_progress(data: dict) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _progress_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _item_keys(track_id: str) -> dict[str, list[str]]:
    """All completable item keys per kind for a track."""
    track = get_track(track_id)
    return {
        "concept": [c["tag"] for c in track["concepts"]],
        "question": [f"q{i + 1}" for i in range(len(track["questions"]))],
        "drill": [d["id"] for d in track["drills"]],
    }


def mark_done(track_id: str, kind: str, key: str) -> dict:
    """Mark one item done. Returns the updated coverage dict."""
    tid = normalize_track_id(track_id)
    if kind not in _ITEM_KINDS:
        raise TrackError(f"Bad kind '{kind}'. Choose from: {', '.join(_ITEM_KINDS)}.")
    valid = _item_keys(tid)[kind]
    if key not in valid:
        raise TrackError(f"Unknown {kind} '{key}' for track '{tid}'.")
    data = _load_progress()
    entry = data.setdefault(tid, {})
    done = entry.setdefault(kind, [])
    if key not in done:
        done.append(key)
    entry["updated"] = date.today().isoformat()
    _save_progress(data)
    return coverage(tid)


def mark_undone(track_id: str, kind: str, key: str) -> dict:
    """Un-mark one item. Returns the updated coverage dict."""
    tid = normalize_track_id(track_id)
    if kind not in _ITEM_KINDS:
        raise TrackError(f"Bad kind '{kind}'. Choose from: {', '.join(_ITEM_KINDS)}.")
    data = _load_progress()
    entry = data.get(tid, {})
    done = entry.get(kind, [])
    if key in done:
        done.remove(key)
        entry["updated"] = date.today().isoformat()
        _save_progress(data)
    return coverage(tid)


def reset_progress(track_id: str) -> None:
    """Clear all progress for a track."""
    tid = normalize_track_id(track_id)
    data = _load_progress()
    data.pop(tid, None)
    _save_progress(data)


def coverage(track_id: str) -> dict:
    """Per-kind and overall completion for a track."""
    tid = normalize_track_id(track_id)
    keys = _item_keys(tid)
    done_map = _load_progress().get(tid, {})
    per_kind = {}
    total_done = total_all = 0
    for kind in _ITEM_KINDS:
        all_keys = keys[kind]
        done = [k for k in done_map.get(kind, []) if k in all_keys]
        per_kind[kind] = {
            "done": len(done),
            "total": len(all_keys),
            "pct": round(100 * len(done) / len(all_keys)) if all_keys else 0,
            "remaining": [k for k in all_keys if k not in done],
        }
        total_done += len(done)
        total_all += len(all_keys)
    return {
        "track": tid,
        "title": get_track(tid)["title"],
        "kinds": per_kind,
        "done": total_done,
        "total": total_all,
        "pct": round(100 * total_done / total_all) if total_all else 0,
    }


def render_coverage(cov: dict) -> str:
    """Human-readable coverage summary."""
    lines = [f"### {cov['title']} — {cov['done']}/{cov['total']} ({cov['pct']}%)", ""]
    for kind in _ITEM_KINDS:
        k = cov["kinds"][kind]
        bar = "█" * (k["pct"] // 10) + "░" * (10 - k["pct"] // 10)
        lines.append(f"- {kind:>8}: {bar} {k['done']}/{k['total']} ({k['pct']}%)")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mock presets: suggested mock commands per round
# ---------------------------------------------------------------------------

def mock_preset(track_id: str) -> list[dict]:
    """Suggested ``python -m candid mock ...`` commands aligned to the track's loop."""
    return [
        {"round": m["round"], "command": m["command"], "note": m["note"]}
        for m in get_track(track_id)["mock"]
    ]


# ---------------------------------------------------------------------------
# Gap -> track suggestions
# ---------------------------------------------------------------------------

_GAP_TRACK_KEYWORDS: list[tuple[str, str]] = [
    ("machine learning", "mle"), ("deep learning", "mle"), ("llm", "mle"),
    ("model", "mle"), ("pytorch", "mle"), ("tensorflow", "mle"),
    ("distributed", "backend"), ("system design", "backend"),
    ("api", "backend"), ("microservice", "backend"),
    ("react", "frontend"), ("javascript", "frontend"), ("css", "frontend"),
    ("frontend", "frontend"), ("ui", "frontend"),
    ("a/b", "data-science"), ("experiment", "data-science"),
    ("statistic", "data-science"), ("sql", "data-science"),
    ("causal", "data-science"), ("metric", "data-science"),
    ("product sense", "pm"), ("roadmap", "pm"), ("stakeholder", "pm"),
    ("priorit", "pm"),
    ("leadership", "em"), ("manage", "em"), ("team", "em"),
    ("behavioral", "em"),
]


def suggest_tracks(gaps: list[str], top_n: int = 2) -> list[dict]:
    """Suggest prep tracks from match-gap strings (most keyword hits first)."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for gap in gaps or []:
        low = str(gap).lower()
        for keyword, tid in _GAP_TRACK_KEYWORDS:
            if keyword in low:
                if tid not in counts:
                    order.append(tid)
                counts[tid] = counts.get(tid, 0) + 1
                break
    ranked = sorted(order, key=lambda t: -counts[t])
    return [
        {"id": tid, "title": TRACKS[tid]["title"],
         "tagline": TRACKS[tid]["tagline"], "hits": counts[tid]}
        for tid in ranked[:top_n]
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_track(track_id: str, include_deep_dives: bool = False) -> str:
    """Full markdown rendering of a track."""
    tid = normalize_track_id(track_id)
    t = get_track(tid)
    lines = [f"# Prep Track: {t['title']}", f"_{t['tagline']}_", "",
             "## Interview loop", ""]
    for r in t["loop"]:
        lines.append(f"- **{r['round']}** ({r['minutes']} min): {r['what']}")
    lines += ["", "## Concepts", ""]
    for c in track_concepts(tid):
        lines.append(f"- **{c['tag'].replace('_', ' ')}** — {c['why']}")
        if include_deep_dives:
            lines += ["", c["deep_dive"], ""]
    lines += ["", "## Questions", ""]
    cur_round = None
    for i, q in enumerate(t["questions"], 1):
        if q["round"] != cur_round:
            cur_round = q["round"]
            lines += [f"### {cur_round}", ""]
        lines.append(f"{i}. {q['q']} _[{q['category']} · {q['difficulty']}]_")
    lines += ["", "## Drills", ""]
    for d in t["drills"]:
        lines.append(f"### {d['name']} ({d['minutes']} min)")
        lines.append("")
        lines.append(d["instructions"])
        lines.append("")
        lines += ["Checklist:"] + [f"- [ ] {c}" for c in d["checklist"]] + [""]
    lines += ["## Suggested mock sessions", ""]
    for m in mock_preset(tid):
        lines.append(f"- **{m['round']}**: `{m['command']}` — {m['note']}")
    lines += ["", "---",
              "_Progress: `python -m candid tracks progress --track "
              + tid + "`. Mark items done with `tracks done --track "
              + tid + " --kind <concept|question|drill> --key <id>`._"]
    return "\n".join(lines)
