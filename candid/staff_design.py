"""Staff/principal-track drills: system-design-at-scale and tech-strategy memos.

Two drills:

  design  - 12 staff-level system design prompts. Each prompt ships with
             scale twists (what if traffic goes 10x, what if you must be
             multi-region, what if cost is capped) and org constraints
             (team size, timeline, legacy realities). The eval checklist is
             what a strong staff-level answer covers: capacity planning,
             failure modes, cost, and org rollout - not just components.
  memo    - a tech-strategy memo scaffold (context, options + tradeoffs,
             recommendation, risks, rollout, success metrics) plus a
             self-critique checklist. Memos are saved as Markdown under
             DATA_DIR/staff_memos/ (git-ignored user data, never committed).

Usage:
    python -m candid.staff_design design --list
    python -m candid.staff_design design --prompt ads-ranking
    python -m candid.staff_design design --prompt ads-ranking --twists
    python -m candid.staff_design memo --topic "Adopt a feature store"
    python -m candid.staff_design memo --topic "Adopt a feature store" --save feature-store
    python -m candid.staff_design memo --list
    python -m candid.staff_design memo --show feature-store

Everything runs locally. Prompts are original candid practice prompts -
scaffolds and checklists only, never fabricated experience.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from candid import config as C


class StaffError(Exception):
    """Raised for staff-drill usage errors."""


SOURCE_LABEL = "candid practice prompt"


def _memos_dir() -> Path:
    """Memo storage dir, resolved lazily so CANDID_DATA_DIR works in tests.

    config.DATA_DIR is computed at import time; calling _data_dir() here
    reads the env var at call time, which is what tests need.
    """
    return C._data_dir() / "staff_memos"


def _sanitize_memo_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip().lower()).strip("-")
    if not safe:
        raise StaffError("Memo name must contain at least one letter or digit.")
    return safe + ".md"


# ---------------------------------------------------------------------------
# design prompts
# ---------------------------------------------------------------------------

DESIGN_PROMPTS: list[dict] = [
    {
        "id": "ads-ranking",
        "title": "Global ads ranking platform",
        "base_brief": (
            "Design the ranking platform behind a global ads marketplace: "
            "10M candidate-selection and ranking queries per second, 500 "
            "engineers contributing models, strict latency budget of 100ms p99 "
            "end to end."
        ),
        "scale_twists": [
            "Traffic spikes 10x during a global shopping event.",
            "Expand to 3 active regions with per-region model customization.",
            "Infra budget is capped: ranking cost per 1k impressions must fall 40%.",
        ],
        "org_constraints": [
            "One platform team of 8 owns the serving stack; 60 model teams ship independently.",
            "6 months to the holiday traffic peak.",
            "Legacy ranker is a monolithic C++ binary with no per-model isolation.",
        ],
        "eval_checklist": [
            "Capacity planning: QPS x fan-out x model cost per query, with headroom math.",
            "Failure modes: model rollback, cascading timeouts, regional outage, poisoned features.",
            "Cost: compute per 1k impressions, GPU vs CPU tradeoffs, batching strategy.",
            "Org rollout: how 60 teams ship models safely (contracts, canaries, ownership of on-call).",
            "Latency budget decomposition across retrieval, ranking, auction.",
            "Experimentation: interleaved or A/B at ranking layer without breaking auctions.",
        ],
    },
    {
        "id": "feed-ranking-ml",
        "title": "ML platform for feed ranking (training to serving)",
        "base_brief": (
            "Design the end-to-end ML platform that trains and serves the "
            "ranking models for a social feed with 2B daily active users: "
            "feature pipelines, training, and online serving with sub-hour "
            "model freshness."
        ),
        "scale_twists": [
            "Model freshness tightens from hourly to 5 minutes during live events.",
            "Training data grows 10x; GPU budget does not.",
            "One bad feature deploy can corrupt every model - blast radius must be tiny.",
        ],
        "org_constraints": [
            "Platform team of 10, 200 ML engineers as customers.",
            "3 months to migrate off a legacy batch-only feature pipeline.",
            "No dedicated ML-infra budget line: you must justify cost per team.",
        ],
        "eval_checklist": [
            "Capacity planning: training FLOPs, feature-store read/write QPS, serving QPS.",
            "Failure modes: training-serving skew, feature backfill failures, stale models.",
            "Cost: GPU utilization targets, spot vs reserved, feature-store storage tiers.",
            "Org rollout: self-serve onboarding, SLAs to model teams, deprecation policy for the legacy pipeline.",
            "Freshness vs consistency tradeoffs in online feature computation.",
            "Model governance: versioning, reproducibility, rollback story.",
        ],
    },
    {
        "id": "event-streaming",
        "title": "Exactly-once event pipeline at 1T events/day",
        "base_brief": (
            "Design a company-wide event ingestion and processing platform: "
            "1 trillion events/day from mobile, web, and backend services, "
            "with exactly-once semantics for billing-adjacent consumers."
        ),
        "scale_twists": [
            "A top client 10x's their event volume overnight with no warning.",
            "Add a second region with < 60s cross-region replication lag.",
            "Cost per billion events must drop 50% over 18 months.",
        ],
        "org_constraints": [
            "Platform team of 6; 40 product teams produce and consume events.",
            "Legacy: teams write directly to a shared Kafka cluster with no schema governance.",
            "4 months before the legacy cluster's hardware refresh forces a decision.",
        ],
        "eval_checklist": [
            "Capacity planning: bytes/sec in, retention windows, consumer lag budgets.",
            "Failure modes: broker loss, poison messages, schema breakage, consumer backpressure.",
            "Cost: retention tiers (hot/warm/cold), compression, partitioning strategy.",
            "Org rollout: schema registry adoption, per-team quotas, self-serve topic provisioning.",
            "Exactly-once: idempotency vs transactional producers, where the guarantee actually holds.",
            "Multi-tenancy isolation so one team's spike cannot starve the rest.",
        ],
    },
    {
        "id": "payments-ledger",
        "title": "Active-active payments ledger across 3 regions",
        "base_brief": (
            "Design the ledger for a payments product processing $5B/day: "
            "active-active across 3 regions, money must never be created or "
            "destroyed, and settlement must survive a full region loss."
        ),
        "scale_twists": [
            "Regulator requires per-country data residency with 1 year of history.",
            "Flash-sale traffic: 20x normal authorization rate for 2 hours.",
            "A region is partitioned from the other two for 30 minutes.",
        ],
        "org_constraints": [
            "Team of 7, including one staff engineer (you).",
            "Must migrate off a single-region Postgres without downtime.",
            "Audit and compliance review every design change - expect 3-week cycles.",
        ],
        "eval_checklist": [
            "Capacity planning: TPS per region, journal write throughput, reconciliation lag.",
            "Failure modes: split brain, double-spend, lost writes, clock skew.",
            "Cost: cross-region replication traffic, storage for immutable history.",
            "Org rollout: phased migration with shadow traffic, rollback criteria, compliance sign-off gates.",
            "Consistency model choice and exactly where it is relaxed.",
            "Reconciliation and repair: detecting and fixing divergence without human heroics.",
        ],
    },
    {
        "id": "global-search",
        "title": "Global search index over 50B documents",
        "base_brief": (
            "Design search over 50B documents (products, listings, user content) "
            "with < 200ms p99 query latency, near-real-time indexing "
            "(< 60s from write to searchable), and personalized ranking."
        ),
        "scale_twists": [
            "Index doubles to 100B docs; query latency budget does not move.",
            "Personalization models must be A/B tested per query segment.",
            "One region must serve the whole world during a maintenance window.",
        ],
        "org_constraints": [
            "Search team of 9; ranking owned by a separate ML team.",
            "Legacy: a single Lucene cluster that falls over on reindex.",
            "5 months to replace it before the hardware contract renews.",
        ],
        "eval_checklist": [
            "Capacity planning: index size, shard count, query fan-out, indexing throughput.",
            "Failure modes: shard loss, reindex storms, ranking model regression, hot shards.",
            "Cost: storage vs compute tradeoffs, index compression, tiered freshness.",
            "Org rollout: dual-run with the legacy cluster, traffic shadowing, cutover criteria.",
            "Freshness vs query latency vs index size three-way tradeoff.",
            "Ranking integration: feature flow from ML team without tight coupling.",
        ],
    },
    {
        "id": "edge-rate-limiter",
        "title": "Distributed rate limiting at the edge",
        "base_brief": (
            "Design rate limiting for a public API platform: 5M requests/sec "
            "across 200 edge PoPs, per-key and per-tenant limits, enforced "
            "within 5ms at the edge, with a centralized policy service."
        ),
        "scale_twists": [
            "A DDoS multiplies abusive traffic 50x; legitimate traffic must be unaffected.",
            "Policy updates must propagate globally in < 10s.",
            "Tenants demand custom limit hierarchies (org > team > key).",
        ],
        "org_constraints": [
            "Edge team of 6; API platform team of 12 is the customer.",
            "Legacy: per-datacenter token buckets that disagree with each other.",
            "One quarter to ship before the next product launch depends on it.",
        ],
        "eval_checklist": [
            "Capacity planning: state per key, sync bandwidth between PoPs, policy fan-out.",
            "Failure modes: PoP isolation, clock skew, policy service outage, thundering herd on sync.",
            "Cost: edge memory footprint, sync traffic, centralized policy service load.",
            "Org rollout: migration from disagreeing buckets, per-tenant onboarding, self-serve policy UI.",
            "Precision vs coordination cost: local approximation vs global exactness.",
            "Abuse response: detection, automatic tightening, and appeal path.",
        ],
    },
    {
        "id": "notifications",
        "title": "Multi-channel notification platform (5B/day)",
        "base_brief": (
            "Design the platform sending 5B notifications/day across push, SMS, "
            "email, and in-app: per-user preference and quiet-hours handling, "
            "provider failover, and exactly-once delivery semantics per channel."
        ),
        "scale_twists": [
            "A product launch needs 500M pushes in one hour.",
            "SMS provider has a 4-hour outage during peak.",
            "New regulation: marketing messages need explicit per-campaign consent proof.",
        ],
        "org_constraints": [
            "Team of 5 owns the platform; 50 product teams send through it.",
            "Legacy: each team calls providers directly; no central preference store.",
            "2 quarters to consolidate before SMS contract renegotiation.",
        ],
        "eval_checklist": [
            "Capacity planning: sends/sec per channel, provider rate limits, retry storms.",
            "Failure modes: provider outage, duplicate sends, preference-store lag, template errors.",
            "Cost: SMS is 1000x push - routing and throttling policy per channel.",
            "Org rollout: SDK/API adoption across 50 teams, deprecation of direct provider calls.",
            "Preference and consent model: data model, propagation latency, audit trail.",
            "Observability: delivery, open, and complaint metrics per team and campaign.",
        ],
    },
    {
        "id": "lakehouse-migration",
        "title": "Legacy Hadoop to cloud lakehouse migration",
        "base_brief": (
            "Design the migration of a 40PB on-prem Hadoop data platform to a "
            "cloud lakehouse: 3000 daily batch jobs, 400 analysts, and "
            "streaming jobs that cannot tolerate more than 4 hours of downtime "
            "in total."
        ),
        "scale_twists": [
            "Data doubles during the migration because the business will not pause ingestion.",
            "CFO caps cloud spend at 1.2x current on-prem run rate.",
            "A business-critical job has no owner and no documentation.",
        ],
        "org_constraints": [
            "Data platform team of 12; 30 downstream teams depend on the tables.",
            "On-prem hardware contract expires in 9 months - the deadline is real.",
            "Half the team has never operated cloud infrastructure.",
        ],
        "eval_checklist": [
            "Capacity planning: migration throughput (PB/week), dual-run compute, cutover windows.",
            "Failure modes: data divergence between old and new, job failures mid-migration, cost overrun.",
            "Cost: storage tiers, compute autoscaling, egress; staying under the 1.2x cap.",
            "Org rollout: strangler pattern per workload, table-level validation, team training plan.",
            "Downtime budget allocation across the 4-hour total.",
            "Rollback criteria and the point of no return, stated explicitly.",
        ],
    },
    {
        "id": "llm-serving",
        "title": "Cost-constrained LLM serving at 100k concurrent users",
        "base_brief": (
            "Design serving for an LLM-powered product: 100k concurrent users, "
            "p95 time-to-first-token under 1s, and a hard unit-economics target - "
            "gross margin per request must stay positive at current pricing."
        ),
        "scale_twists": [
            "Context windows grow 8x; KV-cache memory becomes the bottleneck.",
            "Overnight batch jobs (evals, distillation) compete for the same GPUs.",
            "A new model version must roll out with zero perceived quality regression.",
        ],
        "org_constraints": [
            "Inference team of 7; model research team ships new checkpoints monthly.",
            "GPU quota is fixed for the next 6 months - no more cards.",
            "Startup runway: the margin target is existential, not aspirational.",
        ],
        "eval_checklist": [
            "Capacity planning: tokens/sec per GPU, KV-cache sizing, concurrency vs batch size.",
            "Failure modes: OOM under long contexts, cascading queue buildup, bad checkpoint rollout.",
            "Cost: $/1k tokens by technique (batching, quantization, speculative decoding, caching).",
            "Org rollout: model release process, quality gates, canary by traffic slice.",
            "Latency vs throughput vs quality three-way tradeoff, quantified.",
            "Fallback story: degraded modes when GPUs saturate (shorter contexts, smaller model).",
        ],
    },
    {
        "id": "data-deletion",
        "title": "User data deletion across 200 services (privacy)",
        "base_brief": (
            "Design the system that honors GDPR/CCPA deletion requests across "
            "200 microservices, 3 data warehouses, and ML training datasets: "
            "verifiable completion within 30 days, with an audit trail "
            "regulators accept."
        ),
        "scale_twists": [
            "Request volume 10x's after a press cycle about data practices.",
            "ML models trained on deleted users' data must be addressed.",
            "Backups with 90-day retention must not resurrect deleted data on restore.",
        ],
        "org_constraints": [
            "Privacy platform team of 4; every service team owns their own deletion logic.",
            "Legacy: no central inventory of where user data lives.",
            "Legal deadline: regulator audit in 6 months.",
        ],
        "eval_checklist": [
            "Capacity planning: deletion requests/day, per-service fan-out, verification scans.",
            "Failure modes: partial deletion, service ignores the request, backup restore resurrection.",
            "Cost: verification compute, crypto-shredding key management, audit storage.",
            "Org rollout: data inventory discovery, per-service contracts and SLAs, compliance reporting.",
            "Deletion semantics: hard delete vs tombstone vs crypto-shredding, per data class.",
            "Verification: how you prove completeness to an auditor, not just to yourself.",
        ],
    },
    {
        "id": "realtime-bidding",
        "title": "Real-time bidding exchange at 100ms p99",
        "base_brief": (
            "Design an ad-exchange bidder handling 8M bid requests/sec from "
            "publishers: respond within 100ms p99, run the auction, enforce "
            "budgets in real time, and log every decision for billing disputes."
        ),
        "scale_twists": [
            "Bidder must expand to a region with 250ms round-trip to the exchange.",
            "An advertiser's budget must never overspend by more than 1%.",
            "Fraud traffic spikes: 30% of bid requests are invalid.",
        ],
        "org_constraints": [
            "Exchange team of 8; bidder teams at 20 DSPs integrate with your API.",
            "Legacy auction logic lives in a single-threaded service.",
            "3 months to the holiday season when volume triples.",
        ],
        "eval_checklist": [
            "Capacity planning: requests/sec x auction compute, budget-check latency, log volume.",
            "Failure modes: exchange timeout, budget overshoot, clock skew in auction ordering.",
            "Cost: compute per million auctions, log storage for dispute windows.",
            "Org rollout: API versioning for 20 DSPs, certification process, gradual traffic ramp.",
            "Latency budget: where each millisecond goes, and what gets cut first under pressure.",
            "Fairness and determinism: tie-breaking, auditability of auction outcomes.",
        ],
    },
    {
        "id": "incident-response",
        "title": "Incident response org design at 500-engineer scale",
        "base_brief": (
            "Design the incident management system for a 500-engineer org "
            "running 150 services: detection, declaration, coordination, "
            "communication, and learning. Target: SEV-1 acknowledgment in 5 "
            "minutes and blameless reviews within 48 hours."
        ),
        "scale_twists": [
            "A cascading failure takes down 40 services at once.",
            "On-call burnout: attrition on the busiest teams doubles.",
            "Regulator requires incident disclosure within 72 hours for the payments service.",
        ],
        "org_constraints": [
            "No dedicated SRE team - you must design roles, not headcount.",
            "Legacy: incidents are handled in a 400-person chat channel.",
            "Leadership will fund exactly one platform investment this year.",
            "12 weeks to show measurable improvement.",
        ],
        "eval_checklist": [
            "Capacity planning: on-call load per engineer, alert volume budgets, review throughput.",
            "Failure modes: coordination collapse in multi-service incidents, alert fatigue, review theater.",
            "Cost: the one platform investment - where it goes and its ROI case.",
            "Org rollout: role definitions (commander, comms, scribe), training, adoption metrics.",
            "Detection: SLO-based alerting vs symptom paging, and who owns the SLOs.",
            "Learning loop: how review action items actually get done and tracked.",
        ],
    },
]


def list_design_prompts() -> list[dict]:
    """Return all staff design prompts (id, title, brief summary)."""
    return [
        {
            "id": p["id"],
            "title": p["title"],
            "brief": p["base_brief"][:120] + "...",
            "source": SOURCE_LABEL,
        }
        for p in DESIGN_PROMPTS
    ]


def get_design_prompt(prompt_id: str) -> dict:
    """Return the full prompt dict for `prompt_id`. Raises StaffError if unknown."""
    for p in DESIGN_PROMPTS:
        if p["id"] == prompt_id:
            return dict(p, source=SOURCE_LABEL)
    known = ", ".join(p["id"] for p in DESIGN_PROMPTS)
    raise StaffError(f"Unknown design prompt '{prompt_id}'. Known: {known}")


def format_design_prompt(p: dict, show_twists: bool = True) -> str:
    """Render a full prompt as drill-ready Markdown text."""
    lines = [
        f"### Staff design drill: {p['title']}",
        "",
        f"*{p.get('source', SOURCE_LABEL)}*",
        "",
        "**Brief**",
        "",
        p["base_brief"],
        "",
    ]
    if show_twists:
        lines += ["**Scale twists** (your interviewer will pick one)", ""]
        lines += [f"{i}. {t}" for i, t in enumerate(p["scale_twists"], 1)]
        lines.append("")
    lines += ["**Org constraints**", ""]
    lines += [f"- {c}" for c in p["org_constraints"]]
    lines += [
        "",
        "**Eval checklist** - a strong staff-level answer covers:",
        "",
    ]
    lines += [f"- [ ] {item}" for item in p["eval_checklist"]]
    lines += [
        "",
        "_Drill tip: talk through the brief for 5 minutes, pick one twist, "
        "then walk the checklist out loud. Time yourself: 45 minutes total._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# tech-strategy memo drill
# ---------------------------------------------------------------------------

MEMO_SECTIONS = [
    "context",
    "options",
    "recommendation",
    "risks",
    "rollout",
    "success_metrics",
]

MEMO_CRITIQUE_CHECKLIST: list[str] = [
    "Does the context state the problem in one paragraph a new hire could understand?",
    "Are at least two real options presented, each with honest tradeoffs (not strawmen)?",
    "Is the recommendation explicit about what is being decided and by when?",
    "Do the risks name who gets hurt and what the mitigation costs?",
    "Is the rollout phased with a rollback or off-ramp at each phase?",
    "Are success metrics measurable within one quarter, with an owner named?",
    "Would a skeptic on another team find their objection addressed?",
    "Is anything in the memo fabricated (numbers, quotes, commitments)? If so, mark it as an assumption.",
]


def render_memo_scaffold(topic: str) -> str:
    """Render a blank tech-strategy memo scaffold for `topic`."""
    topic = (topic or "").strip()
    if not topic:
        raise StaffError("Memo topic must not be empty.")
    today = date.today().isoformat()
    lines = [
        f"# Tech Strategy Memo: {topic}",
        "",
        f"*Draft scaffold - {today}. Fill each section, then run the critique checklist at the end.*",
        "",
        "## 1. Context",
        "",
        "_What problem are we solving, for whom, and why now? One to three paragraphs. "
        "Name the stakeholders and the cost of doing nothing._",
        "",
        "## 2. Options and tradeoffs",
        "",
        "_Present at least two real options. For each: what it is, benefits, costs, "
        "and who pays those costs._",
        "",
        "### Option A: ...",
        "",
        "- What: ...",
        "- Benefits: ...",
        "- Costs / tradeoffs: ...",
        "",
        "### Option B: ...",
        "",
        "- What: ...",
        "- Benefits: ...",
        "- Costs / tradeoffs: ...",
        "",
        "### Option C (status quo): ...",
        "",
        "- What: ...",
        "- Benefits: ...",
        "- Costs / tradeoffs: ...",
        "",
        "## 3. Recommendation",
        "",
        "_State the decision explicitly, with the decision date and the "
        "one or two reasons that carry the most weight._",
        "",
        "## 4. Risks and mitigations",
        "",
        "_For the recommended option: what could go wrong, who is affected, "
        "likelihood x impact, and the mitigation with its owner._",
        "",
        "| Risk | Who is affected | Mitigation | Owner |",
        "| ---- | --------------- | ---------- | ----- |",
        "| ... | ... | ... | ... |",
        "",
        "## 5. Rollout plan",
        "",
        "_Phases with entry/exit criteria. Name the rollback or off-ramp for each phase._",
        "",
        "- Phase 1 (pilot): ... - exit criteria: ... - rollback: ...",
        "- Phase 2 (expand): ... - exit criteria: ... - rollback: ...",
        "- Phase 3 (full): ... - exit criteria: ... - rollback: ...",
        "",
        "## 6. Success metrics",
        "",
        "_Measurable within one quarter. Each metric gets a target and an owner._",
        "",
        "- Metric: ... - target: ... - owner: ...",
        "- Metric: ... - target: ... - owner: ...",
        "",
        "---",
        "",
        "## Critique checklist (self-review before sharing)",
        "",
    ]
    lines += [f"- [ ] {item}" for item in MEMO_CRITIQUE_CHECKLIST]
    lines.append("")
    return "\n".join(lines)


def save_memo(name: str, topic: str, body: str) -> Path:
    """Save a memo as Markdown under DATA_DIR/staff_memos/. Returns the path."""
    if not (body or "").strip():
        raise StaffError("Memo body must not be empty.")
    d = _memos_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / _sanitize_memo_name(name)
    header = f"<!-- topic: {topic.strip()} | saved: {date.today().isoformat()} -->\n\n"
    path.write_text(header + body.rstrip() + "\n", encoding="utf-8")
    return path


def list_memos() -> list[str]:
    """Return saved memo names (without .md), newest first."""
    d = _memos_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [f.stem for f in files]


def get_memo(name: str) -> str:
    """Return the saved memo's Markdown. Raises StaffError if missing."""
    path = _memos_dir() / _sanitize_memo_name(name)
    if not path.exists():
        known = list_memos()
        hint = f" Saved: {', '.join(known)}." if known else " No memos saved yet."
        raise StaffError(f"Unknown memo '{name}'.{hint}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_design(args: argparse.Namespace) -> int:
    if args.list:
        for p in list_design_prompts():
            print(f"{p['id']:22} {p['title']}")
        print(f"\n{len(DESIGN_PROMPTS)} prompts. Show one: staff design --prompt <id>")
        return 0
    if not args.prompt:
        print("Usage: staff design --list | staff design --prompt <id> [--twists]",
              file=sys.stderr)
        return 1
    try:
        p = get_design_prompt(args.prompt)
    except StaffError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(format_design_prompt(p, show_twists=args.twists))
    return 0


def _cmd_memo(args: argparse.Namespace) -> int:
    if args.list:
        names = list_memos()
        if not names:
            print("No memos saved yet. Create one: staff memo --topic \"...\" --save <name>")
        else:
            for n in names:
                print(n)
        return 0
    if args.show:
        try:
            print(get_memo(args.show))
        except StaffError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0
    if not args.topic:
        print("Usage: staff memo --topic \"...\" [--save <name>] | staff memo --list | staff memo --show <name>",
              file=sys.stderr)
        return 1
    try:
        scaffold = render_memo_scaffold(args.topic)
    except StaffError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.save:
        try:
            path = save_memo(args.save, args.topic, scaffold)
        except StaffError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Saved memo '{args.save}' to {path}")
        print("Fill in the sections, then self-review with the critique checklist at the end.")
        return 0
    print(scaffold)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="staff",
                                     description="Staff/principal-track drills: system design at scale, tech-strategy memos.")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("design", help="System-design-at-scale drills.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff design --list\n  python -m candid staff design --prompt ads-ranking --twists")
    d.add_argument("--list", action="store_true", help="List all design prompts.")
    d.add_argument("--prompt", metavar="ID", help="Show a design prompt by id.")
    d.add_argument("--twists", action="store_true",
                   help="Include scale twists when showing a prompt.")
    d.set_defaults(func=_cmd_design)

    m = sub.add_parser("memo", help="Tech-strategy memo drill.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff memo --topic \"Migrate to event-driven billing\"\n  python -m candid staff memo --list")
    m.add_argument("--topic", help="Memo topic; prints the scaffold.")
    m.add_argument("--save", metavar="NAME", help="Save the scaffolded memo under NAME.")
    m.add_argument("--list", action="store_true", help="List saved memos.")
    m.add_argument("--show", metavar="NAME", help="Show a saved memo.")
    m.set_defaults(func=_cmd_memo)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StaffError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
