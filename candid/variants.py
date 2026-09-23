"""Resume variant A/B tracking.

Registers the tailored resume files you actually sent (or plan to send)
for tracked applications — e.g. the different tones/lengths produced by
`python -m candid tailor resume` — then reports which variants got
responses or interviews by joining against the application tracker.

Registry lives at DATA_DIR/"resume_variants.json" (a JSON list, git-ignored).
Tailored resume files themselves live under config.TAILOR_DIR; the registry
just records their paths plus the tone/length/label used to produce them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import tracker as TR


class VariantsError(Exception):
    """User-facing variant registry error. Never a traceback."""


def _registry_path(path: str | Path | None) -> Path:
    return Path(path) if path else C.DATA_DIR / "resume_variants.json"


def _load(path: str | Path | None = None) -> list[dict]:
    p = _registry_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VariantsError(
            f"Variant registry {p} is not valid JSON: {exc}. "
            "Next: python -m candid variants list"
        ) from exc
    if not isinstance(data, list):
        raise VariantsError(
            f"Variant registry {p} should contain a JSON list. "
            "Next: python -m candid variants list"
        )
    return data


def _save(variants: list[dict], path: str | Path | None = None) -> Path:
    p = _registry_path(path)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(variants, indent=2), encoding="utf-8")
    return p


def _next_variant_id(variants: list[dict], app_id: int) -> str:
    """Next per-app variant id: v1, v2, ... (scoped to this application)."""
    nums = []
    for v in variants:
        if v.get("app_id") == app_id:
            vid = str(v.get("variant_id", ""))
            if vid.startswith("v") and vid[1:].isdigit():
                nums.append(int(vid[1:]))
    return f"v{max(nums, default=0) + 1}"


def _app_by_id(app_id: int) -> dict | None:
    for a in TR.list_apps():
        if a.get("id") == app_id:
            return a
    return None


def register_variant(app_id: int, file: str | Path, *, tone: str = "",
                     length: str = "", label: str = "",
                     path: str | Path | None = None) -> dict:
    """Register a tailored resume file against a tracked application.

    Creates {variant_id (v1, v2... per app), app_id, file, tone, length,
    label, created}. Raises VariantsError if the app id is unknown or the
    file does not exist.
    """
    app = _app_by_id(app_id)
    if app is None:
        raise VariantsError(
            f"No application #{app_id} in the tracker. "
            "Next: python -m candid track list"
        )
    fp = Path(file).expanduser()
    if not fp.is_file():
        raise VariantsError(
            f"File not found: {file}. "
            "Next: python -m candid tailor resume --jd jd.txt "
            f"--company \"{app['company']}\" --role \"{app['role']}\""
        )
    variants = _load(path)
    rec = {
        "variant_id": _next_variant_id(variants, app_id),
        "app_id": app_id,
        "file": str(fp),
        "tone": tone,
        "length": length,
        "label": label,
        "created": date.today().isoformat(),
    }
    variants.append(rec)
    _save(variants, path)
    return rec


def _find_variant(variants: list[dict], variant_id: str) -> dict:
    matches = [v for v in variants if v.get("variant_id") == variant_id]
    if not matches:
        raise VariantsError(
            f"No variant '{variant_id}' registered. "
            "Next: python -m candid variants list"
        )
    if len(matches) > 1:
        where = ", ".join(f"app #{v.get('app_id')}" for v in matches)
        raise VariantsError(
            f"Variant id '{variant_id}' is used by multiple applications "
            f"({where}); disambiguate with --app-id of the current one. "
            "Next: python -m candid variants list --app-id N"
        )
    return matches[0]


def link_variant(variant_id: str, app_id: int,
                 path: str | Path | None = None) -> dict:
    """Re-point a registered variant at a different application.

    Keeps the variant's id and file; only app_id changes.
    """
    if _app_by_id(app_id) is None:
        raise VariantsError(
            f"No application #{app_id} in the tracker. "
            "Next: python -m candid track list"
        )
    variants = _load(path)
    rec = _find_variant(variants, variant_id)
    rec["app_id"] = app_id
    _save(variants, path)
    return rec


def list_variants(app_id: int | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """List registered variants, optionally filtered by application id."""
    variants = _load(path)
    if app_id is not None:
        variants = [v for v in variants if v.get("app_id") == app_id]
    return sorted(variants, key=lambda v: (v.get("app_id", 0),
                                           v.get("variant_id", "")))


def _summarize(rows: list[dict]) -> dict:
    """{by_tone: {...}, by_length: {...}} response-rate aggregates."""
    def _bucket(key: str) -> dict:
        buckets: dict[str, dict] = {}
        for r in rows:
            name = r.get(key) or "unspecified"
            b = buckets.setdefault(name, {"variants": 0, "responses": 0})
            b["variants"] += 1
            b["responses"] += 1 if r["responded"] else 0
        for b in buckets.values():
            total = b["variants"]
            b["response_rate"] = round(b["responses"] / total, 3) if total else 0.0
        return buckets

    return {"by_tone": _bucket("tone"), "by_length": _bucket("length")}


def variant_stats(path: str | Path | None = None) -> dict:
    """Variant performance report.

    Returns {"variants": [per-variant rows], "summary": aggregates}.
    Each row: {variant_id, app_id, company, role, tone, length, label,
    status, responded, interview}. Joined defensively against the tracker:
    a variant whose application was deleted shows status "removed".
    """
    apps = {a.get("id"): a for a in TR.list_apps()}
    rows = []
    for v in list_variants(path=path):
        app = apps.get(v.get("app_id"))
        status = app.get("status") if app else "removed"
        rows.append({
            "variant_id": v.get("variant_id"),
            "app_id": v.get("app_id"),
            "company": app.get("company", "") if app else "",
            "role": app.get("role", "") if app else "",
            "tone": v.get("tone", ""),
            "length": v.get("length", ""),
            "label": v.get("label", ""),
            "status": status,
            "responded": status in C.RESPONSE_STATUSES,
            "interview": status == "selected_for_interview",
        })
    return {"variants": rows, "summary": _summarize(rows)}
