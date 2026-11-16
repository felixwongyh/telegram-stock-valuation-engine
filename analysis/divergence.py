"""
analysis/divergence.py — DCF vs peer-multiple divergence diagnostics (Phase 1.2)

When the forecast-driven DCF and the peer-multiple cluster disagree materially,
the IQR pruning layer MUST NOT be allowed to *hide* the disagreement. Dropping
the DCF and then reporting a tight survivor cluster as "Very Strong" is
survivorship bias, not evidence of reliability.

This module builds a structured, auditable diagnostic that describes WHERE the
two sides diverge — without presuming which side is correct:

  * WACC level            — is the discount rate out of its industry sanity band?
  * terminal-value weight — how much of the DCF rests on the terminal assumption?
  * FCF-margin alignment  — is the forecast FCF margin disconnected from the
                            TTM / historical FCF margin?
  * forecast assumptions  — revenue CAGR / operating margin / capex ratio vs
                            their own historical anchors.
  * peer fit              — is the multiple based on an archetype we are confident
                            about, or an ambiguous / fallback peer bucket?

Nothing here invents data: every number is read from the DCF breakdown, the TTM
statement, the engine's own base forecast, the classifier output, or the
agreement object. Every check carries a ``status`` so the report can render the
reasoning verbatim instead of a hidden statistic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from analysis.threshold_calibration import DEFAULT_CALIBRATION, calibration_for
from config import get_logger, resolve_forecast_horizon

log = get_logger("analysis.divergence")


# DCF-family model names whose removal is a material event (mirrors
# analysis.model_agreement._CORE_MODELS).
_CORE_MODELS: set = {"DCF", "dcf", "DCF "}
# Display-only / circular models that are never part of either leg.
_EXCLUDED_FROM_MEDIAN: set = {"ReverseDCF", "reverse_dcf", "Reverse DCF"}

# A relative gap of this size (or more) between the raw DCF and the peer-multiple
# cluster counts as a *material* divergence that must be surfaced.
MATERIAL_GAP = 0.30
# The raw DCF is also treated as divergent if it falls outside the peer range
# widened by this fraction on each side (guards n=2 peer clusters).
_RANGE_SLACK = 0.20

_STATUS_FLAG = "flag"
_STATUS_INFO = "info"
_STATUS_ALIGNED = "aligned"
_STATUS_MODERATE = "moderate"

# ---------------------------------------------------------------------------
# FCF-margin divergence bands (Phase A — FCF Normalization + Diagnostic).
#
# The old check flagged only when the ABSOLUTE forecast-vs-TTM FCF-margin gap
# reached 15pp, so a 4.2% → 13.7% forecast (+9.5pp, a >3× multiple) was wrongly
# reported as ALIGNED. Margin levels are small, so a *relative* change matters:
# a forecast FCF margin that is 2× the TTM margin is a material extrapolation
# even when the absolute gap is modest.
#
# M-67 — these are now only the *default* (moderate-tier) bands. The live check
# resolves its band per business archetype via `threshold_calibration`, because
# a 5pp swing means something different for a regulated utility than for a
# high-capex semiconductor. The constants are kept (derived from the default
# calibration) so any legacy importer still sees the base band.
# ---------------------------------------------------------------------------
FCF_MARGIN_ALIGNED_PP: float = DEFAULT_CALIBRATION.fcf_aligned_pp   # |Δ| < 3pp  → aligned
FCF_MARGIN_FLAG_PP: float = DEFAULT_CALIBRATION.fcf_flag_pp         # |Δ| >= 5pp → flag (3–5pp = moderate)
FCF_MARGIN_HIGH_RATIO: float = DEFAULT_CALIBRATION.fcf_high_ratio   # forecast > 2× TTM margin → material


@dataclass
class DivergenceCheck:
    """One auditable diagnostic line."""

    label: str
    status: str          # "flag" | "info" | "aligned"
    detail: str


@dataclass
class DivergenceDiagnostic:
    triggered: bool = False
    summary: str = ""
    # Raw DCF vs peer cluster (pre-IQR; the numbers the reader must see).
    dcf_value: Optional[float] = None
    peer_median: Optional[float] = None
    peer_low: Optional[float] = None
    peer_high: Optional[float] = None
    peer_models: List[str] = field(default_factory=list)
    gap_pct: Optional[float] = None           # (dcf - peer_median) / peer_median
    core_model_excluded: bool = False
    checks: List[DivergenceCheck] = field(default_factory=list)
    # Explicit non-presumption: the report must not declare a winner.
    verdict: str = (
        "本诊断不预设 DCF 或倍数法哪一方正确；"
        "两侧差异应由使用者结合假设来源判断，不得用 IQR 剔除分歧者来掩盖。"
    )


def _fmt_pct(x: Optional[float], nd: int = 1) -> str:
    if x is None:
        return "N/A"
    try:
        return f"{float(x)*100:,.{nd}f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_share(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _split_legs(
    model_results: Dict[str, Any],
) -> Tuple[Optional[float], Dict[str, float]]:
    """Return (raw DCF per-share value, {peer model → value}) from solved results."""
    dcf_value: Optional[float] = None
    peers: Dict[str, float] = {}
    for name, r in (model_results or {}).items():
        if not getattr(r, "is_success", lambda: False)():
            continue
        v = getattr(r, "value_per_share", None)
        if v is None:
            continue
        if name in _EXCLUDED_FROM_MEDIAN:
            continue
        if name in _CORE_MODELS:
            if dcf_value is None:
                dcf_value = float(v)
            continue
        peers[name] = float(v)
    return dcf_value, peers


def _forecast_fcf_margin(data: Any, profile: Any) -> Optional[float]:
    """Engine base-case last-year FCF margin (revenue probe), or ``None``."""
    try:
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile
        from config import ScenarioType

        bt = business_type_from_profile(profile)
        eng = ForecastEngine(
            horizon_years=resolve_forecast_horizon(bt), business_type=bt,
        )
        periods = eng.build_all(data).get(ScenarioType.BASE, [])
        if periods:
            last_rev = getattr(periods[-1], "revenue", None)
            last_fcf = getattr(periods[-1], "free_cash_flow", None)
            if last_rev and last_rev > 0 and last_fcf is not None:
                return float(last_fcf) / float(last_rev)
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"forecast FCF margin probe failed: {e}")
    return None


def _calibration_for_profile(profile: Any):
    """Archetype-calibrated FCF-margin bands (M-67).

    Resolves the company's business archetype so the diagnostic band tracks the
    archetype's own volatility rather than one global constant. Falls back to the
    default (moderate) band for an unknown archetype — nothing is silently
    re-graded.
    """
    from forecasts.nwc_utils import business_type_from_profile

    return calibration_for(business_type_from_profile(profile))


def _fcf_margin_check(data: Any, profile: Any, dcf_bd: Optional[Dict[str, Any]]) -> DivergenceCheck:
    """Compare the engine's forecast FCF margin with the TTM / historical margin.

    Phase A made the trigger *relative* (2× TTM / ≥5pp gap / sign flip) instead
    of a 15pp absolute gap. M-67 then calibrates the band per business archetype,
    so a stable utility is judged on a tighter band than a volatile
    semiconductor — and the chosen band is printed in the audit line.
    """
    ttm = getattr(data, "ttm", None)
    ttm_rev = getattr(ttm, "revenue", None) if ttm is not None else None
    ttm_fcf = getattr(ttm, "free_cash_flow", None) if ttm is not None else None
    if not ttm_rev or ttm_rev <= 0 or ttm_fcf is None:
        return DivergenceCheck(
            "FCF 预测 vs TTM/历史", _STATUS_INFO,
            "TTM 营收或 FCF 缺失，无法对账预测 FCF margin（未做假设）。",
        )
    ttm_margin = float(ttm_fcf) / float(ttm_rev)
    cal = _calibration_for_profile(profile)

    forecast_margin = _forecast_fcf_margin(data, profile)
    if forecast_margin is None:
        fcf_list = (dcf_bd or {}).get("forecast_fcf") or []
        if fcf_list:
            return DivergenceCheck(
                "FCF 预测 vs TTM/历史", _STATUS_INFO,
                f"预测期 FCF 序列可得（首年 {_fmt_share(fcf_list[0])}），"
                f"但缺末年被除数，未推断 margin；TTM FCF margin {_fmt_pct(ttm_margin)}。",
            )
        return DivergenceCheck(
            "FCF 预测 vs TTM/历史", _STATUS_INFO,
            f"预测 FCF 序列不可得；TTM FCF margin {_fmt_pct(ttm_margin)}。",
        )

    delta = forecast_margin - ttm_margin
    abs_d = abs(delta)
    sign_flip = (forecast_margin < 0) != (ttm_margin < 0)
    rel = (forecast_margin / ttm_margin - 1.0) if ttm_margin > 0 else None
    high_multiple = ttm_margin > 0 and forecast_margin > ttm_margin * cal.fcf_high_ratio
    rel_txt = f"，相对 TTM {rel*100:+.0f}%" if rel is not None else ""
    base = (
        f"预测末年 FCF margin {_fmt_pct(forecast_margin)} vs TTM {_fmt_pct(ttm_margin)}"
        f"（差异 {delta*100:+.1f}pp{rel_txt}"
        f"{'，且符号翻转' if sign_flip else ''}）"
    )
    big_txt = (
        f"；预测 FCF margin 超过 TTM {cal.fcf_high_ratio:.2f} 倍，属重大变化"
        if high_multiple else ""
    )
    cal_txt = f"〔{cal.note()}〕"

    if sign_flip or abs_d >= cal.fcf_flag_pp or high_multiple:
        return DivergenceCheck(
            "FCF 预测 vs TTM/历史", _STATUS_FLAG,
            base + big_txt + "→ 预测自由现金流与历史变现能力脱节，DCF 点值对该外推假设敏感。"
            + cal_txt,
        )
    if abs_d >= cal.fcf_aligned_pp:
        return DivergenceCheck(
            "FCF 预测 vs TTM/历史", _STATUS_MODERATE,
            base + big_txt + "→ 中等偏离：预测 FCF margin 相对历史锚有可见抬升，建议核对假设。"
            + cal_txt,
        )
    return DivergenceCheck(
        "FCF 预测 vs TTM/历史", _STATUS_ALIGNED,
        base + "基本一致。" + cal_txt,
    )


def _fcf_normalization_layer(data: Any, profile: Any) -> Optional[DivergenceCheck]:
    """TTM vs 3–5y historical normalisation comparison (Phase A).

    Compares the latest TTM cost structure with the historical anchors so a
    *temporary capex cycle* can be distinguished from a *structural* operating-
    cash deterioration. Reads reported figures only — the historical average is
    never treated as "the future normal".
    """
    ttm = getattr(data, "ttm", None)
    if ttm is None or not getattr(ttm, "revenue", None) or ttm.revenue <= 0:
        return None
    rev = float(ttm.revenue)

    def _r(v: Any) -> Optional[float]:
        return (float(v) / rev) if v is not None else None

    ttm_capex = _r(abs(ttm.capex)) if getattr(ttm, "capex", None) is not None else None
    ttm_da = _r(getattr(ttm, "depreciation_amortization", None))
    ttm_nwc = _r(getattr(ttm, "change_in_nwc", None))
    ttm_fcf_m = _r(getattr(ttm, "free_cash_flow", None))

    hist_capex = hist_da = hist_nwc = None
    hist_fcf_m: Optional[float] = None
    try:
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        bt = business_type_from_profile(profile)
        eng = ForecastEngine(
            horizon_years=resolve_forecast_horizon(bt), business_type=bt,
        )
        _cagr, _gm, hist_om, hist_da, hist_capex, hist_nwc, hist_tax = eng._extract_history(data)
        hist_fcf_m = hist_om * (1.0 - hist_tax) + hist_da - hist_capex - hist_nwc
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"FCF normalisation probe failed: {e}")
    if hist_fcf_m is None:
        return None

    detail = "；".join([
        f"TTM CapEx/收入 {_fmt_pct(ttm_capex)} vs 历史均值 {_fmt_pct(hist_capex)}",
        f"TTM D&A/收入 {_fmt_pct(ttm_da)}",
        f"TTM ΔNWC/收入 {_fmt_pct(ttm_nwc)}",
        f"TTM FCF margin {_fmt_pct(ttm_fcf_m)} vs 历史正常化 {_fmt_pct(hist_fcf_m)}",
    ])

    status = _STATUS_INFO
    verdict = ""
    if ttm_fcf_m is not None and ttm_fcf_m < hist_fcf_m:
        capex_driven = (
            ttm_capex is not None and hist_capex is not None
            and hist_capex > 0 and ttm_capex > hist_capex * 1.3
        )
        if capex_driven:
            status = _STATUS_MODERATE
            verdict = (
                "→ 当前 FCF 走弱伴随 CapEx/收入 明显高于历史，更可能是暂态资本开支周期；"
                "历史均值不得直接当作未来正常值。"
            )
        else:
            status = _STATUS_FLAG
            verdict = (
                "→ FCF 走弱未见 CapEx 抬升解释，更可能反映经营现金流能力变化，"
                "历史均值不可直接外推为未来正常值。"
            )
    return DivergenceCheck("TTM vs 历史正常化", status, detail + verdict)


def _forecast_assumption_checks(data: Any, profile: Any) -> List[DivergenceCheck]:
    """Revenue CAGR / operating margin / capex ratio vs their historical anchors."""
    out: List[DivergenceCheck] = []
    ttm = getattr(data, "ttm", None)
    if ttm is None or not getattr(ttm, "revenue", None):
        return out
    try:
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile
        from config import ScenarioType

        bt = business_type_from_profile(profile)
        eng = ForecastEngine(
            horizon_years=resolve_forecast_horizon(bt), business_type=bt,
        )
        hist_cagr, hist_gm, hist_om, hist_da, hist_capex, _, _ = eng._extract_history(data)
        periods = eng.build_all(data).get(ScenarioType.BASE, [])
        if not periods:
            return out
        y1 = periods[0]
        fc_cagr = getattr(y1, "revenue_growth", None)
        fc_om = getattr(y1, "operating_margin", None)
        # Capex ratio from the engine's own base forecast (capex / revenue).
        fc_capex_ratio = None
        rev = getattr(y1, "revenue", None)
        capex = getattr(y1, "capex", None)
        if rev and rev > 0 and capex is not None:
            fc_capex_ratio = abs(float(capex)) / float(rev)

        if fc_cagr is not None:
            d = fc_cagr - hist_cagr
            out.append(DivergenceCheck(
                "营收 CAGR 预测 vs 历史", _STATUS_FLAG if abs(d) >= 0.10 else _STATUS_ALIGNED,
                f"基准首年增速 {_fmt_pct(fc_cagr)} vs 历史 CAGR {_fmt_pct(hist_cagr)}"
                f"（差异 {d*100:+.1f}pp）。",
            ))
        ttm_om = None
        if getattr(ttm, "operating_income", None) is not None and ttm.revenue > 0:
            ttm_om = float(ttm.operating_income) / float(ttm.revenue)
        if fc_om is not None and ttm_om is not None:
            d_om = fc_om - ttm_om
            out.append(DivergenceCheck(
                "营业利润率 预测 vs TTM", _STATUS_FLAG if abs(d_om) >= 0.10 else _STATUS_ALIGNED,
                f"基准首年 OM {_fmt_pct(fc_om)} vs TTM OM {_fmt_pct(ttm_om)}"
                f"（差异 {d_om*100:+.1f}pp）。",
            ))
        if fc_capex_ratio is not None:
            d_cx = fc_capex_ratio - hist_capex
            out.append(DivergenceCheck(
                "CapEx/收入 预测 vs 历史", _STATUS_FLAG if abs(d_cx) >= 0.10 else _STATUS_ALIGNED,
                f"基准 CapEx/收入 {_fmt_pct(fc_capex_ratio)} vs 历史均值 {_fmt_pct(hist_capex)}"
                f"（差异 {d_cx*100:+.1f}pp）。",
            ))
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"forecast assumption probe failed: {e}")
    return out


def _wacc_check(dcf_bd: Optional[Dict[str, Any]], peers: Dict[str, float]) -> DivergenceCheck:
    if not dcf_bd:
        return DivergenceCheck("WACC 水平", _STATUS_INFO, "无 DCF breakdown，无法核对 WACC。")
    wacc = dcf_bd.get("wacc")
    ir = dcf_bd.get("industry_range")
    status = str(dcf_bd.get("sanity_status") or "")
    if wacc is None:
        return DivergenceCheck("WACC 水平", _STATUS_INFO, "WACC 缺失。")
    out_of_range = False
    band_txt = ""
    if ir:
        lo, hi, lbl = ir[0], ir[1], ir[2]
        band_txt = f"，行业 sanity 区间 [{_fmt_pct(lo)} ~ {_fmt_pct(hi)}]（{lbl}）"
        out_of_range = (wacc < lo or wacc > hi)
    status_up = status.upper()
    if out_of_range or "ABOVE" in status_up or "BELOW" in status_up or "OUT" in status_up:
        return DivergenceCheck(
            "WACC 水平", _STATUS_FLAG,
            f"WACC={_fmt_pct(wacc, 2)}{band_txt}，sanity_status=`{status or 'N/A'}`"
            "→ 折现率可能偏高/偏低，DCF 点值对该参数高度敏感。",
        )
    return DivergenceCheck(
        "WACC 水平", _STATUS_ALIGNED,
        f"WACC={_fmt_pct(wacc, 2)}{band_txt}，sanity_status=`{status or 'N/A'}`。",
    )


def _tv_check(dcf_bd: Optional[Dict[str, Any]]) -> DivergenceCheck:
    """Terminal-value weight diagnostic (Phase B).

    The report *wording* is graded separately from the risk-severity threshold:
    a 73.9% TV/EV must read as "high terminal-value dependence", never "explicit
    period dominates". The risk flag still fires only at the extreme (≥80%).
    """
    if not dcf_bd:
        return DivergenceCheck("终值依赖 (TV/EV)", _STATUS_INFO, "无 DCF breakdown。")
    tv_pct = dcf_bd.get("tv_percent_of_ev")
    if tv_pct is None:
        return DivergenceCheck("终值依赖 (TV/EV)", _STATUS_INFO, "TV/EV 缺失。")
    explicit = 1.0 - float(tv_pct)
    pct = f"TV/EV = {tv_pct:.1%}（显式期贡献 {explicit:.1%}）"
    neg_term = bool(dcf_bd.get("terminal_fcf_negative"))
    if neg_term:
        return DivergenceCheck(
            "终值依赖 (TV/EV)", _STATUS_FLAG,
            f"{pct}；终期 FCF ≤ 0（终值已被抑制）→ DCF 点值主要由显式期与受损终值决定，"
            "可与倍数法产生系统性分歧。",
        )
    if tv_pct >= 0.80:
        return DivergenceCheck(
            "终值依赖 (TV/EV)", _STATUS_FLAG,
            f"{pct} → 极高终值依赖，触发风险警告：DCF 点值几乎完全由终值假设决定。",
        )
    if tv_pct >= 0.70:
        return DivergenceCheck(
            "终值依赖 (TV/EV)", _STATUS_MODERATE,
            f"{pct} → 高终值依赖，需要审查：终值贡献占多数，DCF 点值对终端假设敏感。",
        )
    if tv_pct >= 0.50:
        return DivergenceCheck(
            "终值依赖 (TV/EV)", _STATUS_INFO,
            f"{pct} → 终值贡献占多数。",
        )
    return DivergenceCheck(
        "终值依赖 (TV/EV)", _STATUS_ALIGNED,
        f"{pct} → 显式预测期贡献占多数。",
    )


def _peer_fit_check(profile: Any, agreement: Any) -> DivergenceCheck:
    cls_status = getattr(profile, "classification_status", "confident") if profile else "confident"
    if cls_status and cls_status != "confident":
        return DivergenceCheck(
            "Peer 适配性", _STATUS_FLAG,
            f"分类状态 = `{cls_status}`：倍数法使用的 peer 原型可能不匹配公司身份，"
            "倍数法的可靠性因此下降（并非 DCF 一定正确）。",
        )
    n_na = getattr(agreement, "n_not_applicable", 0) if agreement is not None else 0
    if n_na:
        return DivergenceCheck(
            "Peer 适配性", _STATUS_INFO,
            f"有 {n_na} 个倍数模型因数据不足而不适用；适配性未确认。",
        )
    return DivergenceCheck(
        "Peer 适配性", _STATUS_ALIGNED, "分类明确，倍数法 peer 原型与业务身份一致。"
    )


def diagnose_dcf_vs_multiples(
    model_results: Dict[str, Any],
    data: Any = None,
    agreement: Any = None,
    profile: Any = None,
) -> DivergenceDiagnostic:
    """Build the structured DCF-vs-multiple divergence diagnostic.

    Always returns a diagnostic object; ``triggered`` is False when the two legs
    are close enough that no forced diagnostic is required.
    """
    d = DivergenceDiagnostic()
    dcf_value, peers = _split_legs(model_results or {})
    d.dcf_value = dcf_value
    d.peer_models = sorted(peers)
    if peers:
        pv = list(peers.values())
        d.peer_median = median(pv)
        d.peer_low = min(pv)
        d.peer_high = max(pv)
    d.core_model_excluded = bool(getattr(agreement, "core_model_excluded", False))

    if dcf_value is None or d.peer_median is None or d.peer_median <= 0:
        d.summary = "DCF 或倍数法缺一，无法构成分歧诊断。"
        return d

    d.gap_pct = (dcf_value - d.peer_median) / d.peer_median
    outside_range = False
    if d.peer_low is not None and d.peer_high is not None:
        lo = d.peer_low * (1 - _RANGE_SLACK)
        hi = d.peer_high * (1 + _RANGE_SLACK)
        outside_range = dcf_value < lo or dcf_value > hi

    d.triggered = (
        abs(d.gap_pct) >= MATERIAL_GAP
        or outside_range
        or d.core_model_excluded
        or bool(getattr(agreement, "material_disagreement", False))
    )
    if not d.triggered:
        d.summary = (
            f"DCF {_fmt_share(dcf_value)} 与倍数法中位数 {_fmt_share(d.peer_median)} "
            f"（{d.gap_pct*100:+.1f}%）基本一致，未触发强制分歧诊断。"
        )
        return d

    d.summary = (
        f"DCF 点值 {_fmt_share(dcf_value)} vs 倍数法 ["
        f"{_fmt_share(d.peer_low)} ~ {_fmt_share(d.peer_high)}]，"
        f"中位 {_fmt_share(d.peer_median)}，偏离 {d.gap_pct*100:+.1f}%"
        + ("（核心模型被 IQR 排除）" if d.core_model_excluded else "")
    )

    dcf_bd = None
    r_dcf = (model_results or {}).get("DCF")
    if r_dcf is not None and getattr(r_dcf, "breakdown", None):
        dcf_bd = r_dcf.breakdown

    d.checks.append(_wacc_check(dcf_bd, peers))
    d.checks.append(_tv_check(dcf_bd))
    if data is not None:
        d.checks.append(_fcf_margin_check(data, profile, dcf_bd))
        d.checks.extend(_forecast_assumption_checks(data, profile))
        _norm = _fcf_normalization_layer(data, profile)
        if _norm is not None:
            d.checks.append(_norm)
    d.checks.append(_peer_fit_check(profile, agreement))
    return d


__all__ = [
    "DivergenceCheck",
    "DivergenceDiagnostic",
    "diagnose_dcf_vs_multiples",
    "MATERIAL_GAP",
    "FCF_MARGIN_ALIGNED_PP",
    "FCF_MARGIN_FLAG_PP",
    "FCF_MARGIN_HIGH_RATIO",
]
