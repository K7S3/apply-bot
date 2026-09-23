# Draft revision rules, hygiene checks, and send-time guidance

`candid.drafting` builds email drafts only. Nothing in this package sends
mail, opens sockets, or touches the network. Everything is deterministic
(keyword matching and local heuristics, no LLM).

## Revision rules (`candid/drafting/revise.py`)

`revise(draft, instruction) -> {"subject", "body", "applied"}`

`draft` is `{"subject": ..., "body": ...}`. `instruction` is plain text such
as `"make it shorter and more formal"`. The instruction is lowercased and
matched against keyword sets; every matching rule runs in the fixed order
shorten, formalize, soften, add_cta. `applied` lists the rules that fired.
The subject is never modified. An instruction that matches nothing returns
the draft unchanged with `applied == []`.

### shorten

Target: 80 words (`SHORTEN_TARGET_WORDS`). The body is split into sentences;
each sentence gets an information score (non-stopword token count, minus a
penalty for filler phrases like "hope you are doing well", "just checking
in", "touching base", "circling back"). The lowest-scoring sentences are
dropped until the body fits the target. The first and last sentences are
never dropped, since they usually hold the greeting and the closing. If the
body already fits, the rule is a no-op but is still recorded in `applied`.

### formalize

- Expands contractions: `don't` -> `do not`, `can't` -> `cannot`,
  `I'm` -> `I am`, `it's` -> `it is`, `I'll` -> `I will`,
  `I've` -> `I have`, `let's` -> `let us`, and others; capitalization of
  the original word is preserved (`Don't` -> `Do not`).
- Upgrades casual greetings at the start of the body: `Hey` -> `Hello`,
  `Hi` -> `Dear`.
- Upgrades casual signoffs: `Cheers,` -> `Best regards,`,
  `Thanks,` -> `Thank you,`.

### soften

Deterministic blunt-to-hedged substitutions:

| original | replacement |
|---|---|
| I want (to) | I would like (to) |
| I need / We need | I would appreciate / We would appreciate |
| you need to | it would be helpful if you could |
| ASAP | at your earliest convenience |
| urgent | time-sensitive |

### add_cta

Appends the closing question "Would you be available for a brief call next
week to discuss further?" If a signoff line (`Best,`, `Regards,`,
`Thank you,`, ...) is found, the CTA is inserted as its own line just
before it; otherwise it is appended at the end. If the body already
contains a question, the rule is a no-op.

## Hygiene checks (`candid/drafting/hygiene.py`)

`check(draft) -> [ {"check", "severity", "message"} ]`; an empty list means
the draft passed every check. Severities: `error`, `warn`, `info`.

| check | severity | fires when |
|---|---|---|
| `subject_present` | error | subject is missing or empty |
| `subject_length` | warn | subject longer than 60 characters (inbox cutoff) |
| `body_length` | warn | body longer than 200 words |
| `spam_words` | warn | body contains `free`, `guarantee`, or `act now` |
| `exclamation_marks` | warn | more than 2 `!` in the body |
| `excessive_caps` | warn | more than 30% of letters are uppercase |
| `greeting_present` | info | first line has no greeting (`Hi`, `Hello`, `Dear`, ...) |
| `signoff_present` | info | last three lines contain no signoff (`Best,`, `Regards`, ...) |

## Send-time heuristic (`best_send_time()`)

Returns `{"weekday": "Tuesday-Thursday", "window": "9:00-11:00 AM",
"rationale": ...}`.

Rationale: mid-week mornings are the standard B2B outreach window.
Recipients have cleared the Monday backlog and are still in active work
mode, before the Friday wind-down. Times are expressed in the recipient's
local timezone, which is an assumption: shift the window when the
recipient's timezone is known to differ. Weekends and late-night sends are
avoided because they read as low-effort or automated.
