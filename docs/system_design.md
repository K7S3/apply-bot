# System design fundamentals library

The `sysdesign` module (`candid/sysdesign.py`) is a self-contained study
library for system design interviews. Everything is local: no network, no
model calls, no accounts.

## What's in it

| Piece | What it is | CLI |
|---|---|---|
| Topic library | 10 topics (caching, queues, sharding, consistency, load balancing, rate limiting, CDN, CAP/PACELC, DB scaling, microservices): overview, key patterns, numbers to memorize, an interview one-liner | `sysdesign list`, `sysdesign show --topic caching` |
| Deep-dives | Long-form explainers for the 5 core topics: the idea in 60 seconds, a worked example with real numbers, how to answer, follow-ups to expect | `sysdesign deep-dive --topic queues` |
| Trade-off cards | 20 cards (2 per topic): the decision, options with when/pros/cons, a rule of thumb | `sysdesign tradeoffs --topic sharding [--json]` |
| Practice drills | 20 prompts (2 per topic, easy/medium/hard) with self-check rubrics and follow-ups | `sysdesign drill --topic consistency --level hard` |
| Estimator | Back-of-envelope math: QPS, storage, read/write bandwidth from a few inputs | `sysdesign estimate --qps 10000 --payload-kb 2 --retention-days 365 [--json]` |
| Checklist | The 45-minute interview walkthrough (clarify → estimate → API → data model → high level → deep dive → wrap-up) | `sysdesign checklist` |
| Flashcards | Q/A cards built from trade-off cards + key numbers, deterministic shuffle via `--seed` | `sysdesign flashcards --topic cdn --n 8` |
| Study plan | Ordered steps per topic: read → cards → drills → flashcards → checklist → `mock design` | `sysdesign plan --topic sharding` |

Prep packs pull this in automatically: when your match gaps mention
system-design topics (caching, queues, sharding, consistency, load
balancing, ...), the pack gets a "System design fundamentals" section
with one-liners and the key trade-off rule per topic.

## Estimator assumptions

`estimate()` documents its assumptions in the returned dict:

- `qps` or `daily_active_users * requests_per_user_per_day / 86400`
- writes/sec = qps * (1 - read_ratio)
- storage = writes/day * retention_days * payload * replication * overhead
- bandwidth = qps * payload (split by read ratio)

It is a back-of-envelope tool, not a capacity plan: it ignores
compression, indexing overhead beyond the multiplier, and traffic shape
(peaks vs averages). State those caveats in the interview.

## Adding content

**A new topic** (or extending one): add an entry to `TOPICS` in
`candid/sysdesign.py` with `title`, `overview`, `patterns` (3+),
`numbers` (2+), and `one_liner`. Then add trade-off cards to
`TRADEOFFS` (2 cards: `decision`, `options` with `name`/`when`/`pros`/`cons`,
`rule`) and drills to `DRILLS` (2 prompts: `prompt`, `level`,
`self_check` (3+ bullets), `followups`). The CLI, flashcards, and study
plan pick them up automatically; add tests in `tests/test_sysdesign.py`.

**A new deep-dive**: add markdown to `DEEP_DIVES` keyed by topic id,
following the existing shape (60-second idea, worked example with
numbers, how to answer, follow-ups, trade-offs to name, drill pointer),
and add the topic to `CORE_TOPICS` if it should be treated as core
(prep packs surface core topics for system-design gaps).

Rules: no em dashes (use hyphens/commas), no fabricated "recently
asked" claims, every number either computed by `estimate()` or labeled
as a rule of thumb.

## Verifying

```bash
python3 -m pytest tests/test_sysdesign.py -q
python3 -m candid sysdesign list
python3 -m candid sysdesign estimate --qps 10000 --payload-kb 2 --retention-days 365
```
