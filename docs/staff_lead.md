# Staff / Principal Interview Prep

`candid.staff_lead` provides two prep modules for the staff/principal track:

- **Cross-org influence scenarios** (10): situation write-ups with the
  staff lens (what interviewers are really evaluating), concrete strong
  moves, and pitfalls.
- **Mentorship and team-health topics** (5): guiding principles, practice
  questions with good signals, and red flags.

All content is labeled `candid practice prompt` (original practice guidance
written for candid, not scraped or reported questions). It is frameworks
and checklists only: it never invents your experience or metrics. You must
fill in your own real stories.

## Scenarios

| id | title |
|---|---|
| `disagree-commit` | Disagree and commit with a partner team |
| `decision-no-authority` | Driving a decision with no formal authority |
| `kill-own-project` | Killing your own project |
| `conflict-resolution` | Resolving a conflict between two teams |
| `deprecate-beloved-system` | Deprecating a system people love |
| `standards-adoption` | Getting org-wide adoption of a standard or platform |
| `tech-debt-escalation` | Escalating tech debt to business leadership |
| `inherited-mess` | Inheriting someone else's failing project |
| `vendor-open-source` | Choosing between a vendor and building in-house |
| `org-design` | Shaping an org or team structure change |

## Mentor topics

| key | title |
|---|---|
| `growing-engineers` | Growing engineers |
| `hiring-bar` | Holding the hiring bar |
| `underperformance` | Handling underperformance |
| `feedback` | Giving and receiving feedback |
| `team-health` | Team health |

## CLI

These subcommands are intended to be wired into the main CLI as
`python -m candid staff influence ...` and `python -m candid staff mentor ...`
(by the parent orchestrator; this module only defines the functions).

```
staff influence [--list] [--scenario ID] [--json]
staff mentor [--list] [--topic TOPIC] [--json]
```

- `staff influence` (or `--list`): list all scenario ids and titles.
- `staff influence --scenario decision-no-authority`: show the full scenario.
- `staff influence --json`: emit all scenarios as JSON (payload fields: id,
  title, situation, staff_lens, strong_moves, pitfalls, source).
- `staff mentor`: show the default topic (`growing-engineers`).
- `staff mentor --list`: list topic keys and titles.
- `staff mentor --topic feedback`: show one topic.
- `staff mentor --json`: emit all topics as JSON (payload fields: topic,
  title, guiding_principles, practice_questions, red_flags, source).

Unknown ids/topics exit with code 2 and an error naming the valid options.

## Python API

```python
from candid import staff_lead as SL

SL.list_influence_scenarios()      # ['disagree-commit', ...]
SL.get_influence_scenario("kill-own-project")
SL.format_influence(s)            # readable text

SL.list_mentor_topics()           # ['growing-engineers', ...]
SL.get_mentor_topic("feedback")
SL.format_mentor(t)               # readable text

SL.main(["influence", "--scenario", "org-design", "--json"])  # -> 0
```

`SL.StaffError` is raised for unknown scenario ids or topic keys.

## How to use it

For each scenario: pick a real story from your own experience that fits the
situation. Rehearse it against the strong moves as a checklist, and make
sure your telling avoids the pitfalls. For each mentor topic: answer the
practice questions out loud, checking your answers against the good signals,
and screen your stories for the red flags. Do not invent details or metrics.
