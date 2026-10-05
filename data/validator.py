"""
data/validator.py - Data Validation & Quality Scoring
"""
from __future__ import annotations

from typing import List, Tuple

from config import RISK_THRESHOLDS, RiskType, get_logger
from data.models import FinancialData, FinancialStatement

log = get_logger("data.validator")


class DataValidator:
    """Validates financial data and computes quality scores."""

    MIN_ANNUAL_PERIODS = 3

    @staticmethod
    def validate(data: FinancialData) -> FinancialData:
        """Run full validation pipeline."""
        data = DataValidator._check_minimal_requirements(data)
        data = DataValidator._check_statement_consistency(data)
        data = DataValidator._check_market_data(data)
        data = DataValidator._finalize_quality_score(data)
        return data

    @staticmethod
    def _check_minimal_requirements(data: FinancialData) -> FinancialData:
        n_annual = len(data.annual_income)
        if n_annual < DataValidator.MIN_ANNUAL_PERIODS:
            data.quality.missing_fields.append(
                f"Only {n_annual} annual statements (≥{DataValidator.MIN_ANNUAL_PERIODS} required)"
            )
        ttm = data.ttm
        if ttm is not None:
            if not ttm.has_minimal_dcf_inputs():
                missing = []
                if ttm.revenue is None:
                    missing.append("ttm.revenue")
                if ttm.operating_income is None:
                    missing.append("ttm.operating_income")
                if ttm.shares_outstanding is None:
                    missing.append("ttm.shares_outstanding")
                if missing:
                    data.quality.missing_fields.append(
                        f"TTM missing DCF inputs: {', '.join(missing)}"
                    )
        else:
            data.quality.missing_fields.append("TTM statement missing")
        return data

    @staticmethod
    def _check_statement_consistency(data: FinancialData) -> FinancialData:
        for i, stmt in enumerate(data.annual_income):
            issues = DataValidator._validate_single_statement(stmt)
            if issues:
                data.quality.restatement_notes.append(
                    f"Annual[{i}] ({stmt.period_end}): {'; '.join(issues)}"
                )
        if data.ttm:
            issues = DataValidator._validate_single_statement(data.ttm)
            if issues:
                data.quality.restatement_notes.append(
                    f"TTM: {'; '.join(issues)}"
                )
        return data

    @staticmethod
    def _validate_single_statement(stmt: FinancialStatement) -> List[str]:
        issues: List[str] = []
        if (stmt.revenue is not None and stmt.gross_profit is not None
                and stmt.cost_of_revenue is None):
            pass
        if (stmt.revenue is not None and stmt.operating_income is not None
                and stmt.operating_income > stmt.revenue):
            issues.append("operating_income > revenue")
        if (stmt.ebitda is not None and stmt.ebit is not None
                and stmt.depreciation_amortization is not None):
            if abs(stmt.ebitda - (stmt.ebit + stmt.depreciation_amortization)) > 1e-6:
                issues.append("EBITDA != EBIT + D&A")
        if (stmt.operating_cash_flow is not None and stmt.capex is not None
                and stmt.free_cash_flow is not None):
            expected_fcf = stmt.operating_cash_flow + stmt.capex
            if expected_fcf != 0 and abs(stmt.free_cash_flow - expected_fcf) / abs(expected_fcf) > 0.05:
                issues.append("FCF ~ OCF + CapEx mismatch >5%")
        if (stmt.net_income is not None and stmt.eps is not None
                and stmt.shares_outstanding and stmt.shares_outstanding > 0):
            expected_eps = stmt.net_income / stmt.shares_outstanding
            if expected_eps != 0 and abs(stmt.eps - expected_eps) / abs(expected_eps) > 0.05:
                issues.append("EPS ~ NI / shares mismatch >5%")
        return issues

    @staticmethod
    def _check_market_data(data: FinancialData) -> FinancialData:
        mkt = data.market
        missing = []
        if mkt.current_price is None:
            missing.append("current_price")
        if mkt.shares_outstanding is None:
            missing.append("shares_outstanding")
        if missing:
            data.quality.missing_fields.append(f"Market: {', '.join(missing)}")
        if mkt.market_cap is None and mkt.current_price and mkt.shares_outstanding:
            mkt.market_cap = mkt.current_price * mkt.shares_outstanding
        return data

    @staticmethod
    def _finalize_quality_score(data: FinancialData) -> FinancialData:
        score = 100
        n_annual = len(data.annual_income)
        if n_annual < 5:
            score -= (5 - n_annual) * 5
        if data.quality.missing_fields:
            score -= min(30, len(data.quality.missing_fields) * 5)
        if data.quality.inconsistent_periods:
            score -= 15
        if data.quality.mixed_currencies:
            score -= 20
        if data.quality.restatement_notes:
            score -= min(15, len(data.quality.restatement_notes) * 3)
        data.quality.data_quality_score = max(0, min(100, score))
        return data

    @staticmethod
    def dcf_feasibility_check(data: FinancialData) -> Tuple[bool, List[str]]:
        """Check if DCF model can run. Returns (ok, reasons_if_fail)."""
        reasons: List[str] = []
        ttm = data.ttm
        if ttm is None:
            reasons.append("No TTM statement")
        else:
            if ttm.revenue is None:
                reasons.append("TTM revenue missing")
            if ttm.operating_income is None:
                reasons.append("TTM operating_income missing")
            if ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
                reasons.append("TTM shares_outstanding invalid")
        if data.market.current_price is None:
            reasons.append("Current price missing")
        if data.quality.data_quality_score < 40:
            reasons.append(f"Data quality score too low ({data.quality.data_quality_score}<40)")
        return (len(reasons) == 0, reasons)


__all__ = ["DataValidator"]
