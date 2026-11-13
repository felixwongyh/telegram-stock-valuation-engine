"""Tests for WACC cost-of-debt clamp vs audit trail."""
from __future__ import annotations

from data.models import FinancialData, FinancialStatement, MarketData
from valuation.wacc import WaccCalculator


def test_kd_floor_matches_reported_cost_of_debt():
    """When implied kd < Rf+0.5%, applied kd must equal floor and sources explain it."""
    rf = 0.0528
    int_exp = 3_210_000_000.0
    debt = 65_136_000_000.0
    kd_implied = int_exp / debt  # ~4.93%

    ttm = FinancialStatement(
        period_end="TTM",
        interest_expense=int_exp,
        operating_income=10e9,
        revenue=89e9,
        shares_outstanding=1e9,
    )
    data = FinancialData(
        ticker="AVGO",
        annual_income=[ttm],
        annual_balance_sheet=[{"Total Debt": debt}],
        ttm=ttm,
        market=MarketData(
            current_price=355.0,
            market_cap=1e12,
            total_debt=debt,
            risk_free_rate=rf,
            equity_risk_premium=0.055,
            beta=1.75,
        ),
    )
    wb = WaccCalculator().calculate(data)
    kd_floor = rf + 0.005
    assert abs(wb.cost_of_debt_implied_raw - kd_implied) < 0.001
    assert abs(wb.cost_of_debt - kd_floor) < 0.001
    assert "floor Rf+0.5%" in wb.sources["kd (pre-tax)"]
    assert f"{kd_implied:.3%}" in wb.sources["kd (implied raw)"]


def _no_interest_data(**market_kwargs) -> FinancialData:
    """Unlevered-cost data with no interest/EBIT → kd uses the Rf+spread fallback."""
    ttm = FinancialStatement(period_end="TTM", revenue=1e9, shares_outstanding=1e9)
    market = MarketData(
        current_price=100.0, market_cap=1e10, total_debt=1e9,
        equity_risk_premium=0.05, beta=1.0, **market_kwargs,
    )
    return FinancialData(
        ticker="TEST", annual_income=[ttm], annual_balance_sheet=[],
        ttm=ttm, market=market,
    )


def test_capm_and_kd_fallback_share_same_treasury_rf(monkeypatch):
    """P0-1: with an EMPTY MarketData Rf but a valid Treasury provider value,
    CAPM (ke) and the cost-of-debt fallback must resolve to the SAME Rf."""
    treasury_rf = 0.05103
    data = _no_interest_data(risk_free_rate=None)  # MarketData carries no Rf

    class _FakeTreasury:
        def get_yield_curve(self):
            return {"rates": {"10 Yr": treasury_rf}, "as_of_date": "2026-01-02"}

    import data.providers as providers_mod
    monkeypatch.setattr(providers_mod, "TreasuryYieldProvider", _FakeTreasury)

    wb = WaccCalculator().calculate(data)

    # calculate() resolved the Treasury value ...
    assert abs(wb.risk_free_rate - treasury_rf) < 1e-9
    # ... CAPM used it ...
    assert f"{treasury_rf:.2%}" in wb.sources["ke"]
    # ... and the debt fallback (Rf + 2.5% BBB-like) used the SAME Rf.
    assert abs(wb.cost_of_debt_implied_raw - (treasury_rf + 0.025)) < 1e-9
    assert f"{treasury_rf:.2%}" in wb.sources["kd (implied raw)"]


def test_implied_cost_of_debt_uses_passed_rf_not_marketdata():
    """P0-1: an explicitly passed Rf must win over MarketData.risk_free_rate."""
    data = _no_interest_data(risk_free_rate=None)  # empty Rf in MarketData
    kd, src = WaccCalculator._implied_cost_of_debt(data, risk_free_rate=0.05)
    assert abs(kd - (0.05 + 0.025)) < 1e-9
    assert f"{0.05:.2%}" in src


def test_implied_cost_of_debt_falls_back_when_no_rf_passed():
    """Standalone callers without an Rf still resolve MarketData → config."""
    data = _no_interest_data(risk_free_rate=0.04)
    kd, src = WaccCalculator._implied_cost_of_debt(data)
    assert abs(kd - (0.04 + 0.025)) < 1e-9
    assert f"{0.04:.2%}" in src
