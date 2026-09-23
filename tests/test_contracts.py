"""Tests for candid.contracts (contract-rate normalization + FTE comparison).

No network. Pure parsing and arithmetic.
"""

import pytest

from candid import contracts
from candid.contracts import (annualize, compare_contract_vs_fte,
                              fte_equivalent, parse_rate)


class TestParseRate:
    @pytest.mark.parametrize("text,expected", [
        ("$120/hr", (120.0, "hour")),
        ("$120 per hour", (120.0, "hour")),
        ("$120/hour", (120.0, "hour")),
        ("$85/hrs", (85.0, "hour")),
        ("120/hr", (120.0, "hour")),          # $ optional
        ("$150k/yr", (150000.0, "year")),
        ("$150K", (150000.0, "year")),         # bare = annualized
        ("$12k/month", (12000.0, "month")),
        ("$12000 monthly", (12000.0, "month")),
        ("$900/day", (900.0, "day")),
        ("$900 per day", (900.0, "day")),
        ("$900 daily", (900.0, "day")),
        ("$200,000/year", (200000.0, "year")),
        ("$110-130/hr", (120.0, "hour")),      # range -> midpoint
        ("$110 - 130 per hour", (120.0, "hour")),
        ("$100k-$140k/yr", (120000.0, "year")),
        ("$120 an hour", (120.0, "hour")),
    ])
    def test_variants(self, text, expected):
        got = parse_rate(text)
        assert got == {"amount": expected[0], "period": expected[1]}

    @pytest.mark.parametrize("text", [
        "", "hello world", "$abc/hr", "$/hr", "$-50/hr", "50 percent",
        None, 123, "$120/fortnight",
    ])
    def test_unparseable_returns_none(self, text):
        assert parse_rate(text) is None


class TestAnnualize:
    @pytest.mark.parametrize("period,factor", [
        ("hour", 2080), ("day", 260), ("month", 12), ("year", 1),
    ])
    def test_math(self, period, factor):
        assert annualize({"amount": 100, "period": period}) == 100 * factor

    def test_custom_hours(self):
        assert annualize({"amount": 100, "period": "hour"},
                         hours_per_year=1000) == 100000

    def test_none_raises(self):
        with pytest.raises(ValueError):
            annualize(None)

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            annualize({"amount": 100, "period": "fortnight"})


class TestFteEquivalent:
    def test_worked_example(self):
        # $150k/yr contract, $20k of FTE benefits:
        # 150000 * (1 - 0.0765) - 20000 = 138525 - 20000 = 118525
        assert fte_equivalent(150000, benefits_value=20000) == 118525.0

    def test_zero_benefits(self):
        # 2080 hrs * $100/hr = 208000; 208000 * 0.9235 = 192088
        assert fte_equivalent(208000) == 192088.0

    def test_zero_contract(self):
        assert fte_equivalent(0) == 0.0


class TestCompare:
    def test_worked_example(self):
        # "$120/hr" -> 120 * 2080 = 249600 annualized.
        # net approx: 249600 * 0.9235 = 230505.60
        # fte equiv: 230505.60 - 20000 = 210505.60
        # delta vs 180000 FTE: 249600 - 180000 = 69600
        out = compare_contract_vs_fte("$120/hr", 180000, fte_benefits=20000)
        assert out["contract_rate"] == {"amount": 120.0, "period": "hour"}
        assert out["contract_annual"] == 249600.0
        assert out["contract_net_approx"] == pytest.approx(230505.60)
        assert out["fte_total_comp"] == 180000.0
        assert out["fte_equiv_salary"] == pytest.approx(210505.60)
        assert out["delta"] == pytest.approx(69600.0)
        assert "69,600" in out["verdict"]
        assert len(out["assumptions"]) >= 4

    def test_verdict_contract_wins(self):
        out = compare_contract_vs_fte("$120/hr", 180000)
        assert out["delta"] > 0
        assert "Contract pays" in out["verdict"]

    def test_verdict_fte_wins(self):
        out = compare_contract_vs_fte("$50/hr", 180000)
        assert out["delta"] < 0
        assert "FTE offer pays" in out["verdict"]

    def test_verdict_tie(self):
        out = compare_contract_vs_fte("$150K", 150000)
        assert out["delta"] == 0
        assert "about the same" in out["verdict"]

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            compare_contract_vs_fte("not a rate", 180000)
