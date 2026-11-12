"""
analysis/model_agreement.py - Model Agreement & Valuation Spread

Coverage-aware model agreement
------------------------------
A small spread across a handful of *surviving* models is NOT evidence of
reliability — it can be pure survivorship bias. If 4 of 6 models are dropped
(not-applicable or failed) and the remaining 2 happen to sit close together,
reporting "Very Strong consistency" is misleading: it says "依据更少、结论更
自信" (less evidence, more confident), which is the opposite of honest.

This module therefore gates the agreement level on three independent factors:

    gated_cv = base_cv × coverage_factor ÷ quality_factor

  * coverage_factor — penalises low solved/applicable coverage:
        sqrt(applicable / solved), clamped to [1.0, 2.0]
  * quality_factor  — each SOLVED model counts 1.0, each APPROXIMATE model 0.5,
        and a DCF whose terminal value dominates EV (>80%) is halved again
        (terminal-value "rescue" is not a trustworthy signal)

On top of the continuous gated_cv, a hard coverage cap forbids strong
conclusions when few models survive:

    solved <= 1 → cap Very Weak | ==2 → Weak | ==3 → Moderate | >=4 → no cap

Models are also split into honest buckets so the denominator is no
longer inflated (applicable = solved + failed must hold exactly):
  * solved          — produced a value (SOLVED or APPROXIMATE)
  * not_applicable  — INSUFFICIENT_DATA (e.g. P/E with ~0 earnings, FCF Yield
                      with negative FCF) — must NOT count as "failed"
  * failed          — attempted but no solution (NO_SOLUTION_IN_RANGE / INFEASIBLE)
  * display_only    — solved but circular/derived (ReverseDCF = current price);
                      rendered for context, excluded from applicable/solved/failed
                      so it never masquerades as a failed model
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Dict, List, Optional, Tuple

from config import get_logger, SolverStatus
from models.base import ValuationResult

log = get_logger("analysis.model_agreement")


# Severity ordering: index 0 = strongest agreement, 4 = weakest.
_AGREEMENT_ORDER: List[str] = ["Very Strong", "Strong", "Moderate", "Weak", "Very Weak"]
# Coverage cap: maximum agreement level allowed for a given number of solved models.
_COVERAGE_CAP: Dict[int, str] = {0: "Very Weak", 1: "Very Weak", 2: "Weak", 3: "Moderate"}
# A value below this many solved models can never be called strongly consistent.
_COVERAGE_STRONG_MIN_SOLVED = 4
# DCF terminal-value dominance thresholds (TV as a fraction of EV).
#   > 0.80 → downweighted (terminal-value "rescue" is not trustworthy)
#   > 1.50 → the explicit-period PV of FCF is deeply negative; the point value
#            is almost entirely a terminal assumption → heavy downweight
#   > 3.00 → terminal value swamps EV many times over (a data/assumption
#            artifact for pre-profit build-outs) → near-artifact weight
_TV_DOMINANCE_THRESHOLD = 0.80
_TV_EXTREME_THRESHOLD = 1.50
_TV_ARTIFACT_THRESHOLD = 3.00
# Classification confidence below this halves a multiple model's weight again.
_LOW_CONFIDENCE_THRESHOLD = 0.55
# Reverse DCF returns the current price (circular) — never a valuation.
_EXCLUDED_FROM_MEDIAN = {"ReverseDCF", "reverse_dcf", "Reverse DCF"}


def _weaker_level(a: str, b: str) -> str:
    """Return the less confident (weaker) of two agreement levels."""
    ia = _AGREEMENT_ORDER.index(a) if a in _AGREEMENT_ORDER else len(_AGREEMENT_ORDER)
    ib = _AGREEMENT_ORDER.index(b) if b in _AGREEMENT_ORDER else len(_AGREEMENT_ORDER)
    return a if ia >= ib else b


def _level_from_cv(cv: float) -> str:
    if cv < 0.10:
        return "Very Strong"
    if cv < 0.20:
        return "Strong"
    if cv < 0.35:
        return "Moderate"
    if cv < 0.55:
        return "Weak"
    return "Very Weak"


@dataclass
class ModelAgreement:
    n_applicable: int
    n_solved: int
    values: Dict[str, Optional[float]]
    median_value: Optional[float] = None
    mean_value: Optional[float] = None
    low_value: Optional[float] = None
    high_value: Optional[float] = None
    std_dev: Optional[float] = None
    cv: Optional[float] = None
    spread_pct: Optional[float] = None
    agreement_level: str = "Unknown"
    notes: List[str] = field(default_factory=list)
    n_approximate: int = 0
    n_high_confidence: int = 0
    median_value_high_conf: Optional[float] = None
    median_value_robust: Optional[float] = None
    outliers_removed: List[str] = field(default_factory=list)

    # ---- Coverage / quality gating (Session #07) -------------------------
    n_total: int = 0
    n_not_applicable: int = 0
    n_failed: int = 0
    n_display_only: int = 0
    not_applicable_models: List[Tuple[str, str]] = field(default_factory=list)
    failed_models: List[Tuple[str, str]] = field(default_factory=list)
    display_only_models: List[str] = field(default_factory=list)
    coverage_ratio: float = 1.0
    quality_factor: float = 1.0
    coverage_factor: float = 1.0
    gated_cv: Optional[float] = None
    agreement_level_raw: str = "Unknown"
    coverage_sufficient: bool = True
    median_value_weighted: Optional[float] = None
    model_weights: Dict[str, float] = field(default_factory=dict)
    downweighted_models: List[str] = field(default_factory=list)
    low_conf_downgraded_models: List[str] = field(default_factory=list)


class ModelAgreementAnalyzer:
    """Summarizes the agreement across multiple valuation models."""

    @staticmethod
    def _iqr_filter(
        solved: Dict[str, float]
    ) -> Tuple[Dict[str, float], List[str]]:
        """Remove outliers using the IQR method.

        Returns (filtered_dict, list_of_removed_model_names).
        Only applies when there are >= 4 models; otherwise returns all.
        Uses a generous 2.5×IQR multiplier to avoid removing legitimate values.
        """
        if len(solved) < 4:
            return solved, []

        vals = sorted(solved.values())
        n = len(vals)
        # Q1 and Q3 using linear interpolation
        q1_idx = (n - 1) * 0.25
        q3_idx = (n - 1) * 0.75
        q1 = vals[int(q1_idx)] + (q1_idx - int(q1_idx)) * (
            vals[min(int(q1_idx) + 1, n - 1)] - vals[int(q1_idx)]
        ) if int(q1_idx) + 1 < n else vals[int(q1_idx)]
        q3 = vals[int(q3_idx)] + (q3_idx - int(q3_idx)) * (
            vals[min(int(q3_idx) + 1, n - 1)] - vals[int(q3_idx)]
        ) if int(q3_idx) + 1 < n else vals[int(q3_idx)]

        iqr = q3 - q1
        lower_bound = q1 - 2.5 * iqr
        upper_bound = q3 + 2.5 * iqr

        removed = []
        filtered = {}
        for name, v in solved.items():
            if v < lower_bound or v > upper_bound:
                removed.append(name)
            else:
                filtered[name] = v

        # Safety: never remove more than 1 value (keep at least n-1)
        if len(removed) > 1:
            # Only remove the single most extreme outlier
            all_items = list(solved.items())
            median_val = median(vals)
            most_extreme = max(all_items, key=lambda kv: abs(kv[1] - median_val))
            removed = [most_extreme[0]]
            filtered = {k: v for k, v in solved.items() if k != most_extreme[0]}

        return filtered, removed

    @staticmethod
    def _weighted_median(values: Dict[str, float], weights: Dict[str, float]) -> Optional[float]:
        """Weighted median over (model → value) with per-model quality weights."""
        items = sorted(values.items(), key=lambda kv: kv[1])
        total = sum(max(0.0, weights.get(k, 1.0)) for k, _ in items)
        if total <= 0:
            return None
        cum = 0.0
        for name, v in items:
            cum += max(0.0, weights.get(name, 1.0))
            if cum >= total / 2.0:
                return v
        return items[-1][1] if items else None

    def analyze(self, results: Dict[str, ValuationResult], current_price: Optional[float] = None) -> ModelAgreement:
        n_total = len(results)
        solved: Dict[str, float] = {}
        values_all: Dict[str, Optional[float]] = {}
        high_conf_vals: List[float] = []
        approx_names: List[str] = []
        not_applicable: List[Tuple[str, str]] = []
        failed: List[Tuple[str, str]] = []
        display_only: List[str] = []
        weights: Dict[str, float] = {}
        downweighted: List[str] = []
        low_conf_downgraded: List[str] = []
        extreme_tv: List[Tuple[str, float]] = []

        for name, r in results.items():
            if r.is_success() and r.value_per_share is not None:
                values_all[name] = r.value_per_share
                if name in _EXCLUDED_FROM_MEDIAN:
                    # ReverseDCF returns the current price (circular) — display
                    # only, never part of the valuation statistics or coverage.
                    # Track it explicitly so the bucket accounting stays honest
                    # (otherwise total = solved + failed + not_applicable breaks).
                    display_only.append(name)
                    continue
                solved[name] = r.value_per_share
                # ---- per-model quality weight -------------------------------
                w = 1.0
                if r.status == SolverStatus.APPROXIMATE:
                    approx_names.append(name)
                    w = 0.5
                    # A multiple whose peer bucket came from a low-confidence
                    # classification (e.g. 50%) must not carry the same weight
                    # as a well-classified one.
                    conf = None
                    try:
                        conf = float((r.breakdown or {}).get("classification_confidence"))
                    except (TypeError, ValueError):
                        conf = None
                    if conf is not None and conf < _LOW_CONFIDENCE_THRESHOLD:
                        w *= 0.5
                        low_conf_downgraded.append(name)
                else:
                    high_conf_vals.append(r.value_per_share)
                tv_pct = (r.breakdown or {}).get("tv_percent_of_ev")
                if name in ("DCF", "dcf") and tv_pct is not None and tv_pct > _TV_DOMINANCE_THRESHOLD:
                    if tv_pct > _TV_ARTIFACT_THRESHOLD:
                        w *= 0.10
                    elif tv_pct > _TV_EXTREME_THRESHOLD:
                        w *= 0.25
                    else:
                        w *= 0.5
                    downweighted.append(name)
                    if tv_pct > _TV_EXTREME_THRESHOLD:
                        extreme_tv.append((name, tv_pct))
                weights[name] = w
            else:
                values_all[name] = None
                reason = "; ".join(r.notes) if r.notes else r.status.value
                if r.status == SolverStatus.INSUFFICIENT_DATA:
                    not_applicable.append((name, reason))
                else:
                    failed.append((name, reason))

        n_not_applicable = len(not_applicable)
        n_display_only = len(display_only)
        # Display-only models (e.g. ReverseDCF, which returns the current price by
        # construction) are neither solved nor failed nor not-applicable — they
        # must be removed from the applicable denominator so that
        # applicable = solved + failed holds exactly.
        n_applicable = max(0, n_total - n_not_applicable - n_display_only)

        # IQR-based outlier removal (only when >= 4 models)
        solved_filtered, removed_outliers = self._iqr_filter(solved)
        if removed_outliers:
            # Recompute high_conf_vals from filtered set
            high_conf_vals = [
                v for name, v in solved_filtered.items()
                if name not in approx_names
            ]

        vals = list(solved_filtered.values())
        n_solved = len(vals) + len(removed_outliers)  # report original count
        n_stats = len(vals)  # actual count used for stats
        n_approximate = len([n for n in approx_names if n in solved_filtered])
        n_high_confidence = n_stats - n_approximate

        ma = ModelAgreement(
            n_applicable=n_applicable,
            n_solved=n_solved,
            values=values_all,
            n_approximate=n_approximate,
            n_high_confidence=n_high_confidence,
            outliers_removed=removed_outliers,
            n_total=n_total,
            n_not_applicable=n_not_applicable,
            n_failed=len(failed),
            n_display_only=n_display_only,
            not_applicable_models=not_applicable,
            failed_models=failed,
            display_only_models=display_only,
            model_weights=dict(weights),
            downweighted_models=downweighted,
            low_conf_downgraded_models=low_conf_downgraded,
        )

        if vals:
            mv = sorted(vals)
            ma.low_value = mv[0]
            ma.high_value = mv[-1]
            ma.mean_value = sum(vals) / len(vals)
            ma.median_value = median(vals)

            # Robust median (same as regular median when outliers already filtered,
            # but stored separately for clarity in reporting)
            ma.median_value_robust = ma.median_value

            # High-confidence median (SOLVED models only, excluding APPROXIMATE)
            if high_conf_vals:
                ma.median_value_high_conf = median(high_conf_vals)

            # Quality-weighted median (SOLVED=1.0, APPROXIMATE=0.5,
            # TV-dominated DCF halved again)
            ma.median_value_weighted = self._weighted_median(
                {k: v for k, v in solved_filtered.items()}, weights
            )

            if len(vals) >= 2:
                ma.std_dev = pstdev(vals)
                if ma.mean_value and ma.mean_value > 0:
                    ma.cv = ma.std_dev / ma.mean_value
            if ma.low_value is not None and ma.high_value is not None and ma.median_value and ma.median_value > 0:
                ma.spread_pct = (ma.high_value - ma.low_value) / ma.median_value

            # Note if outliers were removed
            if removed_outliers:
                outlier_vals = [f"{name} (${values_all[name]:.2f})" for name in removed_outliers]
                ma.notes.append(
                    f"⚠️ IQR outlier filter removed: {', '.join(outlier_vals)} "
                    "(extreme value(s) excluded from median/spread)"
                )

            # When all solved models are APPROXIMATE, flag the median as unreliable
            if n_approximate == n_stats and n_stats > 0:
                ma.notes.append(
                    f"⚠️ All {n_stats} solved models are APPROXIMATE — "
                    "median valuation is directional only (low confidence)"
                )
                if ma.median_value and current_price:
                    ma.notes.append(
                        "Consider scenario analysis (DCF-based) as the primary valuation reference "
                        "instead of the multiples-based median."
                    )
            elif n_approximate > 0 and n_approximate < n_stats:
                ma.notes.append(
                    f"{n_approximate} of {n_stats} models are APPROXIMATE — "
                    "median includes low-confidence estimates"
                )

            # ---- Continuous gated CV + hard coverage cap -------------------
            quality_factor = (
                sum(max(0.0, weights.get(k, 1.0)) for k in solved_filtered) / n_stats
                if n_stats > 0 else 0.0
            )
            coverage_ratio = (n_solved / n_applicable) if n_applicable > 0 else 0.0
            coverage_factor = (
                min(2.0, max(1.0, (n_applicable / n_solved) ** 0.5)) if n_solved > 0 else 2.0
            )
            ma.quality_factor = round(quality_factor, 4)
            ma.coverage_ratio = round(coverage_ratio, 4)
            ma.coverage_factor = round(coverage_factor, 4)
            ma.coverage_sufficient = (
                n_solved >= _COVERAGE_STRONG_MIN_SOLVED and coverage_ratio >= 0.6
            )

            if ma.cv is not None:
                gated_cv = ma.cv * coverage_factor / max(quality_factor, 0.25)
                ma.gated_cv = gated_cv
                raw_level = _level_from_cv(gated_cv)
                ma.agreement_level_raw = raw_level
                cap = _COVERAGE_CAP.get(n_solved)  # None when n_solved >= 4
                level = _weaker_level(raw_level, cap) if cap else raw_level
                if cap and level != raw_level:
                    ma.notes.append(
                        f"一致性降级：仅 {n_solved} 个模型解算（覆盖 {n_solved}/{n_applicable}）→ "
                        f"由「{raw_level}」封顶为「{level}」（低覆盖不得给出强结论）"
                    )
                if not ma.coverage_sufficient:
                    ma.notes.append(
                        f"⚠️ 模型覆盖不足（{n_solved}/{n_applicable} 解算，"
                        f"质量因子 {quality_factor:.2f}）→ 结论只能作为方向性参考"
                    )
                if quality_factor < 0.50:
                    level = _weaker_level(level, "Moderate")
                    ma.notes.append(
                        f"质量因子过低（{quality_factor:.2f}）→ 一致性再下调至「{level}」"
                    )
                ma.agreement_level = level
            else:
                ma.agreement_level = "N/A (single model)"
                ma.agreement_level_raw = "N/A (single model)"
        else:
            ma.agreement_level = "N/A (no solved models)"
            ma.agreement_level_raw = "N/A (no solved models)"
            ma.coverage_ratio = 0.0
            ma.coverage_sufficient = False
            ma.notes.append("No models produced a valid value")

        # ---- Honest bucket reporting -------------------------------------
        if not_applicable:
            items = ", ".join(f"{name}（{reason}）" for name, reason in not_applicable)
            ma.notes.append(
                f"不适用模型 {n_not_applicable} 个（数据不足，不计入分母）: {items}"
            )
        if failed:
            items = ", ".join(f"{name}（{reason}）" for name, reason in failed)
            ma.notes.append(f"失败模型 {len(failed)} 个: {items}")
        if n_display_only:
            ma.notes.append(
                f"仅展示模型 {n_display_only} 个（不计入适用/解算统计）: "
                f"{', '.join(display_only)}"
            )
        if len(failed) > 0 and n_solved < n_applicable:
            ma.notes.append(
                f"{len(failed)} of {n_applicable} applicable models failed"
            )
        if downweighted:
            ma.notes.append(
                f"以下模型因终值占比过高（TV/EV>{_TV_DOMINANCE_THRESHOLD:.0%}）被降权: "
                f"{', '.join(downweighted)}"
            )
        if extreme_tv:
            items = ", ".join(f"{name}（TV/EV={pct:.0%}）" for name, pct in extreme_tv)
            # Highest-priority caveat: place first so it survives the report's
            # note-truncation and is not buried under routine bookkeeping notes.
            ma.notes.insert(0,
                f"⚠️ 极端终值占比重估: {items} — 显式期自由现金流现值深度为负，点估值几乎完全由终值假设决定，"
                "不构成可靠公允价值，已大幅降权"
            )
        if low_conf_downgraded:
            ma.notes.append(
                f"以下倍数模型因分类置信度 <{_LOW_CONFIDENCE_THRESHOLD:.0%} 再次降权（权重 ×0.25）: "
                f"{', '.join(low_conf_downgraded)}"
            )

        if current_price and ma.median_value is not None and ma.median_value > 0:
            pct = (current_price - ma.median_value) / ma.median_value
            ma.notes.append(f"当前价格 ${current_price:.2f} vs 中位估值 ${ma.median_value:.2f} ({pct:+.1%})")

        return ma


__all__ = ["ModelAgreementAnalyzer", "ModelAgreement"]
