"""Shadow-mode NWC diagnosis: report, never overwrite.

This assembles the three estimators, the derived growth-direction test, and the
confidence taxonomy into one per-ticker record. It runs *beside* the valuation
engine and writes nothing back into the projection, so the golden baseline and
every published number stay exactly as they were. The purpose is to see what a
better-founded NWC treatment *would* say before deciding to adopt it.

Deliberate non-behaviour: this module never picks a "best" NWC ratio. Picking
one is what produced the original defect — a single point estimate presented as
a mechanism.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.nwc_confidence import classify_nwc_confidence
from data.models import FinancialData
from data.nwc_utils import resolve_change_in_nwc
from config import resolve_forecast_horizon
from forecasts.fcf_projection import (
    dcf_path_inputs_from_data,
    dcf_projection_shape,
)
from forecasts.growth_direction import evaluate as evaluate_direction
from forecasts.nwc_estimators import (
    balance_sheet_nwc_ratio,
    nwc_investment_intensity,
    reconcile,
    robust_marginal_nwc,
)


def _revenue_map(data: FinancialData) -> Dict[str, float]:
    return {
        s.period_end: float(s.revenue)
        for s in data.annual_income
        if s.revenue is not None and s.revenue > 0
    }


def _dnwc_map(data: FinancialData) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for s in data.annual_income:
        v = resolve_change_in_nwc(s)
        if v is not None:
            out[s.period_end] = float(v)
    return out


def _revenue_cagr(data: FinancialData) -> Optional[float]:
    periods = [s for s in data.annual_income if s.revenue and s.revenue > 0]
    if len(periods) < 2:
        return None
    newest, oldest = periods[0].revenue, periods[-1].revenue
    if oldest <= 0 or newest <= 0:
        return None
    return (newest / oldest) ** (1 / (len(periods) - 1)) - 1


def diagnose(
    data: FinancialData,
    *,
    wacc: Optional[float] = None,
    terminal_growth: Optional[float] = None,
    horizon: Optional[int] = None,
    operating_margin: Optional[float] = None,
    tax_rate: Optional[float] = None,
    da_ratio: Optional[float] = None,
    capex_ratio: Optional[float] = None,
    direction_robust: Optional[bool] = None,
    margin_is_flat: bool = True,
) -> Dict[str, Any]:
    """Produce the per-ticker NWC diagnosis record.

    ``direction_robust`` comes from the engine's own EV-direction sweep; it is
    passed in rather than recomputed so the two never disagree.

    ``margin_is_flat`` defaults to True because the derived criterion's *sign*
    survives the engine's margin-fade convention away from the flip point
    (measured 18/21 across a 3x3 grid, with every disagreement on the boundary).
    The criterion guards the boundary itself via ``BOUNDARY_BAND``, so leaving
    this True does not license a sign claim where fade would change it.
    """
    rev = _revenue_map(data)
    dnwc = _dnwc_map(data)

    level = balance_sheet_nwc_ratio(data.annual_balance_sheet or [], rev)
    intensity = nwc_investment_intensity(dnwc, rev)
    series = [
        (s.period_end, float(s.revenue) if s.revenue is not None else None,
         resolve_change_in_nwc(s))
        for s in data.annual_income
    ]
    robust = robust_marginal_nwc(series)
    growth = _revenue_cagr(data)
    rec = reconcile(level, intensity, robust, growth)

    n_years = len(data.annual_income or [])
    confidence = classify_nwc_confidence(rec, n_years, direction_robust)

    direction_test = None
    if all(v is not None for v in (wacc, terminal_growth, horizon,
                                   operating_margin, tax_rate, da_ratio,
                                   capex_ratio)):
        direction_test = evaluate_direction(
            operating_margin=operating_margin,
            tax_rate=tax_rate,
            da_ratio=da_ratio,
            capex_ratio=capex_ratio,
            marginal_nwc=robust.value,
            wacc=wacc,
            terminal_growth=terminal_growth,
            horizon=horizon,
            margin_is_flat=margin_is_flat,
            # Supply a revenue scale so the module can report where the local
            # sign stops holding; dEV/dg is homogeneous of degree one in revenue.
            revenue0=float(data.annual_income[0].revenue)
            if data.annual_income and data.annual_income[0].revenue else None,
        ).as_dict()
        # The engine's own sweep is the stronger evidence: it varies NWC across
        # the whole plausible range instead of trusting one coefficient. If the
        # EV direction flips anywhere in that range, a verdict from the point
        # estimate is not a conclusion the data supports, so it is withdrawn
        # rather than printed next to the warning that contradicts it.
        if direction_robust is False and direction_test["verdict"] != "indeterminate":
            direction_test["verdict"] = "indeterminate"
            direction_test["applicable"] = False
            direction_test["growth_adds_value"] = None
            direction_test["reasons"].append(
                "引擎在合理 NWC 区间内的方向扫描显示 EV 方向翻转："
                "点估计给出的结论被撤销"
            )

    # The taxonomy is the single gate on direction claims. A verdict from the
    # discriminant must not survive if the confidence class says the coefficient
    # is unidentified — otherwise the report contradicts itself.
    if direction_test and not confidence["can_claim_direction"] \
            and direction_test["verdict"] != "indeterminate":
        direction_test["verdict"] = "indeterminate"
        direction_test["applicable"] = False
        direction_test["growth_adds_value"] = None
        direction_test["reasons"].append(
            f"可信度为 {confidence['kind']}：按分类学不得断言方向，结论撤销"
        )

    warnings: List[str] = []
    # The short-history warning is emitted once, by the taxonomy, together with
    # the resulting grade; repeating it here would triple-print the same fact.
    if level.value is None:
        warnings.append("资产负债表营运资本不可用（缺 AR/AP）")
    if direction_test and not direction_test["applicable"]:
        warnings.append(
            "派生判别式不适用：" + "；".join(direction_test["reasons"])
        )

    # Exposed so the sensitivity baseline can sweep the *same* projection the
    # engine runs, instead of reconstructing a look-alike.
    projection_params = None
    if all(v is not None for v in (wacc, terminal_growth, horizon,
                                   operating_margin, tax_rate, da_ratio,
                                   capex_ratio)) and data.annual_income \
            and data.annual_income[0].revenue:
        projection_params = {
            "revenue0": float(data.annual_income[0].revenue),
            "operating_margin": operating_margin,
            "tax_rate": tax_rate,
            "da_ratio": da_ratio,
            "capex_ratio": capex_ratio,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "horizon": horizon,
        }

    return {
        "ticker": data.ticker,
        "n_annual_periods": n_years,
        "estimators": rec,
        "confidence": confidence,
        "direction_test": direction_test,
        "projection_params": projection_params,
        "warnings": warnings,
    }


def projection_params_from_engine(
    data, profile, breakdown: dict,
) -> Optional[dict]:
    """Derive the projection inputs the engine itself uses for this ticker.

    Exposed so a caller (the NWC sensitivity baseline) can sweep the *same*
    projection rather than reconstructing a look-alike from guessed fields.
    Returns ``None`` when the engine did not produce a usable DCF path.
    """
    from forecasts.nwc_utils import business_type_from_profile

    horizon = resolve_forecast_horizon(business_type_from_profile(profile))
    inputs = dcf_path_inputs_from_data(data, profile, horizon)
    if inputs is None:
        return None
    _, _shape, _off, om_center = dcf_projection_shape(
        inputs.base_revenue, inputs.base_growth, inputs.base_margin, horizon
    )
    wacc = breakdown.get("wacc")
    tg = breakdown.get("terminal_growth")
    if wacc is None or tg is None:
        return None
    return {
        "revenue0": float(inputs.base_revenue),
        "operating_margin": om_center,
        "tax_rate": inputs.tax_rate,
        "da_ratio": inputs.da_ratio,
        "capex_ratio": abs(inputs.capex_ratio),
        "wacc": wacc,
        "terminal_growth": tg,
        "horizon": horizon,
    }


def _claim_suffix(conf: dict, dt: dict) -> str:
    """State how far the verdict may be pushed, and where it stops holding.

    A verdict rendered without its scope reads as unconditional. Two things
    limit it: the evidence grade (sample size, not estimator name) and the
    growth range over which the local sign survives.
    """
    strength = conf.get("claim_strength", "none")
    if dt.get("verdict") not in ("adds_value", "destroys_value"):
        return ""
    label = {
        "established": "（证据等级已足够支撑该方向结论）",
        "indicative": "（⚠️ 指示性结论：样本量不足，不可作为确立结论）",
    }.get(strength, "")
    scope = ""
    points = dt.get("flip_points") or []
    if len(points) > 1:
        scope = (
            " ｜ ⚠️ 扫描发现 %d 个翻转点（%s），EV 曲线非单调："
            "有效区间为 %s" % (
                len(points),
                "、".join(f"{p:.1%}" for p in points),
                "、".join(
                    f"[{a:.0%}, {b:.1%}]"
                    for a, b in (dt.get("valid_direction_intervals") or [])
                ) or "—",
            )
        )
    elif points:
        lo = dt.get("reference_growth", 0.0)
        hi = points[0]
        scope = (
            f" ｜ ⚠️ 仅在 g∈[{lo:.0%}, {hi:.1%}) 区间内成立，"
            f"g≳{hi:.1%} 后方向相反；不可外推为全区间结论"
        )
    return label + scope


def format_report(diag: Dict[str, Any]) -> str:
    """Human-readable block for one ticker."""
    est = diag["estimators"]
    conf = diag["confidence"]
    lv, it, rb = est["level"], est["intensity"], est["robust_marginal"]

    def _pct(v: Optional[float]) -> str:
        return "N/A" if v is None else f"{v:+.1%}"

    lines = [
        f"{diag['ticker']} — NWC 估计与增长方向诊断（Shadow Mode，未影响估值）",
        f"  可信度: {conf['kind']} — {conf['label']}",
        f"    理由: {conf['reason']}",
        "",
        "  三种 NWC 指标（经济含义不同，不可互换）:",
        f"    1. 资产负债表营运资本/收入 (level)      {_pct(lv['value'])}"
        f"  n={lv['n_observations']}",
        f"    2. 历史投资强度 ΔNWC/收入 (intensity)   {_pct(it['value'])}"
        f"  n={it['n_observations']}",
        f"    3. 稳健边际 ΔNWC/Δ收入 (marginal)       {_pct(rb['value'])}"
        f"  n={rb['n_observations']}  ← 模型系数",
        f"    强度代理换算边际 (÷增长率 {_pct(est['revenue_growth_used'])}):"
        f" {_pct(est['intensity_proxy_marginal'])}",
    ]
    if est.get("intensity_proxy_refused_reason"):
        lines.append(f"      · {est['intensity_proxy_refused_reason']}")
    lines += [
    ]
    if est.get("estimates_conflict"):
        lines.append(
            f"    ⚠️ 估计冲突：spread={est['marginal_spread']:.3f} — 系数未被数据识别"
        )
    dt = diag.get("direction_test")
    if dt:
        lines += [
            "",
            "  增长方向判别式 (k0/w vs P/D) — 作用域: 参考增长率处的局部导数:",
            f"    k0={dt['k0']:+.4f}  w={dt['marginal_nwc']:+.4f}"
            f"  k0/w={dt['k0_over_w']:+.3f}" if dt["k0_over_w"] is not None
            else f"    k0={dt['k0']:+.4f}  w={dt['marginal_nwc']:+.4f}  k0/w=N/A",
            f"    门槛 P/D={dt['hurdle_ratio']:.4f} (=1/久期 {dt['duration_years']:.2f}年)",
            {
                "adds_value": "    适用: 是  结论: 增长增加价值",
                "destroys_value": "    适用: 是  结论: 增长减少价值",
            }.get(dt.get("verdict"), "    适用: 否  结论: 不作答（判别式不适用或处于边界带）")
            + _claim_suffix(conf, dt),
        ]
        for r in dt["reasons"]:
            lines.append(f"      · {r}")
    for w in diag.get("warnings", []):
        lines.append(f"  ⚠️ {w}")
    for n in conf.get("notes", []):
        lines.append(f"  ⚠️ {n}")
    if conf.get("grade_is_policy") and conf.get("grade_policy_note"):
        lines.append(f"  ℹ️ {conf['grade_policy_note']}")
    return "\n".join(lines)


__all__ = ["diagnose", "format_report"]
