"""
reporting/dashboard.py - Auditable Valuation Dashboard Report Generator
Produces structured Markdown reports for Telegram.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from config import (
    REPORT_SECTION_TITLES,
    TELEGRAM_MAX_MESSAGE_LENGTH,
    DataSource,
    SolverStatus,
    get_logger,
)
from data.models import CompanyProfile, FinancialData

from analysis.model_agreement import _EXCLUDED_FROM_MEDIAN
from models.multiples import PEER_SOURCE_LABELS
from reporting.math_audit import valuation_band_from_model_gap
from valuation.caliber import DiscountCaliber, MetricMeaning, build_caliber_contract
from valuation.wacc import BETA_WINSOR_HI, BETA_WINSOR_LO, resolve_effective_beta

log = get_logger("reporting.dashboard")

# Reader-facing labels for the Reverse-DCF growth-band verdict. The verdict is
# a *credibility* judgement layered on top of the solve, so each label states
# both what happened and how much weight the number deserves.
_GROWTH_BAND_VERDICT_LABELS: Dict[str, tuple] = {
    "SOLVED_WITHIN_BASE_BAND": ("落在合理区间内", ""),
    "SOLVED_OUTSIDE_BASE_BAND": (
        "已解出，但超出该商业模式合理区间",
        "数学有解 ≠ 经济可信，不宜直接作为正常估值结论",
    ),
    "SOLVED_EXTREME_GROWTH": (
        "已解出，但属极端增长假设",
        "更可能是现金流基数或再投资假设存在问题",
    ),
    "NO_ROOT_IN_EXPANDED_RANGE": (
        "扩展区间内无解",
        "当前价无法由本模型的现金流路径解释（非带宽伪影）",
    ),
    "DATA_QUALITY_WARNING": (
        "数据质量存疑",
        "现金流基数不支持增长解读，隐含增长仅供参照",
    ),
    "NEGATIVE_BASE_FCF_NO_VALID_ROOT": (
        "基准 FCF 为负，无有效解",
        "反向 DCF 的前提不成立：无法对负现金流求永续价值，"
        "「增长超上限」是错误归因",
    ),
}


def _fmt_money(v: Optional[float], decimals: int = 0) -> str:
    if v is None:
        return "N/A"
    try:
        v_f = float(v)
    except (TypeError, ValueError):
        return "N/A"
    # ``float('nan')`` formats as "nan", so a non-finite value would reach the
    # reader as "$nan" / "$infT" - a number that is not a number, presented as
    # money. Treat it as missing instead (Session #52).
    if not math.isfinite(v_f):
        return "N/A"
    if abs(v_f) >= 1e12:
        return f"${v_f/1e12:,.{decimals}f}T"
    if abs(v_f) >= 1e9:
        return f"${v_f/1e9:,.{decimals}f}B"
    if abs(v_f) >= 1e6:
        return f"${v_f/1e6:,.{decimals}f}M"
    return f"${v_f:,.{decimals}f}"


def _fmt_share(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(f):
        return "N/A"
    return f"${f:,.2f}"


def _fmt_pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(f):
        return "N/A"
    return f"{f*100:,.{decimals}f}%"


def _fmt_pct_or_reason(v: Optional[float], reason: str, decimals: int = 1) -> str:
    """Like ``_fmt_pct`` but explains *why* a metric is unavailable.

    A bare ``N/A`` reads as a data gap; here it is a deliberate refusal to print
    a CAGR whose endpoints straddle a sign change (the rate is undefined).
    """
    if v is None:
        return f"N/A（{reason}）"
    return _fmt_pct(v, decimals)


def _fmt_num(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(f):
        return "N/A"
    return f"{f:,.{decimals}f}"


def _fmt_recon(v: Optional[float], unit: str = "") -> str:
    """Format a reconciliation value according to its unit (see data/reconciliation.py)."""
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if unit == "USD":
        return _fmt_money(v)
    if unit == "股":
        if abs(v) >= 1e9:
            return f"{v/1e9:,.2f}B 股"
        if abs(v) >= 1e6:
            return f"{v/1e6:,.1f}M 股"
        return f"{v:,.0f} 股"
    if unit == "USD/股":
        return f"${v:,.2f}"
    return _fmt_num(v)


def _etr_basis_suffix(basis: str) -> str:
    """Human gloss for the ETR period caliber recorded by WACC (P0-2 / P1-7).

    ``ttm`` → TTM；``fyN`` → N 个完整财年；``default`` → 法定默认。
    """
    b = (basis or "").strip().lower()
    if not b:
        return ""
    if b == "ttm":
        return "，TTM 口径"
    if b == "default":
        return "，法定默认"
    if b.startswith("fy") and b[2:].isdigit():
        return f"，{b[2:]} 个完整财年"
    return f"，{basis}"


def bank_ke_note_lines(monte_carlo: Any) -> List[str]:
    """Render the bank raw-vs-adjusted CAPM Ke audit lines for the report.

    Kept as a module-level helper so the rendering can be verified without
    building a full ``FinancialData`` object.
    """
    out: List[str] = []
    for note in getattr(monte_carlo, "notes", None) or []:
        if isinstance(note, str) and note.startswith("CAPM Ke 溯源"):
            out.append(f"  • {note}")
    return out


class DashboardReport:
    """Generates the full valuation dashboard as Markdown text."""

    SECTION_TITLES = REPORT_SECTION_TITLES

    def __init__(self) -> None:
        self._sections: List[tuple[str, str]] = []

    def add_section(self, key: str, content: str) -> None:
        title = self.SECTION_TITLES.get(key, key.upper())
        self._sections.append((title, content))

    def build(self) -> str:
        lines: List[str] = []
        for title, content in self._sections:
            lines.append(f"**{title}**")
            lines.append(content)
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def split_for_telegram(report: str, max_len: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> List[str]:
        chunks: List[str] = []
        paragraphs = report.split("\n\n")
        current = ""
        for para in paragraphs:
            candidate = (current + "\n\n" + para).lstrip()
            if len(candidate) > max_len and current:
                chunks.append(current)
                current = para
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks if chunks else [report[:max_len]]


class ValuationReportBuilder:
    """Orchestrates building a full report from analysis outputs."""

    @staticmethod
    def build_report(
        data: FinancialData,
        profile: CompanyProfile,
        model_results: Dict[str, Any],
        scenarios: Dict[str, Any],
        implied: Any,
        gap: Any,
        sensitivity_wacc_tg: Any,
        agreement: Any,
        risk: Any,
        monte_carlo: Any = None,
        operating_scenarios: Optional[Dict[str, Any]] = None,
        coe_sensitivity: Optional[Dict[str, Any]] = None,
        op_sensitivity: Optional[Dict[str, Any]] = None,
        combined_scenario: Optional[Dict[str, Any]] = None,
    ) -> str:
        dash = DashboardReport()
        prov = ValuationReportBuilder._provenance_banner(data)
        if prov:
            dash.add_section("provenance", prov)
        # === 🔥 用户要求的直观判断总览：放在最前面，用户第一眼就能看到结论 ===
        overview = ValuationReportBuilder._intuitive_overview_section(profile)
        if overview:
            dash.add_section("overview", overview)
        dash.add_section("business", ValuationReportBuilder._business_section(data, profile))
        dash.add_section("ml_prob", ValuationReportBuilder._ml_probability_section(profile))
        dcf_breakdown = ValuationReportBuilder._extract_dcf_breakdown(model_results)
        dash.add_section("market", ValuationReportBuilder._market_section(data, profile, dcf_breakdown))
        dash.add_section("valuation", ValuationReportBuilder._valuation_section(model_results, data))
        dash.add_section("scenarios", ValuationReportBuilder._scenario_section(scenarios, data))
        if operating_scenarios:
            dash.add_section(
                "operating_scenarios",
                ValuationReportBuilder._operating_scenario_section(operating_scenarios, data),
            )
        # ---- P0-3: Scenario description must match the actual variable ----
        if coe_sensitivity:
            dash.add_section(
                "coe_sensitivity",
                ValuationReportBuilder._coe_sensitivity_section(coe_sensitivity, data),
            )
        if op_sensitivity:
            dash.add_section(
                "op_sensitivity",
                ValuationReportBuilder._op_sensitivity_section(op_sensitivity, data),
            )
        if combined_scenario:
            dash.add_section(
                "combined_scenario",
                ValuationReportBuilder._combined_scenario_section(combined_scenario, data),
            )
        dash.add_section("implied", ValuationReportBuilder._implied_section(implied))
        dash.add_section("gap", ValuationReportBuilder._gap_section(gap, profile))
        dash.add_section("sensitivity", ValuationReportBuilder._sensitivity_section(sensitivity_wacc_tg, profile))
        dash.add_section("models", ValuationReportBuilder._agreement_section(agreement, profile))
        dash.add_section("risk", ValuationReportBuilder._risk_section(risk, profile))
        if monte_carlo is not None:
            dash.add_section("data", ValuationReportBuilder._data_section(data, monte_carlo))
        else:
            dash.add_section("data", ValuationReportBuilder._data_section(data))
        return dash.build()

    @staticmethod
    def _extract_dcf_breakdown(model_results: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pull the DCF breakdown (which carries the WACC/β of record) from results."""
        r = model_results.get("DCF") if model_results else None
        if r is not None and getattr(r, "is_success", lambda: False)() and getattr(r, "breakdown", None):
            return r.breakdown
        return None

    @staticmethod
    def _intuitive_overview_section(profile: CompanyProfile) -> Optional[str]:
        """🔥 Top-of-report intuitive verdict summary (user's core ask).

        Returns None if verdict data not yet attached (legacy paths).
        """
        v = getattr(profile, "valuation_verdict", None)
        g = getattr(profile, "growth_verdict", None)
        if v is None and g is None:
            return None
        lines: List[str] = []
        if v is not None:
            head = v.header_lines()
            if head:
                lines.extend(head)
        if g is not None:
            growth = g.bullet_lines()
            if growth:
                if lines:
                    lines.append("")
                lines.extend(growth)
        if not lines:
            return None
        lines.append("")
        lines.append("_（以上结论基于多模型中位数 + 情景分析 + 增长三档对比，仅作快速参考）_")
        return "\n".join(lines)

    @staticmethod
    def _business_section(data: FinancialData, profile: CompanyProfile) -> str:
        m = data.market
        lines = [
            f"**代码:** {data.ticker}",
            f"**公司:** {m.company_name or 'N/A'}",
            f"**行业 / 细分行业:** {m.sector or 'N/A'} / {m.industry or 'N/A'}",
        ]

        # ---- Issue #1 + #2: Hybrid classification label
        if profile.is_hybrid_classification and profile.hybrid_classification_label:
            bt_line = (
                f"**Primary Business Model:** {profile.primary_business_type or profile.business_type} "
                f"/ {profile.secondary_business_type or 'N/A'}"
            )
            # Same asset-light prototype conflict guard as the non-hybrid branch:
            # the hybrid headline must not claim a label the engine rejected.
            _eff_h = getattr(profile, "effective_business_type", None)
            if _eff_h and _eff_h != profile.business_type:
                bt_line += f" → **估值原型重路由: {_eff_h}**"
            lines.append(bt_line)
            lines.append(f"**分类:** {profile.hybrid_classification_label}")
            if profile.classification_confidence_level:
                lines.append(f"**置信度等级:** {profile.classification_confidence_level}")
        else:
            bt_line = (
                f"**业务类型:** {profile.business_type}"
                f"（置信度 {profile.classification_confidence:.0%}）"
            )
            # Asset-light prototype conflict: the engine itself rejected this
            # label and re-routed the valuation archetype. Show it in the
            # headline so it does not contradict the confidence audit trail.
            _eff = getattr(profile, "effective_business_type", None)
            if _eff and _eff != profile.business_type:
                bt_line += f" → **估值原型重路由: {_eff}**"
            lines.append(bt_line)

        # ---- Phase 1.3: classification status (identity vs economics) ----
        # When the top-1 label is statistically ambiguous AND disagrees with the
        # provider's identity, the engine refuses to silently use it as the
        # valuation prototype. Surface that state loudly.
        if getattr(profile, "classification_status", "confident") != "confident":
            lines.append(f"**⚠️ 分类状态:** {profile.classification_status}")
            _id_bt = getattr(profile, "identity_business_type", None)
            if _id_bt:
                lines.append(f"  • 行业身份（卖什么）: {_id_bt}")
            _note = getattr(profile, "classification_conflict_note", None)
            if _note:
                lines.append(f"  • 冲突说明: {_note}")

        # ---- Issue #1: Confidence audit trail (ML raw → adjustments → final)
        if profile.ml_raw_confidence is not None and (profile.ml_raw_confidence - profile.classification_confidence) > 1e-6:
            lines.append("")
            lines.append("**置信度拆解:**")
            lines.append(f"  ML Top-1 probability       {profile.ml_raw_confidence * 100:.1f}%")
            running = profile.ml_raw_confidence
            for adj in profile.confidence_adjustments:
                delta_pct = adj.delta * 100
                sign = "+" if delta_pct >= 0 else ""
                lines.append(f"  {adj.step_name:<26s} {sign}{delta_pct:.1f}%")
                lines.append(f"    _理由: {adj.reason}_")
                running += adj.delta
            lines.append(f"  **Final confidence         {profile.classification_confidence * 100:.1f}%**")

        # ---- Issue #2: Business exposures (FinTech / hybrid etc)
        if profile.business_exposures and any(e.weight >= 0.05 for e in profile.business_exposures):
            lines.append("")
            lines.append("**业务模式暴露度（ML 聚合）:**")
            for e in profile.business_exposures:
                if e.weight < 0.02:
                    continue
                bar_len = int(round(e.weight * 24))
                bar = "█" * bar_len + "░" * (24 - bar_len)
                lines.append(f"  {e.label:<34s} │{bar}│ {e.weight * 100:5.1f}%")

        lines.extend([
            f"**收入规模:** {profile.revenue_characteristic}",
            f"**增长特征:** {profile.growth_profile}",
            f"**盈利能力:** {profile.profitability_profile}",
            f"**现金流:** {profile.cash_flow_profile}",
            f"**杠杆情况:** {profile.leverage_profile}",
            f"**资本密集度:** {profile.capital_intensity}",
        ])
        if profile.classification_reasons:
            lines.append("**分类理由:**")
            for r in profile.classification_reasons[:4]:
                lines.append(f"  • {r}")
        return "\n".join(lines)

    @staticmethod
    def _ml_probability_section(profile: CompanyProfile) -> str:
        lines: List[str] = []
        if profile.ml_model_used:
            lines.append(f"**分类引擎:** 🧠 LightGBM ML (v{profile.ml_model_version or '?'})")
        elif profile.rule_fallback_triggered:
            lines.append("**分类引擎:** 📜 规则回退（ML 置信度不足或不可用）")
        else:
            lines.append("**分类引擎:** 📜 确定性规则分类器")

        if profile.ml_probabilities:
            sorted_probs = sorted(profile.ml_probabilities.items(), key=lambda kv: -kv[1])
            top5 = sorted_probs[:5]
            lines.append("**概率分布（Top 5）:**")
            for label, prob in top5:
                bar_len = int(round(prob * 24))
                bar = "█" * bar_len + "░" * (24 - bar_len)
                pct = prob * 100
                lines.append(f"  `{label:20s}` │{bar}│ {pct:5.1f}%")

        if profile.top_2_candidates and len(profile.top_2_candidates) >= 2:
            c1, c2 = profile.top_2_candidates[0], profile.top_2_candidates[1]
            lines.append("")
            lines.append(f"**Top-1 候选:** {c1[0]}（{c1[1]*100:.1f}%）")
            lines.append(f"**Top-2 候选:** {c2[0]}（{c2[1]*100:.1f}%）")
            if c1[1] > 0 and c2[1] > 0:
                ratio = c1[1] / c2[1] if c2[1] > 1e-9 else float("inf")
                if ratio >= 5:
                    clarity = "✅ 高置信（Top1 / Top2 ≥ 5x）"
                elif ratio >= 2:
                    clarity = "🟡 中等区分（Top1 / Top2 2~5x）"
                else:
                    clarity = "⚠️ 边界模糊（Top1 / Top2 < 2x，建议人工复核）"
                lines.append(f"**候选区分度:** {clarity}（ratio = {ratio:.1f}x）")
        return "\n".join(lines)

    @staticmethod
    def _market_section(data: FinancialData, profile: Optional[CompanyProfile] = None,
                        dcf_breakdown: Optional[Dict[str, Any]] = None) -> str:
        m = data.market
        ttm = data.ttm
        # Caliber is an ENGINE output, not a render-time guess: the contract
        # declares which metrics are meaningful and which discount caliber
        # applies. Render sites branch on it (ADR-024).
        contract = build_caliber_contract(profile)
        fin_caveat = contract.note("overview") or None

        trailing_pe = None
        if ttm and ttm.eps and ttm.eps > 0 and m.current_price:
            trailing_pe = m.current_price / ttm.eps

        ev_line = f"**企业价值:** {_fmt_money(m.enterprise_value)}{contract.metric_note('EV')}"
        net_debt_line = (
            f"**总债务:** {_fmt_money(m.total_debt)} | **现金:** {_fmt_money(m.cash_and_equivalents)} "
            f"| **净债务:** {_fmt_money(m.net_debt)}{contract.metric_note('NetDebt')}"
        )
        if contract.meaning("EV_EBITDA") is MetricMeaning.NOT_MEANINGFUL:
            ev_ebitda_line = f"**EV/EBITDA:** N/M{contract.metric_note('EV_EBITDA')}"
        else:
            ev_ebitda_line = f"**EV/EBITDA:** {_fmt_num(m.ev_to_ebitda, 1)}{contract.metric_note('EV_EBITDA')}"

        # Beta: single source of truth (resolve_effective_beta). The displayed β is
        # the exact CAPM β used by WACC and by the risk flags; when the raw
        # regression β sat outside the CAPM band we annotate the raw value so the
        # market section and the WACC section cannot contradict each other.
        eb = resolve_effective_beta(data, dcf_breakdown)
        beta_line = f"**贝塔系数:** {_fmt_num(eb.beta, 2)}"
        if eb.clamped and eb.beta_raw is not None:
            beta_line += (
                f" _(原始回归 β = {eb.beta_raw:.2f} 超出 CAPM 可用区间 "
                f"[{BETA_WINSOR_LO:.2f}, {BETA_WINSOR_HI:.2f}]，市场区 / 风险旗标 / 折现率 "
                f"统一采用 β = {eb.beta:.2f})_"
            )

        lines = [
            f"**当前价格:** {_fmt_share(m.current_price)}",
            f"**市值:** {_fmt_money(m.market_cap)}",
            ev_line,
            net_debt_line,
            f"**每股账面价值:** {_fmt_share(m.book_value_per_share)}",
            beta_line,
            f"**滚动市盈率:** {_fmt_num(m.trailing_pe or trailing_pe, 1)}",
            ev_ebitda_line,
            f"**市净率 (P/B):** {_fmt_num(m.price_to_book, 1)}",
            f"**股息收益率:** {_fmt_pct(m.dividend_yield)}",
        ]
        if fin_caveat:
            lines.append(fin_caveat)
        # Macro / derived snapshot (P1-7). The ETR shown as primary is the one
        # the WACC ACTUALLY used (from the WaccBreakdown, after the P0-2
        # non-overlapping-period policy); the provider figure is an INPUT and may
        # legitimately differ, so it is labelled separately instead of being
        # presented as if it drove the after-tax cost of debt.
        wb_macro = (dcf_breakdown or {}).get("wacc_breakdown") if dcf_breakdown else None
        macro_parts = []
        if getattr(m, "risk_free_rate", None):
            macro_parts.append(f"Rf(10Y) {_fmt_pct(m.risk_free_rate,2)}")
        etr_wacc = getattr(wb_macro, "effective_tax_rate", None) if wb_macro is not None else None
        if etr_wacc is not None:
            macro_parts.append(
                f"ETR {_fmt_pct(etr_wacc,1)}（WACC 实际使用{_etr_basis_suffix(getattr(wb_macro, 'tax_period_basis', ''))}）"
            )
        provider_etr = getattr(m, "effective_tax_rate", None)
        if provider_etr is not None:
            if etr_wacc is None:
                macro_parts.append(f"ETR {_fmt_pct(provider_etr,1)}（供应商，用于 WACC）")
            elif abs(float(provider_etr) - float(etr_wacc)) > 0.001:
                macro_parts.append(
                    f"供应商 ETR {_fmt_pct(provider_etr,1)}（仅输入数据，未用于 WACC 计算）"
                )
        if getattr(m, "implied_cost_of_debt", None):
            macro_parts.append(f"Kd(implied) {_fmt_pct(m.implied_cost_of_debt,1)}")
        if macro_parts:
            lines.append("**宏观快照 (用于 WACC):** " + " | ".join(macro_parts))
        if ttm:
            if contract.meaning("FCF") is MetricMeaning.NOT_MEANINGFUL:
                fcf_part = f"FCF N/M{contract.metric_note('FCF')}"
            else:
                fcf_part = f"FCF {_fmt_money(ttm.free_cash_flow)}{contract.metric_note('FCF')}"
            lines.append(
                f"**TTM 总览:** 营收 {_fmt_money(ttm.revenue)} | EBITDA {_fmt_money(ttm.ebitda)} "
                f"| 净利润 {_fmt_money(ttm.net_income)} | {fcf_part}"
            )
        return "\n".join(lines)

    @staticmethod
    def _valuation_label_for_diff(diff: Optional[float]) -> str:
        """Qualitative label for one model's spread vs current price.

        Uses the shared canonical ladder (reporting.math_audit) so the same
        economic statement is worded identically here and in the verdict card.
        ``diff = (model - price) / price``; positive ⇒ model above price ⇒ 低估.
        """
        if diff is None:
            return ""
        label, _emoji = valuation_band_from_model_gap(float(diff))
        if not label:
            return ""
        return f"  [**{label}**]"

    @staticmethod
    def _valuation_section(model_results: Dict[str, Any], data: FinancialData) -> str:
        lines = []
        price = data.market.current_price
        dcf_breakdown: Optional[Dict[str, Any]] = None
        for name, r in model_results.items():
            if r.is_success() and r.value_per_share is not None:
                pps = r.value_per_share
                if name in _EXCLUDED_FROM_MEDIAN:
                    # ReverseDCF solves for the growth that justifies the CURRENT
                    # price, so its "value" is the current price by construction —
                    # labeling it 估值合理/高估 is a tautology. Show it as a
                    # diagnostic, not a valuation.
                    lines.append(
                        f"• **{name}:** {_fmt_share(pps)}  "
                        "（反向求解＝当前价，非独立估值）"
                    )
                elif price and price > 0:
                    diff = (pps - price) / price
                    label = ValuationReportBuilder._valuation_label_for_diff(diff)
                    lines.append(f"• **{name}:** {_fmt_share(pps)}  （较当前价格 {diff:+.1%}）{label}")
                else:
                    lines.append(f"• **{name}:** {_fmt_share(pps)}")
                if name.startswith("DCF"):
                    v_low = r.breakdown.get("value_per_share_low_g") if getattr(r, "breakdown", None) else None
                    v_high = r.breakdown.get("value_per_share_high_g") if getattr(r, "breakdown", None) else None
                    if v_low is not None and v_high is not None:
                        lines.append(
                            f"    _TVG区间估值:_ Low(g={_fmt_pct(r.breakdown.get('terminal_growth_low',0))}) → {_fmt_share(v_low)}  "
                            f"| High(g={_fmt_pct(r.breakdown.get('terminal_growth_high',0))}) → {_fmt_share(v_high)}"
                        )
                    # WACC-range valuation (Session #07): show how much of the
                    # conclusion is driven by the (possibly out-of-range) WACC.
                    w_lo = r.breakdown.get("value_per_share_wacc_lo")
                    w_hi = r.breakdown.get("value_per_share_wacc_hi")
                    if w_lo is not None and w_hi is not None:
                        lines.append(
                            f"    _WACC区间估值:_ 行业下沿 "
                            f"(WACC={_fmt_pct(r.breakdown.get('wacc_lo_industry',0))}) → {_fmt_share(w_lo)}  "
                            f"| 行业上沿 (WACC={_fmt_pct(r.breakdown.get('wacc_hi_industry',0))}) → {_fmt_share(w_hi)}"
                        )
                for n in r.notes:
                    lines.append(f"    ‣ {n}")
                if name.startswith("DCF") and getattr(r, "breakdown", None):
                    dcf_breakdown = r.breakdown
            else:
                lines.append(f"• **{name}:** {r.status.value}")
                if r.notes:
                    for n in r.notes[:2]:
                        lines.append(f"    ‣ {n}")

        # ---- Peer-multiple provenance (Phase 3.2) ---------------------------
        # The report must state HOW each relative multiple's peer anchor was
        # obtained (exact industry match vs classification/exposure fallback)
        # and how many comparables backed it. A fallback anchor is weaker
        # evidence, so it must be visible, not silently equal to an exact match.
        peer_lines = []
        for name, r in model_results.items():
            bd = getattr(r, "breakdown", None) or {}
            kind = bd.get("peer_source_kind")
            if not kind:
                continue
            n = bd.get("peer_sample_size")
            gloss = PEER_SOURCE_LABELS.get(kind, "")
            n_txt = f"可比样本 n={n}" if n is not None else "静态行业锚点（n 不可得）"
            peer_lines.append(f"• {name}: `{kind}`（{gloss}；{n_txt}）")
        if peer_lines:
            lines.append("")
            lines.append("**🔎 同行倍数来源 (可审计):**")
            lines.extend(f"  {p}" for p in peer_lines)

        # WACC breakdown (if DCF ran)
        if dcf_breakdown is not None:
            lines.append("")
            lines.append("**💡 WACC 计算明细 (可审计):**")
            wb = dcf_breakdown.get("wacc_breakdown")
            if wb is not None:
                ir = dcf_breakdown.get("industry_range")
                lines.append(f"  **Final WACC = {_fmt_pct(wb.wacc, 2)}**")
                if hasattr(wb, "beta_transparency_note"):
                    lines.append(f"  Beta 透明度: {wb.beta_transparency_note()}")
                if hasattr(wb, "beta_window_note"):
                    _wn = wb.beta_window_note()
                    if _wn:
                        lines.append(f"  {_wn}")
                if hasattr(wb, "beta_uncertainty_note"):
                    _un = wb.beta_uncertainty_note()  # P1-6: β 不确定性 → WACC 区间
                    if _un:
                        lines.append(f"  {_un}")
                lines.append(f"  Cost of Equity (CAPM) = Rf + β×ERP = {_fmt_pct(wb.risk_free_rate,2)} + {_fmt_num(wb.beta,2)}×{_fmt_pct(wb.equity_risk_premium,2)} = **{_fmt_pct(wb.cost_of_equity,2)}**")
                raw_kd = getattr(wb, "cost_of_debt_implied_raw", None)
                if raw_kd is not None and abs(raw_kd - wb.cost_of_debt) > 1e-5:
                    lines.append(
                        f"  Cost of Debt (pre-tax, **用于 WACC**) = {_fmt_pct(wb.cost_of_debt,2)} "
                        f"(隐含 Interest/Debt = {_fmt_pct(raw_kd,2)}，已应用 Rf+0.5% 下限或上限)"
                    )
                else:
                    lines.append(
                        f"  Cost of Debt (pre-tax) = {_fmt_pct(wb.cost_of_debt,2)}"
                    )
                lines.append(
                    f"  after-tax (1−ETR)×Kd = {_fmt_pct(wb.after_tax_cost_of_debt,2)}  "
                    f"(ETR = {_fmt_pct(wb.effective_tax_rate,1)})"
                )
                lines.append(f"  Capital Structure: E/(D+E)={_fmt_pct(wb.weight_equity,0)}  D/(D+E)={_fmt_pct(wb.weight_debt,0)}")
                if ir:
                    lo, hi, lbl = ir
                    lines.append(f"  Industry sanity:  **[{_fmt_pct(lo,1)} ~ {_fmt_pct(hi,1)}]**（{lbl}）→  Status = `{wb.sanity_status}`")
                if hasattr(wb, "wacc_range_note"):
                    _rn = wb.wacc_range_note()
                    if _rn:
                        lines.append(f"  ⚠ {_rn}")
                src = wb.sources or {}
                if src:
                    lines.append("  _来源明细:_")
                    priority = (
                        "Rf", "β", "ERP", "ke",
                        "kd (implied raw)", "kd (pre-tax)", "kd (after-tax)",
                        "ETR", "Weights", "WACC (final)",
                    )
                    shown = set()
                    for k in priority:
                        if k in src:
                            lines.append(f"    • {k}: {src[k]}")
                            shown.add(k)
                    for k, v in src.items():
                        if k not in shown:
                            lines.append(f"    • {k}: {v}")
            tg = dcf_breakdown.get("tvg_range")
            if tg is not None:
                lines.append("")
                lines.append("**🎯 Terminal Growth (三档假设):**")
                lines.append(f"  Low = **{_fmt_pct(tg.low,2)}**  |  Base = **{_fmt_pct(tg.base,2)}**  |  High = **{_fmt_pct(tg.high,2)}**")
                lines.append(
                    f"  规则: Base = min(normalized_growth={_fmt_pct(tg.normalized_growth,2)}, "
                    f"LT_nominal_GDP={_fmt_pct(tg.long_term_nominal_gdp,2)}, WACC−0.5%={_fmt_pct(tg.wacc_minus_half_pct,2)}) "
                    f"为长期稳定终值增长率（受 GDP 与 Gordon 上限约束）；"
                    f"Low 为保守情景、High 为乐观情景（= Base±0.5%，仅受 Gordon 上限 WACC−0.5% 约束）"
                )
                if getattr(tg, "high_exceeds_gdp", False):
                    lines.append(
                        f"  ⚠ High {_fmt_pct(tg.high,2)} 高于长期名义 GDP {_fmt_pct(tg.long_term_nominal_gdp,2)}："
                        f"High 仅作乐观情景参考，非长期稳定终值增长率"
                    )
                lines.append(f"  Source: {tg.source}")
                if tg.notes:
                    for n in tg.notes[:3]:
                        lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    @staticmethod
    def _scenario_section(scenarios: Dict[str, Any], data: FinancialData) -> str:
        lines = []
        price = data.market.current_price
        order = ["Bear", "Base", "Bull"]
        translations = {"Bear": "熊市", "Base": "基本面", "Bull": "乐观情景"}
        # Detect whether this is a financial-institution band (Ke label) —
        # in that case the original ``_run_financial_scenarios`` varies BOTH
        # Ke and ROE simultaneously, so the description must NOT say "仅变动
        # 折现率". Instead, point to the P0-3 single-variable sections below.
        first_sv = next(iter(scenarios.values()), None)
        is_fin_band = (
            (getattr(first_sv, "assumptions", {}) or {}).get("discount_label") == "ke"
            or getattr(first_sv, "scenario_kind", "") == "financial"
        )
        if is_fin_band:
            lines.append(
                "_本组为银行联合情景（同时变动 Ke 与 ROE）；"
                "单变量敏感性见下方 Cost of Equity Sensitivity 与 "
                "Operating Performance Sensitivity。_"
            )
        else:
            lines.append(
                "_本组情景仅变动折现率（WACC / 终值增长率 g）；经营驱动情景见下文。_"
            )
        for s in order:
            sv = scenarios.get(s)
            if sv is None:
                continue
            vps = getattr(sv, "value_per_share", None)
            label = (getattr(sv, "assumptions", {}) or {}).get("discount_label", "WACC")
            if label == "ke":
                suffix = f"— ke {_fmt_pct(getattr(sv, 'wacc', 0))} (Bank RIM)"
            else:
                suffix = (
                    f"— WACC {_fmt_pct(getattr(sv, 'wacc', 0))} / "
                    f"g {_fmt_pct(getattr(sv, 'terminal_growth', 0))}"
                )
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)}  （较当前价格 {diff:+.1%}） {suffix}")
                else:
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)} {suffix}")
                for n in getattr(sv, "notes", [])[:2]:
                    lines.append(f"    ‣ {n}")
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A")
                for n in getattr(sv, "notes", [])[:1]:
                    lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    @staticmethod
    def _operating_scenario_section(scenarios: Dict[str, Any], data: FinancialData) -> str:
        """Bear/Base/Bull driven by OPERATING inputs (revenue, margin, CapEx, FCF).

        Distinct from the discount-rate band above: here the discount rate is
        held at the deterministic base case and the revenue / operating-margin
        multipliers move instead, flowing through CapEx / D&A / NWC into FCF.
        Financials return no operating band (DCF is a forbidden caliber there).
        """
        lines = [
            "_经营驱动：营收增长 / 营业利润率（经 CapEx / D&A / NWC 传导至 FCF）；"
            "折现率固定在基准 WACC。_"
        ]
        price = data.market.current_price
        order = ["Bear", "Base", "Bull"]
        translations = {"Bear": "熊市", "Base": "基本面", "Bull": "乐观情景"}
        for s in order:
            sv = scenarios.get(s)
            if sv is None:
                continue
            vps = getattr(sv, "value_per_share", None)
            drivers = getattr(sv, "drivers", {}) or {}
            rev_d = drivers.get("revenue_growth_delta")
            om_d = drivers.get("operating_margin_delta")
            d_txt = ""
            if rev_d is not None and om_d is not None:
                d_txt = f"（营收 {rev_d:+.0%} / 营业利润 {om_d:+.0%}）"
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)}  （较当前价格 {diff:+.1%}） {d_txt}")
                else:
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)} {d_txt}")
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A {d_txt}")
            for n in getattr(sv, "notes", [])[:2]:
                lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # P0-3: Single-variable and combined scenario sections.
    # Each description must match the actual variable being perturbed.
    # ------------------------------------------------------------------
    @staticmethod
    def _coe_sensitivity_section(
        scenarios: Dict[str, Any], data: FinancialData
    ) -> str:
        """Cost of Equity Sensitivity.

        Financials get a true single-variable band (β → Ke, ROE held). For
        non-financials the discount-rate band moves WACC **and** terminal growth
        together, so the heading must say so instead of promising an isolated Ke
        effect.
        """
        _is_ke_only = any(
            (getattr(sv, "drivers", {}) or {}).get("cost_of_equity") is not None
            and (getattr(sv, "drivers", {}) or {}).get("wacc") is None
            for sv in scenarios.values()
        )
        if _is_ke_only:
            lines: List[str] = [
                "_仅变动权益成本 Ke（β 偏移 → CAPM Ke），经营性变量固定在基准；"
                "用于隔离折现率对估值的边际影响。_",
            ]
        else:
            lines = [
                "_普通企业无独立 Ke 通道：折现率档位同时变动 WACC 与终值增长率 g，"
                "经营性变量固定在基准；用于隔离折现率假设对估值的边际影响。_",
            ]
        price = data.market.current_price
        order = ["Bear", "Base", "Bull"]
        translations = {"Bear": "熊市（折现率↑）", "Base": "基本面", "Bull": "乐观（折现率↓）"}
        for s in order:
            sv = scenarios.get(s)
            if sv is None:
                continue
            vps = getattr(sv, "value_per_share", None)
            drv = getattr(sv, "drivers", {}) or {}
            ke = drv.get("cost_of_equity")
            beta = drv.get("beta")
            if ke is not None:
                rate_txt = f"Ke {_fmt_pct(ke)}"
            else:
                _w = getattr(sv, "wacc", None)
                _g = getattr(sv, "terminal_growth", None)
                rate_txt = ""
                if _w:
                    rate_txt = f"WACC {_fmt_pct(_w)}"
                if _g:
                    rate_txt += f" / g {_fmt_pct(_g)}"
            beta_txt = f"（β={_fmt_num(beta)}）" if beta else ""
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)}"
                        f"  （较当前价格 {diff:+.1%}） {rate_txt}{beta_txt}"
                    )
                else:
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)} {rate_txt}{beta_txt}"
                    )
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A {rate_txt}{beta_txt}")
            for n in getattr(sv, "notes", [])[:2]:
                lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    @staticmethod
    def _op_sensitivity_section(
        scenarios: Dict[str, Any], data: FinancialData
    ) -> str:
        """Operating Performance Sensitivity — only ROE / operating driver moves."""
        lines: List[str] = [
            "_仅变动经营性变量（银行：ROE；普通企业：营收/利润率 → FCF），"
            "折现率固定在基准；用于隔离经营绩效对估值的边际影响。_",
        ]
        price = data.market.current_price
        order = ["Bear", "Base", "Bull"]
        translations = {"Bear": "熊市（经营↓）", "Base": "基本面", "Bull": "乐观（经营↑）"}
        for s in order:
            sv = scenarios.get(s)
            if sv is None:
                continue
            vps = getattr(sv, "value_per_share", None)
            drivers = getattr(sv, "drivers", {}) or {}
            # Bank: roe_override / roe; Non-financial: revenue/margin delta
            roe = drivers.get("roe")
            roe_override = drivers.get("roe_override")
            rev_d = drivers.get("revenue_growth_delta")
            om_d = drivers.get("operating_margin_delta")
            d_txt = ""
            if roe is not None:
                d_txt = f"ROE {_fmt_pct(roe)}"
            elif roe_override is not None:
                d_txt = f"ROE → {_fmt_pct(roe_override)}"
            elif rev_d is not None and om_d is not None:
                d_txt = f"（营收 {rev_d:+.0%} / 营业利润 {om_d:+.0%}）"
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)}"
                        f"  （较当前价格 {diff:+.1%}） {d_txt}"
                    )
                else:
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)} {d_txt}"
                    )
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A {d_txt}")
            for n in getattr(sv, "notes", [])[:2]:
                lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    @staticmethod
    def _combined_scenario_section(
        scenarios: Dict[str, Any], data: FinancialData
    ) -> str:
        """Combined Scenario — both Ke and operating driver move simultaneously."""
        if not scenarios:
            return (
                "_联合情景：同时变动折现率与经营性变量。"
                "普通企业的 DCF 折现率情景与经营情景为不同预测路径族，"
                "不宜合成联合情景（避免混合不可比路径）→ N/A_"
            )
        lines: List[str] = [
            "_同时变动权益成本 Ke（β 偏移）与经营性 ROE；"
            "为两者的联合压力测试，而非单变量敏感性。_",
        ]
        price = data.market.current_price
        order = ["Bear", "Base", "Bull"]
        translations = {"Bear": "熊市（Ke↑ + ROE↓）", "Base": "基本面", "Bull": "乐观（Ke↓ + ROE↑）"}
        for s in order:
            sv = scenarios.get(s)
            if sv is None:
                continue
            vps = getattr(sv, "value_per_share", None)
            ke = getattr(sv, "wacc", None)
            roe = (getattr(sv, "drivers", {}) or {}).get("roe_override")
            base_roe = (getattr(sv, "assumptions", {}) or {}).get("roe")
            ke_txt = f"Ke {_fmt_pct(ke)}" if ke else ""
            roe_txt = ""
            if roe is not None and base_roe is not None:
                roe_txt = f" / ROE {_fmt_pct(base_roe)}→{_fmt_pct(roe)}"
            elif base_roe is not None:
                roe_txt = f" / ROE {_fmt_pct(base_roe)}"
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)}"
                        f"  （较当前价格 {diff:+.1%}） {ke_txt}{roe_txt}"
                    )
                else:
                    lines.append(
                        f"• **{translations.get(s, s)}:** {_fmt_share(vps)} {ke_txt}{roe_txt}"
                    )
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A {ke_txt}{roe_txt}")
            for n in getattr(sv, "notes", [])[:2]:
                lines.append(f"    ‣ {n}")
        return "\n".join(lines)

    @staticmethod
    def _growth_value_attribution_block(attr: dict) -> str:
        """Exact additive split of EV(g_hi) − EV(g_lo) by cash-flow component.

        States *which* component drives the curve's slope, and — when the
        components nearly cancel — that the sign of the total is fragile. This
        is what turns "EV falls as growth rises" into an auditable statement
        rather than a bare conclusion.
        """
        total = attr.get("total") or 0.0
        direction = "上升" if total >= 0 else "下降"
        parts = [
            ("NOPAT（税后经营利润）", attr.get("nopat")),
            ("D&A（折旧摊销回加）", attr.get("da")),
            ("CapEx（资本开支）", attr.get("capex")),
            ("ΔNWC（营运资本变动）", attr.get("nwc")),
            ("终值（TV）", attr.get("terminal")),
        ]
        rows = [
            f"    ‣ {label}: {value:+,.0f}"
            for label, value in parts
            if value is not None
        ]
        cancel = attr.get("cancellation_ratio")
        head = (
            f"**增长价值归因（EV 对增长的加性分解，"
            f"g {attr.get('g_lo', 0):.0%}→{attr.get('g_hi', 0):.0%}）:** "
            f"合计 {total:+,.0f}（{direction}）"
        )
        lines = [head, *rows]
        if cancel is not None and cancel >= 3.0:
            lines.append(
                f"  ⚠️ 各分项相互抵消程度 {cancel:.1f}×（分项绝对值之和 / 合计）："
                f"净额是方向相反的大额分项相减的结果，其正负号对输入假设敏感"
            )
        return "\n".join(lines)

    @staticmethod
    def _implied_section(implied: Any) -> str:
        if implied is None:
            return "N/A"
        rev_line = f"**隐含营收 CAGR:** {_fmt_pct(implied.implied_revenue_cagr)}"
        if (getattr(implied, "implied_revenue_cagr_source", None) == "normalized_growth_solve"
                and implied.implied_revenue_cagr is not None):
            rev_line += "  _(成熟稳态经济推导，APPROXIMATE — 非直接求解)_"
        elif implied.implied_revenue_cagr is None:
            # Structured bound (Session #31): the price sits outside what the
            # sanctioned growth band can justify. State the bound honestly,
            # never a fabricated point estimate.
            _bound = getattr(implied, "implied_revenue_cagr_bound", None) or {}
            _bkind, _bval = _bound.get("kind"), _bound.get("value")
            if _bkind == "above_band_ceiling" and _bval is not None:
                rev_line = (
                    f"**隐含营收 CAGR:** ≥ {_bval:.0%}（区间上限，非点估）"
                    "  _(在所辖增长区间内增速无法解释当前股价 → 价格隐含更乐观的利润率/"
                    "折现率/终值假设，见下方单变量隐含解)_"
                )
            elif _bkind == "below_band_floor" and _bval is not None:
                rev_line = (
                    f"**隐含营收 CAGR:** ≤ {_bval:.0%}（区间下限，非点估）"
                    "  _(即使在区间下限模型估值已高于当前价 → 市场隐含增速低于合理下限)_"
                )
            elif _bkind == "ev_decreasing_in_growth":
                rev_line = (
                    "**隐含营收 CAGR:** 不适用（模型 EV 随增速上升而下降）"
                    "  _(增长并非能逼近当前价的杠杆：终值/再投资使更高增速反而压低"
                    "估值 → 该模型无法解释此定价，而非「增速超出上限」)_"
                )
            elif _bkind == "ev_direction_undetermined":
                rev_line = (
                    "**隐含营收 CAGR:** 不可判定（EV 随增速的方向对营运资本假设敏感）"
                    "  _(在合理参数范围内方向并不稳定 → 不据此推断市场隐含增长，"
                    "亦不断言「增长创造/毁灭价值」)_"
                )
        lines = [
            f"**反向 DCF 状态:** {implied.reverse_dcf_status or 'N/A'}",
            f"**隐含 FCF CAGR:** {_fmt_pct(implied.implied_fcf_cagr)}",
            rev_line,
        ]

        verdict = getattr(implied, "growth_band_verdict", None)
        if verdict:
            label, caution = _GROWTH_BAND_VERDICT_LABELS.get(
                verdict, (verdict, "")
            )
            lines.append(f"**隐含增长可信度:** {label}" + (f"  _({caution})_" if caution else ""))

        # ---- Phase 2 (Session #17): one-at-a-time implied drivers ----
        drivers = [
            ("隐含营业利润率", "implied_operating_margin"),
            ("隐含 FCF 利润率", "implied_fcf_margin"),
            ("隐含折现率 (WACC)", "implied_wacc"),
            ("隐含终值增长率", "implied_terminal_growth"),
        ]
        # Non-solved outcomes are rendered from the engine's own SolverStatus
        # enum (no口径 guessing in the render layer).
        unsolved_labels = {
            SolverStatus.NO_SOLUTION_IN_RANGE.value: "不可解（超出约束区间）",
            SolverStatus.NON_MONOTONIC.value: "不可解（目标非单调）",
            SolverStatus.MULTIPLE_ROOTS.value: "不可解（区间内多解）",
            SolverStatus.FLAT_OBJECTIVE.value: "不可解（对该假设无敏感度）",
            SolverStatus.INFEASIBLE.value: "不可解（约束区间为空）",
        }
        driver_lines: List[str] = []
        for label, attr in drivers:
            val = getattr(implied, attr, None)
            st = getattr(implied, f"{attr}_status", None)
            if val is not None:
                suffix = "  _(近似)_" if st == SolverStatus.APPROXIMATE.value else ""
                if getattr(implied, f"{attr}_degenerate", False):
                    # The solve returned its own base input: the anchored growth
                    # path already justifies the price, so this number carries no
                    # incremental information. Say that instead of implying the
                    # market independently demands this discount rate.
                    suffix += (
                        "  _(与基准一致：当前增速已足以解释股价，该项不构成额外证据)_"
                    )
                driver_lines.append(f"**{label}:** {_fmt_pct(val)}{suffix}")
            elif st in unsolved_labels:
                driver_lines.append(f"**{label}:** {unsolved_labels[st]}")
        if driver_lines:
            lines.append("")
            if getattr(implied, "implied_base_cagr_is_bound", False):
                lines.append(
                    "_单变量隐含解（增速锚定于区间边界；回答「其它假设需如何变化才能支撑当前价」）:_"
                )
            else:
                lines.append("_单变量隐含解（其余假设固定为基准）:_")
            lines.extend(driver_lines)

        # Terminal-value suppression (Session #18).
        if getattr(implied, "terminal_fcf_negative", False):
            lines.append(
                "**⚠️ Terminal Value Suppressed** — 终期 FCF ≤ 0，终值已抑制；"
                "隐含值仅由显式期现金流支撑，需转型（Turnaround）假设"
            )

        _gva = (getattr(implied, "solver_meta", None) or {}).get(
            "growth_value_attribution"
        )
        if _gva and _gva.get("total") is not None:
            lines.append(ValuationReportBuilder._growth_value_attribution_block(_gva))

        lines.append(f"**当前价格（目标价）:** {_fmt_share(implied.current_price)}")
        if implied.notes:
            lines.append("**备注:**")
            for n in implied.notes[:3]:
                lines.append(f"  • {n}")
        if getattr(implied, "implied_constraint_notes", None):
            lines.append("**约束说明:**")
            for n in implied.implied_constraint_notes[:3]:
                lines.append(f"  • {n}")
        return "\n".join(lines)

    @staticmethod
    def _gap_section(gap: Any, profile: Optional[CompanyProfile] = None) -> str:
        if gap is None:
            return "N/A"
        implied_rev_line = f"**市场隐含营收 CAGR:** {_fmt_pct(gap.implied_revenue_cagr)}"
        if (getattr(gap, "implied_revenue_cagr_source", None) == "normalized_growth_solve"
                and gap.implied_revenue_cagr is not None):
            implied_rev_line += "  _(成熟稳态经济推导，APPROXIMATE)_"
        elif gap.implied_revenue_cagr is None:
            # Mirror the implied section's honest bound so the two sections agree
            # (Session #32): a price outside the sanctioned growth band must not
            # read "N/A" here while the implied block states "≥ ceiling".
            _bound = getattr(gap, "implied_revenue_cagr_bound", None) or {}
            _bkind, _bval = _bound.get("kind"), _bound.get("value")
            if _bkind == "above_band_ceiling" and _bval is not None:
                implied_rev_line = f"**市场隐含营收 CAGR:** ≥ {_bval:.0%}（区间上限，非点估）"
            elif _bkind == "below_band_floor" and _bval is not None:
                implied_rev_line = f"**市场隐含营收 CAGR:** ≤ {_bval:.0%}（区间下限，非点估）"
            elif _bkind == "ev_decreasing_in_growth":
                implied_rev_line = (
                    "**市场隐含营收 CAGR:** 不适用（模型 EV 随增速上升而下降）"
                )
            elif _bkind == "ev_direction_undetermined":
                implied_rev_line = (
                    "**市场隐含营收 CAGR:** 不可判定（方向对营运资本假设敏感）"
                )
        lines = [
            f"**历史营收 CAGR:** {_fmt_pct(gap.historical_revenue_cagr)}",
            f"**基础预测营收 CAGR:** {_fmt_pct(gap.base_forecast_revenue_cagr)}",
            implied_rev_line,
        ]
        _gap_verdict = getattr(gap, "growth_band_verdict", None)
        if _gap_verdict:
            _label, _caution = _GROWTH_BAND_VERDICT_LABELS.get(_gap_verdict, (_gap_verdict, ""))
            lines.append(
                f"**隐含增长可信度:** {_label}" + (f"  _({_caution})_" if _caution else "")
            )
        if gap.revenue_gap_vs_history is not None:
            direction = "高" if gap.revenue_gap_vs_history >= 0 else "低"
            lines.append(f"  → 隐含营收 CAGR 比历史水平{direction} {abs(gap.revenue_gap_vs_history)*100:.1f} 个百分点")
        lines.extend([
            f"**历史 FCF CAGR:** {_fmt_pct_or_reason(gap.historical_fcf_cagr, 'FCF 跨度为负值（无法计算 CAGR）')}",
            f"**基础预测 FCF CAGR:** {_fmt_pct(gap.base_forecast_fcf_cagr)}",
            f"**市场隐含 FCF CAGR:** {_fmt_pct(gap.implied_fcf_cagr)}",
        ])
        if gap.notes:
            lines.append("**解读:**")
            for n in gap.notes[:3]:
                lines.append(f"  • {n}")
        # ---- Plain-language growth verdict (attached to profile from pipeline) ----
        g = getattr(profile, "growth_verdict", None) if profile is not None else None
        if g is not None:
            bullets = g.bullet_lines()
            if bullets:
                lines.append("")
                lines.append("**📈 增长直观解读:**")
                lines.extend(bullets)
        return "\n".join(lines)

    @staticmethod
    def _sensitivity_section(sm: Any, profile: Optional[CompanyProfile] = None) -> str:
        if profile is not None:
            contract = build_caliber_contract(profile)
            if not contract.sensitivity_applicable:
                return contract.note("sensitivity")
        if sm is None:
            return "N/A"
        lines = [f"**敏感性矩阵:** {sm.title}"]
        try:
            base_row = sm.base_row_idx
            base_col = sm.base_col_idx
            base_val = sm.values[base_row][base_col]
            wacc_pct = sm.rows[base_row] * 100
            tg_pct = sm.cols[base_col] * 100
            lines.append(
                f"**基础情景（{sm.row_label}={wacc_pct:.1f}%, "
                f"{sm.col_label}={tg_pct:.2f}%）：** {_fmt_share(base_val)}"
            )
        except Exception:
            pass
        lines.append("")
        lines.append("_矩阵为等宽代码块，便于手机阅读；* 为基准格。_")
        lines.append("")
        if hasattr(sm, "formatted_code_table"):
            lines.append(
                sm.formatted_code_table(
                    row_title=sm.row_label.split()[0] if sm.row_label else "WACC",
                    col_title="g",
                    row_decimals=1,
                    col_decimals=2,
                    value_decimals=1,
                )
            )
        else:
            lines.append(sm.formatted_markdown_table())
        return "\n".join(lines)

    @staticmethod
    def _agreement_section(ag: Any, profile: Optional[CompanyProfile] = None) -> str:
        if ag is None:
            return "N/A"
        lines = []
        # ---- First line: intuitive valuation details (overview 已放过 headline，这里只展开细节) ----
        v = getattr(profile, "valuation_verdict", None) if profile is not None else None
        if v is not None:
            details = v.header_lines(include_headline=False)
            if details:
                lines.append("**🤝 估值细节拆解:**")
                lines.extend(details)
                lines.append("")
        lines.extend([
            f"**适用模型:** {ag.n_applicable}",
            f"**已解算模型:** {ag.n_solved}",
            f"**一致性水平:** {ag.agreement_level}",
            f"**中位估值:** {_fmt_share(ag.median_value)}",
            f"**平均估值:** {_fmt_share(ag.mean_value)}",
            f"**区间 [{_fmt_share(ag.low_value)} – {_fmt_share(ag.high_value)}]**",
        ])
        # ---- Phase 1: raw vs filtered sample transparency -------------------
        raw_n = getattr(ag, "raw_solved_count", ag.n_solved)
        out_n = getattr(ag, "outlier_count", 0)
        eff_n = getattr(ag, "effective_aggregation_count", ag.n_solved)
        share_n = len(getattr(ag, "share_count_excluded_models", None) or [])
        comp_n = len(getattr(ag, "comparability_excluded_models", None) or [])
        extra = ""
        if share_n or comp_n:
            extra = f" · 股数不可比 {share_n} 个 · 口径不可比 {comp_n} 个"
        lines.append(
            f"**样本口径:** 原始成功模型 {raw_n} 个 · IQR 排除 {out_n} 个{extra} · "
            f"最终参与中位数 {eff_n} 个"
        )
        if (out_n or share_n or comp_n) and raw_n:
            lines.append(
                f"  _原始成功模型 {raw_n} 个，其中 IQR 排除 {out_n} 个、股数不可比 "
                f"{share_n} 个、口径不可比 {comp_n} 个，最终参与中位数 {eff_n} 个；"
                f"中位估值**不代表 {raw_n} 个模型的共识**。_"
            )
        # ---- All-model vs survivor dispersion ------------------------------
        a_cv = getattr(ag, "all_model_cv", None)
        s_cv = getattr(ag, "survivor_cv", None)
        if a_cv is not None:
            lines.append(
                f"**全模型离散度（含被剔除极值）:** CV {a_cv*100:.1f}% → "
                f"{getattr(ag, 'all_model_dispersion_level', 'N/A')}"
            )
        if s_cv is not None:
            lines.append(
                f"**幸存模型一致性（IQR 后）:** CV {s_cv*100:.1f}% → "
                f"{getattr(ag, 'survivor_agreement_level', 'N/A')}"
            )
        if a_cv is not None and s_cv is not None and (a_cv - s_cv) > 0.15:
            lines.append(
                "  _⚠️ 幸存模型一致性明显优于全模型离散度：该「一致性」来自剔除分歧者，"
                "而非真实的跨模型共识。_"
            )
        # ---- Material disagreement banner + DCF vs multiples ranges --------
        if getattr(ag, "material_disagreement", False):
            lines.append("")
            lines.append("**🚨 模型分歧未解决（Material Disagreement / Review Required）**")
            dcf_v = getattr(ag, "dcf_value", None)
            m_lo = getattr(ag, "multiples_low", None)
            m_hi = getattr(ag, "multiples_high", None)
            if dcf_v is not None:
                lines.append(f"  • DCF 点值: {_fmt_share(dcf_v)}")
            if m_lo is not None and m_hi is not None:
                lines.append(f"  • 倍数法区间: {_fmt_share(m_lo)} – {_fmt_share(m_hi)}")
            lines.append(
                "  _核心 DCF 与倍数法方向不一致，须由使用者判断哪一方的假设更可信；"
                "本报告不将该中位估值表述为「高一致性」结论。_"
            )
        # ---- Phase 1.2: forced DCF-vs-multiple structured diagnostics -------
        div = getattr(ag, "divergence", None)
        if div is not None and getattr(div, "triggered", False):
            lines.append("")
            lines.append("**🔍 DCF vs 倍数法分歧诊断（结构化，可审计）**")
            if getattr(div, "summary", ""):
                lines.append(f"  {div.summary}")
            lines.append(
                f"  • 原始 DCF: {_fmt_share(getattr(div, 'dcf_value', None))} · "
                f"倍数法区间: {_fmt_share(getattr(div, 'peer_low', None))} – "
                f"{_fmt_share(getattr(div, 'peer_high', None))} · "
                f"peer 中位: {_fmt_share(getattr(div, 'peer_median', None))}"
            )
            _pm = getattr(div, "peer_models", None)
            if _pm:
                lines.append(f"  • 参与对比的倍数模型: {', '.join(_pm)}")
            for c in getattr(div, "checks", []):
                _icon = {
                    "flag": "🟠", "info": "ℹ️", "aligned": "🟢", "moderate": "🟡",
                }.get(getattr(c, "status", ""), "•")
                lines.append(f"  {_icon} **{c.label}:** {c.detail}")
            if getattr(div, "verdict", ""):
                lines.append(f"  _{div.verdict}_")
        # ---- Coverage / quality breakdown (Session #07) --------------------
        n_total = getattr(ag, "n_total", 0)
        n_na = getattr(ag, "n_not_applicable", 0)
        n_failed = getattr(ag, "n_failed", 0)
        n_disp = getattr(ag, "n_display_only", 0)
        if n_total:
            disp_txt = f"（含 {n_disp} 个仅展示，不计入统计）" if n_disp else ""
            # n_applicable excludes models dropped for a non-comparable share
            # denominator or a conflicting data caliber, so those buckets must
            # be named here or the row does not add up to n_total.
            share_n = len(getattr(ag, "share_count_excluded_models", None) or [])
            comp_n = len(getattr(ag, "comparability_excluded_models", None) or [])
            excl_bits = ""
            if share_n:
                excl_bits += f" · 股数不可比 {share_n}"
            if comp_n:
                excl_bits += f" · 口径不可比 {comp_n}"
            lines.append(
                f"**模型分桶:** 适用 {ag.n_applicable}（不适用 {n_na}）· "
                f"解算 {ag.n_solved} · 失败 {n_failed}{excl_bits} · 合计 {n_total}{disp_txt}"
            )
        qf = getattr(ag, "quality_factor", None)
        cf = getattr(ag, "coverage_factor", None)
        gcv = getattr(ag, "gated_cv", None)
        raw_lvl = getattr(ag, "agreement_level_raw", None)
        if qf is not None and cf is not None:
            gate_bits = [f"质量因子 {qf:.2f}", f"覆盖因子 {cf:.2f}"]
            if gcv is not None:
                gate_bits.append(f"门控 CV {gcv*100:.1f}%")
            if raw_lvl and raw_lvl != ag.agreement_level:
                gate_bits.append(f"原始一致性 {raw_lvl}")
            lines.append("**一致性门控:** " + " · ".join(gate_bits))
        mw = getattr(ag, "median_value_weighted", None)
        if mw is not None:
            lines.append(f"**质量加权中位估值:** {_fmt_share(mw)}")
        weights = getattr(ag, "model_weights", None)
        if weights:
            wtxt = ", ".join(f"{k}={v:g}" for k, v in weights.items())
            lines.append(f"**模型权重:** {wtxt}")
        na_models = getattr(ag, "not_applicable_models", None)
        if na_models:
            lines.append("**不适用模型（非失败）:**")
            for name, reason in na_models[:4]:
                lines.append(f"  • {name}: {reason}")
        failed_models = getattr(ag, "failed_models", None)
        if failed_models:
            lines.append("**失败模型:**")
            for name, reason in failed_models[:4]:
                lines.append(f"  • {name}: {reason}")
        if ag.spread_pct is not None:
            lines.append(f"**估值离散度（区间/中位数）:** {_fmt_pct(ag.spread_pct)}")
        if ag.cv is not None:
            lines.append(f"**变异系数:** {ag.cv*100:.1f}%")
        # ---- Phase F: Share Count Audit Table (P2) --------------------------
        audit_tbl = getattr(ag, "share_count_audit_table", None)
        if callable(audit_tbl):
            tbl = audit_tbl()
            if tbl:
                lines.append("")
                lines.append(tbl)
        if ag.notes:
            lines.append("**备注:**")
            for n in ag.notes[:5]:
                lines.append(f"  • {n}")
        # ---- Phase 1.5: report math & wording self-audit -------------------
        audit = getattr(v, "math_audit", None) if v is not None else None
        if audit is not None and getattr(audit, "checks", None):
            n_flag = getattr(audit, "n_flag", 0)
            if getattr(audit, "ok", True):
                lines.append(
                    f"**🧮 数学一致性校验:** ✅ 通过（{getattr(audit, 'n_ok', 0)} 项）"
                    "（百分比方向/基准、样本口径恒等式、核心模型排除状态）"
                )
            else:
                lines.append(f"**🧮 数学一致性校验:** ⚠️ 发现 {n_flag} 项不一致")
                for c in audit.checks:
                    if getattr(c, "status", "") != "ok":
                        lines.append(f"  • [{c.status}] {c.label}: {c.detail}")
        return "\n".join(lines)

    @staticmethod
    def _risk_section(rr: Any, profile: Optional[CompanyProfile] = None) -> str:
        if rr is None:
            return "N/A"
        # The discount-rate risk flag is named "WACC Risk" at the model layer.
        # For a cost-of-equity caliber (banks/insurers/FinTech) there is no WACC,
        # so rendering "WACC Risk" next to a ke-valued report is a caliber leak.
        # Re-label at the display layer from the engine's caliber contract.
        contract = build_caliber_contract(profile)
        cost_of_equity = contract.discount is DiscountCaliber.COST_OF_EQUITY
        lines = [
            f"**总体风险等级:** {rr.overall_severity}",
            f"**总体评分（100 = 最安全）：** {rr.overall_score}/100",
        ]
        # ---- Severity floor transparency (Phase 1.4) -----------------------
        floor = getattr(rr, "severity_floor", "None")
        by_score = getattr(rr, "overall_severity_by_score", "")
        if floor and floor != "None" and by_score and by_score != rr.overall_severity:
            lines.append(
                f"  _⚠️ 风险下限：存在「{floor}」级信号 → 总体等级不低于 {floor}"
                f"（仅按总分本应为 {by_score}）。总分不得掩盖单项风险。_"
            )
        counts = rr.summary_counts()
        lines.append("**计数:** " + " | ".join(f"{k}={v}" for k, v in counts.items() if v))
        # ---- P0-2: Split Fundamental Risk Score vs Data Confidence Score ----
        fr_score = getattr(rr, "fundamental_risk_score", None)
        dc_score = getattr(rr, "data_confidence_score", None)
        fr_assess = getattr(rr, "fundamental_assessment", "")
        dc_assess = getattr(rr, "data_confidence_assessment", "")
        if fr_score is not None and dc_score is not None:
            _assess_icon = {
                "PASS": "✅", "WARNING": "🟡", "FAIL": "🔴",
                "N/A": "⚪", "UNKNOWN": "❓",
            }
            lines.append("")
            lines.append("**📊 风险引擎拆分评分：**")
            lines.append(
                f"  • **基本面风险评分 (Fundamental Risk):** {fr_score}/100"
                f"  {_assess_icon.get(fr_assess, '•')} `{fr_assess}`"
            )
            lines.append(
                f"  • **数据置信度评分 (Data Confidence):** {dc_score}/100"
                f"  {_assess_icon.get(dc_assess, '•')} `{dc_assess}`"
            )
            lines.append(
                "  _基本面风险＝业务/财务/估值风险；数据置信度＝数据来源/溯源/完整性。"
                "N/A 与 UNKNOWN 不得转换为 PASS 或满分。_"
            )
        # ---- Per-dimension assessment table (PASS/WARNING/FAIL/N/A/UNKNOWN) ----
        dim_assess = getattr(rr, "dimension_assessments", None)
        if dim_assess:
            lines.append("")
            lines.append("**🔍 维度评估明细：**")
            _assess_icon_dim = {
                "PASS": "✅", "WARNING": "🟡", "FAIL": "🔴",
                "N/A": "⚪", "UNKNOWN": "❓",
            }
            for dim_name, assess in dim_assess.items():
                label = dim_name
                if cost_of_equity and label == "WACC Risk":
                    label = "Cost of Equity Risk"
                icon = _assess_icon_dim.get(assess, "•")
                lines.append(f"  {icon} `{assess}` **{label}**")
        # ---- Category split: business/financial vs valuation uncertainty ----
        if hasattr(rr, "counts_by_category"):
            cats = rr.counts_by_category()
            for cat_name in ("Business/Financial Risk", "Valuation Uncertainty"):
                bucket = cats.get(cat_name) or {}
                if not any(bucket.values()):
                    continue
                detail = " · ".join(f"{k}={v}" for k, v in bucket.items() if v)
                label = "🏭 业务/财务风险" if cat_name == "Business/Financial Risk" else "📐 估值不确定性"
                lines.append(f"**{label}:** {detail}")
        if rr.flags:
            lines.append("")
            lines.append("**关键风险信号:**")
            for f in rr.flags[:8]:
                sev = f.severity
                icon = {
                    "Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢", "None": "✅"
                }.get(sev, "•")
                label = f.risk_type
                if cost_of_equity and label == "WACC Risk":
                    label = "Cost of Equity Risk（权益成本/β）"
                lines.append(f"{icon} **[{sev}] {label}:** {f.evidence}")
                if f.rule:
                    lines.append(f"    _规则: {f.rule}_")
        return "\n".join(lines)

    @staticmethod
    def _provenance_banner(data: FinancialData) -> str:
        if data.source == DataSource.YAHOO_FINANCE and not any(
            n.startswith("yahoo_fallback_synthetic:") for n in data.quality.restatement_notes
        ):
            return ""
        lines = ["🚨 **数据溯源警告（请优先阅读）**"]
        if data.source == DataSource.SYNTHETIC:
            lines.append(
                "- 当前为 **SYNTHETIC 演示数据**，财报/价格/FCF 均非 live 市场数据。"
            )
        if any(n.startswith("yahoo_fallback_synthetic:") for n in data.quality.restatement_notes):
            lines.append(
                "- Yahoo Finance 拉取失败后启用了 **演示回退**（仅当环境变量允许时）。"
            )
        for n in data.notes[:4]:
            if "SYNTHETIC" in n or "Yahoo" in n or "演示" in n:
                lines.append(f"- {n}")
        lines.append("_以下估值数字可能不能代表该证券的真实市场状态。_")
        return "\n".join(lines)

    @staticmethod
    def _data_section(data: FinancialData, monte_carlo: Any = None) -> str:
        q = data.quality
        src = data.source.value if hasattr(data.source, "value") else str(data.source)
        rec = getattr(data, "reconciliation", None)
        _n_mm = int(getattr(q, "reconciliation_mismatches", 0) or 0)
        _usability = getattr(q, "valuation_usability_score", q.data_quality_score)
        _usable_lbl = q.usability_label() if hasattr(q, "usability_label") else "N/A"
        # The annotation explains *why* usability can sit below source quality.
        # Printing it unconditionally asserted a mismatch that may not exist.
        if _n_mm:
            _usability_note = f"  _（受对账不一致影响：{_n_mm} 项；与源数据质量分开）_"
        elif _usability < q.data_quality_score:
            _usability_note = "  _（受每股口径/EBITDA 等校验影响；与源数据质量分开）_"
        else:
            _usability_note = "  _（无对账不一致，与源数据质量一致）_"
        lines = [
            f"**数据来源:** {src}",
            f"**源数据质量评分:** {q.data_quality_score}/100  **({q.score_label()})**",
            f"**估值可用性评分:** {_usability}/100  **({_usable_lbl})**" + _usability_note,
            f"**抓取时间:** {data.fetched_at.strftime('%Y-%m-%d %H:%M UTC')}",
            f"**年度周期:** {len(data.annual_income)}年",
            f"**TTM 可用:** {'是' if data.ttm else '否'}",
        ]
        if q.missing_fields:
            lines.append(f"**缺失字段:** {', '.join(q.missing_fields)}")
        if q.restatement_notes:
            lines.append(f"**重述问题:** {len(q.restatement_notes)} 项")
        if rec is not None and getattr(rec, "checks", None):
            lines.append("")
            lines.append("**🔗 数据对账（市值/股数/EPS/PE/EV 交叉校验）:**")
            mismatches = rec.mismatches
            lines.append(
                f"  已校验 {len(rec.checks)} 项 · 一致 {rec.n_ok} · "
                f"不一致 {len(mismatches)} · 数据不足 {rec.n_na}"
            )
            for c in mismatches:
                lines.append("  " + c.render(_fmt_recon))
            if mismatches:
                lines.append(
                    "  _存在不一致项：相关倍数可能因供应商口径（年度 vs TTM、稀释股数、"
                    "重资产折旧）失真；估值以内部推算为准，或已标记为不可比。_"
                )
            # Reverse validation: fields actually corrected (deviation > 25%)
            override_log = getattr(data, "reconciliation_overrides", None)
            if override_log is not None and getattr(override_log, "records", None):
                lines.extend(override_log.to_lines(_fmt_recon))
        if data.notes:
            for n in data.notes[:3]:
                lines.append(f"  • {n}")
        if monte_carlo is not None and monte_carlo.n_simulations > 0:
            lines.append("")
            mode_val = getattr(monte_carlo, "mode", "base_case")
            is_bank_mc = getattr(monte_carlo, "is_bank", False)
            if is_bank_mc:
                mode_txt = "银行 RIM（Ke 与 ROE 联合扰动）"
            else:
                mode_txt = (
                    "基期假设扰动（中心 = 确定性 DCF 基准假设）"
                    if mode_val == "base_case" else "历史分布（中心 = 历史统计）"
                )
            lines.append(
                f"**蒙特卡洛模拟（N={monte_carlo.n_simulations}，模式 = {mode_txt}）：**"
            )
            if is_bank_mc:
                lines.append(
                    "_银行不使用普通企业 DCF 假设的 Monte Carlo（revenue CAGR / operating "
                    "margin / WACC / terminal growth 对借贷型业务无经济含义）；"
                    "改为扰动权益成本 Ke 与 ROE，通过 Bank RIM 模拟内在价值分布。_"
                )
            else:
                lines.append(
                    "_这是 DCF 假设的扰动分布，不是独立估值证据；只是把同一套 DCF 假设的"
                    "不确定性可视化。_"
                )
            seed = getattr(monte_carlo, "random_seed", None)
            n_req = getattr(monte_carlo, "n_requested", monte_carlo.n_simulations)
            n_inv = getattr(monte_carlo, "n_invalid", None)
            n_trunc = getattr(monte_carlo, "n_truncated", None)
            meta = [f"随机种子={seed}"]
            meta.append(f"请求={n_req}")
            meta.append(f"有效={getattr(monte_carlo, 'n_valid', None)}")
            if n_inv is not None:
                meta.append(f"无效={n_inv}")
            if n_trunc is not None and n_trunc > 0:
                meta.append(f"截断(负值 floor)={n_trunc}")
            lines.append("  " + " · ".join(str(m) for m in meta))
            lines.append(f"  均值: {_fmt_share(monte_carlo.mean_value)} | 中位数: {_fmt_share(monte_carlo.median_value)} | σ: {_fmt_share(monte_carlo.std_dev)}")
            pct_line = []
            for p, v in monte_carlo.percentiles.items():
                pct_line.append(f"P{p}={_fmt_share(v)}")
            lines.append("  " + " | ".join(pct_line))
            # Parameter distributions (mean / std / business bounds).
            pdists = getattr(monte_carlo, "param_distributions", None)
            if pdists:
                lines.append("  **参数分布（均值 ± σ，可行域）：**")
                for name, d in pdists.items():
                    try:
                        lines.append(
                            f"    ‣ {name}: {float(d['mean']):.2%} ± {float(d['std']):.2%}"
                            f"  [{float(d['lower']):.2%}, {float(d['upper']):.2%}]"
                        )
                    except (TypeError, ValueError, KeyError):
                        continue
            # Bank MC sample stats for Ke/ROE audit
            if is_bank_mc:
                roe_m = getattr(monte_carlo, "bank_roe_mean", None)
                ke_m = getattr(monte_carlo, "bank_ke_mean", None)
                if roe_m is not None and ke_m is not None:
                    lines.append(
                        f"  **样本统计：** Ke μ={ke_m:.2%} / ROE μ={roe_m:.2%}"
                    )
            corr = getattr(monte_carlo, "correlation", None)
            if corr:
                lines.append(
                    f"  **驱动相关性已建模：** 因子 {', '.join(corr.get('drivers', []))}"
                )
            # Truncated-distribution transparency: requested vs realised sample.
            _transp = getattr(monte_carlo, "distribution_transparency_note", None)
            if callable(_transp):
                _t = _transp()
                if _t:
                    lines.append(f"  {_t}")
            # Deterministic reconciliation (base-case mode only: historical mode
            # is not anchored on a deterministic path, so there is nothing to
            # reconcile against).
            anchor = getattr(monte_carlo, "anchor_value", None)
            gap = getattr(monte_carlo, "reconcile_gap", None)
            if anchor is not None and mode_val == "base_case":
                if gap is not None:
                    lines.append(
                        f"  **对账：** 零扰动锚点 {_fmt_share(anchor)} vs 确定性 DCF "
                        f"{_fmt_share(getattr(monte_carlo, 'dcf_anchor', None))}（差 {gap:+.1%}）"
                    )
                else:
                    lines.append(f"  **对账：** 零扰动锚点 {_fmt_share(anchor)}（未提供 DCF 基准）")
            # ---- P0-1: Bank-specific probability statements ----
            if is_bank_mc:
                p_above = getattr(monte_carlo, "prob_above_price", None)
                p_over_20 = getattr(monte_carlo, "prob_overvalued_20", None)
                p_under_20 = getattr(monte_carlo, "prob_undervalued_20", None)
                p_below_book = getattr(monte_carlo, "prob_below_book", None)
                p_roe_below_ke = getattr(monte_carlo, "prob_roe_below_ke", None)
                bvps_mc = getattr(monte_carlo, "book_value_per_share", None)
                if p_above is not None:
                    lines.append("")
                    lines.append("**🎲 银行概率结论（Bank RIM 模拟分布）：**")
                    price_mc = getattr(monte_carlo, "current_price", None)
                    price_txt = f"${price_mc:.2f}" if price_mc else "当前价"
                    lines.append(
                        f"  • P(内在价值 > 市场价 {price_txt}) = **{p_above:.1%}**"
                    )
                    if p_over_20 is not None:
                        lines.append(f"  • P(高估 > 20%) = **{p_over_20:.1%}**")
                    if p_under_20 is not None:
                        lines.append(f"  • P(低估 > 20%) = **{p_under_20:.1%}**")
                    if p_below_book is not None and bvps_mc is not None:
                        lines.append(
                            f"  • P(内在价值 < 每股账面价值 {_fmt_share(bvps_mc)}) = **{p_below_book:.1%}**"
                        )
                    if p_roe_below_ke is not None:
                        lines.append(
                            f"  • P(ROE < Ke) = **{p_roe_below_ke:.1%}**"
                        )
                    # Raw-vs-adjusted CAPM Ke audit line (bank only).
                    lines.extend(bank_ke_note_lines(monte_carlo))
            else:
                p_above = getattr(monte_carlo, "prob_above_price", None)
                p_over = getattr(monte_carlo, "prob_overvalued_30", None)
                p_zero = getattr(monte_carlo, "prob_equity_zero", None)
                if p_above is not None:
                    lines.append("")
                    lines.append("**🎲 概率结论（模拟分布）：**")
                    price_mc = getattr(monte_carlo, "current_price", None)
                    price_txt = f"${price_mc:.2f}" if price_mc else "当前价"
                    verdict_txt = "高估概率高" if p_above < 0.05 else ("偏贵" if p_above < 0.25 else "接近均衡")
                    lines.append(
                        f"  • P(内在价值 > {price_txt}) = **{p_above:.1%}** → {verdict_txt}"
                    )
                    if p_over is not None:
                        lines.append(f"  • P(高估 > 30%) = **{p_over:.1%}**")
                    if p_zero is not None and p_zero > 0:
                        lines.append(
                            f"  • 模拟下的 Equity Value Wipeout Probability = **{p_zero:.1%}**"
                            f"（负股权价值已 floor 到 0；非实际破产概率）"
                        )
        elif monte_carlo is not None and monte_carlo.n_simulations == 0 and getattr(monte_carlo, "is_bank", False):
            # P0-1: Bank MC not implementable → explicit N/A message
            lines.append("")
            lines.append("**蒙特卡洛模拟：** Monte Carlo: Not Applicable — Financial Institution")
            for n in monte_carlo.notes[:3]:
                lines.append(f"  • {n}")
        lines.append("")
        lines.append("_免责声明：本报告仅用于信息与教育目的，不构成投资建议。请自行进行尽职调查。历史表现并不代表未来结果。_")
        return "\n".join(lines)


__all__ = ["DashboardReport", "ValuationReportBuilder"]
