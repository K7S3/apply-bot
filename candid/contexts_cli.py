"""`candid ctx` CLI surface: named configuration contexts.

All command logic lives here; registration is deferred to
``register_ctx()`` so the coordinator in ``candid.__main__`` can wire it
in without a circular import.
"""

from __future__ import annotations

import argparse
import json
import sys

from candid import contexts as C


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fail(message: str) -> None:
    """Friendly CLI error: __main__.main surfaces this as `Error: ...`."""
    sys.exit(message)


def _get(name: str) -> dict:
    try:
        return C.get_store().get(name)
    except KeyError:
        _fail(f"unknown context: {name!r}")


def _fmt(value) -> str:
    return json.dumps(value, sort_keys=True)


def _json(data) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# list / current
# ---------------------------------------------------------------------------


def cmd_ctx_list(a):
    store = C.get_store()
    names = store.list_names()
    active = store.active_name()
    if a.json:
        out = []
        for name in names:
            raw = store.get(name)
            out.append({
                "name": name,
                "role": raw.get("role", ""),
                "extends": raw.get("extends"),
                "active": name == active,
            })
        _json(out)
        return
    if not names:
        print("No contexts yet. Try: python -m candid ctx init faang-mle")
        return
    width = max(len(n) for n in names) + 2
    print(f"{'NAME':<{width}}{'ROLE':<28}{'EXTENDS':<16}ACTIVE")
    for name in names:
        raw = store.get(name)
        mark = "*" if name == active else ""
        print(f"{name:<{width}}{raw.get('role', ''):<28}"
              f"{raw.get('extends') or '':<16}{mark}")


def cmd_ctx_current(a):
    store = C.get_store()
    name = store.active_name()
    if name is None:
        if a.json:
            _json({"active": None})
        else:
            print("No active context. Set one with: python -m candid ctx use <name>")
        return
    if a.json:
        resolved = C.resolve_context(name)
        _json({"active": name, "resolved": resolved})
        return
    resolved = C.resolve_context(name)
    print(f"active: {name}")
    print(f"role: {resolved['role'] or '(none)'}")
    keys = sorted(resolved["settings"])
    print(f"settings ({len(keys)}): {', '.join(keys) if keys else '(none)'}")


# ---------------------------------------------------------------------------
# create / delete / rename / init / presets
# ---------------------------------------------------------------------------


def cmd_ctx_create(a):
    store = C.get_store()
    if a.from_preset:
        try:
            spec = C.BUILTIN_PRESETS[a.from_preset]
        except KeyError:
            _fail(f"unknown preset: {a.from_preset!r}. Run `python -m candid ctx presets`.")
        role = a.role or spec.get("role", "")
        extends = a.extends or spec.get("extends")
        settings = dict(spec.get("settings", {}))
        companies = dict(spec.get("companies", {}))
    else:
        role, extends, settings, companies = a.role or "", a.extends, {}, {}
    try:
        store.create(a.name, role=role, extends=extends,
                     settings=settings, companies=companies)
    except ValueError as e:
        _fail(str(e))
    print(f"Created context {a.name!r}.")


def cmd_ctx_delete(a):
    if not a.yes:
        try:
            answer = input(f"Delete context {a.name!r}? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return
    try:
        C.get_store().delete(a.name)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    print(f"Deleted context {a.name!r}.")


def cmd_ctx_rename(a):
    try:
        C.get_store().rename(a.old, a.new)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    print(f"Renamed {a.old!r} to {a.new!r}.")


def cmd_ctx_init(a):
    try:
        name = C.init_from_preset(a.preset, name=a.as_name, overwrite=a.overwrite)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    print(f"Created context {name!r} from preset {a.preset!r}.")


def cmd_ctx_presets(a):
    presets = C.list_presets()
    if a.json:
        _json(presets)
        return
    for p in presets:
        role = C.BUILTIN_PRESETS[p].get("role", "")
        print(f"{p:<20}{role}")


# ---------------------------------------------------------------------------
# show / set / unset / use
# ---------------------------------------------------------------------------


def cmd_ctx_show(a):
    if a.resolved:
        try:
            data = C.resolve_context(a.name)
        except (KeyError, ValueError) as e:
            _fail(str(e))
    else:
        data = _get(a.name)
    if a.json:
        _json(data)
        return
    if a.resolved:
        print(f"context: {data['name']}")
        print(f"role: {data['role'] or '(none)'}")
        print(f"extends: {data['extends'] or '(none)'}")
        print("settings (resolved):")
        for key in sorted(data["settings"]):
            print(f"  {key} = {_fmt(data['settings'][key])}")
        if data["companies"]:
            print("companies (resolved):")
            for comp in sorted(data["companies"]):
                print(f"  [{comp}]")
                for key in sorted(data["companies"][comp]):
                    print(f"    {key} = {_fmt(data['companies'][comp][key])}")
        return
    print(f"context: {a.name}")
    print(f"role: {data.get('role', '') or '(none)'}")
    print(f"extends: {data.get('extends') or '(none)'}")
    settings = data.get("settings", {})
    print("settings:")
    if settings:
        for key in sorted(settings):
            print(f"  {key} = {_fmt(settings[key])}")
    else:
        print("  (none)")
    companies = data.get("companies", {})
    if companies:
        print("companies:")
        for comp in sorted(companies):
            keys = sorted(companies[comp])
            print(f"  {comp}: {', '.join(keys)}")


def cmd_ctx_set(a):
    if a.key not in C.KNOWN_KEYS:
        print(f"Warning: {a.key!r} is not a known setting key.", file=sys.stderr)
        value = a.value
    else:
        try:
            value = C.coerce_value(a.key, a.value)
        except ValueError as e:
            _fail(str(e))
    try:
        C.get_store().set_value(a.name, a.key, value)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    print(f"Set {a.key} = {_fmt(value)} on {a.name!r}.")


def cmd_ctx_unset(a):
    _get(a.name)  # error if unknown
    C.get_store().unset_value(a.name, a.key)
    print(f"Unset {a.key} on {a.name!r}.")


def cmd_ctx_use(a):
    store = C.get_store()
    if a.name == "-":
        new = store.toggle_previous()
        if new is None:
            print("No active context to toggle back to.")
        else:
            print(f"Active context: {new}")
        return
    try:
        store.set_active(a.name)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    print(f"Active context: {a.name}")


# ---------------------------------------------------------------------------
# company overrides / role
# ---------------------------------------------------------------------------


def cmd_ctx_company_set(a):
    if a.key not in C.KNOWN_KEYS:
        print(f"Warning: {a.key!r} is not a known setting key.", file=sys.stderr)
        value = a.value
    else:
        try:
            value = C.coerce_value(a.key, a.value)
        except ValueError as e:
            _fail(str(e))
    try:
        C.get_store().set_company_value(a.name, a.company, a.key, value)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    print(f"Set {a.company} / {a.key} = {_fmt(value)} on {a.name!r}.")


def cmd_ctx_company_unset(a):
    _get(a.name)  # error if unknown
    C.get_store().unset_company_value(a.name, a.company, a.key)
    print(f"Unset {a.company} / {a.key} on {a.name!r}.")


def cmd_ctx_company_list(a):
    raw = _get(a.name)
    companies = raw.get("companies", {})
    if a.json:
        _json(companies)
        return
    if not companies:
        print(f"No company overrides on {a.name!r}.")
        return
    for comp in sorted(companies):
        keys = sorted(companies[comp])
        print(f"{comp}: {', '.join(keys)}")


def cmd_ctx_role_show(a):
    raw = _get(a.name)
    print(raw.get("role", "") or "(no role set)")


def cmd_ctx_role_set(a):
    store = C.get_store()
    try:
        raw = store.get(a.name)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    store.create(a.name, role=a.role, extends=raw.get("extends"),
                 settings=raw.get("settings", {}),
                 companies=raw.get("companies", {}), overwrite=True)
    print(f"Role of {a.name!r} set to {a.role!r}.")


# ---------------------------------------------------------------------------
# diff / validate / export / import
# ---------------------------------------------------------------------------


def cmd_ctx_diff(a):
    try:
        rows = C.diff_contexts(a.a, a.b)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    if a.json:
        _json([{"key": k, "a": va, "b": vb} for k, va, vb in rows])
        return
    if not rows:
        print(f"{a.a} and {a.b} resolve to the same settings.")
        return
    for key, va, vb in rows:
        sa = "(unset)" if va is None else _fmt(va)
        sb = "(unset)" if vb is None else _fmt(vb)
        print(f"{key}: {sa} -> {sb}")


def cmd_ctx_validate(a):
    store = C.get_store()
    if a.name:
        names = [a.name]
        try:
            store.get(a.name)
        except KeyError:
            _fail(f"unknown context: {a.name!r}")
    else:
        names = store.list_names()
    all_errors = {}
    for name in names:
        errors = C.validate_context(name)
        if errors:
            all_errors[name] = errors
    if not all_errors:
        print("All contexts valid." if not a.name else f"{a.name!r} is valid.")
        return
    for name in sorted(all_errors):
        print(f"{name}:")
        for err in all_errors[name]:
            print(f"  - {err}")
    sys.exit(1)


def cmd_ctx_export(a):
    try:
        path = C.export_context(a.name, a.out)
    except KeyError:
        _fail(f"unknown context: {a.name!r}")
    print(f"Exported {a.name!r} to {path}.")


def cmd_ctx_import(a):
    try:
        name = C.import_context(a.file, name=a.as_name, overwrite=a.overwrite)
    except (ValueError, KeyError) as e:
        _fail(str(e))
    print(f"Imported context {name!r}.")


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def register_ctx(subparsers):
    """Register the `candid ctx` command tree. Called by candid.__main__."""
    from candid.__main__ import _sub, _nested  # deferred: avoids circular import
    from candid import contexts as C

    s = _sub(subparsers, "ctx",
             "Config profiles: named setting bundles (contexts).", [
                 "python -m candid ctx list",
                 "python -m candid ctx init faang-mle",
                 "python -m candid ctx use faang-mle",
             ])
    cs = _nested(s)

    t = _sub(cs, "list", "List contexts.", ["python -m candid ctx list"])
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_list)

    t = _sub(cs, "create", "Create a context.",
             ["python -m candid ctx create my-ctx --role 'MLE'"])
    t.add_argument("name")
    t.add_argument("--role", default="")
    t.add_argument("--extends")
    t.add_argument("--from-preset", help="seed settings from a preset")
    t.set_defaults(func=cmd_ctx_create)

    t = _sub(cs, "delete", "Delete a context.", ["python -m candid ctx delete my-ctx"])
    t.add_argument("name")
    t.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    t.set_defaults(func=cmd_ctx_delete)

    t = _sub(cs, "rename", "Rename a context.",
             ["python -m candid ctx rename old new"])
    t.add_argument("old")
    t.add_argument("new")
    t.set_defaults(func=cmd_ctx_rename)

    t = _sub(cs, "show", "Show a context.",
             ["python -m candid ctx show my-ctx --resolved"])
    t.add_argument("name")
    t.add_argument("--resolved", action="store_true",
                   help="show inheritance-resolved view")
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_show)

    t = _sub(cs, "use", "Set the active context (`use -` toggles back).",
             ["python -m candid ctx use faang-mle"])
    t.add_argument("name")
    t.set_defaults(func=cmd_ctx_use)

    t = _sub(cs, "current", "Show the active context.",
             ["python -m candid ctx current"])
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_current)

    t = _sub(cs, "set", "Set a value on a context.",
             ["python -m candid ctx set my-ctx jobs.remote_only true"])
    t.add_argument("name")
    t.add_argument("key")
    t.add_argument("value")
    t.set_defaults(func=cmd_ctx_set)

    t = _sub(cs, "unset", "Remove a value from a context.",
             ["python -m candid ctx unset my-ctx jobs.remote_only"])
    t.add_argument("name")
    t.add_argument("key")
    t.set_defaults(func=cmd_ctx_unset)

    c = _sub(cs, "company", "Per-company overrides.",
             ["python -m candid ctx company list my-ctx"])
    co = _nested(c)

    t = _sub(co, "set", "Set a per-company override.",
             ["python -m candid ctx company set my-ctx Meta tailor.tone formal"])
    t.add_argument("name")
    t.add_argument("company")
    t.add_argument("key")
    t.add_argument("value")
    t.set_defaults(func=cmd_ctx_company_set)

    t = _sub(co, "unset", "Remove a per-company override.",
             ["python -m candid ctx company unset my-ctx Meta tailor.tone"])
    t.add_argument("name")
    t.add_argument("company")
    t.add_argument("key")
    t.set_defaults(func=cmd_ctx_company_unset)

    t = _sub(co, "list", "List per-company overrides.",
             ["python -m candid ctx company list my-ctx"])
    t.add_argument("name")
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_company_list)

    r = _sub(cs, "role", "Get or set a context's role.",
             ["python -m candid ctx role show my-ctx"])
    ro = _nested(r)

    t = _sub(ro, "show", "Show a context's role.")
    t.add_argument("name")
    t.set_defaults(func=cmd_ctx_role_show)

    t = _sub(ro, "set", "Set a context's role.")
    t.add_argument("name")
    t.add_argument("role")
    t.set_defaults(func=cmd_ctx_role_set)

    t = _sub(cs, "init", "Create a context from a preset.",
             ["python -m candid ctx init faang-mle --as my-ctx"])
    t.add_argument("preset")
    t.add_argument("--as", dest="as_name", help="context name (default: preset name)")
    t.add_argument("--overwrite", action="store_true")
    t.set_defaults(func=cmd_ctx_init)

    t = _sub(cs, "presets", "List builtin presets.",
             ["python -m candid ctx presets"])
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_presets)

    t = _sub(cs, "diff", "Diff resolved settings of two contexts.",
             ["python -m candid ctx diff a b"])
    t.add_argument("a")
    t.add_argument("b")
    t.add_argument("--json", action="store_true", help="machine-readable output")
    t.set_defaults(func=cmd_ctx_diff)

    t = _sub(cs, "validate", "Validate contexts.",
             ["python -m candid ctx validate", "python -m candid ctx validate my-ctx"])
    t.add_argument("name", nargs="?")
    t.set_defaults(func=cmd_ctx_validate)

    t = _sub(cs, "export", "Export a context to a JSON file.",
             ["python -m candid ctx export my-ctx --out my-ctx.json"])
    t.add_argument("name")
    t.add_argument("--out", required=True)
    t.set_defaults(func=cmd_ctx_export)

    t = _sub(cs, "import", "Import a context from a JSON file.",
             ["python -m candid ctx import my-ctx.json"])
    t.add_argument("file")
    t.add_argument("--as", dest="as_name", help="context name (default: from file)")
    t.add_argument("--overwrite", action="store_true")
    t.set_defaults(func=cmd_ctx_import)

    return s
