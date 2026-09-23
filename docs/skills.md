# Skills normalizer: the alias map

`match` scoring used to miss obvious aliases: a JD asking for **k8s**
wouldn't match a profile listing **Kubernetes**, and vice versa. The
skills normalizer fixes that with a plain JSON alias map.

## Where it lives

- Data: `candid/data/skill_aliases.json` — committed, human-editable.
  Format: `{"aliases": {"k8s": "kubernetes", "js": "javascript", ...}}`.
- Loader: `candid/skills.py` — `canonical(term)` normalizes any term to
  its canonical name (case-insensitive, exact match only, alias chains
  resolve transitively: `k8s` → `kubernetes` → `mlops`).

## How it's applied

Matching is **bidirectional**: a JD term and a profile term match when
they normalize to the same canonical name.

- JD says "k8s", profile says "Kubernetes" → match.
- JD says "Kubernetes" (a lexicon alias of "mlops"), profile skill is
  literally "k8s" → match.
- JD says "JS", profile says "JavaScript" → match.

**Aliases only add matches, never remove.** The section-weighted scoring
in `candid/match.py` is untouched; the alias check is an extra
normalization step on top of the existing exact matching. The tailored
resume's ATS keyword check (`candid/tailor.py`) is alias-aware the same
way.

## Adding your own aliases

Edit `candid/data/skill_aliases.json` and add entries to `"aliases"`:

```json
"aliases": {
  "k8s": "kubernetes",
  "myterm": "canonical-skill-name"
}
```

Rules:

1. **Keys are matched exactly** (case-insensitive), never as substrings —
   `"py": "python"` normalizes the token `py` but never touches `happy`.
2. **Never add an alias that is a common English word.** `go`, `ai`, `cv`,
   `it`, `us` are deliberately absent: "go" the verb would match "Go" the
   language everywhere, "CV" appears in every JD's "send your CV" line.
   This is the false-positive guardrail — short aliases are only safe when
   they are unambiguous tech tokens (`py`, `js`, `ts`, `tf`, `k8s`).
3. Values are canonical names; they can themselves be aliases (chains
   resolve), but avoid cycles.
4. No restart needed — the file is read at import time.

## Checking your changes

```bash
python3 -c "
from candid import skills as SK
print(SK.canonical('k8s'))   # expect: mlops (via kubernetes)
print(SK.canonical('myterm'))  # expect: canonical-skill-name
"
```

And run the alias tests: `python3 -m pytest tests/test_match_boost.py -q`.
