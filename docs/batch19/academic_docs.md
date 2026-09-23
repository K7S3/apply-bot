# Academic CV + Research Statement (batch-19)

Two new grounded, profile-driven modules for academic / research job applications.
Nothing is ever invented: every section comes from your stored candid profile,
and sections with no data are omitted, never fabricated.

## `candid academic-cv`

Export an academic CV from your profile.

```bash
python -m candid academic-cv                 # LaTeX to stdout
python -m candid academic-cv --tex cv.tex    # write LaTeX file
python -m candid academic-cv --text          # plain text to stdout
```

Sections produced (only when the profile has data):

| Section            | Profile source        |
|--------------------|-----------------------|
| Education          | `education`           |
| Appointments       | `experience` (roles + bullets) |
| Publications       | `publications` (omitted if absent) |
| Teaching           | `teaching` (omitted if absent) |
| Grants and Service | `grants` + `service` (omitted if absent) |
| Skills             | `skills`              |

Notes:

- `publications`, `teaching`, `grants`, `service` are optional profile keys
  (strings or dicts). If they are missing or empty, the section is skipped
  cleanly — no empty headings.
- The LaTeX output is a complete `article`-class document, ASCII-safe, with
  all special characters (`& % $ # _ { } ~ ^ \`) escaped. Compile with
  `pdflatex cv.tex`.
- The module defines its own private `_latex_escape`; `candid.tailor` has no
  such helper in this worktree.

Example with a publication in the profile:

```json
// candid_data/profile.json (excerpt)
{"publications": [
  {"authors": "A. Rivera, B. Chen", "title": "Sparse attention at scale",
   "venue": "Proc. of MLConf", "year": "2023"}
]}
```

renders in LaTeX as:

```latex
\section*{Publications}
\begin{itemize}[leftmargin=*,itemsep=2pt]
\item A. Rivera, B. Chen (2023) "Sparse attention at scale." Proc. of MLConf
\end{itemize}
```

## `candid research-statement`

Generate a grounded research-statement draft from your profile.

```bash
python -m candid research-statement
python -m candid research-statement --lab "Vision Lab" --pi "Dr. Rao"
python -m candid research-statement --lab "Vision Lab" --out statement.md
```

The draft has four parts:

1. **Framing** — one paragraph; `--lab` / `--pi` tailor it to the target lab.
2. **Past Research** — bullets distilled ONLY from your profile's
   publications, projects, and experience bullets. Each bullet carries a
   *Source* tag (e.g. "experience: Research Scientist — Meridian AI Lab").
3. **Current Direction** — a synthesis of your summary, skills, domains, and
   most recent role. No future plans are stated here.
4. **Future Directions — SCAFFOLD** — clearly-marked prompts labeled
   **TODO: personalize**. These are questions for you to answer yourself
   before sending; they are never pre-filled with invented plans.

Groundedness rule: if a fact is not in your profile, it is not in the draft.
Add publications/projects to `candid_data/profile.json` to enrich sections 2
and 3.

## Wiring

Both modules expose `add_parsers(subparsers)` so the main CLI can register
them; e.g. in `candid/__main__.py`:

```python
from candid import academic_cv, research_statement
academic_cv.add_parsers(sub)
research_statement.add_parsers(sub)
```

## Tests

```bash
python3 -m unittest tests.test_academic_cv -v
```

18 tests, no network, temporary profile dir: full-profile section coverage,
graceful omission for minimal profiles, LaTeX escaping (no unescaped special
chars), ASCII safety, balanced braces, zero-invented-claims checks for the
research statement (scaffold TODOs present, no fabricated titles), and CLI
parser/file-output wiring.
