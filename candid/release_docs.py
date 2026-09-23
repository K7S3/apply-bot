"""Release gate: documentation coverage checks, AST based, no subprocess.

Three checks:
  1. every CLI command registered via the local _sub() helper appears in
     README.md (case-insensitive substring),
  2. every candid/*.py module (except __init__, __main__ and legacy/)
     has a non-empty module docstring,
  3. every module's name shows up in the "Modules:" list inside the
     candid/__init__.py docstring (module index current).

Results are returned as {"name", "ok", "detail"} dicts; ok=None means a
check was skipped (for example a file it needs is missing).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SKIP_MODULES = {"__init__", "__main__"}
# Entry lines start with the module name; combined with the indentation
# check in index_entries, wrapped description lines never match.
INDEX_LINE_RE = re.compile(r"^(\w+)\s")


def cli_commands(repo_root: Path) -> list[str]:
    """Collect CLI command names registered with the local _sub() helper.

    The helper is called as _sub(subparsers, name, help, ...), so the
    command name is the first positional argument that is a string.
    Names are deduplicated, first occurrence order kept.
    """
    path = repo_root / "candid" / "__main__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_sub"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value not in names:
                    names.append(arg.value)
                break
    return names


def module_docstrings(repo_root: Path) -> dict[str, str | None]:
    """Map module name -> module docstring for candid/*.py files."""
    pkg = repo_root / "candid"
    out: dict[str, str | None] = {}
    for path in sorted(pkg.glob("*.py")):
        name = path.stem
        if name in SKIP_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out[name] = ast.get_docstring(tree)
    return out


def index_entries(repo_root: Path) -> list[str]:
    """Parse the Modules: list from the candid/__init__.py docstring.

    The section ends at the first blank line. Entries are lines at the
    same indentation as the first entry; deeper-indented wrapped
    description lines are skipped, not treated as entries.
    """
    path = repo_root / "candid" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree) or ""
    entries: list[str] = []
    in_modules = False
    base_indent: int | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        if not in_modules:
            if stripped.startswith("Modules:"):
                in_modules = True
            continue
        if not stripped:
            break
        indent = len(line) - len(line.lstrip())
        if base_indent is None:
            base_indent = indent
        if indent != base_indent:
            continue
        m = INDEX_LINE_RE.match(stripped)
        if m:
            entries.append(m.group(1))
    return entries
    return entries


def check_commands_documented(repo_root: Path) -> dict:
    """Every CLI command name must appear in README.md (case-insensitive)."""
    readme_path = repo_root / "README.md"
    if not readme_path.exists():
        return {"name": "cli commands documented", "ok": None, "detail": "README.md not found"}
    commands = cli_commands(repo_root)
    readme = readme_path.read_text(encoding="utf-8").lower()
    missing = [c for c in commands if c.lower() not in readme]
    if missing:
        return {
            "name": "cli commands documented",
            "ok": False,
            "detail": "commands missing from README.md: %s" % ", ".join(missing),
        }
    return {
        "name": "cli commands documented",
        "ok": True,
        "detail": "%d commands all mentioned in README.md" % len(commands),
    }


def check_modules_documented(repo_root: Path) -> dict:
    """Every candid/*.py module must have a non-empty module docstring."""
    docs = module_docstrings(repo_root)
    offenders = [name for name, doc in docs.items() if not (doc and doc.strip())]
    if offenders:
        return {
            "name": "modules documented",
            "ok": False,
            "detail": "modules missing a docstring: %s" % ", ".join(sorted(offenders)),
        }
    return {
        "name": "modules documented",
        "ok": True,
        "detail": "%d modules all have docstrings" % len(docs),
    }


def check_module_index_current(repo_root: Path) -> dict:
    """Every module name must appear in the __init__.py Modules: list."""
    docs = module_docstrings(repo_root)
    entries = set(index_entries(repo_root))
    missing = [name for name in sorted(docs) if name not in entries]
    if missing:
        return {
            "name": "module index current",
            "ok": False,
            "detail": "modules missing from the __init__.py index: %s" % ", ".join(missing),
        }
    return {
        "name": "module index current",
        "ok": True,
        "detail": "all %d modules listed in the __init__.py index" % len(docs),
    }


def run_checks(repo_root: Path) -> list[dict]:
    """Emit the three documentation-coverage results for the checklist."""
    return [
        check_commands_documented(repo_root),
        check_modules_documented(repo_root),
        check_module_index_current(repo_root),
    ]
