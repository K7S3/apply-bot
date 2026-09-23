# Export formats (Obsidian, .eml, vCard)

`python -m candid export` converts candid's own artifacts into formats other
tools understand. All exporters consume real candid outputs (saved prep packs
from `prep`, drafts from `followup`); nothing is invented.

## Commands

### `export prep-obsidian`

Splits a saved interview prep pack (`candid_data/prep_packs/`) into an
Obsidian vault folder:

```bash
python -m candid prep --company "Acme Corp" --role "Data Scientist"   # build the pack first
python -m candid export prep-obsidian --company "Acme Corp" --role "Data Scientist" --out ~/vault
```

Creates `~/vault/Prep - Acme Corp - Data Scientist/` containing:

| File | Contents |
|---|---|
| `Prep - Acme Corp - Data Scientist.md` | Index note: YAML frontmatter (`company`, `role`, `date`, `tags`, `source`) + `[[wikilinks]]` to the child notes |
| `Questions.md` | Company-specific + general prep questions + the tailored mock interview |
| `Concepts.md` | Concept deep-dives |
| `STAR stories.md` | STAR story prompts mapped to your resume bullets |
| `Checklist.md` | Priority focus, comp benchmark/talking points, research + day-before checklists |

Pack section mapping follows the real headings produced by `prep.build_pack`
(`## 1. Company-specific questions …`, `## 2. General preparation questions`,
`## 3. Concept deep-dives`, `## 4. Mock interview …`, `## 5. STAR story prompts …`,
`## 6. Compensation benchmark`, `## 7. Company-research checklist`,
`## 8. Day-Before Checklist`). Sections the pack does not have (e.g. older
pack shapes) get a placeholder line in their note instead of failing.

If several packs match the company/role, the newest is used. Export fails with
a clear message when no pack exists.

### `export followup-eml`

Generates a draft with `followup.thank_you` / `check_in` / `referral_ask` and
writes it as an RFC-compliant `.eml` file (Subject/To/From/Date headers,
plain-text body), importable by any mail client:

```bash
python -m candid export followup-eml --kind thank-you --company "Acme Corp" \
    --role "Data Scientist" --to recruiter@acme.com \
    --counterparty Priya --out thank-you.eml
```

Options: `--kind thank-you|check-in|referral` (required), `--company`
(required), `--role`, `--to` (omit to leave To: blank but valid), `--out`
(required), `--counterparty` (interviewer/recruiter/contact name; generic
greeting if omitted), `--tone warm|formal|concise|enthusiastic`
(thank-you / check-in only), `--sender-name` (defaults to your profile name),
`--sender-email` (From: header).

The draft's own `Subject:` line becomes the message subject; the timing note
(`*Timing: …*`) is kept at the end of the body.

### `export contact-vcard`

Writes a contact as a vCard 3.0 `.vcf` file (RFC 2426 text escaping,
CRLF line endings):

```bash
python -m candid export contact-vcard --name "Jane Doe" --email jane@example.com \
    --org "Acme Corp" --title Recruiter --phone "+1 555-0100" --out jane.vcf
```

Options: `--name` and `--email` (required), `--phone`, `--org`, `--title`,
`--out` (default `contact.vcf`).

There is intentionally no batch `contacts-vcard` command: candid has no
networking-contacts store, so there is nothing to batch-export from.

## API

The same functions back the CLI and are importable for scripting:

- `exports.find_prep_pack(company, role) -> Path | None`
- `exports.export_prep_obsidian(company, role, out_dir) -> Path`
- `exports.export_followup_eml(kind, company, role="", to="", out=…, counterparty="", tone="warm", sender_name="", sender_email="") -> Path`
- `exports.export_contact_vcard(name, email, phone="", org="", title="", out="contact.vcf") -> Path`
- `exports.register(subparsers)` - adds the top-level `export` command; called
  by the coordinator's CLI wiring (phase 2).
