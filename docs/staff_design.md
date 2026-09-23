# Staff design drills (`candid/staff_design.py`)

Staff/principal-track interview drills. Two drills, both fully local:

1. **System-design-at-scale drills** - 12 original candid practice prompts.
   Each prompt has a base brief plus **scale twists** (10x traffic,
   multi-region, cost-constrained) and **org constraints** (team size,
   timeline, legacy reality). The eval checklist is what separates a
   staff-level answer from a senior one: capacity planning, failure modes,
   cost, and org rollout, not just a box diagram.
2. **Tech-strategy memo drill** - a memo scaffold with sections for context,
   options with tradeoffs, recommendation, risks, rollout, and success
   metrics, plus a self-critique checklist. Memos save as Markdown under
   `candid_data/staff_memos/` (git-ignored user data).

## Usage

```bash
python -m candid.staff_design design --list
python -m candid.staff_design design --prompt ads-ranking
python -m candid.staff_design design --prompt ads-ranking --twists
python -m candid.staff_design memo --topic "Adopt a feature store"
python -m candid.staff_design memo --topic "Adopt a feature store" --save feature-store
python -m candid.staff_design memo --list
python -m candid.staff_design memo --show feature-store
```

## The 12 prompts

| id | Title |
|----|-------|
| `ads-ranking` | Global ads ranking platform |
| `feed-ranking-ml` | ML platform for feed ranking (training to serving) |
| `event-streaming` | Exactly-once event pipeline at 1T events/day |
| `payments-ledger` | Active-active payments ledger across 3 regions |
| `global-search` | Global search index over 50B documents |
| `edge-rate-limiter` | Distributed rate limiting at the edge |
| `notifications` | Multi-channel notification platform (5B/day) |
| `lakehouse-migration` | Legacy Hadoop to cloud lakehouse migration |
| `llm-serving` | Cost-constrained LLM serving at 100k concurrent users |
| `data-deletion` | User data deletion across 200 services (privacy) |
| `realtime-bidding` | Real-time bidding exchange at 100ms p99 |
| `incident-response` | Incident response org design at 500-engineer scale |

## Module API

- `list_design_prompts()` - summaries (id, title, brief, source).
- `get_design_prompt(id)` - full prompt dict; raises `StaffError` if unknown.
- `format_design_prompt(p, show_twists=True)` - drill-ready Markdown text.
- `render_memo_scaffold(topic)` - blank memo Markdown for a topic.
- `save_memo(name, topic, body)` - saves to `DATA_DIR/staff_memos/<name>.md`; returns the Path.
- `list_memos()` - saved memo names, newest first.
- `get_memo(name)` - saved memo Markdown; raises `StaffError` if missing.
- `main(argv)` - CLI entry point, returns an exit code.

## Design conventions

- Prompts are original practice scaffolds labeled "candid practice prompt".
  They never contain fabricated experience or metrics for the user; the
  candidate supplies their own numbers and stories during the drill.
- Memo names are sanitized to `[a-z0-9_-]` so they are safe filenames.
- Storage resolves the data dir lazily via `config._data_dir()` (not the
  import-time `config.DATA_DIR`) so the `CANDID_DATA_DIR` env override works
  in tests.
