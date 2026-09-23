"""Template pack import/export, versioning and diff (batch-106, worker C).

A *pack* is a directory with this layout::

    <pack-dir>/
        manifest.json
        templates/
            <template files...>

``manifest.json`` schema::

    {
      "name": "cover-letters",        # required, filesystem-safe
      "version": "1.2.0",             # required, semver
      "kind": "cover-letter",        # optional
      "description": "...",          # optional
      "author": "...",               # optional
      "templates": [                 # optional, default []
        {"file": "templates/terse.md",
         "name": "terse",            # defaults to the file stem
         "kind": "cover-letter",
         "description": "..."},
        ...
      ]
    }

Installed packs live side by side under the user packs dir
(``~/.config/candid/packs``) as ``<name>@<version>`` directories, so
several versions of one pack can coexist.

An exported pack is a ``.candidpack`` zip archive::

    manifest.json
    templates/<files>
    checksums.sha256      # "<sha256>  <arcname>" for every other entry

Worker A's ``candid/templates.py`` (TemplateError, list_packs, get_pack,
validate_pack, pack_to_zip/pack_from_zip) is used opportunistically when
present; everything here also works standalone without it.

Stdlib only.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from candid import config as C

try:  # worker A's module — prefer its TemplateError when available
    from candid.templates import TemplateError
except ImportError:  # pragma: no cover - worker A not merged yet
    class TemplateError(Exception):
        """Raised for template-pack problems (export/import/version/diff)."""


# ---------------------------------------------------------------------------
# small semver parser (stdlib only)
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)"
    r"(?:-([0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_semver(version: str) -> tuple[int, int, int, tuple]:
    """Parse ``MAJOR.MINOR.PATCH[-prerelease]``; raises TemplateError."""
    m = _SEMVER_RE.match(str(version).strip())
    if not m:
        raise TemplateError(
            f"Invalid version {version!r}: expected MAJOR.MINOR.PATCH "
            "(e.g. '1.2.0')."
        )
    pre = tuple(m.group(4).split(".")) if m.group(4) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre)


def _pre_key(pre: tuple) -> tuple:
    # numeric identifiers sort before alphanumeric ones (semver rule)
    key = []
    for ident in pre:
        if ident.isdigit():
            key.append((0, int(ident), ""))
        else:
            key.append((1, 0, ident))
    return tuple(key)


def _semver_key(version: str) -> tuple:
    major, minor, patch, pre = parse_semver(version)
    # a release (no prerelease) is newer than any prerelease of the same numbers
    return ((major, minor, patch), 1 if not pre else 0, _pre_key(pre))


def compare_semver(a: str, b: str) -> int:
    """Return -1, 0 or 1 comparing two version strings."""
    ka, kb = _semver_key(a), _semver_key(b)
    return (ka > kb) - (ka < kb)


# ---------------------------------------------------------------------------
# paths and worker-A interop (lazy, best-effort)
# ---------------------------------------------------------------------------

def user_packs_dir() -> Path:
    """User pack storage dir (overridable in tests via candid.config)."""
    return Path(C.CONFIG_DIR) / "packs"


def _templates_api():
    """Worker A's candid.templates module, or None if not importable.

    Uses sys.modules directly so tests can inject a fake module.
    """
    mod = sys.modules.get("candid.templates")
    if mod is not None:
        return mod
    try:
        import importlib

        return importlib.import_module("candid.templates")
    except ImportError:
        return None


def _check_name(name: str, what: str = "pack name") -> str:
    name = str(name).strip()
    if not _NAME_RE.match(name):
        raise TemplateError(
            f"Invalid {what} {name!r}: use letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return name


# ---------------------------------------------------------------------------
# manifest handling
# ---------------------------------------------------------------------------

MANIFEST_FIELDS = ("name", "version", "kind", "description", "author")


def read_manifest(pack_dir: Path | str) -> dict:
    """Read and JSON-parse a pack's manifest.json; raises TemplateError."""
    path = Path(pack_dir) / "manifest.json"
    if not path.is_file():
        raise TemplateError(f"No manifest.json in pack directory {pack_dir}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise TemplateError(f"Cannot read manifest {path}: {e}")
    if not isinstance(data, dict):
        raise TemplateError(f"manifest.json in {pack_dir} must be a JSON object.")
    return data


def validate_manifest_dict(manifest: dict) -> list[str]:
    """Structural checks on a manifest dict. Returns a list of issues."""
    issues: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append("manifest: 'name' is required (non-empty string)")
    elif not _NAME_RE.match(name.strip()):
        issues.append(f"manifest: invalid 'name' {name!r}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        issues.append("manifest: 'version' is required (semver string)")
    else:
        try:
            parse_semver(version)
        except TemplateError as e:
            issues.append(f"manifest: {e}")
    templates = manifest.get("templates", [])
    if not isinstance(templates, list):
        issues.append("manifest: 'templates' must be a list")
    else:
        seen = set()
        for i, entry in enumerate(templates):
            where = f"manifest: templates[{i}]"
            if not isinstance(entry, dict):
                issues.append(f"{where} must be an object")
                continue
            rel = entry.get("file")
            if not isinstance(rel, str) or not rel.strip():
                issues.append(f"{where} needs a 'file' path")
            else:
                parts = PurePosixPath(rel.replace("\\", "/")).parts
                if rel.startswith("/") or ".." in parts:
                    issues.append(f"{where}: 'file' must be a relative path "
                                  f"inside the pack: {rel!r}")
                elif not rel.startswith("templates/"):
                    issues.append(f"{where}: 'file' should live under "
                                  f"'templates/': {rel!r}")
            tname = entry.get("name") or Path(rel or "").stem
            if tname in seen:
                issues.append(f"{where}: duplicate template name {tname!r}")
            seen.add(tname)
    return issues


def _manifest_files_exist(manifest: dict, pack_dir: Path) -> list[str]:
    issues: list[str] = []
    for entry in manifest.get("templates", []) or []:
        rel = entry.get("file", "")
        if rel and not (pack_dir / rel).is_file():
            issues.append(f"template file listed in manifest is missing: {rel!r}")
    return issues


def validate_pack(path: Path | str) -> dict:
    """Validate a pack dir (or .candidpack file).

    Returns ``{"ok": bool, "issues": [str]}``. Merges worker A's
    ``validate_pack`` result when that module is available.
    """
    p = Path(path)
    issues: list[str] = []
    if p.is_file() and p.suffix == ".candidpack":
        try:
            manifest, _files = _read_zip_manifest(p)
        except TemplateError as e:
            return {"ok": False, "issues": [str(e)]}
        issues.extend(validate_manifest_dict(manifest))
    elif p.is_dir():
        try:
            manifest = read_manifest(p)
        except TemplateError as e:
            return {"ok": False, "issues": [str(e)]}
        issues.extend(validate_manifest_dict(manifest))
        issues.extend(_manifest_files_exist(manifest, p))
    else:
        return {"ok": False,
                "issues": [f"{p} is not a pack directory or .candidpack file"]}

    api = _templates_api()
    if api is not None and hasattr(api, "validate_pack"):
        try:
            other = api.validate_pack(path)
            if isinstance(other, dict):
                issues.extend(other.get("issues", []) or [])
                if not other.get("ok", True):
                    issues.append("candid.templates.validate_pack reported problems")
            # a non-dict truthy/falsy return is ignored; we already validated
        except Exception as e:  # never let worker A's validator break ours
            issues.append(f"candid.templates.validate_pack raised "
                          f"{type(e).__name__}: {e}")
    return {"ok": not issues, "issues": issues}


# ---------------------------------------------------------------------------
# pack resolution (installed dirs, dir paths; worker A as fallback source)
# ---------------------------------------------------------------------------

def _installed_dirs(name: str | None = None) -> list[tuple[str, str, Path]]:
    """(name, version, dir) for installed ``<name>@<version>`` dirs."""
    base = user_packs_dir()
    out: list[tuple[str, str, Path]] = []
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir() or "@" not in child.name:
            continue
        pname, _, pver = child.name.rpartition("@")
        if not pname or not _NAME_RE.match(pname):
            continue
        try:
            parse_semver(pver)
        except TemplateError:
            continue
        if not (child / "manifest.json").is_file():
            continue
        if name is None or pname == name:
            out.append((pname, pver, child))
    return out


def _worker_a_candidates(name: str) -> list[tuple[str, str, Path]]:
    """Best-effort lookup through worker A's list_packs/get_pack."""
    api = _templates_api()
    if api is None:
        return []
    found: list[tuple[str, str, Path]] = []
    try:
        packs = api.list_packs() if hasattr(api, "list_packs") else []
    except Exception:
        packs = []
    for entry in packs or []:
        try:
            if isinstance(entry, dict):
                ename, ever, epath = (entry.get("name"), entry.get("version"),
                                     entry.get("path") or entry.get("dir"))
            else:
                ename = getattr(entry, "name", None)
                ever = getattr(entry, "version", None)
                epath = getattr(entry, "path", getattr(entry, "dir", None))
            if ename == name and epath and Path(epath).is_dir():
                found.append((ename, str(ever or "0.0.0"), Path(epath)))
        except Exception:
            continue
    if not found and hasattr(api, "get_pack"):
        try:
            entry = api.get_pack(name)
            if entry is not None:
                if isinstance(entry, dict):
                    ename, ever = entry.get("name", name), entry.get("version")
                    epath = entry.get("path") or entry.get("dir")
                else:
                    ename = getattr(entry, "name", name)
                    ever = getattr(entry, "version", None)
                    epath = getattr(entry, "path", getattr(entry, "dir", None))
                if epath and Path(epath).is_dir() and ever:
                    found.append((ename, str(ever), Path(epath)))
        except Exception:
            pass
    return found


def resolve_pack(ref: str) -> tuple[str, str, Path]:
    """Resolve a pack reference to ``(name, version, directory)``.

    ``ref`` may be a pack name, ``name@version``, or a path to a pack
    directory. With several versions installed, the newest wins.
    """
    p = Path(ref)
    if p.is_dir() and (p / "manifest.json").is_file():
        manifest = read_manifest(p)
        name = _check_name(manifest.get("name", ""), "manifest name")
        version = str(manifest.get("version", "")).strip()
        parse_semver(version)  # raises TemplateError if bad
        return name, version, p

    if "@" in ref and not p.exists():
        name, _, version = ref.rpartition("@")
        name = _check_name(name)
        parse_semver(version)
        cands = [c for c in _installed_dirs(name) if c[1] == version]
        cands += [c for c in _worker_a_candidates(name) if c[1] == version]
        if not cands:
            raise TemplateError(
                f"Pack '{name}' version {version} is not installed. "
                f"Installed: {', '.join(v for _, v, _ in _installed_dirs(name)) or 'none'}.")
        return cands[0]

    name = _check_name(ref)
    cands = _installed_dirs(name) + _worker_a_candidates(name)
    if not cands:
        raise TemplateError(
            f"Pack '{name}' is not installed (looked in {user_packs_dir()}). "
            f"Install it first with `python -m candid templates pack import`.")
    cands.sort(key=lambda c: _semver_key(c[1]))
    chosen = cands[-1]
    return chosen


# ---------------------------------------------------------------------------
# zip helpers (zip-slip safe)
# ---------------------------------------------------------------------------

CHECKSUMS_FILE = "checksums.sha256"


def _safe_arcname(name: str) -> str:
    """Normalize a zip entry name; raise TemplateError on traversal."""
    raw = name.replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise TemplateError(f"Unsafe archive entry (absolute path): {name!r}")
    parts = [p for p in PurePosixPath(raw).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise TemplateError(f"Unsafe archive entry (path traversal): {name!r}")
    return "/".join(parts)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pack_entries(pack_dir: Path, manifest: dict) -> list[tuple[str, bytes]]:
    """(arcname, bytes) for manifest + template files, sorted."""
    entries = [("manifest.json",
                (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))]
    for tname, rel in _manifest_template_files(pack_dir, manifest).items():
        data = (pack_dir / rel).read_bytes()
        entries.append((rel.replace("\\", "/"), data))
    # de-dupe on arcname, keep first; then sort for determinism
    seen: dict[str, bytes] = {}
    for arc, data in entries:
        seen.setdefault(_safe_arcname(arc), data)
    return sorted(seen.items())


def pack_to_zip(pack_dir: Path | str, out_path: Path | str) -> dict:
    """Write a ``.candidpack`` archive for a pack directory.

    Returns ``{"pack", "version", "out", "files", "sha256"}``.
    """
    out = Path(out_path)
    pdir = Path(pack_dir)
    if (pdir / "manifest.json").is_file():
        manifest = read_manifest(pdir)
        name = _check_name(manifest.get("name", ""), "manifest name")
        version = str(manifest.get("version", "")).strip()
        parse_semver(version)  # raises TemplateError if bad
    else:
        name, version, pdir = resolve_pack(str(pack_dir))
        manifest = read_manifest(pdir)
    entries = _pack_entries(pdir, manifest)
    if out.parent and str(out.parent):
        out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, data in entries:
            zf.writestr(arc, data)
        lines = "".join(f"{_sha256_bytes(data)}  {arc}\n"
                        for arc, data in entries)
        zf.writestr(CHECKSUMS_FILE, lines)
    digest = _sha256_bytes(out.read_bytes())
    return {"pack": name, "version": version, "out": str(out),
            "files": len(entries), "sha256": digest}


def _read_zip_manifest(zip_path: Path) -> tuple[dict, list[str]]:
    """Return (manifest dict, entry names) from a .candidpack file."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise TemplateError(f"{zip_path} is not a valid zip archive: {e}")
    with zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        safe = [_safe_arcname(n) for n in names]
        if "manifest.json" not in safe:
            raise TemplateError(
                f"{zip_path} is not a template pack archive "
                "(missing manifest.json).")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise TemplateError(f"Cannot read manifest.json in {zip_path}: {e}")
    if not isinstance(manifest, dict):
        raise TemplateError(f"manifest.json in {zip_path} must be a JSON object.")
    return manifest, safe


def _verify_zip(zip_path: Path) -> tuple[dict, zipfile.ZipFile]:
    """Verify archive integrity: zip-slip, manifest schema, checksums.

    Returns (manifest, open ZipFile). Caller must close the ZipFile.
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise TemplateError(f"{zip_path} is not a valid zip archive: {e}")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    safe = [_safe_arcname(n) for n in names]  # raises on traversal
    if "manifest.json" not in safe:
        zf.close()
        raise TemplateError(f"{zip_path} is not a template pack archive "
                            "(missing manifest.json).")
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as e:
        zf.close()
        raise TemplateError(f"Cannot read manifest.json in {zip_path}: {e}")
    if not isinstance(manifest, dict):
        zf.close()
        raise TemplateError("manifest.json must be a JSON object.")
    issues = validate_manifest_dict(manifest)
    if issues:
        zf.close()
        raise TemplateError("Invalid pack manifest in "
                            f"{zip_path}:\n- " + "\n- ".join(issues))
    if CHECKSUMS_FILE not in safe:
        zf.close()
        raise TemplateError(f"{zip_path} is not a verified pack archive "
                            f"(missing {CHECKSUMS_FILE}).")
    expected: dict[str, str] = {}
    for line in zf.read(CHECKSUMS_FILE).decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, arc = line.partition("  ")
        if not digest or not arc or len(digest) != 64:
            zf.close()
            raise TemplateError(f"Malformed {CHECKSUMS_FILE} in {zip_path}.")
        expected[_safe_arcname(arc)] = digest
    covered = set(safe) - {CHECKSUMS_FILE}
    if set(expected) != covered:
        zf.close()
        missing = sorted(covered - set(expected))
        extra = sorted(set(expected) - covered)
        raise TemplateError(
            f"Checksum coverage mismatch in {zip_path}: "
            + "; ".join(filter(None, [
                f"unlisted: {missing}" if missing else "",
                f"missing from archive: {extra}" if extra else "",
            ])))
    for arc in covered:
        actual = _sha256_bytes(zf.read(arc))
        if actual != expected[arc]:
            zf.close()
            raise TemplateError(
                f"Checksum mismatch for {arc!r} in {zip_path}: "
                "the archive was modified or corrupted.")
    # every manifest-listed template file must be present in the archive
    for entry in manifest.get("templates", []) or []:
        rel = (entry.get("file") or "").replace("\\", "/")
        if rel not in covered:
            zf.close()
            raise TemplateError(
                f"Template file {rel!r} listed in the manifest is "
                f"missing from {zip_path}.")
    return manifest, zf


def pack_from_zip(zip_path: Path | str, dest_dir: Path | str) -> dict:
    """Verify a ``.candidpack`` and extract it into ``dest_dir``.

    Returns ``{"pack", "version", "dest", "files"}``.
    """
    zpath = Path(zip_path)
    if not zpath.is_file():
        raise TemplateError(f"Pack file not found: {zpath}")
    manifest, zf = _verify_zip(zpath)
    dest = Path(dest_dir)
    try:
        with zf:
            for info in zf.infolist():
                if info.filename.endswith("/"):
                    continue
                arc = _safe_arcname(info.filename)
                if arc == CHECKSUMS_FILE:
                    continue
                target = dest / arc
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as fh:
                    shutil.copyfileobj(src, fh)
    finally:
        try:
            zf.close()
        except Exception:
            pass
    name = manifest["name"]
    version = str(manifest["version"])
    files = len(_manifest_template_files(dest, manifest))
    return {"pack": name, "version": version, "dest": str(dest), "files": files}


# ---------------------------------------------------------------------------
# export / import / upgrade
# ---------------------------------------------------------------------------

def export_pack(ref: str, out: str | None = None) -> dict:
    """Validate a pack and export it as a ``.candidpack`` archive.

    Returns ``{"pack", "version", "out", "files", "sha256"}``.
    """
    name, version, pdir = resolve_pack(ref)
    check = validate_pack(pdir)
    if not check["ok"]:
        raise TemplateError("Pack validation failed:\n- "
                            + "\n- ".join(check["issues"]))
    out_path = Path(out) if out else Path(f"{name}-{version}.candidpack")
    return pack_to_zip(pdir, out_path)


def _installed_versions(name: str) -> list[str]:
    return sorted((v for _, v, _ in _installed_dirs(name)),
                  key=_semver_key)


def import_pack(zip_path: str | Path, force: bool = False) -> dict:
    """Verify and install a ``.candidpack`` into the user packs dir.

    Refuses when the same version is already installed, or when the
    incoming version is older than an installed one, unless ``force``.
    """
    zpath = Path(zip_path)
    if not zpath.is_file():
        raise TemplateError(f"Pack file not found: {zpath}")
    manifest, zf = _verify_zip(zpath)
    try:
        zf.close()
    except Exception:
        pass
    name = _check_name(manifest["name"])
    version = str(manifest["version"]).strip()
    target = user_packs_dir() / f"{name}@{version}"
    installed = _installed_versions(name)
    if target.is_dir() and not force:
        raise TemplateError(
            f"Pack '{name}' version {version} is already installed at {target}. "
            "Re-run with --force to reinstall it.")
    if not force:
        newer = [v for v in installed if compare_semver(v, version) > 0]
        if newer:
            raise TemplateError(
                f"Refusing to install '{name}' {version}: newer version(s) "
                f"already installed ({', '.join(newer)}). Re-run with --force "
                "to install this older version anyway.")
    replaced = target.is_dir()
    if replaced:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    result = pack_from_zip(zpath, target)
    result["installed_path"] = str(target)
    result["replaced"] = replaced
    return result


def upgrade_pack(zip_path: str | Path) -> dict:
    """Install a ``.candidpack`` only if its version is newer than every
    installed version of the same pack. Returns the import result plus
    ``previous`` (newest previously installed version, or None)."""
    zpath = Path(zip_path)
    if not zpath.is_file():
        raise TemplateError(f"Pack file not found: {zpath}")
    manifest, _names = _read_zip_manifest(zpath)
    issues = validate_manifest_dict(manifest)
    if issues:
        raise TemplateError("Invalid pack manifest in "
                            f"{zpath}:\n- " + "\n- ".join(issues))
    name = _check_name(manifest["name"])
    version = str(manifest["version"]).strip()
    installed = _installed_versions(name)
    if installed and compare_semver(version, installed[-1]) <= 0:
        raise TemplateError(
            f"Pack '{name}' {version} is not newer than installed "
            f"version(s) ({', '.join(installed)}): nothing to upgrade.")
    result = import_pack(zpath, force=False)
    result["previous"] = installed[-1] if installed else None
    return result


def pack_versions(name: str) -> dict:
    """List installed versions of a pack (side-by-side dirs)."""
    name = _check_name(name)
    versions = []
    for pname, version, pdir in _installed_dirs(name):
        try:
            manifest = read_manifest(pdir)
        except TemplateError:
            manifest = {}
        versions.append({
            "version": version,
            "path": str(pdir),
            "kind": manifest.get("kind", ""),
            "description": manifest.get("description", ""),
            "templates": len(_manifest_template_files(pdir, manifest)),
        })
    versions.sort(key=lambda v: _semver_key(v["version"]))
    return {"pack": name, "versions": versions}


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def _manifest_template_files(pack_dir: Path, manifest: dict) -> dict[str, str]:
    """{template name: relative file path} for a pack.

    Prefers the manifest's ``templates`` entries; falls back to scanning
    ``templates/*.md`` so packs authored to the worker-A schema (no
    ``templates`` list in the manifest) work too.
    """
    entries = manifest.get("templates") or []
    if entries:
        out = {}
        for entry in entries:
            rel = entry.get("file", "")
            tname = entry.get("name") or Path(rel).stem
            out[tname] = rel
        return out
    tdir = pack_dir / "templates"
    if tdir.is_dir():
        return {p.stem: f"templates/{p.name}" for p in sorted(tdir.glob("*.md"))}
    return {}


def _load_pack_snapshot(pack_dir: Path) -> tuple[dict, dict[str, str]]:
    """(manifest, {template name: text}) for a pack directory."""
    manifest = read_manifest(pack_dir)
    texts: dict[str, str] = {}
    for tname, rel in _manifest_template_files(pack_dir, manifest).items():
        fp = pack_dir / rel
        try:
            texts[tname] = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texts[tname] = ""
    return manifest, texts


def _snapshot_for_ref(ref: str) -> tuple[str, dict, dict[str, str], tempfile.TemporaryDirectory | None]:
    """Resolve a diff operand (name[@version], dir, or .candidpack file)."""
    p = Path(ref)
    if p.is_file() and p.suffix == ".candidpack":
        tmp = tempfile.TemporaryDirectory(prefix="candid-pack-diff-")
        try:
            pack_from_zip(p, Path(tmp.name))
            manifest, texts = _load_pack_snapshot(Path(tmp.name))
        except Exception:
            tmp.cleanup()
            raise
        label = f"{manifest.get('name', ref)}@{manifest.get('version', '?')} ({p.name})"
        return label, manifest, texts, tmp
    name, version, pdir = resolve_pack(ref)
    manifest, texts = _load_pack_snapshot(pdir)
    return f"{name}@{version}", manifest, texts, None


def diff_packs(a_ref: str, b_ref: str) -> dict:
    """Diff two packs (names, name@version, dirs, or .candidpack files).

    Returns ``{"a", "b", "manifest_changes", "added", "removed",
    "changed": [{"name", "diff"}]}``.
    """
    label_a, man_a, text_a, tmp_a = _snapshot_for_ref(a_ref)
    try:
        label_b, man_b, text_b, tmp_b = _snapshot_for_ref(b_ref)
        try:
            manifest_changes = []
            for field in MANIFEST_FIELDS:
                va, vb = man_a.get(field, ""), man_b.get(field, "")
                if va != vb:
                    manifest_changes.append({"field": field, "a": va, "b": vb})
            names_a, names_b = set(text_a), set(text_b)
            added = sorted(names_b - names_a)
            removed = sorted(names_a - names_b)
            changed = []
            for tname in sorted(names_a & names_b):
                if text_a[tname] != text_b[tname]:
                    diff = "".join(difflib.unified_diff(
                        text_a[tname].splitlines(keepends=True),
                        text_b[tname].splitlines(keepends=True),
                        fromfile=f"a/{tname}", tofile=f"b/{tname}"))
                    changed.append({"name": tname, "diff": diff})
            return {"a": label_a, "b": label_b,
                    "manifest_changes": manifest_changes,
                    "added": added, "removed": removed, "changed": changed}
        finally:
            if tmp_b is not None:
                tmp_b.cleanup()
    finally:
        if tmp_a is not None:
            tmp_a.cleanup()


def render_diff_human(result: dict) -> str:
    """Human-readable rendering of a diff_packs() result."""
    lines = [f"diff {result['a']} -> {result['b']}", ""]
    mc = result["manifest_changes"]
    if mc:
        lines.append("manifest changes:")
        for c in mc:
            lines.append(f"  {c['field']}: {c['a']!r} -> {c['b']!r}")
        lines.append("")
    for key, title in (("added", "added templates"),
                       ("removed", "removed templates")):
        items = result[key]
        lines.append(f"{title} ({len(items)}):")
        lines.extend(f"  + {n}" if key == "added" else f"  - {n}" for n in items)
        lines.append("")
    changed = result["changed"]
    lines.append(f"changed templates ({len(changed)}):")
    for c in changed:
        lines.append(f"  ~ {c['name']}")
        for dl in c["diff"].splitlines():
            lines.append(f"    {dl}")
    return "\n".join(lines).rstrip()


def render_versions_human(result: dict) -> str:
    """Human-readable rendering of a pack_versions() result."""
    versions = result["versions"]
    if not versions:
        return f"No installed versions of pack '{result['pack']}'."
    lines = [f"pack '{result['pack']}' — {len(versions)} installed version(s):"]
    for v in versions:
        extra = f" [{v['kind']}]" if v["kind"] else ""
        lines.append(f"  {v['version']}{extra} — "
                     f"{v['templates']} template(s) — {v['path']}")
    return "\n".join(lines)
