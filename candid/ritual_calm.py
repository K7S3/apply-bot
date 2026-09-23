"""Pre-interview calming routine.

A short, guided routine to run in the minutes before an interview:
box breathing, a 5-4-3-2-1 grounding exercise, affirmations built from
the user's real profile strengths (or generic ones when no profile
exists), and two prompts that reframe catastrophic thoughts.

This is a routine, not treatment. It makes no medical or therapeutic
claims; it is just a calm sequence to steady nerves before a call.

Standalone use:
    python -m candid.ritual_calm --cycles 4
    python -m candid.ritual_calm --cycles 2 --no-wait   # instant, for tests

The ``ritual calm`` CLI wiring is done by a sibling module; this module
exposes the clean function interface:

    run_calm(cycles=4, no_wait=False, profile=None) -> dict
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from candid import config as C

PHASES = ("inhale", "hold", "exhale", "hold")
PHASE_SECONDS = 4

GENERIC_AFFIRMATIONS = [
    "I prepared for this interview. Preparation is evidence, not luck.",
    "Nerves mean my body is getting ready. I can feel them and still answer well.",
    "I only need the next question, not the whole interview at once.",
]

REFRAMES = [
    "What is the most useful thing I could learn from this round, "
    "even if it goes badly?",
    "If a friend were this nervous before an interview, what would I "
    "honestly tell them about their chances?",
]

GROUNDING_STEPS = [
    ("5", "Name 5 things you can see right now."),
    ("4", "Notice 4 things you can touch or feel."),
    ("3", "Listen for 3 things you can hear."),
    ("2", "Find 2 things you can smell."),
    ("1", "Notice 1 thing you can taste."),
]


# ---------------------------------------------------------------------------
# profile loading
# ---------------------------------------------------------------------------

def load_profile(profile=None):
    """Return the profile dict, loading candid_data/profile.json if needed.

    A profile passed explicitly wins. Returns None when no profile is
    available anywhere, which is fine: affirmations fall back to generic.
    """
    if profile is not None:
        return profile
    data_dir = Path(os.environ.get("CANDID_DATA_DIR") or C.DATA_DIR)
    path = data_dir / "profile.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def affirmations_for(profile):
    """Build 3 affirmations from real profile strengths.

    Only uses fields actually present in the profile; anything missing is
    filled with the generic affirmations. Never invents specifics.
    """
    out = []
    if profile:
        skills = [s for s in (profile.get("skills") or []) if s][:3]
        years = profile.get("years_experience")
        headline = (profile.get("headline") or "").strip()
        name = (profile.get("name") or "").strip().split()

        if skills:
            pretty = ", ".join(skills)
            out.append(
                f"I have put real hours into {pretty}. "
                "That skill is mine, and I can use it today."
            )
        if years:
            try:
                yrs = float(years)
                yrs_txt = str(int(yrs)) if yrs == int(yrs) else str(yrs)
                out.append(
                    f"I have {yrs_txt} years of real work behind me. "
                    "One hard hour does not erase that."
                )
            except (TypeError, ValueError):
                pass
        if headline:
            first = f"{name[0]}, " if name else ""
            out.append(
                f"{first}you are a {headline}. "
                "You earned this interview by being exactly that."
            )

    for generic in GENERIC_AFFIRMATIONS:
        if len(out) >= 3:
            break
        if generic not in out:
            out.append(generic)
    return out[:3]


# ---------------------------------------------------------------------------
# the routine
# ---------------------------------------------------------------------------

def run_calm(cycles=4, no_wait=False, profile=None):
    """Run the calming routine and return a dict describing what happened.

    cycles: number of box-breathing cycles (inhale/hold/exhale/hold).
    no_wait: skip real sleeping so tests and dry runs are instant.
    profile: optional profile dict; otherwise candid_data/profile.json.
    """
    if cycles < 1:
        cycles = 1

    prof = load_profile(profile)
    affirmations = affirmations_for(prof)

    phases = []
    print("\nPre-interview calm routine")
    print("=" * 28)
    print("\nBox breathing. Breathe with the prompts.\n")
    for c in range(1, cycles + 1):
        print(f"Cycle {c} of {cycles}:")
        for phase in PHASES:
            line = f"  {phase} ... {PHASE_SECONDS} seconds"
            print(line)
            phases.append(
                {"cycle": c, "phase": phase, "seconds": PHASE_SECONDS}
            )
            if not no_wait:
                time.sleep(PHASE_SECONDS)

    print("\nGrounding: 5-4-3-2-1. Go slowly.\n")
    grounding = []
    for count, text in GROUNDING_STEPS:
        print(f"  {count}: {text}")
        grounding.append({"count": count, "prompt": text})

    print("\nThree reminders, from your own record:\n")
    for i, aff in enumerate(affirmations, 1):
        print(f"  {i}. {aff}")

    print("\nIf your thoughts are racing, try one of these:\n")
    for i, ref in enumerate(REFRAMES, 1):
        print(f"  {i}. {ref}")

    print("\nDone. You are as ready as preparation can make you.\n")

    return {
        "routine": "calm",
        "cycles": cycles,
        "breathing": {
            "phases": PHASES,
            "phase_seconds": PHASE_SECONDS,
            "phases_done": phases,
        },
        "grounding": grounding,
        "affirmations": affirmations,
        "reframes": list(REFRAMES),
        "profile_used": bool(prof),
    }


# ---------------------------------------------------------------------------
# standalone entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pre-interview calming routine: box breathing, "
        "grounding, affirmations, reframes."
    )
    ap.add_argument("--cycles", type=int, default=4,
                    help="Breathing cycles (default 4).")
    ap.add_argument("--no-wait", action="store_true",
                    help="Skip the real waiting (instant, for tests).")
    args = ap.parse_args(argv)
    run_calm(cycles=args.cycles, no_wait=args.no_wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
