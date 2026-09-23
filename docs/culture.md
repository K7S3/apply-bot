# Company culture decoder (`candid culture`)

The culture decoder builds a company profile from data you already have:
your pasted values text, curated JDs, interview debriefs, prep bank,
tracker notes, and imported public datasets (LCA, WARN). It never reaches
the network, never scrapes, and never fabricates: every signal carries a
`source` label, and when there is no data it says so explicitly.

## Subcommands

- `candid culture profile --company X [--json]` - aggregate card: values,
  work-style, benefits, flags, interview process, stability, trajectory,
  with per-source coverage counts.
- `candid culture compare --a X --b Y [--json]` - side-by-side cards plus
  shared sources and signal labels unique to each company.
- `candid culture values --company X --text "..."` (or `--from-file`) -
  extract and store the company's stated values from pasted text.
  Extraction is verbatim: every stored quote is a substring of the input.
- `candid culture values --company X` - show stored values.
- `candid culture prep-questions --company X` - behavioral questions
  targeting each stored value. These are generated templates, labeled as
  such, not real questions asked by the company.
- `candid culture workstyle --company X` - remote/hybrid/onsite, async,
  timezone, on-call, travel signals parsed from curated JDs.
- `candid culture benefits --company X` - benefits parsed from JD text.
- `candid culture flags --company X` - red/amber/green flags from JD
  phrasing, each with a verbatim quote and a one-line "why".
- `candid culture process --company X` - interview-process stages derived
  from your debriefs, prep bank entries, and tracker notes for the company.
- `candid culture stability --company X` - layoff filings (last 12 months),
  LCA filing volume, and posting velocity from imported datasets.
- `candid culture trajectory --company X` - directional signals only
  ("increasing", "steady", "insufficient data"); never causal claims.

## Honesty contract

- Every signal: `signal`, `value`, `source`, `as_of` (when time-bounded).
- JD-derived items always include the verbatim quote and the JD id/title.
- Values quotes are always substrings of the text you pasted.
- Generated questions are labeled `generated from company value '<v>'`.
- Missing data yields `note: "insufficient data"` or
  `"no verified culture data for <company>"`, never invented numbers.
- Stability/trajectory language stays observational; no definitive
  claims about a company's health.

## Adding evidence

- Paste a company's values page into
  `candid culture values --company X --text "..."` (or `--from-file`).
- Import WARN layoff filings and LCA data the same way other commands do
  (see `salary` for LCA import); the decoder picks them up defensively.
- Log post-interview notes with the debrief flow; they feed `process`.
