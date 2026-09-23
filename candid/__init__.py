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
    dashboard local web UI (127.0.0.1 only)
    gmail     Gmail Takeout mbox import (proposals, never auto-applied)
    linkedin  official LinkedIn data-export import
    nudges    follow-up reminder engine
    prep_questions  verified interview-question bank with source links
    release_checklist  pre-release check aggregator (tests, docs, version, secrets)
    release_report  release readiness report renderer (markdown/json)
    release_tests  test-suite gate and coverage threshold
    release_docs  CLI/docs coverage checks
    release_version  version consistency checks and version bumping
    release_notes  changelog generation from git history
    release_secrets  pre-release secret, PII, and forbidden-file scan
    release_tag  annotated release tag flow (dry run by default)
    release_verify  read-only local-vs-remote release verification
    release_migrate  migration-notes detection between refs

Everything runs locally and deterministically, except the ``mock ai``
interviewer dialogue which uses the already-configured Gemini fast path.
No paid APIs, no hardcoded candidate data.
Your personal data lives in candid_data/ (git-ignored); sample data lives
in samples/candid/ so a new user can try every command in minutes.
"""

from __future__ import annotations

__version__ = "0.2.0"
