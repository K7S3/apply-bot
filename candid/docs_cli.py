"""Offline documentation command (batch 109).

Implements `python -m candid docs <subcommand>` using the docs_bundle,
docs_search, docs_export, and docs_check modules. Everything works offline;
the bundle ships inside the package under candid/data/docs/.
"""

from __future__ import annotations

import json

from candid import docs_bundle as B
from candid.docs_bundle import DocsError


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2))


def _cmd_list(a) -> None:
    topics = B.list_topics()
    if a.json:
        _print_json([{"slug": s, "title": t} for s, t in topics])
    else:
        for slug, title in topics:
            print(f"{slug} - {title}")


def _read_command_page(name: str) -> str:
    path = B.DOCS_DIR / "commands" / f"{name}.md"
    if not path.is_file():
        raise DocsError(f"no command reference for {name!r}")
    return path.read_text(encoding="utf-8")


def _cmd_show(a) -> None:
    md = B.get_topic(a.topic)
    print(md if a.raw else B.render_text(md))


def _cmd_search(a) -> None:
    from candid import docs_search as S
    topics = S.load_bundle_topics()
    titles = dict(B.list_topics())
    index = S.build_index(topics)
    results = S.search(" ".join(a.query), index, titles)[:a.limit]
    if a.json:
        _print_json([{"slug": s, "title": t, "snippet": sn}
                     for s, t, sn in results])
    else:
        if not results:
            print("No matches.")
            return
        for slug, title, snippet in results:
            print(f"* {title} ({slug})")
            print(f"  {snippet}")
            print()


def _cmd_command(a) -> None:
    md = _read_command_page(a.name)
    print(md if a.raw else B.render_text(md))


def _cmd_export(a) -> None:
    from candid import docs_export as E
    out = a.out
    if a.format == "html":
        path = E.export_html(out)
    else:
        path = E.export_txt(out)
    print(f"Wrote {path}")


def _cmd_version(a) -> None:
    from candid import __version__
    dv = B.docs_version()
    print(f"docs version:    {dv}")
    print(f"package version: {__version__}")
    if dv != __version__:
        print("warning: docs bundle does not match the installed version")


def _cmd_check(a) -> None:
    from candid import docs_check as C
    from candid.__main__ import COMMANDS
    problems = C.check_docs(list(COMMANDS), B.DOCS_DIR)
    if a.json:
        _print_json({"problems": problems})
    elif problems:
        print("Docs problems found:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("Docs OK: all commands documented, links and index consistent.")


_HANDLERS = {
    "list": _cmd_list,
    "show": _cmd_show,
    "search": _cmd_search,
    "command": _cmd_command,
    "export": _cmd_export,
    "version": _cmd_version,
    "check": _cmd_check,
}


def handle(a) -> None:
    """Dispatch a parsed `docs` args namespace to its subcommand."""
    handler = _HANDLERS.get(getattr(a, "what", None))
    if handler is None:
        raise DocsError(f"unknown docs subcommand {getattr(a, 'what', None)!r}")
    handler(a)
