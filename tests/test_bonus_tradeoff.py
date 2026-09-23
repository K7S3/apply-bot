"""Tests for the signing bonus vs base trade-off calculator."""

import pytest

from candid import bonus_tradeoff as T


# -- equivalence -----------------------------------------------------------

def test_bonus_raise_equivalence_simple():
    r = T.bonus_raise_equivalence(10_000, 4)
    assert r["equivalent_sign_on"] == 40_000
    assert r["simple_sign_on"] == 40_000


def test_bonus_raise_equivalence_discounted():
    r = T.bonus_raise_equivalence(10_000, 4, discount_rate=0.05)
    assert r["equivalent_sign_on"] < 40_000  # money today > money later
    assert r["equivalent_sign_on"] == pytest.approx(35_460, abs=10)


def test_base_raise_equivalence_inverts():
    r = T.base_raise_equivalence(40_000, 4)
    assert r["equivalent_annual_raise"] == 10_000
    back = T.bonus_raise_equivalence(r["equivalent_annual_raise"], 4)
    assert back["equivalent_sign_on"] == pytest.approx(40_000)


def test_equivalence_rejects_negative():
    with pytest.raises(T.TradeoffError):
        T.bonus_raise_equivalence(-1, 4)
    with pytest.raises(T.TradeoffError):
        T.base_raise_equivalence(-5, 2)


def test_equivalence_rejects_bad_rate():
    with pytest.raises(T.TradeoffError):
        T.bonus_raise_equivalence(1_000, 4, discount_rate=1.5)


def test_equivalence_rejects_zero_years():
    with pytest.raises(T.TradeoffError):
        T.bonus_raise_equivalence(1_000, 0)


# -- amortization ----------------------------------------------------------

def test_amortize_sign_on_simple():
    r = T.amortize_sign_on(60_000, 3)
    assert r["annualized_value"] == 20_000


def test_amortize_sign_on_discounted_is_higher_annual():
    # discounted money later is worth less, so the same lump buys a larger
    # annualized figure under discounting
    r = T.amortize_sign_on(60_000, 3, discount_rate=0.05)
    assert r["annualized_value"] > 20_000


# -- projection ------------------------------------------------------------

def test_projection_year1_includes_sign_on():
    rows = T.multi_year_projection(180_000, 15, 30_000, 50_000, 15_000, 2)
    assert rows[0]["sign_on"] == 30_000
    assert rows[1]["sign_on"] == 0
    assert rows[0]["total"] == pytest.approx(
        180_000 + 27_000 + 50_000 + 15_000 + 30_000)


def test_projection_base_grows_with_raise():
    rows = T.multi_year_projection(100_000, 0, 0, 0, 0, 3, raise_pct=10)
    assert rows[0]["base"] == pytest.approx(100_000)
    assert rows[1]["base"] == pytest.approx(110_000)
    assert rows[2]["base"] == pytest.approx(121_000)


def test_projection_bonus_attainment_scales():
    full = T.multi_year_projection(100_000, 20, 0, 0, 0, 1, bonus_attainment=1.0)
    half = T.multi_year_projection(100_000, 20, 0, 0, 0, 1, bonus_attainment=0.5)
    assert full[0]["bonus"] == pytest.approx(20_000)
    assert half[0]["bonus"] == pytest.approx(10_000)


def test_projection_rejects_bad_attainment():
    with pytest.raises(T.TradeoffError):
        T.multi_year_projection(100_000, 10, 0, 0, 0, 2, bonus_attainment=2.0)


# -- cumulative / NPV ------------------------------------------------------

def test_cumulative_value():
    rows = T.multi_year_projection(100_000, 0, 0, 0, 0, 3, raise_pct=0)
    cum = T.cumulative_value(rows)
    assert cum[2]["cumulative"] == pytest.approx(300_000)
    assert all(cum[i]["cumulative"] < cum[i + 1]["cumulative"]
               for i in range(2))


def test_present_value_discounts_future():
    assert T.present_value([100_000, 100_000], 0.05) < 200_000
    assert T.present_value([100_000, 100_000], 0.0) == 200_000


def test_present_value_accepts_projection_rows():
    rows = T.multi_year_projection(100_000, 0, 0, 0, 0, 2, raise_pct=0)
    assert T.present_value(rows, 0.0) == pytest.approx(200_000)


# -- breakeven --------------------------------------------------------------

def test_breakeven_years_basic():
    # A: 180k base, no sign-on. B: 165k base, 40k sign-on.
    r = T.breakeven_years(180_000, 0, 165_000, 40_000)
    assert r["crosses"] is True
    assert r["breakeven_year"] == pytest.approx(40_000 / 15_000, abs=0.01)
    assert r["higher_base_offer"] == "A"
    assert r["higher_sign_on_offer"] == "B"


def test_breakeven_equal_bases_never_cross():
    r = T.breakeven_years(170_000, 10_000, 170_000, 50_000)
    assert r["crosses"] is False
    assert r["breakeven_year"] is None


def test_breakeven_dominant_offer_wins_day_one():
    r = T.breakeven_years(190_000, 50_000, 170_000, 10_000)
    assert r["breakeven_year"] == 0.0


def test_breakeven_identical():
    r = T.breakeven_years(170_000, 20_000, 170_000, 20_000)
    assert r["crosses"] is True
    assert r["breakeven_year"] == 0.0


# -- guaranteed vs probabilistic -------------------------------------------

def test_bonus_vs_sign_on_sign_on_wins():
    r = T.bonus_vs_sign_on(30_000, 45_000, attainment=0.5)
    assert r["bonus_expected_value"] == pytest.approx(22_500)
    assert r["better_expected_value"] == "sign-on"


def test_bonus_vs_sign_on_bonus_wins():
    r = T.bonus_vs_sign_on(20_000, 45_000, attainment=1.0)
    assert r["better_expected_value"] == "target bonus"


def test_bonus_vs_sign_on_rejects_bad_attainment():
    with pytest.raises(T.TradeoffError):
        T.bonus_vs_sign_on(10_000, 20_000, attainment=-0.1)


# -- tax timing --------------------------------------------------------------

def test_tax_timing_notes_flags_year1_spike():
    notes = T.tax_timing_notes([300_000, 190_000, 195_000, 200_000])
    assert any("Year 1" in n for n in notes)
    assert any("not advice" in n for n in notes)


def test_tax_timing_notes_flat_income_quiet():
    notes = T.tax_timing_notes([200_000, 205_000, 210_000])
    assert not any("Year 1" in n for n in notes)


def test_tax_timing_notes_rejects_empty():
    with pytest.raises(T.TradeoffError):
        T.tax_timing_notes([])


# -- counter bridge ----------------------------------------------------------

def test_counter_bridge_amount():
    r = T.counter_bridge_amount(15_000, 3, discount_rate=0.0)
    assert r["suggested_sign_on_ask"] == 45_000
    assert r["undiscounted_gap_total"] == 45_000
    assert "45,000" in r["script"]


def test_counter_bridge_discounted_ask_smaller():
    r = T.counter_bridge_amount(15_000, 3, discount_rate=0.05)
    assert r["suggested_sign_on_ask"] < 45_000


def test_counter_bridge_rejects_negative_gap():
    with pytest.raises(T.TradeoffError):
        T.counter_bridge_amount(-1_000, 3)


# -- compare -----------------------------------------------------------------

def _offer(company, base, sign_on, bonus_pct=10, equity_yr=40_000,
           benefits=15_000):
    return {"company": company, "base": base, "bonus_target_pct": bonus_pct,
            "sign_on": sign_on, "annual_equity": equity_yr,
            "benefits_value": benefits}


def test_compare_tradeoffs_picks_higher_total():
    comp = T.compare_tradeoffs(_offer("A", 180_000, 0),
                               _offer("B", 170_000, 0), years=2,
                               discount_rate=0.0, raise_pct=0)
    assert comp["total_a"] > comp["total_b"]
    assert any("A pays" in v for v in comp["verdicts"])


def test_compare_tradeoffs_npv_can_differ_from_total():
    # B pays a huge sign-on up front but lower base: NPV favors B,
    # multi-year total favors A.
    comp = T.compare_tradeoffs(_offer("A", 200_000, 0),
                               _offer("B", 170_000, 100_000), years=5,
                               discount_rate=0.08, raise_pct=0,
                               attainment=1.0)
    assert comp["total_a"] > comp["total_b"] or comp["total_b"] > comp["total_a"]
    assert comp["npv_a"] != comp["npv_b"]
    assert len(comp["verdicts"]) >= 3


def test_compare_tradeoffs_needs_company():
    with pytest.raises(T.TradeoffError):
        T.compare_tradeoffs({"base": 1}, _offer("B", 1, 0))


def test_compare_tradeoffs_projection_lengths():
    comp = T.compare_tradeoffs(_offer("A", 1, 0), _offer("B", 1, 0), years=5)
    assert len(comp["projection_a"]) == 5
    assert len(comp["cumulative_b"]) == 5


# -- report ------------------------------------------------------------------

def test_render_report_contains_verdicts():
    comp = T.compare_tradeoffs(_offer("Acme", 180_000, 30_000),
                               _offer("Beta", 190_000, 0), years=3)
    text = T.render_report(comp)
    assert "Acme" in text and "Beta" in text
    assert "Verdicts" in text
    assert "Tax timing notes" in text


def test_export_report_writes_markdown(tmp_path):
    comp = T.compare_tradeoffs(_offer("Acme", 180_000, 30_000),
                               _offer("Beta", 190_000, 0), years=3)
    path = T.export_report(comp, path=tmp_path / "tradeoff.md")
    md = path.read_text(encoding="utf-8")
    assert md.startswith("# Sign-on vs base trade-off")
    assert "| Year |" in md
    assert "## Verdicts" in md


def test_export_report_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr("candid.config.DATA_DIR", tmp_path)
    comp = T.compare_tradeoffs(_offer("Acme", 180_000, 30_000),
                               _offer("Beta", 190_000, 0), years=3)
    path = T.export_report(comp)
    assert path.exists()
    assert path.parent.name == "tradeoff_reports"


# -- CLI ---------------------------------------------------------------------

import contextlib
import io
import tempfile
from pathlib import Path

from candid import __main__ as CLI
from candid import config as C


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            CLI.main(argv)
        except SystemExit as e:
            return (e.code if isinstance(e.code, int) else 1,
                    out.getvalue(), err.getvalue())
    return 0, out.getvalue(), err.getvalue()


@pytest.fixture()
def _tmpdata():
    tmp = Path(tempfile.mkdtemp(prefix="candid-tradeoff-"))
    saved = {n: getattr(C, n) for n in ("OFFERS_PATH", "DATA_DIR")}
    C.OFFERS_PATH = tmp / "offers.json"
    C.DATA_DIR = tmp
    C.ensure_data_dirs()
    yield tmp
    for n, v in saved.items():
        setattr(C, n, v)


def test_cli_equiv(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "equiv", "--raise", "10000",
                             "--years", "4"])
    assert code == 0
    assert "sign-on" in out


def test_cli_equiv_sign_on_direction(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "equiv", "--sign-on", "40000",
                             "--years", "4"])
    assert code == 0
    assert "/yr" in out


def test_cli_project(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "project", "--company", "Acme",
                             "--base", "180000", "--sign-on", "30000",
                             "--years", "3"])
    assert code == 0
    assert "yr 1" in out and "Cumulative" in out


def test_cli_breakeven_raw(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "breakeven", "--base-a", "180000",
                             "--sign-on-a", "0", "--base-b", "165000",
                             "--sign-on-b", "40000"])
    assert code == 0
    assert "2.7 years" in out


def test_cli_breakeven_with_recorded_offers(_tmpdata):
    from candid import offer as O
    oa = O.add({"company": "Acme", "role": "SDE", "base": 180000})
    ob = O.add({"company": "Beta", "role": "SDE", "base": 165000,
                "sign_on": 40000})
    code, out, _ = _run_cli(["tradeoff", "breakeven",
                             "--offer-a", str(oa["id"]),
                             "--offer-b", str(ob["id"])])
    assert code == 0
    assert "2.7 years" in out


def test_cli_compare_recorded_offers(_tmpdata):
    from candid import offer as O
    oa = O.add({"company": "Acme", "role": "SDE", "base": 180000,
                "sign_on": 30000, "bonus_target_pct": 10})
    ob = O.add({"company": "Beta", "role": "SDE", "base": 195000,
                "bonus_target_pct": 10})
    code, out, _ = _run_cli(["tradeoff", "compare",
                             "--offer-a", str(oa["id"]),
                             "--offer-b", str(ob["id"]),
                             "--years", "3"])
    assert code == 0
    assert "Acme" in out and "Beta" in out and "Verdicts" in out


def test_cli_counter(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "counter", "--gap", "15000",
                             "--years", "3"])
    assert code == 0
    assert "sign-on" in out


def test_cli_risk(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "risk", "--sign-on", "30000",
                             "--bonus-target", "45000", "--attainment", "0.8"])
    assert code == 0
    assert "target bonus" in out


def test_cli_report_to_file(_tmpdata, tmp_path):
    out_path = tmp_path / "r.md"
    code, out, _ = _run_cli(["tradeoff", "report", "--company-a", "Acme",
                             "--base-a", "180000", "--company-b", "Beta",
                             "--base-b", "190000", "--years", "2",
                             "--out", str(out_path)])
    assert code == 0
    md = out_path.read_text(encoding="utf-8")
    assert md.startswith("# Sign-on vs base trade-off")
    assert "| Year | Acme total | Beta total |" in md


def test_cli_tradeoff_in_help(_tmpdata):
    code, out, _ = _run_cli(["tradeoff", "--help"])
    assert code == 0
    for sub in ("equiv", "project", "breakeven", "compare", "counter",
                "risk", "report"):
        assert sub in out


def test_cli_bad_offer_id_is_friendly_error(_tmpdata):
    code, out, err = _run_cli(["tradeoff", "breakeven", "--offer-a", "42",
                               "--offer-b", "43"])
    assert code != 0
    assert "No offer with id" in (out + err)
