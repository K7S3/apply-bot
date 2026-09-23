# Security Policy

## Supported versions

candid is pre-1.0 and under active development on the main branch. We
provide security fixes for the latest release only. If you are running an
older checkout, update to the latest release or main before reporting.

## Scope

candid is a local-first CLI (`python -m candid ...`) plus a local dashboard
(`candid/dashboard.py`). The threat model is simple: candid runs on the
user's own machine and handles their most sensitive job-search data
(resumes, salary info, application history).

## What counts as a vulnerability

We take the following seriously:

- **Secrets handling.** Any place candid writes, logs, or transmits
  credentials, tokens, or private keys. (candid should never ask for or
  store these; if it does somewhere, that is a bug.)
- **Sandbox escape in the mock judge.** `candid/mock_judge.py` executes
  user-supplied code in a sandbox. A way to break out of that sandbox into
  the host filesystem, network, or process table is a vulnerability.
- **Path traversal in imports.** Commands that read user-supplied paths
  (onboard, imports of resumes/JDs/profiles) must not allow `../` or
  absolute paths to escape the intended directories.
- **Local dashboard exposure.** The dashboard must bind to localhost by
  default and must not serve other users' data or enable remote access
  without explicit user consent.
- **Dependency or packaging issues** that could lead to code execution on
  install or update.

## How to report

Report privately. Do not open a public issue for a suspected vulnerability.

Send a description of the issue, steps to reproduce, and the version or
commit you tested to the maintainers of K7S3/candid at
[CONTACT PLACEHOLDER - maintainer email] (or open a private security report
via GitHub Security Advisories if enabled). Please allow a reasonable time
for a fix before disclosing publicly. We will acknowledge your report and
keep you posted on progress.

## What NOT to report

- Social engineering of users (phishing, credential theft by impersonation).
  Those are people problems, not candid bugs.
- Missing features or hardening wishlists that are not exploitable bugs.
  File those as regular feature requests instead.
- Issues in third-party tools candid does not bundle (your OS, your editor).

## Notes for contributors

- Treat anything under `candid_data/`, `resumes/`, or user-supplied files
  as sensitive sample data in tests; do not commit real resumes or personal
  data.
- When in doubt about whether something is a security issue, report it
  privately anyway. We would rather hear about a non-issue than miss a real
  one.
