"""
reporting/dashboard.py - Auditable Valuation Dashboard Report Generator
Produces structured Markdown reports for Telegram.
"""
from __future__ import annotations

from datetime import datetime
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
from valuation.caliber import DiscountCaliber, MetricMeaning, build_caliber_contract
from valuation.wacc import BETA_WINSOR_HI, BETA_WINSOR_LO, resolve_effective_beta

log = get_logger("reporting.dashboard")


def _fmt_money(v: Optional[float], decimals: int = 0) -> str:
    if v is None:
        return "N/A"
    try:
        v_f = float(v)
    except (TypeError, ValueError):
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
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v)*100:,.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_num(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


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
                f"统一采用截断值 {eb.beta:.2f})_"
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
        # Macro / derived snapshot
        macro_parts = []
        if getattr(m, "risk_free_rate", None):
            macro_parts.append(f"Rf(10Y) {_fmt_pct(m.risk_free_rate,2)}")
        if getattr(m, "effective_tax_rate", None):
            macro_parts.append(f"ETR {_fmt_pct(m.effective_tax_rate,1)}")
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
        """Qualitative label for one model's spread vs current price."""
        if diff is None:
            return ""
        d = float(diff) * 100.0  # percentage
        # diff = pps - price / price → negative = underperformed, positive = undervalued? Actually diff = (pps - price) / price → diff > 0: model says price should be higher → 低估
        if d >= 50:
            return "  [模型判断**显著低估**]"
        if d >= 20:
            return "  [**明显低估**]"
        if d >= 8:
            return "  [**小幅低估**]"
        if d > -8:
            return "  [**估值合理**]"
        if d > -20:
            return "  [**小幅高估**]"
        if d > -50:
            return "  [**明显高估**]"
        return "  [**显著高估**]"

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
                lines.append(f"  规则: base = min(normalized_growth={_fmt_pct(tg.normalized_growth,2)}, LT_nominal_GDP={_fmt_pct(tg.long_term_nominal_gdp,2)}, WACC−0.5%={_fmt_pct(tg.wacc_minus_half_pct,2)})；Low/High = Base±0.5% 且 Low < Base < High（High 不受 GDP 4.5% 封顶）")
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
    def _implied_section(implied: Any) -> str:
        if implied is None:
            return "N/A"
        rev_line = f"**隐含营收 CAGR:** {_fmt_pct(implied.implied_revenue_cagr)}"
        if (getattr(implied, "implied_revenue_cagr_source", None) == "normalized_growth_solve"
                and implied.implied_revenue_cagr is not None):
            rev_line += "  _(成熟稳态经济推导，APPROXIMATE — 非直接求解)_"
        lines = [
            f"**反向 DCF 状态:** {implied.reverse_dcf_status or 'N/A'}",
            f"**隐含 FCF CAGR:** {_fmt_pct(implied.implied_fcf_cagr)}",
            rev_line,
        ]

        # ---- Phase 2 (Session #17): one-at-a-time implied drivers ----
        drivers = [
            ("隐含营业利润率", "implied_operating_margin"),
            ("隐含 FCF 利润率", "implied_fcf_margin"),
            ("隐含折现率 (WACC)", "implied_wacc"),
            ("隐含终值增长率", "implied_terminal_growth"),
        ]
        driver_lines: List[str] = []
        for label, attr in drivers:
            val = getattr(implied, attr, None)
            st = getattr(implied, f"{attr}_status", None)
            if val is not None:
                suffix = "  _(近似)_" if st == SolverStatus.APPROXIMATE.value else ""
                driver_lines.append(f"**{label}:** {_fmt_pct(val)}{suffix}")
            elif st == SolverStatus.NO_SOLUTION_IN_RANGE.value:
                driver_lines.append(f"**{label}:** 不可解（超出约束区间）")
        if driver_lines:
            lines.append("")
            lines.append("_单变量隐含解（其余假设固定为基准）:_")
            lines.extend(driver_lines)

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
        lines = [
            f"**历史营收 CAGR:** {_fmt_pct(gap.historical_revenue_cagr)}",
            f"**基础预测营收 CAGR:** {_fmt_pct(gap.base_forecast_revenue_cagr)}",
            implied_rev_line,
        ]
        if gap.revenue_gap_vs_history is not None:
            direction = "高" if gap.revenue_gap_vs_history >= 0 else "低"
            lines.append(f"  → 隐含营收 CAGR 比历史水平{direction} {abs(gap.revenue_gap_vs_history)*100:.1f} 个百分点")
        lines.extend([
            f"**历史 FCF CAGR:** {_fmt_pct(gap.historical_fcf_cagr)}",
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
        # ---- Coverage / quality breakdown (Session #07) --------------------
        n_total = getattr(ag, "n_total", 0)
        n_na = getattr(ag, "n_not_applicable", 0)
        n_failed = getattr(ag, "n_failed", 0)
        n_disp = getattr(ag, "n_display_only", 0)
        if n_total:
            disp_txt = f"（含 {n_disp} 个仅展示，不计入统计）" if n_disp else ""
            lines.append(
                f"**模型分桶:** 适用 {ag.n_applicable}（不适用 {n_na}）· "
                f"解算 {ag.n_solved} · 失败 {n_failed} · 合计 {n_total}{disp_txt}"
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
        if ag.notes:
            lines.append("**备注:**")
            for n in ag.notes[:5]:
                lines.append(f"  • {n}")
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
        counts = rr.summary_counts()
        lines.append(f"**计数:** " + " | ".join(f"{k}={v}" for k, v in counts.items() if v))
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
        lines = [
            f"**数据来源:** {src}",
            f"**源数据质量评分:** {q.data_quality_score}/100  **({q.score_label()})**",
            f"**估值可用性评分:** {getattr(q,'valuation_usability_score',q.data_quality_score)}/100"
            f"  **({q.usability_label() if hasattr(q,'usability_label') else 'N/A'})**"
            f"  _（受对账不一致影响；与源数据质量分开）_",
            f"**抓取时间:** {data.fetched_at.strftime('%Y-%m-%d %H:%M UTC')}",
            f"**年度周期:** {len(data.annual_income)}年",
            f"**TTM 可用:** {'是' if data.ttm else '否'}",
        ]
        if q.missing_fields:
            lines.append(f"**缺失字段:** {', '.join(q.missing_fields)}")
        if q.restatement_notes:
            lines.append(f"**重述问题:** {len(q.restatement_notes)} 项")
        rec = getattr(data, "reconciliation", None)
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
            lines.append(f"**蒙特卡洛模拟（N={monte_carlo.n_simulations}）：**")
            lines.append(f"  均值: {_fmt_share(monte_carlo.mean_value)} | 中位数: {_fmt_share(monte_carlo.median_value)} | σ: {_fmt_share(monte_carlo.std_dev)}")
            pct_line = []
            for p, v in monte_carlo.percentiles.items():
                pct_line.append(f"P{p}={_fmt_share(v)}")
            lines.append("  " + " | ".join(pct_line))
            p_above = getattr(monte_carlo, "prob_above_price", None)
            p_over = getattr(monte_carlo, "prob_overvalued_30", None)
            p_zero = getattr(monte_carlo, "prob_equity_zero", None)
            if p_above is not None:
                lines.append("")
                lines.append("**🎲 概率结论（负值已 floor 到 0；驱动因子相关性已建模）：**")
                price_mc = getattr(monte_carlo, "current_price", None)
                price_txt = f"${price_mc:.2f}" if price_mc else "当前价"
                verdict_txt = "高估概率高" if p_above < 0.05 else ("偏贵" if p_above < 0.25 else "接近均衡")
                lines.append(
                    f"  • P(内在价值 > {price_txt}) = **{p_above:.1%}** → {verdict_txt}"
                )
                if p_over is not None:
                    lines.append(f"  • P(高估 > 30%) = **{p_over:.1%}**")
                if p_zero is not None and p_zero > 0:
                    lines.append(f"  • P(股权价值归零/资不抵债) = **{p_zero:.1%}**")
        lines.append("")
        lines.append("_免责声明：本报告仅用于信息与教育目的，不构成投资建议。请自行进行尽职调查。历史表现并不代表未来结果。_")
        return "\n".join(lines)


__all__ = ["DashboardReport", "ValuationReportBuilder"]
