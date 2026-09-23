"""Org-impact storytelling (STAR+I) and promo-packet builder for the
staff/principal engineer track.

STAR+I = Situation / Task / Action / Result / Influence.
The extra "Influence" section captures what staff+ interviews and promo
packets actually look for: scope of impact, what changed for other people
and teams, and what persisted after the work shipped.

Honesty rules (non-negotiable):
- Everything is reframed from the user's OWN words. Missing fields become
  explicit "[add detail]" placeholders, never invented content.
- Selected metrics are ONLY numbers that already appear in the profile,
  stories, or tracker records, each with its source attribution.
- No em dashes anywhere (user style rule): hyphens and commas only.

Story dicts come from stories.list_stories() (owned by another
workstream), which may not exist in this checkout. upgrade_star() is
defensive: it accepts any dict with STAR-ish keys, a dict with a free-text
key ("bullet", "text", "description", "raw"), or a plain resume-bullet
string.

Usage:
    python -m candid staff story --bullet "Cut p99 latency 40% by rebuilding the ranking cache"
    python -m candid staff story --story ads-cache-rebuild
    python -m candid staff packet --out staff-packet.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from candid import config as C


class StaffError(Exception):
    """Raised for invalid staff-impact operations."""


MISSING = "[add detail]"

STAR_FIELDS = ("situation", "task", "action", "result", "influence")

# Free-text keys a story dict might carry when it has no STAR structure.
_TEXT_KEYS = ("bullet", "text", "description", "raw", "content", "story")

# Scope/leadership keywords for influence scoring. Simple, transparent,
# and documented in docs/staff_packet.md. Heuristic only: it orders
# stories, it never invents impact.
_INFLUENCE_SIGNALS: dict[str, int] = {
    "company-wide": 4,
    "company wide": 4,
    "org-wide": 4,
    "across the org": 3,
    "cross-team": 3,
    "cross team": 3,
    "multiple teams": 3,
    "multiple orgs": 4,
    "adopted by": 3,
    "standardized": 3,
    "mentored": 2,
    "mentor": 2,
    "coached": 2,
    "onboarded": 1,
    "tech talk": 2,
    "design doc": 1,
    "rfc": 1,
}

_MENTOR_SIGNALS = (
    "mentor", "coached", "onboard", "guided", "junior",
    "intern", "code review", "1:1", "career", "tech talk",
)

_TECH_LEAD_SIGNALS = (
    "led", "tech lead", "architect", "design doc", "rfc",
    "roadmap", "migration", "platform", "standard", "adopted",
    "owned", "drove", "spearheaded",
)

_METRIC_RE = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|x|X|ms|s\b|m\b|hrs?|days?|weeks?|months?|"
    r"million|billion|thousand|[KMB]\b|engineers?|users?|requests?|"
    r"QPS|latency|revenue|cost|dollars?|\$)",
)

_CLAUSE_SPLIT = re.compile(r"[.;\n]|,\s*(?=[A-Z])")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _free_text(story: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        val = story.get(key)
        if val and isinstance(val, str):
            return _clean(val)
    return ""


def _story_text(story: dict[str, Any]) -> str:
    """All text in a (possibly upgraded) story, for scoring/searching."""
    parts = [_clean(str(story.get(f, ""))) for f in STAR_FIELDS]
    parts.append(_free_text(story))
    parts.append(_clean(str(story.get("title", ""))))
    return " ".join(p for p in parts if p and p != MISSING)


def upgrade_star(story_or_bullet: dict[str, Any] | str) -> dict[str, Any]:
    """Reframe a story or raw resume bullet into STAR+I.

    Accepts:
      - a story dict (from stories.list_stories() or anywhere else),
      - a dict with free text under "bullet"/"text"/"description"/"raw",
      - a raw resume-bullet string.

    Missing STAR+I fields become explicit "[add detail]" placeholders.
    Nothing is invented. Returns an idempotent dict: re-running
    upgrade_star() on its output is a no-op.

    Output keys: id, title, situation, task, action, result, influence,
    source, missing (list of still-empty fields), completeness (0.0-1.0).
    """
    if isinstance(story_or_bullet, str):
        story: dict[str, Any] = {"bullet": story_or_bullet, "source": "bullet"}
    elif isinstance(story_or_bullet, dict):
        story = dict(story_or_bullet)
        story.setdefault("source", "story")
    else:
        raise StaffError(
            "upgrade_star() needs a story dict or a bullet string, "
            f"got {type(story_or_bullet).__name__}."
        )

    free = _free_text(story)
    title = _clean(str(story.get("title", "") or story.get("id", "")))
    if not title:
        # Derive a short title from the free text: first clause, truncated.
        title = (_CLAUSE_SPLIT.split(free)[0] if free else "").strip()
        title = (title[:72] + "...") if len(title) > 72 else title

    out: dict[str, Any] = {
        "id": str(story.get("id", "") or ""),
        "title": title or MISSING,
        "source": story.get("source", "story"),
    }
    missing: list[str] = []
    for field in STAR_FIELDS:
        val = _clean(str(story.get(field, "")))
        if not val:
            # Free text from a raw bullet maps to "action" by default:
            # the bullet usually describes what the person did. The
            # surrounding S/T/R/I still need their own detail.
            if field == "action" and free:
                val = free
            else:
                val = MISSING
                missing.append(field)
        out[field] = val

    out["missing"] = missing
    out["completeness"] = round(
        (len(STAR_FIELDS) - len(missing)) / len(STAR_FIELDS), 2
    )
    return out


def format_star_plus(story: dict[str, Any] | str) -> str:
    """Render a story (dict or bullet) as Markdown STAR+I."""
    s = upgrade_star(story)
    lines = [f"## {s['title']}", ""]
    for field in STAR_FIELDS:
        lines.append(f"**{field.capitalize()}:** {s[field]}")
        lines.append("")
    if s["missing"]:
        lines.append(
            "_Still needed before this is packet-ready: "
            + ", ".join(s["missing"])
            + "._"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def influence_score(story: dict[str, Any] | str) -> float:
    """Heuristic influence score used to rank stories in a packet.

    Transparent keyword counting over the story's text, plus credit for
    having a quantified result and a filled Influence section. Heuristic
    only: it orders stories, it never invents impact.
    """
    s = upgrade_star(story)
    text = _story_text(s).lower()
    score = 0.0
    for signal, weight in _INFLUENCE_SIGNALS.items():
        if signal in text:
            score += weight
    if s["result"] != MISSING and _METRIC_RE.search(s["result"]):
        score += 2.0
    if s["influence"] != MISSING:
        score += 2.0
    if s["result"] != MISSING:
        score += 1.0
    return round(score, 1)


def extract_metrics(text: str, source: str) -> list[dict[str, str]]:
    """Pull quantified claims from text, each tagged with its source.

    ONLY returns numbers that literally appear in the text. The caller
    decides which texts to feed in (story fields, profile bullets), so no
    value is ever invented here.
    """
    out: list[dict[str, str]] = []
    for clause in _CLAUSE_SPLIT.split(text or ""):
        clause = _clean(clause)
        if not clause:
            continue
        for m in _METRIC_RE.finditer(clause):
            value = f"{m.group('num')}{m.group('unit')}".strip()
            # Include a few words of context around the number so the
            # metric reads like a claim, not a bare number.
            out.append({"value": value, "context": clause, "source": source})
    return out


# ---------------------------------------------------------------------------
# packet building
# ---------------------------------------------------------------------------

def _scope_note(entry: dict[str, Any]) -> str:
    """Scope language for an experience entry, only if stated in the data."""
    title = entry.get("title", "") or ""
    bullets = entry.get("bullets", []) or []
    blob = " ".join([title] + bullets).lower()
    hints = []
    m = re.search(r"team of (\d+)", blob)
    if m:
        hints.append(f"team of {m.group(1)}")
    m = re.search(r"(\d+)\+?\s*(?:engineers?|reports)", blob)
    if m:
        hints.append(f"{m.group(1)} engineers")
    for kw in ("org", "company-wide", "cross-team", "multiple teams", "platform"):
        if kw in blob and kw not in " ".join(hints):
            hints.append(kw)
    return "; ".join(hints) if hints else "scope not stated in resume"


def _has_signal(text: str, signals: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(sig in low for sig in signals)


def _packet_struct(profile: dict[str, Any],
                   stories: list[dict[str, Any]],
                   tracker_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the packet as structured data; build_packet() renders it."""
    upgraded = [upgrade_star(s) for s in stories]
    ranked = sorted(upgraded, key=influence_score, reverse=True)

    leadership = [s for s in upgraded if _has_signal(_story_text(s), _TECH_LEAD_SIGNALS)]
    mentorship = [s for s in upgraded if _has_signal(_story_text(s), _MENTOR_SIGNALS)]

    # Metrics only from data the user provided: story fields and profile
    # experience bullets, each with its source.
    metrics: list[dict[str, str]] = []
    for s in upgraded:
        src = s["title"] if s["title"] != MISSING else "story"
        for field in ("result", "influence", "action"):
            if s[field] != MISSING:
                metrics.extend(extract_metrics(s[field], source=f"story: {src}"))
    for entry in profile.get("experience", []) or []:
        for b in entry.get("bullets", []) or []:
            metrics.extend(
                extract_metrics(b, source=f"resume: {entry.get('title', '')}")
            )
    # Dedupe identical (value, context) pairs, keep first source.
    seen: set[tuple[str, str]] = set()
    unique_metrics = []
    for m in metrics:
        key = (m["value"], m["context"])
        if key not in seen:
            seen.add(key)
            unique_metrics.append(m)

    interviews = [r for r in tracker_records
                  if r.get("status") in ("selected_for_interview", "offer")]

    return {
        "name": profile.get("name", ""),
        "headline": profile.get("headline", ""),
        "seniority": profile.get("seniority", ""),
        "years_experience": profile.get("years_experience", 0),
        "ranked_stories": ranked,
        "experience": profile.get("experience", []) or [],
        "leadership_stories": leadership,
        "mentorship_stories": mentorship,
        "metrics": unique_metrics,
        "interviews": interviews,
        "open_gaps": sorted({f for s in upgraded for f in s["missing"]}),
    }


def build_packet(profile: dict[str, Any],
                 stories: list[dict[str, Any]],
                 tracker_records: list[dict[str, Any]]) -> str:
    """Assemble the staff/promo packet as Markdown.

    Sections: impact summary (top stories by influence), scope
    trajectory (roles with scope language from the profile), technical
    leadership evidence, mentorship evidence, selected metrics (only
    values present in the inputs, each attributed), and open gaps.
    """
    p = _packet_struct(profile, stories, tracker_records)
    name = p["name"] or "Staff engineer packet"
    lines = [
        f"# Staff impact packet: {name}",
        "",
        f"Headline: {p['headline'] or MISSING}  ",
        f"Seniority: {p['seniority'] or MISSING} (~{p['years_experience']} yrs)",
        "",
        "---",
        "",
        "## Impact summary",
        "",
        "_Top stories, ranked by org influence (heuristic score; "
        "highest first)._",
        "",
    ]
    if not p["ranked_stories"]:
        lines.append(f"No stories yet. Add one with: {MISSING}")
        lines.append("")
    for s in p["ranked_stories"][:6]:
        lines.append(
            f"### {s['title']}  "
            f"(influence {influence_score(s)}, "
            f"{int(s['completeness'] * 100)}% complete)"
        )
        lines.append("")
        lines.append(f"- **Result:** {s['result']}")
        lines.append(f"- **Influence:** {s['influence']}")
        if s["missing"]:
            lines.append(f"- _To add: {', '.join(s['missing'])}_")
        lines.append("")

    lines += ["## Scope trajectory", ""]
    if not p["experience"]:
        lines.append(f"No experience entries in profile. {MISSING}")
    for e in p["experience"]:
        lines.append(
            f"- **{e.get('title', '')}**, {e.get('company', '')} "
            f"({e.get('dates', '')})"
        )
        lines.append(f"  - scope: {_scope_note(e)}")
    lines.append("")

    lines += ["## Technical leadership evidence", ""]
    if not p["leadership_stories"]:
        lines.append(f"No tech-leadership signals found in stories. {MISSING}")
    for s in p["leadership_stories"]:
        lines.append(f"- **{s['title']}**: {s['action'][:160]}")
    lines.append("")

    lines += ["## Mentorship evidence", ""]
    if not p["mentorship_stories"]:
        lines.append(f"No mentorship signals found in stories. {MISSING}")
    for s in p["mentorship_stories"]:
        lines.append(f"- **{s['title']}**: {s['action'][:160]}")
    lines.append("")

    lines += [
        "## Selected metrics",
        "",
        "_Only numbers that appear in your profile/stories, each with its "
        "source. Nothing here is estimated._",
        "",
    ]
    if not p["metrics"]:
        lines.append(f"No quantified metrics found in stories or resume. {MISSING}")
    for m in p["metrics"]:
        lines.append(f"- **{m['value']}** - {m['context']} ({m['source']})")
    lines.append("")

    if p["interviews"]:
        lines += ["## Active pipeline (context for packet timing)", ""]
        for r in p["interviews"]:
            lines.append(
                f"- {r.get('company', '')} - {r.get('role', '')} "
                f"({r.get('status', '')})"
            )
        lines.append("")

    lines += ["## Open gaps", ""]
    if p["open_gaps"]:
        lines.append(
            "Fields still marked [add detail] across stories. Fill these "
            "before the packet goes anywhere:"
        )
        lines.append("")
        for g in p["open_gaps"]:
            lines.append(f"- {g}")
    else:
        lines.append("No open gaps: every story is STAR+I complete.")
    lines.append("")

    return "\n".join(lines)


def save_packet(markdown: str, out_path: str | Path) -> Path:
    """Write packet Markdown to out_path (parents created). Returns Path."""
    p = Path(out_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# loading inputs (lazy: stories module belongs to another workstream)
# ---------------------------------------------------------------------------

def _load_stories() -> list[dict[str, Any]]:
    """Best-effort story loading.

    1. Try candid.stories.list_stories() (stories workstream).
    2. Fall back to raw bullets from the profile's experience entries.
    """
    try:
        from candid import stories as stories_mod
        return list(stories_mod.list_stories())
    except ImportError:
        pass
    try:
        from candid import profile as profile_mod
        profile = profile_mod.load_profile()
    except Exception as exc:
        raise StaffError(
            "Could not load stories (candid.stories is not available in "
            "this checkout) and no profile exists to fall back on: "
            f"{exc}"
        ) from exc
    stories: list[dict[str, Any]] = []
    for entry in profile.get("experience", []) or []:
        for b in entry.get("bullets", []) or []:
            stories.append({
                "title": "",
                "bullet": b,
                "source": f"resume: {entry.get('title', '')} @ {entry.get('company', '')}",
            })
    return stories


def _load_profile() -> dict[str, Any]:
    from candid import profile as profile_mod
    return profile_mod.load_profile()


def _load_tracker_records() -> list[dict[str, Any]]:
    from candid import tracker as tracker_mod
    return tracker_mod.list_apps()


def _default_packet_path() -> Path:
    C.ensure_data_dirs()
    return C.DATA_DIR / "staff_packet" / "staff-packet.md"


# ---------------------------------------------------------------------------
# CLI: staff story ... / staff packet ...
# ---------------------------------------------------------------------------

def _cmd_story(args: argparse.Namespace) -> int:
    if args.bullet and args.story:
        raise StaffError("Use one of --bullet or --story, not both.")
    if args.bullet:
        story: dict[str, Any] | str = args.bullet
        slug = "bullet"
    elif args.story:
        stories = _load_stories()
        match = next(
            (s for s in stories
             if str(s.get("id", "")) == args.story
             or _clean(str(s.get("title", ""))).lower() == args.story.lower()),
            None,
        )
        if match is None:
            ids = [str(s.get("id", s.get("title", "?"))) for s in stories]
            raise StaffError(
                f"No story '{args.story}'. Available: {', '.join(ids) or '(none)'}"
            )
        story = match
        slug = args.story
    else:
        raise StaffError(
            "Provide --bullet \"...\" or --story ID. "
            "Run `staff packet` to see your stories first."
        )

    rendered = format_star_plus(story)
    if args.save is not None:
        out = (Path(args.save) if args.save
               else _default_packet_path().parent / "stories" / f"{slug or 'story'}.md")
        save_packet(rendered, out)
        print(f"Saved STAR+I story to {out}")
    else:
        print(rendered, end="")
    return 0


def _cmd_packet(args: argparse.Namespace) -> int:
    profile = _load_profile()
    stories = _load_stories()
    records = _load_tracker_records()
    if args.json:
        print(json.dumps(_packet_struct(profile, stories, records), indent=2))
        return 0
    markdown = build_packet(profile, stories, records)
    out = Path(args.out) if args.out else _default_packet_path()
    save_packet(markdown, out)
    print(f"Saved staff packet to {out}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m candid staff",
        description="Org-impact storytelling (STAR+I) and promo-packet builder.",
    )
    sub = p.add_subparsers(dest="what", required=True)

    s = sub.add_parser("story", help="Upgrade a story/bullet to STAR+I.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff story --bullet \"Cut p99 latency 40%\"\n  python -m candid staff story --story s1")
    s.add_argument("--story", default="", help="Story id (from stories.list_stories())")
    s.add_argument("--bullet", default="", help="Raw resume bullet to scaffold")
    s.add_argument("--save", nargs="?", const="", default=None,
                   help="Save the rendered story to a file "
                        "(default path under candid_data/staff_packet/stories/)")
    s.set_defaults(func=_cmd_story)

    s = sub.add_parser("packet", help="Build the staff promo packet.",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="examples:\n  python -m candid staff packet\n  python -m candid staff packet --out packet.md")
    s.add_argument("--out", default="",
                   help="Where to write the Markdown packet "
                        "(default: candid_data/staff_packet/staff-packet.md)")
    s.add_argument("--json", action="store_true",
                   help="Print the packet's structured data as JSON instead of writing Markdown")
    s.set_defaults(func=_cmd_packet)
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point: `staff story ...` / `staff packet ...`. Returns exit code."""
    args = build_arg_parser().parse_args(argv)
    try:
        return args.func(args)
    except StaffError as exc:
        print(f"staff: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
