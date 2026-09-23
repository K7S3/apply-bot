# Polish: interview answer polisher

The `polish` feature turns rough, spoken-style drafts of your interview
answers into tight, interview-ready responses - in **your voice**, with no
invented facts.

## Concept

You write (or paste) a first-draft answer to a common interview question.
Polish cleans up structure, grammar, and pacing, then stores the result in
`polish_library.json` (under your data dir, local only). Nothing is final
until **you approve it**: only `approved` entries can be exported into
cheatsheets, printer sheets, or flashcards.

## The 10 features

1. **Draft answers** - start from a raw draft, dictation, or bullet dump.
2. **Question prompts** - seeded common questions (behavioral, leadership,
   "tell me about yourself").
3. **Rewrite in your voice** - the polisher keeps your wording and rhythm;
   it tightens, never ghostwrites a different persona.
4. **STAR structuring** - drafts get reshaped into Situation / Task / Action /
   Result without adding facts you didn't provide.
5. **Grounding rule** - the polisher never invents metrics, company names, or
   outcomes. If your draft says "the launch went well," the polished answer
   says that too - it does not add "increased revenue 40%."
6. **Voice-preservation note** - run the polish pass, then read the result
   out loud. If a sentence doesn't sound like you, edit it or re-draft that
   part. The tool preserves your phrasing; you are the final editor.
7. **Approval gate** - every entry has a status (`draft` / `approved` /
   `archived`). Only `approved` entries are exportable. Approve with
   `candid polish library approve ID` after reading the polished answer.
8. **Competency tags** - each approved answer gets lightweight tags
   (leadership, ownership, reliability...) from a local keyword map, so your
   cheatsheet shows coverage at a glance.
9. **Exports** - Markdown cheatsheet (`export`), printer-friendly 80-column
   sheet (`sheet`), and flashcard decks (`flashcards`) for self-quizzing.
10. **Drill mode** - deterministic seeded shuffle (`--seed N`) so a practice
    run is reproducible, and a friend can quiz you in the same order.

## Commands

```bash
# Export approved answers to a Markdown cheatsheet
# (default: <data-dir>/polish_cheatsheet.md)
python -m candid polish export
python -m candid polish export --id ans-1 --out /tmp/my-sheet.md

# Printer-friendly 80-column plain-text sheet (prints to stdout)
python -m candid polish sheet
python -m candid polish sheet --id ans-1 > /tmp/sheet.txt

# Flashcards from approved entries
python -m candid polish flashcards
python -m candid polish flashcards --seed 7   # reproducible drill order
```

## Approval-gate workflow

```
draft answer  -->  polish  -->  review  -->  approve  -->  export / drill
     ^                                                        |
     +------------ edit and re-polish as needed ---------------+
```

1. Add a draft answer (kept private in your local library).
2. Polish it into an interview-ready response.
3. **Read it out loud.** Anything that doesn't sound like you goes back to
   draft.
4. Approve it (`status: approved`).
5. Export a cheatsheet the night before the interview, and drill with
   flashcards on the morning of.

Only approved entries ever leave the library. Drafts are never exported,
printed, or shown to anyone - the export functions raise `ExportError`
rather than leaking a draft.

## Voice-preservation note

The polisher's job is cleanup, not authorship. It fixes grammar, orders the
story into STAR, and cuts filler - but your examples, your phrasing, and your
level of detail stay yours. If the polished answer uses a word you would
never say in an interview, change it. Interviewers can tell when an answer
wasn't written by the candidate, and a memorized-sounding answer hurts more
than a slightly rough one helps.

## Grounding rule

Polish never invents metrics, timelines, team sizes, or outcomes. Everything
in the polished answer traces back to your draft. If a sentence can't be
traced back, it gets cut or flagged for you to fill in. This keeps every
exported answer something you can defend under follow-up questions.
