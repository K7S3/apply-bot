# candid doctor

`python -m candid doctor` runs environment diagnostics and prints one
`[PASS]` / `[WARN]` / `[FAIL]` line per check, with a one-line `Fix:`
suggestion on failures. Exit code is **0 when nothing FAILs, 1 otherwise**,
so you can gate scripts on it.

## Checks

| Check | FAIL when | Fix hint |
|---|---|---|
| `python-version` | Python < 3.10 | install Python 3.10+ |
| `data-dir` | `candid_data/` missing | `python -m candid onboard --resume <file>` |
| `data-dir-writable` | data dir not writable | check permissions |
| `profile-json` | missing or invalid JSON | `python -m candid onboard --resume <file>` |
| `tracker-json` | invalid JSON | repair or re-create via `track add` |
| `samples-dir` | repo samples missing | reinstall (optional data) |
| `config-dir-writable` | config dir not writable | check permissions / set `CANDID_CONFIG_DIR` |
| `ollama` | never FAILs | WARN only: local LLM features skipped |
| `disk-space` | never FAILs | WARN only when < 100 MB free |

`ollama` and `disk-space` are advisory by design: candid is fully usable
without a local LLM, and low disk space deserves a nudge, not a hard stop.

Ollama is probed with a 2-second HTTP GET to `localhost:11434/api/tags`
(stdlib only, no dependency).

## Usage

```bash
python -m candid doctor
python -m candid doctor --json   # machine-readable
```

Example output:

```
[PASS] python-version: 3.11.4 (meets minimum 3.10)
[FAIL] profile-json: /home/you/candid_data/profile.json is missing
         Fix: Run `python -m candid onboard --resume <path-to-resume>` to build your profile.
[WARN] ollama: not reachable at localhost:11434
         Fix: Local LLM features will be skipped. To enable them, start Ollama with `ollama serve` ...

doctor: 7 PASS, 1 WARN, 1 FAIL
```

`--json` emits:

```json
{
  "ok": false,
  "summary": {"pass": 7, "warn": 1, "fail": 1},
  "checks": [
    {"name": "python-version", "status": "PASS", "detail": "..."},
    {"name": "profile-json", "status": "FAIL", "detail": "...", "fix": "..."}
  ]
}
```

## Python API (for other modules)

```python
from candid import doctor

checks = doctor.run_checks()      # list[Check]: name, status, detail, fix
code = doctor.render_text(checks)  # 0/1
code = doctor.render_json(checks)  # 0/1
```

Verify with:

```bash
python3 -m candid doctor
python3 -m candid doctor --json | python3 -c "import json,sys; print(json.load(sys.stdin)['ok'])"
```
