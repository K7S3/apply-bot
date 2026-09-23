"""Tests for candid.apply_adapters using fake duck-typed page objects.

No playwright is imported or required here; the adapters only rely on the
duck-typed page API documented in candid.apply_adapters.
"""

from __future__ import annotations

import pytest

from candid.apply_adapters import ADAPTERS, pick
from candid.apply_adapters.base import Adapter, FillResult, Need
from candid.apply_adapters.generic import (
    LABEL_JS,
    OPTIONS_JS,
    VISIBLE_JS,
    GenericAdapter,
)


class FakeElement:
    """Duck-typed stand-in for a playwright ElementHandle/Locator."""

    def __init__(
        self,
        tag,
        label="",
        ctype=None,
        name="",
        el_id="",
        options=None,
        visible=True,
        checked=False,
        fail=False,
    ):
        self.tag = tag.upper()
        self.label = label
        self.ctype = ctype
        self.name = name
        self.el_id = el_id
        self.options = options or []
        self.visible = visible
        self.checked = checked
        self.fail = fail
        self.filled_value = None
        self.selected_label = None
        self.uploaded = None

    def evaluate(self, js, *args):
        if self.fail:
            raise RuntimeError("element gone")
        if js is LABEL_JS:
            return self.label
        if js is OPTIONS_JS:
            return list(self.options)
        if js is VISIBLE_JS:
            return self.visible
        if js == "e => e.tagName":
            return self.tag
        # radio group click / generic JS: nothing to do on the fake
        return None

    def get_attribute(self, attr):
        return {"type": self.ctype, "name": self.name, "id": self.el_id}.get(attr)

    def set_input_files(self, path):
        self.uploaded = path

    def select_option(self, label=None):
        self.selected_label = label

    def fill(self, value):
        self.filled_value = value

    def check(self):
        self.checked = True

    def uncheck(self):
        self.checked = False

    def is_checked(self):
        return self.checked


class FakePage:
    """Duck-typed stand-in for a playwright Page (adapter-facing API only)."""

    def __init__(self, elements):
        self.elements = elements

    def query_selector_all(self, selector):
        assert selector == "input, textarea, select"
        return self.elements

    def evaluate(self, js, arg=None):
        # only used by GenericAdapter._group_options(page, el) with a group name
        opts = []
        for el in self.elements:
            if el.ctype == "radio" and el.name == arg and el.label:
                opts.append(el.label)
        return opts


class StubProfile:
    VALUES = {
        "first_name": "Alex",
        "last_name": "Rivera",
        "email": "alex.rivera@example.com",
        "phone": "+1 555-010-2030",
        "city": "New York",
        "state": "NY",
        "zip": "10019",
        "country": "United States",
        "linkedin": "https://www.linkedin.com/in/alexrivera",
        "github": "https://github.com/alexrivera",
    }

    def value(self, key):
        return self.VALUES.get(key)


def make_page(elements):
    return FakePage(elements)


def test_safe_fields_fill_from_profile():
    els = [
        FakeElement("input", label="First name", ctype="text", name="firstName"),
        FakeElement("input", label="Last name", ctype="text", name="lastName"),
        FakeElement("input", label="Email", ctype="email", name="email"),
        FakeElement("input", label="Phone", ctype="tel", name="phone"),
        FakeElement("input", label="City", ctype="text", name="city"),
        FakeElement("input", label="State", ctype="text", name="state"),
        FakeElement("input", label="ZIP code", ctype="text", name="zip"),
        FakeElement("input", label="Country", ctype="text", name="country"),
        FakeElement("input", label="LinkedIn profile", ctype="url", name="linkedin"),
        FakeElement("input", label="GitHub", ctype="url", name="github"),
        FakeElement("textarea", label="Anything else", name="notes"),
    ]
    result = GenericAdapter().fill(make_page(els), StubProfile(), "resume.pdf", {})
    assert len(result.filled) == 10
    assert els[0].filled_value == "Alex"
    assert els[2].filled_value == "alex.rivera@example.com"
    assert els[7].filled_value == "United States"
    # "Anything else" classifies unknown -> becomes a need, not filled
    assert any(n.label == "Anything else" and n.kind == "unknown" for n in result.needs)


def test_sensitive_field_becomes_need():
    el = FakeElement(
        "input",
        label="Are you authorized to work in the United States?",
        ctype="text",
        name="workAuth",
    )
    result = GenericAdapter().fill(make_page([el]), StubProfile(), "resume.pdf", {})
    assert result.filled == []
    assert len(result.needs) == 1
    need = result.needs[0]
    assert need.kind == "sensitive:work_authorization"
    assert need.field_id == "workAuth"
    assert need.control == "text"
    assert el.filled_value is None


def test_unknown_field_becomes_need():
    el = FakeElement("input", label="Favorite hobby", ctype="text", name="hobby")
    result = GenericAdapter().fill(make_page([el]), StubProfile(), "resume.pdf", {})
    assert result.filled == []
    assert len(result.needs) == 1
    assert result.needs[0].kind == "unknown"
    assert result.needs[0].control == "text"


def test_radio_group_never_autofilled_single_need():
    els = [
        FakeElement("input", label="Male", ctype="radio", name="gender"),
        FakeElement("input", label="Female", ctype="radio", name="gender"),
    ]
    result = GenericAdapter().fill(make_page(els), StubProfile(), "resume.pdf", {})
    assert result.filled == []
    assert len(result.needs) == 1
    need = result.needs[0]
    assert need.field_id == "gender"
    assert need.control == "radio"
    assert set(need.options) == {"Male", "Female"}


def test_checkbox_explicit_answer_checked():
    el = FakeElement(
        "input", label="Subscribe to job alerts", ctype="checkbox", name="alerts"
    )
    result = GenericAdapter().fill(
        make_page([el]), StubProfile(), "resume.pdf", {"alerts": "yes"}
    )
    assert el.checked is True
    assert result.filled == ["Subscribe to job alerts [user answer]"]
    assert result.needs == []


def test_explicit_answer_wins_over_sensitive_classification():
    el = FakeElement(
        "input", label="Expected salary", ctype="text", name="salary"
    )
    result = GenericAdapter().fill(
        make_page([el]), StubProfile(), "resume.pdf", {"salary": "150000"}
    )
    assert el.filled_value == "150000"
    assert result.filled == ["Expected salary [user answer]"]
    assert result.needs == []


def test_resume_upload_sets_flag():
    el = FakeElement("input", label="Upload resume", ctype="file", name="resume")
    result = GenericAdapter().fill(make_page([el]), StubProfile(), "resume.pdf", {})
    assert el.uploaded == "resume.pdf"
    assert result.resume_uploaded is True
    assert result.filled == ["Upload resume [resume uploaded]"]


def test_select_fills_from_profile():
    el = FakeElement(
        "select",
        label="Country",
        name="country",
        options=["Canada", "United States"],
    )
    result = GenericAdapter().fill(make_page([el]), StubProfile(), "resume.pdf", {})
    assert el.selected_label == "United States"
    assert result.filled == ["Country -> country"]
    assert result.needs == []


def test_invisible_control_skipped():
    el = FakeElement(
        "input", label="First name", ctype="text", name="firstName", visible=False
    )
    result = GenericAdapter().fill(make_page([el]), StubProfile(), "resume.pdf", {})
    assert result.filled == []
    assert result.needs == []


def test_broken_control_does_not_kill_run():
    good = FakeElement("input", label="First name", ctype="text", name="firstName")
    bad = FakeElement("input", label="Last name", ctype="text", name="lastName", fail=True)
    result = GenericAdapter().fill(make_page([good, bad]), StubProfile(), "resume.pdf", {})
    assert good.filled_value == "Alex"
    assert len(result.notes) == 1
    assert "skipped a control" in result.notes[0]


def test_registry_pick_and_register(monkeypatch):
    import candid.apply_adapters as reg

    assert "generic" in ADAPTERS
    assert isinstance(ADAPTERS["generic"], GenericAdapter)

    class CustomAdapter:
        name = "custom"

        def detect(self, page):
            return True

        def fill(self, page, profile, resume_pdf, answered):
            return FillResult(notes=["custom"])

    monkeypatch.setitem(reg.ADAPTERS, "custom", CustomAdapter())
    assert pick(object(), hint="custom").name == "custom"
    # detect loop: custom registered before generic wins on an unknown hint
    monkeypatch.setattr(
        reg, "ADAPTERS", {"custom": CustomAdapter(), "generic": GenericAdapter()}
    )
    assert pick(object(), hint="nope").name == "custom"
    assert pick(object()).name == "generic"
    assert GenericAdapter().detect(object()) is True


def test_need_defaults():
    need = Need(field_id="x", label="Q", kind="unknown", control="input")
    assert need.options == []


def test_protocol_structural_conformance():
    adapter: Adapter = GenericAdapter()
    assert isinstance(adapter.name, str)
