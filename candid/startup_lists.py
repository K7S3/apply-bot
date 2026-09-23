"""Curated startup company registry: import, list, add, remove, filter.

A startup list is a registry of companies (usually early-stage) you want to
watch for job openings. Import a curated CSV, keep it tidy, and filter by
funding stage or remote policy when browsing.

Storage: ``candid_data/startups.json`` (git-ignored), holding both the
company records and your preferred funding stages::

    {"startups": [...], "preferred_stages": ["seed", "series-a"]}

CSV columns: name, stage, funding_total_usd, employees, url, remote_policy,
notes. Stage vocabulary: pre-seed, seed, series-a, series-b, series-c-plus,
public.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from candid import config as C


class StartupListError(Exception):
    """Raised for invalid startup-list operations (bad stage, dupes, missing file)."""


# --- constants ----------------------------------------------------------------
STAGES = (
    "pre-seed",
    "seed",
    "series-a",
    "series-b",
    "series-c-plus",
    "public",
)

# Common shorthands users type; normalized to the canonical vocabulary.
_STAGE_ALIASES = {
    "preseed": "pre-seed",
    "pre seed": "pre-seed",
    "series c+": "series-c-plus",
    "series-c+": "series-c-plus",
    "series c-plus": "series-c-plus",
    "series a": "series-a",
    "series b": "series-b",
}

# funding suffix multipliers: "1.5M" -> 1500000
_FUNDING_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

_REMOTE_HINT = re.compile(r"\b(remote|distributed|anywhere)\b", re.IGNORECASE)


def _startups_path() -> Path:
    return C.DATA_DIR / "startups.json"


# --- storage ------------------------------------------------------------------
def _load() -> dict:
    """Load the registry doc; empty doc if the file doesn't exist yet."""
    p = _startups_path()
    if not p.exists():
        return {"startups": [], "preferred_stages": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StartupListError(f"Startup list file {p} is not valid JSON: {exc}") from exc
    if isinstance(data, list):
        # Legacy shape: bare list of records, before preferred_stages existed.
        data = {"startups": data, "preferred_stages": []}
    if not isinstance(data, dict) or not isinstance(data.get("startups"), list):
        raise StartupListError(f"Startup list file {p} should contain an object with a 'startups' list.")
    data.setdefault("preferred_stages", [])
    return data


def _save(doc: dict) -> Path:
    p = _startups_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def _find(doc: dict, name: str) -> dict | None:
    needle = name.strip().lower()
    for s in doc["startups"]:
        if s.get("name", "").strip().lower() == needle:
            return s
    return None


# --- validation ----------------------------------------------------------------
def normalize_stage(stage: str) -> str:
    """Normalize a stage to the canonical vocabulary, or raise StartupListError."""
    if stage is None:
        raise StartupListError("Stage is required. Choose from: " + ", ".join(STAGES))
    key = stage.strip().lower().replace("_", "-")
    key = _STAGE_ALIASES.get(key, key)
    if key not in STAGES:
        raise StartupListError(
            f"Unknown stage '{stage.strip()}'. Choose from: {', '.join(STAGES)}"
        )
    return key


def parse_funding(value: str) -> int | None:
    """Parse a funding amount into whole USD. ''/None -> None.

    Accepts plain numbers ("250000", "1.5"), comma groupings, a leading "$",
    and k/m/b suffixes ("$1.5M", "500k").
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        text = str(value).strip().lower().replace("$", "").replace(",", "").replace(" ", "")
        if not text:
            return None
        mult = 1
        if text[-1] in _FUNDING_SUFFIXES:
            mult = _FUNDING_SUFFIXES[text[-1]]
            text = text[:-1]
        try:
            amount = float(text)
        except ValueError:
            raise StartupListError(f"Could not parse funding amount '{value}'.")
        amount *= mult
    if amount < 0:
        raise StartupListError(f"Funding amount '{value}' must not be negative.")
    return int(round(amount))


def parse_employees(value: str) -> int | None:
    """Parse a headcount into an int. ''/None -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        count = int(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            count = int(float(text))
        except ValueError:
            raise StartupListError(f"Could not parse employee count '{value}'.")
    if count < 0:
        raise StartupListError(f"Employee count '{value}' must not be negative.")
    return count


def normalize_row(raw: dict[str, str | None]) -> dict:
    """Validate a raw mapping (CSV row or CLI input) into a startup record."""
    name = (raw.get("name") or "").strip()
    if not name:
        raise StartupListError("Row is missing a company name.")
    return {
        "name": name,
        "stage": normalize_stage(raw.get("stage") or "") if (raw.get("stage") or "").strip() else "",
        "funding_total_usd": parse_funding(raw.get("funding_total_usd")),
        "employees": parse_employees(raw.get("employees")),
        "url": (raw.get("url") or "").strip(),
        "remote_policy": (raw.get("remote_policy") or "").strip().lower(),
        "notes": (raw.get("notes") or "").strip(),
    }


# --- import ---------------------------------------------------------------------
def import_csv(path: str | Path) -> dict:
    """Import startups from a CSV file. Returns a summary dict.

    ``summary = {"imported": N, "updated": M, "skipped": [{"line": 4, "reason": "..."}]}``

    Expected row problems (missing name, bad stage, bad numbers) are
    collected into ``skipped`` with reasons, never raised. A file that is
    missing or not parseable as CSV raises StartupListError.
    """
    p = Path(path)
    if not p.exists():
        raise StartupListError(f"CSV file not found: {p}")
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise StartupListError(f"CSV file {p} has no header row.")
            names = {n.strip().lower() for n in reader.fieldnames if n}
            if "name" not in names:
                raise StartupListError(f"CSV file {p} is missing the required 'name' column.")
            rows = list(reader)
    except csv.Error as exc:
        raise StartupListError(f"Could not parse CSV file {p}: {exc}") from exc

    doc = _load()
    imported, updated, skipped = 0, 0, []
    for i, row in enumerate(rows, start=2):  # header is line 1
        lowered = {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
                   for k, v in row.items() if k}
        # Skip entirely blank rows without complaint.
        if not any(v for v in lowered.values()):
            continue
        try:
            rec = normalize_row(lowered)
        except StartupListError as exc:
            skipped.append({"line": i, "reason": str(exc)})
            continue
        existing = _find(doc, rec["name"])
        if existing is None:
            rec["date_added"] = date.today().isoformat()
            doc["startups"].append(rec)
            imported += 1
        else:
            # Update in place: fill in fields the row provides, keep the rest.
            for key in ("stage", "funding_total_usd", "employees", "url", "remote_policy", "notes"):
                if rec[key] not in (None, ""):
                    existing[key] = rec[key]
            existing["date_updated"] = date.today().isoformat()
            updated += 1
    _save(doc)
    return {"imported": imported, "updated": updated, "skipped": skipped}


def render_import_summary(summary: dict) -> str:
    lines = [
        f"Startup import: {summary['imported']} added, {summary['updated']} updated, "
        f"{len(summary['skipped'])} skipped."
    ]
    for s in summary["skipped"]:
        lines.append(f"  line {s['line']}: {s['reason']}")
    return "\n".join(lines)


# --- CRUD ------------------------------------------------------------------------
def add(*, name: str, stage: str = "", funding_usd: str | int | None = None,
        employees: str | int | None = None, url: str = "", remote_policy: str = "",
        notes: str = "") -> dict:
    """Add a startup. Returns the new record, or the existing one with
    ``"duplicate": True`` (no write) when the name is already registered."""
    rec = normalize_row({
        "name": name,
        "stage": stage,
        "funding_total_usd": funding_usd,
        "employees": employees,
        "url": url,
        "remote_policy": remote_policy,
        "notes": notes,
    })
    doc = _load()
    existing = _find(doc, rec["name"])
    if existing is not None:
        return {**existing, "duplicate": True}
    rec["date_added"] = date.today().isoformat()
    doc["startups"].append(rec)
    _save(doc)
    return rec


def remove(name: str) -> dict:
    """Remove a startup by name (case-insensitive). Returns the removed record."""
    if not name or not name.strip():
        raise StartupListError("--name is required to remove a startup.")
    doc = _load()
    rec = _find(doc, name)
    if rec is None:
        raise StartupListError(f"No startup named '{name.strip()}' in the registry.")
    doc["startups"].remove(rec)
    _save(doc)
    return rec


def set_preferred_stages(stages: list[str] | str) -> list[str]:
    """Store preferred funding stages. Validates every entry against the
    stage vocabulary. Returns the stored list."""
    if isinstance(stages, str):
        stages = re.split(r"[,\s]+", stages)
    normalized = []
    for s in stages:
        s = (s or "").strip()
        if not s:
            continue
        norm = normalize_stage(s)
        if norm not in normalized:
            normalized.append(norm)
    doc = _load()
    doc["preferred_stages"] = normalized
    _save(doc)
    return normalized


def preferred_stages() -> list[str]:
    """Your saved preferred stages (may be empty)."""
    return list(_load().get("preferred_stages", []))


def is_remote(rec: dict) -> bool:
    """True when the startup's remote policy mentions remote work."""
    return bool(_REMOTE_HINT.search(rec.get("remote_policy") or ""))


def list_startups(*, stage: str = "", remote_only: bool = False,
                  use_preferred: bool = False) -> list[dict]:
    """List startups, optionally filtered by stage and/or remote policy.

    With use_preferred=True, startups matching your saved preferred stages
    are returned (only when --stage is not given).
    """
    doc = _load()
    records = doc["startups"]
    if stage:
        want = normalize_stage(stage)
        records = [r for r in records if r.get("stage") == want]
    elif use_preferred and doc.get("preferred_stages"):
        wanted = set(doc["preferred_stages"])
        records = [r for r in records if r.get("stage") in wanted]
    if remote_only:
        records = [r for r in records if is_remote(r)]
    return sorted(records, key=lambda r: r.get("name", "").lower())


# --- rendering ----------------------------------------------------------------------
def _fmt_money(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value}"


def render_table(records: list[dict]) -> str:
    """Plain-text table for the `startups list` command."""
    if not records:
        return "No startups in the registry yet. Import one with `startups import --csv FILE`."
    header = f"{'Name':28} {'Stage':13} {'Funding':9} {'Headcount':9} {'Remote'}"
    lines = [header, "-" * len(header)]
    for r in records:
        name = r.get("name", "")[:28]
        remote = r.get("remote_policy") or "-"
        emp = str(r.get("employees")) if r.get("employees") is not None else "-"
        lines.append(f"{name:28} {r.get('stage') or '-':13} "
                     f"{_fmt_money(r.get('funding_total_usd')):9} {emp:9} {remote}")
    return "\n".join(lines)


# --- CLI entry point (wired into candid/__main__.py by the coordinator) --------------
def cmd_startups(a) -> None:
    """Handler for the `startups` command group (set as argparse func)."""
    if a.what == "import":
        summary = import_csv(a.csv)
        print(render_import_summary(summary))
    elif a.what == "list":
        records = list_startups(
            stage=a.stage or "",
            remote_only=bool(a.remote_only),
            use_preferred=bool(getattr(a, "preferred", False)),
        )
        if a.json:
            print(json.dumps(records, indent=2, default=str))
        else:
            print(render_table(records))
    elif a.what == "add":
        rec = add(
            name=a.name, stage=a.stage or "", funding_usd=a.funding_usd,
            employees=a.employees, url=a.url or "", remote_policy=a.remote_policy or "",
            notes=a.notes or "",
        )
        if rec.get("duplicate"):
            print(f"'{rec['name']}' is already in the registry (no changes made).")
        else:
            print(f"Added '{rec['name']}' to the startup registry.")
    elif a.what == "remove":
        rec = remove(a.name)
        print(f"Removed '{rec['name']}' from the startup registry.")
    elif a.what == "set-stages":
        if a.stages:
            stored = set_preferred_stages(a.stages)
            if stored:
                print("Preferred stages: " + ", ".join(stored))
            else:
                print("Preferred stages cleared.")
        else:
            current = preferred_stages()
            if current:
                print("Preferred stages: " + ", ".join(current))
            else:
                print("No preferred stages set. "
                      "Use `startups set-stages --stages seed,series-a`.")
    else:  # pragma: no cover - argparse requires a subcommand
        raise StartupListError(f"Unknown startups subcommand: {a.what}")
