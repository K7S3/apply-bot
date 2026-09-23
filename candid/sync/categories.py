"""Sync categories: named groups of files/dirs under DATA_DIR.

A category maps to one or more paths *relative* to config.DATA_DIR.
Directories are synced recursively. Missing paths are simply skipped.
"""

from __future__ import annotations

#: category -> tuple of relative paths under DATA_DIR
CATEGORIES: dict[str, tuple[str, ...]] = {
    "profile": ("profile.json",),
    "tracker": ("tracker.json",),
    "offers": ("offers.json",),
    "salary": ("salary.db",),
    "prep": ("prep_packs",),
    "tailored": ("tailored",),
    "gmail": ("gmail_proposals.json",),
}

#: Where sync bookkeeping lives (base snapshots, history, pairing registry).
SYNC_STATE_DIRNAME = "sync"


def resolve(category: str) -> tuple[str, ...]:
    """Return the relative paths for a category; raises SyncError if unknown."""
    from candid.sync.errors import SyncError

    try:
        return CATEGORIES[category]
    except KeyError:
        raise SyncError(
            f"unknown sync category {category!r}; "
            f"choose from: {', '.join(sorted(CATEGORIES))}"
        ) from None


def all_categories() -> list[str]:
    return sorted(CATEGORIES)
