# Matching: score a job against your profile

Before you spend time on an application, score the job description (JD)
against your profile. The match report shows your fit score, the skills you
already have, the gaps, and what to emphasize in your application.

## The command

```bash
python -m candid match --jd jd.txt --company Acme --role "Data Scientist"
cat jd.txt | python -m candid match --jd - --company Acme
python -m candid match --app-id 3
python -m candid match --jd jd.txt --json
```

Flags:

- `--jd` — JD text, file path, URL, or `-` to read from stdin
- `--app-id` — tracked job id: pulls company/role/JD from the tracker
- `--company` — company name
- `--role` — role title
- `--location` — location (used in the report context)
- `--json` — print the raw match result as JSON, for scripting

## Reading the report

The report ranks your fit and calls out:

- **Matched skills** — your profile skills that appear in the JD. Lead with
  these in your resume and cover letter.
- **Gaps** — JD requirements not visible in your profile. Decide whether you
  can truthfully bridge them (a side project, a course, adjacent experience)
  or whether the role is a stretch.
- **Suggested emphasis** — which parts of your background the tailored
  application should foreground.

## Match score is a triage tool, not a verdict

A high score does not guarantee an interview; a low score does not mean you
cannot win the role. Use it to decide where to invest: tailor for the
high-fit roles, use `jobs curate --min-score N` to filter discovery, and
spend less time on long shots.

## Next steps after a good match

1. `tailor resume` / `tailor cover-letter` to build the application.
2. `track add` to put it in your pipeline.
3. `prep` when you get the interview.
