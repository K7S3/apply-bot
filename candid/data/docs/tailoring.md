# Tailoring: resume and cover letter

Generic resumes lose to tailored ones. Give candid the JD and it rewrites
your resume bullets and cover letter to foreground the experience that
matches the role — using only what is in your profile. It never invents
jobs, skills, or dates.

## The commands

```bash
python -m candid tailor resume --jd jd.txt --company Acme --role "Data Scientist"
python -m candid tailor cover-letter --app-id 3 --hook "I loved your infra blog"
python -m candid tailor resume --jd jd.txt --out tailored-acme.md
```

Both subcommands (`resume` and `cover-letter`) accept:

- `--jd` — JD text, file path, URL, or `-` (stdin)
- `--app-id` — tracked job id: pulls company/role/JD from the tracker
- `--company`, `--role` — used directly or filled from the tracker record
- `--tone` — `concise`, `confident` (default), `formal`, or `warm`
- `--out` — write to a file instead of printing to stdout
- `resume` only: `--length` — `one-page` (default) or `detailed`
- `cover-letter` only: `--hook` — one-line "why this company" sentence;
  cover letters also require `--company` and `--role` (or `--app-id`)

## How to use it well

1. **Match first.** Run `python -m candid match` on the JD so you know the
   gaps the tailor will try to bridge.
2. **Read what it wrote.** Tailored output is a draft, not a submission.
   Check every bullet against your real experience; fix anything that
   overstates.
3. **Keep one source of truth.** Your profile is the input. If a tailored
   bullet keeps coming out weak, improve the profile (`onboard` again with a
   better resume), not the output.

## Output formats

- Stdout by default, so you can pipe it: `--out tailored-acme.md` saves it.
- `one-page` fits the standard single-page resume convention; `detailed`
  is for roles that expect more depth (e.g. staff-level applications).

## Truthfulness rule

candid only rearranges and emphasizes what your profile contains. If a
bullet does not match your real experience, rewrite it or drop it — never
submit claims you cannot defend in an interview.
