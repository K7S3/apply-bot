# Hiring-manager outreach (batch 68)

candid drafts personalized outreach to hiring managers, grounded in two things
you provide: the manager's **dossier** (public notes you collected yourself)
and **your profile**. It never scrapes, never invents hooks, and never sends
anything — every message is a draft for you to review.

## Workflow

```bash
# 1. Save what you know about the manager (from their posts, talks, team page)
python -m candid hm add --name "Priya Nair" --title "Eng Manager" \
    --company "Acme Corp" --team "Ads Ranking" \
    --notes "Gave a talk on infra cost at DataConf 2025" \
    --interest "infra cost" --source "DataConf 2025 talk"

# 2. See talking points, openers, and questions before you write
python -m candid hm brief priya

# 3. Work the research checklist (recent posts, team page, mutuals, ...)
python -m candid hm research --ref priya
python -m candid hm research --ref priya --check recent_posts --mark done

# 4. Draft (email, LinkedIn <=300 chars, or DM) in 3 templates
python -m candid outreach draft --to priya --role "ML Engineer" --channel email
python -m candid outreach variants --to priya --role "ML Engineer"

# 5. Score it and fix weaknesses before sending
python -m candid outreach score --to priya --file draft.txt
python -m candid outreach fix --to priya --file draft.txt

# 6. Track it like a mini-CRM
python -m candid outreach log --to priya --channel email
python -m candid outreach sent <entry-id>
python -m candid outreach nudge --days 7   # who has gone quiet
```

## JD clue extraction

JDs sometimes name the hiring manager or team. Pull those clues out to seed a
dossier:

```bash
python -m candid outreach clues --jd jd.txt
```

## Groundedness rules

- Drafts cite only dossier fields (notes, interests, sources) and your profile
  experience. A dossier with no specifics degrades to an honest short draft
  instead of inventing a hook ("I could not find much public detail...").
- The `mutual-connection` template refuses to run without a named connection.
- The scorer's `dossier_specifics` check fails drafts that praise without
  naming anything concrete, and flags spammy phrasing, ALL-CAPS, and
  placeholder tokens like `[Your Name]`.
- Brief talking points derived from thin dossiers are prefixed `verify:`.
