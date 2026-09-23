"""Impact metrics on ledger wins.

Builds on candid.wins: each win may carry a list of impact entries,
{"metric": str, "before": num|None, "after": num|None, "unit": str,
"category": str}. This module adds typed add/remove helpers plus
rollup, timeline, and ranking views used by the dashboard.

Compatibility note: the wins ledger in this branch exposes Win objects
as dataclass instances (see candid/wins.py), while the original batch-60
contract described plain dicts with a get_win() accessor. The helpers
below work with both shapes: wins may be dataclass instances or dicts,
and get_win is used when the wins module provides it.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Mapping, Optional

from candid import wins as _wins

IMPACT_CATEGORIES = {"revenue", "cost", "performance", "quality", "scale", "time"}


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _field(win: Any, name: str, default: Any = "") -> Any:
    """Read a win field whether the win is a dataclass or a dict."""
    if is_dataclass(win) and not isinstance(win, type):
        return getattr(win, name, default)
    if isinstance(win, Mapping):
        return win.get(name, default)
    return getattr(win, name, default)


def _impacts_of(win: Any) -> list:
    impacts = _field(win, "impacts", None)
    if impacts is None:
        impacts = []
        if is_dataclass(win) and not isinstance(win, type):
            win.impacts = impacts
        elif isinstance(win, dict):
            win["impacts"] = impacts
    if not isinstance(impacts, list):
        raise ValueError(
            f"win {_field(win, 'id')!r} has a non-list impacts field"
        )
    return impacts


def _as_dict(win: Any) -> dict:
    if is_dataclass(win) and not isinstance(win, type):
        return asdict(win)
    if isinstance(win, Mapping):
        return dict(win)
    return {
        k: getattr(win, k)
        for k in ("id", "title", "date", "impacts")
        if hasattr(win, k)
    }


def _require_win(win_id: str) -> Any:
    """Fetch a win by id; ValueError when it does not exist."""
    get_win = getattr(_wins, "get_win", None)
    if get_win is not None:
        try:
            return get_win(win_id)
        except Exception as exc:
            raise ValueError(f"unknown win: {win_id!r}") from exc
    for win in _wins.list_wins():
        if _field(win, "id") == win_id:
            return win
    raise ValueError(f"unknown win: {win_id!r}")


def _win_date_key(win: Any) -> str:
    return str(_field(win, "date", "") or "")


def add_impact(
    win_id: str,
    *,
    metric: str,
    before: Optional[float] = None,
    after: Optional[float] = None,
    unit: str = "",
    category: str = "",
) -> dict:
    """Append an impact metric to a win and persist it.

    Returns the updated win as a dict. Raises ValueError on unknown win,
    empty metric, non-numeric before/after, or a category outside
    IMPACT_CATEGORIES.
    """
    if not metric or not str(metric).strip():
        raise ValueError("metric must be a non-empty string")
    if before is not None and not _is_num(before):
        raise ValueError("before must be numeric or None")
    if after is not None and not _is_num(after):
        raise ValueError("after must be numeric or None")
    if category and category not in IMPACT_CATEGORIES:
        raise ValueError(
            f"unknown category: {category!r} "
            f"(choose from {sorted(IMPACT_CATEGORIES)})"
        )
    wins = _wins.list_wins()
    for win in wins:
        if _field(win, "id") == win_id:
            _impacts_of(win).append(
                {
                    "metric": str(metric),
                    "before": before,
                    "after": after,
                    "unit": str(unit),
                    "category": str(category),
                }
            )
            updated = win
            break
    else:
        raise ValueError(f"unknown win: {win_id!r}")
    _wins.save_wins(wins)
    return _as_dict(updated)


def remove_impact(win_id: str, index: int) -> dict:
    """Remove the impact at `index` from a win and persist it.

    Returns the updated win as a dict. Raises ValueError on unknown win,
    non-integer index, or index out of range.
    """
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError("index must be an integer")
    wins = _wins.list_wins()
    for win in wins:
        if _field(win, "id") == win_id:
            impacts = _impacts_of(win)
            if index < 0 or index >= len(impacts):
                raise ValueError(
                    f"impact index {index} out of range for win {win_id!r}"
                )
            impacts.pop(index)
            updated = win
            break
    else:
        raise ValueError(f"unknown win: {win_id!r}")
    _wins.save_wins(wins)
    return _as_dict(updated)


def impact_rollup(wins: Optional[Iterable[Any]] = None) -> dict:
    """Aggregate impact coverage across wins.

    Returns {"total_wins": n, "wins_with_impact": n,
    "by_category": {cat: {"count": n, "metrics": [metric names]}}}.
    """
    items = list(_wins.list_wins() if wins is None else wins)
    by_category: dict[str, dict] = {
        cat: {"count": 0, "metrics": set()} for cat in IMPACT_CATEGORIES
    }
    wins_with_impact = 0
    for win in items:
        impacts = _field(win, "impacts", None) or []
        if impacts:
            wins_with_impact += 1
        for impact in impacts:
            cat = (impact.get("category") or "") if isinstance(impact, Mapping) else ""
            if cat not in IMPACT_CATEGORIES:
                continue
            by_category[cat]["count"] += 1
            by_category[cat]["metrics"].add(str(impact.get("metric", "")))
    for cat in by_category:
        by_category[cat]["metrics"] = sorted(by_category[cat]["metrics"])
    return {
        "total_wins": len(items),
        "wins_with_impact": wins_with_impact,
        "by_category": by_category,
    }


def delta_pct(before: Any, after: Any) -> Optional[float]:
    """Percent change from before to after, or None when not computable."""
    if _is_num(before) and _is_num(after) and before != 0:
        return (after - before) / before * 100
    return None


def _impact_field(impact: Any, name: str, default: Any = "") -> Any:
    if isinstance(impact, Mapping):
        return impact.get(name, default)
    return getattr(impact, name, default)


def impact_timeline(
    wins: Optional[Iterable[Any]] = None,
    category: Optional[str] = None,
) -> list[dict]:
    """Flat chronological view of every impact entry.

    Sorted by win date ascending. delta_pct is the percent change from
    before to after, or None when either side is missing/non-numeric
    or before is zero.
    """
    if category and category not in IMPACT_CATEGORIES:
        raise ValueError(f"unknown category: {category!r}")
    items = list(_wins.list_wins() if wins is None else wins)
    rows: list[dict] = []
    for win in items:
        for impact in _field(win, "impacts", None) or []:
            if category and _impact_field(impact, "category") != category:
                continue
            rows.append(
                {
                    "date": _win_date_key(win),
                    "win_id": _field(win, "id"),
                    "title": _field(win, "title"),
                    "metric": _impact_field(impact, "metric"),
                    "before": _impact_field(impact, "before", None),
                    "after": _impact_field(impact, "after", None),
                    "unit": _impact_field(impact, "unit"),
                    "category": _impact_field(impact, "category"),
                    "delta_pct": delta_pct(
                        _impact_field(impact, "before", None),
                        _impact_field(impact, "after", None),
                    ),
                }
            )
    rows.sort(key=lambda r: (r["date"], r["win_id"] or ""))
    return rows


def _quantified_count(win: Any) -> int:
    return sum(
        1
        for impact in _field(win, "impacts", None) or []
        if _is_num(_impact_field(impact, "before", None))
        and _is_num(_impact_field(impact, "after", None))
    )


def biggest_wins(
    wins: Optional[Iterable[Any]] = None, limit: int = 5
) -> list[dict]:
    """Wins ranked by number of quantified impacts, then most recent.

    A quantified impact has numeric before and after values. Ties are
    broken by win date descending. Returns at most `limit` wins, each
    as a dict.
    """
    items = list(_wins.list_wins() if wins is None else wins)
    ranked = sorted(
        items,
        key=lambda w: (_quantified_count(w), _win_date_key(w)),
        reverse=True,
    )
    return [_as_dict(w) for w in ranked[: max(limit, 0)]]
