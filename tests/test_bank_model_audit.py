"""Bank valuation audit: beta provenance, Rf basis, and RIM formula.

These pin the defects found in the Bank Master Validation audit (Session #55):

* ``breakdown["beta_raw"]`` used to be ``None`` whenever no clamp fired, which
  left the audit trail unable to prove the raw beta had not been overwritten.
* The bank cost-of-equity path silently fell back to a hard-coded 4% Rf with no
  provenance, indistinguishable from a market-observed 10Y yield.
* The RIM formula must reproduce an independent reimplementation exactly.

All tests use synthetic FinancialData so they do not depend on a data snapshot.
"""
from __future__ import annotations

import pytest

from config import BusinessType, SolverStatus
from data.models import CompanyProfile, FinancialData, FinancialStatement, MarketData
from models.bank import BankDDMModel, BankRIMModel, _resolve_discount_inputs_detail


def _profile(**kw) -> CompanyProfile:
    base = dict(
        ticker="TEST",
        business_type=BusinessType.BANK.value,
        classification_confidence=0.95,
        classification_reasons=["synthetic bank"],
        applicable_models=["Bank RIM", "Bank DDM"],
        not_applicable_models=[],
        not_applicable_reasons={},
        revenue_characteristic="Large Cap",
        growth_profile="Moderate Growth",
        profitability_profile="Good",
        cash_flow_profile="Adequate",
        leverage_profile="High Leverage",
        capital_intensity="Asset Intensive",
        is_financial_institution=True,
        is_reit=False,
    )
    base.update(kw)
    return CompanyProfile(**base)


def _bank_data(
    *,
    beta: float | None = 1.0,
    risk_free: float | None = None,
    risk_free_source: str | None = None,
    bvps: float = 100.0,
    book_value: float = 1.0e10,
    net_income: float = 1.2e9,
    eps: float = 10.0,
    shares: float = 1.0e8,
    price: float = 120.0,
    dividend_yield: float | None = None,
) -> FinancialData:
    stmt = FinancialStatement(
        period_end="2026-09-30",
        period_type="ttm",
        net_income=net_income,
        eps=eps,
        shares_outstanding=shares,
    )
    mkt = MarketData(
        current_price=price,
        beta=beta,
        book_value=book_value,
        book_value_per_share=bvps,
        shares_outstanding=shares,
        risk_free_rate=risk_free,
        risk_free_source=risk_free_source,
        equity_risk_premium=0.055,
        dividend_yield=dividend_yield,
    )
    return FinancialData(
        ticker="TEST",
        market=mkt,
        ttm=stmt,
        annual_income=[stmt],
    )


# ---------------------------------------------------------------------------
# beta_raw must always be exposed (never nulled on the unclamped path).
# ---------------------------------------------------------------------------
def test_beta_raw_is_present_when_no_clamp_fires():
    data = _bank_data(beta=0.90)
    _, _, _, beta_raw, clamped, chain = _resolve_discount_inputs_detail(data)
    assert clamped is False
    assert beta_raw == pytest.approx(0.90)
    assert chain.raw_beta == pytest.approx(0.90)


def test_beta_raw_is_preserved_when_clamp_fires():
    # β=1.9 with Rf=4%, ERP=5.5% → ke=14.45%, far above the 10% band ceiling.
    data = _bank_data(beta=1.9)
    beta_used, rf, erp, beta_raw, clamped, chain = _resolve_discount_inputs_detail(data)
    assert clamped is True
    assert beta_raw == pytest.approx(1.9)
    assert beta_used < beta_raw
    assert rf + beta_used * erp <= 0.10 + 1e-12


def test_rim_breakdown_always_carries_beta_raw():
    data = _bank_data(beta=0.90)
    result = BankRIMModel().calculate(data, _profile())
    assert result.status is SolverStatus.SOLVED
    assert result.breakdown["beta_raw"] == pytest.approx(0.90)
    assert result.breakdown["beta_clamped"] is False


def test_ddm_breakdown_always_carries_beta_raw():
    # 3% yield on a $120 price → $3.60 DPS, so the DDM path is applicable.
    data = _bank_data(beta=0.90, dividend_yield=0.03)
    result = BankDDMModel().calculate(data, _profile())
    assert result.status is SolverStatus.SOLVED
    assert result.breakdown["beta_raw"] == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# Rf provenance: assumed default must be recorded, market value must be used.
# ---------------------------------------------------------------------------
def test_assumed_rf_default_is_recorded():
    data = _bank_data(beta=1.0, risk_free=None)
    _, rf, _, _, _, chain = _resolve_discount_inputs_detail(data)
    assert rf == pytest.approx(0.04)
    assert chain.risk_free_source.startswith("assumed")


def test_market_rf_is_used_and_sourced():
    data = _bank_data(beta=1.0, risk_free=0.043, risk_free_source="^TNX US 10Y Treasury (Yahoo)")
    _, rf, _, _, _, chain = _resolve_discount_inputs_detail(data)
    assert rf == pytest.approx(0.043)
    assert chain.risk_free_source == "^TNX US 10Y Treasury (Yahoo)"


def test_explicit_rf_override_is_sourced():
    data = _bank_data(beta=1.0, risk_free=None)
    _, rf, _, _, _, chain = _resolve_discount_inputs_detail(data, risk_free=0.05)
    assert rf == pytest.approx(0.05)
    assert chain.risk_free_source == "explicit_override"


def test_rf_provenance_reaches_serialized_chain():
    data = _bank_data(beta=0.90)
    result = BankRIMModel().calculate(data, _profile())
    chain = result.breakdown["capm_chain"]
    assert chain is not None
    assert "risk_free_source" in chain
    assert chain["risk_free_source"].startswith("assumed")


# ---------------------------------------------------------------------------
# RIM formula: must match an independent reimplementation exactly.
# ---------------------------------------------------------------------------
def _independent_rim(b0: float, roe0: float, ke: float, payout: float, horizon: int) -> float:
    b = b0
    pv = 0.0
    for t in range(1, horizon + 1):
        roe_t = roe0 + (ke - roe0) * (t / horizon)
        pv += ((roe_t - ke) * b) / (1 + ke) ** t
        b = b * (1 + roe_t * (1 - payout))
    return b0 + pv


def test_rim_matches_independent_reimplementation():
    data = _bank_data(beta=0.90, bvps=100.0, book_value=1.0e10,
                      net_income=1.2e9, eps=10.0, dividend_yield=0.03)
    result = BankRIMModel().calculate(data, _profile())
    assert result.status is SolverStatus.SOLVED
    bd = result.breakdown
    expected = _independent_rim(
        bd["book_value_per_share"], bd["roe"], bd["cost_of_equity"],
        bd["payout"], bd["horizon"],
    )
    assert result.value_per_share == pytest.approx(expected, abs=1e-9)


def test_rim_value_equals_book_plus_pv_residual():
    data = _bank_data(beta=0.90)
    result = BankRIMModel().calculate(data, _profile())
    bd = result.breakdown
    assert result.value_per_share == pytest.approx(
        bd["book_value_per_share"] + bd["pv_residual_income"], abs=1e-9
    )


# ---------------------------------------------------------------------------
# Guard rails: the models must decline rather than fabricate.
# ---------------------------------------------------------------------------
def test_rim_declines_without_book_equity():
    data = _bank_data(bvps=0.0, book_value=0.0)
    result = BankRIMModel().calculate(data, _profile())
    assert result.status is SolverStatus.INSUFFICIENT_DATA


def test_bank_models_refuse_non_financial_profile():
    data = _bank_data()
    non_fin = CompanyProfile(
        ticker="X",
        business_type=BusinessType.MATURE_TECH.value,
        classification_confidence=0.9,
        classification_reasons=["synthetic tech"],
        applicable_models=["DCF"],
        not_applicable_models=[],
        not_applicable_reasons={},
        revenue_characteristic="Large Cap",
        growth_profile="Moderate Growth",
        profitability_profile="Excellent",
        cash_flow_profile="Strong FCF",
        leverage_profile="Low Leverage",
        capital_intensity="Asset Light",
        is_financial_institution=False,
        is_reit=False,
    )
    ok_rim, reasons_rim = BankRIMModel().applicability_check(data, non_fin)
    ok_ddm, reasons_ddm = BankDDMModel().applicability_check(data, non_fin)
    assert ok_rim is False and reasons_rim
    assert ok_ddm is False and reasons_ddm
