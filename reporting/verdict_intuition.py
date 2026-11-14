"""
reporting/verdict_intuition.py — Plain-language intuitive labels for the
valuation report.

Turns raw percentages (CAGR, spreads vs price, scenario ranges, DCF success
rate) into concise Chinese qualitative labels (高速增长 / 明显高估 / 增长放缓
/ 低估但模型矛盾等) so Telegram readers don't need to scan the numbers.

Pure functions; all verdict objects live in data/models.py (GrowthVerdictCard,
ValuationVerdictCard) and are attached to CompanyProfile in the pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import get_logger
from data.models import GrowthVerdictCard, ValuationVerdictCard
from reporting.math_audit import (
    audit_report_math,
    pct_vs,
    phrase_vs,
    valuation_band,
    valuation_emoji,
)

log = get_logger("reporting.verdict_intuition")


# ---------- Growth: revenue / FCF CAGR buckets ----------

def _rev_cagr_label(cagr: Optional[float]) -> str:
    if cagr is None:
        return "数据缺失"
    r = float(cagr)
    if r >= 0.40:
        return "爆发式增长 (>40%)"
    if r >= 0.25:
        return "高速增长 (25%~40%)"
    if r >= 0.15:
        return "稳健增长 (15%~25%)"
    if r >= 0.05:
        return "温和增长 (5%~15%)"
    if r >= 0.00:
        return "低速增长 (0%~5%)"
    if r >= -0.10:
        return "轻微负增长 (-10%~0%)"
    return "明显负增长 (<-10%)"


def _fcf_cagr_label(cagr: Optional[float]) -> str:
    if cagr is None:
        return "数据缺失"
    r = float(cagr)
    if r >= 0.30:
        return "现金流高速增长 (>30%)"
    if r >= 0.10:
        return "现金流稳健增长 (10%~30%)"
    if r >= 0.00:
        return "现金流温和改善 (0%~10%)"
    if r >= -0.15:
        return "现金流小幅恶化 (-15%~0%)"
    return "现金流明显恶化 (<-15%)"


def _change_label(delta_pp: Optional[float]) -> str:
    """delta_pp = forecast - historical or implied - base, in proportion units (not pp)."""
    if delta_pp is None:
        return "数据不足"
    d = float(delta_pp)
    # Treat as "pp" for CAGR values, 1 unit = 100pp
    d_pp = d * 100.0
    if d_pp >= 10:
        return f"明显提升 (+{d_pp:+.1f}pp)"
    if d_pp >= 3:
        return f"小幅提升 (+{d_pp:+.1f}pp)"
    if d_pp > -3:
        return f"基本持平 ({d_pp:+.1f}pp)"
    if d_pp > -10:
        return f"小幅下滑 ({d_pp:+.1f}pp)"
    return f"明显放缓 ({d_pp:+.1f}pp)"


def build_growth_verdict(gap: Any) -> GrowthVerdictCard:
    """Build GrowthVerdictCard from ExpectationGap output."""
    v = GrowthVerdictCard()
    if gap is None:
        v.overall_growth_summary = "增长数据缺失，无法判断"
        return v

    hist_rev = getattr(gap, "historical_revenue_cagr", None)
    base_rev = getattr(gap, "base_forecast_revenue_cagr", None)
    impl_rev = getattr(gap, "implied_revenue_cagr", None)
    hist_fcf = getattr(gap, "historical_fcf_cagr", None)

    v.historical_revenue_label = _rev_cagr_label(hist_rev)
    if hist_rev is not None:
        v.historical_revenue_detail = (
            f"{v.historical_revenue_label}（{hist_rev*100:.1f}% 历史营收 CAGR）"
        )
    v.forecast_revenue_label = _rev_cagr_label(base_rev)
    v.implied_revenue_label = _rev_cagr_label(impl_rev)
    v.historical_fcf_label = _fcf_cagr_label(hist_fcf)

    # Forecast vs History (the user's "增长/高速增长/明显放缓/放缓/负增长" requirement)
    if base_rev is not None and hist_rev is not None:
        delta = base_rev - hist_rev
        v.forecast_vs_history_label = _change_label(delta)
        if delta is not None:
            d_pp = float(delta) * 100.0
            # Build intuitive summary sentence (key requirement!)
            if base_rev >= 0.25 and d_pp < -5:
                detail = (
                    f"仍属「高速增长」，但预测 CAGR {base_rev*100:.1f}% "
                    f"较历史 {hist_rev*100:.1f}% 有**明显放缓**（{d_pp:+.1f}pp）"
                )
            elif base_rev >= 0.15 and d_pp < -5:
                detail = (
                    f"「稳健增长」区间，预测 CAGR {base_rev*100:.1f}% "
                    f"较历史 {hist_rev*100:.1f}% **有所放缓**（{d_pp:+.1f}pp）"
                )
            elif base_rev >= 0 and d_pp <= -10:
                detail = (
                    f"增长**明显放缓**：历史 {hist_rev*100:.1f}% → "
                    f"预测 {base_rev*100:.1f}%（{d_pp:+.1f}pp）"
                )
            elif base_rev < 0 and hist_rev >= 0:
                detail = (
                    f"「负增长」：历史正增长 {hist_rev*100:.1f}% → "
                    f"预测转负 {base_rev*100:.1f}%"
                )
            elif base_rev < 0 and hist_rev < 0:
                detail = (
                    f"「持续负增长」：历史 {hist_rev*100:.1f}% → "
                    f"预测 {base_rev*100:.1f}%"
                )
            else:
                detail = (
                    f"{v.forecast_revenue_label}（{base_rev*100:.1f}%），"
                    f"vs 历史 {hist_rev*100:.1f}%（{d_pp:+.1f}pp）"
                )
            v.forecast_vs_history_detail = detail

    if impl_rev is not None and hist_rev is not None:
        v.implied_vs_history_label = _change_label(impl_rev - hist_rev)
    if impl_rev is not None and base_rev is not None:
        v.implied_vs_forecast_label = _change_label(impl_rev - base_rev)

    # Overall headline
    overall_parts = []
    if hist_rev is not None:
        # Keep the headline bucket identical to the bullet's `_rev_cagr_label`
        # band, otherwise the header ("高速增长") contradicts the bullet
        # ("爆发式增长 (>40%)") for the same historical CAGR.
        if hist_rev >= 0.40:
            overall_parts.append("历史表现属于**爆发式增长**")
            v.overall_growth_emoji = "🚀"
        elif hist_rev >= 0.25:
            overall_parts.append("历史表现属于**高速增长**")
            v.overall_growth_emoji = "🚀"
        elif hist_rev >= 0.15:
            overall_parts.append("历史表现**稳健增长**")
            v.overall_growth_emoji = "📈"
        elif hist_rev >= 0.05:
            overall_parts.append("历史表现**温和增长**")
            v.overall_growth_emoji = "📊"
        elif hist_rev >= 0:
            overall_parts.append("历史表现**低速增长**")
            v.overall_growth_emoji = "📊"
        else:
            overall_parts.append("历史增长承压")
            v.overall_growth_emoji = "📉"
    if base_rev is not None and hist_rev is not None:
        d_pp = (base_rev - hist_rev) * 100.0
        if d_pp <= -10:
            overall_parts.append("预测增速**明显放缓**")
            v.overall_growth_emoji = "🟡"
        elif d_pp <= -3:
            overall_parts.append("预测增速**小幅放缓**")
        elif d_pp >= 10:
            overall_parts.append("预测增速提升明显")
            v.overall_growth_emoji = "🟢"
    if overall_parts:
        v.overall_growth_summary = "；".join(overall_parts)
    else:
        v.overall_growth_summary = "增长数据不足，无法判断"
    return v


# ---------- Valuation labels ----------

def _vs_median_label(price: Optional[float], median: Optional[float]) -> tuple[str, str, str, str]:
    """Return (short_label, median_vs_price_sentence, headline_label_candidate, spread_only).

    - short_label: e.g. "**高估**" (for bullet list)
    - median_vs_price_sentence: self-contained Chinese sentence used as bullet detail
      e.g. "当前价 $15.58 比中位估值高 +41.6%" (主语清晰，不重复)
    - headline_label_candidate: for main emoji headline, e.g. "偏高"
    - spread_only: pure percentage line for reasoning
    """
    if price is None or median is None or median <= 0:
        return ("数据不足", "", "数据不足", "")
    pct = pct_vs(price, median)
    if pct is None:
        return ("数据不足", "", "数据不足", "")
    spread_txt = f"{pct*100:+.1f}%"
    # Base-anchored sentence (base = 中位估值): a positive gap is always worded
    # "当前价 较 中位估值 高出 X%", never "…低于 X%" — the Phase 1.5 base-inversion
    # guard. The magnitude and its base come from the same pct_vs() call.
    sent = phrase_vs(price, median, subject="当前价", ref_name="中位估值")
    # Canonical ladder (shared with dashboard per-model labels) — one wording
    # for "高估/低估" across every section.
    label, _band_emoji = valuation_band(pct)
    return (f"**{label}**", sent, label, spread_txt)


def _scenario_summary(scenarios: Dict[str, Any], price: Optional[float]) -> tuple[str, str]:
    """Return (short_scenario_label, one_sentence_summary)."""
    if not scenarios:
        return ("情景数据不足", "")
    bear = scenarios.get("Bear")
    base = scenarios.get("Base")
    bull = scenarios.get("Bull")
    bv = getattr(bear, "value_per_share", None) if bear else None
    sv = getattr(base, "value_per_share", None) if base else None
    uv = getattr(bull, "value_per_share", None) if bull else None
    if bv is None or sv is None or uv is None:
        return ("情景数据不足", "")
    bits = []
    if price and price > 0:
        bear_diff = (bv - price) / price * 100.0
        bull_diff = (uv - price) / price * 100.0
        # Where does the current price actually sit relative to ALL scenarios?
        lo, hi = min(bv, sv, uv), max(bv, sv, uv)
        if price > hi:
            # Current price is above even the most optimistic scenario. The
            # percentage is anchored on the scenario base; when that base is
            # non-positive no meaningful relative gap exists — say so instead of
            # printing a misleading "高出 0.0%".
            if uv > 0:
                bits.append(
                    f"当前价高于**全部**情景（"
                    f"{phrase_vs(price, uv, subject='当前价', ref_name='乐观情景')}）"
                )
            else:
                bits.append("当前价高于**全部**情景（乐观情景估值 ≤ 0，无法计算相对幅度）")
        elif price < lo:
            if bv > 0:
                bits.append(
                    f"当前价低于**全部**情景（"
                    f"{phrase_vs(price, bv, subject='当前价', ref_name='悲观情景')}）"
                )
            else:
                bits.append("当前价低于**全部**情景（悲观情景估值 ≤ 0，无法计算相对幅度）")
        else:
            bits.append(
                f"当前价落在 熊市({bear_diff:+.1f}%) ~ 牛市({bull_diff:+.1f}%) 区间"
            )
    bits.append(
        f"三档跨度 {bv:.2f} → {sv:.2f} → {uv:.2f}"
    )
    # How wide is the spread? Base = 基准情景 Base 值（不再使用含糊的 "% SV" 缩写）
    if sv and uv and bv:
        span = (uv - bv) / sv * 100.0
        span_txt = f"（三档跨度 {span:.0f}%，基准 = 基准情景 Base ${sv:.2f}）"
        if span > 120:
            return ("估值区间极宽（结果高度分歧）", "；".join(bits) + span_txt)
        if span > 60:
            return ("估值区间较宽（存在一定分歧）", "；".join(bits) + span_txt)
        if span > 25:
            return ("估值区间适中", "；".join(bits) + span_txt)
        return ("估值区间窄（模型较一致）", "；".join(bits) + span_txt)
    return ("情景数据不足", "；".join(bits))


def build_valuation_verdict(
    *,
    agreement: Any,
    scenarios: Dict[str, Any],
    model_results: Dict[str, Any],
    data: Any,
    profile: Any,
    implied: Any,
) -> ValuationVerdictCard:
    """Build ValuationVerdictCard from multiple upstream analysis outputs."""
    v = ValuationVerdictCard()
    price = getattr(getattr(data, "market", None), "current_price", None)
    median = getattr(agreement, "median_value", None)
    n_applicable = getattr(agreement, "n_applicable", 0)
    n_solved = getattr(agreement, "n_solved", 0)
    n_approximate = getattr(agreement, "n_approximate", 0)
    median_high_conf = getattr(agreement, "median_value_high_conf", None)
    low = getattr(agreement, "low_value", None)
    high = getattr(agreement, "high_value", None)

    # When all solved models are APPROXIMATE, prefer high-confidence median (SOLVED only)
    # or scenario-based valuation as the primary reference.
    all_approximate = n_solved > 0 and n_approximate == n_solved
    median_weighted = getattr(agreement, "median_value_weighted", None)
    coverage_sufficient = getattr(agreement, "coverage_sufficient", True)
    quality_factor = getattr(agreement, "quality_factor", 1.0)
    n_not_applicable = getattr(agreement, "n_not_applicable", 0)
    agreement_level_raw = getattr(agreement, "agreement_level_raw", None)

    # Reference value = quality-weighted median (SOLVED=1.0, APPROXIMATE=0.5,
    # terminal-value-dominated DCF halved again). This prevents a single
    # low-confidence model from pulling the headline fair value.
    effective_median = median_weighted
    if effective_median is None:
        effective_median = median_high_conf if all_approximate else median
    median_is_weighted = median_weighted is not None and median is not None and abs(
        median_weighted - median
    ) > 1e-9

    # Shares basis reliability: if the provider share count / EPS basis is off
    # the internally derived value, any per-share figure is distorted.
    shares_unreliable = False
    rec = getattr(data, "reconciliation", None)
    if rec is not None and hasattr(rec, "has_mismatch"):
        try:
            shares_unreliable = any(
                rec.has_mismatch(k) for k in ("流通股数", "市值", "TTM EPS")
            )
        except Exception:
            shares_unreliable = False

    # Model coverage label
    if n_applicable <= 0:
        v.model_coverage_label = "无适用模型"
    elif n_solved >= n_applicable and n_solved >= 4:
        v.model_coverage_label = f"模型覆盖充分（{n_solved}/{n_applicable} 已解算）"
    elif n_solved >= max(1, n_applicable - 1) and n_solved >= 4:
        v.model_coverage_label = f"模型基本可用（{n_solved}/{n_applicable} 已解算）"
    elif n_solved == n_applicable:
        v.model_coverage_label = f"已解算但样本过少（{n_solved}/{n_applicable}，不足以给强结论）"
    else:
        v.model_coverage_label = f"模型覆盖不足（{n_solved}/{n_applicable} 已解算，方向性参考）"

    # Median vs Price headline
    med_short, med_sentence, med_headline, _spread = _vs_median_label(price, effective_median)
    v.median_vs_price_label = med_short
    v.median_vs_price_detail = med_sentence  # self-contained Chinese sentence (主语清晰)

    # Fair value range & label (honest: n + coverage, per-share basis caveat)
    if low is not None and high is not None:
        v.fair_value_estimate_range = (
            f"${low:.2f} ~ ${high:.2f}（样本 n={n_solved}，覆盖 {n_solved}/{n_applicable}）"
        )
        if shares_unreliable:
            # The re-check caliber must follow the engine's caliber contract: for
            # financials EV is declared NOT_MEANINGFUL, so advising "re-check via
            # EV" would contradict the same report's market section (it prints
            # "EV: N/M, 金融机构不适用"). UPST round3 caliber leak.
            from valuation.caliber import MetricMeaning, build_caliber_contract
            _cal = build_caliber_contract(profile)
            if _cal.meaning("EV") is MetricMeaning.NOT_MEANINGFUL:
                _recheck = "建议以 P/B、P/E、RIM（残差收益）口径复核"
            else:
                _recheck = "建议以 EV 口径复核"
            v.fair_value_estimate_label = (
                "⚠️ 每股估值基数不可靠（供应商股数 vs 年报偏差 >25%）→ 仅方向性参考，"
                + _recheck
            )
        elif price is not None and price > 0:
            if price > high:
                v.fair_value_estimate_label = "当前价已高于公允区间上限，偏贵"
            elif price < low:
                v.fair_value_estimate_label = "当前价低于公允区间下限，便宜"
            else:
                v.fair_value_estimate_label = "当前价落在公允估值区间内"
        else:
            v.fair_value_estimate_label = "公允区间"
        if not coverage_sufficient and not shares_unreliable:
            v.fair_value_estimate_label += "｜⚠️ 低覆盖：仅为低置信模型集成区间，非统计置信区间"

    # Scenario
    v.scenario_label, v.scenario_summary = _scenario_summary(scenarios, price)

    # Agreement-level qualifier
    agreement_level = getattr(agreement, "agreement_level", "Unknown")
    coverage_ok = coverage_sufficient
    agreement_txt = agreement_level
    if agreement_level_raw and agreement_level_raw != agreement_level:
        agreement_txt = f"{agreement_level}（原始 {agreement_level_raw}，已按覆盖率/质量降级）"
    reasoning_bits = []
    if coverage_ok:
        reasoning_bits.append(f"{v.model_coverage_label}，一致性 {agreement_txt}")
    else:
        reasoning_bits.append(
            f"{v.model_coverage_label}，一致性 {agreement_txt}"
            f"｜⚠️ 低覆盖（质量因子 {quality_factor:.2f}）：结论仅为方向性参考"
        )
    if v.median_vs_price_detail:
        reasoning_bits.append(v.median_vs_price_detail)
    if median_is_weighted:
        reasoning_bits.append("参考值已按模型质量加权（APPROXIMATE / 终值主导模型降权）")
    if low is not None and high is not None and median is not None and median > 0:
        spread = (high - low) / median * 100.0
        reasoning_bits.append(f"估值离散度 {spread:.1f}%（{agreement_level}）")
    v.reasoning = "；".join(reasoning_bits)

    # Final headline (combine all signals). Hard floor: <2 solved models → no call.
    if median is None or n_solved < 2:
        v.headline_label = "数据不足"
        v.headline_emoji = "⚪"
        v.headline_summary = "可用估值模型 < 2 个，不给出明确高估/低估结论（以上中位对比仅作参考）"
        _attach_math_audit(v, price, effective_median, scenarios, agreement)
        return v

    # Start with median-based label
    headline = med_headline
    emoji = valuation_emoji(med_headline)

    # Downgrade confidence if agreement level is Weak/Very Weak OR spread too large
    weak_agree = agreement_level in ("Weak", "Very Weak")
    very_weak_agree = agreement_level == "Very Weak"
    caveats: List[str] = []
    if very_weak_agree:
        caveats.append("模型分歧极大，需结合业务判断")
        emoji = "🟠"
    elif weak_agree:
        caveats.append("模型间存在一定分歧")

    # Material disagreement (core DCF removed by IQR, or DCF vs multiples point
    # in opposite directions) must be NAMED with the same wording the agreement
    # section uses — not softened into "一定分歧".
    if bool(getattr(agreement, "material_disagreement", False)):
        caveats.append(
            "⚠️ 模型分歧未解决（Material Disagreement）：核心 DCF 与倍数法方向不一致，"
            "中位估值不代表全体模型共识，需人工复核"
        )

    # Low-coverage gate: fewer than 4 solved models cannot support a strong call.
    if not coverage_sufficient:
        caveats.append(
            f"⚠️ 低覆盖（{n_solved}/{n_applicable} 模型解算，质量因子 {quality_factor:.2f}，"
            f"{n_not_applicable} 个不适用）→ 估值结论为**方向性参考**，非精确公允价"
        )

    # Shares-basis gate: per-share figures are distorted when the provider
    # share count disagrees with the latest filing by >25%.
    if shares_unreliable:
        caveats.append(
            "⚠️ 每股估值基数不可靠（供应商股数与年报偏差 >25%）→ 每股数值仅供参考"
        )

    # Scenario cross-check: even bull < price → strong overvaluation
    scenario_overrides_headline = False
    base_sv = None
    try:
        bsv = getattr(scenarios.get("Bull", None), "value_per_share", None) if scenarios else None
        brv = getattr(scenarios.get("Bear", None), "value_per_share", None) if scenarios else None
        base_sv = getattr(scenarios.get("Base", None), "value_per_share", None) if scenarios else None
        if price is not None and bsv is not None and brv is not None:
            if price > bsv and price > brv:
                # Even the bull case is below current price → strong overvaluation.
                # The gap is measured against the BULL SCENARIO value (base), and
                # the sentence must quote that same base — never re-anchor the
                # percentage on the current price ("乐观情景低于当前价 X%").
                bull_gap = pct_vs(price, bsv)
                if bull_gap is not None and bull_gap >= 0.50:
                    caveats.append(
                        "即使乐观情景也低于当前价："
                        f"{phrase_vs(price, bsv, subject='当前价', ref_name='乐观情景')}"
                        "（显著高估信号）"
                    )
                    # Force headline to reflect strong overvaluation
                    headline = "显著高估"
                    emoji = "🔴"
                    scenario_overrides_headline = True
                else:
                    caveats.append("即使乐观情景也达不到当前价（高估信号强）")
                    emoji = "🔴"
                    # Raise to at least "明显高估" if currently less severe
                    if headline in ("小幅高估", "估值合理"):
                        headline = "明显高估"
            elif price < bsv and price < brv:
                caveats.append("即使悲观情景也高于当前价（低估信号强）")
                emoji = "🟩"
    except Exception:
        pass

    # When scenario analysis strongly contradicts the median-based headline
    # (e.g. all scenarios >50% below price but median says "fair"),
    # add an explicit warning about the discrepancy.
    if not scenario_overrides_headline and base_sv is not None and price is not None:
        try:
            base_gap = pct_vs(price, base_sv)
            if base_gap is not None and base_gap >= 0.50 and headline in ("小幅高估", "估值合理"):
                caveats.append(
                    f"{phrase_vs(price, base_sv, subject='当前价', ref_name='DCF 基准情景')}，"
                    "与中位数结论存在显著分歧（中位数可能被极端值拉高）"
                )
        except Exception:
            pass

    # Median-vs-scenario SIGN conflict: the multi-model median and the DCF
    # scenario band can point in OPPOSITE directions. That is a genuine internal
    # contradiction — the same report calling the stock both heavily overvalued
    # (median) and undervalued (DCF base) — and it must be NAMED, not averaged
    # away. The systematic driver is DCF terminal-value domination (TV/EV far
    # above 100%), which the agreement layer already de-weights / IQR-removes;
    # the headline should say so instead of silently presenting both lenses.
    if price is not None and price > 0 and base_sv is not None and base_sv > 0:
        try:
            # Keep BOTH bases explicit: gap_vs_base anchors on the DCF base value,
            # gap_vs_price anchors on the market price. Each sentence quotes the
            # base it actually measured against (no base inversion).
            gap_vs_base = pct_vs(price, base_sv)
            median_overvalued = headline in ("显著高估", "明显高估", "小幅高估")
            median_cheap = headline in ("小幅低估", "明显低估", "显著低估")
            if median_overvalued and gap_vs_base is not None and gap_vs_base <= -0.25:
                caveats.append(
                    f"⚠️ 口径冲突：中位口径判「{med_headline.replace('**', '')}」，但 "
                    f"{phrase_vs(base_sv, price, subject='DCF 基准情景', ref_name='当前价')}"
                    "（DCF 反判低估）→ 两口径方向相反；系统性分歧多源于 DCF 终值主导"
                    "（TV/EV 过高）已被降权/剔除，此处不做平均"
                )
            elif median_cheap and gap_vs_base is not None and gap_vs_base >= 0.25:
                caveats.append(
                    f"⚠️ 口径冲突：中位口径判「{med_headline.replace('**', '')}」，但 "
                    f"{phrase_vs(base_sv, price, subject='DCF 基准情景', ref_name='当前价')}"
                    "（DCF 反判高估）→ 两口径方向相反；系统性分歧多源于 DCF 终值主导"
                    "已被降权/剔除，此处不做平均"
                )
        except Exception:
            pass

    # If reverse DCF is "Not Applicable" for non-financial → add note
    rev_status = getattr(implied, "reverse_dcf_status", None) if implied is not None else None
    is_fin = bool(getattr(profile, "is_financial_institution", False))
    if rev_status == "Not Applicable" and not is_fin:
        caveats.append("Reverse DCF 不可用（缺 operating_income）")

    # When all models are APPROXIMATE, add caveat and prefer scenario-based reference
    if all_approximate:
        caveats.append("全部已解算模型为 APPROXIMATE（peer 乘数未经行业验证），中位估值仅供参考")
        # If scenario base is available, mention it as the primary reference
        try:
            base_sv = getattr(scenarios.get("Base", None), "value_per_share", None) if scenarios else None
            if base_sv is not None:
                caveats.append(f"建议参考 DCF 情景基准 ${base_sv:.2f}")
        except Exception:
            pass

    v.headline_label = headline
    v.headline_emoji = emoji

    # Build headline_summary: one clean sentence + caveats (if any) joined with "｜"
    price_s = f"${price:.2f}" if price is not None else "N/A"
    med_s = f"${effective_median:.2f}" if effective_median is not None else "N/A"
    first = f"{emoji} 当前价 {price_s} {med_short.replace('**', '')}（中位估值 {med_s}）"
    if caveats:
        first += "｜" + "；".join(caveats)
    v.headline_summary = first
    # If we're clearly under-covered (2/4 models), append a caution even when not weak agreement
    if n_solved < n_applicable - 1 and not caveats:
        v.headline_summary += f"｜⚠️ {n_applicable - n_solved} 个模型失败未参与（需注意数据质量）"
    _attach_math_audit(v, price, effective_median, scenarios, agreement)
    return v


def _attach_math_audit(
    v: ValuationVerdictCard,
    price: Optional[float],
    median: Optional[float],
    scenarios: Dict[str, Any],
    agreement: Any,
) -> None:
    """Attach the Phase 1.5 report-math self-audit to the verdict card.

    Built from the exact facts rendered above, so a direction/base mismatch, a
    broken sample-count identity, or an illegal "strong agreement beside an
    IQR-excluded core model" surfaces as a flag in the report instead of
    silently reaching the reader. Never raises.
    """
    try:
        v.math_audit = audit_report_math(
            price=price,
            median=median,
            dcf_value=getattr(agreement, "dcf_value", None),
            scenarios=scenarios,
            agreement=agreement,
            card=v,
        )
    except Exception as e:  # pragma: no cover - audit must never break valuation
        log.debug(f"math audit failed: {e}")


__all__ = ["build_growth_verdict", "build_valuation_verdict",
           "_rev_cagr_label", "_fcf_cagr_label", "_change_label",
           "_vs_median_label", "_scenario_summary"]
