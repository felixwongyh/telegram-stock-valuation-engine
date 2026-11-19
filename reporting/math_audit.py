"""
reporting/math_audit.py — Report math & wording self-validation (Phase 1.5)

The report must never state a percentage whose direction or basis contradicts the
underlying numbers. The canonical failure is a *base inversion*:

    "当前价较乐观情景高 170.4%"   (correct — base = 乐观情景值)
    "乐观情景低于当前价 170%"     (WRONG  — same number, base silently swapped
                                  to the current price)

Both sentences quote the same magnitude, but only the first is honest: 170.4% is
measured against the *scenario* value, not the current price.

This module centralises:

  * ``pct_vs(value, ref)`` — the one signed relative difference, always anchored
    on an explicit ``ref`` so a number and its wording cannot drift apart;
  * ``phrase_vs(...)`` — a base-anchored Chinese sentence builder, so any caller
    that needs to *say* a percentage uses the same (base, value) pair that
    produced it;
  * ``audit_report_math(...)`` — a structured audit over the facts the report
    actually renders (price / median / DCF / scenario band / agreement sample
    counts) that flags a stated label whose direction contradicts the numbers,
    an illegal "strong agreement" beside an IQR-excluded core model, or a broken
    sample-count identity (raw = survivors + outliers).

Nothing here invents data; every check compares two values already produced by
the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("reporting.math_audit")


# ---------------------------------------------------------------------------
# Canonical valuation vocabulary
# ---------------------------------------------------------------------------
# ONE ladder shared by every renderer (dashboard per-model labels, verdict card
# headline, median-vs-price label) so the same economic statement is never
# phrased two different ways across sections (Phase 1.5 "统一措辞"). Keys are
# ``(price - fair) / fair``: positive ⇒ current price above fair ⇒ 高估.
VALUATION_LADDER: Tuple[Tuple[float, str, str], ...] = (
    (0.50, "显著高估", "🔴"),
    (0.20, "明显高估", "🔴"),
    (0.08, "小幅高估", "🟡"),
    (-0.08, "估值合理", "🟢"),
    (-0.20, "小幅低估", "🟢"),
    (-0.50, "明显低估", "🟩"),
    (float("-inf"), "显著低估", "🟩"),
)
VALUATION_EMOJI: Dict[str, str] = {label: emoji for _, label, emoji in VALUATION_LADDER}


def valuation_band(price_gap: Optional[float]) -> Tuple[str, str]:
    """Canonical ``(label, emoji)`` for ``(price - fair) / fair``."""
    if price_gap is None:
        return ("数据不足", "⚪")
    for threshold, label, emoji in VALUATION_LADDER:
        if price_gap >= threshold:
            return (label, emoji)
    return ("数据不足", "⚪")


def valuation_band_from_model_gap(model_gap: Optional[float]) -> Tuple[str, str]:
    """Same ladder keyed on ``(model - price) / price`` (positive ⇒ 低估)."""
    if model_gap is None:
        return ("", "")
    return valuation_band(-float(model_gap))


def valuation_emoji(label: Optional[str]) -> str:
    return VALUATION_EMOJI.get(str(label), "🟡")


# Agreement levels that assert confidence. A core model dropped by the IQR
# filter must never coexist with one of these (survivorship bias).
_STRONG_LEVELS = ("Very Strong", "Strong")

# Wording → implied direction. Order matters: LOW words are checked first so
# that "略便宜" (cheap) is not mis-read through any substring overlap.
_LOW_WORDS = ("低估", "偏低", "略便宜", "便宜", "折价")
_HIGH_WORDS = ("高估", "偏高", "略贵", "偏贵", "溢价")
_FAIR_WORDS = ("合理", "公允", "中性")


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct_vs(value: Any, ref: Any) -> Optional[float]:
    """Return the signed relative difference ``(value - ref) / ref``.

    Always anchored on ``ref`` so the base is explicit and cannot be silently
    swapped by a caller. ``None`` when either side is missing or ``ref == 0``.
    """
    v = _as_float(value)
    r = _as_float(ref)
    if v is None or r is None or r == 0:
        return None
    return (v - r) / r


def phrase_vs(
    value: Any,
    ref: Any,
    *,
    subject: str = "当前价",
    ref_name: str = "参考值",
) -> str:
    """Base-anchored Chinese sentence for ``value`` relative to ``ref``.

    The subject is compared *against* ``ref_name`` and the percentage is
    measured relative to ``ref`` — the same base the number came from. A
    positive difference is always worded "高出 X%", never "低于 X%".
    """
    p = pct_vs(value, ref)
    v = _as_float(value)
    r = _as_float(ref)
    if p is None or v is None or r is None:
        return f"{subject}或{ref_name}缺失，无法比较"
    subj = f"{subject} ${v:,.2f}"
    referee = f"{ref_name} ${r:,.2f}"
    if p >= 0:
        return f"{subj} 较 {referee} **高出 {abs(p) * 100:.1f}%**"
    return f"{subj} 较 {referee} **低 {abs(p) * 100:.1f}%**"


def stated_direction(label: Optional[str]) -> Optional[str]:
    """Infer the direction a qualitative label asserts: high/low/fair/None."""
    if not label:
        return None
    s = str(label)
    for w in _LOW_WORDS:
        if w in s:
            return "low"
    for w in _HIGH_WORDS:
        if w in s:
            return "high"
    for w in _FAIR_WORDS:
        if w in s:
            return "fair"
    return None


@dataclass
class MathCheck:
    """One auditable consistency line."""

    label: str
    status: str          # "ok" | "flag" | "info"
    detail: str


@dataclass
class ReportMathAudit:
    checks: List[MathCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == "flag" for c in self.checks)

    @property
    def n_flag(self) -> int:
        return sum(1 for c in self.checks if c.status == "flag")

    @property
    def n_ok(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")


def _check_direction(
    label: str,
    stated: Optional[str],
    price: Optional[float],
    ref: Optional[float],
    ref_name: str,
) -> MathCheck:
    """Compare a qualitative label's direction with the real (price, ref) sign."""
    p = pct_vs(price, ref)
    if stated is None or p is None:
        return MathCheck(label, "info", "方向无法校验（标签或数值缺失）")
    if stated == "high" and p < 0:
        return MathCheck(
            label, "flag",
            f"措辞暗示当前价高于{ref_name}，但当前价 ${price:,.2f} 实际**低**于 "
            f"{ref_name} ${ref:,.2f}（{p*100:+.1f}%）；百分比方向与基准不一致",
        )
    if stated == "low" and p > 0:
        return MathCheck(
            label, "flag",
            f"措辞暗示当前价低于{ref_name}，但当前价 ${price:,.2f} 实际**高**于 "
            f"{ref_name} ${ref:,.2f}（{p*100:+.1f}%）；百分比方向与基准不一致",
        )
    return MathCheck(
        label, "ok",
        f"当前价 vs {ref_name} 方向与措辞一致（{p*100:+.1f}%，基准 = {ref_name}）",
    )


def audit_report_math(
    *,
    price: Any = None,
    median: Any = None,
    dcf_value: Any = None,
    scenarios: Optional[Dict[str, Any]] = None,
    agreement: Any = None,
    card: Any = None,
) -> ReportMathAudit:
    """Audit the report's stated numbers/labels against the underlying facts.

    Returns a :class:`ReportMathAudit`; ``ok`` is False when any check flags.
    """
    checks: List[MathCheck] = []
    price_f = _as_float(price)
    median_f = _as_float(median)

    # 1) Stated median-vs-price label must agree with sign(price - median).
    if card is not None:
        checks.append(_check_direction(
            "中位对比方向",
            stated_direction(getattr(card, "median_vs_price_label", None)),
            price_f, median_f, "中位估值",
        ))
        # 2) Headline must not contradict the median direction either.
        checks.append(_check_direction(
            "总判定方向",
            stated_direction(getattr(card, "headline_label", None)),
            price_f, median_f, "中位估值",
        ))

    # 3) DCF direction (base = DCF point value).
    dcf_f = _as_float(dcf_value)
    if dcf_f is not None and price_f is not None:
        p = pct_vs(price_f, dcf_f)
        checks.append(MathCheck(
            "DCF 方向",
            "ok" if p is not None else "info",
            f"当前价 ${price_f:,.2f} vs DCF ${dcf_f:,.2f}（{p*100:+.1f}%，基准 = DCF）"
            if p is not None else "DCF 数值缺失",
        ))

    # 4) Scenario ordering: Bull >= Base >= Bear (band must be monotone).
    if scenarios:
        bv = _as_float(getattr(scenarios.get("Bear"), "value_per_share", None))
        sv = _as_float(getattr(scenarios.get("Base"), "value_per_share", None))
        uv = _as_float(getattr(scenarios.get("Bull"), "value_per_share", None))
        if bv is not None and sv is not None and uv is not None:
            if not (uv >= sv >= bv):
                checks.append(MathCheck(
                    "情景区间单调性", "flag",
                    f"情景档位非单调：Bear ${bv:,.2f} · Base ${sv:,.2f} · Bull ${uv:,.2f}",
                ))
            else:
                checks.append(MathCheck(
                    "情景区间单调性", "ok",
                    f"Bear ${bv:,.2f} ≤ Base ${sv:,.2f} ≤ Bull ${uv:,.2f}（相对基准 = Base）",
                ))

    # 5) Agreement sample identity + core-model exclusion honesty.
    if agreement is not None:
        raw = getattr(agreement, "raw_solved_count", None)
        out = getattr(agreement, "outlier_count", None)
        eff = getattr(agreement, "effective_aggregation_count", None)
        # Not every solved model can enter the median: a per-share denominator
        # that is not comparable with the reference, and a declared data caliber
        # that conflicts with it, both remove a model before the IQR filter runs.
        # Omitting those two channels made a fully explained pool look
        # self-contradictory (VST: 5 solved = 2 median + 0 IQR, with the missing
        # 3 sitting in share-incomparable and comparability exclusions).
        share_out = len(getattr(agreement, "share_count_excluded_models", None) or [])
        comp_out = len(getattr(agreement, "comparability_excluded_models", None) or [])
        if raw is not None and out is not None and eff is not None:
            explained = eff + out + share_out + comp_out
            if explained == raw:
                checks.append(MathCheck(
                    "样本口径恒等式", "ok",
                    f"原始成功 {raw} = 最终参与 {eff} + IQR 排除 {out}"
                    f" + 股数不可比 {share_out} + 口径不可比 {comp_out}",
                ))
            else:
                checks.append(MathCheck(
                    "样本口径恒等式", "flag",
                    f"样本口径不自洽：原始成功 {raw} ≠ 最终参与 {eff} + IQR 排除 {out}"
                    f" + 股数不可比 {share_out} + 口径不可比 {comp_out}（合计 {explained}）",
                ))
        lvl = str(getattr(agreement, "agreement_level", "") or "")
        if getattr(agreement, "core_model_excluded", False) and any(
            s in lvl for s in _STRONG_LEVELS
        ):
            checks.append(MathCheck(
                "核心模型排除一致性", "flag",
                f"核心模型被 IQR 排除，但一致性仍标为「{lvl}」——"
                "剔除分歧者后不得声称强一致性（幸存者偏差）",
            ))
        elif getattr(agreement, "core_model_excluded", False):
            checks.append(MathCheck(
                "核心模型排除一致性", "ok",
                f"核心模型被 IQR 排除，一致性 `{lvl or 'N/A'}` 未声称强共识",
            ))

    return ReportMathAudit(checks=checks)


__all__ = [
    "MathCheck",
    "ReportMathAudit",
    "audit_report_math",
    "pct_vs",
    "phrase_vs",
    "stated_direction",
    "valuation_band",
    "valuation_band_from_model_gap",
    "valuation_emoji",
    "VALUATION_LADDER",
]
