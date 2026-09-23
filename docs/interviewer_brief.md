# Interviewer brief (`brief`)

Know who's across the table before you sit down. The interviewer brief
collects what you learn about your interviewers, predicts what each one is
likely to ask based on their role, and turns it into a focused prep sheet.

## Honesty rules

- candid never scrapes anyone. Background info is entered by you from public
  sources you looked at yourself (LinkedIn, talks, blogs, GitHub).
- Role angles and deep-dive questions are deterministic templates, not
  verified reports. They are labeled as generated wherever they appear.

## Workflow

```bash
# when you learn the loop
python -m candid brief add --name "Jane Doe" --role hiring_manager --app-id 3 --round "Round 2"
python -m candid brief add --name "Sam Lee" --role peer_engineer --app-id 3 --round "Round 3"

# record what you found about them
python -m candid brief background --id 1 --title "Eng Manager, Growth" \
  --focus "ranking, experimentation, on-call"

# build the brief
python -m candid brief show --company Acme --role-title "Data Scientist"

# after the interview, log what happened
python -m candid brief debrief --id 1 \
  --asked "churn case; SQL window functions" \
  --signals "dug three levels deep on metrics"

# see the role playbook
python -m candid brief roles
```

Roles: `hiring_manager`, `peer_engineer`, `bar_raiser`, `recruiter`,
`skip_level`, `domain_specialist`. Unknown roles get a generic profile.

## What the brief contains

1. Interviewer cards: name, role, round, background highlights.
2. Likely angles per interviewer, from the role profile (what they evaluate,
   observable tells, prep tips).
3. Top questions to prepare: company-reported and general questions ranked by
   role fit and JD keyword overlap, with a rationale per question.
4. Deep dives generated from their focus areas and talk topics (labeled
   generated, not verified).
5. Panel strategy: distinct focus categories per interviewer, your resume
   bullets distributed with no repeats, and what not to repeat.
6. Questions to ask each interviewer, tailored to their role.
7. A 5-item research checklist.
8. Debrief history: what they asked last time, if you logged it.

## Integrations

- `prep` packs automatically append an "Interview brief" section when
  interviewers are recorded for the company.
- The dashboard's prep status includes the interviewer count per application.

Data lives in `candid_data/interviewers.json` and `candid_data/briefs/`.
Modules: `candid/interviewers.py`, `candid/interviewer_roles.py`,
`candid/brief_rank.py`, `candid/panel.py`, `candid/reverse_questions.py`,
`candid/brief.py`.
