"""Pre-interview confidence routine: thin dispatcher for ritual_* subcommands.

Workers A-D own logistics, timeline, materials, dossier, warmup, techcheck,
calm, countdown; worker E owns interviewers and cooldown. Every handler
here imports its sibling module lazily (function level) so missing siblings
never break import of this module or the CLI: a missing sibling raises a
clean RitualError at dispatch time.
"""

from __future__ import annotations

import importlib
import os
import re


class RitualError(Exception):
    """Expected ritual failure: reported cleanly, no traceback."""


#: All ten ritual subcommands, kept in sync with __main__.py's SUBCOMMANDS.
SUBCOMMANDS = [
    "logistics", "timeline", "materials", "dossier", "warmup",
    "techcheck", "calm", "countdown", "interviewers", "cooldown",
]


def _import_sibling(name: str):
    """Lazy-import candid.ritual_<name>; friendly RitualError if absent."""
    try:
        return importlib.import_module(f"candid.ritual_{name}")
    except ImportError:
        raise RitualError(
            f"ritual subcommand '{name}' is not available in this checkout "
            f"(candid.ritual_{name} is missing)."
        )


def _ritual_id(company: str, role: str) -> str:
    """Stable, filesystem-safe id shared by all ritual features."""
    return re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-")


def _rituals_dir():
    """Rituals data dir, resolved at call time so CANDID_DATA_DIR overrides
    (including per-test temp dirs) always take effect."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        from pathlib import Path
        return Path(override).expanduser() / "rituals"
    from candid import config
    return config.DATA_DIR / "rituals"


def cmd_logistics(a):
    m = _import_sibling("logistics")
    if getattr(a, "check", None) is not None:
        if not getattr(a, "ritual_id", None):
            raise RitualError("--ritual-id is required with --check.")
        data = m.check_item(a.ritual_id, a.check, done=not a.uncheck)
        print(m.render_logistics(data))
        return 0
    for flag in ("date", "round_type"):
        if not getattr(a, flag, None):
            raise RitualError(f"--{flag.replace('_', '-')} is required.")
    data = m.build_logistics(a.round_type, a.company, a.role, a.date,
                             ritual_id=a.ritual_id)
    path = m.save_logistics(data)
    print(m.render_logistics(data))
    print(f"\nSaved to {path}")
    return 0


def cmd_timeline(a):
    m = _import_sibling("timeline")
    start = m.parse_start(a.start, a.timezone)
    events = m.build_timeline(start, a.round_type, wake=a.wake,
                              interview_minutes=a.duration)
    if a.json:
        print(m.timeline_json(events))
    else:
        header = (f"INTERVIEW DAY TIMELINE - {start.strftime('%Y-%m-%d %H:%M')}"
                  + (f" {start.tzinfo}" if start.tzinfo else ""))
        print(m.render_timeline(events, title=header))
    return 0


def cmd_materials(a):
    m = _import_sibling("materials")
    if getattr(a, "check", None) is not None:
        rid = a.ritual_id or m.new_ritual_id(a.company, a.role)
        data = m.uncheck_item(rid, a.check) if a.uncheck else m.check_item(rid, a.check)
        print(m.render_materials(data))
        return 0
    data = m.build_materials(a.company, a.role, ritual_id=a.ritual_id)
    print(m.render_materials(data))
    return 0


def cmd_dossier(a):
    m = _import_sibling("dossier")
    print(m.build_dossier(a.company, a.role))
    return 0


def cmd_warmup(a):
    m = _import_sibling("warmup")
    m.run_warmup(minutes=a.minutes, seed=a.seed, no_wait=a.no_wait)
    return 0


def cmd_techcheck(a):
    m = _import_sibling("techcheck")
    items = m.run_techcheck(a.round_type, check_network=not a.no_net)
    print(f"Tech check for a {a.round_type} round:\n")
    m.print_checklist(items)
    return 0


def cmd_calm(a):
    m = _import_sibling("calm")
    m.run_calm(cycles=a.cycles, no_wait=a.no_wait)
    return 0


def cmd_countdown(a):
    m = _import_sibling("countdown")
    result = m.countdown_result(m.parse_start(a.start))
    if a.json:
        import json
        print(json.dumps(result, indent=2))
    else:
        print(m.format_checklist_text(result))
    return 0


def cmd_interviewers(a):
    return _import_sibling("interviewers").run(a)


def cmd_cooldown(a):
    return _import_sibling("cooldown").run(a)


_HANDLERS = {
    "logistics": cmd_logistics,
    "timeline": cmd_timeline,
    "materials": cmd_materials,
    "dossier": cmd_dossier,
    "warmup": cmd_warmup,
    "techcheck": cmd_techcheck,
    "calm": cmd_calm,
    "countdown": cmd_countdown,
    "interviewers": cmd_interviewers,
    "cooldown": cmd_cooldown,
}


def run(a) -> int:
    """Dispatch `python -m candid ritual <subcommand>`; returns exit code."""
    handler = _HANDLERS.get(getattr(a, "what", None))
    if handler is None:
        raise RitualError(
            f"Unknown ritual subcommand. Choose from: {', '.join(SUBCOMMANDS)}."
        )
    return handler(a) or 0
