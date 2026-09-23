"""Career-capital ledger: log wins and impact as they happen.

A win is one accomplishment: what you did, when, the STAR narrative, the
competencies it demonstrates, quantified impacts, and supporting quotes.
The ledger feeds performance-review brag sheets (candid.brag), interview
STAR stories (candid.star), and resume bullets.

Storage is a plain JSON list at the wins path (git-ignored user data).
The data dir is resolved at call time from CANDID_DATA_DIR so tests can
isolate it with monkeypatch.
"""

from __future__ import annotations

import json
import os
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

# Seeded competency vocabulary: slug -> what it means. Wins are tagged with
# these slugs; users can add their own with register_competency().
COMPETENCIES: dict[str, str] = {
    "leadership": "Leading teams, setting direction, driving outcomes through others",
    "ownership": "End-to-end responsibility and initiative beyond the job description",
    "communication": "Writing, presenting, and explaining clearly",
    "system-design": "Architecture decisions, scaling, and tradeoffs",
    "coding": "Implementation quality and craftsmanship",
    "debugging": "Root-causing and fixing hard problems",
    "data-analysis": "Turning data into decisions",
    "experimentation": "A/B tests, causal inference, measurement",
    "ml-modeling": "Model building, training, and evaluation",
    "product-sense": "User empathy, prioritization, product judgment",
    "stakeholder-management": "Aligning cross-functional partners",
    "mentoring": "Growing other engineers",
    "project-management": "Planning, estimation, and delivery",
    "incident-response": "Handling outages calmly and effectively",
    "technical-writing": "Design docs, RFCs, documentation",
    "collaboration": "Working effectively with others",
    "strategic-thinking": "Long-term bets, connecting work to strategy",
    "customer-focus": "Customer obsession and external impact",
}


def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "candid_data"


def _wins_path() -> Path:
    return _data_dir() / "wins.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_date(value: str) -> str:
    try:
        date_cls.fromisoformat((value or "")[:10])
    except ValueError:
        raise ValueError(f"Bad date {value!r}: expected YYYY-MM-DD")
    return (value or "")[:10]


def normalize_competency(slug: str) -> str:
    """Return the canonical slug or raise ValueError listing valid ones."""
    slug = (slug or "").strip().lower().replace(" ", "-").replace("_", "-")
    known = set(COMPETENCIES) | set(_meta().get("competencies", {}))
    if slug not in known:
        raise ValueError(
            f"Unknown competency {slug!r}. Valid: {', '.join(sorted(known))}")
    return slug


def _meta() -> dict:
    """User-registered taxonomy additions, stored alongside the ledger."""
    raw = _read_raw()
    meta = raw.get("_meta") if isinstance(raw, dict) else None
    return meta if isinstance(meta, dict) else {}


def register_competency(slug: str, description: str) -> None:
    """Add a user competency to the taxonomy (persisted in the ledger)."""
    slug = (slug or "").strip().lower().replace(" ", "-").replace("_", "-")
    if not slug:
        raise ValueError("Competency slug must not be empty")
    if slug in COMPETENCIES:
        raise ValueError(f"{slug!r} is a built-in competency already")
    raw = _read_raw()
    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    custom = meta.get("competencies") if isinstance(
        meta.get("competencies"), dict) else {}
    custom[slug] = description or ""
    meta["competencies"] = custom
    raw["_meta"] = meta
    _write_raw(raw)


def _read_raw():
    path = _wins_path()
    if not path.exists():
        return {"_meta": {}, "wins": []}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"_meta": {}, "wins": []}
    if isinstance(raw, list):  # tolerate bare-list ledgers
        return {"_meta": {}, "wins": raw}
    if isinstance(raw, dict):
        raw.setdefault("_meta", {})
        raw.setdefault("wins", [])
        return raw
    return {"_meta": {}, "wins": []}


def _write_raw(raw) -> Path:
    path = _wins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2))
    return path


def _next_id(wins: list[dict]) -> str:
    taken = {w.get("id") for w in wins}
    n = len(wins) + 1
    while f"w-{n:04d}" in taken:
        n += 1
    return f"w-{n:04d}"


def _blank_win() -> dict:
    return {
        "id": "", "title": "", "date": "", "role": "", "description": "",
        "star": {"situation": "", "task": "", "action": "", "result": ""},
        "competencies": [], "impacts": [], "quotes": [], "tags": [],
        "created_at": "", "updated_at": "",
    }


def new_win(**kwargs) -> dict:
    """Build an unsaved win dict with defaults (id + today's date)."""
    win = _blank_win()
    win.update({k: v for k, v in kwargs.items() if k in win})
    if "star" in kwargs and isinstance(kwargs["star"], dict):
        win["star"] = {**win["star"], **kwargs["star"]}
    if not win["id"]:
        win["id"] = _next_id(load_wins())
    if not win["date"]:
        win["date"] = date_cls.today().isoformat()
    else:
        win["date"] = _validate_date(win["date"])
    if win["competencies"]:
        win["competencies"] = [normalize_competency(c)
                               for c in win["competencies"]]
    return win


def load_wins() -> list[dict]:
    """Load all wins from the ledger. Missing/corrupt file -> []."""
    raw = _read_raw()
    wins = raw.get("wins", [])
    return [w for w in wins if isinstance(w, dict)]


def save_wins(wins: list[dict]) -> None:
    """Persist wins (plain dicts). Returns None."""
    raw = _read_raw()
    raw["wins"] = [dict(w) for w in wins]
    _write_raw(raw)


def add_win(*, title: str, win_date: str | None = None, description: str = "",
            role: str = "", competencies=(), impacts=(), quotes=(),
            tags=(), star: dict | None = None, date: str | None = None) -> dict:
    """Create, persist, and return a win."""
    if not (title or "").strip():
        raise ValueError("title is required")
    if date is not None and win_date is None:
        win_date = date  # tolerate the old kwarg name
    wins = load_wins()
    win = _blank_win()
    win["id"] = _next_id(wins)
    win["title"] = title.strip()
    win["date"] = _validate_date(win_date) if win_date else date_cls.today().isoformat()
    win["description"] = description or ""
    win["role"] = role or ""
    win["competencies"] = [normalize_competency(c) for c in (competencies or ())]
    win["impacts"] = [dict(i) for i in (impacts or ())]
    win["quotes"] = [dict(q) for q in (quotes or ())]
    win["tags"] = [str(t) for t in (tags or ())]
    if star:
        win["star"] = {**win["star"], **{k: star.get(k, "") for k in win["star"]}}
    win["created_at"] = _now_iso()
    win["updated_at"] = win["created_at"]
    wins.append(win)
    save_wins(wins)
    return win


def get_win(win_id: str) -> dict | None:
    """Return the win with this id, or None."""
    for w in load_wins():
        if w.get("id") == win_id:
            return w
    return None


def update_win(win_id: str, **fields) -> dict:
    """Update fields on a win. Raises KeyError if missing."""
    wins = load_wins()
    for w in wins:
        if w.get("id") == win_id:
            for key, value in fields.items():
                if key == "id":
                    continue
                if key == "competencies" and value is not None:
                    value = [normalize_competency(c) for c in value]
                if key == "date" and value:
                    value = _validate_date(value)
                if key == "star" and isinstance(value, dict):
                    merged = dict(w.get("star") or {})
                    merged.update(value)
                    value = merged
                w[key] = value
            w["updated_at"] = _now_iso()
            save_wins(wins)
            return w
    raise KeyError(f"No win with id {win_id!r}")


def delete_win(win_id: str) -> bool:
    """Delete a win. Returns True if one was removed."""
    wins = load_wins()
    kept = [w for w in wins if w.get("id") != win_id]
    if len(kept) == len(wins):
        return False
    save_wins(kept)
    return True


def list_wins(wins: list[dict] | None = None, *, competency: str | None = None,
              tag: str | None = None, since: str | None = None,
              until: str | None = None, query: str | None = None,
              role: str | None = None) -> list[dict]:
    """Wins newest-first, with optional filters.

    competency/tag/role filter on exact (case-insensitive) match;
    since/until bound the ISO date; query is a case-insensitive substring
    over title + description.
    """
    all_wins = list(load_wins() if wins is None else wins)
    if competency:
        competency = normalize_competency(competency)
        all_wins = [w for w in all_wins if competency in (w.get("competencies") or ())]
    if tag:
        tl = tag.lower()
        all_wins = [w for w in all_wins
                    if any(t.lower() == tl for t in (w.get("tags") or ()))]
    if since:
        all_wins = [w for w in all_wins if (w.get("date") or "") >= since]
    if until:
        all_wins = [w for w in all_wins if (w.get("date") or "") <= until]
    if role:
        rl = role.lower()
        all_wins = [w for w in all_wins if rl in (w.get("role") or "").lower()]
    if query:
        ql = query.lower()
        all_wins = [w for w in all_wins
                    if ql in (w.get("title") or "").lower()
                    or ql in (w.get("description") or "").lower()]
    all_wins.sort(key=lambda w: (w.get("date") or "", w.get("title") or ""),
                  reverse=True)
    return all_wins
