"""Skills normalizer: alias map so match scoring stops missing aliases.

``k8s`` = Kubernetes, ``js`` = JavaScript, ``ts`` = TypeScript,
``py`` = Python, ``tf`` = TensorFlow, ``ml`` = machine learning, ...

The map lives in ``candid/data/skill_aliases.json`` (committed, editable).
``canonical(term)`` normalizes any term to its canonical skill name; terms
not in the map are returned unchanged (lowercased/stripped).

Matching is bidirectional: a JD term and a profile term match when they
normalize to the same canonical name. Aliases only ADD matches — they
never remove ones the plain matcher already found.

Deliberately conservative: aliases that are common English words (``go``,
``ai`` as a bare word, ``cv``) are NOT in the map, because they would
match ordinary prose and create false positives. See docs/skills.md.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_ALIAS_FILE = Path(__file__).resolve().parent / "data" / "skill_aliases.json"


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    """Load the alias map: alias (lowercased) -> canonical (lowercased)."""
    try:
        raw = json.loads(_ALIAS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.get("aliases", {}).items():
        key = str(k).strip().lower()
        if not key or key.startswith("_"):
            continue
        out[key] = str(v).strip().lower()
    return out


def aliases() -> dict[str, str]:
    """A copy of the current alias map."""
    return dict(load_aliases())


def canonical(term: str) -> str:
    """Return the canonical skill name for ``term``.

    Exact (case-insensitive) alias lookup only — never substring matching,
    so ``py`` normalizes but ``happy`` does not. Alias chains resolve
    transitively (``k8s`` -> ``kubernetes`` -> ``mlops``), with cycle
    protection. Unknown terms are returned as-is (lowercased, stripped).
    """
    t = (term or "").strip().lower()
    amap = load_aliases()
    seen: set[str] = set()
    while t in amap and t not in seen:
        seen.add(t)
        t = amap[t]
    return t


def normalize_skill_list(skills: list[str]) -> set[str]:
    """Canonicalize a list of skill names (profile or JD side)."""
    return {canonical(s) for s in skills or []}
