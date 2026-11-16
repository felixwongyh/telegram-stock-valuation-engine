"""
tests/test_equity_bridge.py - EV ↔ Equity bridge (Phase 1 — Valuation Integrity).

Locks in the shared bridge used by DCF / Reverse DCF / Multiples / SOTP /
Unit-Economics / NAV so a complex capital structure (Tencent/Alibaba-style
minority interests, preferred equity, associates held outside the operating
FCF, IFRS-16 leases) is bridged explicitly instead of collapsed into a bare
``ev - net_debt``.

Invariants under test:
  * Simple structure degrades to the classic ``ev - net_debt``.
  * Each claim is deducted once — never double-counted when it already sits
    inside net debt.
  * ``equity_to_enterprise`` is the exact inverse of ``enterprise_to_equity``.
  * Missing data is never fabricated into a silent zero *claim*; it is surfaced
    as a note.
"""
from __future__ import annotations

import pytest

from data.models import MarketData
from valuation.equity_bridge import (
    EB_STATUS_INCOMPLETE,
    EB_STATUS_OK,
    EB_STATUS_UNAVAILABLE,
    enterprise_to_equity,
    equity_bridge_components,
    equity_to_enterprise,
)


def _mkt(**kw) -> MarketData:
    base = dict(total_debt=1000.0, cash_and_equivalents=200.0)
    base.update(kw)
    return MarketData(**base)


class TestSimpleStructure:
    def test_degrades_to_ev_minus_net_debt(self):
        b = enterprise_to_equity(5000.0, _mkt())
        assert b.net_debt == pytest.approx(800.0)
        assert b.equity_value == pytest.approx(4200.0)

    def test_no_complex_claim_is_deducted(self):
        b = enterprise_to_equity(5000.0, _mkt())
        assert b.minority_interest == 0.0
        assert b.preferred_equity == 0.0
        assert b.lease_liabilities == 0.0
        assert b.non_operating_assets == 0.0

    def test_has_complex_structure_flag(self):
        assert equity_bridge_components(_mkt())["has_complex_structure"] is False
        assert (
            equity_bridge_components(_mkt(minority_interest=10.0))[
                "has_complex_structure"
            ]
            is True
        )


class TestComplexStructure:
    def test_full_bridge(self):
        m = _mkt(
            minority_interest=300.0,
            preferred_equity=150.0,
            non_operating_assets=400.0,
        )
        b = enterprise_to_equity(5000.0, m)
        # 5000 - 800 (net debt) - 300 - 150 + 400
        assert b.equity_value == pytest.approx(4150.0)

    def test_minority_not_double_deducted_when_inside_net_debt(self):
        m = _mkt(minority_interest=300.0)
        b = enterprise_to_equity(5000.0, m, net_debt_includes_minority=True)
        assert b.minority_interest == 0.0
        assert b.equity_value == pytest.approx(4200.0)
        assert any("少数股东权益" in n for n in b.notes)

    def test_preferred_not_double_deducted_when_inside_net_debt(self):
        m = _mkt(preferred_equity=150.0)
        b = enterprise_to_equity(5000.0, m, net_debt_includes_preferred=True)
        assert b.preferred_equity == 0.0
        assert b.equity_value == pytest.approx(4200.0)

    def test_other_claims_deducted(self):
        b = enterprise_to_equity(5000.0, _mkt(), other_claims=250.0)
        assert b.other_claims == 250.0
        assert b.equity_value == pytest.approx(3950.0)


class TestLeaseConvention:
    def test_lease_deducted_when_not_in_debt(self):
        b = enterprise_to_equity(5000.0, _mkt(leases_in_debt=False), lease_liabilities=120.0)
        assert b.lease_liabilities == 120.0
        assert b.equity_value == pytest.approx(4080.0)

    def test_lease_not_double_deducted_when_in_debt(self):
        b = enterprise_to_equity(5000.0, _mkt(leases_in_debt=True), lease_liabilities=120.0)
        assert b.lease_liabilities == 0.0
        assert b.equity_value == pytest.approx(4200.0)
        assert any("租赁负债" in n for n in b.notes)

    def test_unknown_lease_convention_flags_a_note(self):
        b = enterprise_to_equity(5000.0, _mkt(leases_in_debt=None), lease_liabilities=120.0)
        assert b.lease_liabilities == 120.0
        assert any("租赁负债口径未知" in n for n in b.notes)


class TestInverse:
    @pytest.mark.parametrize(
        "m",
        [
            _mkt(),
            _mkt(minority_interest=300.0, preferred_equity=150.0, non_operating_assets=400.0),
            _mkt(minority_interest=300.0, leases_in_debt=False),
        ],
    )
    def test_round_trip(self, m):
        eq = 4150.0
        ev = equity_to_enterprise(eq, m)
        assert enterprise_to_equity(ev, m).equity_value == pytest.approx(eq)

    def test_round_trip_with_lease(self):
        m = _mkt(leases_in_debt=False)
        eq = 3000.0
        ev = equity_to_enterprise(eq, m, lease_liabilities=120.0)
        back = enterprise_to_equity(ev, m, lease_liabilities=120.0).equity_value
        assert back == pytest.approx(eq)


class TestMissingData:
    def test_missing_net_debt_marks_bridge_incomplete(self):
        # P0-1: an absent debt/cash input must not masquerade as a *verified*
        # zero net debt. The bridge still returns a display number, but flags
        # itself INCOMPLETE and records the missing input.
        m = MarketData()
        b = enterprise_to_equity(5000.0, m)
        assert b.net_debt == 0.0
        assert b.equity_value == pytest.approx(5000.0)
        assert b.net_debt_verified is False
        assert b.status == EB_STATUS_INCOMPLETE
        assert b.missing_inputs == ["net_debt"]
        assert any("未验证" in n for n in b.notes)

    def test_verified_zero_net_debt_is_not_flagged_missing(self):
        # ``total_debt == cash`` is a genuine, verifiable zero net debt.
        m = MarketData(total_debt=500.0, cash_and_equivalents=500.0)
        b = enterprise_to_equity(5000.0, m)
        assert b.net_debt == pytest.approx(0.0)
        assert b.net_debt_verified is True
        assert b.status == EB_STATUS_OK
        assert b.missing_inputs == []

    def test_explicit_zero_net_debt_is_verified(self):
        m = MarketData(net_debt=0.0)
        b = enterprise_to_equity(5000.0, m)
        assert b.net_debt == pytest.approx(0.0)
        assert b.net_debt_verified is True
        assert b.status == EB_STATUS_OK

    def test_missing_ev_never_becomes_zero(self):
        # P0-1: a missing EV must not bridge to a fabricated ``0 - claims``.
        b = enterprise_to_equity(None, _mkt(total_debt=1000.0, cash_and_equivalents=200.0))
        assert b.equity_value is None
        assert b.enterprise_value is None
        assert b.status == EB_STATUS_UNAVAILABLE
        assert "enterprise_value" in b.missing_inputs
        assert b.is_reliable() is False
        assert "N/A" in b.itemized_note()

    def test_missing_cash_only_flags_that_leg(self):
        m = MarketData(total_debt=1000.0)
        b = enterprise_to_equity(5000.0, m)
        assert b.net_debt_verified is False
        assert b.missing_inputs == ["cash_and_equivalents"]

    def test_missing_total_debt_only_flags_that_leg(self):
        m = MarketData(cash_and_equivalents=200.0)
        b = enterprise_to_equity(5000.0, m)
        assert b.net_debt_verified is False
        assert b.missing_inputs == ["total_debt"]

    def test_itemized_note_lists_each_adjustment(self):
        m = _mkt(minority_interest=300.0, non_operating_assets=400.0)
        b = enterprise_to_equity(5000.0, m)
        note = b.itemized_note()
        assert "EV=5,000" in note
        assert "少数股东权益=-300" in note
        assert "+非经营性资产=400" in note


class TestModelWiring:
    """Every EV-based model must declare an itemised bridge in its breakdown."""

    def test_unit_economics_exposes_bridge(self, nbis_data):
        from classification.classifier import BusinessClassifier
        from models.unit_economics import UnitEconomicsSalesModel

        profile = BusinessClassifier().classify(nbis_data)
        r = UnitEconomicsSalesModel().calculate(nbis_data, profile)
        assert "equity_bridge" in r.breakdown
        assert r.breakdown["equity_bridge"]["net_debt"] == pytest.approx(
            -(nbis_data.market.net_debt_or_zero())
        )

    def test_dcf_exposes_bridge(self, nbis_data):
        from classification.classifier import BusinessClassifier
        from models.dcf import DCFModel

        profile = BusinessClassifier().classify(nbis_data)
        r = DCFModel().calculate(nbis_data, profile)
        assert "equity_bridge" in r.breakdown
