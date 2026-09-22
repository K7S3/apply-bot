# Offer letter parser (`offer parse`)

`python -m candid offer parse letter.pdf --company Acme --role "Data Scientist" [--yes]`

Reads an offer letter PDF (via `pypdf`, the same dependency `onboard` uses
for resume PDFs; `.txt`/`.md` also accepted) and extracts comp fields into
the offer normalizer (`candid/offer.py`), replacing manual entry.

## Flow

1. Extract text from the PDF.
2. Print **every extracted field with the source snippet** it came from.
3. List fields **not found** (left blank, never guessed) and benefit mentions.
4. Ask for confirmation before writing to `candid_data/offers.json`
   (`--yes` skips the prompt).

## Extraction heuristics (regex only)

| Field | Patterns matched (case-insensitive) |
|---|---|
| `base` | "annual base salary of $X", "base salary ... $X", "base pay ... $X", "annual salary ... $X" |
| `bonus_target_pct` | "target bonus of X%", "bonus ... X% of base", "X% target bonus"; "bonus ... X%" within one sentence |
| `bonus_first_year_guaranteed` | "guaranteed (first-year) bonus of $X" |
| `sign_on` | "sign-on bonus of $X", "$X sign-on bonus", "one-time ... bonus/payment of $X" |
| `equity_total` | "RSUs with a grant value of $X", "grant value of $X", "$X in RSUs", "equity grant of $X" |
| `equity_shares` | "1,200 restricted stock units" / "1,200 RSUs" (share count; kept in notes, not converted to $) |
| `equity_type` | `rsu` if RSU/restricted-stock-unit mentioned, `options` if stock options/NSO/ISO |
| `vest_years` | "vest over 4 years", "4-year vesting", "vesting period of 4 years" |
| `vest_schedule` | "25/25/25/25" style lists summing to 100, or "25% annually" (expanded to an even split) |
| `start_date` | "start date ... Month DD, YYYY" |
| benefit mentions | 401(k), health/medical, dental, vision, PTO (incl. days), vacation, parental leave, life insurance, disability, HSA/FSA - recorded in notes; `benefits_value` is NOT auto-estimated |

Amounts accept `$190,000`, `$190000`, `$190K`/`$190k`. First match wins per
field (patterns ordered most-specific first).

## Limits (honest)

- **Heuristic, not perfect.** Novel phrasings ("total comp of $X", tables,
  footnotes) will be missed. Review the printed snippets before confirming.
- **No number is ever invented.** Missing fields stay blank; check the
  "Not found in letter" list and fill gaps with `offer add` flags if needed.
- **Equity share counts are not converted to dollars** - there is no share
  price in the letter. If the letter gives both a share count and a grant
  value, the grant value feeds the $ math and the count goes in notes.
- **`benefits_value` is never auto-filled.** Benefit mentions are keywords
  (401(k), health insurance, PTO...), not dollar estimates; set a benefits
  estimate yourself via `offer add --benefits`.
- **Scanned/image PDFs fail cleanly** with an error telling you to export
  the letter as text. The parser reads embedded text only, no OCR.
- Confirmation is interactive by default; use `--yes` only when you have
  reviewed the extraction (e.g. in scripts after a first manual run).
