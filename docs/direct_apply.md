# Direct-apply vs portal guidance

Not all "Apply" buttons are equal. A referral beats a portal, a direct
email beats a queue, and a Taleo portal is a different afternoon than a
Greenhouse one. `candid guide` answers, per posting: **what is the best
way to apply?**

## The channel model

Every posting is classified into these channels (also the vocabulary for
the tracker's `channel` field):

| Channel | Meaning |
|---|---|
| `referral` | A 1st-degree connection at the company can refer you (from your LinkedIn export). |
| `direct_email` | The posting publishes an apply email (e.g. "send your resume to jobs@…"). |
| `ats_portal` | A recognized ATS portal (Greenhouse, Lever, Workday, …). |
| `company_site` | The employer's own careers page, no ATS identified. |
| `linkedin_easy_apply` | LinkedIn Easy Apply. |
| `aggregator` | Indeed / Glassdoor / ZipRecruiter / … listing — not the employer's posting. |

Channels rank in that order when several are available: referral first,
aggregator last (with a warning to find the company posting instead).

## Commands

```bash
# Full per-posting advice (ranked channels, ATS notes, referral path, freshness)
python -m candid guide posting --app-id 3
python -m candid guide posting --url https://boards.greenhouse.io/acme/jobs/123 \
    --company Acme --role "ML Engineer" --jd jd.txt

# Portal notes: account needed? parsing quality? quirks? time budget?
python -m candid guide ats --name workday
python -m candid guide ats --name greenhouse

# Referral paths at a company + draft the ask
python -m candid guide referral --company Acme
python -m candid guide referral --company Acme --connections Connections.csv

# Log how you applied; see which channels actually convert
python -m candid guide log --app-id 3 --channel referral
python -m candid track add --company Acme --role "ML Engineer" --channel ats_portal
python -m candid guide stats

# Cold direct-application email draft (for the direct_email channel)
python -m candid guide email --company Acme --role "ML Engineer" --to jobs@acme.com
```

All read commands accept `--json` for scripting.

## What `guide posting` tells you

- **Headline**: the single best channel, e.g. `Best channel: Referral - Priya Nair (Senior Engineer) can refer you: works at Acme Corp now; senior-level title.`
- **Ranked channels** with a `Next:` step for each.
- **ATS portal notes**: whether an account is required, resume-parsing quality, quirks (Workday session timeouts, Taleo weak parsing), and tips.
- **Direct apply emails** found in the posting text, with context snippets.
- **Referral path**: ranked 1st-degree connections at the company (exact company match first, then fuzzy; senior titles and recent connections first).
- **Freshness**: posting age with advice (≤48h: apply today; >30d: verify still open).
- **Aggregator warning** when the URL is Indeed/Glassdoor/etc.

## ATS coverage

28 portals are identified by URL (plus text hints as a fallback):
Greenhouse, Lever, Ashby, Workday, iCIMS, Taleo, SmartRecruiters, BambooHR,
Workable, Jobvite, JazzHR, Breezy HR, Rippling, SAP SuccessFactors,
Eightfold, Pinpoint, UKG, Oracle HCM, BrassRing, Phenom, ADP, Recruitee,
Teamtailor, Personio, Zoho Recruit, Freshteam, Wellfound, ApplyToJob.
Unidentified portals get generic notes instead of a wrong guess.

## Honesty notes

- Referral detection uses **only** your LinkedIn export's 1st-degree
  connections. candid cannot see 2nd-degree connections and never claims to.
- Email extraction only finds addresses the employer **published** in the
  job text. Nothing is looked up, guessed, or scraped.
- Aggregator detection is URL-based; a company site behind an unrecognized
  path is treated as `company_site`, not mislabeled.

## Module

`candid/channels.py` — pure stdlib, no network. Entry points:
`identify_ats`, `ats_notes`, `classify_channels`, `extract_apply_emails`,
`aggregator_info`, `recommend_channels`, `referral_path`,
`load_connections`, `draft_referral_request`, `draft_direct_apply_email`,
`freshness_note`, `guide`, `render_guide`, `channel_stats`.
