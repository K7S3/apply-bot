# Pull request

## What this changes
Describe the change in one or two paragraphs. Link related issues with `Fixes #123` or `Closes #123`.

## Why
What problem does this solve, or what does it enable? Keep it short.

## How tested
List the exact commands you ran and their results.

- `python -m pytest` : (e.g. 214 passed, 0 failed)
- Other commands: (e.g. `python -m candid match --help`)

## Docs updated
- [ ] README feature table / usage docs updated (if the change alters CLI behavior)
- [ ] docs/ page updated (if the change alters a documented workflow)
- [ ] CONTRIBUTING.md updated (if the change alters contributor workflow)

## Checklist
- [ ] No secrets, credentials, or personal data committed (no PII, no API keys, no tokens)
- [ ] No changes to `profile.yaml`, `output/`, or `run_ollama_shim.py`
- [ ] Tests added for new features (or an explanation of why none were needed)
- [ ] Full test suite is green (`python -m pytest`)
