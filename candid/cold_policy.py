"""Cold-archival retention policies for candid.

One place that decides *what* gets archived, compressed, and eventually
deleted from cold storage, and in what order:

1. ``archive_old_cycles``  — move stale closed applications into cold storage
2. ``compress_stale_data``  — compress stale search/curation data into archives
3. ``prune_archives``       — delete archives older than the retention window

Sibling modules (``candid.coldstore``, ``candid.cold_cycles``,
``candid.cold_searchdata``, ``candid.cold_verify``) are imported lazily
inside functions so this module stays importable even while they are being
developed concurrently.  ``candid.config.DATA_DIR`` is resolved dynamically
at call time (via coldstore), so tests can point it at a tmp dir.

Safety rules:
- An archive is never deleted unless it passes verification.
- ``prune_archives`` always keeps at least ``keep_minimum`` newest archives.
- ``policy_report`` and any ``dry_run=True`` call change nothing.
- A failing step is recorded under ``"errors"`` instead of aborting the run.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import zipfile
from datetime import datetime, timezone

DEFAULT_POLICY = {
    "cycles_after_days": 90,
    "searchdata_after_days": 30,
    "prune_archives_after_days": 365,
    "min_archives_to_keep": 1,
}

# parameter names a sibling step might use for its age threshold
_THRESHOLD_PARAM_NAMES = ("days", "older_than_days", "age_days", "threshold_days")

# keys a verify_all() result might use for failed archives
_FAILED_KEYS = ("failed", "failures", "bad", "invalid", "corrupt", "errors")
# keys a verify_all() result might use for verified archives
_OK_KEYS = ("verified", "ok", "passed", "valid", "good")
# keys a verify_all() result might use for per-archive detail rows
_DETAIL_KEYS = ("results", "archives", "details", "items", "checks")
# per-archive flags meaning "this archive passed verification"
_OK_FLAGS = ("ok", "valid", "verified", "passed", "success")


def load_policy(overrides: dict | None = None) -> dict:
    """Return the effective retention policy: defaults merged with overrides.

    Pure function — no file I/O.  Unknown override keys are kept as-is so
    callers can extend the policy without breaking this merge.
    """
    policy = dict(DEFAULT_POLICY)
    if overrides:
        policy.update(dict(overrides))
    return policy


def _coldstore():
    return importlib.import_module("candid.coldstore")


def _call_days_dryrun(fn, days: int, dry_run: bool):
    """Call a sibling archival step with an age threshold and dry_run flag.

    Tolerates the different parameter names used across the concurrently
    built sibling modules (``days`` vs ``older_than_days``), falling back to
    positional passing when no recognised keyword matches.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(days, dry_run)

    names = set(params)
    kwargs: dict = {}
    if "dry_run" in names:
        kwargs["dry_run"] = bool(dry_run)
    for cand in _THRESHOLD_PARAM_NAMES:
        if cand in names:
            kwargs[cand] = days
            break
    else:
        positional = [
            p
            for p in params.values()
            if p.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if positional:
            return fn(days, **kwargs)
    return fn(**kwargs)


def _manifest_age_days(manifest: dict) -> float | None:
    """Age of an archive in days from its manifest ``created_utc``.

    Returns None when the timestamp is missing or unparseable (such an
    archive is treated as *not* old enough to prune).
    """
    raw = manifest.get("created_utc")
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() / 86400.0


def _archive_sort_key(manifest: dict) -> tuple:
    # ISO-8601 UTC timestamps sort chronologically as plain strings.
    return (str(manifest.get("created_utc") or ""), str(manifest.get("archive_id") or ""))


def _id_of(item) -> str | None:
    if isinstance(item, str):
        return item or None
    if isinstance(item, dict):
        for key in ("archive_id", "id", "name"):
            val = item.get(key)
            if val:
                return str(val)
    return None


def _row_failed(item: dict) -> tuple[bool, str]:
    """(failed, reason) for one per-archive verification detail row."""
    present = [k for k in _OK_FLAGS if k in item]
    if present:
        if all(item[k] for k in present):
            return False, ""
        reason = (
            item.get("error") or item.get("reason") or item.get("message") or "failed verification"
        )
        return True, str(reason)
    return False, ""


def _failed_from_verify(result, known_ids: set[str]) -> dict[str, str]:
    """Extract ``{archive_id: reason}`` failures from a verify_all() result.

    Accepts several result shapes since the verifier is built concurrently:
    ``{"failed": [...]}``, ``{"verified": [...]}`` (invert against known ids),
    ``{"results": [{archive_id, ok, ...}]}``, or a bare list of detail rows.
    """
    failed: dict[str, str] = {}

    def add(item, reason: str = "failed verification"):
        aid = _id_of(item)
        if not aid:
            return
        if isinstance(item, dict):
            reason = str(
                item.get("error") or item.get("reason") or item.get("message") or reason
            )
        failed.setdefault(aid, reason)

    rows: list = []
    if isinstance(result, dict):
        for key in _FAILED_KEYS:
            val = result.get(key)
            if isinstance(val, dict):
                for aid, reason in val.items():
                    failed.setdefault(str(aid), str(reason))
            elif isinstance(val, (list, tuple)):
                for item in val:
                    add(item)
        for key in _DETAIL_KEYS:
            val = result.get(key)
            if isinstance(val, (list, tuple)):
                rows.extend(val)
        if not failed and not rows:
            for key in _OK_KEYS:
                val = result.get(key)
                if isinstance(val, (list, tuple, set)):
                    good = {_id_of(i) for i in val}
                    good.discard(None)
                    for aid in known_ids - good:
                        failed.setdefault(aid, "not reported as verified")
                    break
    elif isinstance(result, (list, tuple)):
        rows.extend(result)

    for row in rows:
        if isinstance(row, dict):
            is_failed, reason = _row_failed(row)
            if is_failed:
                add(row, reason)

    return failed


def _verify_local(archive_id: str, cold) -> tuple[bool, str]:
    """Verify one archive directly: manifest present, members hash-match."""
    try:
        path = cold.archive_root() / f"{archive_id}.zip"
        with zipfile.ZipFile(path) as zf:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except KeyError:
                return False, "missing manifest.json"
            expected = manifest.get("files") or {}
            for name, digest in expected.items():
                try:
                    data = zf.read(name)
                except KeyError:
                    return False, f"missing member {name!r}"
                if hashlib.sha256(data).hexdigest() != digest:
                    return False, f"hash mismatch for member {name!r}"
        return True, ""
    except zipfile.BadZipFile as exc:
        return False, f"corrupt zip: {exc}"
    except Exception as exc:  # unreadable file etc.
        return False, str(exc)


def _verification_map(archives: list[dict]) -> tuple[set[str], dict[str, str], list[dict]]:
    """Return (verified_ids, {archive_id: reason}, errors).

    Calls ``candid.cold_verify.verify_all`` first; when it is unavailable or
    raises, falls back to direct local verification of each archive.
    Archives never seen in a successful verification are treated as failed
    (never pruned).
    """
    cold = _coldstore()
    known = {str(m.get("archive_id")) for m in archives if m.get("archive_id")}
    errors: list[dict] = []
    try:
        mod = importlib.import_module("candid.cold_verify")
        verify_all = getattr(mod, "verify_all")
    except ImportError as exc:
        errors.append(
            {"step": "verify_all", "error": f"candid.cold_verify unavailable: {exc}"}
        )
        verify_all = None
    except Exception as exc:
        errors.append({"step": "verify_all", "error": f"import failed: {exc}"})
        verify_all = None

    if verify_all is not None:
        try:
            failed = _failed_from_verify(verify_all(), known)
            verified = known - set(failed)
            return verified, failed, errors
        except Exception as exc:
            errors.append({"step": "verify_all", "error": str(exc)})
            # fall through to local verification

    verified: set[str] = set()
    failed: dict[str, str] = {}
    for aid in sorted(known):
        ok, reason = _verify_local(aid, cold)
        if ok:
            verified.add(aid)
        else:
            failed[aid] = reason
    return verified, failed, errors


def _err(step: str, exc: BaseException) -> dict:
    return {"step": step, "error": f"{type(exc).__name__}: {exc}"}


def prune_archives(
    older_than_days: int = 365,
    dry_run: bool = False,
    keep_minimum: int = 1,
) -> dict:
    """Delete archives older than ``older_than_days`` (by manifest created_utc).

    The ``keep_minimum`` newest archives are always kept, even when older
    than the threshold.  An archive that fails verification is never
    deleted; such ids are reported under ``"skipped_unverified"``.

    Returns ``{"deleted": [ids], "kept": n, "dry_run": bool,
    "skipped_unverified": [ids], "errors": [...]}``.  With ``dry_run=True``
    nothing is deleted; ``"deleted"`` lists what *would* be deleted.
    """
    cold = _coldstore()
    dry_run = bool(dry_run)
    report: dict = {
        "deleted": [],
        "kept": 0,
        "dry_run": dry_run,
        "skipped_unverified": [],
        "errors": [],
    }
    try:
        archives = cold.list_archives()
    except Exception as exc:
        report["errors"].append(_err("list_archives", exc))
        return report

    archives = sorted(archives, key=_archive_sort_key, reverse=True)
    keep_minimum = max(0, int(keep_minimum))
    protected = {
        str(m.get("archive_id")) for m in archives[:keep_minimum] if m.get("archive_id")
    }

    verified, failed, verify_errors = _verification_map(archives)
    report["errors"].extend(verify_errors)

    for manifest in archives:
        aid = str(manifest.get("archive_id") or "")
        if not aid or aid in protected:
            continue
        age = _manifest_age_days(manifest)
        if age is None or age <= max(0, older_than_days):
            continue  # not old enough (or undatable) -> kept
        if aid in failed or aid not in verified:
            report["skipped_unverified"].append(aid)
            continue
        if dry_run:
            report["deleted"].append(aid)
            continue
        try:
            if cold.delete_archive(aid):
                report["deleted"].append(aid)
            else:
                report["errors"].append(
                    {"step": "prune_archives", "error": f"archive vanished before delete: {aid}"}
                )
        except Exception as exc:
            report["errors"].append(_err("prune_archives", exc))

    report["kept"] = len(archives) - len(report["deleted"])
    return report


def policy_report(policy: dict | None = None) -> dict:
    """Read-only preview of what ``apply_policies`` would do.

    Runs every step in dry-run mode: counts of archivable cycles (via
    ``archive_old_cycles``), compressible search data (via
    ``compress_stale_data``), and prunable archives (via ``prune_archives``).
    Changes nothing.
    """
    policy = load_policy(policy)
    report: dict = {
        "policy": policy,
        "dry_run": True,
        "cycles": None,
        "searchdata": None,
        "prune": None,
        "errors": [],
    }
    try:
        cycles = importlib.import_module("candid.cold_cycles")
        report["cycles"] = _call_days_dryrun(
            cycles.archive_old_cycles, policy["cycles_after_days"], True
        )
    except Exception as exc:
        report["errors"].append(_err("archive_old_cycles", exc))
    try:
        searchdata = importlib.import_module("candid.cold_searchdata")
        report["searchdata"] = _call_days_dryrun(
            searchdata.compress_stale_data, policy["searchdata_after_days"], True
        )
    except Exception as exc:
        report["errors"].append(_err("compress_stale_data", exc))
    try:
        report["prune"] = prune_archives(
            older_than_days=policy["prune_archives_after_days"],
            dry_run=True,
            keep_minimum=policy["min_archives_to_keep"],
        )
    except Exception as exc:
        report["errors"].append(_err("prune_archives", exc))
    return report


def apply_policies(policy: dict | None = None, dry_run: bool = False) -> dict:
    """Apply the retention policy end to end and return one combined report.

    Steps run in order: archive old cycles, compress stale search data, then
    prune old archives.  A failing step is recorded under ``"errors"`` and
    the remaining steps still run.  With ``dry_run=True`` nothing changes.
    """
    policy = load_policy(policy)
    dry_run = bool(dry_run)
    report: dict = {
        "policy": policy,
        "dry_run": dry_run,
        "archive_cycles": None,
        "compress_searchdata": None,
        "prune_archives": None,
        "errors": [],
    }
    try:
        cycles = importlib.import_module("candid.cold_cycles")
        report["archive_cycles"] = _call_days_dryrun(
            cycles.archive_old_cycles, policy["cycles_after_days"], dry_run
        )
    except Exception as exc:
        report["errors"].append(_err("archive_old_cycles", exc))
    try:
        searchdata = importlib.import_module("candid.cold_searchdata")
        report["compress_searchdata"] = _call_days_dryrun(
            searchdata.compress_stale_data, policy["searchdata_after_days"], dry_run
        )
    except Exception as exc:
        report["errors"].append(_err("compress_stale_data", exc))
    try:
        report["prune_archives"] = prune_archives(
            older_than_days=policy["prune_archives_after_days"],
            dry_run=dry_run,
            keep_minimum=policy["min_archives_to_keep"],
        )
    except Exception as exc:
        report["errors"].append(_err("prune_archives", exc))
    return report
