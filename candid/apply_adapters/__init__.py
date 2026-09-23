"""Adapter registry for the apply module.

The registry maps a short name to an adapter instance. ``pick`` chooses the
adapter for a page; ``register`` lets new ATS adapters plug in without
editing this file.

Adapter contract
----------------
A new adapter must satisfy the ``candid.apply_adapters.base.Adapter``
protocol:

- ``name: str`` - unique registry name (e.g. "greenhouse").
- ``detect(page) -> bool`` - True if this adapter handles the current page.
  Must be cheap and side-effect free; exceptions are swallowed by ``pick``.
- ``fill(page, profile, resume_pdf, answered) -> FillResult`` - fill only
  SAFE-classified fields, upload the resume PDF, and collect everything
  else as ``Need`` items. It must NEVER submit the application.

The ``page`` argument is duck-typed (never a playwright type), so adapters
can be unit-tested against a fake page object. The page-facing methods an
adapter may call are: ``query_selector_all``, ``evaluate``,
``get_attribute``, ``set_input_files``, ``select_option``, ``fill``,
``check`` / ``uncheck``, ``is_checked``, and ``get_by_role``.
"""

from __future__ import annotations

from candid.apply_adapters.base import Adapter, FillResult, Need
from candid.apply_adapters.generic import GenericAdapter

__all__ = ["Adapter", "FillResult", "Need", "ADAPTERS", "pick", "register"]

ADAPTERS: dict[str, Adapter] = {
    "generic": GenericAdapter(),
}


def register(name: str, adapter: Adapter) -> None:
    """Add (or replace) an adapter under ``name``.

    Example::

        from candid.apply_adapters import register
        register("greenhouse", GreenhouseAdapter())
    """
    ADAPTERS[name] = adapter


def pick(page, hint: str = "generic"):
    """Pick the adapter for a page: explicit hint wins, else first that detects."""
    if hint in ADAPTERS:
        return ADAPTERS[hint]
    for adapter in ADAPTERS.values():
        try:
            if adapter.detect(page):
                return adapter
        except Exception:  # noqa: BLE001
            continue
    return ADAPTERS["generic"]
