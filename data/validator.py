"""
data/validator.py - Data Validation & Quality Scoring
"""
from __future__ import annotations

from typing import List, Tuple

from config import DataSource, RISK_THRESHOLDS, RiskType, get_logger
from data.models import FinancialData, FinancialStatement
from data.nwc_utils import effective_tax_rate, infer_change_in_nwc

log = get_logger("data.validator")


class DataValidator:
    """Validates financial data and computes quality scores."""

    MIN_ANNUAL_PERIODS = 3

    @staticmethod
    def validate(data: FinancialData) -> FinancialData:
        """Run full validation pipeline."""
        data = DataValidator._check_minimal_requirements(data)
        data = DataValidator._check_data_provenance(data)
        data = DataValidator._check_statement_consistency(data)
        data = DataValidator._check_market_data(data)
        data = DataValidator._check_reconciliation(data)
        data = DataValidator._finalize_quality_score(data)
        return data

    @staticmethod
    def _check_reconciliation(data: FinancialData) -> FinancialData:
        """Cross-validate headline market/financial fields (data 对账层),
        then apply the reverse-validation overrides so downstream models do
        not read a provider-contaminated base."""
        from data.reconciliation import apply_overrides, reconcile
        try:
            report = reconcile(data)
        except Exception as e:  # never let reconciliation break the pipeline
            log.warning("Reconciliation failed for %s: %s", data.ticker, e)
            return data
        data.reconciliation = report
        data.quality.reconciliation_mismatches = len(report.mismatches)
        for c in report.mismatches:
            note = f"[对账不一致] {c.name}: 供应商/推算偏差 {c.rel_diff:+.1%}" if c.rel_diff is not None else f"[对账不一致] {c.name}"
            if note not in data.quality.restatement_notes:
                data.quality.restatement_notes.append(note)
        # ---- Reverse validation: replace provider fields off by >25% -------
        try:
            override_log = apply_overrides(data, report)
        except Exception as e:  # overrides must never break the pipeline
            log.warning("Reconciliation overrides failed for %s: %s", data.ticker, e)
            return data
        data.reconciliation_overrides = override_log
        for r in override_log.applied:
            note = (
                f"[对账自动修正] {r.field}: 改用内部推算值"
                f"（原供应商口径偏差 {r.rel_diff:+.1%} > 25%）"
                if r.rel_diff is not None else f"[对账自动修正] {r.field}: 改用内部推算值"
            )
            if note not in data.quality.restatement_notes:
                data.quality.restatement_notes.append(note)
        return data

    # Per-share basis fields: if any of these disagree between the provider and
    # the internally derived value, a per-share fair value is not trustworthy.
    _PER_SHARE_BASIS_KEYS = ("流通股数", "市值", "TTM EPS")

    @staticmethod
    def _check_data_provenance(data: FinancialData) -> FinancialData:
        if data.source == DataSource.SYNTHETIC:
            tag = "synthetic_demo_not_live_market"
            if tag not in data.quality.missing_fields:
                data.quality.missing_fields.append(tag)
            data.quality.data_quality_score = min(data.quality.data_quality_score, 35)
            warn = "⚠️ 数据为 SYNTHETIC 演示集，非 Yahoo/live 行情。"
            if warn not in data.notes:
                data.notes.insert(0, warn)
        for note in data.notes:
            if "yahoo_fallback_synthetic" in note.lower() or "已回退至 SYNTHETIC" in note:
                data.quality.data_quality_score = min(data.quality.data_quality_score, 30)
                break
        if any(n.startswith("yahoo_fallback_synthetic:") for n in data.quality.restatement_notes):
            data.quality.data_quality_score = min(data.quality.data_quality_score, 30)
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
        if (
            stmt.operating_income is not None
            and stmt.depreciation_amortization is not None
            and stmt.capex is not None
            and stmt.free_cash_flow is not None
        ):
            nwc = stmt.change_in_nwc
            if nwc is None:
                nwc = infer_change_in_nwc(stmt, effective_tax_rate(stmt))
            if nwc is not None:
                tax = effective_tax_rate(stmt)
                nopat = stmt.operating_income * (1 - tax)
                capex_out = -abs(float(stmt.capex))
                expected = nopat + stmt.depreciation_amortization + capex_out - nwc
                if expected != 0 and abs(stmt.free_cash_flow - expected) / abs(expected) > 0.08:
                    issues.append("FCF ~ NOPAT + D&A + CapEx − ΔNWC mismatch >8%")
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
        data.quality.valuation_usability_score = DataValidator._valuation_usability(data)
        return data

    @staticmethod
    def per_share_basis_unreliable(data: FinancialData) -> bool:
        """True when the provider and internal per-share basis disagree so much
        that a per-share fair value should not be published (user rule:
        share-count deviation > 25%)."""
        rec = getattr(data, "reconciliation", None)
        if rec is None or not hasattr(rec, "has_mismatch"):
            return False
        try:
            return any(rec.has_mismatch(k) for k in DataValidator._PER_SHARE_BASIS_KEYS)
        except Exception:
            return False

    @staticmethod
    def _valuation_usability(data: FinancialData) -> int:
        """Valuation-usability score: 'can I trust a per-share number built from
        this data?'. Degrades faster than source quality when cross-field
        reconciliation fails — especially on the per-share basis (shares/EPS)."""
        score = data.quality.data_quality_score
        rec = getattr(data, "reconciliation", None)
        n_mm = int(getattr(data.quality, "reconciliation_mismatches", 0) or 0)
        if n_mm:
            score -= min(30, n_mm * 6)
        if rec is not None and hasattr(rec, "has_mismatch"):
            if DataValidator.per_share_basis_unreliable(data):
                score -= 20
            try:
                if rec.has_mismatch("EBITDA"):
                    score -= 5
            except Exception:
                pass
        return max(0, min(100, score))

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
