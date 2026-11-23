"""Classify how well NWC — and therefore growth direction — is actually known.

The point of this taxonomy is to make "we cannot tell" a *first-class*,
informative answer instead of a failure. Five states, in descending order of
evidential strength:

``NWC_DIRECT``
    Balance-sheet operating NWC is available across enough periods to compute a
    level ratio, and a robust marginal coefficient is estimable. The strongest
    state; a direction claim may be made if the robustness sweep agrees.

``NWC_ROBUST_MARGINAL``
    No usable balance-sheet series, but the year-over-year marginal coefficient
    is stable across median / Theil-Sen / Huber. A *conditional* direction may
    be given, explicitly resting on the marginal estimate. **The name records
    the estimator family, not the strength of the evidence**: three pairs is
    three observations whatever the statistic, so the history grade
    (``history_grade``) governs whether a direction claim is allowed at all.

``NWC_INTENSITY_PROXY``
    Only the investment-intensity proxy is available. Report the proxy with an
    interval; do not state a direction.

``NWC_ESTIMATE_CONFLICT``
    Two or more estimators disagree in sign, or by more than the tolerance. The
    honest answer is that the coefficient is not identified by the data.

``MECHANISM_UNCONFIRMED``
    Nothing beyond a single FCF-residual-derived number. No mechanism claim.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

NWC_DIRECT = "NWC_DIRECT"
NWC_ROBUST_MARGINAL = "NWC_ROBUST_MARGINAL"
NWC_INTENSITY_PROXY = "NWC_INTENSITY_PROXY"
NWC_ESTIMATE_CONFLICT = "NWC_ESTIMATE_CONFLICT"
MECHANISM_UNCONFIRMED = "MECHANISM_UNCONFIRMED"

#: Minimum balance-sheet periods before a level ratio counts as computable.
#: This is a *computability* floor, not an evidence grade — see
#: ``history_grade()`` for how much weight the series can actually bear.
MIN_LEVEL_PERIODS = 3
#: Minimum y/y pairs before a marginal coefficient is *computable*.
MIN_MARGINAL_PAIRS = 3
#: Below this many annual periods, no long-horizon claim is supportable.
RECOMMENDED_ANNUAL_YEARS = 5

# --- History-length grades: a DATA-QUALITY POLICY, not a statistical law ----
#
# This table is a *product decision* about how much history this engine will
# require before it will speak with confidence. It is **not** a result from
# statistics, and it must never be cited as one.
#
# Sample size is only a *proxy* for the things that actually threaten validity,
# and it is an imperfect one. Eight annual pairs can still be undermined by:
#   * a change of business mix or industry structure over the window;
#   * a change of accounting policy or of the XBRL tag mapping;
#   * acquisitions, disposals or restatements that break comparability;
#   * one or two anomalous years (a working-capital release, a deferred-revenue
#     shock) that dominate the estimate.
#
# Therefore ``MORE_ESTABLISHED`` means "this engine will treat it as the primary
# estimate", **not** "this has been shown to be correct". Every grade is
# published with :data:`GRADE_POLICY_NOTE` attached so a reader cannot mistake
# the policy for a proof.
GRADE_IS_POLICY = True

GRADE_POLICY_NOTE = (
    "证据等级是模型的**数据质量政策**，不是统计学定律：样本量只是有效性的"
    "近似代理，无法排除行业结构变化、会计口径变更、并购与异常年份。"
    "MORE_ESTABLISHED 表示「本引擎将其作为主要估计」，不表示「已被证明正确」"
)
HISTORY_INSUFFICIENT = "INSUFFICIENT"
HISTORY_INDICATIVE = "INDICATIVE"
HISTORY_PROVISIONAL = "PROVISIONAL"
HISTORY_MORE_ESTABLISHED = "MORE_ESTABLISHED"

#: Upper bound (inclusive) of y/y pairs for each grade.
HISTORY_GRADES = [
    (2, HISTORY_INSUFFICIENT),
    (4, HISTORY_INDICATIVE),
    (7, HISTORY_PROVISIONAL),
    (10 ** 6, HISTORY_MORE_ESTABLISHED),
]

HISTORY_GRADE_LABELS = {
    HISTORY_INSUFFICIENT: "样本不足（1–2 对）：不作任何边际估计",
    HISTORY_INDICATIVE: "指示性（3–4 对）：仅作方向性参考，非确立结论",
    HISTORY_PROVISIONAL: "暂定（5–7 对）：可用于建模，仍需外部验证",
    # Deliberately not "established": the policy grades usability, not truth.
    HISTORY_MORE_ESTABLISHED: "较可用（8+ 对）：本引擎作为主要估计，非已证明正确",
}

#: Grades at which an *established* direction claim is permitted.
DIRECTION_GRADES = (HISTORY_PROVISIONAL, HISTORY_MORE_ESTABLISHED)
#: Grades at which only an *indicative* direction may be stated — flagged as
#: such, never presented as established. Suppressing it entirely would discard
#: real (if weak) evidence; presenting it unqualified would overstate it.
INDICATIVE_DIRECTION_GRADES = (HISTORY_INDICATIVE,)


def history_grade(n_pairs: int) -> str:
    """Grade the evidence behind a marginal coefficient by sample size."""
    for upper, grade in HISTORY_GRADES:
        if n_pairs <= upper:
            return grade
    return HISTORY_MORE_ESTABLISHED

LABELS = {
    NWC_DIRECT: "直接财报营运资本（可给出正式边际 NWC）",
    NWC_ROBUST_MARGINAL: "稳健边际估计（可给出条件性方向判断）",
    NWC_INTENSITY_PROXY: "仅投资强度代理（仅提供代理估计及敏感性区间）",
    NWC_ESTIMATE_CONFLICT: "多法估计冲突（系数未被数据识别）",
    MECHANISM_UNCONFIRMED: "机制未证实（仅 FCF 残差，不作机制断言）",
}


def classify_nwc_confidence(
    reconciliation: Dict[str, Any],
    n_annual_periods: int,
    direction_robust: Optional[bool],
) -> Dict[str, Any]:
    """Return ``{kind, label, reason, can_claim_direction}``.

    ``direction_robust`` is the EV-direction sweep result under plausible NWC
    ratios: ``True`` stable, ``False`` flips, ``None`` not evaluated. A stable
    coefficient still cannot license a direction claim if the EV curve itself
    flips — those are two different instabilities.
    """
    grade = history_grade(n_annual_periods - 1 if n_annual_periods else 0)
    level = reconciliation.get("level") or {}
    intensity = reconciliation.get("intensity") or {}
    robust = reconciliation.get("robust_marginal") or {}
    conflict = bool(reconciliation.get("estimates_conflict"))

    level_n = int(level.get("n_observations") or 0)
    level_val = level.get("value")
    robust_n = int(robust.get("n_observations") or 0)
    robust_val = robust.get("value")
    intensity_val = intensity.get("value")

    if conflict:
        kind = NWC_ESTIMATE_CONFLICT
        reason = (
            "不同 NWC 估计方法给出相互冲突的边际系数"
            f"（spread={reconciliation.get('marginal_spread')}），"
            "因此系数未被数据识别，不得据此断言 EV 方向或归因机制"
        )
        can_claim = False
    elif level_val is not None and level_n >= MIN_LEVEL_PERIODS and robust_n >= MIN_MARGINAL_PAIRS:
        kind = NWC_DIRECT
        reason = (
            f"资产负债表营运资本比率可用（{level_n} 期）且稳健边际系数可估（{robust_n} 对）"
        )
        can_claim = bool(direction_robust)
    elif robust_val is not None and robust_n >= MIN_MARGINAL_PAIRS:
        kind = NWC_ROBUST_MARGINAL
        reason = (
            f"无可用资产负债表序列，但年度配对边际系数在 {robust_n} 对上稳健；"
            "方向判断须标注为条件性"
        )
        can_claim = bool(direction_robust)
    elif intensity_val is not None:
        kind = NWC_INTENSITY_PROXY
        reason = "仅有投资强度代理（ΔNWC/Revenue）；仅可给区间，不可给方向"
        can_claim = False
    else:
        kind = MECHANISM_UNCONFIRMED
        reason = "仅剩单一 FCF 残差来源，不足以支持任何机制断言"
        can_claim = False

    notes = []
    if n_annual_periods < RECOMMENDED_ANNUAL_YEARS:
        notes.append(
            f"年度数据仅 {n_annual_periods} 年（< {RECOMMENDED_ANNUAL_YEARS} 年）："
            f"证据等级 {grade}（{HISTORY_GRADE_LABELS[grade]}）"
        )
    if direction_robust is False and kind in (NWC_DIRECT, NWC_ROBUST_MARGINAL):
        notes.append("NWC 系数可估，但 EV 曲线方向随 NWC 假设翻转：仍不可断言方向")

    # Sample size, not estimator name, decides how strong a claim is licensed.
    claim_strength = "none"
    if can_claim:
        if grade in DIRECTION_GRADES:
            claim_strength = "established"
        elif grade in INDICATIVE_DIRECTION_GRADES:
            claim_strength = "indicative"
            notes.append(
                f"证据等级 {grade}（{HISTORY_GRADE_LABELS[grade]}）："
                "方向结论仅为指示性，不得表述为确立结论；"
                "算法稳健性不能弥补样本量不足"
            )
        else:
            can_claim = False
            notes.append(
                f"证据等级 {grade}（{HISTORY_GRADE_LABELS[grade]}）："
                "样本不足，不作任何方向结论"
            )

    return {
        "kind": kind,
        "label": LABELS[kind],
        "reason": reason,
        "can_claim_direction": can_claim,
        "n_annual_periods": n_annual_periods,
        "history_grade": grade,
        "history_grade_label": HISTORY_GRADE_LABELS[grade],
        # Carried in the payload so the policy framing cannot be lost when the
        # record is copied into a report, a table or a chat message.
        "grade_is_policy": GRADE_IS_POLICY,
        "grade_policy_note": GRADE_POLICY_NOTE,
        "claim_strength": claim_strength,
        "notes": notes,
    }


__all__ = [
    "DIRECTION_GRADES",
    "GRADE_IS_POLICY",
    "GRADE_POLICY_NOTE",
    "INDICATIVE_DIRECTION_GRADES",
    "HISTORY_GRADES",
    "HISTORY_GRADE_LABELS",
    "HISTORY_INDICATIVE",
    "HISTORY_INSUFFICIENT",
    "HISTORY_MORE_ESTABLISHED",
    "HISTORY_PROVISIONAL",
    "LABELS",
    "MECHANISM_UNCONFIRMED",
    "MIN_LEVEL_PERIODS",
    "MIN_MARGINAL_PAIRS",
    "NWC_DIRECT",
    "NWC_ESTIMATE_CONFLICT",
    "NWC_INTENSITY_PROXY",
    "NWC_ROBUST_MARGINAL",
    "RECOMMENDED_ANNUAL_YEARS",
    "classify_nwc_confidence",
    "history_grade",
]
