"""Networking follow-up cadence manager.

A contact book plus the cadence around it: post-event follow-up sequences,
touchpoint logging, relationship-warmth tracking, value-add ideas,
re-engagement planning, double opt-in intros, and thank-you drafts.

Everything is local JSON under ``candid_data/network/``. Nothing is ever
sent automatically - drafts are printed for you to copy, edit, and send.
"""

from __future__ import annotations

FEATURES = [
    "contacts",     # network contact book
    "sequences",    # post-event follow-up sequences
    "touchpoints",  # touchpoint logging
    "warmth",       # relationship warmth tracking
    "valueadd",     # value-add touchpoint ideas + drafts
    "reminders",    # due follow-ups + re-engagement nudges
    "intros",       # double opt-in introduction builder
    "checkins",     # quarterly re-engagement planner
    "thanks",       # thank-you drafts after help / referrals
    "report",       # networking activity report
]
