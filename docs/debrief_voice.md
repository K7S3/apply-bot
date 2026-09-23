# Interview debriefs (voice or typed)

After an interview, your memory of it fades fast — and the details that
fade are exactly the ones that matter: which questions stumped you, what
to drill before the next round. The debrief flow captures all of it in
about five minutes, right after the interview, by voice or by typing.

Everything is local and offline. No accounts, no API keys, no network.

## Setup

You need nothing to start: `python -m candid debrief start --typed`
works everywhere with typed answers. For voice, install one layer at a
time — each layer degrades gracefully to the next when missing:

**Microphone.** Any working mic. The recorder tries, in order:
`sounddevice` (Python) → `arecord` (Linux) → `rec` (sox). If none is
available, the session falls back to typed answers automatically.

**Speech-to-text (pick one, both local):**

- **vosk** — `pip install vosk`, then download a model from
  https://alphacephei.com/vosk/models, unpack it, and point
  `VOSK_MODEL_DIR` at the directory. Small, fast, fully offline.
- **whisper.cpp** — install the `whisper-cli` / `whisper-cpp` binary and
  a model file (https://github.com/ggml-org/whisper.cpp). More accurate,
  heavier.

**Text-to-speech (optional):** `espeak-ng` / `espeak`, or `say` on macOS.
Without any of them, prompts are printed with a `[voice]` prefix instead
of spoken.

**ffmpeg** is handy if your recorder produces `.mp3`/`.m4a` — the audio
layer accepts `.wav`, `.mp3`, and `.m4a`.

If no STT engine is usable, the session tells you exactly what to install
and continues in typed mode. Voice is a convenience, never a gate.

## The guided flow

```bash
python -m candid debrief start --app 3            # linked to tracker app #3
python -m candid debrief start --app 3 --typed    # skip voice, type answers
python -m candid debrief start --company Acme --role "Data Scientist"
```

The session asks six prompts in order, one turn each:

1. Walk me through the interview from the start — format, who you spoke with.
2. What were you asked? Main questions or topics.
3. What stumped you, if anything?
4. What went well? What are you most proud of?
5. What are the next steps — theirs and yours?
6. Anything else to remember for the next round, or next time?

Answers adapt: mention being stumped and you get a follow-up ("Which
question tripped you up the most, and what would you say now if you could
redo it?"); mention something going well and it asks what made it work.
At most one follow-up per turn. Type `done` any time to finish early.

When the session ends it:

- saves the transcript to `candid_data/debriefs/deb-<timestamp>.json`,
- runs the extractor over your answers (below),
- registers the result with the debrief store (`candid_data/debriefs.json`),
  linked to the tracker app id when given.

Review and manage sessions:

```bash
python -m candid debrief list            # all sessions, newest first
python -m candid debrief list --app 3   # sessions for one application
python -m candid debrief show deb-20260922-201212
python -m candid debrief export deb-20260922-201212 --format md   # or txt
```

## How extraction works

`candid/debrief_extract.py` turns a transcript into a structured summary:

```python
{
    "key_questions": [...],        # interviewer prompts, deduped, in order
    "key_answers": [...],          # condensed answers, aligned with questions
    "weak_spots": [...],          # phrases signaling struggle
    "action_items": [...],         # follow-ups / things to study
    "one_paragraph_summary": "...",
    "enhanced": False,             # True if the local-LLM tier ran
}
```

Two tiers, both offline:

1. **Heuristic (`extract`)** — cue-phrase matching plus sentence scoring.
   Strong signals ("stumped", "blanked", "didn't know", "no idea") flag an
   answer as a weak spot on a single hit; softer signals ("shaky",
   "unsure", "fumbled") need corroboration. This tier alone is enough for
   the debrief store.
2. **Local LLM (`extract_enhanced`)** — sends the transcript plus the
   heuristic output to an Ollama model on `localhost:11434` (override with
   `CANDID_OLLAMA_URL` / `CANDID_OLLAMA_MODEL`) and merges improvements.
   Never a paid API. On any failure — no server, timeout, bad response —
   it silently falls back to the heuristic result with `enhanced=False`.

## How debriefs feed prep

The debrief store is keyed by tracker app id, so past interviews steer
future preparation:

- `python -m candid debrief due [--days N]` lists interviews from the
  last N days (default 7) with no debrief recorded — the same reminders
  also surface in the dashboard nudge feed as `debrief_due` items.
- `candid/prep.py` pulls `weak_spots(app_id)` from the store and renders
  a **"Based on your past debriefs, drill these:"** section at the top of
  every prep pack built with `--app-id`. Stumbled on SQL window functions
  last time? The next pack for that company leads with them.
- `python -m candid debrief export <id> --format md` exports a recorded
  debrief — transcript, summary, weak spots, action items — as Markdown
  under `candid_data/debrief_exports/`. The `<id>` is a debrief id, or a
  tracker app id (exports its newest debrief).

All of these degrade gracefully: with no debrief store or no recorded
debriefs, the prep pack simply omits the section and the due list treats
every recent interview as due — nothing raises, nothing blocks.
