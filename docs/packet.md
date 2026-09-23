# Application packet export

`candid/packet.py` builds ONE PDF per tracked application containing the
**already-tailored** resume and cover letter, plus an optional references
page. It reuses `candid.tailor.build_resume` / `build_cover_letter` verbatim —
nothing is re-tailored or invented here (see the never-invent guarantee in
`docs/../candid/tailor.py`).

## Content resolution

1. `--app-id` fills `--company`/`--role` from the tracker record.
2. The JD comes from `--jd` (text, file, URL, or `-` for stdin) or falls back
   to the curated JD stored for the app (`jobs.get_job_meta`).
3. References come from `candid_data/references.json` (managed with
   `add_reference` / `list_references`) and are included **only** when the
   caller passes `include_references=True` — the references page is consent
   gated. If the flag is set with no saved references, `PacketError` tells
   you to add one first.

## API

```python
from candid import packet as P

pdf_bytes = P.build_packet(3, include_references=True)
dest = P.save_packet(3, "packet-acme.pdf", include_references=True,
                     jd="jd text ...", tone="formal")

P.add_reference("Sam Rivera", "former manager", "sam@example.com")
P.list_references()
```

`profile` and `path` (data-dir override) are optional parameters for tests
and scripting; by default the stored profile and the real data dir are used.
Errors raise `PacketError` with the next command embedded.

## The stdlib-only PDF writer

`requirements.txt` is stdlib-only by design (pypdf is optional, for parsing
only), so `packet.py` ships a minimal hand-rolled writer:

- US Letter pages, standard 14 fonts (Helvetica / Helvetica-Bold), no
  embedded fonts, no compression — byte-inspectable output.
- Each page: page title (14pt bold), body text (10pt, word-wrapped), and a
  `Page X of Y` footer.
- Non-Latin-1 glyphs (bullets, em dashes, smart quotes) are mapped to ASCII
  equivalents before encoding.
- Long documents flow across pages; continued pages are marked "(continued)".

Correctness is verified in `tests/test_packet.py`: output starts with
`%PDF`, parses in pypdf's strict mode, page counts and footers check out,
and extracted text matches the tailor-produced input.

## CLI (registration in CLI_REGISTRATION.txt)

```
python -m candid packet --app-id 3
python -m candid packet --app-id 3 --include-references --out packet-acme.pdf
python -m candid packet --app-id 3 --jd jd.txt --tone formal --length detailed
python -m candid references add --name "Sam Rivera" --relationship "former manager" --contact sam@example.com
python -m candid references list
```
