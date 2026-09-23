# Recruiter message classifier (`gmail classify`)

`python -m candid gmail classify --mbox mail.mbox` buckets inbound mail
from a Gmail Takeout export into four buckets and lists each message with
the reasons it landed there:

| Bucket | Meaning |
|---|---|
| `direct_outreach` | A real person at the hiring company: hiring manager, team lead, founder, ... |
| `agency_outreach` | A third-party recruiter / staffing agency selling someone else's opening |
| `interview_invite` | Interview invites / scheduling: phone screens, "share your availability", Calendly links, assessments |
| `unsure` | Ambiguous mail. Never forced into a wrong bucket; review manually |

Messages in the `interview_invite` bucket become tracker **proposals**
(status `pending`) via the same dedupe rules as `gmail import`. Nothing
is written to your tracker until you confirm each one:
`python -m candid gmail confirm <id>` (or `gmail reject <id>`).

## The heuristics

Heuristic rules only. No model downloads, no network, stdlib only
(`candid/classify.py`).

**Interview invite** (checked first; scheduling intent wins over sender
type, so an interview invite from an agency recruiter still lands here):

- *Strong signals* (any one is enough): a Calendly/Cal.com scheduling
  link, "interview invitation/invite", "phone screen"/"technical screen",
  "onsite interview", "final/next round", "share/send your availability",
  "calendar invite", coding challenge / take-home / HireVue.
- *Weak signals* (need 2+): "interview", "schedule...", "onsite",
  "availability". A single "let's schedule a call" in first-touch
  outreach is an intro chat, not an interview invite, and stays out.

**Agency outreach:**

- Sender domain root contains staffing/recruiting keywords
  (`staffing`, `recruit`, `talent`, `headhunt`, `workforce`, `placement`).
- Body language: "my/our/the client", C2C/corp-to-corp, W2/1099,
  hourly rate ($/hr), "hot/urgent requirement", "dear candidate",
  "contract opportunity".

**Direct outreach:**

- Body language: "hiring manager", "my team", "I'm the <title> at
  <company>", "we're hiring", "I lead", company-side titles
  (engineering manager, director, VP eng, CTO, CEO, founder).
- Sender domain matches a company named in the message
  (e.g. `jane@novacorp.com` writing about NovaCorp), or the sender
  looks like a person at a non-free, non-agency domain.

**Unsure:** no decisive signals, or conflicting ones (agency evidence
*and* direct evidence), or only a single weak interview mention.

## Limits (read before trusting the buckets)

- These are regexes over English job-search language, not understanding.
  Clever phrasing ("come meet the team for coffee" as a final round)
  will be missed; sarcasm and non-English mail mostly land in `unsure`.
- The domain heuristics can't know your actual employer list: a
  recruiter writing from a personal Gmail with no agency language may
  land in `unsure`, and an internal recruiter at a company whose domain
  contains "talent" (e.g. `talent-bridge.com`) could be misread as
  agency. The reasons shown per message make this auditable.
- Offer letters and rejection emails are out of scope for this
  classifier; they land in `unsure`. Use `gmail import` (which has
  `offer` / `rejection` kinds) for those.
- When in doubt it says `unsure` rather than guessing. That is the
  design: a missed bucket is a manual review, a wrong bucket is a
  wrong action.
