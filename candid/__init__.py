"""candid — a generic, local-first job-search candid.

Modules:
    config    paths, statuses, defaults
    profile   onboarding: resume / LinkedIn ingest -> structured profile
    match     job-description fit scoring
    tailor    tailored resume + cover letter generation
    tracker   application tracker with funnel stats
    salary    salary intelligence (pay ranges + DOL LCA data)
    prep      interview prep packs (questions, deep-dives, mock, checklist)
    prep_concepts  concept explainer library used by prep
    prep_tracks role-family prep tracks: curated loops, question banks,
                concept deep-dives, timed drills, study plans, progress
    followup  thank-you / recruiter nudge drafts
    offer     offer comparison and total-comp normalization
    vesting   vesting schedule visualizer: timelines, cliff markers,
              cumulative value charts, refresher modeling, departure
              analysis, price scenarios, golden handcuffs, tax events
    negotiate recruiter scripts, counter drafts, BATNA framing
    alumni    alumni network mapper: Connections.csv import, school/company
              overlap, warm-path finder, outreach queue, drafts, coverage,
              freshness (all local, all deterministic)
    mock      interactive mock interviews (coding judge, AI interviewer,
              behavioral, system design)
    mock_judge  sandboxed subprocess judge used by mock
    jobs      curated job discovery → tracker pipeline
    patterns  coding patterns curriculum: taxonomy, gap-driven Blind-75-style
              study plans, spaced repetition, drills, mastery, cheat sheets
    apply_fields  safe/sensitive/unknown field classifier for form filling
    apply_profile safe contact store (13 contact keys only, git-ignored)
    apply_jobs    job specs (jobs/*.yaml) + resume resolution
    apply_state   per-application state machine (JSON store)
    apply_adapters ATS form adapters (generic heuristic filler)
    apply_browser optional Playwright browser layer (opt-in extra)
    apply_runner  supervised apply pipeline: fill, park at review, approve,
                  submit. See docs/apply.md

Everything runs locally and deterministically, except the ``mock ai``
interviewer dialogue which uses the already-configured Gemini fast path.
No paid APIs, no hardcoded candidate data.
Your personal data lives in candid_data/ (git-ignored); sample data lives
in samples/candid/ so a new user can try every command in minutes.
"""

from __future__ import annotations

__version__ = "0.5.0"
