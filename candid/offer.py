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


class OfferError(ValueError):
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


_ANNOUNCE_TONES = ("warm", "concise")


def _start_phrase(start_date: str) -> str:
    start_date = (start_date or "").strip()
    return f", starting {start_date}" if start_date else ""


def announcement(name: str, role: str, company: str, start_date: str = "",
                 tone: str = "warm") -> dict:
    """Draft announcement texts for after you sign.

    Returns a dict with two variants:
      - "linkedin_post": a tasteful public post (gratitude, new role and
        company, start date if given).
      - "network_message": a short DM-style note for telling contacts
        individually.

    Comp numbers are never included in any variant. Tones: "warm"
    (default), "concise". These are drafts - nothing posts or sends
    itself.
    """
    if tone not in _ANNOUNCE_TONES:
        raise OfferError(f"Unknown tone '{tone}'. Choose from {list(_ANNOUNCE_TONES)}.")
    for label, value in (("name", name), ("role", role), ("company", company)):
        if not str(value or "").strip():
            raise OfferError(f"Announcement needs a {label}.")
    name, role, company = name.strip(), role.strip(), company.strip()
    start = _start_phrase(start_date)
    if tone == "concise":
        linkedin_post = (
            f"Excited to share some personal news: I'm joining {company} "
            f"as a {role}{start}.\n\n"
            f"Thanks to everyone who supported me through the search. "
            f"Looking forward to what's ahead!\n\n"
            f"- {name}"
        )
        network_message = (
            f"Quick personal update: I'm joining {company} as a "
            f"{role}{start}. Thanks for your support during the search - "
            f"let's catch up once I settle in!\n\n"
            f"- {name}"
        )
    else:
        linkedin_post = (
            f"Some personal news I'm excited to share: I'm joining {company} "
            f"as a {role}{start}.\n\n"
            f"Huge thanks to everyone who supported me through the search - "
            f"the mentors who took my calls, the friends who talked me "
            f"through tough decisions, and everyone who cheered me on. "
            f"I'm grateful for this opportunity and looking forward to "
            f"what's ahead.\n\n"
            f"- {name}"
        )
        network_message = (
            f"Hi! Wanted to share some news with you personally: I've signed "
            f"an offer and I'm joining {company} as a {role}{start}.\n\n"
            f"Thanks for all your support during the search - it really "
            f"meant a lot. Would love to catch up properly once I settle in!\n\n"
            f"- {name}"
        )
    return {"linkedin_post": linkedin_post, "network_message": network_message}


def render_announcement(name: str, role: str, company: str, start_date: str = "",
                        tone: str = "warm") -> str:
    """Render both announcement variants as Markdown."""
    variants = announcement(name, role, company, start_date=start_date, tone=tone)
    lines = [
        "# Offer Announcement Drafts",
        "",
        f"*For: {name.strip()} - {role.strip()} at {company.strip()}*",
        "",
        "## LinkedIn post",
        "",
        variants["linkedin_post"],
        "",
        "## Message to your network",
        "",
        variants["network_message"],
        "",
        "_These are drafts. Nothing posts or sends itself - copy, edit, and "
        "share yourself._",
        "",
    ]
    return "\n".join(lines)
