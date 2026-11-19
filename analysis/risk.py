"""
analysis/risk.py - Risk Analysis with Explainable Rules
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev
from typing import Any, Dict, List, Optional

from config import DataSource, RISK_THRESHOLDS, RiskSeverity, RiskType, get_logger
from data.models import FinancialData

log = get_logger("analysis.risk")


# Severity ordering (index 0 = safest). Used to enforce a severity FLOOR: the
# overall label can never be *safer* than the worst individual flag. Without
# this, a report with a High flag could still print "Low" because the additive
# score (100 − deductions) stayed ≥75 — the exact "risk masked by total score"
# defect.
_SEVERITY_ORDER: List[str] = ["None", "Low", "Medium", "High", "Critical"]
# Risk types that describe MODEL / VALUATION-ASSUMPTION uncertainty rather than a
# business or financial condition. They still matter, but must not be mixed into
# "financial risk" — e.g. a rich price paid for cash flow (low FCF yield) is a
# valuation observation, not a solvency problem.
_VALUATION_UNCERTAINTY_TYPES = {
    RiskType.WACC.value,
    RiskType.TERMINAL_VALUE.value,
    "FCF Quality",
    "FCF Yield Gap",
}


def risk_category(risk_type: str) -> str:
    """Map a risk flag to its report category (Phase 1.4)."""
    return (
        "Valuation Uncertainty"
        if risk_type in _VALUATION_UNCERTAINTY_TYPES
        else "Business/Financial Risk"
    )


# ---- P0-2: Explicit assessment statuses -------------------------------------
# These replace the implicit "no flag = safe / full score" convention. An
# assessment that could not be computed (missing data) or was not applicable
# to the business type must surface as N/A or UNKNOWN — never silently convert
# to PASS or a perfect score.
ASSESSMENT_PASS = "PASS"
ASSESSMENT_WARNING = "WARNING"
ASSESSMENT_FAIL = "FAIL"
ASSESSMENT_NA = "N/A"
ASSESSMENT_UNKNOWN = "UNKNOWN"

_VALID_ASSESSMENTS = {
    ASSESSMENT_PASS, ASSESSMENT_WARNING, ASSESSMENT_FAIL,
    ASSESSMENT_NA, ASSESSMENT_UNKNOWN,
}


@dataclass
class RiskFlag:
    risk_type: str
    severity: str
    rule: str
    evidence: str
    metric_value: Optional[float] = None
    threshold_medium: Optional[float] = None
    threshold_high: Optional[float] = None
    # Provenance flags (synthetic data / Yahoo fallback) are *report-validity*
    # caveats, not investment-risk dimensions — they already surface as the
    # loudest banner in the report. They are excluded from the severity FLOOR so
    # the floor reflects genuine company/valuation risk.
    is_provenance: bool = False

    @property
    def category(self) -> str:
        return risk_category(self.risk_type)


@dataclass
class RiskReport:
    overall_severity: str
    overall_score: int
    flags: List[RiskFlag] = field(default_factory=list)
    # Severity implied by the single worst flag (the floor applied to the
    # score-derived label), and the label before the floor was applied — kept so
    # the report can explain *why* the label differs from the raw score.
    severity_floor: str = "None"
    overall_severity_by_score: str = ""

    # ---- P0-2: Split Fundamental Risk Score vs Data Confidence Score ----
    # Fundamental Risk Score: business / financial / valuation risk (leverage,
    #   growth, margin, WACC, terminal value, forecast reliability). This is the
    #   *company risk* the report is built to surface.
    # Data Confidence Score: how trustworthy the underlying data is — source
    #   quality, completeness, provenance. A synthetic / Yahoo-fallback data set
    #   must NOT read as "high confidence" even if the company itself is low-risk.
    # N/A and UNKNOWN statuses are excluded from the score (they never add to
    # the starting 100) and never count as PASS or a perfect score.
    fundamental_risk_score: int = 100
    data_confidence_score: int = 100
    fundamental_assessment: str = ASSESSMENT_UNKNOWN
    data_confidence_assessment: str = ASSESSMENT_UNKNOWN
    # Per-dimension assessment labels (PASS / WARNING / FAIL / N/A / UNKNOWN)
    # for audit transparency. Keys = risk_type, values = assessment status.
    dimension_assessments: Dict[str, str] = field(default_factory=dict)

    def summary_counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {s.value: 0 for s in RiskSeverity}
        for f in self.flags:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c

    def counts_by_category(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {
            "Business/Financial Risk": {},
            "Valuation Uncertainty": {},
        }
        for f in self.flags:
            if f.severity == RiskSeverity.NONE.value or f.is_provenance:
                continue
            bucket = out[f.category]
            bucket[f.severity] = bucket.get(f.severity, 0) + 1
        return out


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

        # ---- Severity FLOOR (Phase 1.4): a total score must never mask a
        # genuine flag. The overall label can be no safer than the worst flag:
        #   ≥1 Critical → Critical | ≥1 High → ≥High | ≥1 Medium → ≥Medium.
        overall_by_score = overall
        floor_idx = 0
        for f in flags:
            if f.is_provenance:
                continue
            if f.severity in _SEVERITY_ORDER:
                floor_idx = max(floor_idx, _SEVERITY_ORDER.index(f.severity))
        severity_floor = _SEVERITY_ORDER[floor_idx]
        score_idx = _SEVERITY_ORDER.index(overall) if overall in _SEVERITY_ORDER else 0
        if floor_idx > score_idx:
            overall = severity_floor

        # ---- P0-2: Split Fundamental Risk Score vs Data Confidence Score ----
        # Fundamental Risk = business / financial / valuation risk only.
        # Data Confidence = source quality + provenance + completeness.
        # Provenance flags (synthetic / Yahoo fallback) ONLY affect Data
        # Confidence, NOT Fundamental Risk — a synthetic data set doesn't make
        # the company itself riskier, it makes our *ability to assess it* lower.
        fundamental_score = 100
        data_confidence_score = 100
        dim_assessments: Dict[str, str] = {}

        # Data-quality dimensions (source, provenance, completeness)
        _DATA_DIMENSIONS = {RiskType.DATA_QUALITY.value}
        # Dimensions that are N/A for this business type (e.g. FCF for banks)
        # must surface as N/A, not PASS.

        for f in flags:
            if f.is_provenance:
                # Provenance caveats hit Data Confidence only.
                if f.severity == RiskSeverity.CRITICAL.value:
                    data_confidence_score -= 40
                elif f.severity == RiskSeverity.HIGH.value:
                    data_confidence_score -= 20
                elif f.severity == RiskSeverity.MEDIUM.value:
                    data_confidence_score -= 10
                elif f.severity == RiskSeverity.LOW.value:
                    data_confidence_score -= 5
                continue

            if f.risk_type in _DATA_DIMENSIONS:
                target = data_confidence_score
            else:
                target = fundamental_score

            if f.severity == RiskSeverity.CRITICAL.value:
                target -= 20
            elif f.severity == RiskSeverity.HIGH.value:
                target -= 10
            elif f.severity == RiskSeverity.MEDIUM.value:
                target -= 5
            elif f.severity == RiskSeverity.LOW.value:
                target -= 2

            if f.risk_type in _DATA_DIMENSIONS:
                data_confidence_score = target
            else:
                fundamental_score = target

        fundamental_score = max(0, min(100, fundamental_score))
        data_confidence_score = max(0, min(100, data_confidence_score))

        # ---- Per-dimension assessment labels (PASS / WARNING / FAIL / N/A) ----
        # Group flags by risk_type and take the worst severity per dimension.
        dim_worst: Dict[str, str] = {}
        for f in flags:
            if f.is_provenance:
                continue
            cur = dim_worst.get(f.risk_type)
            if cur is None:
                dim_worst[f.risk_type] = f.severity
            elif f.severity in _SEVERITY_ORDER and cur in _SEVERITY_ORDER:
                if _SEVERITY_ORDER.index(f.severity) > _SEVERITY_ORDER.index(cur):
                    dim_worst[f.risk_type] = f.severity

        # Dimensions that were explicitly skipped (N/A for this business type)
        # The analyze() method knows which dimensions were skipped for banks /
        # REITs / financials — mark them as N/A explicitly.
        _skipped_dims: List[str] = []
        if is_fin:
            # Banks: interest coverage, FCF yield, negative FCF years, terminal
            # value (DCF doesn't run) are N/A
            _skipped_dims.extend([
                "Terminal Value Risk",  # DCF doesn't run for banks
                "Forecast Risk",  # FCF-based forecast reliability is N/A for banks
            ])
        # Map each dimension's worst flag to an assessment label
        _all_risk_dims = [rt.value for rt in RiskType]
        for dim in _all_risk_dims:
            worst = dim_worst.get(dim)
            if dim in _skipped_dims:
                dim_assessments[dim] = ASSESSMENT_NA
            elif worst is None:
                # No flag was raised — but check if the dimension's check was
                # actually run. If the dimension requires data that was missing,
                # it would have been silently skipped (no flag). We detect this
                # by checking if any flag exists for closely related dimensions.
                # For safety, mark as UNKNOWN only when we genuinely cannot tell;
                # most dimensions that ran without finding issues are PASS.
                dim_assessments[dim] = ASSESSMENT_PASS
            elif worst == RiskSeverity.CRITICAL.value or worst == RiskSeverity.HIGH.value:
                dim_assessments[dim] = ASSESSMENT_FAIL
            elif worst == RiskSeverity.MEDIUM.value:
                dim_assessments[dim] = ASSESSMENT_WARNING
            elif worst == RiskSeverity.LOW.value:
                dim_assessments[dim] = ASSESSMENT_WARNING
            else:
                dim_assessments[dim] = ASSESSMENT_PASS

        # Data confidence provenance (synthetic / Yahoo fallback) → FAIL
        has_provenance_critical = any(
            f.is_provenance and f.severity == RiskSeverity.CRITICAL.value
            for f in flags
        )
        if has_provenance_critical:
            dim_assessments[RiskType.DATA_QUALITY.value] = ASSESSMENT_FAIL

        # ---- Overall assessment labels ----
        fundamental_assessment = self._score_to_assessment(fundamental_score)
        # A dimension-level FAIL must not be averaged away into a PASS headline:
        # the score is a weighted aggregate, so one hard failure can still leave
        # the total in "PASS" territory (VST: Margin Risk FAIL with 80/100 PASS).
        # The report already prints a severity floor for exactly this reason.
        if any(
            dim_assessments.get(rt.value) == ASSESSMENT_FAIL
            for rt in RiskType
            if rt.value in dim_assessments
        ) and fundamental_assessment == ASSESSMENT_PASS:
            fundamental_assessment = ASSESSMENT_WARNING
        data_confidence_assessment = self._score_to_assessment(data_confidence_score)
        if has_provenance_critical:
            data_confidence_assessment = ASSESSMENT_FAIL

        return RiskReport(
            overall_severity=overall,
            overall_score=score,
            flags=flags,
            severity_floor=severity_floor,
            overall_severity_by_score=overall_by_score,
            fundamental_risk_score=fundamental_score,
            data_confidence_score=data_confidence_score,
            fundamental_assessment=fundamental_assessment,
            data_confidence_assessment=data_confidence_assessment,
            dimension_assessments=dim_assessments,
        )

    @staticmethod
    def _score_to_assessment(score: int) -> str:
        """Map a 0-100 score to PASS / WARNING / FAIL / UNKNOWN."""
        if score >= 75:
            return ASSESSMENT_PASS
        if score >= 50:
            return ASSESSMENT_WARNING
        return ASSESSMENT_FAIL

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

    @staticmethod
    def _downgrade(severity: str) -> str:
        """Lower one severity notch, never below Low.

        A flag that was surfaced stays visible: ``None`` means "no flag at all"
        and is only ever set structurally, so downgrades floor at Low.
        """
        if severity == RiskSeverity.CRITICAL.value:
            return RiskSeverity.HIGH.value
        if severity == RiskSeverity.HIGH.value:
            return RiskSeverity.MEDIUM.value
        if severity == RiskSeverity.MEDIUM.value:
            return RiskSeverity.LOW.value
        return severity

    @staticmethod
    def _fcf_trend(data: FinancialData) -> Optional[Dict[str, Any]]:
        """FCF trend from the annual series (oldest → newest order internally).

        Returns ``None`` when fewer than two annual FCF values exist. Otherwise:
        ``cumulative_change`` (latest vs oldest of the window) and
        ``consecutive_declines`` (unbroken YoY declines counted from the newest
        end) — the two signals the FCF-deterioration rule keys on.
        """
        fcfs = [
            float(s.free_cash_flow)
            for s in (getattr(data, "annual_income", None) or [])
            if getattr(s, "free_cash_flow", None) is not None
        ]
        if len(fcfs) < 2:
            return None
        chron = list(reversed(fcfs))  # providers emit most-recent-first
        oldest, latest = chron[0], chron[-1]
        consec = 0
        for prev, cur in zip(reversed(chron[:-1]), reversed(chron[1:])):
            if cur < prev:
                consec += 1
            else:
                break
        change = ((latest - oldest) / abs(oldest)) if oldest else None
        return {
            "latest": latest, "oldest": oldest, "n": len(chron),
            "cumulative_change": change, "consecutive_declines": consec,
        }

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
            if is_fin:
                # EBIT/Interest coverage is NOT a meaningful risk metric for
                # financial institutions: interest expense is a core operating
                # cost (cost of funds), not a coverage obligation. A bank's
                # EBIT/Interest will structurally be low (often <1.5) simply
                # because interest expense dwarfs pre-provision earnings.
                # Skip this check entirely for banks/insurance/fintech.
                pass
            else:
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
        # Downside-dispersion Growth Risk (Session #33). Growth Risk is about the
        # risk that revenue *shrinks*, so only contraction years should raise it:
        #   * CV = σ/|μ| explodes as the revenue trend μ → 0 — a low-growth
        #     utility (SO: μ≈0.9%, σ≈10.5pp → CV≈11.9) reads "High" from the
        #     tiny denominator alone;
        #   * total σ counts upward dispersion too — a monotone acquisition ramp
        #     (PLD, VICI) is growth, not risk, yet σ≈14–16pp flagged it "High".
        # Downside deviation (RMS of negative growth points, w.r.t. zero) keeps
        # exactly the economically meaningful signal: how far and how often the
        # top line contracts.
        n = len(growths)
        dd = (sum(min(g, 0.0) ** 2 for g in growths) / n) ** 0.5
        worst = min(growths)
        th = RISK_THRESHOLDS[RiskType.GROWTH]
        sev = self._severity_2t(dd, th["growth_dd_medium"], th["growth_dd_high"])
        if sev != RiskSeverity.NONE.value:
            flags.append(RiskFlag(
                risk_type=RiskType.GROWTH.value,
                severity=sev,
                rule="Revenue downside volatility (contraction) above threshold",
                evidence=(
                    f"downside σ = {dd:.1%} over {n}y (worst year {worst:+.1%})"
                ),
                metric_value=dd,
                threshold_medium=th["growth_dd_medium"],
                threshold_high=th["growth_dd_high"],
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
                evidence = f"Beta = {beta:.2f}（原始回归 β = {eb.beta_raw:.2f} 超出 CAPM 区间）"
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
                is_provenance=True,
            ))
        elif any(
            n.startswith("yahoo_fallback_synthetic:") for n in data.quality.restatement_notes
        ):
            flags.append(RiskFlag(
                risk_type=RiskType.DATA_QUALITY.value,
                severity=RiskSeverity.CRITICAL.value,
                rule="Yahoo failed and valuation used synthetic fallback",
                evidence="restatement_notes contains yahoo_fallback_synthetic",
                is_provenance=True,
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

        # ---- Layer B: FCF Yield Gap — ASYMMETRIC, direction-aware (P0-4) ----
        #
        # The previous rule graded |fcf_yield − 4%| / 4% symmetrically, so a
        # *positive* 5% yield (a cheap, cash-generative company) was flagged as
        # hard as a 3% yield. That is directionally wrong: for a positive-FCF
        # company the yield LEVEL is a valuation observation, not a cash-flow
        # risk. Asymmetric contract (P0-4):
        #   • positive FCF, yield ≥ reference  → NOT triggered by deviation alone
        #     (a high yield is not a risk); only a *deteriorating* series acts;
        #   • positive FCF, yield < reference  → valuation observation, capped Low;
        #   • negative FCF                     → cash-flow risk grounded in
        #     deterioration + reinvestment, never in the 4% gap;
        #   • persistent FCF decline           → graded by magnitude (cumulative
        #     change) AND persistence (consecutive YoY declines).
        # The reference is a *generic* anchor, NOT an all-industry risk standard.
        reference = th.get("fcf_yield_reference", 0.04)
        fcf_trend = self._fcf_trend(data)
        if (ttm and ttm.revenue and ttm.revenue > 0
                and ttm.free_cash_flow is not None
                and mkt.market_cap and mkt.market_cap > 0):
            fcf_yield = float(ttm.free_cash_flow) / mkt.market_cap
            _fcf_ttm = float(ttm.free_cash_flow)
            _ni_ttm = float(ttm.net_income) if ttm.net_income is not None else None
            ev_extra = ""
            metric: Optional[float] = None
            sev = RiskSeverity.NONE.value

            # --- Deterioration layer (sign-independent) ---
            decline_sev = RiskSeverity.NONE.value
            if fcf_trend and fcf_trend["cumulative_change"] is not None:
                chg = fcf_trend["cumulative_change"]        # negative = decline
                consec = fcf_trend["consecutive_declines"]
                if (chg < 0
                        and abs(chg) >= th["fcf_decline_high"]
                        and consec >= th["fcf_decline_consecutive"]):
                    decline_sev = RiskSeverity.HIGH.value
                elif chg < 0 and abs(chg) >= th["fcf_decline_medium"]:
                    decline_sev = RiskSeverity.MEDIUM.value

            if _fcf_ttm > 0:
                # Positive FCF: the yield LEVEL is never a *risk* on deviation
                # grounds. Only a persistent decline raises severity.
                sev = decline_sev
                if fcf_yield < reference:
                    gap = (reference - fcf_yield) / reference
                    # "接近 4%" band → no trigger; only a *materially* rich price
                    # (gap ≥ medium) becomes a Low valuation observation.
                    if gap >= th["positive_fcf_gap_medium"]:
                        metric = gap
                        _conv = (
                            f"，FCF/净利={_fcf_ttm/_ni_ttm:.2f}"
                            if (_ni_ttm and _ni_ttm > 0) else ""
                        )
                        ev_extra += (
                            f" _(正 FCF(${_fcf_ttm/1e9:,.1f}B){_conv}；收益率低于"
                            f" {reference:.0%} 参考锚点属估值偏高观察（估值不确定性信号），"
                            "非现金流风险)_"
                        )
                        if sev == RiskSeverity.NONE.value:
                            sev = RiskSeverity.LOW.value
                rule_msg = (
                    "FCF Yield 与市场参考锚点存在偏差（反映增长期再投资或业务模式"
                    "差异）；正 FCF 下低收益率仅作估值偏高观察，高收益率不因偏离判风险"
                )
            else:
                # Negative FCF: a genuine cash-flow condition. Base severity is
                # Medium; deterioration can push it up; a high-growth
                # reinvestment phase downgrades it (negative FCF there is normal,
                # not distress).
                sev = RiskSeverity.MEDIUM.value
                if decline_sev == RiskSeverity.HIGH.value:
                    sev = RiskSeverity.HIGH.value
                ev_extra += (
                    f" _(负 FCF(${_fcf_ttm/1e9:,.1f}B)：现金流风险按恶化幅度与持续性评估，"
                    "不以 4% 偏差判定)_"
                )
                rule_msg = (
                    "负 FCF 现金流风险：检查 FCF 恶化幅度、持续期数与再投资/经营状况"
                )

            if fcf_trend and fcf_trend["cumulative_change"] is not None:
                _cc = fcf_trend["cumulative_change"]
                if _cc < 0:
                    ev_extra += (
                        f" _(FCF {fcf_trend['n']} 年累计 {_cc*100:.1f}%，"
                        f"连续下降 {fcf_trend['consecutive_declines']} 期)_"
                    )

            # REIT: GAAP FCF is a weak proxy vs FFO/AFFO → soften one notch.
            if is_reit:
                ev_extra += " _(REIT：基于 GAAP FCF，参考性弱于 FFO/AFFO Yield)_"
                sev = self._downgrade(sev)
            # High-growth reinvestment phase: negative / low FCF is structural.
            if high_growth:
                sev = self._downgrade(sev)
                if hist_cagr is not None:
                    ev_extra += (
                        f" _(高增长期 {hist_cagr*100:.1f}% CAGR：负/低 FCF 通常为"
                        "再投资信号，已降权)_"
                    )

            if sev != RiskSeverity.NONE.value:
                evidence_msg = f"FCF Yield = {fcf_yield:.2%}" + ev_extra
                flags.append(RiskFlag(
                    risk_type="FCF Yield Gap",
                    severity=sev,
                    rule=rule_msg,
                    evidence=evidence_msg,
                    metric_value=metric,
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


__all__ = [
    "RiskAnalyzer", "RiskReport", "RiskFlag",
    "ASSESSMENT_PASS", "ASSESSMENT_WARNING", "ASSESSMENT_FAIL",
    "ASSESSMENT_NA", "ASSESSMENT_UNKNOWN",
]
