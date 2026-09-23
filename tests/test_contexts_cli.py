"""Tests for candid.contexts_cli (batch 108, worker B)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from candid import contexts as C
from candid import contexts_cli as CLI


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def datadir(tmp_path, monkeypatch):
    """Isolate contexts.json in a tmp dir; clear env layering."""
    monkeypatch.setattr("candid.config.DATA_DIR", tmp_path)
    monkeypatch.delenv("CANDID_CTX", raising=False)
    monkeypatch.delenv("CANDID_CTX_COMPANY", raising=False)
    monkeypatch.delenv("CANDID_CTX_FILE", raising=False)
    return tmp_path


def ns(**kwargs):
    return argparse.Namespace(**kwargs)


def make(name="work", **kw):
    return C.get_store().create(name, **kw)


# ---------------------------------------------------------------------------
# create / list
# ---------------------------------------------------------------------------


def test_create_and_list(datadir, capsys):
    CLI.cmd_ctx_create(ns(name="work", role="MLE", extends=None, from_preset=None))
    out = capsys.readouterr().out
    assert "Created context 'work'" in out
    CLI.cmd_ctx_list(ns(json=False))
    out = capsys.readouterr().out
    assert "work" in out and "MLE" in out


def test_list_empty(datadir, capsys):
    CLI.cmd_ctx_list(ns(json=False))
    assert "No contexts yet" in capsys.readouterr().out


def test_list_json(datadir, capsys):
    make("a", role="R1")
    make("b", role="R2", extends="a")
    CLI.cmd_ctx_list(ns(json=True))
    rows = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in rows] == ["a", "b"]
    assert rows[1]["extends"] == "a"
    assert rows[0]["active"] is False


def test_list_marks_active(datadir, capsys):
    make("a")
    C.get_store().set_active("a")
    CLI.cmd_ctx_list(ns(json=False))
    lines = capsys.readouterr().out.splitlines()
    assert any(l.startswith("a") and l.rstrip().endswith("*") for l in lines)


def test_create_duplicate_fails(datadir):
    make("dup")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_create(ns(name="dup", role="", extends=None, from_preset=None))


def test_create_from_preset_seeds_settings(datadir):
    CLI.cmd_ctx_create(ns(name="f", role="", extends=None, from_preset="faang-mle"))
    raw = C.get_store().get("f")
    assert raw["settings"]["match.min_score"] == 70
    assert raw["role"] == "Machine Learning Engineer"


def test_create_from_bad_preset_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_create(ns(name="x", role="", extends=None, from_preset="nope"))


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_raw(datadir, capsys):
    make("s", role="Data Scientist")
    C.get_store().set_value("s", "jobs.days", 45)
    CLI.cmd_ctx_show(ns(name="s", resolved=False, json=False))
    out = capsys.readouterr().out
    assert "Data Scientist" in out and "jobs.days" in out and "45" in out


def test_show_json(datadir, capsys):
    make("s")
    CLI.cmd_ctx_show(ns(name="s", resolved=False, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["role"] == "" and "settings" in data


def test_show_resolved_inherits(datadir, capsys):
    make("parent")
    C.get_store().set_value("parent", "jobs.days", 10)
    make("child", extends="parent")
    C.get_store().set_value("child", "jobs.days", 20)
    CLI.cmd_ctx_show(ns(name="child", resolved=True, json=False))
    out = capsys.readouterr().out
    assert "jobs.days" in out and "20" in out and "10" not in out


def test_show_unknown_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_show(ns(name="ghost", resolved=False, json=False))


# ---------------------------------------------------------------------------
# use / current / toggle
# ---------------------------------------------------------------------------


def test_use_and_current(datadir, capsys):
    make("one")
    make("two")
    CLI.cmd_ctx_use(ns(name="two"))
    assert "Active context: two" in capsys.readouterr().out
    CLI.cmd_ctx_current(ns(json=False))
    out = capsys.readouterr().out
    assert "active: two" in out


def test_use_unknown_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_use(ns(name="ghost"))


def test_toggle_previous(datadir, capsys):
    make("one")
    make("two")
    CLI.cmd_ctx_use(ns(name="one"))
    CLI.cmd_ctx_use(ns(name="two"))
    capsys.readouterr()
    CLI.cmd_ctx_use(ns(name="-"))
    out = capsys.readouterr().out
    assert "Active context: one" in out
    assert C.get_store().active_name() == "one"


def test_toggle_with_no_previous(datadir, capsys):
    CLI.cmd_ctx_use(ns(name="-"))
    assert "No active context" in capsys.readouterr().out


def test_current_json(datadir, capsys):
    make("one")
    C.get_store().set_active("one")
    CLI.cmd_ctx_current(ns(json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["active"] == "one"
    assert data["resolved"]["name"] == "one"


def test_current_none(datadir, capsys):
    CLI.cmd_ctx_current(ns(json=False))
    assert "No active context" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# set / unset
# ---------------------------------------------------------------------------


def test_set_typed_coercion(datadir, capsys):
    make("c")
    CLI.cmd_ctx_set(ns(name="c", key="jobs.days", value="45"))
    CLI.cmd_ctx_set(ns(name="c", key="jobs.remote_only", value="yes"))
    CLI.cmd_ctx_set(ns(name="c", key="jobs.sources", value="a, b"))
    capsys.readouterr()
    raw = C.get_store().get("c")["settings"]
    assert raw["jobs.days"] == 45
    assert raw["jobs.remote_only"] is True
    assert raw["jobs.sources"] == ["a", "b"]


def test_set_unknown_key_warns_not_fails(datadir, capsys):
    make("c")
    CLI.cmd_ctx_set(ns(name="c", key="mystery.key", value="x"))
    err = capsys.readouterr().err
    assert "not a known setting key" in err
    assert C.get_store().get("c")["settings"]["mystery.key"] == "x"


def test_set_bad_value_fails(datadir):
    make("c")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_set(ns(name="c", key="jobs.days", value="notanint"))


def test_set_bad_choice_fails(datadir):
    make("c")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_set(ns(name="c", key="tailor.tone", value="pirate"))


def test_unset(datadir, capsys):
    make("c")
    C.get_store().set_value("c", "jobs.days", 5)
    CLI.cmd_ctx_unset(ns(name="c", key="jobs.days"))
    assert "Unset jobs.days" in capsys.readouterr().out
    assert "jobs.days" not in C.get_store().get("c")["settings"]


# ---------------------------------------------------------------------------
# company overrides
# ---------------------------------------------------------------------------


def test_company_set_and_list(datadir, capsys):
    make("c")
    CLI.cmd_ctx_company_set(ns(name="c", company="Meta", key="tailor.tone",
                               value="formal"))
    assert "Meta / tailor.tone" in capsys.readouterr().out
    CLI.cmd_ctx_company_list(ns(name="c", json=False))
    out = capsys.readouterr().out
    assert "Meta" in out and "tailor.tone" in out


def test_company_list_json(datadir, capsys):
    make("c")
    C.get_store().set_company_value("c", "Meta", "tailor.tone", "formal")
    CLI.cmd_ctx_company_list(ns(name="c", json=True))
    data = json.loads(capsys.readouterr().out)
    assert data == {"Meta": {"tailor.tone": "formal"}}


def test_company_list_empty(datadir, capsys):
    make("c")
    CLI.cmd_ctx_company_list(ns(name="c", json=False))
    assert "No company overrides" in capsys.readouterr().out


def test_company_unset(datadir):
    make("c")
    C.get_store().set_company_value("c", "Meta", "tailor.tone", "formal")
    CLI.cmd_ctx_company_unset(ns(name="c", company="Meta", key="tailor.tone"))
    assert C.get_store().companies("c") == []


def test_company_set_unknown_key_warns(datadir, capsys):
    make("c")
    CLI.cmd_ctx_company_set(ns(name="c", company="Meta", key="weird", value="1"))
    assert "not a known setting key" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------


def test_role_show_and_set(datadir, capsys):
    make("c", role="Backend")
    CLI.cmd_ctx_role_show(ns(name="c"))
    assert "Backend" in capsys.readouterr().out
    CLI.cmd_ctx_role_set(ns(name="c", role="ML Engineer"))
    assert "ML Engineer" in capsys.readouterr().out
    assert C.get_store().get("c")["role"] == "ML Engineer"


def test_role_show_empty(datadir, capsys):
    make("c")
    CLI.cmd_ctx_role_show(ns(name="c"))
    assert "no role set" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# init / presets
# ---------------------------------------------------------------------------


def test_init_preset(datadir, capsys):
    CLI.cmd_ctx_init(ns(preset="startup-fullstack", as_name=None, overwrite=False))
    out = capsys.readouterr().out
    assert "startup-fullstack" in out
    assert C.get_store().exists("startup-fullstack")


def test_init_as_and_overwrite(datadir):
    make("mine")
    CLI.cmd_ctx_init(ns(preset="new-grad", as_name="mine", overwrite=True))
    assert C.get_store().get("mine")["role"] == "Software Engineer"


def test_init_without_overwrite_fails(datadir):
    make("mine")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_init(ns(preset="new-grad", as_name="mine", overwrite=False))


def test_presets(datadir, capsys):
    CLI.cmd_ctx_presets(ns(json=False))
    out = capsys.readouterr().out
    assert "faang-mle" in out
    CLI.cmd_ctx_presets(ns(json=True))
    names = json.loads(capsys.readouterr().out)
    assert "faang-mle" in names and names == sorted(names)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_diff(datadir, capsys):
    make("a")
    make("b")
    C.get_store().set_value("a", "jobs.days", 10)
    C.get_store().set_value("b", "jobs.days", 20)
    CLI.cmd_ctx_diff(ns(a="a", b="b", json=False))
    out = capsys.readouterr().out
    assert "jobs.days" in out and "10" in out and "20" in out


def test_diff_json(datadir, capsys):
    make("a")
    make("b")
    C.get_store().set_value("a", "jobs.days", 10)
    CLI.cmd_ctx_diff(ns(a="a", b="b", json=True))
    rows = json.loads(capsys.readouterr().out)
    assert rows == [{"key": "jobs.days", "a": 10, "b": None}]


def test_diff_identical(datadir, capsys):
    make("a")
    make("b")
    CLI.cmd_ctx_diff(ns(a="a", b="b", json=False))
    assert "same settings" in capsys.readouterr().out


def test_diff_unknown_fails(datadir):
    make("a")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_diff(ns(a="a", b="ghost", json=False))


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_ok(datadir, capsys):
    make("good")
    C.get_store().set_value("good", "jobs.days", 30)
    CLI.cmd_ctx_validate(ns(name="good"))
    assert "valid" in capsys.readouterr().out


def test_validate_all_ok(datadir, capsys):
    make("good")
    CLI.cmd_ctx_validate(ns(name=None))
    assert "All contexts valid" in capsys.readouterr().out


def test_validate_fails(datadir, capsys):
    C.get_store().create("bad", settings={"bogus.key": 1})
    with pytest.raises(SystemExit) as exc:
        CLI.cmd_ctx_validate(ns(name="bad"))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "bad" in out and "bogus.key" in out


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------


def test_export_import_roundtrip(datadir, capsys, tmp_path):
    make("orig", role="R")
    C.get_store().set_value("orig", "jobs.days", 9)
    C.get_store().set_company_value("orig", "Meta", "tailor.tone", "formal")
    target = tmp_path / "orig.json"
    CLI.cmd_ctx_export(ns(name="orig", out=str(target)))
    assert "Exported" in capsys.readouterr().out
    CLI.cmd_ctx_delete(ns(name="orig", yes=True))
    capsys.readouterr()
    CLI.cmd_ctx_import(ns(file=str(target), as_name=None, overwrite=False))
    assert "Imported" in capsys.readouterr().out
    raw = C.get_store().get("orig")
    assert raw["role"] == "R"
    assert raw["settings"]["jobs.days"] == 9
    assert raw["companies"]["Meta"]["tailor.tone"] == "formal"


def test_import_as_and_overwrite(datadir, tmp_path):
    make("keep")
    target = tmp_path / "x.json"
    target.write_text(json.dumps({"name": "x", "settings": {}, "companies": {}}))
    CLI.cmd_ctx_import(ns(file=str(target), as_name="renamed", overwrite=False))
    assert C.get_store().exists("renamed")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_import(ns(file=str(target), as_name="renamed", overwrite=False))
    CLI.cmd_ctx_import(ns(file=str(target), as_name="renamed", overwrite=True))
    assert C.get_store().exists("renamed")


def test_import_missing_file_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_import(ns(file="/nope/missing.json", as_name=None,
                               overwrite=False))


def test_export_unknown_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_export(ns(name="ghost", out="x.json"))


# ---------------------------------------------------------------------------
# delete / rename
# ---------------------------------------------------------------------------


def test_delete_yes(datadir, capsys):
    make("gone")
    CLI.cmd_ctx_delete(ns(name="gone", yes=True))
    assert "Deleted" in capsys.readouterr().out
    assert not C.get_store().exists("gone")


def test_delete_prompt_yes(datadir, capsys, monkeypatch):
    make("gone")
    monkeypatch.setattr("builtins.input", lambda _p: "y")
    CLI.cmd_ctx_delete(ns(name="gone", yes=False))
    assert not C.get_store().exists("gone")


def test_delete_prompt_no(datadir, capsys, monkeypatch):
    make("stay")
    monkeypatch.setattr("builtins.input", lambda _p: "n")
    CLI.cmd_ctx_delete(ns(name="stay", yes=False))
    assert "Cancelled" in capsys.readouterr().out
    assert C.get_store().exists("stay")


def test_delete_prompt_eof_treated_as_no(datadir, capsys, monkeypatch):
    make("stay")
    def boom(_p):
        raise EOFError
    monkeypatch.setattr("builtins.input", boom)
    CLI.cmd_ctx_delete(ns(name="stay", yes=False))
    assert C.get_store().exists("stay")


def test_delete_unknown_fails(datadir):
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_delete(ns(name="ghost", yes=True))


def test_rename(datadir, capsys):
    make("old")
    C.get_store().set_active("old")
    make("child", extends="old")
    CLI.cmd_ctx_rename(ns(old="old", new="new"))
    assert "Renamed" in capsys.readouterr().out
    store = C.get_store()
    assert store.exists("new") and not store.exists("old")
    assert store.active_name() == "new"
    assert store.get("child")["extends"] == "new"


def test_rename_conflict_fails(datadir):
    make("a")
    make("b")
    with pytest.raises(SystemExit):
        CLI.cmd_ctx_rename(ns(old="a", new="b"))


# ---------------------------------------------------------------------------
# register_ctx wiring
# ---------------------------------------------------------------------------


def _fresh_ctx_subparsers():
    parser = argparse.ArgumentParser(prog="candid")
    subs = parser.add_subparsers(dest="cmd")
    CLI.register_ctx(subs)
    return parser


def test_register_ctx_list(datadir):
    p = _fresh_ctx_subparsers()
    args = p.parse_args(["ctx", "list"])
    assert args.func is CLI.cmd_ctx_list


def test_register_ctx_nested_company_set(datadir):
    p = _fresh_ctx_subparsers()
    args = p.parse_args(["ctx", "company", "set", "c", "Meta", "jobs.days", "7"])
    assert args.func is CLI.cmd_ctx_company_set
    assert args.name == "c" and args.company == "Meta"
    assert args.key == "jobs.days" and args.value == "7"


def test_register_ctx_role_and_flags(datadir):
    p = _fresh_ctx_subparsers()
    args = p.parse_args(["ctx", "role", "set", "c", "MLE"])
    assert args.func is CLI.cmd_ctx_role_set and args.role == "MLE"
    args = p.parse_args(["ctx", "show", "c", "--resolved", "--json"])
    assert args.func is CLI.cmd_ctx_show
    assert args.resolved is True and args.json is True
    args = p.parse_args(["ctx", "init", "faang-mle", "--as", "f", "--overwrite"])
    assert args.func is CLI.cmd_ctx_init
    assert args.preset == "faang-mle" and args.as_name == "f"
    assert args.overwrite is True


def test_register_ctx_use_dash(datadir):
    p = _fresh_ctx_subparsers()
    args = p.parse_args(["ctx", "use", "-"])
    assert args.func is CLI.cmd_ctx_use and args.name == "-"


def test_register_ctx_examples_present():
    p = _fresh_ctx_subparsers()
    # the ctx parser was registered with usage examples
    sub = p._subparsers._group_actions[0].choices["ctx"]
    assert "python -m candid ctx list" in (sub.epilog or "")
