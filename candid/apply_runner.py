"""Supervised apply runner: the state machine that drives job applications.

Flow
----
apply()  -> fill safe fields, upload resume; parks at review by default.
            Pass auto_submit=True to submit once the form is clean.
            Sensitive/unknown fields become needs_input items and are never
            guessed. Every run writes run.log + screenshots under
            runs/<job_id>/<ts>/.
answer() -> record the user's explicit answers to needs_input questions
approve() -> manual gate: record explicit approval to submit (who + when)
submit() -> manual gate: only runs when an approval is on record

Even with auto_submit=True, any unresolved needs_input item parks the job
instead of submitting. Submitting always requires a clean form (or, via the
manual path, an explicit approval with no open questions).

Testing hook
------------
Sibling modules (apply_state, apply_jobs, apply_profile, apply_adapters,
apply_browser) are imported at module level inside try/except so that
``import candid.apply_runner`` succeeds even when they are absent (they are
built by sibling workers). All runner logic reaches them through the
module-level names ``apply_state``, ``apply_jobs``, ``apply_profile``,
``pick_adapter`` and ``B``; tests monkeypatch those attributes with fakes,
e.g. ``monkeypatch.setattr(R, "B", fake_browser)``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from candid import apply_state
except ImportError:  # sibling worker builds this
    apply_state = None  # type: ignore[assignment]

try:
    from candid import apply_jobs
except ImportError:  # sibling worker builds this
    apply_jobs = None  # type: ignore[assignment]

try:
    from candid import apply_profile
except ImportError:  # sibling worker builds this
    apply_profile = None  # type: ignore[assignment]

try:
    from candid.apply_adapters import pick as pick_adapter
except ImportError:  # sibling worker builds this
    pick_adapter = None  # type: ignore[assignment]

try:
    from candid import apply_browser as B
except ImportError:  # sibling worker builds this
    B = None  # type: ignore[assignment]


SUBMIT_LABELS = ["submit application", "submit"]
SUCCESS_MARKERS = [
    "thank you for applying",
    "application submitted",
    "application received",
    "successfully submitted",
]


class ApplyError(Exception):
    """Every user-facing runner error. candid's CLI maps this to clean output."""


def _require(mod, name: str):
    if mod is None:
        raise ApplyError(
            f"candid.{name} is not available in this install; "
            "the runner cannot proceed."
        )
    return mod


def _need_to_dict(need) -> dict:
    """Serialize a Need (dataclass or plain object) for state storage."""
    if isinstance(need, dict):
        return dict(need)
    try:
        return asdict(need)
    except Exception:  # noqa: BLE001
        pass
    return {
        "field_id": getattr(need, "field_id", None),
        "label": getattr(need, "label", None),
        "kind": getattr(need, "kind", None),
        "control": getattr(need, "control", None),
        "options": getattr(need, "options", None),
    }


class Runner:
    def __init__(self, store=None):
        if store is None:
            mod = _require(apply_state, "apply_state")
            store = mod.Store()
        self.store = store

    # -- apply ----------------------------------------------------------
    def apply(self, job_path: str, headless: bool = True,
              auto_submit: bool = False) -> dict:
        """Fill the form; park at review unless auto_submit=True and clean.

        Sensitive/unknown fields become needs_input items and are never
        guessed. The default (auto_submit=False) never submits. Even with
        auto_submit=True, unresolved needs park the job instead of submitting.
        """
        _require(apply_jobs, "apply_jobs")
        _require(apply_profile, "apply_profile")
        _require(pick_adapter, "apply_adapters")
        _require(B, "apply_browser")

        job = apply_jobs.JobSpec.load(job_path)
        resume_pdf = apply_jobs.resolve_resume(job)
        profile = apply_profile.load_apply_profile()

        data = self.store.transition(job.id, "filling", f"applying to {job.url}")
        data["job"] = {
            "company": job.company,
            "role": job.role,
            "url": job.url,
            "resume_pdf": job.resume_pdf,
            "ats": job.ats,
        }

        run_dir = Path(self.store.run_dir(job.id))
        run_dir.mkdir(parents=True, exist_ok=True)
        log = (run_dir / "run.log").open("w", encoding="utf-8")

        def say(msg: str) -> None:
            print(msg)
            log.write(msg + "\n")
            log.flush()

        try:
            with B.launch(headless=headless) as page:
                say(f"opening {job.url}")
                page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                blocker = B.detect_blockers(page)
                if blocker:
                    say(f"BLOCKED: {blocker}")
                    page.screenshot(path=str(run_dir / "blocked.png"))
                    self.store.transition(job.id, "blocked", blocker)
                    return self._finish(log, job.id, {"blocked": blocker})

                adapter = pick_adapter(page, job.ats)
                say(f"adapter: {adapter.name}")
                answered = data.get("answers", {})
                result = adapter.fill(page, profile, resume_pdf, answered)

                say(
                    f"filled {len(result.filled)} fields; "
                    f"{len(result.needs)} need input; "
                    f"resume uploaded: {result.resume_uploaded}"
                )
                for note in result.notes:
                    say(f"note: {note}")

                page.screenshot(path=str(run_dir / "review.png"), full_page=True)

                data = self.store.load(job.id)
                data["filled"] = list(result.filled)
                data["resume_uploaded"] = result.resume_uploaded
                # merge new needs with already-known ones
                known = {n["field_id"] for n in data.get("needs", [])}
                for need in result.needs:
                    if need.field_id not in answered and need.field_id not in known:
                        data.setdefault("needs", []).append(_need_to_dict(need))
                # drop needs that are now answered
                data["needs"] = [
                    n for n in data.get("needs", []) if n["field_id"] not in answered
                ]
                self.store.save(job.id, data)

                if data["needs"]:
                    say(f"PARKED: {len(data['needs'])} questions need your answers.")
                    for n in data["needs"]:
                        say(f"  - [{n.get('kind')}] {n.get('label')}")
                    self.store.transition(
                        job.id, "needs_input", f"{len(data['needs'])} questions open"
                    )
                elif auto_submit:
                    self._do_submit(page, job, run_dir, say)
                else:
                    say("PARKED at review.")
                    self.store.transition(
                        job.id, "ready_for_review", "all fields filled or uploaded"
                    )
        except Exception as exc:  # noqa: BLE001
            say(f"FAILED: {exc}")
            self.store.transition(job.id, "failed", str(exc)[:500])
        finally:
            log.close()
        return self.store.load(job.id)

    # -- answer ---------------------------------------------------------
    def answer(self, job_id: str, answers: dict) -> dict:
        """Record the user's explicit answers and drop the answered needs."""
        data = self.store.load(job_id)
        if data.get("state") not in ("needs_input", "ready_for_review", "failed"):
            raise ApplyError(
                f"job {job_id} is in state {data.get('state')}; "
                "nothing to answer right now."
            )
        open_ids = {n["field_id"] for n in data.get("needs", [])}
        unknown = set(answers) - open_ids
        if unknown:
            raise ApplyError(
                f"answers for unknown questions: {sorted(unknown)}"
            )
        data.setdefault("answers", {}).update(answers)
        data["needs"] = [
            n for n in data.get("needs", []) if n["field_id"] not in answers
        ]
        self.store.save(job_id, data)
        print(f"recorded {len(answers)} answer(s) for {job_id}")
        return data

    # -- approve / submit ----------------------------------------------
    def approve(self, job_id: str, approver: str) -> dict:
        """Manual gate: record explicit approval to submit (who + when)."""
        data = self.store.load(job_id)
        if data.get("state") not in ("ready_for_review", "needs_input"):
            raise ApplyError(
                f"cannot approve job {job_id} in state {data.get('state')}"
            )
        if data.get("needs"):
            raise ApplyError(
                f"job {job_id} still has {len(data['needs'])} open questions; "
                "answer them first."
            )
        data["approval"] = {
            "by": approver,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.save(job_id, data)
        self.store.transition(job_id, "approved", f"approved by {approver}")
        print(f"{job_id}: approved to submit by {approver}")
        return self.store.load(job_id)

    def submit(self, job_id: str, job_path: str, headless: bool = True) -> dict:
        """Manual submit gate: requires an approval record on state 'approved'.

        Re-fills the form (idempotent) and then clicks submit.
        """
        _require(apply_jobs, "apply_jobs")
        _require(apply_profile, "apply_profile")
        _require(pick_adapter, "apply_adapters")
        _require(B, "apply_browser")

        data = self.store.load(job_id)
        if data.get("state") != "approved" or not data.get("approval"):
            raise ApplyError(
                f"refusing to submit {job_id}: no explicit approval on record. "
                "Run approve first."
            )
        job = apply_jobs.JobSpec.load(job_path)
        resume_pdf = apply_jobs.resolve_resume(job)
        run_dir = Path(self.store.run_dir(job.id))
        run_dir.mkdir(parents=True, exist_ok=True)

        def say(msg: str) -> None:
            print(msg)

        try:
            with B.launch(headless=headless) as page:
                page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                # re-fill to be safe (idempotent), then submit
                profile = apply_profile.load_apply_profile()
                adapter = pick_adapter(page, job.ats)
                adapter.fill(page, profile, resume_pdf, data.get("answers", {}))
                self._do_submit(page, job, run_dir, say)
        except Exception as exc:  # noqa: BLE001
            self.store.transition(job.id, "failed", str(exc)[:500])
            say(f"{job_id}: submit failed: {exc}")
        return self.store.load(job_id)

    # -- status ----------------------------------------------------------
    def status(self, job_id: str) -> dict:
        """Compact, read-only view of one job's apply state."""
        data = self.store.load(job_id)
        needs = data.get("needs", [])
        history = data.get("history", [])
        return {
            "job_id": job_id,
            "state": data.get("state"),
            "job": data.get("job"),
            "needs_open": len(needs),
            "needs": [n.get("label") for n in needs],
            "approval": data.get("approval"),
            "history_tail": history[-5:],
        }

    # -- internals -------------------------------------------------------
    def _do_submit(self, page, job, run_dir, say) -> None:
        """Click submit in the live form and verify a confirmation marker."""
        self.store.transition(job.id, "submitting", "clicking submit")
        clicked = self._click_submit(page)
        if not clicked:
            raise RuntimeError("could not find a submit button")
        page.wait_for_timeout(5000)
        page.screenshot(path=str(run_dir / "submitted.png"), full_page=True)
        text = (page.content() or "").lower()
        if any(m in text for m in SUCCESS_MARKERS):
            self.store.transition(job.id, "submitted", "confirmation detected")
            say(f"{job.id}: SUBMITTED and confirmed.")
        else:
            self.store.transition(
                job.id,
                "failed",
                "clicked submit but no confirmation marker found; "
                f"check {run_dir / 'submitted.png'}",
            )
            say(f"{job.id}: submit clicked but NOT confirmed - check screenshot.")

    def _click_submit(self, page) -> bool:
        for label in SUBMIT_LABELS:
            try:
                btn = page.get_by_role("button", name=label)
                if btn.count() > 0:
                    btn.first.scroll_into_view_if_needed()
                    btn.first.click()
                    return True
            except Exception:  # noqa: BLE001
                continue
        # fallback: any submit-type input
        try:
            btns = page.query_selector_all("input[type=submit], button[type=submit]")
            if btns:
                btns[0].scroll_into_view_if_needed()
                btns[0].click()
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _finish(self, log, job_id: str, extra: dict) -> dict:
        log.close()
        data = self.store.load(job_id)
        data.update(extra)
        return data
