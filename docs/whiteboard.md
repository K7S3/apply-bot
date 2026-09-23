# Whiteboard practice mode

`python -m candid whiteboard` turns system-design interview prep into a
repeatable practice loop: pick a drill, run it on a timer, narrate your
diagram out loud, then score yourself against a fixed rubric. Everything is
local and deterministic; sessions are saved under
`CANDID_DATA_DIR/whiteboard_sessions/`.

## The loop

```bash
# 1. Pick a drill (10 seeded: url-shortener, chat-system, kv-store, ...)
python -m candid whiteboard drills --difficulty hard

# 2. See the timed phase plan (clarify / high-level / deep dive / wrap-up)
python -m candid whiteboard plan --drill chat-system --minutes 45

# 3. Run it on a timer (draw on a real board or paper, talk out loud)
python -m candid whiteboard drill --drill chat-system --minutes 45

# 4. Capture what you said about your diagram, section by section
python -m candid whiteboard narrate --drill chat-system
# non-interactive: --notes-file samples/candid/whiteboard_notes.json

# 5. Check which expected components you actually drew
python -m candid whiteboard components --drill chat-system --check gateway router store

# 6. Rate yourself 1-5 on the four rubric dimensions -> structured feedback
python -m candid whiteboard feedback --session wb20260922-001 \
    --clarity 4 --completeness 3 --depth 5 --communication 4

# 7. Track progress over time
python -m candid whiteboard history
```

## The ten subcommands

| Subcommand | What it does |
|---|---|
| `drills [--difficulty] [--topic] [--json]` | List/search the drill bank (10 drills, easy/medium/hard). |
| `plan --drill ID [--minutes N]` | Timed phase plan; minutes always sum exactly to the total. |
| `narrate --drill ID [--notes-file F] [--no-save]` | Describe-your-diagram flow: five guided narration checkpoints (requirements recap, components, data flow, failure & scale, tradeoffs). Blank sections are flagged. |
| `components --drill ID [--check ...] [--session ID]` | Expected-component checklist with coverage %; prefix matching (`--check cache`); attachable to a session. |
| `outline --drill ID` | Reference outline (APIs, data model, scale, pitfalls) for post-session self-comparison. Read it *after* you practice, not before. |
| `feedback --session ID --clarity N --completeness N --depth N --communication N [--notes T]` | Weighted rubric score, per-dimension verdicts, strengths, gaps, and concrete next steps. |
| `drill --drill ID [--minutes N] [--no-wait]` | Timed run with phase prompts; saves a session record. |
| `followups --drill ID [--quiz] [--answer T]` | Follow-up question bank ("why they ask" included); quiz mode asks one and captures your answer. |
| `history [--drill ID] [--json]` | Session history plus per-drill best scores and rubric-dimension averages. |
| `rubric` | Print the evaluation rubric. |

## The rubric

Four dimensions, weights in parentheses: **Clarity** (3), **Completeness**
(3), **Depth** (2), **Communication** (2). Self-rate 1-5 after each drill;
`feedback` computes the weighted score and maps gaps to concrete next steps
(e.g. low depth -> "pick the hardest component and go three levels deeper").
Bands: >= 4.5 whiteboard-ready, >= 3.5 solid, >= 2.5 developing, else needs
work.

## Adding drills

Drills live in `candid/data/whiteboard_drills.json`. Copy an existing entry
and fill in: `id`, `title`, `prompt`, `difficulty`, `topics`, `minutes`,
`functional`, `non_functional`, `scale`, `expected_components` (name + why),
`api_sketch`, `data_model`, `deep_dives`, `followups` (question + why they
ask), `pitfalls`. Keep entries tight: 3-6 bullets per list.
