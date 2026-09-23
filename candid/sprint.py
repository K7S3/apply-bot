"""Weekly application sprint planning: sprints, targets, batching, timeboxes.

A sprint is one week (Monday-Sunday) of structured job-search work: a set
of target applications, auto-batched for efficient tailoring, and an
evening timebox plan that fits around a day job.

Stored as a JSON list at <DATA_DIR>/sprints.json (git-ignored).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from candid import config as C


class SprintError(Exception):
    """Raised for invalid sprint operations."""


SPRINTS_FILE = "sprints.json"
PRIORITIES = ("high", "medium", "low")
TARGET_STATUSES = ("todo", "done")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIMEBLOCK_KINDS = ("research", "tailor", "apply", "followup", "prep")

#: Share of the hours budget each timebox kind gets, in order.
KIND_SHARES = (("research", 0.25), ("tailor", 0.40), ("apply", 0.25), ("followup", 0.10))

#: Role-family keyword rules for batching targets (first match wins).
ROLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "data": (
        "data", "ml ", "ml/", " machine learning", "analytics", "scientist",
        "artificial intelligence", "nlp", "bi ", "business intelligence",
        "data engineer", "machine learning engineer",
    ),
    "engineering": (
        "engineer", "developer", "software", "backend", "frontend",
        "full-stack", "fullstack", "mobile", "ios", "android", "devops",
        "sre", "platform", "infrastructure", "systems", "embedded",
    ),
    "product": ("product", "program manager", "growth", "chief of staff"),
    "design": ("design", "ux", "ui ", "user experience", "user interface"),
    "ops": (
        "operations", "support", "recruiter", "talent", "hr ", "sales",
        "marketing", "customer success", "finance", "accounting",
    ),
}
FAMILY_ORDER = ("engineering", "data", "product", "design", "ops", "other")


def _data_dir() -> Path:
    """Data dir resolved at call time so CANDID_DATA_DIR overrides work."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _sprints_path() -> Path:
    return _data_dir() / SPRINTS_FILE


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _sprints_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SprintError(f"Sprints file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SprintError(f"Sprints file {p} should contain a JSON list.")
    return data


def _save(sprints: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else _sprints_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sprints, indent=2), encoding="utf-8")
    return p


def _next_id(sprints: list[dict]) -> int:
    return max((s.get("id", 0) for s in sprints), default=0) + 1


def snap_to_monday(week_start: str | date) -> date:
    """Snap any date (or YYYY-MM-DD string) back to its week's Monday."""
    if isinstance(week_start, str):
        try:
            d = date.fromisoformat(week_start.strip())
        except ValueError as exc:
            raise SprintError(f"week_start must be YYYY-MM-DD, got {week_start!r}.") from exc
    elif isinstance(week_start, date):
        d = week_start
    else:
        raise SprintError(f"week_start must be a date or YYYY-MM-DD string, got {type(week_start).__name__}.")
    return d - timedelta(days=d.weekday())


def _sprint_or_raise(sprints: list[dict], sprint_id: int) -> dict:
    sprint = next((s for s in sprints if s.get("id") == sprint_id), None)
    if sprint is None:
        raise SprintError(f"No sprint with id {sprint_id}.")
    return sprint


def create_sprint(week_start: str | date, title: str = "", target_apps: int = 5,
                  hours_budget: float = 6.0) -> dict:
    """Create a sprint for the week containing ``week_start`` (snapped to Monday).

    Rejects a second *active* sprint for the same week. Returns the new sprint.
    """
    monday = snap_to_monday(week_start)
    if target_apps < 0:
        raise SprintError("target_apps must be >= 0.")
    if hours_budget <= 0:
        raise SprintError("hours_budget must be > 0.")
    sprints = _load()
    for s in sprints:
        if s.get("week_start") == monday.isoformat() and s.get("status") == "active":
            raise SprintError(f"An active sprint already exists for week {monday} (id {s['id']}).")
    sprint = {
        "id": _next_id(sprints),
        "week_start": monday.isoformat(),
        "title": title.strip() or f"Week of {monday}",
        "target_apps": target_apps,
        "hours_budget": hours_budget,
        "targets": [],
        "time_blocks": [],
        "notes": [],
        "status": "active",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "review": {},
        "template": "",
    }
    sprints.append(sprint)
    _save(sprints)
    return sprint


def list_sprints() -> list[dict]:
    """All sprints, newest week first."""
    return sorted(_load(), key=lambda s: (s.get("week_start", ""), s.get("id", 0)), reverse=True)


def get_sprint(ref: int | str) -> dict:
    """Fetch a sprint by id, "current" (active sprint whose week contains
    today), or "latest" (highest id)."""
    sprints = _load()
    if isinstance(ref, str) and ref in ("current", "latest"):
        if ref == "latest":
            if not sprints:
                raise SprintError("No sprints yet.")
            return max(sprints, key=lambda s: s.get("id", 0))
        today = date.today()
        for s in sprints:
            if s.get("status") != "active":
                continue
            start = date.fromisoformat(s["week_start"])
            if start <= today < start + timedelta(days=7):
                return s
        raise SprintError("No active sprint for the current week.")
    try:
        sprint_id = int(ref)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise SprintError(f"Unknown sprint reference {ref!r}. Use an id, 'current', or 'latest'.") from None
    return _sprint_or_raise(sprints, sprint_id)


def add_target(sprint_id: int, company: str, role: str, jd_link: str = "",
               priority: str = "medium") -> dict:
    """Add an application target to a sprint.

    Same company+role (case-insensitive) returns the EXISTING target with
    ``"duplicate": True`` and no write, mirroring tracker.add.
    """
    company = (company or "").strip()
    role = (role or "").strip()
    if not company or not role:
        raise SprintError("Both company and role are required to add a target.")
    if priority not in PRIORITIES:
        raise SprintError(f"Unknown priority {priority!r}. Choose from: {', '.join(PRIORITIES)}")
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    for t in sprint["targets"]:
        if t["company"].lower() == company.lower() and t["role"].lower() == role.lower():
            return {**t, "duplicate": True}
    target = {
        "company": company,
        "role": role,
        "jd_link": (jd_link or "").strip(),
        "priority": priority,
        "status": "todo",
        "batch": "",
        "tracker_id": None,
        "done_at": None,
    }
    sprint["targets"].append(target)
    _save(sprints)
    return target


def remove_target(sprint_id: int, company: str, role: str) -> None:
    """Remove a target (matched case-insensitively) from a sprint."""
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    kept = [t for t in sprint["targets"]
            if not (t["company"].lower() == company.lower() and t["role"].lower() == role.lower())]
    if len(kept) == len(sprint["targets"]):
        raise SprintError(f"No target '{company} / {role}' in sprint {sprint_id}.")
    sprint["targets"] = kept
    _save(sprints)


def role_family(role: str) -> str:
    """Map a role title to a family: engineering/data/product/design/ops/other."""
    text = f" {(role or '').lower()} "
    for family in FAMILY_ORDER:
        for kw in ROLE_FAMILIES.get(family, ()):
            if kw in text:
                return family
    return "other"


def batch_targets(sprint_id: int) -> dict[str, list[dict]]:
    """Group a sprint's targets into batches and store batch ids on the targets.

    First by company (same company = same batch), then remaining single
    targets by role family. Assigns ``batch-1``, ``batch-2``, ... in a
    deterministic order. Idempotent: re-running yields the same assignment.

    Returns {batch_id: [target, ...]}.
    """
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    targets = sprint["targets"]

    by_company: dict[str, list[dict]] = {}
    for t in targets:
        by_company.setdefault(t["company"].lower(), []).append(t)

    # Company batches first: companies with 2+ targets get their own batch,
    # ordered by company name for stable numbering.
    company_groups = sorted(
        (g for g in by_company.values() if len(g) > 1),
        key=lambda g: g[0]["company"].lower(),
    )
    # Everyone else: group by role family, ordered by canonical family order.
    singles = [t for g in by_company.values() for t in g if len(g) == 1]
    family_groups: dict[str, list[dict]] = {}
    for t in singles:
        family_groups.setdefault(role_family(t["role"]), []).append(t)
    family_batches = [
        sorted(family_groups[f], key=lambda t: (t["company"].lower(), t["role"].lower()))
        for f in FAMILY_ORDER if f in family_groups
    ]

    grouping: dict[str, list[dict]] = {}
    for i, group in enumerate([*company_groups, *family_batches], start=1):
        batch_id = f"batch-{i}"
        for t in group:
            t["batch"] = batch_id
        grouping[batch_id] = group
    _save(sprints)
    return grouping


def _block_counts(total: int) -> dict[str, int]:
    """Split ``total`` blocks across kinds by KIND_SHARES, at least 1 apply block."""
    raw = {kind: share * total for kind, share in KIND_SHARES}
    counts = {kind: round(v) for kind, v in raw.items()}
    remainders = {kind: raw[kind] - counts[kind] for kind in counts}
    # Fix rounding drift by nudging kinds with the largest/smallest remainders.
    while sum(counts.values()) < total:
        kind = max(counts, key=lambda k: (remainders[k], dict(KIND_SHARES)[k]))
        counts[kind] += 1
        remainders[kind] -= 1
    while sum(counts.values()) > total:
        kind = min(counts, key=lambda k: (remainders[k], -dict(KIND_SHARES)[k]))
        if kind == "apply" and counts[kind] <= 1:
            kind = max((k for k in counts if k != "apply"), key=lambda k: counts[k])
        counts[kind] -= 1
        remainders[kind] += 1
    # Guarantee at least one apply block.
    if counts["apply"] < 1:
        donor = max((k for k in counts if k != "apply"), key=lambda k: counts[k])
        if counts[donor] > 0:
            counts[donor] -= 1
            counts["apply"] += 1
    return counts


def plan_timeboxes(sprint_id: int, block_minutes: int = 90) -> list[dict]:
    """Distribute a sprint's hours_budget into evening time blocks, Mon-Fri.

    Kinds split research 25% / tailor 40% / apply 25% / followup 10%,
    rounded to whole blocks with at least 1 apply block. Blocks start at
    18:00 each weekday (evenings). Stored on the sprint; returned as well.
    """
    if block_minutes <= 0:
        raise SprintError("block_minutes must be > 0.")
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    total = round(sprint["hours_budget"] * 60 / block_minutes)
    if total < 1:
        raise SprintError(
            f"hours_budget {sprint['hours_budget']}h is too small for {block_minutes}-min blocks.")
    counts = _block_counts(total)
    labels = {"research": "Research", "tailor": "Tailor resume", "apply": "Apply", "followup": "Follow up"}
    ordered_kinds: list[str] = []
    for kind, _ in KIND_SHARES:
        ordered_kinds.extend([kind] * counts[kind])

    blocks: list[dict] = []
    for i, kind in enumerate(ordered_kinds):
        weekday = WEEKDAYS[i % 5]
        slot = i // 5
        start_min = 18 * 60 + slot * block_minutes
        end_min = start_min + block_minutes
        blocks.append({
            "day": weekday,
            "start": f"{start_min // 60:02d}:{start_min % 60:02d}",
            "end": f"{end_min // 60:02d}:{end_min % 60:02d}",
            "kind": kind,
            "label": labels[kind],
        })
    sprint["time_blocks"] = blocks
    _save(sprints)
    return blocks


def close_sprint(sprint_id: int) -> dict:
    """Mark a sprint closed. Idempotent."""
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    sprint["status"] = "closed"
    _save(sprints)
    return sprint


def reopen_sprint(sprint_id: int) -> dict:
    """Reopen a closed sprint. Idempotent."""
    sprints = _load()
    sprint = _sprint_or_raise(sprints, sprint_id)
    sprint["status"] = "active"
    _save(sprints)
    return sprint
