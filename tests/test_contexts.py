"""Tests for candid.contexts: named configuration contexts."""

from __future__ import annotations

import json
import os

import pytest

from candid import config, contexts
from candid.contexts import ContextStore, get_store


@pytest.fixture()
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for var in ("CANDID_CTX", "CANDID_CTX_COMPANY", "CANDID_CTX_FILE"):
        monkeypatch.delenv(var, raising=False)
    return get_store()


# --- path plumbing -------------------------------------------------------------


def test_contexts_path_follows_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CANDID_CTX_FILE", raising=False)
    assert contexts.CONTEXTS_PATH == tmp_path / "contexts.json"


def test_candid_ctx_file_overrides_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    alt = tmp_path / "alt" / "ctx.json"
    monkeypatch.setenv("CANDID_CTX_FILE", str(alt))
    assert contexts.CONTEXTS_PATH == alt
    s = get_store()
    s.create("x")
    assert alt.exists()
    assert not (tmp_path / "contexts.json").exists()


def test_missing_file_is_empty_store_no_crash(store):
    assert store.list_names() == []
    assert store.active_name() is None
    assert not store.exists("nope")


# --- CRUD ----------------------------------------------------------------------


def test_create_and_get_roundtrip(store):
    created = store.create(
        "faang",
        role="MLE",
        settings={"tailor.tone": "confident"},
        companies={"Acme": {"jobs.remote_only": True}},
    )
    assert created["role"] == "MLE"
    raw = store.get("faang")
    assert raw["settings"] == {"tailor.tone": "confident"}
    assert raw["companies"] == {"Acme": {"jobs.remote_only": True}}
    assert raw["extends"] is None


def test_create_defaults(store):
    raw = store.create("plain")
    assert raw["role"] == ""
    assert raw["extends"] is None
    assert raw["settings"] == {}
    assert raw["companies"] == {}


def test_create_duplicate_without_overwrite_raises(store):
    store.create("dup")
    with pytest.raises(ValueError):
        store.create("dup")


def test_create_duplicate_with_overwrite_replaces(store):
    store.create("dup", settings={"a": 1})
    store.create("dup", settings={"b": 2}, overwrite=True)
    assert store.get("dup")["settings"] == {"b": 2}


def test_create_empty_name_raises(store):
    with pytest.raises(ValueError):
        store.create("")


def test_get_missing_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.get("missing")


def test_list_names_sorted_and_exists(store):
    store.create("zeta")
    store.create("alpha")
    assert store.list_names() == ["alpha", "zeta"]
    assert store.exists("alpha")
    assert not store.exists("beta")


def test_delete_removes(store):
    store.create("gone")
    store.delete("gone")
    assert not store.exists("gone")
    with pytest.raises(KeyError):
        store.get("gone")


def test_delete_missing_raises(store):
    with pytest.raises(KeyError):
        store.delete("missing")


def test_delete_fixes_active_and_previous_pointers(store):
    store.create("a")
    store.create("b")
    store.set_active("a")
    store.set_active("b")  # previous is now "a"
    store.delete("a")
    assert store.active_name() == "b"
    assert store.toggle_previous() == "b"  # previous cleared, no-op
    store.delete("b")
    assert store.active_name() is None


def test_rename_rewrites_everything(store):
    store.create("base", settings={"jobs.days": 10})
    store.create("child", extends="base")
    store.set_active("child")
    store.set_active("base")  # previous is "child"
    store.rename("base", "renamed")
    assert not store.exists("base")
    assert store.exists("renamed")
    assert store.get("child")["extends"] == "renamed"
    assert store.active_name() == "renamed"
    assert store.toggle_previous() == "child"


def test_rename_to_existing_raises(store):
    store.create("a")
    store.create("b")
    with pytest.raises(ValueError):
        store.rename("a", "b")


def test_rename_missing_raises(store):
    with pytest.raises(KeyError):
        store.rename("nope", "new")


def test_rename_same_name_is_noop(store):
    store.create("same", settings={"x": 1})
    store.rename("same", "same")
    assert store.exists("same")


def test_set_and_unset_value(store):
    store.create("c")
    store.set_value("c", "jobs.days", 45)
    assert store.get("c")["settings"]["jobs.days"] == 45
    store.unset_value("c", "jobs.days")
    assert "jobs.days" not in store.get("c")["settings"]
    store.unset_value("c", "jobs.days")  # absent key is a no-op
    with pytest.raises(KeyError):
        store.set_value("missing", "jobs.days", 1)


def test_set_and_unset_company_value(store):
    store.create("c")
    store.set_company_value("c", "Acme", "tailor.tone", "warm")
    assert store.companies("c") == ["Acme"]
    assert store.get("c")["companies"]["Acme"] == {"tailor.tone": "warm"}
    store.unset_company_value("c", "Acme", "tailor.tone")
    assert store.companies("c") == []  # empty company pruned
    store.unset_company_value("c", "Acme", "tailor.tone")  # no-op
    with pytest.raises(KeyError):
        store.set_company_value("missing", "Acme", "k", "v")


def test_companies_missing_context_raises(store):
    with pytest.raises(KeyError):
        store.companies("missing")


def test_set_value_rejects_non_jsonable(store):
    store.create("c")
    with pytest.raises(ValueError):
        store.set_value("c", "k", object())


# --- active / previous ---------------------------------------------------------


def test_set_active_records_previous(store):
    store.create("a")
    store.create("b")
    store.set_active("a")
    assert store.active_name() == "a"
    store.set_active("b")
    assert store.active_name() == "b"
    assert store.toggle_previous() == "a"
    assert store.active_name() == "a"


def test_set_active_missing_raises(store):
    with pytest.raises(KeyError):
        store.set_active("missing")


def test_toggle_previous_noop_without_previous(store):
    store.create("a")
    store.set_active("a")
    assert store.toggle_previous() == "a"
    assert store.active_name() == "a"


def test_toggle_previous_roundtrip(store):
    store.create("a")
    store.create("b")
    store.set_active("a")
    store.set_active("b")
    assert store.toggle_previous() == "a"
    assert store.toggle_previous() == "b"


# --- inheritance / resolution --------------------------------------------------


@pytest.fixture()
def chained(store):
    store.create("base", role="Base Role", settings={"jobs.days": 10, "tailor.tone": "formal"},
               companies={"Acme": {"jobs.days": 5, "tailor.tone": "warm"}})
    store.create("mid", extends="base", settings={"tailor.tone": "confident"})
    store.create("leaf", extends="mid",
                 settings={"jobs.days": 20},
                 companies={"Acme": {"tailor.tone": "concise"}, "Beta": {"jobs.days": 3}})
    return store


def test_resolve_merges_parent_first_child_wins(chained):
    r = contexts.resolve_context("mid")
    assert r["settings"] == {"jobs.days": 10, "tailor.tone": "confident"}


def test_resolve_multilevel_chain(chained):
    r = contexts.resolve_context("leaf")
    assert r["settings"] == {"jobs.days": 20, "tailor.tone": "confident"}
    assert r["name"] == "leaf"
    assert r["extends"] == "mid"


def test_resolve_companies_deep_merged(chained):
    r = contexts.resolve_context("leaf")
    # Acme: base days + leaf tone override; Beta only in leaf.
    assert r["companies"]["Acme"] == {"jobs.days": 5, "tailor.tone": "concise"}
    assert r["companies"]["Beta"] == {"jobs.days": 3}


def test_resolve_role_inherited_when_empty(chained):
    assert contexts.resolve_context("leaf")["role"] == "Base Role"
    chained.set_value("leaf", "x", 1)
    chained.create("withrole", extends="leaf", role="Own")
    assert contexts.resolve_context("withrole")["role"] == "Own"


def test_resolve_missing_parent_raises_valueerror(store):
    store.create("orphan", extends="ghost")
    with pytest.raises(ValueError):
        contexts.resolve_context("orphan")


def test_resolve_cycle_raises_valueerror(store):
    store.create("a", extends="b")
    store.create("b", extends="a")
    with pytest.raises(ValueError):
        contexts.resolve_context("a")


def test_resolve_self_cycle_raises_valueerror(store):
    store.create("loop", extends="loop")
    with pytest.raises(ValueError):
        contexts.resolve_context("loop")


def test_resolve_missing_name_raises_keyerror(store):
    with pytest.raises(KeyError):
        contexts.resolve_context("missing")


def test_resolve_none_uses_active(store):
    store.create("a", settings={"jobs.days": 7})
    store.set_active("a")
    r = contexts.resolve_context(None)
    assert r["name"] == "a"
    assert r["settings"]["jobs.days"] == 7


def test_resolve_none_without_active_raises_keyerror(store):
    with pytest.raises(KeyError):
        contexts.resolve_context(None)


# --- ctx_value precedence ------------------------------------------------------


def test_ctx_value_company_beats_setting(chained):
    assert contexts.ctx_value("tailor.tone", context="leaf", company="Acme") == "concise"


def test_ctx_value_setting_beats_inherited(chained):
    # leaf overrides jobs.days; tailor.tone comes from mid (inherited).
    assert contexts.ctx_value("jobs.days", context="leaf") == 20
    assert contexts.ctx_value("tailor.tone", context="leaf") == "confident"


def test_ctx_value_inherited_when_not_overridden(chained):
    assert contexts.ctx_value("jobs.days", context="mid") == 10


def test_ctx_value_defaults_fallback(store):
    assert contexts.ctx_value("tailor.tone") == "confident"
    assert contexts.ctx_value("jobs.days") == 30
    assert contexts.ctx_value("jobs.sources") == []


def test_ctx_value_default_arg_for_unknown_key(store):
    assert contexts.ctx_value("nope.unknown", default="fallback") == "fallback"
    assert contexts.ctx_value("nope.unknown") is None


def test_ctx_value_unknown_context_falls_back(store):
    assert contexts.ctx_value("tailor.tone", context="ghost") == "confident"
    assert contexts.ctx_value("nope.unknown", default=5, context="ghost") == 5


def test_ctx_value_company_from_env(monkeypatch, chained):
    monkeypatch.setenv("CANDID_CTX_COMPANY", "Acme")
    assert contexts.ctx_value("tailor.tone", context="leaf") == "concise"
    monkeypatch.setenv("CANDID_CTX_COMPANY", "  ")
    assert contexts.ctx_value("tailor.tone", context="leaf") == "confident"


def test_ctx_value_uses_active_context(store):
    store.create("a", settings={"jobs.days": 99})
    store.set_active("a")
    assert contexts.ctx_value("jobs.days") == 99


def test_effective_company(monkeypatch):
    monkeypatch.setenv("CANDID_CTX_COMPANY", "  Globex  ")
    assert contexts.effective_company() == "Globex"
    monkeypatch.setenv("CANDID_CTX_COMPANY", "   ")
    assert contexts.effective_company() is None
    monkeypatch.delenv("CANDID_CTX_COMPANY", raising=False)
    assert contexts.effective_company() is None


def test_ctx_value_returns_copies(store):
    store.create("a", settings={"jobs.sources": ["x"]})
    first = contexts.ctx_value("jobs.sources", context="a")
    first.append("mutated")
    assert contexts.ctx_value("jobs.sources", context="a") == ["x"]


# --- env overrides for active --------------------------------------------------


def test_candid_ctx_wins_when_existing(monkeypatch, store):
    store.create("a")
    store.create("b")
    store.set_active("a")
    monkeypatch.setenv("CANDID_CTX", "b")
    assert store.active_name() == "b"


def test_candid_ctx_unknown_falls_back_to_stored(monkeypatch, store):
    store.create("a")
    store.set_active("a")
    monkeypatch.setenv("CANDID_CTX", "ghost")
    assert store.active_name() == "a"


def test_resolve_uses_candid_ctx(monkeypatch, store):
    store.create("a", settings={"jobs.days": 11})
    store.create("b", settings={"jobs.days": 22})
    store.set_active("a")
    monkeypatch.setenv("CANDID_CTX", "b")
    assert contexts.resolve_context()["settings"]["jobs.days"] == 22


# --- coerce_value --------------------------------------------------------------


def test_coerce_int():
    assert contexts.coerce_value("jobs.days", "45") == 45
    assert contexts.coerce_value("match.min_score", " 70 ") == 70


def test_coerce_int_bad_raises():
    with pytest.raises(ValueError):
        contexts.coerce_value("jobs.days", "soon")
    with pytest.raises(ValueError):
        contexts.coerce_value("jobs.days", "4.5")


def test_coerce_bool_variants():
    for raw in ("true", "True", "1", "yes", "YES"):
        assert contexts.coerce_value("jobs.remote_only", raw) is True
    for raw in ("false", "False", "0", "no", "NO"):
        assert contexts.coerce_value("jobs.remote_only", raw) is False


def test_coerce_bool_bad_raises():
    with pytest.raises(ValueError):
        contexts.coerce_value("jobs.remote_only", "maybe")


def test_coerce_list():
    assert contexts.coerce_value("jobs.sources", "linkedin, indeed ,hiring.cafe") == [
        "linkedin",
        "indeed",
        "hiring.cafe",
    ]
    assert contexts.coerce_value("jobs.sources", "  ") == []


def test_coerce_str_passthrough():
    assert contexts.coerce_value("salary.location", "New York, NY") == "New York, NY"


def test_coerce_choices_ok_and_bad():
    assert contexts.coerce_value("tailor.tone", "warm") == "warm"
    with pytest.raises(ValueError):
        contexts.coerce_value("tailor.tone", "shouty")
    with pytest.raises(ValueError):
        contexts.coerce_value("prep.depth", "extreme")


def test_coerce_unknown_key_raises():
    with pytest.raises(ValueError):
        contexts.coerce_value("nope.key", "1")


# --- validation ----------------------------------------------------------------


def test_validate_clean(store):
    store.create("ok", settings={"tailor.tone": "warm", "jobs.days": 10},
                 companies={"Acme": {"jobs.remote_only": True}})
    assert contexts.validate_context("ok") == []


def test_validate_unknown_key(store):
    store.create("bad", settings={"nope.key": 1})
    errors = contexts.validate_context("bad")
    assert any("unknown setting key" in e for e in errors)


def test_validate_wrong_type(store):
    store.create("bad", settings={"jobs.days": "thirty"})
    errors = contexts.validate_context("bad")
    assert any("should be int" in e for e in errors)


def test_validate_bool_is_not_int(store):
    store.create("bad", settings={"jobs.days": True})
    errors = contexts.validate_context("bad")
    assert any("should be int" in e for e in errors)


def test_validate_bad_choice(store):
    store.create("bad", settings={"tailor.tone": "shouty"})
    errors = contexts.validate_context("bad")
    assert any("invalid value" in e for e in errors)


def test_validate_bad_list_element(store):
    store.create("bad", settings={"jobs.sources": ["ok", 5]})
    errors = contexts.validate_context("bad")
    assert any("jobs.sources" in e for e in errors)


def test_validate_company_unknown_key(store):
    store.create("bad", companies={"Acme": {"nope.key": 1}})
    errors = contexts.validate_context("bad")
    assert any("Acme" in e and "unknown setting key" in e for e in errors)


def test_validate_missing_extends(store):
    store.create("orphan", extends="ghost")
    errors = contexts.validate_context("orphan")
    assert any("extends unknown context" in e for e in errors)


def test_validate_cycle(store):
    store.create("a", extends="b")
    store.create("b", extends="a")
    errors = contexts.validate_context("a")
    assert any("cycle" in e for e in errors)


def test_validate_missing_context_raises(store):
    with pytest.raises(KeyError):
        contexts.validate_context("missing")


def test_validate_all(store):
    store.create("good", settings={"jobs.days": 3})
    store.create("bad", settings={"tailor.tone": "shouty"})
    result = contexts.validate_all()
    assert set(result) == {"good", "bad"}
    assert result["good"] == []
    assert result["bad"] != []


# --- presets -------------------------------------------------------------------


def test_list_presets():
    assert contexts.list_presets() == [
        "backend-generalist",
        "data-scientist",
        "faang-mle",
        "new-grad",
        "startup-fullstack",
    ]


def test_builtin_presets_shape():
    for name, spec in contexts.BUILTIN_PRESETS.items():
        assert set(spec) >= {"role", "settings", "companies", "extends"}, name
        assert isinstance(spec["role"], str) and spec["role"]
        assert isinstance(spec["settings"], dict) and spec["settings"]


def test_preset_settings_exact(store):
    created_name = contexts.init_from_preset("faang-mle")
    assert created_name == "faang-mle"
    raw = store.get("faang-mle")
    assert raw["role"] == "Machine Learning Engineer"
    assert raw["settings"] == {
        "tailor.tone": "confident",
        "tailor.length": "one-page",
        "match.min_score": 70,
        "jobs.min_score": 60,
        "jobs.remote_only": False,
        "prep.depth": "deep",
        "nudges.stale_days": 7,
        "salary.location": "New York, NY",
    }
    assert contexts.validate_context("faang-mle") == []


def test_init_from_preset_custom_name_and_overwrite(store):
    name = contexts.init_from_preset("new-grad", name="junior")
    assert name == "junior"
    assert store.get("junior")["role"] == "Software Engineer"
    with pytest.raises(ValueError):
        contexts.init_from_preset("new-grad", name="junior")
    contexts.init_from_preset("new-grad", name="junior", overwrite=True)
    assert store.get("junior")["settings"]["jobs.days"] == 60


def test_init_from_preset_unknown_raises(store):
    with pytest.raises(KeyError):
        contexts.init_from_preset("ghost-preset")


def test_all_presets_validate(store):
    for preset in contexts.list_presets():
        contexts.init_from_preset(preset)
    assert all(v == [] for v in contexts.validate_all().values())


# --- export / import -------------------------------------------------------------


def test_export_import_roundtrip(store, tmp_path):
    store.create("orig", role="R", extends=None,
                 settings={"tailor.tone": "warm"},
                 companies={"Acme": {"jobs.days": 3}})
    out = tmp_path / "ctx.json"
    result = contexts.export_context("orig", out)
    assert result == out
    payload = json.loads(out.read_text())
    assert payload == {
        "name": "orig",
        "role": "R",
        "extends": None,
        "settings": {"tailor.tone": "warm"},
        "companies": {"Acme": {"jobs.days": 3}},
    }
    store.delete("orig")
    imported = contexts.import_context(out)
    assert imported == "orig"
    assert store.get("orig")["settings"] == {"tailor.tone": "warm"}
    assert store.get("orig")["companies"] == {"Acme": {"jobs.days": 3}}


def test_import_name_override_and_overwrite(store, tmp_path):
    store.create("a", settings={"jobs.days": 1})
    contexts.export_context("a", tmp_path / "a.json")
    with pytest.raises(ValueError):
        contexts.import_context(tmp_path / "a.json")
    name = contexts.import_context(tmp_path / "a.json", name="b")
    assert name == "b"
    assert store.get("b")["settings"] == {"jobs.days": 1}
    contexts.import_context(tmp_path / "a.json", name="b", overwrite=True)


def test_import_bad_file_raises(store, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError):
        contexts.import_context(bad)
    missing_name = tmp_path / "noname.json"
    missing_name.write_text(json.dumps({"settings": {}}))
    with pytest.raises(ValueError):
        contexts.import_context(missing_name)


def test_export_missing_raises(store, tmp_path):
    with pytest.raises(KeyError):
        contexts.export_context("ghost", tmp_path / "x.json")


# --- diff ------------------------------------------------------------------------


def test_diff_contexts(store):
    store.create("a", settings={"jobs.days": 10, "tailor.tone": "warm"})
    store.create("b", settings={"jobs.days": 20, "tailor.tone": "warm", "prep.depth": "deep"})
    diff = contexts.diff_contexts("a", "b")
    assert diff == [
        ("jobs.days", 10, 20),
        ("prep.depth", None, "deep"),
    ]


def test_diff_same_context_empty(store):
    store.create("a", settings={"jobs.days": 10})
    assert contexts.diff_contexts("a", "a") == []


def test_diff_uses_resolved_settings(chained):
    diff = dict((k, (va, vb)) for k, va, vb in contexts.diff_contexts("mid", "leaf"))
    assert diff["jobs.days"] == (10, 20)
    assert "tailor.tone" not in diff  # both resolve to confident


# --- persistence -----------------------------------------------------------------


def test_store_persists_across_instances(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CANDID_CTX_FILE", raising=False)
    s1 = get_store()
    s1.create("keep", settings={"jobs.days": 5})
    s1.set_active("keep")
    s2 = get_store()
    assert s2.exists("keep")
    assert s2.active_name() == "keep"
    assert s2.get("keep")["settings"]["jobs.days"] == 5


def test_get_store_explicit_path(tmp_path):
    p = tmp_path / "custom.json"
    s = get_store(path=p)
    assert isinstance(s, ContextStore)
    s.create("x")
    assert p.exists()
