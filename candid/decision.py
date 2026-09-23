"""Offer decision journal: structured thinking for hard offer choices.

Beyond raw comp (see candid/offer.py), a good decision needs structured
reflection. This module keeps a per-offer decision journal at
candid_data/decisions.json (git-ignored), keyed by offer id from
candid/offer.py. Everything is user-entered; nothing is inferred or
estimated from the network.

The ten features:

1. Weighted pros/cons: add pros and cons with 1-3 weights, see weighted
   totals and a net score per offer.
2. Criteria scorecard: set your own decision criteria with weights
   (comp, growth, work-life balance, manager, mission, location...), score
   each offer 1-10 per criterion, and get a ranked decision matrix.
3. Gut-check prompts: a rotating bank of reflective questions; journal
   your answers per offer.
4. Decision deadlines: track respond-by dates with countdowns and
   exploding-offer flags.
5. Decision lifecycle: states (considering, leaning, negotiating, accepted,
   declined, withdrawn) plus timestamped freeform journal notes and a
   full timeline view.
6. Regret-minimization exercise: record what you would regret about taking
   vs. declining each offer, plus a 10-year projection.
7. Reasons snapshot + revisit: freeze your top reasons at decision time,
   then revisit later and mark what is still true vs. what changed.
8. Advice log: record who advised what and their stance per offer, with a
   consensus view.
9. Confidence tracking: log 1-10 confidence in your leaning over time and
   see the history.
10. Journal export: one markdown document with everything above, per offer
    or for all offers, suitable for sharing with a partner or mentor.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from candid import config as C
from candid import offer as OFF


class DecisionError(Exception):
    """Raised for invalid decision-journal data or operations."""


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

STATES = ["considering", "leaning", "negotiating", "accepted",
          "declined", "withdrawn"]

DEFAULT_CRITERIA = ["comp", "growth", "wlb", "manager", "mission", "location"]

CRITERIA_LABELS = {
    "comp": "Compensation",
    "growth": "Growth / scope",
    "wlb": "Work-life balance",
    "manager": "Manager / team",
    "mission": "Mission / product",
    "location": "Location / remote",
}

STANCES = ["for", "against", "neutral"]

# Rotating bank of reflective prompts. Shown one per day by default.
GUT_PROMPTS = [
    "If this offer were withdrawn tomorrow, how disappointed would you be (1-10)?",
    "Imagine it is one year from now and you took this offer. What does a good Tuesday look like?",
    "What is the single biggest thing you would be giving up by taking this offer?",
    "If comp were identical across all your offers, which would you pick?",
    "What would you tell a close friend to do if they had these exact offers?",
    "Which part of this offer are you trying to talk yourself into (or out of)?",
    "Fast-forward 10 years: which choice makes the better story?",
    "What does your gut say before your brain starts negotiating with it?",
    "If you had to decide in the next 60 seconds, what would you pick?",
    "What fear is driving your hesitation here, and is it about the offer or about change itself?",
]


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else C.DECISIONS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DecisionError(f"Decisions file {p} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _save(data: dict, path: str | Path | None = None) -> None:
    p = Path(path) if path else C.DECISIONS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _offers(data: dict) -> dict:
    return data.setdefault("offers", {})


def _entry(data: dict, offer_key: str) -> dict:
    offers = _offers(data)
    e = offers.setdefault(str(offer_key), {})
    e.setdefault("pros", [])
    e.setdefault("cons", [])
    e.setdefault("criteria_scores", {})
    e.setdefault("gut_answers", [])
    e.setdefault("deadline", None)
    e.setdefault("state", "considering")
    e.setdefault("journal", [])
    e.setdefault("regret", None)
    e.setdefault("snapshot", None)
    e.setdefault("revisits", [])
    e.setdefault("advice", [])
    e.setdefault("confidence", [])
    return e


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(e: dict, kind: str, text: str) -> None:
    e["journal"].append({"at": _now_iso(), "kind": kind, "text": text})


def _today(d: date | None) -> date:
    return d or date.today()


# ---------------------------------------------------------------------------
# offer resolution
# ---------------------------------------------------------------------------

def resolve_offer(ref: str, offer_path: str | Path | None = None) -> tuple[str, dict]:
    """Resolve an offer reference (id or company-name substring).

    Returns (offer_key, offer_record). Raises DecisionError when the
    reference matches nothing or is ambiguous.
    """
    offers = OFF.list_offers(offer_path)
    ref = str(ref).strip()
    if ref.isdigit():
        for o in offers:
            if str(o.get("id")) == ref:
                return ref, o
    matches = [o for o in offers
               if ref.lower() in str(o.get("company", "")).lower()]
    if len(matches) == 1:
        return str(matches[0].get("id")), matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{o.get('company')} (#{o.get('id')})" for o in matches)
        raise DecisionError(
            f"Offer reference '{ref}' is ambiguous: {names}. Use the offer id.")
    raise DecisionError(
        f"No offer matches '{ref}'. Add one first with: python -m candid offer add ...")


# ---------------------------------------------------------------------------
# 1. weighted pros/cons
# ---------------------------------------------------------------------------

def _check_weight(weight: int) -> int:
    try:
        w = int(weight)
    except (TypeError, ValueError):
        raise DecisionError(f"Weight must be 1, 2, or 3, got '{weight}'.")
    if w not in (1, 2, 3):
        raise DecisionError(f"Weight must be 1, 2, or 3, got {w}.")
    return w


def add_point(offer_key: str, side: str, text: str, weight: int = 2,
              path: str | Path | None = None) -> dict:
    """Add a pro or con with a 1-3 importance weight. Returns the record."""
    if side not in ("pro", "con"):
        raise DecisionError("side must be 'pro' or 'con'.")
    text = (text or "").strip()
    if not text:
        raise DecisionError("Pro/con text cannot be empty.")
    data = _load(path)
    e = _entry(data, offer_key)
    rec = {"text": text, "weight": _check_weight(weight), "added": _now_iso()}
    e["pros" if side == "pro" else "cons"].append(rec)
    _log(e, side, f"({rec['weight']}) {text}")
    _save(data, path)
    return rec


def remove_point(offer_key: str, side: str, index: int,
                 path: str | Path | None = None) -> dict:
    """Remove the 1-based indexed pro/con. Returns the removed record."""
    if side not in ("pro", "con"):
        raise DecisionError("side must be 'pro' or 'con'.")
    data = _load(path)
    e = _entry(data, offer_key)
    items = e["pros" if side == "pro" else "cons"]
    if not 1 <= index <= len(items):
        raise DecisionError(
            f"No {side} #{index} for this offer (has {len(items)}).")
    rec = items.pop(index - 1)
    _log(e, "remove", f"Removed {side} #{index}: {rec['text']}")
    _save(data, path)
    return rec


def pro_con_totals(offer_key: str, path: str | Path | None = None) -> dict:
    """Weighted totals for pros, cons, and the net score."""
    data = _load(path)
    e = _entry(data, offer_key)
    pro_total = sum(p.get("weight", 0) for p in e["pros"])
    con_total = sum(c.get("weight", 0) for c in e["cons"])
    return {
        "pros": e["pros"],
        "cons": e["cons"],
        "pro_total": pro_total,
        "con_total": con_total,
        "net": pro_total - con_total,
    }


def render_pros_cons(offer_key: str, offer: dict | None = None,
                     path: str | Path | None = None) -> str:
    """Render the weighted pros/cons scoreboard for one offer."""
    t = pro_con_totals(offer_key, path)
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    lines = [f"Pros / cons: {title}", ""]
    lines.append("PROS (weight x)")
    if t["pros"]:
        for i, p in enumerate(t["pros"], 1):
            lines.append(f"  {i}. [{p['weight']}] {p['text']}")
    else:
        lines.append("  (none recorded)")
    lines.append("")
    lines.append("CONS (weight x)")
    if t["cons"]:
        for i, c in enumerate(t["cons"], 1):
            lines.append(f"  {i}. [{c['weight']}] {c['text']}")
    else:
        lines.append("  (none recorded)")
    lines += [
        "",
        f"Weighted total: +{t['pro_total']} pros / -{t['con_total']} cons "
        f"=> net {t['net']:+d}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. criteria scorecard
# ---------------------------------------------------------------------------

def set_criteria_weights(weights: dict[str, float],
                         path: str | Path | None = None) -> dict:
    """Set decision-criterion weights. Keys are criterion names, values are
    positive numbers (they are normalized to percentages at rank time)."""
    clean = {}
    for name, w in weights.items():
        name = str(name).strip().lower()
        if not name:
            continue
        try:
            w = float(w)
        except (TypeError, ValueError):
            raise DecisionError(f"Weight for '{name}' must be a number.")
        if w <= 0:
            raise DecisionError(f"Weight for '{name}' must be positive.")
        clean[name] = w
    if not clean:
        raise DecisionError("Give at least one criterion weight.")
    data = _load(path)
    data["criteria_weights"] = clean
    _save(data, path)
    return clean


def get_criteria_weights(path: str | Path | None = None) -> dict:
    data = _load(path)
    return dict(data.get("criteria_weights") or {})


def score_offer(offer_key: str, scores: dict[str, float],
                path: str | Path | None = None) -> dict:
    """Score an offer 1-10 on any criteria. Returns the stored score dict."""
    clean = {}
    for name, s in scores.items():
        name = str(name).strip().lower()
        if not name:
            continue
        try:
            s = float(s)
        except (TypeError, ValueError):
            raise DecisionError(f"Score for '{name}' must be a number 1-10.")
        if not 1 <= s <= 10:
            raise DecisionError(f"Score for '{name}' must be between 1 and 10.")
        clean[name] = s
    if not clean:
        raise DecisionError("Give at least one criterion score (1-10).")
    data = _load(path)
    e = _entry(data, offer_key)
    e["criteria_scores"].update(clean)
    _log(e, "score",
         "Scored " + ", ".join(f"{k}={v:g}" for k, v in sorted(clean.items())))
    _save(data, path)
    return dict(e["criteria_scores"])


def _weighted_score(scores: dict, weights: dict) -> float | None:
    usable = {k: weights[k] for k in scores if k in weights and weights[k] > 0}
    if not usable:
        return None
    total_w = sum(usable.values())
    return sum(scores[k] * usable[k] for k in usable) / total_w


def criteria_rank(offer_path: str | Path | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """Rank all scored offers by weighted criteria score (1-10 scale).

    Returns rows sorted best-first: offer_key, offer, weighted score, and the
    per-criterion scores used. Offers with no scores are skipped.
    """
    data = _load(path)
    weights = get_criteria_weights(path)
    if not weights:
        raise DecisionError(
            "No criteria weights set. Set them with: "
            "python -m candid decision criteria-set --comp 30 --growth 25 ...")
    rows = []
    for key, e in _offers(data).items():
        scores = e.get("criteria_scores") or {}
        if not scores:
            continue
        w = _weighted_score(scores, weights)
        if w is None:
            continue
        offer = next((o for o in OFF.list_offers(offer_path)
                      if str(o.get("id")) == str(key)), {})
        rows.append({"offer_key": str(key), "offer": offer,
                     "weighted": round(w, 2), "scores": scores})
    return sorted(rows, key=lambda r: r["weighted"], reverse=True)


def render_criteria_rank(rows: list[dict], weights: dict) -> str:
    """Render the decision matrix table."""
    if not rows:
        return ("No offers have criteria scores yet. Score one with:\n"
                "  python -m candid decision criteria-score --offer 1 "
                "--comp 8 --growth 7")
    criteria = sorted(weights)
    header = (f"{'Offer':<22}" +
              "".join(f"{CRITERIA_LABELS.get(c, c)[:10]:>11}" for c in criteria) +
              f"{'Weighted':>10}")
    lines = ["Decision matrix (scores 1-10, weighted by your criteria)", "",
             "Weights: " + ", ".join(
                 f"{CRITERIA_LABELS.get(c, c)}={weights[c]:g}" for c in criteria),
             "", header, "-" * len(header)]
    for r in rows:
        name = r["offer"].get("company", f"#{r['offer_key']}")
        cells = "".join(f"{r['scores'].get(c, 0):>11.1f}" for c in criteria)
        lines.append(f"{name[:21]:<22}{cells}{r['weighted']:>10.2f}")
    lines += ["", f"Leader: {rows[0]['offer'].get('company', '#' + rows[0]['offer_key'])} "
                  f"({rows[0]['weighted']:.2f})"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. gut-check prompts
# ---------------------------------------------------------------------------

def gut_prompt(today: date | None = None) -> str:
    """Today's rotating gut-check prompt."""
    d = _today(today)
    return GUT_PROMPTS[d.toordinal() % len(GUT_PROMPTS)]


def gut_answer(offer_key: str, answer: str, prompt: str | None = None,
               path: str | Path | None = None) -> dict:
    """Journal an answer to a gut-check prompt. Returns the record."""
    answer = (answer or "").strip()
    if not answer:
        raise DecisionError("Gut-check answer cannot be empty.")
    data = _load(path)
    e = _entry(data, offer_key)
    rec = {"prompt": prompt or gut_prompt(), "answer": answer,
           "at": _now_iso()}
    e["gut_answers"].append(rec)
    _log(e, "gut", f"Q: {rec['prompt']} -- A: {answer[:80]}")
    _save(data, path)
    return rec


def list_gut_answers(offer_key: str,
                     path: str | Path | None = None) -> list[dict]:
    return list(_entry(_load(path), offer_key)["gut_answers"])


# ---------------------------------------------------------------------------
# 4. decision deadlines
# ---------------------------------------------------------------------------

def set_deadline(offer_key: str, date_str: str, exploding: bool = False,
                 note: str = "", path: str | Path | None = None) -> dict:
    """Set the respond-by deadline for an offer. date_str is YYYY-MM-DD."""
    try:
        d = date.fromisoformat(date_str.strip())
    except ValueError:
        raise DecisionError(
            f"Deadline must be YYYY-MM-DD, got '{date_str}'.") from None
    data = _load(path)
    e = _entry(data, offer_key)
    e["deadline"] = {"date": d.isoformat(), "exploding": bool(exploding),
                     "note": (note or "").strip(), "set_at": _now_iso()}
    _log(e, "deadline",
         f"Respond-by {d.isoformat()}"
         f"{' (exploding)' if exploding else ''}"
         f"{': ' + note.strip() if note.strip() else ''}")
    _save(data, path)
    return e["deadline"]


def clear_deadline(offer_key: str, path: str | Path | None = None) -> None:
    data = _load(path)
    e = _entry(data, offer_key)
    e["deadline"] = None
    _log(e, "deadline", "Deadline cleared.")
    _save(data, path)


def deadline_status(deadline: dict | None,
                    today: date | None = None) -> dict | None:
    """Countdown info for a deadline dict. None when no deadline set."""
    if not deadline:
        return None
    d = _today(today)
    target = date.fromisoformat(deadline["date"])
    days_left = (target - d).days
    if days_left < 0:
        urgency = "overdue"
    elif days_left == 0:
        urgency = "due-today"
    elif days_left <= 3 or (deadline.get("exploding") and days_left <= 7):
        urgency = "urgent"
    elif days_left <= 14:
        urgency = "upcoming"
    else:
        urgency = "scheduled"
    return {"date": deadline["date"], "days_left": days_left,
            "urgency": urgency, "exploding": bool(deadline.get("exploding")),
            "note": deadline.get("note", "")}


def list_deadlines(today: date | None = None,
                   offer_path: str | Path | None = None,
                   path: str | Path | None = None) -> list[dict]:
    """All offers with deadlines, sorted by days left (most urgent first)."""
    data = _load(path)
    out = []
    for key, e in _offers(data).items():
        st = deadline_status(e.get("deadline"), today)
        if not st:
            continue
        offer = next((o for o in OFF.list_offers(offer_path)
                      if str(o.get("id")) == str(key)), {})
        out.append({"offer_key": str(key), "offer": offer, **st})
    return sorted(out, key=lambda r: r["days_left"])


def render_deadlines(rows: list[dict]) -> str:
    if not rows:
        return ("No decision deadlines set. Set one with:\n"
                "  python -m candid decision deadline-set --offer 1 "
                "--date 2026-10-05")
    flag = {"overdue": "OVERDUE", "due-today": "DUE TODAY",
            "urgent": "URGENT", "upcoming": "upcoming", "scheduled": ""}
    lines = ["Decision deadlines", ""]
    for r in rows:
        name = r["offer"].get("company", f"#{r['offer_key']}")
        when = (f"{abs(r['days_left'])}d ago" if r["days_left"] < 0
                else f"in {r['days_left']}d")
        boom = " [exploding]" if r["exploding"] else ""
        tag = f" -- {flag[r['urgency']]}" if flag[r["urgency"]] else ""
        note = f" ({r['note']})" if r["note"] else ""
        lines.append(f"  {name}: {r['date']} ({when}){boom}{tag}{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. decision lifecycle + journal notes + timeline
# ---------------------------------------------------------------------------

def set_state(offer_key: str, state: str,
              path: str | Path | None = None) -> str:
    """Move an offer through the decision lifecycle. Returns the new state."""
    state = (state or "").strip().lower()
    if state not in STATES:
        raise DecisionError(
            f"State must be one of: {', '.join(STATES)}. Got '{state}'.")
    data = _load(path)
    e = _entry(data, offer_key)
    old = e["state"]
    e["state"] = state
    if old != state:
        _log(e, "state", f"State: {old} -> {state}")
    _save(data, path)
    return state


def add_note(offer_key: str, text: str, kind: str = "note",
             path: str | Path | None = None) -> dict:
    """Add a freeform timestamped journal note. Returns the record."""
    text = (text or "").strip()
    if not text:
        raise DecisionError("Journal note cannot be empty.")
    data = _load(path)
    e = _entry(data, offer_key)
    rec = {"at": _now_iso(), "kind": kind, "text": text}
    e["journal"].append(rec)
    _save(data, path)
    return rec


def timeline(offer_key: str, path: str | Path | None = None) -> list[dict]:
    """All journal entries for an offer, oldest first."""
    entries = list(_entry(_load(path), offer_key)["journal"])
    return sorted(entries, key=lambda r: r.get("at", ""))


def render_timeline(offer_key: str, offer: dict | None = None,
                    path: str | Path | None = None) -> str:
    entries = timeline(offer_key, path)
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    lines = [f"Decision timeline: {title}", ""]
    if not entries:
        lines.append("(no journal entries yet)")
        return "\n".join(lines)
    for r in entries:
        lines.append(f"  [{r['at'][:16]}] ({r['kind']}) {r['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. regret-minimization exercise
# ---------------------------------------------------------------------------

def set_regret(offer_key: str, take: str, decline: str, ten_year: str = "",
               path: str | Path | None = None) -> dict:
    """Record the regret-minimization exercise: what you would regret about
    taking the offer, about declining it, and the 10-year projection."""
    take, decline = (take or "").strip(), (decline or "").strip()
    if not take or not decline:
        raise DecisionError(
            "The regret exercise needs both sides: what you would regret "
            "about taking the offer AND about declining it.")
    data = _load(path)
    e = _entry(data, offer_key)
    e["regret"] = {"take": take, "decline": decline,
                   "ten_year": (ten_year or "").strip(), "at": _now_iso()}
    _log(e, "regret", "Regret-minimization exercise recorded.")
    _save(data, path)
    return e["regret"]


def render_regret(offer_key: str, offer: dict | None = None,
                  path: str | Path | None = None) -> str:
    r = _entry(_load(path), offer_key)["regret"]
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    if not r:
        return (f"No regret exercise recorded for {title}. Run:\n"
                "  python -m candid decision regret-set --offer 1 "
                "--take \"...\" --decline \"...\" --ten-year \"...\"")
    lines = [f"Regret minimization: {title}", "",
             "If I TAKE this offer, I might regret:",
             f"  {r['take']}", "",
             "If I DECLINE this offer, I might regret:",
             f"  {r['decline']}"]
    if r.get("ten_year"):
        lines += ["", "10-year projection:", f"  {r['ten_year']}"]
    lines += ["", "Ask: which regret would be harder to live with?"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. reasons snapshot + revisit
# ---------------------------------------------------------------------------

def _split_reasons(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(";") if p.strip()]


def take_snapshot(offer_key: str, reasons: str,
                  path: str | Path | None = None) -> dict:
    """Freeze your top reasons at decision time (semicolon-separated)."""
    items = _split_reasons(reasons)
    if not items:
        raise DecisionError(
            "Give your top reasons separated by ';', e.g. "
            "--reasons \"team I trust; comp; remote\".")
    data = _load(path)
    e = _entry(data, offer_key)
    e["snapshot"] = {"reasons": items, "at": _now_iso(), "state": e["state"]}
    _log(e, "snapshot",
         "Reasons snapshot (" + e["state"] + "): " + "; ".join(items))
    _save(data, path)
    return e["snapshot"]


def revisit(offer_key: str, still_true: str = "", changed: str = "",
            note: str = "", path: str | Path | None = None) -> dict:
    """Revisit a reasons snapshot: mark which reasons still hold and which
    changed. Both are semicolon-separated. Returns the revisit record."""
    data = _load(path)
    e = _entry(data, offer_key)
    if not e.get("snapshot"):
        raise DecisionError(
            "No reasons snapshot to revisit. Take one first with: "
            "python -m candid decision snapshot --offer 1 "
            "--reasons \"reason one; reason two\"")
    rec = {"at": _now_iso(),
           "still_true": _split_reasons(still_true),
           "changed": _split_reasons(changed),
           "note": (note or "").strip()}
    e["revisits"].append(rec)
    summary = (f"Revisit: still true [{'; '.join(rec['still_true'])}]; "
               f"changed [{'; '.join(rec['changed'])}]"
               + (f"; note: {rec['note']}" if rec["note"] else ""))
    _log(e, "revisit", summary)
    _save(data, path)
    return rec


def render_revisit(offer_key: str, offer: dict | None = None,
                   path: str | Path | None = None) -> str:
    e = _entry(_load(path), offer_key)
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    snap = e.get("snapshot")
    if not snap:
        return (f"No reasons snapshot for {title} yet. Take one with:\n"
                "  python -m candid decision snapshot --offer 1 "
                "--reasons \"reason one; reason two\"")
    lines = [f"Revisit your reasons: {title}", "",
             f"Snapshot from {snap['at'][:10]} (state: {snap['state']}):"]
    for i, r in enumerate(snap["reasons"], 1):
        lines.append(f"  {i}. {r}")
    if e["revisits"]:
        lines.append("")
        lines.append("Revisits:")
        for rv in e["revisits"]:
            lines.append(f"  [{rv['at'][:16]}] still true: "
                         f"{'; '.join(rv['still_true']) or '(none marked)'}")
            lines.append(f"  {' ' * 18}changed: "
                         f"{'; '.join(rv['changed']) or '(none marked)'}")
            if rv.get("note"):
                lines.append(f"  {' ' * 18}note: {rv['note']}")
    else:
        lines += ["",
                  "No revisits yet. Ask yourself: which of these reasons is "
                  "still true, and what has changed since?",
                  "Record it with: python -m candid decision revisit "
                  f"--offer {offer_key} --still-true \"r1; r2\" "
                  "--changed \"r3\" --note \"...\""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. advice log
# ---------------------------------------------------------------------------

def add_advice(offer_key: str, advisor: str, stance: str, note: str = "",
               path: str | Path | None = None) -> dict:
    """Log advice from someone (mentor, partner, friend) about an offer."""
    advisor = (advisor or "").strip()
    stance = (stance or "").strip().lower()
    if not advisor:
        raise DecisionError("Name the advisor (--from).")
    if stance not in STANCES:
        raise DecisionError(
            f"Stance must be one of: {', '.join(STANCES)}. Got '{stance}'.")
    data = _load(path)
    e = _entry(data, offer_key)
    rec = {"from": advisor, "stance": stance, "note": (note or "").strip(),
           "at": _now_iso()}
    e["advice"].append(rec)
    _log(e, "advice",
         f"{advisor} is {stance} this offer"
         + (f": {rec['note'][:80]}" if rec["note"] else ""))
    _save(data, path)
    return rec


def advice_consensus(offer_key: str,
                     path: str | Path | None = None) -> dict:
    """Count of for/against/neutral advice for one offer."""
    items = list(_entry(_load(path), offer_key)["advice"])
    counts = {s: 0 for s in STANCES}
    for a in items:
        if a.get("stance") in counts:
            counts[a["stance"]] += 1
    return {"items": items, "counts": counts}


def render_advice(offer_key: str, offer: dict | None = None,
                  path: str | Path | None = None) -> str:
    c = advice_consensus(offer_key, path)
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    lines = [f"Advice log: {title}", "",
             "Consensus: " + ", ".join(f"{s}={c['counts'][s]}" for s in STANCES),
             ""]
    if not c["items"]:
        lines.append("(no advice recorded)")
    for a in c["items"]:
        note = f" -- {a['note']}" if a.get("note") else ""
        lines.append(f"  [{a['at'][:10]}] {a['from']}: {a['stance']}{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. confidence tracking
# ---------------------------------------------------------------------------

def set_confidence(offer_key: str, level: int, note: str = "",
                   path: str | Path | None = None) -> dict:
    """Log 1-10 confidence in your current leaning for an offer."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        raise DecisionError(f"Confidence must be 1-10, got '{level}'.")
    if not 1 <= level <= 10:
        raise DecisionError(f"Confidence must be 1-10, got {level}.")
    data = _load(path)
    e = _entry(data, offer_key)
    rec = {"at": _now_iso(), "level": level, "note": (note or "").strip()}
    e["confidence"].append(rec)
    _log(e, "confidence",
         f"Confidence {level}/10"
         + (f": {rec['note'][:80]}" if rec["note"] else ""))
    _save(data, path)
    return rec


def confidence_history(offer_key: str,
                       path: str | Path | None = None) -> list[dict]:
    return sorted(_entry(_load(path), offer_key)["confidence"],
                  key=lambda r: r.get("at", ""))


def render_confidence(offer_key: str, offer: dict | None = None,
                      path: str | Path | None = None) -> str:
    hist = confidence_history(offer_key, path)
    title = offer.get("company", f"offer #{offer_key}") if offer else f"offer #{offer_key}"
    lines = [f"Confidence over time: {title}", ""]
    if not hist:
        lines.append("(no confidence entries yet)")
        return "\n".join(lines)
    for r in hist:
        bar = "#" * r["level"] + "-" * (10 - r["level"])
        note = f" {r['note']}" if r.get("note") else ""
        lines.append(f"  [{r['at'][:16]}] [{bar}] {r['level']}/10{note}")
    if len(hist) >= 2:
        delta = hist[-1]["level"] - hist[0]["level"]
        trend = "rising" if delta > 0 else "falling" if delta < 0 else "flat"
        lines.append(f"\nTrend: {trend} ({hist[0]['level']} -> {hist[-1]['level']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. summary + journal export
# ---------------------------------------------------------------------------

def offer_label(offer_key: str, offer: dict | None = None) -> str:
    if offer and offer.get("company"):
        return f"{offer['company']} (#{offer_key})"
    return f"offer #{offer_key}"


def render_summary(offer_key: str, offer: dict | None = None,
                   today: date | None = None,
                   offer_path: str | Path | None = None,
                   path: str | Path | None = None) -> str:
    """One-screen view of everything in the journal for one offer."""
    data = _load(path)
    e = _entry(data, offer_key)
    if offer is None:
        offer = next((o for o in OFF.list_offers(offer_path)
                      if str(o.get("id")) == str(offer_key)), {})
    t = pro_con_totals(offer_key, path)
    st = deadline_status(e.get("deadline"), today)
    hist = confidence_history(offer_key, path)
    c = advice_consensus(offer_key, path)

    lines = [f"Decision journal: {offer_label(offer_key, offer)}",
             f"State: {e['state']}"]
    if st:
        when = (f"{abs(st['days_left'])}d ago" if st["days_left"] < 0
                else f"in {st['days_left']}d")
        lines.append(f"Deadline: {st['date']} ({when})"
                     + (" [exploding]" if st["exploding"] else "")
                     + f" -- {st['urgency'].upper()}")
    if hist:
        lines.append(f"Confidence: {hist[-1]['level']}/10 "
                     f"({len(hist)} entries)")
    lines += [
        f"Pros/cons: +{t['pro_total']} / -{t['con_total']} "
        f"(net {t['net']:+d}, {len(t['pros'])} pros, {len(t['cons'])} cons)",
        f"Criteria scored: {len(e['criteria_scores'])} | "
        f"Gut answers: {len(e['gut_answers'])} | "
        f"Advice: {c['counts']['for']} for / {c['counts']['against']} against / "
        f"{c['counts']['neutral']} neutral",
        f"Regret exercise: {'done' if e.get('regret') else 'not done'} | "
        f"Reasons snapshot: {'taken' if e.get('snapshot') else 'not taken'} "
        f"({len(e['revisits'])} revisits)",
        f"Journal entries: {len(e['journal'])}",
    ]
    recent = timeline(offer_key, path)[-3:]
    if recent:
        lines.append("")
        lines.append("Recent:")
        for r in recent:
            lines.append(f"  [{r['at'][:16]}] ({r['kind']}) {r['text']}")
    return "\n".join(lines)


def export_journal(offer_key: str | None = None,
                   out: str | Path | None = None,
                   today: date | None = None,
                   offer_path: str | Path | None = None,
                   path: str | Path | None = None) -> Path:
    """Write the full decision journal as markdown. Returns the saved path."""
    data = _load(path)
    weights = get_criteria_weights(path)
    d = _today(today)
    if out is None:
        dest = C.DATA_DIR / "decision_journals"
        dest.mkdir(parents=True, exist_ok=True)
        scope = f"offer_{offer_key}" if offer_key else "all_offers"
        out = dest / f"{d.isoformat()}_decision_journal_{scope}.md"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    keys = [str(offer_key)] if offer_key else sorted(_offers(data))
    if not keys:
        out.write_text("# Decision Journal\n\nNo journal entries yet.\n",
                       encoding="utf-8")
        return out

    lines = ["# Decision Journal", "",
             f"*Exported {d.isoformat()}*",
             ""]
    if weights:
        lines += ["## My decision criteria",
                  "",
                  "Weights: " + ", ".join(
                      f"{CRITERIA_LABELS.get(c, c)}={weights[c]:g}"
                      for c in sorted(weights)),
                  ""]
    for key in keys:
        e = _entry(data, key)
        offer = next((o for o in OFF.list_offers(offer_path)
                      if str(o.get("id")) == str(key)), {})
        label = offer_label(key, offer)
        lines += ["---", "", f"## {label}", ""]
        lines.append(f"**State:** {e['state']}")
        if offer.get("normalized_annual"):
            lines.append(f"**Normalized comp:** "
                         f"${offer['normalized_annual']:,.0f}/yr")
        st = deadline_status(e.get("deadline"), today)
        if st:
            lines.append(f"**Deadline:** {st['date']} "
                         f"({st['days_left']} days) "
                         f"{'[exploding] ' if st['exploding'] else ''}"
                         f"-- {st['urgency']}")
        if offer.get("notes"):
            lines.append(f"**Offer notes:** {offer['notes']}")
        lines.append("")

        t = pro_con_totals(key, path)
        lines += ["### Pros / cons",
                  f"(weighted +{t['pro_total']} / -{t['con_total']}, "
                  f"net {t['net']:+d})", ""]
        for i, p in enumerate(t["pros"], 1):
            lines.append(f"{i}. **[+{p['weight']}]** {p['text']}")
        for i, c_ in enumerate(t["cons"], 1):
            lines.append(f"{i}. **[-{c_['weight']}]** {c_['text']}")
        if not t["pros"] and not t["cons"]:
            lines.append("(none recorded)")
        lines.append("")

        if e["criteria_scores"]:
            lines.append("### Criteria scores")
            for crit in sorted(e["criteria_scores"]):
                lines.append(f"- {CRITERIA_LABELS.get(crit, crit)}: "
                             f"{e['criteria_scores'][crit]:g}/10")
            w = _weighted_score(e["criteria_scores"], weights) if weights else None
            if w is not None:
                lines.append(f"- **Weighted: {w:.2f}/10**")
            lines.append("")

        if e["gut_answers"]:
            lines.append("### Gut checks")
            for g in e["gut_answers"]:
                lines.append(f"- *{g['prompt']}*")
                lines.append(f"  > {g['answer']} ({g['at'][:10]})")
            lines.append("")

        if e.get("regret"):
            r = e["regret"]
            lines += ["### Regret minimization", "",
                      f"If I take it, I might regret: {r['take']}", "",
                      f"If I decline, I might regret: {r['decline']}"]
            if r.get("ten_year"):
                lines += ["", f"10-year projection: {r['ten_year']}"]
            lines.append("")

        if e.get("snapshot"):
            s = e["snapshot"]
            lines += ["### Reasons snapshot "
                      f"({s['at'][:10]}, state: {s['state']})", ""]
            for i, reason in enumerate(s["reasons"], 1):
                lines.append(f"{i}. {reason}")
            lines.append("")
        for rv in e["revisits"]:
            lines.append(f"**Revisit {rv['at'][:10]}:** still true: "
                         f"{'; '.join(rv['still_true']) or '(none)'}; "
                         f"changed: {'; '.join(rv['changed']) or '(none)'}"
                         + (f" -- {rv['note']}" if rv.get("note") else ""))
        if e["revisits"]:
            lines.append("")

        c = advice_consensus(key, path)
        if c["items"]:
            lines += ["### Advice",
                      "Consensus: " + ", ".join(
                          f"{s}={c['counts'][s]}" for s in STANCES), ""]
            for a in c["items"]:
                lines.append(f"- **{a['from']}** ({a['stance']}, "
                             f"{a['at'][:10]}): {a['note']}")
            lines.append("")

        hist = confidence_history(key, path)
        if hist:
            lines += ["### Confidence",
                      " <- ".join(
                          f"{r['at'][:10]}: {r['level']}/10" for r in hist),
                      ""]

        if e["journal"]:
            lines += ["### Timeline", ""]
            for r in sorted(e["journal"], key=lambda x: x.get("at", "")):
                lines.append(f"- [{r['at'][:16]}] *({r['kind']})* {r['text']}")
            lines.append("")
    lines.append("_Decide slowly, then commit fully._\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
