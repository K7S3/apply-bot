"""Interactive triage of tracked job applications.

Walks the tracker (oldest/least-recently-updated first), shows a one-line
summary per app, and prompts for an action per app:

    [k]eep / [u]pdate stage / [n]ote / [a]rchive / [q]uit

- [u] prompts for a stage drawn from tracker's real status set
  (``candid.config.STATUSES``).
- [n] prompts for note text, appended to the app's existing notes via
  ``tracker.update(notes=...)`` (update replaces notes, so the append is
  done here before the call).
- [a] marks the app "withdrawn" (tracker has no "archived" status;
  ``ARCHIVE_STATUS`` resolves to "archived" only if tracker ever supports it).
- [q] stops the walk and returns immediately.

``answers`` lets callers script the session without stdin (used by tests
and by non-interactive wrappers). When ``answers`` is None, input comes
from ``input()`` and a non-TTY stdin raises ``TriageError`` instead of
hanging.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from candid import config as C
from candid import tracker as T


class TriageError(Exception):
    """Raised when interactive triage cannot run (e.g. no TTY)."""


# tracker's accepted statuses come from config.STATUSES via tracker.update's
# validation; "archived" is not a supported status, so archiving means "withdrawn".
ARCHIVE_STATUS = "archived" if "archived" in C.STATUSES else "withdrawn"


def _ask(prompt: str, script, out, lower: bool = True) -> str:
    """Read one answer: from the script iterator, or from stdin."""
    out.write(prompt)
    flush = getattr(out, "flush", None)
    if callable(flush):
        flush()
    if script is not None:
        try:
            ans = str(next(script))
        except StopIteration:
            ans = "q"  # scripted answers exhausted: stop gracefully
        out.write(ans + "\n")
    else:
        ans = input()
    return ans.strip().lower() if lower else ans.strip()


def _one_line(app: dict) -> str:
    return (f"[{app.get('id')}] {app.get('company', '?')} - "
            f"{app.get('role', '?')} "
            f"({app.get('status', '?')}, updated {app.get('date_updated', '')})")


def triage(answers: Iterable[str] | None = None, path=None, stream=None) -> dict:
    """Review each tracked app and act on it. Returns a summary dict."""
    out = stream if stream is not None else sys.stdout
    script = iter(answers) if answers is not None else None
    if script is None and not sys.stdin.isatty():
        raise TriageError(
            "Interactive triage needs a TTY (stdin is not a terminal). "
            "Pass `answers=[...]` to script the session instead."
        )

    apps = sorted(
        T.list_apps(path=path),
        key=lambda a: (a.get("date_updated", ""), a.get("date_added", ""),
                       a.get("id", 0)),
    )
    if not apps:
        out.write("No applications to review.\n")
        return {"reviewed": 0, "updated": 0, "archived": 0, "quit": False}

    out.write(f"Reviewing {len(apps)} application(s), least recently updated first.\n")
    reviewed = updated = archived = 0
    quit_ = False
    for app in apps:
        app_id = app["id"]
        out.write(_one_line(app) + "\n")
        action = _ask("[k]eep / [u]pdate stage / [n]ote / [a]rchive / [q]uit: ",
                      script, out)
        reviewed += 1
        if action == "q":
            quit_ = True
            break
        elif action == "u":
            stage = _ask(f"new stage ({', '.join(C.STATUSES)}): ", script, out)
            while stage not in C.STATUSES:
                out.write(f"Unknown stage '{stage}'. Choose from: "
                          f"{', '.join(C.STATUSES)}\n")
                stage = _ask("new stage: ", script, out)
            T.update(app_id, status=stage, path=path)
            updated += 1
            out.write(f"  -> stage set to '{stage}'.\n")
        elif action == "n":
            note = _ask("note: ", script, out, lower=False)
            if note:
                existing = (app.get("notes") or "").strip()
                combined = f"{existing}\n{note}".strip() if existing else note
                T.update(app_id, notes=combined, path=path)
                updated += 1
                out.write("  -> note added.\n")
            else:
                out.write("  -> empty note, skipped.\n")
        elif action == "a":
            T.update(app_id, status=ARCHIVE_STATUS, path=path)
            archived += 1
            out.write(f"  -> archived (status='{ARCHIVE_STATUS}').\n")
        else:  # "k" or anything unrecognized: keep, don't nag
            out.write("  -> kept.\n")

    out.write(f"Done: {reviewed} reviewed, {updated} updated, "
              f"{archived} archived.\n")
    return {"reviewed": reviewed, "updated": updated, "archived": archived,
            "quit": quit_}
