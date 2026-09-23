# Contexts (config profiles)

A **context** is a named bundle of candid settings: the tone and length you
want for tailored output, the score threshold for curating jobs, how deep
interview prep goes, and so on. Instead of repeating the same flags on every
command, you save them once as a context (say `faang-mle`) and switch to it
with one command. Contexts live in `candid_data/contexts.json` on your
machine, never in the repo.

```bash
# Start from a built-in preset, switch to it, tweak one key
python -m candid ctx init faang-mle --as faang
python -m candid ctx use faang
python -m candid ctx set tailor.tone warm
```

## Why contexts

Different job hunts want different defaults. A FAANG MLE hunt cares about
deep prep and a confident tone; a spray-and-pray internship hunt wants a
lower match threshold and quick prep. Contexts keep those hunts separate so
you don't accidentally run one with the other's settings.

## Quickstart

```bash
# 1. See the built-in presets
python -m candid ctx presets

# 2. Create a context from a preset (or from scratch)
python -m candid ctx init faang-mle --as faang-mle
python -m candid ctx create my-newgrad

# 3. Switch to it, check what's active, toggle back
python -m candid ctx use faang-mle
python -m candid ctx current
python -m candid ctx use -        # back to the previous context

# 4. Read and tweak settings
python -m candid ctx show
python -m candid ctx show --resolved   # see inherited values resolved
python -m candid ctx set match.min_score 60
python -m candid ctx unset match.min_score
```

All commands are `python -m candid ctx <command> --help`.

## How settings resolve: precedence

When a command needs a value (say `match.min_score`), the winner is the
first one that provides it, top to bottom:

| Priority | Source | Example |
|---|---|---|
| 1 | Explicit CLI flag | `match --min-score 50` |
| 2 | Per-company override for the active company | `ctx company set Acme match.min_score 55` |
| 3 | Active context's own settings | `ctx set match.min_score 60` |
| 4 | Inherited settings from parent contexts | `extends` chain, child wins |
| 5 | Built-in defaults | `match.min_score = 50` |
| 6 | The command's own fallback | e.g. hard-coded behavior when nothing is set |

**Environments variables.** `CANDID_CTX` selects the active context,
`CANDID_CTX_COMPANY` sets the company scope (so per-company overrides apply
without passing `--company` everywhere), and `CANDID_CTX_FILE` points at an
alternate contexts file instead of `candid_data/contexts.json`. CLI flags
always beat environment variables, because env vars only choose *which*
context/company is active, not individual values.

## Inheritance: `extends`

A context can extend another. The child inherits every parent setting and
overrides only what it sets itself. Chains can be as deep as you like, and
the child always wins on conflicts.

```bash
# A senior variant of your FAANG context: same everything, deeper prep
python -m candid ctx create faang-senior --extends faang-mle
python -m candid ctx set prep.depth deep
```

`ctx show --resolved` prints the effective settings after walking the whole
chain, which is the fastest way to sanity-check an override. If a parent is
renamed or deleted, `ctx validate` flags the dangling reference; cycles
(A extends B extends A) are rejected by `ctx validate` and by `ctx set` when
you create them.

## Per-company overrides

Some companies deserve special treatment: a dream company gets a lower
threshold so nothing is filtered out, a reach gets your most formal tone.
Overrides live *inside* the active context, keyed by company name.

```bash
# Inside context "faang-mle": treat "Acme Corp" specially
python -m candid ctx company set "Acme Corp" match.min_score 45
python -m candid ctx company set "Acme Corp" tailor.tone formal
python -m candid ctx company list            # what's overridden, and where
python -m candid ctx company unset "Acme Corp" tailor.tone
```

Overrides apply when the active company matches (via `--company` on the
command or `CANDID_CTX_COMPANY`). Everything not overridden falls back to
the context's normal settings.

## Known settings keys

These are the settings candid commands actually read today. You can `set`
any dotted key; keys outside this list are stored but ignored until a
command uses them (`ctx validate` warns about them).

| Key | Type | Meaning |
|---|---|---|
| `match.min_score` | int | Minimum score for `match` verdicts and tracker gating |
| `tailor.tone` | concise\|confident\|formal\|warm | Tone of tailored resume and cover letter |
| `tailor.length` | one-page\|detailed | Length of tailored output |
| `jobs.sources` | list | Which feeds `jobs curate` reads |
| `jobs.days` | int | Recency window (days) for `jobs curate` |
| `jobs.remote_only` | bool | Curate remote postings only |
| `jobs.min_score` | int | Minimum score before a curated job is saved to the tracker |
| `prep.depth` | quick\|standard\|deep | Interview prep pack depth |
| `nudges.stale_days` | int | Days before an application counts as stale |
| `nudges.followup_days` | int | Days before a follow-up nudge fires |
| `salary.location` | str | Default worksite for salary lookups |
| `dashboard.default_view` | funnel\|list\|kanban | Default dashboard layout |

## Built-in presets

`ctx init <preset>` seeds a context from one of these; `--as NAME` renames
it so the stock preset stays untouched.

| Preset | Meant for |
|---|---|
| `faang-mle` | FAANG-style MLE roles: confident tone, deep prep, selective thresholds |
| `startup-fullstack` | Startup full-stack roles: warm tone, broader sourcing, quicker prep |
| `data-scientist` | Data science roles: formal tone, detailed output, standard prep |
| `backend-generalist` | General backend roles: concise tone, balanced defaults |
| `new-grad` | New-grad hunts: warm tone, lower score thresholds, standard prep |

```bash
python -m candid ctx init startup-fullstack --as my-startup-hunt
python -m candid ctx use my-startup-hunt
```

## Company role context

A context can also carry a default *role* (job title) so you stop typing
`--role` everywhere:

```bash
python -m candid ctx role set "Senior ML Engineer"
python -m candid ctx role show
```

## Comparing and validating

```bash
python -m candid ctx diff faang-mle new-grad   # what differs, side by side
python -m candid ctx validate                  # check all contexts
python -m candid ctx validate faang-mle        # check one
```

`validate` reports unknown setting keys, references to missing parents,
inheritance cycles, and per-company overrides whose company name doesn't
match any tracked application (a hint, not an error: the company may just
not be in your tracker yet).

## Export, import, sharing

Contexts are plain JSON, easy to share with a friend or back up:

```bash
python -m candid ctx export faang-mle --out ~/faang-mle.json
python -m candid ctx import ~/faang-mle.json --as faang-mle-v2
```

`import` without `--as` keeps the name stored in the file. If a context with
that name already exists, `import` refuses to overwrite unless you pick a
new name with `--as`.

## Renaming and deleting

```bash
python -m candid ctx rename faang-mle faang
python -m candid ctx delete old-experiment
```

Renaming updates every child that extends the renamed context. Deleting a
context that still has children fails with an error naming the children;
rename or re-parent them first.

## Troubleshooting

- **"context not found"**: check spelling with `ctx list`; `CANDID_CTX`
  may be pointing at a name that doesn't exist. Unset it to go back to no
  active context (built-in defaults everywhere).
- **Inheritance cycle**: `ctx validate` names the cycle (A -> B -> A).
  Fix with `ctx delete` or by re-creating one link with a different
  `--extends`.
- **Dangling parent**: you deleted or renamed a parent. `ctx validate`
  flags the child; recreate the parent or point the child elsewhere.
- **Setting not taking effect**: run `ctx show --resolved` and check the
  precedence table. An explicit CLI flag or a per-company override for the
  active company beats the context setting. Also check `CANDID_CTX_COMPANY`:
  it may be scoping you to a company you forgot about.
- **Validation warnings about unknown keys**: the key is stored but no
  command reads it yet. Either fix the typo (`tailor.ton` -> `tailor.tone`)
  or wait for a command that uses it.
- **Alternate file**: `CANDID_CTX_FILE` points at a different JSON file.
  Make sure it exists and is valid JSON; commands error clearly if it can't
  be parsed.
