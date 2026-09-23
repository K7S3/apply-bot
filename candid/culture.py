"""Company culture decoder: merge culture signals into one profile card.

The sibling modules each own one evidence stream (stated values, JD
signals, stability/trajectory, interview process). This module is the
orchestrator: it builds a context dict for a company, pulls signals
from whichever siblings exist, dedupes and merges them into a single
culture profile card, and can diff two companies' cards.

Every sibling import is defensive — the siblings are developed in
parallel, so a missing module degrades to a coverage note, never a
crash. Nothing here invents culture data: with zero signals the card
says so explicitly instead of guessing.

CLI: ``python -m candid culture profile --company X`` (see also
compare, values, prep-questions, workstyle, benefits, flags, process,
stability, trajectory).
"""

from __future__ import annotations

import importlib
import json
import re
from datetime import date

from candid import config as C


class CultureError(Exception):
    """Raised for culture-decoder failures (bad input, unavailable extractor)."""


# ---------------------------------------------------------------------------
# defensive sibling imports
# ---------------------------------------------------------------------------

_SIBLINGS = ("culture_values", "culture_signals", "culture_stability",
             "culture_process")


def _sibling(name: str):
    """Import a sibling culture module, or None when not (yet) available.

    ImportError only — a module that exists but fails to import for
    another reason should surface loudly, not masquerade as missing.
    """
    try:
        return importlib.import_module(f"candid.{name}")
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# signal normalization
# ---------------------------------------------------------------------------

_SIGNAL_KEYS = ("signal", "value", "source", "as_of", "note")


def _as_signal(raw: dict) -> dict:
    """Normalize any sibling signal dict into the canonical shape."""
    if not isinstance(raw, dict):
        raw = {"signal": str(raw)}
    return {
        "signal": str(raw.get("signal") or "").strip(),
        "value": str(raw.get("value") or "").strip(),
        "source": str(raw.get("source") or "").strip(),
        "as_of": raw.get("as_of") or None,
        "note": str(raw.get("note") or "").strip(),
    }


def _dedupe_key(sig: dict) -> tuple[str, str]:
    """Near-identity key: same label + same value, ignoring case/whitespace."""
    return (re.sub(r"\s+", " ", sig["signal"]).strip().lower(),
            re.sub(r"\s+", " ", sig["value"]).strip().lower())


def _dedupe(signals: list[dict]) -> list[dict]:
    """Drop near-identical signals, keeping the first occurrence."""
    seen: set[tuple[str, str]] = set()
    out = []
    for sig in signals:
        sig = _as_signal(sig)
        if not sig["signal"]:
            continue
        key = _dedupe_key(sig)
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out


def _flatten(prefix: str, payload, source: str, as_of=None) -> list[dict]:
    """Turn an unknown-shaped JD section (dict/list/str) into signals."""
    sigs = []
    if isinstance(payload, dict):
        items = payload.items()
        for k, v in items:
            sigs.append(_as_signal({"signal": f"{prefix}: {k}",
                                    "value": v, "source": source,
                                    "as_of": as_of}))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            if isinstance(item, dict):
                label = (item.get("label") or item.get("name")
                         or item.get("flag") or "")
                if not label:
                    label = json.dumps(item, default=str)[:80]
                sigs.append(_as_signal({
                    "signal": f"{prefix}: {label}",
                    "value": item.get("detail") or item.get("value") or "",
                    "source": item.get("source") or source,
                    "as_of": item.get("as_of") or as_of,
                    "note": item.get("note") or "",
                }))
            elif str(item).strip():
                sigs.append(_as_signal({"signal": f"{prefix}: {item}",
                                        "value": "", "source": source,
                                        "as_of": as_of}))
    elif payload is not None and str(payload).strip():
        sigs.append(_as_signal({"signal": f"{prefix}: {payload}",
                                "value": "", "source": source,
                                "as_of": as_of}))
    return sigs


# ---------------------------------------------------------------------------
# context building
# ---------------------------------------------------------------------------

def _jobs_for_company(company: str) -> list[dict]:
    """Job dicts for the company, from the tracker + curated job metadata.

    The jobs store (candid_data/jobs.json) only keeps ``{last_run, seen}``,
    so the actual job dicts are rebuilt from tracker records joined with
    job_meta.json. Anything failing here degrades to [].
    """
    try:
        from candid import tracker as T
        from candid import jobs as J
    except Exception:
        return []
    try:
        apps = T.list_apps(company=company)
    except Exception:
        return []
    out = []
    for app in apps:
        meta = {}
        try:
            meta = J.get_job_meta(app.get("id")) or {}
        except Exception:
            pass
        out.append({
            "source": meta.get("source") or "tracker",
            "source_id": meta.get("source_id") or "",
            "title": app.get("role", ""),
            "company": app.get("company", ""),
            "location": app.get("location", ""),
            "url": meta.get("source_url") or app.get("jd_link") or "",
            "description": meta.get("jd_text") or "",
            "salary_text": "",
            "remote": False,
            "posted_at": app.get("date_added", ""),
            "status": app.get("status", ""),
        })
    return out


def _lca_for_company(company: str):
    """Best-effort pay data for the company from the salary database."""
    try:
        from candid import salary as S
        return S.lookup(company=company)
    except Exception:
        return None


def _prep_packs_for_company(company: str) -> list[str]:
    """Prep-pack files whose name mentions the company (best effort)."""
    try:
        d = C.PREP_PACKS_DIR
        if not d.exists():
            return []
        needle = company.strip().lower()
        return [str(p) for p in sorted(d.iterdir())
                if p.is_file() and needle and needle in p.name.lower()]
    except Exception:
        return []


def _tracked_for_company(company: str) -> list[dict]:
    try:
        from candid import tracker as T
        return T.list_apps(company=company)
    except Exception:
        return []


def build_ctx(company: str) -> dict:
    """Build the context dict the sibling modules consume.

    Keys: jobs (job dicts), datasets {warn, lca, jobs}, prep_bank,
    debriefs, tracker. Every source is best-effort; failures degrade to
    empty/None rather than raising.
    """
    jobs = _jobs_for_company(company)
    return {
        "jobs": jobs,
        # No WARN layoff feed exists in this repo yet; the slot is kept
        # so culture_stability can consume it when one lands.
        "datasets": {"warn": None,
                     "lca": _lca_for_company(company),
                     "jobs": jobs},
        "prep_bank": _prep_packs_for_company(company),
        "debriefs": [],
        "tracker": _tracked_for_company(company),
    }


# ---------------------------------------------------------------------------
# per-sibling gatherers -> (signals, coverage_note)
# ---------------------------------------------------------------------------

def _gather_values(company: str, ctx: dict) -> tuple[list[dict], str | None]:
    mod = _sibling("culture_values")
    if mod is None:
        return [], "culture_values module not available"
    try:
        vals = mod.load_values(company) or []
    except Exception as exc:
        return [], f"culture_values.load_values failed: {exc}"
    sigs = []
    for v in vals:
        if not isinstance(v, dict):
            continue
        name = v.get("value") or v.get("name") or ""
        if not str(name).strip():
            continue
        sigs.append(_as_signal({
            "signal": f"value: {name}",
            "value": v.get("quote") or "",
            "source": v.get("source") or "user-provided",
            "as_of": v.get("as_of"),
            "note": "stated company value",
        }))
    return sigs, None


def _gather_jd(company: str, ctx: dict) -> tuple[list[dict], str | None]:
    mod = _sibling("culture_signals")
    if mod is None:
        return [], "culture_signals module not available"
    try:
        res = mod.company_jd_signals(company, ctx.get("jobs", [])) or {}
    except Exception as exc:
        return [], f"culture_signals.company_jd_signals failed: {exc}"
    if not isinstance(res, dict):
        return [], "culture_signals.company_jd_signals returned no data"
    src = ", ".join(s for s in (res.get("sources") or []) if s) or "job descriptions"
    sigs: list[dict] = []
    if res.get("job_count"):
        sigs.append(_as_signal({
            "signal": "jd sample size",
            "value": res["job_count"],
            "source": src,
            "note": f"culture signals drawn from {res['job_count']} posting(s)",
        }))
    sigs.extend(_flatten("workstyle", res.get("workstyle"), src))
    sigs.extend(_flatten("benefit", res.get("benefits"), src))
    sigs.extend(_flatten("flag", res.get("flags"), src))
    return sigs, None


def _gather_stability(company: str, ctx: dict) -> tuple[list[dict], str | None]:
    mod = _sibling("culture_stability")
    if mod is None:
        return [], "culture_stability module not available"
    datasets = ctx.get("datasets", {}) or {}
    sigs: list[dict] = []
    for fn_name in ("stability", "trajectory"):
        fn = getattr(mod, fn_name, None)
        if fn is None:
            continue
        try:
            rows = fn(company, datasets) or []
        except Exception as exc:
            return sigs, f"culture_stability.{fn_name} failed: {exc}"
        for row in rows:
            if isinstance(row, dict):
                sigs.append(_as_signal(row))
    return sigs, None


def _gather_process(company: str, ctx: dict) -> tuple[list[dict], str | None]:
    mod = _sibling("culture_process")
    if mod is None:
        return [], "culture_process module not available"
    try:
        prof = mod.process_profile(company, ctx) or {}
    except Exception as exc:
        return [], f"culture_process.process_profile failed: {exc}"
    if not isinstance(prof, dict):
        return [], "culture_process.process_profile returned no data"
    sigs = []
    for st in prof.get("stages") or []:
        if not isinstance(st, dict):
            continue
        stage = str(st.get("stage") or "unknown stage").strip()
        quotes, sources = [], []
        for ev in st.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("quote"):
                quotes.append(str(ev["quote"]).strip())
            if ev.get("source"):
                sources.append(str(ev["source"]).strip())
        sigs.append(_as_signal({
            "signal": f"interview process: {stage}",
            "value": " | ".join(quotes),
            "source": sources[0] if sources else "interview process data",
            "note": (f"{len(quotes)} evidence quote(s)"
                     if quotes else "stage reported with no quotes"),
        }))
    return sigs, None


_GATHERERS = (_gather_values, _gather_jd, _gather_stability, _gather_process)


# ---------------------------------------------------------------------------
# profile card + compare
# ---------------------------------------------------------------------------

def profile_card(company: str, ctx: dict | None = None) -> dict:
    """Merge every sibling's signals into one culture profile card.

    Returns {"company", "generated_at", "signals", "coverage",
    "coverage_notes"?}. ``coverage`` maps each signal source to its
    signal count. With zero signals the card carries coverage {} and a
    top-level "note": "no verified culture data for <company>" — no
    data is ever invented to fill the gap.
    """
    company = (company or "").strip()
    if not company:
        raise CultureError("profile_card needs a company name")
    if ctx is None:
        ctx = build_ctx(company)
    signals: list[dict] = []
    coverage_notes: list[str] = []
    for gather in _GATHERERS:
        sigs, note = gather(company, ctx)
        signals.extend(sigs)
        if note:
            coverage_notes.append(note)
    signals = _dedupe(signals)
    coverage: dict[str, int] = {}
    for sig in signals:
        src = sig["source"] or "unknown"
        coverage[src] = coverage.get(src, 0) + 1
    card: dict = {
        "company": company,
        "generated_at": date.today().isoformat(),
        "signals": signals,
        "coverage": coverage,
    }
    if coverage_notes:
        card["coverage_notes"] = coverage_notes
    if not signals:
        card["coverage"] = {}
        card["note"] = f"no verified culture data for {company}"
    return card


def compare(company_a: str, company_b: str, ctx: dict | None = None) -> dict:
    """Diff two companies' culture cards at the signal-label level.

    Returns {"a", "b", "shared_sources", "only_in_a", "only_in_b"}.
    ``shared_sources`` is the intersection of the cards' coverage
    sources; ``only_in_a``/``only_in_b`` are signal labels present on
    one card but not the other.
    """
    a = profile_card(company_a, ctx)
    b = profile_card(company_b, ctx)
    labels_a = {s["signal"] for s in a["signals"]}
    labels_b = {s["signal"] for s in b["signals"]}
    return {
        "a": a,
        "b": b,
        "shared_sources": sorted(set(a["coverage"]) & set(b["coverage"])),
        "only_in_a": sorted(labels_a - labels_b),
        "only_in_b": sorted(labels_b - labels_a),
    }


# ---------------------------------------------------------------------------
# values extraction / storage (culture_values sibling + local fallback)
# ---------------------------------------------------------------------------

def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.strip().lower()).strip("-") or "unknown"


def values_path(company: str):
    """Path of this module's local values store for a company."""
    return C.CULTURE_DIR / f"{_slug(company)}_values.json"


def _merge_value(merged: list[dict], seen: set[str], raw) -> None:
    if not isinstance(raw, dict):
        return
    name = str(raw.get("value") or raw.get("name") or "").strip()
    if not name or name.lower() in seen:
        return
    seen.add(name.lower())
    merged.append({
        "value": name,
        "quote": str(raw.get("quote") or ""),
        "source": str(raw.get("source") or "user-provided"),
    })


def extract_and_store_values(company: str, text: str,
                             origin: str = "user-provided text") -> list[dict]:
    """Extract values from text via the sibling, then persist them locally.

    Persists to CULTURE_DIR (created lazily). Returns the extracted
    value dicts. Raises CultureError when the sibling is unavailable.
    """
    company = (company or "").strip()
    if not company:
        raise CultureError("extract_and_store_values needs a company name")
    if not (text or "").strip():
        raise CultureError("no text to extract values from")
    mod = _sibling("culture_values")
    if mod is None:
        raise CultureError("culture_values module not available; cannot extract values")
    try:
        vals = mod.extract_values(text, company, origin=origin) or []
    except Exception as exc:
        raise CultureError(f"culture_values.extract_values failed: {exc}") from exc
    vals = [v for v in vals if isinstance(v, dict)]
    path = values_path(company)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "company": company,
        "extracted_at": date.today().isoformat(),
        "origin": origin,
        "values": vals,
    }, indent=2), encoding="utf-8")
    return vals


def stored_values(company: str) -> list[dict]:
    """Stored values for a company: sibling store first, local file fallback.

    Merges both (deduped by value name) so extraction via the CLI and
    whatever the sibling persists on its own never lose each other.
    """
    merged: list[dict] = []
    seen: set[str] = set()
    mod = _sibling("culture_values")
    if mod is not None:
        try:
            for v in mod.load_values(company) or []:
                _merge_value(merged, seen, v)
        except Exception:
            pass
    path = values_path(company)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            vals = data.get("values", data) if isinstance(data, dict) else data
            for v in vals or []:
                _merge_value(merged, seen, v)
        except (json.JSONDecodeError, OSError):
            pass
    return merged


def prep_questions_for(company: str) -> list[dict]:
    """Interview questions targeting the company's stored values."""
    mod = _sibling("culture_values")
    if mod is None:
        raise CultureError("culture_values module not available; cannot build questions")
    try:
        return mod.values_to_questions(stored_values(company)) or []
    except Exception as exc:
        raise CultureError(f"culture_values.values_to_questions failed: {exc}") from exc


def jd_signals_for(company: str, ctx: dict | None = None) -> dict | None:
    """Raw JD-signals dict from the sibling, or None when unavailable."""
    mod = _sibling("culture_signals")
    if mod is None:
        return None
    if ctx is None:
        ctx = build_ctx(company)
    try:
        return mod.company_jd_signals(company, ctx.get("jobs", []))
    except Exception:
        return None


def process_profile_for(company: str, ctx: dict | None = None) -> dict | None:
    """Raw interview-process profile from the sibling, or None."""
    mod = _sibling("culture_process")
    if mod is None:
        return None
    if ctx is None:
        ctx = build_ctx(company)
    try:
        return mod.process_profile(company, ctx)
    except Exception:
        return None


def stability_signals_for(company: str, kind: str = "stability",
                          ctx: dict | None = None) -> tuple[list[dict], str | None]:
    """(signals, note) for one stability kind: 'stability' or 'trajectory'."""
    mod = _sibling("culture_stability")
    if mod is None:
        return [], "culture_stability module not available"
    if kind not in ("stability", "trajectory"):
        raise CultureError(f"unknown stability kind {kind!r}")
    if ctx is None:
        ctx = build_ctx(company)
    fn = getattr(mod, kind, None)
    if fn is None:
        return [], f"culture_stability.{kind} not available"
    try:
        rows = fn(company, ctx.get("datasets", {}) or {}) or []
    except Exception as exc:
        return [], f"culture_stability.{kind} failed: {exc}"
    return [_as_signal(r) for r in rows if isinstance(r, dict)], None


# ---------------------------------------------------------------------------
# human-readable rendering (plain text: no emojis, no em dashes)
# ---------------------------------------------------------------------------

def render_card(card: dict) -> str:
    """Render a profile card as plain text."""
    lines = [f"Culture profile: {card.get('company', '')}",
             f"Generated: {card.get('generated_at', '')}", ""]
    if card.get("note"):
        lines.append(card["note"])
        for note in card.get("coverage_notes", []):
            lines.append(f"note: {note}")
        return "\n".join(lines)
    sigs = card.get("signals", [])
    lines.append(f"Signals ({len(sigs)}):")
    for s in sigs:
        lines.append(f"  [{s.get('source') or 'unknown'}] {s.get('signal')}")
        if s.get("value"):
            lines.append(f"      {s['value']}")
        bits = []
        if s.get("as_of"):
            bits.append(f"as of {s['as_of']}")
        if s.get("note"):
            bits.append(s["note"])
        if bits:
            lines.append("      (" + "; ".join(bits) + ")")
    lines.append("")
    lines.append("Coverage:")
    for src, n in sorted(card.get("coverage", {}).items()):
        lines.append(f"  {src}: {n}")
    for note in card.get("coverage_notes", []):
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def render_compare(result: dict) -> str:
    """Render a compare() result as plain text."""
    a, b = result["a"], result["b"]
    lines = [f"Culture compare: {a.get('company', '')} vs {b.get('company', '')}", ""]
    shared = result.get("shared_sources", [])
    lines.append(f"Shared sources ({len(shared)}): "
                 + (", ".join(shared) if shared else "none"))
    lines.append("")
    for key, company in (("only_in_a", a.get("company", "")),
                         ("only_in_b", b.get("company", ""))):
        labels = result.get(key, [])
        lines.append(f"Only in {company} ({len(labels)}):")
        for label in labels:
            lines.append(f"  - {label}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_values(values: list[dict], company: str) -> str:
    """Render stored values as plain text."""
    if not values:
        return (f"No stored values for {company}.\n"
                f"Add some: python -m candid culture values --company \"{company}\" "
                f"--text \"...\"")
    lines = [f"Stored values for {company} ({len(values)}):"]
    for v in values:
        lines.append(f"  - {v.get('value', '')} [{v.get('source', '')}]")
        if v.get("quote"):
            lines.append(f"      \"{v['quote']}\"")
    return "\n".join(lines)


def render_questions(questions: list[dict], company: str) -> str:
    """Render value-targeted interview questions as plain text."""
    if not questions:
        return (f"No prep questions for {company}: store values first with "
                f"`python -m candid culture values --company \"{company}\" --text \"...\"`.")
    lines = [f"Interview questions targeting {company}'s values ({len(questions)}):"]
    for i, q in enumerate(questions, 1):
        target = q.get("targets_value") or q.get("value") or ""
        src = f" [{q.get('source')}]" if q.get("source") else ""
        suffix = f" (targets: {target})" if target else ""
        lines.append(f"  {i}. {q.get('question', '')}{suffix}{src}")
    return "\n".join(lines)


def render_signals(signals: list[dict], title: str) -> str:
    """Render a bare signal list as plain text."""
    if not signals:
        return f"{title}: no signals."
    lines = [f"{title} ({len(signals)}):"]
    for s in signals:
        s = _as_signal(s)
        lines.append(f"  - [{s['source'] or 'unknown'}] {s['signal']}"
                     + (f": {s['value']}" if s["value"] else ""))
        if s["note"]:
            lines.append(f"      ({s['note']})")
    return "\n".join(lines)


def render_jd_section(res: dict, section: str) -> str:
    """Render one JD-signals section (workstyle/benefits/flags) as text."""
    company = res.get("company", "")
    payload = res.get({"workstyle": "workstyle", "benefits": "benefits",
                       "flags": "flags"}.get(section, section))
    sigs = _flatten(section.rstrip("s") if section != "benefits" else "benefit",
                    payload, ", ".join(res.get("sources") or []) or "job descriptions")
    title = f"{company}: {section} (from {res.get('job_count', 0)} posting(s))"
    return render_signals(sigs, title)


def render_process(prof: dict | None, company: str) -> str:
    """Render an interview-process profile as plain text."""
    if not prof:
        return (f"No interview process data for {company} "
                f"(culture_process module not available).")
    lines = [f"Interview process: {prof.get('company', company)}"]
    stages = prof.get("stages") or []
    if not stages:
        lines.append("  no stages recorded")
    for st in stages:
        if not isinstance(st, dict):
            continue
        lines.append(f"  Stage: {st.get('stage', '')}")
        for ev in st.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            quote = f"\"{ev.get('quote', '')}\"" if ev.get("quote") else ""
            src = f" [{ev.get('source')}]" if ev.get("source") else ""
            if quote or src:
                lines.append(f"    - {quote}{src}")
    if prof.get("note"):
        lines.append(f"note: {prof['note']}")
    return "\n".join(lines)
