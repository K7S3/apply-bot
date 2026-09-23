"""Early-stage and team-size filters for curated job postings.

Stage inference: keyword scan over title + description (``seed``,
``pre-seed``, ``series a/b/c``, ``stealth``, ``founding engineer``), with
``candid_data/startups.json`` consulted first as an authoritative registry
whose stage always overrides text inference.

Size-band inference: headcount ranges in the posting text (``1-10``,
``11-50``, ``51-200``, ``201-500``, ``501+ employees``, ``founding team``,
``team of N``) or the registry's ``employees`` count.

Canonical size bands: ``1-10``, ``11-50``, ``51-200``, ``201-500``, ``501+``.
Filter arguments also accept coarse ranges such as ``1-50`` or ``500+``;
a posting matches when its band's numeric span overlaps the requested one.

Registry format (all optional, read defensively):
    {"startups": [{"name": "...", "stage": "seed", "employees": 8}, ...]}
or a plain list of such dicts, or a {"name": {...}} mapping.
Unknown company or unreadable file: inference falls back to text only.

No network. Postings are treated as data, never executed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config as C


class StartupFilterError(Exception):
    """Raised for startup-filter failures (e.g. malformed CLI values)."""


# ---------------------------------------------------------------------------
# stage inference
# ---------------------------------------------------------------------------

# Canonical stage labels, ordered most-specific first so "pre-seed" wins over
# "seed" and "series a" wins over bare "seed" in the same text.
_STAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"pre[\s-]*seed"), "pre-seed"),
    (re.compile(r"series\s*e\b|series\s*5"), "series-d+"),
    (re.compile(r"series\s*d\b|series\s*4"), "series-d+"),
    (re.compile(r"series\s*c\b|series\s*3"), "series-c"),
    (re.compile(r"series\s*b\b|series\s*2"), "series-b"),
    (re.compile(r"series\s*a\b|series\s*1|\bseries a\b"), "series-a"),
    (re.compile(r"\bseed\b|\bseed[- ]stage\b|\bseed[- ]funded\b"), "seed"),
    (re.compile(r"\bstealth\b|\bstealth[- ]mode\b|\bin stealth\b"), "stealth"),
    (re.compile(r"founding engineer|founding team|founding member"), "seed"),
)

# Labels accepted as filter values (normalized form).
_KNOWN_STAGES = {
    "pre-seed", "seed", "series-a", "series-b", "series-c",
    "series-d+", "stealth",
}

# ---------------------------------------------------------------------------
# size-band inference
# ---------------------------------------------------------------------------

# Canonical bands: (label, lo, hi) with hi=None meaning open-ended.
_SIZE_BANDS: tuple[tuple[str, int, int | None], ...] = (
    ("1-10", 1, 10),
    ("11-50", 11, 50),
    ("51-200", 51, 200),
    ("201-500", 201, 500),
    ("501+", 501, None),
)

# Explicit ranges like "11-50 employees", "51 - 200 people", "201-500 headcount".
_RANGE_RE = re.compile(
    r"(\d{1,4})\s*[-–]\s*(\d{1,4})\s*(?:employees|people|persons|headcount|staff)?"
)
# Open-ended like "500+ employees", "501+".
_PLUS_RE = re.compile(r"(\d{1,4})\s*\+\s*(?:employees|people|persons|headcount|staff)?")
# "team of 12", "team of ~40", "grown to 30 people".
_TEAM_OF_RE = re.compile(
    r"(?:team of|headcount of|grown to|now at)\s*~?\s*(\d{1,4})\s*(?:people|employees|persons|staff|engineers|members)?"
)
# "founding team" implies a handful of people.
_FOUNDING_TEAM_RE = re.compile(r"founding team|founding staff")


def _normalize_stage(label: str) -> str | None:
    s = label.strip().lower().replace("_", "-").replace(" ", "-")
    s = s.replace("--", "-")
    aliases = {
        "seriesa": "series-a", "seriesb": "series-b", "seriesc": "series-c",
        "preseed": "pre-seed", "series-d": "series-d+",
    }
    s = aliases.get(s, s)
    return s if s in _KNOWN_STAGES else None


def _normalize_size(spec: str) -> tuple[int, int | None]:
    """Parse a filter size spec like '1-50' or '500+' into (lo, hi)."""
    s = spec.strip().lower()
    m = re.fullmatch(r"(\d{1,4})\s*[-–]\s*(\d{1,4})", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            raise StartupFilterError(f"Invalid size range '{spec}': low > high")
        return lo, hi
    m = re.fullmatch(r"(\d{1,4})\s*\+", s)
    if m:
        return int(m.group(1)), None
    for label, blo, bhi in _SIZE_BANDS:
        if s == label:
            return blo, bhi
    raise StartupFilterError(
        f"Unknown size spec '{spec}': use bands like 1-10, 11-50, 51-200, "
        "201-500, 501+, or ranges like 1-50 / 500+"
    )


def _band_for_count(n: int) -> str:
    for label, lo, hi in _SIZE_BANDS:
        if hi is None:
            if n >= lo:
                return label
        elif lo <= n <= hi:
            return label
    return _SIZE_BANDS[0][0] if n < 1 else _SIZE_BANDS[-1][0]


def _band_spans_overlap(
    band_lo: int, band_hi: int | None, want_lo: int, want_hi: int | None
) -> bool:
    """True when a canonical band's numeric span overlaps the wanted span."""
    effective_band_hi = band_hi if band_hi is not None else 10 ** 9
    effective_want_hi = want_hi if want_hi is not None else 10 ** 9
    return band_lo <= effective_want_hi and want_lo <= effective_band_hi


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

_REGISTRY_CACHE: dict | None = None


def _registry_path() -> Path:
    return C.DATA_DIR / "startups.json"


def _load_registry() -> dict:
    """Company-name (lowercased) -> {"stage": ..., "employees": ...}, or {}."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    entries: dict[str, dict] = {}
    try:
        path = _registry_path()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            records: list = []
            if isinstance(raw, list):
                records = raw
            elif isinstance(raw, dict):
                if isinstance(raw.get("startups"), list):
                    records = raw["startups"]
                else:
                    # mapping of name -> attrs
                    records = [
                        {"name": name, **(attrs if isinstance(attrs, dict) else {})}
                        for name, attrs in raw.items()
                    ]
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                name = str(rec.get("name") or rec.get("company") or "").strip().lower()
                if not name:
                    continue
                entries[name] = {
                    "stage": _normalize_stage(str(rec.get("stage", "") or "")),
                    "employees": rec.get("employees"),
                }
    except (OSError, ValueError):
        entries = {}  # unreadable registry: fall back to text-only inference
    _REGISTRY_CACHE = entries
    return entries


def _registry_hit(posting: dict) -> dict | None:
    company = str(posting.get("company") or "").strip().lower()
    if not company:
        return None
    return _load_registry().get(company)


# ---------------------------------------------------------------------------
# public inference API
# ---------------------------------------------------------------------------

def _text(posting: dict) -> str:
    title = str(posting.get("title") or "")
    desc = str(posting.get("description") or "")
    return f"{title}\n{desc}".lower()


def infer_stage(posting: dict) -> str | None:
    """Infer company stage. Registry stage wins; else keyword scan; else None."""
    hit = _registry_hit(posting)
    if hit and hit.get("stage"):
        return hit["stage"]
    text = _text(posting)
    for pattern, stage in _STAGE_PATTERNS:
        if pattern.search(text):
            return stage
    return None


def infer_size_band(posting: dict) -> str | None:
    """Infer team-size band. Registry employees count wins; else text; else None."""
    hit = _registry_hit(posting)
    if hit is not None:
        try:
            n = int(hit.get("employees"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            n = None
        if n and n > 0:
            return _band_for_count(n)
    text = _text(posting)
    m = _RANGE_RE.search(text)
    if m:
        return _band_for_count(int(m.group(1)))
    m = _PLUS_RE.search(text)
    if m:
        n = int(m.group(1))
        upper_bounds = {hi for _, _, hi in _SIZE_BANDS if hi is not None}
        if n in upper_bounds:  # "500+" is open-ended, not the closed 201-500 band
            n += 1
        return _band_for_count(n)
    m = _TEAM_OF_RE.search(text)
    if m:
        return _band_for_count(int(m.group(1)))
    if _FOUNDING_TEAM_RE.search(text):
        return "1-10"
    return None


def filter_postings(
    postings: list[dict],
    stages: list[str] | tuple[str, ...] | set[str] | None = None,
    size_bands: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict]:
    """Keep postings matching any of the given stages / size specs.

    stages: canonical labels like "seed", "series-a" (unknown labels raise).
    size_bands: canonical bands ("11-50") or coarse ranges ("1-50", "500+");
    a posting matches when its inferred band overlaps the requested span.
    Postings with unknown stage/size match only when the corresponding
    filter is absent.
    """
    want_stages: set[str] | None = None
    if stages:
        want_stages = set()
        for s in stages:
            norm = _normalize_stage(str(s))
            if norm is None:
                raise StartupFilterError(
                    f"Unknown stage '{s}': choose from "
                    + ", ".join(sorted(_KNOWN_STAGES))
                )
            want_stages.add(norm)
    want_sizes: list[tuple[int, int | None]] | None = None
    if size_bands:
        want_sizes = [_normalize_size(str(s)) for s in size_bands]

    out = []
    for p in postings:
        if want_stages is not None and infer_stage(p) not in want_stages:
            continue
        if want_sizes is not None:
            band = infer_size_band(p)
            if band is None:
                continue
            blo, bhi = next((l, h) for label, l, h in _SIZE_BANDS if label == band)
            if not any(_band_spans_overlap(blo, bhi, wlo, whi) for wlo, whi in want_sizes):
                continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# CLI helpers (wired into jobs curate by the coordinator; __main__.py untouched)
# ---------------------------------------------------------------------------

def add_filter_args(parser) -> None:
    """Register --stage / --size on the `jobs curate` subparser."""
    parser.add_argument(
        "--stage", default=None,
        help="Filter by company stage, comma-separated: "
             "pre-seed, seed, series-a, series-b, series-c, series-d+, stealth")
    parser.add_argument(
        "--size", default=None,
        help="Filter by team size, comma-separated bands or ranges: "
             "1-10, 11-50, 51-200, 201-500, 501+, or ranges like 1-50, 500+")


def apply_filters(args, postings: list[dict]) -> list[dict]:
    """Apply parsed --stage/--size filters to a posting list. No-op when unset."""
    def csv(value: str | None) -> list[str]:
        return [x.strip() for x in value.split(",") if x.strip()] if value else []
    stages = csv(getattr(args, "stage", None))
    sizes = csv(getattr(args, "size", None))
    if not stages and not sizes:
        return postings
    return filter_postings(postings, stages=stages or None, size_bands=sizes or None)
