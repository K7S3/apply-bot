"""Interactive CLI wizards for candid.

A small stdlib-only framework (:class:`Wizard`) plus five concrete wizards
that collect answers and return them as dicts keyed to the real CLI flag
names (see ``build_parser()`` in ``candid/__main__.py``), e.g.::

    answers = run_wizard("track-add")
    # {"company": "Acme", "role": "Data Scientist", "source": "Referral",
    #  "status": "applied"}

Navigation: at any prompt the user may type ``back`` to return to the
previous step, or ``quit`` / ``exit`` to abort (raises :class:`WizardAborted`).
Every wizard ends with a review screen listing all answers: press Enter to
confirm, type a step number to edit that step, or ``quit`` to abort.

``answers`` may be pre-seeded (session resume): any step whose key is already
present is skipped during the walk but still shown on the review screen.

Integration with ``candid.interactive`` (worker 1's module): the wizard reads
all input through ``interactive.ask`` (TTY gating, EOF handling, ``[default]``
rendering) and uses its ``InteractiveError`` plus the ``bold``/``dim``/``hint``
styling helpers. Choice / int / path / confirm steps are interpreted locally
on top of ``ask`` rather than via ``ask_choice``/``ask_confirm``/``ask_path``/
``ask_int`` because those helpers swallow the reserved words ``back`` /
``quit`` / ``exit`` inside their re-prompt loops; the wizard must intercept
them first. If ``candid.interactive`` is unavailable, a tiny local shim with
the same ``ask``/``InteractiveError``/styling names is used instead.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# interactive backend: candid.interactive when present, else a local shim
# ---------------------------------------------------------------------------

try:  # real module (worker 1)
    from candid import interactive as I

    InteractiveError = I.InteractiveError
    _HAVE_INTERACTIVE = True
except ImportError:  # tiny local shim with the same names
    _HAVE_INTERACTIVE = False

    class InteractiveError(Exception):
        """Raised for interactive-prompt failures."""


class WizardAborted(Exception):
    """Raised when the user types ``quit`` / ``exit`` during a wizard."""

    def __init__(self, partial=None):
        super().__init__("wizard aborted")
        #: Answers collected before the abort. The CLI auto-saves these so
        #: the wizard can be resumed later with ``--resume-from``.
        self.partial = dict(partial or {})


class _GoBack(Exception):
    """Internal: user typed ``back``; return to the previous step."""


_RESERVED = {"back": _GoBack, "quit": WizardAborted, "exit": WizardAborted}


if not _HAVE_INTERACTIVE:  # noqa: E402  (conditional shim definition)

    def _shim_ask(prompt, default=None, validator=None, required=False,
                  password=False):
        shown = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
        while True:
            raw = input(shown).strip()
            sig = _RESERVED.get(raw.lower())
            if sig is not None:
                raise sig("")
            if raw == "" and default is not None:
                return default
            if raw == "" and required:
                print("  A value is required.")
                continue
            if validator is not None:
                ok = validator(raw)
                if ok is not True:
                    print(f"  {ok if isinstance(ok, str) else 'Invalid input.'}")
                    continue
            return raw

    class _ShimModule:
        InteractiveError = InteractiveError
        ask = staticmethod(_shim_ask)

        @staticmethod
        def bold(t): return t

        @staticmethod
        def dim(t): return t

        @staticmethod
        def hint(t): print(f"hint: {t}")

    I = _ShimModule()


# ---------------------------------------------------------------------------
# Wizard framework
# ---------------------------------------------------------------------------

# step dict keys:
#   key        -> answers dict key (a CLI flag name, no leading dashes)
#   prompt     -> text shown to the user
#   kind       -> 'text' | 'choice' | 'confirm' | 'path' | 'int'
#   options    -> list of strings (kind='choice')
#   default    -> default value (Enter keeps it)
#   validator  -> callable(str) -> True | error-string | raises ValueError
#   required   -> bool (kind='text'/'path'): blank input re-prompts
#   must_exist -> bool (kind='path'): path must exist on disk
#   allow_custom -> bool (kind='choice'): extra "Other (type your own)" option


class Wizard:
    """A linear, navigable multi-step prompt flow."""

    def __init__(self, name: str, steps: list[dict], title: str | None = None):
        self.name = name
        self.steps = steps
        self.title = title or name

    # -- input primitive ---------------------------------------------------

    def _prompt(self, prompt: str, default=None) -> str:
        """Read one line via interactive.ask; reserved words raise nav signals.

        Returns the stripped string. Empty input yields ``default`` (handled
        by ask itself); ``back`` raises _GoBack, ``quit``/``exit`` raise
        WizardAborted.
        """
        d = None if default in ("", None) else str(default)
        try:
            raw = I.ask(prompt, default=d)
        except _GoBack:
            raise
        if isinstance(raw, str):
            sig = _RESERVED.get(raw.strip().lower())
            if sig is not None:
                raise sig("")
            return raw.strip()
        return raw

    # -- per-kind readers ----------------------------------------------------

    def _read_text(self, step: dict, default):
        shown = default if default not in (None, "") else None
        while True:
            val = self._prompt(step["prompt"], default=shown)
            if val == "":
                if step.get("required"):
                    print("  A value is required.")
                    continue
                return ""
            validator = step.get("validator")
            if validator is not None:
                try:
                    ok = validator(val)
                except ValueError as e:
                    print(f"  {e}")
                    continue
                if ok is False:
                    print("  Invalid value, try again.")
                    continue
                if isinstance(ok, str):
                    print(f"  {ok}")
                    continue
            return val

    def _read_choice(self, step: dict, default):
        options = list(step["options"])
        labels = options + (["Other (type your own)"]
                            if step.get("allow_custom") else [])
        print(I.bold(step["prompt"]))
        for i, label in enumerate(labels, 1):
            marker = " (default)" if default is not None and label == default else ""
            print(f"  {i}. {label}{marker}")
        while True:
            val = self._prompt("Choose [number or name]", default=default)
            if val == "":
                if default is not None:
                    return default
                print("  Pick one of the listed options.")
                continue
            picked = None
            if val.isdigit():
                idx = int(val) - 1
                if 0 <= idx < len(labels):
                    picked = labels[idx]
            else:
                for label in labels:
                    if label.lower() == val.lower():
                        picked = label
                        break
            if picked is None:
                print(f"  Pick a number 1-{len(labels)} or an option name.")
                continue
            if step.get("allow_custom") and picked == labels[-1]:
                custom = self._prompt("Your value")
                if custom == "":
                    print("  A value is required.")
                    continue
                return custom
            return picked

    def _read_confirm(self, step: dict, default):
        d = default if isinstance(default, bool) else False
        while True:
            val = self._prompt(f"{step['prompt']} [{'Y/n' if d else 'y/N'}]")
            if val == "":
                return d
            if val.lower() in ("y", "yes"):
                return True
            if val.lower() in ("n", "no"):
                return False
            print("  Please answer y or n.")

    def _read_path(self, step: dict, default):
        shown = default if default not in (None, "") else None
        while True:
            val = self._prompt(step["prompt"], default=shown)
            if val == "":
                if step.get("required"):
                    print("  A value is required.")
                    continue
                return ""
            expanded = os.path.expanduser(val)
            if step.get("must_exist") and not os.path.exists(expanded):
                print(f"  No such file or directory: {val}")
                continue
            return expanded

    def _read_int(self, step: dict, default):
        dflt = 0 if default in (None, "") else default
        while True:
            val = self._prompt(step["prompt"], default=dflt)
            try:
                n = int(val)
            except (TypeError, ValueError):
                print(f"  Enter a whole number (got {val!r}).")
                continue
            if n < 0:
                print("  Enter 0 or more (blank skips).")
                continue
            return n

    def _ask_step(self, step: dict, current):
        kind = step.get("kind", "text")
        default = current if current not in (None, "") else step.get("default")
        if kind == "text":
            return self._read_text(step, default)
        if kind == "choice":
            return self._read_choice(step, default)
        if kind == "confirm":
            return self._read_confirm(step, default)
        if kind == "path":
            return self._read_path(step, default)
        if kind == "int":
            return self._read_int(step, default)
        raise InteractiveError(f"Unknown step kind: {kind!r}")

    # -- main loop ----------------------------------------------------------

    def run(self, answers: dict | None = None) -> dict:
        """Walk the steps, then show a review screen. Returns answers dict.

        On abort, the raised :class:`WizardAborted` carries ``.partial``
        with the answers collected so far.
        """
        answers = dict(answers or {})
        try:
            return self._run_inner(answers)
        except WizardAborted as e:
            e.partial = dict(answers)
            raise

    def _run_inner(self, answers: dict) -> dict:
        """Walk the steps, then show a review screen. Returns answers dict."""
        preseeded = set(answers)  # first-pass only: skip, still reviewable
        total = len(self.steps)
        print(I.dim(f"== {self.title} =="))
        I.hint("type 'back' for the previous step, 'quit' to abort")
        print()

        i = 0
        while i < total:
            step = self.steps[i]
            if step["key"] in preseeded:
                preseeded.discard(step["key"])
                i += 1
                continue
            current = answers.get(step["key"], step.get("default"))
            print(I.dim(f"[Step {i + 1}/{total}]"))
            try:
                answers[step["key"]] = self._ask_step(step, current)
            except _GoBack:
                if i > 0:
                    i -= 1
                    print("  (back)")
                else:
                    print("  (already at the first step)")
                continue
            i += 1

        return self._review(answers)

    def _review(self, answers: dict) -> dict:
        """Final review screen: confirm, edit a step number, or abort."""
        while True:
            print("\n-- Review --")
            for n, step in enumerate(self.steps, 1):
                print(f"  {n}. {step['prompt']}: {answers.get(step['key'], '')}")
            try:
                raw = self._prompt(
                    "Confirm? [Enter=yes, step number=edit, "
                    "back=redo last, quit=abort]")
            except _GoBack:
                return self._resume_from(len(self.steps) - 1, answers)
            if raw == "":
                print("Done.\n")
                return answers
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= len(self.steps):
                    return self._resume_from(n - 1, answers)
            print("  Press Enter to confirm, or type a step number.")
            # WizardAborted from _prompt propagates: abort.

    def _resume_from(self, index: int, answers: dict) -> dict:
        """Re-run from step ``index`` (existing answers become defaults)."""
        total = len(self.steps)
        i = index
        while i < total:
            step = self.steps[i]
            current = answers.get(step["key"], step.get("default"))
            print(I.dim(f"[Step {i + 1}/{total}] (editing)"))
            try:
                answers[step["key"]] = self._ask_step(step, current)
            except _GoBack:
                if i > 0:
                    i -= 1
                continue
            i += 1
        return self._review(answers)


# ---------------------------------------------------------------------------
# step-builder helpers
# ---------------------------------------------------------------------------


def _text(key, prompt, *, required=False, default=None, validator=None):
    return {"key": key, "prompt": prompt, "kind": "text",
            "required": required, "default": default, "validator": validator}


def _path(key, prompt, *, required=False, must_exist=False, default=None):
    return {"key": key, "prompt": prompt, "kind": "path",
            "required": required, "must_exist": must_exist, "default": default}


def _choice(key, prompt, options, *, default=None, allow_custom=False):
    return {"key": key, "prompt": prompt, "kind": "choice",
            "options": list(options), "default": default,
            "allow_custom": allow_custom}


def _int(key, prompt, *, default=0):
    return {"key": key, "prompt": prompt, "kind": "int", "default": default}


def _nonneg_int(key, prompt):
    """Money-ish int field: blank/0 skips, negatives rejected."""
    return _int(key, f"{prompt} (0/blank to skip)", default=0)


# ---------------------------------------------------------------------------
# concrete wizards (answers keyed to real CLI flag names)
# ---------------------------------------------------------------------------


def onboard_wizard() -> Wizard:
    """onboard: resume path (must exist) + optional LinkedIn ZIP export."""
    return Wizard("onboard", [
        _path("resume", "Resume file (.pdf/.md/.txt)",
              required=True, must_exist=True),
        _path("linkedin", "LinkedIn export ZIP (blank to skip)",
              required=False, must_exist=True),
    ], title="Onboard - ingest resume / LinkedIn")


def tailor_wizard() -> Wizard:
    """tailor resume: jd + company/role + tone + length.

    Tone/length choices mirror the real ``tailor resume`` flags
    (--tone: concise/confident/formal/warm, --length: one-page/detailed).
    """
    return Wizard("tailor", [
        _path("jd", "Job description file", required=True, must_exist=True),
        _text("company", "Company name", required=True),
        _text("role", "Role title", required=True),
        _choice("tone", "Tone",
                ["confident", "warm", "concise", "formal"],
                default="confident"),
        _choice("length", "Length",
                ["one-page", "detailed"],
                default="one-page"),
    ], title="Tailor resume")


def track_add_wizard() -> Wizard:
    """track add: company + role + source + status.

    Note: ``track add`` has no --source flag; ``source`` is collected so the
    caller can fold it into --notes (e.g. "Source: referral"). Statuses come
    from candid.config.STATUSES.
    """
    from candid import config as _C  # local import: keep module import-light
    return Wizard("track-add", [
        _text("company", "Company", required=True),
        _text("role", "Role", required=True),
        _choice("source", "Where did you find this role?",
                ["LinkedIn", "Indeed", "Company website", "Referral",
                 "Recruiter", "Job board"],
                default="LinkedIn", allow_custom=True),
        _choice("status", "Status", list(_C.STATUSES), default="saved"),
    ], title="Track - add application")


def offer_add_wizard() -> Wizard:
    """offer add: company/role + money fields (ints; 0/blank skips).

    Key mapping to real flags: base -> --base, bonus -> --bonus-first
    (guaranteed first-year $), sign_on -> --sign-on, equity -> --equity.
    """
    return Wizard("offer-add", [
        _text("company", "Company", required=True),
        _text("role", "Role", required=True),
        _nonneg_int("base", "Base salary ($)"),
        _nonneg_int("bonus", "First-year guaranteed bonus ($)"),
        _nonneg_int("sign_on", "Sign-on bonus ($)"),
        _nonneg_int("equity", "Total equity grant ($)"),
        _text("notes", "Notes (blank to skip)"),
    ], title="Offer - record offer")


def prep_wizard() -> Wizard:
    """prep: company + role + optional jd file."""
    return Wizard("prep", [
        _text("company", "Company", required=True),
        _text("role", "Role", required=True),
        _path("jd", "Job description file (blank to skip)",
              required=False, must_exist=True),
    ], title="Prep - interview prep pack")


WIZARDS = {
    "onboard": onboard_wizard,
    "tailor": tailor_wizard,
    "track-add": track_add_wizard,
    "offer-add": offer_add_wizard,
    "prep": prep_wizard,
}


def run_wizard(name: str, answers: dict | None = None) -> dict:
    """Build and run the named wizard. Raises ValueError on unknown name."""
    try:
        factory = WIZARDS[name]
    except KeyError:
        raise ValueError(
            f"Unknown wizard {name!r}. Choose from: {', '.join(sorted(WIZARDS))}"
        ) from None
    return factory().run(answers)
