# Glossary

- **Profile** — your structured record (name, skills, experience, education)
  built by `onboard` from your resume/LinkedIn files and stored in
  `candid_data/`.
- **JD** — job description. Accepted as text, file path, URL, or `-` (stdin)
  by any `--jd` flag.
- **Match score** — how well a JD fits your profile (see `matching`). A
  triage signal, not a verdict.
- **Tailoring** — rewriting your resume/cover letter to foreground the
  profile experience a specific JD asks for (see `tailoring`).
- **Tracker** — your application pipeline: one row per application with
  company, role, status, and notes (see `tracking`).
- **App id** — the tracker's numeric id for an application. Pass
  `--app-id N` to `match`, `tailor`, and `prep` instead of repeating
  company/role/JD.
- **Prep pack** — the interview preparation document built by `prep`:
  questions, concept deep-dives, mock plan, checklist.
- **Mock** — practice interviews: coding judge, AI interviewer, behavioral
  (STAR), system design (see `mock`).
- **STAR** — Situation, Task, Action, Result: the structure for behavioral
  interview answers practiced in `mock behavioral`.
- **Curated jobs** — the scored shortlist from `jobs curate`, saved into
  the tracker as `saved` rows.
- **LCA data** — DOL H-1B Labor Condition Application records with filed
  salary figures, imported via `salary import-lca`.
- **Posted range** — a pay range from a job posting, captured with
  `salary parse-range`.
- **Normalized comp** — an offer's annualized total (base + bonus + equity
  amortized over vesting + sign-on amortized over 2 years + benefits), used
  by `offer compare`.
- **BATNA** — Best Alternative To a Negotiated Agreement: your walk-away
  option. The `negotiate` playbook frames every counter around it.
- **Takeout mbox** — your Gmail export from Google Takeout, parsed by
  `gmail import` into tracker proposals you confirm or reject.
- **LinkedIn export** — LinkedIn's official data-export archive (a ZIP),
  imported by `linkedin import`. No scraping, ever.
- **Dashboard** — the local web UI (`dashboard`), bound to 127.0.0.1 only.
- **candid_data/** — where your personal data lives on your machine
  (git-ignored). Sample data for trying commands lives in
  `samples/candid/`.
