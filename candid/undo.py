"""Undo tracker changes recorded in the audit log.

undo(entry_id) reverses the tracker operation described by an audit entry:

- action "create"        -> the added record is removed
- action "delete"        -> the removed record is re-inserted
- action "update"/"undo" -> the record is restored to the entry's "before" snapshot

Undo itself records a NEW audit entry with action="undo" referencing the
original entry, so undo-of-undo works naturally. Only tracker entities are
undoable; everything else raises UndoError.

CLI: ``python -m candid undo <entry-id>`` (wired by the CLI worker;
this module exposes the ``undo()`` function).
"""

from __future__ import annotations

from copy import deepcopy


class UndoError(Exception):
    """Raised when an audit entry cannot be undone."""


def _snapshot(rec: dict | None) -> dict | None:
    return deepcopy(rec) if rec is not None else None


def undo(entry_id) -> dict:
    """Reverse the tracker change recorded in audit entry ``entry_id``.

    Returns the new audit entry (action="undo") describing the reversal.
    Raises UndoError for unknown ids, non-tracker entities, or entries
    with no usable snapshot.
    """
    from candid import audit as A
    from candid import tracker as T

    try:
        entry = A.get(entry_id)
    except Exception as exc:
        raise UndoError(f"Unknown audit entry id {entry_id!r}: {exc}") from exc
    if not isinstance(entry, dict):
        raise UndoError(f"Unknown audit entry id {entry_id!r}.")

    if entry.get("entity") != "tracker":
        raise UndoError(
            f"Cannot undo audit entry {entry.get('id')!r}: "
            f"entity {entry.get('entity')!r} is not undoable "
            "(only tracker entries can be undone)."
        )

    action = entry.get("action")
    if action not in ("create", "update", "delete", "undo"):
        raise UndoError(
            f"Cannot undo audit entry {entry.get('id')!r}: "
            f"unknown action {action!r}."
        )

    entity_id = str(entry.get("entity_id"))
    apps = T._load()
    current = next((a for a in apps if str(a.get("id")) == entity_id), None)
    before_now = _snapshot(current)  # state before this undo runs

    if action in ("update", "undo"):
        target = _snapshot(entry.get("before"))
        if target is None:
            raise UndoError(
                f"Cannot undo audit entry {entry.get('id')!r}: no 'before' snapshot."
            )
        for i, a in enumerate(apps):
            if str(a.get("id")) == entity_id:
                apps[i] = target
                break
        else:
            # Record was removed after the update; re-insert the old state.
            apps.append(target)
        restored = target
    elif action == "delete":
        target = _snapshot(entry.get("before"))
        if target is None:
            raise UndoError(
                f"Cannot undo audit entry {entry.get('id')!r}: no 'before' snapshot."
            )
        if current is None:
            apps.append(target)
        restored = target
    else:  # action == "create"
        apps = [a for a in apps if str(a.get("id")) != entity_id]
        restored = None

    T._save(apps)
    return A.record(
        actor="cli",
        command="undo",
        entity="tracker",
        entity_id=entity_id,
        action="undo",
        before=before_now,
        after=_snapshot(restored),
        note=f"undo of audit entry {entry.get('id')}",
    )
