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
        is_fin = bool(getattr(profile, "is_financial_institution", False))
        is_reit = bool(getattr(profile, "is_reit", False))
        flags: List[RiskFlag] = []
        flags.extend(self._leverage(data, profile))
        flags.extend(self._terminal_value_risk(data, dcf_breakdown))
        flags.extend(self._growth_risk(data))
        flags.extend(self._margin_risk(data, profile))
        flags.extend(self._wacc_risk(data, profile, dcf_breakdown))
        flags.extend(self._data_quality_risk(data))
        flags.extend(self._forecast_risk(data, profile))
        # ---- Financial-institution disclaimer flag (once, if profile says so)
        if is_fin:
            flags.append(RiskFlag(
                risk_type="Data Interpretation",
                severity=RiskSeverity.NONE.value,
                rule="金融机构指标定义差异说明",
                evidence="对于银行/保险：FCF、Net Debt、EV、EV/EBITDA 等指标的经济学意义不同于普通企业，银行借贷=业务本身；请以 DDM/RIM、P/B、P/E 和净息差等为准，报告中的 FCF Yield 与负 FCF 年数对银行无参考意义。",
            ))
        elif is_reit:
            flags.append(RiskFlag(
                risk_type="Data Interpretation",
                severity=RiskSeverity.NONE.value,
                rule="REIT 指标定义差异说明",
                evidence="对于 REIT：请优先使用 FFO / AFFO / NAV，而不是 GAAP FCF；DCF 也不是首选模型（报告的 FCF、FCF Yield 参考价值有限）。",
            ))

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

    def _leverage(self, data: FinancialData, profile: Any = None) -> List[RiskFlag]:
        is_fin = bool(getattr(profile, "is_financial_institution", False))
        flags: List[RiskFlag] = []
        th = RISK_THRESHOLDS[RiskType.LEVERAGE]
        de = None
        bv = data.market.book_value
        td = data.market.total_debt
        if bv and bv > 0 and td is not None:
            de = td / bv
            if is_fin:
                # High D/E is NORMAL for banks (deposit base + wholesale funding), not automatically a risk.
                # Only flag if D/E is absurdly high (>15) or way below peers for a bank.
                if de >= 15:
                    flags.append(RiskFlag(
                        risk_type=RiskType.LEVERAGE.value,
                        severity=RiskSeverity.MEDIUM.value,
                        rule="Financial-institution leverage in extreme range (>15x D/E)",
                        evidence=f"D/E = {de:.2f} (banks: high D/E is structural; flagged only at extreme)",
                        metric_value=de,
                        threshold_medium=15.0,
                        threshold_high=20.0,
                    ))
            else:
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
        # A non-positive terminal-year FCF means the terminal value was
        # SUPPRESSED (no sign flip, Session #16) — a far larger terminal-value
        # risk than a merely "high TV weight", and one the tv_percent_of_ev
        # threshold (which reads 0 when suppressed) can never catch.
        if dcf_breakdown.get("terminal_fcf_negative"):
            flags.append(RiskFlag(
                risk_type=RiskType.TERMINAL_VALUE.value,
                severity=RiskSeverity.HIGH.value,
                rule="Terminal-year FCF is non-positive — terminal value suppressed",
                evidence=(
                    "终期 FCF ≤ 0：已抑制终值（不做符号翻转），估值退化为显式期现值下限；"
                    "须明确的转型（turnaround）假设（营收转正 FCF）才成立"
                ),
            ))
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

    def _margin_risk(self, data: FinancialData, profile: Any = None) -> List[RiskFlag]:
        is_fin = bool(getattr(profile, "is_financial_institution", False))
        is_reit = bool(getattr(profile, "is_reit", False))
        flags: List[RiskFlag] = []
        # Margin ratios are only comparable across periods with a comparable
        # revenue base. A year whose revenue is a tiny fraction of the peak
        # (post-restructuring shells / pre-revenue ramp) has a near-zero
        # denominator and yields a meaningless ratio — e.g. a "-1143% mean
        # margin" that is pure scale distortion, not a real earnings signal.
        _revs = [s.revenue for s in data.annual_income if s.revenue and s.revenue > 0]
        _peak_rev = max(_revs) if _revs else 0.0
        oms = []
        _scale_excluded = 0
        for s in data.annual_income:
            if s.revenue and s.revenue > 0 and s.operating_income is not None:
                if _peak_rev > 0 and (s.revenue / _peak_rev) < 0.10:
                    _scale_excluded += 1
                    continue
                oms.append(s.operating_income / s.revenue)
        th = RISK_THRESHOLDS[RiskType.MARGIN]
        if len(oms) >= 3:
            mean_m = sum(oms) / len(oms)
            vol = pstdev(oms) if len(oms) > 1 else 0.0
            cv = vol / abs(mean_m) if mean_m != 0 else 1.0
            sev = self._severity_2t(cv, th["margin_vol_medium"], th["margin_vol_high"])
            if sev != RiskSeverity.NONE.value:
                ev = f"CV = {cv:.2f} (mean {mean_m:.1%})"
                if _scale_excluded:
                    ev += f" _(已剔除 {_scale_excluded} 个营收基期过小的年份，比率失真)_"
                flags.append(RiskFlag(
                    risk_type=RiskType.MARGIN.value,
                    severity=sev,
                    rule="Operating margin volatility above threshold",
                    evidence=ev,
                    metric_value=cv,
                    threshold_medium=th["margin_vol_medium"],
                    threshold_high=th["margin_vol_high"],
                ))
        elif _scale_excluded:
            # Fewer than 3 comparable periods remain after dropping
            # scale-distorted years → report as a data limitation, not a
            # quantitative risk (a bogus CV would mislead).
            flags.append(RiskFlag(
                risk_type=RiskType.MARGIN.value,
                severity=RiskSeverity.LOW.value,
                rule="Operating margin volatility not assessable (scale-distorted base years)",
                evidence=(
                    f"剔除 {_scale_excluded} 个营收基期过小的年份后不足 3 期，"
                    "无法计算可靠的利润率波动"
                ),
            ))
        # ---- Negative FCF years: skip for financial institutions (FCF definition differs)
        if not is_fin:
            neg_fcf_yrs = 0
            for s in data.annual_income:
                if s.free_cash_flow is not None and s.free_cash_flow < 0:
                    neg_fcf_yrs += 1
            if neg_fcf_yrs >= th["negative_fcf_years"]:
                ev_extra = ""
                if is_reit:
                    ev_extra = " _(REIT：此指标基于 GAAP FCF，参考性弱于 FFO/AFFO)_"
                flags.append(RiskFlag(
                    risk_type=RiskType.MARGIN.value,
                    severity=RiskSeverity.MEDIUM.value,
                    rule=f"Negative FCF in {neg_fcf_yrs} of last {len(data.annual_income)} years",
                    evidence=f"{neg_fcf_yrs}y negative FCF" + ev_extra,
                ))
        return flags

    def _wacc_risk(self, data: FinancialData, profile: Any, dcf_breakdown: Optional[Dict] = None) -> List[RiskFlag]:
        flags: List[RiskFlag] = []
        # Single β source of truth: reuse the winsorized CAPM β from the WACC
        # breakdown (falling back to the same winsorization when DCF did not run),
        # so the risk flag and the WACC / market sections cannot disagree.
        from valuation.wacc import resolve_effective_beta
        eb = resolve_effective_beta(data, dcf_breakdown)
        beta = eb.beta
        if beta is None:
            return flags
        if abs(beta - 1.0) > 0.8:
            if eb.clamped and eb.beta_raw is not None:
                evidence = f"Beta = {beta:.2f}（CAPM 采用截断值；原始回归 β = {eb.beta_raw:.2f}）"
            else:
                evidence = f"Beta = {beta:.2f}"
            flags.append(RiskFlag(
                risk_type=RiskType.WACC.value,
                severity=RiskSeverity.MEDIUM.value,
                rule="Beta deviates strongly from market (1.0)",
                evidence=evidence,
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

    def _forecast_risk(self, data: FinancialData, profile: Any = None) -> List[RiskFlag]:
        """Issue #4 fix: split "FCF Yield vs 4%" into two semantic layers:

        A) FCF QUALITY RISK — whether GAAP FCF is weak vs net income (signal about
           working-capital swings, high-growth reinvestment, fintech-style volatility),
           NOT about "forecast being unreliable".

        B) FORECAST RELIABILITY (still under Forecast umbrella) — whether the
           prediction horizon has enough data. For high-growth / fintech companies,
           a negative FCF yield should NOT trigger a HIGH flag.
        """
        is_fin = bool(getattr(profile, "is_financial_institution", False))
        is_reit = bool(getattr(profile, "is_reit", False))
        flags: List[RiskFlag] = []
        th = RISK_THRESHOLDS[RiskType.FORECAST]
        if is_fin:
            return flags

        ttm = data.ttm
        mkt = data.market

        # ---- Helper: historical revenue CAGR (to detect high-growth phase) ----
        annuals = data.annual_income
        hist_cagr: Optional[float] = None
        if len(annuals) >= 2 and annuals[0].revenue and annuals[-1].revenue and annuals[-1].revenue > 0:
            n = len(annuals) - 1
            hist_cagr = (annuals[0].revenue / annuals[-1].revenue) ** (1.0 / n) - 1.0
        high_growth = hist_cagr is not None and hist_cagr >= 0.20

        # ---- Layer A: FCF Quality (Weak / Normal vs. NI) ----
        if (ttm and ttm.revenue and ttm.revenue > 0
                and ttm.free_cash_flow is not None
                and ttm.net_income is not None):
            fcf = float(ttm.free_cash_flow)
            ni = float(ttm.net_income)
            ni_positive_fcf_negative = ni > 0 and fcf < 0
            if ni_positive_fcf_negative:
                quality_label = "Weak"
                reason = (
                    "FCF currently negative despite positive net income — often "
                    "driven by working-capital build, high reinvestment, or fintech-style "
                    "operating cash-flow volatility (≠ forecast intrinsically dangerous)."
                )
                # Severity: Medium for high-growth, Medium-High otherwise; capped at Medium for high-growth
                if high_growth:
                    sev = RiskSeverity.MEDIUM.value
                else:
                    sev = RiskSeverity.MEDIUM.value
                flags.append(RiskFlag(
                    risk_type="FCF Quality",
                    severity=sev,
                    rule="FCF Quality: GAAP FCF diverges from net income",
                    evidence=(
                        f"FCF Quality = {quality_label} | Net Income = ${ni/1e9:,.2f}B, "
                        f"FCF = ${fcf/1e9:,.2f}B (gap driven by NWC / capex)"
                    ),
                    metric_value=round(fcf - ni, 2),
                ))
            elif ni <= 0 and fcf < 0:
                # Both negative: not a "quality" problem but fundamental loss
                flags.append(RiskFlag(
                    risk_type="FCF Quality",
                    severity=RiskSeverity.MEDIUM.value,
                    rule="FCF Quality: Both FCF and Net Income negative",
                    evidence=(
                        f"FCF = ${fcf/1e9:,.2f}B, Net Income = ${ni/1e9:,.2f}B — "
                        "loss-making; FCF yield interpretation secondary to profitability recovery."
                    ),
                ))

        # ---- Layer B: FCF Yield deviation (renamed from "Forecast Risk" → FCF Yield Gap) ----
        if (ttm and ttm.revenue and ttm.revenue > 0
                and ttm.free_cash_flow is not None
                and mkt.market_cap and mkt.market_cap > 0):
            fcf_yield = ttm.free_cash_flow / mkt.market_cap
            pos_fcf_gap = abs(fcf_yield - 0.04) / 0.04
            sev = self._severity_2t(pos_fcf_gap, th["positive_fcf_gap_medium"], th["positive_fcf_gap_high"])
            if sev != RiskSeverity.NONE.value:
                ev_extra = ""
                if is_reit:
                    ev_extra = " _(REIT：基于 GAAP FCF，参考性弱于 FFO/AFFO Yield)_"
                    if sev == RiskSeverity.HIGH.value:
                        sev = RiskSeverity.MEDIUM.value
                    elif sev == RiskSeverity.MEDIUM.value:
                        sev = RiskSeverity.LOW.value
                # Downgrade by one notch for high-growth companies:
                # negative FCF yield in high-growth phase is common and
                # does NOT mean "forecast highly uncertain".
                if high_growth:
                    if sev == RiskSeverity.HIGH.value:
                        sev = RiskSeverity.MEDIUM.value
                    elif sev == RiskSeverity.MEDIUM.value:
                        sev = RiskSeverity.LOW.value
                # A POSITIVE FCF yield that merely sits BELOW the 4% heuristic is a
                # valuation observation (a rich price paid for cash flow), not a
                # cash-flow reliability risk — the flag's own rule text says it does
                # not equate to unreliable forecasts. This is the typical profile of
                # a mature, profitable, low-beta compounder (e.g. a large-cap
                # pharma). Reserve High/Medium for negative or deteriorating FCF.
                _ni_ttm = float(ttm.net_income) if ttm.net_income is not None else None
                _fcf_ttm = float(ttm.free_cash_flow)
                _healthy_conversion = (
                    _ni_ttm is not None and _ni_ttm > 0 and _fcf_ttm / _ni_ttm >= 0.80
                )
                if (not high_growth and _fcf_ttm > 0
                        and fcf_yield < 0.04 and _healthy_conversion):
                    if sev == RiskSeverity.HIGH.value:
                        sev = RiskSeverity.MEDIUM.value
                    elif sev == RiskSeverity.MEDIUM.value:
                        sev = RiskSeverity.LOW.value
                    ev_extra += (
                        f" _(正 FCF(${_fcf_ttm/1e9:,.1f}B) 且 FCF/净利="
                        f"{_fcf_ttm/_ni_ttm:.2f} 转化健康；收益率低于 4% 启发式属"
                        "估值偏高观察，非现金流质量风险，已降级)_"
                    )
                rule_msg = (
                    "FCF Yield 与市场常见 4% 存在偏差（反映增长期再投资或业务模式差异），"
                    "不直接等同于预测不可靠"
                )
                evidence_msg = f"FCF Yield = {fcf_yield:.2%}" + ev_extra
                if high_growth:
                    evidence_msg += f" _(高增长期 {hist_cagr*100:.1f}% CAGR：负 FCF yield 通常为再投资信号，已降权)_"
                flags.append(RiskFlag(
                    risk_type="FCF Yield Gap",
                    severity=sev,
                    rule=rule_msg,
                    evidence=evidence_msg,
                    metric_value=pos_fcf_gap,
                    threshold_medium=th["positive_fcf_gap_medium"],
                    threshold_high=th["positive_fcf_gap_high"],
                ))

        # ---- Layer C: Forecast Reliability based on data coverage ----
        # (Keep original Forecast umbrella for data-completeness signal)
        years_available = len(data.annual_income)
        ttm_ok = ttm is not None and ttm.revenue is not None
        if not ttm_ok:
            flags.append(RiskFlag(
                risk_type=RiskType.FORECAST.value,
                severity=RiskSeverity.MEDIUM.value,
                rule="Forecast Reliability: TTM revenue missing — forecasts rely on annuals only",
                evidence=f"Annual income available: {years_available}y; TTM: {('OK' if ttm_ok else 'N/A')}",
            ))
        elif years_available < 3:
            flags.append(RiskFlag(
                risk_type=RiskType.FORECAST.value,
                severity=RiskSeverity.LOW.value,
                rule="Forecast Reliability: <3 years of annual history — trend estimation limited",
                evidence=f"Annual income available: {years_available}y (≥3y preferred for stable CAGR)",
            ))
        return flags


__all__ = ["RiskAnalyzer", "RiskReport", "RiskFlag"]
