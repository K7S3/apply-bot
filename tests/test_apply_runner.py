"""Tests for candid.apply_runner using monkeypatched fakes.

Sibling modules (apply_state, apply_jobs, apply_profile, apply_adapters,
apply_browser) do not exist in this worktree, so every dependency is faked
and monkeypatched onto candid.apply_runner's module-level names.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import candid.apply_runner as R


# ---------------------------------------------------------------- fakes
class ApplyBrowserError(Exception):
    pass


class FakeLocator:
    """get_by_role('button', name=...).count() > 0 path."""

    def __init__(self, page, found: bool):
        self._page = page
        self._found = found

    def count(self):
        return 1 if self._found else 0

    @property
    def first(self):
        return self

    def scroll_into_view_if_needed(self):
        self._page.calls.append("scroll")

    def click(self):
        self._page.calls.append("submit-clicked")


class FakePage:
    def __init__(self, *, content_text="", submit_found=True, fallback_submit=False):
        self.calls = []
        self._content_text = content_text
        self._submit_found = submit_found
        self._fallback_submit = fallback_submit

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url))

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    def screenshot(self, path, full_page=False):
        self.calls.append(("screenshot", path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("fake-png")

    def content(self):
        return self._content_text

    def get_by_role(self, role, name=None):
        return FakeLocator(self, self._submit_found and role == "button")

    def query_selector_all(self, selector):
        if self._fallback_submit:
            return [FakeLocator(self, True)]
        return []


class FakeBrowserModule:
    """Fake candid.apply_browser: launch is a contextmanager; detect_blockers
    is configurable per-test via the module-level flag."""

    ApplyBrowserError = ApplyBrowserError
    blocker = None
    launch_error = None

    def __init__(self, page):
        self._page = page

    @classmethod
    def reset(cls):
        cls.blocker = None
        cls.launch_error = None

    def launch(self, headless=True):
        if type(self).launch_error is not None:
            raise type(self).launch_error

        @contextlib.contextmanager
        def _cm():
            yield self._page

        return _cm()

    def detect_blockers(self, page):
        return type(self).blocker


def make_fill_result(filled=None, needs=None, resume_uploaded=True, notes=None):
    return SimpleNamespace(
        filled=filled or [],
        needs=needs or [],
        resume_uploaded=resume_uploaded,
        notes=notes or [],
    )


def make_need(field_id, label, kind="text", control=None, options=None):
    return SimpleNamespace(
        field_id=field_id, label=label, kind=kind,
        control=control, options=options,
    )


class FakeAdapter:
    def __init__(self, result):
        self.name = "fake-adapter"
        self.result = result
        self.fill_calls = []

    def fill(self, page, profile, resume_pdf, answered):
        self.fill_calls.append(
            {"profile": profile, "resume_pdf": resume_pdf, "answered": dict(answered)}
        )
        return self.result


class FakeStore:
    def __init__(self, root):
        self.root = Path(root)
        self._data = {}

    def load(self, job_id):
        return self._data.get(job_id, {"job_id": job_id, "state": "new", "history": []})

    def save(self, job_id, data):
        self._data[job_id] = data

    def transition(self, job_id, to, note=""):
        data = self.load(job_id)
        data["state"] = to
        data.setdefault("history", []).append({"state": to, "note": note})
        self.save(job_id, data)
        return data

    def run_dir(self, job_id):
        d = self.root / "runs" / job_id / "ts"
        d.mkdir(parents=True, exist_ok=True)
        return d


class FakeJobSpec:
    @classmethod
    def load(cls, path):
        return JOB_SPEC


JOB_SPEC = SimpleNamespace(
    id="job-1",
    company="Acme Corp",
    role="Backend Engineer",
    url="https://example.com/apply",
    resume_pdf="resume.pdf",
    ats="generic",
)


@pytest.fixture
def store(tmp_path):
    return FakeStore(tmp_path)


@pytest.fixture
def env(monkeypatch, store):
    """Monkeypatch all sibling-module names on candid.apply_runner."""
    page = FakePage()
    browser = FakeBrowserModule(page)
    adapter = FakeAdapter(make_fill_result(filled=["name", "email"]))
    jobs = SimpleNamespace(
        JobSpec=FakeJobSpec,
        resolve_resume=lambda spec: Path("/tmp/resume.pdf"),
    )
    profile = SimpleNamespace(load_apply_profile=lambda path="profile.yaml": {"name": "Test"})
    adapters = SimpleNamespace(pick=lambda pg, hint: adapter)

    FakeBrowserModule.reset()
    monkeypatch.setattr(R, "B", browser)
    monkeypatch.setattr(R, "pick_adapter", adapters.pick)
    monkeypatch.setattr(R, "apply_jobs", jobs)
    monkeypatch.setattr(R, "apply_profile", profile)
    monkeypatch.setattr(R, "apply_state", None)  # Runner gets explicit store

    return SimpleNamespace(store=store, page=page, browser=browser, adapter=adapter,
                           runner=R.Runner(store=store))


def run_dir_of(store, job_id="job-1"):
    return store.run_dir(job_id)


def screenshots(page):
    return [c[1] for c in page.calls if c[0] == "screenshot"]


# ---------------------------------------------------------------- tests
def test_import_needs_no_siblings():
    # module imported at top of this file already proves this
    assert R.B is None or hasattr(R.B, "launch")
    assert R.ApplyError is not None
    assert R.SUBMIT_LABELS == ["submit application", "submit"]
    assert len(R.SUCCESS_MARKERS) == 4


def test_apply_parks_at_review_when_clean(env):
    data = env.runner.apply("job.yaml", auto_submit=False)
    assert data["state"] == "ready_for_review"
    assert data["needs"] == []
    shots = screenshots(env.page)
    assert any(str(s).endswith("review.png") for s in shots)
    run_log = run_dir_of(env.store) / "run.log"
    assert run_log.exists()
    text = run_log.read_text()
    assert "adapter: fake-adapter" in text
    assert "PARKED at review" in text
    # never clicked submit
    assert "submit-clicked" not in env.page.calls


def test_apply_needs_input(env):
    needs = [make_need("q1", "Are you authorized to work?", kind="select")]
    env.adapter.result = make_fill_result(filled=["name"], needs=needs)
    data = env.runner.apply("job.yaml")
    assert data["state"] == "needs_input"
    assert len(data["needs"]) == 1
    assert data["needs"][0]["label"] == "Are you authorized to work?"
    assert data["needs"][0]["field_id"] == "q1"
    assert any(str(s).endswith("review.png") for s in screenshots(env.page))
    assert "submit-clicked" not in env.page.calls


def test_auto_submit_with_needs_parks_and_never_submits(env):
    needs = [make_need("q1", "Work authorization?", kind="select")]
    env.adapter.result = make_fill_result(needs=needs)
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "needs_input"
    assert "submit-clicked" not in env.page.calls
    assert not any(str(s).endswith("submitted.png") for s in screenshots(env.page))


def test_auto_submit_clean_submits(env):
    env.page._content_text = "Thank you for applying. Your application was received."
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "submitted"
    assert "submit-clicked" in env.page.calls
    assert any(str(s).endswith("submitted.png") for s in screenshots(env.page))


def test_submit_no_marker_marks_failed(env):
    env.page._content_text = "some random page text without confirmation"
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "failed"
    assert "submit-clicked" in env.page.calls
    assert any(str(s).endswith("submitted.png") for s in screenshots(env.page))


def test_submit_button_missing_marks_failed(env):
    env.page._submit_found = False  # no get_by_role hit, no fallback
    env.page._content_text = "Thank you for applying"
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "failed"
    assert "submit-clicked" not in env.page.calls


def test_submit_fallback_input_clicks(env):
    env.page._submit_found = False
    env.page._fallback_submit = True
    env.page._content_text = "Application submitted. Thank you!"
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "submitted"
    assert "submit-clicked" in env.page.calls


def test_blocked_page(env):
    FakeBrowserModule.blocker = "CAPTCHA detected"
    data = env.runner.apply("job.yaml", auto_submit=True)
    assert data["state"] == "blocked"
    assert data["blocked"] == "CAPTCHA detected"
    assert any(str(s).endswith("blocked.png") for s in screenshots(env.page))
    assert "submit-clicked" not in env.page.calls


def test_launch_error_marks_failed(env):
    FakeBrowserModule.launch_error = ApplyBrowserError("playwright crashed")
    data = env.runner.apply("job.yaml")
    assert data["state"] == "failed"
    assert "playwright crashed" in data["history"][-1]["note"]


def test_answer_records_and_drops_needs(env):
    needs = [make_need("q1", "Work authorization?"), make_need("q2", "Start date?")]
    env.adapter.result = make_fill_result(needs=needs)
    env.runner.apply("job.yaml")

    data = env.runner.answer("job-1", {"q1": "Yes"})
    assert data["answers"]["q1"] == "Yes"
    assert [n["field_id"] for n in data["needs"]] == ["q2"]

    with pytest.raises(R.ApplyError):
        env.runner.answer("job-1", {"bogus": "x"})


def test_answer_rejected_in_bad_state(env):
    env.store.transition("job-1", "submitted", "done")
    with pytest.raises(R.ApplyError):
        env.runner.answer("job-1", {"q1": "x"})


def test_approve_refuses_with_open_needs(env):
    needs = [make_need("q1", "Work authorization?")]
    env.adapter.result = make_fill_result(needs=needs)
    env.runner.apply("job.yaml")
    with pytest.raises(R.ApplyError):
        env.runner.approve("job-1", "Keshavan")


def test_approve_then_submit_flow(env):
    env.runner.apply("job.yaml")  # parks at ready_for_review
    data = env.runner.approve("job-1", "Keshavan")
    assert data["state"] == "approved"
    assert data["approval"]["by"] == "Keshavan"
    assert data["approval"]["at"]

    env.page._content_text = "Thank you for applying"
    out = env.runner.submit("job-1", "job.yaml")
    assert out["state"] == "submitted"
    # re-fill happened with stored answers and resolved resume
    assert env.adapter.fill_calls[-1]["resume_pdf"] == Path("/tmp/resume.pdf")
    assert "submit-clicked" in env.page.calls


def test_submit_refuses_without_approval(env):
    env.runner.apply("job.yaml")  # ready_for_review, no approval
    with pytest.raises(R.ApplyError):
        env.runner.submit("job-1", "job.yaml")
    assert "submit-clicked" not in env.page.calls


def test_submit_refuses_from_wrong_state(env):
    env.store.transition("job-1", "needs_input", "parked")
    with pytest.raises(R.ApplyError):
        env.runner.submit("job-1", "job.yaml")


def test_status(env):
    needs = [make_need("q1", "Work authorization?"), make_need("q2", "Start date?")]
    env.adapter.result = make_fill_result(needs=needs)
    env.runner.apply("job.yaml")
    st = env.runner.status("job-1")
    assert st["job_id"] == "job-1"
    assert st["state"] == "needs_input"
    assert st["needs_open"] == 2
    assert st["needs"] == ["Work authorization?", "Start date?"]
    assert st["approval"] is None
    assert st["job"]["company"] == "Acme Corp"
    assert len(st["history_tail"]) <= 5
    assert st["history_tail"][-1]["state"] == "needs_input"


def test_status_history_tail_caps_at_five(env):
    for i in range(7):
        env.store.transition("job-1", f"state-{i}", f"note-{i}")
    st = env.runner.status("job-1")
    assert len(st["history_tail"]) == 5
    assert st["history_tail"][0]["state"] == "state-2"


def test_runner_needs_store_or_state_module(monkeypatch):
    monkeypatch.setattr(R, "apply_state", None)
    with pytest.raises(R.ApplyError):
        R.Runner()
