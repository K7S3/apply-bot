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
    followup  thank-you / recruiter nudge drafts
    offer     offer comparison and total-comp normalization
    negotiate recruiter scripts, counter drafts, BATNA framing
    mock      interactive mock interviews (coding judge, AI interviewer,
              behavioral, system design)
    mock_judge  sandboxed subprocess judge used by mock
    jobs      curated job discovery → tracker pipeline

Everything runs locally and deterministically, except the ``mock ai``
interviewer dialogue which uses the already-configured Gemini fast path.
No paid APIs, no hardcoded candidate data.
Your personal data lives in candid_data/ (git-ignored); sample data lives
in samples/candid/ so a new user can try every command in minutes.
"""

from __future__ import annotations

__version__ = "0.4.0"
