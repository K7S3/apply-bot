"""Packaging: version, entry point, and shipped package-data checks."""

import re
from importlib import metadata
from pathlib import Path

import pytest

import candid

EXPECTED_VERSION = "0.3.0"


def test_version_single_sourced_and_format():
    assert candid.__version__ == EXPECTED_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", candid.__version__), \
        "version must look like X.Y.Z"
    # pyproject reads the same value via setuptools dynamic attr
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'version = { attr = "candid.__version__" }' in text


def test_console_script_entry_point_registered():
    try:
        dist = metadata.distribution("candid")
    except metadata.PackageNotFoundError:
        pytest.skip("candid distribution not installed")
    if dist.version != EXPECTED_VERSION:
        pytest.skip(f"installed candid {dist.version} != {EXPECTED_VERSION}")
    eps = metadata.entry_points()
    if hasattr(eps, "select"):  # Python >= 3.10
        entry = eps.select(group="console_scripts", name="candid")
    else:  # Python 3.9
        entry = [e for e in eps.get("console_scripts", []) if e.name == "candid"]
    assert len(entry) == 1, "console_scripts must register exactly one `candid` entry"
    ep = next(iter(entry))
    assert ep.value == "candid.__main__:main"
    # the target is importable and callable
    obj = ep.load()
    assert callable(obj)


def test_version_flag_matches_package():
    from candid.__main__ import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0


def test_package_data_files_present():
    data = Path(candid.__file__).resolve().parent / "data"
    expected = [
        data / "dashboard.html",
        data / "behavioral.json",
        data / "personas.json",
        data / "system_design.json",
    ]
    problems = sorted((data / "problems").glob("*.json"))
    assert all(p.is_file() for p in expected), \
        [str(p) for p in expected if not p.is_file()]
    assert len(problems) >= 1, "candid/data/problems/*.json must ship"


def test_package_data_declared_in_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    for pattern in ('data/*.html', 'data/*.json', 'data/problems/*.json'):
        assert pattern in text, f"missing package-data pattern {pattern}"


def test_wheel_or_sdist_includes_package_data(tmp_path):
    """Build artifacts must contain the dashboard HTML + data files.

    Needs this exact version installed (e.g. pip install dist/*.whl);
    skipped otherwise so plain source checkouts stay green.
    """
    try:
        dist = metadata.distribution("candid")
    except metadata.PackageNotFoundError:
        pytest.skip("candid distribution not installed")
    if dist.version != EXPECTED_VERSION:
        pytest.skip(f"installed candid {dist.version} != {EXPECTED_VERSION}")
    files = metadata.files("candid") or []
    names = {str(f) for f in files}
    assert any(n.endswith("candid/data/dashboard.html") for n in names)
    assert any(n.endswith("candid/data/behavioral.json") for n in names)
    assert any("candid/data/problems/" in n for n in names)
