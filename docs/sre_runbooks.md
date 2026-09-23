# SRE Runbooks (`candid sre`)

Three DevOps/SRE practice tools, wired under one `sre` command group.
All content is static and local: no network calls, no API keys.

## 1. Troubleshooting playbooks

```
python -m candid sre playbook disk-full
python -m candid sre playbook oomkilled --export /tmp/oom.md
```

Six incidents ship with playbooks: `disk-full`, `oomkilled`, `tls-expiry`,
`latency-spike`, `bad-deploy`, `dns-failure`. Each playbook covers symptoms,
ordered diagnosis steps, common root causes, the fix, verification, and
prevention. `--export FILE.md` saves the markdown instead of printing it.

## 2. Blameless postmortems

Interactive:

```
python -m candid sre postmortem
```

You are prompted for summary, impact, timeline, root cause, what went well,
what went poorly, and action items (each with an owner). The postmortem is
rendered as markdown and saved to `candid_data/sre_postmortems/`.

From a notes file:

```
python -m candid sre postmortem --from-notes notes.txt
```

The notes file accepts `## Section` headers or `Key: value` lines. Known
sections: Summary, Impact, Timeline, Root Cause, What went well,
What went poorly, Action items (one per line, `owner: task`).

Before saving, the text is checked for blame language (e.g. "his fault",
"blame the on-call"). Any hits are printed as warnings so you can reword
around systems and process before sharing. The postmortem itself never names
individuals as causes.

## 3. IaC review drill

```
python -m candid sre iac-review
python -m candid sre iac-review --difficulty medium
python -m candid sre iac-review --index 2 --answers
```

You are shown a Terraform or Kubernetes YAML snippet containing 2-4 realistic
misconfigurations (open security groups, `:latest` tags, missing resource
limits, no health probes, unencrypted volumes, privileged pods, secrets in
ConfigMaps, and more). List the issues you spot, one per line, then get a
score and the answer key with explanations.

- `--difficulty easy|medium` filters the 10 snippets.
- `--index N` picks a snippet deterministically (0-based).
- `--answers` is the non-interactive mode: prints the snippet and the answer
  key, used by tests and scripts.

## Module API

All logic lives in `candid/sre_runbooks.py` as pure functions, so tests and
other tooling can call them directly:

- `list_incidents()`, `render_playbook(incident)`, `export_playbook(incident, dest)`
- `parse_notes(text)`, `render_postmortem(data)`, `save_postmortem(data)`,
  `check_blameless(data)`, `prompt_postmortem()`
- `list_snippets(difficulty)`, `get_snippet(index, difficulty)`,
  `render_challenge(snippet)`, `render_answers(snippet)`,
  `match_issues(snippet, user_text)`, `run_drill(snippet, answers)`
- `register(subparsers)` adds the `playbook`, `postmortem`, `iac-review`
  subcommands; `dispatch(args)` routes on `args.sre_cmd`.
