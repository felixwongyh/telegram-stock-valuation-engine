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
