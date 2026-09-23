# Security-engineer interview track

The `security` command groups candid's security-engineer interview prep.
Every subcommand is available as `python -m candid security <subcommand>`.
Run `python -m candid security --help` for the full list.

All content is researched and source-attributed: interview questions carry
their source and report date, and incident case studies link to primary
sources. Nothing is fabricated.

## questions

Browse the researched security question bank (46 questions across 8
categories: appsec, cloudsec, threat-modeling, crypto, incident-response,
iam-network, detection, behavioral).

```bash
python -m candid security questions
python -m candid security questions --category appsec
python -m candid security questions --search ssrf
python -m candid security questions --search "jwt" --json
```

`--category` filters to one category (unknown categories are rejected with
the valid list). `--search` does a case-insensitive search over question
text. `--json` prints the raw question dicts for scripting.

## concepts

Deep-dives on the core concepts security interviews probe: OWASP Top 10,
authentication, OAuth2/OIDC, TLS, crypto primitives, password hashing, and
more.

```bash
python -m candid security concepts --list
python -m candid security concepts owasp-top-10
```

Each concept covers a summary, key points, likely interview angles, and
related question categories.

## threat-model

Interactive STRIDE threat-modeling drills. Pick a scenario, list the
threats you see (one per line as `LETTER: description`), and get a score
report showing which hints you matched and which STRIDE letters you missed.

```bash
python -m candid security threat-model --list
python -m candid security threat-model --scenario file-upload-service
python -m candid security threat-model   # pick a scenario interactively
```

Scenarios: `file-upload-service`, `sso-login-flow`, `public-api-keys`,
`cicd-pipeline`, `mobile-app-backend`, `pii-data-pipeline`.

## design-drill

Secure system-design drills. Each drill gives a design prompt and a
checklist of security considerations; answer y/n for each item you covered
and get a coverage score plus the missed items to study.

```bash
python -m candid security design-drill --list
python -m candid security design-drill --drill secure-auth-saas
```

Drills: `secure-auth-saas`, `secure-file-sharing`, `secrets-rotation`,
`multitenant-isolation`, `secure-webhook-receiver`, `passwordless-login`,
`audit-logging-pipeline`, `third-party-api-integration`.

## incidents

Real-world breach case studies with root-cause analysis, lessons, and
interview framing (how to tell the story in an interview).

```bash
python -m candid security incidents --list
python -m candid security incidents --search ransomware
python -m candid security incidents --search "log4shell"
```

Incidents include Capital One 2019, SolarWinds Sunburst, Log4Shell,
Equifax 2017, Target 2013, Uber 2016, LastPass 2022, and MOVEit 2023.

## mock

Scored, interactive mock interviews drawn from the question bank. Answers
are read from stdin (end each answer with a single `.` line) and scored
against the question's expected points.

```bash
python -m candid security mock
python -m candid security mock -n 3
python -m candid security mock -n 3 --category crypto
```

`-n` sets the number of questions (default 5); `--category` filters the
bank first.

## gaps

Interactive skill-gap assessment. Rate yourself 1-5 in each security
domain and get a prioritized study plan with your weakest domains first.

```bash
python -m candid security gaps
```

## stories

STAR story prompts for behavioral rounds, each with scaffolding for the
situation, task, action, and result.

```bash
python -m candid security stories --list
python -m candid security stories --prompt found-vulnerability
```

Prompts cover finding vulnerabilities, handling incidents, pushing back on
risky ships, velocity/security tradeoffs, mentoring, threat-modeling a
feature, audit response, and more.

## loop

Interview-loop guides by company type: what each round covers and how to
prepare for it.

```bash
python -m candid security loop --list
python -m candid security loop startup
```

Loops: `startup`, `bigtech`, `fintech`, `consulting`.

## Prep-pack integration

`prep --track security` prepends a Security track section to any prep
pack: 5 sampled security questions (mixed across categories) plus pointers
to 3 concept deep-dives.

```bash
python -m candid prep --company Acme --role "Security Engineer" --track security
```
