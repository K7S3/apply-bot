# Nonprofit and mission-driven job search

The `nonprofit` command group is candid's mission-driven layer. It does not
change how the core commands work; it adds nonprofit-aware feeds, scoring,
prep, comp notes, and a weekly digest on top of them.

```bash
python -m candid nonprofit sources
python -m candid nonprofit mission-fit --jd jd.txt
python -m candid nonprofit questions --category mission
python -m candid nonprofit org-status --company "Ford Foundation"
python -m candid nonprofit comp-note --title "Program Manager" --company "Khan Academy"
python -m candid nonprofit negotiate-guide --role "Program Manager"
python -m candid nonprofit pitch --mission "..." --background "..."
python -m candid nonprofit employers --query education
python -m candid nonprofit digest
```

## Feeds (`sources`, `jobs curate --sources ...`)

Two nonprofit feeds are registered in `jobs.ADAPTERS` alongside Arbeitnow and
RemoteOK:

- `reliefweb` — humanitarian jobs from the public ReliefWeb Jobs RSS feed
  (`https://reliefweb.int/jobs/rss.xml`). Free, no key, no login.
- `reliefweb_volunteer` — the same feed filtered to bridge roles:
  Internships, Volunteering, and Fellowships. Use it when you want a foot in
  the door rather than a full-time role.

Honest limits, verified 2026-09-23: the ReliefWeb v1 API returns 410 Gone
(retired); the v2 API requires an approved appname (unapproved names get
403). The RSS feed is what works without credentials, so that is what candid
uses. Only this one feed was verified, so only this one feed ships — no
second feed was fabricated to pad the list. See
`candid/nonprofit_feeds.py` for the adapter (~20 lines each, following
[docs/adding_sources.md](adding_sources.md)).

```bash
python -m candid jobs curate --role "Program Manager" \
    --sources reliefweb reliefweb_volunteer
```

## Mission fit (`mission-fit`, and `match`)

Add your cause interests to your profile (optional, free-form strings):

```json
{ "cause_interests": ["education", "climate"] }
```

Then `match` (text and `--json`) shows a mission-fit line for the JD, and
`nonprofit mission-fit --jd jd.txt` scores it standalone. The scorer
(`candid/mission_fit.py`) classifies the JD into 12 cause areas with local
keyword lists and computes:

`score = 60 * overlap_strength + 40 * cause_signal_clarity`

- `overlap_strength`: how much of *your* cause interests show up in the JD.
- `cause_signal_clarity`: how clearly the JD signals any mission at all
  (nonprofit markers, beneficiaries, impact language).

If you never set `cause_interests`, the score is `None` with an honest setup
note instead of a fake number. If the JD has no mission signals, the text
output hides the block entirely rather than printing a zero that looks like
a verdict.

## Interview prep (`questions`, and `prep`)

`nonprofit questions` prints 13 nonprofit interview questions with their
published sources (TruPath Search, Idealist, Alabama Association of
Nonprofits, and others) and URLs — never fabricated. Filter with
`--category mission|behavioral|situational`.

When you build a prep pack for a nonprofit-looking employer, the mission
questions are appended automatically:

```bash
python -m candid prep --company "Ford Foundation" --role "Program Manager"
```

The "nonprofit-looking" check (`candid/nonprofit_prep.py::org_status`) is a
name heuristic (foundation, 501(c)(3), .org, charity, etc.) plus PSLF
framing. It is explicitly a heuristic, not a tax-status lookup: confirm
real 501(c)(3) status with the IRS Tax Exempt Organization Search
(https://apps.irs.gov/app/eos/).

## Compensation (`comp-note`, `negotiate-guide`)

`comp-note` writes honest notes for a nonprofit-sector role: what the posted
band does or does not tell you, questions to ask when the range is missing,
PSLF framing (qualifying employment can forgive remaining federal direct
loan balance after 120 qualifying payments — priced as a real benefit), and
what to negotiate when base salary is rigid (benefits, title scope,
professional development, flexibility). It never invents salary figures;
PSLF eligibility questions are directed to studentaid.gov.

`negotiate-guide` gives nonprofit-specific negotiation scripts: mission
anchoring without underselling yourself, trading base for benefits, asking
for the band early, and walking away cleanly. No salary numbers are
invented anywhere in this module.

## Pitch (`pitch`)

A "why this mission" scaffold built from *your own* words: you pass
`--mission` (what the org does) and `--background` (your relevant
experience), and it returns a structured 60-90 second outline with
placeholders you fill in. Nothing about you is generated.

## Employers (`employers`)

A curated list of 44 mission-driven employers (nonprofits, B-corps, and
social enterprises) with 13 name aliases for matching:

```bash
python -m candid nonprofit employers --query education
python -m candid nonprofit employers   # full list
```

`is_mission_employer(company)` normalizes names through the aliases, so
"Teach For America" matches your tracker's "Teach for America". Direct
watchlist wiring waits on the batch that adds `watchlist.py`; until then,
use the digest.

## Digest (`digest`)

A weekly mission digest built from data you already have:

1. Saved tracker apps whose `source` is a nonprofit feed (ReliefWeb).
2. Tracker companies that match the mission-employer list.

It renders new nonprofit-sourced postings, mission-employer hits already in
your pipeline, and a short suggested-next-actions list. Run it weekly; it
reads, never writes.

## Honesty rules for this module

- No invented feeds, salaries, employers, or tax statuses.
- Heuristics are labeled as heuristics (`org_status`).
- Missing profile data yields a setup note, not a fabricated score.
- PSLF is framed as "confirm at studentaid.gov", never as a promise.
