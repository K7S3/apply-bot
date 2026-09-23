# Engineering Manager track (batch 91)

The EM track helps engineers aiming at Engineering Manager roles: reframing an
IC-leaning resume around management scope, prepping for EM interview loops,
practicing EM communication (updates, exec summaries, 30-60-90 plans), and
checking management pay bands. It is built for two audiences: EMs applying to
new roles, and senior ICs making the IC-to-EM switch.

## Commands

| Feature | Command | What it does |
|---|---|---|
| em-questions | (batch 91) | EM interview question bank: behavioral, hiring, delivery, org-design, and people-problem themes. |
| prep em | (batch 91) | EM-flavored interview prep pack built on `prep`. |
| em drill | (batch 91) | Rapid-fire EM scenario drills for reps under time pressure. |
| em hiring-loop | (batch 91) | Full mock EM hiring loop: behavioral + hiring + org-design rounds. |
| em stories | (batch 91) | STAR story builder tuned for EM themes (hiring wins, conflict, delivery, growing people). |
| team-health storytelling | (batch 91) | Turn team-health evidence (retention, morale, performance turnarounds) into interview-ready stories. |
| update-template | (batch 91) | Status update templates: weekly, exec, and incident flavors. |
| exec-summary | (batch 91) | Distill a project or quarter into a crisp executive summary. |
| plan-30-60-90 | (batch 91) | Draft a 30-60-90 day plan for a new EM role. |
| em reframe | `python -m candid em reframe [--json]` | Reframe your resume for EM roles (detailed below). |
| em salary | `python -m candid em salary [--title T] [--location L] [--json]` | Management-title pay bands (detailed below). |

## `em reframe`: the grounded scope reframe

`em reframe` reads your stored profile and does three things:

1. **Extracts scope signals** - team size ("led a team of 8 engineers"),
   org size, hiring ("hired 6 engineers", "grew the team from 3 to 10"),
   mentoring, cross-team impact ("partnered with 3 product teams"), and
   delivery/process ownership (roadmap, OKRs, sprint planning, performance
   reviews). Every signal carries its exact source quote and the role it
   came from.
2. **Flags missing scope** - anything not stated is a gap, not a guess:
   "Team size: not stated anywhere in the profile - add 'team of N' to each
   role where you led people." If your titles read as an IC track, it says
   so plainly and highlights leadership-adjacent scope (mentoring, tech-lead
   work, cross-team delivery) rather than claiming management experience
   you do not state.
3. **Promotes EM-relevant bullets** per role and drafts an EM summary built
   only from extracted signals.

The hard rule: **missing data is an honest gap, never fabrication.** The
reframe will never invent a team size, a hiring number, or management
experience. Fill the gaps from your real history.

Example:

```
$ python -m candid em reframe
EM REFRAME - Jordan Lee

SCOPE SIGNALS FOUND (7)
  - team_size: 8 -- "...Led a team of 8 engineers shipping the..." [Acme]
  - hiring: 6 -- "...Hired 6 engineers in 18 months..." [Acme]
  ...

WHAT IS MISSING (0 gaps)
  (none - strong scope coverage)

ROLE-BY-ROLE REFRAME
...
EM SUMMARY DRAFT
Jordan Lee: Engineering Manager (8.0 yrs) reframed for EM roles. Scope on
record: led teams of up to 8. Hiring stated: 6 (see source quotes). ...
```

## `em salary`: management pay bands

`em salary` filters your existing salary database (`salary` command: DOL
H-1B LCA disclosures plus parsed posted ranges) to management titles and
reports p25/median/p75 bands per title bucket:

- **Engineering Manager** - engineering manager / senior / staff /
  software engineering manager / mgr variants
- **EM** - standalone "EM" titles
- **Director** - director of engineering / engineering director variants,
  plus bare "Director" rows (flagged: a bare "Director" row may not be an
  engineering role, so narrow with `--title` if the band looks off)

```bash
python -m candid em salary
python -m candid em salary --title "Engineering Manager" --location "New York"
python -m candid em salary --json   # machine-readable output
```

Sparsity is reported honestly: bands built from fewer than 5 data points
are labeled "indicative, not authoritative", and an empty database says
so and tells you how to build it (`salary import-lca`, `salary
parse-range`) instead of guessing. The notes also remind you that the
underlying data skews toward larger employers and disclosed postings, not
the whole market.

## For IC-to-EM switchers

If you have never held a manager title, run `em reframe` first. It will
show you exactly which scope dimensions your resume evidences and which
are missing. The typical high-leverage fixes, in order:

1. Add team sizes to every role where you led people ("team of N").
2. Add hiring evidence ("hired N", "interviewed N candidates").
3. Add mentoring with outcomes ("mentored N engineers; M promoted").
4. Name cross-team partnerships and the alignment you drove.
5. Add delivery-ownership signals (who set the roadmap, ran planning,
   made the prioritization calls).

Then re-run `em reframe` to confirm the gaps closed, and use `em salary`
to calibrate your ask before negotiations.
