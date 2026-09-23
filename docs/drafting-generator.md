# Email Draft Generator (`candid.drafting`)

Template-based, context-aware email drafts for the job search. Local-first
and deterministic: no LLM, no network, no sending. Drafts are returned as
plain dicts for the user to review, copy, and send themselves.

**Hard rule:** nothing in `candid/drafting/` may send email, open sockets,
or make network calls. Tests assert the module sources contain no
`smtplib` / `socket` / `requests` / `urllib` / `http.client` / `sendmail`.

## `candid.drafting.drafts`

```python
from candid.drafting.drafts import generate

draft = generate(
    "thank_you",
    {
        "company": "Acme Robotics",
        "role": "Machine Learning Engineer",
        "contact_name": "Priya Nair",
        "user_name": "Keshavan Seshadri",
        "topic": "ads ranking infrastructure",
    },
    tone="professional",
)
# draft -> {"subject": ..., "body": ..., "kind": ..., "tone": ..., "missing": [...]}
```

`generate(kind, context, tone="professional") -> dict` returns:

| key       | meaning                                                        |
|-----------|----------------------------------------------------------------|
| `subject` | filled subject line                                            |
| `body`    | filled email body                                              |
| `kind`    | the requested draft kind                                       |
| `tone`    | the tone used (`"professional"` if the requested tone was unknown) |
| `missing` | sorted list of placeholder names with no value in `context`    |

Placeholders use `{name}` syntax. Any placeholder missing from `context`
is left verbatim in the text (e.g. `{company}`) and reported in
`missing`, so the user can fill it in by hand. Nothing is silently
dropped.

### Per-kind table

| kind              | use when                                  | key placeholders                                                        |
|-------------------|-------------------------------------------|-------------------------------------------------------------------------|
| `thank_you`       | after applying or a screening call        | `company`, `role`, `contact_name`, `user_name`, `topic`                 |
| `check_in`        | follow-up after applying, no response yet | `company`, `role`, `contact_name`, `user_name`, `applied_date`          |
| `referral_request`| asking a contact for an employee referral | `company`, `role`, `contact_name`, `user_name`                          |
| `post_interview`  | thank-you after an interview round        | `company`, `role`, `contact_name`, `interviewer_names`, `user_name`, `topic` |
| `offer_stall`     | politely ask for more decision time       | `company`, `role`, `contact_name`, `user_name`, `decision_date`         |
| `rejection_thanks`| gracious reply to a rejection             | `company`, `role`, `contact_name`, `user_name`                          |
| `cold_intro`      | cold outreach to a hiring manager         | `company`, `contact_name`, `user_name`, `target_role`, `location`, `source`, `topic` |

Tones: `professional` (default), `friendly`, `concise`. Every kind
provides 2-3 sentence templates per tone.

## `candid.drafting.personalize`

Substitutes `{tokens}` from a profile dict (by convention, the user's
`candid_data/profile.json`).

```python
from candid.drafting.personalize import apply_tokens, preview_substitutions

text, missing = apply_tokens("Hi, I'm {full_name}, a {target_role}.", profile)
# -> ("Hi, I'm Keshavan Seshadri, a Machine Learning Engineer.", [])

preview = preview_substitutions(context, profile)
# -> {"user_name": {"value": ..., "resolved": True, "source": ..., "unresolved_tokens": []}, ...}
```

`apply_tokens(text, profile) -> (text, missing)`: returns the substituted
text plus the tokens (in order of first appearance) that had no value.
Unresolved tokens stay verbatim.

`preview_substitutions(context, profile) -> dict`: for each context key,
shows the expanded value, whether it fully resolved, the profile key it
came from, and any unresolved tokens. Use it to review substitutions
before generating a draft.

### Token reference

| token                | profile key            | notes                                  |
|----------------------|------------------------|----------------------------------------|
| `{full_name}`        | `full_name`            | alias: `{name}`                        |
| `{first_name}`       | `first_name`           | falls back to first word of `full_name`|
| `{last_name}`        | `last_name`            | falls back to last word of `full_name` |
| `{target_role}`      | `target_role`          | alias: `{role}`                        |
| `{location}`         | `location`             | alias: `{city}`                        |
| `{email}`            | `email`                |                                        |
| `{phone}`            | `phone`                |                                        |
| `{years_experience}` | `years_experience`     | alias: `{years}`                       |
| `{headline}`         | `headline`             |                                        |
| `{linkedin}`         | `linkedin`             |                                        |
| `{github}`           | `github`               |                                        |
| `{website}`          | `website`              |                                        |

Empty strings and absent keys both count as missing. A typical flow is:
`preview_substitutions(context, profile)` → fix gaps → merge profile
values into `context` → `generate(kind, context, tone=...)`.
