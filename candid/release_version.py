"""Version consistency checks and version bump helper for the candid repo.

The single source of truth for the package version is the ``__version__``
assignment in ``candid/__init__.py``. Nothing here imports the candid
package; the version is always read by parsing the file with ``ast`` so
there are no import side effects.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import date
from pathlib import Path

INIT_REL = Path("candid") / "__init__.py"

# A version-looking string like 0.2.0 or v0.2.0. The lookarounds keep
# things like 127.0.0.1 (an IP address) from matching, while a trailing
# sentence period (as in "at v0.2.0.") is still accepted.
_VERSION_LOOKING_RE = re.compile(r"(?<![0-9.])v?(\d+\.\d+\.\d+)(?!\.?\d)")
_STRICT_PART_RE = re.compile(r"(?:0|[1-9][0-9]*)")
# Rewrites only the __version__ assignment line, preserving quote style.
_VERSION_LINE_RE = re.compile(
    r"(?m)^([ \t]*__version__[ \t]*=[ \t]*)(['\"])[^'\"]*\2"
)
# Fallback line scan for .py files that fail to parse.
_FALLBACK_ASSIGN_RE = re.compile(r"\b(__version__|version)\b\s*=")


def get_version(repo_root: Path) -> str:
    """Return the ``__version__`` string from ``candid/__init__.py``.

    Parsed with ``ast``; the candid package is never imported.
    Raises ValueError if no string assignment is found.
    """
    init = Path(repo_root) / INIT_REL
    tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "__version__"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                return value.value
    raise ValueError(f"no __version__ string assignment in {init}")


def parse_version(v: str) -> tuple[int, int, int]:
    """Parse a strict X.Y.Z version into an (int, int, int) tuple.

    Each part must be digits with no leading zeros (so semver-strict).
    Raises ValueError for anything else.
    """
    if not isinstance(v, str):
        raise ValueError(f"version must be a string, got {type(v).__name__}")
    parts = v.strip().split(".")
    if len(parts) != 3 or not all(_STRICT_PART_RE.fullmatch(p) for p in parts):
        raise ValueError(f"not a strict X.Y.Z version: {v!r}")
    major, minor, patch = (int(p) for p in parts)
    return (major, minor, patch)


def _assign_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _py_has_version_assignment(path: Path) -> bool:
    """True if a .py file defines a package version.

    Uses the AST so reads (``from candid import __version__``), keyword
    arguments (``version=...`` in a call), and function-local variables
    named ``version`` are not flagged. Only real definitions count:
    ``__version__`` assigned anywhere, or a bare module-level
    ``version = ...`` assignment.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        # Best effort fallback: line scan ignoring comment lines.
        for line in text.splitlines():
            stripped = line.lstrip()
            if not stripped.startswith("#") and _FALLBACK_ASSIGN_RE.search(line):
                return True
        return False
    for node in ast.walk(tree):
        if any(
            isinstance(t, ast.Name) and t.id == "__version__"
            for t in _assign_targets(node)
        ):
            return True
    for node in tree.body:  # module level only for bare `version = ...`
        if any(
            isinstance(t, ast.Name) and t.id == "version"
            for t in _assign_targets(node)
        ):
            return True
    return False


def _version_definitions(repo_root: Path) -> list[str]:
    """Repo-relative paths of files that define a package version."""
    root = Path(repo_root)
    found: list[str] = []
    pkg = root / "candid"
    if pkg.is_dir():
        for py_file in sorted(pkg.glob("*.py")):
            if _py_has_version_assignment(py_file):
                found.append(py_file.relative_to(root).as_posix())
    for name in ("pyproject.toml", "setup.cfg"):
        cfg = root / name
        if cfg.is_file():
            try:
                text = cfg.read_text(encoding="utf-8")
            except OSError:
                continue
            if re.search(r"(?m)^\s*version\s*=", text):
                found.append(name)
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and "version" in data:
            found.append("package.json")
    return found


def _first_heading_version(text: str) -> str | None:
    """Return the first version-looking string in a markdown heading, if any."""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            match = _VERSION_LOOKING_RE.search(stripped)
            if match:
                return match.group(1)
    return None


def run_checks(repo_root: Path) -> list[dict]:
    """Run the version consistency checks.

    Returns a list of {"name", "ok", "detail"} dicts. ``ok`` is True/False,
    or None when the check is skipped (no CHANGELOG.md / no version mention
    in README.md).
    """
    root = Path(repo_root)
    results: list[dict] = []

    try:
        version = get_version(root)
        parsed = parse_version(version)
        results.append(
            {
                "name": "version parses as semver",
                "ok": True,
                "detail": f"{version} parses as {parsed}",
            }
        )
        version_known = True
    except (ValueError, OSError, SyntaxError) as exc:
        results.append(
            {"name": "version parses as semver", "ok": False, "detail": str(exc)}
        )
        version = ""
        version_known = False

    definitions = _version_definitions(root)
    if definitions == [INIT_REL.as_posix()]:
        results.append(
            {
                "name": "single version source",
                "ok": True,
                "detail": "only version definition is candid/__init__.py",
            }
        )
    else:
        results.append(
            {
                "name": "single version source",
                "ok": False,
                "detail": f"version defined in: {', '.join(definitions) or 'no files'}",
            }
        )

    changelog = root / "CHANGELOG.md"
    if not changelog.is_file():
        results.append(
            {
                "name": "changelog matches version",
                "ok": None,
                "detail": "no CHANGELOG.md",
            }
        )
    elif not version_known:
        results.append(
            {
                "name": "changelog matches version",
                "ok": False,
                "detail": "cannot determine package version to compare",
            }
        )
    else:
        try:
            heading_version = _first_heading_version(
                changelog.read_text(encoding="utf-8")
            )
        except OSError as exc:
            results.append(
                {
                    "name": "changelog matches version",
                    "ok": False,
                    "detail": f"could not read CHANGELOG.md: {exc}",
                }
            )
        else:
            if heading_version is None:
                results.append(
                    {
                        "name": "changelog matches version",
                        "ok": False,
                        "detail": "no version-looking heading found in CHANGELOG.md",
                    }
                )
            else:
                results.append(
                    {
                        "name": "changelog matches version",
                        "ok": heading_version == version,
                        "detail": (
                            f"CHANGELOG heading is {heading_version}, "
                            f"package version is {version}"
                        ),
                    }
                )

    readme = root / "README.md"
    mentions: list[str] = []
    if readme.is_file():
        try:
            mentions = [
                m.group(1)
                for m in _VERSION_LOOKING_RE.finditer(
                    readme.read_text(encoding="utf-8")
                )
            ]
        except OSError:
            mentions = []
    if not mentions:
        results.append(
            {
                "name": "readme version mentions consistent",
                "ok": None,
                "detail": "no version-looking string in README.md",
            }
        )
    elif not version_known:
        results.append(
            {
                "name": "readme version mentions consistent",
                "ok": False,
                "detail": "cannot determine package version to compare",
            }
        )
    else:
        mismatched = sorted({m for m in mentions if m != version})
        results.append(
            {
                "name": "readme version mentions consistent",
                "ok": not mismatched,
                "detail": (
                    f"all README mentions match {version}"
                    if not mismatched
                    else f"README mentions {', '.join(mismatched)} "
                    f"but package version is {version}"
                ),
            }
        )

    return results


def bump_version(repo_root: Path, part: str) -> tuple[str, str]:
    """Bump the package version in place; return (old_version, new_version).

    ``part`` is one of "major", "minor", "patch". Only the ``__version__``
    assignment line in ``candid/__init__.py`` is rewritten; the rest of the
    file is preserved byte for byte. If CHANGELOG.md exists, a new section
    heading ``## [<new>] - <today ISO date>`` with an empty bullet
    placeholder is prepended (after any top-level title).
    """
    if part not in ("major", "minor", "patch"):
        raise ValueError(
            f"part must be one of major/minor/patch, got {part!r}"
        )
    root = Path(repo_root)
    old = get_version(root)
    major, minor, patch = parse_version(old)
    if part == "major":
        new = f"{major + 1}.0.0"
    elif part == "minor":
        new = f"{major}.{minor + 1}.0"
    else:
        new = f"{major}.{minor}.{patch + 1}"

    init = root / INIT_REL
    text = init.read_text(encoding="utf-8")
    new_text, count = _VERSION_LINE_RE.subn(
        lambda m: m.group(1) + m.group(2) + new + m.group(2), text, count=1
    )
    if count == 0:
        raise ValueError(f"no __version__ assignment line found in {init}")
    init.write_text(new_text, encoding="utf-8")

    changelog = root / "CHANGELOG.md"
    if changelog.is_file():
        lines = changelog.read_text(encoding="utf-8").split("\n")
        insert_at = 0
        if lines and lines[0].lstrip().startswith("# ") and not lines[
            0
        ].lstrip().startswith("##"):
            insert_at = 1
            while insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
        block = [f"## [{new}] - {date.today().isoformat()}", "", "-", ""]
        changelog.write_text("\n".join(lines[:insert_at] + block + lines[insert_at:]),
                             encoding="utf-8")

    return (old, new)
