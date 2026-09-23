"""JD red-flag detector: surface warning signs in job postings before you apply.

Each detector in this package exposes ``detect(text) -> list[Flag]`` and is
registered in :data:`candid.redflags.core.DETECTORS`. Use
:func:`candid.redflags.core.analyze` to run them all over a posting.

Importing this package imports every detector module so that all detectors
are registered no matter which entry point is used (CLI, report, or tests).
"""

from . import bait  # noqa: F401  (registers detectors on import)
from . import clarity  # noqa: F401  (registers detectors on import)
from . import compliance  # noqa: F401  (registers detectors on import)
from . import compensation  # noqa: F401  (registers detectors on import)
from . import ghostjobs  # noqa: F401  (registers detectors on import)
from . import greenflags  # noqa: F401  (registers detectors on import)
from . import requirements  # noqa: F401  (registers detectors on import)
from . import turnover  # noqa: F401  (registers detectors on import)
from .core import DETECTORS, Flag, analyze, register, risk_score

__all__ = [
    "DETECTORS",
    "Flag",
    "analyze",
    "register",
    "risk_score",
    "bait",
    "clarity",
    "compliance",
    "compensation",
    "ghostjobs",
    "greenflags",
    "requirements",
    "turnover",
]
