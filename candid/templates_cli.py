"""CLI logic for `candid templates` (batch 106, worker B).

Everything the command does lives here; candid/__main__.py only wires the
parser and dispatches to cmd_templates(). The template engine itself
(candid/templates.py) is built by worker A to the contract below and is
imported lazily (see _require_templates) so tests can stub it.

Contract (worker A):
    TemplateError(Exception)
    PACK_KINDS = ("cover-letter", "outreach", "questions")
    list_packs(kind=None) -> list[dict manifest]
    get_pack(name) -> dict {manifest, templates: [names]}
    render_template(pack_name, template_name, variables: dict) -> str
    validate_pack(path) -> {ok: bool, issues: [str]}
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path

#: Matches {{variable}} placeholders in a rendered template body.
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")

_BOLD = "\033[1m"
_RESET = "\033[0m"


class TemplatesUnavailableError(Exception):
    """candid/templates.py (worker A's template engine) is not in this build."""


def _require_templates():
    """Lazy import of the template engine with a clear error when absent."""
    try:
        return importlib.import_module("candid.templates")
    except ImportError as e:
        raise TemplatesUnavailableError(
            "The template engine (candid/templates.py) is not available in "
            f"this build, so `candid templates` cannot run. ({e})"
        ) from e


def _builtin_packs_dir() -> Path:
    """Directory of built-in gallery packs (overridable for tests)."""
    override = os.environ.get("CANDID_PACKS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "data" / "packs"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def list_packs(kind: str | None = None, as_json: bool = False) -> int:
    """List installed template packs (worker A engine)."""
    T = _require_templates()
    packs = T.list_packs(kind=kind)
    if as_json:
        print(json.dumps(packs, indent=2))
        return 0
    if not packs:
        print("No template packs installed yet.")
        print("Browse the built-in gallery with: python -m candid templates gallery")
        return 0
    for p in packs:
        name = p.get("name", "?")
        parts = [x for x in (p.get("kind", ""),) if x]
        if p.get("version"):
            parts.append(f"v{p['version']}")
        line = f"- {name}"
        if parts:
            line += f" ({', '.join(parts)})"
        if p.get("description"):
            line += f" — {p['description']}"
        print(line)
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def _highlight_vars(body: str) -> tuple[str, list[str]]:
    """Bold {{var}} placeholders; return (highlighted_body, var_names)."""
    names: list[str] = []

    def _repl(m: re.Match) -> str:
        names.append(m.group(1))
        return f"{_BOLD}{m.group(0)}{_RESET}"

    return _VAR_RE.sub(_repl, body), names


def show_pack(pack: str, template: str | None = None) -> int:
    """Show a pack manifest; with --template, show the template body."""
    T = _require_templates()
    info = T.get_pack(pack)
    manifest = info.get("manifest", {})
    names = info.get("templates", [])
    if template is None:
        print(f"Pack: {manifest.get('name', pack)}")
        if manifest.get("version"):
            print(f"Version: {manifest['version']}")
        if manifest.get("kind"):
            print(f"Kind: {manifest['kind']}")
        if manifest.get("title"):
            print(f"Title: {manifest['title']}")
        if manifest.get("description"):
            print(f"Description: {manifest['description']}")
        if names:
            print(f"Templates ({len(names)}): {', '.join(names)}")
        else:
            print("Templates: none")
        return 0
    if template not in names:
        raise T.TemplateError(
            f"Pack '{pack}' has no template '{template}'. "
            f"Available: {', '.join(names) if names else 'none'}")
    # Render with no variables so unfilled {{var}} placeholders stay visible.
    body = T.render_template(pack, template, {})
    highlighted, vars_ = _highlight_vars(body)
    print(f"--- {pack} / {template} ---")
    print(highlighted)
    if vars_:
        print(f"\nVariables: {', '.join(vars_)}")
        print("Fill them with: python -m candid templates use "
              f"{pack} {template} " + " ".join(f"--var {v}=..." for v in vars_))
    else:
        print("\nVariables: none detected in the rendered output.")
    return 0


# ---------------------------------------------------------------------------
# use
# ---------------------------------------------------------------------------

def _parse_vars(var_list: list[str], vars_json: str | None) -> dict:
    """Merge --vars-json FILE (base) with repeated --var k=v (wins)."""
    variables: dict = {}
    if vars_json:
        try:
            with open(vars_json, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            T = _require_templates()
            raise T.TemplateError(f"Could not read --vars-json '{vars_json}': {e}")
        if not isinstance(data, dict):
            T = _require_templates()
            raise T.TemplateError(
                f"--vars-json '{vars_json}' must contain a JSON object, "
                f"got {type(data).__name__}.")
        variables.update({str(k): v for k, v in data.items()})
    for item in var_list or []:
        if "=" not in item:
            T = _require_templates()
            raise T.TemplateError(
                f"Bad --var '{item}': expected k=v (e.g. --var name=\"Jane Doe\").")
        k, v = item.split("=", 1)
        variables[k] = v
    return variables


def use_template(pack: str, template: str, var_list: list[str],
                 vars_json: str | None, out: str | None) -> int:
    """Render a template to stdout or a file."""
    T = _require_templates()
    variables = _parse_vars(var_list, vars_json)
    rendered = T.render_template(pack, template, variables)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(rendered)
        print(f"Saved to {out}")
    else:
        # Avoid adding a second trailing newline when the template ends with one.
        sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")
    return 0


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def search_packs(query: str, as_json: bool = False) -> int:
    """Search pack titles/descriptions/template names for query."""
    T = _require_templates()
    q = query.lower()
    hits = []
    for manifest in T.list_packs():
        pack_hits: list[str] = []
        hay = " ".join(str(manifest.get(k, "")) for k in
                       ("name", "title", "description", "kind"))
        try:
            templates = T.get_pack(manifest.get("name", ""))["templates"]
        except Exception:
            templates = []
        for tname in templates:
            if q in str(tname).lower():
                pack_hits.append(str(tname))
        if q in hay.lower() or pack_hits:
            hits.append({"manifest": manifest, "matched_templates": pack_hits})
    if as_json:
        print(json.dumps(hits, indent=2))
        return 0
    if not hits:
        print(f"No template packs match '{query}'.")
        return 0
    for h in hits:
        m = h["manifest"]
        line = f"- {m.get('name', '?')} ({m.get('kind', '')})"
        if m.get("description"):
            line += f" — {m['description']}"
        print(line)
        for tname in h["matched_templates"]:
            print(f"    · {tname}")
    return 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate_pack(path: str) -> int:
    """Validate a pack directory; non-zero exit (via TemplateError) if invalid."""
    T = _require_templates()
    result = T.validate_pack(path)
    issues = result.get("issues", []) if isinstance(result, dict) else []
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    if ok and not issues:
        print(f"Pack '{path}' is valid.")
        return 0
    print(f"Pack '{path}' is invalid ({len(issues)} issue(s)):")
    for issue in issues:
        print(f"  - {issue}")
    raise T.TemplateError(f"Pack '{path}' failed validation.")


# ---------------------------------------------------------------------------
# gallery
# ---------------------------------------------------------------------------

def _gallery_packs(kind: str | None = None) -> list[dict]:
    """Read built-in packs from candid/data/packs/<pack-name>/."""
    packs_dir = _builtin_packs_dir()
    if not packs_dir.is_dir():
        return []
    packs = []
    for entry in sorted(packs_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta = {"name": entry.name}
        manifest_file = entry / "manifest.json"
        if manifest_file.is_file():
            try:
                meta.update(json.loads(manifest_file.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                meta["description"] = "(manifest.json unreadable)"
        if kind and meta.get("kind") != kind:
            continue
        packs.append(meta)
    return packs


def gallery(kind: str | None = None) -> int:
    """List built-in gallery packs, marking which are installed."""
    T = _require_templates()
    packs = _gallery_packs(kind)
    if not packs:
        print("The template gallery is empty — no built-in packs ship with this "
              "build yet.")
        print("Check back after the next update, or validate a pack directory "
              "with: python -m candid templates validate <path>")
        return 0
    try:
        installed = {str(p.get("name")) for p in T.list_packs()}
    except Exception:
        installed = set()
    for meta in packs:
        name = meta.get("name", "?")
        status = "installed" if name in installed else "not installed"
        line = f"- {name} [{status}]"
        if meta.get("kind"):
            line += f" ({meta['kind']}"
            if meta.get("version"):
                line += f" v{meta['version']}"
            line += ")"
        if meta.get("description"):
            line += f" — {meta['description']}"
        print(line)
    return 0


# ---------------------------------------------------------------------------
# dispatcher (called from candid/__main__.py)
# ---------------------------------------------------------------------------

def cmd_templates(a) -> None:
    """Dispatch `candid templates <subcommand>` (wired in __main__.py)."""
    what = a.what
    if what == "list":
        list_packs(kind=a.kind, as_json=a.json)
    elif what == "show":
        show_pack(a.pack, template=a.template)
    elif what == "use":
        use_template(a.pack, a.template, a.var, a.vars_json, a.out)
    elif what == "search":
        search_packs(a.query, as_json=a.json)
    elif what == "validate":
        validate_pack(a.path)
    elif what == "gallery":
        gallery(kind=a.kind)
    else:  # pragma: no cover - argparse restricts choices
        raise ValueError(f"Unknown templates subcommand: {what}")
