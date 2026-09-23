"""Named configuration contexts for candid.

A context bundles per-setting defaults (match/tailor/jobs/prep/nudges/
salary/dashboard) under a name like "faang-mle", with optional
inheritance (extends), per-company overrides, and env-var layering
(CANDID_CTX, CANDID_CTX_COMPANY).

Storage: ``config.DATA_DIR / "contexts.json"`` (or ``CANDID_CTX_FILE``
for an alternate file), shaped as::

    {"active": str|None, "previous": str|None,
     "contexts": {name: {"role": str, "extends": str|None,
                         "settings": {...}, "companies": {company: {...}}}}}

``config.DATA_DIR`` is read dynamically so tests can monkeypatch it.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from candid import config

__all__ = [
    "CONTEXTS_PATH",
    "KNOWN_KEYS",
    "DEFAULTS",
    "BUILTIN_PRESETS",
    "get_store",
    "ContextStore",
    "resolve_context",
    "effective_company",
    "ctx_value",
    "coerce_value",
    "diff_contexts",
    "validate_context",
    "validate_all",
    "list_presets",
    "init_from_preset",
    "export_context",
    "import_context",
]

# --- known settings -----------------------------------------------------------

KNOWN_KEYS: dict[str, dict] = {
    "match.min_score": {
        "type": "int",
        "default": 0,
        "choices": None,
        "desc": "Minimum match score (0-100) for a job to be worth tailoring.",
    },
    "tailor.tone": {
        "type": "str",
        "default": "confident",
        "choices": ["concise", "confident", "formal", "warm"],
        "desc": "Voice used when tailoring resumes and cover letters.",
    },
    "tailor.length": {
        "type": "str",
        "default": "one-page",
        "choices": ["one-page", "detailed"],
        "desc": "Resume length target.",
    },
    "jobs.sources": {
        "type": "list[str]",
        "default": [],
        "choices": None,
        "desc": "Job sources to query.",
    },
    "jobs.days": {
        "type": "int",
        "default": 30,
        "choices": None,
        "desc": "How many days back to search for jobs.",
    },
    "jobs.remote_only": {
        "type": "bool",
        "default": False,
        "choices": None,
        "desc": "Only consider remote jobs.",
    },
    "jobs.min_score": {
        "type": "int",
        "default": 0,
        "choices": None,
        "desc": "Minimum match score to surface a job in results.",
    },
    "prep.depth": {
        "type": "str",
        "default": "standard",
        "choices": ["quick", "standard", "deep"],
        "desc": "Depth of interview prep packs.",
    },
    "nudges.stale_days": {
        "type": "int",
        "default": 14,
        "choices": None,
        "desc": "Days without activity before an application is stale.",
    },
    "nudges.followup_days": {
        "type": "int",
        "default": 7,
        "choices": None,
        "desc": "Days after applying before a follow-up nudge.",
    },
    "salary.location": {
        "type": "str",
        "default": "",
        "choices": None,
        "desc": "Default location for salary lookups.",
    },
    "dashboard.default_view": {
        "type": "str",
        "default": "funnel",
        "choices": ["funnel", "list", "kanban"],
        "desc": "Default dashboard view.",
    },
}

DEFAULTS: dict[str, object] = {
    key: copy.deepcopy(spec["default"]) for key, spec in KNOWN_KEYS.items()
}

# --- builtin presets ----------------------------------------------------------

BUILTIN_PRESETS: dict[str, dict] = {
    "faang-mle": {
        "role": "Machine Learning Engineer",
        "extends": None,
        "settings": {
            "tailor.tone": "confident",
            "tailor.length": "one-page",
            "match.min_score": 70,
            "jobs.min_score": 60,
            "jobs.remote_only": False,
            "prep.depth": "deep",
            "nudges.stale_days": 7,
            "salary.location": "New York, NY",
        },
        "companies": {},
    },
    "startup-fullstack": {
        "role": "Full-Stack Engineer",
        "extends": None,
        "settings": {
            "tailor.tone": "concise",
            "match.min_score": 60,
            "jobs.remote_only": True,
            "prep.depth": "standard",
            "nudges.stale_days": 5,
        },
        "companies": {},
    },
    "data-scientist": {
        "role": "Data Scientist",
        "extends": None,
        "settings": {
            "tailor.tone": "formal",
            "match.min_score": 65,
            "prep.depth": "deep",
            "salary.location": "New York, NY",
        },
        "companies": {},
    },
    "backend-generalist": {
        "role": "Backend Engineer",
        "extends": None,
        "settings": {
            "tailor.tone": "confident",
            "match.min_score": 60,
            "prep.depth": "standard",
        },
        "companies": {},
    },
    "new-grad": {
        "role": "Software Engineer",
        "extends": None,
        "settings": {
            "tailor.tone": "warm",
            "match.min_score": 50,
            "jobs.days": 60,
            "prep.depth": "deep",
        },
        "companies": {},
    },
}


def list_presets() -> list[str]:
    """Names of the builtin presets."""
    return sorted(BUILTIN_PRESETS)


# --- storage path (dynamic: honors monkeypatched config.DATA_DIR) -------------


def _contexts_path() -> Path:
    override = os.environ.get("CANDID_CTX_FILE")
    if override:
        return Path(override).expanduser()
    return config.DATA_DIR / "contexts.json"


def __getattr__(name: str):
    # CONTEXTS_PATH is computed dynamically so tests can monkeypatch
    # candid.config.DATA_DIR (or set CANDID_CTX_FILE) and see the new path.
    if name == "CONTEXTS_PATH":
        return _contexts_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_store(path=None) -> "ContextStore":
    """Open a ContextStore. ``path`` defaults to the dynamic contexts file."""
    return ContextStore(path)


# --- store ---------------------------------------------------------------------


def _blank_data() -> dict:
    return {"active": None, "previous": None, "contexts": {}}


class ContextStore:
    """CRUD + active/previous bookkeeping for contexts.json."""

    def __init__(self, path=None):
        self._path = Path(path).expanduser() if path is not None else _contexts_path()
        self._data = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict:
        if not self._path.exists():
            return _blank_data()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"contexts file {self._path} is not a JSON object")
        merged = _blank_data()
        merged.update({k: v for k, v in data.items() if k in merged})
        if not isinstance(merged["contexts"], dict):
            raise ValueError(f"contexts file {self._path} has a bad 'contexts' entry")
        return merged

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _refresh(self) -> None:
        """Reload from disk so the store is never stale.

        CLI commands run as separate processes, but tests and future
        in-process flows may mix store instances; always read fresh.
        """
        self._data = self._load()

    def _require(self, name: str) -> dict:
        try:
            return self._data["contexts"][name]
        except KeyError:
            raise KeyError(f"unknown context: {name!r}") from None

    # -- reads ----------------------------------------------------------

    def list_names(self) -> list[str]:
        self._refresh()
        return sorted(self._data["contexts"])

    def exists(self, name: str) -> bool:
        self._refresh()
        return name in self._data["contexts"]

    def get(self, name: str) -> dict:
        self._refresh()
        """Raw context dict. Raises KeyError if missing."""
        return copy.deepcopy(self._require(name))

    def companies(self, name: str) -> list[str]:
        self._refresh()
        return sorted(self._require(name).get("companies", {}))

    def active_name(self) -> str | None:
        self._refresh()
        """CANDID_CTX wins if it names an existing context, else stored active."""
        env = os.environ.get("CANDID_CTX", "").strip()
        if env and env in self._data["contexts"]:
            return env
        return self._data.get("active")

    # -- writes ---------------------------------------------------------

    def create(
        self,
        name,
        *,
        role: str = "",
        extends=None,
        settings: dict | None = None,
        companies: dict | None = None,
        overwrite: bool = False,
    ) -> dict:
        self._refresh()
        if not name or not str(name).strip():
            raise ValueError("context name must be a non-empty string")
        name = str(name)
        if name in self._data["contexts"] and not overwrite:
            raise ValueError(f"context {name!r} already exists")
        if extends is not None and not str(extends).strip():
            extends = None
        entry = {
            "role": role or "",
            "extends": extends,
            "settings": copy.deepcopy(settings or {}),
            "companies": copy.deepcopy(companies or {}),
        }
        _check_jsonable(entry)
        self._data["contexts"][name] = entry
        self._save()
        return copy.deepcopy(entry)

    def delete(self, name: str) -> None:
        self._refresh()
        self._require(name)
        del self._data["contexts"][name]
        # Fix pointers that referenced the deleted context.
        if self._data.get("active") == name:
            self._data["active"] = None
        if self._data.get("previous") == name:
            self._data["previous"] = None
        self._save()

    def rename(self, old: str, new: str) -> None:
        self._refresh()
        if old == new:
            self._require(old)
            return
        entry = self._require(old)
        if not new or not str(new).strip():
            raise ValueError("new context name must be a non-empty string")
        if new in self._data["contexts"]:
            raise ValueError(f"context {new!r} already exists")
        del self._data["contexts"][old]
        self._data["contexts"][str(new)] = entry
        # Rewrite extends references pointing at the old name.
        for other in self._data["contexts"].values():
            if other.get("extends") == old:
                other["extends"] = str(new)
        if self._data.get("active") == old:
            self._data["active"] = str(new)
        if self._data.get("previous") == old:
            self._data["previous"] = str(new)
        self._save()

    def set_active(self, name: str) -> None:
        self._refresh()
        self._require(name)
        self._data["previous"] = self._data.get("active")
        self._data["active"] = name
        self._save()

    def toggle_previous(self) -> str | None:
        self._refresh()
        """Switch to the previous context. No-op returning current if none."""
        prev = self._data.get("previous")
        cur = self._data.get("active")
        if not prev or prev == cur or prev not in self._data["contexts"]:
            return cur
        self._data["previous"] = cur
        self._data["active"] = prev
        self._save()
        return prev

    def set_value(self, name: str, key: str, value) -> None:
        self._refresh()
        entry = self._require(name)
        _check_jsonable(value)
        entry.setdefault("settings", {})[key] = copy.deepcopy(value)
        self._save()

    def unset_value(self, name: str, key: str) -> None:
        self._refresh()
        entry = self._require(name)
        entry.get("settings", {}).pop(key, None)
        self._save()

    def set_company_value(self, name: str, company: str, key: str, value) -> None:
        self._refresh()
        entry = self._require(name)
        _check_jsonable(value)
        companies = entry.setdefault("companies", {})
        companies.setdefault(company, {})[key] = copy.deepcopy(value)
        self._save()

    def unset_company_value(self, name: str, company: str, key: str) -> None:
        self._refresh()
        entry = self._require(name)
        companies = entry.get("companies", {})
        overrides = companies.get(company)
        if overrides is not None:
            overrides.pop(key, None)
            if not overrides:
                del companies[company]
        self._save()


def _check_jsonable(value) -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not JSON-serializable: {exc}") from None


# --- resolution ----------------------------------------------------------------


def resolve_context(name=None, _seen=()) -> dict:
    """Resolve a context along its extends chain.

    Returns ``{"name", "role", "extends", "settings", "companies"}`` with
    settings and per-company overrides deep-merged parent-first (child
    wins). ``name=None`` resolves the active context. Raises KeyError if
    the context (or active) is missing, ValueError on a missing parent or
    an inheritance cycle.
    """
    store = get_store()
    if name is None:
        name = store.active_name()
        if name is None:
            raise KeyError("no active context")
    if name in _seen:
        chain = " -> ".join([*_seen, name])
        raise ValueError(f"inheritance cycle detected: {chain}")
    raw = store.get(name)  # KeyError if missing
    parent = raw.get("extends")
    if parent:
        if not store.exists(parent):
            raise ValueError(f"context {name!r} extends unknown context {parent!r}")
        base = resolve_context(parent, _seen + (name,))
        settings = {**base["settings"], **raw.get("settings", {})}
        companies: dict[str, dict] = {}
        for comp in set(base["companies"]) | set(raw.get("companies", {})):
            merged = dict(base["companies"].get(comp, {}))
            merged.update(raw.get("companies", {}).get(comp, {}))
            companies[comp] = merged
        role = raw.get("role") or base["role"]
    else:
        settings = dict(raw.get("settings", {}))
        companies = copy.deepcopy(raw.get("companies", {}))
        role = raw.get("role", "")
    return {
        "name": name,
        "role": role,
        "extends": raw.get("extends"),
        "settings": settings,
        "companies": companies,
    }


def effective_company() -> str | None:
    """Company from CANDID_CTX_COMPANY, stripped; None if empty/unset."""
    value = os.environ.get("CANDID_CTX_COMPANY", "").strip()
    return value or None


def ctx_value(key, default=None, *, company=None, context=None):
    """Read one setting with full layering.

    Precedence: per-company override (``company`` arg or CANDID_CTX_COMPANY)
    > resolved context settings > inherited (already merged into resolved)
    > DEFAULTS[key] > ``default`` arg. Unknown context names fall back to
    DEFAULTS/default instead of raising.
    """
    if company is None:
        company = effective_company()
    resolved = None
    try:
        resolved = resolve_context(context)
    except KeyError:
        resolved = None
    if resolved is not None:
        if company:
            overrides = resolved["companies"].get(company, {})
            if key in overrides:
                return copy.deepcopy(overrides[key])
        if key in resolved["settings"]:
            return copy.deepcopy(resolved["settings"][key])
    if key in DEFAULTS:
        return copy.deepcopy(DEFAULTS[key])
    return default


# --- coercion / validation -------------------------------------------------------


_BOOL_TRUE = {"true", "1", "yes"}
_BOOL_FALSE = {"false", "0", "no"}


def coerce_value(key, raw: str):
    """Parse a CLI string per KNOWN_KEYS type; comma-separated for lists.

    Bools accept true/false/1/0/yes/no. Validates choices.
    Raises ValueError on unknown keys or bad input.
    """
    spec = KNOWN_KEYS.get(key)
    if spec is None:
        raise ValueError(f"unknown setting key: {key!r}")
    type_name = spec["type"]
    text = raw.strip() if isinstance(raw, str) else raw
    try:
        if type_name == "int":
            value = int(text)
        elif type_name == "float":
            value = float(text)
        elif type_name == "bool":
            lowered = str(text).strip().lower()
            if lowered in _BOOL_TRUE:
                value = True
            elif lowered in _BOOL_FALSE:
                value = False
            else:
                raise ValueError(f"not a bool: {raw!r}")
        elif type_name == "list[str]":
            value = [part.strip() for part in str(text).split(",") if part.strip()]
        else:  # str
            value = str(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"cannot parse {raw!r} as {type_name} for {key!r}") from exc
    choices = spec.get("choices")
    if choices and value not in choices:
        raise ValueError(
            f"invalid value {value!r} for {key!r}; choices: {', '.join(choices)}"
        )
    return value


def _type_ok(type_name: str, value) -> bool:
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "list[str]":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    return False


def _check_settings(mapping: dict, where: str, errors: list[str]) -> None:
    for key, value in mapping.items():
        spec = KNOWN_KEYS.get(key)
        if spec is None:
            errors.append(f"{where}: unknown setting key {key!r}")
            continue
        if not _type_ok(spec["type"], value):
            errors.append(
                f"{where}: {key!r} should be {spec['type']}, "
                f"got {type(value).__name__}"
            )
            continue
        choices = spec.get("choices")
        if choices and value not in choices:
            errors.append(
                f"{where}: {key!r} has invalid value {value!r}; "
                f"choices: {', '.join(choices)}"
            )


def validate_context(name: str) -> list[str]:
    """Error strings for a context: unknown keys, wrong types, bad choices,
    missing extends target, cycles. Empty list means clean."""
    store = get_store()
    raw = store.get(name)  # KeyError if missing
    errors: list[str] = []
    role = raw.get("role", "")
    if not isinstance(role, str):
        errors.append(f"{name!r}: role should be a string")
    parent = raw.get("extends")
    if parent is not None:
        if not isinstance(parent, str):
            errors.append(f"{name!r}: extends should be a string or null")
        elif not store.exists(parent):
            errors.append(f"{name!r}: extends unknown context {parent!r}")
        else:
            # Walk the chain for cycles.
            seen = {name}
            cursor = parent
            while cursor:
                if cursor in seen:
                    errors.append(
                        f"{name!r}: inheritance cycle involving {cursor!r}"
                    )
                    break
                seen.add(cursor)
                cursor = store.get(cursor).get("extends")
    _check_settings(raw.get("settings", {}), f"{name!r} settings", errors)
    for company, overrides in raw.get("companies", {}).items():
        if not isinstance(overrides, dict):
            errors.append(f"{name!r}: company {company!r} overrides must be an object")
            continue
        _check_settings(overrides, f"{name!r} company {company!r}", errors)
    return errors


def validate_all() -> dict[str, list[str]]:
    """Map every context name to its validation error list."""
    store = get_store()
    return {name: validate_context(name) for name in store.list_names()}


# --- diff ------------------------------------------------------------------------


def diff_contexts(a: str, b: str) -> list[tuple]:
    """Sorted [(key, val_a, val_b)] over differing resolved settings keys.

    Uses None for a side where the key is missing.
    """
    ra = resolve_context(a)
    rb = resolve_context(b)
    out = []
    for key in set(ra["settings"]) | set(rb["settings"]):
        va = ra["settings"].get(key)
        vb = rb["settings"].get(key)
        if va != vb:
            out.append((key, copy.deepcopy(va), copy.deepcopy(vb)))
    return sorted(out, key=lambda item: item[0])


# --- presets / import / export -----------------------------------------------------


def init_from_preset(preset: str, name=None, *, overwrite: bool = False) -> str:
    """Create a context from a builtin preset. Returns the context name."""
    try:
        spec = BUILTIN_PRESETS[preset]
    except KeyError:
        raise KeyError(f"unknown preset: {preset!r}") from None
    name = name or preset
    get_store().create(
        name,
        role=spec.get("role", ""),
        extends=spec.get("extends"),
        settings=spec.get("settings", {}),
        companies=spec.get("companies", {}),
        overwrite=overwrite,
    )
    return name


def export_context(name: str, path) -> Path:
    """Write a context to JSON (raw, inheritance preserved). Returns Path."""
    store = get_store()
    raw = store.get(name)  # KeyError if missing
    payload = {
        "name": name,
        "role": raw.get("role", ""),
        "extends": raw.get("extends"),
        "settings": raw.get("settings", {}),
        "companies": raw.get("companies", {}),
    }
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def import_context(path, name=None, *, overwrite: bool = False) -> str:
    """Read an exported context file and create it. Returns the context name."""
    target = Path(path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read context file {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"context file {target} is not a JSON object")
    name = name or payload.get("name")
    if not name or not str(name).strip():
        raise ValueError(f"context file {target} has no usable name")
    settings = payload.get("settings", {})
    companies = payload.get("companies", {})
    if not isinstance(settings, dict) or not isinstance(companies, dict):
        raise ValueError(f"context file {target} has bad settings/companies")
    get_store().create(
        str(name),
        role=payload.get("role", "") or "",
        extends=payload.get("extends"),
        settings=settings,
        companies=companies,
        overwrite=overwrite,
    )
    return str(name)
