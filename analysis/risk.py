"""
analysis/risk.py - Risk Analysis with Explainable Rules
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev
from typing import Any, Dict, List, Optional, Tuple

from config import DataSource, RISK_THRESHOLDS, RiskSeverity, RiskType, get_logger
from data.models import FinancialData

log = get_logger("analysis.risk")


@dataclass
class RiskFlag:
    risk_type: str
    severity: str
    rule: str
    evidence: str
    metric_value: Optional[float] = None
    threshold_medium: Optional[float] = None
    threshold_high: Optional[float] = None


@dataclass
class RiskReport:
    overall_severity: str
    overall_score: int
    flags: List[RiskFlag] = field(default_factory=list)

    def summary_counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {s.value: 0 for s in RiskSeverity}
        for f in self.flags:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c


class RiskAnalyzer:
    """Evaluates 9 risk dimensions with explainable, rule-based flags."""

    def analyze(self, data: FinancialData, dcf_breakdown: Optional[Dict] = None, profile: Any = None) -> RiskReport:
        flags: List[RiskFlag] = []
        flags.extend(self._leverage(data))
        flags.extend(self._terminal_value_risk(data, dcf_breakdown))
        flags.extend(self._growth_risk(data))
        flags.extend(self._margin_risk(data))
        flags.extend(self._wacc_risk(data, profile))
        flags.extend(self._data_quality_risk(data))
        flags.extend(self._forecast_risk(data))

        score = 100
        for f in flags:
            if f.severity == RiskSeverity.CRITICAL.value:
                score -= 20
            elif f.severity == RiskSeverity.HIGH.value:
                score -= 10
            elif f.severity == RiskSeverity.MEDIUM.value:
                score -= 5
            elif f.severity == RiskSeverity.LOW.value:
                score -= 2
        score = max(0, min(100, score))

        if score >= 75:
            overall = RiskSeverity.LOW.value
        elif score >= 55:
            overall = RiskSeverity.MEDIUM.value
        elif score >= 35:
            overall = RiskSeverity.HIGH.value
        else:
            overall = RiskSeverity.CRITICAL.value

        return RiskReport(overall_severity=overall, overall_score=score, flags=flags)

    def _severity_2t(self, value: float, medium: float, high: float, higher_is_worse: bool = True) -> str:
        if higher_is_worse:
            if value >= high:
                return RiskSeverity.HIGH.value
            elif value >= medium:
                return RiskSeverity.MEDIUM.value
            else:
                return RiskSeverity.NONE.value
        else:
            if value <= high:
                return RiskSeverity.HIGH.value
            elif value <= medium:
                return RiskSeverity.MEDIUM.value
            else:
                return RiskSeverity.NONE.value

    def _leverage(self, data: FinancialData) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        th = RISK_THRESHOLDS[RiskType.LEVERAGE]
        de = None
        bv = data.market.book_value
        td = data.market.total_debt
        if bv and bv > 0 and td is not None:
            de = td / bv
            sev = self._severity_2t(de, th["de_ratio_medium"], th["de_ratio_high"], higher_is_worse=True)
            if sev != RiskSeverity.NONE.value:
                flags.append(RiskFlag(
                    risk_type=RiskType.LEVERAGE.value,
                    severity=sev,
                    rule="Debt/Equity exceeds threshold",
                    evidence=f"D/E = {de:.2f}",
                    metric_value=de,
                    threshold_medium=th["de_ratio_medium"],
                    threshold_high=th["de_ratio_high"],
                ))
        ttm = data.ttm
        if ttm and ttm.interest_expense and ttm.ebit and ttm.interest_expense > 0:
            ic = ttm.ebit / ttm.interest_expense
            sev = self._severity_2t(ic, th["int_cov_medium"], th["int_cov_high"], higher_is_worse=False)
            if sev != RiskSeverity.NONE.value:
                flags.append(RiskFlag(
                    risk_type=RiskType.LEVERAGE.value,
                    severity=sev,
                    rule="Interest coverage below threshold",
                    evidence=f"EBIT/Interest = {ic:.2f}",
                    metric_value=ic,
                    threshold_medium=th["int_cov_medium"],
                    threshold_high=th["int_cov_high"],
                ))
        return flags

    def _terminal_value_risk(self, data: FinancialData, dcf_breakdown: Optional[Dict]) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        if not dcf_breakdown:
            return flags
        tvp = dcf_breakdown.get("tv_percent_of_ev")
        if tvp is None:
            return flags
        th = RISK_THRESHOLDS[RiskType.TERMINAL_VALUE]
        sev = self._severity_2t(tvp, th["tv_pct_medium"], th["tv_pct_high"])
        if sev != RiskSeverity.NONE.value:
            flags.append(RiskFlag(
                risk_type=RiskType.TERMINAL_VALUE.value,
                severity=sev,
                rule="Terminal value as % of EV exceeds threshold",
                evidence=f"TV / EV = {tvp:.1%}",
                metric_value=tvp,
                threshold_medium=th["tv_pct_medium"],
                threshold_high=th["tv_pct_high"],
            ))
        return flags

    def _growth_risk(self, data: FinancialData) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        revs = [s.revenue for s in data.annual_income if s.revenue is not None and s.revenue > 0]
        if len(revs) < 3:
            return flags
        growths = [(revs[i] - revs[i + 1]) / revs[i + 1] for i in range(len(revs) - 1)]
        if not growths:
            return flags
        mean_g = sum(growths) / len(growths)
        vol = pstdev(growths) if len(growths) > 1 else 0.0
        if mean_g != 0:
            cv = vol / abs(mean_g)
        else:
            cv = 1.0
        th = RISK_THRESHOLDS[RiskType.GROWTH]
        sev = self._severity_2t(cv, th["growth_vol_medium"], th["growth_vol_high"])
        if sev != RiskSeverity.NONE.value:
            flags.append(RiskFlag(
                risk_type=RiskType.GROWTH.value,
                severity=sev,
                rule="Revenue growth volatility (CV) above threshold",
                evidence=f"CV = {cv:.2f} over {len(growths)}y",
                metric_value=cv,
                threshold_medium=th["growth_vol_medium"],
                threshold_high=th["growth_vol_high"],
            ))
        return flags

    def _margin_risk(self, data: FinancialData) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        oms = []
        for s in data.annual_income:
            if s.revenue and s.revenue > 0 and s.operating_income is not None:
                oms.append(s.operating_income / s.revenue)
        th = RISK_THRESHOLDS[RiskType.MARGIN]
        if len(oms) >= 3:
            mean_m = sum(oms) / len(oms)
            vol = pstdev(oms) if len(oms) > 1 else 0.0
            cv = vol / abs(mean_m) if mean_m != 0 else 1.0
            sev = self._severity_2t(cv, th["margin_vol_medium"], th["margin_vol_high"])
            if sev != RiskSeverity.NONE.value:
                flags.append(RiskFlag(
                    risk_type=RiskType.MARGIN.value,
                    severity=sev,
                    rule="Operating margin volatility above threshold",
                    evidence=f"CV = {cv:.2f} (mean {mean_m:.1%})",
                    metric_value=cv,
                    threshold_medium=th["margin_vol_medium"],
                    threshold_high=th["margin_vol_high"],
                ))
        neg_fcf_yrs = 0
        for s in data.annual_income:
            if s.free_cash_flow is not None and s.free_cash_flow < 0:
                neg_fcf_yrs += 1
        if neg_fcf_yrs >= th["negative_fcf_years"]:
            flags.append(RiskFlag(
                risk_type=RiskType.MARGIN.value,
                severity=RiskSeverity.MEDIUM.value,
                rule=f"Negative FCF in {neg_fcf_yrs} of last {len(data.annual_income)} years",
                evidence=f"{neg_fcf_yrs}y negative FCF",
            ))
        return flags

    def _wacc_risk(self, data: FinancialData, profile: Any) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        beta = data.market.beta
        if beta is None:
            return flags
        if abs(beta - 1.0) > 0.8:
            flags.append(RiskFlag(
                risk_type=RiskType.WACC.value,
                severity=RiskSeverity.MEDIUM.value,
                rule="Beta deviates strongly from market (1.0)",
                evidence=f"Beta = {beta:.2f}",
                metric_value=beta,
            ))
        return flags

    def _data_quality_risk(self, data: FinancialData) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        if data.source == DataSource.SYNTHETIC:
            flags.append(RiskFlag(
                risk_type=RiskType.DATA_QUALITY.value,
                severity=RiskSeverity.CRITICAL.value,
                rule="Synthetic demo data must not be presented as live market data",
                evidence=f"data.source={data.source.value}",
            ))
        elif any(
            n.startswith("yahoo_fallback_synthetic:") for n in data.quality.restatement_notes
        ):
            flags.append(RiskFlag(
                risk_type=RiskType.DATA_QUALITY.value,
                severity=RiskSeverity.CRITICAL.value,
                rule="Yahoo failed and valuation used synthetic fallback",
                evidence="restatement_notes contains yahoo_fallback_synthetic",
            ))
        th = RISK_THRESHOLDS[RiskType.DATA_QUALITY]
        score = data.quality.data_quality_score
        sev = self._severity_2t(score, th["score_medium"], th["score_high"], higher_is_worse=False)
        if sev != RiskSeverity.NONE.value:
            flags.append(RiskFlag(
                risk_type=RiskType.DATA_QUALITY.value,
                severity=sev,
                rule="Data quality score below threshold",
                evidence=f"Score = {score}/100; missing: {data.quality.missing_fields}",
                metric_value=float(score),
                threshold_medium=float(th["score_medium"]),
                threshold_high=float(th["score_high"]),
            ))
        return flags

    def _forecast_risk(self, data: FinancialData) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        th = RISK_THRESHOLDS[RiskType.FORECAST]
        if data.ttm and data.ttm.revenue and data.ttm.revenue > 0 and data.ttm.free_cash_flow is not None:
            fcf_yield = data.ttm.free_cash_flow / (data.market.market_cap or 1.0)
            if data.market.market_cap and data.market.market_cap > 0:
                pos_fcf_gap = abs(fcf_yield - 0.04) / 0.04
                sev = self._severity_2t(pos_fcf_gap, th["positive_fcf_gap_medium"], th["positive_fcf_gap_high"])
                if sev != RiskSeverity.NONE.value:
                    flags.append(RiskFlag(
                        risk_type=RiskType.FORECAST.value,
                        severity=sev,
                        rule="FCF 收益率 vs 常见 4% — 差距过大意味着预测存在不确定性",
                        evidence=f"FCF Yield = {fcf_yield:.2%}",
                        metric_value=pos_fcf_gap,
                        threshold_medium=th["positive_fcf_gap_medium"],
                        threshold_high=th["positive_fcf_gap_high"],
                    ))
        return flags


__all__ = ["RiskAnalyzer", "RiskReport", "RiskFlag"]
