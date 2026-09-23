# Label taxonomy

candid uses 20 labels so every issue can say **what it is**, **what part of the
app it touches**, and **how urgent it is**. One label from each group is the
norm: e.g. `type: bug` + `area: salary` + `priority: p1`.

| Group | Labels |
|---|---|
| type (4) | `type: bug`, `type: enhancement`, `type: docs`, `type: question` |
| area (9) | `area: jobs`, `area: match`, `area: prep`, `area: mock`, `area: salary`, `area: dashboard`, `area: onboarding`, `area: infra` |
| priority (3) | `priority: p0`, `priority: p1`, `priority: p2` |
| lifecycle (4) | `good first issue`, `help wanted`, `wontfix`, `duplicate` |

The authoritative definition lives in `scripts/sync-labels.py`; running it
with no arguments prints an offline create plan, and `--apply` syncs the
live repo via the GitHub API.

## Type

- **type: bug** - something is broken or behaves incorrectly. Include steps to
  reproduce, expected vs actual behavior, and the CLI command you ran.
- **type: enhancement** - a new feature or a change that improves existing
  behavior. Describe the use case and, if you have one, the proposed UX.
- **type: docs** - documentation fixes, clarifications, or new guides.
- **type: question** - you need help or clarification, not a code change. If it
  turns into real work, a maintainer re-labels it as an enhancement or bug.

## Area

The area maps to candid's modules (`python -m candid <module>`):

- **area: jobs** - job discovery and curated listings (`candid/jobs`).
- **area: match** - job match scoring against your profile (`candid/match`).
- **area: tailor** - tailored resumes and cover letters (`candid/tailor`).
- **area: prep** - interview prep packs, concept deep-dives, question banks
  (`candid/prep`, `candid/prep_concepts`, `candid/prep_questions`).
- **area: mock** - mock interviews and the online judge (`candid/mock`,
  `candid/mock_judge`).
- **area: salary** - salary intelligence: posting ranges plus DOL H-1B LCA
  data (`candid/salary`).
- **area: dashboard** - the local dashboard (`candid/dashboard`).
- **area: onboarding** - first-run onboarding and data import, including the
  Gmail mbox and LinkedIn export flows (`candid/profile`, `candid/gmail`,
  `candid/linkedin`).
- **area: infra** - build, tests, repo tooling, CI, and contributor scripts
  that do not fit a feature area.

## Priority

- **priority: p0** - critical. Blocks a release or breaks the core happy path
  (e.g. the CLI crashes on startup). Fix before anything else.
- **priority: p1** - high. A real defect or a needed feature with a release in
  mind. Fixed soon.
- **priority: p2** - normal. Worth doing when convenient; most good first
  issues land here.

## Lifecycle

- **good first issue** - small, well-scoped, and newcomer-friendly. See the
  guide below.
- **help wanted** - maintainers would love community help here; may be bigger
  than a good first issue.
- **wontfix** - decided not to do. Kept open for the record, then closed.
- **duplicate** - already tracked elsewhere; points at the canonical issue.

## "Good first issue" guide

A good first issue lets someone make a useful contribution in an evening,
with no deep context. Three properties:

1. **Small scope.** One file changed, or a handful of lines, plus a test.
   No cross-module refactors.
2. **Acceptance criteria.** The issue states exactly what "done" looks like:
   the command to run, the test to pass, or the output to produce.
3. **Pointers.** It names the module, the file, and the function or test to
   start from, so the contributor is not spelunking.

How maintainers write them: pick a bite-sized task from the backlog, add
`good first issue` plus a `priority: p2` and an `area:` label, then include
(a) a one-paragraph summary, (b) acceptance criteria in a checklist, and
(c) pointers like "start in `candid/salary.py`, see `tests/test_salary.py`".
Keep the setup friction at zero: the task must be doable after running
`./scripts/dev-setup.sh --skip-tests`.

## Example good-first-issue ideas

Grounded in candid's 0.2.0 module set:

1. **Add a sample JD fixture for match tests.** `tests/` has no fixture with a
   real-world job description. Add `tests/fixtures/sample_jd.md` and a test
   in `tests/` asserting `candid/match` scores it deterministically.
   Acceptance: the new test passes and running it twice gives the same score.
2. **Document a salary edge case.** In `candid/salary`, LCA rows with a $0 or
   missing wage can skew ranges. Add a paragraph to the module docstring (or
   README section) describing how such rows are handled, with a pointer to the
   relevant test.
3. **Add a mock interview problem.** Add one entry-level algorithms problem to
   the `candid/mock` problem bank with a prompt, sample input/output, and at
   least one hidden test, following the existing problem format.
4. **A --help text polish.** Pick one `candid/prep` subcommand whose help text
   is terse or confusing and rewrite it. Acceptance: `python -m candid prep
   --help` reads clearly; no behavior change; tests still pass.
5. **A dashboard empty-state message.** When the local dashboard has no
   applications yet, show a helpful empty state pointing at `candid jobs` and
   `candid tracker`. Acceptance: manual screenshot or a test on the
   template/data function.
6. **Reject a bad LinkedIn export early.** If the LinkedIn export archive is
   missing the messages CSV, `candid/linkedin` should fail with a clear
   message naming the missing file instead of a traceback. Add the check and
   a test with a fixture archive.
7. **A follow-up template typo or tone pass.** Review the drafts in
   `candid/followup` for one template with awkward phrasing, fix it, and add
   a test asserting the template renders with sample data.
