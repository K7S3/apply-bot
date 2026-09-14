# Test fixtures

Fake end-to-end test data for the apply-bot. **Nothing here is real** — all
names, emails, and companies are invented for testing.

- `jobs/data-scientist-acme.html` — straightforward application form
- `jobs/ml-engineer-initech.html` — straightforward form, different field labels
- `jobs/data-analyst-hooli.html` — fake login wall (exercises the `needs_manual` path)
- `applications-test.xlsx` — 3 rows pointing at the pages above via `file://` URLs,
  with `resume_doc_link` left empty so the `resumes/` fallback is exercised

Run the fixtures (needs a Gemini key for the review step, or stub it):

```bash
python -m applybot --excel samples/applications-test.xlsx --dry-run
```

The matching fallback resumes live in `../resumes/` (`Acme_Data_Scientist.txt`, etc.).
