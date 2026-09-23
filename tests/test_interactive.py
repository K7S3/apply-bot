"""Tests for candid.interactive (prompt-toolkit primitives).

Data paths are redirected into a temp dir via CANDID_DATA_DIR /
CANDID_CONFIG_DIR env vars. All input is faked by monkeypatching
builtins.input; a real TTY is never used.
"""
import builtins
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import interactive as I  # noqa: E402


@pytest.fixture(autouse=True)
def _data_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CANDID_CONFIG_DIR", str(tmp_path / "config"))


def _fake_stdin(monkeypatch, is_tty: bool):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: is_tty)


def _fake_stdout(monkeypatch, is_tty: bool):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: is_tty)


def _inputs(monkeypatch, responses):
    """Feed scripted answers to input(); track calls."""
    calls = []
    it = iter(responses)

    def fake(prompt=""):
        calls.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"input() called more times than scripted: {prompt!r}")

    monkeypatch.setattr(builtins, "input", fake)
    return calls


class TestIsTty:
    def test_true_only_when_both_tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _fake_stdout(monkeypatch, True)
        assert I.is_tty() is True

    def test_false_when_stdin_not_tty(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        _fake_stdout(monkeypatch, True)
        assert I.is_tty() is False

    def test_false_when_stdout_not_tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _fake_stdout(monkeypatch, False)
        assert I.is_tty() is False


class TestColors:
    def test_no_color_env_disables_ansi(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _fake_stdout(monkeypatch, True)
        monkeypatch.setenv("NO_COLOR", "1")
        assert I.bold("x") == "x"
        assert I.green("x") == "x"
        assert I.yellow("x") == "x"
        assert I.red("x") == "x"
        assert I.dim("x") == "x"

    def test_non_tty_disables_ansi(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _fake_stdout(monkeypatch, False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert I.green("x") == "x"
        assert I.dim("x") == "x"

    def test_tty_emits_ansi(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _fake_stdout(monkeypatch, True)
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert I.green("x") == "\033[32mx\033[0m"
        assert I.bold("x") == "\033[1mx\033[0m"
        assert I.dim("x") == "\033[2mx\033[0m"


class TestBannerHint:
    def test_banner_prints(self, capsys):
        I.banner("Setup")
        out = capsys.readouterr().out
        assert "Setup" in out

    def test_hint_prints(self, capsys):
        I.hint("press q to quit")
        out = capsys.readouterr().out
        assert "press q to quit" in out


class TestInteractiveError:
    def test_is_exception(self):
        assert issubclass(I.InteractiveError, Exception)


class TestAsk:
    def test_plain(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        calls = _inputs(monkeypatch, ["hello"])
        assert I.ask("Name") == "hello"
        assert calls[0] == "Name: "

    def test_default_shown_and_returned(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        calls = _inputs(monkeypatch, [""])
        assert I.ask("Name", default="Alex") == "Alex"
        assert "[Alex]" in calls[0]

    def test_nonempty_overrides_default(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _inputs(monkeypatch, ["Sam"])
        assert I.ask("Name", default="Alex") == "Sam"

    def test_required_reprompts(self, monkeypatch, capsys):
        _fake_stdin(monkeypatch, True)
        calls = _inputs(monkeypatch, ["", "  ", "ok"])
        assert I.ask("Name", required=True) == "ok"
        assert len(calls) == 3

    def test_validator_true_passes(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        _inputs(monkeypatch, ["abc"])
        assert I.ask("Code", validator=lambda v: True) == "abc"

    def test_validator_error_string_reprompts(self, monkeypatch, capsys):
        _fake_stdin(monkeypatch, True)
        calls = _inputs(monkeypatch, ["x", "abcd"])
        assert I.ask("Code", validator=lambda v: True if len(v) == 4 else "need 4 chars") == "abcd"
        assert len(calls) == 2
        assert "need 4 chars" in capsys.readouterr().out

    def test_validator_false_reprompts(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        calls = _inputs(monkeypatch, ["no", "yes"])
        assert I.ask("Q", validator=lambda v: v == "yes") == "yes"
        assert len(calls) == 2

    def test_eof_raises_interactive_error(self, monkeypatch):
        _fake_stdin(monkeypatch, True)
        monkeypatch.setattr(builtins, "input", lambda prompt="": (_ for _ in ()).throw(EOFError))
        with pytest.raises(I.InteractiveError):
            I.ask("Name")

    def test_non_tty_never_calls_input_returns_default(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask("Name", default="Alex") == "Alex"
        assert called == []

    def test_non_tty_no_default_raises(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        with pytest.raises(I.InteractiveError, match="not interactive"):
            I.ask("Name")
        assert called == []

    def test_non_tty_password_does_not_prompt(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask("Secret", default="pw", password=True) == "pw"
        assert called == []


class TestAskChoice:
    def _tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)

    def test_number_selects(self, monkeypatch, capsys):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["2"])
        assert I.ask_choice("Pick", ["a", "b", "c"]) == "b"
        out = capsys.readouterr().out
        assert "1) a" in out and "3) c" in out

    def test_exact_value_selects(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["c"])
        assert I.ask_choice("Pick", ["a", "b", "c"]) == "c"

    def test_tuple_options_return_value(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["2"])
        opts = [("v1", "First label"), ("v2", "Second label")]
        assert I.ask_choice("Pick", opts) == "v2"

    def test_tuple_options_value_text_selects(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["v1"])
        opts = [("v1", "First label"), ("v2", "Second label")]
        assert I.ask_choice("Pick", opts) == "v1"

    def test_invalid_reprompts(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, ["9", "zzz", "1"])
        assert I.ask_choice("Pick", ["a", "b"]) == "a"
        assert len(calls) == 3

    def test_default_value_on_empty(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [""])
        assert I.ask_choice("Pick", ["a", "b"], default="b") == "b"

    def test_default_index_on_empty(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [""])
        assert I.ask_choice("Pick", ["a", "b"], default=1) == "a"

    def test_empty_options_raises(self, monkeypatch):
        self._tty(monkeypatch)
        with pytest.raises(I.InteractiveError):
            I.ask_choice("Pick", [])

    def test_non_tty_returns_default(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask_choice("Pick", ["a", "b"], default="b") == "b"
        assert called == []

    def test_non_tty_no_default_raises(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        with pytest.raises(I.InteractiveError, match="not interactive"):
            I.ask_choice("Pick", ["a", "b"])
        assert called == []


class TestAskConfirm:
    def _tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)

    @pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "Yes"])
    def test_yes_variants(self, monkeypatch, answer):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [answer])
        assert I.ask_confirm("Sure?") is True

    @pytest.mark.parametrize("answer", ["n", "N", "no", "NO", "No"])
    def test_no_variants(self, monkeypatch, answer):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [answer])
        assert I.ask_confirm("Sure?") is False

    def test_empty_returns_default_false(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [""])
        assert I.ask_confirm("Sure?") is False

    def test_empty_returns_default_true(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [""])
        assert I.ask_confirm("Sure?", default=True) is True

    def test_prompt_style_reflects_default(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, ["y", "n"])
        I.ask_confirm("A?", default=True)
        I.ask_confirm("B?", default=False)
        assert "[Y/n]" in calls[0]
        assert "[y/N]" in calls[1]

    def test_invalid_reprompts(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, ["maybe", "y"])
        assert I.ask_confirm("Sure?") is True
        assert len(calls) == 2

    def test_non_tty_returns_default(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask_confirm("Sure?", default=True) is True
        assert I.ask_confirm("Sure?", default=False) is False
        assert called == []


class TestAskPath:
    def _tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)

    def test_returns_path(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["/tmp/foo"])
        assert I.ask_path("Where?") == Path("/tmp/foo")

    def test_expands_tilde(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["~/docs"])
        assert I.ask_path("Where?") == Path.home() / "docs"

    def test_must_exist_reprompts(self, monkeypatch, tmp_path):
        self._tty(monkeypatch)
        real = tmp_path / "real.txt"
        real.write_text("x")
        calls = _inputs(monkeypatch, ["/definitely/not/here", str(real)])
        assert I.ask_path("Where?", must_exist=True) == real
        assert len(calls) == 2

    def test_default_returned(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, [""])
        assert I.ask_path("Where?", default="/tmp/d") == Path("/tmp/d")

    def test_non_tty_returns_default(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask_path("Where?", default="~/x") == Path.home() / "x"
        assert called == []

    def test_non_tty_no_default_raises(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        with pytest.raises(I.InteractiveError, match="not interactive"):
            I.ask_path("Where?")


class TestAskInt:
    def _tty(self, monkeypatch):
        _fake_stdin(monkeypatch, True)

    def test_parses_int(self, monkeypatch):
        self._tty(monkeypatch)
        _inputs(monkeypatch, ["42"])
        assert I.ask_int("Count") == 42

    def test_garbage_reprompts(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, ["abc", "3.5", "7"])
        assert I.ask_int("Count") == 7
        assert len(calls) == 3

    def test_min_max_bounds(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, ["0", "11", "5"])
        assert I.ask_int("Count", min=1, max=10) == 5
        assert len(calls) == 3

    def test_default_on_empty(self, monkeypatch):
        self._tty(monkeypatch)
        calls = _inputs(monkeypatch, [""])
        assert I.ask_int("Count", default=3) == 3
        assert "[3]" in calls[0]

    def test_non_tty_returns_default(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        called = _inputs(monkeypatch, [])
        assert I.ask_int("Count", default=9) == 9
        assert called == []

    def test_non_tty_no_default_raises(self, monkeypatch):
        _fake_stdin(monkeypatch, False)
        with pytest.raises(I.InteractiveError, match="not interactive"):
            I.ask_int("Count")
