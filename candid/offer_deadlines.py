"""Offer decision deadlines: exploding-offer countdown + decision framework.

Deadlines live in a sidecar file (candid_data/offer_deadlines.json, keyed by
offer id) so offer.py's storage and core logic stay untouched. Reads offers
only through offer.py's public functions (list_offers, normalize).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class OfferDeadlineError(Exception):
    """Raised for invalid deadline data or operations."""


#: Fewer than this many days left counts as an "exploding" offer.
EXPLODING_DAYS = 7

#: Criteria supported by the weighted decision framework.
CRITERIA = ("comp", "growth", "team", "location", "stability")

_NEXT = "Run: python -m candid offer deadline --help"


def _data_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir) if data_dir else C.DATA_DIR


def deadlines_path(data_dir: str | Path | None = None) -> Path:
    """Path of the sidecar file. Overridable for tests."""
    return _data_dir(data_dir) / "offer_deadlines.json"


def _load(data_dir: str | Path | None = None) -> dict[str, dict]:
    p = deadlines_path(data_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OfferDeadlineError(
            f"Deadline file {p} is not valid JSON: {exc}. {_NEXT}") from exc
    return data if isinstance(data, dict) else {}


def _save(deadlines: dict[str, dict],
          data_dir: str | Path | None = None) -> Path:
    p = deadlines_path(data_dir)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(deadlines, indent=2), encoding="utf-8")
    return p


def _parse_date(value: str, what: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except (ValueError, AttributeError):
        raise OfferDeadlineError(
            f"{what} '{value}' is not a valid YYYY-MM-DD date. {_NEXT}"
        ) from None


def _offers(offers_path: str | Path | None = None) -> list[dict]:
    from candid import offer as O
    return O.list_offers(path=offers_path)


def set_deadline(offer_id: int, deadline: str,
                 offers_path: str | Path | None = None,
                 data_dir: str | Path | None = None) -> dict:
    """Attach a decision deadline (YYYY-MM-DD) to an offer.

    Returns the stored deadline record. Raises OfferDeadlineError if the
    offer id is unknown or the date is invalid.
    """
    dl = _parse_date(deadline, "Deadline")
    offers = _offers(offers_path)
    match = next((o for o in offers if o.get("id") == offer_id), None)
    if match is None:
        known = ", ".join(f"#{o.get('id')} {o.get('company', '')}"
                          for o in offers) or "no offers recorded"
        raise OfferDeadlineError(
            f"Unknown offer id {offer_id} (have: {known}). "
            f"Run: python -m candid offer list")
    deadlines = _load(data_dir)
    rec = {
        "offer_id": offer_id,
        "company": match.get("company", ""),
        "role": match.get("role", ""),
        "decision_deadline": dl.isoformat(),
    }
    deadlines[str(offer_id)] = rec
    _save(deadlines, data_dir)
    return rec


def remove_deadline(offer_id: int,
                    data_dir: str | Path | None = None) -> bool:
    """Remove a stored deadline. Returns True if one existed."""
    deadlines = _load(data_dir)
    if str(offer_id) not in deadlines:
        return False
    del deadlines[str(offer_id)]
    _save(deadlines, data_dir)
    return True


def get_deadline(offer_id: int,
                 data_dir: str | Path | None = None) -> dict | None:
    """Return the deadline record for an offer, or None if unset."""
    return _load(data_dir).get(str(offer_id))


def _days_left(dl: str, today: date) -> int:
    return (_parse_date(dl, "Deadline") - today).days


def list_deadlines(today: date | None = None,
                   offers_path: str | Path | None = None,
                   data_dir: str | Path | None = None) -> list[dict]:
    """Deadlines merged with offer info, most urgent first.

    Each entry: {offer_id, company, role, decision_deadline, days_left,
    exploding}. Entries are skipped if their offer no longer exists.
    """
    today = today or date.today()
    offers = {o.get("id"): o for o in _offers(offers_path)}
    out = []
    for key, rec in _load(data_dir).items():
        try:
            oid = int(key)
        except (TypeError, ValueError):
            continue
        offer = offers.get(oid)
        if offer is None:
            continue  # offer deleted since the deadline was set
        days = _days_left(rec["decision_deadline"], today)
        out.append({
            "offer_id": oid,
            "company": offer.get("company", ""),
            "role": offer.get("role", ""),
            "decision_deadline": rec["decision_deadline"],
            "days_left": days,
            "exploding": days < EXPLODING_DAYS,
        })
    return sorted(out, key=lambda e: e["days_left"])


def render_countdown(today: date | None = None,
                     offers_path: str | Path | None = None,
                     data_dir: str | Path | None = None) -> str:
    """Render the deadline countdown, most urgent first."""
    entries = list_deadlines(today=today, offers_path=offers_path,
                             data_dir=data_dir)
    if not entries:
        return ("No decision deadlines set yet. "
                "Set one with:\n  python -m candid offer deadline set "
                "--id <offer-id> --date YYYY-MM-DD")
    lines = ["Offer decision deadlines:", ""]
    for e in entries:
        d = e["days_left"]
        if d < 0:
            when = f"PASSED {-d}d ago"
        elif d == 0:
            when = "DUE TODAY"
        elif d == 1:
            when = "1 day left"
        else:
            when = f"{d} days left"
        flag = "  <-- EXPLODING OFFER" if e["exploding"] else ""
        lines.append(f"  #{e['offer_id']} {e['company']} — decide by "
                     f"{e['decision_deadline']} ({when}){flag}")
    lines.append("")
    lines.append(f"Exploding = fewer than {EXPLODING_DAYS} days left. "
                 "Negotiate an extension or decide now.")
    return "\n".join(lines)


# --- weighted decision framework --------------------------------------------


def _validate_weights(weights: dict) -> dict[str, float]:
    if not weights:
        raise OfferDeadlineError(
            f"Weights are required, e.g. --weights comp=5,growth=4,team=3,"
            f"location=2,stability=3. {_NEXT}")
    unknown = [k for k in weights if k not in CRITERIA]
    if unknown:
        raise OfferDeadlineError(
            f"Unknown criteria: {', '.join(unknown)} "
            f"(use: {', '.join(CRITERIA)}). {_NEXT}")
    out = {}
    for k in CRITERIA:
        try:
            v = float(weights.get(k, 1))
        except (TypeError, ValueError):
            raise OfferDeadlineError(
                f"Weight for '{k}' must be a number, got "
                f"'{weights.get(k)}'. {_NEXT}") from None
        if v < 0:
            raise OfferDeadlineError(
                f"Weight for '{k}' must be >= 0. {_NEXT}")
        out[k] = v
    if sum(out.values()) <= 0:
        raise OfferDeadlineError(
            f"At least one weight must be positive. {_NEXT}")
    return out


def _validate_scores(scores: dict, offer_ids: set[int]) -> dict[int, dict]:
    """Scores: {offer_id: {criterion: 0-10}} for non-comp criteria.

    ``comp`` is always derived from offer.normalize() and any supplied comp
    score is ignored (comp comes from the numbers, not gut feel).
    """
    scores = scores or {}
    out: dict[int, dict] = {}
    for oid in offer_ids:
        raw = scores.get(oid) or scores.get(str(oid)) or {}
        crit: dict[str, float] = {}
        for k in CRITERIA:
            if k == "comp":
                continue
            v = raw.get(k, 0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise OfferDeadlineError(
                    f"Score for '{k}' on offer #{oid} must be 0-10, got "
                    f"'{v}'. {_NEXT}") from None
            if not 0 <= v <= 10:
                raise OfferDeadlineError(
                    f"Score for '{k}' on offer #{oid} must be 0-10, got "
                    f"{v}. {_NEXT}")
            crit[k] = v
        out[oid] = crit
    return out


def _comp_scores(offers: list[dict]) -> dict[int, float]:
    """Comp score 0-10 per offer, scaled from normalized_annual (best = 10)."""
    from candid import offer as O
    vals: dict[int, float] = {}
    for o in offers:
        n = O.normalize(o)
        vals[int(o.get("id"))] = float(n.get("normalized_annual") or 0)
    peak = max(vals.values(), default=0)
    if peak <= 0:
        return {oid: 0.0 for oid in vals}
    return {oid: round(10 * v / peak, 2) for oid, v in vals.items()}


def score_offers(weights: dict, scores: dict | None = None,
                 offers: list[dict] | None = None,
                 offers_path: str | Path | None = None) -> list[dict]:
    """Rank offers on weighted criteria.

    weights: {criterion: weight} over comp/growth/team/location/stability.
    scores: {offer_id: {criterion: 0-10}} — needed for every criterion
      except comp, which is derived from offer.normalize() and scaled
      0-10 across the offers.

    Returns ranked rows: {offer_id, company, role, normalized_annual,
    total (weighted avg 0-10), breakdown {criterion: weighted pts}}.
    """
    offers = _offers(offers_path) if offers is None else offers
    if len(offers) < 2:
        raise OfferDeadlineError(
            "Weighted comparison needs at least 2 offers. "
            "Run: python -m candid offer add --help")
    w = _validate_weights(weights)
    oids = {int(o.get("id")) for o in offers}
    crit_scores = _validate_scores(scores or {}, oids)
    comp = _comp_scores(offers)
    total_w = sum(w.values())
    rows = []
    for o in offers:
        oid = int(o.get("id"))
        full = {**crit_scores[oid], "comp": comp.get(oid, 0.0)}
        breakdown = {k: round(full[k] * w[k] / total_w, 2)
                     for k in CRITERIA}
        rows.append({
            "offer_id": oid,
            "company": o.get("company", ""),
            "role": o.get("role", ""),
            "normalized_annual": float(o.get("normalized_annual") or 0),
            "total": round(sum(breakdown.values()), 2),
            "breakdown": breakdown,
            "raw_scores": {k: full[k] for k in CRITERIA},
        })
    return sorted(rows, key=lambda r: r["total"], reverse=True)


def _mind_change_levers(winner: dict, loser: dict,
                        weights: dict) -> list[str]:
    """For one non-winning offer: what score bumps would close the gap.

    Returns human-readable 'levers' — criterion + the 0-10 score the offer
    would need on that criterion alone to tie the winner.
    """
    total_w = sum(weights.values())
    gap = winner["total"] - loser["total"]
    if gap <= 0:
        return []
    levers = []
    for k in CRITERIA:
        w = weights[k]
        if w <= 0:
            continue
        # weighted contribution needed: need_delta on the 0-10 score
        need_delta = gap * total_w / w
        current = loser["raw_scores"][k]
        target = current + need_delta
        if target <= 10:
            levers.append((need_delta, k, current, target))
    levers.sort()
    out = []
    for _, k, current, target in levers[:2]:
        if k == "comp":
            # comp is derived from normalized comp, not a gut score the
            # user controls — phrase it as what the numbers would need.
            out.append(
                f"its comp scored {target:.1f}/10 instead of {current:.0f}/10 "
                f"(i.e. negotiate the numbers up)")
        else:
            out.append(
                f"raise {k} from {current:.0f}/10 to {target:.1f}/10")
    return out


def render_decision(weights: dict, scores: dict | None = None,
                    offers: list[dict] | None = None,
                    today: date | None = None,
                    offers_path: str | Path | None = None,
                    data_dir: str | Path | None = None) -> str:
    """Ranked weighted comparison + 'what would change my mind' prompt."""
    rows = score_offers(weights, scores=scores, offers=offers,
                        offers_path=offers_path)
    w = _validate_weights(weights)
    today = today or date.today()
    deadlines = {int(k): v.get("decision_deadline")
                 for k, v in _load(data_dir).items() if k.lstrip("-").isdigit()}

    lines = ["Weighted offer comparison "
             f"(weights: {', '.join(f'{k}={w[k]:g}' for k in CRITERIA)}):", ""]
    header = (f"{'#':<4}{'Company':<18}{'Total':<8}"
              + "".join(f"{k[:6]:>8}" for k in CRITERIA)
              + f"{'$/yr':>12}{'Decide by':>14}")
    lines.append(header)
    lines.append("-" * len(header))
    for i, r in enumerate(rows):
        dl = deadlines.get(r["offer_id"], "—")
        mark = " <-- top" if i == 0 else ""
        lines.append(
            f"#{r['offer_id']:<3}{r['company'][:16]:<18}{r['total']:<8.1f}"
            + "".join(f"{r['breakdown'][k]:>8.1f}" for k in CRITERIA)
            + f" ${r['normalized_annual']:>10,.0f}{dl:>14}{mark}")
    lines.append("")
    lines.append("Scores are 0-10 per criterion, weighted into the total. "
                 "comp is derived from normalized annual comp (best = 10); "
                 "the rest are your gut scores.")
    lines.append("")
    lines.append("What would change my mind:")
    winner = rows[0]
    any_lever = False
    for loser in rows[1:]:
        levers = _mind_change_levers(winner, loser, w)
        if levers:
            any_lever = True
            lines.append(f"  {loser['company']} beats {winner['company']} if you:")
            for lv in levers:
                lines.append(f"    - {lv}")
    if not any_lever:
        lines.append("  No single-criterion score change (0-10) closes the "
                     "gap — the top offer wins on the merits you weighted.")
    lines.append("")
    lines.append("Before you decide, pressure-test the weights: would you "
                 "still pick it if comp counted half as much?")
    return "\n".join(lines)
