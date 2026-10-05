"""
reporting/dashboard.py - Auditable Valuation Dashboard Report Generator
Produces structured Markdown reports for Telegram.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from config import REPORT_SECTION_TITLES, TELEGRAM_MAX_MESSAGE_LENGTH, DataSource, get_logger
from data.models import CompanyProfile, FinancialData

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
        dash.add_section("business", ValuationReportBuilder._business_section(data, profile))
        dash.add_section("ml_prob", ValuationReportBuilder._ml_probability_section(profile))
        dash.add_section("market", ValuationReportBuilder._market_section(data))
        dash.add_section("valuation", ValuationReportBuilder._valuation_section(model_results, data))
        dash.add_section("scenarios", ValuationReportBuilder._scenario_section(scenarios, data))
        dash.add_section("implied", ValuationReportBuilder._implied_section(implied))
        dash.add_section("gap", ValuationReportBuilder._gap_section(gap))
        dash.add_section("sensitivity", ValuationReportBuilder._sensitivity_section(sensitivity_wacc_tg))
        dash.add_section("models", ValuationReportBuilder._agreement_section(agreement))
        dash.add_section("risk", ValuationReportBuilder._risk_section(risk))
        if monte_carlo is not None:
            dash.add_section("data", ValuationReportBuilder._data_section(data, monte_carlo))
        else:
            dash.add_section("data", ValuationReportBuilder._data_section(data))
        return dash.build()

    @staticmethod
    def _business_section(data: FinancialData, profile: CompanyProfile) -> str:
        m = data.market
        lines = [
            f"**代码:** {data.ticker}",
            f"**公司:** {m.company_name or 'N/A'}",
            f"**行业 / 细分行业:** {m.sector or 'N/A'} / {m.industry or 'N/A'}",
            f"**业务类型:** {profile.business_type}（置信度 {profile.classification_confidence:.0%}）",
            f"**收入规模:** {profile.revenue_characteristic}",
            f"**增长特征:** {profile.growth_profile}",
            f"**盈利能力:** {profile.profitability_profile}",
            f"**现金流:** {profile.cash_flow_profile}",
            f"**杠杆情况:** {profile.leverage_profile}",
            f"**资本密集度:** {profile.capital_intensity}",
        ]
        if profile.classification_reasons:
            lines.append("**分类理由:**")
            for r in profile.classification_reasons[:3]:
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
    def _market_section(data: FinancialData) -> str:
        m = data.market
        ttm = data.ttm
        trailing_pe = None
        if ttm and ttm.eps and ttm.eps > 0 and m.current_price:
            trailing_pe = m.current_price / ttm.eps
        lines = [
            f"**当前价格:** {_fmt_share(m.current_price)}",
            f"**市值:** {_fmt_money(m.market_cap)}",
            f"**企业价值:** {_fmt_money(m.enterprise_value)}",
            f"**总债务:** {_fmt_money(m.total_debt)} | **现金:** {_fmt_money(m.cash_and_equivalents)} | **净债务:** {_fmt_money(m.net_debt)}",
            f"**每股账面价值:** {_fmt_share(m.book_value_per_share)}",
            f"**贝塔系数:** {_fmt_num(m.beta, 2)}",
            f"**滚动市盈率:** {_fmt_num(m.trailing_pe or trailing_pe, 1)}",
            f"**EV/EBITDA:** {_fmt_num(m.ev_to_ebitda, 1)}",
            f"**市净率 (P/B):** {_fmt_num(m.price_to_book, 1)}",
            f"**股息收益率:** {_fmt_pct(m.dividend_yield)}",
        ]
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
            lines.append(
                f"**TTM 总览:** 营收 {_fmt_money(ttm.revenue)} | EBITDA {_fmt_money(ttm.ebitda)} | 净利润 {_fmt_money(ttm.net_income)} | FCF {_fmt_money(ttm.free_cash_flow)}"
            )
        return "\n".join(lines)

    @staticmethod
    def _valuation_section(model_results: Dict[str, Any], data: FinancialData) -> str:
        lines = []
        price = data.market.current_price
        dcf_breakdown: Optional[Dict[str, Any]] = None
        for name, r in model_results.items():
            if r.is_success() and r.value_per_share is not None:
                pps = r.value_per_share
                if price and price > 0:
                    diff = (pps - price) / price
                    lines.append(f"• **{name}:** {_fmt_share(pps)}  （较当前价格 {diff:+.1%}）")
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
                lines.append(f"  规则: base = min(normalized_growth={_fmt_pct(tg.normalized_growth,2)}, LT_nominal_GDP={_fmt_pct(tg.long_term_nominal_gdp,2)}, WACC−0.5%={_fmt_pct(tg.wacc_minus_half_pct,2)})")
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
            if vps is not None:
                if price and price > 0:
                    diff = (vps - price) / price
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)}  （较当前价格 {diff:+.1%}） — WACC {_fmt_pct(getattr(sv,'wacc',0))} / g {_fmt_pct(getattr(sv,'terminal_growth',0))}")
                else:
                    lines.append(f"• **{translations.get(s, s)}:** {_fmt_share(vps)}")
                for n in getattr(sv, "notes", [])[:2]:
                    lines.append(f"    ‣ {n}")
            else:
                lines.append(f"• **{translations.get(s, s)}:** N/A")
        return "\n".join(lines)

    @staticmethod
    def _implied_section(implied: Any) -> str:
        if implied is None:
            return "N/A"
        lines = [
            f"**反向 DCF 状态:** {implied.reverse_dcf_status or 'N/A'}",
            f"**隐含 FCF CAGR:** {_fmt_pct(implied.implied_fcf_cagr)}",
            f"**隐含营收 CAGR:** {_fmt_pct(implied.implied_revenue_cagr)}",
            f"**当前价格（目标价）:** {_fmt_share(implied.current_price)}",
        ]
        if implied.notes:
            lines.append("**备注:**")
            for n in implied.notes[:3]:
                lines.append(f"  • {n}")
        return "\n".join(lines)

    @staticmethod
    def _gap_section(gap: Any) -> str:
        if gap is None:
            return "N/A"
        lines = [
            f"**历史营收 CAGR:** {_fmt_pct(gap.historical_revenue_cagr)}",
            f"**基础预测营收 CAGR:** {_fmt_pct(gap.base_forecast_revenue_cagr)}",
            f"**市场隐含营收 CAGR:** {_fmt_pct(gap.implied_revenue_cagr)}",
        ]
        if gap.revenue_gap_vs_history is not None:
            direction = "高于" if gap.revenue_gap_vs_history >= 0 else "低于"
            lines.append(f"  → 隐含营收 CAGR 比历史水平高出 {abs(gap.revenue_gap_vs_history)*100:.1f} 个百分点")
        lines.extend([
            f"**历史 FCF CAGR:** {_fmt_pct(gap.historical_fcf_cagr)}",
            f"**基础预测 FCF CAGR:** {_fmt_pct(gap.base_forecast_fcf_cagr)}",
            f"**市场隐含 FCF CAGR:** {_fmt_pct(gap.implied_fcf_cagr)}",
        ])
        if gap.notes:
            lines.append("**解读:**")
            for n in gap.notes[:3]:
                lines.append(f"  • {n}")
        return "\n".join(lines)

    @staticmethod
    def _sensitivity_section(sm: Any) -> str:
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
    def _agreement_section(ag: Any) -> str:
        if ag is None:
            return "N/A"
        lines = [
            f"**适用模型:** {ag.n_applicable}",
            f"**已解算模型:** {ag.n_solved}",
            f"**一致性水平:** {ag.agreement_level}",
            f"**中位估值:** {_fmt_share(ag.median_value)}",
            f"**平均估值:** {_fmt_share(ag.mean_value)}",
            f"**区间 [{_fmt_share(ag.low_value)} – {_fmt_share(ag.high_value)}]**",
        ]
        if ag.spread_pct is not None:
            lines.append(f"**估值离散度（区间/中位数）:** {_fmt_pct(ag.spread_pct)}")
        if ag.cv is not None:
            lines.append(f"**变异系数:** {ag.cv*100:.1f}%")
        if ag.notes:
            lines.append("**备注:**")
            for n in ag.notes[:3]:
                lines.append(f"  • {n}")
        return "\n".join(lines)

    @staticmethod
    def _risk_section(rr: Any) -> str:
        if rr is None:
            return "N/A"
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
                lines.append(f"{icon} **[{sev}] {f.risk_type}:** {f.evidence}")
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
            f"**数据质量评分:** {q.data_quality_score}/100  **({q.score_label()})**",
            f"**抓取时间:** {data.fetched_at.strftime('%Y-%m-%d %H:%M UTC')}",
            f"**年度周期:** {len(data.annual_income)}年",
            f"**TTM 可用:** {'是' if data.ttm else '否'}",
        ]
        if q.missing_fields:
            lines.append(f"**缺失字段:** {', '.join(q.missing_fields)}")
        if q.restatement_notes:
            lines.append(f"**重述问题:** {len(q.restatement_notes)} 项")
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
        lines.append("")
        lines.append("_免责声明：本报告仅用于信息与教育目的，不构成投资建议。请自行进行尽职调查。历史表现并不代表未来结果。_")
        return "\n".join(lines)


__all__ = ["DashboardReport", "ValuationReportBuilder"]
