# Career-switcher track (`candid switch`)

Ten subcommands for people changing roles or industries. Everything is
deterministic, offline, and grounded: content is built strictly from your
profile and the facts you supply. Missing facts become explicit
`[PLACEHOLDER]` markers — candid never invents experience.

Inputs are JSON files or flags; run `python -m candid switch <sub> --help`
for exact usage.

| Subcommand | What it does |
|---|---|
| `switch skills` | Map your profile skills to a target role's requirements (`direct` / `adjacent` / `foundational`), with verbatim evidence from your profile. Alias-aware (`k8s` -> Kubernetes). |
| `switch readiness` | 0-100 readiness score: coverage (50) + gap control (30) + adjacent experience (20), letter grade, top gaps, quick wins. |
| `switch reframe` | Reframe resume bullets through the target role's lens. The bullet text is preserved verbatim; only the competency framing prefix changes. |
| `switch pivot-resume` | Competency-led pivot resume (Markdown): "Relevant capabilities" grouped by competency, condensed work history, skills, education. |
| `switch plan` | Week-by-week gap-closing study plan from free resources (official docs, freeCodeCamp, MIT OCW, Kaggle Learn, etc.), each week with a proof-of-learning deliverable. |
| `switch signals` | Score companies for switcher-friendliness from job text (career-change, returnship, apprenticeship, bootcamp-friendly signals). |
| `switch interview` | Classic switcher questions ("Why are you switching?", "How will you ramp up?") with hook-bridge-proof-close frameworks; draft answers from your facts only. |
| `switch stories` | Re-angle a STAR story toward the target role, tagging competencies from a fixed taxonomy. |
| `switch letter` | An honest "why the switch" cover-letter paragraph (draft only, never sent). |
| `switch ramp` | A 30-60-90 ramp plan (Learn / Contribute / Own) with goals, questions, relationships, and success metrics; your known gaps become explicit learning goals. |

Example:

```bash
python -m candid switch readiness \
  --requirements-file reqs.json --years-adjacent 3 \
  --target-role "Product Manager"
python -m candid switch plan --gaps-file gaps.json \
  --target-role "Product Manager" --weeks 8
```
