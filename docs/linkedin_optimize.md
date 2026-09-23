# LinkedIn optimizer (`candid/linkedin_optimize.py`)

Turns your onboarded profile into LinkedIn-ready copy: headline options,
an about-section draft, per-role experience suggestions, and keyword gaps.

**Groundedness rule:** every suggestion traces back to `candid_data/profile.json`.
Titles, companies, metrics, and skills are never invented. Keyword gaps are
framed as "consider adding if true" questions, never auto-added.

## Functions

- `suggest_headline(profile, n=3)` — `n` headline options, each ≤ 220 chars,
  built from your real title, company, skills, seniority, and domain tags.
- `suggest_about(profile, open_to_work=False)` — first-person about draft
  (2-3 short paragraphs: who you are, experience arc, skills + education).
  The open-to-work closing line appears **only** when `open_to_work=True`.
- `polish_about(current_text, profile)` — rewrites your existing about
  section while preserving your voice (person, sentence length,
  contractions, formality markers, emoji). Returns
  `{"polished", "voice_notes", "changes"}`.
- `suggest_experience(profile, about_text="")` — per role: a clean title
  line, title-mismatch flags (e.g. the about text claims a different title
  at the same company), 3-4 bullet suggestions quoted from your resume,
  and profile skills to tag.
- `keyword_gaps(profile)` — missing seniority/domain keywords as
  suggestions; never modifies the profile.
- `full_report(profile, open_to_work=False, about_text="")` — all of the
  above rendered as markdown.

## Example

```python
from candid import profile as P
from candid import linkedin_optimize as LO

prof = P.load_profile()                       # honors CANDID_DATA_DIR
print(LO.suggest_headline(prof))
print(LO.suggest_about(prof, open_to_work=True))
out = LO.polish_about("i'm a data scientist. i love sql 🚀", prof)
print(out["polished"])
print("\n".join(out["voice_notes"]))
print(LO.full_report(prof))
```

## Tests

```sh
python3 -m pytest tests/test_linkedin_optimize.py -q
```
