"""Tests for candid.staff_design.

CANDID_DATA_DIR is set to a tmp dir before importing candid so no test
touches real user data.
"""

import os

import pytest

_tmp = os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid_test_staff_design")

from candid import staff_design as S  # noqa: E402


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# design prompts
# ---------------------------------------------------------------------------

def test_prompt_count_and_unique_ids():
    prompts = S.list_design_prompts()
    assert len(prompts) == 12
    ids = [p["id"] for p in prompts]
    assert len(set(ids)) == len(ids)


def test_prompt_shape():
    p = S.get_design_prompt("ads-ranking")
    for key in ("id", "title", "base_brief", "scale_twists",
                "org_constraints", "eval_checklist", "source"):
        assert key in p, f"missing {key}"
    assert p["source"] == "candid practice prompt"
    assert len(p["scale_twists"]) >= 2
    assert len(p["org_constraints"]) >= 2
    assert len(p["eval_checklist"]) >= 4
    low = " ".join(p["eval_checklist"]).lower()
    for kw in ("capacity", "failure", "cost", "rollout"):
        assert kw in low, f"checklist missing '{kw}'"


def test_unknown_prompt_raises():
    with pytest.raises(S.StaffError):
        S.get_design_prompt("nope")


def test_format_prompt_with_and_without_twists():
    p = S.get_design_prompt("payments-ledger")
    with_twists = S.format_design_prompt(p, show_twists=True)
    without = S.format_design_prompt(p, show_twists=False)
    assert "Scale twists" in with_twists
    assert "Scale twists" not in without
    assert "Eval checklist" in with_twists
    assert "Org constraints" in without


# ---------------------------------------------------------------------------
# memo drill
# ---------------------------------------------------------------------------

def test_memo_scaffold_sections():
    text = S.render_memo_scaffold("Adopt a feature store")
    assert "Adopt a feature store" in text
    for section in ("Context", "Options and tradeoffs", "Recommendation",
                    "Risks", "Rollout", "Success metrics", "Critique checklist"):
        assert section in text


def test_memo_scaffold_empty_topic_raises():
    with pytest.raises(S.StaffError):
        S.render_memo_scaffold("  ")


def test_memo_roundtrip(tmp_data):
    path = S.save_memo("feature-store", "Adopt a feature store",
                       S.render_memo_scaffold("Adopt a feature store"))
    assert path.exists()
    assert str(tmp_data) in str(path)
    assert "feature-store" in S.list_memos()
    body = S.get_memo("feature-store")
    assert "Adopt a feature store" in body
    assert "Critique checklist" in body


def test_memo_name_sanitized(tmp_data):
    path = S.save_memo("My Memo / 2026!", "topic", "body text")
    assert path.name == "my-memo---2026.md"
    assert "my-memo---2026" in S.list_memos()


def test_unknown_memo_raises(tmp_data):
    with pytest.raises(S.StaffError):
        S.get_memo("missing")


def test_save_empty_body_raises(tmp_data):
    with pytest.raises(S.StaffError):
        S.save_memo("x", "topic", "   ")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_design_list(capsys):
    assert S.main(["design", "--list"]) == 0
    out = capsys.readouterr().out
    assert "ads-ranking" in out


def test_cli_design_prompt(capsys):
    assert S.main(["design", "--prompt", "llm-serving"]) == 0
    out = capsys.readouterr().out
    assert "Eval checklist" in out
    # twists hidden by default
    assert "Scale twists" not in out


def test_cli_design_prompt_twists(capsys):
    assert S.main(["design", "--prompt", "llm-serving", "--twists"]) == 0
    assert "Scale twists" in capsys.readouterr().out


def test_cli_design_unknown_prompt():
    assert S.main(["design", "--prompt", "nope"]) == 1


def test_cli_design_no_args():
    assert S.main(["design"]) == 1


def test_cli_memo_topic(capsys):
    assert S.main(["memo", "--topic", "Build vs buy the queue"]) == 0
    assert "Build vs buy the queue" in capsys.readouterr().out


def test_cli_memo_save_list_show(tmp_data, capsys):
    assert S.main(["memo", "--topic", "T", "--save", "q1"]) == 0
    capsys.readouterr()
    assert S.main(["memo", "--list"]) == 0
    assert "q1" in capsys.readouterr().out
    assert S.main(["memo", "--show", "q1"]) == 0
    assert "Tech Strategy Memo" in capsys.readouterr().out


def test_cli_memo_show_unknown():
    assert S.main(["memo", "--show", "nope"]) == 1


def test_cli_memo_no_args():
    assert S.main(["memo"]) == 1
