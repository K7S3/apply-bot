"""Tests for the Homebrew packaging artifacts (batch 101: packaging)."""

import os
import re
import stat

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMULA = os.path.join(REPO, "Formula", "candid.rb")
INSTALL_SH = os.path.join(REPO, "scripts", "install.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_formula_exists():
    assert os.path.isfile(FORMULA), "Formula/candid.rb is missing"


def test_formula_class_declaration():
    src = _read(FORMULA)
    assert re.search(r"class\s+Candid\s*<\s*Formula", src), \
        "formula must declare 'class Candid < Formula'"


def test_formula_metadata_stanzas():
    src = _read(FORMULA)
    for stanza in ("desc ", "homepage", "url ", "sha256", "license"):
        assert stanza in src, f"formula is missing the '{stanza.strip()}' stanza"
    assert "https://github.com/K7S3/candid" in src, \
        "formula homepage must be https://github.com/K7S3/candid"


def test_formula_points_at_pypi_sdist_0_3_0():
    src = _read(FORMULA)
    assert "candid-0.3.0.tar.gz" in src, \
        "formula url should point at the 0.3.0 sdist"
    assert "pypi" in src.lower() or "files.pythonhosted.org" in src, \
        "formula url should reference the PyPI sdist"
    assert re.search(r'sha256\s+"[0-9a-fA-F]{64}"', src), \
        "formula sha256 must be a 64-char hex string (placeholder OK)"


def test_formula_placeholder_is_marked():
    src = _read(FORMULA).upper()
    assert "PLACEHOLDER" in src, \
        "the placeholder sha256 must be clearly marked as PLACEHOLDER"


def test_formula_python_dependency():
    src = _read(FORMULA)
    assert 'depends_on "python@3.12"' in src, \
        "formula must depend on python@3.12"


def test_formula_install_method():
    src = _read(FORMULA)
    assert re.search(r"def\s+install", src), "formula must define an install method"
    assert ("virtualenv_install_with_resources" in src
            or "pip install" in src
            or "system \"pip" in src), \
        "formula install should use virtualenv_install_with_resources or a pip-based install"


def test_formula_test_block():
    src = _read(FORMULA)
    assert re.search(r"test\s+do", src), "formula must contain a 'test do' block"
    assert re.search(r"test\s+do.*?candid\s+--version", src, re.DOTALL), \
        "formula test block must run 'candid --version'"
    assert "end" in src


def test_install_sh_exists_and_executable():
    assert os.path.isfile(INSTALL_SH), "scripts/install.sh is missing"
    mode = os.stat(INSTALL_SH).st_mode
    assert mode & stat.S_IXUSR, "scripts/install.sh must be executable"


def test_install_sh_shebang_and_strict_mode():
    src = _read(INSTALL_SH)
    first = src.splitlines()[0]
    assert first.startswith("#!") and ("sh" in first or "bash" in first), \
        "install.sh must start with a sh/bash shebang"
    assert "set -e" in src or "set -eu" in src, \
        "install.sh should use set -e (strict mode)"


def test_install_sh_detects_python3():
    src = _read(INSTALL_SH)
    assert "python3" in src, "install.sh must detect/require python3"
    assert re.search(r"command -v python3", src), \
        "install.sh must check for python3 with 'command -v'"


def test_install_sh_prefers_pipx_with_pip_fallback():
    src = _read(INSTALL_SH)
    assert "pipx" in src, "install.sh must prefer pipx"
    assert re.search(r"pip install.*--user", src) or re.search(r"pip.*install.*--user.*candid", src), \
        "install.sh must fall back to 'pip install --user candid'"


def test_install_sh_verifies_version():
    src = _read(INSTALL_SH)
    assert "candid --version" in src, \
        "install.sh must verify with 'candid --version'"
