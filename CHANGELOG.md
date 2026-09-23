## [0.2.0] - 2026-09-23

Changes since `the beginning of history`.

### Features

- candid 0.2.0: deeper matching, smarter CLI, dashboard v2, 15 coding problems (`b214b42`) - Keshavan Seshadri
- Rename apply-bot to candid: generic job-search copilot (`8ca3a9e`) - Keta
- Upload-ready PDF resumes + live-submit safety guard (`a072c4c`) - Keta (apply-bot)

### Bug Fixes

- Fix: 11 Bloomberg/NVIDIA rows were wrongly skipped; mark needs_manual for per-role verification (`0ab0a51`) - Keta (apply-bot)

### Documentation

- Export-based ingestion: Gmail Takeout mbox and LinkedIn ZIP imports (`a000fd5`) - Keta (apply-bot)
- docs: README now describes local Ollama setup instead of Gemini API key (`21684fc`) - Keta
- E2E test fixtures + polished README (`3787e0d`) - Keta (apply-bot)

### Other

- Rewire resume review to local Ollama (deepseek-r1:8b); live-mode consent guard; --yes flag; resume skip (`fdc18ca`) - Keta (apply-bot)
- Allow system Chromium via APPLYBOT_CHROMIUM_PATH / APPLYBOT_NO_SANDBOX env vars (`c105227`) - Keta (apply-bot)
- Initial apply-bot: Excel-driven resume review + auto-apply pipeline (`94adedd`) - Keta

### Stats

- 10 commits
- By category: feat: 3, fix: 1, docs: 3, other: 3
- Authors: Keta (apply-bot) (6), Keta (3), Keshavan Seshadri (1)
- Range: 2026-09-13T20:49:00-04:00 to 2026-09-22T00:23:45+00:00
