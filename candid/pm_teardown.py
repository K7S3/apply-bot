"""Product teardown generator: ``python -m candid pm teardown``.

Creates structured teardown template files for PM interview prep. The tool
never fabricates product facts — every section starts as a fill-in prompt
for the user to complete from their own hands-on use of the product.

Actions:

    new  --company X --product Y   create a new teardown template
    list                           list saved teardowns
    show NAME [--json]             print a saved teardown

Templates live in ``DATA_DIR/teardowns/`` and are plain Markdown, so they
can be edited in any editor and brought to the interview.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class TeardownError(Exception):
    """Raised when a teardown cannot be created, listed, or shown."""


def _teardowns_dir() -> Path:
    d = C.DATA_DIR / "teardowns"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:60]


def _template(company: str, product: str) -> str:
    """The blank teardown template — all sections are prompts, no facts."""
    return f"""<!-- candid-teardown | company: {company} | product: {product} -->
# Product Teardown — {product} ({company})

*Started {date.today().isoformat()}*

> **How to use this file:** every section below starts blank on purpose.
> Fill it in from your own hands-on use of the product — its onboarding,
> its docs, its pricing page, reviews, and your own sessions. Never copy
> marketing copy as your own opinion; interviewers want *your* critique.

## 1. Product overview

<!-- [TODO: In 2-3 sentences, what is this product and who pays for it?
How does it make money (subscription, ads, transaction cut, freemium)?] -->

## 2. Target users

<!-- [TODO: Who is the primary user? List 2-3 personas: who they are,
what job they are hiring this product to do, how often they use it.] -->

- Persona 1:
- Persona 2:
- Persona 3:

## 3. Strengths

<!-- [TODO: From your own use — what does this product do genuinely well?
Name specific moments, not adjectives. What would users miss most if it
disappeared tomorrow?] -->

-
-

## 4. Gaps and pain points

<!-- [TODO: Where did you personally get stuck, confused, or annoyed?
Note the exact screen and step. Check 2-3 app-store / G2 reviews and add
the complaints that keep recurring.] -->

-
-

## 5. Opportunities (with RICE scoring)

<!-- [TODO: Write 3 concrete opportunities below, then score each:
Reach = how many users it touches (1-10),
Impact = how much it moves the key metric (1-10),
Confidence = how sure you are (as a % — be honest),
Effort = person-weeks to ship.
RICE score = Reach x Impact x Confidence / Effort. Rank them.] -->

### Opportunity 1

<!-- [TODO: One-sentence opportunity, tied to a gap from section 4.] -->

### Opportunity 2

<!-- [TODO] -->

### Opportunity 3

<!-- [TODO] -->

| Opportunity | Reach (1-10) | Impact (1-10) | Confidence (%) | Effort (person-weeks) | RICE score | Rank |
|---|---|---|---|---|---|---|
| [Opportunity 1] |  |  |  |  |  |  |
| [Opportunity 2] |  |  |  |  |  |  |
| [Opportunity 3] |  |  |  |  |  |  |

_RICE = Reach x Impact x Confidence / Effort. Highest score first — but
flag any high-confidence, low-effort quick win even if it ranks second._

## 6. Interview talking points

<!-- [TODO: Boil this teardown down to a 2-minute spoken answer:
1) the product and its north star,
2) the one gap you would fix first and why,
3) the experiment you would run to validate the fix.] -->

- The product and its north star:
- The one gap I would fix first (and why):
- The experiment I would run:
"""


def new_teardown(company: str, product: str) -> Path:
    """Create a blank teardown template. Returns the file path.

    Raises TeardownError if company/product is missing.
    """
    if not (company or "").strip():
        raise TeardownError("company is required")
    if not (product or "").strip():
        raise TeardownError("product is required")
    company = company.strip()
    product = product.strip()
    C.ensure_data_dirs()
    slug = _safe_slug(f"{company}_{product}_{date.today().isoformat()}")
    path = _teardowns_dir() / f"{slug}.md"
    if path.exists():
        raise TeardownError(f"teardown already exists: {path}")
    path.write_text(_template(company, product), encoding="utf-8")
    return path


def _meta_of(path: Path) -> dict:
    company = product = ""
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        for part in first.strip("<!-> ").split("|"):
            if ":" in part:
                k, v = part.split(":", 1)
                k, v = k.strip(), v.strip()
                if k == "company":
                    company = v
                elif k == "product":
                    product = v
    except Exception:
        pass
    return {
        "name": path.stem,
        "company": company,
        "product": product,
        "path": str(path),
    }


def list_teardowns() -> list[dict]:
    """List saved teardown templates, newest first."""
    d = _teardowns_dir()
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return [_meta_of(p) for p in files]


def show_teardown(name: str) -> str:
    """Return the Markdown content of a teardown by name (stem or filename).

    Raises TeardownError when nothing matches.
    """
    name = (name or "").strip()
    if not name:
        raise TeardownError("teardown name is required")
    d = _teardowns_dir()
    stem = name[:-3] if name.endswith(".md") else name
    candidates = [d / f"{stem}.md"]
    matches = [p for p in candidates if p.exists()]
    if not matches:  # fuzzy: unique prefix match
        pref = [p for p in d.glob("*.md") if p.stem.startswith(stem)]
        matches = pref if len(pref) == 1 else []
    if not matches:
        raise TeardownError(f"no teardown found matching '{name}'")
    return matches[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI registration (wired by the coordinator under ``python -m candid pm``).
# ---------------------------------------------------------------------------

def _cmd_new(args) -> int:
    try:
        path = new_teardown(args.company, args.product)
    except TeardownError as e:
        print(f"error: {e}")
        return 1
    if args.json:
        print(json.dumps({"path": str(path)}, indent=2))
    else:
        print(f"Created teardown template: {path}")
        print("Fill in each section from your own use of the product — "
              "the tool never invents product facts.")
    return 0


def _cmd_list(args) -> int:
    items = list_teardowns()
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("No teardowns yet. Create one with: "
              "python -m candid pm teardown new --company X --product Y")
        return 0
    for i, t in enumerate(items, 1):
        label = f"{t['product']} ({t['company']})" if t["product"] else t["name"]
        print(f"{i}. {label}  [{t['name']}]")
    return 0


def _cmd_show(args) -> int:
    try:
        content = show_teardown(args.name)
    except TeardownError as e:
        print(f"error: {e}")
        return 1
    if args.json:
        print(json.dumps({"name": args.name, "markdown": content}, indent=2))
    else:
        print(content)
    return 0


def register_pm(pm_subparsers) -> None:
    """Register the ``teardown`` subcommand (new|list|show) on the ``pm`` parser."""
    p = pm_subparsers.add_parser(
        "teardown",
        help="Product teardown templates for PM interviews.",
        epilog="examples:\n"
               "  python -m candid pm teardown new --company Spotify --product \"Discover Weekly\"\n"
               "  python -m candid pm teardown list\n")
    sub = p.add_subparsers(dest="action", required=True,
                           title="actions", metavar="<action>")

    n = sub.add_parser("new", help="Create a blank teardown template.")
    n.add_argument("--company", required=True, help="Company name")
    n.add_argument("--product", required=True, help="Product to tear down")
    n.add_argument("--json", action="store_true",
                   help="Print the created path as JSON")
    n.set_defaults(func=_cmd_new)

    ls = sub.add_parser("list", help="List saved teardowns.")
    ls.add_argument("--json", action="store_true",
                    help="Print the list as JSON")
    ls.set_defaults(func=_cmd_list)

    sh = sub.add_parser("show", help="Show a saved teardown.")
    sh.add_argument("name", help="Teardown name (file stem or prefix)")
    sh.add_argument("--json", action="store_true",
                    help="Print as JSON instead of Markdown")
    sh.set_defaults(func=_cmd_show)
