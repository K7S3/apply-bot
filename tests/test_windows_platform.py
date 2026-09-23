"""Tests for candid.platform (Windows-aware path helpers) and the
platform wiring in candid.config.

Windows branches are exercised by monkeypatching the module-level
``candid.platform._ON_WINDOWS`` flag, so these run on any OS.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from candid import config
from candid import platform


@pytest.fixture
def win(monkeypatch):
    """Force the Windows branch for platform helpers."""
    monkeypatch.setattr(platform, "_ON_WINDOWS", True)


def test_is_windows_is_posix():
    # This suite runs on Linux: not Windows, is POSIX.
    assert platform.is_windows() is False
    assert platform.is_posix() is True
    assert platform._ON_WINDOWS == (os.name == "nt")


def test_data_dir_posix(tmp_path):
    assert platform.data_dir() == Path.home() / ".candid"
    assert platform.data_dir("myapp") == Path.home() / ".myapp"


def test_config_dir_posix():
    assert platform.config_dir() == Path.home() / ".config" / "candid"
    assert platform.config_dir("myapp") == Path.home() / ".config" / "myapp"


def test_data_dir_windows_appdata(win, monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\k\AppData\Roaming")
    assert platform.data_dir() == Path(r"C:\Users\k\AppData\Roaming") / "candid"


def test_data_dir_windows_fallback(win, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\k")
    expected = Path(os.path.join(r"C:\Users\k", "AppData", "Roaming")) / "candid"
    assert platform.data_dir() == expected


def test_config_dir_windows_uses_appdata(win, monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\k\AppData\Roaming")
    assert platform.config_dir() == platform.data_dir()


def test_long_path_posix_noop(tmp_path):
    long_p = tmp_path / ("x" * 300)
    assert platform.long_path(long_p) == Path(long_p)
    assert platform.long_path("/short") == Path("/short")


def test_long_path_windows_short_unchanged(win):
    p = Path("/a/b.txt")
    assert platform.long_path(p) == Path("/a/b.txt")


def test_long_path_windows_long_gets_prefix(win):
    long_p = "/" + "x" * 300 + "/file.txt"
    got = platform.long_path(long_p)
    assert str(got) == "\\\\?\\" + long_p


def test_long_path_windows_already_prefixed(win):
    prefixed = "\\\\?\\" + "/" + "y" * 300 + "/file.txt"
    assert platform.long_path(prefixed) == Path(prefixed)


def test_long_path_windows_relative_long_unchanged(win):
    # Not absolute: no prefix even when long.
    rel = "x" * 300 + "/file.txt"
    assert platform.long_path(rel) == Path(rel)


def test_normalize_path_tilde():
    assert platform.normalize_path("~/candid_x") == Path.home() / "candid_x"


def test_normalize_path_dollar_var_posix(monkeypatch):
    monkeypatch.setenv("CANDID_TESTVAR", "sub")
    assert platform.normalize_path("$CANDID_TESTVAR/dir") == Path("sub/dir")


def test_normalize_path_windows_percent_var(win, monkeypatch):
    monkeypatch.setenv("CANDID_TESTVAR", "sub")
    assert platform.normalize_path("%CANDID_TESTVAR%/dir") == Path("sub/dir")


def test_normalize_path_windows_unknown_var_kept(win):
    got = platform.normalize_path("%CANDID_NO_SUCH_VAR_XYZ%/dir")
    assert "%CANDID_NO_SUCH_VAR_XYZ%" in str(got)


@pytest.mark.parametrize(
    "bad,expected",
    [
        ('a<b>c:d"e/f\\g|h?i*j', "abcdefghij"),
        ("plain.txt", "plain.txt"),
        ("trailing.", "trailing"),
    ],
)
def test_safe_filename_strips_reserved_chars(bad, expected):
    assert platform.safe_filename(bad) == expected


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "Aux", "NUL", "COM1", "com9", "LPT1", "lpt9"])
def test_safe_filename_reserved_names(name):
    got = platform.safe_filename(name)
    assert got == "_" + name


def test_safe_filename_reserved_name_with_extension():
    assert platform.safe_filename("con.txt") == "_con.txt"


def test_safe_filename_non_reserved_like_names_ok():
    # "console" starts with "con" but is not a reserved name.
    assert platform.safe_filename("console.log") == "console.log"
    assert platform.safe_filename("COM10") == "COM10"


def test_safe_filename_truncates():
    got = platform.safe_filename("x" * 200)
    assert got == "x" * 120


def test_safe_filename_never_empty():
    assert platform.safe_filename("") == "_"
    assert platform.safe_filename("***") == "_"


# --- config.py wiring --------------------------------------------------------


def test_config_dir_uses_platform_config_dir(monkeypatch):
    # On this Linux box the default must be unchanged from before.
    monkeypatch.delenv("CANDID_CONFIG_DIR", raising=False)
    assert config._config_dir() == Path.home() / ".config" / "candid"


def test_config_dir_env_override_normalized(monkeypatch):
    monkeypatch.setenv("CANDID_CONFIG_DIR", "~/candid_cfg_x")
    assert config._config_dir() == Path.home() / "candid_cfg_x"


def test_config_dir_env_override_windows_percent_var(win, monkeypatch):
    monkeypatch.setenv("CANDID_DATA_VAR", r"C:\data")
    monkeypatch.setenv("CANDID_CONFIG_DIR", "%CANDID_DATA_VAR%/cfg")
    assert config._config_dir() == Path(r"C:\data") / "cfg"


def test_data_dir_default_project_local(monkeypatch):
    monkeypatch.delenv("CANDID_DATA_DIR", raising=False)
    assert config._data_dir() == config.PROJECT_ROOT / "candid_data"


def test_data_dir_env_override_normalized(monkeypatch):
    monkeypatch.setenv("CANDID_DATA_DIR", "~/candid_data_x")
    assert config._data_dir() == Path.home() / "candid_data_x"


def test_config_dir_default_windows_branch(win, monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\k\AppData\Roaming")
    assert config._config_dir() == Path(r"C:\Users\k\AppData\Roaming") / "candid"
