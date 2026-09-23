"""System design fundamentals library.

A self-contained study library for system design interviews: topic
overviews, long-form deep-dives, trade-off cards, practice drills with
self-check rubrics, a back-of-envelope estimator, flashcards, a study
planner, and the 45-minute interview checklist.

Everything is local (no network, no model calls). The CLI surface is
``python -m candid sysdesign <subcommand>``; prep packs pull the
deep-dives in automatically when system-design gaps are detected
(see ``topics_for_gaps``).

Conventions follow the rest of the codebase: pure functions, JSON-able
return values, ``SysdesignError`` for bad input, and no em dashes.
"""

from __future__ import annotations

import json
import random


class SysdesignError(Exception):
    """Raised for invalid system-design library operations."""


# ---------------------------------------------------------------------------
# Topic library
# ---------------------------------------------------------------------------
# Each topic: title, overview (what it is and why it matters), patterns
# (named approaches with a one-line summary), numbers (back-of-envelope
# facts worth memorizing), one_liner (the interview-ready summary).

TOPICS: dict[str, dict] = {
    "caching": {
        "title": "Caching",
        "overview": (
            "Caching trades freshness for speed: keep hot or expensive data "
            "close to the reader so repeat requests never touch the slow path. "
            "The three decisions are what to cache (hot, expensive, staleness-"
            "tolerant), where (client, CDN, in-memory store like Redis, DB "
            "query cache), and how to invalidate (the hard part)."
        ),
        "patterns": [
            "Cache-aside (lazy load): app checks cache, falls back to DB, then populates. Simple; first read misses.",
            "Write-through: write to cache and DB together. Reads always hit; writes are slower.",
            "Write-behind: write to cache, flush to DB async. Fast writes; risk of data loss on crash.",
            "TTL expiry: accept bounded staleness and let keys expire. The pragmatic default.",
            "Read-through / refresh-ahead: cache loads itself; refresh hot keys before they expire.",
        ],
        "numbers": [
            "In-memory (Redis/Memcached) reads: sub-millisecond; DB reads: single-digit ms; cross-region: 50-150 ms.",
            "A 90% hit ratio on a 10 ms DB query cuts average read latency to ~1 ms.",
            "Cache stampede: one hot key expiring can 100x backend load; mitigate with jittered TTLs or request coalescing.",
        ],
        "one_liner": "Cache what is hot, expensive, and staleness-tolerant; pick the write pattern by who can afford to lose a write.",
    },
    "queues": {
        "title": "Message Queues & Streaming",
        "overview": (
            "Queues decouple producers from consumers in time: the producer "
            "writes and moves on, the consumer drains at its own pace. They "
            "absorb bursts, smooth load, enable retries, and make async "
            "workflows (notifications, ETL, webhooks) survivable."
        ),
        "patterns": [
            "Point-to-point queue (SQS, RabbitMQ): one consumer group drains each message once (logically).",
            "Pub/sub log (Kafka, Kinesis): append-only partitioned log; many consumer groups replay independently.",
            "Delayed/scheduled delivery: for retries with backoff and scheduled notifications.",
            "Dead-letter queue: poison messages park after N failures instead of blocking the queue forever.",
        ],
        "numbers": [
            "Kafka sustains millions of writes/sec on modest clusters; SQS standard is effectively unbounded but unordered.",
            "At-least-once + idempotent consumers is the industry default; true exactly-once needs transactions (Kafka) or dedupe.",
            "Retention is the superpower of logs: replay last week's events to rebuild a consumer's state.",
        ],
        "one_liner": "Use queues to decouple in time and absorb bursts; default to at-least-once delivery with idempotent consumers.",
    },
    "sharding": {
        "title": "Sharding & Partitioning",
        "overview": (
            "Sharding splits a dataset across machines so no single node must "
            "hold everything. The shard key decides which rows live where, and "
            "that one choice determines your query patterns, hotspot risk, and "
            "how painful rebalancing is."
        ),
        "patterns": [
            "Hash sharding: hash(key) mod N. Even spread; range queries scatter.",
            "Range sharding: contiguous key ranges per shard. Great range scans; hotspots on sequential keys (timestamps).",
            "Consistent hashing: remapping only K/N keys when a node joins/leaves. The standard for caches and Dynamo-style stores.",
            "Virtual nodes: many small partitions per machine smooth out heterogeneity and speed up rebalancing.",
            "Directory/coordinator routing: a lookup service maps keys to shards; flexible, but another component to run.",
        ],
        "numbers": [
            "Adding a node to naive mod-N hashing remaps ~all keys; consistent hashing remaps ~K/N.",
            "A celebrity hotspot (one key = 50% of traffic) defeats any static sharding; fix with key splitting or caching the hot key.",
            "Cross-shard transactions are expensive: design the shard key so the common transaction stays on one shard.",
        ],
        "one_liner": "Pick the shard key from your access pattern, not your schema: co-locate what you query together.",
    },
    "consistency": {
        "title": "Consistency Models",
        "overview": (
            "Consistency answers: after a write, when do readers see it, and "
            "do all readers agree? Strong consistency is simpler to reason "
            "about but costs latency and availability; eventual consistency is "
            "fast and available but pushes conflict resolution to the app."
        ),
        "patterns": [
            "Strong (linearizable): reads see the latest write. Needs consensus (Raft/Paxos); pays cross-replica latency.",
            "Eventual: replicas converge if writes stop. Fast local reads/writes; readers may disagree briefly.",
            "Quorum (R + W > N): tunable middle ground; Dynamo-style. W=N, R=1 favors read speed; W=1, R=N favors write speed.",
            "Read-your-write / monotonic reads: session guarantees that fix the most jarring UX without full linearizability.",
            "CRDTs: data structures that merge deterministically; the clean way to do multi-writer without coordination.",
        ],
        "numbers": [
            "Quorum rule: with N=3, W=2 + R=2 gives strong-ish consistency; W=1 + R=1 is fast and eventually consistent.",
            "Cross-region strong consistency costs a round trip (50-150 ms) per write; many systems keep it single-region.",
            "Last-write-wins is simple but silently drops concurrent writes; vector clocks detect them, CRDTs resolve them.",
        ],
        "one_liner": "Name the consistency each read path needs; pay for strong only where the business logic breaks without it.",
    },
    "load_balancing": {
        "title": "Load Balancing",
        "overview": (
            "Load balancers spread traffic across backends and hide failures: "
            "unhealthy hosts get no traffic, healthy ones share the load. "
            "They sit at L4 (TCP/UDP, fast, dumb) or L7 (HTTP-aware: routing, "
            "TLS termination, retries)."
        ),
        "patterns": [
            "Round-robin / weighted: simple; fine when backends are uniform.",
            "Least-connections: sends to the emptiest backend; better for uneven request costs.",
            "Consistent hashing: same client/key to same backend; gives session affinity without stickiness config.",
            "L7 routing: path/host/header-based routing to different services; the backbone of microservice ingress.",
            "Active health checks: the LB probes backends and drains failures; passive checks watch real traffic errors.",
        ],
        "numbers": [
            "A single LB is a single point of failure: run active/passive or anycast pairs.",
            "Sticky sessions simplify stateful apps but reintroduce hotspots and complicate failover.",
            "L7 adds latency (TLS + parsing) but buys retries, canarying, and request shaping.",
        ],
        "one_liner": "Balance at L4 for speed, L7 for brains; health-check aggressively and never trust a single balancer.",
    },
    "rate_limiting": {
        "title": "Rate Limiting",
        "overview": (
            "Rate limiters protect backends from abuse and overload by capping "
            "how many requests a client can make. The design questions are "
            "where to enforce (edge, gateway, service), what the key is "
            "(IP, user, API key), and what happens on breach (reject, delay, degrade)."
        ),
        "patterns": [
            "Token bucket: tokens refill at a fixed rate; bursts allowed up to bucket size. The most common choice.",
            "Leaky bucket: requests drain at a constant rate; smooths bursts into steady flow.",
            "Fixed window: count per window; simple but allows 2x bursts at boundaries.",
            "Sliding window log/counter: fixes the boundary problem at higher memory cost.",
        ],
        "numbers": [
            "Distributed limiters need shared state (Redis) or accept per-node approximation (usually fine at 10+ nodes).",
            "Return 429 with Retry-After; clients that retry immediately turn a spike into an outage.",
            "Per-user limits stop abuse; per-service limits stop cascading overload (bulkheads).",
        ],
        "one_liner": "Token bucket at the edge for abuse, per-service limits as bulkheads; always answer 429 with Retry-After.",
    },
    "cdn": {
        "title": "CDNs & Edge Caching",
        "overview": (
            "A CDN puts static (and increasingly dynamic) content on servers "
            "near users, cutting latency and origin load. The edge also "
            "terminates TLS, absorbs DDoS, and increasingly runs compute "
            "(edge workers) close to the user."
        ),
        "patterns": [
            "Push vs pull: push uploads to the CDN; pull (origin fetch) lazily caches on first request.",
            "Cache purging/invalidation: versioned URLs (fingerprinted assets) beat purging.",
            "Edge compute: run auth, A/B assignment, or personalization at the edge to skip the origin round trip.",
            "Tiered caching: edge PoPs shield a regional mid-tier, which shields origin; misses rarely reach origin.",
        ],
        "numbers": [
            "Edge RTT is typically 10-50 ms vs 100-200 ms cross-continent to origin.",
            "Static assets with fingerprinted URLs can carry year-long TTLs; HTML gets seconds-to-minutes.",
            "A CDN absorbs L3/L4 DDoS at the edge; origin only sees clean traffic.",
        ],
        "one_liner": "Push bytes to the edge, version assets instead of purging, and let the CDN absorb both latency and attacks.",
    },
    "cap_pacelc": {
        "title": "CAP & PACELC",
        "overview": (
            "CAP: during a network partition, choose consistency or "
            "availability; you cannot have both. PACELC extends it: else "
            "(no partition), choose latency or consistency. Together they "
            "frame every distributed datastore decision."
        ),
        "patterns": [
            "CP systems (etcd, ZooKeeper, HBase): refuse or block rather than serve stale data during partitions.",
            "AP systems (Cassandra, Dynamo): stay writable during partitions; reconcile later.",
            "PACELC trade: single-leader Postgres (low latency reads, consistent) vs multi-leader (available, conflicts).",
            "Design escape hatch: degrade gracefully (read-only mode, cached responses) instead of hard-failing.",
        ],
        "numbers": [
            "Partitions are rare but inevitable; design for them anyway because the failure mode is the interview question.",
            "Most real systems are PACELC: latency vs consistency in the normal case matters more than partition behavior.",
            "Consensus (Raft) needs a majority: a 3-node cluster survives 1 failure; 5 nodes survive 2.",
        ],
        "one_liner": "CAP is for partitions; PACELC is for every day: name what you trade for latency when the network is fine.",
    },
    "db_scaling": {
        "title": "Database Scaling",
        "overview": (
            "Databases scale reads differently from writes. Reads scale with "
            "replicas and caches; writes scale with partitioning (sharding) or "
            "by moving work out (queues, batching). Pick the scaling axis "
            "that matches the workload's read/write ratio."
        ),
        "patterns": [
            "Read replicas: async copies take read traffic; expect replication lag (ms to seconds).",
            "Vertical scaling: bigger box; simplest, hits a ceiling fast.",
            "Sharding: split writes across nodes; the endgame for write-heavy workloads.",
            "CQRS: separate read and write models; great when reads and writes want different shapes.",
            "Caching in front: the cheapest read scaling; invalidation is the tax.",
        ],
        "numbers": [
            "A primary with 3 async replicas roughly 4x read throughput; writes still hit one primary.",
            "Replication lag means read-your-write fails on replicas; route the writer's own reads to the primary briefly.",
            "Connection pools cap DB connections (often ~100-500); the app tier must pool, not open per request.",
        ],
        "one_liner": "Scale reads with replicas and caches, writes with sharding; never let the app tier open unbounded DB connections.",
    },
    "microservices": {
        "title": "Microservices & Decomposition",
        "overview": (
            "Microservices trade one deployable for many: independent "
            "deploys, scaling, and ownership at the cost of distributed "
            "complexity (network calls, versioning, observability). Decompose "
            "by business capability, not by layer."
        ),
        "patterns": [
            "API gateway: single entry, routing, auth, rate limiting; can become a bottleneck if it does too much.",
            "Service discovery: registry (or mesh) so services find each other without hardcoded hosts.",
            "Saga pattern: distributed transactions as local steps + compensating actions; no 2PC across services.",
            "Strangler fig: incrementally replace the monolith behind the same interface.",
        ],
        "numbers": [
            "Each hop adds latency: 3 serial service calls at 20 ms each is 60 ms before business logic.",
            "The network is not reliable: every inter-service call needs timeouts, retries with backoff, and circuit breakers.",
            "Start with a modular monolith; extract services when teams or scaling force it, not before.",
        ],
        "one_liner": "Decompose by business capability, assume every call can fail, and prefer a modular monolith until scale says otherwise.",
    },
}

#: The five deep-dive topics, in the recommended study order.
CORE_TOPICS = ["caching", "queues", "sharding", "consistency", "load_balancing"]


def list_topics() -> list[dict]:
    """All topics as {id, title, one_liner}, in study order (core first)."""
    ordered = CORE_TOPICS + [t for t in TOPICS if t not in CORE_TOPICS]
    return [{"id": t, "title": TOPICS[t]["title"],
             "one_liner": TOPICS[t]["one_liner"]} for t in ordered]


def get_topic(topic: str) -> dict:
    """Full topic record; raises SysdesignError on unknown topic."""
    key = (topic or "").strip().lower().replace("-", "_")
    if key not in TOPICS:
        raise SysdesignError(
            f"Unknown topic '{topic}'. Choose from: {', '.join(sorted(TOPICS))}.")
    return dict(TOPICS[key])


# ---------------------------------------------------------------------------
# Deep-dives: long-form explainers for the five core topics.
# Style matches candid.prep_concepts: the idea in 60 seconds, a worked
# example with real numbers, how to answer it in an interview, and
# follow-ups to expect. These go deeper than the CONCEPTS entries and
# cross-reference the trade-off cards and drills below.
# ---------------------------------------------------------------------------

DEEP_DIVES: dict[str, str] = {
    "caching": """### Caching: Speed vs Freshness (Deep Dive)

**The idea in 60 seconds.** Every cache answers three questions: what to
cache (hot, expensive-to-compute, tolerant of staleness), where (client,
CDN, in-memory store like Redis/Memcached, or the DB query cache), and
how to invalidate. Invalidation is the only hard part; the rest is
plumbing. A cache hit ratio below ~80% usually means you are caching the
wrong things.

**Worked example.** Product page: 50k reads/sec, DB p99 read is 12 ms.
Cache-aside in Redis (p99 0.8 ms) with a 92% hit ratio gives average read
latency = 0.92 * 0.8 + 0.08 * 12 = ~1.7 ms, and cuts DB QPS from 50k to
4k. Price changes must reflect within 60 s, so set TTL 30 s with jitter
(+-10 s) to avoid a stampede when the key expires. On deploy of a pricing
change, publish an invalidation event on the queue; subscribers delete the
key instead of waiting for TTL.

**How to answer.** "I'd cache-aside the product payload in Redis, TTL 30 s
with jitter because prices tolerate a minute of staleness. Hot keys get
request coalescing so a stampede can't 100x the DB. Writes publish
invalidation events. If the interviewer pushes: write-through only if we
needed read-after-write guarantees, which we don't."

**Follow-ups to expect.** "Cache stampede?" -> jittered TTLs, request
coalescing, or a stale-while-revalidate pattern. "Thundering herd on a
cold start?" -> warm the cache from the DB snapshot before cutting
traffic. "How do you size Redis?" -> working set * 1.3 overhead, shard
when a single instance exceeds ~25 GB or ~100k ops/sec.

**Trade-offs to name:** cache-aside vs write-through vs write-behind;
TTL vs explicit invalidation; local vs distributed cache.
**Drill yourself:** `python -m candid sysdesign drill --topic caching`""",
    "queues": """### Message Queues & Streaming (Deep Dive)

**The idea in 60 seconds.** Queues decouple producers from consumers in
time. The producer writes and moves on; the consumer drains at its own
pace. That buys you burst absorption, retries, and replay. The decisions:
delivery semantics (at-most-once, at-least-once, exactly-once), ordering
(partition key), retention (queue vs log), and what happens to poison
messages (dead-letter queue).

**Worked example.** Order notifications: checkout emits `order.placed`,
three consumers (email, SMS, analytics) react. Traffic spikes 10x on
Black Friday. A Kafka topic with 12 partitions absorbs the burst; each
consumer group tracks its own offset, so analytics can reprocess last
week without touching email. Delivery is at-least-once, so every consumer
is idempotent (dedupe on order id). Messages failing 5 times go to the
DLQ with the exception attached; an on-call dashboard pages on DLQ depth
> 100. Email needs ordering per user, so the partition key is user id.

**How to answer.** "I'd put a durable log (Kafka) between checkout and the
notifiers: 12 partitions keyed by user id for per-user ordering,
at-least-once with idempotent consumers, 7-day retention for replays, and
a DLQ after 5 failures with alerting on depth. Backpressure: if email
lags, the log just grows; we autoscale consumers on consumer-lag, not
CPU."

**Follow-ups to expect.** "Exactly-once?" -> Kafka transactions or
idempotent consumers; true exactly-once end-to-end is rare, name the
cost. "Ordering across partitions?" -> you don't get it; if you need
global order you need one partition (and its throughput cap). "Queue vs
log?" -> queues delete on ack (SQS), logs retain and replay (Kafka);
pick logs when consumers need replays.

**Trade-offs to name:** at-least-once + idempotent vs exactly-once;
queue vs log; partition count (parallelism vs rebalance cost).
**Drill yourself:** `python -m candid sysdesign drill --topic queues`""",
    "sharding": """### Sharding & Partitioning (Deep Dive)

**The idea in 60 seconds.** Sharding splits data across machines so no
single node holds everything. The shard key is the whole design: it
decides query patterns (single-shard vs scatter-gather), hotspot risk,
and rebalancing pain. Choose it from the access pattern, not the schema.

**Worked example.** Multi-tenant SaaS, 2 TB of `events` growing 100 GB/mo,
queries are always `WHERE tenant_id = ? AND ts BETWEEN ? AND ?`. Shard by
`tenant_id` (hash): every query hits one shard, no cross-shard joins.
One tenant is 40% of traffic (hotspot): split that tenant's key range
across 4 shards (key splitting) and cache its hot rows. Growth plan:
consistent hashing with virtual nodes (256 vnodes/node) so adding a node
moves ~1/N of data. Rebalancing runs as a background copy with dual-read
verification before cutover; the router is a small lookup service, not
baked into the app.

**How to answer.** "Shard key is tenant_id because every query filters on
it, so reads stay single-shard. Hot tenant gets key splitting plus a
cache tier. Consistent hashing with vnodes keeps rebalances to ~1/N data
movement. Cross-shard transactions are banned by design; the few that
need it go through a saga."

**Follow-ups to expect.** "Range queries?" -> hash sharding scatters them;
use range sharding or a secondary index service if ranges are core. "How
do you rebalance without downtime?" -> background copy, dual reads, then
cutover; or pre-split into many more shards than nodes. "What breaks?" ->
resharding storms, uneven vnodes on heterogeneous hardware, and the
router becoming a single point of failure (replicate it).

**Trade-offs to name:** hash vs range sharding; consistent hashing vs
directory routing; pre-splitting vs dynamic rebalancing.
**Drill yourself:** `python -m candid sysdesign drill --topic sharding`""",
    "consistency": """### Consistency Models (Deep Dive)

**The idea in 60 seconds.** Consistency is the contract between a write
and later reads: when is the write visible, and do all readers agree?
Strong consistency is easy to reason about and expensive (coordination,
latency). Eventual consistency is fast and available but pushes conflict
handling into the app. Most systems are mixed: strong where correctness
demands it, eventual everywhere else.

**Worked example.** Bank ledger vs activity feed. The ledger needs
linearizability: two concurrent transfers must not double-spend. Keep the
ledger in a CP store (single-leader Postgres with Raft, or etcd-backed
sequencer); writes pay a cross-replica round trip (~5 ms in-region, fine).
The activity feed is eventual: a like count converging in 2 s is
invisible to users, so it lives in Cassandra with W=1, R=1. Read-your-write
for the feed author: route their own reads to the primary for 5 s after a
write (or track a session watermark). Conflicts on the feed (two likes at
once) merge with a counter CRDT, no coordination needed.

**How to answer.** "I'd split by correctness needs: the ledger is
linearizable on a consensus-backed store because money can't fork; the
feed is eventual with W=1/R=1 and CRDT counters because staleness is
invisible. Read-your-write for the author's own session papers over the
worst UX. I'd name the quorum math explicitly: N=3, W=2, R=2 where I need
it."

**Follow-ups to expect.** "CAP vs PACELC?" -> CAP is partition behavior;
PACELC adds the everyday latency-vs-consistency trade. "When does
eventual bite?" -> read-after-write UX, unique constraints, and anything
money-adjacent. "How do you detect conflicts?" -> vector clocks or version
vectors; resolve with last-write-wins (simple, lossy) or CRDTs (principled).

**Trade-offs to name:** strong vs eventual per read path; quorum tuning
(W=N/R=1 vs W=1/R=N); LWW vs CRDTs for conflicts.
**Drill yourself:** `python -m candid sysdesign drill --topic consistency`""",
    "load_balancing": """### Load Balancing (Deep Dive)

**The idea in 60 seconds.** Load balancers spread traffic and hide
failure: unhealthy hosts get drained, healthy ones share load. L4
balancers (TCP/UDP) are fast and dumb; L7 (HTTP) understand requests and
can route, terminate TLS, retry, and canary. Every balancer is itself a
single point of failure until you pair it.

**Worked example.** API serving 20k rps across 40 app servers in 2 AZs.
Two L7 balancers (active/active via anycast) terminate TLS, route
`/api/*` to the API pool and `/static/*` to the CDN origin, and retry
idempotent GETs once on 5xx. Algorithm: least-connections, because request
cost varies 10x (cheap reads vs heavy reports). Health checks: HTTP
`/healthz` every 5 s, 2 failures to mark down, 2 successes to rejoin;
plus passive outlier detection ejecting hosts with >50% 5xx over 30 s.
WebSocket connections use consistent hashing on connection id so reconnects
land on warm hosts. Autoscaling keys off p99 latency and LB queue depth,
not CPU.

**How to answer.** "L7 pair, active/active, TLS at the edge, least-
connections because request costs vary, aggressive health checks with
outlier detection, and retries only for idempotent methods. Sticky sessions
are out: the app is stateless, session state lives in Redis, so any host
can serve any user and failover is clean."

**Follow-ups to expect.** "Sticky sessions?" -> avoid; they reintroduce
hotspots and painful failover. Keep state out of the app tier. "L4 vs
L7?" -> L4 for raw throughput (millions of connections), L7 when you need
routing, retries, or header-based canarying. "What if the LB dies?" ->
pairs, anycast, and health-checked DNS failover; the control plane must
not share fate with the data plane.

**Trade-offs to name:** L4 vs L7; round-robin vs least-connections vs
consistent hash; active vs passive health checking.
**Drill yourself:** `python -m candid sysdesign drill --topic load_balancing`""",
}


def deep_dive(topic: str) -> str:
    """Markdown deep-dive for a core topic; raises SysdesignError otherwise."""
    key = (topic or "").strip().lower().replace("-", "_")
    if key not in DEEP_DIVES:
        raise SysdesignError(
            f"No deep-dive for '{topic}'. Available: {', '.join(sorted(DEEP_DIVES))}.")
    return DEEP_DIVES[key]


# ---------------------------------------------------------------------------
# Trade-off cards: the decisions interviewers actually probe.
# Each card: decision, options (name / when to pick / pros / cons), and a
# rule of thumb. Rendered by the CLI and reused by flashcards.
# ---------------------------------------------------------------------------

TRADEOFFS: dict[str, list[dict]] = {
    "caching": [
        {"decision": "How do writes reach the cache?",
         "options": [
             {"name": "Cache-aside (lazy)",
              "when": "Read-heavy, staleness-tolerant data; the default choice.",
              "pros": ["Simple", "only caches what is read", "DB stays source of truth"],
              "cons": ["First read misses", "stale reads until TTL/invalidation"]},
             {"name": "Write-through",
              "when": "You need reads to never miss after a write.",
              "pros": ["Cache always warm", "no stale reads"],
              "cons": ["Every write pays cache + DB latency", "caches data nobody reads"]},
             {"name": "Write-behind",
              "when": "Write throughput dominates and some loss is acceptable.",
              "pros": ["Fastest writes", "absorbs write bursts"],
              "cons": ["Data loss on crash before flush", "complex failure modes"]},
         ],
         "rule": "Default to cache-aside + TTL; reach for write-through only when read-after-write matters."},
        {"decision": "TTL expiry vs explicit invalidation?",
         "options": [
             {"name": "TTL expiry",
              "when": "Bounded staleness is fine (seconds to minutes).",
              "pros": ["No invalidation plumbing", "self-healing"],
              "cons": ["Stale reads within TTL", "stampede risk on mass expiry"]},
             {"name": "Explicit invalidation",
              "when": "Freshness is a correctness requirement (prices, inventory).",
              "pros": ["Immediate consistency on demand"],
              "cons": ["Event plumbing", "missed invalidations = stale forever"]},
         ],
         "rule": "TTL with jitter for everything; add explicit invalidation only for the keys where staleness costs money."},
    ],
    "queues": [
        {"decision": "What delivery semantics?",
         "options": [
             {"name": "At-least-once + idempotent consumers",
              "when": "The default for almost everything.",
              "pros": ["Simple", "no lost messages", "works on every broker"],
              "cons": ["Consumers must dedupe", "duplicates under failure"]},
             {"name": "Exactly-once (transactions)",
              "when": "Duplicates are unacceptable and worth the cost (billing).",
              "pros": ["No duplicates end to end"],
              "cons": ["Broker-specific", "throughput cost", "complex ops"]},
             {"name": "At-most-once",
              "when": "Loss is cheaper than duplication (metrics, heartbeats).",
              "pros": ["Fastest", "simplest consumer"],
              "cons": ["Messages can silently drop"]},
         ],
         "rule": "At-least-once with idempotent consumers unless someone can show the duplicate cost exceeds the exactly-once cost."},
        {"decision": "Queue (SQS-style) vs log (Kafka-style)?",
         "options": [
             {"name": "Queue",
              "when": "Fire-and-forget tasks; one consumer group.",
              "pros": ["Simple semantics", "auto-deletes on ack", "scales to zero"],
              "cons": ["No replay", "one logical consumer"]},
             {"name": "Log",
              "when": "Multiple consumers, replays, or event sourcing.",
              "pros": ["Replayable", "many consumer groups", "ordering per partition"],
              "cons": ["Retention to manage", "partition count is a capacity decision"]},
         ],
         "rule": "Need replays or fan-out? Log. Otherwise a queue is less to operate."},
    ],
    "sharding": [
        {"decision": "Hash vs range sharding?",
         "options": [
             {"name": "Hash sharding",
              "when": "Point lookups dominate; even spread matters most.",
              "pros": ["Uniform distribution", "no hotspots from key order"],
              "cons": ["Range queries scatter to all shards"]},
             {"name": "Range sharding",
              "when": "Range scans are the core access pattern.",
              "pros": ["Efficient range queries", "natural locality"],
              "cons": ["Hotspots on sequential keys (timestamps)", "uneven shard sizes"]},
         ],
         "rule": "Match the sharding to the dominant query shape; hash by default, range only when scans pay the bills."},
        {"decision": "How to route keys to shards?",
         "options": [
             {"name": "Consistent hashing",
              "when": "Nodes churn and you want minimal remapping.",
              "pros": ["~K/N keys move on membership change", "no central state"],
              "cons": ["Uneven without vnodes", "harder range queries"]},
             {"name": "Directory / lookup service",
              "when": "You need flexible placement (tenant isolation, tiering).",
              "pros": ["Arbitrary placement", "easy targeted moves"],
              "cons": ["Another stateful component", "lookup latency"]},
         ],
         "rule": "Consistent hashing with vnodes for caches and KV; a directory when placement policy is business-driven."},
    ],
    "consistency": [
        {"decision": "Strong vs eventual per read path?",
         "options": [
             {"name": "Strong (linearizable)",
              "when": "Correctness breaks on staleness: money, inventory, auth.",
              "pros": ["Simple reasoning", "no anomalies"],
              "cons": ["Coordination latency", "unavailable during partitions (CP)"]},
             {"name": "Eventual",
              "when": "Staleness is invisible: feeds, counts, recommendations.",
              "pros": ["Low latency", "highly available"],
              "cons": ["Readers disagree briefly", "app handles conflicts"]},
         ],
         "rule": "Pay for strong only where the business logic breaks without it; default everything else to eventual."},
        {"decision": "How to handle concurrent writes?",
         "options": [
             {"name": "Last-write-wins",
              "when": "Conflicts are rare and loss is tolerable.",
              "pros": ["Trivial"],
              "cons": ["Silently drops concurrent writes"]},
             {"name": "CRDTs",
              "when": "Multi-writer without coordination (counters, sets, text).",
              "pros": ["Principled merge", "no coordination"],
              "cons": ["Limited data types", "state growth"]},
             {"name": "Single writer / serialization",
              "when": "You can route all writes for a key through one owner.",
              "pros": ["No conflicts at all"],
              "cons": ["The owner is a bottleneck and SPOF"]},
         ],
         "rule": "Serialize when you can, CRDTs when you cannot, LWW only when loss is genuinely fine."},
    ],
    "load_balancing": [
        {"decision": "L4 vs L7 balancing?",
         "options": [
             {"name": "L4 (TCP/UDP)",
              "when": "Raw throughput; millions of connections.",
              "pros": ["Fast", "cheap", "protocol-agnostic"],
              "cons": ["No request awareness", "no retries/routing"]},
             {"name": "L7 (HTTP)",
              "when": "You need routing, TLS termination, retries, canarying.",
              "pros": ["Smart routing", "retries", "observability per route"],
              "cons": ["More latency", "more CPU", "must parse traffic"]},
         ],
         "rule": "L4 for speed, L7 for brains; most internet-facing setups end up L7 at the edge."},
        {"decision": "Which balancing algorithm?",
         "options": [
             {"name": "Round-robin / weighted",
              "when": "Backends are uniform and requests cost the same.",
              "pros": ["Simple", "predictable"],
              "cons": ["Ignores actual load", "bad with uneven costs"]},
             {"name": "Least-connections",
              "when": "Request costs vary (mixed API).",
              "pros": ["Adapts to real load"],
              "cons": ["Slightly more state"]},
             {"name": "Consistent hashing",
              "when": "Affinity matters (warm caches, connections).",
              "pros": ["Stable mapping", "minimal reshuffle"],
              "cons": ["Can hotspot on skewed keys"]},
         ],
         "rule": "Round-robin until request costs vary, then least-connections; hashing only when affinity buys something."},
    ],
    "rate_limiting": [
        {"decision": "Which limiter algorithm?",
         "options": [
             {"name": "Token bucket",
              "when": "The default: allow bursts, cap sustained rate.",
              "pros": ["Bursty-friendly", "well understood"],
              "cons": ["Two knobs to tune (rate, burst)"]},
             {"name": "Sliding window",
              "when": "You must not exceed the cap in any window (billing).",
              "pros": ["No boundary bursts", "precise"],
              "cons": ["More memory", "heavier at scale"]},
         ],
         "rule": "Token bucket at the edge; sliding window where the cap is contractual."},
        {"decision": "Where to enforce?",
         "options": [
             {"name": "Edge / gateway",
              "when": "Abuse prevention, DDoS absorption.",
              "pros": ["Stops bad traffic early", "central policy"],
              "cons": ["Coarse keys (IP)", "shared fate"]},
             {"name": "Per service (bulkhead)",
              "when": "Protecting a specific backend from overload.",
              "pros": ["Fine-grained", "isolates failures"],
              "cons": ["More limiters to operate"]},
         ],
         "rule": "Both: edge limits stop attackers, per-service limits stop cascading overload."},
    ],
    "cdn": [
        {"decision": "Push vs pull (origin fetch)?",
         "options": [
             {"name": "Pull",
              "when": "Large catalog, unpredictable popularity.",
              "pros": ["No pre-upload", "origin stays source of truth"],
              "cons": ["First request misses", "origin must handle fill"]},
             {"name": "Push",
              "when": "Known hot assets (releases, viral content).",
              "pros": ["No cold misses", "predictable"],
              "cons": ["Upload plumbing", "stale copies if you forget"]},
         ],
         "rule": "Pull by default; push the assets you know will be hot."},
        {"decision": "How to handle updates to cached assets?",
         "options": [
             {"name": "Versioned URLs (fingerprints)",
              "when": "Static assets: JS, CSS, images.",
              "pros": ["Year-long TTLs", "no purge needed", "atomic deploys"],
              "cons": ["Build plumbing"]},
             {"name": "Purge / short TTL",
              "when": "HTML and API responses that change.",
              "pros": ["Simple"],
              "cons": ["Purge is eventually consistent", "short TTLs hit origin"]},
         ],
         "rule": "Fingerprint immutable assets; short TTLs for HTML; purge as the exception, not the strategy."},
    ],
    "cap_pacelc": [
        {"decision": "CP vs AP during a partition?",
         "options": [
             {"name": "CP (consistent)",
              "when": "Serving wrong data is worse than serving none: money, config, locks.",
              "pros": ["No split-brain", "simple reasoning"],
              "cons": ["Unavailable without majority"]},
             {"name": "AP (available)",
              "when": "Serving stale beats serving nothing: feeds, carts, DNS.",
              "pros": ["Stays writable", "low latency"],
              "cons": ["Conflicts to reconcile", "readers disagree"]},
         ],
         "rule": "Ask what a wrong answer costs: if it costs money or safety, pick CP."},
        {"decision": "What to optimize when there is no partition (the E in PACELC)?",
         "options": [
             {"name": "Latency",
              "when": "User-facing paths where ms matter.",
              "pros": ["Fast", "available"],
              "cons": ["Weaker consistency day to day"]},
             {"name": "Consistency",
              "when": "The everyday read must reflect the everyday write.",
              "pros": ["Predictable behavior"],
              "cons": ["Pays coordination latency always"]},
         ],
         "rule": "Most systems live in the E, not the P: design the common case first, the partition case second."},
    ],
    "db_scaling": [
        {"decision": "How to scale reads?",
         "options": [
             {"name": "Read replicas",
              "when": "Read-heavy, lag-tolerant workloads.",
              "pros": ["Easy", "big read multiplier"],
              "cons": ["Replication lag", "writes still single-primary"]},
             {"name": "Cache in front",
              "when": "Hot, repeatable reads.",
              "pros": ["Cheapest scaling", "huge multiplier"],
              "cons": ["Invalidation tax", "another system"]},
         ],
         "rule": "Cache first (cheapest), replicas second; both before sharding."},
        {"decision": "How to scale writes?",
         "options": [
             {"name": "Bigger primary (vertical)",
              "when": "You have headroom and want simplicity.",
              "pros": ["No app changes"],
              "cons": ["Hard ceiling", "expensive", "failover still hurts"]},
             {"name": "Sharding",
              "when": "Write volume exceeds one node, durably.",
              "pros": ["Near-linear write scaling"],
              "cons": ["App complexity", "no cross-shard transactions", "rebalancing"]},
             {"name": "Move work out (queues/batching)",
              "when": "Writes can be async or batched.",
              "pros": ["Absorbs bursts", "simpler DB"],
              "cons": ["Eventual visibility", "pipeline to operate"]},
         ],
         "rule": "Defer sharding as long as possible: vertical, then async, then shard when the math forces it."},
    ],
    "microservices": [
        {"decision": "Monolith vs microservices?",
         "options": [
             {"name": "Modular monolith",
              "when": "Small team, unclear boundaries, pre-product-market fit.",
              "pros": ["Simple deploys", "easy refactors", "one observability story"],
              "cons": ["Scales as one unit", "one bad deploy takes all"]},
             {"name": "Microservices",
              "when": "Independent teams, independent scaling, or blast-radius needs.",
              "pros": ["Independent deploys/scaling", "team autonomy"],
              "cons": ["Distributed complexity", "versioning", "network failures"]},
         ],
         "rule": "Start modular-monolith; extract services when teams or scaling force it, not on day one."},
        {"decision": "How do services stay consistent?",
         "options": [
             {"name": "Saga (choreography/orchestration)",
              "when": "Multi-service workflows without distributed transactions.",
              "pros": ["No 2PC", "each step independent"],
              "cons": ["Compensating actions to write", "no isolation"]},
             {"name": "2PC / distributed transactions",
              "when": "Almost never across services.",
              "pros": ["ACID"],
              "cons": ["Blocking", "fragile", "couples availability"]},
         ],
         "rule": "Sagas with compensating actions; treat 2PC across services as a design smell."},
    ],
}


def tradeoff_cards(topic: str) -> list[dict]:
    """Trade-off cards for a topic; raises SysdesignError on unknown topic."""
    key = (topic or "").strip().lower().replace("-", "_")
    if key not in TRADEOFFS:
        raise SysdesignError(
            f"No trade-off cards for '{topic}'. Choose from: {', '.join(sorted(TRADEOFFS))}.")
    return [dict(c) for c in TRADEOFFS[key]]


def render_tradeoffs(topic: str) -> str:
    """Human-readable rendering of a topic's trade-off cards."""
    title = get_topic(topic)["title"]
    lines = [f"## Trade-off cards: {title}", ""]
    for card in tradeoff_cards(topic):
        lines.append(f"### {card['decision']}")
        lines.append("")
        for opt in card["options"]:
            lines.append(f"**{opt['name']}** - use when: {opt['when']}")
            lines.append(f"  + {'; '.join(opt['pros'])}")
            lines.append(f"  - {'; '.join(opt['cons'])}")
            lines.append("")
        lines.append(f"_Rule of thumb: {card['rule']}_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Practice drills: prompts with difficulty, self-check rubrics, and
# follow-ups. Self-grade honestly: if you miss a self-check bullet, that
# is the thing to study next.
# ---------------------------------------------------------------------------

DRILLS: dict[str, list[dict]] = {
    "caching": [
        {"prompt": "Design the cache layer for a news homepage: 200k reads/sec, articles update every few minutes.",
         "level": "easy",
         "self_check": ["Named what to cache and the TTL with a reason",
                        "Picked cache-aside and said why not write-through",
                        "Mentioned stampede protection (jitter/coalescing)"],
         "followups": ["What if an article must update within 5 seconds?",
                       "How do you handle a cold start after a deploy?"]},
        {"prompt": "Your 95% hit-ratio cache drops to 40% every hour on the hour. Diagnose and fix.",
         "level": "hard",
         "self_check": ["Suspected synchronized TTL expiry (thundering herd)",
                        "Proposed jittered TTLs or staggered refresh",
                        "Suggested request coalescing / stale-while-revalidate",
                        "Mentioned how to confirm via cache metrics (evictions, hit ratio by key)"],
         "followups": ["How would you prove the fix worked?",
                       "When would you accept the hourly dip instead?"]},
    ],
    "queues": [
        {"prompt": "Design order confirmation emails for a store doing 5k orders/day with Black Friday 20x spikes.",
         "level": "easy",
         "self_check": ["Decoupled checkout from sending via a queue",
                        "Chose delivery semantics and justified it",
                        "Made consumers idempotent", "Added a dead-letter queue"],
         "followups": ["How do you keep per-user email ordering?",
                       "What pages on-call at 3am?"]},
        {"prompt": "Two consumers process payments; duplicates would double-charge. Design for exactly-once effects.",
         "level": "hard",
         "self_check": ["Explained why broker exactly-once is not enough alone",
                        "Used idempotency keys on the payment intent",
                        "Made the charge operation itself idempotent (or transactional outbox)",
                        "Named the residual failure windows honestly"],
         "followups": ["Where does the idempotency key live and for how long?",
                       "How do you test the duplicate path?"]},
    ],
    "sharding": [
        {"prompt": "Shard a 5 TB user-photos store. Queries are always by user id; some users have 100k photos.",
         "level": "medium",
         "self_check": ["Chose a shard key from the access pattern (user id)",
                        "Addressed the heavy-user hotspot (key splitting or separate tier)",
                        "Named the routing mechanism",
                        "Described how to add capacity later"],
         "followups": ["What if product wants 'photos near a location' search?",
                       "How do you rebalance without downtime?"]},
        {"prompt": "Design shard-aware request routing for a multi-region chat app with 100M users.",
         "level": "hard",
         "self_check": ["Kept a user's data in one region (locality)",
                        "Handled cross-region reads (follower reads vs routing)",
                        "Named the consistency trade for messages vs presence",
                        "Addressed region failure (failover, not split-brain)"],
         "followups": ["Where does the routing directory live?",
                       "How do you move a user between regions?"]},
    ],
    "consistency": [
        {"prompt": "A social app shows like counts. Design the counter for 1M likes/day with 5 writers/sec on hot posts.",
         "level": "easy",
         "self_check": ["Said strong consistency is unnecessary here and why",
                        "Picked eventual with a merge strategy (CRDT counter or sharded counters)",
                        "Named the user-visible staleness bound"],
         "followups": ["What if the count drives payouts to creators?",
                       "How do you handle the hot-post write hotspot?"]},
        {"prompt": "Design seat reservations for a concert: 50k seats, 500k concurrent buyers, no double-booking.",
         "level": "hard",
         "self_check": ["Identified this as needing strong consistency (or serialization)",
                        "Serialized per-seat or per-section writes (single owner/queue)",
                        "Handled the hold-expiry path (TTL + compensating release)",
                        "Named what happens under partition (fail closed, not double-book)"],
         "followups": ["How long is a hold, and what releases it?",
                       "Where is the serialization point and is it a SPOF?"]},
    ],
    "load_balancing": [
        {"prompt": "Balance 10k rps across 20 identical API servers. Requests are uniform.",
         "level": "easy",
         "self_check": ["Picked an algorithm and justified it (round-robin is fine here)",
                        "Added health checks with concrete thresholds",
                        "Made the app tier stateless (no sticky sessions)",
                        "Noted the LB itself needs redundancy"],
         "followups": ["Requests stop being uniform (some 10x heavier). Now what?",
                       "How do you drain a host for deploy?"]},
        {"prompt": "Design L7 routing for 200 microservices with canary deploys and per-route rate limits.",
         "level": "hard",
         "self_check": ["Separated edge concerns (TLS, rate limit) from routing",
                        "Described canary by header/weight with automatic rollback signals",
                        "Named the config distribution mechanism (and its failure mode)",
                        "Addressed retry storms (budgets, idempotency, circuit breakers)"],
         "followups": ["Who owns the gateway config: platform or service teams?",
                       "How do you test a routing change safely?"]},
    ],
    "rate_limiting": [
        {"prompt": "Protect a public signup API from abuse: 100 req/min per IP, 1000 req/min globally.",
         "level": "easy",
         "self_check": ["Chose token bucket and the key (IP + global)",
                        "Said where state lives (Redis) and why",
                        "Returns 429 with Retry-After", "Considered NAT/proxy shared IPs"],
         "followups": ["An attacker rotates IPs. What next?",
                       "How do you avoid the limiter becoming the bottleneck?"]},
        {"prompt": "Design per-tenant rate limits for a SaaS API with 10k tenants on 50 gateway nodes.",
         "level": "hard",
         "self_check": ["Decided between centralized vs per-node approximation (and the error bound)",
                        "Handled burst vs sustained separately",
                        "Named the fairness question (one tenant starving others)",
                        "Described what degrades first under overload"],
         "followups": ["A tenant legitimately needs 100x for a migration. How?",
                       "How do you test the limiter under realistic skew?"]},
    ],
    "cdn": [
        {"prompt": "Serve product images for a global storefront: 1M images, 500M views/day.",
         "level": "easy",
         "self_check": ["Put images on a CDN with pull/origin-fetch",
                        "Used fingerprinted URLs with long TTLs",
                        "Named the origin-shield/tiering setup",
                        "Handled image variants (resizing at edge or build time)"],
         "followups": ["A wrong image is cached globally. How do you fix it fast?",
                       "How do you keep origin costs down?"]},
        {"prompt": "Design edge personalization: homepage differs per user segment, must load in <300 ms worldwide.",
         "level": "hard",
         "self_check": ["Separated cacheable shell from dynamic fragments (ESI or edge assembly)",
                        "Ran segmentation at the edge (workers) to skip origin",
                        "Named the cache key design (segment, not user)",
                        "Quantified the latency budget per hop"],
         "followups": ["What can never be cached at the edge?",
                       "How do you debug a wrong segment assignment?"]},
    ],
    "cap_pacelc": [
        {"prompt": "Pick CP or AP for: (a) a feature-flag service, (b) a shopping cart, (c) a distributed lock service.",
         "level": "medium",
         "self_check": ["Justified each from the cost of a wrong answer, not from habit",
                        "Named the partition behavior for each choice",
                        "Gave the PACELC (no-partition) trade for at least one"],
         "followups": ["The cart team says 'we need strong consistency'. How do you push back?",
                       "What changes if the lock service picks AP?"]},
        {"prompt": "Your multi-region KV store must survive a region partition without losing writes or forking data. Reconcile the requirements.",
         "level": "hard",
         "self_check": ["Stated the impossibility plainly (CAP) before designing",
                        "Proposed the actual business trade (which requirement bends)",
                        "Designed the reconciliation path (CRDTs, version vectors, or manual)",
                        "Named the user-visible behavior during the partition"],
         "followups": ["Who decides the merge policy: platform or product?",
                       "How do you detect the fork healed?"]},
    ],
    "db_scaling": [
        {"prompt": "A Postgres primary is at 80% CPU on reads, 20% on writes. Scale it without sharding.",
         "level": "easy",
         "self_check": ["Added read replicas and routed reads (with lag caveats)",
                        "Added a cache for the hottest reads",
                        "Checked the real bottleneck first (slow queries, missing indexes, pool sizing)",
                        "Named the replication-lag UX edge (read-your-write)"],
         "followups": ["Lag spikes to 10 s. What breaks first?",
                       "When do you admit replicas are not enough?"]},
        {"prompt": "Design the write path for 100k writes/sec of immutable events with 7-year retention.",
         "level": "hard",
         "self_check": ["Questioned whether a relational DB is the right store",
                        "Sized storage: 100k * 86400 * 365 * 7 * payload bytes",
                        "Chose partitioning (time-based) and the query implications",
                        "Separated hot (recent) from cold (archive) tiers"],
         "followups": ["How do you backfill a new consumer over 7 years?",
                       "What is the restore story if a partition is lost?"]},
    ],
    "microservices": [
        {"prompt": "Split a monolithic checkout (cart, payment, inventory, notify) into services. Draw the boundaries.",
         "level": "medium",
         "self_check": ["Decomposed by business capability, not by layer",
                        "Named the data ownership per service (no shared DB)",
                        "Designed the payment failure path (saga + compensations)",
                        "Kept the call graph shallow; named timeouts/retries"],
         "followups": ["Inventory says no, payment already charged. Walk through the saga.",
                       "Which service owns the order id?"]},
        {"prompt": "Your 40-service mesh has cascading failures every deploy. Harden it.",
         "level": "hard",
         "self_check": ["Named the actual failure mode (retry storms, no bulkheads)",
                        "Added circuit breakers, timeouts, retries with budgets and jitter",
                        "Separated deploy from release (feature flags, canaries)",
                        "Designed bulkheads (per-dependency pools/queues) and load shedding"],
         "followups": ["How do you find which service started the cascade?",
                       "What is the blast radius of the gateway going down?"]},
    ],
}

_LEVELS = ["easy", "medium", "hard"]


def practice_prompts(topic: str, level: str | None = None) -> list[dict]:
    """Drills for a topic, optionally filtered by level."""
    key = (topic or "").strip().lower().replace("-", "_")
    if key not in DRILLS:
        raise SysdesignError(
            f"No drills for '{topic}'. Choose from: {', '.join(sorted(DRILLS))}.")
    drills = DRILLS[key]
    if level is None:
        return [dict(d) for d in drills]
    lvl = level.strip().lower()
    if lvl not in _LEVELS:
        raise SysdesignError(f"Unknown level '{level}'. Choose from {_LEVELS}.")
    return [dict(d) for d in drills if d["level"] == lvl]


def render_drill(topic: str, level: str | None = None) -> str:
    """Human-readable rendering of drills for a topic/level."""
    title = get_topic(topic)["title"]
    drills = practice_prompts(topic, level)
    head = f"## Practice drills: {title}"
    if level:
        head += f" ({level})"
    lines = [head, ""]
    for i, d in enumerate(drills, 1):
        lines.append(f"### Drill {i} [{d['level']}]")
        lines.append("")
        lines.append(d["prompt"])
        lines.append("")
        lines.append("**Self-check (be honest):**")
        lines += [f"- [ ] {s}" for s in d["self_check"]]
        lines.append("")
        lines.append("**Follow-ups to expect:**")
        lines += [f"- {f}" for f in d["followups"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Interview checklist: the 45-minute system design walkthrough.
# ---------------------------------------------------------------------------

CHECKLIST = """### System Design Interview Checklist (45 minutes)

**0-5 min: Clarify requirements**
- [ ] Functional: what exactly must the system do? (write the verbs down)
- [ ] Non-functional: scale, latency, availability targets (ask for numbers)
- [ ] Scope: what is explicitly out of scope? (say it out loud)

**5-10 min: Back-of-envelope estimation**
- [ ] QPS (read/write split), storage per day, bandwidth
- [ ] `python -m candid sysdesign estimate --qps ... --payload-kb ...`
- [ ] Name the bottleneck the math points at

**10-15 min: API design**
- [ ] 3-5 endpoints max; request/response shapes
- [ ] Idempotency where it matters (writes, webhooks)

**15-20 min: Data model**
- [ ] Entities and relationships; what the shard/partition key is and why
- [ ] Which queries hit one partition vs scatter

**20-30 min: High-level design**
- [ ] Draw: client -> LB -> app -> cache -> queue -> DB; CDN at the edge
- [ ] One sentence per component: why it exists
- [ ] Name the consistency choice per read path (strong vs eventual)

**30-40 min: Deep dive (pick ONE hard part)**
- [ ] Go deep on the bottleneck: sharding, hotspots, exactly-once, failover
- [ ] State 2-3 trade-offs explicitly and pick a side with reasons

**40-45 min: Bottlenecks, failure modes, wrap-up**
- [ ] Single points of failure and how each is mitigated
- [ ] What breaks first at 10x scale? What would you monitor?
- [ ] Summarize the design in 60 seconds
"""


def checklist() -> str:
    """The 45-minute system design interview checklist (markdown)."""
    return CHECKLIST


# ---------------------------------------------------------------------------
# Back-of-envelope estimator
# ---------------------------------------------------------------------------

def estimate(*, qps: float | None = None, daily_active_users: float | None = None,
             requests_per_user_per_day: float = 10.0, read_ratio: float = 0.9,
             payload_kb: float = 1.0, retention_days: float = 365.0,
             replication: int = 3, overhead: float = 1.3) -> dict:
    """Back-of-envelope capacity math. Returns raw numbers + readable lines.

    Provide either qps or daily_active_users (with requests_per_user_per_day).
    Assumptions are documented in the result so the math is auditable.
    """
    if qps is None and daily_active_users is None:
        raise SysdesignError("estimate needs qps or daily_active_users.")
    if qps is None:
        if daily_active_users <= 0 or requests_per_user_per_day <= 0:
            raise SysdesignError("daily_active_users and requests_per_user_per_day must be positive.")
        qps = daily_active_users * requests_per_user_per_day / 86400.0
    if qps <= 0:
        raise SysdesignError("qps must be positive.")
    if not 0.0 <= read_ratio <= 1.0:
        raise SysdesignError("read_ratio must be between 0 and 1.")
    if payload_kb <= 0 or retention_days <= 0 or replication < 1 or overhead < 1:
        raise SysdesignError("payload_kb, retention_days must be positive; replication >= 1; overhead >= 1.")

    write_qps = qps * (1.0 - read_ratio)
    requests_per_day = qps * 86400.0
    writes_per_day = write_qps * 86400.0
    payload_bytes = payload_kb * 1024.0
    storage_bytes = writes_per_day * retention_days * payload_bytes * replication * overhead
    read_bw_bps = qps * read_ratio * payload_bytes
    write_bw_bps = write_qps * payload_bytes

    def _fmt_bytes(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
            if n < 1024.0 or unit == "PB":
                return f"{n:.1f} {unit}"
            n /= 1024.0
        return f"{n:.1f} PB"

    def _fmt_rate(n: float) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M/s"
        if n >= 1000:
            return f"{n / 1000:.1f}k/s"
        return f"{n:.0f}/s"

    lines = [
        f"QPS: {_fmt_rate(qps)} ({_fmt_rate(write_qps)} writes)",
        f"Requests/day: {requests_per_day:,.0f}",
        f"Storage ({retention_days:,.0f}d retention, x{replication} replicas, {overhead:.1f}x overhead): {_fmt_bytes(storage_bytes)}",
        f"Read bandwidth: {_fmt_bytes(read_bw_bps)}/s",
        f"Write bandwidth: {_fmt_bytes(write_bw_bps)}/s",
    ]
    return {
        "qps": qps,
        "write_qps": write_qps,
        "requests_per_day": requests_per_day,
        "storage_bytes": storage_bytes,
        "read_bandwidth_bps": read_bw_bps,
        "write_bandwidth_bps": write_bw_bps,
        "assumptions": {
            "read_ratio": read_ratio,
            "payload_kb": payload_kb,
            "retention_days": retention_days,
            "replication": replication,
            "overhead": overhead,
        },
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Flashcards: Q/A cards built from trade-off cards and numbers.
# ---------------------------------------------------------------------------

def flashcards(topic: str, n: int = 5, seed: int = 0) -> list[dict]:
    """Deterministic Q/A flashcards for a topic (shuffled with seed)."""
    if n < 1:
        raise SysdesignError("n must be at least 1.")
    title = get_topic(topic)["title"]
    cards: list[dict] = []
    for card in tradeoff_cards(topic):
        for opt in card["options"]:
            cards.append({
                "q": f"{title}: {card['decision']} - when would you pick '{opt['name']}'?",
                "a": f"{opt['when']} Rule of thumb: {card['rule']}",
            })
    for fact in get_topic(topic)["numbers"]:
        cards.append({
            "q": f"{title}: complete the fact - {fact.split(':')[0].strip()}?",
            "a": fact,
        })
    rng = random.Random(seed)
    rng.shuffle(cards)
    return cards[:n]


def render_flashcards(topic: str, n: int = 5, seed: int = 0) -> str:
    """Human-readable rendering of flashcards (Q then A)."""
    title = get_topic(topic)["title"]
    lines = [f"## Flashcards: {title} (showing {n})", ""]
    for i, c in enumerate(flashcards(topic, n, seed), 1):
        lines.append(f"**Q{i}.** {c['q']}")
        lines.append(f"_A{i}._ {c['a']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Study plan + gap mapping (used by prep packs)
# ---------------------------------------------------------------------------

def study_plan(topic: str) -> list[str]:
    """Ordered study steps for a topic: read, cards, drills, rehearse."""
    title = get_topic(topic)["title"]
    key = (topic or "").strip().lower().replace("-", "_")
    steps = [
        f"1. Read the overview: `python -m candid sysdesign show --topic {key}`",
    ]
    if key in DEEP_DIVES:
        steps.append(f"2. Read the deep-dive: `python -m candid sysdesign deep-dive --topic {key}`")
        step_no = 3
    else:
        step_no = 2
    steps.append(f"{step_no}. Review trade-off cards: `python -m candid sysdesign tradeoffs --topic {key}`")
    step_no += 1
    steps.append(f"{step_no}. Do the drills, self-check honestly: `python -m candid sysdesign drill --topic {key}`")
    step_no += 1
    steps.append(f"{step_no}. Drill the facts: `python -m candid sysdesign flashcards --topic {key} --n 8`")
    step_no += 1
    steps.append(f"{step_no}. Rehearse out loud with the checklist: `python -m candid sysdesign checklist`")
    step_no += 1
    steps.append(f"{step_no}. Full mock: `python -m candid mock design` (talk through a {title} prompt)")
    return steps


def render_study_plan(topic: str) -> str:
    """Human-readable rendering of the study plan."""
    title = get_topic(topic)["title"]
    lines = [f"## Study plan: {title}", ""]
    lines += study_plan(topic)
    return "\n".join(lines) + "\n"


#: gap-text keyword -> sysdesign topic(s). Used by prep packs.
_GAP_TOPIC_KEYWORDS: list[tuple[str, str]] = [
    ("cach", "caching"),
    ("redis", "caching"),
    ("memcach", "caching"),
    ("queue", "queues"),
    ("kafka", "queues"),
    ("stream", "queues"),
    ("messag", "queues"),
    ("shard", "sharding"),
    ("partition", "sharding"),
    ("consist", "consistency"),
    ("eventual", "consistency"),
    ("cap theorem", "cap_pacelc"),
    ("pacelc", "cap_pacelc"),
    ("load balanc", "load_balancing"),
    ("rate limit", "rate_limiting"),
    ("throttl", "rate_limiting"),
    ("cdn", "cdn"),
    ("edge", "cdn"),
    ("replica", "db_scaling"),
    ("microservice", "microservices"),
    ("distributed", "caching"),
    ("system design", "caching"),
    ("scalab", "sharding"),
]


def topics_for_gaps(gaps: list[str] | None) -> list[str]:
    """Map match-gap strings to sysdesign topic ids (deduped, stable order)."""
    found: list[str] = []
    for gap in gaps or []:
        low = str(gap).lower()
        for keyword, topic in _GAP_TOPIC_KEYWORDS:
            if keyword in low and topic not in found:
                found.append(topic)
    return found


def to_jsonable(obj):
    """Convert library structures to JSON-serializable values."""
    return json.loads(json.dumps(obj, default=str))
