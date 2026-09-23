"""A small, safe plugin system for candid.

Plugins are plain ``*.py`` files dropped into the user config plugins dir
(``CONFIG_DIR/plugins/``, overridable via ``CANDID_CONFIG_DIR``) or into any
extra directories named by the ``CANDID_PLUGINS`` env var (colon-separated).
Each plugin declares itself with a module-level ``CANDID_PLUGIN`` dict:

    CANDID_PLUGIN = {
        "name": "my_source",
        "version": "0.1.0",
        "hooks": {
            "job_source": fetch_jobs,   # (name) -> iterable[posting_dict]
            "scorer": make_scorer,      # (name) -> callable(profile, jd) -> float
        },
    }

Hook kinds:

- ``job_source(name)`` — a custom job-source adapter. Calling it with the
  plugin's registered name must return an iterable of posting dicts in the
  canonical format used by :mod:`candid.jobs` (see :func:`POSTING_KEYS` and
  ``docs/plugins.md``).
- ``scorer(name)`` — a factory returning ``callable(profile: dict, jd: dict)
  -> float``, a custom match scorer returning 0-100.

Safety: plugin loading is per-file and fully isolated — an import error, a
syntax error, a missing ``CANDID_PLUGIN``, or a malformed hook is recorded
on the plugin's :class:`PluginInfo` and never breaks the CLI or the other
plugins. Plugins are trusted local code (they run with your privileges),
so only install plugins you wrote or trust.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from candid import config as C

log = C.get_logger("plugins")

# Canonical posting dict keys — mirrors the adapters in candid/jobs.py.
# ``source``/``source_id``/``title``/``company`` are required; the rest may
# be empty strings / False but should be present.
POSTING_KEYS = ("source", "source_id", "title", "company", "location",
                "url", "description", "salary_text", "remote", "posted_at")
REQUIRED_POSTING_KEYS = ("source", "source_id", "title", "company")

HOOK_KINDS = ("job_source", "scorer")


@dataclass
class PluginInfo:
    """Everything discovered about one plugin file."""
    name: str
    version: str
    path: Path
    hooks: dict[str, Callable[..., Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    loaded_ok: bool = False

    @property
    def hook_names(self) -> list[str]:
        return sorted(self.hooks)


def _default_plugins_dir() -> Path:
    override = os.environ.get("CANDID_CONFIG_DIR")
    base = Path(override).expanduser() if override else C.CONFIG_DIR
    return base / "plugins"


def plugin_dirs() -> list[Path]:
    """Plugin search dirs: CONFIG_DIR/plugins/ + CANDID_PLUGINS extras.

    Env override is read live (not cached) so tests can repoint it.
    """
    dirs = [_default_plugins_dir()]
    extra = os.environ.get("CANDID_PLUGINS", "")
    for part in extra.split(os.pathsep):
        part = part.strip()
        if part:
            dirs.append(Path(part).expanduser())
    # de-dupe while keeping order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _iter_plugin_files() -> Iterator[Path]:
    for d in plugin_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            stem = f.stem
            if stem.startswith((".", "_")) or stem == "__init__":
                continue
            yield f


def _module_name_for(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return f"candid_plugin_{digest}"


def _load_module(path: Path) -> tuple[Any | None, str | None]:
    """Import a plugin file. Returns (module, error). Never raises."""
    mod_name = _module_name_for(path)
    # If an identical-path module was loaded before (e.g. in tests that
    # rewrite the file), force a fresh import.
    old = sys.modules.pop(mod_name, None)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return None, f"cannot build import spec for {path.name}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module, None
    except Exception as exc:
        sys.modules.pop(mod_name, None)
        if old is not None:
            sys.modules[mod_name] = old
        tb = traceback.format_exception_only(type(exc), exc)
        return None, f"import failed: {''.join(tb).strip()}"


def _validate_decl(path: Path, module: Any) -> tuple[PluginInfo, list[str]]:
    """Check the CANDID_PLUGIN declaration. Returns (info, errors)."""
    info = PluginInfo(name=path.stem, version="0.0.0", path=path)
    decl = getattr(module, "CANDID_PLUGIN", None)
    if decl is None:
        return info, [f"{path.name}: no module-level CANDID_PLUGIN dict"]
    if not isinstance(decl, dict):
        return info, [f"{path.name}: CANDID_PLUGIN must be a dict, got "
                      f"{type(decl).__name__}"]
    name = decl.get("name")
    if not isinstance(name, str) or not name.strip():
        return info, [f"{path.name}: CANDID_PLUGIN['name'] must be a non-empty string"]
    info.name = name.strip()
    version = decl.get("version", "0.0.0")
    info.version = str(version)
    hooks = decl.get("hooks", {})
    if not isinstance(hooks, dict):
        return info, [f"{path.name}: CANDID_PLUGIN['hooks'] must be a dict"]
    errors: list[str] = []
    for kind, fn in hooks.items():
        if kind not in HOOK_KINDS:
            errors.append(f"{path.name}: unknown hook kind {kind!r} "
                          f"(expected one of {', '.join(HOOK_KINDS)})")
            continue
        if not callable(fn):
            errors.append(f"{path.name}: hook {kind!r} is not callable")
            continue
        info.hooks[kind] = fn
    return info, errors


def discover_plugins() -> list[PluginInfo]:
    """Load every plugin file found. Failures are recorded, never raised.

    Returns PluginInfo for every ``*.py`` file discovered, including ones
    that failed to import or declare themselves — their ``errors`` list
    explains why and ``loaded_ok`` is False.
    """
    infos: list[PluginInfo] = []
    seen_names: set[str] = set()
    for path in _iter_plugin_files():
        module, err = _load_module(path)
        if err is not None:
            infos.append(PluginInfo(name=path.stem, version="0.0.0",
                                    path=path, errors=[err]))
            continue
        info, decl_errors = _validate_decl(path, module)
        info.errors.extend(decl_errors)
        if info.name in seen_names:
            info.errors.append(
                f"duplicate plugin name {info.name!r} — the first one wins")
        else:
            seen_names.add(info.name)
        info.loaded_ok = not info.errors
        infos.append(info)
    return infos


def validate_posting(posting: Any) -> list[str]:
    """Check one posting dict against the canonical format.

    Returns a list of problems (empty = valid). Extra keys are allowed;
    missing required keys or wrong types are reported.
    """
    problems: list[str] = []
    if not isinstance(posting, dict):
        return [f"posting is {type(posting).__name__}, expected dict"]
    for key in REQUIRED_POSTING_KEYS:
        if not posting.get(key):
            problems.append(f"missing/empty required key {key!r}")
    for key in POSTING_KEYS:
        if key not in posting:
            problems.append(f"missing key {key!r}")
    remote = posting.get("remote", False)
    if not isinstance(remote, bool):
        problems.append(f"'remote' should be bool, got {type(remote).__name__}")
    return problems


def _bind(hook: Callable[..., Any], name: str) -> Callable[..., Any]:
    """Bind the plugin name into a hook factory, checking its signature."""
    try:
        sig = inspect.signature(hook)
        params = list(sig.parameters.values())
        if not params or any(p.kind == inspect.Parameter.VAR_POSITIONAL
                             for p in params):
            pass  # *args style — call with the name, let it decide
        elif len([p for p in params
                  if p.default is inspect.Parameter.empty
                  and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                 inspect.Parameter.POSITIONAL_OR_KEYWORD)]) > 1:
            log.warning("plugin hook %s takes >1 required arg; "
                        "only the name will be passed", name)
    except (TypeError, ValueError):
        pass

    def bound(*args: Any, **kwargs: Any) -> Any:
        if args or kwargs:
            return hook(*args, **kwargs)
        return hook(name)
    bound.__name__ = getattr(hook, "__name__", f"{name}_hook")
    bound.__doc__ = getattr(hook, "__doc__", None)
    return bound


def get_job_sources() -> dict[str, Callable[[], Iterable[dict]]]:
    """{plugin name: job_source callable} for every loaded plugin.

    Each callable takes no arguments (the plugin name is bound in) and
    returns an iterable of canonical posting dicts. Plugins that failed
    to load, or that declare no ``job_source`` hook, are skipped.
    """
    sources: dict[str, Callable[[], Iterable[dict]]] = {}
    for info in discover_plugins():
        hook = info.hooks.get("job_source")
        if hook is None or not info.loaded_ok:
            continue
        sources[info.name] = _bind(hook, info.name)  # type: ignore[assignment]
    return sources


def get_scorers() -> dict[str, Callable[[dict, dict], float]]:
    """{plugin name: scorer callable} for every loaded plugin.

    Each callable has signature ``(profile: dict, jd: dict) -> float`` in
    0-100, built by the plugin's ``scorer`` hook factory.
    """
    scorers: dict[str, Callable[[dict, dict], float]] = {}
    for info in discover_plugins():
        hook = info.hooks.get("scorer")
        if hook is None or not info.loaded_ok:
            continue
        factory = _bind(hook, info.name)
        try:
            scorer = factory()
        except Exception as exc:
            log.warning("plugin %s scorer factory failed: %s", info.name, exc)
            continue
        if not callable(scorer):
            log.warning("plugin %s scorer hook did not return a callable",
                        info.name)
            continue
        scorers[info.name] = scorer
    return scorers


# ---------------------------------------------------------------------------
# CLI: `candid plugins list` / `candid plugins test <name>`
# ---------------------------------------------------------------------------

_SYNTHETIC_PROFILE = {
    "name": "Test User",
    "skills": ["python", "sql", "machine learning"],
    "years_experience": 3,
    "titles": ["Data Scientist"],
}
_SYNTHETIC_JD = {
    "title": "Data Scientist",
    "company": "ExampleCo",
    "description": "We need python and sql for machine learning models.",
    "location": "Remote",
}


def render_list(infos: list[PluginInfo]) -> str:
    if not infos:
        dirs = ", ".join(str(d) for d in plugin_dirs())
        return ("No plugins found.\n"
                f"Drop *.py plugin files into one of:\n  {dirs}\n"
                "See docs/plugins.md for the plugin format.")
    lines = [f"{len(infos)} plugin file(s) discovered:"]
    for info in infos:
        status = "OK" if info.loaded_ok else "ERROR"
        lines.append(f"\n[{status}] {info.name} (v{info.version})")
        lines.append(f"  path: {info.path}")
        hooks = ", ".join(info.hook_names) if info.hook_names else "(no hooks)"
        lines.append(f"  hooks: {hooks}")
        for err in info.errors:
            lines.append(f"  ! {err}")
    return "\n".join(lines)


def test_plugin(info: PluginInfo) -> str:
    """Dry-run a plugin's hooks with tiny synthetic input. No network."""
    lines = [f"Testing plugin {info.name!r} (v{info.version}) from {info.path}"]
    if not info.loaded_ok or not info.hooks:
        for err in info.errors or ["plugin did not load cleanly"]:
            lines.append(f"  FAIL load: {err}")
        return "\n".join(lines)

    if "job_source" in info.hooks:
        try:
            gen = _bind(info.hooks["job_source"], info.name)()
            if isinstance(gen, dict):
                postings = [gen]
            else:
                postings = []
                for i, p in enumerate(gen):
                    postings.append(p)
                    if i >= 2:
                        break
            if not postings:
                lines.append("  FAIL job_source: hook returned no postings")
            else:
                bad = [(i, validate_posting(p)) for i, p in enumerate(postings)]
                bad = [(i, ps) for i, ps in bad if ps]
                if bad:
                    detail = "; ".join(f"posting {i}: {', '.join(ps)}"
                                       for i, ps in bad)
                    lines.append(f"  FAIL job_source: {detail}")
                else:
                    lines.append(f"  OK job_source: {len(postings)} posting(s), "
                                 "canonical format valid")
        except Exception as exc:
            lines.append(f"  FAIL job_source: raised {type(exc).__name__}: {exc}")

    if "scorer" in info.hooks:
        try:
            scorer = _bind(info.hooks["scorer"], info.name)()
            if not callable(scorer):
                lines.append("  FAIL scorer: hook did not return a callable")
            else:
                score = scorer(dict(_SYNTHETIC_PROFILE), dict(_SYNTHETIC_JD))
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    lines.append(f"  FAIL scorer: returned {type(score).__name__}, "
                                 "expected a number 0-100")
                elif not 0 <= score <= 100:
                    lines.append(f"  FAIL scorer: returned {score}, "
                                 "expected 0-100")
                else:
                    lines.append(f"  OK scorer: returned {score} for synthetic input")
        except Exception as exc:
            lines.append(f"  FAIL scorer: raised {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def _cmd_plugins(args: argparse.Namespace) -> int:
    infos = discover_plugins()
    if args.plugins_cmd == "list":
        print(render_list(infos))
        return 0
    if args.plugins_cmd == "test":
        match = [i for i in infos if i.name == args.name]
        if not match:
            names = ", ".join(i.name for i in infos) or "(none)"
            print(f"No plugin named {args.name!r}. Discovered: {names}")
            return 1
        print(test_plugin(match[0]))
        return 0
    return 1  # pragma: no cover


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``candid plugins`` command to the top-level parser.

    Creates exactly: ``plugins`` parser -> required subcommands
    ``list`` and ``test <name>``; dispatches via ``set_defaults(func=...)``
    like the other candid commands.
    """
    p = subparsers.add_parser(
        "plugins",
        help="Manage candid plugins (custom job sources and scorers)",
        description="Discover, list, and dry-run plugins from the config "
                    "plugins directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python -m candid plugins list\n"
               "  python -m candid plugins test my_source",
    )
    sub = p.add_subparsers(dest="plugins_cmd", required=True,
                           title="subcommands", metavar="<subcommand>")
    sub.add_parser("list", help="List discovered plugins, hooks, and load errors",
                   formatter_class=argparse.RawDescriptionHelpFormatter,
                   epilog="examples:\n  python -m candid plugins list")
    t = sub.add_parser("test", help="Dry-run a plugin's hooks with synthetic "
                                    "input (no network)",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid plugins test my_source")
    t.add_argument("name", help="Plugin name (see `candid plugins list`)")
    p.set_defaults(func=_cmd_plugins)
