"""Offer evaluation: side-by-side total-comp comparison.

Everything is driven by offer data the user enters — nothing is estimated
from the network. Each offer records:

    company, role, level, location,
    base (annual $), bonus_target_pct, bonus_first_year_guaranteed ($),
    sign_on (one-time $, optional),
    equity_type (rsu/options), equity_total ($ grant value), vest_years,
    vest_schedule (e.g. "25/25/25/25" or "40/30/20/10"),
    benefits_value ($/yr estimate: 401k match, health, etc.),
    start_date, notes

Total comp year 1 = base + first-year bonus + sign-on + equity vesting year 1
+ benefits. Normalized annual = base + target bonus + sign-on/2 (amortized
over 2 years) + equity_total/vest_years + benefits. The sign-on amortization
keeps offers comparable when one leans on a big first-year sweetener.
Stored at candid_data/offers.json (git-ignored).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class OfferError(Exception):
    """Raised for invalid offer data or operations."""


# Clearly labeled rough estimate - tax law changes and this is not advice.
TAX_NOTE = (
    "_Rough tax note (estimate, not advice): in the US, base salary, cash "
    "bonuses, and sign-ons are taxed as ordinary income when paid, and RSUs are "
    "taxed as ordinary income when they vest (on the share price at vest). As a "
    "very rough 2026 federal reference for a single filer, marginal brackets run "
    "about 22% up to ~$120k, 24% to ~$247k, 32% to ~$626k, then 35%/37% - plus "
    "state and city tax on top (e.g., NYC). A large year-1 vest can push you "
    "into a higher bracket that year, so compare offers after-tax, not pre-tax. "
    "ISOs/NSOs have different rules. Confirm the current IRS tables and talk "
    "to a tax pro before deciding._"
)


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.OFFERS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OfferError(f"Offers file {p} is not valid JSON: {exc}") from exc
    return data if isinstance(data, list) else []


def _save(offers: list[dict], path: str | Path | None = None) -> None:
    p = Path(path) if path else C.OFFERS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(offers, indent=2), encoding="utf-8")


def _money(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        raise OfferError(f"Expected a dollar amount, got '{x}'.")


def normalize(offer: dict) -> dict:
    """Compute normalized comp figures for one offer. Returns a new dict."""
    base = _money(offer.get("base"))
    bonus_pct = _money(offer.get("bonus_target_pct"))
    bonus_first = _money(offer.get("bonus_first_year_guaranteed"))
    sign_on = _money(offer.get("sign_on"))
    equity_total = _money(offer.get("equity_total"))
    vest_years = int(offer.get("vest_years") or 4)
    if vest_years < 1:
        raise OfferError("vest_years must be >= 1.")
    benefits = _money(offer.get("benefits_value"))

    schedule = str(offer.get("vest_schedule") or "").strip()
    if schedule:
        parts = [float(p) for p in schedule.replace("%", "").split("/")]
        if abs(sum(parts) - 100) > 0.5:
            raise OfferError(f"vest_schedule '{schedule}' should sum to 100.")
        year1_pct = parts[0] / 100
    else:
        year1_pct = 1 / vest_years

    target_bonus = base * bonus_pct / 100
    first_year_bonus = bonus_first or target_bonus
    year1_equity = equity_total * year1_pct
    annual_equity = equity_total / vest_years
    signon_amortized_2yr = sign_on / 2

    year1_total = base + first_year_bonus + sign_on + year1_equity + benefits
    normalized_annual = (base + target_bonus + signon_amortized_2yr
                         + annual_equity + benefits)

    out = dict(offer)
    out.update({
        "target_bonus": round(target_bonus, 2),
        "year1_equity_vest": round(year1_equity, 2),
        "annual_equity": round(annual_equity, 2),
        "signon_amortized_2yr": round(signon_amortized_2yr, 2),
        "year1_total": round(year1_total, 2),
        "normalized_annual": round(normalized_annual, 2),
    })
    return out


def add(fields: dict, path: str | Path | None = None) -> dict:
    """Add an offer from a fields dict. Returns the normalized record."""
    if not fields.get("company") or not fields.get("role"):
        raise OfferError("Offers need at least company and role.")
    offers = _load(path)
    rec = normalize({**fields, "id": max((o.get("id", 0) for o in offers), default=0) + 1})
    offers.append(rec)
    _save(offers, path)
    return rec


def list_offers(path: str | Path | None = None) -> list[dict]:
    return sorted(_load(path), key=lambda o: o.get("normalized_annual", 0), reverse=True)


def get_offer(offer_id: int, path: str | Path | None = None) -> dict:
    """Fetch one recorded offer by id. Raises OfferError if missing."""
    for o in _load(path):
        if o.get("id") == int(offer_id):
            return o
    raise OfferError(f"No offer with id {offer_id}.")


def render_comparison(offers: list[dict]) -> str:
    """Side-by-side comparison table, sorted by normalized annual comp."""
    if not offers:
        return "No offers recorded yet. Add one with: python -m candid offer add ..."
    rows = [
        ("Company", lambda o: o.get("company", "")),
        ("Role / level", lambda o: f"{o.get('role', '')} {o.get('level', '')}".strip()),
        ("Location", lambda o: o.get("location", "")),
        ("Base", lambda o: _fmt(o.get("base"))),
        ("Target bonus", lambda o: f"{_fmt(o.get('target_bonus'))} ({o.get('bonus_target_pct', 0)}%)"),
        ("Sign-on", lambda o: _fmt(o.get("sign_on"))),
        ("Equity (total)", lambda o: f"{_fmt(o.get('equity_total'))} {o.get('equity_type', '').upper()} / {o.get('vest_years', 4)}y"),
        ("Equity / yr", lambda o: _fmt(o.get("annual_equity"))),
        ("Benefits est.", lambda o: _fmt(o.get("benefits_value"))),
        ("Year-1 total", lambda o: _fmt(o.get("year1_total"))),
        ("Normalized $/yr", lambda o: _fmt(o.get("normalized_annual"))),
    ]
    col_w = max(len(str(o.get("company", ""))) for o in offers + [{}]) + 4
    lines = []
    header = f"{'':<16}" + "".join(f"{o.get('company', '')[:col_w-2]:<{col_w}}" for o in offers)
    lines.append(header)
    lines.append("-" * len(header))
    for label, fn in rows:
        lines.append(f"{label:<16}" + "".join(f"{str(fn(o))[:col_w-2]:<{col_w}}" for o in offers))
    lines += [
        "",
        "Normalized $/yr = base + target bonus + sign-on/2 (amortized over 2 "
        "years) + equity/vesting-years + benefits.",
        "Year-1 total uses the guaranteed first-year bonus, the full sign-on, "
        "and the actual year-1 vest %."
        if any(o.get("vest_schedule") for o in offers) else
        "Year-1 total uses the guaranteed first-year bonus, the full sign-on, "
        "and straight-line vesting.",
        "",
        TAX_NOTE,
    ]
    return "\n".join(lines)


def export_comparison(offers: list[dict], path: str | Path | None = None) -> Path:
    """Write the comparison as markdown. Returns the saved path."""
    if path is None:
        d = C.DATA_DIR / "offer_comparisons"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{date.today().isoformat()}_offer_comparison.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    if not offers:
        md = "# Offer Comparison\n\nNo offers recorded yet.\n"
    else:
        offers = sorted(offers, key=lambda o: o.get("normalized_annual", 0),
                        reverse=True)
        header = ["Company", "Role / level", "Location", "Base", "Target bonus",
                  "Sign-on", "Equity (total)", "Equity / yr", "Benefits",
                  "Year-1 total", "Normalized $/yr"]
        lines = ["# Offer Comparison", "",
                 f"*Generated {date.today().isoformat()} · sorted by normalized annual comp*",
                 ""]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for o in offers:
            cells = [
                o.get("company", ""),
                f"{o.get('role', '')} {o.get('level', '')}".strip(),
                o.get("location", ""),
                _fmt(o.get("base")),
                f"{_fmt(o.get('target_bonus'))} ({o.get('bonus_target_pct', 0)}%)",
                _fmt(o.get("sign_on")),
                f"{_fmt(o.get('equity_total'))} {o.get('equity_type', '').upper()} / {o.get('vest_years', 4)}y",
                _fmt(o.get("annual_equity")),
                _fmt(o.get("benefits_value")),
                _fmt(o.get("year1_total")),
                f"**{_fmt(o.get('normalized_annual'))}**",
            ]
            lines.append("| " + " | ".join(cells) + " |")
        for o in offers:
            if o.get("notes"):
                lines += ["", f"**{o.get('company', '')} notes:** {o['notes']}"]
        lines += ["",
                  "Normalized $/yr = base + target bonus + sign-on/2 (amortized "
                  "over 2 years) + equity/vesting-years + benefits.",
                  "",
                  TAX_NOTE,
                  ""]
        md = "\n".join(lines)
    path.write_text(md, encoding="utf-8")
    return path


def _fmt(x) -> str:
    try:
        return f"${float(x or 0):,.0f}"
    except (TypeError, ValueError):
        return "—"
