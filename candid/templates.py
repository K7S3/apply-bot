"""Template pack gallery: reusable ``{{variable}}`` document templates.

A template pack is a directory (or a ``.candidpack`` zip of one) containing:

- ``manifest.json`` — name (slug), title, version (semver), kind, author,
  description, variables (``[{name, description, required}]``), and
  ``min_candid_version``.
- ``templates/`` — one or more ``.md`` files with ``{{variable}}``
  placeholders, rendered by the small stdlib-only renderer below.

Packs ship built-in under ``candid/data/packs/`` and users can drop their
own into ``TEMPLATES_USER_DIR`` (``~/.config/candid/templates/``,
overridable via ``CANDID_CONFIG_DIR``). ``validate_pack()`` checks the
manifest schema, semver, kind, that every ``{{var}}`` used is declared,
that templates are non-empty, and the verified-only rule for
``questions`` packs (every question block carries a ``Source:`` line).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from candid import __version__ as CANDID_VERSION
from candid import config as C


class TemplateError(Exception):
    """Raised for invalid template packs or failed template operations."""


PACK_KINDS = ("cover-letter", "outreach", "questions")

BUILTIN_PACKS_DIR = Path(__file__).resolve().parent / "data" / "packs"

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_QUESTION_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_SOURCE_LINE_RE = re.compile(r"^\s*source\s*:", re.IGNORECASE)

# Manifest fields every pack must declare (besides the variables list).
_REQUIRED_MANIFEST_FIELDS = (
    "name", "title", "version", "kind", "author",
    "description", "variables", "min_candid_version",
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _user_dir() -> Path:
    """Resolve the user templates dir at call time so CANDID_CONFIG_DIR wins."""
    override = os.environ.get("CANDID_CONFIG_DIR")
    if override:
        return Path(override).expanduser() / "packs"
    return C.TEMPLATES_USER_DIR


def _pack_dirs() -> list[Path]:
    """All pack directories: built-ins first, then user dir. Sorted by name."""
    dirs: list[Path] = []
    for base in (BUILTIN_PACKS_DIR, _user_dir()):
        if base.is_dir():
            dirs.extend(sorted(
                (p for p in base.iterdir() if p.is_dir()),
                key=lambda p: p.name,
            ))
    return dirs


def _manifest_of(pack_dir: Path) -> dict | None:
    """Read a pack's manifest.json; None when missing or unparseable."""
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    manifest = dict(manifest)
    manifest["path"] = str(pack_dir)
    return manifest


def _template_files(pack_dir: Path) -> list[Path]:
    templates_dir = pack_dir / "templates"
    if not templates_dir.is_dir():
        return []
    return sorted(
        (p for p in templates_dir.iterdir()
         if p.is_file() and p.suffix.lower() == ".md"),
        key=lambda p: p.name,
    )


def _semver_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def list_packs(kind: str | None = None) -> list[dict]:
    """Return manifest dicts for all packs (built-ins + user dir).

    Raises TemplateError for an unknown kind filter.
    """
    if kind is not None and kind not in PACK_KINDS:
        raise TemplateError(
            f"Unknown pack kind '{kind}'. Choose from {list(PACK_KINDS)}."
        )
    packs = []
    for pack_dir in _pack_dirs():
        manifest = _manifest_of(pack_dir)
        if manifest is None:
            continue
        if kind is not None and manifest.get("kind") != kind:
            continue
        packs.append(manifest)
    packs.sort(key=lambda m: str(m.get("name", "")))
    return packs


def get_pack(name: str) -> dict:
    """Return ``{"manifest", "templates", "path"}`` for the named pack.

    Templates are ``[{"name", "filename", "text"}]`` with the ``.md``
    suffix stripped from ``name``. Raises TemplateError when unknown.
    """
    for pack_dir in _pack_dirs():
        manifest = _manifest_of(pack_dir)
        if manifest is None:
            continue
        if manifest.get("name") == name or pack_dir.name == name:
            templates = [
                {"name": p.stem, "filename": p.name,
                 "text": p.read_text(encoding="utf-8")}
                for p in _template_files(pack_dir)
            ]
            return {"manifest": manifest, "templates": templates,
                    "path": str(pack_dir)}
    raise TemplateError(f"Unknown template pack '{name}'.")


# ---------------------------------------------------------------------------
# Rendering (stdlib only)
# ---------------------------------------------------------------------------

def render_text(text: str, variables: dict) -> str:
    """Substitute ``{{variable}}`` placeholders; unknown ones are left as-is."""
    def _sub(match: re.Match) -> str:
        name = match.group(1)
        return str(variables[name]) if name in variables else match.group(0)

    return _VAR_RE.sub(_sub, text)


def template_variables(text: str) -> list[str]:
    """All ``{{variable}}`` names used in a template, in first-use order."""
    seen: list[str] = []
    for match in _VAR_RE.finditer(text):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def render_template(pack_name: str, template_name: str,
                    variables: dict) -> str:
    """Render one template from a pack.

    ``template_name`` is the ``.md`` stem (or full filename).
    Raises TemplateError for an unknown pack/template, or when a
    required manifest variable has no value. Optional variables left
    unset keep their ``{{placeholder}}`` in the output.
    """
    pack = get_pack(pack_name)
    manifest = pack["manifest"]
    wanted = template_name[:-3] if template_name.lower().endswith(".md") \
        else template_name
    match = next(
        (t for t in pack["templates"]
         if t["name"] == wanted or t["filename"] == template_name),
        None,
    )
    if match is None:
        available = [t["name"] for t in pack["templates"]]
        raise TemplateError(
            f"Pack '{pack_name}' has no template '{template_name}'. "
            f"Available: {available}."
        )
    declared = {
        v.get("name"): bool(v.get("required"))
        for v in manifest.get("variables", [])
        if isinstance(v, dict) and v.get("name")
    }
    missing = [n for n, req in declared.items() if req and n not in variables]
    if missing:
        raise TemplateError(
            f"Template '{template_name}' in pack '{pack_name}' is missing "
            f"required variables: {missing}."
        )
    return render_text(match["text"], variables)


def _pack_root(extracted: Path) -> Path:
    """Pick the pack dir inside an extracted zip.

    Handles zips that put the pack at the root (manifest.json at top
    level, as :func:`pack_to_zip` writes) and zips that wrap the pack in
    a single enclosing folder.
    """
    if (extracted / "manifest.json").is_file():
        return extracted
    roots = [p for p in extracted.iterdir() if p.is_dir()]
    return roots[0] if roots else extracted


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_pack(path: str | Path) -> dict:
    """Load a pack from a directory or a ``.candidpack`` zip.

    Returns the same dict shape as :func:`get_pack`.
    """
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".candidpack":
        tmp = Path(tempfile.mkdtemp(prefix="candid-pack-"))
        try:
            _extract_zip(path, tmp)
            pack_dir = _pack_root(tmp)
            return _load_pack_dir(pack_dir, original=str(path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return _load_pack_dir(path, original=str(path))


def _load_pack_dir(pack_dir: Path, original: str) -> dict:
    manifest = _manifest_of(pack_dir)
    if manifest is None:
        raise TemplateError(
            f"No readable manifest.json in pack at '{pack_dir}'."
        )
    manifest["path"] = original
    templates = [
        {"name": p.stem, "filename": p.name,
         "text": p.read_text(encoding="utf-8")}
        for p in _template_files(pack_dir)
    ]
    return {"manifest": manifest, "templates": templates, "path": original}


def save_pack(pack: dict, dest_dir: str | Path) -> Path:
    """Write a pack dict (``manifest`` + ``templates``) to ``dest_dir``.

    Returns the destination directory path.
    """
    dest = Path(dest_dir)
    manifest = dict(pack.get("manifest", {}))
    manifest.pop("path", None)
    templates_dir = dest / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for tpl in pack.get("templates", []):
        filename = tpl.get("filename") or f"{tpl.get('name', 'template')}.md"
        if not filename.lower().endswith(".md"):
            filename += ".md"
        filename = Path(filename).name  # never escape templates/
        (templates_dir / filename).write_text(
            tpl.get("text", ""), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_questions_sources(text: str, filename: str, issues: list[str]) -> None:
    """Verified-only rule: every question block needs a ``Source:`` line.

    A question block is a bullet/numbered-list item group (blank-line
    separated). Each block must contain a line starting with ``Source:``.
    """
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = block.splitlines()
        if not lines or not _QUESTION_LINE_RE.match(lines[0]):
            continue
        if not any(_SOURCE_LINE_RE.match(line) for line in lines):
            snippet = lines[0].strip()[:60]
            issues.append(
                f"template '{filename}': question block has no 'Source:' "
                f"line: '{snippet}...'"
            )


def validate_pack(path: str | Path) -> dict:
    """Validate a pack directory (or ``.candidpack`` zip).

    Returns ``{"ok": bool, "issues": [str]}``. Checks: manifest exists
    and is complete, name is a slug, version and min_candid_version are
    semver, kind is known, variables are well-formed, every ``{{var}}``
    used in a template is declared in the manifest, templates are
    non-empty, and (for ``questions`` packs) every question block has a
    ``Source:`` line. A newer ``min_candid_version`` than the running
    candid is also flagged.
    """
    path = Path(path)
    issues: list[str] = []

    if path.is_file() and path.suffix.lower() == ".candidpack":
        tmp = Path(tempfile.mkdtemp(prefix="candid-pack-validate-"))
        try:
            _extract_zip(path, tmp)
            result = validate_pack(_pack_root(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return result

    if not path.is_dir():
        return {"ok": False, "issues": [f"pack path '{path}' is not a directory"]}
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "issues": ["missing manifest.json"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "issues": [f"manifest.json is not valid JSON: {exc}"]}
    if not isinstance(manifest, dict):
        return {"ok": False, "issues": ["manifest.json must be a JSON object"]}

    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            issues.append(f"manifest: missing required field '{field}'")

    name = manifest.get("name", "")
    if name and not _SLUG_RE.match(str(name)):
        issues.append(
            f"manifest: name '{name}' is not a slug (lowercase letters, "
            "digits, hyphens)"
        )

    for field in ("version", "min_candid_version"):
        value = manifest.get(field)
        if value and not _SEMVER_RE.match(str(value)):
            issues.append(
                f"manifest: {field} '{value}' is not valid semver (X.Y.Z)"
            )

    kind = manifest.get("kind")
    if kind and kind not in PACK_KINDS:
        issues.append(
            f"manifest: kind '{kind}' is not one of {list(PACK_KINDS)}"
        )

    variables = manifest.get("variables", [])
    declared: dict[str, bool] = {}
    if isinstance(variables, list):
        for i, var in enumerate(variables):
            if not isinstance(var, dict):
                issues.append(f"manifest: variables[{i}] must be an object")
                continue
            vname = var.get("name")
            if not vname or not isinstance(vname, str):
                issues.append(f"manifest: variables[{i}] needs a 'name'")
                continue
            if vname in declared:
                issues.append(f"manifest: duplicate variable '{vname}'")
            declared[vname] = bool(var.get("required"))
            if "description" not in var:
                issues.append(
                    f"manifest: variable '{vname}' is missing 'description'"
                )
    elif "variables" in manifest:
        issues.append("manifest: 'variables' must be a list")

    min_version = manifest.get("min_candid_version")
    if (min_version and _SEMVER_RE.match(str(min_version))
            and _SEMVER_RE.match(CANDID_VERSION)
            and _semver_tuple(str(min_version)) > _semver_tuple(CANDID_VERSION)):
        issues.append(
            f"manifest: min_candid_version {min_version} is newer than "
            f"candid {CANDID_VERSION}"
        )

    templates_dir = path / "templates"
    files = _template_files(path)
    if not templates_dir.is_dir():
        issues.append("pack: missing templates/ directory")
    elif not files:
        issues.append("pack: templates/ has no .md files")

    for tpl_path in files:
        try:
            text = tpl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"template '{tpl_path.name}': unreadable: {exc}")
            continue
        if not text.strip():
            issues.append(f"template '{tpl_path.name}' is empty")
            continue
        for var in template_variables(text):
            if var not in declared:
                issues.append(
                    f"template '{tpl_path.name}': uses undeclared variable "
                    f"'{{{{{var}}}}}'"
                )
        if kind == "questions":
            _check_questions_sources(text, tpl_path.name, issues)

    return {"ok": not issues, "issues": issues}


# ---------------------------------------------------------------------------
# Zip support (with zip-slip protection)
# ---------------------------------------------------------------------------

def _extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract a zip into dest_dir; raises TemplateError on path traversal."""
    dest = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute():
                raise TemplateError(
                    f"Refusing to extract absolute path '{member.filename}' "
                    f"from '{zip_path}'."
                )
            target = (dest / member_path).resolve()
            if target != dest and dest not in target.parents:
                raise TemplateError(
                    f"Refusing to extract '{member.filename}': path escapes "
                    f"the destination directory."
                )
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    return dest


def pack_to_zip(pack_dir: str | Path, dest: str | Path) -> Path:
    """Zip a pack directory into a ``.candidpack`` file. Returns its path."""
    pack_dir = Path(pack_dir)
    dest = Path(dest)
    if dest.suffix.lower() != ".candidpack":
        dest = dest.with_suffix(".candidpack")
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        raise TemplateError(f"'{pack_dir}' is not a pack (no manifest.json).")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, "manifest.json")
        for tpl_path in _template_files(pack_dir):
            zf.write(tpl_path, f"templates/{tpl_path.name}")
    return dest


def pack_from_zip(zip_path: str | Path, dest_dir: str | Path) -> Path:
    """Extract a ``.candidpack`` zip into dest_dir (zip-slip protected)."""
    zip_path = Path(zip_path)
    dest = Path(dest_dir)
    if not zip_path.is_file():
        raise TemplateError(f"Zip file '{zip_path}' does not exist.")
    dest.mkdir(parents=True, exist_ok=True)
    return _extract_zip(zip_path, dest)
