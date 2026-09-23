"""Windows hardening: line-ending correctness in exports + path handling.

Covers batch-98 worker 4:
  - CSV export uses newline="" (csv module owns the terminator) and
    round-trips through csv.reader without blank rows.
  - Markdown/text exports (offer comparison, prep packs, tailored
    resume/cover-letter writes, legacy run logs) pin newline="\\n" so
    Windows never translates \\n to CRLF.
  - No .ics writer exists in this snapshot, so the RFC 5545 CRLF rule has
    no applicable site (verified by test_no_ics_writer_without_crlf).
  - User-supplied CLI paths expand ~ and env vars (%USERPROFILE% on
    Windows, $VAR on POSIX) via _user_path.
  - No hardcoded '+ "/" +' path concatenation remains in the touched
    export modules.
"""
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid.__main__ import _user_path  # noqa: E402


def _src(mod_name):
    mod = sys.modules.get(mod_name) or __import__(mod_name, fromlist=["*"])
    return Path(mod.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------- path args


def test_user_path_expands_tilde():
    got = _user_path("~/candid_test_dir")
    assert got == Path(os.path.expanduser("~/candid_test_dir"))
    assert not str(got).startswith("~")


def test_user_path_expands_env_var(monkeypatch):
    monkeypatch.setenv("CANDID_TEST_DIR", "expanded_dir")
    if os.name == "nt":
        got = _user_path("%CANDID_TEST_DIR%/sub")
    else:
        got = _user_path("$CANDID_TEST_DIR/sub")
    assert got == Path("expanded_dir") / "sub"


def test_user_path_plain_path_unchanged():
    assert _user_path("relative/path") == Path("relative/path")
    assert _user_path("/abs/path") == Path("/abs/path")


# ------------------------------------------------------- line-ending pinning


def test_csv_export_uses_newline_empty():
    assert 'newline=""' in _src("candid.tracker")


def test_markdown_exports_pin_lf_newline():
    for mod in ("candid.offer", "candid.prep", "candid.__main__",
                "candid.legacy.runner"):
        assert 'newline="\\n"' in _src(mod), mod


def test_no_ics_writer_without_crlf():
    """No .ics writer exists in this snapshot, so the RFC 5545 CRLF rule
    has no applicable site. If one is added later, it must use \\r\\n."""
    hits = [p for p in (ROOT / "candid").rglob("*.py")
            if "BEGIN:VCALENDAR" in p.read_text(encoding="utf-8")]
    assert hits == [], hits


def test_no_hardcoded_slash_concatenation():
    touched = ["candid/__main__.py", "candid/match.py", "candid/offer.py",
               "candid/prep.py", "candid/tracker.py",
               "candid/legacy/runner.py"]
    bad = []
    for rel in touched:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for pat in ('+ "/" +', "+ '/' +", '+"/"+', "+'/'+"):
            if pat in text:
                bad.append(f"{rel}: {pat!r}")
    assert bad == [], bad


# ------------------------------------------------------------- functional


def _write_bytes(path):
    return Path(path).read_bytes()


def test_offer_export_has_lf_only(tmp_path):
    from candid import offer as O
    out = tmp_path / "comparison.md"
    got = O.export_comparison([], path=out)
    data = _write_bytes(got)
    assert b"\r" not in data
    assert b"\n" in data
    assert data.startswith(b"# Offer Comparison")


def test_prep_pack_has_lf_only(tmp_path, monkeypatch):
    from candid import prep as P
    monkeypatch.setattr(C, "PREP_PACKS_DIR", tmp_path)
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    profile = {"skills": ["python"], "years_experience": 5}
    md, out = P.build_pack(profile, "Fictional Corp", "Data Scientist")
    data = _write_bytes(out)
    assert b"\r" not in data
    assert b"\n" in data
    assert md.encode("utf-8") == data


def test_csv_export_roundtrip(tmp_path):
    from candid import tracker as T
    tracker_json = tmp_path / "tracker.json"
    tracker_json.write_text(json.dumps([
        {"id": 1, "company": "Acme", "role": "Engineer", "status": "applied",
         "jd_link": "", "notes": "hello, world", "date_added": "2026-01-01",
         "date_updated": "2026-01-02", "prep_pack": ""},
    ]), encoding="utf-8")
    dest = tmp_path / "apps.csv"
    got = T.export_csv(dest, path=tracker_json)
    raw = _write_bytes(got)
    # csv module writes \r\n terminators; with newline="" there must be no
    # stray \r\r\n or doubled blank rows from platform translation.
    assert b"\r\r\n" not in raw
    with open(got, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["id", "company", "role", "status", "jd_link", "notes",
                       "date_added", "date_updated", "prep_pack"]
    assert rows[1][1] == "Acme"
    assert rows[1][5] == "hello, world"
    assert len(rows) == 2  # header + one row, no blank rows
